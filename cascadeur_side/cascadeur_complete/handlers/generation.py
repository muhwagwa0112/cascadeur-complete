from __future__ import annotations

from ..handler_registry import handler, transact


def _read(value, name, context):
    return context["read_member"](value, name)


def _generation_state(scene, context):
    domain = context["domain_scene"](scene)
    viewer = domain.layers_viewer()
    selector = domain.get_layers_selector()
    layer_ids = list(selector.all_included_layer_ids())
    selection = selector.selection()
    interval = selection.frames_interval()
    interval_valid = bool(_read(interval, "valid", context))
    first = int(_read(interval, "first", context)) if interval_valid else None
    last = int(_read(interval, "last", context)) if interval_valid else None
    selected_keys = set()
    per_layer_keys = {}
    per_layer_max_gaps = {}
    for layer_id in layer_ids:
        keys = sorted(int(frame) for frame in _read(viewer.layer(layer_id), "sections", context))
        if interval_valid:
            keys = [frame for frame in keys if first <= frame <= last]
        layer_text = context["id_string"](layer_id)
        per_layer_keys[layer_text] = keys
        per_layer_max_gaps[layer_text] = max(
            (right - left for left, right in zip(keys, keys[1:], strict=False)), default=0
        )
        selected_keys.update(keys)
    ordered_keys = sorted(selected_keys)
    max_key_gap = max(per_layer_max_gaps.values(), default=0)
    behaviours = domain.model_viewer().behaviour_viewer()
    rig_info_count = len(list(behaviours.get_behaviours("RigInfo")))
    missing = []
    if not layer_ids:
        missing.append("selected_character_layers")
    if not interval_valid or first == last:
        missing.append("selected_timeline_interval")
    if len(ordered_keys) < 2:
        missing.append("two_keyframes")
    if rig_info_count < 1:
        missing.append("standard_humanoid_rig")
    return {
        "selected_layer_ids": [context["id_string"](item) for item in layer_ids],
        "selected_layer_count": len(layer_ids),
        "interval": {"valid": interval_valid, "first": first, "last": last},
        "keyframes": ordered_keys,
        "keyframe_count": len(ordered_keys),
        "max_key_gap": max_key_gap,
        "per_layer_keys": per_layer_keys,
        "per_layer_max_key_gaps": per_layer_max_gaps,
        "rig_info_count": rig_info_count,
        "auto_posing_supported": rig_info_count > 0,
        "missing_preconditions": missing,
        "ready_for_root_motion": not missing,
        "ready_for_inbetweening": not missing and max_key_gap <= 120,
        "ready_for_unbaking": bool(layer_ids and interval_valid and first != last),
    }


@handler("generation.state", postconditions=("generation_precondition_report",))
def generation_state(scene, _arguments, _request, context):
    return _generation_state(scene, context), []


def _call_generation_action(scene, context, action_id, readiness_key, feature_name):
    state = _generation_state(scene, context)
    if not state[readiness_key]:
        detail = list(state["missing_preconditions"])
        if readiness_key == "ready_for_inbetweening" and state["max_key_gap"] > 120:
            detail.append("nearest_key_gap_at_most_120_frames")
        raise ValueError(feature_name + " prerequisites are missing: " + ", ".join(detail))
    before = context["scene_state"](context["scene_view"]() or scene)
    result = context["csc"].app.get_application().get_action_manager().call_action(action_id)
    after = context["scene_state"](context["scene_view"]() or scene)
    if before["revision"] == after["revision"]:
        raise AssertionError("POSTCONDITION_FAILED: " + feature_name + " made no observable scene change")
    return {
        "action_id": action_id,
        "return_value": context["json_safe"](result),
        "preconditions": state,
        "before_revision": before["revision"],
        "after_revision": after["revision"],
    }, []


@handler("generation.inbetweening", postconditions=("scene_revision_changed",))
def inbetweening(scene, _arguments, _request, context):
    return _call_generation_action(scene, context, "View.Inbetweening_Run", "ready_for_inbetweening", "Inbetweening")


@handler("generation.root_motion", postconditions=("scene_revision_changed",))
def root_motion(scene, _arguments, _request, context):
    return _call_generation_action(
        scene, context, "View.Inbetweening_RunRootMotion", "ready_for_root_motion", "Root Motion"
    )


@handler("generation.unbaking", postconditions=("scene_revision_changed",))
def unbaking(scene, arguments, _request, context):
    step = str(arguments.get("step", "adjust_keys_and_interpolation"))
    actions = {
        "prepare_keys_by_fulcrums": "View.AutoInterpolation_Keys",
        "adjust_keys_and_interpolation": "View.Animation unbaking",
        "adjust_autoposing_lock_state": "AutoPosingTool.AutoUnlock",
    }
    if step not in actions:
        raise ValueError("Unknown unbaking step: " + step)
    return _call_generation_action(scene, context, actions[step], "ready_for_unbaking", "Animation Unbaking")


@handler("generation.auto_posing", postconditions=("scene_revision_changed",))
def auto_posing(scene, arguments, _request, context):
    action = str(arguments.get("action", "update"))
    if action not in ("add", "update"):
        raise ValueError("AutoPosing action must be add or update")
    view_scene = context["scene_view"]()
    if view_scene is None:
        raise RuntimeError("No application scene is available")
    domain = context["domain_scene"](scene)
    before = context["scene_state"](view_scene)
    selected = list(before["selection"])
    if not selected:
        raise ValueError("AutoPosing requires selected character controllers")
    editor = context["csc"].app.get_application().get_tools_manager().get_tool("AutoPosingTool").editor(view_scene)
    if editor is None:
        raise RuntimeError("AutoPosing editor is unavailable for the current scene")

    def apply(_model, _update, _scene, session):
        getattr(editor, action)(session)

    transact(domain.modify_with_session, "Cascadeur Complete: AutoPosing " + action, apply)
    after = context["scene_state"](context["scene_view"]() or scene)
    if before["revision"] == after["revision"]:
        raise AssertionError("POSTCONDITION_FAILED: AutoPosing made no observable scene change")
    return {
        "action": action,
        "selection": selected,
        "before_revision": before["revision"],
        "after_revision": after["revision"],
    }, []


@handler("generation.retargeting", postconditions=("target_animation_changed",))
def retargeting(scene, arguments, _request, context):
    """Edit > Retargeting copy/paste: move an interval of animation between two AutoPosing rigs.

    Copy reads the selected frames of the character owning the selected point;
    paste applies them to the whole character owning the target point. The
    target character's layer must change on at least one copied frame.
    """
    from .timeline_edit import _call, _fingerprint, _select_interval, _select_objects

    domain = context["domain_scene"](scene)
    source = str(arguments["source_point_id"])
    target = str(arguments["target_point_id"])
    existing = {context["id_string"](item) for item in domain.model_viewer().get_objects()}
    unknown = sorted({source, target} - existing)
    if unknown:
        raise KeyError("Unknown object IDs: " + ", ".join(unknown))
    viewer = domain.model_viewer().behaviour_viewer()
    for raw_id in (source, target):
        if viewer.get_behaviour_by_name(context["object_id"](raw_id), "Point").is_null():
            raise ValueError("Retargeting needs a point controller of each character: " + raw_id)
    if not list(viewer.get_behaviours("RigInfo")):
        raise ValueError("Retargeting needs characters with a generated AutoPosing rig")
    layers = domain.layers_viewer()
    source_layer = layers.layer_id_by_obj_id(context["object_id"](source))
    target_layer = layers.layer_id_by_obj_id(context["object_id"](target))
    if source_layer.is_null() or target_layer.is_null():
        raise ValueError("Both points must belong to an animation layer")
    if context["id_string"](source_layer) == context["id_string"](target_layer):
        raise ValueError("Source and target points belong to the same character layer")
    first = int(arguments["first_frame"])
    last = int(arguments["last_frame"])
    if first < 0 or last < first or last >= int(layers.frames_count()):
        raise ValueError(f"Invalid retargeting interval: {first}..{last}")
    target_objects = sorted(context["id_string"](item) for item in layers.layer(target_layer).obj_ids)
    frames = range(first, last + 1)
    before = [_fingerprint(domain, target_objects, frame, context) for frame in frames]

    _select_interval(domain, [source_layer], first, last)
    _select_objects(domain, [source], context)
    _call(context, "View.Retargeting_Copy")
    _select_objects(domain, [target], context)
    _call(context, "View.Retargeting_Paste")

    after = [_fingerprint(domain, target_objects, frame, context) for frame in frames]
    changed = [frame for frame, old, new in zip(frames, before, after, strict=True) if old != new]
    if not changed:
        raise AssertionError("POSTCONDITION_FAILED: target character animation did not change")
    return {
        "source_point_id": source,
        "target_point_id": target,
        "interval": [first, last],
        "target_objects": len(target_objects),
        "changed_frames": len(changed),
    }, []


@handler("generation.auto_posing_state", postconditions=("auto_posing_state_dispatched",))
def auto_posing_state(scene, arguments, _request, context):
    """Activate or deactivate AutoPosing for explicit controllers.

    Controllers with an AutoPosingLink (e.g. Quick Rig fingers) are re-solved
    by AutoPosing after every change, which silently replaces keyed values
    written through the data editor. Deactivating them keeps such edits;
    activating hands them back to the solver. Cascadeur exposes no getter for
    the per-object state, so persistence of later edits is verified by the
    host's settled read-back instead.
    """
    state = str(arguments.get("state", ""))
    if state not in ("active", "inactive"):
        raise ValueError("state must be active or inactive")
    raw_ids = [str(item) for item in arguments.get("ids") or []]
    if not raw_ids:
        raise ValueError("ids must list the controllers to (de)activate")
    view_scene = context["scene_view"]()
    if view_scene is None:
        raise RuntimeError("No application scene is available")
    domain = context["domain_scene"](scene)
    object_ids = {context["object_id"](raw_id) for raw_id in raw_ids}
    editor = context["csc"].app.get_application().get_tools_manager().get_tool("AutoPosingTool").editor(view_scene)
    if editor is None:
        raise RuntimeError("AutoPosing editor is unavailable for the current scene")
    method = getattr(editor, "activate" if state == "active" else "deactivate")

    def apply(_model, _update, _scene, session):
        method(session, object_ids)

    transact(domain.modify_with_session, "Cascadeur Complete: AutoPosing " + state, apply)
    return {"state": state, "ids": sorted(raw_ids)}, []
