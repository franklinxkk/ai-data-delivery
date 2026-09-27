"""Behavioral regressions for the v0.0.5 contract and its failure boundaries."""
import copy
import datetime as dt
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from _contract import evidence, load, snapshot, write
from _sql import compile_single
from check_constraints import check_rule, check_all
from check_join_graph import analyze
from guide_model import new_session, proposal, apply_proposal, blockers
from ingest_ddl import parse_sql
from release_gate import assess_eval
from run_eval import apply_declared, judge_live
from visualize_model import build_data, PAGE


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)
        self.model = load(ROOT / "examples/onboarding/partial.yaml")
        self.model["datasets"][0].update(grain="one order", temporal={"kind": "current"})
        self.model["metrics"][0].update(expr="SUM(amount)", caliber={"note": "paid orders"})
        self.db = self.path / "test.db"
        self.conn = sqlite3.connect(self.db)
        self.conn.executescript((ROOT / "examples/onboarding/source.sql").read_text())
        self.conn.executemany("INSERT INTO orders VALUES (?,?,?,?,?,?,?)", [
            ("a", 1, 10, 100, "paid", "2026-01-01", "2026-01-02"),
            ("a", 2, 20, 200, "paid", "2026-01-01", "2026-01-03")])
        self.conn.executemany("INSERT INTO customers VALUES (?,?,?)", [("a", 10, "x"), ("a", 20, "y")])
        self.conn.executemany("INSERT INTO items VALUES (?,?,?)", [(1, "a", 1), (2, "a", 1), (3, "a", 2)])
        self.conn.commit()
        self.model_path = self.path / "semantic.yaml"
        self.cases_path = self.path / "cases.json"
        write(self.model_path, self.model)
        self.cases = [{"id": "a", "question": "amount", "expect": {"type": "scalar", "value": 300}}]
        write(self.cases_path, self.cases)

    def tearDown(self):
        self.conn.close()
        self.temp.cleanup()

    def cli(self, name, *args):
        return subprocess.run([sys.executable, str(ROOT / "scripts" / name), *map(str, args)],
                              encoding="utf-8", capture_output=True,
                              env=dict(os.environ, PYTHONIOENCODING="utf-8"))

    def compile(self, **changes):
        metric = {**self.model["metrics"][0], **changes}
        return compile_single(metric, self.model["datasets"][0], {"orders", "customers"})

    def test_filters_and_extra_where_both_retained(self):
        sql, error = self.compile(extra_where="order_id=1")
        self.assertIsNone(error)
        self.assertEqual(self.conn.execute(sql).fetchone()[0], 100)

    def test_foreign_dataset_prefix_is_rejected(self):
        self.assertIsNone(self.compile(expr="SUM(customers.amount)")[0])

    def test_quoted_foreign_prefix_is_rejected(self):
        self.assertIsNone(self.compile(expr='SUM("customers".amount)')[0])

    def test_dotted_literal_not_changed(self):
        sql, error = self.compile(extra_where="status <> 'customers.paid'")
        self.assertIsNone(error)
        self.assertIn("'customers.paid'", sql)

    def test_empty_filter_is_not_silently_discarded(self):
        self.assertIsNone(self.compile(filters=[{"field": "status", "values": []}])[0])

    def test_join_request_is_not_silently_ignored(self):
        self.assertIsNone(self.compile(join_path=["order_customer"])[0])

    def test_subquery_is_outside_compiler(self):
        self.assertIsNone(self.compile(expr="(SELECT SUM(amount) FROM orders)")[0])

    def test_nonaggregate_cannot_return_arbitrary_first_row(self):
        self.assertIsNone(self.compile(expr="amount")[0])

    def test_multi_statement_is_rejected(self):
        self.assertIsNone(self.compile(expr="SUM(amount); DELETE FROM orders")[0])

    def test_group_by_injected_in_where_is_rejected(self):
        self.assertIsNone(self.compile(extra_where="1=1 GROUP BY customer_ref")[0])

    def test_composite_different_name_many_to_one_is_safe(self):
        report = analyze(self.model, self.conn)
        self.assertEqual(report["queries"][0]["status"], "pass")
        self.assertEqual(report["status"], "pass")

    def test_one_to_many_query_is_fanout(self):
        self.model["query_plans"][0]["relationships"] = ["order_items"]
        report = analyze(self.model, self.conn)
        self.assertEqual(report["queries"][0]["status"], "fail")
        self.assertEqual(self.conn.execute("SELECT SUM(amount) FROM orders JOIN items ON orders.tenant_id=items.tenant_id AND orders.order_id=items.order_ref").fetchone()[0], 400)

    def test_reverse_many_to_one_is_fanout(self):
        self.model["metrics"][0]["dataset"] = "customers"
        self.assertEqual(analyze(self.model, self.conn)["queries"][0]["status"], "fail")

    def test_declared_unique_is_not_data_proof(self):
        self.conn.executescript("ALTER TABLE customers RENAME TO old_customers; CREATE TABLE customers AS SELECT * FROM old_customers; INSERT INTO customers SELECT * FROM old_customers LIMIT 1;")
        report = analyze(self.model, self.conn)
        self.assertEqual(report["relationships"][0]["status"], "fail")
        self.assertNotEqual(report["queries"][0]["status"], "pass")

    def test_no_database_means_unknown_query(self):
        self.assertEqual(analyze(self.model)["queries"][0]["status"], "unknown")

    def test_unknown_relationship_key_is_error(self):
        self.model["relationships"][0]["to_columns"] = ["missing", "customer_id"]
        self.assertEqual(analyze(self.model, self.conn)["relationships"][0]["status"], "error")

    def test_sum_distinct_does_not_fix_fanout(self):
        self.conn.execute("UPDATE orders SET amount=100")
        self.assertEqual(self.conn.execute("SELECT SUM(amount),SUM(DISTINCT amount) FROM orders").fetchone(), (200, 100))

    def test_all_six_constraint_types(self):
        self.model["constraints"].append({"id": "amount_present", "kind": "not_null", "dataset": "orders", "field": "amount", "null_policy": "forbid"})
        self.assertEqual(check_all(self.model, self.conn)["status"], "pass")

    def test_null_unknown_does_not_pass(self):
        self.conn.execute("UPDATE orders SET delivered_at=NULL WHERE order_id=1")
        self.assertEqual(check_rule(self.conn, self.model, self.model["constraints"][4])["status"], "unknown")

    def test_null_forbid_is_failure(self):
        self.conn.execute("UPDATE orders SET amount=NULL WHERE order_id=1")
        self.assertEqual(check_rule(self.conn, self.model, self.model["constraints"][2])["status"], "fail")

    def test_null_ignore_is_explicit(self):
        self.conn.execute("UPDATE orders SET delivered_at=NULL WHERE order_id=1")
        rule = {**self.model["constraints"][4], "null_policy": "ignore"}
        self.assertEqual(check_rule(self.conn, self.model, rule)["status"], "pass")

    def test_invalid_date_is_failure(self):
        self.conn.execute("UPDATE orders SET delivered_at='not-a-date' WHERE order_id=1")
        self.assertEqual(check_rule(self.conn, self.model, self.model["constraints"][4])["status"], "fail")

    def test_numeric_range_rejects_text(self):
        self.conn.execute("UPDATE orders SET amount='unknown' WHERE order_id=1")
        self.assertEqual(check_rule(self.conn, self.model, self.model["constraints"][2])["status"], "fail")

    def test_referential_orphan_fails(self):
        self.conn.execute("UPDATE orders SET customer_ref=99 WHERE order_id=1")
        self.assertEqual(check_rule(self.conn, self.model, self.model["constraints"][5])["violation_count"], 1)

    def test_empty_dataset_not_verified(self):
        self.conn.execute("DELETE FROM orders")
        self.assertEqual(check_rule(self.conn, self.model, self.model["constraints"][0])["status"], "unknown")

    def test_missing_table_is_execution_error(self):
        self.model["datasets"][0]["source"] = "missing"
        self.assertEqual(check_rule(self.conn, self.model, self.model["constraints"][0])["status"], "error")

    def test_no_rules_not_a_pass(self):
        self.assertEqual(check_all({"constraints": []}, self.conn)["status"], "not_ready")

    def test_missing_db_never_created(self):
        missing = self.path / "missing.db"
        with self.assertRaises(sqlite3.OperationalError):
            snapshot(missing)
        self.assertFalse(missing.exists())

    def test_snapshot_changes_when_data_changes(self):
        first, first_hash = snapshot(self.db)
        first.close()
        self.conn.execute("UPDATE orders SET amount=1 WHERE order_id=1")
        self.conn.commit()
        second, second_hash = snapshot(self.db)
        second.close()
        self.assertNotEqual(first_hash, second_hash)

    def session(self):
        return new_session(load(ROOT / "examples/onboarding/partial.yaml"), load(ROOT / "examples/onboarding/scope.yaml"), "source-hash")

    def answer(self, session):
        gap = session["gaps"][0]
        return {"session_revision": session["revision"], "decisions": [{"gap_id": gap["id"], "state": "confirmed", "value": "one order", "actor": "business approver", "role": gap["owner_role"], "basis": "signed definition"}]}

    def test_proposal_does_not_mutate_session(self):
        session = self.session()
        patch = proposal(session, self.answer(session))
        self.assertEqual(session["revision"], 0)
        self.assertNotIn("grain", session["model"]["datasets"][0])
        self.assertEqual(patch["changes"][0]["after"], "one order")

    def test_apply_resume_idempotent(self):
        session = self.session()
        patch = proposal(session, self.answer(session))
        updated = apply_proposal(session, patch)
        write(self.path / "session.json", updated)
        resumed = load(self.path / "session.json")
        self.assertEqual(apply_proposal(resumed, patch), resumed)
        self.assertEqual(resumed["revision"], 1)
        self.assertEqual(len(resumed["decisions"]), 1)

    def test_stale_patch_is_rejected(self):
        session = self.session()
        patch = proposal(session, self.answer(session))
        session["scope"]["question"] += " changed"
        with self.assertRaises(ValueError):
            apply_proposal(session, patch)

    def test_tampered_patch_is_rejected(self):
        session = self.session()
        patch = proposal(session, self.answer(session))
        patch["changes"][0]["after"] = "tampered"
        with self.assertRaises(ValueError):
            apply_proposal(session, patch)

    def test_fde_cannot_fill_business_owner_slot(self):
        session = self.session()
        answer = self.answer(session)
        answer["decisions"][0]["role"] = "fde"
        with self.assertRaises(ValueError):
            proposal(session, answer)

    def test_confirmed_answer_requires_supersession(self):
        session = self.session()
        session = apply_proposal(session, proposal(session, self.answer(session)))
        with self.assertRaises(ValueError):
            proposal(session, self.answer(session))

    def test_historical_request_is_blocked_by_current_data(self):
        session = self.session()
        session["scope"]["time_requirement"] = "historical_as_of"
        self.assertTrue(any(b["id"].startswith("history:") for b in blockers(session)))

    def report(self):
        return {"summary": {"passed": 1, "total": 1, "declared": 0},
                "cases": [{"id": "a", "pass": True}],
                "evidence": evidence(self.model_path, self.cases_path, mode="offline")}

    def test_bound_report_passes(self):
        self.assertEqual(assess_eval(self.report(), self.model_path, self.cases_path)["status"], "pass")

    def test_stale_model_report_fails(self):
        report = self.report()
        self.model["version"] = "next"
        write(self.model_path, self.model)
        self.assertEqual(assess_eval(report, self.model_path, self.cases_path)["status"], "fail")

    def test_old_report_without_binding_fails(self):
        report = self.report()
        report.pop("evidence")
        self.assertEqual(assess_eval(report, self.model_path, self.cases_path)["status"], "fail")

    def test_expired_report_fails(self):
        report = self.report()
        report["evidence"]["created_at"] = "2020-01-01T00:00:00+00:00"
        self.assertEqual(assess_eval(report, self.model_path, self.cases_path)["status"], "fail")

    def test_missing_record_fails_even_if_summary_claims_success(self):
        report = self.report()
        report["cases"] = []
        self.assertEqual(assess_eval(report, self.model_path, self.cases_path)["status"], "fail")

    def test_unknown_is_not_pass(self):
        report = self.report()
        report["cases"][0]["pass"] = None
        self.assertEqual(assess_eval(report, self.model_path, self.cases_path)["status"], "fail")

    def test_sql_without_gold_result_is_unknown(self):
        self.assertIsNone(judge_live({"value": 10}, {"kind": "sql_only"})[0])

    def test_bare_declaration_is_not_waiver(self):
        self.assertFalse(apply_declared({"declared_conflict": True}, False, "wrong")[0])

    def test_expired_waiver_is_not_waiver(self):
        waiver = {"owner": "owner", "ref": "minutes", "note": "known", "case_ids": ["a"], "expires_on": "2020-01-01"}
        self.assertFalse(apply_declared({"id": "a", "declared_conflict": waiver}, False, "wrong")[0])

    def test_full_waiver_is_conditional(self):
        waiver = {"owner": "owner", "ref": "minutes", "note": "known", "case_ids": ["a"], "expires_on": "2099-01-01"}
        self.assertTrue(apply_declared({"id": "a", "declared_conflict": waiver}, False, "wrong")[0])

    def test_missing_report_blocks_default_gate(self):
        result = self.cli("release_gate.py", "--model", self.model_path, "--cases", self.cases_path, "--log", self.path / "log.yaml")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("not_ready", result.stdout)

    def test_mock_report_cannot_pass_production_gate(self):
        report = self.report()
        conn, fingerprint = snapshot(self.db)
        conn.close()
        report["evidence"].update(mode="mock", data_snapshot_sha256=fingerprint)
        write(self.path / "eval.json", report)
        result = self.cli("release_gate.py", "--model", self.model_path, "--cases", self.cases_path,
                          "--db", self.db, "--eval-report", self.path / "eval.json", "--profile", "production",
                          "--log", self.path / "log.yaml", "--out", self.path / "gate.json")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        gate = load(self.path / "gate.json")
        self.assertEqual(next(g for g in gate["gates"] if g["gate"] == "live_evidence")["status"], "unknown")

    def test_changed_snapshot_cannot_reuse_report(self):
        report = self.report()
        conn, fingerprint = snapshot(self.db)
        conn.close()
        report["evidence"].update(data_snapshot_sha256=fingerprint)
        write(self.path / "eval.json", report)
        self.conn.execute("UPDATE orders SET amount=999 WHERE order_id=1")
        self.conn.commit()
        result = self.cli("release_gate.py", "--model", self.model_path, "--cases", self.cases_path,
                          "--db", self.db, "--eval-report", self.path / "eval.json",
                          "--log", self.path / "log.yaml", "--out", self.path / "gate.json")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        gate = load(self.path / "gate.json")
        self.assertEqual(next(g for g in gate["gates"] if g["gate"] == "data_binding")["status"], "unknown")

    def test_static_profile_is_labelled_static(self):
        result = self.cli("release_gate.py", "--model", self.model_path, "--cases", self.cases_path, "--profile", "static", "--log", self.path / "log.yaml")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("static_ready", result.stdout)

    def test_eval_unknown_suite_nonzero(self):
        write(self.cases_path, [{"id": "a", "question": "unknown"}])
        write(self.path / "actual.json", [{"id": "a", "value": 1}])
        result = self.cli("run_eval.py", "--gold", self.cases_path, "--actual", self.path / "actual.json")
        self.assertEqual(result.returncode, 1)

    def test_reconcile_sql_error_nonzero(self):
        self.model["metrics"][0]["expr"] = "SUM(missing_column)"
        write(self.model_path, self.model)
        result = self.cli("reconcile_paths.py", "--model", self.model_path, "--db", self.db)
        self.assertEqual(result.returncode, 1, result.stderr)

    def test_patch_zero_is_valid_with_independent_expectation(self):
        result = self.cli("patch_model.py", "-f", self.model_path, "struct", "gmv",
                          "--expr", "COUNT(*)", "--extra-where", "order_id=999",
                          "--db", self.db, "--expect", "0")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(load(self.model_path)["metrics"][0]["extra_where"], "order_id=999")

    def test_patch_failed_verification_preserves_file(self):
        original = self.model_path.read_bytes()
        result = self.cli("patch_model.py", "-f", self.model_path, "struct", "gmv",
                          "--expr", "SUM(customers.amount)", "--db", self.db)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.model_path.read_bytes(), original)

    def test_patch_without_db_invalidates_published_status(self):
        self.model["metrics"][0]["status"] = "已发布"
        write(self.model_path, self.model)
        result = self.cli("patch_model.py", "-f", self.model_path, "struct", "gmv", "--expr", "COUNT(*)")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(load(self.model_path)["metrics"][0]["status"], "草案")

    def test_ddl_inline_composite_key_and_decimal(self):
        tables = parse_sql('CREATE TABLE "t" (a INTEGER, b TEXT DEFAULT \'x,y\', price DECIMAL(10,2), PRIMARY KEY (a,b));', "ddl")
        self.assertEqual([c["name"] for c in tables[0]["columns"]], ["a", "b", "price"])
        self.assertEqual(tables[0]["pk_guess"], ["a", "b"])
        self.assertTrue(tables[0]["columns"][1]["pk"])

    def test_visualizer_escapes_script_content(self):
        self.model["name"] = '</script><script>alert("x")</script>'
        write(self.model_path, self.model)
        output = self.path / "model.html"
        result = self.cli("visualize_model.py", "--model", self.model_path, "--out", output)
        self.assertEqual(result.returncode, 0)
        self.assertNotIn(self.model["name"], output.read_text(encoding="utf-8"))
        self.assertIn("\\u003c/script", output.read_text(encoding="utf-8"))

    def test_visualizer_marks_stale_report(self):
        report = self.report()
        report["evidence"]["model_sha256"] = "stale"
        write(self.path / "report.json", report)
        self.assertTrue(build_data(self.model_path, [self.path / "report.json"])["reports"][0]["binding_errors"])


if __name__ == "__main__":
    unittest.main()
