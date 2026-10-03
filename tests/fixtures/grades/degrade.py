#!/usr/bin/env python3
"""degrade.py — 由各领域 L3（mocks/<domain>/）确定性生成 L0/L1/L2 退化档位 fixtures。

退化规则（即"档位定义"的可执行形态，详见《分级测试装置设计.md》）：
  L0 不全   ：只保留第一个数据集（第二张表"未到货"）；去 grain/primary_key/ai.instructions；
              指标只留首数据集上的，同义词砍到 1 个，去 on_zero_denominator/display_scale；
              删 constraints/templates/ontology/concepts；物理表剥掉主键约束
  L1 质量差 ：结构保持 L3 不动；物理表剥掉主键约束；按本领域 DIRTY 注入 4 类脏数据
              （主键重复 / 枚举越界 / 负值 / 引用悬空），位置固定可复算
  L2 中等   ：结构数据双干净；同义词砍到 2 个，去除零策略与展示刻度；
              删 constraints/templates/ontology/concepts
  L3 完整   ：原样复制

金标准纪律：本脚本生成 fixtures 后，须先跑 verify_grades.py 观察实际诊断，
人工审查合理后方可把 expected_diagnostics.yaml 当作审定标准（本脚本已按
edu_assess 审定过的同款模式生成，新领域首次运行等同于复审一次）。

用法：python degrade.py            # 重新生成全部声明领域的 L0-L2（L3 复制）
"""
import json
import os
import re
import shutil

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))            # tests/fixtures/grades
REPO = os.path.normpath(os.path.join(HERE, "..", "..", ".."))  # v007_repo

# 每领域的退化参数：第二张表名、L1 脏数据注入 SQL、L1 期望被抓的规则、reconcile 金值（4 位小数）
DOMAINS = {
    "med_kpi": {
        "title": "医疗·三级公立医院绩效考核",
        "second_table": "inpatients",
        "dirty_sql": """
INSERT INTO inpatients VALUES ('P0001','骨科',9,'医嘱离院',12345.0,'2026-07-15');
INSERT INTO inpatients VALUES ('P9001','骨科',7,'急诊离院',8800.0,'2026-08-15');
INSERT INTO inpatients VALUES ('P9002','整形美容科',5,'医嘱离院',6600.0,'2026-08-16');
UPDATE dws_dept_monthly SET outpatient_rev=-100 WHERE dept='骨科' AND month='2026-08';""",
        "failed_ids": ["dws_rev_nonnegative", "ip_dept_ref", "ip_pk", "ip_way_values"],
        "dirty_desc": "ip_pk 主键重复（P0001 两条）/ ip_way_values 枚举越界（急诊离院）/ "
                      "dws_rev_nonnegative 负收入（骨科 2026-08）/ ip_dept_ref 引用悬空（整形美容科）",
        "reconcile": {"avg_stay_days": 9.2, "bed_occupancy_rate": 0.87, "drug_ratio": 0.2898,
                      "level4_surgery_ratio": 0.2407, "med_service_rev_ratio": 0.2613,
                      "outpatient_avg_fee": 321.8519},
    },
    "green_factory": {
        "title": "绿色制造·绿色工厂评价",
        "second_table": "waste_records",
        "dirty_sql": """
INSERT INTO waste_records VALUES ('W0001','焊装车间','边角料',2.0,'综合利用','2026-07-15');
INSERT INTO waste_records VALUES ('W9001','焊装车间','废溶剂',3.0,'安全处置','2026-08-15');
INSERT INTO waste_records VALUES ('W9002','总装车间','边角料',1.5,'综合利用','2026-08-16');
UPDATE dws_workshop_monthly SET energy_tce=-5 WHERE workshop='焊装车间' AND month='2026-08';""",
        "failed_ids": ["dws_energy_nonnegative", "wr_pk", "wr_type_values", "wr_ws_ref"],
        "dirty_desc": "wr_pk 主键重复（W0001 两条）/ wr_type_values 枚举越界（废溶剂）/ "
                      "dws_energy_nonnegative 负能耗（焊装 2026-08）/ wr_ws_ref 引用悬空（总装车间）",
        "reconcile": {"energy_per_unit": 0.0115, "renewable_rate": 0.1458, "water_reuse_rate": 0.9,
                      "waste_reuse_rate": 0.9237, "water_per_unit": 0.0736, "safe_disposal_count": 6},
    },
    "elderly_care": {
        "title": "养老·机构等级评定",
        "second_table": "residents",
        "dirty_sql": """
INSERT INTO residents VALUES ('R0001','颐年养老院','自理','一级','2025-06-15');
INSERT INTO residents VALUES ('R9001','颐年养老院','植物人','二级','2026-08-15');
INSERT INTO residents VALUES ('R9002','舒心养老院','半失能','二级','2026-08-16');
UPDATE dws_facility_monthly SET bed_count=0 WHERE facility='颐年养老院' AND month='2026-08';""",
        "failed_ids": ["dws_bed_positive", "res_ability_values", "res_fac_ref", "res_pk"],
        "dirty_desc": "res_pk 主键重复（R0001 两条）/ res_ability_values 枚举越界（植物人，能力等级须按 GB/T 42195 字典）/ "
                      "dws_bed_positive 床位为零（颐年 2026-08）/ res_fac_ref 引用悬空（舒心养老院不在机构主数据）",
        "reconcile": {"occupancy_rate": 0.9027, "caregiver_ratio": 6.0991,
                      "certified_caregiver_rate": 0.7027, "rehab_coverage_rate": 0.5096,
                      "monthly_complaints": 3.0, "disabled_ratio": 0.5},
    },
    "diag_reform": {
        "title": "高职·内部质量保证体系诊改",
        "second_table": "diag_warnings",
        "dirty_sql": """
INSERT INTO diag_warnings VALUES ('W0001','T0002','逾期预警','未处理','2026-08-30');
INSERT INTO diag_tasks VALUES ('T9001','院系','学校发展规划','双高任务','改革试点任务数','个','≥',5.0,6.0,'已达标','教务处','2026年度诊改','2026-12-31',0.5);
INSERT INTO diag_warnings VALUES ('W9001','T9999','倒计时预警','未处理','2026-08-31');
UPDATE diag_tasks SET weight=-0.5 WHERE task_id='T0003';""",
        "failed_ids": ["tasks_level_values", "tasks_weight_range", "warn_pk", "warn_task_ref"],
        "dirty_desc": "warn_pk 主键重复（W0001 两条）/ tasks_level_values 枚举越界（院系，层面字典须为五横之一，真实项目里「院系」天天被随手填进来）/ "
                      "tasks_weight_range 负权重（T0003=-0.5）/ warn_task_ref 引用悬空（T9999 不存在）",
        "reconcile": {"pass_rate": 0.6667, "completion_rate": 0.8, "overdue_ratio": 0.1,
                      "unhandled_warning_count": 8.0},
    },
}

L0_GUIDE = [
    "E01/E02 是阻断项：先确认每张表「一行代表什么」（grain）与去重依据（primary_key），可用 guide_model 开补齐会话（先业务后物理）",
    "指标同义词补到 3 个以上（W17），否则用户问法路由不上，会掉进慢速 NL2SQL",
    "比率指标显式声明 on_zero_denominator（W11）；unit 为 % 的比率声明 display_scale=100（W15）",
    "数据集补 ai.instructions：能答什么、不能答什么、必带的时间围栏（W01）",
    "第二张明细表 DDL 到货后补第二数据集，再谈其上的指标",
]
L1_GUIDE = [
    "按 fail 规则逐条修复：{dirty_desc}",
    "修复完成前阻塞 S3 交付与指标发布——脏数据上算的指标是负资产",
    "修复后重跑 check_constraints，全 pass 才进 L2/L3 流程",
    "建议源头侧加物理主键约束，防止脏数据再次流入",
]
L2_GUIDE = [
    "W17：每个指标同义词补到 3 个以上（盘点真实用户问法，含口语变体）",
    "W11/W15：比率指标补 on_zero_denominator 与 display_scale，把除零与 ×100 展示责任显式落地",
    "补 constraints 段（主键唯一/枚举字典/非空/范围/引用完整），把数据正确性从假设变成证明",
    "补 templates 明细模板与 ontology 声明层，明细查询和实体语义成为一等资产",
    "指标口径 basis 从「mock 内部约定」换成真实文件依据",
]
L3_GUIDE = [
    "进本体建模评审：实体/关系/投影对账已齐，可出语义图供业务评审",
    "S4 交付：export_exchange 出交换包（模型/用例/证据/视图 + 哈希清单）",
    "供 AI 使用：结构化指标走口径编译直答，明细走模板，越界与写操作走拒答守卫",
    "交付后转 S5 巡检：check_model --drift 盯演进，--history 记质量趋势",
]


def strip_pk(src):
    """剥掉 DDL 里的主键约束（真实业务库常态）：行内 TEXT PRIMARY KEY 与独立 PRIMARY KEY 行两种形态。"""
    src = src.replace(" TEXT PRIMARY KEY", " TEXT")
    return re.sub(r"\s*,PRIMARY KEY \([^)]*\)", "", src)


def gen_build_db(domain, grade, spec):
    src = open(os.path.join(REPO, "mocks", domain, "build_db.py"), encoding="utf-8").read()
    banner = f'"""GENERATED by degrade.py：{domain}/{grade}（勿手改，改 mocks/{domain} 后重新生成）"""\n'
    src = re.sub(r'^"""[\s\S]*?"""', banner.strip(), src, count=1)
    if grade == "L0":
        src = strip_pk(src) + (
            f"\n# ---- L0 退化：第二数据集表「未到货」，物理主键亦未声明 ----\n"
            f"_c = sqlite3.connect(DB)\n"
            f"_c.execute(\"DROP TABLE IF EXISTS {spec['second_table']}\")\n"
            f"_c.commit(); _c.close()\n")
    elif grade == "L1":
        src = strip_pk(src) + (
            f"\n# ---- L1 退化：注入 4 类脏数据（{spec['dirty_desc']}） ----\n"
            f"_c = sqlite3.connect(DB)\n"
            f"_c.executescript('''{spec['dirty_sql']}\n''')\n"
            f"_c.commit(); _c.close()\n")
    return src


def gen_model(domain, grade):
    path = os.path.join(REPO, "mocks", domain, "semantic.yaml")
    if grade == "L1":
        # L1 结构完整（脏的是数据）：仅改版本号，文本级替换以保留 YAML 锚点
        src = open(path, encoding="utf-8").read()
        return re.sub(r"^version: \S+", f"version: mock-{domain}-L1", src, count=1, flags=re.M)
    m = yaml.safe_load(open(path, encoding="utf-8"))
    m["version"] = f"{m['version']}-{grade}"
    first_ds = m["datasets"][0]["name"]
    if grade == "L0":
        m["datasets"] = m["datasets"][:1]
        for ds in m["datasets"]:
            ds.pop("grain", None)
            ds.pop("primary_key", None)
            ds.pop("ai", None)
        keep_syn = 1
    else:  # L2
        keep_syn = 2
    for ds in m["datasets"]:
        ds.pop("ontology_ref", None)  # ontology 段将被删除，投影回指必须一并去掉（E14）
    for x in m.get("metrics", []):
        x["synonyms"] = (x.get("synonyms") or [])[:keep_syn]
        x.pop("on_zero_denominator", None)
        x.pop("display_scale", None)
    if grade == "L0":
        m["metrics"] = [x for x in m.get("metrics", []) if x.get("dataset") == first_ds]
    for k in ("constraints", "templates", "ontology", "concepts"):
        m.pop(k, None)
    m["relationships"] = []
    return yaml.dump(m, allow_unicode=True, sort_keys=False)


def gen_cases(domain, grade, first_ds_metrics):
    cases = json.load(open(os.path.join(REPO, "mocks", domain, "cases.json"), encoding="utf-8"))
    rejects = [c for c in cases if c.get("expect_reject")]
    if grade == "L0":
        metric_case = next(c for c in cases if c.get("metric") in first_ds_metrics)
        picked = [metric_case, rejects[0]]
    elif grade == "L1":
        picked = rejects[:2]
    else:  # L2
        picked = [c for c in cases if not c.get("expect_reject")][:2] + rejects[:1]
    for i, c in enumerate(picked, 1):
        c["id"] = f"{grade}-{i:02d}"
    return json.dumps(picked, ensure_ascii=False, indent=1) + "\n"


def write_expected(gdir, domain, grade, spec, first_ds_metrics):
    title = {"L0": "不全——只有部分 DDL 到货，口径靠口头描述",
             "L1": "质量差——结构完整，但数据没人审过",
             "L2": "中等——结构干净、数据干净，但语义薄",
             "L3": "完整——结构、数据、语义三轴齐备，可供 AI 使用"}[grade]
    if grade == "L0":
        cm = {"exit": 1, "errors": ["E01", "E02"], "warns": ["W01", "W11", "W15", "W17"]}
        cc = {"status": "not_ready", "failed_ids": []}
        rec = "skip"
        guide, nxt = L0_GUIDE, "结构补齐后进 L2；若到手数据未经核验，先进 L1 流程跑约束"
    elif grade == "L1":
        cm = {"exit": 0, "errors": [], "warns": []}
        cc = {"status": "not_ready", "failed_ids": spec["failed_ids"]}
        rec = "skip"
        guide = [g.format(dirty_desc=spec["dirty_desc"]) for g in L1_GUIDE]
        nxt = "数据修复、约束全 pass 后进 L3"
    elif grade == "L2":
        cm = {"exit": 0, "errors": [], "warns": ["W11", "W15", "W17"]}
        cc = {"status": "not_ready", "failed_ids": []}
        rec = {"metrics": spec["reconcile"]}
        guide, nxt = L2_GUIDE, "语义加厚 + 约束声明后进 L3"
    else:
        cm = {"exit": 0, "errors": [], "warns": []}
        cc = {"status": "pass", "failed_ids": []}
        rec = {"metrics": spec["reconcile"]}
        guide, nxt = L3_GUIDE, "已是目标态；持续巡检与漂移管理"
    doc = {
        "grade": grade, "title": title,
        "scenario": f"{spec['title']} 领域的 {grade} 档（由 degrade.py 从 mocks/{domain} 确定性生成）。",
        "check_model": cm, "check_constraints": cc, "reconcile": rec,
        "guidance": guide, "next_grade": nxt,
    }
    with open(os.path.join(gdir, "expected_diagnostics.yaml"), "w", encoding="utf-8") as f:
        yaml.dump(doc, f, allow_unicode=True, sort_keys=False, width=120)


def build_domain(domain, spec):
    src = os.path.join(REPO, "mocks", domain)
    m = yaml.safe_load(open(os.path.join(src, "semantic.yaml"), encoding="utf-8"))
    first_ds = m["datasets"][0]["name"]
    first_ds_metrics = {x["id"] for x in m.get("metrics", []) if x.get("dataset") == first_ds}
    for grade in ("L0", "L1", "L2", "L3"):
        gdir = os.path.join(HERE, domain, grade)
        os.makedirs(gdir, exist_ok=True)
        if grade == "L3":
            for f in ("build_db.py", "semantic.yaml", "cases.json"):
                shutil.copyfile(os.path.join(src, f), os.path.join(gdir, f))
        else:
            with open(os.path.join(gdir, "build_db.py"), "w", encoding="utf-8") as f:
                f.write(gen_build_db(domain, grade, spec))
            with open(os.path.join(gdir, "semantic.yaml"), "w", encoding="utf-8") as f:
                f.write(gen_model(domain, grade))
            with open(os.path.join(gdir, "cases.json"), "w", encoding="utf-8") as f:
                f.write(gen_cases(domain, grade, first_ds_metrics))
        write_expected(gdir, domain, grade, spec, first_ds_metrics)
    print(f"{domain}: L0-L3 已生成")


def main():
    for domain, spec in DOMAINS.items():
        build_domain(domain, spec)
    print("全部生成完毕；请运行 verify_grades.py 复审实际诊断是否符合金标准。")


if __name__ == "__main__":
    main()
