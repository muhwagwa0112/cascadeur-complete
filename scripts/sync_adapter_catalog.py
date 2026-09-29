"""Write adapter bindings into the product catalog.

Promotes ``official_gap.*`` rows to their bound feature ids and marks every
bound feature as implemented with its exact operation, postconditions and
argument contract. Run after editing ``cascadeur_complete.adapter_bindings``,
then run ``scripts/sync_live_catalog.py`` to bind live scenarios.
"""

from __future__ import annotations

import json
from pathlib import Path

from cascadeur_complete.adapter_bindings import BINDINGS
from cascadeur_complete.product_catalog import CATALOG_FILE_NAME

CATALOG = Path(__file__).resolve().parents[1] / "inventory" / CATALOG_FILE_NAME
CONTRACT_TESTS = [
    "tests/test_postcondition_contract.py::test_every_live_feature_postcondition_is_asserted",
    "tests/test_adapter_bindings.py::test_catalog_rows_match_adapter_bindings",
]


def main() -> int:
    payload = json.loads(CATALOG.read_text(encoding="utf-8"))
    rows = {row["id"]: row for row in payload["features"]}
    changed = 0
    for binding in BINDINGS:
        if binding.replaces and binding.replaces in rows:
            if binding.feature_id in rows:
                raise SystemExit(f"{binding.feature_id} already exists; cannot promote {binding.replaces}")
            row = rows.pop(binding.replaces)
            row["id"] = binding.feature_id
            rows[binding.feature_id] = row
        row = rows.get(binding.feature_id)
        if row is None:
            raise SystemExit(f"Catalog has no row for {binding.feature_id}")
        update = {
            "implementation_status": "implemented",
            "route": binding.operation,
            "action": binding.operation,
            "operation": binding.operation,
            "adapter_id": f"cascadeur_2026_1.{binding.operation}",
            "execution_mode": binding.mode.value,
            "preconditions": list(binding.preconditions),
            "postconditions": list(binding.postconditions),
            "mutation": binding.mutation,
            "requires_scene": binding.requires_scene,
            "contract_test_ids": list(CONTRACT_TESTS),
            "arguments": dict(binding.arguments),
            "fixed_arguments": dict(binding.fixed_arguments),
        }
        if any(row.get(key) != value for key, value in update.items()):
            row.update(update)
            changed += 1
    order = [row["id"] for row in payload["features"]]
    renamed = {binding.replaces: binding.feature_id for binding in BINDINGS if binding.replaces}
    payload["features"] = [rows[renamed.get(item, item)] for item in order]
    CATALOG.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"updated {changed} catalog rows from {len(BINDINGS)} adapter bindings")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
