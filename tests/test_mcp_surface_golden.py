"""Golden snapshot of the public MCP surface (tools, resources, templates).

Refactors must not change what MCP clients see. An intended API change updates
the snapshot in the same commit:

    CASCADEUR_UPDATE_GOLDEN=1 uv run --frozen --all-extras pytest tests/test_mcp_surface_golden.py
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from mcp import Client

from cascadeur_complete.server import mcp

GOLDEN = Path(__file__).parent / "golden" / "mcp_surface.json"


async def _surface() -> dict:
    async with Client(mcp) as client:
        tools = (await client.list_tools()).tools
        resources = (await client.list_resources()).resources
        templates = (await client.list_resource_templates()).resource_templates
    return {
        "tools": {item.name: _plain(item) for item in tools},
        "resources": {str(item.uri): _plain(item) for item in resources},
        "resource_templates": {_plain(item)["uri_template"]: _plain(item) for item in templates},
    }


def _plain(item) -> dict:
    return item.model_dump(mode="json", exclude_none=True)


def _dump(surface: dict) -> str:
    return json.dumps(surface, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


@pytest.mark.asyncio
async def test_mcp_surface_matches_golden_snapshot():
    surface = await _surface()
    if os.environ.get("CASCADEUR_UPDATE_GOLDEN") == "1":
        GOLDEN.parent.mkdir(exist_ok=True)
        GOLDEN.write_text(_dump(surface), encoding="utf-8", newline="\n")
    assert GOLDEN.is_file(), "missing golden snapshot; run with CASCADEUR_UPDATE_GOLDEN=1"
    expected = json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert sorted(surface["tools"]) == sorted(expected["tools"]), "tool set changed"
    for name, tool in surface["tools"].items():
        assert json.loads(_dump(tool)) == expected["tools"][name], f"tool {name} changed"
    assert json.loads(_dump(surface["resources"])) == expected["resources"]
    assert json.loads(_dump(surface["resource_templates"])) == expected["resource_templates"]
