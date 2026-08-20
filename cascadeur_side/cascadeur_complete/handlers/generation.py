from __future__ import annotations

from ..handler_registry import handler


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


@handler("generation.state")
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


@handler("generation.inbetweening")
def inbetweening(scene, _arguments, _request, context):
    return _call_generation_action(scene, context, "View.Inbetweening_Run", "ready_for_inbetweening", "Inbetweening")


@handler("generation.root_motion")
def root_motion(scene, _arguments, _request, context):
    return _call_generation_action(
        scene, context, "View.Inbetweening_RunRootMotion", "ready_for_root_motion", "Root Motion"
    )


@handler("generation.unbaking")
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


@handler("generation.auto_posing")
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

    domain.modify_with_session("Cascadeur Complete: AutoPosing " + action, apply)
    after = context["scene_state"](context["scene_view"]() or scene)
    if before["revision"] == after["revision"]:
        raise AssertionError("POSTCONDITION_FAILED: AutoPosing made no observable scene change")
    return {
        "action": action,
        "selection": selected,
        "before_revision": before["revision"],
        "after_revision": after["revision"],
    }, []
