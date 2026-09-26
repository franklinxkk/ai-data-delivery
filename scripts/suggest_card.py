#!/usr/bin/env python3
"""suggest_card.py — 评测资产段：bad case → 修订建议卡片（ai-data-delivery v0.0.2）

RULE-LOOP-01 的出口：登记卡 triage 出归因层之后，自动生成一张"修订建议卡片"，
把证据、建议动作（精确到命令）、影响面、回归占位写成一页，FDE 评审照单执行即可。

用法：
  python suggest_card.py --card badcases/BC001.yaml --out suggest.md
归因层 → 建议动作映射：
  词表层 → patch_model.py syn 补同义词（指标/数据集/概念三目标）
  引擎层 → 检索/生成链路排查；修完 run_eval.py 定向回归
  口径层 → patch_model.py struct 落地口径 + --db 物理库验算；ratio 类检查分子分母
退出码：0 成功；2 登记卡不完整（layer 未定）。
"""
import argparse
import sys

import yaml

LAYER_ACTIONS = {
    "词表层": [
        "确认问句中的业务黑话/别名未命中模型同义词",
        "patch_model.py syn --metric/--dataset/--concept 补同义词（幂等，可反复执行）",
        "补完跑 run_eval.py 定向回归该问句"],
    "引擎层": [
        "保留证据三件套（应答/检索/模型快照），复现检索命中偏差",
        "排查检索打分与生成链路；必要时升级引擎版本",
        "plan_stability.py 抽查同句多次执行的计划一致性"],
    "口径层": [
        "确认指标口径缺失或错误（expr/分子分母/extra_where/time_field）",
        "patch_model.py struct 落地口径，必须 --db 直连物理库验算（0 行拒绝）",
        "reconcile_paths.py 双路径对账，确认指标路径与问数路径一致"],
}


def main():
    ap = argparse.ArgumentParser(description="bad case → 修订建议卡片")
    ap.add_argument("--card", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    c = yaml.safe_load(open(args.card, encoding="utf-8"))
    layer = c.get("layer")
    if not layer or layer not in LAYER_ACTIONS:
        print(f"错误：登记卡 layer 未定或非法（应为：{' / '.join(LAYER_ACTIONS)}）",
              file=sys.stderr)
        return 2

    L = []
    L.append(f"# 修订建议卡片：{c.get('id')}")
    L.append("")
    L.append(f"- 问句：{c.get('question')}")
    L.append(f"- 归因层：**{layer}**　症状：{c.get('symptom', '—')}")
    L.append(f"- 取证时间：{c.get('captured_at', '—')}　来源：{c.get('source', 'capture_case')}")
    L.append("")
    L.append("## 证据")
    L.append("")
    ev = c.get("evidence") or {}
    if ev:
        ms = ev.get("model_snapshot") or {}
        L.append(f"- 模型快照：version={ms.get('modelVersion', '?')} 指标数={ms.get('total', '?')}")
        hits = (ev.get("retrieval") or {}).get("hits") or []
        L.append(f"- 检索命中：{[h.get('name') for h in hits] or '无'}")
        ans = ev.get("answer") or {}
        L.append(f"- 引擎应答：value={ans.get('value')} rejected={ans.get('rejected')}")
        if ans.get("sql"):
            L.append(f"- 实际 SQL：`{ans['sql']}`")
    else:
        L.append("- （无活引擎证据——建议先跑 capture_case.py 补取证）")
    L.append("")
    L.append("## 建议动作")
    L.append("")
    for i, a in enumerate(LAYER_ACTIONS[layer], 1):
        L.append(f"{i}. {a}")
    L.append("")
    L.append("## 影响面")
    L.append("")
    L.append("对修复对象（指标/字段/数据集）执行：")
    L.append("")
    L.append("```")
    L.append("python impact_analysis.py --model <semantic.yaml> --target <修复对象>")
    L.append("```")
    L.append("")
    L.append("## 回归占位")
    L.append("")
    L.append("- [ ] 修复已落地，verify 证据已回填登记卡")
    L.append("- [ ] promote_gold.py 回流评测集（expect 已填）")
    L.append("- [ ] run_eval.py 定向回归通过（附前后对比）")
    L.append("- [ ] 回归 gold_lint.py 无新增 ERROR")
    L.append("")

    with open(args.out, "w", encoding="utf-8") as f:
        f.write("\n".join(L))
    print(f"修订建议卡片 → {args.out}（归因层：{layer}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
