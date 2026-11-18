#!/usr/bin/env python3
"""Local CLI: import structure, edit semantics, export a portable package.

Read a prepared task and propose against its source revision. Review/edit commands
record explicit operator decisions through the same guards as the workbench.
No LLM or automatic confirmation. Metadata commands use the configured catalog.
"""
import argparse
import base64
import json
import os
from pathlib import Path
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from workbench.store import Store, Conflict
from workbench.knowledge import KnowledgeService
from workbench.semantic_package import PackageError, bounded_warnings, scope_summary


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        print(json.dumps({"ok": False, "status": "argument_error", "error": message,
                          "hint": "Use COMMAND --help / 使用子命令 --help 查看参数"}, ensure_ascii=False))
        raise SystemExit(2)


def main(argv=None):
    parser = JsonArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--full-output", action="store_true", help="Return the full import/export receipt including all asset IDs, issues and parser warnings; place before command")
    parser.add_argument("--revision", type=int)
    parser.add_argument("--language", choices=['en', 'zh'], default='en')
    parser.add_argument("--operation-id", help="Reuse this ID with identical input after an uncertain result")
    commands = parser.add_subparsers(dest="command", required=True)
    state = commands.add_parser("state", help="Read the current project and material/candidate status")
    state.add_argument("--summary", action="store_true", help="Compact identities, revisions and pending work")
    inspect = commands.add_parser("inspect", help="Inspect model dependency closure and authoring gaps; read only")
    inspect.add_argument("--id", action="append", dest="asset_ids")
    connection = commands.add_parser("connect", help="Register a metadata-only connection; credentials use environment variable names")
    connection.add_argument("--file", required=True, help="Connection profile JSON, never a password or SQL")
    for command in ("scan", "regress"):
        item = commands.add_parser(command, help="Read selected catalog / check affected question contracts")
        item.add_argument("--connection", required=True)
        if command == "scan":
            item.add_argument("--seed-draft", action="store_true", help="Initialize an empty graph with physical drafts; never confirm business meaning")
            item.add_argument("--refresh-review", action="store_true", help="Explicitly regenerate unresolved candidates against current graph and a fresh catalog observation")
    commands.add_parser("example", help="Prepare authored proposals after reviewing the equipment example DDL; never confirms knowledge")
    scenario = commands.add_parser("scenario", help="Save a business question and selected knowledge, never confirm it")
    scenario.add_argument("--file", required=True, help="JSON scenario object; omit ID for a new question")
    check = commands.add_parser("check", help="Read current scenario context and gaps; no query, publication or answer validation")
    check.add_argument("--scenario", required=True)
    check.add_argument("--limit", type=int, default=50)
    check.add_argument("--offset", type=int, default=0)
    assess = commands.add_parser("assess", help="Record a local operator observation, evidence and checked fingerprint")
    assess.add_argument("--file", required=True, help="JSON with scenario_id, case_id, basis_fingerprint, outcome, observed, evidence, actor")
    impact = commands.add_parser("impact", help="Read registered source/definition changes and affected question paths")
    impact.add_argument("--scenario")
    handoff = commands.add_parser("handoff", help="Explicitly export a saved question with its dependency-closed semantic snapshot")
    handoff.add_argument("--scenario", required=True)
    handoff.add_argument("--out", required=True)
    handoff.add_argument("--draft", action="store_true")
    export = commands.add_parser("export", help="Export the model without a question or a running server")
    export.add_argument("--out", required=True)
    export.add_argument("--id", action="append", dest="asset_ids", help="Optional selected asset ID; repeat for multiple assets. Default: all active model assets")
    export.add_argument("--draft", action="store_true", help="Preserve draft status and unresolved gaps")
    export.add_argument("--include-execution", action="store_true", help="Also include existing execution declarations; does not authorize execution")
    material = commands.add_parser("import", help="Register material without overwriting the graph")
    material.add_argument("--file", required=True)
    material.add_argument("--domain", default="")
    material.add_argument("--scope", default="")
    material.add_argument("--source-id")
    material.add_argument("--distinct-source", action="store_true")
    material.add_argument("--seed-draft", action="store_true", help="DDL only: initialize an empty graph with editable physical drafts")
    task = commands.add_parser("task", help="Read material fragments and current graph for the selected host task")
    task.add_argument("--batch", required=True)
    task.add_argument("--scenario", help="Optional saved business question guiding this material task")
    task.add_argument("--action", choices=["prepare", "cancel", "resume"], default="prepare")
    proposal = commands.add_parser("propose", help="Submit evidence-linked candidate groups, never confirm them")
    proposal.add_argument("--batch", required=True)
    proposal.add_argument("--file", required=True)
    proposal.add_argument("--partial", action="store_true")
    review = commands.add_parser("review", help="Record an explicitly authorized operator decision; never auto-accept proposals")
    review.add_argument("--group", required=True)
    review.add_argument("--action", required=True, choices=["accept", "reject", "defer"])
    review.add_argument("--reason", required=True)
    review.add_argument("--assets", help="Optional JSON array of revised assets within this group")
    edit = commands.add_parser("edit", help="Maintain an asset through normal graph guards; draft unless explicitly confirmed")
    edit.add_argument("--file", required=True, help="Complete semantic asset object or atomic array; same-batch dependencies allowed")
    edit.add_argument("--confirm", action="store_true", help="Only when the operator has authorized confirmation")
    receipt = commands.add_parser("receipt", help="Read the durable result of an earlier operation")
    receipt.add_argument("id")
    args = parser.parse_args(argv)
    if args.command in {"state", "inspect", "check", "impact", "receipt", "export", "handoff"} and not (Path(args.project) / "project.sqlite").is_file():
        print(json.dumps({"ok": False, "status": "project_not_found", "error": "No project.sqlite here; check --project or import a schema first / 未找到项目，请核对路径或先导入结构"}, ensure_ascii=False))
        return 2
    store = Store(args.project)
    service = KnowledgeService(store)
    operation_id = args.operation_id or uuid.uuid4().hex
    req = {"revision": store.read()["revision"] if args.revision is None else args.revision, "operation_id": operation_id}
    try:
        if args.command == "state":
            result = service.state()
            if args.summary:
                result = {"revision": result["revision"], "project_id": result["project_id"],
                          "assets": [{k: a.get(k) for k in ("id", "name", "kind", "status")} for a in result["assets"]],
                          "sources": [{"id": a["id"], "name": a.get("name"), "current_revision": a.get("current_revision"),
                                       "revisions": [r["revision"] for r in a.get("revisions", [])]} for a in result["sources"]],
                          "pending_groups": [{k: a.get(k) for k in ("id", "batch_id", "status")} for a in result["groups"] if a.get("status") not in {"accepted", "rejected"}],
                          "batches": [{k: a.get(k) for k in ("id", "sources", "status")} for a in result["batches"]]}
        elif args.command == "inspect":
            from workbench.authoring_inspect import inspect_model
            current = service.state()
            result = {"revision": current["revision"], **inspect_model(current["assets"], current["sources"], asset_ids=args.asset_ids)}
        elif args.command == "connect":
            result = service.metadata_connect({**req, "connection": json.loads(Path(args.file).read_text(encoding="utf-8-sig"))})
        elif args.command in {"scan", "regress"}:
            result = getattr(service, "metadata_" + args.command)({**req, "connection_id": args.connection,
                **({"refresh_review": args.refresh_review, "seed_draft": args.seed_draft} if args.command == "scan" else {})})
        elif args.command == "receipt":
            result = {"receipt": store.operation(args.id)}
        elif args.command == "impact":
            result = service.impact({"scenario_id": args.scenario})
        elif args.command == "assess":
            data = json.loads(Path(args.file).read_text(encoding="utf-8-sig"))
            result = service.scenario_assess({**data, **req})
        elif args.command in {"handoff", "export"}:
            path = Path(args.out)
            if path.exists() or not path.parent.is_dir():
                raise ValueError("Choose a new output file in an existing directory / 请在已有目录中指定新文件")
            if args.command == "handoff":
                scope = {"scenario_id": args.scenario}
            else:
                selected = args.asset_ids if args.asset_ids is not None else [a["id"] for a in service.state()["assets"] if a["status"] != "retired"]
                if not selected:
                    raise ValueError("No model assets to export / 当前没有可导出的模型资产")
                scope = {"asset_ids": selected, "include_execution": args.include_execution}
            result = service.publish({**req, **scope, "draft": args.draft})
            created = False
            try:
                with path.open("xb") as stream:
                    created = True
                    stream.write(service.download(result["result"]["snapshot_id"]))
                    stream.flush()
                    os.fsync(stream.fileno())
            except OSError:
                if created:
                    path.unlink(missing_ok=True)
                raise
            result["output"] = str(path.resolve())
            manifest = result["result"]["manifest"]
            if not args.full_output and len(manifest["scope"].get("included_ids", [])) > 100:
                from collections import Counter
                result["result"]["manifest"] = {**{k:v for k,v in manifest.items() if k not in ("scope", "issues")},
                    "scope": scope_summary(manifest["scope"]), "issue_count": len(manifest["issues"]),
                    "issue_counts": dict(Counter(i["code"] for i in manifest["issues"])),
                    "full_receipt_option": "--full-output"}
        elif args.command == "import":
            path = Path(args.file)
            result = service.import_material({**req, "filename": path.name, "content_base64": base64.b64encode(path.read_bytes()).decode(),
                "domain": args.domain, "scope": args.scope, "language": args.language, "source_id": args.source_id, "distinct_source": args.distinct_source,
                "seed_draft": args.seed_draft})
        elif args.command == "task":
            result = service.task({**req, "batch_id": args.batch, "action": args.action, 'language': args.language,
                                   "scenario_id": args.scenario})
        elif args.command == "scenario":
            result = service.scenario({**req, "scenario": json.loads(Path(args.file).read_text(encoding="utf-8-sig"))})
        elif args.command == "check":
            result = service.scenario_check({"revision": req["revision"], "scenario_id": args.scenario,
                                             "limit": args.limit, "offset": args.offset})
        elif args.command == "example":
            result = service.example(req)
        elif args.command == "review":
            assets = json.loads(Path(args.assets).read_text(encoding="utf-8-sig")) if args.assets else []
            if not isinstance(assets, list):
                raise ValueError("Revised assets must be a JSON array / 修订资产须为 JSON 数组")
            if not args.reason.strip():
                raise ValueError("Describe the operator decision / 请填写操作者的核对理由")
            result = service.review({**req, "group_id": args.group, "action": args.action, "reason": args.reason, "assets": assets})
        elif args.command == "edit":
            result = service.edit({**req, **({"create_only": True} if args.revision is None else {}),
                                   "asset": json.loads(Path(args.file).read_text(encoding="utf-8-sig")), "confirm": args.confirm})
        else:
            data = json.loads(Path(args.file).read_text(encoding="utf-8-sig"))
            groups = data if isinstance(data, list) else data.get("groups")
            result = service.propose({**req, "batch_id": args.batch, "groups": groups, "complete": not args.partial})
        if args.command in {"import", "scan"} and args.seed_draft:
            detail = result["result"]
            result = {"revision": result["revision"], "result": {
                **{k: detail[k] for k in ("source_id", "batch_id", "seeded", "status") if k in detail},
                **bounded_warnings(detail.get("parsed", {}).get("warnings", []), full=args.full_output),
                "optional_editor_argv": [sys.executable, str(Path(__file__).with_name("start.py")), "--project", str(Path(args.project).resolve()), "--language", args.language]}}
            receipt = result["result"]
            seeded = receipt.get("seeded") or {}
            if not args.full_output and len(seeded.get("asset_ids", [])) > 100:
                receipt["seeded"] = {**{k:v for k,v in seeded.items() if k!="asset_ids"},
                                    "asset_id_count": len(seeded["asset_ids"]), "ids_omitted": True}
            if receipt.get("warnings_truncated") or (receipt.get("seeded") or {}).get("ids_omitted"):
                receipt["full_receipt_hint"] = "state for stored source details and asset IDs; --full-output before a command for verbose output"
        print(json.dumps({"ok": True, "operation_id": operation_id, "result": result}, ensure_ascii=False, allow_nan=False))
        return 0
    except (ValueError, OSError, TypeError) as exc:
        print(json.dumps({"ok": False, "operation_id": operation_id, "status": "conflict" if isinstance(exc, Conflict) else "error", "error": str(exc),
                          **({"details": exc.as_dict()} if isinstance(exc, PackageError) else {})}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
