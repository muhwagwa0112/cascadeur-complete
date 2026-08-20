from __future__ import annotations

import hashlib
from pathlib import Path

from ..handler_registry import handler

_TAB_IDENTITIES = []


def _tab_identity(scene):
    """Return a session-stable ID even when tab order changes."""
    for known_scene, token in _TAB_IDENTITIES:
        try:
            if known_scene is scene or known_scene == scene:
                return token
        except Exception:
            continue
    token = "tab-" + hashlib.sha256((repr(scene) + "\n" + str(len(_TAB_IDENTITIES))).encode("utf-8")).hexdigest()[:20]
    _TAB_IDENTITIES.append((scene, token))
    return token


def _member(value, name, default=None):
    attribute = getattr(value, name, None)
    if attribute is None:
        return default
    try:
        return attribute() if callable(attribute) else attribute
    except Exception:
        return default


def _tabs(context):
    csc = context["csc"]
    app = csc.app.get_application()
    manager = app.get_scene_manager()
    current = manager.current_scene()
    result = []
    for index, item in enumerate(manager.scenes()):
        name = str(_member(item, "name", "untitled.casc"))
        path = str(_member(item, "get_path_name", ""))
        identity = _tab_identity(item)
        result.append(
            {
                "tab_id": identity,
                "index": index,
                "name": name,
                "path": path,
                "active": item == current,
                "scene": item,
            }
        )
    return result


def _public_tab(item):
    return {key: value for key, value in item.items() if key != "scene"}


def _find_tab(context, tab_id):
    tabs = _tabs(context)
    if tab_id is None:
        return next((item for item in tabs if item["active"]), None)
    text = str(tab_id)
    for item in tabs:
        if item["tab_id"] == text or str(item["index"]) == text:
            return item
    return None


@handler("scene.list")
def list_scenes(_scene, _arguments, _request, context):
    return [_public_tab(item) for item in _tabs(context)], []


@handler("scene.activate")
def activate_scene(_scene, arguments, _request, context):
    target = _find_tab(context, arguments.get("tab_id"))
    if target is None:
        raise KeyError("Unknown scene tab: " + str(arguments.get("tab_id")))
    manager = context["csc"].app.get_application().get_scene_manager()
    manager.set_current_scene(target["scene"])
    observed = _find_tab(context, target["tab_id"])
    if observed is None or not observed["active"]:
        raise AssertionError("POSTCONDITION_FAILED: scene tab did not become active")
    return _public_tab(observed), []


@handler("scene.close")
def close_scene(_scene, arguments, _request, context):
    target = _find_tab(context, arguments.get("tab_id"))
    if target is None:
        raise KeyError("Unknown scene tab: " + str(arguments.get("tab_id")))
    manager = context["csc"].app.get_application().get_scene_manager()
    replacement = None
    if target["active"] or len(manager.scenes()) == 1:
        # Removing the active application scene can terminate Cascadeur even
        # when SceneManager still reports stale background tabs. Always move
        # focus to a newly-created replacement before removing an active tab.
        replacement = manager.create_application_scene()
        manager.set_current_scene(replacement)
    manager.remove_application_scene(target["scene"])
    if _find_tab(context, target["tab_id"]) is not None:
        raise AssertionError("POSTCONDITION_FAILED: scene tab remains open")
    return {
        "tab_id": target["tab_id"],
        "closed": True,
        "replacement_tab_id": _tab_identity(replacement) if replacement is not None else None,
    }, []


@handler("scene.save_as")
def save_scene_as(_scene, arguments, _request, context):
    destination = Path(str(arguments["path"]))
    normalized = str(destination).replace("\\", "/")
    target = _find_tab(context, arguments.get("tab_id"))
    if target is None:
        raise KeyError("Unknown scene tab: " + str(arguments.get("tab_id")))
    app = context["csc"].app.get_application()
    manager = app.get_data_source_manager()
    attempts = (
        ("save_scene", lambda: manager.save_scene(target["scene"], normalized)),
        ("scene.save", lambda: target["scene"].save(normalized)),
    )
    errors = []
    result = None
    method = None
    for label, attempt in attempts:
        try:
            result = attempt()
            if destination.is_file() and destination.stat().st_size > 0:
                method = label
                break
            errors.append(label + " returned without creating a non-empty output")
        except Exception as exc:
            errors.append(label + ": " + type(exc).__name__ + ": " + str(exc))
    if method is None:
        raise AssertionError("POSTCONDITION_FAILED: save-as output was not created; " + " | ".join(errors))
    return {
        "tab_id": target["tab_id"],
        "path": str(destination),
        "bytes": destination.stat().st_size,
        "method": method,
        "return_value": context["json_safe"](result),
    }, []


@handler("scene.validate")
def validate_scene(scene, _arguments, _request, context):
    state = context["scene_state"](scene)
    object_ids = [item["id"] for item in state["objects"]]
    layer_ids = [item["id"] for item in state["layers"]]
    folder_ids = {item["id"] for item in state.get("folders", [])}
    root_id = state.get("layer_root_id")
    null_guid = "00000000-0000-0000-0000-000000000000"
    issues = []
    if len(object_ids) != len(set(object_ids)):
        issues.append({"code": "DUPLICATE_OBJECT_ID", "count": len(object_ids) - len(set(object_ids))})
    if len(layer_ids) != len(set(layer_ids)):
        issues.append({"code": "DUPLICATE_LAYER_ID", "count": len(layer_ids) - len(set(layer_ids))})
    for item in [*state["layers"], *state.get("folders", [])]:
        parent = item.get("parent")
        if parent and parent != null_guid and parent not in folder_ids and parent != root_id:
            issues.append({"code": "MISSING_LAYER_PARENT", "id": item["id"], "parent": parent})
    return {
        "valid": not issues,
        "issues": issues,
        "object_count": len(object_ids),
        "layer_count": len(layer_ids),
        "folder_count": len(folder_ids),
        "scene_id": state["scene_id"],
        "revision": state["revision"],
    }, []
