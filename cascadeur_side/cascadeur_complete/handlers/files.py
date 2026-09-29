"""File-level adapters that Cascadeur exposes through Python without a dialog."""

from __future__ import annotations

import json
import os
from pathlib import Path

from ..handler_registry import handler


def _autosave_dir():
    local = os.environ.get("LOCALAPPDATA")
    if not local:
        raise RuntimeError("LOCALAPPDATA is unavailable")
    return (Path(local) / "Nekki Limited" / "Cascadeur" / "autosave").resolve()


def _groups(context, view):
    tool = context["csc"].app.get_application().get_tools_manager().get_tool("SelectionGroupsTool")
    editor = tool.editor(view)
    core = editor.core()
    rows = {}
    for index, group in dict(core.get_groups()).items():
        objects = sorted(context["id_string"](item) for item in context["read_member"](group, "objects"))
        rows[int(index)] = objects
    return editor, rows


@handler("io.selection_groups_import", postconditions=("selection_groups_loaded",))
def selection_groups_import(scene, arguments, _request, context):
    path = Path(str(arguments["path"]))
    if not path.is_file():
        raise FileNotFoundError(path)
    try:
        expected = {
            int(row["index"]): sorted(str(name) for name in row.get("objects", []))
            for row in json.loads(path.read_text(encoding="utf-8"))["groups"]
        }
    except (ValueError, KeyError, TypeError) as exc:
        raise ValueError("path is not a Cascadeur selection groups file") from exc
    if not any(expected.values()):
        raise ValueError("The selection groups file names no objects")
    view = context["scene_view"]()
    editor, _before = _groups(context, view)
    editor.import_file(str(path).replace("\\", "/"))
    _editor, after = _groups(context, view)
    # The file stores object names; every group it names must now hold exactly
    # the scene objects with those names (whatever the groups held before).
    model_viewer = context["domain_scene"](scene).model_viewer()
    names = {context["id_string"](item): str(model_viewer.get_object_name(item)) for item in model_viewer.get_objects()}
    observed = {index: sorted(names.get(item, item) for item in after.get(index, [])) for index in expected}
    present = set(names.values())
    for index, wanted in expected.items():
        if sorted(name for name in wanted if name in present) != observed[index]:
            raise AssertionError(f"POSTCONDITION_FAILED: selection group {index} does not match the file")
    return {"path": str(path), "groups": {str(key): len(value) for key, value in observed.items()}}, []


@handler("scene.open_autosave", postconditions=("autosave_scene_loaded",))
def open_autosave(_scene, arguments, _request, context):
    root = _autosave_dir()
    candidates = sorted(root.glob("*.casc"), key=lambda item: item.stat().st_mtime, reverse=True)
    if arguments.get("path"):
        requested = Path(str(arguments["path"])).resolve()
        if requested.parent != root or not requested.is_file():
            raise ValueError("path must be an existing .casc file inside the Cascadeur autosave folder")
        target = requested
    elif candidates:
        target = candidates[0]
    else:
        raise FileNotFoundError("The Cascadeur autosave folder has no scenes")
    loaded = context["csc"].app.get_application().get_data_source_manager().load_scene(str(target))
    current = context["scene_view"]()
    observed = os.path.normcase(os.path.abspath(str(current.get_path_name()))) if current else ""
    if observed != os.path.normcase(str(target)):
        raise AssertionError("POSTCONDITION_FAILED: autosave scene is not the active document")
    return {"path": str(target), "loaded": bool(loaded), "available": len(candidates)}, []


@handler("scene.save_new_version", postconditions=("new_version_file_saved",))
def save_new_version(_scene, _arguments, _request, context):
    view = context["scene_view"]()
    before = Path(str(view.get_path_name()))
    if not before.is_file():
        raise ValueError("Save As New Version needs a scene that was saved to a file")
    siblings = {item.name for item in before.parent.glob("*.casc")}
    context["csc"].app.get_application().get_action_manager().call_action("File.Save as new version")
    after = Path(str(context["scene_view"]().get_path_name()))
    created = sorted({item.name for item in before.parent.glob("*.casc")} - siblings)
    if after == before or not after.is_file() or after.stat().st_size <= 0 or after.name not in created:
        raise AssertionError("POSTCONDITION_FAILED: no new version file became the active document")
    return {"previous_path": str(before), "path": str(after), "bytes": after.stat().st_size}, []
