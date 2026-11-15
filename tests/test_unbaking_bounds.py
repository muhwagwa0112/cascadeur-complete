"""Unbaking authority and projection bounds; no live action completion claim."""
from copy import deepcopy
import importlib

import pytest

from tests.bridge_support import loaded_bridge


@pytest.fixture
def native():
    with loaded_bridge("unbaking_bounds_bridge"):
        yield importlib.import_module("unbaking_bounds_bridge.native_unbaking")


def arguments(**policy):
    return {"step": "adjust_keys_and_interpolation", "object_ids": ["target"], "layer_ids": ["layer"],
        "first_frame": 0, "last_frame": 4, "topology_policy": {"allow_key_insertion": True,
        "allow_interpolation_change": False, "maximum_added_keys": 1, "maximum_removed_keys": 1,
        "maximum_written_keys": 3, **policy}}


def section(frame):
    return {"frame": frame, "interpolation": "LINEAR", "description_for_ai_interpolation": "",
        "tangents": "Auto", "label": None, "left_weight_velocity": 1., "right_weight_velocity": 1.,
        "key_common": {"ik_fk": "FK", "fixation": "Free"},
        "interval_common": {"ik_fk": "FK", "fixation": "Free"}}


def projection():
    return {"schema_version": 1, "reader": "native-model-assets-v1", "frames": 6,
        "objects": [{"id": "target", "behaviours": []}, {"id": "other", "behaviours": []}],
        "layers": [{"id": "layer", "locked": False, "visible": True, "object_ids": ["target"],
            "keys": [0, 4], "sections": [section(0), section(4)]},
            {"id": "other-layer", "locked": False, "visible": True, "object_ids": ["other"],
             "keys": [0, 4], "sections": [section(0), section(4)]}],
        "data": [{"id": "position", "owner": "target", "mode": "Animation", "values": [0.] * 6}],
        "settings": [], "assets": [], "additive": {"stacked_layers_count": 0, "current_layer_index": 0}}


@pytest.mark.parametrize("change", [
    {"maximum_added_keys": True}, {"maximum_written_keys": -1},
    {"allow_interpolation_change": 1}, {"allow_key_insertion": False},
    {"maximum_written_keys": 1}, {"maximum_removed_keys": float("inf")}, {"extra": 1},
])
def test_unbaking_native_rejects_implicit_or_invalid_policy(native, change):
    with pytest.raises(ValueError, match="INVALID_POLICY"):
        native.validate_arguments(arguments(**change))


def test_unbaking_native_requires_policy_before_capture(native):
    value = arguments()
    del value["topology_policy"]
    with pytest.raises(ValueError, match="INVALID_WRITE_SCOPE"):
        native.capture_before(object(), value)


def test_unbaking_native_normalizes_only_the_observed_sdk_no_label(native, monkeypatch):
    import sys
    from types import ModuleType, SimpleNamespace
    csc = sys.modules["csc"]
    layers, layer = ModuleType("csc.layers"), ModuleType("csc.layers.layer")
    layer.Key = SimpleNamespace(no_label_id=lambda: -37)
    layers.layer = layer
    monkeypatch.setattr(csc, "layers", layers, raising=False)
    monkeypatch.setitem(sys.modules, "csc.layers", layers)
    monkeypatch.setitem(sys.modules, "csc.layers.layer", layer)
    reader = importlib.import_module("unbaking_bounds_bridge.native_scene_reader")
    raw = projection()
    raw["layers"][0]["sections"][0]["label"] = -37
    raw["layers"][0]["sections"][1]["label"] = 42
    monkeypatch.setattr(reader, "read_scene", lambda scene: deepcopy(raw))
    captured = native.capture_before(object(), arguments())
    assert captured["layers"][0]["sections"][0]["label"] is None
    assert captured["layers"][0]["sections"][1]["label"] == 42
    assert raw["layers"][0]["sections"][0]["label"] == -37


def test_unbaking_projection_counts_observed_effects_without_claiming_completion(native):
    before = projection()
    after = deepcopy(before)
    after["layers"][0]["keys"].insert(1, 2)
    after["layers"][0]["sections"].insert(1, section(2))
    after["data"][0]["values"][2] = 1.
    after["data"][0]["values"][3] = 2.
    result = native.compare_projections(before, after, arguments())
    assert (result["added_keys"], result["removed_keys"], result["written_keys"]) == (1, 0, 1)
    assert result["native_completion"] == "unverified"
    assert result["status"] == "observed_within_bounds"
    assert result["before_projection_digest"] != result["after_projection_digest"]
    with pytest.raises(ValueError, match="KEY_BUDGET_EXCEEDED"):
        native.compare_projections(before, after, arguments(maximum_added_keys=0, maximum_removed_keys=0))


@pytest.mark.parametrize("change", ["outside_interval", "non_target", "shared_data", "labeled_value",
    "existing_interpolation", "new_interpolation", "fixed_removal"])
def test_unbaking_projection_rejects_protected_or_unapproved_effects(native, change):
    before = projection()
    if change == "shared_data":
        before["objects"][1]["behaviours"] = [{"properties": [{"kind": "DataType", "value": "position"}]}]
    if change == "labeled_value":
        before["layers"][0]["sections"][0]["label"] = "event"
    if change == "fixed_removal":
        before["layers"][0]["sections"][1]["key_common"]["fixation"] = "Fixed"
    after = deepcopy(before)
    if change == "outside_interval":
        after["data"][0]["values"][5] = 1.
    elif change == "non_target":
        after["layers"][1]["sections"][0]["interpolation"] = "STEP"
    elif change in {"shared_data", "labeled_value"}:
        after["data"][0]["values"][1] = 1.
    elif change == "existing_interpolation":
        after["layers"][0]["sections"][0]["interpolation"] = "STEP"
    elif change == "new_interpolation":
        after["layers"][0]["keys"].insert(1, 2)
        row = section(2)
        row["interpolation"] = "STEP"
        after["layers"][0]["sections"].insert(1, row)
    else:
        after["layers"][0]["keys"].pop()
        after["layers"][0]["sections"].pop()
    with pytest.raises(ValueError, match="UNBAKING_SCOPE_VIOLATION"):
        native.compare_projections(before, after, arguments())


def test_unbaking_projection_requires_separate_interpolation_and_removal_permissions(native):
    before = projection()
    after = deepcopy(before)
    after["layers"][0]["sections"][0]["interpolation"] = "STEP"
    observed = native.compare_projections(before, after, arguments(allow_interpolation_change=True))
    assert observed["written_keys"] == 1 and observed["native_completion"] == "unverified"
    after = deepcopy(before)
    after["layers"][0]["keys"].pop()
    after["layers"][0]["sections"].pop()
    observed = native.compare_projections(before, after, arguments())
    assert observed["removed_keys"] == observed["written_keys"] == 1
    with pytest.raises(ValueError, match="KEY_BUDGET_EXCEEDED"):
        native.compare_projections(before, after, arguments(maximum_removed_keys=0))


@pytest.mark.asyncio
async def test_unbaking_public_mcp_requires_and_forwards_explicit_policy(monkeypatch):
    from mcp import Client
    from cascadeur_complete import server
    observed = []
    monkeypatch.setattr(server, "_prepare", lambda feature, operation, args, ttl, source: (
        observed.append((feature, operation, args)) or {"prepared": True}))
    async with Client(server.mcp) as client:
        request = arguments()
        missing = {key: value for key, value in request.items() if key != "topology_policy"}
        rejected = await client.call_tool("animation_unbaking_prepare", missing)
        assert rejected.is_error and observed == []
        accepted = await client.call_tool("animation_unbaking_prepare", request)
        assert not accepted.is_error
        assert observed == [("unbaking", "generation.unbaking", request)]
