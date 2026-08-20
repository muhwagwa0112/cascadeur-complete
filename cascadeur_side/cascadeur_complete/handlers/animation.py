from __future__ import annotations

from ..handler_registry import handler


def _enum_name(value, context):
    return str(context["read_member"](value, "name"))


def _section_row(layer_id, frame, section, context):
    interval = context["read_member"](section, "interval")
    key = context["read_member"](section, "key")
    interval_common = context["read_member"](interval, "common")
    key_common = context["read_member"](key, "common")
    return {
        "layer_id": context["id_string"](layer_id),
        "frame": int(frame),
        "interpolation": _enum_name(context["read_member"](interval, "interpolation"), context),
        "tangents": _enum_name(context["read_member"](key, "tangents"), context),
        "interval": {
            "ik_fk": _enum_name(context["read_member"](interval_common, "ik_fk"), context),
            "fixation": _enum_name(context["read_member"](interval_common, "fixation"), context),
        },
        "key": {
            "ik_fk": _enum_name(context["read_member"](key_common, "ik_fk"), context),
            "fixation": _enum_name(context["read_member"](key_common, "fixation"), context),
            "label": context["json_safe"](context["read_member"](key, "label")),
        },
    }


def _sections(domain, arguments, context):
    viewer = domain.layers_viewer()
    requested = [str(item) for item in arguments.get("layer_ids", [])]
    layer_ids = [context["guid"](item) for item in requested] if requested else list(viewer.all_layer_ids())
    first = arguments.get("first_frame")
    last = arguments.get("last_frame")
    rows = []
    for layer_id in layer_ids:
        if not viewer.has_item(layer_id):
            raise KeyError("Unknown layer ID: " + context["id_string"](layer_id))
        layer = viewer.layer(layer_id)
        sections = context["read_member"](layer, "sections")
        for frame, section in sections.items():
            if first is not None and int(frame) < int(first):
                continue
            if last is not None and int(frame) > int(last):
                continue
            rows.append(_section_row(layer_id, frame, section, context))
    return sorted(rows, key=lambda item: (item["layer_id"], item["frame"]))


def _cycle_row(cycle):
    return {
        "first_active_frame": int(cycle.first_active_frame_index),
        "last_active_frame": int(cycle.last_active_frame_index),
        "left_inactive_frame": int(cycle.left_inactive_frame_index),
        "right_inactive_frame": int(cycle.right_inactive_frame_index),
        "following_interval": int(cycle.following_interval),
        "left_frame": int(cycle.left_frame_index()),
        "right_frame": int(cycle.right_frame_index()),
    }


def _cycles(domain, layer_ids, first, last, context):
    viewer = domain.layers_viewer()
    rows = []
    for layer_id in layer_ids:
        cycles_viewer = context["csc"].layers.CyclesViewer(viewer.layer(layer_id))
        seen = set()
        for cycle in cycles_viewer.get_cycles_in_frames(first, last):
            row = _cycle_row(cycle)
            identity = tuple(row.values())
            if identity in seen:
                continue
            seen.add(identity)
            rows.append({"layer_id": context["id_string"](layer_id), **row})
    return sorted(rows, key=lambda item: (item["layer_id"], item["left_frame"], item["right_frame"]))


def _cycle_layers(domain, requested, context):
    viewer = domain.layers_viewer()
    layer_ids = [context["guid"](item) for item in requested] if requested else list(viewer.all_layer_ids())
    if not layer_ids:
        raise ValueError("Cycle operation requires at least one animation layer")
    unknown = [context["id_string"](item) for item in layer_ids if not viewer.has_item(item)]
    if unknown:
        raise KeyError("Unknown layer IDs: " + ", ".join(unknown))
    return layer_ids


@handler("animation.cycle_query")
def cycle_query(scene, arguments, _request, context):
    domain = context["domain_scene"](scene)
    viewer = domain.layers_viewer()
    frames_count = int(viewer.frames_count())
    action = str(arguments.get("action", "list"))
    if action != "list":
        raise ValueError("animation.cycle_query only supports list")
    layer_ids = _cycle_layers(domain, arguments.get("layer_ids", []), context)
    first = int(arguments.get("first_frame", 0))
    last = int(arguments.get("last_frame", frames_count - 1))
    if first < 0 or last < first or last >= frames_count:
        raise ValueError(f"Invalid cycle query interval: {first}..{last}")
    rows = _cycles(domain, layer_ids, first, last, context)
    return {"cycles": rows, "count": len(rows), "first_frame": first, "last_frame": last}, []


@handler("animation.graph_query")
def graph_query(scene, arguments, _request, context):
    domain = context["domain_scene"](scene)
    rows = _sections(domain, arguments, context)
    return {"sections": rows, "count": len(rows)}, []


@handler("animation.interpolation_set", "animation.tangent_set")
def edit_section(scene, arguments, _request, context):
    domain = context["domain_scene"](scene)
    layer_id = context["guid"](arguments["layer_id"])
    frame = int(arguments["frame"])
    operation = str(arguments["operation"])
    requested = str(arguments["value"])
    if operation == "interpolation":
        enum_class = context["csc"].layers.layer.Interpolation
        attribute = "interpolation"
    elif operation == "tangent":
        enum_class = context["csc"].layers.layer.Tangents
        attribute = "tangents"
    else:
        raise ValueError("Unsupported section operation: " + operation)
    try:
        enum_name = next(name for name in dir(enum_class) if name.casefold() == requested.casefold())
        enum_value = getattr(enum_class, enum_name)
    except (AttributeError, StopIteration) as exc:
        allowed = [name for name in dir(enum_class) if not name.startswith("_") and name[:1].isupper()]
        raise ValueError("Unsupported value. Expected one of: " + ", ".join(allowed)) from exc

    def edit(model, _update, _scene_updater):
        def modify(section):
            target = section.interval if operation == "interpolation" else section.key
            setattr(target, attribute, enum_value)

        model.layers_editor().change_section(frame, layer_id, modify)

    domain.modify("Cascadeur Complete: set " + operation, edit)
    rows = _sections(domain, {"layer_ids": [str(arguments["layer_id"])]}, context)
    observed = next((item for item in rows if item["frame"] == frame), None)
    expected = _enum_name(enum_value, context)
    actual = observed["interpolation" if operation == "interpolation" else "tangents"] if observed else None
    if actual != expected:
        raise AssertionError("POSTCONDITION_FAILED: section value differs")
    return observed, []


@handler("animation.key_reduce")
def key_reduce(scene, arguments, _request, context):
    domain = context["domain_scene"](scene)
    viewer = domain.layers_viewer()
    every_n = int(arguments.get("every_n", 2))
    if every_n <= 0:
        raise ValueError("every_n must be a positive integer")
    first = int(arguments["first_frame"])
    last = int(arguments["last_frame"])
    if first < 0 or last < first or last >= int(viewer.frames_count()):
        raise ValueError(f"Invalid key reduction interval: {first}..{last}")
    requested = [str(item) for item in arguments.get("layer_ids", [])]
    layer_ids = [context["guid"](item) for item in requested] if requested else list(viewer.all_layer_ids())
    if not layer_ids:
        raise ValueError("Key reduction requires at least one animation layer")
    unknown = [context["id_string"](item) for item in layer_ids if not viewer.has_item(item)]
    if unknown:
        raise KeyError("Unknown layer IDs: " + ", ".join(unknown))
    preserve_endpoints = bool(arguments.get("preserve_endpoints", True))
    fixed_interpolation = bool(arguments.get("fixed_interpolation", False))
    before = {}
    expected = {}
    for layer_id in layer_ids:
        key_frames = [
            int(frame)
            for frame in viewer.layer(layer_id).key_frame_indices()
            if first <= int(frame) <= last
        ]
        layer_text = context["id_string"](layer_id)
        before[layer_text] = key_frames
        preserved = set(key_frames[::every_n])
        if preserve_endpoints and key_frames:
            preserved.update((key_frames[0], key_frames[-1]))
        expected[layer_text] = sorted(preserved)

    def reduce(model, _update, _scene_updater):
        editor = model.layers_editor()

        def set_fixed(section):
            section.interval.interpolation = context["csc"].layers.layer.Interpolation.FIXED

        for layer_id in layer_ids:
            layer_text = context["id_string"](layer_id)
            preserved = set(expected[layer_text])
            layer_keys = before[layer_text]
            for frame in layer_keys:
                if frame not in preserved:
                    editor.unset_section(frame, layer_id)
                elif fixed_interpolation and frame != layer_keys[-1]:
                    editor.change_section(frame, layer_id, set_fixed)

    domain.modify("Cascadeur Complete: reduce keyframes", reduce)
    observed = {}
    for layer_id in layer_ids:
        layer_text = context["id_string"](layer_id)
        observed[layer_text] = sorted(
            int(frame)
            for frame in domain.layers_viewer().layer(layer_id).key_frame_indices()
            if first <= int(frame) <= last
        )
        if observed[layer_text] != expected[layer_text]:
            raise AssertionError("POSTCONDITION_FAILED: reduced key set differs for layer " + layer_text)
    removed = {
        layer_id: sorted(set(before[layer_id]) - set(observed[layer_id])) for layer_id in observed
    }
    return {
        "first_frame": first,
        "last_frame": last,
        "every_n": every_n,
        "preserve_endpoints": preserve_endpoints,
        "fixed_interpolation": fixed_interpolation,
        "before_keys": before,
        "after_keys": observed,
        "removed_keys": removed,
        "removed_count": sum(len(items) for items in removed.values()),
        "execution": "commands.animation_scripts.keyframe_reduction verified direct implementation",
    }, []
