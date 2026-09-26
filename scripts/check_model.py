#!/usr/bin/env python3
"""check_model.py — semantic.yaml 铁律 lint（ai-data-delivery v0.0.2）

把五条铁律与评测暴露的元数据缺陷落成机器检查。发布门禁：零 ERROR。

用法：
  python check_model.py -f semantic.yaml [--strict]   # --strict：WARN 也视为失败

规则（E=ERROR / W=WARN）：
  E01 数据集缺 grain（粒度声明是第一约束，粒度不清则聚合必错）
  E02 数据集主键缺失
  E03 字段 role 非法（必须 ∈ pk/fk/dim/measure/time/attr）
  E04 疑似敏感字段未标记（身份证/手机号/资格证号等，必须 sensitive: true 或 allow_llm: false）
  E05 ratio 指标缺分子/分母（禁行级平均 DEC-METRIC-01）
  E06 ratio 指标表达式含 AVG(（行级平均，F01 实测事故）
  E07 structured 指标缺 expr 且缺分子分母（指标必须自含全口径）
  E08 指标挂载的数据集不存在 / 指标 time_field 不在数据集字段中
  E09 关系缺 join_key/cardinality/traversable，或 from/to 不是已声明数据集
       （traversable=true 必须有真实 join_key；弱关联必须 traversable=false 且有 note）
  E10 概念缺可执行展开（expand.dataset/field/values 或 union；无展开条件的概念不准发布）
  E11 id/name/term 重复
  W01 数据集缺 ai.instructions（表描述是给模型的路由+边界指令，不是给人看的说明书）
  W02 维度字段缺 enum（若该字段是状态/枚举类，缺字典则模型写错过滤条件且不报错）
  W03 数据集无 time 角色字段（时间围栏无法落地，"今天/本月"必错）
  W04 structured 指标缺 time_field
  W05 structured 指标还是 草案 状态
  W06 tenant_field 指向不存在字段
"""
import argparse
import re
import sys

import yaml

ROLES = {"pk", "fk", "dim", "measure", "time", "attr"}
SENSITIVE_PAT = re.compile(r"身份证|手机号|电话|资格证号|证件号|license_no|id_card|phone|mobile", re.I)
ENUM_HINT = re.compile(r"状态|类型|等级|类别|方式|来源|是否|标志|类目|岗位|"
                       r"status|type|level|category|class|post|source|is_", re.I)


class Reporter:
    def __init__(self):
        self.errors = []
        self.warnings = []

    def error(self, code, where, msg):
        self.errors.append(f"[ERROR {code}] {where} —— {msg}")

    def warn(self, code, where, msg):
        self.warnings.append(f"[WARN  {code}] {where} —— {msg}")


def field_names(ds):
    return {f.get("name") for f in ds.get("fields", []) if isinstance(f, dict)}


def check_datasets(m, rep):
    seen = set()
    for ds in m.get("datasets", []) or []:
        name = ds.get("name", "?")
        where = f"dataset[{name}]"
        if name in seen:
            rep.error("E11", where, "数据集 name 重复")
        seen.add(name)
        if not ds.get("grain"):
            rep.error("E01", where, "缺 grain 粒度声明（一行代表什么）")
        if not ds.get("primary_key"):
            rep.error("E02", where, "缺 primary_key（去重与 join 依据）")
        if not (ds.get("ai") or {}).get("instructions"):
            rep.warn("W01", where, "缺 ai.instructions（能答什么/不能答什么/必带过滤）")
        tf = ds.get("tenant_field")
        if tf and tf not in field_names(ds):
            rep.warn("W06", where, f"tenant_field {tf!r} 不在字段清单中")
        has_time = False
        for f in ds.get("fields", []) or []:
            fn, fw = f.get("name", "?"), f"{where}.fields[{f.get('name', '?')}]"
            if f.get("role") not in ROLES:
                rep.error("E03", fw, f"role 非法：{f.get('role')!r}（∈ {sorted(ROLES)}）")
            if f.get("role") == "time":
                has_time = True
            cn = str(f.get("cn", ""))
            if f.get("role") == "dim" and not f.get("enum") and ENUM_HINT.search(fn + " " + cn):
                rep.warn("W02", fw, "疑似枚举类 dim 缺 enum 值字典（缺则模型写错过滤条件且不报错）")
            if SENSITIVE_PAT.search(fn) or SENSITIVE_PAT.search(cn):
                if not (f.get("sensitive") or f.get("allow_llm") is False):
                    rep.error("E04", fw, "疑似敏感字段未标记 sensitive: true / allow_llm: false")
        if not has_time:
            rep.warn("W03", where, "无 time 角色字段（时间围栏与相对时间口径无法落地）")


def check_relationships(m, rep, ds_names):
    for r in m.get("relationships", []) or []:
        where = f"relationship[{r.get('from','?')}→{r.get('to','?')}]"
        for ep in (r.get("from"), r.get("to")):
            if ep not in ds_names:
                rep.error("E09", where, f"端点 {ep!r} 不是已声明数据集")
        if r.get("cardinality") is None:
            rep.error("E09", where, "缺 cardinality")
        trav = r.get("traversable")
        if trav is None:
            rep.error("E09", where, "缺 traversable 标记")
        jk = r.get("join_key")
        if trav and not jk:
            rep.error("E09", where, "可遍历关系缺 join_key")
        if trav is False and not r.get("note"):
            rep.warn("E09", where, "不可遍历关系应写明原因（note），防静默弱 join")


def check_concepts(m, rep, ds_index):
    seen = set()
    for c in m.get("concepts", []) or []:
        term = c.get("term", "?")
        where = f"concept[{term}]"
        if term in seen:
            rep.error("E11", where, "概念 term 重复")
        seen.add(term)
        ex = c.get("expand")
        if not ex:
            rep.error("E10", where, "无 expand 展开条件（概念必须可执行，不准发布）")
            continue
        branches = ex.get("union") if isinstance(ex.get("union"), list) else [ex]
        for b in branches:
            dsn, fld = b.get("dataset"), b.get("field")
            if not dsn or not fld or b.get("values") is None:
                rep.error("E10", where, "expand 分支缺 dataset/field/values")
                continue
            ds = ds_index.get(dsn)
            if ds is None:
                rep.error("E10", where, f"expand.dataset {dsn!r} 不存在")
            elif fld not in field_names(ds):
                rep.error("E10", where, f"expand.field {fld!r} 不在 {dsn} 的字段中")


def check_metrics(m, rep, ds_index):
    seen = set()
    for mt in m.get("metrics", []) or []:
        mid = mt.get("id", "?")
        where = f"metric[{mid}]"
        if mid in seen:
            rep.error("E11", where, "指标 id 重复")
        seen.add(mid)

        dsn = mt.get("dataset")
        ds = ds_index.get(dsn)
        if mt.get("structured") and not dsn:
            rep.error("E08", where, "structured 指标缺 dataset 挂载")
        if dsn and ds is None:
            rep.error("E08", where, f"挂载的数据集 {dsn!r} 不存在")
        tf = mt.get("time_field")
        if ds is not None and tf and tf not in field_names(ds):
            rep.error("E08", where, f"time_field {tf!r} 不在 {dsn} 的字段中")

        expr = mt.get("expr") or ""
        num = (mt.get("numerator") or {}).get("expr", "")
        den = (mt.get("denominator") or {}).get("expr", "")
        if mt.get("structured"):
            # 编译强制只针对已结构化指标；未结构化指标保留 legacy 口径式，属"暂不落地"状态
            if mt.get("type") == "ratio":
                if not (num and den) and "/" not in expr:
                    rep.error("E05", where, "ratio 缺分子/分母（numerator/denominator 或含 / 的 expr）")
                if re.search(r"\bAVG\s*\(", " ".join([expr, num, den]), re.I):
                    rep.error("E06", where, "ratio 含 AVG( —— 禁行级平均，必须 SUM/SUM 加权")
            if not (expr or num):
                rep.error("E07", where, "structured 指标缺 expr 且缺分子分母（口径未自含）")
            if not tf:
                rep.warn("W04", where, "structured 指标缺 time_field")
            if mt.get("status") == "草案":
                rep.warn("W05", where, "structured 指标仍为 草案 状态，验收后改 已发布")


def main():
    ap = argparse.ArgumentParser(description="semantic.yaml 铁律 lint")
    ap.add_argument("-f", "--file", required=True)
    ap.add_argument("--strict", action="store_true", help="WARN 也视为失败")
    args = ap.parse_args()

    m = yaml.safe_load(open(args.file, encoding="utf-8")) or {}
    rep = Reporter()
    ds_index = {d.get("name"): d for d in m.get("datasets", []) or []}

    check_datasets(m, rep)
    check_relationships(m, rep, set(ds_index))
    check_concepts(m, rep, ds_index)
    check_metrics(m, rep, ds_index)

    for line in rep.errors + rep.warnings:
        print(line)
    print(f"\nlint 结果：{len(rep.errors)} ERROR / {len(rep.warnings)} WARN"
          f"（数据集 {len(ds_index)}，关系 {len(m.get('relationships', []) or [])}，"
          f"概念 {len(m.get('concepts', []) or [])}，指标 {len(m.get('metrics', []) or [])}）")
    if rep.errors or (args.strict and rep.warnings):
        print("门禁：未通过")
        return 1
    print("门禁：通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
