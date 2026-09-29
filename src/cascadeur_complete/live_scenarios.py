"""Per-feature live scenarios registered with ``live_validation.scenario``.

Scenarios only use the public service contract. Mutations run through
``prepare_change``/``commit_change``; the service records live evidence when the
bridge and host report every catalog postcondition for the feature.
"""

from __future__ import annotations

import math
import struct
import wave
from pathlib import Path
from typing import Any

from .live_validation import LiveSession, LiveValidationError, scenario
from .service import ui_file_flow_arguments

NONE = "fixture.none"
EMPTY = "fixture.empty_scene"
CUBE = "fixture.sample.cube"
CASCY = "fixture.sample.cascy"
BACKFLIP = "fixture.sample.backflip"


def _first(items, predicate, label: str):
    for item in items:
        if predicate(item):
            return item
    raise LiveValidationError(f"Fixture has no {label}")


def _write_tone(path: Path, seconds: float = 1.0, rate: int = 22050) -> Path:
    with wave.open(str(path), "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(rate)
        frames = b"".join(
            struct.pack("<h", int(8000 * math.sin(2 * math.pi * 440 * index / rate)))
            for index in range(int(seconds * rate))
        )
        stream.writeframes(frames)
    return path


# -- diagnostics and scene lifecycle --------------------------------------------------


@scenario("status", NONE)
def _status(s: LiveSession) -> Any:
    return {"scene": s.read("status", "system.status")["name"]}


@scenario("logs", NONE)
def _logs(s: LiveSession) -> Any:
    return {"count": s.read("logs", "system.logs", {"lines": 50})["count"]}


@scenario("scene_list", NONE)
def _scene_list(s: LiveSession) -> Any:
    return {"tabs": len(s.read("scene_list", "scene.list"))}


@scenario("scene_new", EMPTY)
def _scene_new(s: LiveSession) -> Any:
    # use_fixture(EMPTY) already created the scene through scene.new.
    return {"scene": s.status()["name"]}


@scenario("scene_open", CUBE)
def _scene_open(s: LiveSession) -> Any:
    return {"scene": s.status()["path"]}


@scenario("scene_summary", CUBE)
def _scene_summary(s: LiveSession) -> Any:
    return {"objects": len(s.read("scene_summary", "scene.summary")["objects"])}


@scenario("scene_validate", CUBE)
def _scene_validate(s: LiveSession) -> Any:
    return s.read("scene_validate", "scene.validate")["valid"]


@scenario("scene_save_as", CUBE)
def _scene_save_as(s: LiveSession) -> Any:
    return s.change("scene_save_as", "scene.save_as", {"path": s.output("save-as.casc")})["path"]


@scenario("scene_save", CUBE)
def _scene_save(s: LiveSession) -> Any:
    # scene_save_as moved the working document to a writable user path.
    return s.change("scene_save", "scene.save", {})["bytes"]


@scenario("scene_activate", CUBE)
def _scene_activate(s: LiveSession) -> Any:
    tabs = s.read("scene_list", "scene.list")
    current = _first(tabs, lambda item: item["active"], "active tab")
    other = _first(tabs, lambda item: not item["active"], "second tab")
    s.change("scene_activate", "scene.activate", {"tab_id": other["tab_id"]})
    s.change("scene_activate", "scene.activate", {"tab_id": current["tab_id"]})
    return {"activated": other["name"], "restored": current["name"]}


@scenario("scene_close", CUBE)
def _scene_close(s: LiveSession) -> Any:
    tabs = s.read("scene_list", "scene.list")
    closable = [item for item in tabs if not item["active"]]
    if not closable:
        raise LiveValidationError("scene_close needs an inactive tab")
    return s.change("scene_close", "scene.close", {"tab_id": closable[0]["tab_id"]})


# -- objects and selection ------------------------------------------------------------


@scenario("object_search", CUBE)
def _object_search(s: LiveSession) -> Any:
    return {"total": s.read("object_search", "scene.objects", {"offset": 0, "limit": 10})["total"]}


@scenario("object_hierarchy", CUBE)
def _object_hierarchy(s: LiveSession) -> Any:
    return {"roots": len(s.read("object_hierarchy", "object.hierarchy")["roots"])}


@scenario("object_properties", CUBE)
def _object_properties(s: LiveSession) -> Any:
    joint = s.object_named("joint1")
    return {"items": len(s.read("object_properties", "object.properties", {"ids": [joint]})["items"])}


@scenario("object_behaviors", CUBE)
def _object_behaviors(s: LiveSession) -> Any:
    joint = s.object_named("joint1")
    rows = s.read("object_behaviors", "object.behaviors", {"ids": [joint], "include_values": True})["items"]
    return {"behaviours": [item["name"] for item in rows[0]["behaviors"]]}


@scenario("selection_get", CUBE)
def _selection_get(s: LiveSession) -> Any:
    return {"selected": len(s.read("selection_get", "selection.get"))}


@scenario("selection_set", CUBE)
def _selection_set(s: LiveSession) -> Any:
    return s.change("selection_set", "selection.set", {"ids": [s.object_named("joint1")]})


@scenario("selection_add", CUBE)
def _selection_add(s: LiveSession) -> Any:
    return s.change("selection_add", "selection.add", {"ids": [s.object_named("joint1_Box")]})


@scenario("selection_remove", CUBE)
def _selection_remove(s: LiveSession) -> Any:
    return s.change("selection_remove", "selection.remove", {"ids": [s.object_named("joint1_Box")]})


@scenario("selection_filter", CUBE)
def _selection_filter(s: LiveSession) -> Any:
    rows = s.read("selection_filter", "selection.filter", {"type": "Joint", "selected_only": False})
    return {"joints": len(rows)}


@scenario("transform_get", CUBE)
def _transform_get(s: LiveSession) -> Any:
    return s.read("transform_get", "animation.transform_get", {"ids": [s.object_named("joint1_Box")]})


@scenario("transform_set", CUBE)
def _transform_set(s: LiveSession) -> Any:
    box = s.object_named("joint1_Box")
    current = s.read("transform_get", "animation.transform_get", {"ids": [box]})[0]
    position = [current["position"][0] + 1.0, current["position"][1], current["position"][2]]
    return s.change("transform_set", "animation.transform_set", {"ids": [box], "position": position})


@scenario("object_create", CUBE)
def _object_create(s: LiveSession) -> Any:
    created = s.change(
        "object_create", "object.create", {"name": "MCP Live Cube", "position": [6.0, 0.0, 0.0], "size": 1.0}
    )
    s.created_cube = created["id"]
    return created


def _live_cube(s: LiveSession) -> str:
    cube = getattr(s, "created_cube", None)
    if cube and any(item["id"] == cube for item in s.objects()):
        return cube
    return _object_create(s)["id"]


@scenario("object_rename", CUBE)
def _object_rename(s: LiveSession) -> Any:
    return s.change("object_rename", "object.rename", {"id": _live_cube(s), "name": "MCP Live Cube Renamed"})


@scenario("object_parent", CUBE)
def _object_parent(s: LiveSession) -> Any:
    return s.change("object_parent", "object.parent", {"ids": [_live_cube(s)], "parent_id": s.object_named("joint1")})


@scenario("object_unparent", CUBE)
def _object_unparent(s: LiveSession) -> Any:
    return s.change("object_unparent", "object.unparent", {"ids": [_live_cube(s)]})


# -- render ---------------------------------------------------------------------------


@scenario("camera_create", CUBE)
def _camera_create(s: LiveSession) -> Any:
    return s.change("camera_create", "render.camera_create", {})


@scenario("camera_aim", CUBE)
def _camera_aim(s: LiveSession) -> Any:
    return s.change("camera_aim", "render.camera_aim", {})


@scenario("light_point", CUBE)
def _light_point(s: LiveSession) -> Any:
    return s.change("light_point", "render.light_point", {})


@scenario("light_spot", CUBE)
def _light_spot(s: LiveSession) -> Any:
    return s.change("light_spot", "render.light_spot", {})


@scenario("viewport_state", CUBE)
def _viewport_state(s: LiveSession) -> Any:
    return {"viewports": s.read("viewport_state", "render.viewport_state")["count"]}


@scenario("camera_catalog", CUBE)
def _camera_catalog(s: LiveSession) -> Any:
    return s.read("camera_catalog", "render.camera_catalog")


@scenario("camera_view", CUBE)
def _camera_view(s: LiveSession) -> Any:
    return s.change("camera_view", "render.camera_view", {"position": [12.0, 8.0, 12.0], "target": [0.0, 1.0, 0.0]})


@scenario("camera_activate", CUBE)
def _camera_activate(s: LiveSession) -> Any:
    cameras = s.read("camera_catalog", "render.camera_catalog")["cameras"]
    target = next((item for item in cameras if not item["active"]), None)
    if target is None:
        s.change("camera_create", "render.camera_create", {})
        cameras = s.read("camera_catalog", "render.camera_catalog")["cameras"]
        target = _first(cameras, lambda item: not item["active"], "inactive camera")
    return s.change("camera_activate", "render.camera_activate", {"camera_id": target["id"]})


@scenario("view_mode", CUBE)
def _view_mode(s: LiveSession) -> Any:
    s.change("view_mode", "system.view_mode", {"mode": "Joint"})
    return s.change("view_mode", "system.view_mode", {"mode": "View"})


def _render(s: LiveSession, feature_id: str, operation: str, name: str) -> Any:
    return s.change(
        feature_id,
        operation,
        {"path": s.output(name), "width": 320, "height": 240, "samples": 4},
        timeout=300,
    )


@scenario("viewport_capture", CUBE)
def _viewport_capture(s: LiveSession) -> Any:
    return _render(s, "viewport_capture", "render.viewport_capture", "viewport.png")


@scenario("render_image", CUBE)
def _render_image(s: LiveSession) -> Any:
    return _render(s, "render_image", "render.image", "render.png")


@scenario("export_image", CUBE)
def _export_image(s: LiveSession) -> Any:
    return _render(s, "export_image", "io.export_image", "export.png")


# -- file exchange --------------------------------------------------------------------


@scenario("export_dae", CUBE)
def _export_dae(s: LiveSession) -> Any:
    result = s.change("export_dae", "io.export_dae", {"path": s.output("cube.dae")})
    s.exported_dae = result["path"]
    return result


@scenario("import_dae", CUBE)
def _import_dae(s: LiveSession) -> Any:
    source = getattr(s, "exported_dae", None) or _export_dae(s)["path"]
    return s.change("import_dae", "io.import_dae", {"path": source})


@scenario("export_fbx", CUBE)
def _export_fbx(s: LiveSession) -> Any:
    # FBX export fails on duplicate object names, which earlier import scenarios
    # add to the shared Cube scene; export from a freshly opened fixture.
    s.use_fixture(CUBE)
    result = s.change("export_fbx", "io.export_fbx", {"path": s.output("cube.fbx")})
    s.exported_fbx = result["path"]
    return result


@scenario("import_fbx", CUBE)
def _import_fbx(s: LiveSession) -> Any:
    source = getattr(s, "exported_fbx", None) or _export_fbx(s)["path"]
    return s.change("import_fbx", "io.import_fbx", {"path": source})


@scenario("import_audio", CUBE)
def _import_audio(s: LiveSession) -> Any:
    tone = _write_tone(Path(s.output("tone.wav")))
    return s.change("import_audio", "io.import_audio", {"path": str(tone), "duration": 1.0})


def _ui_flow(s: LiveSession, direction: str, format_name: str, path: str, preset: str = "scene") -> Any:
    feature_id, arguments = ui_file_flow_arguments(direction, format_name, path, preset)
    return s.change(feature_id, "system.ui_file_flow", arguments, timeout=240)


@scenario("export_usd", CUBE)
def _export_usd(s: LiveSession) -> Any:
    s.exported_usd = s.output("cube.usd")
    return _ui_flow(s, "export", "usd", s.exported_usd)


@scenario("import_usd", CUBE)
def _import_usd(s: LiveSession) -> Any:
    source = getattr(s, "exported_usd", None)
    if not source:
        _export_usd(s)
        source = s.exported_usd
    return _ui_flow(s, "import", "usd", source)


@scenario("action_invoke", CUBE)
def _action_invoke(s: LiveSession) -> Any:
    # A bound installed Python command; the product dispatcher is proven by it.
    return s.change(
        "command.add.primitives.cube",
        "system.action_invoke",
        {"action_id": "Add.Primitives.Cube", "expect_change": True},
    )


@scenario("ui_flow_run", CUBE)
def _ui_flow_run(s: LiveSession) -> Any:
    return _ui_flow(s, "export", "glb", s.output("dispatcher.glb"))


@scenario("export_glb", CUBE)
def _export_glb(s: LiveSession) -> Any:
    s.exported_glb = s.output("cube.glb")
    return _ui_flow(s, "export", "glb", s.exported_glb)


@scenario("import_glb", CUBE)
def _import_glb(s: LiveSession) -> Any:
    source = getattr(s, "exported_glb", None)
    if not source:
        _export_glb(s)
        source = s.exported_glb
    return _ui_flow(s, "import", "glb", source)


@scenario("export_gltf", CUBE)
def _export_gltf(s: LiveSession) -> Any:
    s.exported_gltf = s.output("cube.gltf")
    return _ui_flow(s, "export", "gltf", s.exported_gltf)


@scenario("import_gltf", CUBE)
def _import_gltf(s: LiveSession) -> Any:
    source = getattr(s, "exported_gltf", None)
    if not source:
        _export_gltf(s)
        source = s.exported_gltf
    return _ui_flow(s, "import", "gltf", source)


# -- undo / redo ----------------------------------------------------------------------


@scenario("undo", CUBE)
def _undo(s: LiveSession) -> Any:
    s.change("object_create", "object.create", {"name": "MCP Undo Cube", "position": [0.0, 4.0, 0.0], "size": 1.0})
    return s.change("undo", "system.undo", {"expect_change": True})


@scenario("redo", CUBE)
def _redo(s: LiveSession) -> Any:
    return s.change("redo", "system.redo", {"expect_change": True})


@scenario("inventory_refresh", NONE)
def _inventory_refresh(s: LiveSession) -> Any:
    result = s.service.refresh_inventory(timeout=180)
    if not result.get("ok"):
        raise LiveValidationError(f"inventory refresh failed: {result}")
    return {"counts": result.get("counts"), "features": result.get("feature_count")}
