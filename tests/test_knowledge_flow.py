"""Behavioral acceptance of authoring transactions, incremental intake and handoff."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
import uuid

from workbench.store import Store, Conflict
from workbench.knowledge import KnowledgeService
from workbench.semantic_package import read_package


DDL = """CREATE TABLE company (id TEXT PRIMARY KEY, region TEXT);
CREATE TABLE vehicle (id TEXT PRIMARY KEY, company_id TEXT,
 FOREIGN KEY (company_id) REFERENCES company(id));"""
TEXT = """营运车辆是获准经营运输业务的车辆，营运车为其别名。

企业负责本企业车辆维护。

监管机构监管企业，不是企业或车辆的所有者。

异常车辆数按企业统计有效异常车辆的不同车辆ID，不按异常记录条数计数。"""


class KnowledgeFlowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="语义 项目 ")
        self.store = Store(self.temp.name)
        self.service = KnowledgeService(self.store)

    def tearDown(self):
        self.temp.cleanup()

    def call(self, method, **data):
        req = {"revision": self.store.read()["revision"], "operation_id": uuid.uuid4().hex, **data}
        return getattr(self.service, method)(req)

    def source(self, text=TEXT, filename="领域说明.txt", **extra):
        result = self.call("import_material", filename=filename, text=text, domain="交通", scope="合成验收范围", **extra)["result"]
        source = next(s for s in self.service.state()["sources"] if s["id"] == result["source_id"])
        return source, result

    def evidence(self, source, phrase):
        rev = source["revisions"][-1]
        fragment = next(f for f in rev["parsed"]["fragments"] if phrase in f["text"])
        return [{"source_id": source["id"], "revision": rev["revision"], "fragment_id": fragment["id"], "quote": phrase}]

    def entity(self, id, name, source, quote):
        return {"id": id, "kind": "entity", "name": name, "definition": quote, "domain": "交通", "scope": "合成验收范围",
                "aliases": [], "refs": [], "properties": {}, "evidence": self.evidence(source, quote)}

    def propose(self, batch, assets, **extra):
        return self.call("propose", batch_id=batch, groups=[{"summary": "核对车辆知识", "candidates": [
            {"op": "upsert", "asset": a} for a in assets]}], complete=True, **extra)["result"]["group_ids"][0]

    def seed(self):
        source, result = self.source()
        company = self.entity("company", "企业", source, "企业负责本企业车辆维护。")
        vehicle = self.entity("vehicle", "营运车辆", source, "营运车辆是获准经营运输业务的车辆，营运车为其别名。")
        vehicle["aliases"] = ["营运车"]
        rule = {**self.entity("maintain", "车辆维护职责", source, "企业负责本企业车辆维护。"), "kind": "rule",
                "refs": ["company", "vehicle"], "properties": {"condition": "本企业车辆", "requirement": "企业负责维护"}}
        group = self.propose(result["batch_id"], [company, vehicle, rule])
        self.call("review", group_id=group, action="accept")
        return source, group

    def package(self, name="snapshot.zip", **req):
        result = self.call("publish", **req)["result"]
        path = Path(self.temp.name) / name
        path.write_bytes(self.service.download(result["snapshot_id"]))
        return path, result

    def test_m1_from_real_material_to_independent_package_reopen(self):
        _, ddl = self.source(DDL, "schema.sql")
        group = self.service.state()["groups"][0]
        self.assertEqual(self.service.state()["assets"], [])
        self.call("review", group_id=group["id"], action="accept")
        physical = [a for a in self.service.state()["assets"] if a.get("relation_type") == "physical_fk"]
        self.assertEqual(physical[0]["properties"]["from_fields"], ["company_id"])
        self.seed()
        path, result = self.package()
        read = read_package(path)
        self.assertIn("企业负责", json.dumps(read.get("maintain"), ensure_ascii=False))
        self.assertIn("营运车", json.dumps(read.search("营运车"), ensure_ascii=False))
        reloaded = KnowledgeService(Store(self.temp.name)).state()
        self.assertEqual(len(reloaded["assets"]), len(self.service.state()["assets"]))
        self.assertEqual(reloaded["snapshots"][0]["snapshot_id"], result["snapshot_id"])

    def test_m2_source_change_blocks_affected_scope_but_allows_independent_terms(self):
        source, _ = self.seed()
        s1, _ = self.package("s1.zip")
        text = TEXT.replace("企业负责本企业车辆维护。", "企业负责本企业车辆维护并保存维护记录。")
        self.source(text, source_id=source["id"])
        state = self.service.state()
        self.assertEqual(next(a for a in state["assets"] if a["id"] == "maintain")["status"], "needs_review")
        with self.assertRaises(ValueError):
            self.package(asset_ids=["maintain"])
        independent, _ = self.package("terms.zip", asset_ids=["vehicle"])
        self.assertIn("营运车辆", json.dumps(read_package(independent).get("vehicle"), ensure_ascii=False))
        current_source = state["sources"][0]
        for key in ("company", "maintain"):
            a = copy.deepcopy(next(a for a in state["assets"] if a["id"] == key))
            a["definition"] = "企业负责本企业车辆维护并保存维护记录。"
            a["evidence"] = self.evidence(current_source, a["definition"])
            if key == "maintain":
                a["properties"]["requirement"] = "维护并保存维护记录"
            self.call("review_source", asset_id=key, action="adopt", reason="验收给定采纳修订", asset=a)
        s2, _ = self.package("s2.zip")
        self.assertNotIn("保存维护记录", json.dumps(read_package(s1).get("maintain"), ensure_ascii=False))
        self.assertIn("保存维护记录", json.dumps(read_package(s2).get("maintain"), ensure_ascii=False))

    def test_same_content_distinct_provenance_and_changed_filename(self):
        source, _ = self.source()
        _, repeated = self.source(filename="重命名.txt")
        self.assertTrue(repeated["duplicate"])
        self.assertEqual(len(self.service.state()["sources"]), 1)
        self.source(filename="另一机构发布.txt", distinct_source=True)
        self.assertEqual(len(self.service.state()["sources"]), 2)
        with self.assertRaisesRegex(ValueError, "同名"):
            self.source("另一条规定")
        self.assertEqual(self.service.state()["sources"][0]["current_revision"], 1)

    def test_stale_target_atomic_group_no_partial_relation(self):
        source, _ = self.seed()
        _, new = self.source(TEXT + "\n新补充。", filename="补充.txt", distinct_source=True)
        a = copy.deepcopy(next(x for x in self.service.state()["assets"] if x["id"] == "vehicle"))
        a["aliases"].append("运营车辆")
        group = self.propose(new["batch_id"], [a, {**self.entity("new", "新对象", source, "企业负责本企业车辆维护。")}])
        original = copy.deepcopy(next(x for x in self.service.state()["assets"] if x["id"] == "vehicle"))
        original["name"] = "人工改名的车辆"
        self.call("edit", asset=original, confirm=True)
        before = self.store.read()
        with self.assertRaises(Conflict):
            self.call("review", group_id=group, action="accept")
        self.assertEqual(self.store.read(), before)
        self.assertNotIn("new", [a["id"] for a in self.service.state()["assets"]])

    def test_missing_dependency_and_bad_evidence_do_not_write_graph(self):
        source, result = self.source()
        a = self.entity("one", "对象", source, "企业负责本企业车辆维护。")
        a["refs"] = ["missing"]
        group = self.propose(result["batch_id"], [a])
        with self.assertRaises(ValueError) as missing:
            self.call("review", group_id=group, action="accept")
        self.assertEqual(missing.exception.code, "INVALID_MODEL")
        self.assertIn("missing", json.dumps(missing.exception.details, ensure_ascii=False))
        self.assertEqual(self.service.state()["assets"], [])
        a["evidence"][0]["quote"] = "并不存在的政策"
        with self.assertRaisesRegex(ValueError, "原文"):
            self.propose(result["batch_id"], [a])

    def test_receipt_replay_before_revision_guard_and_payload_reuse_rejected(self):
        req = {"revision": 0, "operation_id": "fixed", "filename": "a.txt", "text": TEXT}
        first = self.service.import_material(req)
        self.source("其他材料。", filename="b.txt")
        self.assertEqual(self.service.import_material(req), first)
        with self.assertRaises(Conflict):
            self.service.import_material({**req, "text": "different"})

    def test_cancel_late_results_and_reject_replay(self):
        source, result = self.source()
        a = self.entity("one", "对象", source, "企业负责本企业车辆维护。")
        self.call("task", batch_id=result["batch_id"], action="cancel")
        late = self.call("propose", batch_id=result["batch_id"], groups=[{"candidates": [{"asset": a}]}])["result"]
        self.assertEqual(late["status"], "cancelled")
        self.assertFalse(self.service.state()["groups"])
        self.call("task", batch_id=result["batch_id"], action="resume")
        group = self.propose(result["batch_id"], [a])
        self.call("review", group_id=group, action="reject", reason="验收拒绝")
        again = self.propose(result["batch_id"], [a])
        self.assertEqual(again, group)
        self.assertEqual(self.service.state()["groups"][0]["status"], "rejected")

    def test_merge_redirects_references_and_safe_undo(self):
        source, _ = self.seed()
        vehicle = copy.deepcopy(next(a for a in self.service.state()["assets"] if a["id"] == "vehicle"))
        vehicle["id"], vehicle["name"] = "vehicle2", "运营车辆"
        self.call("edit", asset=vehicle, confirm=True)
        merged = self.call("merge", survivor_id="vehicle", merged_id="vehicle2", reason="同一对象别名")
        self.assertEqual(self.service.state()["document"]["model"]["semantic"]["redirects"]["vehicle2"], "vehicle")
        self.call("undo", target_revision=merged["revision"])
        self.assertIn("vehicle2", [a["id"] for a in self.service.state()["assets"]])
        self.assertNotIn("vehicle2", self.service.state()["document"]["model"]["semantic"]["redirects"])

    def test_retired_required_asset_blocks_publication_and_delete_is_guarded(self):
        self.seed()
        self.call("retire", asset_id="vehicle", reason="定义停用")
        with self.assertRaises(ValueError):
            self.package(asset_ids=["maintain"])
        with self.assertRaises(ValueError):
            self.call("retire", asset_id="vehicle", action="delete")

    def test_execution_dependencies_guard_delete_undo_and_report_retire_references(self):
        source, _ = self.source()
        for ref_field in ("refs", "data_refs"):
            with self.subTest(ref_field=ref_field):
                target_id, consumer_id = "target_" + ref_field, "consumer_" + ref_field
                target = self.entity(target_id, target_id, source, "企业负责本企业车辆维护。")
                created = self.call("edit", asset=target, confirm=False)
                consumer = self.entity(consumer_id, consumer_id, source, "企业负责本企业车辆维护。")
                consumer["properties"]["execution"] = {ref_field: [target_id], "status": "declared"}
                self.call("edit", asset=consumer, confirm=True)
                before = self.store.read()
                with self.assertRaisesRegex(ValueError, "只能删除无引用草稿"):
                    self.call("retire", asset_id=target_id, action="delete")
                with self.assertRaises(ValueError) as missing:
                    self.call("undo", target_revision=created["revision"])
                self.assertEqual(missing.exception.code, "INVALID_MODEL")
                self.assertIn(target_id, json.dumps(missing.exception.details))
                self.assertEqual(self.store.read(), before)
                result = self.call("retire", asset_id=target_id, reason="不再适用")["result"]
                self.assertIn(consumer_id, result["references"])

    def test_merge_rewrites_execution_references_and_invalidates_transitive_execution(self):
        source, _ = self.seed()
        vehicle = copy.deepcopy(next(a for a in self.service.state()["assets"] if a["id"] == "vehicle"))
        vehicle["id"], vehicle["name"] = "vehicle2", "运营车辆"
        self.call("edit", asset=vehicle, confirm=True)
        consumer = self.entity("consumer", "执行声明", source, "企业负责本企业车辆维护。")
        consumer["properties"]["execution"] = {"refs": ["vehicle2", "vehicle"], "data_refs": ["vehicle2", "vehicle"], "status": "verified"}
        self.call("edit", asset=consumer, confirm=True)
        downstream = self.entity("downstream", "后续声明", source, "企业负责本企业车辆维护。")
        downstream["properties"]["execution"] = {"refs": ["consumer"], "status": "verified"}
        self.call("edit", asset=downstream, confirm=True)
        # Model a previously verified execution receipt; authoring does not execute it.
        def existing_receipts(doc, db):
            for a in doc["model"]["semantic"]["assets"]:
                if a["id"] in {"consumer", "downstream"}:
                    a["properties"]["execution"]["status"] = "verified"
            return {"fixture": "existing_execution_receipts"}
        self.store.knowledge_change({"revision": self.store.read()["revision"], "operation_id": uuid.uuid4().hex},
                                    "测试预置已有执行回执", existing_receipts)
        self.call("merge", survivor_id="vehicle", merged_id="vehicle2", reason="核对同一对象")
        current = {a["id"]: a for a in self.service.state()["assets"]}
        execution = current["consumer"]["properties"]["execution"]
        self.assertEqual(execution["refs"], ["vehicle"])
        self.assertEqual(execution["data_refs"], ["vehicle"])
        self.assertEqual(execution["status"], "stale")
        self.assertEqual(current["downstream"]["properties"]["execution"]["status"], "stale")
        path, _ = self.package(asset_ids=["consumer"], include_execution=True)
        self.assertEqual(read_package(path).get("consumer")["asset"]["properties"]["execution"]["refs"], ["vehicle"])

    def test_proposal_detects_execution_dependency_change(self):
        source, _ = self.seed()
        batch = self.service.state()["batches"][0]["id"]
        candidate = self.entity("execution_candidate", "待核对声明", source, "企业负责本企业车辆维护。")
        candidate["properties"]["execution"] = {"refs": ["vehicle"]}
        group = self.propose(batch, [candidate])
        vehicle = copy.deepcopy(next(a for a in self.service.state()["assets"] if a["id"] == "vehicle"))
        vehicle["definition"] = "仅本企业营运车辆"
        self.call("edit", asset=vehicle, confirm=True)
        before = self.store.read()
        with self.assertRaisesRegex(Conflict, "依赖 vehicle 已改变"):
            self.call("review", group_id=group, action="accept")
        self.assertEqual(self.store.read(), before)

    def test_identity_publication_guard_uses_actual_dependency_closure(self):
        source, _ = self.seed()
        vehicle = copy.deepcopy(next(a for a in self.service.state()["assets"] if a["id"] == "vehicle"))
        vehicle["id"] = "vehicle2"
        self.call("edit", asset=vehicle, confirm=True)
        bundle = self.entity("bundle", "需要两个车辆定义", source, "企业负责本企业车辆维护。")
        bundle["refs"] = ["vehicle", "vehicle2"]
        self.call("edit", asset=bundle, confirm=True)
        before = self.store.read()
        with self.assertRaises(ValueError) as conflict:
            self.package(asset_ids=["bundle"])
        self.assertEqual(conflict.exception.code, "NOT_PUBLISHABLE")
        self.assertEqual(conflict.exception.details["issues"][0]["code"], "IDENTITY_REVIEW")
        self.assertEqual(set(conflict.exception.details["issues"][0]["asset_ids"]), {"vehicle", "vehicle2"})
        self.assertEqual(self.store.read(), before)
        self.package("unrelated.zip", asset_ids=["company"])
        self.package("one_meaning.zip", asset_ids=["vehicle"])
        bundle["id"], bundle["name"], bundle["refs"] = "execution_bundle", "附带执行声明", []
        bundle["properties"]["execution"] = {"refs": ["vehicle", "vehicle2"]}
        self.call("edit", asset=bundle, confirm=True)
        self.package("semantic_only.zip", asset_ids=["execution_bundle"])
        with self.assertRaises(ValueError):
            self.package(asset_ids=["execution_bundle"], include_execution=True)
        self.call("separate", left_id="vehicle", right_id="vehicle2", reason="验收中明确保留两种适用定义")
        self.package("separated.zip", asset_ids=["bundle"])

    def test_pending_proposal_does_not_automatically_block_confirmed_definition(self):
        source, _ = self.seed()
        batch = self.service.state()["batches"][0]["id"]
        candidate = self.entity("vehicle", "拟改定义", source, "企业负责本企业车辆维护。")
        group = self.propose(batch, [candidate])
        self.assertEqual(next(g for g in self.service.state()["groups"] if g["id"] == group)["status"], "pending")
        path, _ = self.package(asset_ids=["vehicle"])
        self.assertEqual(read_package(path).get("vehicle")["asset"]["name"], "营运车辆")

    def test_draft_identity_conflicts_are_export_only_and_reader_reports_incomplete(self):
        source, _ = self.seed()
        vehicle = copy.deepcopy(next(a for a in self.service.state()["assets"] if a["id"] == "vehicle"))
        vehicle["id"] = "vehicle2"
        self.call("edit", asset=vehicle, confirm=True)
        bundle = self.entity("bundle", "引用两个待分辨对象", source, "企业负责本企业车辆维护。")
        bundle["refs"] = ["vehicle", "vehicle2"]
        self.call("edit", asset=bundle, confirm=True)
        before = copy.deepcopy(self.store.read()["document"])
        path, result = self.package(asset_ids=["bundle"], draft=True)
        manifest = result["manifest"]
        self.assertTrue(manifest["draft"])
        self.assertFalse(manifest["complete"])
        self.assertEqual({x["asset_id"] for x in manifest["issues"] if x["code"] == "UNRESOLVED_CONFLICT"}, {"vehicle", "vehicle2"})
        reader = read_package(path)
        self.assertFalse(reader.verify()["complete"])
        definition = reader.get("vehicle")
        self.assertFalse(definition["complete"])
        conflict = definition["asset"]["properties"]["unresolved_conflicts"]["identity_review"][0]
        self.assertEqual(conflict["code"], "IDENTITY_REVIEW")
        self.assertEqual(set(conflict["asset_ids"]), {"vehicle", "vehicle2"})
        self.assertFalse(reader.search("营运车辆")["complete"])
        self.assertEqual(self.store.read()["document"], before)
        independent, result = self.package("independent_draft.zip", asset_ids=["company"], draft=True)
        self.assertTrue(result["manifest"]["complete"])
        self.assertNotIn("unresolved_conflicts", read_package(independent).get("company")["asset"]["properties"])

    def test_classification_cycle_rejected_but_business_cycle_allowed(self):
        source, _ = self.seed()
        base = self.entity("r1", "关系一", source, "企业负责本企业车辆维护。")
        a = {**base, "kind": "relation", "from": "company", "to": "vehicle", "predicate": "关联", "relation_type": "business"}
        b = {**a, "id": "r2", "name": "关系二", "from": "vehicle", "to": "company"}
        self.call("edit", asset=a, confirm=True)
        self.call("edit", asset=b, confirm=True)
        a["relation_type"] = "is_a"
        b["relation_type"] = "is_a"
        self.call("edit", asset=a, confirm=True)
        with self.assertRaisesRegex(ValueError, "分类关系形成环"):
            self.call("edit", asset=b, confirm=True)

    def test_context_added_exception_requires_review_even_if_original_quote_remains(self):
        source, _ = self.seed()
        changed = TEXT.replace("企业负责本企业车辆维护。", "企业负责本企业车辆维护。租赁车辆由承租人维护。")
        self.source(changed, source_id=source["id"])
        assets = {a["id"]: a for a in self.service.state()["assets"]}
        self.assertEqual(assets["maintain"]["status"], "needs_review")
        self.assertEqual(assets["vehicle"]["status"], "confirmed")

    def test_dependency_changes_require_new_proposal_not_silent_rebase(self):
        self.seed()
        _, source = self.source("补充核对规则。", filename="补充.txt")
        rule = copy.deepcopy(next(a for a in self.service.state()["assets"] if a["id"] == "maintain"))
        rule["name"] = "车辆维护责任"
        group = self.propose(source["batch_id"], [rule])
        vehicle = copy.deepcopy(next(a for a in self.service.state()["assets"] if a["id"] == "vehicle"))
        vehicle["definition"] = "仅指非出租的营运车辆"
        vehicle["evidence"].append({"type": "manual", "quote": "本用例限定非出租营运车辆", "actor": "local"})
        self.call("edit", asset=vehicle, confirm=True)
        with self.assertRaisesRegex(Conflict, "依赖"):
            self.call("review", group_id=group, action="accept")
        new = self.propose(source["batch_id"], [rule])
        self.assertNotEqual(group, new)
        old = next(g for g in self.service.state()["groups"] if g["id"] == group)
        self.assertEqual(old["superseded_by"], new)
        self.assertFalse(any(p.get("group_id") == group for p in self.service.state()["problems"]))
        with self.assertRaisesRegex(ValueError, "已由新组替代"):
            self.call("review", group_id=group, action="accept")
        self.call("review", group_id=new, action="accept")
        self.assertEqual(self.propose(source["batch_id"], [rule]), new)

    def test_invalid_ddl_reference_never_generates_confirmable_edge(self):
        _, result = self.source("CREATE TABLE parent(id INT); CREATE TABLE child(x INT, FOREIGN KEY(missing) REFERENCES parent(id));", "bad.sql")
        self.assertEqual(result["parsed"]["status"], "partial")
        group = self.service.state()["groups"][0]
        self.assertFalse(any(c["asset"].get("relation_type") == "physical_fk" for c in group["candidates"]))
        self.call("review", group_id=group["id"], action="accept")
        self.assertFalse(any(a.get("relation_type") == "physical_fk" for a in self.service.state()["assets"]))

    def test_reparse_preserves_original_revision_and_old_evidence(self):
        source, result = self.source("名称,定义\n车辆,营运车辆\n企业,负责维护\n", "词表.csv")
        original = source["revisions"][0]
        fragment = next(f for f in original["parsed"]["fragments"] if "营运车辆" in f["text"])
        a = {"id": "term", "kind": "term", "name": "车辆", "definition": "营运车辆", "domain": "交通", "scope": "合成",
             "evidence": [{"source_id": source["id"], "revision": 1, "extraction_id": original["current_extraction"],
                           "fragment_id": fragment["id"], "quote": fragment["text"]}]}
        self.call("edit", asset=a, confirm=True)
        self.source("名称,定义\n车辆,营运车辆\n企业,负责维护\n", "词表.csv", source_id=source["id"], options={"range": "A1:B2"})
        current = self.service.state()["sources"][0]
        self.assertEqual(current["current_revision"], 1)
        self.assertEqual(len(current["revisions"]), 1)
        self.assertEqual(len(current["revisions"][0]["extractions"]), 2)
        path, _ = self.package(asset_ids=["term"])
        self.assertIn(original["current_extraction"], json.dumps(read_package(path).sources("term"), ensure_ascii=False))
        ambiguous = copy.deepcopy(next(x for x in self.service.state()["assets"] if x["id"] == "term"))
        ambiguous["evidence"][0].pop("extraction_id")
        before = self.store.read()["revision"]
        with self.assertRaisesRegex(ValueError, "extraction_id"):
            self.call("edit", asset=ambiguous, confirm=True)
        self.assertEqual(self.store.read()["revision"], before)

    def test_structured_model_intake_creates_candidates_not_replaces(self):
        self.seed()
        data = {"assets": [{"id": "new-term", "kind": "term", "name": "新术语", "definition": "明确新定义", "domain": "交通", "scope": "合成"}]}
        _, result = self.source(json.dumps(data, ensure_ascii=False), "模型.json")
        group = next(g for g in self.service.state()["groups"] if g["batch_id"] == result["batch_id"])
        self.assertNotIn("new-term", [a["id"] for a in self.service.state()["assets"]])
        self.call("review", group_id=group["id"], action="accept")
        self.assertIn("vehicle", [a["id"] for a in self.service.state()["assets"]])
        self.assertIn("new-term", [a["id"] for a in self.service.state()["assets"]])


if __name__ == "__main__":
    unittest.main()
