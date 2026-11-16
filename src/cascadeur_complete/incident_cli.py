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
    manual = commands.add_parser("prepare-manual-setup", help="Draft one fresh bounded setup with explicit legacy residuals")
    manual.add_argument("--step", action="append", required=True)
    manual.add_argument("--workspace", type=Path, required=True)
    manual.add_argument("--review-open-incident", action="append", default=None,
        help="Explicitly name EVERY current open incident for a new local reviewed plan; repeat per UUID")
    for name in ("approve-manual-setup", "dispatch-manual-setup"):
        command = commands.add_parser(name, help="Review locally or submit the exact approved manual setup once")
        command.add_argument("--plan-digest", required=True)
    pair = commands.add_parser("prepare-pair-continuation", help="Draft a finite run from an actual succeeded owned-pair setup")
    pair.add_argument("--setup-plan-digest", required=True)
    pair.add_argument("--context-json", type=Path, required=True)
    pair.add_argument("--mutation-json", type=Path, default=None)
    for name in ("approve-pair-continuation", "run-pair-continuation"):
        command = commands.add_parser(name, help="Review the complete finite plan or run its exact steps once")
        command.add_argument("--plan-digest", required=True)
    args = parser.parse_args()
    root = args.root or store.canonical_root()
    if args.command == "enroll":
        result = store.enroll_domains(args.store)
    elif args.command == "inspect":
        result = control.inspect(root)
    elif args.command == "prepare-manual-setup":
        from .incident_manual_setup import prepare_with_runtime
        result = prepare_with_runtime(root, args.step, args.workspace,
            reviewed_incident_ids=args.review_open_incident)
    elif args.command == "approve-manual-setup":
        from .incident_manual_setup import approve_local
        result = approve_local(root, args.plan_digest)
    elif args.command == "dispatch-manual-setup":
        from .incident_manual_setup import dispatch
        result = dispatch(root, args.plan_digest)
    elif args.command == "prepare-pair-continuation":
        from .incident_pair_continuation import prepare
        result = prepare(root, args.setup_plan_digest, store.read(args.context_json),
            None if args.mutation_json is None else store.read(args.mutation_json))
    elif args.command == "approve-pair-continuation":
        from .incident_pair_continuation import approve_local
        result = approve_local(root, args.plan_digest)
    elif args.command == "run-pair-continuation":
        from .incident_pair_continuation import run
        result = run(root, args.plan_digest)
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
