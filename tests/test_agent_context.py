"""Consumer-facing context, scope fidelity, discoverability and honest capability boundaries."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from test_semantic_package import asset, fixture
from workbench.semantic_package import PackageError, build_package, read_package
from workbench.knowledge import KnowledgeService
from workbench.store import Store
import uuid


class AgentContextTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="独立 Agent 上下文 ")
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "语义.zip"

    def package(self, assets, sources=None, **kw):
        content, _ = build_package(assets, sources or [], project_id="context-test", revision=3, **kw)
        self.path.write_bytes(content)
        return read_package(self.path)

    def test_rule_property_scope_and_metric_search_without_indexing_execution_or_instructions(self):
        dispatch = asset("dispatch", "rule", "工单派发", properties={"condition": "需要派单且企业唯一", "requirement": "保留原记录"})
        outcome = asset("outcome", "rule", "成果判断", properties={"condition": "排除缺考", "requirement": "累计比例达到70%"},
                        scope={"currency": "单一币种", "constraints": ["仅校内"]})
        metric = asset("metric", "metric", properties={"exclusions": "撤销记录"})
        outcome["properties"]["execution"] = {"sql": "SECRET_EXECUTION_MARKER"}
        outcome["evidence"][0]["quote"] = "UNTRUSTED_SOURCE_COMMAND"
        package = self.package([dispatch, outcome, metric], include_execution=True)
        for word, aid, field in [("派单", "dispatch", "properties.condition"), ("70%", "outcome", "properties.requirement"),
                                  ("缺考", "outcome", "properties.condition"), ("单一币种", "outcome", "scope.currency"),
                                  ("撤销记录", "metric", "properties.exclusions")]:
            row = package.search(word)["matches"][0]
            self.assertEqual(row["asset"]["id"], aid)
            self.assertIn(field, row["match_fields"])
        self.assertEqual(package.search("SECRET_EXECUTION_MARKER")["status"], "not_found")
        self.assertEqual(package.search("UNTRUSTED_SOURCE_COMMAND")["status"], "not_found")

    def test_context_closes_required_references_and_preserves_edge_meaning(self):
        values, sources = fixture()
        values[3]["refs"] += ["maintains", "scope"]
        values.append(asset("scope", "rule", "业务适用范围", scope="单一账簿、只做多", refs=["rule"]))
        package = self.package(values, sources)
        result = package.context(["rule"])
        self.assertTrue(result["complete"])
        self.assertEqual(set(result["required_asset_ids"]), {"rule", "vehicle", "company", "maintains", "scope"})
        self.assertNotIn("revenue_sales", {a["id"] for a in result["assets"]})
        self.assertIn({"asset_id": "scope", "scope": "单一账簿、只做多"}, result["business_scopes"])
        ref = next(e for e in result["dependency_edges"] if e["from"] == "rule" and e["to"] == "maintains")
        self.assertEqual(ref["edge_kind"], "definition_reference")
        endpoint = next(e for e in result["dependency_edges"] if e["from"] == "maintains" and e["to"] == "company")
        self.assertEqual(endpoint["edge_kind"], "relation_endpoint")
        self.assertEqual(result["relations"][0]["from"], "company")
        self.assertEqual(result["relations"][0]["predicate"], "维护")
        ev = next(e for e in result["evidence"] if e["asset_id"] == "rule")["evidence"][0]
        self.assertEqual(ev["fragment"]["text"], "企业负责本企业车辆维护。")
        self.assertEqual(ev["assertion"]["revision"], 1)

    def test_context_quality_is_local_and_conflict_diagnostics_preserve_actual_trigger(self):
        bad = asset("bad", properties={"unresolved_conflicts": {"identity_review": [
            {"code": "IDENTITY_REVIEW", "matched_terms": ["账户"], "asset_ids": ["bad", "other"]}]}})
        package = self.package([asset("good"), bad, asset("other")], draft=True)
        clean = package.context(["good"])
        self.assertTrue(clean["request_complete"])
        self.assertFalse(clean["package_complete"])
        self.assertTrue(package.get("good")["complete"])
        conflict = package.context(["bad"])
        self.assertFalse(conflict["request_complete"])
        issue = next(g for g in conflict["gaps"] if g["code"] == "UNRESOLVED_CONFLICT")
        self.assertEqual(issue["conflicts"]["identity_review"][0]["matched_terms"], ["账户"])

    def test_missing_reference_evidence_declared_gaps_and_source_warnings_are_explicit(self):
        values, sources = fixture()
        values[3]["refs"] += ["unknown"]
        values[3]["properties"]["knowledge_gaps"] = ["生效时点未提供"]
        sources[0]["revisions"][0]["parsed"].update(status="partial", warnings=["第2页未提取"])
        package = self.package(values, sources, draft=True)
        result = package.context(["rule"], as_of="2026-11-09")
        codes = {g["code"] for g in result["gaps"]}
        self.assertTrue({"MISSING_DEPENDENCY", "DECLARED_KNOWLEDGE_GAP", "APPLICABILITY_UNKNOWN"} <= codes)
        self.assertFalse(result["complete"])
        self.assertEqual(result["missing_dependencies"], [{"asset_id": "rule", "dependency": "unknown"}])
        self.assertEqual(result["source_warnings"][0]["parse"]["warnings"], ["第2页未提取"])
        package = self.package([asset("bad", status="draft", evidence=[])], draft=True)
        result = package.context(["bad"])
        self.assertIn("MISSING_EVIDENCE", {x["code"] for x in result["gaps"]})
        self.assertFalse(result["knowledge_complete"])

    def test_pagination_no_silent_truncation_and_capabilities_do_not_imply_execution(self):
        values = [asset("r", "rule", refs=["a", "b"], properties={"execution": {"refs": ["executor"], "status": "approved"}}),
                  asset("a"), asset("b"), asset("executor", "dataset")]
        package = self.package(values, include_execution=True)
        first = package.context(["r"], intent="query", limit=2)
        self.assertEqual(first["assets"][0]["id"], "r")
        self.assertFalse(first["request_complete"])
        self.assertTrue(first["knowledge_complete"])
        self.assertEqual(first["next_offset"], 2)
        self.assertTrue({"NO_DATA_CONNECTOR", "CONTEXT_TRUNCATED"} <= {x["code"] for x in first["gaps"]})
        second = package.context(["r"], limit=2, offset=2)
        self.assertFalse(second["complete"])
        self.assertIsNone(second["next_offset"])
        self.assertEqual({a["id"] for a in first["assets"] + second["assets"]}, {"r", "a", "b", "executor"})
        action = package.context(["r"], intent="act")
        self.assertFalse(action["capabilities"]["execute_actions"]["available"])
        self.assertIn("NO_ACTION_EXECUTOR", {x["code"] for x in action["gaps"]})

    def test_redirects_and_invalid_context_inputs(self):
        package = self.package([asset("new")], redirects={"old": "new"})
        self.assertEqual(package.context(["old"])["root_ids"], ["new"])
        for ids, kwargs in [([], {}), (["new", "new"], {}), (["new"], {"intent": "execute"}), (["new"], {"limit": 0}),
                            (["new"], {"as_of": "2026-02-30"})]:
            with self.assertRaises(PackageError):
                package.context(ids, **kwargs)
        with self.assertRaises(PackageError) as caught:
            package.context(["absent"])
        self.assertEqual(caught.exception.code, "UNKNOWN_ID")

    def test_scope_survives_real_authoring_publish_and_subgraph_in_independent_cli(self):
        store = Store(Path(self.temp.name) / "project")
        service = KnowledgeService(store)
        def call(method, **data):
            return getattr(service, method)({"revision": store.read()["revision"], "operation_id": uuid.uuid4().hex, **data})["result"]
        scope = "仅单一币种、单一账簿、只做多。"
        imported = call("import_material", filename="账簿原文.txt", text=scope + "\n\n可用资金为现金减有效冻结。", domain="证券模拟", scope=scope)
        task = call("task", batch_id=imported["batch_id"])
        material = task["materials"][0]
        fragments = material["parsed"]["fragments"]
        evidence = [{"source_id": material["source_id"], "revision": material["revision"], "fragment_id": f["id"], "quote": f["text"]} for f in fragments]
        scope_rule = asset("scope", "rule", "账簿范围", scope=scope, evidence=[evidence[0]], properties={"condition": "使用本模拟账簿", "requirement": scope})
        metric = asset("cash", "metric", "可用资金", refs=["scope"], scope=scope, evidence=[evidence[-1]])
        group = call("propose", batch_id=imported["batch_id"], groups=[{"summary": "核对范围及资金", "candidates": [{"asset": a} for a in [scope_rule, metric]]}])["group_ids"][0]
        call("review", group_id=group, action="accept")
        published = call("publish", asset_ids=["cash"], draft=True)
        self.path.write_bytes(service.download(published["snapshot_id"]))
        reader = read_package(self.path)
        content, _ = reader.export(["cash"])
        child = Path(self.temp.name) / "单指标 子图.zip"
        child.write_bytes(content)
        cli = Path(__file__).resolve().parents[1] / "scripts/semantic_read.py"
        result = subprocess.run([sys.executable, "-X", "utf8", str(cli), "--package", str(child), "context", "--id", "cash"],
                                cwd=self.temp.name, capture_output=True, text=True, encoding="utf-8", check=True)
        answer = json.loads(result.stdout)
        self.assertEqual(set(answer["required_asset_ids"]), {"cash", "scope"})
        self.assertTrue(all(row["scope"] == scope for row in answer["business_scopes"]))
        source = next(x for x in answer["evidence"] if x["asset_id"] == "scope")["evidence"][0]
        self.assertEqual(source["fragment"]["text"], scope)
        self.assertEqual(source["source_scope"], scope)
        # Independent reopening did not require the original project or source attachment.
        discover = subprocess.run([sys.executable, str(cli), "--package", str(child), "describe"],
                                  cwd=self.temp.name, capture_output=True, text=True, encoding="utf-8", check=True)
        self.assertIn("context", {t["name"] for t in json.loads(discover.stdout)["tools"]})


if __name__ == "__main__":
    unittest.main()
