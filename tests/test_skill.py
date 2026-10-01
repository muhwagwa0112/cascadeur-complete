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


def _server_kinds() -> set[str]:
    source = (ROOT / "src" / "cascadeur_complete" / "server.py").read_text(encoding="utf-8")
    block = source.split("def motion_cleanup_prepare(", 1)[1].split(") -> dict", 1)[0]
    literal = block.split("kind: Literal[", 1)[1].split("]", 1)[0]
    return set(re.findall(r'"([a-z_]+)"', literal))


def test_standard_workflow_document_covers_every_cleanup_kind_and_links_resolve():
    document = ROOT / "docs" / "MOCAP_CLEANUP_WORKFLOW.md"
    text = document.read_text(encoding="utf-8")
    kinds = _server_kinds()
    assert len(kinds) >= 8
    assert not {kind for kind in kinds if kind not in text}
    for link in re.findall(r"\]\((\.\./[^)#]+)\)", text):
        assert (document.parent / link).resolve().is_file(), link
    skill = (ROOT / "skills" / "cascadeur-mocap-cleanup" / "SKILL.md").read_text(encoding="utf-8")
    assert "MOCAP_CLEANUP_WORKFLOW.md" in skill
    assert "MOCAP_CLEANUP_WORKFLOW.md" in (ROOT / "README.md").read_text(encoding="utf-8")


def test_fbx_check_reads_curves_and_takes_from_a_binary_fbx(tmp_path):
    import struct

    import numpy as np

    script = ROOT / "skills" / "cascadeur-mocap-cleanup" / "scripts" / "fbx_check.py"
    spec = importlib.util.spec_from_file_location("fbx_check", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    def string(value):
        raw = value.encode()
        return b"S" + struct.pack("<I", len(raw)) + raw

    def node(name, properties=(), children=b"", base=0):
        body = b"".join(properties)
        header_size = 13 + len(name)
        end = base + header_size + len(body) + len(children)
        return struct.pack("<IIIB", end, len(properties), len(body), len(name)) + name.encode() + body + children

    def nested(name, properties, child_builders, base):
        # Children need absolute offsets: build them after the parent's header and properties.
        offset = base + 13 + len(name) + sum(len(item) for item in properties)
        children = b""
        for build in child_builders:
            children += build(offset + len(children))
        children += b"\x00" * 13
        return node(name, properties, children, base)

    times = (np.arange(5) * module.KTIME // 30).astype("<i8")
    key_time = b"l" + struct.pack("<III", len(times), 0, times.nbytes) + times.tobytes()
    header = b"Kaydara FBX Binary  \x00\x1a\x00" + struct.pack("<I", 7400)
    curve = nested(
        "AnimationCurve",
        [b"L" + struct.pack("<q", 7)],
        [lambda base: node("KeyTime", [key_time], base=base)],
        len(header),
    )
    stack = node(
        "AnimationStack",
        [b"L" + struct.pack("<q", 9), string("Take 001\x00\x01AnimStack")],
        base=len(header) + len(curve),
    )
    path = tmp_path / "tiny.fbx"
    path.write_bytes(header + curve + stack + b"\x00" * 13 + b"\x00" * 200)
    report = module.main(str(path))
    assert report["version"] == 7400 and report["takes"] == ["Take 001"]
    assert report["curves"] == 1 and report["keys_per_curve"] == {"min": 5, "median": 5, "max": 5}
    assert report["key_time_s"] == [0.0, round(4 / 30, 4)]
