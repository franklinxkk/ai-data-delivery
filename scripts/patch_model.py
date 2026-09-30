#!/usr/bin/env python3
"""patch_model.py — semantic.yaml 幂等补丁器（ai-data-delivery v0.0.5）

权威源 Schema（semantic.yaml，唯一事实源）：
  datasets[]:       name / display_name / source(物理表) / grain / primary_key
                    / ai{instructions, synonyms[]} / tenant_field
                    / fields[]{name,cn,role(pk|fk|dim|measure|time|attr),type,enum,sensitive,synonyms}
  concepts[]:       term / aliases[] / expand{dataset,field,values[] | union[]} / note
  relationships[]:  from / to / type / join_key / cardinality / traversable / note
  metrics[]:        id / name / type(count|ratio|sum|avg|list) / structured / dataset
                    / expr / numerator{expr,dialect} / denominator{expr,dialect}
                    / extra_where / time_field / unit / grain
                    / caliber{note,basis} / synonyms[] / status

四个子命令（全部幂等：内容无变化时不写盘）：

  syn    补同义词（自然问法）。三类目标：
           python patch_model.py -f semantic.yaml syn 指标ID 词1 词2 ...
           python patch_model.py -f semantic.yaml syn --dataset 数据集名 词1 词2 ...
           python patch_model.py -f semantic.yaml syn --concept 概念名 词1 词2 ...

  struct 结构化指标（自含全口径：expr/分子分母 + extra_where + time_field）：
           python patch_model.py -f semantic.yaml struct 指标ID \
               --expr "COUNT(*)" --extra-where "rectify_status = '待整改'" \
               --time-field stat_date --unit 条 \
               --caliber-note "待整改重大隐患" --caliber-basis "内部约定" \
               --synonym 自然问法1 --synonym 自然问法2
           新建指标（默认必须已存在，防笔误造重复指标）：
               ... struct 新ID --create --name 指标名 --type count --dataset 数据集 ...
           ratio 型用 --numerator/--denominator（禁止行级平均）：
               ... struct 指标ID --numerator "SUM(a)" --denominator "SUM(b)"

  set    改键值：
           python patch_model.py -f semantic.yaml set 指标ID --key extra_where --value "..."
           python patch_model.py -f semantic.yaml set --path engine.timezone --value Asia/Shanghai

提供 --db 时编译完整单表口径并检查可执行性；提供 --expect 时再对拍期望。
错误/NULL 拒绝写入（--force 会绕过，不能作为验证证据）；零值本身不是错误。
未提供 --db 时只生成草案并提醒未验证。

注意：PyYAML 重写会丢失原文件注释，重要注释请迁移到 caliber.note / description 字段。
"""
import argparse
import copy
import re
import sys

import yaml

from _contract import load as _contract_load


# ---------- 基础读写 ----------

def load(path):
    return _contract_load(path) or {}


def dump_if_changed(path, before, after):
    if before == after:
        print("no change（已是最新，幂等跳过）")
        return False
    import shutil
    backup = path + ".bak"
    shutil.copyfile(path, backup)
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(after, f, allow_unicode=True, sort_keys=False,
                       default_flow_style=False, width=120)
    print(f"patched ✓（原文已备份 → {backup}）")
    return True


def err(msg):
    print(f"错误：{msg}", file=sys.stderr)
    return 1


def find_one(items, key, value):
    for item in items or []:
        if isinstance(item, dict) and item.get(key) == value:
            return item
    return None


def merge_synonyms(existing, new_words):
    """保序去重合并：已有顺序不动，新词追加。"""
    out = list(existing or [])
    added = []
    for w in new_words:
        if w not in out:
            out.append(w)
            added.append(w)
    return out, added


# ---------- 物理库验算 ----------

def compile_full_sql(model, mt):
    """指标完整口径（expr/分子分母 + filters + extra_where）→ 可执行 SQL。返回 (sql, err)。"""
    from _sql import compile_single
    ds = find_one(model.get("datasets"), "name", mt.get("dataset"))
    return compile_single(mt, ds)


def verify_with_db(db_path, model, mt, expect=None, tol=1e-6):
    """对物理库验算 patched 后的完整口径。返回 (ok, detail)。
    给了 --expect 就对拍数值；没给只证明可执行且非 NULL，不证明业务正确。"""
    sql, err_ = compile_full_sql(model, mt)
    if err_:
        return False, err_
    try:
        from _contract import readonly
        conn = readonly(db_path)
        row = conn.execute(sql).fetchone()
        conn.close()
    except Exception as e:
        return False, f"验算 SQL 执行失败：{e}\n  SQL: {sql}"
    v = row[0] if row else None
    if v is None:
        return False, f"验算结果为 NULL（口径可能过严或枚举值写错）\n  SQL: {sql}"
    if expect is not None:
        try:
            ok = abs(float(v) - float(expect)) <= tol
        except (TypeError, ValueError):
            return False, f"验算结果 {v!r} 非数值，无法与 --expect {expect} 对拍\n  SQL: {sql}"
        if not ok:
            return False, (f"验算对拍失败：实算 {v} ≠ 期望 {expect}（容差 {tol}）\n  SQL: {sql}\n"
                           "  口径改错了还是金标准变了？先确认再 --force")
        return True, f"验算对拍通过：{v} ≈ {expect}\n  SQL: {sql}"
    return True, f"可执行性检查通过：值 {v}；未提供 --expect，业务口径正确性未验证\n  SQL: {sql}"


# ---------- 子命令 ----------

def cmd_syn(args):
    data = load(args.file)
    before = copy.deepcopy(data)
    words = list(args.words or []) + list(args.synonym or [])
    if not words:
        return err("syn 需要一个以上同义词（位置参数或 --synonym）")

    if args.dataset:
        ds = find_one(data.get("datasets"), "name", args.target)
        if ds is None:
            return err(f"数据集 {args.target!r} 不存在于 datasets")
        syns = ds.setdefault("ai", {}).setdefault("synonyms", [])
        merged, added = merge_synonyms(syns, words)
        ds["ai"]["synonyms"] = merged
        print(f"数据集 {args.target!r} 新增同义词 {added}" if added else "同义词已存在")
    elif args.concept:
        c = find_one(data.get("concepts"), "term", args.target)
        if c is None:
            return err(f"概念 {args.target!r} 不存在于 concepts")
        merged, added = merge_synonyms(c.setdefault("aliases", []), words)
        c["aliases"] = merged
        print(f"概念 {args.target!r} 新增别名 {added}" if added else "别名已存在")
    else:
        m = find_one(data.get("metrics"), "id", args.target)
        if m is None:
            return err(f"指标 {args.target!r} 不存在于 metrics（按 id 寻址；数据集用 --dataset，概念用 --concept）")
        merged, added = merge_synonyms(m.setdefault("synonyms", []), words)
        m["synonyms"] = merged
        print(f"指标 {args.target!r} 新增同义词 {added}" if added else "同义词已存在")

    dump_if_changed(args.file, before, data)
    return 0


def cmd_struct(args):
    data = load(args.file)
    before = copy.deepcopy(data)
    metrics = data.setdefault("metrics", [])
    m = find_one(metrics, "id", args.target)

    if m is None:
        if not args.create:
            return err(f"指标 {args.target!r} 不存在；确认 id 后重试，或显式加 --create 新建")
        missing = [k for k in ("name", "type", "dataset") if not getattr(args, k)]
        if missing:
            return err(f"--create 需提供 --name/--type/--dataset，缺：{missing}")
        if find_one(data.get("datasets"), "name", args.dataset) is None:
            return err(f"数据集 {args.dataset!r} 不存在，先建数据集再挂指标")
        m = {"id": args.target, "name": args.name, "type": args.type,
             "dataset": args.dataset, "status": "草案", "synonyms": []}
        metrics.append(m)
        print(f"新建指标 {args.target!r}（status=草案，验收后改 已发布）")

    # 幂等写入（先改内存副本，验算不过不落盘）
    m["structured"] = True
    if args.expr:
        m["expr"] = args.expr
        m.pop("numerator", None)
        m.pop("denominator", None)
    if args.numerator or args.denominator:
        if not (args.numerator and args.denominator):
            return err("ratio 口径必须同时给 --numerator 与 --denominator（禁行级平均）")
        m["numerator"] = {"expr": args.numerator, "dialect": "ANSI_SQL"}
        m["denominator"] = {"expr": args.denominator, "dialect": "ANSI_SQL"}
        m.pop("expr", None)
    if args.extra_where is not None:
        m["extra_where"] = args.extra_where
    if args.time_field:
        m["time_field"] = args.time_field
    if args.unit:
        m["unit"] = args.unit
    if args.grain:
        m["grain"] = args.grain
    if args.caliber_note or args.caliber_basis:
        cal = m.setdefault("caliber", {})
        if args.caliber_note:
            cal["note"] = args.caliber_note
        if args.caliber_basis:
            cal["basis"] = args.caliber_basis
    if args.synonym:
        merged, added = merge_synonyms(m.get("synonyms"), args.synonym)
        m["synonyms"] = merged
        if added:
            print(f"同步补充同义词 {added}")

    if not (m.get("expr") or m.get("numerator")):
        return err("结构化指标必须提供 --expr 或 --numerator/--denominator")
    if m.get("type") == "ratio":
        expr_text = " ".join([m.get("expr", ""),
                              (m.get("numerator") or {}).get("expr", ""),
                              (m.get("denominator") or {}).get("expr", "")])
        if re.search(r"\bAVG\s*\(", expr_text, re.I):
            return err("ratio 指标禁止行级平均（DEC-METRIC-01）：请用 SUM/SUM 分子分母")

    # 验算（铁律：写口径前必须验算；验算对象是 patched 后的完整口径——filters + extra_where 全量）
    if args.db:
        ok, detail = verify_with_db(args.db, data, m, expect=args.expect, tol=args.tol)
        print(detail)
        if not ok and not args.force:
            print("验算未通过，拒绝写入（确认无误后加 --force 强制写入）", file=sys.stderr)
            return 2
        if not ok:
            print("warning：--force 生效，验算未通过仍写入（必须在交付说明中声明）", file=sys.stderr)
    else:
        print("提醒：未提供 --db，本次口径写入未经物理库验算——交付前必须补验算并留痕", file=sys.stderr)
    print("边界声明：验算只保证口径可执行且非 NULL（或与 --expect 对拍一致）；"
          "口径语义正确性仍须金标准用例 run_eval 定向回归把关。")

    if m != find_one(before.get("metrics"), "id", args.target):
        m["status"] = "草案"
    dump_if_changed(args.file, before, data)
    n = sum(1 for t in metrics if t.get("structured"))
    print(f"structured: {n}/{len(metrics)}")
    return 0


def cmd_set(args):
    data = load(args.file)
    before = copy.deepcopy(data)
    try:
        value = yaml.safe_load(args.value)
    except yaml.YAMLError:
        value = args.value

    if args.path:
        keys = args.path.split(".")
        node = data
        for k in keys[:-1]:
            nxt = node.get(k)
            if not isinstance(nxt, dict):
                nxt = {}
                node[k] = nxt
            node = nxt
        node[keys[-1]] = value
        print(f"set {args.path} = {value!r}")
    else:
        if not args.key:
            return err("set 指标键值需要 --key 与 --value；全局点路径用 --path")
        m = find_one(data.get("metrics"), "id", args.target)
        if m is None:
            return err(f"指标 {args.target!r} 不存在")
        m[args.key] = value
        print(f"set {args.target}.{args.key} = {value!r}")

    dump_if_changed(args.file, before, data)
    return 0


def main():
    ap = argparse.ArgumentParser(description="semantic.yaml 幂等补丁器（v0.0.5）")
    ap.add_argument("-f", "--file", required=True, help="semantic.yaml 路径")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("syn", help="补同义词（指标/数据集/概念）")
    p.add_argument("target", help="指标 id；或配合 --dataset/--concept 的目标名")
    p.add_argument("words", nargs="*")
    p.add_argument("--dataset", action="store_true", help="target 按数据集名解析")
    p.add_argument("--concept", action="store_true", help="target 按概念 term 解析")
    p.add_argument("--synonym", action="append", default=[])
    p.set_defaults(fn=cmd_syn)

    p = sub.add_parser("struct", help="结构化指标（自含全口径）")
    p.add_argument("target", help="指标 id")
    p.add_argument("--expr", default=None)
    p.add_argument("--numerator", default=None, help="ratio 分子表达式")
    p.add_argument("--denominator", default=None, help="ratio 分母表达式")
    p.add_argument("--extra-where", dest="extra_where", default=None)
    p.add_argument("--time-field", dest="time_field", default=None)
    p.add_argument("--unit", default=None)
    p.add_argument("--grain", default=None)
    p.add_argument("--caliber-note", dest="caliber_note", default=None)
    p.add_argument("--caliber-basis", dest="caliber_basis", default=None)
    p.add_argument("--synonym", action="append", default=[])
    p.add_argument("--create", action="store_true", help="指标不存在时新建（需 --name/--type/--dataset）")
    p.add_argument("--name", default=None)
    p.add_argument("--type", default=None)
    p.add_argument("--dataset", default=None)
    p.add_argument("--db", default=None, help="物理库（sqlite）路径：写入前自动验算完整口径")
    p.add_argument("--expect", default=None,
                   help="期望值对拍：验算结果与之一致才允许写入（如金标准值 15）")
    p.add_argument("--tol", type=float, default=1e-6, help="--expect 对拍容差")
    p.add_argument("--force", action="store_true", help="验算未通过仍强制写入（须声明）")
    p.set_defaults(fn=cmd_struct)

    p = sub.add_parser("set", help="改键值（指标键或全局点路径）")
    p.add_argument("target", nargs="?", default=None, help="指标 id（用 --path 时省略）")
    p.add_argument("--key", default=None)
    p.add_argument("--path", default=None, help="全局点路径，如 engine.timezone")
    p.add_argument("--value", required=True)
    p.set_defaults(fn=cmd_set)

    args = ap.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
