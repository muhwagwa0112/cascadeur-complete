"""Bind catalog fixture/live-test identities to the registered live scenarios.

Run after adding or moving a scenario. Evidence records are bound to these
identities, so changing a scenario's fixture invalidates earlier evidence.
"""

from __future__ import annotations

import json
from pathlib import Path

from cascadeur_complete.live_validation import SCENARIOS
from cascadeur_complete.product_catalog import CATALOG_FILE_NAME

CATALOG = Path(__file__).resolve().parents[1] / "inventory" / CATALOG_FILE_NAME


def main() -> int:
    payload = json.loads(CATALOG.read_text(encoding="utf-8"))
    changed = 0
    for feature in payload["features"]:
        item = SCENARIOS.get(feature["id"])
        fixture = item.fixture_id if item else None
        live_test = item.live_test_id if item else None
        if feature.get("fixture_id") != fixture or feature.get("live_test_id") != live_test:
            feature["fixture_id"] = fixture
            feature["live_test_id"] = live_test
            changed += 1
    CATALOG.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"updated {changed} catalog rows; {len(SCENARIOS)} scenarios registered")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
