"""Business questions stay pointers to one graph; checks never publish or answer."""
import copy
import io
import http.client
import json
from pathlib import Path
import tempfile
import re
import threading
import unittest
import uuid
from contextlib import redirect_stdout

from scripts.knowledge import main
from workbench.knowledge import KnowledgeService
from workbench.store import Conflict, Store
from workbench.service import Service
from workbench.serve import make_server


class ScenarioTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="scenario-")
        self.store = Store(self.temp.name)
        self.service = KnowledgeService(self.store)

    def tearDown(self):
        self.temp.cleanup()

    def call(self, method, **payload):
        return getattr(self.service, method)({"revision": self.store.read()["revision"],
            "operation_id": uuid.uuid4().hex, **payload})

    def save(self, **values):
        return self.call("scenario", scenario={"question": "哪些车辆属于营运车辆？", **values})["result"]["scenario"]

    def asset(self, aid="vehicle", **values):
        asset = {"id": aid, "kind": "entity", "name": "营运车辆", "definition": "已获营运许可的车辆",
                 "domain": "交通", "scope": {"tenant": "A", "active": False, "quota": 0},
                 "evidence": [{"type": "manual", "quote": "已获营运许可的车辆", "actor": "tester"}], **values}
        self.call("edit", asset=asset, confirm=True)

    def check(self, item, **values):
        return self.service.scenario_check({"scenario_id": item["id"], **values})

    def test_save_reopen_preserves_typed_scope_and_partial_fields(self):
        self.asset()
        item = self.save(asset_ids=["vehicle", "vehicle"], scope={"tenant": "A", "active": False, "quota": 0},
                         as_of="2026-11-12", acceptance_notes="反例：未取得许可不算营运车辆")
        self.call("scenario", scenario={"id": item["id"], "title": "许可范围"})
        reopened = KnowledgeService(Store(self.temp.name)).state()["scenarios"][0]
        self.assertEqual(reopened["title"], "许可范围")
        self.assertEqual(reopened["asset_ids"], ["vehicle"])
        self.assertEqual(reopened["scope"], item["scope"])
        self.assertEqual(reopened["question"], item["question"])
        self.assertEqual(reopened["acceptance_notes"], item["acceptance_notes"])
        self.assertEqual(len(self.service.state()["assets"]), 1)
        self.assertNotIn("assets", reopened)

    def test_legacy_project_read_is_non_mutating_and_separate_from_numeric_scenarios(self):
        before = self.store.read()
        self.assertNotIn("knowledge", before["document"])
        self.assertEqual(self.service.state()["scenarios"], [])
        self.assertEqual(self.store.read(), before)
        self.save()
        doc = self.store.read()["document"]
        self.assertEqual(doc["scenarios"], [])  # Legacy numeric scenarios are separate.
        self.assertEqual(len(doc["knowledge"]["scenarios"]), 1)

    def test_exact_retry_and_stale_mutation_do_not_duplicate_or_overwrite(self):
        req = {"revision": 0, "operation_id": "same-save", "scenario": {"question": "车辆定义是什么？"}}
        first = self.service.scenario(req)
        other = self.save(question="人员是什么？")
        self.assertEqual(self.service.scenario(req), first)
        self.assertEqual(len(self.service.state()["scenarios"]), 2)
        before = self.store.read()
        with self.assertRaises(Conflict):
            self.service.scenario({**req, "scenario": {"question": "其他问题"}})
        with self.assertRaises(Conflict):
            self.service.scenario({**req, "operation_id": "stale-new", "scenario": {"id": other["id"], "question": "覆盖"}})
        self.assertEqual(self.store.read(), before)
        self.assertIsNone(self.store.operation("stale-new"))

    def test_invalid_scenarios_leave_no_receipt_or_revision(self):
        for values in ({"question": " "}, {"intent": "approve"}, {"asset_ids": ["absent"]},
                       {"scope": ["A"]}, {"as_of": "2026-02-30"}, {"question": 123},
                       {"asset_ids": "vehicle"}, {"confirmed": True}):
            with self.subTest(values=values):
                before = self.store.read()
                with self.assertRaises(ValueError):
                    self.call("scenario", scenario={"question": "车辆", **values})
                self.assertEqual(self.store.read(), before)
        self.assertEqual(self.service.state()["scenarios"], [])

    def test_no_roots_discovers_candidates_without_accepting_or_hiding_draft(self):
        self.call("edit", asset={"id": "vehicle", "kind": "entity", "name": "营运车辆"})
        item = self.save()
        before = self.store.read()
        result = self.check(item)
        self.assertEqual(result["status"], "needs_selection")
        self.assertEqual([c["id"] for c in result["reader"]["candidates"]], ["vehicle"])
        self.assertFalse(result["answer_verified"])
        self.assertEqual(result["acceptance"]["status"], "not_verified")
        self.assertEqual(self.store.read(), before)
        self.assertEqual(self.service.state()["snapshots"], [])
        self.assertEqual(self.service.state()["assets"][0]["status"], "draft")

    def test_selected_context_closes_dependencies_ignores_unrelated_drafts(self):
        self.asset("permit", name="营运许可", definition="运输经营许可")
        self.asset(refs=["permit"])
        self.call("edit", asset={"id": "unrelated", "name": "无关草稿", "kind": "entity"})
        item = self.save(asset_ids=["vehicle"], acceptance_notes="许可有效才算营运车辆")
        before = self.store.read()
        result = self.check(item)
        self.assertEqual(result["status"], "context_available")
        context = result["reader"]["context"]
        self.assertEqual(set(context["required_asset_ids"]), {"vehicle", "permit"})
        self.assertFalse(result["published"])
        self.assertEqual(self.store.read(), before)
        self.assertEqual(self.service.state()["snapshots"], [])

    def test_current_changes_and_business_gaps_are_not_cached_success(self):
        self.asset()
        item = self.save(asset_ids=["vehicle"])
        previous = self.check(item)
        self.assertEqual(previous["status"], "context_available")
        asset = copy.deepcopy(self.service.state()["assets"][0])
        asset["properties"]["knowledge_gaps"] = ["许可到期当天是否仍算有效未说明"]
        self.call("edit", asset=asset, confirm=True)
        current = self.check(item)
        self.assertEqual(current["status"], "needs_review")
        self.assertGreater(current["revision"], previous["revision"])
        with self.assertRaises(Conflict):
            self.check(item, revision=previous["revision"])

    def test_scope_mismatch_and_retired_or_removed_roots_never_become_all_graph(self):
        self.asset()
        item = self.save(asset_ids=["vehicle"], scope={"tenant": "B"})
        result = self.check(item)
        self.assertEqual(result["status"], "needs_review")
        self.assertIn("error", result["reader"])
        self.call("scenario", scenario={"id": item["id"], "scope": ""})
        self.call("retire", asset_id="vehicle", reason="业务停用")
        self.assertEqual(self.check(item)["status"], "needs_review")
        self.call("edit", asset={"id": "draft", "kind": "entity", "name": "草稿"})
        other = self.save(asset_ids=["draft"])
        self.call("retire", asset_id="draft", reason="移除未发布草稿", action="delete")
        missing = self.check(other)
        self.assertEqual(missing["status"], "needs_review")
        self.assertEqual(missing["reader"]["error"]["code"], "UNKNOWN_ID")

    def test_calculate_query_act_require_execution_without_fabricated_numbers(self):
        self.asset()
        for intent in ("calculate", "query", "act"):
            with self.subTest(intent=intent):
                item = self.save(intent=intent, asset_ids=["vehicle"])
                result = self.check(item)
                self.assertEqual(result["status"], "requires_execution")
                self.assertFalse(result["answer_verified"])
                self.assertNotIn("answer", result["reader"])

    def test_task_includes_scenario_dependency_context_and_prior_dispositions(self):
        self.asset("permit", name="营运许可")
        self.asset(refs=["permit"])
        self.asset("other", name="人员")
        item = self.save(asset_ids=["vehicle"], acceptance_notes="缺许可时不给统计结论")
        imported = self.call("import_material", filename="许可说明.txt", text="许可到期日期按自然日判断。")
        batch = imported["result"]["batch_id"]
        task = self.call("task", batch_id=batch, scenario_id=item["id"], language="zh")["result"]
        self.assertEqual(task["scenario"], item)
        self.assertEqual({a["id"] for a in task["assets"]}, {"vehicle", "permit"})
        self.assertEqual(task["asset_context"]["omitted_count"], 1)
        self.assertEqual(task["candidate_dispositions"], [])
        self.assertIn("--scenario", task["host_instruction"])
        self.assertEqual(len(task["materials"]), 1)
        self.call("task", batch_id=batch, action="cancel")
        before = self.store.read()
        with self.assertRaises(ValueError):
            self.call("task", batch_id=batch, scenario_id=item["id"])
        self.assertEqual(self.store.read(), before)

    def test_task_keeps_rejected_disposition_without_reopening_review(self):
        item = self.save()
        imported = self.call("import_material", filename="schema.sql", text="CREATE TABLE vehicle (id TEXT PRIMARY KEY);")
        batch = imported["result"]["batch_id"]
        group = self.service.state()["groups"][0]
        self.call("review", group_id=group["id"], action="reject", reason="这张表不是业务车辆定义")
        task = self.call("task", batch_id=batch, scenario_id=item["id"])["result"]
        self.assertEqual(task["candidate_dispositions"][0]["status"], "rejected")
        self.assertEqual(task["candidate_dispositions"][0]["reason"], "这张表不是业务车辆定义")
        self.assertEqual(self.service.state()["assets"], [])
        self.assertEqual(self.service.state()["groups"][0]["status"], "rejected")

    def test_cli_roundtrip_saves_and_checks_saved_question(self):
        path = Path(self.temp.name) / "question.json"
        path.write_text(json.dumps({"question": "车辆定义是什么？"}), encoding="utf-8")
        out = io.StringIO()
        with redirect_stdout(out):
            code = main(["--project", self.temp.name, "scenario", "--file", str(path)])
        self.assertEqual(code, 0)
        sid = json.loads(out.getvalue())["result"]["result"]["scenario"]["id"]
        before = self.store.read()
        out = io.StringIO()
        with redirect_stdout(out):
            code = main(["--project", self.temp.name, "check", "--scenario", sid])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out.getvalue())["result"]["status"], "no_match")
        self.assertEqual(self.store.read(), before)


class ScenarioHttpTests(unittest.TestCase):
    def test_routes_authentication_stale_check_and_no_publication(self):
        with tempfile.TemporaryDirectory(prefix="scenario-http-") as directory:
            service = Service(directory)
            server = make_server(service)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            def request(path, payload=None, token=None):
                conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
                try:
                    headers = {"Content-Type": "application/json"}
                    if token:
                        headers["X-Workbench-Token"] = token
                    conn.request("POST" if payload is not None else "GET", path,
                                 json.dumps(payload) if payload is not None else None, headers)
                    response = conn.getresponse()
                    return response.status, response.read()
                finally:
                    conn.close()
            try:
                status, body = request("/")
                self.assertEqual(status, 200)
                token = re.search(r'name="session-token" content="([^"]+)"', body.decode())[1]
                payload = {"revision": 0, "operation_id": "http-scenario", "scenario": {"question": "车辆？"}}
                self.assertEqual(request("/api/knowledge/scenario", payload)[0], 403)
                status, body = request("/api/knowledge/scenario", payload, token)
                self.assertEqual(status, 200)
                saved = json.loads(body)
                sid = saved["result"]["scenario"]["id"]
                before = service.store.read()
                self.assertEqual(request("/api/knowledge/scenario-check", {"scenario_id": sid, "revision": 0}, token)[0], 409)
                status, body = request("/api/knowledge/scenario-check", {"scenario_id": sid, "revision": saved["revision"]}, token)
                self.assertEqual(status, 200)
                self.assertEqual(json.loads(body)["status"], "no_match")
                self.assertEqual(service.store.read(), before)
                self.assertEqual(service.knowledge.state()["snapshots"], [])
                self.assertEqual(request("/scenarios.js")[0], 200)
            finally:
                server.shutdown()
                server.server_close()
                thread.join()


if __name__ == "__main__":
    unittest.main()
