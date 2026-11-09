#!/usr/bin/env python3
"""Reproducible synthetic service/package acceptance; no UI or performance SLA.

All project writes use KnowledgeService. A bootstrap proposal creates the graph;
the separately measured candidate workload then updates existing entities.
Artifacts are retained under a fresh run directory, never an existing project.
"""
import argparse
import copy
import ctypes
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import time
import traceback
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from workbench.knowledge import KnowledgeService
from workbench.semantic_package import read_package
from workbench.store import Store


def json_write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def process_memory():
    """Native working set, not Python-only allocations; peak is process lifetime."""
    if os.name == "nt":
        class Counters(ctypes.Structure):
            _fields_ = [("cb", ctypes.c_uint32), ("PageFaultCount", ctypes.c_uint32)] + [
                (name, ctypes.c_size_t) for name in ("PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage",
                    "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage")]
        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.GetCurrentProcess.restype = ctypes.c_void_p
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        psapi.GetProcessMemoryInfo.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32]
        if psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
            return {"working_set_bytes": counters.WorkingSetSize,
                    "peak_working_set_bytes_process_lifetime": counters.PeakWorkingSetSize}
    try:
        import resource
        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return {"peak_working_set_bytes_process_lifetime": peak * (1 if sys.platform == "darwin" else 1024)}
    except (ImportError, ValueError):
        return {"unavailable": True}


def machine_info():
    result = {"platform": platform.platform(), "python": sys.version, "python_executable": sys.executable,
              "logical_processors": os.cpu_count(), "processor": platform.processor()}
    if os.name == "nt":
        command = ("[Console]::OutputEncoding=[System.Text.Encoding]::UTF8; "
                   "$p=Get-CimInstance Win32_Processor; $m=Get-CimInstance Win32_ComputerSystem; "
                   "@{cpu=@($p|Select-Object Name,NumberOfCores,NumberOfLogicalProcessors); "
                   "ram_bytes=$m.TotalPhysicalMemory}|ConvertTo-Json -Depth 4 -Compress")
        response = subprocess.run(["powershell", "-NoProfile", "-Command", command], capture_output=True, timeout=20)
        if response.returncode == 0:
            result.update(json.loads(response.stdout.decode("utf-8-sig")))
        else:
            result["hardware_query_error"] = response.stderr.decode("utf-8", errors="replace")
    elif hasattr(os, "sysconf"):
        result["ram_bytes"] = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    return result


class Recorder:
    def __init__(self, report, output):
        self.report, self.output = report, output

    def stage(self, name, operation, **counts):
        before = process_memory()
        started = time.perf_counter()
        entry = {"name": name, "counts": counts, "memory_before": before}
        try:
            value = operation()
            entry["status"] = "passed"
            return value
        except Exception as exc:
            entry.update(status="failed", error=f"{type(exc).__name__}: {exc}")
            raise
        finally:
            entry.update(elapsed_seconds=round(time.perf_counter() - started, 6), memory_after=process_memory())
            self.report["stages"].append(entry)
            json_write(self.output / "report.json", self.report)
            print(json.dumps(entry, ensure_ascii=False), flush=True)


def assert_equal(actual, expected, message):
    if actual != expected:
        raise AssertionError(f"{message}: actual={actual!r}, expected={expected!r}")


def benchmark(args, output, report):
    record = Recorder(report, output)
    store = Store(output / "project")
    service = KnowledgeService(store)
    def call(method, **data):
        return getattr(service, method)({"revision": store.read()["revision"], "operation_id": uuid.uuid4().hex, **data})

    specs = []
    for number in range(args.entities):
        specs.append({"id": f"entity_{number:04d}", "kind": "entity", "name": f"对象{number:04d}",
                      "definition": f"对象 {number:04d} 是合成业务对象；别称为「别称{number:04d}」，仅用于本机规模验收。"})
    for number in range(args.relations):
        left = number % args.entities
        right = (left + number // args.entities + 1) % args.entities
        specs.append({"id": f"relation_{number:04d}", "kind": "relation", "name": f"关系{number:04d}",
                      "definition": f"关系 {number:04d}：对象 {left:04d} 指向对象 {right:04d}，谓词为「关联」，仅用于本机规模验收。",
                      "from": f"entity_{left:04d}", "to": f"entity_{right:04d}", "predicate": "关联", "relation_type": "business"})
    texts = [[] for _ in range(args.sources)]
    for index, spec in enumerate(specs):
        spec["source_number"] = index % args.sources
        texts[index % args.sources].append(spec["definition"])
    inputs = [f"合成资料 {i:03d}。\n\n" + "\n\n".join(parts) for i, parts in enumerate(texts)]
    report["input"] = {"entities": args.entities, "relations": args.relations, "sources": args.sources,
        "followup_candidates": args.candidates, "review_group_size": args.group_size,
        "bootstrap_candidates": len(specs), "source_utf8_bytes": sum(len(t.encode("utf-8")) for t in inputs),
        "source_texts_sha256": hashlib.sha256(json.dumps(inputs, ensure_ascii=False).encode()).hexdigest()}
    imported = []
    def import_sources():
        for number, text in enumerate(inputs):
            imported.append(call("import_material", filename=f"合成来源_{number:03d}.txt", text=text,
                                 domain="合成验收", scope="本机规模验收")["result"])
    record.stage("import_sources", import_sources, sources=args.sources)
    state = record.stage("read_sources_state", service.state, expected_sources=args.sources)
    assert_equal(len(state["sources"]), args.sources, "source count after import")
    source_by_id = {s["id"]: s for s in state["sources"]}
    assets = []
    for spec in specs:
        asset = dict(spec)
        source = source_by_id[imported[asset.pop("source_number")]["source_id"]]
        revision = source["revisions"][-1]
        fragment = next(f for f in revision["parsed"]["fragments"] if f["text"] == asset["definition"])
        asset.update(domain="合成验收", scope="本机规模验收", aliases=[], refs=[], properties={},
                     evidence=[{"source_id": source["id"], "revision": revision["revision"],
                        "extraction_id": revision["current_extraction"], "fragment_id": fragment["id"], "quote": fragment["text"]}])
        assets.append(asset)
    initial = record.stage("bootstrap_propose", lambda: call("propose", batch_id=imported[0]["batch_id"],
        groups=[{"summary": "建立合成基准图", "candidates": [{"asset": a} for a in assets]}]), candidates=len(assets))
    initial_group = initial["result"]["group_ids"][0]
    record.stage("bootstrap_review", lambda: call("review", group_id=initial_group, action="accept"), candidates=len(assets))
    baseline = record.stage("read_full_graph", service.state, expected_assets=len(assets))
    expected_ids = {a["id"] for a in assets}
    assert_equal({a["id"] for a in baseline["assets"]}, expected_ids, "bootstrap IDs")
    record.stage("prepare_host_task", lambda: call("task", batch_id=imported[0]["batch_id"]), context_assets=len(assets))

    updates = []
    for number, a in enumerate(baseline["assets"][:args.candidates]):
        updated = copy.deepcopy(a)
        updated["aliases"] = [f"别称{number:04d}"]
        updates.append(updated)
    groups = [{"summary": f"补充来源已声明的别称 {start}", "candidates": [{"asset": a} for a in updates[start:start + args.group_size]]}
              for start in range(0, len(updates), args.group_size)]
    proposed = record.stage("propose_followup_candidates", lambda: call("propose", batch_id=imported[0]["batch_id"], groups=groups),
                            candidates=len(updates), groups=len(groups))
    group_ids = proposed["result"]["group_ids"]
    pending = record.stage("reopen_pending_state", lambda: KnowledgeService(Store(output / "project")).state(),
                           expected_assets=len(assets), expected_pending_candidates=args.candidates)
    pending_count = sum(len(g["candidates"]) for g in pending["groups"] if g["status"] == "pending")
    assert_equal(pending_count, args.candidates, "pending candidates on reopen")
    assert_equal({a["id"] for a in pending["assets"]}, expected_ids, "pending candidates do not replace graph")
    review_times = []
    def review_followups():
        for group_id in group_ids:
            started = time.perf_counter()
            call("review", group_id=group_id, action="accept", reason="合成核对：原文明确给出别称")
            review_times.append(time.perf_counter() - started)
    record.stage("review_followup_candidates", review_followups, candidates=args.candidates, groups=len(groups))
    report["review_group_seconds"] = {"min": min(review_times), "median": statistics.median(review_times),
                                       "max": max(review_times), "samples": review_times}
    final_state = record.stage("reopen_confirmed_state", lambda: KnowledgeService(Store(output / "project")).state(), expected_assets=len(assets))
    assert_equal({a["id"] for a in final_state["assets"]}, expected_ids, "final IDs")
    assert_equal(sum(a["status"] == "confirmed" for a in final_state["assets"]), len(assets), "confirmed assets")
    current_by_id = {a["id"]: a for a in final_state["assets"]}
    for expected in updates:
        assert_equal(current_by_id[expected["id"]]["aliases"], expected["aliases"], "accepted candidate value")
    assert_equal(sum(len(g["candidates"]) for g in final_state["groups"] if g["status"] == "accepted"),
                 len(assets) + args.candidates, "accepted historical candidate count")

    published = record.stage("publish_confirmed_package", lambda: call("publish"), assets=len(assets), sources=args.sources)
    snapshot = published["result"]
    package_path = output / "semantic-package.zip"
    record.stage("download_and_write_package", lambda: package_path.write_bytes(service.download(snapshot["snapshot_id"])))
    package = record.stage("load_and_verify_package", lambda: read_package(package_path), expected_assets=len(assets))
    assert_equal(set(package.index), expected_ids, "package IDs")
    assert_equal(len(package.source_records), args.sources, "referenced sources in package")
    assert_equal(package.manifest["complete"], True, "confirmed package complete")
    for expected in assets:
        actual = package.index[expected["id"]]
        for key in ("from", "to", "predicate", "relation_type"):
            if key in expected:
                assert_equal(actual[key], expected[key], f"preserved relationship {expected['id']}.{key}")

    def search_all(kind, query, expected):
        found, offset, pages = set(), 0, 0
        while True:
            response = package.search(query, kind=kind, limit=200, offset=offset)
            assert_equal(response["total"], len(expected), "search total")
            if response["truncated"]:
                assert_equal(response["complete"], False, "truncated search must not claim complete")
            found.update(row["asset"]["id"] for row in response["matches"])
            pages += 1
            if response["next_offset"] is None:
                break
            offset = response["next_offset"]
        assert_equal(found, expected, "all search pages preserve IDs")
        return {"returned_unique_ids": len(found), "pages": pages}
    report["entity_search"] = record.stage("search_all_entities", lambda: search_all("entity", "对象", {a["id"] for a in assets if a["kind"] == "entity"}))
    report["relation_search"] = record.stage("search_all_relations", lambda: search_all("relation", "关系", {a["id"] for a in assets if a["kind"] == "relation"}))

    edges = [a for a in assets if a["kind"] == "relation"]
    adjacency = {}
    for edge in edges:
        for endpoint in (edge["from"], edge["to"]):
            adjacency.setdefault(endpoint, []).append(edge)
    expected_edges, frontier, visited = set(), {"entity_0000"}, {"entity_0000"}
    for _ in range(2):
        following = set()
        for node in frontier:
            for edge in adjacency.get(node, []):
                expected_edges.add(edge["id"])
                following.update({edge["from"], edge["to"]} - visited)
        visited.update(following)
        frontier = following
    def neighbors_all():
        found, offset, pages = set(), 0, 0
        while True:
            result = package.neighbors("entity_0000", depth=2, limit=7, offset=offset)
            assert_equal(result["total"], len(expected_edges), "neighborhood total")
            if result["truncated"]:
                assert_equal(result["complete"], False, "truncated neighborhood must not claim complete")
            found.update(row["asset"]["id"] for row in result["edges"])
            pages += 1
            if result["next_offset"] is None:
                break
            offset = result["next_offset"]
        assert_equal(found, expected_edges, "neighborhood IDs and direction")
        return {"depth": 2, "returned_unique_edges": len(found), "pages": pages}
    report["neighbors"] = record.stage("neighbors_all_pages", neighbors_all)
    def source_samples():
        for asset in assets[:args.sources]:
            result = package.sources(asset["id"])
            assert_equal(result["evidence"][0]["assertion"]["quote"], asset["definition"], "original evidence retained")
            assert_equal(result["evidence"][0]["status"], "available", "evidence available")
    record.stage("source_evidence_samples", source_samples, sources=args.sources, assertions_checked=args.sources)

    standalone = output / "consumer"
    standalone.mkdir()
    def cli(*arguments):
        proc = subprocess.run([sys.executable, str(ROOT / "scripts" / "semantic_read.py"), "--package", str(package_path), *arguments],
                              cwd=standalone, capture_output=True, encoding="utf-8", timeout=120)
        if proc.returncode:
            raise AssertionError(f"independent CLI failed: {proc.stdout} {proc.stderr}")
        value = json.loads(proc.stdout)
        assert_equal(value["snapshot_id"], snapshot["snapshot_id"], "independent snapshot identity")
        return value
    verified = record.stage("independent_cli_verify", lambda: cli("verify"))
    assert_equal(verified["complete"], True, "CLI verification")
    matched = record.stage("independent_cli_alias_search", lambda: cli("search", "--query", "别称0000"))
    assert_equal([row["asset"]["id"] for row in matched["matches"]], ["entity_0000"], "CLI reviewed alias")
    neighboring = record.stage("independent_cli_neighbors", lambda: cli("neighbors", "--id", "entity_0000", "--depth", "1"))
    assert_equal({row["asset"]["id"] for row in neighboring["edges"]}, {edge["id"] for edge in adjacency["entity_0000"]}, "CLI direct edges")

    parent_hash = hashlib.sha256(package_path.read_bytes()).hexdigest()
    selected_edges = edges[:min(200, len(edges))]
    selected_ids = {edge["id"] for edge in selected_edges}
    closure_ids = selected_ids | {edge[key] for edge in selected_edges for key in ("from", "to")}
    def subgraph():
        content, manifest = package.export(sorted(selected_ids))
        path = output / "subgraph.zip"
        path.write_bytes(content)
        child = read_package(path)
        assert_equal(set(child.index), closure_ids, "subgraph dependency closure")
        assert_equal(hashlib.sha256(package_path.read_bytes()).hexdigest(), parent_hash, "parent snapshot remains fixed")
        return {"requested_relations": len(selected_ids), "included_assets": len(child.index), "complete": manifest["complete"]}
    report["subgraph"] = record.stage("export_and_verify_subgraph", subgraph)
    report["output"] = {"project": str(output / "project"), "package": str(package_path), "snapshot_id": snapshot["snapshot_id"],
        "package_bytes": package_path.stat().st_size, "package_sha256": parent_hash, "project_sqlite_bytes": store.path.stat().st_size,
        "assets": len(package.index), "entities": args.entities, "relations": args.relations, "sources": len(package.source_records),
        "accepted_followup_candidates": args.candidates, "accepted_historical_candidates": len(assets) + args.candidates,
        "source_fragments_exported": sum(len(e["parsed"]["fragments"]) for s in package.source_records for v in s["revisions"] for e in v.get("extractions", [])),
        "current_project_revision": store.read()["revision"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT.parent / "ai-data-delivery_m1_m2_load_acceptance")
    parser.add_argument("--entities", type=int, default=1000)
    parser.add_argument("--relations", type=int, default=3000)
    parser.add_argument("--sources", type=int, default=100)
    parser.add_argument("--candidates", type=int, default=200)
    parser.add_argument("--group-size", type=int, default=10)
    args = parser.parse_args()
    if not (2 <= args.entities and 1 <= args.relations and 1 <= args.sources <= args.entities
            and 1 <= args.candidates <= args.entities and 1 <= args.group_size <= args.candidates):
        parser.error("requires entities>=2, relations>=1, 1<=sources,candidates<=entities and 1<=group-size<=candidates")
    args.out.mkdir(parents=True, exist_ok=True)
    output = args.out.resolve() / (datetime.now(timezone.utc).strftime("run_%Y%m%dT%H%M%SZ_") + uuid.uuid4().hex[:8])
    output.mkdir()
    tracked = [ROOT / p for p in ("workbench/knowledge.py", "workbench/semantic_package.py", "workbench/store.py", "maintainer/benchmark_semantic.py")]
    report = {"status": "running", "started_utc": datetime.now(timezone.utc).isoformat(), "machine": machine_info(),
        "script": str(Path(__file__).resolve()), "command_argv": [sys.executable, *sys.argv], "run_directory": str(output),
        "source_sha256": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in tracked},
        "measurement_scope": ["One synthetic local process; direct KnowledgeService transactions, SQLite persistence, offline package library and independent CLI child processes.",
            "No browser, HTTP request, LLM inference, real business review or production concurrency measured.",
            "CPU/RAM describe this machine; other applications were not stopped. Elapsed timings are one run, no performance promise.",
            "Memory is native current/peak process working set; the peak is cumulative since process start, not a stage allocation delta. CLI child memory is not included.",
            "Bootstrap candidate count is reported separately from the 200-candidate workload on the already populated graph."], "stages": []}
    started = time.perf_counter()
    try:
        benchmark(args, output, report)
        report["status"] = "passed"
    except Exception as exc:
        report.update(status="failed", error=f"{type(exc).__name__}: {exc}", traceback=traceback.format_exc())
    finally:
        report.update(finished_utc=datetime.now(timezone.utc).isoformat(), total_elapsed_seconds=round(time.perf_counter() - started, 6), memory_final=process_memory())
        json_write(output / "report.json", report)
        print(json.dumps({"status": report["status"], "report": str(output / "report.json"), "total_elapsed_seconds": report["total_elapsed_seconds"]}, ensure_ascii=False), flush=True)
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
