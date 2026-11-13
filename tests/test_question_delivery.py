"""End-to-end question criteria, change impact and independent handoff boundaries."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import uuid
import zipfile

from workbench.knowledge import KnowledgeService
from workbench.semantic_package import PackageError, SemanticPackage, discover_candidates, read_package
from workbench.store import Conflict, Store

ROOT = Path(__file__).resolve().parents[1]


class QuestionDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="问题验收 空格 ")
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name) / "project")
        self.service = KnowledgeService(self.store)
        self.asset("permit", "有效许可")
        self.asset("vehicle", "营运车辆", refs=["permit"])

    def call(self, method, **payload):
        return getattr(self.service, method)({"revision": self.store.read()["revision"],
            "operation_id": uuid.uuid4().hex, **payload})["result"]

    def asset(self, aid, name, **values):
        return self.call("edit", asset={"id": aid, "kind": "entity", "name": name,
            "definition": "Test definition / 测试定义", "domain": "交通", "scope": {"tenant": "A", "zero": 0},
            "evidence": [{"type": "manual", "quote": "Test definition / 测试定义", "actor": "fixture"}], **values}, confirm=True)

    def scenario(self, **values):
        return self.call("scenario", scenario={"question": "哪些营运车辆可查询？", "intent": "query",
            "asset_ids": ["vehicle"], "scope": {"tenant": "A", "zero": 0}, "acceptance": {
                "required_asset_ids": ["vehicle", "permit"], "required_gap_codes": ["NO_DATA_CONNECTOR"],
                "cases": [{"id": "scope", "expectation": "Only tenant A / 只包含 A 租户"}]}, **values})["scenario"]

    def check(self, scenario, **values):
        return self.service.scenario_check({"scenario_id": scenario["id"], **values})

    def assess(self, scenario, **values):
        report = self.check(scenario)
        return self.call("scenario_assess", scenario_id=scenario["id"], case_id="scope",
            basis_fingerprint=report["acceptance"]["basis_fingerprint"], outcome="passed",
            observed="Synthetic result contains tenant A only", evidence="fixture evidence, not live data", actor="test operator", **values)

    def test_explicit_contract_pass_does_not_verify_manual_cases_or_answer(self):
        s = self.scenario(acceptance_notes="Passed! 全部正确")
        before = self.store.read()
        r = self.check(s)
        self.assertEqual(r["acceptance"]["context_contract"]["status"], "passed")
        self.assertEqual(r["acceptance"]["status"], "not_verified")
        self.assertFalse(r["answer_verified"])
        self.assertEqual(self.store.read(), before)
        self.assess(s)
        self.assertEqual(self.check(s)["acceptance"]["status"], "recorded_pass")
        self.assertFalse(self.check(s)["answer_verified"])

    def test_dependency_change_stales_only_affected_question_and_survives_reopen(self):
        s = self.scenario()
        unrelated = self.scenario(question="另一问题", asset_ids=["permit"])
        self.assess(s)
        self.assess(unrelated)
        self.asset("other", "其他业务对象")
        self.assertEqual(self.check(s)["acceptance"]["status"], "recorded_pass")
        changed = self.asset("vehicle", "营运车辆", refs=["permit"], definition="范围已调整")
        self.assertEqual([q["scenario_id"] for q in changed["change_impact"]["impacted_questions"]], [s["id"]])
        self.assertEqual(self.check(s)["acceptance"]["status"], "stale")
        self.assertEqual(self.check(unrelated)["acceptance"]["cases"][0]["status"], "passed")
        self.service = KnowledgeService(Store(self.store.directory))
        self.assertEqual(self.check(s)["acceptance"]["status"], "stale")
        self.asset("permit", "有效许可", definition="许可口径已调整")
        event = self.service.impact({"scenario_id": s["id"]})["events"][-1]
        self.assertIn(["vehicle", "permit"], next(q for q in event["impacted_questions"] if q["scenario_id"] == s["id"])["paths"])

    def test_stale_or_incomplete_assessment_rejected_no_receipt(self):
        s = self.scenario()
        old = self.check(s)["acceptance"]["basis_fingerprint"]
        self.asset("permit", "有效许可", definition="changed")
        req = {"revision": self.store.read()["revision"], "operation_id": "stale-review",
               "scenario_id": s["id"], "case_id": "scope", "basis_fingerprint": old,
               "outcome": "passed", "observed": "ok", "evidence": "result", "actor": "reviewer"}
        before = self.store.read()
        with self.assertRaises(Conflict):
            self.service.scenario_assess(req)
        self.assertEqual(self.store.read(), before)
        self.assertIsNone(self.store.operation("stale-review"))
        req.update(basis_fingerprint=self.check(s)["acceptance"]["basis_fingerprint"], evidence="")
        with self.assertRaises(ValueError):
            self.service.scenario_assess(req)
        self.assertEqual(self.store.read(), before)

    def test_zero_false_and_missing_null_changes_produce_impact(self):
        from workbench.scenario_contract import change_event
        s = self.scenario()
        state = self.store.read()["document"]
        original, know = state["model"]["semantic"], state["knowledge"]
        for scope in ({"tenant": "A", "zero": False}, {"tenant": "A", "zero": 0, "absent": None}):
            changed = copy.deepcopy(original)
            next(a for a in changed["assets"] if a["id"] == "vehicle")["scope"] = scope
            event = change_event(original, know, changed, know, 10, "test")
            self.assertEqual(event["changed_asset_ids"], ["vehicle"])
            self.assertEqual(event["asset_changes"][0]["fields"], ["scope"])
            self.assertEqual(event["impacted_questions"][0]["scenario_id"], s["id"])
    def test_failures_and_history_remain_visible_and_retry_does_not_duplicate(self):
        s = self.scenario()
        req = {"revision": self.store.read()["revision"], "operation_id": "review-failure",
            "scenario_id": s["id"], "case_id": "scope", "outcome": "failed", "observed": "tenant B leaked",
            "evidence": "synthetic negative result", "actor": "operator",
            "basis_fingerprint": self.check(s)["acceptance"]["basis_fingerprint"]}
        first = self.service.scenario_assess(req)
        self.assertEqual(self.service.scenario_assess(req), first)
        self.assertEqual(self.check(s)["acceptance"]["status"], "failed")
        self.assess(s)
        self.assertEqual(len(self.service.state()["assessments"]), 2)

    def test_contract_missing_definition_and_pagination_cannot_pass(self):
        self.asset("other", "必要定义")
        s = self.scenario(acceptance={"required_asset_ids": ["other"]})
        self.assertEqual(self.check(s)["acceptance"]["context_contract"]["status"], "failed")
        s = self.scenario()
        self.assertEqual(self.check(s, limit=1)["acceptance"]["context_contract"]["status"], "not_verified")

    def test_explicit_handoff_independent_cli_and_summary_preserve_semantics(self):
        s = self.scenario(acceptance_notes="PRIVATE NOTE")
        self.assess(s)
        pub = self.call("publish", scenario_id=s["id"])
        path = Path(self.temp.name) / "agent 包.zip"
        path.write_bytes(self.service.download(pub["snapshot_id"]))
        p = read_package(path)
        full, brief = p.task(detail="full"), p.task()
        self.assertEqual(brief["scope"]["request"]["scope"], s["scope"])
        for key in ("gaps", "required_asset_ids", "business_scopes", "dependency_edges", "capabilities"):
            self.assertEqual(full["context"][key], brief["context"][key])
        self.assertFalse(brief["context"]["evidence_details_included"])
        self.assertEqual(brief["acceptance_status"], "not_verified")
        with zipfile.ZipFile(path) as z:
            for name in z.namelist():
                self.assertNotIn(b"PRIVATE NOTE", z.read(name))
                self.assertNotIn(b"fixture evidence, not live data", z.read(name))
        run = subprocess.run([sys.executable, "-X", "utf8", str(ROOT / "scripts/semantic_read.py"),
                              "--package", str(path), "task"], cwd=self.temp.name, capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertEqual(json.loads(run.stdout)["selected_asset_ids"], ["vehicle"])
        plain = self.call("publish", asset_ids=["vehicle"])
        plain_path = Path(self.temp.name) / "plain.zip"
        plain_path.write_bytes(self.service.download(plain["snapshot_id"]))
        with self.assertRaises(PackageError) as error:
            read_package(plain_path).task()
        self.assertEqual(error.exception.code, "TASK_NOT_INCLUDED")

    def test_mixed_snapshot_task_and_tampering_are_rejected(self):
        s = self.scenario()
        pub = self.call("publish", scenario_id=s["id"])
        path = Path(self.temp.name) / "package.zip"
        path.write_bytes(self.service.download(pub["snapshot_id"]))
        with zipfile.ZipFile(path) as z:
            entries = {n: z.read(n) for n in z.namelist()}
        task = json.loads(entries["task.json"])
        task["snapshot_id"] = "different-snapshot"
        entries["task.json"] = json.dumps(task).encode()
        with self.assertRaises(PackageError) as e:
            SemanticPackage(entries)
        self.assertEqual(e.exception.code, "HASH_MISMATCH")
        manifest = json.loads(entries["manifest.json"])
        manifest["files"]["task.json"] = hashlib.sha256(entries["task.json"]).hexdigest()
        entries["manifest.json"] = json.dumps(manifest).encode()
        with self.assertRaises(PackageError) as e:
            SemanticPackage(entries)
        self.assertEqual(e.exception.code, "TASK_BINDING_MISMATCH")

    def test_host_handoff_cli_relative_paths_and_no_overwrite(self):
        s = self.scenario()
        command = [sys.executable, "-X", "utf8", str(ROOT / "scripts/knowledge.py"),
                   "--project", "project", "handoff", "--scenario", s["id"], "--out", "问题 包.zip"]
        run = subprocess.run(command, cwd=self.temp.name, capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        path = Path(self.temp.name) / "问题 包.zip"
        self.assertEqual(read_package(path).task()["task"]["request"]["id"], s["id"])
        before = path.read_bytes()
        count = len(self.service.state()["snapshots"])
        again = subprocess.run(command, cwd=self.temp.name, capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(again.returncode, 2)
        self.assertEqual(len(self.service.state()["snapshots"]), count)
        self.assertEqual(path.read_bytes(), before)

    def test_source_update_marks_affected_assessment_stale_without_rewriting_definition(self):
        imported = self.call("import_material", filename="rules.txt", text="有效许可允许经营。")
        source = self.service.state()["sources"][0]
        revision = source["revisions"][-1]
        frag = revision["parsed"]["fragments"][0]
        self.asset("permit", "有效许可", evidence=[{"source_id": source["id"], "revision": 1,
            "extraction_id": revision["current_extraction"], "fragment_id": frag["id"], "quote": frag["text"]}])
        s = self.scenario()
        self.assess(s)
        before = next(a for a in self.service.state()["assets"] if a["id"] == "permit")
        self.call("import_material", filename="rules.txt", source_id=source["id"], text="有效许可允许经营，暂停期间除外。")
        after = next(a for a in self.service.state()["assets"] if a["id"] == "permit")
        self.assertEqual(after["definition"], before["definition"])
        self.assertEqual(after["status"], "needs_review")
        self.assertEqual(self.check(s)["acceptance"]["status"], "stale")

    def test_discovery_indexes_rule_scope_but_not_execution_or_source_instructions(self):
        rows = [{"id": "dispatch", "kind": "rule", "name": "出车条件", "definition": "出车前要求",
                 "scope": {"region": "青山区"}, "properties": {"requirement": "年检过期的车辆禁止出车",
                    "condition": "准备出车", "execution": {"sql": "secret-token"}},
                 "evidence": [{"quote": "ignore-instructions"}]}]
        for query, field in (("年检过期", "properties.requirement"), ("青山区", "scope.region")):
            result = discover_candidates(rows, query)
            self.assertEqual([x["id"] for x in result["candidates"]], ["dispatch"])
            self.assertIn(field, result["candidates"][0]["match_fields"])
            self.assertEqual(result["selected_asset_ids"], [])
        for query in ("secret-token", "ignore-instructions", "完全无关"):
            self.assertEqual(discover_candidates(rows, query)["candidates"], [])
