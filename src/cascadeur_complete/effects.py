"""Argument-aware effect policy shared by every host entry point."""
from __future__ import annotations

READ_ONLY_OPERATIONS = frozenset({
    "system.rebind_source", "system.verify_observation", "system.native_adapter_status",
    "system.observe_motion_inputs", "system.observe_key_layout", "system.observe_motion_capture", "system.observe_recipe_target",
    "system.status", "system.logs", "system.view_mode_get", "system.tools", "system.introspect",
    "scene.summary", "scene.objects", "scene.list", "scene.validate", "selection.get", "selection.filter",
    "object.hierarchy", "object.properties", "object.behaviors", "timeline.get", "timeline.range",
    "animation.transform_get", "animation.mesh_sample", "animation.key_list", "animation.graph_query",
    "animation.cycle_query", "layer.list", "render.viewport_state", "render.camera_catalog",
    "generation.state", "physics.state", "physics.auto_state", "rig.state", "rig.constraint_drivers",
    "system.capture_source", "system.validate_source",
})


def classify_effect(operation_name: str, normalized_arguments: dict | None = None) -> str:
    args = normalized_arguments or {}
    if operation_name == "animation.interpolation_refresh":
        return "evaluation"
    if operation_name == "animation.transform_get" and args.get("refresh", False):
        return "evaluation"
    if operation_name in {"system.view_mode", "system.view_mode_get"}:
        if args.get("mode") is not None:
            return "scene"
        if str(args.get("action", "get")) in {"get", "list"}:
            return "none"
        return "scene"
    if operation_name in READ_ONLY_OPERATIONS:
        return "none"
    if operation_name.startswith("io.export_") or operation_name == "scene.save":
        return "file"
    if operation_name.startswith("io.import_") or operation_name.startswith("safety."):
        return "mixed"
    return "scene"
