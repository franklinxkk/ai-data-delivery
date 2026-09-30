# -*- coding: utf-8 -*-
"""v0.0.9 测试：E14 uid 双解析 / W17 同义词门禁 / templates 一等资产(E18/W18)
/ patch_model batch+fixuid+原子写 / promote_draft 端到端。"""
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parent.parent


def run_cli(args, cwd=None):
    return subprocess.run([sys.executable] + args,
                          encoding="utf-8", capture_output=True,
                          env=dict(os.environ, PYTHONIOENCODING="utf-8"),
                          cwd=cwd or ROOT / "scripts")


def write_yaml(path, obj):
    Path(path).write_text(yaml.safe_dump(obj, allow_unicode=True, sort_keys=False),
                          encoding="utf-8")


def base_model():
    return {
        "datasets": [{
            "name": "隐患明细", "source": "dws_hazard", "grain": "一行一隐患",
            "primary_key": ["hazard_id"],
            "ai": {"instructions": "隐患明细宽表", "synonyms": ["隐患表"]},
            "fields": [
                {"name": "hazard_id", "cn": "隐患ID", "role": "pk", "type": "varchar"},
                {"name": "ent_id", "cn": "企业ID", "role": "fk", "type": "varchar"},
                {"name": "stat_date", "cn": "统计日期", "role": "time", "type": "date"},
                {"name": "status", "cn": "整改状态", "role": "dim", "type": "varchar",
                 "enum": {"待整改": "待整改", "已整改": "已整改"}},
                {"name": "level", "cn": "隐患等级", "role": "dim", "type": "varchar"},
            ],
        }],
        "metrics": [{
            "id": "hazard_count", "name": "隐患数", "type": "count", "structured": True,
            "dataset": "隐患明细", "expr": "COUNT(*)", "time_field": "stat_date",
            "unit": "条", "synonyms": ["隐患数量", "有多少隐患", "隐患条数"],
            "status": "已发布",
        }],
        "ontology": {"entities": [
            {"name": "企业", "uid": "ent_enterprise"},
            {"name": "隐患", "uid": "ent_hazard", "unprojected_reason": "示例"},
        ], "relations": []},
    }


class TestE14UidRef(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.model = Path(self.tmp.name) / "m.yaml"

    def tearDown(self):
        self.tmp.cleanup()

    def lint(self, m):
        write_yaml(self.model, m)
        return run_cli([str(ROOT / "scripts" / "check_model.py"), "-f", str(self.model)])

    def test_ref_by_uid_passes_and_projects(self):
        m = base_model()
        m["datasets"][0]["ontology_ref"] = "ent_enterprise"  # uid 写法
        r = self.lint(m)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("E14", r.stdout)
        # uid 投影归一为 name：企业实体不应再吃 W07
        self.assertNotIn("ontology.entity[企业]", r.stdout)

    def test_ref_by_name_still_passes(self):
        m = base_model()
        m["datasets"][0]["ontology_ref"] = "企业"
        r = self.lint(m)
        self.assertNotIn("E14", r.stdout)

    def test_ref_dangling_still_errors(self):
        m = base_model()
        m["datasets"][0]["ontology_ref"] = "ent_ghost"
        r = self.lint(m)
        self.assertEqual(r.returncode, 1)
        self.assertIn("E14", r.stdout)


class TestW17SynonymGate(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.model = Path(self.tmp.name) / "m.yaml"

    def tearDown(self):
        self.tmp.cleanup()

    def test_few_synonyms_warns(self):
        m = base_model()
        m["metrics"][0]["synonyms"] = ["隐患数量"]
        write_yaml(self.model, m)
        r = run_cli([str(ROOT / "scripts" / "check_model.py"), "-f", str(self.model)])
        self.assertIn("W17", r.stdout)
        self.assertEqual(r.returncode, 0)  # WARN 不破门禁

    def test_retired_metric_exempt(self):
        m = base_model()
        m["metrics"][0]["synonyms"] = []
        m["metrics"][0]["status"] = "停用"
        write_yaml(self.model, m)
        r = run_cli([str(ROOT / "scripts" / "check_model.py"), "-f", str(self.model)])
        self.assertNotIn("W17", r.stdout)


class TestTemplates(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.model = Path(self.tmp.name) / "m.yaml"

    def tearDown(self):
        self.tmp.cleanup()

    def lint(self, m):
        write_yaml(self.model, m)
        return run_cli([str(ROOT / "scripts" / "check_model.py"), "-f", str(self.model)])

    def good_template(self):
        return {"id": "hazard_list", "name": "隐患明细查询", "dataset": "隐患明细",
                "columns": ["hazard_id", "status"], "time_field": "stat_date",
                "synonyms": ["隐患列表", "隐患明细", "有哪些隐患"], "status": "已发布"}

    def test_good_template_clean(self):
        m = base_model()
        m["templates"] = [self.good_template()]
        r = self.lint(m)
        self.assertNotIn("E18", r.stdout)
        self.assertNotIn("W18", r.stdout)

    def test_bad_dataset_and_column_error(self):
        m = base_model()
        t = self.good_template()
        t["dataset"] = "不存在的表"
        t["columns"] = ["hazard_id", "ghost_col"]
        m["templates"] = [t]
        r = self.lint(m)
        self.assertEqual(r.returncode, 1)
        self.assertIn("E18", r.stdout)

    def test_dup_id_error(self):
        m = base_model()
        m["templates"] = [self.good_template(), self.good_template()]
        r = self.lint(m)
        self.assertEqual(r.returncode, 1)
        self.assertIn("E18", r.stdout)

    def test_missing_time_field_and_synonyms_warn(self):
        m = base_model()
        t = self.good_template()
        del t["time_field"]
        t["synonyms"] = ["隐患列表"]
        m["templates"] = [t]
        r = self.lint(m)
        self.assertEqual(r.returncode, 0)
        self.assertIn("W18", r.stdout)

    def test_drift_breaking_when_dataset_removed(self):
        cur = base_model()
        cur["templates"] = [self.good_template()]
        base = Path(self.tmp.name) / "base.yaml"
        write_yaml(base, cur)
        cur["datasets"] = []
        cur["metrics"] = []
        cur["templates"] = []
        cur["ontology"] = {"entities": [{"name": "企业", "uid": "ent_enterprise"}],
                           "relations": []}
        write_yaml(self.model, cur)
        r = run_cli([str(ROOT / "scripts" / "check_model.py"), "-f", str(self.model),
                     "--drift", str(base)])
        self.assertIn("template[hazard_list]", r.stdout)


class TestBatchAndFixuid(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.model = self.dir / "m.yaml"
        write_yaml(self.model, base_model())

    def tearDown(self):
        self.tmp.cleanup()

    def batch(self, ops, extra=None):
        ops_path = self.dir / "ops.yaml"
        write_yaml(ops_path, {"ops": ops})
        cmd = [str(ROOT / "scripts" / "patch_model.py"), "-f", str(self.model),
               "batch", str(ops_path)] + (extra or [])
        return run_cli(cmd)

    def test_batch_applies_and_skips_failures(self):
        r = self.batch([
            {"op": "syn", "metric": "hazard_count", "words": ["隐患总量"]},
            {"op": "set_uid", "entity": "企业", "uid": "ent_ent2"},
            {"op": "syn", "metric": "ghost", "words": ["x"]},
        ])
        self.assertEqual(r.returncode, 1)  # 有失败条目
        self.assertIn("2/3", r.stdout)
        m = yaml.safe_load(self.model.read_text(encoding="utf-8"))
        self.assertIn("隐患总量", m["metrics"][0]["synonyms"])
        self.assertEqual(m["ontology"]["entities"][0]["uid"], "ent_ent2")
        self.assertFalse((self.dir / "m.yaml.tmp").exists())  # 原子写无残留

    def test_batch_idempotent_second_run(self):
        ops = [{"op": "syn", "metric": "hazard_count", "words": ["隐患总量"]}]
        self.batch(ops)
        r = self.batch(ops)
        self.assertEqual(r.returncode, 0)
        self.assertIn("no change", r.stdout)

    def test_batch_struct_verified_with_db(self):
        db = self.dir / "t.db"
        conn = sqlite3.connect(db)
        conn.execute("CREATE TABLE dws_hazard (hazard_id TEXT, ent_id TEXT, "
                     "stat_date TEXT, status TEXT, level TEXT)")
        conn.execute("INSERT INTO dws_hazard VALUES ('h1','e1','2026-09-01','待整改','重大')")
        conn.commit()
        conn.close()
        r = self.batch([{"op": "struct", "id": "hazard_unresolved", "create": True,
                         "name": "未整改隐患数", "type": "count", "dataset": "隐患明细",
                         "expr": "COUNT(*)", "extra_where": "status = '待整改'",
                         "time_field": "stat_date", "synonyms": ["待整改隐患", "未整改隐患"]}],
                       extra=["--db", str(db)])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        m = yaml.safe_load(self.model.read_text(encoding="utf-8"))
        new = [x for x in m["metrics"] if x["id"] == "hazard_unresolved"]
        self.assertTrue(new and new[0]["structured"])

    def test_fixuid_map_vocab_hash(self):
        m = base_model()
        for e in m["ontology"]["entities"]:
            e.pop("uid", None)
        m["ontology"]["entities"].append({"name": "量子纠缠体"})  # 词表外 → 哈希回退
        write_yaml(self.model, m)
        r = run_cli([str(ROOT / "scripts" / "patch_model.py"), "-f", str(self.model),
                     "fixuid"])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        after = yaml.safe_load(self.model.read_text(encoding="utf-8"))
        uids = {e["name"]: e.get("uid") for e in after["ontology"]["entities"]}
        self.assertEqual(uids["企业"], "ent_enterprise")   # 内置词表
        self.assertEqual(uids["隐患"], "ent_hazard")
        self.assertTrue(uids["量子纠缠体"].startswith("ent_"))  # 哈希回退
        # 幂等：再跑一次 no change
        r2 = run_cli([str(ROOT / "scripts" / "patch_model.py"), "-f", str(self.model),
                      "fixuid"])
        self.assertIn("no change", r2.stdout)


class TestPromoteDraft(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        meta_dir = self.dir / "meta"
        meta_dir.mkdir()
        write_yaml(meta_dir / "dws_hazard.yaml", {
            "table": "dws_hazard",
            "columns": [
                {"name": "hazard_id", "cn": "隐患ID", "role": "pk"},
                {"name": "stat_date", "cn": "统计日期", "role": "time"},
                {"name": "status", "cn": "整改状态",
                 "enum": {"待整改": "待整改", "已整改": "已整改"}},
                {"name": "level", "cn": "隐患等级",
                 "enum": {"重大": "重大", "一般": "一般"}},
            ]})
        write_yaml(self.dir / "model.yaml", base_model())
        write_yaml(self.dir / "raw.yaml", {"metrics": [
            {"id": "hazard_major", "name": "重大隐患数", "type": "num",
             "source_table": "t1", "mapped_table": "dws_hazard",
             "formula_raw": "SELECT COUNT(*) FROM t1 WHERE 隐患等级='重大'"},
            {"id": "hazard_bad_val", "name": "待处理隐患数", "type": "num",
             "source_table": "t1", "mapped_table": "dws_hazard",
             "formula_raw": "SELECT COUNT(*) FROM t1 WHERE 整改状态='待处理'"},
            {"id": "hazard_ratio", "name": "隐患整改率", "type": "pct",
             "source_table": "t1", "mapped_table": "dws_hazard",
             "formula_raw": "SELECT 已整改数/隐患总数 FROM t1"},
            {"id": "hazard_list", "name": "隐患明细列表", "type": "list",
             "source_table": "t1", "mapped_table": "dws_hazard",
             "formula_raw": "SELECT hazard_id, status FROM t1 WHERE 隐患等级='重大'"},
            {"id": "hazard_count", "name": "隐患数", "type": "num",
             "source_table": "t1", "mapped_table": "dws_hazard",
             "formula_raw": "SELECT COUNT(*) FROM t1"},
            {"id": "no_table", "name": "无来源指标", "type": "num",
             "source_table": "—NO_TABLE—", "mapped_table": None,
             "formula_raw": "SELECT COUNT(*)"},
        ]})

    def tearDown(self):
        self.tmp.cleanup()

    def test_end_to_end(self):
        out = self.dir / "promote"
        r = run_cli([str(ROOT / "scripts" / "promote_draft.py"),
                     "--raw", str(self.dir / "raw.yaml"),
                     "--from-meta", str(self.dir / "meta"),
                     "--model", str(self.dir / "model.yaml"),
                     "--out", str(out)])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        doc = yaml.safe_load((out / "promote_draft.yaml").read_text(encoding="utf-8"))
        kinds = {d["id"]: d["kind"] for d in doc["drafts"]}
        self.assertEqual(kinds["hazard_major"], "✅ 可直接合入")
        self.assertTrue(kinds["hazard_bad_val"].startswith("🔶"))   # 枚举无近似 → 待确认
        self.assertTrue(kinds["hazard_ratio"].startswith("⛔"))      # 派生引用
        self.assertEqual([t["id"] for t in doc["detail_templates"]], ["hazard_list"])
        self.assertEqual({s["id"] for s in doc["skipped"]}, {"hazard_count", "no_table"})
        # ✅ 进 ops.yaml 且可被 patch_model batch 消费
        ops = yaml.safe_load((out / "ops.yaml").read_text(encoding="utf-8"))["ops"]
        self.assertEqual([o["id"] for o in ops], ["hazard_major"])
        self.assertEqual(ops[0]["extra_where"], "level = '重大'")
        r2 = run_cli([str(ROOT / "scripts" / "patch_model.py"),
                      "-f", str(self.dir / "model.yaml"), "batch", str(out / "ops.yaml")])
        self.assertEqual(r2.returncode, 0, r2.stdout + r2.stderr)
        merged = yaml.safe_load((self.dir / "model.yaml").read_text(encoding="utf-8"))
        self.assertIn("hazard_major", {m["id"] for m in merged["metrics"]})
        # 📋 模板草稿进 templates_draft.yaml
        tpl = yaml.safe_load((out / "templates_draft.yaml").read_text(encoding="utf-8"))
        self.assertEqual(tpl["templates"][0]["time_field"], "stat_date")
        self.assertTrue((out / "提升清单.md").exists())


class TestVisualizeAlias(unittest.TestCase):
    def test_dash_f_alias(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "v.html"
            r = run_cli([str(ROOT / "scripts" / "visualize_model.py"),
                         "-f", str(ROOT / "mocks" / "retail" / "semantic.yaml"),
                         "--out", str(out)])
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertTrue(out.exists())


class TestPipelineSeams(unittest.TestCase):
    """通用性走查发现的管线接缝：DDL COMMENT 应流入 meta.cn；
    meta sources 占位应点名提醒；未映射指标必须在 promote 输出中可见。"""

    def test_gen_metadata_prefers_ddl_comment(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            write_yaml(d / "tables.yaml", {"tables": [{"name": "t1", "columns": 1}]})
            write_yaml(d / "columns.yaml", [
                {"table": "t1", "name": "ticket_id", "type": "VARCHAR(20)",
                 "pk": True, "is_time": False, "comment": "工单号"},
                {"table": "t1", "name": "ghost_col", "type": "INT",
                 "pk": False, "is_time": False, "comment": ""}])
            r = run_cli([str(ROOT / "scripts" / "gen_metadata.py"),
                         "--tables", str(d / "tables.yaml"),
                         "--columns", str(d / "columns.yaml"),
                         "--out", str(d / "meta")])
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            meta = yaml.safe_load((d / "meta" / "t1.yaml").read_text(encoding="utf-8"))
            cns = {c["name"]: c["cn"] for c in meta["columns"]}
            self.assertEqual(cns["ticket_id"], "工单号")          # COMMENT 预填
            self.assertEqual(cns["ghost_col"], "【待填中文名】")   # 无 COMMENT 仍占位

    def test_harvest_warns_placeholder_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            meta = d / "meta"
            meta.mkdir()
            write_yaml(meta / "tickets.yaml",
                       {"table": "tickets", "sources": ["【待填：上游来源表】"]})
            write_yaml(d / "exp.yaml", [{"id": "m1", "name": "x",
                                         "formula": "SELECT COUNT(*) FROM tickets"}])
            r = run_cli([str(ROOT / "scripts" / "harvest_metrics.py"),
                         "--metrics", str(d / "exp.yaml"),
                         "--from-meta", str(meta),
                         "--out", str(d / "inv")])
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("占位", r.stderr)  # 占位 sources 必须点名，不再静默无映射

    def test_promote_unmapped_is_visible(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            write_yaml(d / "raw.yaml", {"metrics": [
                {"id": "m_unmapped", "name": "未映射指标", "type": "num",
                 "source_table": "real_table", "mapped_table": None,
                 "formula_raw": "SELECT COUNT(*) FROM real_table"},
                {"id": "m_nosource", "name": "无来源指标", "type": "num",
                 "source_table": "—NO_TABLE—", "mapped_table": None,
                 "formula_raw": "SELECT COUNT(*)"}]})
            r = run_cli([str(ROOT / "scripts" / "promote_draft.py"),
                         "--raw", str(d / "raw.yaml"),
                         "--from-meta", str(d),
                         "--model", str(ROOT / "mocks" / "crm" / "semantic.yaml"),
                         "--out", str(d / "out")])
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            doc = yaml.safe_load((d / "out" / "promote_draft.yaml").read_text(encoding="utf-8"))
            self.assertEqual(doc["summary"]["⚠️ 表名未映射"], 1)
            self.assertEqual(doc["unmapped"][0]["id"], "m_unmapped")
            self.assertEqual(doc["summary"]["跳过"], 1)  # 无来源仍归跳过
            checklist = (d / "out" / "提升清单.md").read_text(encoding="utf-8")
            self.assertIn("表名未映射", checklist)


if __name__ == "__main__":
    unittest.main()
