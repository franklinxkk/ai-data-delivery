#!/usr/bin/env python3
"""Host-agent tools for material intake and evidence-linked proposals.

Read a prepared task, propose against its source revision, then let the operator
review the proposal in the workbench. No LLM, network or automatic confirmation.
"""
import argparse
import base64
import json
from pathlib import Path
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from workbench.store import Store, Conflict
from workbench.knowledge import KnowledgeService


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--revision", type=int)
    parser.add_argument("--language", choices=['en', 'zh'], default='en')
    parser.add_argument("--operation-id", help="Reuse this ID with identical input after an uncertain result")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("state", help="Read the current project and material/candidate status")
    commands.add_parser("example", help="Prepare authored proposals after reviewing the equipment example DDL; never confirms knowledge")
    scenario = commands.add_parser("scenario", help="Save a business question and selected knowledge, never confirm it")
    scenario.add_argument("--file", required=True, help="JSON scenario object; omit ID for a new question")
    check = commands.add_parser("check", help="Read current scenario context and gaps; no query, publication or answer validation")
    check.add_argument("--scenario", required=True)
    check.add_argument("--limit", type=int, default=50)
    check.add_argument("--offset", type=int, default=0)
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
        elif args.command == "receipt":
            result = {"receipt": store.operation(args.id)}
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
        else:
            data = json.loads(Path(args.file).read_text(encoding="utf-8-sig"))
            groups = data if isinstance(data, list) else data.get("groups")
            result = service.propose({**req, "batch_id": args.batch, "groups": groups, "complete": not args.partial})
        print(json.dumps({"ok": True, "operation_id": operation_id, "result": result}, ensure_ascii=False, allow_nan=False))
        return 0
    except (ValueError, OSError, TypeError) as exc:
        print(json.dumps({"ok": False, "operation_id": operation_id, "status": "conflict" if isinstance(exc, Conflict) else "error", "error": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
