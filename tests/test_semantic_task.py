"""Business-question discovery must never silently choose a meaning or invent results."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from test_semantic_package import asset, fixture
from workbench.semantic_package import PackageError, build_package, discover_candidates, read_package

ROOT = Path(__file__).resolve().parents[1]


class SemanticTaskTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="问题读取 ")
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "知识.zip"

    def package(self, assets=None, sources=None, **kwargs):
        if assets is None:
            assets, sources = fixture()
        payload, _ = build_package(assets, sources or [], project_id="tasks", revision=4, **kwargs)
        self.path.write_bytes(payload)
        return read_package(self.path)

    def test_chinese_question_retains_all_same_name_meanings_and_no_selection(self):
        p = self.package()
        result = p.resolve("本月收入应该按哪个口径统计？", limit=1)
        self.assertEqual(result["status"], "needs_selection")
        self.assertEqual(result["total"], 2)
        self.assertEqual(result["selected_asset_ids"], [])
        self.assertNotIn("context", result)
        self.assertFalse(result["answer_verified"])
        self.assertFalse(result["request_complete"])
        self.assertTrue(result["truncated"])
        second = p.resolve("本月收入应该按哪个口径统计？", limit=1, offset=result["next_offset"])
        self.assertEqual({result["candidates"][0]["id"], second["candidates"][0]["id"]}, {"revenue_sales", "revenue_finance"})
        self.assertEqual(second["status"], "needs_selection")
        self.assertIsNone(second["next_offset"])

    def test_scoped_single_result_is_still_only_a_candidate(self):
        p = self.package()
        r = p.resolve("收入怎么算？", domain="销售", scope={"basis": "已支付订单"})
        self.assertEqual([c["id"] for c in r["candidates"]], ["revenue_sales"])
        self.assertEqual(r["decision"], "needs_selection")
        self.assertEqual(r["capabilities"]["authorization"], "not_granted_by_knowledge_or_role_definitions")

    def test_english_aliases_and_definition_terms_rank_without_word_substrings(self):
        values = [asset("available", name="Available equipment", aliases=["Ready stock"], definition="Equipment available for a laboratory loan."),
                  asset("scar", name="Scar", definition="A healed wound."),
                  asset("car", name="Car", definition="A transport vehicle.")]
        p = self.package(values)
        r = p.resolve("How many items of ready stock can I borrow?")
        self.assertEqual(r["candidates"][0]["id"], "available")
        self.assertEqual(r["candidates"][0]["match_reason"], "label_in_question")
        self.assertEqual([x["id"] for x in p.resolve("Show car details")["candidates"]], ["car"])
        self.assertEqual(p.resolve("Can I get a laboratory loan?")["candidates"][0]["id"], "available")

    def test_no_match_does_not_mean_zero_or_no_business_objects(self):
        p = self.package()
        r = p.resolve("紫外线灭菌流程")
        self.assertEqual(r["status"], "no_match")
        self.assertFalse(r["complete"])
        self.assertNotIn("answer", r)
        self.assertNotIn("value", r)

    def test_short_chinese_business_word_finds_compound_label_without_definition_noise(self):
        values = [asset("batch", name="产品批次", definition="收获或加工的可追踪单位"),
                  asset("trace", name="批次追溯", definition="说明产品的来处与去向"),
                  asset("noise", name="设备说明", definition="备注可能提及批次，但本对象是设备")]
        result = self.package(values).resolve("批次怎么追溯？")
        self.assertEqual({item["id"] for item in result["candidates"]}, {"batch", "trace"})
        self.assertEqual(result["status"], "needs_selection")
        self.assertEqual(result["selected_asset_ids"], [])
        self.assertFalse(result["answer_verified"])

    def test_explicit_context_preserves_dependencies_evidence_and_source_revision(self):
        p = self.package()
        r = p.resolve("车辆维护有什么要求？", asset_ids=["rule"])
        self.assertEqual(r["status"], "context_available")
        c = r["context"]
        self.assertEqual(set(c["required_asset_ids"]), {"rule", "company", "vehicle"})
        rule_evidence = next(e for e in c["evidence"] if e["asset_id"] == "rule")
        self.assertEqual(rule_evidence["evidence"][0]["assertion"]["revision"], 1)
        self.assertFalse(r["answer_verified"])
        self.assertEqual(r["resolution"]["question_coverage"], "not_verified")

    def test_explicit_unrelated_ids_are_not_claimed_to_answer_the_question(self):
        p = self.package()
        r = p.resolve("其他实验室可以借设备吗？", asset_ids=["vehicle"])
        self.assertEqual(r["selected_asset_ids"], ["vehicle"])
        self.assertEqual(r["resolution"]["question_coverage"], "not_verified")
        self.assertIn("VERIFY_QUESTION_COVERAGE", [s["code"] for s in r["next_steps"]])

    def test_declared_gaps_and_dates_require_review_even_when_package_is_complete(self):
        value = asset("available", name="可借设备", properties={"knowledge_gaps": ["跨实验室是否允许借用尚未明确"]})
        p = self.package([value])
        r = p.resolve("跨实验室能借设备吗？", asset_ids=["available"])
        self.assertTrue(r["package_complete"])
        self.assertEqual(r["decision"], "needs_review")
        self.assertIn("DECLARED_KNOWLEDGE_GAP", [g["code"] for g in r["context"]["gaps"]])
        p = self.package([asset("dated", effective_from="2025-01-01", effective_to="2025-12-31")])
        r = p.resolve("dated", asset_ids=["dated"], as_of="2026-01-01")
        self.assertEqual(r["decision"], "needs_review")
        self.assertIn("OUTSIDE_KNOWN_INTERVAL", [g["code"] for g in r["context"]["gaps"]])
        self.assertEqual(p.resolve("dated", as_of="2026-01-01")["total"], 0)

    def test_query_action_and_calculate_require_actual_executors_or_data(self):
        p = self.package()
        for intent, code in [("query", "CONNECT_AUTHORIZED_DATA"), ("act", "USE_AUTHORIZED_ACTION_EXECUTOR"), ("calculate", "SUPPLY_VERIFIED_DATA_AND_CALCULATE")]:
            with self.subTest(intent=intent):
                r = p.resolve("现在有多少车辆？", asset_ids=["vehicle"], intent=intent)
                self.assertEqual(r["decision"], "requires_execution")
                self.assertFalse(r["answer_verified"])
                self.assertIn(code, [s["code"] for s in r["next_steps"]])
                self.assertNotIn("value", r)
                self.assertFalse(r["capabilities"]["query_data"]["available"])

    def test_explicit_root_filters_do_not_drop_shared_dependency_scopes(self):
        shared = asset("shared", domain="政策", scope="集团")
        scoped = asset("scopeA", domain="运输", scope={"tenant": "A"}, refs=["shared"])
        p = self.package([scoped, shared])
        r = p.resolve("服务范围", asset_ids=["scopeA"], domain="运输", scope={"tenant": "A"})
        self.assertEqual(r["context"]["business_scopes"], [{"asset_id": "scopeA", "scope": {"tenant": "A"}}, {"asset_id": "shared", "scope": "集团"}])
        with self.assertRaises(PackageError) as exc:
            p.resolve("服务范围", asset_ids=["scopeA"], scope={"tenant": "B"})
        self.assertEqual(exc.exception.code, "SELECTION_SCOPE_MISMATCH")

    def test_scope_values_distinguish_missing_null_false_and_zero(self):
        values = [asset("zero", name="名额", scope={"value": 0}), asset("false", name="名额", scope={"value": False}),
                  asset("null", name="名额", scope={"value": None}), asset("missing", name="名额", scope={"other": "value"})]
        p = self.package(values)
        for value, aid in [(0, "zero"), (False, "false"), (None, "null")]:
            self.assertEqual([r["id"] for r in p.resolve("名额", scope={"value": value})["candidates"]], [aid])

    def test_context_pages_remain_incomplete_and_keep_required_identity_set(self):
        p = self.package()
        r = p.resolve("车辆维护要求", asset_ids=["rule"], limit=1)
        self.assertEqual(r["decision"], "needs_review")
        self.assertFalse(r["request_complete"])
        self.assertEqual(r["context"]["next_offset"], 1)
        self.assertEqual(set(r["context"]["required_asset_ids"]), {"rule", "company", "vehicle"})

    def test_workspace_discovery_has_no_verification_or_write_side_effects(self):
        values = [asset("draft", name="可用库存", status="draft", evidence=[])]
        before = copy.deepcopy(values)
        r = discover_candidates(values, "可用库存有多少？")
        self.assertEqual(r["candidates"][0]["status"], "draft")
        self.assertNotIn("package_complete", r)
        r["candidates"][0]["scope"] = "changed output"
        self.assertEqual(values, before)

    def test_discovery_does_not_index_execution_or_untrusted_source_instructions(self):
        value = asset("safe", name="公共定义", properties={"execution": {"sql": "SECRET_EXECUTION_MARKER"}})
        value["evidence"][0]["quote"] = "UNTRUSTED_SOURCE_COMMAND"
        p = self.package([value], include_execution=True)
        self.assertEqual(p.resolve("SECRET_EXECUTION_MARKER")["total"], 0)
        self.assertEqual(p.resolve("UNTRUSTED_SOURCE_COMMAND")["total"], 0)

    def test_cli_resolve_and_invalid_input_leave_package_unchanged(self):
        self.package()
        before = self.path.read_bytes()
        command = [sys.executable, "-X", "utf8", str(ROOT / "scripts/semantic_read.py"), "--package", str(self.path), "resolve", "--question", "收入怎么算？"]
        run = subprocess.run(command + ["--domain", "销售"], capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(json.loads(run.stdout)["candidates"][0]["id"], "revenue_sales")
        run = subprocess.run(command + ["--id", "revenue_sales", "--intent", "calculate"], capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(json.loads(run.stdout)["status"], "requires_execution")
        bad = subprocess.run(command + ["--scope", "{bad"], capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(bad.returncode, 2)
        self.assertEqual(json.loads(bad.stdout)["error"]["code"], "INVALID_INPUT")
        self.assertEqual(self.path.read_bytes(), before)

    def test_invalid_questions_ids_and_pages_are_explicit_errors(self):
        p = self.package()
        for kwargs in [{"question": ""}, {"question": "x" * 4001}, {"question": "收入", "limit": 0},
                       {"question": "收入", "asset_ids": ["missing"]}, {"question": "收入", "intent": "invent"},
                       {"question": "收入", "scope": []}]:
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(PackageError):
                    p.resolve(**kwargs)


if __name__ == "__main__":
    unittest.main()
