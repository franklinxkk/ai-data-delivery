#!/usr/bin/env python3
"""profile_db.py — 盘点段：连库出实测画像（ai-data-delivery v0.0.4）

对源库逐表实测：行数、枚举实测值（低基数列）、空值率、近似粒度（唯一键基数）。
敏感列（身份证/手机号等）只出计数与空值率，不取样值。

用法：
  python profile_db.py --db path/to.db --out inventory/profile.yaml [--enum-max 20]

输出 profile.yaml：
  tables[]: name / row_count / columns[]{name,type,distinct,null_rate,enum_values?,note}
"""
import os
import argparse
import re
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

from _contract import quote, readonly, write

SENSITIVE_PAT = re.compile(r"身份证|手机号|电话|资格证号|证件号|id_card|phone|mobile", re.I)


def ensure_separate_output(db_path, out_path):
    """只读连接不保护输出文件；拒绝路径别名、符号链接或硬链接指向源库。"""
    source, output = Path(db_path), Path(out_path)
    if output.resolve() == source.resolve() or (output.exists() and output.samefile(source)):
        raise ValueError(f"--out 不能指向 --db 数据库或其文件别名：{out_path}；请选择新的画像文件路径")


def profile_table(conn, table, enum_max):
    table_sql = quote(table)
    cols = conn.execute(f"PRAGMA table_info({table_sql})").fetchall()
    # PRAGMA: cid, name, type, notnull, dflt_value, pk
    row_count = conn.execute(f"SELECT COUNT(*) FROM {table_sql}").fetchone()[0]
    out_cols = []
    for _, cname, ctype, _, _, pk in cols:
        rec = {"name": cname, "type": ctype or "", "pk": bool(pk)}
        column_sql = quote(cname)
        n = conn.execute(
            f"SELECT COUNT(DISTINCT {column_sql}) FROM {table_sql}").fetchone()[0]
        nulls = conn.execute(
            f"SELECT COUNT(*) FROM {table_sql} WHERE {column_sql} IS NULL").fetchone()[0]
        rec["distinct"] = n
        rec["null_rate"] = round(nulls / row_count, 4) if row_count else 0
        if pk and row_count:
            rec["grain_hint"] = "唯一" if n == row_count else f"有重复({row_count - n} 行)"
        if SENSITIVE_PAT.search(cname):
            rec["note"] = "敏感列：不取样"
        elif 0 < n <= enum_max:
            vals = [r[0] for r in conn.execute(
                f"SELECT DISTINCT {column_sql} FROM {table_sql} WHERE {column_sql} IS NOT NULL "
                f"ORDER BY 1 LIMIT {enum_max}").fetchall()]
            rec["enum_values"] = [str(v) for v in vals]
        out_cols.append(rec)
    return {"name": table, "row_count": row_count, "columns": out_cols}


def main():
    ap = argparse.ArgumentParser(description="源库实测画像")
    ap.add_argument("--db", required=True)
    ap.add_argument("--out", required=True, help="输出文件路径（如 profile.yaml；注意：是文件不是目录）")
    ap.add_argument("--enum-max", type=int, default=20, help="枚举候选列的基数上限")
    args = ap.parse_args()

    if os.path.isdir(args.out):
        print(f"错误：--out 应为输出文件路径（如 profile.yaml），不是目录：{args.out}", file=sys.stderr)
        return 2
    if not os.path.isfile(args.db):
        print(f"错误：--db 数据库文件不存在：{args.db}\n"
              f"检查路径拼写；相对路径以当前工作目录为基准。", file=sys.stderr)
        return 2

    try:
        ensure_separate_output(args.db, args.out)
        with closing(readonly(args.db)) as conn:
            tables = [r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
            profile = [profile_table(conn, t, args.enum_max) for t in sorted(tables)]
        ensure_separate_output(args.db, args.out)
        write(args.out, {"db": args.db, "table_count": len(profile), "tables": profile})
    except (sqlite3.Error, ValueError, OSError) as exc:
        print(f"错误：无法生成数据库画像 {args.db}：{exc}\n"
              "请核对数据库与输出路径、权限和 SQLite 文件格式。", file=sys.stderr)
        return 2
    enum_cols = sum(1 for t in profile for c in t["columns"] if "enum_values" in c)
    print(f"画像完成：{len(profile)} 张表，{enum_cols} 个枚举候选列 → {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
