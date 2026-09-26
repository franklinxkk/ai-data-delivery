#!/usr/bin/env python3
"""harvest_metrics.py — 盘点段：既有指标库 → metrics_raw.yaml（ai-data-delivery v0.0.2）

把既有指标/报表导出（哪怕是中文伪代码 SQL）收成结构化盘点资产，
每条指标三分：可执行候选 / 需改写（伪代码） / 无来源（数据缺口）。

用法：
  python harvest_metrics.py --metrics 指标与规则全量导出.json --out inventory/

输入兼容：JSON/YAML，顶层为 list 或含 metrics 键的 dict；
记录字段按名兼容：id/name/table(或 tbl)/data_type(或 type)/formula(或 sql)/category/dims/status。

输出：
  metrics_raw.yaml  全量清单（含 status 三分与理由）
  gaps.yaml         数据缺口台账（无来源指标逐条登记，供信息中心闭环）
"""
import argparse
import json
import re
import sys

import yaml

CJK = re.compile(r"[一-鿿]")


def load(path):
    with open(path, encoding="utf-8") as f:
        data = json.load(f) if path.endswith(".json") else yaml.safe_load(f)
    if isinstance(data, dict):
        for k in ("metrics", "指标", "items"):
            if k in data:
                return data[k]
        raise ValueError("找不到指标清单键（metrics/指标/items）")
    return data


def strip_literals(sql):
    """去掉字符串字面量后再判断标识符是否含中文。"""
    return re.sub(r"'[^']*'", "''", sql or "")


def classify(rec):
    table = (rec.get("table") or rec.get("tbl") or "").strip()
    formula = (rec.get("formula") or rec.get("sql") or "").strip()
    if not table or table in ("-", "—", "—NO_TABLE—") or "NO_TABLE" in formula:
        return "无来源", "来源表缺失（NO_TABLE/空表名），记数据缺口"
    if not formula:
        return "需改写", "无口径式，需人工补口径"
    if CJK.search(strip_literals(formula)):
        return "需改写", "口径式为中文伪代码（标识符含中文），不可直接执行"
    return "可执行候选", "口径式形态可执行（仍需落宽表字段并验算）"


def main():
    ap = argparse.ArgumentParser(description="既有指标库盘点收割")
    ap.add_argument("--metrics", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    import os
    raw = load(args.metrics)
    out, gaps = [], []
    for r in raw:
        status, reason = classify(r)
        item = {"id": r.get("id"), "name": r.get("name"),
                "type": r.get("data_type") or r.get("type"),
                "source_table": (r.get("table") or r.get("tbl") or "").strip() or None,
                "category": r.get("category") or None,
                "dims": r.get("dims") or [],
                "formula_raw": (r.get("formula") or r.get("sql") or "").strip(),
                "status": status, "reason": reason,
                "rule_bound": bool(r.get("is_rule_source"))}
        out.append(item)
        if status == "无来源":
            gaps.append({"metric_id": item["id"], "metric_name": item["name"],
                         "issue": "无来源表", "owner": "信息中心",
                         "action": "确认数据源接入或显式标记暂不落地"})

    from collections import Counter
    dist = Counter(i["status"] for i in out)
    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, "metrics_raw.yaml"), "w", encoding="utf-8") as f:
        yaml.safe_dump({"total": len(out), "status_dist": dict(dist), "metrics": out},
                       f, allow_unicode=True, sort_keys=False)
    with open(os.path.join(args.out, "gaps.yaml"), "w", encoding="utf-8") as f:
        yaml.safe_dump({"gap_count": len(gaps), "gaps": gaps}, f, allow_unicode=True, sort_keys=False)

    print(f"收割 {len(out)} 个指标：{dict(dist)}")
    print(f"数据缺口 {len(gaps)} 条 → gaps.yaml（信息中心闭环依据）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
