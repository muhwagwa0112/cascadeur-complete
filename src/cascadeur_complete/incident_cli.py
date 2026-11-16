"""Local operator controls; no approval is issued by an MCP prepare tool."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from . import incident_control as control, incident_store as store


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=None)
    commands = parser.add_subparsers(dest="command", required=True)
    enroll = commands.add_parser("enroll", help="Pin every known original auth/store domain; canonical root is mandatory")
    enroll.add_argument("--store", action="append", required=True, type=Path)
    commands.add_parser("inspect", help="Read all enrolled incident domains without the app")
    for name in ("approve-setup", "approve-retirement"):
        approval = commands.add_parser(name, help="Issue exact approval ONLY after the operator reviews and approves this plan")
        approval.add_argument("--plan-digest", required=True)
        approval.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    root = args.root or store.canonical_root()
    if args.command == "enroll":
        result = store.enroll_domains(args.store)
    elif args.command == "inspect":
        result = control.inspect(root)
    else:
        # Deliberately a separate local invocation, never implicit in prepare
        # or commit. Exclusive output cannot replace a prior approval artifact.
        if args.command == "approve-setup":
            from .incident_setup import approve_local
            result = approve_local(root, args.plan_digest)
        else:
            result = control.approve_retirement_local(root, args.plan_digest)
        store.publish_new(args.output, result)
        result = {"approval_path": str(args.output.absolute()), "plan_digest": args.plan_digest}
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
