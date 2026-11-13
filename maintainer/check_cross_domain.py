"""Exercise four synthetic domains through public services and a separate reader process.

This is an authored fixture test, not an extraction benchmark, user acceptance or
production query. It refuses a nonempty output directory and never opens customer
projects. JSON observations are evaluated by the explicit toy reference functions
below; no fixture text or SQL is executed.
"""
import argparse
import copy
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from workbench.knowledge import KnowledgeService
from workbench.store import Store

FIXTURES = ROOT / "examples" / "cross-domain"
DOMAINS = ("traffic", "agriculture", "university", "finance")


def load_fixture(domain):
    if domain not in DOMAINS:
        raise ValueError("Unknown synthetic domain")
    return json.loads((FIXTURES / (domain + ".json")).read_text(encoding="utf-8"))


def observations(fixture):
    """Independent small computations; never claim these were reader answers."""
    rows = fixture["observations"]
    if fixture["id"] == "traffic":
        trips = rows["trip_rows"]
        employers = []
        for day in rows["at_dates"]:
            active = [r["employer"] for r in rows["employment"]
                      if r["from"] <= day and (r["to"] is None or day < r["to"])]
            if len(active) != 1:
                raise AssertionError("Toy employment records must resolve to one employer")
            employers.append(active[0])
        return {"whole_fixture_raw_trip_rows": len(trips), "whole_fixture_distinct_source_trips": len({tuple(t) for t in trips}),
                "tenant_A_source_trips": len({tuple(t) for t in trips if t[0] == "A"}),
                "wrong_tenant_A_unfiltered_count": len({tuple(t) for t in trips}),
                "wrong_original_number_only_count": len({t[2] for t in trips}),
                "employer_on_dates": employers}
    if fixture["id"] == "agriculture":
        harvested = sum(r["kg"] for r in rows["harvest_kg"])
        transferred = sum(r["kg"] for r in rows["transfers_kg"])
        # Transfers do not identify the composition of X. This is not inferred.
        return {"harvest_total_kg": harvested, "transfers_total_kg": transferred,
                "wrong_harvest_plus_transfer_kg": harvested + transferred,
                "X_origin_composition": "unknown_without_mix_rule"}
    if fixture["id"] == "university":
        active = [r for r in rows["enrollments"] if r["status"] == "active"]
        current = [r for r in active if r["term"] == "T2"]
        return {"natural_people": len({r["person"] for r in rows["roles"]}),
                "role_rows": len(rows["roles"]), "active_attempts_all_terms": len({r["id"] for r in active}),
                "active_people_T2": len({r["person"] for r in current}),
                "active_attempts_T2": len({r["id"] for r in current})}
    if fixture["id"] == "finance":
        balances, unique = {}, {}
        for row in rows["joined_contract_rows"]:
            key = (row["contract"], row["date"], row["currency"])
            amount = Decimal(row["amount"])
            if key in unique and unique[key] != amount:
                raise AssertionError("Conflicting balance cannot be deduplicated by choosing first")
            unique[key] = amount
        for (_, _, currency), amount in unique.items():
            balances[currency] = balances.get(currency, Decimal(0)) + amount
        cny = [Decimal(r["amount"]) for r in rows["joined_contract_rows"] if r["currency"] == "CNY"]
        return {"CNY_contract_balance": str(balances["CNY"]), "USD_contract_balance": str(balances["USD"]),
                "wrong_CNY_joined_sum": str(sum(cny)), "wrong_CNY_sum_distinct_amount": str(sum(set(cny))),
                "converted_total": None}
    raise ValueError("Unknown synthetic domain")


def validate_result(case, result, *, scenario=False):
    """Compare with manually authored expectations, not with another reader call."""
    reader = result["reader"] if scenario else result
    if case.get("expected_error"):
        assert reader.get("error", {}).get("code") == case["expected_error"], (case["id"], reader)
        if scenario:
            assert result["status"] == "needs_review"
        return
    assert reader["status"] == case["expected_status"], (case["id"], reader["status"], case["expected_status"])
    assert not reader.get("answer_verified", False), case["id"]
    assert "answer" not in reader and "value" not in reader, case["id"]
    if scenario:
        assert result["acceptance"]["status"] == "not_verified"
        assert result["published"] is False and result["answer_verified"] is False
    if not case["asset_ids"]:
        found = {c["id"] for c in reader["candidates"]}
        assert set(case.get("expected_candidates", [])) <= found, (case["id"], found)
        assert not reader.get("selected_asset_ids"), case["id"]
        return
    context = reader["context"]
    assert set(context["required_asset_ids"]) == set(case["expected_required_ids"]), (
        case["id"], context["required_asset_ids"], case["expected_required_ids"])
    assert not context["missing_dependencies"] and not context["truncated"], case["id"]
    text = json.dumps(context["assets"], ensure_ascii=False)
    for term in case.get("expected_terms", []):
        assert term in text, (case["id"], term)
    for gap in case.get("expected_gap_codes", []):
        assert gap in {g["code"] for g in context["gaps"]}, (case["id"], gap)
    for evidence in context["evidence"]:
        assert evidence["evidence"], case["id"]
        for row in evidence["evidence"]:
            assert row["status"] == "available" and row["assertion"]["revision"] == 1, (case["id"], row)
            assert row["assertion"]["extraction_id"] == row["extraction_id"]
            assert row["assertion"]["quote"] in row["fragment"]["text"]
    assert reader["capabilities"]["authorization"] == "not_granted_by_knowledge_or_role_definitions"
    if case["intent"] in {"query", "act", "calculate"}:
        assert not reader["capabilities"]["query_data"]["available"]


def make_project(fixture, directory):
    service = KnowledgeService(Store(directory))
    def call(method, **payload):
        return getattr(service, method)({"revision": service.store.read()["revision"],
            "operation_id": uuid.uuid4().hex, **payload})["result"]
    paragraphs = fixture["source"]["paragraphs"]
    notice = fixture["source"]["notice"] + " 适用范围：" + json.dumps(fixture["scope"], ensure_ascii=False) + "。"
    text = notice + "\n\n" + "\n\n".join(f"[{key}] {value}" for key, value in paragraphs.items())
    imported = call("import_material", filename=fixture["id"] + "-synthetic.txt", text=text,
                    domain=fixture["domain"], scope=fixture["scope"])
    task = call("task", batch_id=imported["batch_id"], action="prepare", language="zh")
    source = task["materials"][0]
    # Evidence identity comes from the returned source, never guessed fixture IDs.
    state_source = service.state()["sources"][0]
    revision = state_source["revisions"][-1]
    assets = []
    for candidate in fixture["assets"]:
        asset = copy.deepcopy(candidate)
        paragraph = asset.pop("source_paragraph")
        phrase = paragraphs[paragraph]
        fragment = next(f for f in source["parsed"]["fragments"] if phrase in f["text"])
        asset["evidence"] = [{"source_id": state_source["id"], "revision": revision["revision"],
            "extraction_id": revision["current_extraction"], "fragment_id": fragment["id"], "quote": phrase}]
        scope_fragment = next(f for f in source["parsed"]["fragments"] if notice in f["text"])
        asset["evidence"].append({"source_id": state_source["id"], "revision": revision["revision"],
            "extraction_id": revision["current_extraction"], "fragment_id": scope_fragment["id"], "quote": notice})
        assets.append(asset)
    proposed = call("propose", batch_id=imported["batch_id"], complete=True,
        groups=[{"summary": "合成练习：核对本领域依赖闭合的候选组", "candidates": [{"op": "upsert", "asset": a} for a in assets]}])
    assert service.state()["assets"] == [], "Proposals must not confirm themselves"
    # Test operator explicitly accepts authored fixtures; this is not autonomous real-user approval.
    for group in proposed["group_ids"]:
        call("review", group_id=group, action="accept", reason="synthetic-test-operator：仅核对本次虚构夹具；不是客户签署或行业政策")
    assert len(service.state()["assets"]) == len(fixture["assets"])
    return service, call


def run_domain(domain, output, *, cli=True):
    fixture = load_fixture(domain)
    out = Path(output).resolve()
    out.mkdir(parents=True, exist_ok=False)
    service, call = make_project(fixture, out / "project")
    results = []
    for case in fixture["cases"]:
        fields = {k: copy.deepcopy(case[k]) for k in ("question", "intent", "asset_ids", "acceptance_notes", "scope", "as_of") if k in case}
        if case["asset_ids"] and not case.get("expected_error"):
            fields["acceptance"] = {"required_asset_ids": case["expected_required_ids"],
                "required_gap_codes": case.get("expected_gap_codes", []),
                "cases": [{"id": "business-example", "expectation": case["acceptance_notes"]}]}
        scenario = call("scenario", scenario={"title": case["id"], **fields})["scenario"]
        before = service.store.read()
        check = service.scenario_check({"scenario_id": scenario["id"]})
        validate_result(case, check, scenario=True)
        if case["asset_ids"] and not case.get("expected_error"):
            assert check["acceptance"]["context_contract"]["status"] == "passed", case["id"]
        assert service.store.read() == before, "Checks must not mutate source or expectations"
        results.append({"case_id": case["id"], "scenario_check": check})
    assert service.state()["snapshots"] == [], "Scenario checks never publish"
    publication = call("publish", asset_ids=[a["id"] for a in fixture["assets"]], draft=False)
    package = out / (domain + "-semantic.zip")
    package.write_bytes(service.download(publication["snapshot_id"]))
    before_hash = hashlib.sha256(package.read_bytes()).hexdigest()
    if cli:
        for case, result in zip(fixture["cases"], results):
            cmd = [sys.executable, "-X", "utf8", str(ROOT / "scripts" / "semantic_read.py"), "--package", str(package),
                   "resolve", "--question", case["question"], "--intent", case["intent"]]
            for aid in case["asset_ids"]:
                cmd += ["--id", aid]
            if "scope" in case:
                cmd += ["--scope", json.dumps(case["scope"], ensure_ascii=False)]
            if "as_of" in case:
                cmd += ["--as-of", case["as_of"]]
            run = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", timeout=30, cwd=out)
            expected_exit = 2 if case.get("expected_error") else 0
            assert run.returncode == expected_exit, (case["id"], run.stderr, run.stdout)
            read = json.loads(run.stdout)
            validate_result(case, read)
            result["independent_cli"] = read
    assert hashlib.sha256(package.read_bytes()).hexdigest() == before_hash
    handoffs = []
    from workbench.semantic_package import read_package
    for case, result in zip(fixture["cases"], results):
        if not case["asset_ids"] or case.get("expected_error"):
            continue
        scenario = result["scenario_check"]["scenario"]
        delivered = call("publish", scenario_id=scenario["id"], draft=False)
        task_path = out / (case["id"] + "-agent.zip")
        task_path.write_bytes(service.download(delivered["snapshot_id"]))
        reader = read_package(task_path)
        full, brief = reader.task(detail="full"), reader.task()
        validate_result(case, full)
        for key in ("gaps", "business_scopes", "required_asset_ids", "dependency_edges", "capabilities"):
            assert brief["context"][key] == full["context"][key], (case["id"], key)
        if cli:
            run = subprocess.run([sys.executable, "-X", "utf8", str(ROOT / "scripts/semantic_read.py"),
                "--package", str(task_path), "task"], capture_output=True, text=True, encoding="utf-8", timeout=30, cwd=out)
            assert run.returncode == 0, (case["id"], run.stdout, run.stderr)
            assert json.loads(run.stdout)["task"] == brief["task"]
        handoffs.append({"case_id": case["id"], "package": str(task_path),
            "summary_bytes": len(json.dumps(brief, ensure_ascii=False).encode()),
            "full_bytes": len(json.dumps(full, ensure_ascii=False).encode()), "independent_cli": cli})
    calculated = observations(fixture)
    assert calculated == fixture["expected_observations"], (domain, calculated, fixture["expected_observations"])
    # Exercise operator-record lifecycle with explicitly labelled synthetic evidence, not customer acceptance.
    sample = next(r["scenario_check"]["scenario"] for c, r in zip(fixture["cases"], results)
                  if c["asset_ids"] and not c.get("expected_error"))
    sample["acceptance"]["cases"] = [{"id": "reference-calculation", "expectation": json.dumps(fixture["expected_observations"], ensure_ascii=False)}]
    sample = call("scenario", scenario=sample)["scenario"]
    checked = service.scenario_check({"scenario_id": sample["id"]})
    call("scenario_assess", scenario_id=sample["id"], case_id="reference-calculation", outcome="passed",
         basis_fingerprint=checked["acceptance"]["basis_fingerprint"], actor="synthetic-test-operator",
         observed=json.dumps(calculated, ensure_ascii=False), evidence="Maintainer toy oracle on supplied fixture rows; not an Agent query or customer approval")
    assert service.scenario_check({"scenario_id": sample["id"]})["acceptance"]["cases"][0]["status"] == "passed"
    source = service.state()["sources"][0]
    imported = call("import_material", filename=source["name"], source_id=source["id"],
                    text=fixture["source"]["notice"] + "\n\nRevised synthetic policy: definitions require another review.")
    stale = service.scenario_check({"scenario_id": sample["id"]})
    assert stale["acceptance"]["cases"][0]["status"] == "stale"
    assert any(q["scenario_id"] == sample["id"] for q in imported["change_impact"]["impacted_questions"])
    assert hashlib.sha256(package.read_bytes()).hexdigest() == before_hash, "Issued snapshots never change"
    report = {"domain": domain, "synthetic_only": True, "asset_count": len(fixture["assets"]),
        "cases_passed": len(results), "independent_cli": cli, "package": str(package.resolve()), "sha256": before_hash,
        "question_handoffs": handoffs, "source_change_recheck": {"status": "stale", "impact": imported["change_impact"]},
        "reference_calculations": {"executed_by": "maintainer toy Python oracle, not semantic reader", "actual": calculated,
            "expected": fixture["expected_observations"]}, "results": results,
        "limits": ["Authored proposals, not extraction-quality evaluation", "No live database, Neo4j or production authorization",
                   "No novice usability or business acceptance claim", "Reader never executes the observation calculations"]}
    (out / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {k: v for k, v in report.items() if k not in {"results"}}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", required=True, type=Path, help="New or empty dedicated synthetic test directory")
    ap.add_argument("--domain", choices=DOMAINS, action="append")
    args = ap.parse_args()
    if args.out.exists() and any(args.out.iterdir()):
        ap.error("Output directory must be empty; existing projects and evidence are never overwritten")
    args.out.mkdir(parents=True, exist_ok=True)
    reports = [run_domain(domain, args.out / domain) for domain in (args.domain or DOMAINS)]
    summary = {"domains": reports, "cases_passed": sum(r["cases_passed"] for r in reports),
               "assets_reviewed": sum(r["asset_count"] for r in reports)}
    (args.out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
