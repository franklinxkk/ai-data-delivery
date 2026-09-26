#!/usr/bin/env python3
"""run_eval.py — 回归比对器（ai-data-delivery v0.0.2，双模式）

模式 A · 活引擎（FDE 日常：改完一键回归）
  python run_eval.py --endpoint http://localhost:7100 --cases cases.json \
      [--gold-results gold_results.json] [--multihop multihop.json] [--out report.json]
  逐条 POST {endpoint}/api/ask，比对标量/行集合/拒绝判定，
  失败明细带 SQL 与推理链（route/value/sql/reasoning 全留痕）。

模式 B · 离线文件比对（无引擎环境 / CI 存档比对）
  python run_eval.py --gold gold.yaml --actual actual.jsonl [--report report.json]

用例格式自动识别（三种兼容）：
  fmt1  {"id","question","expect":{"type":"scalar|rows|refusal","value|rows","tolerance"}}
  fmt2  {"id","question","gold_rows":[[...]],"expect_reject":false}
  fmt3  {"id","question","gold_sql":"...","expect_table":"..."}  —— 需 --gold-results 提供期望行

actual 文件（模式 B）：jsonl/yaml/json，每条形如
  {"id":"q001","value":123,"rows":null,"refused":false}

退出码：0 = 全部通过；1 = 有失败项；2 = 用法/数据错误。
"""
import argparse
import json
import math
import sys
import urllib.request

import yaml


# ---------- 载入 ----------

def load_structured(path):
    with open(path, encoding="utf-8") as f:
        if path.endswith((".yaml", ".yml")):
            return yaml.safe_load(f)
        return json.load(f)


def load_cases(path):
    data = load_structured(path)
    if isinstance(data, dict):
        for key in ("cases", "gold_results"):
            if key in data:
                return data[key]
        raise ValueError(f"用例文件缺少 cases/gold_results 键：{path}")
    return data


def load_actual_map(path):
    if path.endswith(".jsonl"):
        out = {}
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    item = json.loads(line)
                    out[item["id"]] = item
        return out
    data = load_structured(path)
    if isinstance(data, dict):
        data = data.get("results", data.get("cases", data))
        if isinstance(data, dict):  # {id: record} 形态（如 gold_results.json）
            return data
    return {item["id"]: item for item in data}


# ---------- 断言归一 ----------

def norm_number(x):
    if isinstance(x, bool):
        return x
    if isinstance(x, (int, float)):
        return float(x)
    try:
        return float(str(x).replace(",", "").strip())
    except (ValueError, AttributeError):
        return x


def cmp_scalar(expected, actual, tol=1e-6):
    e, a = norm_number(expected), norm_number(actual)
    if isinstance(e, float) and isinstance(a, float):
        if math.isclose(e, a, rel_tol=tol, abs_tol=tol):
            return True, ""
        return False, f"期望 {e}，实际 {a}"
    ok = e == a
    return ok, "" if ok else f"期望 {e!r}，实际 {a!r}"


def norm_row(row):
    if isinstance(row, dict):
        return tuple(norm_number(v) for v in row.values())
    if isinstance(row, (list, tuple)):
        return tuple(norm_number(v) for v in row)
    return (norm_number(row),)


def cmp_rows(expected_rows, actual_rows):
    """多重集合比对：顺序无关，重复行计数敏感。"""
    if actual_rows is None:
        return False, "实际结果无 rows"
    exp = sorted(map(repr, (norm_row(r) for r in expected_rows)))
    act = sorted(map(repr, (norm_row(r) for r in actual_rows)))
    if exp == act:
        return True, ""
    missing = [r for r in exp if r not in act]
    extra = [r for r in act if r not in exp]
    return False, f"行集合不一致：缺少 {missing[:3]}，多出 {extra[:3]}"


# ---------- 用例期望归一（三种格式 → 统一 expect） ----------

def unify_expect(case, gold_results):
    """返回 dict：{kind: refusal|rows|scalar|sql_rows|none, value?, rows?, tolerance?}"""
    if "expect" in case and isinstance(case["expect"], dict):  # fmt1
        e = case["expect"]
        return {"kind": e.get("type", "scalar"), "value": e.get("value"),
                "rows": e.get("rows"), "tolerance": float(e.get("tolerance", 1e-6))}
    if case.get("expect_reject"):  # fmt2 refusal
        return {"kind": "refusal"}
    if case.get("gold_rows") is not None:  # fmt2
        rows = case["gold_rows"]
        if len(rows) == 1 and len(rows[0]) == 1:
            return {"kind": "scalar", "value": rows[0][0]}
        return {"kind": "rows", "rows": rows}
    if case.get("gold_sql"):  # fmt3
        rec = (gold_results or {}).get(case["id"])
        if rec and rec.get("rows") is not None:
            rows = rec["rows"]
            if len(rows) == 1 and len(rows[0]) == 1:
                return {"kind": "scalar", "value": rows[0][0]}
            return {"kind": "rows", "rows": rows}
        return {"kind": "sql_only"}  # 有 SQL 无结果：只做可回答性检查
    return {"kind": "none"}


# ---------- 模式 A：活引擎 ----------

def ask(endpoint, question, timeout=30):
    req = urllib.request.Request(
        endpoint.rstrip("/") + "/api/ask",
        data=json.dumps({"question": question}).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)
    except Exception as e:
        return {"error": str(e)}


def judge_live(resp, expect):
    """活引擎响应 × 统一期望 → (pass|None, detail)。pass=None 表示无法判定。"""
    if "error" in resp:
        return False, f"http_error: {resp['error']}"
    refused = bool(resp.get("rejected") or resp.get("refused"))
    kind = expect["kind"]
    if kind == "refusal":
        return (True, "") if refused else (False, "期望拒绝，但引擎给出了答案")
    if refused:
        return False, "引擎拒绝了，但期望给出答案"
    if kind == "scalar":
        return cmp_scalar(expect["value"], resp.get("value"), expect.get("tolerance", 1e-6)) \
            if resp.get("value") is not None else \
            cmp_rows([[expect["value"]]], resp.get("rows"))
    if kind == "rows":
        return cmp_rows(expect["rows"], resp.get("rows"))
    if kind == "sql_only":
        has_answer = resp.get("rows") is not None or resp.get("value") is not None
        return (True, "仅可回答性检查（无期望行，需 --gold-results）") if has_answer \
            else (False, "引擎未给出任何结果")
    return None, "无期望定义（跳过判定）"


def run_live(args):
    cases = load_cases(args.cases)
    gold_results = load_actual_map(args.gold_results) if args.gold_results else None
    suites = [("main", cases)]
    if args.multihop:
        suites.append(("multihop", load_cases(args.multihop)))

    records = []
    for label, suite in suites:
        for c in suite:
            expect = unify_expect(c, gold_results)
            resp = ask(args.endpoint, c["question"])
            ok, why = judge_live(resp, expect)
            records.append({
                "id": c["id"], "type": c.get("type", label), "pass": ok, "why": why,
                "route": "reject" if resp.get("rejected") or resp.get("refused")
                         else ("table" if resp.get("rows") else "scalar"),
                "value": resp.get("value"), "sql": resp.get("sql"),
                "reasoning": resp.get("reasoning")})
            mark = "pass" if ok else ("skip" if ok is None else "FAIL")
            print(f"{c['id']} [{label}] {mark}  {c['question'][:32]}"
                  + ("" if ok else f"  << {why}"))

    judged = [r for r in records if r["pass"] is not None]
    passed = sum(1 for r in judged if r["pass"])
    by_type = {}
    for r in judged:
        t = by_type.setdefault(r["type"] or "main", [0, 0])
        t[1] += 1
        t[0] += bool(r["pass"])
    summary = {"total": len(judged), "passed": passed,
               "acc": round(passed / len(judged), 4) if judged else 0,
               "by_type": {k: {"pass": v[0], "total": v[1], "acc": round(v[0] / v[1], 4)}
                           for k, v in sorted(by_type.items())},
               "failures": [r for r in judged if not r["pass"]]}
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump({"summary": summary, "records": records}, f, ensure_ascii=False, indent=1)
    print("\n==== SUMMARY ====")
    print(json.dumps(summary, ensure_ascii=False, indent=1, default=str)[:2000])
    return 0 if passed == len(judged) else 1


# ---------- 模式 B：离线文件比对 ----------

def judge_file(case, actual):
    expect = unify_expect(case, None)
    if actual is None:
        return False, "无实际输出（引擎未返回该用例）"
    kind = expect["kind"]
    refused = bool(actual.get("refused") or actual.get("rejected"))
    if kind == "refusal":
        return (True, "") if refused else (False, "期望拒绝，但引擎给出了答案")
    if refused:
        return False, "引擎拒绝了，但期望给出答案"
    if kind == "scalar":
        return cmp_scalar(expect["value"], actual.get("value"), expect.get("tolerance", 1e-6))
    if kind == "rows":
        return cmp_rows(expect["rows"], actual.get("rows"))
    return False, f"离线模式不支持的断言类型：{kind}"


def run_offline(args):
    cases = load_cases(args.gold)
    actuals = load_actual_map(args.actual)
    results, passed = [], 0
    for case in cases:
        ok, detail = judge_file(case, actuals.get(case["id"]))
        passed += bool(ok)
        results.append({"id": case["id"], "pass": ok, "detail": detail})
        print(f"[{'PASS' if ok else 'FAIL'}] {case['id']}" + (f" —— {detail}" if detail else ""))
    print(f"\n回归结果：{passed}/{len(cases)} 通过")
    if args.report:
        with open(args.report, "w", encoding="utf-8") as f:
            json.dump({"passed": passed, "total": len(cases), "cases": results},
                      f, ensure_ascii=False, indent=2)
    return 0 if passed == len(cases) else 1


def main():
    ap = argparse.ArgumentParser(description="回归比对器 v0.0.2（活引擎 / 离线双模式）")
    ap.add_argument("--endpoint", help="活引擎地址（模式 A）")
    ap.add_argument("--cases", help="用例集 json/yaml（模式 A）")
    ap.add_argument("--gold-results", dest="gold_results", default=None,
                    help="fmt3 用例的期望行（gold_results.json）")
    ap.add_argument("--multihop", default=None, help="多跳用例（可选，单独汇总）")
    ap.add_argument("--out", default="eval_report.json")
    ap.add_argument("--gold", help="gold 用例集（模式 B）")
    ap.add_argument("--actual", help="引擎实际输出 jsonl/yaml/json（模式 B）")
    ap.add_argument("--report", default=None, help="模式 B 报告输出路径")
    args = ap.parse_args()

    if args.endpoint:
        if not args.cases:
            print("错误：模式 A 需要 --cases", file=sys.stderr)
            return 2
        return run_live(args)
    if args.gold and args.actual:
        return run_offline(args)
    print("错误：二选一——模式 A 用 --endpoint + --cases；模式 B 用 --gold + --actual",
          file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
