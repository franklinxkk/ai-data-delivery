"""Behavioral regressions for v0.0.7: stable uid, evidence grading, starter packs,
gap suggestions/clearance, drift classification, quality history, visualization hooks."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from _contract import evidence_source, ont_entity_id, write
from check_model import (Reporter, check_datasets, check_relationships, check_concepts,
                         check_metrics, check_ontology, drift_report, append_history)
from guide_model import merge_packs, new_session, gap_view, clearance, show
from visualize_model import build_data, PAGE


def base_model():
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


class TestStableUid(unittest.TestCase):
    def test_entity_without_uid_warns_w12(self):
        m = base_model()
        m["ontology"] = {"entities": [{"name": "订单"}], "relations": []}
        errors, warnings = lint(m)
        self.assertIn("W12", codes(warnings))

    def test_entity_with_uid_no_w12(self):
        m = base_model()
        m["ontology"] = {"entities": [{"name": "订单", "uid": "ent_order"}], "relations": []}
        errors, warnings = lint(m)
        w12 = [w for w in warnings if "W12" in w]
        self.assertEqual(w12, [])

    def test_duplicate_uid_is_e11(self):
        m = base_model()
        m["ontology"] = {"entities": [{"name": "订单", "uid": "ent_x"},
                                      {"name": "客户", "uid": "ent_x"}], "relations": []}
        errors, _ = lint(m)
        self.assertIn("E11", codes(errors))

    def test_invalid_evidence_source_warns(self):
        m = base_model()
        m["ontology"] = {"entities": [{"name": "订单", "uid": "ent_order",
                                       "evidence": {"source": "guess"}}], "relations": []}
        _, warnings = lint(m)
        self.assertTrue(any("evidence.source" in w for w in warnings))

    def test_ont_entity_id_prefers_uid(self):
        self.assertEqual(ont_entity_id({"name": "订单", "uid": "ent_order"}), "ent_order")
        self.assertEqual(ont_entity_id({"name": "订单"}), "订单")
        self.assertEqual(evidence_source({"evidence": {"source": "user_provided"}}), "user_provided")
        self.assertIsNone(evidence_source({"evidence": {"source": "bogus"}}))


class TestDrift(unittest.TestCase):
    def test_added_removed_changed(self):
        before = base_model()
        after = base_model()
        after["datasets"].append({"name": "cust", "source": "cust", "grain": "一行一户",
                                  "primary_key": "id", "fields": [{"name": "id", "role": "pk"}]})
        after["datasets"][0]["ai"]["instructions"] = "改了说明"
        report = drift_report(after, before)
        self.assertEqual([x["key"] for x in report["added"]], ["cust"])
        self.assertEqual([x["key"] for x in report["changed"]], ["orders"])
        self.assertEqual(report["breaking"], [])

    def test_removed_dataset_mounted_by_metric_is_breaking(self):
        before = base_model()
        before["metrics"] = [{"id": "m1", "dataset": "orders", "structured": True,
                              "expr": "COUNT(*)", "time_field": "dt"}]
        after = base_model()
        after["metrics"] = list(before["metrics"])
        after["datasets"] = []
        report = drift_report(after, before)
        self.assertTrue(any(b["kind"] == "dataset" and b["key"] == "orders"
                            for b in report["breaking"]))

    def test_pk_change_is_breaking(self):
        before = base_model()
        after = base_model()
        after["datasets"][0]["primary_key"] = "cust_id"
        report = drift_report(after, before)
        self.assertTrue(any("primary_key" in b["reason"] for b in report["breaking"]))

    def test_mapping_downgrade_is_breaking(self):
        before = base_model()
        before["ontology"] = {"entities": [{"name": "订单", "uid": "ent_o"},
                                           {"name": "客户", "uid": "ent_c"}],
                              "relations": [{"id": "rel_co", "from": "客户", "to": "订单",
                                             "predicate": "下", "mapping": "equi_key"}]}
        after = base_model()
        after["ontology"] = {"entities": list(before["ontology"]["entities"]),
                             "relations": [{"id": "rel_co", "from": "客户", "to": "订单",
                                            "predicate": "下", "mapping": "weak", "note": "x"}]}
        report = drift_report(after, before)
        self.assertTrue(any(b["kind"] == "ontology_relation" for b in report["breaking"]))

    def test_rename_with_uid_detects_stale_projection(self):
        before = base_model()
        before["ontology"] = {"entities": [{"name": "订单", "uid": "ent_o"}], "relations": []}
        before["datasets"][0]["ontology_ref"] = "订单"
        after = base_model()
        after["ontology"] = {"entities": [{"name": "销售订单", "uid": "ent_o"}], "relations": []}
        after["datasets"][0]["ontology_ref"] = "订单"
        report = drift_report(after, before)
        self.assertTrue(any("重命名" in b["reason"] for b in report["breaking"]))


class TestHistory(unittest.TestCase):
    def test_append_history_writes_jsonl(self):
        with tempfile.TemporaryDirectory() as tmp:
            model_path = Path(tmp) / "m.yaml"
            write(model_path, base_model())
            rep = Reporter()
            rep.warn("W01", "x", "y")
            hist = Path(tmp) / "h.jsonl"
            append_history(hist, model_path, base_model(), rep)
            append_history(hist, model_path, base_model(), rep)
            lines = hist.read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(lines), 2)
            record = json.loads(lines[0])
            self.assertEqual(record["warnings"], 1)
            self.assertEqual(record["by_code"], {"W01": 1})


class TestStarterPacks(unittest.TestCase):
    def test_all_packs_parse_and_have_ontology(self):
        import yaml
        packs = sorted((ROOT / "starter_packs").glob("*.yaml"))
        self.assertGreaterEqual(len(packs), 6)
        for pack in packs:
            data = yaml.safe_load(pack.read_text(encoding="utf-8"))
            self.assertIn("pack", data)
            self.assertTrue(data["ontology"].get("entities"))

    def test_pack_entities_have_uid(self):
        import yaml
        for pack in sorted((ROOT / "starter_packs").glob("*.yaml")):
            data = yaml.safe_load(pack.read_text(encoding="utf-8"))
            for e in data["ontology"]["entities"]:
                self.assertTrue(e.get("uid"), f"{pack.name}: {e.get('name')} 缺 uid")

    def test_merge_packs_dedup_and_no_overwrite(self):
        model = base_model()
        model["ontology"] = {"entities": [{"name": "订单", "uid": "ent_order", "cn": "我自己的订单"}],
                             "relations": []}
        applied = merge_packs(model, [ROOT / "starter_packs" / "retail.yaml",
                                      ROOT / "starter_packs" / "general.yaml"])
        ents = model["ontology"]["entities"]
        mine = [e for e in ents if e.get("uid") == "ent_order"]
        self.assertEqual(len(mine), 1)
        self.assertEqual(mine[0]["cn"], "我自己的订单")  # 已有对象不被覆盖
        self.assertTrue(any(e.get("uid") == "ent_customer" for e in ents))
        self.assertTrue(any(e.get("uid") == "ent_organization" for e in ents))
        self.assertEqual(len(applied), 2)

    def test_init_with_pack_merges_and_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            scope_path = Path(tmp) / "scope.yaml"
            write(scope_path, {"id": "s1", "question": "订单量？", "datasets": ["orders"]})
            session = new_session(base_model(), {"id": "s1", "question": "订单量？",
                                                 "datasets": ["orders"]}, "h",
                                  pack_paths=[ROOT / "starter_packs" / "general.yaml"])
            self.assertEqual(session["packs_applied"][0]["id"], "general")
            self.assertEqual(len(session["model"]["ontology"]["entities"]), 4)


class TestGapProtocol(unittest.TestCase):
    def make_session(self):
        scope = {"id": "s1", "question": "订单量？", "datasets": ["orders"],
                 "required": [{"object": "dataset:orders", "property": "grain",
                               "question": "一行是什么？", "owner_role": "business_owner",
                               "candidate": "一行一单"},
                              {"object": "dataset:orders", "property": "ai.instructions",
                               "question": "给模型的路由指令？", "owner_role": "fde",
                               "candidate": "只答订单量"}]}
        return new_session(base_model(), scope, "h")

    def test_state_labels(self):
        session = self.make_session()
        views = [gap_view(g) for g in session["gaps"]]
        labels = {v["property"]: v["state_label"] for v in views}
        self.assertEqual(labels["grain"], "[候选·来自材料]")
        self.assertEqual(labels["ai.instructions"], "[AI建议]")
        self.assertEqual(labels["temporal.kind"], "[待确认]")

    def test_suggestion_present_when_candidate(self):
        session = self.make_session()
        views = [gap_view(g) for g in session["gaps"] if g["property"] == "grain"]
        self.assertEqual(views[0]["suggestion"]["value"], "一行一单")
        self.assertIn("adopt_hint", views[0]["suggestion"])

    def test_clearance_counts_and_ready(self):
        session = self.make_session()
        c = clearance(session)
        self.assertEqual(c["counts"].get("candidate"), 2)
        self.assertGreater(c["outstanding"], 0)
        self.assertFalse(c["ready_for_validation"])
        for g in session["gaps"]:
            g["state"] = "confirmed"
        c2 = clearance(session)
        self.assertEqual(c2["outstanding"], 0)
        self.assertTrue(show(session)["clearance"]["ready_for_validation"])


class TestVisualizeV007(unittest.TestCase):
    def test_page_has_v007_hooks(self):
        for marker in ["导出 SVG", "主题域：", "data-kind", "EVIDENCE_STYLE",
                       "edgeFilter", "applyVisibility", "质量趋势"]:
            self.assertIn(marker, PAGE)

    def test_build_data_with_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            model_path = Path(tmp) / "m.yaml"
            write(model_path, base_model())
            hist = Path(tmp) / "h.jsonl"
            hist.write_text('{"at":"2026-09-29T00:00:00+00:00","errors":0,"warnings":2}\n',
                            encoding="utf-8")
            data = build_data(str(model_path), history_path=str(hist))
            self.assertEqual(data["history"][0]["warnings"], 2)

    def test_build_data_without_history_is_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            model_path = Path(tmp) / "m.yaml"
            write(model_path, base_model())
            data = build_data(str(model_path))
            self.assertIsNone(data["history"])


class TestCliDrift(unittest.TestCase):
    def test_cli_drift_exit_code_on_breaking(self):
        with tempfile.TemporaryDirectory() as tmp:
            before = base_model()
            before["metrics"] = [{"id": "m1", "dataset": "orders", "structured": True,
                                  "expr": "COUNT(*)", "time_field": "dt"}]
            after = base_model()
            after["metrics"] = list(before["metrics"])
            after["datasets"] = [{"name": "other", "source": "other", "grain": "一行一条",
                                  "primary_key": "id", "fields": [{"name": "id", "role": "pk"}]}]
            bp, ap = Path(tmp) / "b.yaml", Path(tmp) / "a.yaml"
            write(bp, before)
            write(ap, after)
            result = subprocess.run([sys.executable, str(ROOT / "scripts" / "check_model.py"),
                                     "-f", str(ap), "--drift", str(bp)],
                                    encoding="utf-8", capture_output=True,
                                    env=dict(os.environ, PYTHONIOENCODING="utf-8"),
                                    cwd=ROOT / "scripts")
            self.assertEqual(result.returncode, 1)
            self.assertIn("破坏", result.stdout)


if __name__ == "__main__":
    unittest.main()
