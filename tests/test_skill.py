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


def test_adapter_feature_reference_matches_bindings():
    spec = importlib.util.spec_from_file_location(
        "render_feature_reference", ROOT / "scripts" / "render_feature_reference.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module.TARGET.read_text(encoding="utf-8") == module.render()


def test_mocap_cleanup_skill_links_resolve_and_name_the_cleanup_tools():
    skill = ROOT / "skills" / "cascadeur-mocap-cleanup"
    entrypoint = (skill / "SKILL.md").read_text(encoding="utf-8")
    assert entrypoint.startswith("---\nname: cascadeur-mocap-cleanup\n")
    local_links = re.findall(r"\]\((references/[^)]+)\)", entrypoint)
    assert len(local_links) >= 5
    assert all((skill / link).is_file() for link in local_links)
    contract = _coverage_module().public_mcp_tools(ROOT / "src" / "cascadeur_complete" / "server.py")
    text = "".join(path.read_text(encoding="utf-8") for path in (skill / "references").glob("*.md"))
    for tool in ("motion_cleanup_analyze", "motion_cleanup_prepare", "change_commit", "key_reduction_prepare"):
        assert tool in contract and tool in text
