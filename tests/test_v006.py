"""Behavioral regressions for v0.0.6: ontology declaration layer, projection
fidelity, zero-denominator policy, forbidden-term assertions, business-first gaps."""
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
from _contract import write
from _sql import compile_single
from check_model import (Reporter, check_datasets, check_relationships, check_concepts,
                         check_metrics, check_ontology)
from guide_model import new_session, proposal, apply_proposal
from run_eval import judge_live, judge_file
from visualize_model import build_data


def base_model():
    """Lint-clean contract; tests add exactly one defect at a time."""
    return {
        "version": "t0",
        "datasets": [{"name": "orders", "source": "orders", "grain": "一行一单",
                      "primary_key": "id", "ai": {"instructions": "只答订单统计"},
                      "fields": [{"name": "id", "role": "pk"},
                                 {"name": "cust_id", "role": "fk"},
                                 {"name": "dt", "role": "time"}]}],
        "relationships": [], "concepts": [], "metrics": [],
    }


def lint(model):
    rep = Reporter()
    ds_index = {d.get("name"): d for d in model.get("datasets", [])}
    check_datasets(model, rep)
    check_relationships(model, rep, set(ds_index))
    check_concepts(model, rep, ds_index)
    check_metrics(model, rep, ds_index)
    check_ontology(model, rep)
    return rep.errors, rep.warnings


def codes(lines):
    return {line.split("]")[0].split()[-1].strip("[") for line in lines}


def with_ontology(model):
    model["ontology"] = {
        "entities": [{"name": "订单"}, {"name": "客户"}],
        "relations": [{"from": "客户", "to": "订单", "predicate": "下", "mapping": "equi_key"}],
    }
    model["datasets"][0]["ontology_ref"] = "订单"
    model["relationships"] = [{"from": "orders", "to": "orders", "join_key": "cust_id",
                               "cardinality": "N:1", "traversable": True,
                               "ontology_ref": "客户->订单:下"}]
    return model


class OntologyLintTests(unittest.TestCase):
    def test_no_ontology_section_is_not_penalized(self):
        errors, warnings = lint(base_model())
        self.assertFalse(errors)
        self.assertFalse(codes(warnings) & {"W07", "W08"})

    def test_valid_ontology_and_projection_passes(self):
        errors, warnings = lint(with_ontology(base_model()))
        self.assertFalse(errors)
        self.assertNotIn("W07", codes(warnings) - {"W07"})  # 客户未投影且未说明 → 允许 W07 存在但不报错
        self.assertFalse(codes(errors) & {"E12", "E13", "E14", "E15"})

    def test_is_a_unknown_target(self):
        m = with_ontology(base_model())
        m["ontology"]["entities"][0]["is_a"] = "幽灵"
        errors, _ = lint(m)
        self.assertIn("E12", codes(errors))

    def test_is_a_cycle(self):
        m = with_ontology(base_model())
        m["ontology"]["entities"][0]["is_a"] = "客户"
        m["ontology"]["entities"][1]["is_a"] = "订单"
        errors, _ = lint(m)
        self.assertIn("E12", codes(errors))

    def test_relation_bad_mapping(self):
        m = with_ontology(base_model())
        m["ontology"]["relations"][0]["mapping"] = "maybe"
        errors, _ = lint(m)
        self.assertIn("E13", codes(errors))

    def test_weak_relation_requires_note(self):
        m = with_ontology(base_model())
        m["ontology"]["relations"].append(
            {"from": "客户", "to": "订单", "predicate": "关注", "mapping": "weak"})
        errors, _ = lint(m)
        self.assertIn("E13", codes(errors))

    def test_relation_endpoint_must_be_entity(self):
        m = with_ontology(base_model())
        m["ontology"]["relations"].append(
            {"from": "客户", "to": "不存在", "predicate": "x", "mapping": "weak", "note": "n"})
        errors, _ = lint(m)
        self.assertIn("E13", codes(errors))

    def test_dataset_ontology_ref_unknown(self):
        m = with_ontology(base_model())
        m["datasets"][0]["ontology_ref"] = "幽灵"
        errors, _ = lint(m)
        self.assertIn("E14", codes(errors))

    def test_ontology_ref_without_ontology_section(self):
        m = base_model()
        m["datasets"][0]["ontology_ref"] = "订单"
        errors, _ = lint(m)
        self.assertIn("E14", codes(errors))

    def test_weak_relation_must_not_be_projected(self):
        m = with_ontology(base_model())
        m["ontology"]["relations"].append(
            {"id": "r-weak", "from": "客户", "to": "订单", "predicate": "关注",
             "mapping": "weak", "note": "人工台账"})
        m["relationships"][0]["ontology_ref"] = "r-weak"
        errors, _ = lint(m)
        self.assertIn("E15", codes(errors))

    def test_unprojected_entity_needs_reason(self):
        m = with_ontology(base_model())
        _, warnings = lint(m)
        self.assertIn("W07", codes(warnings))  # 客户未投影未说明
        m["ontology"]["entities"][1]["unprojected_reason"] = "维度建设中"
        _, warnings = lint(m)
        self.assertNotIn("W07", codes(warnings))

    def test_equi_relation_not_projected_warns(self):
        m = with_ontology(base_model())
        m["relationships"] = []  # 声明了 equi_key 关系却不落地
        _, warnings = lint(m)
        self.assertIn("W08", codes(warnings))


class ConceptGlossaryTests(unittest.TestCase):
    def concept(self, **kw):
        base = {"term": "重点客户", "expand": {"dataset": "orders", "field": "cust_id", "values": [1]}}
        base.update(kw)
        return base

    def test_forbidden_conflicts_with_own_synonym(self):
        m = base_model()
        m["concepts"] = [self.concept(synonyms=["大户"], forbidden=["大户"])]
        errors, _ = lint(m)
        self.assertIn("E16", codes(errors))

    def test_synonym_conflict_within_same_domain(self):
        m = base_model()
        m["concepts"] = [self.concept(term="A", synonyms=["大户"], domain="金融"),
                         self.concept(term="B", synonyms=["大户"], domain="金融")]
        _, warnings = lint(m)
        self.assertIn("W09", codes(warnings))

    def test_synonym_conflict_across_domains_is_allowed(self):
        m = base_model()
        m["concepts"] = [self.concept(term="A", synonyms=["大户"], domain="金融"),
                         self.concept(term="B", synonyms=["大户"], domain="政务")]
        _, warnings = lint(m)
        self.assertNotIn("W09", codes(warnings))

    def test_expired_concept_warns(self):
        m = base_model()
        m["concepts"] = [self.concept(valid_to="2020-01-01")]
        _, warnings = lint(m)
        self.assertIn("W10", codes(warnings))


class ZeroDenominatorTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.execute("CREATE TABLE t (a REAL, b REAL)")
        self.conn.executemany("INSERT INTO t VALUES (?,?)", [(10, 5), (20, -5)])  # SUM(b)=0
        self.ds = {"name": "t", "source": "t",
                   "fields": [{"name": "a", "role": "measure"}, {"name": "b", "role": "measure"}]}

    def tearDown(self):
        self.conn.close()

    def metric(self, policy):
        mt = {"id": "r", "type": "ratio", "dataset": "t", "structured": True,
              "numerator": {"expr": "SUM(a)"}, "denominator": {"expr": "SUM(b)"}}
        if policy is not ...:
            mt["on_zero_denominator"] = policy
        return mt

    def value(self, mt):
        sql, error = compile_single(mt, self.ds)
        self.assertIsNone(error)
        return self.conn.execute(sql).fetchone()[0]

    def test_null_policy_yields_null(self):
        self.assertIsNone(self.value(self.metric("null")))

    def test_default_policy_is_null(self):
        self.assertIsNone(self.value(self.metric(...)))

    def test_zero_policy_yields_zero(self):
        self.assertEqual(self.value(self.metric("zero")), 0)

    def test_error_policy_yields_sentinel_that_cannot_pass_numeric_compare(self):
        self.assertEqual(self.value(self.metric("error")), "ZERO_DENOMINATOR")

    def test_invalid_policy_rejected_by_compiler(self):
        sql, error = compile_single(self.metric("ignore"), self.ds)
        self.assertIsNone(sql)
        self.assertIn("on_zero_denominator", error)

    def test_lint_invalid_policy(self):
        m = base_model()
        m["metrics"] = [dict(self.metric("ignore"), time_field="dt", status="已发布")]
        errors, _ = lint(m)
        self.assertIn("E17", codes(errors))

    def test_lint_missing_policy_warns(self):
        m = base_model()
        m["metrics"] = [dict(self.metric(...), time_field="dt", status="已发布")]
        _, warnings = lint(m)
        self.assertIn("W11", codes(warnings))


class BusinessFirstGapTests(unittest.TestCase):
    def scope(self):
        return {"id": "s1", "question": "订单量", "datasets": ["orders"]}

    def test_ontology_ref_gap_comes_before_physical_gaps(self):
        m = with_ontology(base_model())
        del m["datasets"][0]["ontology_ref"]
        del m["datasets"][0]["grain"]
        session = new_session(m, self.scope(), "h")
        props = [g["property"] for g in session["gaps"]]
        self.assertEqual(props[0], "ontology_ref")
        self.assertLess(props.index("ontology_ref"), props.index("grain"))

    def test_no_ontology_section_no_ontology_gap(self):
        session = new_session(base_model(), self.scope(), "h")
        self.assertNotIn("ontology_ref", [g["property"] for g in session["gaps"]])

    def test_entity_attributes_gap_is_business_owner(self):
        m = with_ontology(base_model())  # 订单实体无 attributes
        session = new_session(m, self.scope(), "h")
        gap = next(g for g in session["gaps"] if g["object"].startswith("ontology_entity:"))
        self.assertEqual(gap["property"], "attributes")
        self.assertEqual(gap["owner_role"], "business_owner")
        self.assertEqual(session["gaps"][0]["property"], "attributes")  # 业务问题先于物理问题

    def test_confirm_ontology_ref_via_session(self):
        m = with_ontology(base_model())
        del m["datasets"][0]["ontology_ref"]
        session = new_session(m, self.scope(), "h")
        gap = next(g for g in session["gaps"] if g["property"] == "ontology_ref")
        answers = {"session_revision": session["revision"], "decisions": [
            {"gap_id": gap["id"], "state": "confirmed", "actor": "fde-1",
             "basis": "盘点确认", "role": "fde", "value": "订单"}]}
        patch = proposal(session, answers)
        updated = apply_proposal(session, patch)
        ds = updated["model"]["datasets"][0]
        self.assertEqual(ds["ontology_ref"], "订单")
        # 再确认实体属性，写回 ontology 段（attributes 缺口在 init 时生成，用包含该缺口的新会话）
        session2 = new_session(updated["model"], self.scope(), "h")
        gap2 = next(g for g in session2["gaps"] if g["property"] == "attributes")
        answers2 = {"session_revision": session2["revision"], "decisions": [
            {"gap_id": gap2["id"], "state": "confirmed", "actor": "biz-1", "basis": "业务访谈",
             "role": "business_owner", "value": [{"name": "订单来源", "value_type": "enum"}]}]}
        patch2 = proposal(session2, answers2)
        updated2 = apply_proposal(session2, patch2)
        entity = next(e for e in updated2["model"]["ontology"]["entities"] if e["name"] == "订单")
        self.assertEqual(entity["attributes"], [{"name": "订单来源", "value_type": "enum"}])


class ForbiddenTermEvalTests(unittest.TestCase):
    def test_live_answer_with_forbidden_word_fails(self):
        case = {"id": "c1", "expect": {"type": "scalar", "value": 5},
                "answer_must_not_contain": ["身份证号"]}
        ok, why = judge_live({"value": 5, "sql": "SELECT COUNT(*) FROM t -- 身份证号"}, case and
                             {"kind": "scalar", "value": 5, "rows": None, "tolerance": 1e-6}, case)
        self.assertFalse(ok)
        self.assertIn("禁用词", why)

    def test_live_answer_without_forbidden_word_passes(self):
        case = {"id": "c1", "expect": {"type": "scalar", "value": 5},
                "answer_must_not_contain": ["身份证号"]}
        ok, _ = judge_live({"value": 5, "sql": "SELECT COUNT(*) FROM t"},
                           {"kind": "scalar", "value": 5, "rows": None, "tolerance": 1e-6}, case)
        self.assertTrue(ok)

    def test_offline_forbidden_word_fails(self):
        case = {"id": "c1", "expect": {"type": "scalar", "value": 5},
                "answer_must_not_contain": ["13"]}
        ok, why = judge_file(case, {"id": "c1", "value": 5, "rows": [[5, "x13"]]})
        self.assertFalse(ok)
        self.assertIn("禁用词", why)


class VisualizeOntologyTests(unittest.TestCase):
    def test_ontology_view_with_projection_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "semantic.yaml"
            write(path, with_ontology(base_model()))
            data = build_data(path)
        ont = data["ontology"]
        order = next(e for e in ont["entities"] if e["name"] == "订单")
        cust = next(e for e in ont["entities"] if e["name"] == "客户")
        self.assertEqual(order["projected_by"], ["orders"])
        self.assertEqual(cust["projected_by"], [])
        self.assertTrue(ont["relations"][0]["projected"])
        self.assertEqual(ont["relations"][0]["id"], "客户->订单:下")

    def test_no_ontology_view_without_section(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "semantic.yaml"
            write(path, base_model())
            self.assertIsNone(build_data(path)["ontology"])


class GateIntegrationTests(unittest.TestCase):
    def cli(self, name, *args):
        return subprocess.run([sys.executable, str(ROOT / "scripts" / name), *map(str, args)],
                              encoding="utf-8", capture_output=True,
                              env=dict(os.environ, PYTHONIOENCODING="utf-8"))

    def test_check_model_cli_blocks_projected_weak_relation(self):
        with tempfile.TemporaryDirectory() as tmp:
            m = with_ontology(base_model())
            m["ontology"]["relations"].append(
                {"id": "r-weak", "from": "客户", "to": "订单", "predicate": "关注",
                 "mapping": "weak", "note": "人工台账"})
            m["relationships"][0]["ontology_ref"] = "r-weak"
            path = Path(tmp) / "semantic.yaml"
            write(path, m)
            result = self.cli("check_model.py", "-f", path)
            self.assertEqual(result.returncode, 1)
            self.assertIn("E15", result.stdout)

    def test_check_model_cli_passes_clean_ontology(self):
        with tempfile.TemporaryDirectory() as tmp:
            m = with_ontology(base_model())
            m["ontology"]["entities"][1]["unprojected_reason"] = "建设中"
            path = Path(tmp) / "semantic.yaml"
            write(path, m)
            result = self.cli("check_model.py", "-f", path)
            self.assertEqual(result.returncode, 0, result.stdout)
            self.assertIn("本体实体 2", result.stdout)


if __name__ == "__main__":
    unittest.main()
