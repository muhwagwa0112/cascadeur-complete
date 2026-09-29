"""Run live feature scenarios against the running Cascadeur and report evidence.

Usage:
  uv run python scripts/live_validate.py --all
  uv run python scripts/live_validate.py --fixture fixture.sample.cube
  uv run python scripts/live_validate.py timeline_get key_add
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from pathlib import Path

from cascadeur_complete.live_validation import FIXTURES, SCENARIOS, LiveSession, run_scenario


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("features", nargs="*")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--fixture", action="append", default=[])
    parser.add_argument("--skip-verified", action="store_true")
    args = parser.parse_args()
    if args.all:
        selected = list(SCENARIOS)
    else:
        selected = [item for item in SCENARIOS if SCENARIOS[item].fixture_id in args.fixture] + [
            item for item in args.features if item in SCENARIOS
        ]
        unknown = [item for item in args.features if item not in SCENARIOS]
        if unknown:
            print("unknown scenarios: " + ", ".join(unknown), file=sys.stderr)
            return 2
    fixture_order = {name: index for index, name in enumerate(FIXTURES)}
    registration = {name: index for index, name in enumerate(SCENARIOS)}
    selected = sorted(
        dict.fromkeys(selected),
        key=lambda item: (fixture_order[SCENARIOS[item].fixture_id], registration[item]),
    )
    session = LiveSession()
    report = []
    for feature_id in selected:
        if args.skip_verified and session.verified(feature_id):
            report.append({"feature_id": feature_id, "verified": True, "skipped": True})
            continue
        started = time.monotonic()
        try:
            row = run_scenario(session, feature_id)
        except Exception as exc:  # report and continue with the next scenario
            row = {
                "feature_id": feature_id,
                "fixture_id": SCENARIOS[feature_id].fixture_id,
                "verified": session.verified(feature_id),
                "error": f"{type(exc).__name__}: {exc}"[:2000],
                "trace": traceback.format_exc(limit=4)[-1500:],
                "seconds": round(time.monotonic() - started, 1),
            }
            session.current_fixture = None
        report.append(row)
        mark = "PASS" if row.get("verified") else "FAIL"
        print(f"{mark} {feature_id:28} {row.get('seconds', 0):6}s {row.get('error', '')[:300]}", flush=True)
    output = session.output_root / f"report-{int(time.time())}.json"
    Path(output).write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    verified = sum(1 for item in report if item.get("verified"))
    print(f"verified {verified}/{len(report)}; report: {output}")
    return 0 if verified == len(report) else 1


if __name__ == "__main__":
    raise SystemExit(main())
