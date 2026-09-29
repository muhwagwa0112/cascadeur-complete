"""Timeline, keyframe-structure and editing adapters.

Every operation verifies its own result from the domain scene after the edit
(key sets, section fixation, cycles, object sets, transform fingerprints).
Actions that Cascadeur only exposes through its ActionManager are dispatched by
their exact 2026.1 identifiers and still verified through scene state.
"""

from __future__ import annotations

import hashlib
import json

from ..handler_registry import handler, transact


def _layers(domain, requested, context):
    viewer = domain.layers_viewer()
    layer_ids = [context["guid"](item) for item in requested] if requested else list(viewer.all_layer_ids())
    if not layer_ids:
        raise ValueError("At least one animation layer is required")
    unknown = [context["id_string"](item) for item in layer_ids if not viewer.has_item(item)]
    if unknown:
        raise KeyError("Unknown layer IDs: " + ", ".join(unknown))
    return layer_ids


def _interval(domain, arguments):
    frames = int(domain.layers_viewer().frames_count())
    first = int(arguments["first_frame"])
    last = int(arguments["last_frame"])
    if first < 0 or last < first or last >= frames:
        raise ValueError(f"Invalid frame interval {first}..{last} for {frames} frames")
    return first, last


def _keys(domain, layer_id, first=None, last=None):
    frames = sorted(int(item) for item in domain.layers_viewer().layer(layer_id).key_frame_indices())
    if first is None:
        return frames
    return [item for item in frames if first <= item <= last]


def _select_interval(domain, layer_ids, first, last):
    def apply(_model, _update, _scene, session):
        session.take_layers_selector().set_full_selection_by_parts(layer_ids, first, last)

    transact(domain.modify_with_session, "Cascadeur Complete: select interval", apply)


def _select_objects(domain, object_ids, context):
    converted = [context["object_id"](item) for item in object_ids]

    def select(_model, _update, _scene, session):
        session.take_selector().select(
            set(converted), converted[0] if converted else context["csc"].model.ObjectId.null()
        )

    transact(domain.modify_with_session, "Cascadeur Complete: select objects", select)
    return converted


def _set_frame(domain, frame):
    def apply(_model, _update, _scene, session):
        session.set_current_frame(frame)

    transact(domain.modify_with_session, "Cascadeur Complete: set frame", apply)


def _call(context, action_id):
    return context["csc"].app.get_application().get_action_manager().call_action(action_id)


def _existing(domain, context):
    return {context["id_string"](item) for item in domain.model_viewer().get_objects()}


def _fingerprint(domain, object_ids, frame, context):
    viewer = domain.model_viewer().behaviour_viewer()
    data = domain.data_viewer()
    rows = []
    for raw_id in sorted(object_ids):
        transform = viewer.get_behaviour_by_name(context["object_id"](raw_id), "Transform")
        if transform.is_null():
            continue
        row = [raw_id]
        for name in ("global_position", "global_rotation"):
            data_id = viewer.get_behaviour_data(transform, name)
            if data_id.is_null():
                row.append(None)
                continue
            value = data.get_data_value(data_id, frame)
            converter = getattr(value, "tolist", None)
            quaternion = getattr(value, "to_quaternion", None)
            if callable(converter):
                row.append([round(float(item), 5) for item in converter()])
            elif callable(quaternion):
                q = quaternion()
                row.append([round(float(getattr(q, axis)()), 5) for axis in ("w", "x", "y", "z")])
            else:
                row.append(repr(value)[:100])
        rows.append(row)
    return hashlib.sha256(json.dumps(rows).encode()).hexdigest()


def _assert_scene_saves(context, label):
    """Cascadeur checks its layer invariants when saving; a timeline edit that
    breaks them (e.g. "checkAnimatedSettings") only surfaces as "Saving scene
    failed!" in its log and a later crash. The save must rewrite the file and
    log no failure."""
    import os
    import time
    from pathlib import Path

    view = context["scene_view"]()
    path = Path(str(view.get_path_name()))
    before = path.stat().st_mtime_ns if path.is_file() else None
    log = Path(os.environ.get("LOCALAPPDATA", "")) / "Nekki Limited" / "Cascadeur" / "logs" / "cascadeur_log.log"
    log_offset = log.stat().st_size if log.is_file() else 0
    started = time.time()
    try:
        context["save_current_scene"](view)
    except RuntimeError as exc:
        raise AssertionError(f"POSTCONDITION_FAILED: Cascadeur cannot save the scene after {label}: {exc}") from exc
    failure = None
    if log.is_file():
        with log.open("rb") as stream:
            stream.seek(log_offset)
            tail = stream.read().decode("utf-8", errors="replace")
        failure = next((line for line in tail.splitlines() if "Saving scene failed" in line), None)
    rewritten = path.is_file() and path.stat().st_mtime_ns != before and path.stat().st_mtime >= started - 2.0
    if failure or not rewritten:
        raise AssertionError(
            f"POSTCONDITION_FAILED: Cascadeur cannot save the scene after {label} (layer invariants): "
            + (failure.split("] ", 1)[-1][:200] if failure else "the scene file was not rewritten")
        )


# -- cycles -------------------------------------------------------------------------


def _cycles(domain, layer_id, context):
    viewer = context["csc"].layers.CyclesViewer(domain.layers_viewer().layer(layer_id))
    frames = int(domain.layers_viewer().frames_count())
    return [
        (int(item.first_active_frame_index), int(item.last_active_frame_index))
        for item in viewer.get_cycles_in_frames(0, max(0, frames - 1))
    ]


CYCLE_ACTIONS = {
    "none": "Timeline.Create cycle",
    "position": "Timeline.Create cycle with position offset",
    "position_rotation": "Timeline.Create cycle with position and rotation offsets",
}


@handler("timeline.cycle", postconditions=("cycle_present", "cycle_absent"))
def cycle(scene, arguments, _request, context):
    domain = context["domain_scene"](scene)
    action = str(arguments.get("action", "create"))
    if action not in ("create", "delete"):
        raise ValueError("cycle action must be create or delete")
    layer_ids = _layers(domain, arguments.get("layer_ids", []), context)
    if action == "create":
        first, last = _interval(domain, arguments)
        if last - first < 1:
            raise ValueError("A cycle needs at least two frames")
        # Cascadeur's layer invariant rejects a cycle whose ends are not keys
        # ("checkCycles: no keys") when the scene is saved later.
        for layer_id in layer_ids:
            keys = set(_keys(domain, layer_id))
            if first not in keys or last not in keys:
                raise ValueError("first_frame and last_frame must be keyframes on every layer")
    else:
        frame = int(arguments["frame"])

    # The Timeline actions operate on the selected layers and interval, exactly
    # like the Cycles menu; the result is read back through CyclesViewer.
    if action == "create":
        offset = str(arguments.get("offset", "none"))
        if offset not in CYCLE_ACTIONS:
            raise ValueError("cycle offset must be one of " + ", ".join(CYCLE_ACTIONS))
        _select_interval(domain, layer_ids, first, last)
        _call(context, CYCLE_ACTIONS[offset])
    else:
        _select_interval(domain, layer_ids, frame, frame)
        _call(context, "Timeline.Remove cycles")
    observed = {context["id_string"](layer_id): _cycles(domain, layer_id, context) for layer_id in layer_ids}
    for layer_text, cycles in observed.items():
        if action == "create" and not any(start <= first and end >= last for start, end in cycles):
            raise AssertionError("POSTCONDITION_FAILED: cycle missing on layer " + layer_text)
        if action == "delete" and any(start <= frame <= end for start, end in cycles):
            raise AssertionError("POSTCONDITION_FAILED: cycle remains on layer " + layer_text)
    _assert_scene_saves(context, "cycle")
    return {
        "observed_postconditions": ["cycle_present"] if action == "create" else ["cycle_absent"],
        "action": action,
        "cycles": observed,
    }, []


# -- keys -----------------------------------------------------------------------------


@handler("timeline.bake", postconditions=("every_frame_is_key",))
def bake(scene, arguments, _request, context):
    domain = context["domain_scene"](scene)
    layer_ids = _layers(domain, arguments.get("layer_ids", []), context)
    first, last = _interval(domain, arguments)

    def edit(model, _update, _scene_updater):
        editor = model.layers_editor()
        for layer_id in layer_ids:
            for frame in range(first, last + 1):
                editor.set_fixed_interpolation_or_key_if_need(layer_id, frame, True)

    transact(domain.modify, "Cascadeur Complete: bake interval", edit)
    expected = list(range(first, last + 1))
    for layer_id in layer_ids:
        if _keys(domain, layer_id, first, last) != expected:
            raise AssertionError("POSTCONDITION_FAILED: baked interval is missing keys")
    _assert_scene_saves(context, "bake")
    return {
        "layer_ids": [context["id_string"](item) for item in layer_ids],
        "first_frame": first,
        "last_frame": last,
    }, []


def _fixation_rows(domain, layer_id, first, last, context):
    layer = domain.layers_viewer().layer(layer_id)
    rows = {}
    for frame in _keys(domain, layer_id, first, last):
        section = layer.section(frame)
        rows[frame] = str(context["read_member"](section.key.common.fixation, "name"))
    return rows


@handler("timeline.fulcrum", postconditions=("key_fixation_equals_request",))
def fulcrum(scene, arguments, _request, context):
    domain = context["domain_scene"](scene)
    layer_ids = _layers(domain, arguments.get("layer_ids", []), context)
    first, last = _interval(domain, arguments)
    state = str(arguments.get("state", "Fulcrum"))
    fixation_enum = context["csc"].layers.layer.Fixation
    if state not in ("Fulcrum", "Free"):
        raise ValueError("state must be Fulcrum or Free")
    target = getattr(fixation_enum, state)
    touched = {}
    for layer_id in layer_ids:
        touched[context["id_string"](layer_id)] = _keys(domain, layer_id, first, last)
    if not any(touched.values()):
        raise ValueError("No keyframes in the requested interval")

    def edit(model, _update, _scene_updater):
        editor = model.layers_editor()

        def mark(section):
            section.key.common.fixation = target
            section.interval.common.fixation = target

        for layer_id in layer_ids:
            for frame in touched[context["id_string"](layer_id)]:
                editor.change_section(frame, layer_id, mark)

    transact(domain.modify, "Cascadeur Complete: fulcrum " + state, edit)
    observed = {
        context["id_string"](layer_id): _fixation_rows(domain, layer_id, first, last, context) for layer_id in layer_ids
    }
    if any(value != state for rows in observed.values() for value in rows.values()):
        raise AssertionError("POSTCONDITION_FAILED: key fixation differs from " + state)
    return {"state": state, "keys": observed}, []


@handler("timeline.interval_edit", postconditions=("frame_count_changed_by_request",))
def interval_edit(scene, arguments, _request, context):
    """Insert or remove frames inside a selected interval (Timeline interval edit)."""
    domain = context["domain_scene"](scene)
    action = str(arguments.get("action", "add"))
    actions = {"add": "Timeline.Add frame(s)", "remove": "Timeline.Remove frames"}
    if action not in actions:
        raise ValueError("interval edit action must be add or remove")
    layer_ids = _layers(domain, arguments.get("layer_ids", []), context)
    first, last = _interval(domain, arguments)
    before = int(domain.layers_viewer().frames_count())
    before_keys = {context["id_string"](item): _keys(domain, item) for item in layer_ids}
    _select_interval(domain, layer_ids, first, last)
    _set_frame(domain, first)
    _call(context, actions[action])
    after = int(domain.layers_viewer().frames_count())
    after_keys = {context["id_string"](item): _keys(domain, item) for item in layer_ids}
    width = last - first + 1
    shifted = (after - before) == (width if action == "add" else -width)
    keys_moved = before_keys != after_keys
    if not shifted and not keys_moved:
        raise AssertionError("POSTCONDITION_FAILED: interval edit changed neither frames nor keys")
    _assert_scene_saves(context, "interval edit")
    return {
        "action": action,
        "action_id": actions[action],
        "before_frames": before,
        "after_frames": after,
        "before_keys": before_keys,
        "after_keys": after_keys,
    }, []


@handler("timeline.stretch", postconditions=("keys_retimed_to_request",))
def stretch(scene, arguments, _request, context):
    """Retime the keys of an interval to a new length, moving their key sections."""
    domain = context["domain_scene"](scene)
    layer_ids = _layers(domain, arguments.get("layer_ids", []), context)
    first, last = _interval(domain, arguments)
    new_last = int(arguments["new_last_frame"])
    frames = int(domain.layers_viewer().frames_count())
    if new_last <= first or new_last >= frames:
        raise ValueError("new_last_frame must lie after first_frame and inside the animation")
    for layer_id in layer_ids:
        if any(start <= max(last, new_last) and end >= first for start, end in _cycles(domain, layer_id, context)):
            raise ValueError("The stretched interval overlaps a cycle; remove the cycle first")
    scale = (new_last - first) / float(last - first)
    plans = {}
    for layer_id in layer_ids:
        keys = _keys(domain, layer_id, first, last)
        outside = [item for item in _keys(domain, layer_id) if last < item <= new_last]
        if outside:
            raise ValueError("Keys exist between last_frame and new_last_frame; they would be overwritten")
        mapping = {frame: first + int(round((frame - first) * scale)) for frame in keys}
        if len(set(mapping.values())) != len(mapping):
            raise ValueError("Stretch would merge keys; choose a longer interval")
        plans[layer_id] = mapping
    view = context["scene_view"]()

    def edit(model, update, scene_updater):
        editor = model.layers_editor()
        data_editor = model.data_editor()
        data_viewer = domain.data_viewer()
        layers_viewer = domain.layers_viewer()
        changed = set()
        for layer_id, mapping in plans.items():
            layer = layers_viewer.layer(layer_id)
            object_ids = set(layer.obj_ids)
            # Same as pycsc Layer.get_all_datas: every non-static datum of the layer's objects.
            animated = [
                data_id
                for object_id in object_ids
                for data_id in data_viewer.get_all_data_id(object_id)
                if data_viewer.get_data(data_id).mode != context["csc"].model.DataMode.Static
            ]
            values = {
                (data_id, frame): data_viewer.get_data_value(data_id, frame)
                for data_id in animated
                for frame in mapping
            }
            # Same order as pycsc Timeline.move_frames: write the target section,
            # then drop the source; walk away from the fixed first frame so a
            # target never overwrites a key that has not moved yet.
            for frame in sorted(mapping, reverse=scale > 1):
                target = mapping[frame]
                if target == frame:
                    continue
                section = layers_viewer.layer(layer_id).find_section(frame)
                if section is None:
                    raise ValueError(f"No section at key frame {frame}")
                editor.set_section(section, target, layer_id)
                editor.unset_section(frame, layer_id)
            for frame, target in mapping.items():
                for data_id in animated:
                    data_editor.set_data_value(data_id, target, values[(data_id, frame)])
                    changed.add(data_id)
        editor.normalize_sections(domain)  # shipped scripts pass the scene; the API doc omits it
        scene_updater.generate_update()
        scene_updater.run_update(changed, domain.get_current_frame(False))

    transact(domain.modify_update, "Cascadeur Complete: stretch interval", edit)
    observed = {}
    for layer_id, mapping in plans.items():
        keys = _keys(domain, layer_id, first, max(last, new_last))
        if keys != sorted(mapping.values()):
            raise AssertionError(
                f"POSTCONDITION_FAILED: retimed keys {keys} differ from plan {sorted(mapping.values())}"
            )
        observed[context["id_string"](layer_id)] = keys
    del view
    _assert_scene_saves(context, "stretch")
    return {"scale": scale, "keys": observed}, []


@handler("timeline.copy_interval", postconditions=("destination_keys_match_source",))
def copy_interval(scene, arguments, _request, context):
    """Copy an interval with Cascadeur's Copier and paste it at a target frame."""
    domain = context["domain_scene"](scene)
    layer_ids = _layers(domain, arguments.get("layer_ids", []), context)
    first, last = _interval(domain, arguments)
    target = int(arguments["target_frame"])
    frames = int(domain.layers_viewer().frames_count())
    if target + (last - first) >= frames or first <= target <= last:
        raise ValueError("target_frame must leave room for the interval and not overlap it")
    source = {
        context["id_string"](item): [frame - first for frame in _keys(domain, item, first, last)] for item in layer_ids
    }
    if not any(source.values()):
        raise ValueError("The source interval has no keyframes")
    _select_interval(domain, layer_ids, first, last)
    _call(context, "Copier.Copy interval")
    _set_frame(domain, target)
    _select_interval(domain, layer_ids, target, target + (last - first))
    _call(context, "Copier.Paste interval")
    observed = {
        context["id_string"](item): [frame - target for frame in _keys(domain, item, target, target + (last - first))]
        for item in layer_ids
    }
    for layer_text, offsets in source.items():
        if not set(offsets) <= set(observed[layer_text]):
            raise AssertionError("POSTCONDITION_FAILED: pasted interval misses source keys on " + layer_text)
    _assert_scene_saves(context, "interval copy")
    return {"source_offsets": source, "destination_offsets": observed, "target_frame": target}, []


@handler("timeline.playback", postconditions=("playback_action_dispatched",))
def playback(scene, arguments, _request, context):
    """Toggle playback; the host verifies frame motion after the UI event loop runs."""
    domain = context["domain_scene"](scene)
    before = int(domain.get_current_frame(False))
    _call(context, "Timeline.Play")
    return {"action_id": "Timeline.Play", "frame_before": before, "requested": arguments.get("state", "toggle")}, []


# -- objects and poses ----------------------------------------------------------------


@handler("objects.delete", postconditions=("objects_absent",))
def delete_objects(scene, arguments, _request, context):
    import common.delete_objects as deleter

    domain = context["domain_scene"](scene)
    ids = [str(item) for item in arguments.get("ids", [])]
    if not ids:
        raise ValueError("ids must contain at least one object")
    unknown = sorted(set(ids) - _existing(domain, context))
    if unknown:
        raise KeyError("Unknown object IDs: " + ", ".join(unknown))
    deleter.delete_model_objects(domain, {context["object_id"](item) for item in ids})
    remaining = sorted(set(ids) & _existing(domain, context))
    if remaining:
        raise AssertionError("POSTCONDITION_FAILED: objects remain: " + ", ".join(remaining))
    return {"deleted_ids": sorted(ids), "execution": "common.delete_objects.delete_model_objects"}, []


@handler("objects.duplicate", postconditions=("one_duplicate_created",))
def duplicate_object(scene, arguments, _request, context):
    from commands.copy_paste_objects import duplicate

    domain = context["domain_scene"](scene)
    source = str(arguments.get("id", ""))
    if source not in _existing(domain, context):
        raise KeyError("Unknown object ID: " + source)
    before = _existing(domain, context)
    _select_objects(domain, [source], context)
    duplicate.run(domain)
    created = sorted(_existing(domain, context) - before)
    if not created:
        raise AssertionError("POSTCONDITION_FAILED: duplicate created no object")
    viewer = domain.model_viewer()
    source_type = str(viewer.get_object_type_name(context["object_id"](source)))
    types = {item: str(viewer.get_object_type_name(context["object_id"](item))) for item in created}
    if source_type not in types.values():
        raise AssertionError("POSTCONDITION_FAILED: no created object matches the source type")
    return {"source_id": source, "created_ids": created, "types": types}, []


@handler("editing.tween", postconditions=("target_transform_fingerprint_changed",))
def tween(scene, arguments, _request, context):
    csc = context["csc"]
    domain = context["domain_scene"](scene)
    view = context["scene_view"]()
    mode_name = str(arguments.get("mode", "Average"))
    modes = {"Previous", "Next", "Inertial", "InverseInertial", "Average"}
    if mode_name not in modes:
        raise ValueError("mode must be one of: " + ", ".join(sorted(modes)))
    ids = [str(item) for item in arguments.get("ids", [])]
    if not ids:
        raise ValueError("ids must list the objects to attract")
    unknown = sorted(set(ids) - _existing(domain, context))
    if unknown:
        raise KeyError("Unknown object IDs: " + ", ".join(unknown))
    frame = int(arguments.get("frame", domain.get_current_frame(False)))
    factor = float(arguments.get("factor", 1.0))
    if not 0.0 < factor <= 1.0:
        raise ValueError("factor must be in (0, 1]")
    _set_frame(domain, frame)
    _select_objects(domain, ids, context)
    before = _fingerprint(domain, ids, frame, context)
    tool = csc.app.get_application().get_tools_manager().get_tool("AttractorTool").editor(view)
    settings = tool.get_general_settings()
    settings.factor = factor
    args = csc.tools.attractor.Args(
        domain,
        view.gravity_per_frame(),
        settings,
        tool.is_only_key_frames(),
        getattr(csc.tools.attractor.ArgsMode, mode_name),
    )
    csc.tools.attractor.attract(args)
    after = _fingerprint(domain, ids, frame, context)
    if after == before:
        raise AssertionError("POSTCONDITION_FAILED: tween produced no transform change")
    return {"mode": mode_name, "frame": frame, "factor": factor, "before": before, "after": after}, []


def _revision_action(scene, arguments, context, action_id, label):
    domain = context["domain_scene"](scene)
    ids = [str(item) for item in arguments.get("ids", [])]
    if ids:
        unknown = sorted(set(ids) - _existing(domain, context))
        if unknown:
            raise KeyError("Unknown object IDs: " + ", ".join(unknown))
        _select_objects(domain, ids, context)
    if arguments.get("first_frame") is not None:
        layer_ids = _layers(domain, arguments.get("layer_ids", []), context)
        first, last = _interval(domain, arguments)
        _select_interval(domain, layer_ids, first, last)
    before = context["scene_state"](context["scene_view"]() or scene)["revision"]
    result = _call(context, action_id)
    after = context["scene_state"](context["scene_view"]() or scene)["revision"]
    if before == after:
        raise AssertionError("POSTCONDITION_FAILED: " + label + " made no observable scene change")
    return {
        "action_id": action_id,
        "before_revision": before,
        "after_revision": after,
        "return_value": context["json_safe"](result),
    }, []


@handler("editing.fix_foot", postconditions=("scene_revision_changed",))
def fix_foot(scene, arguments, _request, context):
    return _revision_action(scene, arguments, context, "View.FixFoot", "Fix foot")


@handler("physics.fix_collisions", postconditions=("scene_revision_changed",))
def fix_collisions(scene, arguments, _request, context):
    return _revision_action(scene, arguments, context, "View.FixCollisions", "Fix collisions")


@handler("render.viewport_layout", postconditions=("viewport_count_equals_request",))
def viewport_layout(_scene, arguments, _request, context):
    view = context["scene_view"]()
    count = int(arguments.get("count", 1))
    actions = {1: "Viewport.One Viewport", 2: "Viewport.Two Viewports", 4: "Viewport.Four Viewports"}
    if count not in actions:
        raise ValueError("count must be 1, 2 or 4")
    _call(context, actions[count])
    observed = len(list(view.viewports()))
    if observed != count:
        raise AssertionError(f"POSTCONDITION_FAILED: viewport count is {observed}, expected {count}")
    return {"action_id": actions[count], "viewports": observed}, []


@handler("layer.activate", postconditions=("active_layer_equals_request",))
def activate_layer(scene, arguments, _request, context):
    domain = context["domain_scene"](scene)
    layer_id = _layers(domain, [arguments["layer_id"]], context)[0]
    frame = int(domain.get_current_frame(False))
    # Activating a layer selects its whole track (a one-frame part is rejected).
    last = max(0, int(domain.layers_viewer().frames_count()) - 1)

    accepted = []

    def apply(_model, _update, _scene, session):
        # The session changer is the one pycsc uses; it reports acceptance.
        accepted.append(session.take_layers_selector().set_full_selection_by_parts([layer_id], 0, last))

    transact(domain.modify_with_session, "Cascadeur Complete: activate layer", apply)
    if accepted and accepted[0] is False:
        raise ValueError("Cascadeur rejected the layer selection")
    selector = domain.get_layers_selector()
    # all_included_layer_ids() lists the layers enabled for editing, not the
    # timeline selection; the selection container holds the selected items.
    selected = sorted(context["id_string"](item) for item in selector.selection().item_ids())
    requested = context["id_string"](layer_id)
    if selected != [requested]:
        raise AssertionError(
            f"POSTCONDITION_FAILED: selected items {selected[:3]} (of {len(selected)}) after selecting {requested}"
        )
    return {"layer_id": requested, "frame": frame, "top_layer_id": context["id_string"](selector.top_layer_id())}, []


SECTION_FIELDS = {
    "interpolation": ("interval", "interpolation", "Interpolation"),
    "tangents": ("key", "tangents", "Tangents"),
    "ik_fk": ("key.common", "ik_fk", "IkFk"),
    "fixation": ("key.common", "fixation", "Fixation"),
}


def _section_part(section, path):
    for name in path.split("."):
        section = getattr(section, name)
    return section


@handler("animation.section_edit", postconditions=("section_equals_request",))
def section_edit(scene, arguments, _request, context):
    """Edit several properties of one key section in a single graph-editor style change."""
    domain = context["domain_scene"](scene)
    layer_id = _layers(domain, [arguments["layer_id"]], context)[0]
    frame = int(arguments["frame"])
    if frame not in _keys(domain, layer_id):
        raise ValueError("frame must be a keyframe of the layer")
    enums = context["csc"].layers.layer
    requested = {}
    for name, (_path, _attribute, enum_name) in SECTION_FIELDS.items():
        if arguments.get(name) is None:
            continue
        enum_class = getattr(enums, enum_name)
        value = str(arguments[name])
        member = next((item for item in dir(enum_class) if item.casefold() == value.casefold()), None)
        if member is None or member.startswith("_"):
            raise ValueError(f"Unknown {name} value: {value}")
        requested[name] = (member, getattr(enum_class, member))
    if not requested:
        raise ValueError("At least one of interpolation, tangents, ik_fk or fixation is required")

    def edit(model, _update, _scene_updater):
        def modify(section):
            for name, (_member, value) in requested.items():
                path, attribute, _enum = SECTION_FIELDS[name]
                setattr(_section_part(section, path), attribute, value)

        model.layers_editor().change_section(frame, layer_id, modify)

    transact(domain.modify, "Cascadeur Complete: edit key section", edit)
    section = domain.layers_viewer().layer(layer_id).section(frame)
    observed = {}
    for name, (member, _value) in requested.items():
        path, attribute, _enum = SECTION_FIELDS[name]
        observed[name] = str(context["read_member"](getattr(_section_part(section, path), attribute), "name"))
        if observed[name] != member:
            raise AssertionError("POSTCONDITION_FAILED: section " + name + " differs from request")
    return {"layer_id": context["id_string"](layer_id), "frame": frame, "section": observed}, []
