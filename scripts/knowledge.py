#!/usr/bin/env python3
"""Host-agent tools for material intake and evidence-linked proposals.

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
from workbench.semantic_package import PackageError


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--revision", type=int)
    parser.add_argument("--language", choices=['en', 'zh'], default='en')
    parser.add_argument("--operation-id", help="Reuse this ID with identical input after an uncertain result")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("state", help="Read the current project and material/candidate status")
    connection = commands.add_parser("connect", help="Register a metadata-only connection; credentials use environment variable names")
    connection.add_argument("--file", required=True, help="Connection profile JSON, never a password or SQL")
    for command in ("scan", "regress"):
        item = commands.add_parser(command, help="Read selected catalog / check affected question contracts")
        item.add_argument("--connection", required=True)
        if command == "scan":
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
    material = commands.add_parser("import", help="Register material without overwriting the graph")
    material.add_argument("--file", required=True)
    material.add_argument("--domain", default="")
    material.add_argument("--scope", default="")
    material.add_argument("--source-id")
    material.add_argument("--distinct-source", action="store_true")
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
    edit.add_argument("--file", required=True, help="Complete semantic asset JSON")
    edit.add_argument("--confirm", action="store_true", help="Only when the operator has authorized confirmation")
    receipt = commands.add_parser("receipt", help="Read the durable result of an earlier operation")
    receipt.add_argument("id")
    args = parser.parse_args(argv)
    store = Store(args.project)
    service = KnowledgeService(store)
    operation_id = args.operation_id or uuid.uuid4().hex
    req = {"revision": store.read()["revision"] if args.revision is None else args.revision, "operation_id": operation_id}
    try:
        if args.command == "state":
            result = service.state()
        elif args.command == "connect":
            result = service.metadata_connect({**req, "connection": json.loads(Path(args.file).read_text(encoding="utf-8-sig"))})
        elif args.command in {"scan", "regress"}:
            result = getattr(service, "metadata_" + args.command)({**req, "connection_id": args.connection,
                **({"refresh_review": args.refresh_review} if args.command == "scan" else {})})
        elif args.command == "receipt":
            result = {"receipt": store.operation(args.id)}
        elif args.command == "impact":
            result = service.impact({"scenario_id": args.scenario})
        elif args.command == "assess":
            data = json.loads(Path(args.file).read_text(encoding="utf-8-sig"))
            result = service.scenario_assess({**data, **req})
        elif args.command == "handoff":
            path = Path(args.out)
            if path.exists() or not path.parent.is_dir():
                raise ValueError("Choose a new output file in an existing directory / 请在已有目录中指定新文件")
            result = service.publish({**req, "scenario_id": args.scenario, "draft": args.draft})
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
        elif args.command == "import":
            path = Path(args.file)
            result = service.import_material({**req, "filename": path.name, "content_base64": base64.b64encode(path.read_bytes()).decode(),
                "domain": args.domain, "scope": args.scope, "language": args.language, "source_id": args.source_id, "distinct_source": args.distinct_source})
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
            result = service.edit({**req, "asset": json.loads(Path(args.file).read_text(encoding="utf-8-sig")), "confirm": args.confirm})
        else:
            data = json.loads(Path(args.file).read_text(encoding="utf-8-sig"))
            groups = data if isinstance(data, list) else data.get("groups")
            result = service.propose({**req, "batch_id": args.batch, "groups": groups, "complete": not args.partial})
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
