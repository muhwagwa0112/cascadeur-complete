"""View-state toggles that Cascadeur only exposes as registered UI actions.

These actions change what Cascadeur draws (silhouette, grids, ghosts,
trajectories, panels) without touching scene data, so the bridge cannot observe
them. The bridge dispatches exactly one whitelisted 2026.1.2 action id and the
host verifies the rendered window changed (``viewport_render_changed``).
"""

from __future__ import annotations

from ..handler_registry import handler, transact

VIEW_ACTIONS = {
    "view.silhouette": "View.Silhouette mode",
    "view.isometric_grid": "View.Isometric Grid",
    "view.composition": "View.Composition",
    "view.trajectory": "TrajectoryTool.Switch trajectory activity",
    "view.trajectory_translate": "TrajectoryTool.Translate mode",
    "view.trajectory_rotate": "TrajectoryTool.Rotate mode",
    "view.trajectory_direction": "TrajectoryTool.Direction mode",
    "view.trajectory_edit": "TrajectoryTool.Trajectory edit mode",
    "view.ballistic_ghosts": "BallisticTrajectoryTool.Switch ballistic ghosts",
    "view.fingers_drawing": "AutoPosingTool.SwitchFingersDrawing",
    "physics.autophysics_freeze": "AutoPhysicsTool.Switch Frozen Auto Physics",
}
GHOST_ACTIONS = {
    "keyframe": "GhostTool.Keyframe ghosts",
    "neighbor": "GhostTool.Neighbor frame ghosts",
    "next": "GhostTool.Next frames ghosts",
    "previous": "GhostTool.Previous frames ghosts",
    "selected": "GhostTool.Ghosts for selected frames",
    "disable": "GhostTool.Disable ghost",
}
NODE_EDITOR_ACTIONS = {"on": "Window.Node editor turn on", "off": "Window.Node editor turn off"}


def _dispatch(context, action_id):
    result = context["csc"].app.get_application().get_action_manager().call_action(action_id)
    return {"action_id": action_id, "return_value": context["json_safe"](result)}


def _select(scene, arguments, context):
    ids = [str(item) for item in arguments.get("ids", [])]
    if not ids:
        return []
    domain = context["domain_scene"](scene)
    existing = {context["id_string"](item) for item in domain.model_viewer().get_objects()}
    unknown = sorted(set(ids) - existing)
    if unknown:
        raise KeyError("Unknown object IDs: " + ", ".join(unknown))
    converted = [context["object_id"](item) for item in ids]

    def apply(_model, _update, _scene, session):
        session.take_selector().select(set(converted), converted[0])

    transact(domain.modify_with_session, "Cascadeur Complete: select for view toggle", apply)
    return ids


@handler(*VIEW_ACTIONS)
def view_toggle(scene, arguments, request, context):
    operation = str((request.get("operations") or [{}])[0].get("name", ""))
    selected = _select(scene, arguments, context)
    return {**_dispatch(context, VIEW_ACTIONS[operation]), "selected_ids": selected}, []


@handler("view.ghost")
def ghost(scene, arguments, _request, context):
    mode = str(arguments.get("mode", "keyframe"))
    if mode not in GHOST_ACTIONS:
        raise ValueError("ghost mode must be one of: " + ", ".join(sorted(GHOST_ACTIONS)))
    selected = _select(scene, arguments, context)
    return {**_dispatch(context, GHOST_ACTIONS[mode]), "mode": mode, "selected_ids": selected}, []


@handler("view.node_editor")
def node_editor(_scene, arguments, _request, context):
    state = str(arguments.get("state", "on"))
    if state not in NODE_EDITOR_ACTIONS:
        raise ValueError("state must be on or off")
    return {**_dispatch(context, NODE_EDITOR_ACTIONS[state]), "state": state}, []


@handler("view.control_picker")
def control_picker(_scene, arguments, _request, context):
    state = str(arguments.get("state", "on"))
    if state not in ("on", "off"):
        raise ValueError("state must be on or off")
    view = context["scene_view"]()
    editor = context["csc"].app.get_application().get_tools_manager().get_tool("ControlPicker").editor(view)
    if state == "on":
        editor.activate()
    else:
        editor.deactivate()
    return {
        "state": state,
        "execution": "csc.tools.ControlPicker." + ("activate" if state == "on" else "deactivate"),
    }, []
