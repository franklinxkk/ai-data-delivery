"""Counterexamples for metric promotion, gold expectations and read-only inspection."""
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from check_consistency import db_structure
from promote_draft import classify, to_struct_op
from promote_gold import to_case
from run_eval import cmp_rows, cmp_scalar, unify_expect


def dump(path, value):
    path.write_text(yaml.safe_dump(value, allow_unicode=True), encoding="utf-8")


def cli(script, *args):
    return subprocess.run(
        [sys.executable, "-X", "utf8", str(ROOT / "scripts" / script), *map(str, args)],
        capture_output=True, encoding="utf-8",
        env=dict(os.environ, PYTHONIOENCODING="utf-8"))


class PredicateIntegrity(unittest.TestCase):
    def setUp(self):
        self.cols = {"a": {"cn": "甲", "enum": []},
                     "b": {"cn": "乙", "enum": []},
                     "status": {"cn": "状态", "enum": ["已整改", "待整改"]}}
        self.ctx = {"src2ds": {"t": "D"}, "ds_time": {},
                    "meta_idx": {"t": self.cols}, "syn_map": {}, "promoted": set()}

    def draft(self, predicate=None, formula=None, kind="num"):
        formula = formula or "SELECT COUNT(*) FROM t" + (
            " WHERE " + predicate if predicate is not None else "")
        return classify({"id": "x", "name": "数量", "type": kind,
                         "source_table": "t", "mapped_table": "t",
                         "formula_raw": formula}, self.ctx)[1]

    def assert_blocked(self, draft):
        self.assertTrue(draft["kind"].startswith("⛔"), draft)
        self.assertFalse(draft.get("extra_where"), draft)
        self.assertTrue(draft["issues"] or draft.get("reason"), draft)
        with self.assertRaises(ValueError):
            to_struct_op(draft)

    def test_supported_conjunction_preserves_answer(self):
        draft = self.draft("甲 >= 1 AND b <> 2")
        self.assertTrue(draft["kind"].startswith("✅"), draft)
        op = to_struct_op(draft)
        with sqlite3.connect(":memory:") as conn:
            conn.execute("CREATE TABLE t (a INT, b INT)")
            conn.executemany("INSERT INTO t VALUES (?, ?)", [(1, 1), (1, 2), (0, 1)])
            count = conn.execute("SELECT COUNT(*) FROM t WHERE " + op["extra_where"]).fetchone()[0]
        self.assertEqual(count, 1)

    def test_unsupported_predicate_cannot_be_partially_translated(self):
        for predicate in ("a=1 OR b=2", "a=1 AND b LIKE 'x%'", "a IN (1,2)",
                          "(a=1 AND b=2)", "a=1 AND b BETWEEN 1 AND 3",
                          "a=1 AND", "a=1 rubbish", "NOT a=1", "a=1 /* note */",
                          "a=1 OR 1=1", "a=1 AND b IS NULL", ""):
            with self.subTest(predicate=predicate):
                self.assert_blocked(self.draft(predicate))

    def test_missing_field_or_enum_blocks_whole_filter(self):
        for predicate in ("a=1 AND missing=2", "a=1 AND 状态='待处理'"):
            with self.subTest(predicate=predicate):
                self.assert_blocked(self.draft(predicate))

    def test_quoted_conjunction_and_apostrophe_are_literals(self):
        for value, expected in (("'A AND B'", "A AND B"), ("'O''Brien'", "O'Brien")):
            with self.subTest(value=value):
                draft = self.draft("a = " + value)
                op = to_struct_op(draft)
                with sqlite3.connect(":memory:") as conn:
                    conn.execute("CREATE TABLE t (a TEXT)")
                    conn.executemany("INSERT INTO t VALUES (?)", [(expected,), ("other",)])
                    count = conn.execute("SELECT COUNT(*) FROM t WHERE " + op["extra_where"]).fetchone()[0]
                self.assertEqual(count, 1)

    def test_approximate_mapping_remains_reviewable_without_dropping_conditions(self):
        draft = self.draft("a=1 AND 状态='整改'")
        # Two matching enum values are ambiguous; neither is silently chosen.
        self.assert_blocked(draft)
        draft = self.draft("a=1 AND 状态='待'")
        self.assertTrue(draft["kind"].startswith("🔶"), draft)
        self.assertEqual(to_struct_op(draft)["extra_where"], "a = 1 AND status = '待整改'")

    def test_unconsumed_query_or_aggregate_is_blocked(self):
        for formula in ("SELECT COUNT(*) FROM t GROUP BY a", "SELECT COUNT(*) FROM t LIMIT 0",
                        "SELECT COUNT(*) FROM t WHERE a=1 ORDER BY b",
                        "SELECT COUNT(*) + SUM(a) FROM t", "SELECT SUM(a) FROM t",
                        "SELECT COUNT(*) FROM t WHERE", "SELECT COUNT(*) FROM t JOIN u ON t.a=u.a"):
            with self.subTest(formula=formula):
                self.assert_blocked(self.draft(formula=formula))

    def test_no_filter_and_trailing_semicolon_are_valid(self):
        for formula in ("SELECT COUNT(*) FROM t", "SELECT COUNT(*) FROM t;",
                        " SELECT COUNT(*) FROM t WHERE a=1; "):
            with self.subTest(formula=formula):
                self.assertTrue(self.draft(formula=formula)["kind"].startswith("✅"))

    def test_incomplete_detail_filter_is_not_emitted_as_template(self):
        self.assert_blocked(self.draft(formula="SELECT a FROM t WHERE a=1 AND missing=2", kind="list"))

    def test_query_source_must_match_recorded_source_or_mapped_table(self):
        ctx = {**self.ctx, "src2ds": {"wide_orders": "D"},
               "meta_idx": {"wide_orders": self.cols}}
        raw = {"id": "x", "name": "订单数", "type": "num",
               "source_table": "source_orders", "mapped_table": "wide_orders"}
        for source in ("unrelated_payments", "source_orders", "wide_orders", "SOURCE_ORDERS"):
            with self.subTest(source=source):
                _, draft = classify({**raw, "formula_raw": f"SELECT COUNT(*) FROM {source} WHERE a=1"}, ctx)
                if source == "unrelated_payments":
                    self.assert_blocked(draft)
                    self.assertIn("来源不一致", " ".join(draft["issues"]))
                else:
                    self.assertTrue(draft["kind"].startswith("✅"), draft)
                    self.assertEqual(to_struct_op(draft)["dataset"], "D")

    def test_cli_excludes_blocked_metrics_from_both_operation_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            (p / "meta").mkdir()
            dump(p / "meta" / "t.yaml", {"table": "t", "columns": [
                {"name": name, **fields} for name, fields in self.cols.items()]})
            dump(p / "model.yaml", {"datasets": [{"name": "D", "source": "t", "fields": []}]})
            metrics = []
            for mid, pred in (("ok", "a=1 AND b=2"), ("or", "a=1 OR b=2"),
                              ("missing", "a=1 AND missing=2"), ("enum", "状态='待处理'")):
                metrics.append({"id": mid, "name": mid, "mapped_table": "t", "type": "num",
                                "formula_raw": "SELECT COUNT(*) FROM t WHERE " + pred})
            dump(p / "raw.yaml", {"metrics": metrics})
            result = cli("promote_draft.py", "--raw", p / "raw.yaml", "--from-meta", p / "meta",
                         "--model", p / "model.yaml", "--out", p / "out")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            ops = yaml.safe_load((p / "out" / "ops.yaml").read_text(encoding="utf-8"))["ops"]
            review = yaml.safe_load((p / "out" / "ops_review.yaml").read_text(encoding="utf-8"))["ops"]
            self.assertEqual([op["id"] for op in ops + review], ["ok"])
            checklist = (p / "out" / "提升清单.md").read_text(encoding="utf-8")
            self.assertIn("missing", checklist)
            self.assertIn("待处理", checklist)


class GoldExpectationIntegrity(unittest.TestCase):
    def card(self, expect):
        return {"id": "x", "question": "数量？", "expect": expect}

    def test_missing_value_and_rows_are_rejected_in_both_formats(self):
        for fmt in ("merged", "expect"):
            for expect in ({"type": "scalar"}, {"type": "rows"},
                           {"type": "rows", "rows": None}, {"type": "rows", "rows": "[]"},
                           {"type": "rows", "rows": [0]}, {"type": "scalar", "value": []}):
                with self.subTest(fmt=fmt, expect=expect):
                    with self.assertRaises(ValueError):
                        to_case(self.card(expect), fmt)

    def test_explicit_zero_null_empty_rows_and_refusal_survive(self):
        for value in (0, None):
            with self.subTest(value=value):
                card = self.card({"type": "scalar", "value": value})
                self.assertEqual(to_case(card, "expect")["expect"]["value"], value)
                self.assertEqual(to_case(card, "merged")["gold_rows"], [[value]])
        for rows in ([], [[None]], [[0, "x"]]):
            self.assertEqual(to_case(self.card({"type": "rows", "rows": rows}), "merged")["gold_rows"], rows)
        self.assertTrue(to_case(self.card({"type": "refusal"}), "merged")["expect_reject"])

    def test_valid_gold_promotion_reopens_and_is_consumed_by_evaluator(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            for fmt in ("merged", "expect"):
                gold = p / (fmt + ".yaml")
                for expect in ({"type": "scalar", "value": 0},
                               {"type": "scalar", "value": None},
                               {"type": "rows", "rows": []}):
                    dump(p / "card.yaml", self.card(expect))
                    result = cli("promote_gold.py", "--card", p / "card.yaml", "--gold", gold, "--fmt", fmt)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    cases = yaml.safe_load(gold.read_text(encoding="utf-8"))
                    self.assertEqual(len(cases), 1)  # 同 id 更新，不累加重复用例
                    normalized = unify_expect(cases[0], {})
                    self.assertEqual(normalized["kind"], expect["type"])
                    if expect["type"] == "scalar":
                        self.assertTrue(cmp_scalar(normalized["value"], expect["value"])[0])
                        self.assertFalse(cmp_scalar(normalized["value"], 9)[0])
                    else:
                        self.assertTrue(cmp_rows(normalized["rows"], [])[0])
                        self.assertFalse(cmp_rows(normalized["rows"], [[9]])[0])

    def test_invalid_card_neither_creates_nor_overwrites_gold(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            for expect in ({"type": "scalar"}, {"type": "rows"}):
                dump(p / "card.yaml", self.card(expect))
                for exists in (False, True):
                    gold = p / ("existing.yaml" if exists else "new.yaml")
                    if exists:
                        dump(gold, [{"id": "x", "gold_rows": [[42]]}])
                    before = gold.read_bytes() if exists else None
                    result = cli("promote_gold.py", "--card", p / "card.yaml", "--gold", gold)
                    self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                    self.assertIn("expect", result.stderr)
                    self.assertNotIn("Traceback", result.stderr)
                    if exists:
                        self.assertEqual(gold.read_bytes(), before)
                    else:
                        self.assertFalse(gold.exists())


class ReadonlyInspection(unittest.TestCase):
    def test_profile_output_cannot_overwrite_database_through_path_or_hardlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            db = p / "source.db"
            with sqlite3.connect(db) as conn:
                conn.execute("CREATE TABLE keep_me (value INT)")
                conn.execute("INSERT INTO keep_me VALUES (42)")
            conn.close()
            (p / "subdir").mkdir()
            hardlink = p / "output-hardlink.yaml"
            os.link(db, hardlink)
            original = db.read_bytes()
            for output in (db, p / "subdir" / ".." / "source.db", hardlink):
                with self.subTest(output=output):
                    result = cli("profile_db.py", "--db", db, "--out", output)
                    self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                    self.assertIn("--out 不能指向 --db", result.stderr)
                    self.assertNotIn("画像完成", result.stdout)
                    self.assertEqual(db.read_bytes(), original)
                    self.assertEqual(hardlink.read_bytes(), original)
            with sqlite3.connect(db) as conn:
                self.assertEqual(conn.execute("SELECT value FROM keep_me").fetchall(), [(42,)])
            conn.close()

    def test_missing_db_is_not_created_by_function_or_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            db = p / "missing.db"
            with self.assertRaises((sqlite3.Error, ValueError, FileNotFoundError)):
                db_structure(db)
            self.assertFalse(db.exists())
            dump(p / "empty-model.yaml", {"datasets": []})
            result = cli("check_consistency.py", "--model", p / "empty-model.yaml", "--db", db)
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertNotIn("ERROR 0", result.stdout)
            self.assertNotIn("Traceback", result.stderr)
            self.assertFalse(db.exists())

    def test_valid_inspection_handles_quoted_names_and_preserves_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            db = p / "数据 # 库.db"
            with sqlite3.connect(db) as conn:
                conn.execute('CREATE TABLE "odd\'name" ("a\"\"b" INTEGER)')
                conn.execute('INSERT INTO "odd\'name" VALUES (3)')
            conn.close()
            before = db.read_bytes()
            self.assertEqual(db_structure(db), {"odd'name": {'a"b': "INTEGER"}})
            result = cli("profile_db.py", "--db", db, "--out", p / "profile.yaml")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            profile = yaml.safe_load((p / "profile.yaml").read_text(encoding="utf-8"))
            self.assertEqual(profile["tables"][0]["row_count"], 1)
            self.assertEqual(db.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
