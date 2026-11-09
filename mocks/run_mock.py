#!/usr/bin/env python3
"""run_mock.py — 多领域快速 mock：无需活引擎，端到端自检工具链（ai-data-delivery v0.0.5）

对每个领域场景目录（含 build_db.py + semantic.yaml + cases.json）依次执行：
  1) 建库：运行 build_db.py 生成确定性 SQLite 物理库（固定造数，可复算）
  2) G1 模型自检：check_model.py（零 ERROR 才放行）
  3) G2 gold 体检：gold_lint.py（零 ERROR 才放行）
  4) 模拟引擎：用 reconcile_paths 的口径编译器把结构化指标编译成 SQL 直算物理库，
     生成"引擎应答"actual.jsonl（refusal 用例模拟守卫拒答；declared_conflict 用例
     用另一套口径 SQL 应答，演示豁免留痕）
  5) G3 回归比对：run_eval.py 离线模式（期望 vs 模拟应答，零失败才放行）

用法：
  python run_mock.py --domain retail          # 跑单个领域
  python run_mock.py --all                    # 跑全部领域（退出码取最差）
  python run_mock.py --domain finance --keep  # 保留中间产物（actual.jsonl / report.json）

用例辅助字段（run_eval/gold_lint 会忽略，仅供模拟引擎使用）：
  "metric": "<指标id>"  → 编译该指标完整口径 SQL 直算（验证 filters+extra_where 全量编译）
  "sql": "<原生SQL>"    → 直接执行（演示分组 rows 等编译器不覆盖的形态）
退出码：0 = 所选领域全部通过；1 = 任一环节失败；2 = 用法错误。
"""
import argparse
import json
import os
from pathlib import Path
import sqlite3
import stat
import subprocess
import sys

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.normpath(os.path.join(HERE, "..", "scripts"))
sys.path.insert(0, SCRIPTS)

import reconcile_paths as recon
from _contract import minimal_env


def _plain_path(path):
    """Reject links/reparse points before reading, executing or replacing a file."""
    try:
        info = path.lstat()
    except FileNotFoundError:
        return
    if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
        raise ValueError(f"场景路径不能是符号链接或 junction：{path}")
    if path.is_file() and info.st_nlink > 1:
        raise ValueError(f"场景文件不能是硬链接：{path}")


def managed_domain(domain_dir):
    """Only real, immediate children of this source checkout's mocks directory."""
    root = Path(HERE).resolve(strict=True)
    path = Path(domain_dir)
    if ".." in path.parts or path.name in {"", ".", ".."}:
        raise ValueError("领域必须是 mocks 下的真实一级目录")
    _plain_path(path)
    resolved = path.resolve(strict=True)
    if path.parent.resolve(strict=True) != root or resolved.parent != root or not resolved.is_dir():
        raise ValueError("领域必须是 mocks 下的真实一级目录")
    for name in ("build_db.py", "semantic.yaml", "cases.json", "domain.db", "actual.jsonl", "report.json"):
        child = resolved / name
        _plain_path(child)
        if child.resolve().parent != resolved:
            raise ValueError(f"场景文件超出领域目录：{child}")
        if name in {"build_db.py", "semantic.yaml", "cases.json"} and not child.is_file():
            raise ValueError(f"领域缺少场景文件：{child}")
        if child.exists() and not child.is_file():
            raise ValueError(f"场景路径必须是普通文件：{child}")
    return resolved


def domain_from_name(name):
    if not isinstance(name, str) or not name or name in {".", ".."} or any(c in name for c in "/\\:\0") or name[-1] in ". ":
        raise ValueError("--domain 只接受 mocks 下的一级目录名，不接受路径")
    return managed_domain(Path(HERE) / name)


def run_step(name, cmd, cwd):
    domain = managed_domain(cwd)
    if not isinstance(cmd, (list, tuple)) or not cmd:
        raise ValueError("mock 步骤必须使用已知脚本参数数组")
    script = Path(cmd[0])
    if not script.is_absolute():
        script = domain / script
    _plain_path(script)
    script = script.resolve(strict=True)
    allowed = {domain / "build_db.py"} | {Path(SCRIPTS).resolve() / filename for filename in
               ("check_model.py", "gold_lint.py", "run_eval.py")}
    if script not in allowed:
        raise ValueError(f"mock 步骤不允许执行此脚本：{script}")
    p = subprocess.run([sys.executable, str(script)] + list(cmd[1:]), capture_output=True, text=True,
                       encoding="utf-8", errors="replace", cwd=domain, env=minimal_env())
    ok = p.returncode == 0
    print(f"[{'PASS' if ok else 'FAIL'}] {name}")
    if not ok:
        tail = "\n".join(((p.stdout or "") + (p.stderr or "")).strip().splitlines()[-5:])
        print("      " + tail.replace("\n", "\n      "))
    return ok


def norm(x):
    try:
        return round(float(x), 4)
    except (TypeError, ValueError):
        return x


def gen_actual(domain_dir, db_path, recon):
    """模拟引擎：cases.json → actual.jsonl（编译指标口径 / 执行原生 SQL / 守卫拒答）。"""
    domain_dir = managed_domain(domain_dir)
    if Path(db_path).resolve() != domain_dir / "domain.db":
        raise ValueError("模拟数据库必须是当前领域的 domain.db")
    m = yaml.safe_load((domain_dir / "semantic.yaml").read_text(encoding="utf-8"))
    cases = json.loads((domain_dir / "cases.json").read_text(encoding="utf-8"))
    if isinstance(cases, dict):
        cases = cases.get("cases", cases.get("gold_results"))
    ds_index = {d["name"]: d for d in m.get("datasets", [])}
    names = set(ds_index) | {d.get("source") for d in m.get("datasets", [])}
    mt_index = {t["id"]: t for t in m.get("metrics", [])}
    conn = sqlite3.connect(db_path)
    out = []
    for c in cases:
        cid = c["id"]
        e = c.get("expect") or {}
        if c.get("expect_reject") or e.get("type") == "refusal":
            out.append({"id": cid, "refused": True})
            continue
        if c.get("metric"):
            sql, why = recon.compile_metric_sql(
                mt_index[c["metric"]], ds_index.get(mt_index[c["metric"]].get("dataset")), names)
            if not sql:
                conn.close()
                raise RuntimeError(f"{cid} 指标 {c['metric']} 不可编译：{why}")
        elif c.get("sql"):
            sql = c["sql"]
        else:
            conn.close()
            raise RuntimeError(f"{cid} 缺 metric/sql 辅助字段，模拟引擎无法应答")
        rows = conn.execute(sql).fetchall()
        rec = {"id": cid, "rows": [list(r) for r in rows]}
        if len(rows) == 1 and len(rows[0]) == 1:
            rec["value"] = norm(rows[0][0])
        out.append(rec)
    conn.close()
    path = os.path.join(domain_dir, "actual.jsonl")
    with open(path, "w", encoding="utf-8") as f:
        for rec in out:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return path


def run_domain(domain_dir):
    domain_dir = managed_domain(domain_dir)
    name = os.path.basename(domain_dir)
    print(f"\n===== 领域 mock：{name} =====")
    db_path = os.path.join(domain_dir, "domain.db")
    if os.path.exists(db_path):
        os.remove(db_path)
    if not run_step("1 建库 build_db", [os.path.join(domain_dir, "build_db.py")], domain_dir):
        return False
    if not run_step("2 G1 模型自检 check_model",
                    [os.path.join(SCRIPTS, "check_model.py"), "-f", "semantic.yaml"], domain_dir):
        return False
    if not run_step("3 G2 gold 体检 gold_lint",
                    [os.path.join(SCRIPTS, "gold_lint.py"), "--cases", "cases.json",
                     "--model", "semantic.yaml"], domain_dir):
        return False
    actual = gen_actual(domain_dir, db_path, recon)
    ok = run_step("4 G3 回归比对 run_eval（离线）",
                  [os.path.join(SCRIPTS, "run_eval.py"), "--gold", "cases.json",
                   "--actual", actual, "--mode", "mock", "--model", "semantic.yaml",
                   "--db", db_path, "--report",
                   os.path.join(domain_dir, "report.json")], domain_dir)
    return ok


def main():
    ap = argparse.ArgumentParser(description="多领域快速 mock 自检")
    ap.add_argument("--domain", help="领域目录名（mocks/ 下）")
    ap.add_argument("--all", action="store_true", help="跑全部领域")
    ap.add_argument("--keep", action="store_true", help="保留中间产物（默认也保留，便于查阅）")
    args = ap.parse_args()

    if args.all:
        domains = sorted(d for d in os.listdir(HERE)
                         if os.path.isdir(os.path.join(HERE, d))
                         and os.path.exists(os.path.join(HERE, d, "semantic.yaml")))
    elif args.domain:
        domains = [args.domain]
    else:
        print("错误：--domain <名> 或 --all 二选一", file=sys.stderr)
        return 2
    if not domains:
        print("错误：未找到任何领域场景", file=sys.stderr)
        return 2

    try:
        selected = [(name, domain_from_name(name)) for name in domains]
        results = {name: run_domain(path) for name, path in selected}
    except (ValueError, OSError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2
    print("\n===== MOCK 总览 =====")
    for d, ok in results.items():
        print(f"[{'PASS' if ok else 'FAIL'}] {d}")
    failed = [d for d, ok in results.items() if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} 个领域通过")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
