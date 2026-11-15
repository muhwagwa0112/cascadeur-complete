"""Direct bounds and publication checks; no creative application is launched."""
import hashlib
import json
import os
import struct
import time
import zlib
from dataclasses import replace
from types import SimpleNamespace
import numpy as np

import pytest

from cascadeur_complete.export_models import ArtifactRef, PublishPermit, ValidationBundle, ValidationReport
from cascadeur_complete.export_publisher import publish_verified, reconcile_publish
from cascadeur_complete.fbx_validation import (
    FbxError, FOOTER_END, FOOTER_START, MAGIC, NEW_KTIME, LEGACY_KTIME,
    ParseLimits, read_fbx_structure, timebase,
    FbxDocument, FbxNode, validate_fbx_structure,
)


def _node(name, props=(), children=(), base=27, version=7700):
    header = struct.Struct("<QQQB" if version >= 7500 else "<IIIB")
    body = b"".join(props)
    offset = base + header.size + len(name) + len(body)
    nested = b""
    for child in children:
        data = child(offset + len(nested))
        nested += data
    if children:
        nested += bytes(header.size)
    end = offset + len(nested)
    return header.pack(end, len(props), len(body), len(name)) + name.encode() + body + nested


def _file(path, nodes, version=7700):
    data = MAGIC + struct.pack("<I", version)
    for node in nodes:
        data += node(len(data))
    data += bytes(25 if version >= 7500 else 13)
    data += FOOTER_START + bytes(4) + struct.pack("<I", version) + bytes(120) + FOOTER_END
    path.write_bytes(data)
    return path


@pytest.mark.parametrize("flag,clock", [(0, NEW_KTIME), (127, LEGACY_KTIME)])
def test_exact_footer_and_tcdefinition(tmp_path, flag, clock):
    path = _file(tmp_path / "clock.fbx", [lambda b: _node("FBXHeaderExtension", children=[
        lambda x: _node("TCDefinition", [b"I" + struct.pack("<i", flag)], base=x)
    ], base=b)])
    doc = read_fbx_structure(path)
    assert doc.footer_verified and timebase(doc) == clock
    path.write_bytes(path.read_bytes()[:-1])
    with pytest.raises(FbxError, match="FBX_FOOTER_UNSUPPORTED"):
        read_fbx_structure(path)


def test_compressed_array_cannot_exceed_declared_or_total_budget(tmp_path):
    compressed = zlib.compress(bytes(100000))
    prop = b"d" + struct.pack("<III", 1, 1, len(compressed)) + compressed
    path = _file(tmp_path / "bomb.fbx", [lambda b: _node("Values", [prop], base=b)])
    with pytest.raises(FbxError, match="FBX_INVALID_COMPRESSION"):
        read_fbx_structure(path)
    prop = b"d" + struct.pack("<III", 100, 0, 800) + bytes(800)
    _file(path, [lambda b: _node("Values", [prop], base=b)])
    with pytest.raises(FbxError, match="FBX_RESOURCE_LIMIT"):
        read_fbx_structure(path, ParseLimits(max_decompressed_bytes=100))


def test_node_offset_cannot_escape_container(tmp_path):
    path = _file(tmp_path / "offset.fbx", [lambda b: _node("Values", base=b)])
    data = bytearray(path.read_bytes())
    struct.pack_into("<Q", data, 27, len(data) + 1)
    path.write_bytes(data)
    with pytest.raises(FbxError, match="FBX_NODE_OFFSET"):
        read_fbx_structure(path)


def test_structure_checks_actual_curve_graph_and_dense_grid(tmp_path):
    from cascadeur_complete.export_models import ExportProfile
    profile = ExportProfile(character_ref="character", skeleton_map=[
        {"role": "root", "node_path": "Root", "source_id": "1"}], take_name="Take",
        first_frame=0, last_frame=2, fps_num=30, axes={"up_axis": 1, "up_sign": 1,
        "front_axis": 2, "front_sign": -1, "coord_axis": 0, "coord_sign": 1},
        metres_per_export_unit=.01, root_motion={"node_path": "Root"}, target_adapter="unavailable",
        target_adapter_fingerprint="unavailable", target_import_settings_digest="unavailable",
        required_channels=[{"node_path": "Root", "property": "Lcl Translation", "axis": "X", "animated": True}],
        destination=str(tmp_path / "out.fbx"))
    def named(values):
        return (FbxNode("Properties70", (), tuple(FbxNode("P", (key, "", "", "", value), ())
                                                  for key, value in values.items())),)
    ticks = np.arange(3, dtype=np.int64) * (LEGACY_KTIME // 30)
    settings = {"UpAxis": 1, "UpAxisSign": 1, "FrontAxis": 2, "FrontAxisSign": -1,
                "CoordAxis": 0, "CoordAxisSign": 1, "UnitScaleFactor": 1., "TimeMode": 6,
                "TimeSpanStart": 0, "TimeSpanStop": int(ticks[-1])}
    objects = (FbxNode("Model", (1, "Root", "LimbNode"), ()),
               FbxNode("AnimationStack", (2, "Take", ""), named({"LocalStart": 0, "LocalStop": int(ticks[-1])})),
               FbxNode("AnimationLayer", (3, "Layer", ""), ()),
               FbxNode("AnimationCurveNode", (4, "T", ""), ()),
               FbxNode("AnimationCurve", (5, "Curve", ""), (
                   FbxNode("KeyTime", (ticks,), ()), FbxNode("KeyValueFloat", (np.arange(3.),), ()))))
    connections = (FbxNode("C", ("OO", 1, 0), ()), FbxNode("C", ("OO", 3, 2), ()),
                   FbxNode("C", ("OO", 4, 3), ()), FbxNode("C", ("OP", 4, 1, "Lcl Translation"), ()),
                   FbxNode("C", ("OP", 5, 4, "d|X"), ()))
    doc = FbxDocument(7400, (FbxNode("GlobalSettings", (), named(settings)),
        FbxNode("Objects", (), objects), FbxNode("Connections", (), connections)), "a"*64, 100, True)
    expected = SimpleNamespace(time_s=(0., 1/30, 2/30), parent_paths={"Root": None})
    assert validate_fbx_structure(doc, profile, expected).status == "pass"
    broken = replace(doc, nodes=doc.nodes[:2] + (FbxNode("Connections", (), connections[:-1]),))
    assert "EXPORT_CURVE_TAKE_MEMBERSHIP" in validate_fbx_structure(broken, profile, expected).reason_codes
    sparse = replace(objects[-1], children=(FbxNode("KeyTime", (ticks[[0, 2]],), ()),
                                           FbxNode("KeyValueFloat", (np.array([0., 2.]),), ())))
    broken = replace(doc, nodes=(doc.nodes[0], FbxNode("Objects", (), objects[:-1] + (sparse,)), doc.nodes[-1]))
    assert "EXPORT_DENSE_COVERAGE" in validate_fbx_structure(broken, profile, expected).reason_codes


def _publication(tmp_path, mode="fail_if_exists"):
    sealed = tmp_path / "sealed.fbx"
    sealed.write_bytes(b"validated exact artifact")
    digest = hashlib.sha256(sealed.read_bytes()).hexdigest()
    artifact = ArtifactRef(path=str(sealed), sha256=digest, bytes=sealed.stat().st_size)
    report = ValidationReport(status="pass", artifact_sha256=digest)
    bundle = ValidationBundle(artifact_sha256=digest, execution="succeeded", quality="pass",
                              structure=report, target=report, source_capture_digest="a" * 64,
                              profile_digest="b" * 64)
    permit = PublishPermit(destination=str(tmp_path / "final.fbx"), authorization_digest="c" * 64,
                           artifact_sha256=digest, profile_digest="b" * 64, expires_at=time.time()+60,
                           run_id="run", step_id="step", overwrite_mode=mode,
                           overwrite_semantics="replace_any_current_content" if mode == "replace_path" else "none")
    return artifact, bundle, permit


def test_publication_retains_separate_inode_and_reconciles(tmp_path):
    artifact, bundle, permit = _publication(tmp_path)
    result = publish_verified(artifact, bundle, permit)
    assert result["status"] == "published"
    assert not os.path.samestat(os.stat(artifact.path), os.stat(permit.destination))
    assert reconcile_publish(result["intent_path"])["status"] == "published"
    assert publish_verified(artifact, bundle, permit)["status"] == "published"
    # Replacing a final file with identical bytes is not this publication.
    replacement = tmp_path / "replacement"
    replacement.write_bytes(Path(artifact.path).read_bytes())
    os.replace(replacement, permit.destination)
    assert reconcile_publish(result["intent_path"])["reason"] == "destination_identity_conflict"


from pathlib import Path


def test_no_clobber_preserves_existing_bytes(tmp_path):
    artifact, bundle, permit = _publication(tmp_path)
    Path(permit.destination).write_bytes(b"existing owner")
    result = publish_verified(artifact, bundle, permit)
    assert result["status"] == "failed" and result["reason"] == "destination_exists"
    assert Path(permit.destination).read_bytes() == b"existing owner"


def test_explicit_replace_is_exact_path_and_preserves_sealed(tmp_path):
    artifact, bundle, permit = _publication(tmp_path, "replace_path")
    Path(permit.destination).write_bytes(b"older")
    assert publish_verified(artifact, bundle, permit)["status"] == "published"
    assert Path(artifact.path).read_bytes() == Path(permit.destination).read_bytes()
    assert not os.path.samestat(os.stat(artifact.path), os.stat(permit.destination))


def test_nonzero_consumer_cannot_succeed_with_a_report_marker(monkeypatch):
    from cascadeur_complete import external
    monkeypatch.setattr(external, "find_blender", lambda: Path("blender.exe"))
    monkeypatch.setattr(external.subprocess, "run", lambda *a, **kw: SimpleNamespace(
        returncode=2, stdout=external._MARKER + '{"bones": 100}', stderr="import failed"))
    with pytest.raises(RuntimeError, match="exit code 2"):
        external.verify_blender_fbx("input.fbx")


def test_blender45_requires_the_assigned_slot_and_single_channelbag():
    from cascadeur_complete.blender_export_adapter import _action_binding
    slot = object()
    curves = (object(),)
    strip = SimpleNamespace(channelbag=lambda assigned: SimpleNamespace(fcurves=curves) if assigned is slot else None)
    action = SimpleNamespace(slots=[slot], layers=[SimpleNamespace(strips=[strip])])
    animation = SimpleNamespace(action=action, action_slot=slot)
    obj = SimpleNamespace(animation_data=animation)
    assert _action_binding(obj, (4, 5, 3)) == (action, curves)
    animation.action_slot = object()
    with pytest.raises(ValueError, match="TARGET_ACTION_SLOT_AMBIGUOUS"):
        _action_binding(obj, (4, 5, 3))
