from __future__ import annotations

import os
from collections import deque
from pathlib import Path

from ..handler_registry import handler
from ..log_safety import LOG_LEVELS, MAX_LOG_SCAN_BYTES, read_bounded_log_lines, summarize_log_levels


@handler("system.logs", postconditions=("bounded_tail",))
def read_logs(_scene, arguments, _request, _context):
    count = min(500, max(1, int(arguments.get("lines", 200))))
    pattern = str(arguments.get("pattern", ""))
    aliases = {"warn": "WARNING"}
    requested_level = aliases.get(pattern.casefold(), pattern.upper()) if pattern else ""
    if requested_level and requested_level not in LOG_LEVELS:
        raise ValueError("log filter must be a level: critical, fatal, error, warning, info, debug, trace, or other")
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        raise RuntimeError("LOCALAPPDATA is unavailable")
    path = Path(local_app_data) / "Nekki Limited" / "Cascadeur" / "logs" / "cascadeur_log.log"
    if not path.is_file():
        raise FileNotFoundError(path)
    # Public production diagnostics never return raw log messages. Convert a
    # fixed-size tail into a level-only schema so paths, scene data, tokens, and
    # novel multiline credential formats cannot cross the MCP boundary.
    raw_rows, source_truncated = read_bounded_log_lines(path)
    levels = summarize_log_levels(raw_rows)
    if requested_level:
        levels = [level for level in levels if level == requested_level]
    levels = list(deque(levels, maxlen=count))
    counts = {level: levels.count(level) for level in LOG_LEVELS if level in levels}
    return {
        "source": "cascadeur_log.log",
        "lines": [f"<{level}>" for level in levels],
        "levels": levels,
        "level_counts": counts,
        "count": len(levels),
        "tail_limit": count,
        "scan_limit_bytes": MAX_LOG_SCAN_BYTES,
        "source_truncated": source_truncated,
        "raw_content_exposed": False,
    }, []


@handler(
    "system.view_mode",
    "system.view_mode_get",
    "system.view_mode_set",
    postconditions=("viewport_mode_equals_request",),
)
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
        "observed_postconditions": ["viewport_mode_equals_request"] if requested is not None else [],
        "mode_changed": requested is not None,
        "apply_to_all": apply_to_all,
        "viewports": rows,
    }, []


@handler("system.dialog_probe", postconditions=("probe_dialog_shown",))
def dialog_probe(_scene, arguments, _request, context):
    """Show a Yes/No "Warning" dialog that records the pressed button.

    Live validation for focus-free dialog handling: the host answers it with the
    same helper it uses for Cascadeur's own warnings, while another application
    keeps the foreground. The answer lands in state/dialog_probe.json.
    """
    import json
    import time

    from ..runtime import atomic_json, runtime_root

    csc = context["csc"]
    token = str(arguments.get("token", ""))
    path = runtime_root() / "state" / "dialog_probe.json"
    atomic_json(path, {"token": token, "answer": None, "shown_at": time.time()})

    def answer(button):
        def record():
            atomic_json(path, {"token": token, "answer": button, "answered_at": time.time()})

        return record

    buttons = [
        csc.view.DialogButton(csc.view.StandardButton.Yes, answer("Yes")),
        csc.view.DialogButton(csc.view.StandardButton.No, answer("No")),
    ]
    csc.view.DialogManager.instance().show_buttons_dialog("Warning", "Cascadeur Complete dialog probe", buttons)
    return {"token": token, "path": str(path), "state": json.loads(path.read_text(encoding="utf-8"))}, []
