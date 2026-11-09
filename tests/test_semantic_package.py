import copy
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from workbench.semantic_package import PackageError, build_package, package_preview, read_package, validate_semantic_assets


def asset(aid, kind="term", name=None, **changes):
    properties = {"rule": {"condition": "存在本企业车辆", "requirement": "执行声明的维护要求"},
                  "field": {"value_type": "string"}, "attribute": {"value_type": "string"},
                  "metric": {"unit": "辆", "grain": "企业", "inclusions": "异常标记有效", "exclusions": "无异常标记", "time_scope": "当前"}}.get(kind, {})
    properties.update(changes.pop("properties", {}))
    value = {"id": aid, "kind": kind, "name": name or aid, "definition": "明确的业务定义：" + aid,
             "domain": "交通", "scope": "本地演示范围", "aliases": [], "status": "confirmed",
             "properties": properties, "refs": [], "evidence": [{"type": "manual", "quote": "操作者明确输入",
                 "actor": "reviewer", "created": "2026-11-09T00:00:00Z"}], "effective_from": None, "effective_to": None}
    value.update(changes)
    return value


def fixture():
    sources = [{"id": "src_policy", "name": "维护制度", "format": "txt", "domain": "交通", "current_revision": 2,
                "private": "do not export", "revisions": [
        {"revision": 1, "sha256": "a" * 64, "attachment_id": "private_attachment", "created": "2026-01-01",
         "parsed": {"format": "txt", "status": "complete", "fragments": [
             {"id": "p1", "location": {"line_start": 1, "line_end": 1}, "text": "企业负责本企业车辆维护。"},
             {"id": "p2", "location": {"line_start": 2}, "text": "PRIVATE_UNRELATED_CONTENT"}]}},
        {"revision": 2, "sha256": "b" * 64, "created": "2026-02-01", "parsed": {"format": "txt", "status": "complete", "fragments": [
             {"id": "p1", "location": {"line_start": 1}, "text": "企业负责维护并保存维护记录。"}]}}]}]
    assets = [asset("vehicle", "entity", "营运车辆", aliases=["营运车"]), asset("company", "entity", "企业"),
              asset("maintains", "relation", "企业维护车辆", **{"from": "company", "to": "vehicle", "predicate": "维护", "relation_type": "business"}),
              asset("rule", "rule", "车辆维护要求", refs=["vehicle", "company"],
                    evidence=[{"source_id": "src_policy", "revision": 1, "fragment_id": "p1", "quote": "企业负责本企业车辆维护。"}]),
              asset("revenue_sales", name="收入", domain="销售", scope={"basis": "已支付订单"}),
              asset("revenue_finance", name="收入", domain="财务", scope={"basis": "已确认收入"})]
    return assets, sources


class PackageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="semantic package 中文 ")
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)

    def write_package(self, assets=None, sources=None, filename="知识 快照.zip", **kwargs):
        if assets is None:
            assets, sources = fixture()
        content, manifest = build_package(assets, sources or [], project_id="review", revision=7, **kwargs)
        path = self.directory / filename
        path.write_bytes(content)
        return read_package(path), path, manifest

    def assert_code(self, code, fn):
        with self.assertRaises(PackageError) as caught:
            fn()
        self.assertEqual(caught.exception.code, code)
        return caught.exception

    def test_full_package_is_offline_and_keeps_rule_direction_and_exact_source_revision(self):
        package, path, manifest = self.write_package()
        self.assertEqual(package.verify()["status"], "verified")
        self.assertEqual(package.get("maintains")["asset"]["from"], "company")
        self.assertEqual(package.get("maintains")["asset"]["predicate"], "维护")
        evidence = package.sources("rule")["evidence"][0]
        self.assertEqual(evidence["assertion"]["revision"], 1)
        self.assertEqual(evidence["fragment"]["text"], "企业负责本企业车辆维护。")
        self.assertEqual(evidence["fragment"]["location"]["line_start"], 1)
        with zipfile.ZipFile(path) as z:
            self.assertEqual(set(z.namelist()), {"model.json", "sources.json", "manifest.json", "README.md", "human-review.html"})
            source_text = z.read("sources.json").decode()
            self.assertNotIn("PRIVATE_UNRELATED_CONTENT", source_text)
            self.assertNotIn("private_attachment", source_text)
            self.assertNotIn('"revision":2', source_text)
            extracted = self.directory / "解包后"
            z.extractall(extracted)
        self.assertEqual(read_package(extracted).get("rule"), package.get("rule"))
        self.assertEqual(manifest["source_revision"], 7)
        self.assertEqual(manifest["is_latest"], "unknown_offline")

    def test_terms_publish_without_database_or_metric(self):
        package, _, _ = self.write_package([asset("t", name="管理职责")], [])
        self.assertEqual(package.search("管理职责")["matches"][0]["asset"]["id"], "t")
        self.assertTrue(package.verify()["complete"])

    def test_source_warnings_and_coverage_survive_projection_and_subgraph_export(self):
        values, sources = fixture()
        version = sources[0]["revisions"][0]
        old_parse = copy.deepcopy(version["parsed"])
        old_parse.update(status="partial", warnings=["第 2 页为扫描图片，未提取文字。", {"code": "LIMIT", "message": "仅处理指定范围"}],
                         coverage={"pages": [1], "total_pages": 2})
        new_parse = copy.deepcopy(version["parsed"])
        new_parse["warnings"] = ["新提取警告，不应替换旧依据的警告"]
        version.update(parsed=new_parse, current_extraction="new",
                       extractions=[{"id": "old", "parsed": old_parse}, {"id": "new", "parsed": new_parse}])
        values[3]["evidence"][0]["extraction_id"] = "old"
        package, path, manifest = self.write_package(values, sources, asset_ids=["rule"])
        evidence = package.sources("rule")["evidence"][0]
        self.assertEqual(evidence["status"], "available")
        self.assertEqual(evidence["parse"]["status"], "partial")
        self.assertEqual(evidence["parse"]["warnings"], old_parse["warnings"])
        self.assertEqual(evidence["parse"]["coverage"], "selected_evidence_fragments")
        self.assertEqual(evidence["parse"]["source_coverage"], old_parse["coverage"])
        self.assertTrue(manifest["complete"])  # Complete confirmed definitions, not a claim about every source page.
        with zipfile.ZipFile(path) as archive:
            self.assertIn("第 2 页为扫描图片", archive.read("human-review.html").decode())
        child, _ = package.export(["rule"])
        child_path = self.directory / "子图.zip"
        child_path.write_bytes(child)
        self.assertEqual(read_package(child_path).sources("rule")["evidence"][0]["parse"], evidence["parse"])

    def test_same_name_ambiguity_is_not_hidden_by_page_size_and_can_be_scoped(self):
        package, _, _ = self.write_package()
        result = package.search("收入", limit=1)
        self.assertEqual(result["status"], "ambiguous")
        self.assertEqual(result["total"], 2)
        self.assertTrue(result["truncated"])
        self.assertFalse(result["complete"])
        self.assertEqual(result["next_offset"], 1)
        scoped = package.search("收入", domain="财务")
        self.assertEqual(scoped["status"], "ok")
        self.assertEqual(scoped["matches"][0]["asset"]["id"], "revenue_finance")
        self.assertEqual(package.search("收入", scope={"basis": "已支付订单"})["matches"][0]["asset"]["id"], "revenue_sales")
        self.assertEqual(package.search("营运车")["matches"][0]["match_reason"], "name_or_alias_exact")
        self.assertEqual(package.search("报废补贴")["status"], "not_found")

    def test_business_date_does_not_default_today_or_hide_unknown_time(self):
        values = [asset("old", name="口径", effective_from="2025-01-01", effective_to="2025-12-31"),
                  asset("new", name="口径", effective_from="2026-01-01", effective_to="2026-12-31"),
                  asset("unknown", name="口径"), asset("open", name="口径", effective_from="2026-01-01")]
        package, _, _ = self.write_package(values, [])
        self.assertEqual(package.search("口径")["total"], 4)
        result = package.search("口径", as_of="2026-06-01")
        found = {r["asset"]["id"]: r["applicability"] for r in result["matches"]}
        self.assertEqual(found, {"new": "within_declared_interval", "unknown": "unknown", "open": "unknown"})
        self.assertEqual(result["status"], "ambiguous")
        self.assertEqual(package.get("old", as_of="2026-06-01")["applicability"], "outside_known_interval")
        self.assert_code("INVALID_INPUT", lambda: package.search("口径", as_of="2026-02-30"))

    def test_required_dependencies_close_without_expanding_optional_neighbors(self):
        package, _, _ = self.write_package()
        content, manifest = package.export(["rule"])
        target = self.directory / "子图.zip"
        target.write_bytes(content)
        child = read_package(target)
        self.assertEqual(set(child.index), {"rule", "vehicle", "company"})
        self.assertEqual(set(manifest["scope"]["dependency_ids"]), {"vehicle", "company"})
        self.assertNotIn("maintains", child.index)
        self.assertTrue(child.verify()["complete"])

    def test_physical_required_dependency_is_included_and_execution_is_optional(self):
        values = [asset("rule", "rule", refs=["field"], properties={"execution": {"sql": "SELECT private_value FROM data", "data_refs": ["executor"]}}),
                  asset("field", "field", refs=["table"]), asset("table", "dataset"), asset("executor", "dataset")]
        package, _, manifest = self.write_package(values, [])
        self.assertEqual(set(package.index), {"rule", "field", "table"})
        self.assertNotIn("execution", package.get("rule")["asset"]["properties"])
        self.assertEqual(manifest["scope"]["omitted_execution_ids"], ["rule"])
        self.assert_code("CONTENT_NOT_AVAILABLE", lambda: package.export(["rule"], include_execution=True))
        extended, _, _ = self.write_package(values, [], filename="执行定义.zip", include_execution=True)
        self.assertIn("executor", extended.index)
        self.assertIn("execution", extended.get("rule")["asset"]["properties"])
        direct, _, _ = self.write_package(values, [], filename="选字段.zip", asset_ids=["field"])
        self.assertEqual(set(direct.index), {"field", "table"})

    def test_relation_selection_includes_ends_and_reverse_is_only_a_traversal(self):
        package, _, _ = self.write_package()
        forward = package.neighbors("company", direction="out")
        self.assertEqual(forward["edges"][0]["asset"]["id"], "maintains")
        reverse = package.neighbors("vehicle", direction="in")
        self.assertEqual(reverse["edges"][0]["traversed"], ["reverse"])
        self.assertEqual(reverse["edges"][0]["asset"]["predicate"], "维护")
        self.assertEqual(reverse["edges"][0]["asset"]["from"], "company")
        self.assertEqual(package.neighbors("vehicle", direction="out")["edges"], [])
        content, _ = package.export(["maintains"])
        path = self.directory / "关系.zip"; path.write_bytes(content)
        self.assertEqual(set(read_package(path).index), {"company", "vehicle", "maintains"})

    def test_neighbor_pagination_never_claims_complete(self):
        values = [asset("a", "entity"), asset("b", "entity"), asset("c", "entity")]
        for aid, to in (("ab", "b"), ("ac", "c")):
            values.append(asset(aid, "relation", **{"from": "a", "to": to, "predicate": "监管", "relation_type": "business"}))
        package, _, _ = self.write_package(values, [])
        result = package.neighbors("a", limit=1)
        self.assertEqual(result["total"], 2)
        self.assertTrue(result["truncated"])
        self.assertFalse(result["complete"])
        self.assertEqual(result["next_offset"], 1)
        self.assertEqual(package.neighbors("a", relation_types=["physical_fk"])["edges"], [])

    def test_missing_refs_unconfirmed_states_and_invalid_evidence_block_only_selected_scope(self):
        values, sources = fixture()
        values += [asset("bad", "rule", refs=["undefined"])]
        error = self.assert_code("NOT_PUBLISHABLE", lambda: build_package(values, sources, project_id="x", revision=1))
        self.assertIn("MISSING_DEPENDENCY", {x["code"] for x in error.details["issues"]})
        good, _, _ = self.write_package(values, sources, asset_ids=["vehicle"])
        self.assertEqual(set(good.index), {"vehicle"})
        for state in ("needs_review", "retired", "draft"):
            self.assert_code("NOT_PUBLISHABLE", lambda: build_package([asset("state", status=state)], [], project_id="x", revision=1))
        values[3]["evidence"][0]["quote"] = "不在原文中的编造依据"
        self.assert_code("NOT_PUBLISHABLE", lambda: build_package(values[:4], sources, project_id="x", revision=1))

    def test_draft_preserves_missing_content_and_reports_incomplete(self):
        value = asset("draft", "rule", refs=["missing"], evidence=[], status="draft", definition="")
        package, _, manifest = self.write_package([value], [], draft=True)
        self.assertFalse(manifest["complete"])
        self.assertFalse(package.verify()["complete"])
        self.assertEqual(package.sources("draft")["status"], "incomplete")
        incomplete_relation = asset("edge", "relation", status="draft", definition="")
        draft, _, _ = self.write_package([incomplete_relation], [], draft=True, filename="关系草稿.zip")
        self.assertFalse(draft.verify()["complete"])
        self.assert_code("NOT_PUBLISHABLE", lambda: draft.export(["edge"], draft=False))

    def test_redirect_is_explicit_and_cycles_or_unknown_ids_are_errors(self):
        package, _, _ = self.write_package([asset("new", name="新名称")], [], redirects={"old": "new"})
        self.assertEqual(package.get("old")["redirected_from"], "old")
        self.assertEqual(package.get("old")["asset"]["id"], "new")
        self.assert_code("UNKNOWN_ID", lambda: package.get("新名称"))
        self.assert_code("INVALID_MODEL", lambda: build_package([asset("new")], [], project_id="x", revision=1, redirects={"a": "b", "b": "a"}))

    def test_fixed_bytes_survive_working_model_changes_and_are_reproducible(self):
        values, sources = fixture()
        first, manifest = build_package(values, sources, project_id="x", revision=1)
        repeated, same = build_package(values, sources, project_id="x", revision=1)
        self.assertEqual(first, repeated)
        values[0]["definition"] = "最新修改"
        second, revised = build_package(values, sources, project_id="x", revision=2)
        self.assertNotEqual(manifest["snapshot_id"], revised["snapshot_id"])
        old = self.directory / "S1.zip"; old.write_bytes(first)
        new = self.directory / "S2.zip"; new.write_bytes(second)
        self.assertNotEqual(read_package(old).get("vehicle")["asset"]["definition"], read_package(new).get("vehicle")["asset"]["definition"])

    def test_hash_tamper_unknown_format_and_extra_files_are_rejected(self):
        _, path, _ = self.write_package()
        with zipfile.ZipFile(path) as z:
            entries = {name: z.read(name) for name in z.namelist()}
        entries["model.json"] = entries["model.json"].replace("营运车辆".encode(), "伪造车辆".encode())
        bad = self.directory / "坏包.zip"
        with zipfile.ZipFile(bad, "w") as z:
            for name, content in entries.items(): z.writestr(name, content)
        self.assert_code("HASH_MISMATCH", lambda: read_package(bad))
        with zipfile.ZipFile(path) as z: z.extractall(self.directory / "目录")
        (self.directory / "目录" / "private.txt").write_text("unexpected")
        self.assert_code("PACKAGE_CORRUPT", lambda: read_package(self.directory / "目录"))
        with zipfile.ZipFile(path) as z:
            entries = {name: z.read(name) for name in z.namelist()}
        manifest = json.loads(entries["manifest.json"]); manifest["format_version"] = "future/99"
        entries["manifest.json"] = json.dumps(manifest).encode()
        with zipfile.ZipFile(bad, "w") as z:
            for name, content in entries.items(): z.writestr(name, content)
        self.assert_code("UNSUPPORTED_FORMAT", lambda: read_package(bad))

    def test_reader_rechecks_false_claim_of_confirmed_publication(self):
        _, path, _ = self.write_package([asset("t", status="draft")], [], draft=True)
        with zipfile.ZipFile(path) as z:
            entries = {name: z.read(name) for name in z.namelist()}
        manifest = json.loads(entries["manifest.json"])
        manifest.update(draft=False, complete=True, issues=[])
        entries["manifest.json"] = json.dumps(manifest).encode()
        forged = self.directory / "伪声明.zip"
        with zipfile.ZipFile(forged, "w") as z:
            for name, content in entries.items(): z.writestr(name, content)
        self.assert_code("PACKAGE_CORRUPT", lambda: read_package(forged))

    def test_source_quote_is_escaped_in_offline_html_without_execution(self):
        value = asset("t", name="<script>alert(1)</script>", definition="<img src=x onerror=alert(1)>")
        _, path, _ = self.write_package([value], [])
        with zipfile.ZipFile(path) as z:
            page = z.read("human-review.html").decode()
        self.assertNotIn("<script>", page)
        self.assertNotIn("<img src=x", page)
        self.assertIn("&lt;script&gt;", page)

    def test_common_validator_requires_type_fields_only_when_confirmed(self):
        rule = asset("r", "rule")
        rule["properties"] = {}
        error = self.assert_code("INVALID_MODEL", lambda: validate_semantic_assets([rule]))
        self.assertEqual({i["field"] for i in error.details["issues"]}, {"condition", "requirement"})
        rule["status"] = "draft"
        self.assertIsNone(validate_semantic_assets([rule]))
        rule["refs"] = ["missing"]
        self.assert_code("INVALID_MODEL", lambda: validate_semantic_assets([rule]))

    def test_common_validator_rejects_classification_cycle_and_wrong_endpoint_type(self):
        values = [asset("a", "entity"), asset("b", "entity")]
        values += [asset("ab", "relation", **{"from": "a", "to": "b", "predicate": "属于类别", "relation_type": "is_a"}),
                   asset("ba", "relation", **{"from": "b", "to": "a", "predicate": "属于类别", "relation_type": "is_a"})]
        error = self.assert_code("INVALID_MODEL", lambda: validate_semantic_assets(values))
        self.assertEqual(error.details["issues"][0]["code"], "CLASSIFICATION_CYCLE")
        values[-1]["relation_type"] = "business"
        self.assertIsNone(validate_semantic_assets(values))
        values[0]["kind"] = "term"
        self.assert_code("INVALID_MODEL", lambda: validate_semantic_assets(values))

    def test_endpoint_diagnostic_names_assets_and_chinese_required_and_actual_types(self):
        values = [asset("vehicle_term", "term", "营运车辆术语"), asset("company", "entity", "企业"),
                  asset("owns", "relation", "车辆拥有营运证类型", **{
                      "from": "vehicle_term", "to": "company", "predicate": "拥有", "relation_type": "has_attribute"})]
        error = self.assert_code("INVALID_MODEL", lambda: validate_semantic_assets(values))
        self.assertEqual(error.details["asset_id"], "owns")
        self.assertEqual(error.details["asset_name"], "车辆拥有营运证类型")
        issue = error.details["issues"][0]
        self.assertEqual(issue["code"], "INVALID_RELATION_ENDPOINT")
        for text in ("车辆拥有营运证类型", "拥有属性", "业务对象", "数据集", "业务属性", "数据字段",
                     "当前起点「营运车辆术语」是术语", "终点「企业」是业务对象", "重新选择"):
            self.assertIn(text, str(error))
        self.assertNotIn("has_attribute", str(error))
        self.assertNotIn("vehicle_term", str(error))

    def test_missing_definition_and_metric_fields_are_chinese_but_keep_machine_keys(self):
        metric = asset("metric_missing", "metric", "有效异常车辆数", definition="", domain="", scope="")
        metric["properties"] = {}
        error = self.assert_code("INVALID_MODEL", lambda: validate_semantic_assets([metric]))
        self.assertIn("有效异常车辆数", str(error))
        self.assertEqual(error.details["asset_id"], "metric_missing")
        expected = {"definition": "定义", "domain": "领域", "scope": "适用范围", "unit": "单位", "grain": "统计粒度",
                    "inclusions": "包含范围", "exclusions": "排除范围", "time_scope": "业务时间范围"}
        issues = {issue["field"]: issue for issue in error.details["issues"]}
        self.assertEqual(set(issues), set(expected))
        for key, label in expected.items():
            self.assertIn(label, issues[key]["message"])
            self.assertIn("有效异常车辆数", issues[key]["message"])
            self.assertNotIn(key, issues[key]["message"])
            self.assertEqual(issues[key]["code"], "MISSING_DEFINITION" if key in {"definition", "domain", "scope"} else "MISSING_PROPERTY")
        reader, _, manifest = self.write_package([metric], draft=True)
        self.assertEqual(manifest["issues"], error.details["issues"])
        self.assertFalse(reader.verify()["complete"])

    def test_reextraction_keeps_content_revision_and_original_fragment_identity(self):
        values, sources = fixture()
        source = sources[0]
        source["revisions"] = source["revisions"][:1]
        version = source["revisions"][0]
        old_parse = copy.deepcopy(version["parsed"])
        new_parse = copy.deepcopy(old_parse)
        new_parse["fragments"][0]["location"] = {"paragraph": 9}
        new_parse["fragments"][0]["text"] = "重新提取后此编号代表别处，不能换绑。"
        version.update(current_extraction="extract_new", parsed=new_parse,
                       extractions=[{"id": "extract_old", "parsed": old_parse}, {"id": "extract_new", "parsed": new_parse}])
        values[3]["evidence"][0]["extraction_id"] = "extract_old"
        package, _, _ = self.write_package(values, sources, asset_ids=["rule"])
        found = package.sources("rule")["evidence"][0]
        self.assertEqual(found["extraction_id"], "extract_old")
        self.assertEqual(found["assertion"]["revision"], 1)
        self.assertEqual(found["fragment"]["text"], "企业负责本企业车辆维护。")
        self.assertEqual(found["fragment"]["location"]["line_start"], 1)
        self.assertEqual([e["id"] for e in package.source_records[0]["revisions"][0]["extractions"]], ["extract_old"])
        # A legacy reference cannot silently resolve a reused fragment ID to a new location.
        del values[3]["evidence"][0]["extraction_id"]
        self.assert_code("NOT_PUBLISHABLE", lambda: build_package(values, sources, project_id="x", revision=1, asset_ids=["rule"]))
        # With an unambiguous fragment ID the old extraction can still be found offline.
        new_parse["fragments"][0]["id"] = "new_p1"
        package, _, _ = self.write_package(values, sources, asset_ids=["rule"], filename="旧证据.zip")
        self.assertEqual(package.get("rule")["asset"]["evidence"][0]["extraction_id"], "extract_old")
        self.assertEqual(package.sources("rule")["evidence"][0]["fragment"]["text"], "企业负责本企业车辆维护。")

    def test_cli_in_independent_process_and_unrelated_working_directory(self):
        _, path, _ = self.write_package()
        cli = ROOT / "scripts" / "semantic_read.py"
        def run(*args):
            call = subprocess.run([sys.executable, "-X", "utf8", str(cli), "--package", str(path), *args],
                                  cwd=self.directory, capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(call.stderr, "")
            return call, json.loads(call.stdout)
        call, verified = run("verify")
        self.assertEqual(call.returncode, 0)
        self.assertEqual(verified["status"], "verified")
        _, found = run("search", "--query", "收入")
        self.assertEqual(found["status"], "ambiguous")
        _, evidence = run("sources", "--id", "rule")
        self.assertEqual(evidence["evidence"][0]["fragment"]["text"], "企业负责本企业车辆维护。")
        target = self.directory / "独立 子图.zip"
        call, exported = run("export", "--id", "rule", "--out", str(target))
        self.assertEqual(call.returncode, 0)
        self.assertEqual(set(read_package(target).index), {"rule", "company", "vehicle"})
        call, duplicate = run("export", "--id", "rule", "--out", str(target))
        self.assertEqual(call.returncode, 2)
        self.assertEqual(duplicate["error"]["code"], "OUTPUT_EXISTS")
        call, missing = run("get", "--id", "unknown")
        self.assertEqual(call.returncode, 2)
        self.assertEqual(missing["error"]["code"], "UNKNOWN_ID")
        self.assertEqual(missing["snapshot_id"], verified["snapshot_id"])
        call, mutation = run("edit", "--id", "vehicle")
        self.assertEqual(call.returncode, 2)
        self.assertEqual(mutation["error"]["code"], "INVALID_INPUT")


if __name__ == "__main__":
    unittest.main()
