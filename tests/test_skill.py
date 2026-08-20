from __future__ import annotations

import importlib.util
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "cascadeur-mcp-workflows"


def _coverage_module():
    script = SKILL / "scripts" / "validate_tool_coverage.py"
    spec = importlib.util.spec_from_file_location("cascadeur_skill_coverage", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_skill_catalog_covers_every_public_mcp_tool():
    module = _coverage_module()
    contract = module.public_mcp_tools(ROOT / "src" / "cascadeur_complete" / "server.py")
    catalog = module.catalog_tools(SKILL / "references" / "tool-routing.md")

    assert len(contract) == 75
    assert catalog == contract


def test_skill_entrypoint_links_resolve_inside_skill():
    entrypoint = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    local_links = re.findall(r"\]\((references/[^)]+)\)", entrypoint)

    assert local_links
    assert all((SKILL / link).is_file() for link in local_links)
