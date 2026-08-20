from __future__ import annotations

import json
from functools import lru_cache
from typing import Any, Literal

from mcp.server import MCPServer

from .models import ErrorCode, ExecutionMode, ResultEnvelope
from .service import CascadeurService

mcp = MCPServer(
    "cascadeur-complete",
    instructions=(
        "Cascadeur 2026.1.x automation. Read capabilities first. Destructive operations require "
        "change_prepare followed by change_commit. Never assume a gated feature ran."
    ),
)


@lru_cache(maxsize=1)
def service() -> CascadeurService:
    return CascadeurService()


def _dump(value: Any) -> str:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return json.dumps(value, ensure_ascii=False, indent=2)


@mcp.resource("cascadeur://capabilities")
def capabilities_resource() -> str:
    """Version, license, bridge, dependency, and policy status."""
    return _dump(service().capabilities(live=True))


@mcp.resource("cascadeur://features")
def features_resource() -> str:
    """Complete generated feature matrix."""
    return _dump(
        {"count": len(service().features), "features": [item.model_dump(mode="json") for item in service().features]}
    )


@mcp.resource("cascadeur://csc/schema")
def csc_schema_resource() -> str:
    """Normalized schema discovered from the installed csc API."""
    return _dump(service().schema)


@mcp.resource("cascadeur://actions")
def actions_resource() -> str:
    """Installed Python commands and GUI/action routes."""
    return _dump(
        {
            "commands": service().commands,
            "features": [
                item.model_dump(mode="json")
                for item in service().features
                if item.execution_mode in (ExecutionMode.ACTION, ExecutionMode.UIA)
            ],
        }
    )


@mcp.resource("cascadeur://scene/summary")
def scene_summary_resource() -> str:
    """Current scene state and revision."""
    return _dump(service().execute("scene_summary", "scene.summary"))


@mcp.resource("cascadeur://scene/objects")
def scene_objects_resource() -> str:
    """First page of current objects and controllers."""
    return _dump(service().execute("object_search", "scene.objects", {"offset": 0, "limit": 200}))


@mcp.resource("cascadeur://jobs/{job_id}")
def job_resource(job_id: str) -> str:
    """Long-running job progress, logs, and result."""
    record = service().jobs.get(job_id)
    return _dump(record or {"ok": False, "error": "job not found", "job_id": job_id})


@mcp.resource("cascadeur://snapshots/{snapshot_id}")
def snapshot_resource(snapshot_id: str) -> str:
    """Snapshot metadata without exposing file contents."""
    path = service().paths.snapshots / f"{snapshot_id}.casc"
    return _dump(
        {
            "snapshot_id": snapshot_id,
            "exists": path.is_file(),
            "path": str(path) if path.is_file() else None,
            "bytes": path.stat().st_size if path.is_file() else None,
            "modified_at": path.stat().st_mtime if path.is_file() else None,
        }
    )


@mcp.tool()
def cascadeur_status(refresh: bool = True) -> dict[str, Any]:
    """Get bridge health, installed version baseline, license, scene and capability counts."""
    return service().capabilities(live=refresh)


@mcp.tool()
def cascadeur_logs(lines: int = 200, pattern: str | None = None) -> dict[str, Any]:
    """Read a bounded tail of Cascadeur's current log, optionally filtered by a regular expression."""
    return service().execute("logs", "system.logs", {"lines": lines, "pattern": pattern or ""}).model_dump(mode="json")


@mcp.tool()
def cascadeur_tool_inspect(tool_name: str) -> dict[str, Any]:
    """List public runtime/editor members of one registered Cascadeur tool without invoking them."""
    return service().execute("tool_inspect", "system.tool_inspect", {"tool_name": tool_name}).model_dump(mode="json")


@mcp.tool()
def setting_get(
    key: str,
    value_type: Literal["bool", "float", "int", "string"] = "string",
    section: str | None = None,
) -> dict[str, Any]:
    """Read SECTION/KEY (or an explicit section and key) through Cascadeur's SettingsHandler."""
    return (
        service()
        .execute(
            "settings_get",
            "system.settings_get",
            {"key": key, "type": value_type, "section": section or ""},
        )
        .model_dump(mode="json")
    )


@mcp.tool()
def viewport_mode(
    mode: Literal["View", "AutoPosing", "PointController", "Controller", "Joint", "Mesh", "Rigging"]
    | None = None,
    apply_to_all: bool = False,
) -> dict[str, Any]:
    """Read or set the active (or every) viewport visualizer mode and verify the observed mode."""
    svc = service()
    operation = "system.view_mode_get" if mode is None else "system.view_mode_set"
    scene_id = None
    expected_revision = None
    if mode is not None:
        status = svc.refresh_live()
        if not status.ok or not isinstance(status.result, dict):
            return status.model_dump(mode="json")
        scene_id = status.result.get("scene_id")
        expected_revision = status.result.get("revision")
    return (
        svc
        .execute(
            "view_mode",
            operation,
            {"mode": mode, "apply_to_all": apply_to_all},
            scene_id=scene_id,
            expected_revision=expected_revision,
        )
        .model_dump(mode="json")
    )


@mcp.tool()
def feature_search(
    query: str = "", family: str | None = None, state: str | None = None, limit: int = 100
) -> list[dict[str, Any]]:
    """Search every product, csc API, GUI tool and bundled command capability."""
    return service().feature_search(query, family, state, limit)


@mcp.tool()
def feature_describe(feature_id: str) -> dict[str, Any]:
    """Describe route, safety, license/dependency state, and test identity for one feature."""
    try:
        return service().feature(feature_id).model_dump(mode="json")
    except KeyError:
        return {"ok": False, "error_code": ErrorCode.INVALID_REQUEST, "error": "Unknown feature id"}


@mcp.tool()
def inventory_refresh(timeout: float = 120) -> dict[str, Any]:
    """Rebuild the csc schema and feature matrix from the running installed Cascadeur."""
    return service().refresh_inventory(timeout)


@mcp.tool()
def job_submit(
    feature_id: str,
    operation_name: str,
    arguments: dict[str, Any] | None = None,
    scene_id: str | None = None,
    expected_revision: str | None = None,
    timeout: float = 300,
) -> dict[str, Any]:
    """Submit a non-destructive operation as a persistent background job."""
    return service().submit_job(
        feature_id,
        operation_name,
        arguments,
        scene_id=scene_id,
        expected_revision=expected_revision,
        timeout=timeout,
    )


@mcp.tool()
def job_status(job_id: str) -> dict[str, Any]:
    """Read current progress, logs and retained result for a job."""
    record = service().jobs.get(job_id)
    return (
        record.model_dump(mode="json")
        if record
        else {"ok": False, "error_code": ErrorCode.INVALID_REQUEST, "error_message": "Unknown job id"}
    )


@mcp.tool()
def job_cancel(job_id: str) -> dict[str, Any]:
    """Cancel a queued job or request cancellation of an already claimed operation."""
    try:
        return service().jobs.cancel(job_id).model_dump(mode="json")
    except KeyError:
        return {"ok": False, "error_code": ErrorCode.INVALID_REQUEST, "error_message": "Unknown job id"}


@mcp.tool()
def job_retry(job_id: str) -> dict[str, Any]:
    """Retry a failed or canceled job using its persisted operation contract."""
    return service().retry_job(job_id)


@mcp.tool()
def scene_summary() -> dict[str, Any]:
    """Read current scene, verified frame, selection, objects, layers, and revision."""
    return service().execute("scene_summary", "scene.summary").model_dump(mode="json")


@mcp.tool()
def scene_objects(offset: int = 0, limit: int = 200) -> dict[str, Any]:
    """Read a paginated page of scene objects, types and IDs."""
    return (
        service().execute("object_search", "scene.objects", {"offset": offset, "limit": limit}).model_dump(mode="json")
    )


@mcp.tool()
def selection_edit(
    action: Literal["get", "set", "add", "remove", "filter"],
    ids: list[str] | None = None,
    pivot_id: str | None = None,
    object_type: str | None = None,
    name_contains: str | None = None,
    selected_only: bool = True,
    scene_id: str | None = None,
    expected_revision: str | None = None,
) -> dict[str, Any]:
    """Read, replace, add, remove, or filter the current object selection."""
    feature_id = {
        "get": "selection_get",
        "set": "selection_set",
        "add": "selection_add",
        "remove": "selection_remove",
        "filter": "selection_filter",
    }[action]
    arguments: dict[str, Any] = {"ids": ids or []}
    if pivot_id is not None:
        arguments["pivot_id"] = pivot_id
    if object_type is not None:
        arguments["type"] = object_type
    if name_contains is not None:
        arguments["name_contains"] = name_contains
    arguments["selected_only"] = selected_only
    return (
        service()
        .execute(
            feature_id,
            f"selection.{action}",
            arguments,
            scene_id=scene_id,
            expected_revision=expected_revision,
        )
        .model_dump(mode="json")
    )


@mcp.tool()
def object_delete_prepare(ids: list[str], ttl_seconds: float = 300) -> dict[str, Any]:
    """Return the exact UI-only gate for deletion until a verified adapter exists."""
    if not ids:
        return {"ok": False, "error_code": ErrorCode.INVALID_REQUEST, "error_message": "ids cannot be empty"}
    return service().prepare_change("object_delete", "object.delete", {"ids": ids}, ttl_seconds)


@mcp.tool()
def object_read(
    action: Literal["hierarchy", "properties", "behaviors"],
    ids: list[str] | None = None,
    include_values: bool = False,
) -> dict[str, Any]:
    """Read object hierarchy, layer membership, properties, and Behavior metadata."""
    feature_id = {
        "hierarchy": "object_hierarchy",
        "properties": "object_properties",
        "behaviors": "object_behaviors",
    }[action]
    return (
        service()
        .execute(
            feature_id,
            f"object.{action}",
            {"ids": ids or [], "include_values": include_values},
        )
        .model_dump(mode="json")
    )


@mcp.tool()
def object_write(
    action: Literal["rename", "create", "duplicate", "parent", "unparent", "delete"],
    ids: list[str] | None = None,
    object_id: str | None = None,
    name: str | None = None,
    parent_id: str | None = None,
    position: list[float] | None = None,
    size: float = 3.0,
    scene_id: str | None = None,
    expected_revision: str | None = None,
    confirmation_token: str | None = None,
) -> dict[str, Any]:
    """Rename, create, duplicate, reparent, unparent, or delete scene objects with safety checks."""
    if action == "rename" and (not object_id or not name):
        return {"ok": False, "error_code": ErrorCode.INVALID_REQUEST, "error_message": "id and name are required"}
    if action in ("duplicate", "parent", "unparent", "delete") and not ids:
        return {"ok": False, "error_code": ErrorCode.INVALID_REQUEST, "error_message": "ids are required"}
    if action == "create" and position is not None and len(position) != 3:
        return {
            "ok": False,
            "error_code": ErrorCode.INVALID_REQUEST,
            "error_message": "position must contain exactly three values",
        }
    feature_id = {
        "rename": "object_rename",
        "create": "object_create",
        "duplicate": "object_duplicate",
        "parent": "object_parent",
        "unparent": "object_unparent",
        "delete": "object_delete",
    }[action]
    arguments: dict[str, Any] = {"ids": ids or []}
    if object_id:
        arguments["id"] = object_id
    if name:
        arguments["name"] = name
    if parent_id and action != "unparent":
        arguments["parent_id"] = parent_id
    if position is not None:
        arguments["position"] = position
    arguments["size"] = size
    return (
        service()
        .execute(
            feature_id,
            f"object.{action}",
            arguments,
            scene_id=scene_id,
            expected_revision=expected_revision,
            confirmation_token=confirmation_token,
        )
        .model_dump(mode="json")
    )


@mcp.tool()
def operation_batch(
    feature_id: str,
    operations: list[dict[str, Any]],
    scene_id: str | None = None,
    expected_revision: str | None = None,
    timeout: float = 60,
    confirmation_token: str | None = None,
) -> dict[str, Any]:
    """Execute multiple registered bridge operations in one Cascadeur UI-thread entry."""
    return (
        service()
        .batch(
            feature_id,
            operations,
            scene_id=scene_id,
            expected_revision=expected_revision,
            timeout=timeout,
            confirmation_token=confirmation_token,
        )
        .model_dump(mode="json")
    )


@mcp.tool()
def change_prepare(
    feature_id: str, operation_name: str, arguments: dict[str, Any], ttl_seconds: float = 300
) -> dict[str, Any]:
    """Dry-run a destructive change, save a CASC snapshot, and return an expiring token."""
    try:
        return service().prepare_change(feature_id, operation_name, arguments, ttl_seconds)
    except (KeyError, ValueError) as exc:
        return {"ok": False, "error_code": ErrorCode.INVALID_REQUEST, "error_message": str(exc)}


@mcp.tool()
def change_commit(confirmation_token: str, timeout: float = 120) -> dict[str, Any]:
    """Commit exactly the prepared operation if scene revision and selection still match."""
    return service().commit_change(confirmation_token, timeout).model_dump(mode="json")


@mcp.tool()
def change_cancel(confirmation_token: str) -> dict[str, Any]:
    """Cancel an unused confirmation token without touching the scene."""
    return {"ok": service().changes.cancel(confirmation_token)}


@mcp.tool()
def change_rollback(snapshot_id: str, expected_revision: str | None = None) -> dict[str, Any]:
    """Open a Cascadeur snapshot created before a protected change."""
    return service().rollback(snapshot_id, expected_revision).model_dump(mode="json")


@mcp.tool()
def scene_exchange_prepare(
    direction: Literal["import", "export"],
    format: Literal["usd", "glb", "gltf", "vrm"],
    path: str,
    preset: Literal["animation", "model", "scene"] = "scene",
    allow_overwrite: bool = False,
    ttl_seconds: float = 300,
) -> dict[str, Any]:
    """Prepare a protected USD/GLB/GLTF/VRM file flow using exact 2026.1 action and dialog IDs."""
    suffix = "." + format
    if not path.casefold().endswith(suffix):
        return {
            "ok": False,
            "error_code": ErrorCode.INVALID_REQUEST,
            "error_message": f"{format} path must end with {suffix}",
        }
    if format == "vrm" and direction == "export":
        return {
            "ok": False,
            "error_code": ErrorCode.INVALID_REQUEST,
            "error_message": "Cascadeur 2026.1.2 exposes VRM import but no VRM export action",
        }
    if format == "usd":
        allowed = {"import": {"animation", "model", "scene"}, "export": {"model", "scene"}}[direction]
        if preset not in allowed:
            return {
                "ok": False,
                "error_code": ErrorCode.INVALID_REQUEST,
                "error_message": f"USD {direction} supports presets: {', '.join(sorted(allowed))}",
            }
        action_id = f"File.{direction.title()}.{preset.title()}.Usd..."
        feature_id = f"{direction}_usd"
        dialog_title = f"{direction.title()}. preset: {preset}"
        options_title = None
        options_accept_title = None
        file_type_extension = None
    else:
        action_id = "File.Import.Glb" if direction == "import" else "File.Export.Glb"
        feature_id = f"{direction}_{format}"
        dialog_title = f"{direction.title()}. preset: default"
        options_title = "Glb/Gltf/Vrm(a) Import" if direction == "import" else "Glb/Gltf Export"
        options_accept_title = direction.title()
        file_type_extension = None if format == "glb" else suffix
    return service().prepare_change(
        feature_id,
        "system.ui_file_flow",
        {
            "action_id": action_id,
            "path": path,
            "dialog_title": dialog_title,
            "options_title": options_title,
            "options_accept_title": options_accept_title,
            "file_type_extension": file_type_extension,
            "input": direction == "import",
            "output": direction == "export",
            "allow_overwrite": allow_overwrite,
        },
        ttl_seconds,
    )


@mcp.tool()
def ui_flow_prepare(
    flow_id: Literal[
        "import_usd_animation",
        "import_usd_model",
        "import_usd_scene",
        "export_usd_model",
        "export_usd_scene",
        "import_glb",
        "import_gltf",
        "import_vrm",
        "export_glb",
        "export_gltf",
    ],
    path: str,
    allow_overwrite: bool = False,
    ttl_seconds: float = 300,
) -> dict[str, Any]:
    """Prepare one exact, version-registered UIA file flow; commit it with change_commit."""
    direction, format_name, *preset_parts = flow_id.split("_")
    preset = preset_parts[0] if preset_parts else "scene"
    return scene_exchange_prepare(
        direction=direction,  # type: ignore[arg-type]
        format=format_name,  # type: ignore[arg-type]
        path=path,
        preset=preset,  # type: ignore[arg-type]
        allow_overwrite=allow_overwrite,
        ttl_seconds=ttl_seconds,
    )


@mcp.tool()
def scene_file(
    action: Literal["list", "activate", "new", "open", "save", "save_as", "close", "validate"],
    path: str | None = None,
    tab_id: str | None = None,
    scene_id: str | None = None,
    expected_revision: str | None = None,
    confirmation_token: str | None = None,
) -> dict[str, Any]:
    """Create, open, or save CASC scenes. New/open use the protected change contract."""
    feature_id = {
        "list": "scene_list",
        "activate": "scene_activate",
        "new": "scene_new",
        "open": "scene_open",
        "save": "scene_save",
        "save_as": "scene_save_as",
        "close": "scene_close",
        "validate": "scene_validate",
    }[action]
    arguments: dict[str, Any] = {}
    if path:
        arguments["path"] = path
    if tab_id:
        arguments["tab_id"] = tab_id
    return (
        service()
        .execute(
            feature_id,
            f"scene.{action}",
            arguments,
            scene_id=scene_id,
            expected_revision=expected_revision,
            confirmation_token=confirmation_token,
        )
        .model_dump(mode="json")
    )


@mcp.tool()
def io_transfer(
    feature_id: str,
    path: str,
    options: dict[str, Any] | None = None,
    scene_id: str | None = None,
    expected_revision: str | None = None,
    confirmation_token: str | None = None,
    timeout: float = 180,
) -> dict[str, Any]:
    """Run a registered import/export feature with path validation and postcondition checks."""
    operation = feature_id.replace("import_", "io.import_").replace("export_", "io.export_")
    arguments = {"path": path, **(options or {})}
    return (
        service()
        .execute(
            feature_id,
            operation,
            arguments,
            scene_id=scene_id,
            expected_revision=expected_revision,
            timeout=timeout,
            confirmation_token=confirmation_token,
        )
        .model_dump(mode="json")
    )


@mcp.tool()
def timeline_set_frame(frame: int, scene_id: str | None = None, expected_revision: str | None = None) -> dict[str, Any]:
    """Set and verify the playhead using the domain scene getter, not cached UI telemetry."""
    return (
        service()
        .execute(
            "timeline_set_frame",
            "timeline.set_frame",
            {"frame": frame},
            scene_id=scene_id,
            expected_revision=expected_revision,
        )
        .model_dump(mode="json")
    )


@mcp.tool()
def timeline_get() -> dict[str, Any]:
    """Read unclamped playhead, total layer frame count, and animation boundary."""
    return service().execute("timeline_get", "timeline.get").model_dump(mode="json")


@mcp.tool()
def transform_edit(
    action: Literal["get", "set"],
    ids: list[str] | None = None,
    frame: int | None = None,
    space: Literal["local", "global"] = "local",
    position: list[float] | None = None,
    rotation_euler_xyz_radians: list[float] | None = None,
    scale: list[float] | None = None,
    scene_id: str | None = None,
    expected_revision: str | None = None,
) -> dict[str, Any]:
    """Read or write position, Euler rotation (radians), and local scale for explicit or selected objects."""
    if action == "set" and all(value is None for value in (position, rotation_euler_xyz_radians, scale)):
        return {
            "ok": False,
            "error_code": ErrorCode.INVALID_REQUEST,
            "error_message": "set requires at least one transform component",
        }
    arguments: dict[str, Any] = {"ids": ids or [], "space": space}
    if frame is not None:
        arguments["frame"] = frame
    if position is not None:
        arguments["position"] = position
    if rotation_euler_xyz_radians is not None:
        arguments["rotation_euler_xyz_radians"] = rotation_euler_xyz_radians
    if scale is not None:
        arguments["scale"] = scale
    return (
        service()
        .execute(
            "transform_get" if action == "get" else "transform_set",
            "animation.transform_get" if action == "get" else "animation.transform_set",
            arguments,
            scene_id=scene_id,
            expected_revision=expected_revision,
        )
        .model_dump(mode="json")
    )


@mcp.tool()
def layer_list() -> dict[str, Any]:
    """Read every animation layer with ID, name, parent, visibility, lock and keys."""
    return service().execute("layer_list", "layer.list").model_dump(mode="json")


@mcp.tool()
def layer_write(
    action: Literal[
        "create", "delete", "visibility", "lock", "activate", "folder_create", "folder_move", "folder_rename"
    ],
    layer_id: str | None = None,
    name: str | None = None,
    parent_id: str | None = None,
    value: bool | None = None,
    item_id: str | None = None,
    position: int | None = None,
    with_default_layer: bool = True,
    scene_id: str | None = None,
    expected_revision: str | None = None,
    confirmation_token: str | None = None,
) -> dict[str, Any]:
    """Create/delete a layer or set visibility/lock with revision and deletion protection."""
    if action == "create" and not name:
        return {"ok": False, "error_code": ErrorCode.INVALID_REQUEST, "error_message": "name is required"}
    if action in ("delete", "visibility", "lock", "activate") and not layer_id:
        return {"ok": False, "error_code": ErrorCode.INVALID_REQUEST, "error_message": "layer_id is required"}
    if action in ("visibility", "lock") and value is None:
        return {"ok": False, "error_code": ErrorCode.INVALID_REQUEST, "error_message": "value is required"}
    if action in ("folder_move", "folder_rename") and not item_id:
        return {"ok": False, "error_code": ErrorCode.INVALID_REQUEST, "error_message": "item_id is required"}
    if action in ("folder_create", "folder_rename") and not name:
        return {"ok": False, "error_code": ErrorCode.INVALID_REQUEST, "error_message": "name is required"}
    feature_id = {
        "create": "layer_create",
        "delete": "layer_delete",
        "visibility": "layer_visibility",
        "lock": "layer_lock",
        "activate": "layer_activate",
        "folder_create": "layer_folder",
        "folder_move": "layer_folder",
        "folder_rename": "layer_folder",
    }[action]
    arguments: dict[str, Any] = {}
    if layer_id is not None:
        arguments["layer_id"] = layer_id
    if name is not None:
        arguments["name"] = name
    if parent_id is not None:
        arguments["parent_id"] = parent_id
    if item_id is not None:
        arguments["item_id"] = item_id
    if position is not None:
        arguments["position"] = position
    arguments["with_default_layer"] = with_default_layer
    if action == "visibility":
        arguments["visible"] = value
    if action == "lock":
        arguments["locked"] = value
    operation_action = action.removeprefix("folder_")
    if action.startswith("folder_"):
        arguments["action"] = operation_action
    return (
        service()
        .execute(
            feature_id,
            "layer.folder" if action.startswith("folder_") else f"layer.{action}",
            arguments,
            scene_id=scene_id,
            expected_revision=expected_revision,
            confirmation_token=confirmation_token,
        )
        .model_dump(mode="json")
    )


@mcp.tool()
def key_edit(
    action: Literal["list", "add", "delete"],
    layer_id: str | None = None,
    frame: int | None = None,
    scene_id: str | None = None,
    expected_revision: str | None = None,
    confirmation_token: str | None = None,
) -> dict[str, Any]:
    """List, add or delete layer keys; deletion uses the protected change contract."""
    if action in ("add", "delete") and (not layer_id or frame is None):
        return {
            "ok": False,
            "error_code": ErrorCode.INVALID_REQUEST,
            "error_message": "layer_id and frame are required",
        }
    feature_id = {"list": "key_list", "add": "key_add", "delete": "key_delete"}[action]
    arguments: dict[str, Any] = {}
    if layer_id is not None:
        arguments["layer_id"] = layer_id
    if frame is not None:
        arguments["frame"] = frame
    return (
        service()
        .execute(
            feature_id,
            f"animation.key_{action}",
            arguments,
            scene_id=scene_id,
            expected_revision=expected_revision,
            confirmation_token=confirmation_token,
        )
        .model_dump(mode="json")
    )


@mcp.tool()
def animation_curve(
    action: Literal["query", "set_interpolation", "set_tangent"],
    layer_id: str | None = None,
    layer_ids: list[str] | None = None,
    frame: int | None = None,
    value: str | None = None,
    first_frame: int | None = None,
    last_frame: int | None = None,
    scene_id: str | None = None,
    expected_revision: str | None = None,
) -> dict[str, Any]:
    """Query layer sections or set interpolation and tangent modes with postcondition verification."""
    if action != "query" and (not layer_id or frame is None or not value):
        return {
            "ok": False,
            "error_code": ErrorCode.INVALID_REQUEST,
            "error_message": "layer_id, frame, and value are required for edits",
        }
    if action == "query":
        arguments: dict[str, Any] = {"layer_ids": layer_ids or ([layer_id] if layer_id else [])}
        if first_frame is not None:
            arguments["first_frame"] = first_frame
        if last_frame is not None:
            arguments["last_frame"] = last_frame
        feature_id = "graph_query"
        operation = "animation.graph_query"
    else:
        operation_kind = "interpolation" if action == "set_interpolation" else "tangent"
        arguments = {"layer_id": layer_id, "frame": frame, "value": value, "operation": operation_kind}
        feature_id = "interpolation_set" if action == "set_interpolation" else "tangent_set"
        operation = f"animation.{feature_id}"
    return (
        service()
        .execute(
            feature_id,
            operation,
            arguments,
            scene_id=scene_id,
            expected_revision=expected_revision,
        )
        .model_dump(mode="json")
    )


@mcp.tool()
def viewport_camera(
    action: Literal["viewport_state", "camera_catalog", "camera_view", "camera_activate"],
    position: list[float] | None = None,
    target: list[float] | None = None,
    camera_type: Literal["PERSPECTIVE", "ISOMETRIC"] | None = None,
    camera_id: str | None = None,
    scene_id: str | None = None,
    expected_revision: str | None = None,
) -> dict[str, Any]:
    """Read viewports/cameras or update and verify the active viewport camera."""
    if action == "camera_view" and all(value is None for value in (position, target, camera_type)):
        return {
            "ok": False,
            "error_code": ErrorCode.INVALID_REQUEST,
            "error_message": "camera_view requires position, target, or camera_type",
        }
    if action == "camera_activate" and not camera_id:
        return {"ok": False, "error_code": ErrorCode.INVALID_REQUEST, "error_message": "camera_id is required"}
    for label, value in (("position", position), ("target", target)):
        if value is not None and len(value) != 3:
            return {
                "ok": False,
                "error_code": ErrorCode.INVALID_REQUEST,
                "error_message": label + " must contain exactly three values",
            }
    arguments = {
        key: value
        for key, value in {
            "position": position,
            "target": target,
            "camera_type": camera_type,
            "camera_id": camera_id,
        }.items()
        if value is not None
    }
    feature_id = action
    return (
        service()
        .execute(
            feature_id,
            f"render.{action}",
            arguments,
            scene_id=scene_id,
            expected_revision=expected_revision,
        )
        .model_dump(mode="json")
    )


@mcp.tool()
def render_object_create_prepare(
    kind: Literal["camera", "camera_with_aim", "point_light", "spot_light"], ttl: float = 300
) -> dict[str, Any]:
    """Snapshot and prepare creation of a Camera, aimed Camera rig, Point Light, or Spot Light."""
    mapping = {
        "camera": ("camera_create", "render.camera_create"),
        "camera_with_aim": ("camera_aim", "render.camera_aim"),
        "point_light": ("light_point", "render.light_point"),
        "spot_light": ("light_spot", "render.light_spot"),
    }
    feature_id, operation = mapping[kind]
    return service().prepare_change(feature_id, operation, {}, ttl)


@mcp.tool()
def render_output(
    action: Literal["viewport_capture", "image", "video"],
    path: str,
    width: int = 1920,
    height: int = 1080,
    samples: int = 64,
    scene_id: str | None = None,
    expected_revision: str | None = None,
) -> dict[str, Any]:
    """Render a still or video after change_prepare/change_commit validates the destination and snapshot."""
    if width < 16 or height < 16 or samples < 1:
        return {
            "ok": False,
            "error_code": ErrorCode.INVALID_REQUEST,
            "error_message": "width/height must be at least 16 and samples must be positive",
        }
    feature_id = "viewport_capture" if action == "viewport_capture" else f"render_{action}"
    return (
        service()
        .execute(
            feature_id,
            f"render.{action}",
            {"path": path, "width": width, "height": height, "samples": samples},
            scene_id=scene_id,
            expected_revision=expected_revision,
        )
        .model_dump(mode="json")
    )


@mcp.tool()
def auto_posing(
    action: Literal["add", "update"],
    scene_id: str | None = None,
    expected_revision: str | None = None,
) -> dict[str, Any]:
    """Add or update AutoPosing through Cascadeur's session API; use change_prepare/change_commit."""
    return (
        service()
        .execute(
            "auto_posing",
            "generation.auto_posing",
            {"action": action},
            scene_id=scene_id,
            expected_revision=expected_revision,
        )
        .model_dump(mode="json")
    )


@mcp.tool()
def generation_state() -> dict[str, Any]:
    """Inspect selected layers, interval, keys, rig support, and generation prerequisites."""
    return service().execute("generation_state", "generation.state", {}).model_dump(mode="json")


@mcp.tool()
def timeline_select_interval(
    first_frame: int,
    last_frame: int,
    layer_ids: list[str] | None = None,
    scene_id: str | None = None,
    expected_revision: str | None = None,
) -> dict[str, Any]:
    """Select an exact frame interval across explicit layers, or all layers when omitted."""
    return (
        service()
        .execute(
            "timeline_range",
            "timeline.range",
            {"first_frame": first_frame, "last_frame": last_frame, "layer_ids": layer_ids or []},
            scene_id=scene_id,
            expected_revision=expected_revision,
        )
        .model_dump(mode="json")
    )


@mcp.tool()
def root_motion_prepare(ttl: float = 300) -> dict[str, Any]:
    """Snapshot and prepare Root Motion generation for the selected timeline interval."""
    return service().prepare_change("root_motion", "generation.root_motion", {}, ttl)


@mcp.tool()
def inbetweening_prepare(ttl: float = 300) -> dict[str, Any]:
    """Snapshot and prepare Pro Inbetweening for the selected timeline interval."""
    return service().prepare_change("inbetweening", "generation.inbetweening", {}, ttl)


@mcp.tool()
def animation_unbaking_prepare(
    step: Literal[
        "prepare_keys_by_fulcrums", "adjust_keys_and_interpolation", "adjust_autoposing_lock_state"
    ] = "adjust_keys_and_interpolation",
    ttl: float = 300,
) -> dict[str, Any]:
    """Snapshot and prepare one documented Animation Unbaking stage."""
    return service().prepare_change("unbaking", "generation.unbaking", {"step": step}, ttl)


@mcp.tool()
def key_reduction_prepare(
    first_frame: int,
    last_frame: int,
    layer_ids: list[str],
    every_n: int = 2,
    preserve_endpoints: bool = True,
    fixed_interpolation: bool = False,
    ttl: float = 300,
) -> dict[str, Any]:
    """Snapshot and prepare deterministic key reduction without an input dialog."""
    return service().prepare_change(
        "key_reduction",
        "animation.key_reduce",
        {
            "first_frame": first_frame,
            "last_frame": last_frame,
            "layer_ids": layer_ids,
            "every_n": every_n,
            "preserve_endpoints": preserve_endpoints,
            "fixed_interpolation": fixed_interpolation,
        },
        ttl,
    )


@mcp.tool()
def mirror_prepare(
    ids: list[str],
    mode: Literal["frame", "interval"] = "frame",
    frame: int | None = None,
    first_frame: int | None = None,
    last_frame: int | None = None,
    layer_ids: list[str] | None = None,
    plane_normal: list[float] | None = None,
    plane_origin: list[float] | None = None,
    ttl: float = 300,
) -> dict[str, Any]:
    """Snapshot and prepare an exact frame or interval mirror for Box controllers."""
    if not ids:
        return {"ok": False, "error_code": ErrorCode.INVALID_REQUEST, "error_message": "ids is required"}
    if plane_normal is not None and len(plane_normal) != 3:
        return {
            "ok": False,
            "error_code": ErrorCode.INVALID_REQUEST,
            "error_message": "plane_normal must contain exactly three values",
        }
    if plane_origin is not None and len(plane_origin) != 3:
        return {
            "ok": False,
            "error_code": ErrorCode.INVALID_REQUEST,
            "error_message": "plane_origin must contain exactly three values",
        }
    if mode == "frame" and frame is None:
        return {"ok": False, "error_code": ErrorCode.INVALID_REQUEST, "error_message": "frame is required"}
    if mode == "interval" and (first_frame is None or last_frame is None):
        return {
            "ok": False,
            "error_code": ErrorCode.INVALID_REQUEST,
            "error_message": "first_frame and last_frame are required for interval mode",
        }
    arguments = {
        "ids": ids,
        "mode": mode,
        "plane_normal": plane_normal or [1.0, 0.0, 0.0],
        "plane_origin": plane_origin or [0.0, 0.0, 0.0],
        "layer_ids": layer_ids or [],
    }
    if frame is not None:
        arguments["frame"] = frame
    if first_frame is not None:
        arguments["first_frame"] = first_frame
    if last_frame is not None:
        arguments["last_frame"] = last_frame
    return service().prepare_change("mirror", "editing.mirror", arguments, ttl)


@mcp.tool()
def cycle_list(
    layer_ids: list[str] | None = None,
    first_frame: int = 0,
    last_frame: int | None = None,
) -> dict[str, Any]:
    """List normalized cycles for explicit layers and an optional frame interval."""
    arguments: dict[str, Any] = {
        "action": "list",
        "layer_ids": layer_ids or [],
        "first_frame": first_frame,
    }
    if last_frame is not None:
        arguments["last_frame"] = last_frame
    return service().execute("cycle_query", "animation.cycle_query", arguments).model_dump(mode="json")


@mcp.tool()
def auto_physics_state() -> dict[str, Any]:
    """Inspect Center of Mass, animation length, selection, and AutoPhysics prerequisites."""
    return service().execute("auto_physics_state", "physics.auto_state", {}).model_dump(mode="json")


@mcp.tool()
def physics_state() -> dict[str, Any]:
    """Inventory rigid bodies, masses, constraints, collisions, and physics behaviours."""
    return service().execute("physics_state", "physics.state", {}).model_dump(mode="json")


@mcp.tool()
def rig_state() -> dict[str, Any]:
    """Inventory RigInfo, joints, controllers, rigid bodies, IK, twist, and Quick Rig state."""
    return service().execute("rig_state", "rig.state", {}).model_dump(mode="json")


@mcp.tool()
def constraint_driver_catalog() -> dict[str, Any]:
    """List actual update-graph Triangle objects eligible to drive Point Constraints."""
    return service().execute("constraint_drivers", "rig.constraint_drivers", {}).model_dump(mode="json")


@mcp.tool()
def rigid_body_mass_prepare(
    total_mass: float,
    ids: list[str] | None = None,
    ttl: float = 300,
) -> dict[str, Any]:
    """Snapshot and prepare proportional rigid-body mass scaling to an exact positive total."""
    return service().prepare_change(
        "mass",
        "rig.mass_set",
        {"total_mass": total_mass, "ids": ids or []},
        ttl,
    )


@mcp.tool()
def joint_create_prepare(ttl: float = 300) -> dict[str, Any]:
    """Snapshot and prepare creation of one Joint using Cascadeur's bundled Add.Joint command."""
    return service().prepare_change("joint", "rig.joint_create", {}, ttl)


@mcp.tool()
def rig_info_create_prepare(
    joint_ids: list[str],
    name: str = "",
    ttl: float = 300,
) -> dict[str, Any]:
    """Snapshot and prepare one RigInfo linked to the exact unassigned Joint owners."""
    return service().prepare_change(
        "rig_info",
        "rig.rig_info_create",
        {"joint_ids": joint_ids, "name": name},
        ttl,
    )


@mcp.tool()
def ik_chain_create_prepare(ordered_ids: list[str], ttl: float = 300) -> dict[str, Any]:
    """Snapshot and prepare IK with explicit main end, middle links, and secondary end order."""
    return service().prepare_change(
        "ik",
        "rig.ik_chain_create",
        {"ordered_ids": ordered_ids},
        ttl,
    )


@mcp.tool()
def rig_elements_create_prepare(
    pairs: list[dict[str, Any]],
    options: dict[str, Any] | None = None,
    feature: Literal["manual_rig", "rig_create", "rigid_body"] = "manual_rig",
    ttl: float = 300,
) -> dict[str, Any]:
    """Prepare deterministic manual-rig elements from explicit Joint/direction-Joint pairs."""
    normalized_options = dict(options or {})
    if feature == "rigid_body" and normalized_options.get("only_box_controller") is True:
        return {
            "ok": False,
            "feature_id": feature,
            "error_code": ErrorCode.INVALID_REQUEST,
            "error_message": "rigid_body requires only_box_controller=false",
        }
    return service().prepare_change(
        feature,
        "rig.rig_elements_create",
        {"pairs": pairs, "options": normalized_options},
        ttl,
    )


@mcp.tool()
def additional_point_controller_prepare(rig_element_id: str, ttl: float = 300) -> dict[str, Any]:
    """Prepare one additional Point controller on an exact manual-rig element."""
    return service().prepare_change(
        "controller_point",
        "rig.additional_point_create",
        {"rig_element_id": rig_element_id},
        ttl,
    )


@mcp.tool()
def additional_box_controller_prepare(rig_element_id: str, ttl: float = 300) -> dict[str, Any]:
    """Prepare one additional Box controller on an exact manual-rig element."""
    return service().prepare_change(
        "controller_box",
        "rig.additional_box_create",
        {"rig_element_id": rig_element_id},
        ttl,
    )


@mcp.tool()
def spline_ik_create_prepare(
    start_joint_id: str,
    end_joint_id: str,
    name: str = "",
    ttl: float = 300,
) -> dict[str, Any]:
    """Prepare a Proto Spline IK for two endpoints on one explicitly resolved rig hierarchy."""
    return service().prepare_change(
        "spline_ik",
        "rig.spline_ik_create",
        {
            "start_joint_id": start_joint_id,
            "end_joint_id": end_joint_id,
            "name": name,
        },
        ttl,
    )


@mcp.tool()
def twist_prepare(
    action: Literal["set", "remove"],
    box_id: str,
    joint_id: str | None = None,
    ttl: float = 300,
) -> dict[str, Any]:
    """Snapshot and prepare Twist assignment or removal on an explicit ProtoBox."""
    if not box_id:
        return {
            "ok": False,
            "error_code": ErrorCode.INVALID_REQUEST,
            "error_message": "box_id is required",
        }
    if action == "set" and not joint_id:
        return {
            "ok": False,
            "error_code": ErrorCode.INVALID_REQUEST,
            "error_message": "joint_id is required for set",
        }
    return service().prepare_change(
        "twist",
        "rig.twist",
        {"action": action, "box_id": box_id, "joint_id": joint_id or ""},
        ttl,
    )


@mcp.tool()
def center_of_mass_prepare(
    mode: Literal["from_rigids", "composite", "connect_direction_controllers", "snap_mesh"],
    ids: list[str],
    ttl: float = 300,
) -> dict[str, Any]:
    """Snapshot and prepare an explicit Center of Mass construction or binding operation."""
    return service().prepare_change("center_of_mass", "physics.center_of_mass", {"mode": mode, "ids": ids}, ttl)


@mcp.tool()
def collision_create_prepare(
    shape: Literal["box", "capsule", "kinematic_mesh", "convex_decomposition", "convex_by_skinning"],
    ids: list[str],
    options: dict[str, Any] | None = None,
    ttl: float = 300,
) -> dict[str, Any]:
    """Snapshot and prepare collision generation with explicit targets and numeric options."""
    return service().prepare_change(
        "collision_create",
        "physics.collision_create",
        {"shape": shape, "ids": ids, **(options or {})},
        ttl,
    )


@mcp.tool()
def collision_delete_prepare(ids: list[str], ttl: float = 300) -> dict[str, Any]:
    """Snapshot and prepare removal of every supported collision behaviour from exact objects."""
    return service().prepare_change(
        "collision_delete",
        "physics.collision_delete",
        {"ids": ids},
        ttl,
    )


@mcp.tool()
def transform_constraint_prepare(
    driver_id: str,
    constrained_id: str,
    ttl: float = 300,
) -> dict[str, Any]:
    """Snapshot and prepare a transform constraint without an ambiguous parent-choice dialog."""
    return service().prepare_change(
        "constraint_transform",
        "physics.constraint_transform",
        {"driver_id": driver_id, "constrained_id": constrained_id},
        ttl,
    )


@mcp.tool()
def point_constraint_prepare(
    driver_id: str,
    point_ids: list[str],
    spherical_position: bool = False,
    ttl: float = 300,
) -> dict[str, Any]:
    """Snapshot and prepare point-controller constraints with an explicit driver."""
    return service().prepare_change(
        "constraint_point",
        "physics.constraint_point",
        {
            "driver_id": driver_id,
            "point_ids": point_ids,
            "spherical_position": spherical_position,
        },
        ttl,
    )


@mcp.tool()
def ballistic_create_prepare(
    center_of_mass_id: str,
    first_frame: int,
    last_frame: int,
    layer_ids: list[str] | None = None,
    ttl: float = 300,
) -> dict[str, Any]:
    """Snapshot and prepare a persisted Ballistic Trajectory for an exact CoM and interval."""
    return service().prepare_change(
        "ballistic",
        "physics.ballistic",
        {
            "center_of_mass_id": center_of_mass_id,
            "first_frame": first_frame,
            "last_frame": last_frame,
            "layer_ids": layer_ids or [],
        },
        ttl,
    )


@mcp.tool()
def auto_physics_enable(scene_id: str, expected_revision: str) -> dict[str, Any]:
    """Select the main Center of Mass and enable Physics Assistant before snapping."""
    return (
        service()
        .execute(
            "auto_physics_enable",
            "physics.auto_enable",
            {},
            scene_id=scene_id,
            expected_revision=expected_revision,
        )
        .model_dump(mode="json")
    )


@mcp.tool()
def auto_physics_snap(scene_id: str | None = None, expected_revision: str | None = None) -> dict[str, Any]:
    """Snap a working AutoPhysics simulation; run auto_physics_state and auto_physics_enable first."""
    return (
        service()
        .execute(
            "auto_physics",
            "physics.auto_snap",
            {},
            scene_id=scene_id,
            expected_revision=expected_revision,
        )
        .model_dump(mode="json")
    )


@mcp.tool()
def action_invoke(
    feature_id: str,
    action_id: str,
    expect_change: bool = True,
    postcondition: dict[str, Any] | None = None,
    scene_id: str | None = None,
    expected_revision: str | None = None,
    confirmation_token: str | None = None,
    timeout: float = 60,
) -> dict[str, Any]:
    """Invoke a known action and require an observable change or explicit postcondition."""
    try:
        allowed = service().action_allowed(feature_id, action_id)
    except KeyError:
        allowed = False
    if not allowed:
        return ResultEnvelope(
            ok=False,
            feature_id=feature_id,
            execution_mode=ExecutionMode.ACTION,
            error_code=ErrorCode.INVALID_REQUEST,
            error_message=(
                "action_id is not the exact installed Python command registered for feature_id; "
                "unmapped GUI actions must use a dedicated adapter or remain ui_only"
            ),
        ).model_dump(mode="json")
    if not expect_change and postcondition is None:
        return ResultEnvelope(
            ok=False,
            feature_id=feature_id,
            execution_mode=ExecutionMode.ACTION,
            error_code=ErrorCode.INVALID_REQUEST,
            error_message="expect_change=false requires an explicit postcondition",
        ).model_dump(mode="json")
    arguments = {"action_id": action_id, "expect_change": expect_change}
    if postcondition is not None:
        arguments["postcondition"] = postcondition
    return (
        service()
        .execute(
            feature_id,
            "system.action_invoke",
            arguments,
            scene_id=scene_id,
            expected_revision=expected_revision,
            timeout=timeout,
            confirmation_token=confirmation_token,
        )
        .model_dump(mode="json")
    )


@mcp.tool()
def tool_call(
    feature_id: str,
    tool_name: str,
    chain: list[dict[str, Any]],
    mutate: bool = False,
    scene_id: str | None = None,
    expected_revision: str | None = None,
    confirmation_token: str | None = None,
    timeout: float = 60,
) -> dict[str, Any]:
    """Call a runtime-registered Cascadeur tool through an explicit attribute/call chain."""
    return (
        service()
        .execute(
            feature_id,
            "system.tool_call",
            {
                "tool_name": tool_name,
                "chain": chain,
                "mutate": mutate,
            },
            scene_id=scene_id,
            expected_revision=expected_revision,
            timeout=timeout,
            confirmation_token=confirmation_token,
        )
        .model_dump(mode="json")
    )


@mcp.tool()
def csc_query(root: str, chain: list[dict[str, Any]], timeout: float = 30) -> dict[str, Any]:
    """Call an allowlisted read-only csc path with typed JSON arguments and safe serialization."""
    return (
        service()
        .execute("csc_query", "system.csc_query", {"root": root, "chain": chain}, timeout=timeout)
        .model_dump(mode="json")
    )


@mcp.tool()
def csc_mutate(
    root: str,
    chain: list[dict[str, Any]],
    scene_id: str,
    expected_revision: str,
    confirmation_token: str | None = None,
    timeout: float = 60,
) -> dict[str, Any]:
    """Call a mutation only when its final installed csc method is registered and revision matches."""
    if not service().csc_mutate_allowed(chain):
        return ResultEnvelope(
            ok=False,
            feature_id="csc_mutate",
            execution_mode=ExecutionMode.NATIVE,
            error_code=ErrorCode.INVALID_REQUEST,
            error_message="Final method is not in the installed mutation allowlist",
        ).model_dump(mode="json")
    return (
        service()
        .execute(
            "csc_mutate",
            "system.csc_mutate",
            {"root": root, "chain": chain},
            scene_id=scene_id,
            expected_revision=expected_revision,
            confirmation_token=confirmation_token,
            timeout=timeout,
        )
        .model_dump(mode="json")
    )


@mcp.tool()
def external_workflow(feature_id: str, configuration: dict[str, Any]) -> dict[str, Any]:
    """Describe or run a registered DCC/LiveLink workflow; returns an exact dependency gate when absent."""
    feature = service().feature(feature_id)
    if feature.state.value == "missing_dependency":
        return {
            "ok": False,
            "feature_id": feature_id,
            "execution_mode": feature.execution_mode,
            "error_code": ErrorCode.DEPENDENCY_MISSING,
            "dependency": feature.dependency,
            "preparation": [
                "Install and enable the named integration in the target application",
                "Open a compatible target project and verify its connection/listening state",
                "Refresh cascadeur://capabilities before retrying",
            ],
        }
    return service().execute(feature_id, "system.tool_call", configuration).model_dump(mode="json")


@mcp.tool()
def undo(expected_revision: str, scene_id: str | None = None, expect_change: bool = True) -> dict[str, Any]:
    """Undo and verify an observable scene revision change."""
    return (
        service()
        .execute(
            "undo",
            "system.undo",
            {"expect_change": expect_change},
            scene_id=scene_id,
            expected_revision=expected_revision,
        )
        .model_dump(mode="json")
    )


@mcp.tool()
def redo(expected_revision: str, scene_id: str | None = None, expect_change: bool = True) -> dict[str, Any]:
    """Redo and verify an observable scene revision change."""
    return (
        service()
        .execute(
            "redo",
            "system.redo",
            {"expect_change": expect_change},
            scene_id=scene_id,
            expected_revision=expected_revision,
        )
        .model_dump(mode="json")
    )


@mcp.tool()
def developer_execute_python(
    code: str, scene_id: str | None = None, expected_revision: str | None = None
) -> dict[str, Any]:
    """Execute restricted Python only when the local developer policy explicitly enables it."""
    if not service()._developer_policy():
        return {
            "ok": False,
            "feature_id": "developer_execute_python",
            "error_code": ErrorCode.LICENSE_GATED,
            "error_message": "Disabled by policy. Set developer_execute_python=true locally to opt in.",
        }
    return (
        service()
        .execute(
            "developer_execute_python",
            "system.developer_execute_python",
            {"code": code},
            scene_id=scene_id,
            expected_revision=expected_revision,
        )
        .model_dump(mode="json")
    )


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
