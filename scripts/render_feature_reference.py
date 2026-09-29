"""Render the adapter-bound feature reference for the Cascadeur MCP skill.

The reference is generated from ``cascadeur_complete.adapter_bindings`` and the
product catalog, so it cannot drift from the runtime contract. Run after
editing bindings; ``tests/test_skill.py`` fails when the file is stale.
"""

from __future__ import annotations

import sys
from pathlib import Path

from cascadeur_complete.adapter_bindings import BINDINGS
from cascadeur_complete.product_catalog import PRODUCT_CATALOG

TARGET = (
    Path(__file__).resolve().parents[1] / "skills" / "cascadeur-mcp-workflows" / "references" / "adapter-features.md"
)
FAMILY_ORDER = (
    "objects",
    "editing",
    "animation",
    "generation",
    "physics",
    "rigging",
    "render",
    "io",
    "scene",
    "external",
)


def render() -> str:
    lines = [
        "# Adapter-bound features",
        "",
        "Generated from `cascadeur_complete.adapter_bindings` by `scripts/render_feature_reference.py`; "
        "do not edit by hand.",
        "",
        "Every row is a dedicated adapter with exact postconditions. Mutating rows run through",
        "`feature_prepare(feature_id, arguments)` and `change_commit(token)`; dialog rows can also use",
        "`file_dialog_prepare`. `fixed` arguments are pinned by the feature and must not be overridden.",
        "Check `feature_describe` for the live state: only `available` rows have live evidence on this build.",
        "",
    ]
    rows = sorted(
        BINDINGS,
        key=lambda item: (
            FAMILY_ORDER.index(PRODUCT_CATALOG.by_id[item.feature_id].family)
            if PRODUCT_CATALOG.by_id[item.feature_id].family in FAMILY_ORDER
            else len(FAMILY_ORDER),
            item.feature_id,
        ),
    )
    family = None
    for binding in rows:
        product = PRODUCT_CATALOG.by_id[binding.feature_id]
        if product.family != family:
            family = product.family
            lines += [
                "",
                f"## {family.title()}",
                "",
                "| Feature | Name | Operation | Arguments | Fixed | Postconditions |",
            ]
            lines.append("|---|---|---|---|---|---|")
        arguments = (
            ", ".join(f"`{key}`: {value}" for key, value in binding.arguments.items()).replace("|", r"\|") or "—"
        )
        fixed = ", ".join(f"`{key}={value}`" for key, value in binding.fixed_arguments.items()) or "—"
        post = ", ".join(f"`{item}`" for item in binding.postconditions)
        lines.append(
            f"| `{binding.feature_id}` | {product.name} | `{binding.operation}` | {arguments} | {fixed} | {post} |"
        )
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    text = render()
    if "--check" in sys.argv:
        return 0 if TARGET.is_file() and TARGET.read_text(encoding="utf-8") == text else 1
    TARGET.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {TARGET}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
