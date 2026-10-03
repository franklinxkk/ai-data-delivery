#!/usr/bin/env python3
"""verify_grades.py — 分级测试装置验证 harness（诊断金标准比对，多领域版）。

目录约定：tests/fixtures/grades/<领域>/<档位>/（档位目录含 expected_diagnostics.yaml）。
对每个档位依次执行：
  1) 建库：运行该档 build_db.py 生成确定性 SQLite 物理库
  2) check_model：断言退出码一致、期望 ERROR/WARN 码 ⊆ 实际诊断（子集断言，允许新规则加报）
  3) check_constraints：断言整体状态一致；声明 failed_ids 时做精确集合断言（脏数据必须被对应规则抓到）
  4) reconcile_paths：档位声明了 reconcile.metrics 时，断言指标直算值与金标准一致（4 位小数）
  5) 打印该档指引动作（guidance）——工具的产出不只是红绿灯，还有下一步建议

用法：
  python verify_grades.py                     # 验证全部领域全部档位
  python verify_grades.py --grade L1          # 所有领域的 L1 档
  python verify_grades.py --grade med_kpi/L1  # 指定领域指定档
退出码：0 = 所有档位诊断符合金标准；1 = 任一不符；2 = 用法错误。
"""
import argparse
import os
import re
import subprocess
import sys
import tempfile

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.normpath(os.path.join(HERE, "..", "..", "..", "scripts"))

RE_ERR = re.compile(r"\[ERROR\s+(\w+)\]")
RE_WARN = re.compile(r"\[WARN\s+(\w+)\]")
RE_METRIC = re.compile(r"\[computed_only\]\s+(\S+)\s+(-?[0-9.]+)")


def run(cmd, cwd=None):
    env = dict(os.environ, PYTHONIOENCODING="utf-8")  # Windows 控制台默认 GBK，强制子进程 UTF-8
    p = subprocess.run([sys.executable] + cmd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", cwd=cwd, env=env)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def check_subset(label, expected, actual, failures):
    exp_set, act_set = set(expected or []), set(actual)
    missing = exp_set - act_set
    if missing:
        failures.append(f"{label} 缺诊断码：{sorted(missing)}（实际：{sorted(act_set)}）")
        return f"{label} ✗ 缺 {sorted(missing)}"
    return f"{label} ✓ {sorted(exp_set) if exp_set else '（无声明）'}"


def verify_grade(gdir, label):
    exp = yaml.safe_load(open(os.path.join(gdir, "expected_diagnostics.yaml"), encoding="utf-8"))
    print(f"\n===== {label} {exp.get('title', '')} =====")
    failures = []

    # 1) 建库
    code, out = run(["build_db.py"], cwd=gdir)
    if code != 0:
        print(out)
        return False, [f"建库失败 exit={code}"]

    # 2) check_model
    cm = exp.get("check_model") or {}
    code, out = run([os.path.join(SCRIPTS, "check_model.py"), "-f",
                     os.path.join(gdir, "semantic.yaml")])
    errors, warns = RE_ERR.findall(out), RE_WARN.findall(out)
    if code != cm.get("exit"):
        failures.append(f"check_model 退出码期望 {cm.get('exit')} 实际 {code}")
    print(check_subset("check_model ERROR", cm.get("errors"), errors, failures))
    print(check_subset("check_model WARN ", cm.get("warns"), warns, failures))
    print(f"           （实际 {len(errors)} ERROR / {len(warns)} WARN，exit={code}）")

    # 3) check_constraints
    cc = exp.get("check_constraints") or {}
    with tempfile.TemporaryDirectory() as td:
        rep_path = os.path.join(td, "cc.yaml")
        run([os.path.join(SCRIPTS, "check_constraints.py"), "--model",
             os.path.join(gdir, "semantic.yaml"), "--db", os.path.join(gdir, "domain.db"),
             "--out", rep_path])
        rep = yaml.safe_load(open(rep_path, encoding="utf-8")) if os.path.exists(rep_path) else {}
    status = (rep or {}).get("status")
    if status != cc.get("status"):
        failures.append(f"constraints 状态期望 {cc.get('status')} 实际 {status}")
    failed_actual = sorted(r["id"] for r in (rep.get("records") or []) if r.get("status") == "fail")
    failed_exp = sorted(cc.get("failed_ids") or [])
    ok = "✓" if status == cc.get("status") and failed_actual == failed_exp else "✗"
    print(f"check_constraints: {status} {ok}（fail 规则：{failed_actual or '无'}）")
    if failed_actual != failed_exp:
        failures.append(f"constraints fail 集合期望 {failed_exp} 实际 {failed_actual}")

    # 4) reconcile（按声明）
    rec = exp.get("reconcile")
    if rec and rec != "skip" and rec.get("metrics"):
        code, out = run([os.path.join(SCRIPTS, "reconcile_paths.py"), "--model",
                         os.path.join(gdir, "semantic.yaml"), "--db", os.path.join(gdir, "domain.db")])
        actual = {m: round(float(v), 4) for m, v in RE_METRIC.findall(out)}
        for m, v in rec["metrics"].items():
            if actual.get(m) != round(float(v), 4):
                failures.append(f"指标 {m} 期望 {v} 实际 {actual.get(m)}")
        print(f"reconcile: {'✓' if not any('指标' in f for f in failures) else '✗'}"
              f"（直算 {len(actual)} 个指标）")
    else:
        print("reconcile: skip（本档未到算指标阶段 / 数据不可信）")

    # 5) 指引动作
    print("指引动作：")
    for i, g in enumerate(exp.get("guidance") or [], 1):
        print(f"  {i}. {g}")
    print(f"下一步：{exp.get('next_grade', '—')}")
    return not failures, failures


def discover():
    """返回 [(label, grade_dir)]：两级扫描 <领域>/<档位>。"""
    found = []
    for domain in sorted(os.listdir(HERE)):
        ddir = os.path.join(HERE, domain)
        if not os.path.isdir(ddir):
            continue
        for grade in sorted(os.listdir(ddir)):
            gdir = os.path.join(ddir, grade)
            if os.path.isdir(gdir) and os.path.exists(os.path.join(gdir, "expected_diagnostics.yaml")):
                found.append((f"{domain}/{grade}", gdir))
    return found


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--grade", help="档位过滤：'L1'（所有领域）或 'med_kpi/L1'（指定领域）")
    args = ap.parse_args()
    found = discover()
    if args.grade:
        found = [(lb, gd) for lb, gd in found
                 if lb == args.grade or lb.endswith("/" + args.grade)]
        if not found:
            print(f"档位 {args.grade} 不存在（现有：{[lb for lb, _ in discover()]}）")
            return 2
    if not found:
        print("未发现任何档位（缺 expected_diagnostics.yaml）")
        return 2
    results = {}
    for label, gdir in found:
        ok, failures = verify_grade(gdir, label)
        results[label] = (ok, failures)
        print(f"[{'PASS' if ok else 'FAIL'}] {label}")
        for f in failures:
            print(f"  ✗ {f}")
    bad = {lb: f for lb, (ok, f) in results.items() if not ok}
    print(f"\n===== 分级验证总览：{len(results) - len(bad)}/{len(results)} 档符合金标准 =====")
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
