"""Public host review/edit entry points retain transaction and operator boundaries."""
import json
from contextlib import closing
from pathlib import Path
import subprocess
import sqlite3
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class KnowledgeCliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="核对 CLI ")
        self.root = Path(self.temp.name)
        self.project = self.root / "项目"

    def tearDown(self):
        self.temp.cleanup()

    def run_cli(self, *args, code=0):
        p = subprocess.run([sys.executable, "-X", "utf8", str(ROOT / "scripts/knowledge.py"),
                            "--project", str(self.project), *args], cwd=self.root,
                           capture_output=True, encoding="utf-8")
        self.assertEqual(p.returncode, code, p.stdout + p.stderr)
        return json.loads(p.stdout)

    def write(self, name, data):
        path = self.root / name
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8-sig")
        return str(path)

    def proposal(self):
        path = self.root / "表结构.sql"
        path.write_text("CREATE TABLE plant (id INTEGER PRIMARY KEY, moisture REAL);", encoding="utf-8")
        self.run_cli("import", "--file", str(path), "--domain", "植物", "--scope", "H1")
        state = self.run_cli("state")["result"]
        self.assertEqual(state["assets"], [])
        return state["groups"][0]["id"]

    def test_superseded_cli_edits_never_remove_another_edit(self):
        f = self.write("item.json", {"id":"x","kind":"entity","name":"Before"})
        self.run_cli("edit", "--file", f)
        base = self.run_cli("state")["result"]
        a = base["assets"][0]
        a["aliases"] = ["new alias"]
        self.run_cli("--revision", str(base["revision"]), "edit", "--file", self.write("a.json", a))
        for options in ([], ["--revision", str(base["revision"])]):
            self.assertEqual(self.run_cli(*options, "edit", "--file", f, code=2)["status"], "conflict")
        self.assertEqual(self.run_cli("state")["result"]["assets"][0]["aliases"], ["new alias"])

    def test_material_task_pages_selects_and_reads_a_dependency_closed_slice(self):
        ddl = self.root / "schema.sql"
        ddl.write_text("\n".join(f"CREATE TABLE t{i:03}(id INT, code TEXT, label TEXT, num INT);" for i in range(80)), encoding="utf8")
        self.run_cli("import", "--file", str(ddl), "--seed-draft")
        note = self.root / "note.txt"
        note.write_text("Which table contains this field?", encoding="utf8")
        batch = self.run_cli("import", "--file", str(note))["result"]["result"]["batch_id"]
        def prepare(*flags):
            return self.run_cli("task", "--batch", batch, *flags)["result"]["result"]
        first = prepare("--limit", "3")
        ctx = first["asset_context"]
        self.assertEqual((first["assets"], ctx["omitted_count"], ctx["next_offset"]), ([], 400, 3))
        second = prepare("--limit", "3", "--offset", "3")["asset_context"]
        self.assertFalse({a["id"] for a in ctx["candidates"]} & {a["id"] for a in second["candidates"]})
        search = prepare("--question", "t018")
        table = next(a for a in search["asset_context"]["candidates"] if a["name"] == "t018")
        self.assertEqual(table["evidence"][0]["source_name"], "schema.sql")
        picked = prepare("--id", table["id"])
        self.assertEqual([a["id"] for a in picked["assets"]], [table["id"]])
        self.assertEqual(picked["asset_context"]["omitted_count"], 399)
        inventory = prepare("--all-assets")["assets"]
        self.assertEqual(len(inventory), 400)
        field = next(a for a in inventory if a["kind"] == "field" and table["id"] in a["refs"])
        self.assertEqual({a["id"] for a in prepare("--id", field["id"])["assets"]}, {field["id"], table["id"]})
        self.assertEqual(prepare("--id", "unknown")["asset_context"]["status"], "needs_selection")
        unknown = prepare("--question", "无此业务")
        self.assertEqual((unknown["assets"], unknown["asset_context"]["status"]), ([], "no_match"))

    def test_cross_scope_comparison_discovery_and_declared_validity(self):
        def register(name, content, scope, *options):
            path = self.root / name
            path.write_text(content, encoding="utf8")
            return self.run_cli("import", "--file", str(path), "--scope", scope, *options)["result"]["result"]
        origin = register("通用说明A.txt", "企业应登记隐患整改结果。", "全国", "--effective-from", "2025-01-01")
        thematic = register("其他地区细则.txt", "完成隐患整改须记录复核人和整改结果。", "乙地区")
        unrelated = register("车辆维护.txt", "甲地区的车辆每月更换润滑油。", "甲地区")
        body = "甲地区依据《通用说明A》，须登记隐患整改结果，并将复核凭证关联同一隐患。"
        local = register("甲地区细则.txt", body, "甲地区")
        def prepare(*extra):
            return self.run_cli("task", "--batch", local["batch_id"], *extra)["result"]["result"]
        task = prepare()
        ranked = task["related_sources"]
        self.assertEqual([s["id"] for s in ranked], [origin["source_id"], thematic["source_id"]])
        self.assertEqual(ranked[0]["effective_from"], "2025-01-01")
        self.assertIsNone(ranked[0]["effective_to"])
        reason = ranked[0]["reasons"][0]
        self.assertEqual(reason["kind"], "explicit_reference")
        for side, source_id in (("primary", local["source_id"]), ("counterpart", origin["source_id"])):
            anchor = reason[side]
            self.assertEqual((anchor["source_id"], anchor["revision"]), (source_id, 1))
            self.assertIn("line_start", anchor["location"])
            self.assertTrue(anchor["quote"])
        self.assertEqual(ranked[1]["reasons"][0]["kind"], "shared_passage_terms")
        self.assertEqual(prepare("--compare-source", unrelated["source_id"])["materials"][1]["role"], "comparison")
        self.assertEqual(task["comparison_review"]["status"], "awaiting_judgment")
        revised = register("通用说明A.txt", "企业应登记隐患整改结果。", "全国", "--source-id", origin["source_id"],
                           "--effective-from", "2026-01-01")
        self.assertEqual(revised["source_id"], origin["source_id"])
        updated = prepare()["related_sources"][0]
        self.assertEqual((updated["revision"], updated["effective_from"]), (2, "2026-01-01"))

    def test_material_discovery_discloses_unread_fragments_and_full_comparison_still_reads_them(self):
        target = self.root / "标准.txt"
        target.write_text("编制年度维保计划。", encoding="utf8")
        target_id = self.run_cli("import", "--file", str(target))["result"]["result"]["source_id"]
        material = self.root / "附件.txt"
        material.write_text("\n\n".join([f"序号{i}的图册。" for i in range(300)] + ["见《标准》。"]), encoding="utf8")
        imported = self.run_cli("import", "--file", str(material))["result"]["result"]
        prep = self.run_cli("task", "--batch", imported["batch_id"])["result"]["result"]
        self.assertEqual(prep["related_sources"], [])
        self.assertEqual(prep["source_discovery"]["truncated_source_count"], 1)
        self.assertEqual(prep["source_discovery"]["full_text_option"], "--compare-source")
        selected = self.run_cli("task", "--batch", imported["batch_id"], "--compare-source", target_id)["result"]["result"]
        self.assertEqual(selected["materials"][0]["parsed"]["fragments"][-1]["text"], "见《标准》。")
        self.assertEqual(selected["materials"][1]["parsed"]["fragments"][0]["text"], "编制年度维保计划。")

    def test_inspecting_wrong_project_creates_no_database(self):
        self.assertEqual(self.run_cli("inspect", code=2)["status"], "project_not_found")
        self.assertFalse(self.project.exists())

    def test_independent_grain_guards_atomic_batch(self):
        metric = {"id":"m","kind":"metric","name":"Closed hazards","properties":{"grain":"work order"}}
        source = self.write("scope.json",[{"id":"x","kind":"entity","name":"Hazard"}, metric])
        failed = self.run_cli("edit","--file",source,"--expect-grain","hazard","--confirm",code=2)
        self.assertEqual(failed["details"]["code"],"GRAIN_MISMATCH")
        self.assertEqual(self.run_cli("state")["result"]["assets"],[])
        accepted = self.run_cli("edit","--file",source,"--expect-grain","Work  Order")
        self.assertEqual(accepted["result"]["result"]["grain_check"]["actual"],"work order")

    def test_graph_image_reopens_original_revision_without_live_editor(self):
        from xml.etree import ElementTree
        self.run_cli("graph-image", "--out", str(self.root / "none.svg"), code=2)
        self.assertFalse(self.project.exists())
        a = {"id":"unit", "kind":"entity", "name":"Enterprise & A"}
        b = {"id":"case", "kind":"entity", "name":"Case H1"}
        edge = {"id":"owns", "kind":"relation", "name":"Owner", "from":"unit", "to":"case",
                "relation_type":"business", "predicate":"Owner", "evidence":[{"type":"manual","actor":"tester","quote":"Assigned in area A"}]}
        initial = self.run_cli("edit", "--file", self.write("three.json", [a, b, edge]))["result"]
        revision = str(initial["revision"])
        self.assertEqual(initial["result"]["guidance"]["focus_id"], "owns")
        self.assertIn("graph-image", initial["result"]["guidance"]["preview"]["image_argv_prefix"])
        edge["predicate"] = "Later label"
        self.run_cli("--revision", revision, "edit", "--file", self.write("change.json", edge))
        image = self.root / "graph.svg"
        receipt = self.run_cli("--revision", revision, "graph-image", "--id", "owns", "--out", str(image))["result"]
        self.assertEqual((receipt["shown"], receipt["total_connections"]), (1, 1))
        original = image.read_bytes()
        tree = ElementTree.fromstring(original)
        self.assertEqual({node.get("data-asset-id") for node in tree.iter() if "data-asset-id" in node.attrib}, {"unit", "case"})
        self.assertIn("Enterprise & A", "".join(tree.itertext()))
        self.assertIn("Assigned in area A", "".join(tree.itertext()))
        self.assertNotIn("Later label", "".join(tree.itertext()))
        self.run_cli("graph-image", "--id", "owns", "--out", str(image), code=2)
        self.assertEqual(image.read_bytes(), original)

    def test_repeatable_ddl_ids_and_independent_source_keys(self):
        ddl = self.root / 'base.sql'
        ddl.write_text('CREATE TABLE plant(id INTEGER PRIMARY KEY); CREATE TABLE note(plant_id INT REFERENCES plant(id));', encoding='utf8')
        def seed(project, path, *flags):
            self.project = self.root / project
            self.run_cli('import', '--file', str(path), '--seed-draft', *flags)
            return {a['name']: a['id'] for a in self.run_cli('state')['result']['assets']}
        first = seed('one', ddl)
        renamed = self.root / 'copy.sql'
        renamed.write_bytes(ddl.read_bytes())
        self.assertEqual(first, seed('two', renamed))
        self.assertNotEqual(first['plant'], seed('three', ddl, '--distinct-source')['plant'])
        original = seed('four', ddl, '--source-key', 'fleet/prod')
        ddl.write_text(ddl.read_text(encoding='utf8') + ' CREATE TABLE extra(id INT);', encoding='utf8')
        updated = seed('five', ddl, '--source-key', 'fleet/prod')
        self.assertEqual(original, {k: updated[k] for k in original})
        self.assertNotEqual(updated['plant'], seed('six', ddl, '--source-key', 'fleet/test')['plant'])

    def test_bulk_retire_is_atomic_revision_guarded_and_replayable(self):
        for key in ('a', 'b'):
            self.run_cli('edit', '--file', self.write(key+'.json', {'id':key,'kind':'entity','name':key}))
        base = self.run_cli('state')['result']['revision']
        self.run_cli('retire', '--id', 'a', '--reason', 'duplicate', code=2)
        self.run_cli('--revision', str(base-1), 'retire', '--id', 'a', '--reason', 'old', code=2)
        self.run_cli('--revision', str(base), 'retire', '--id', 'a', '--id', 'missing', '--reason', 'wrong', code=2)
        self.assertEqual(base, self.run_cli('state')['result']['revision'])
        args = ['--revision',str(base),'--operation-id','bulk1','retire','--file',self.write('ids.json',['a','b']),'--reason','duplicate']
        reply = self.run_cli(*args)
        self.assertEqual(reply, self.run_cli(*args))
        self.assertEqual(reply['result']['result']['changed'], ['a','b'])
        self.assertTrue(all(a['status']=='retired' and a['retire_reason']=='duplicate' for a in self.run_cli('state')['result']['assets']))

    def test_rejected_import_leaves_no_new_attachment(self):
        path = self.root / 'schema.sql'
        path.write_text('CREATE TABLE plant(id INT);', encoding='utf8')
        self.run_cli('import', '--file', str(path), '--seed-draft')
        path.write_text('CREATE TABLE other(id INT);', encoding='utf8')
        self.run_cli('import', '--file', str(path), code=2)
        self.run_cli('--revision','0','import','--file',str(path),code=2)
        with closing(sqlite3.connect(self.project / 'project.sqlite')) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM attachments').fetchone()[0], 1)

    def test_large_receipts_keep_evidence_without_repeating_project_inventory(self):
        ddl = self.root/"large.sql"
        ddl.write_text("\n".join(f"DROP TABLE IF EXISTS t{i}; CREATE TABLE t{i}(id INTEGER PRIMARY KEY);" for i in range(62)),encoding="utf8")
        seed = self.run_cli("import","--file",str(ddl),"--seed-draft")["result"]["result"]
        self.assertEqual(seed["seeded"]["asset_id_count"],124)
        self.assertTrue(seed["warnings_truncated"])
        package = self.root/"large.zip"
        receipt=self.run_cli("export","--draft","--out",str(package))["result"]["result"]["manifest"]
        self.assertEqual(receipt["scope"]["id_counts"]["included_ids"],124)
        def read(*args):
            return json.loads(subprocess.check_output([sys.executable,"-X","utf8",str(ROOT/"scripts/semantic_read.py"),"--package",str(package),*args],encoding="utf8"))
        brief,full=read("verify"),read("--full-scope","verify")
        self.assertEqual(brief["issue_count"],len(full["issues"]))
        aid=full["scope"]["package"]["included_ids"][0]
        small,large=(read(*flags,"sources","--id",aid)["evidence"][0] for flags in ([],["--full-scope"]))
        self.assertEqual((small["assertion"],small["fragment"]),(large["assertion"],large["fragment"]))
        self.assertEqual(small["parse"]["warning_count"],len(large["parse"]["warnings"]))
        self.assertLess(len(small["parse"]["warnings"]),small["parse"]["warning_count"])

    def test_review_requires_explicit_decision_and_preserves_receipt_and_conflict(self):
        group = self.proposal()
        self.run_cli("review", "--group", group, "--action", "accept", "--reason", " ", code=2)
        self.assertEqual(self.run_cli("state")["result"]["assets"], [])
        stale_revision = self.run_cli("state")["result"]["revision"]
        args = ("--operation-id", "test-review", "review", "--group", group, "--action", "accept", "--reason", "Authorized synthetic operator")
        first = self.run_cli(*args)
        replay = self.run_cli(*args)
        self.assertEqual(first["result"], replay["result"])
        self.assertTrue(all(a["status"] == "confirmed" for a in self.run_cli("state")["result"]["assets"]))
        asset = self.run_cli("state")["result"]["assets"][0]
        asset["definition"] = "Changed without fresh revision"
        fail = self.run_cli("--revision", str(stale_revision), "edit", "--file", self.write("变更.json", asset), "--confirm", code=2)
        self.assertEqual(fail["status"], "conflict")
        self.assertNotEqual(self.run_cli("state")["result"]["assets"][0]["definition"], asset["definition"])

    def test_rejection_cannot_be_silently_reaccepted(self):
        group = self.proposal()
        self.run_cli("review", "--group", group, "--action", "reject", "--reason", "Incorrect scope")
        self.run_cli("review", "--group", group, "--action", "accept", "--reason", "Retry", code=2)
        self.assertEqual(self.run_cli("state")["result"]["assets"], [])

    def test_conflict_clearance_requires_a_recorded_operator_decision(self):
        claims = {"claims": [{"claim": "Count once per case"}, {"claim": "Count once per reply"}]}
        item = {"id": "complaint", "kind": "term", "name": "Complaint count", "definition": "One per case",
                "domain": "Transport", "scope": "Area A", "properties": {"unresolved_conflicts": claims},
                "evidence": [{"type": "manual", "actor": "reviewer", "quote": "Two counting rules exist."}]}
        initial = self.run_cli("edit", "--file", self.write("item.json", item))["result"]
        self.assertEqual(initial["result"]["guidance"]["attention"]["kind"], "conflicting_sources")
        image = self.root / "conflict.svg"
        self.run_cli("graph-image", "--id", "complaint", "--out", str(image))
        for words in ("Unresolved source claims", "Count once per case", "Count once per reply"):
            self.assertIn(words, image.read_text(encoding="utf-8"))
        rev = str(initial["revision"])
        def save(code=0, confirm=True):
            return self.run_cli("--revision", rev, "edit", "--file", self.write("item.json", item),
                                *(["--confirm"] if confirm else []), code=code)
        self.assertIn("competing claims", save(2)["error"])
        del item["properties"]["unresolved_conflicts"]
        self.assertIn("operator decision", save(2, confirm=False)["error"])
        decision = "For Area A, count distinct cases including all their replies."
        item["properties"]["conflict_resolutions"] = [{"previous": claims, "decision": decision}]
        self.assertIn("operator decision", save(2)["error"])
        item["evidence"].append({"type": "manual", "actor": "Area A data owner", "quote": decision})
        rev = str(save()["result"]["revision"])
        del item["properties"]["conflict_resolutions"]
        save()
        saved = self.run_cli("state")["result"]["assets"][0]
        self.assertEqual(saved["properties"]["conflict_resolutions"][0]["previous"], claims)
        self.assertEqual(saved["status"], "confirmed")

    def test_inference_is_disclosed_in_draft_and_requires_a_concrete_observation(self):
        item = {"id": "assignment", "kind": "term", "name": "Assignment", "definition": "Current assignee",
                "domain": "Campus", "scope": "Lab A", "properties": {"assertion_basis": "model_inferred"}}
        path = self.write("inference.json", item)
        initial = self.run_cli("edit", "--file", path)["result"]
        guidance = initial["result"]["guidance"]
        self.assertEqual(guidance["attention"]["kind"], "confirm_inference")
        self.assertEqual(guidance["focus_id"], item["id"])
        rev = str(initial["revision"])
        self.assertIn("operator observation", self.run_cli("--revision", rev, "edit", "--file", path, "--confirm", code=2)["error"])
        item["evidence"] = [{"type": "manual", "actor": "Lab A director", "quote": "Assignment names the current custodian in Lab A."}]
        self.run_cli("--revision", rev, "edit", "--file", self.write("inference.json", item), "--confirm")

    def test_edit_is_draft_by_default_and_confirmation_is_validated(self):
        asset = {"id": "r", "kind": "rule", "name": "人工确认", "definition": "温室 H1 须人工核对",
                 "domain": "植物", "scope": "H1", "properties": {"conditions": "H1", "requirements": "核对"},
                 "evidence": [{"type": "manual", "quote": "温室 H1 须人工核对", "actor": "synthetic operator"}]}
        file = self.write("规则.json", asset)
        self.run_cli("edit", "--file", file)
        self.assertEqual(self.run_cli("state")["result"]["assets"][0]["status"], "draft")
        self.run_cli("edit", "--file", file, "--confirm", code=2)
        self.assertEqual(self.run_cli("state")["result"]["assets"][0]["status"], "draft")
        asset["properties"] = {"condition": "H1", "requirement": "人工核对"}
        revision = self.run_cli("state")["result"]["revision"]
        self.run_cli("--revision", str(revision), "edit", "--file", self.write("规则.json", asset), "--confirm")
        self.assertEqual(self.run_cli("state")["result"]["assets"][0]["status"], "confirmed")

    def test_short_structure_flow_exports_physical_drafts_without_server_or_question(self):
        from workbench.semantic_package import read_package
        path = self.root / "结构.sql"
        path.write_text("CREATE TABLE plant(id INTEGER PRIMARY KEY); CREATE TABLE care(id INTEGER PRIMARY KEY, plant_id INTEGER REFERENCES plant(id));", encoding="utf-8")
        first = self.run_cli("--operation-id", "seed", "import", "--file", str(path), "--seed-draft")
        self.assertEqual(first, self.run_cli("--operation-id", "seed", "import", "--file", str(path), "--seed-draft"))
        self.assertEqual(first["result"]["result"]["seeded"]["counts"], {"dataset": 2, "field": 3, "relation": 1})
        state = self.run_cli("state")["result"]
        self.assertEqual(len(state["assets"]), 6)
        self.assertTrue(all(a["status"] == "draft" and a["evidence"] and "confirmed_by" not in a for a in state["assets"]))
        edited = state["assets"][0]
        edited["definition"] = "Manually refined physical definition"
        self.run_cli("--revision", str(state["revision"]), "edit", "--file", self.write("edit.json", edited))
        self.run_cli("review", "--group", state["groups"][0]["id"], "--action", "accept", "--reason", "Cannot overwrite editing", code=2)
        current = self.run_cli("state")["result"]
        self.run_cli("import", "--file", str(path), "--seed-draft", code=2)
        self.assertEqual(self.run_cli("state")["result"]["revision"], current["revision"])
        out = self.root / "model.zip"
        self.run_cli("export", "--out", str(out), code=2)
        self.assertFalse(out.exists())
        self.run_cli("export", "--out", str(out), "--draft")
        package = read_package(out)
        self.assertEqual(len(package.index), 6)
        self.assertTrue(package.manifest["draft"])
        before = out.read_bytes()
        self.run_cli("export", "--out", str(out), "--draft", code=2)
        self.assertEqual(out.read_bytes(), before)

    def test_seed_draft_rejects_nonstructural_material_and_empty_export(self):
        path = self.root / "说明.md"
        path.write_text("A document is not a table declaration.", encoding="utf-8")
        self.run_cli("import", "--file", str(path), "--seed-draft", code=2)
        state = self.run_cli("state")["result"]
        self.assertEqual(state["assets"], [])
        self.assertEqual(state["sources"], [])
        self.run_cli("export", "--out", str(self.root / "empty.zip"), "--draft", code=2)

    def test_seed_draft_does_not_report_success_for_already_imported_candidates(self):
        self.proposal()
        before = self.run_cli("state")["result"]
        self.run_cli("import", "--file", str(self.root / "表结构.sql"), "--seed-draft", code=2)
        after = self.run_cli("state")["result"]
        self.assertEqual(after["assets"], [])
        self.assertEqual(after["revision"], before["revision"])


if __name__ == "__main__":
    unittest.main()
