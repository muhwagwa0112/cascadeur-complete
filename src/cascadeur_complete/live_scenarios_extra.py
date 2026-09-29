"""Live scenarios for file adapters, registered file dialogs and view toggles."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .live_scenarios import BACKFLIP, CASCY, CUBE
from .live_scenarios_scene import center_of_mass
from .live_validation import FIXTURES, LiveSession, LiveValidationError, scenario
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
    return _dialog(s, "scene_parts_import", source)


@scenario("import_image", CUBE)
def _import_image(s: LiveSession) -> Any:
    return _dialog(s, "import_image", _render_png(s))


@scenario("camera_textures", CUBE)
def _camera_textures(s: LiveSession) -> Any:
    created = s.change("camera_create", "render.camera_create", {})["created_ids"]
    cameras = [
        item for item in created if item in s.owners("Camera", [row for row in s.objects() if row["id"] in created])
    ]
    return s.change(
        "camera_textures",
        "render.camera_texture",
        {"camera_id": cameras[0], "paths": [_render_png(s)], "start_frame": 0},
    )


@scenario("import_video", CUBE)
def _import_video(s: LiveSession) -> Any:
    video = s.service.paths.root / "live-fixtures" / "reference.mp4"
    if not video.is_file():
        raise LiveValidationError("place a short reference.mp4 in live-fixtures to validate video import")
    return _dialog(s, "import_video", str(video))


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


@scenario("import_vrm", CUBE)
def _import_vrm(s: LiveSession) -> Any:
    from .live_scenarios import _ui_flow

    source = s.service.paths.root / "live-fixtures" / "VRM1_Constraint_Twist_Sample.vrm"
    if not source.is_file():
        raise LiveValidationError("run scripts/fetch_live_fixtures.py to download the VRM sample")
    return _ui_flow(s, "import", "vrm", str(source))


@scenario(
    "blend_shape",
    CUBE,
    crash_risk="2026.1.3 crashed right after importing a blend-shape FBX through the Python FBX loader",
)
def _blend_shape(s: LiveSession) -> Any:
    # blendshape_cube.fbx: a Blender cube "BlendCube" with one "Stretch" shape key.
    source = s.service.paths.root / "live-fixtures" / "blendshape_cube.fbx"
    if not source.is_file():
        raise LiveValidationError("run scripts/fetch_live_fixtures.py to build the blend shape fixture")
    before = {item["id"] for item in s.objects()}
    s.change("import_fbx", "io.import_fbx", {"path": str(source)})
    created = [item for item in s.objects() if item["id"] not in before]
    meshes = s.owners("MeshObject", created)
    if len(meshes) != 1:
        raise LiveValidationError(f"expected one imported mesh, found {len(meshes)}")
    return s.change("blend_shape", "mesh.blend_shape_weight", {"object_id": meshes[0], "weights": {"Stretch": 60.0}})


@scenario("retargeting", BACKFLIP)
def _retargeting(s: LiveSession) -> Any:
    # Backflip's animated Cascy is the source; a second, unanimated Cascy is
    # imported into the same scene as the target (both carry AutoPosing rigs).
    before = {item["id"]: item for item in s.objects()}
    _dialog(s, "import_scene_to_current", str(FIXTURES["fixture.sample.cascy"]))
    created = [item for item in s.objects() if item["id"] not in before]
    # "Import scene to current" adds a namespace to the imported names.
    def base(name: str) -> str:
        return name.replace("|", ":").rsplit(":", 1)[-1]

    targets = {base(item["name"]): item["id"] for item in created if item["type"] == "Point"}
    sources = {base(item["name"]): item["id"] for item in before.values() if item["type"] == "Point"}
    shared = sorted(set(targets) & set(sources))
    if not shared:
        raise LiveValidationError(
            "the imported character shares no point names with the animated one: "
            f"imported {[item['name'] for item in created][:4]}, existing {sorted(sources)[:4]}"
        )
    name = next((item for item in shared if "pelvis" in item.casefold()), shared[0])
    return s.change(
        "retargeting",
        "generation.retargeting",
        {"source_point_id": sources[name], "target_point_id": targets[name], "first_frame": 0, "last_frame": 20},
    )


def _video_export(s: LiveSession, feature_id: str) -> Any:
    arguments = dialog_flow_arguments(feature_id, s.output(feature_id))
    arguments.update({"width": 320, "height": 180, "quality": "LOW"})
    return s.change(feature_id, "system.ui_file_flow", arguments, timeout=900)


@scenario("export_video", BACKFLIP)
def _export_video(s: LiveSession) -> Any:
    return _video_export(s, "export_video")


@scenario("render_video", CUBE)
def _render_video(s: LiveSession) -> Any:
    return _video_export(s, "render_video")
