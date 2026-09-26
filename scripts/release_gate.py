#!/usr/bin/env python3
"""release_gate.py — 运营段：模型发版门禁（ai-data-delivery v0.0.2）

RULE-STATE-01 的收口：模型版本从"草案"到"已发布"必须过门禁，且留下发版日志。
聚合四类闸门，任一不过则拒绝发版：
  G1 模型自检   check_model.py（结构/引用/口径完备性）
  G2 gold 体检  gold_lint.py（评测集自身无矛盾）
  G3 全量回归   run_eval.py 的报告 json（acc 达标，默认 1.0；缺报告则跳过并声明）
  G4 计划稳定   plan_stability.py（可选，需 --endpoint；同句连跑 SQL 指纹一致）

用法：
  python release_gate.py --model semantic.yaml --cases cases.json \
      [--eval-report eval_report.json] [--endpoint http://...] [--min-acc 1.0] \
      [--log release_log.yaml]
退出码：0 全部通过（写入发版日志）；1 任一闸门拒绝；2 用法错误。
"""
import argparse
import json
import os
import subprocess
import sys
import datetime

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))


def run_gate(name, cmd):
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    p = subprocess.run([sys.executable, os.path.join(HERE, cmd[0])] + cmd[1:],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", env=env)
    tail = "\n".join((p.stdout or "").strip().splitlines()[-3:])
    ok = p.returncode == 0
    print(f"[{'PASS' if ok else 'REJ'}] {name}")
    if not ok and tail:
        print("      " + tail.replace("\n", "\n      "))
    return {"gate": name, "ok": ok, "detail": tail}


def main():
    ap = argparse.ArgumentParser(description="模型发版门禁")
    ap.add_argument("--model", required=True)
    ap.add_argument("--cases", required=True, help="gold 用例集")
    ap.add_argument("--eval-report", default=None, help="run_eval.py 的 --out 产物")
    ap.add_argument("--endpoint", default=None, help="给 G4 计划稳定性抽查用")
    ap.add_argument("--min-acc", type=float, default=1.0)
    ap.add_argument("--log", default="release_log.yaml")
    ap.add_argument("--results", default=None, help="gold_results.json（传给 gold_lint）")
    args = ap.parse_args()

    gates = []
    gates.append(run_gate("G1 模型自检", ["check_model.py", "-f", args.model]))
    lint_cmd = ["gold_lint.py", "--cases", args.cases, "--model", args.model]
    if args.results:
        lint_cmd += ["--results", args.results]
    gates.append(run_gate("G2 gold 体检", lint_cmd))

    if args.eval_report and os.path.exists(args.eval_report):
        rep = json.load(open(args.eval_report, encoding="utf-8"))
        s = rep.get("summary", {})
        ok = s.get("passed") == s.get("total") and s.get("acc", 0) >= args.min_acc
        detail = f"acc={s.get('acc')} ({s.get('passed')}/{s.get('total')}) 阈值={args.min_acc}"
        print(f"[{'PASS' if ok else 'REJ'}] G3 全量回归  {detail}")
        gates.append({"gate": "G3 全量回归", "ok": ok, "detail": detail})
    else:
        print("[SKIP] G3 全量回归（无 --eval-report，跳过并声明）")
        gates.append({"gate": "G3 全量回归", "ok": None, "detail": "跳过：未提供回归报告"})

    if args.endpoint:
        gates.append(run_gate("G4 计划稳定", ["plan_stability.py", "--endpoint",
                                              args.endpoint, "--cases", args.cases,
                                              "--times", "3", "--limit", "10"]))
    else:
        print("[SKIP] G4 计划稳定（无 --endpoint，跳过并声明）")
        gates.append({"gate": "G4 计划稳定", "ok": None, "detail": "跳过：未提供端点"})

    failed = [g for g in gates if g["ok"] is False]
    decision = "拒绝发版" if failed else "通过"
    print(f"\n门禁结论：{decision}（{len(gates) - len(failed)} 过 / {len(failed)} 拒）")

    log = []
    if os.path.exists(args.log):
        log = yaml.safe_load(open(args.log, encoding="utf-8")) or []
    m = yaml.safe_load(open(args.model, encoding="utf-8"))
    log.append({
        "ts": datetime.datetime.now().isoformat(timespec="seconds"),
        "model_version": m.get("version", "?"),
        "decision": decision,
        "gates": gates,
    })
    with open(args.log, "w", encoding="utf-8") as f:
        yaml.safe_dump(log, f, allow_unicode=True, sort_keys=False)
    print(f"发版日志 → {args.log}（累计 {len(log)} 条）")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
