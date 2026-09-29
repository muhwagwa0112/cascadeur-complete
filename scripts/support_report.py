"""Write docs/SUPPORT_STATUS.md from the live evidence recorded on this machine.

The report uses the same registry the MCP server builds, so a row is
``supported`` only with current live evidence on the pinned build (or, for
host-only features, contract evidence). Gated rows list their exact reason.
"""

from __future__ import annotations

import collections
import datetime
from pathlib import Path

from cascadeur_complete.service import CascadeurService

TARGET = Path(__file__).resolve().parents[1] / "docs" / "SUPPORT_STATUS.md"

GATE_REASON = {
    "license_gated": "requires a Cascadeur Pro license (this machine: {license})",
    "missing_dependency": "requires {dependency}",
    "unsupported": "the pinned build exposes no such capability",
    "unsupported_version": "installed build differs from the pinned build",
    "ui_only": "only reachable through Cascadeur's QML UI; no safe action id or Python API in the pinned build",
    "not_implemented": "no adapter yet",
    "unhealthy": "adapter present, no current live evidence on this machine",
    "needs_scene": "adapter present, no current live evidence on this machine",
}


def main() -> int:
    service = CascadeurService()
    status = service.capabilities(live=False)
    coverage = status["product_coverage"]
    product = [item for item in service.features if item.truth_layer == "product"]
    supported = [
        item
        for item in product
        # "needs_scene" only means no scene is open while the report runs.
        if item.state.value in ("available", "needs_scene")
        and (item.verification.value == "verified_live" or item.route.startswith("host."))
    ]
    lines = [
        "# Support status",
        "",
        f"Generated {datetime.date.today().isoformat()} by `scripts/support_report.py` for Cascadeur "
        f"`{status['baseline']}` (license: {service._license_name}).",
        "",
        f"**{len(supported)} of {coverage['catalog_count']} product features are supported** "
        "(dedicated adapter + exact postconditions + live evidence on this build; host-only features by contract).",
        "",
        "| State | Count |",
        "|---|---|",
    ]
    counts = collections.Counter(
        "supported" if item in supported else item.state.value for item in product
    )
    lines += [f"| {state} | {count} |" for state, count in sorted(counts.items(), key=lambda row: -row[1])]
    lines += ["", "## Not supported on this machine", "", "| Feature | Family | State | Reason |", "|---|---|---|---|"]
    for item in sorted((row for row in product if row not in supported), key=lambda row: (row.state.value, row.id)):
        reason = GATE_REASON.get(item.state.value, item.state.value).format(
            license=service._license_name, dependency=item.dependency or "an external integration"
        )
        lines.append(f"| `{item.id}` | {item.family} | {item.state.value} | {reason} |")
    lines += ["", "## Supported", "", "| Feature | Family | Mode | Evidence |", "|---|---|---|---|"]
    for item in sorted(supported, key=lambda row: (row.family, row.id)):
        evidence = "live" if item.verification.value == "verified_live" else "host contract"
        lines.append(f"| `{item.id}` | {item.family} | {item.execution_mode.value} | {evidence} |")
    TARGET.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print(f"{len(supported)}/{coverage['catalog_count']} supported; wrote {TARGET}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
