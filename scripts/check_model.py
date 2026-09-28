#!/usr/bin/env python3
"""check_model.py — semantic.yaml 铁律 lint（ai-data-delivery v0.0.6）

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
  E12 本体实体 name 缺失/重复、is_a 指向未声明实体、is_a 成环
  E13 本体关系端点不是已声明本体实体、缺 predicate、mapping 非法，
       或 mapping≠equi_key 而无 note（无键关系必须写明落地说明）
  E14 投影回指悬空：dataset/relationship 的 ontology_ref 指向不存在的本体对象
       （含声明了 ontology_ref 但模型无 ontology 段）
  E15 无键关系被投影：合同 relationship 的 ontology_ref 指向 mapping≠equi_key 的本体关系
       （合同只承载等值键关系；本体表达得了 ≠ 合同该承载）
  E16 概念禁用词与自身 term/synonyms 冲突（禁用词是被禁止的说法，不能同时是别名）
  E17 指标 on_zero_denominator 非法（∈ null/zero/error；缺省为 null）
  W01 数据集缺 ai.instructions（表描述是给模型的路由+边界指令，不是给人看的说明书）
  W02 维度字段缺 enum（若该字段是状态/枚举类，缺字典则模型写错过滤条件且不报错）
  W03 数据集无 time 角色字段（时间围栏无法落地，"今天/本月"必错）
  W04 structured 指标缺 time_field
  W05 structured 指标还是 草案 状态
  W06 tenant_field 指向不存在字段
  W07 本体实体未被任何数据集投影且未写 unprojected_reason（未投影必须说明原因）
  W08 本体关系 mapping=equi_key 但未被任何合同关系投影（声明了可落地关系却未落地）
  W09 同一 domain 内两个概念认领同一 synonym（路由会歧义）
  W10 概念 valid_to 已过期（需复审：续期、下线或改口径）
  W11 比率指标有分母但未显式声明 on_zero_denominator（缺省 null 会把除零静默变 NULL）

本体段是声明式事实清单：本工具只做静态结构检查与两层对账，不做任何跨声明推导
（不推 is-a 传递、不推子类继承关系、不推逆关系、不做逻辑一致性判定；不是 OWL/SHACL）。
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
        else:
            from _contract import keys
            if not set(keys(ds["primary_key"])) <= field_names(ds):
                rep.error("E02", where, "primary_key 引用了不存在的字段")
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
    from check_join_graph import validate_relation
    ds_index = {d["name"]: d for d in m.get("datasets", [])}
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
        if trav:
            try:
                validate_relation(r, ds_index)
            except (ValueError, TypeError) as exc:
                rep.error("E09", where, str(exc))
        elif not isinstance(trav, bool):
            rep.error("E09", where, "traversable 必须为布尔值")
        if trav is False and not r.get("note"):
            rep.warn("E09", where, "不可遍历关系应写明原因（note），防静默弱 join")


def check_concepts(m, rep, ds_index):
    import datetime as dt
    seen = set()
    synonym_owner = {}
    for c in m.get("concepts", []) or []:
        term = c.get("term", "?")
        where = f"concept[{term}]"
        if term in seen:
            rep.error("E11", where, "概念 term 重复")
        seen.add(term)
        own_words = {term} | set(c.get("synonyms", []) or []) | set(c.get("aliases", []) or [])
        forbidden = set(c.get("forbidden", []) or [])
        if forbidden & own_words:
            rep.error("E16", where, f"禁用词与自身说法冲突：{sorted(forbidden & own_words)}")
        domain = c.get("domain", "")
        for syn in (c.get("synonyms", []) or []) + (c.get("aliases", []) or []):
            key = (domain, syn)
            if key in synonym_owner and synonym_owner[key] != term:
                rep.warn("W09", where,
                         f"synonym {syn!r} 在同 domain 内已被概念 {synonym_owner[key]!r} 认领")
            synonym_owner.setdefault(key, term)
        valid_to = c.get("valid_to")
        if valid_to:
            try:
                if dt.date.fromisoformat(str(valid_to)[:10]) < dt.date.today():
                    rep.warn("W10", where, f"valid_to {valid_to} 已过期（需复审：续期/下线/改口径）")
            except ValueError:
                rep.warn("W10", where, f"valid_to {valid_to!r} 不是 ISO 日期")
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


def check_ontology(m, rep):
    """本体段结构检查 + 合同投影对账。ontology 段是声明式事实清单，不做推理。"""
    from _contract import MAPPINGS, ont_entities, ont_relations, ont_relation_id
    entities = ont_entities(m)
    relations = ont_relations(m)
    datasets = m.get("datasets", []) or []
    contract_rels = m.get("relationships", []) or []
    has_refs = any(d.get("ontology_ref") for d in datasets) or \
        any(r.get("ontology_ref") for r in contract_rels)
    if not entities and not relations:
        if has_refs:
            rep.error("E14", "model", "声明了 ontology_ref 但模型无 ontology 段")
        return
    ent_names = set()
    for e in entities:
        name = e.get("name")
        where = f"ontology.entity[{name or '?'}]"
        if not name:
            rep.error("E12", "ontology.entity[?]", "缺 name")
            continue
        if name in ent_names:
            rep.error("E12", where, "本体实体 name 重复")
        ent_names.add(name)
    for e in entities:
        name, parent = e.get("name"), e.get("is_a")
        if parent is not None and parent not in ent_names:
            rep.error("E12", f"ontology.entity[{name}]", f"is_a 指向未声明实体 {parent!r}")
    # is_a 环检测（静态结构检查，不是推理）
    parent_of = {e.get("name"): e.get("is_a") for e in entities if e.get("name")}
    for start in parent_of:
        seen, node = set(), start
        while node in parent_of and parent_of[node]:
            node = parent_of[node]
            if node in seen or node == start:
                rep.error("E12", f"ontology.entity[{start}]", "is_a 成环")
                break
            seen.add(node)
    rel_ids = set()
    for r in relations:
        rid = ont_relation_id(r)
        where = f"ontology.relation[{rid}]"
        if rid in rel_ids:
            rep.error("E11", where, "本体关系 id 重复（平行边请显式给 id）")
        rel_ids.add(rid)
        for ep in (r.get("from"), r.get("to")):
            if ep not in ent_names:
                rep.error("E13", where, f"端点 {ep!r} 不是已声明本体实体")
        if not r.get("predicate"):
            rep.error("E13", where, "缺 predicate（语义谓词是关系的核心，键只是落地方式之一）")
        mapping = r.get("mapping")
        if mapping not in MAPPINGS:
            rep.error("E13", where, f"mapping 非法：{mapping!r}（∈ {sorted(MAPPINGS)}）")
        elif mapping != "equi_key" and not r.get("note"):
            rep.error("E13", where, "mapping≠equi_key 必须写 note（无键关系的落地说明）")
    # 投影对账
    projected_entities = set()
    for d in datasets:
        ref = d.get("ontology_ref")
        if ref:
            if ref not in ent_names:
                rep.error("E14", f"dataset[{d.get('name','?')}]", f"ontology_ref 指向未声明实体 {ref!r}")
            projected_entities.add(ref)
    ont_rel_by_id = {ont_relation_id(r): r for r in relations}
    projected_rel_ids = set()
    for r in contract_rels:
        ref = r.get("ontology_ref")
        if not ref:
            continue
        where = f"relationship[{r.get('from','?')}→{r.get('to','?')}]"
        target = ont_rel_by_id.get(ref)
        if target is None:
            rep.error("E14", where, f"ontology_ref 指向未声明本体关系 {ref!r}")
        elif target.get("mapping") != "equi_key":
            rep.error("E15", where,
                      f"无键关系不得投影：{ref!r} 的 mapping={target.get('mapping')!r}，合同只承载 equi_key")
        projected_rel_ids.add(ref)
    for e in entities:
        name = e.get("name")
        if name and name not in projected_entities and not e.get("unprojected_reason"):
            rep.warn("W07", f"ontology.entity[{name}]",
                     "未被任何数据集投影且未写 unprojected_reason")
    for r in relations:
        rid = ont_relation_id(r)
        if r.get("mapping") == "equi_key" and rid not in projected_rel_ids:
            rep.warn("W08", f"ontology.relation[{rid}]", "equi_key 关系未被任何合同关系投影")


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
            if den:
                policy = mt.get("on_zero_denominator")
                if policy is None:
                    rep.warn("W11", where, "有分母但未声明 on_zero_denominator（缺省 null 会把除零静默变 NULL）")
                elif policy not in {"null", "zero", "error"}:
                    rep.error("E17", where, f"on_zero_denominator 非法：{policy!r}（∈ null/zero/error）")
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
    if not isinstance(m, dict) or not m.get("datasets"):
        print("[ERROR E00] 模型必须包含非空 datasets")
        return 1
    ds_index = {d.get("name"): d for d in m.get("datasets", []) or []}

    check_datasets(m, rep)
    check_relationships(m, rep, set(ds_index))
    check_concepts(m, rep, ds_index)
    check_metrics(m, rep, ds_index)
    check_ontology(m, rep)

    for line in rep.errors + rep.warnings:
        print(line)
    from _contract import ont_entities, ont_relations
    print(f"\nlint 结果：{len(rep.errors)} ERROR / {len(rep.warnings)} WARN"
          f"（数据集 {len(ds_index)}，关系 {len(m.get('relationships', []) or [])}，"
          f"概念 {len(m.get('concepts', []) or [])}，指标 {len(m.get('metrics', []) or [])}，"
          f"本体实体 {len(ont_entities(m))}，本体关系 {len(ont_relations(m))}）")
    if rep.errors or (args.strict and rep.warnings):
        print("门禁：未通过")
        return 1
    print("门禁：通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
