"""Run live feature scenarios against the running Cascadeur and report evidence.

Usage:
  uv run python scripts/live_validate.py --all
  uv run python scripts/live_validate.py --fixture fixture.sample.cube
  uv run python scripts/live_validate.py timeline_get key_add
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import traceback
from pathlib import Path

from cascadeur_complete.discovery import discover_installation
from cascadeur_complete.live_validation import FIXTURES, SCENARIOS, LiveSession, run_scenario
from cascadeur_complete.uia import _native_cascadeur_handles


def ensure_cascadeur(session: LiveSession, restart_wait: float = 240.0) -> bool:
    """Relaunch Cascadeur after a crash so one crashing scenario cannot fail the rest.

    Returns True when a restart happened. Waits until the bridge answers and the
    license has been applied (the first seconds after start report Basic).
    """
    if _native_cascadeur_handles():
        return False
    subprocess.Popen([discover_installation()["executable"]], close_fds=True)
    deadline = time.monotonic() + restart_wait
    ready_since = None
    while time.monotonic() < deadline:
        time.sleep(5)
        status = session.service.refresh_live(timeout=30)
        if status.ok:
            ready_since = ready_since or time.monotonic()
            if session.service._license_name == "Pro" or time.monotonic() - ready_since > 30:
                break
    session.current_fixture = None
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("features", nargs="*")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--fixture", action="append", default=[])
    parser.add_argument("--skip-verified", action="store_true")
    args = parser.parse_args()
    if args.all:
        risky = sorted(name for name, item in SCENARIOS.items() if item.crash_risk)
        if risky:
            print("skipping crash-risk scenarios (run them by name): " + ", ".join(risky), file=sys.stderr)
        selected = [name for name, item in SCENARIOS.items() if not item.crash_risk]
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
        if ensure_cascadeur(session):
            print(f"RESTARTED Cascadeur after a crash (before {feature_id})", flush=True)
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
            if not _native_cascadeur_handles():
                row["error"] = "CASCADEUR CRASHED during this scenario; " + row["error"]
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
