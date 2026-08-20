from __future__ import annotations

import os
import re
from collections import deque
from pathlib import Path

from ..handler_registry import handler


def _public_members(value):
    rows = []
    for name in sorted(item for item in dir(value) if not item.startswith("_")):
        try:
            member = getattr(value, name)
        except Exception as exc:
            rows.append({"name": name, "kind": "error", "detail": str(exc)})
            continue
        rows.append({"name": name, "kind": "method" if callable(member) else "property", "type": type(member).__name__})
    return rows


@handler("system.tool_inspect")
def tool_inspect(_scene, arguments, _request, context):
    name = str(arguments["tool_name"])
    app = context["csc"].app.get_application()
    tool = app.get_tools_manager().get_tool(name)
    view_scene = context["scene_view"]()
    editor = None
    editor_error = None
    if view_scene is not None:
        try:
            editor = tool.editor(view_scene)
        except Exception as exc:
            editor_error = str(exc)
    return {
        "tool_name": name,
        "tool_type": type(tool).__name__,
        "tool_members": _public_members(tool),
        "editor_type": type(editor).__name__ if editor is not None else None,
        "editor_members": _public_members(editor) if editor is not None else [],
        "editor_error": editor_error,
    }, []


@handler("system.logs")
def read_logs(_scene, arguments, _request, _context):
    count = min(2000, max(1, int(arguments.get("lines", 200))))
    pattern = str(arguments.get("pattern", ""))
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        raise RuntimeError("LOCALAPPDATA is unavailable")
    path = Path(local_app_data) / "Nekki Limited" / "Cascadeur" / "logs" / "cascadeur_log.log"
    if not path.is_file():
        raise FileNotFoundError(path)
    with path.open("r", encoding="utf-8", errors="replace") as stream:
        lines = deque(stream, maxlen=count)
    rows = [line.rstrip("\r\n") for line in lines]
    if pattern:
        expression = re.compile(pattern, flags=re.IGNORECASE)
        rows = [line for line in rows if expression.search(line)]
    return {"path": str(path), "lines": rows, "count": len(rows), "tail_limit": count}, []


@handler("system.settings_get")
def settings_get(_scene, arguments, _request, context):
    value_type = str(arguments.get("type", "string")).casefold()
    getters = {
        "bool": "get_bool_value",
        "float": "get_float_value",
        "int": "get_int_value",
        "string": "get_string_value",
    }
    if value_type not in getters:
        raise ValueError("type must be bool, float, int, or string")
    view_scene = context["scene_view"]()
    if view_scene is None:
        raise RuntimeError("No application scene is available")
    handler = view_scene.get_setting_handler()
    path = str(arguments["key"])
    section = str(arguments.get("section", ""))
    key = path
    if not section:
        if "/" not in path:
            raise ValueError("key must be SECTION/KEY or section must be provided explicitly")
        section, key = path.split("/", 1)
    value = getattr(handler, getters[value_type])(section, key)
    return {
        "path": path,
        "section": section,
        "key": key,
        "type": value_type,
        "value": context["json_safe"](value),
    }, []


@handler("system.view_mode", "system.view_mode_get", "system.view_mode_set")
def view_mode(_scene, arguments, _request, context):
    view_scene = context["scene_view"]()
    if view_scene is None:
        raise RuntimeError("No application scene is available")
    apply_to_all = bool(arguments.get("apply_to_all", False))
    viewports = list(view_scene.viewports()) if apply_to_all else [view_scene.active_viewport()]
    if not viewports or any(item is None for item in viewports):
        raise RuntimeError("No target viewport is available")
    domains = [item.domain_viewport() for item in viewports]
    allowed = ("View", "AutoPosing", "PointController", "Controller", "Joint", "Mesh", "Rigging")
    requested = arguments.get("mode")
    if requested is not None:
        requested_text = str(requested)
        try:
            enum_name = next(item for item in allowed if item.casefold() == requested_text.casefold())
        except StopIteration as exc:
            raise ValueError("mode must be one of: " + ", ".join(allowed)) from exc
        enum_value = getattr(context["csc"].view.ViewportMode, enum_name)
        for viewport in domains:
            viewport.set_mode_visualizers(enum_value)
    rows = []
    for viewport in domains:
        observed = viewport.mode_visualizers()
        observed_name = str(context["read_member"](observed, "name"))
        rows.append(
            {
                "viewport_id": context["id_string"](viewport.id()),
                "mode": observed_name,
                "is_main": bool(viewport.is_main()),
            }
        )
    if requested is not None and any(item["mode"].casefold() != enum_name.casefold() for item in rows):
        raise AssertionError("POSTCONDITION_FAILED: viewport mode differs from request")
    return {
        "mode_changed": requested is not None,
        "apply_to_all": apply_to_all,
        "viewports": rows,
    }, []
