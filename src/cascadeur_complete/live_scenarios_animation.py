"""Live scenarios for timeline, key, generation and physics editing on an animated character."""

from __future__ import annotations

from typing import Any

from .live_scenarios import BACKFLIP
from .live_scenarios_scene import center_of_mass
from .live_validation import LiveSession, LiveValidationError, scenario


def animated_layer(s: LiveSession, rank: int = 0) -> tuple[str, list[int]]:
    layers = sorted(s.layers(), key=lambda item: -len(item["keys"]))
    return layers[rank]["id"], sorted(layers[rank]["keys"])


def layer_with_gap(s: LiveSession) -> tuple[str, list[int], int]:
    for layer in sorted(s.layers(), key=lambda item: -len(item["keys"])):
        keys = sorted(layer["keys"])
        for left, right in zip(keys, keys[1:], strict=False):
            if right - left > 1:
                return layer["id"], keys, left + 1
    raise LiveValidationError("no layer has a free frame between keys")


def gap_frame(keys: list[int]) -> int:
    for left, right in zip(keys, keys[1:], strict=False):
        if right - left > 1:
            return left + 1
    raise LiveValidationError("layer has no free frame between keys")


@scenario("timeline_get", BACKFLIP)
def _timeline_get(s: LiveSession) -> Any:
    return s.read("timeline_get", "timeline.get")


@scenario("timeline_set_frame", BACKFLIP)
def _timeline_set_frame(s: LiveSession) -> Any:
    return s.change("timeline_set_frame", "timeline.set_frame", {"frame": 12})


@scenario("timeline_range", BACKFLIP)
def _timeline_range(s: LiveSession) -> Any:
    return s.read("timeline_range", "timeline.range", {"first_frame": 0, "last_frame": 40})


@scenario("layer_list", BACKFLIP)
def _layer_list(s: LiveSession) -> Any:
    return {"layers": len(s.read("layer_list", "layer.list"))}


@scenario("layer_create", BACKFLIP)
def _layer_create(s: LiveSession) -> Any:
    created = s.change("layer_create", "layer.create", {"name": "MCP Live Layer"})
    s.live_layer = created["layer_id"]
    return created


def _live_layer(s: LiveSession) -> str:
    layer = getattr(s, "live_layer", None)
    if layer and any(item["id"] == layer for item in s.layers()):
        return layer
    return _layer_create(s)["layer_id"]


@scenario("layer_visibility", BACKFLIP)
def _layer_visibility(s: LiveSession) -> Any:
    return s.change("layer_visibility", "layer.visibility", {"layer_id": _live_layer(s), "visible": False})


@scenario("layer_lock", BACKFLIP)
def _layer_lock(s: LiveSession) -> Any:
    return s.change("layer_lock", "layer.lock", {"layer_id": _live_layer(s), "locked": True})


@scenario("layer_folder", BACKFLIP)
def _layer_folder(s: LiveSession) -> Any:
    return s.change("layer_folder", "layer.folder", {"action": "create", "name": "MCP Folder"})


@scenario("layer_delete", BACKFLIP)
def _layer_delete(s: LiveSession) -> Any:
    return s.change("layer_delete", "layer.delete", {"layer_id": _live_layer(s)})


@scenario("layer_activate", BACKFLIP)
def _layer_activate(s: LiveSession) -> Any:
    layer, _keys = animated_layer(s)
    return s.change("layer_activate", "layer.activate", {"layer_id": layer})


@scenario("key_list", BACKFLIP)
def _key_list(s: LiveSession) -> Any:
    layer, _keys = animated_layer(s)
    return {"keys": len(s.read("key_list", "animation.key_list", {"layer_id": layer})["keys"])}


@scenario("key_add", BACKFLIP)
def _key_add(s: LiveSession) -> Any:
    layer, _keys, frame = layer_with_gap(s)
    s.added_key = (layer, frame)
    return s.change("key_add", "animation.key_add", {"layer_id": layer, "frame": frame})


@scenario("key_delete", BACKFLIP)
def _key_delete(s: LiveSession) -> Any:
    if not getattr(s, "added_key", None):
        _key_add(s)
    layer, frame = s.added_key
    return s.change("key_delete", "animation.key_delete", {"layer_id": layer, "frame": frame})


@scenario("graph_query", BACKFLIP)
def _graph_query(s: LiveSession) -> Any:
    layer, _keys = animated_layer(s)
    rows = s.read("graph_query", "animation.graph_query", {"layer_ids": [layer], "last_frame": 40})
    return {"sections": rows["count"]}


@scenario("interpolation_set", BACKFLIP)
def _interpolation_set(s: LiveSession) -> Any:
    layer, _keys, gap = layer_with_gap(s)
    return s.change(
        "interpolation_set",
        "animation.interpolation_set",
        {"layer_id": layer, "frame": gap - 1, "value": "LINEAR", "operation": "interpolation"},
    )


@scenario("tangent_set", BACKFLIP)
def _tangent_set(s: LiveSession) -> Any:
    layer, _keys, gap = layer_with_gap(s)
    return s.change(
        "tangent_set",
        "animation.tangent_set",
        {"layer_id": layer, "frame": gap - 1, "value": "UserDefined", "operation": "tangent"},
    )


@scenario("graph_edit", BACKFLIP)
def _graph_edit(s: LiveSession) -> Any:
    layer, _keys, gap = layer_with_gap(s)
    return s.change(
        "graph_edit",
        "animation.section_edit",
        {"layer_id": layer, "frame": gap - 1, "interpolation": "STEP", "ik_fk": "FK"},
    )


@scenario("cycle_query", BACKFLIP)
def _cycle_query(s: LiveSession) -> Any:
    layer, _keys = animated_layer(s)
    return s.read("cycle_query", "animation.cycle_query", {"action": "list", "layer_ids": [layer]})


@scenario("cycle", BACKFLIP)
def _cycle(s: LiveSession) -> Any:
    # Like a cycle made in the Timeline: as many layers as share both bounding
    # keyframes (Backflip's layers do not all key the same frames).
    layers = [item for item in s.layers() if item["keys"]]
    best = None
    for layer in layers:
        keys = sorted(layer["keys"])
        for first, last in zip(keys, keys[2:], strict=False):
            sharing = [item["id"] for item in layers if first in item["keys"] and last in item["keys"]]
            if best is None or len(sharing) > len(best[2]):
                best = (first, last, sharing)
    if best is None:
        raise LiveValidationError("no layer has three keyframes")
    first, last, sharing = best
    return s.change("cycle", "timeline.cycle", {"layer_ids": sharing, "first_frame": first, "last_frame": last})


@scenario("bake", BACKFLIP)
def _bake(s: LiveSession) -> Any:
    layer, _keys = animated_layer(s)
    return s.change("bake", "timeline.bake", {"layer_ids": [layer], "first_frame": 30, "last_frame": 36})


@scenario("stretch", BACKFLIP)
def _stretch(s: LiveSession) -> Any:
    for layer in s.layers():
        keys = sorted(layer["keys"])
        # Walk from the end: the cycle scenario occupies the first keys.
        for first, last, following in reversed(list(zip(keys, keys[1:], keys[2:], strict=False))):
            if following - last >= 4:
                return s.change(
                    "stretch",
                    "timeline.stretch",
                    {"layer_ids": [layer["id"]], "first_frame": first, "last_frame": last, "new_last_frame": last + 2},
                )
    raise LiveValidationError("no layer has room to stretch")


@scenario("interval_edit", BACKFLIP)
def _interval_edit(s: LiveSession) -> Any:
    frames = s.read("timeline_get", "timeline.get")["frames_count"]
    return s.change(
        "interval_edit",
        "timeline.interval_edit",
        {"action": "add", "first_frame": frames - 4, "last_frame": frames - 3},
    )


@scenario("copy_animation", BACKFLIP)
def _copy_animation(s: LiveSession) -> Any:
    layer, _keys = animated_layer(s)
    return s.change(
        "copy_animation",
        "timeline.copy_interval",
        {"layer_ids": [layer], "first_frame": 0, "last_frame": 8, "target_frame": 60},
    )


@scenario("fulcrum", BACKFLIP)
def _fulcrum(s: LiveSession) -> Any:
    layer, _keys = animated_layer(s)
    return s.change("fulcrum", "timeline.fulcrum", {"layer_ids": [layer], "first_frame": 0, "last_frame": 12})


@scenario("fulcrum_cleaning", BACKFLIP)
def _fulcrum_cleaning(s: LiveSession) -> Any:
    layer, _keys = animated_layer(s)
    return s.change("fulcrum_cleaning", "timeline.fulcrum", {"layer_ids": [layer], "first_frame": 0, "last_frame": 12})


@scenario("interpolation_range", BACKFLIP)
def _interpolation_range(s: LiveSession) -> Any:
    layer, _keys = animated_layer(s)
    return s.change(
        "interpolation_range",
        "timeline.interpolation_range",
        {"layer_ids": [layer], "first_frame": 0, "last_frame": 12, "interpolation": "LINEAR"},
    )


@scenario("timeline_play", BACKFLIP)
def _timeline_play(s: LiveSession) -> Any:
    return s.change("timeline_play", "timeline.playback", {})


@scenario("timeline_stop", BACKFLIP)
def _timeline_stop(s: LiveSession) -> Any:
    return s.change("timeline_stop", "timeline.playback", {})


@scenario("key_reduction", BACKFLIP)
def _key_reduction(s: LiveSession) -> Any:
    layer, _keys = animated_layer(s, rank=1)
    return s.change(
        "key_reduction",
        "animation.key_reduce",
        {"first_frame": 0, "last_frame": 60, "layer_ids": [layer], "every_n": 2},
    )


def _select_interval(s: LiveSession, first: int, last: int) -> None:
    s.read("timeline_range", "timeline.range", {"first_frame": first, "last_frame": last})


@scenario("unbaking", BACKFLIP)
def _unbaking(s: LiveSession) -> Any:
    _select_interval(s, 0, 40)
    return s.change("unbaking", "generation.unbaking", {"step": "adjust_keys_and_interpolation"})


@scenario("root_motion", BACKFLIP)
def _root_motion(s: LiveSession) -> Any:
    _select_interval(s, 0, 40)
    return s.change("root_motion", "generation.root_motion", {})


@scenario("inbetweening", BACKFLIP)
def _inbetweening(s: LiveSession) -> Any:
    # Pro: generates motion between the selected keyframes (gaps of at most 120 frames).
    _select_interval(s, 0, 40)
    return s.change("inbetweening", "generation.inbetweening", {})


@scenario("auto_posing", BACKFLIP)
def _auto_posing(s: LiveSession) -> Any:
    # AutoPosing re-solves controllers that carry an AutoPosingLink, so move a
    # hand controller without one (a free input for the AutoPosing update).
    candidates = s.objects_of_type("Box") + s.objects_of_type("Point")
    behaviours = s.behaviour_names([item["id"] for item in candidates])
    free = sorted(
        (item for item in candidates if "AutoPosingLink" not in behaviours[item["id"]]),
        key=lambda item: (not any(part in item["name"] for part in ("hand", "arm")), item["name"]),
    )
    free = [item["id"] for item in free]
    if not free:
        raise LiveValidationError("every controller is driven by AutoPosing")
    box = free[0]
    current = s.read("transform_get", "animation.transform_get", {"ids": [box], "space": "global"})[0]["position"]
    s.change("selection_set", "selection.set", {"ids": [box]})
    moved = [current[0] + 0.2, current[1] + 0.2, current[2]]
    s.change("transform_set", "animation.transform_set", {"ids": [box], "position": moved, "space": "global"})
    return s.change("auto_posing", "generation.auto_posing", {"action": "update"})


@scenario("mirror", BACKFLIP)
def _mirror(s: LiveSession) -> Any:
    boxes = [item["id"] for item in s.objects_of_type("Box") if item["name"].endswith("_l")][:3]
    return s.change("mirror", "editing.mirror", {"ids": boxes, "mode": "frame", "frame": 10})


@scenario("tween", BACKFLIP)
def _tween(s: LiveSession) -> Any:
    _layer, _keys, frame = layer_with_gap(s)
    points = [item["id"] for item in s.objects_of_type("Point")][:6]
    return s.change("tween", "editing.tween", {"ids": points, "mode": "Average", "frame": frame})


@scenario("fixing", BACKFLIP)
def _fixing(s: LiveSession) -> Any:
    feet = [item["id"] for item in s.objects_of_type("Box") if "foot" in item["name"]]
    return s.change("fixing", "editing.fix_foot", {"ids": feet, "first_frame": 0, "last_frame": 40})


@scenario("collision_clean", BACKFLIP)
def _collision_clean(s: LiveSession) -> Any:
    return s.change("collision_clean", "physics.fix_collisions", {"first_frame": 0, "last_frame": 40})


@scenario("ballistic", BACKFLIP)
def _ballistic(s: LiveSession) -> Any:
    return s.change(
        "ballistic",
        "physics.ballistic",
        {"center_of_mass_id": center_of_mass(s), "first_frame": 20, "last_frame": 32},
    )


@scenario("auto_physics_enable", BACKFLIP)
def _auto_physics_enable(s: LiveSession) -> Any:
    return s.change("auto_physics_enable", "physics.auto_enable", {})


@scenario("auto_physics", BACKFLIP)
def _auto_physics(s: LiveSession) -> Any:
    return s.change("auto_physics", "physics.auto_snap", {}, timeout=300)


@scenario("blender_export", BACKFLIP)
def _blender_export(s: LiveSession) -> Any:
    s.use_fixture(BACKFLIP)  # FBX export rejects duplicate names (retargeting imports a second Cascy)
    return s.change("blender_export", "io.export_fbx", {"path": s.output("blender.fbx")}, timeout=360)
