"""Live scenarios for file adapters, registered file dialogs and view toggles."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .live_scenarios import BACKFLIP, CASCY, CUBE
from .live_scenarios_scene import center_of_mass
from .live_validation import LiveSession, LiveValidationError, scenario
from .service import dialog_flow_arguments

# -- files (Cube) ---------------------------------------------------------------------


def _render_png(s: LiveSession) -> str:
    image = getattr(s, "extra_png", None)
    if image and Path(image).is_file():
        return image
    s.extra_png = s.output("reference.png")
    s.change("render_image", "render.image", {"path": s.extra_png, "width": 256, "height": 256, "samples": 4})
    return s.extra_png


def _dialog(s: LiveSession, feature_id: str, path: str) -> Any:
    return s.change(feature_id, "system.ui_file_flow", dialog_flow_arguments(feature_id, path), timeout=240)


@scenario("render_video", CUBE)
def _render_video(s: LiveSession) -> Any:
    result = s.change(
        "render_video", "render.video", {"path": s.output("video.mp4"), "width": 320, "height": 240, "samples": 2}
    )
    s.extra_video = result["path"]
    return result


@scenario("export_video", CUBE)
def _export_video(s: LiveSession) -> Any:
    return s.change(
        "export_video", "render.video", {"path": s.output("export.mp4"), "width": 320, "height": 240, "samples": 2}
    )


@scenario("save_as_without_assets", CUBE)
def _save_as_without_assets(s: LiveSession) -> Any:
    result = _dialog(s, "save_as_without_assets", s.output("no-assets.casc"))
    s.extra_casc = result["path"]
    return result


@scenario("import_scene_to_current", CUBE)
def _import_scene_to_current(s: LiveSession) -> Any:
    source = getattr(s, "extra_casc", None)
    if not source:
        source = s.change("scene_save_as", "scene.save_as", {"path": s.output("merge-source.casc")})["path"]
    return _dialog(s, "import_scene_to_current", source)


@scenario("scene_parts_export", CUBE)
def _scene_parts_export(s: LiveSession) -> Any:
    s.change("selection_set", "selection.set", {"ids": [s.object_named("joint1_Box")]})
    result = _dialog(s, "scene_parts_export", s.output("parts.partscasc"))
    s.extra_parts = result["path"]
    return result


@scenario("scene_parts_import", CUBE)
def _scene_parts_import(s: LiveSession) -> Any:
    source = getattr(s, "extra_parts", None) or _scene_parts_export(s)["path"]
    return s.change("scene_parts_import", "io.scene_parts_import", {"path": source})


@scenario("import_image", CUBE)
def _import_image(s: LiveSession) -> Any:
    return _dialog(s, "import_image", _render_png(s))


@scenario("camera_textures", CUBE)
def _camera_textures(s: LiveSession) -> Any:
    s.change("camera_create", "render.camera_create", {})
    return _dialog(s, "camera_textures", _render_png(s))


@scenario("import_video", CUBE)
def _import_video(s: LiveSession) -> Any:
    video = getattr(s, "extra_video", None) or _render_video(s)["path"]
    return _dialog(s, "import_video", video)


@scenario("save_as_new_version", CUBE)
def _save_as_new_version(s: LiveSession) -> Any:
    return s.change("save_as_new_version", "scene.save_new_version", {})


@scenario("open_autosave", CUBE)
def _open_autosave(s: LiveSession) -> Any:
    return s.change("open_autosave", "scene.open_autosave", {}, timeout=240)


# -- selection groups (Cascy ships with selection groups for its picker) -------------


@scenario("selection_groups_export", CASCY)
def _selection_groups_export(s: LiveSession) -> Any:
    result = _dialog(s, "selection_groups_export", s.output("groups.json"))
    s.extra_groups = result["path"]
    return result


@scenario("selection_groups_import", CASCY)
def _selection_groups_import(s: LiveSession) -> Any:
    source = getattr(s, "extra_groups", None) or _selection_groups_export(s)["path"]
    return s.change("selection_groups_import", "io.selection_groups_import", {"path": source})


# -- view toggles (Backflip: animated, rigged, has a ballistic trajectory) ------------


def _points(s: LiveSession, count: int = 4) -> list[str]:
    points = [item["id"] for item in s.objects_of_type("Point") if "MainPoint" in item["name"]]
    if not points:
        raise LiveValidationError("fixture has no main points")
    return points[:count]


def _toggle(s: LiveSession, feature_id: str, operation: str, arguments: dict[str, Any] | None = None) -> Any:
    first = s.change(feature_id, operation, dict(arguments or {}))
    second = s.change(feature_id, operation, dict(arguments or {}))
    return {"on": first, "off": second}


@scenario("silhouette", BACKFLIP)
def _silhouette(s: LiveSession) -> Any:
    return _toggle(s, "silhouette", "view.silhouette")


@scenario("grid", BACKFLIP)
def _grid(s: LiveSession) -> Any:
    return _toggle(s, "grid", "view.isometric_grid")


@scenario("composition", BACKFLIP)
def _composition(s: LiveSession) -> Any:
    return _toggle(s, "composition", "view.composition")


@scenario("trajectory", BACKFLIP)
def _trajectory(s: LiveSession) -> Any:
    return s.change("trajectory", "view.trajectory", {"ids": _points(s)})


@scenario("trajectory_translation", BACKFLIP)
def _trajectory_translation(s: LiveSession) -> Any:
    return s.change("trajectory_translation", "view.trajectory_translate", {"ids": _points(s)})


@scenario("trajectory_rotation", BACKFLIP)
def _trajectory_rotation(s: LiveSession) -> Any:
    return s.change("trajectory_rotation", "view.trajectory_rotate", {"ids": _points(s)})


@scenario("trajectory_direction", BACKFLIP)
def _trajectory_direction(s: LiveSession) -> Any:
    return s.change("trajectory_direction", "view.trajectory_direction", {"ids": _points(s)})


@scenario("trajectory_tangents", BACKFLIP)
def _trajectory_tangents(s: LiveSession) -> Any:
    return _toggle(s, "trajectory_tangents", "view.trajectory_edit", {"ids": _points(s)})


@scenario("ghost", BACKFLIP)
def _ghost(s: LiveSession) -> Any:
    on = s.change("ghost", "view.ghost", {"mode": "neighbor", "ids": _points(s, 8)})
    off = s.change("ghost", "view.ghost", {"mode": "disable"})
    return {"on": on, "off": off}


@scenario("ballistic_ghosts", BACKFLIP)
def _ballistic_ghosts(s: LiveSession) -> Any:
    return _toggle(s, "ballistic_ghosts", "view.ballistic_ghosts", {"ids": [center_of_mass(s)]})


@scenario("finger_auto_posing", BACKFLIP)
def _finger_auto_posing(s: LiveSession) -> Any:
    hands = [item["id"] for item in s.objects_of_type("Box") if "hand" in item["name"]]
    return _toggle(s, "finger_auto_posing", "view.fingers_drawing", {"ids": hands})


@scenario("autophysics_freeze", BACKFLIP)
def _autophysics_freeze(s: LiveSession) -> Any:
    return _toggle(s, "autophysics_freeze", "physics.autophysics_freeze")


@scenario("node_editor", BACKFLIP)
def _node_editor(s: LiveSession) -> Any:
    on = s.change("node_editor", "view.node_editor", {"state": "on"})
    off = s.change("node_editor", "view.node_editor", {"state": "off"})
    return {"on": on, "off": off}


@scenario("control_picker", BACKFLIP)
def _control_picker(s: LiveSession) -> Any:
    on = s.change("control_picker", "view.control_picker", {"state": "on"})
    off = s.change("control_picker", "view.control_picker", {"state": "off"})
    return {"on": on, "off": off}
