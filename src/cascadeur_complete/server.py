from __future__ import annotations

import json
import uuid
from functools import lru_cache
from typing import Any, Literal

from mcp.server import MCPServer

from .models import ErrorCode, ExecutionMode, ResultEnvelope
from .product_catalog import PRODUCT_CATALOG, SUPPORTED_BUILD
from .service import CascadeurService
from .ui_file_flow import dialog_flow_arguments, ui_file_flow_arguments

mcp = MCPServer(
    "cascadeur-complete",
    instructions=(
        f"Cascadeur {SUPPORTED_BUILD} automation only. Read capabilities first. Every scene or file change is "
        "prepared by a *_prepare tool (or change_prepare) and runs only through change_commit. "
        "Never assume a gated feature ran."
    ),
)


@lru_cache(maxsize=1)
def service() -> CascadeurService:
    return CascadeurService()


def _invalid(message: str) -> dict[str, Any]:
    return {"ok": False, "error_code": ErrorCode.INVALID_REQUEST, "error_message": message}


def _prepare(feature_id: str, operation: str, arguments: dict[str, Any], ttl_seconds: float) -> dict[str, Any]:
    """Snapshot the scene and mint a one-use token for exactly this operation; run it with change_commit."""
    try:
        return service().prepare_change(feature_id, operation, arguments, ttl_seconds)
    except (KeyError, ValueError) as exc:
        return _invalid(str(exc))


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
    try:
        record = service().jobs.get(job_id)
    except ValueError:
        record = None
    return _dump(record or {"ok": False, "error": "job not found", "job_id": job_id})


@mcp.resource("cascadeur://snapshots/{snapshot_id}")
def snapshot_resource(snapshot_id: str) -> str:
    """Snapshot metadata without exposing file contents."""
    try:
        canonical = str(uuid.UUID(snapshot_id))
    except ValueError:
        return _dump({"snapshot_id": snapshot_id, "exists": False, "error": "invalid snapshot id"})
    path = (service().paths.snapshots / f"{canonical}.casc").resolve()
    if path.parent != service().paths.snapshots.resolve():
        return _dump({"snapshot_id": snapshot_id, "exists": False, "error": "invalid snapshot id"})
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
    """Return bounded level-only diagnostics; pattern may be a log level, never arbitrary text."""
    return service().execute("logs", "system.logs", {"lines": lines, "pattern": pattern or ""}).model_dump(mode="json")


ViewMode = Literal["View", "AutoPosing", "PointController", "Controller", "Joint", "Mesh", "Rigging"]


@mcp.tool()
def viewport_mode(apply_to_all: bool = False) -> dict[str, Any]:
    """Read the active (or every) viewport visualizer mode; change it with viewport_mode_prepare."""
    return (
        service()
        .execute("view_mode", "system.view_mode_get", {"mode": None, "apply_to_all": apply_to_all})
        .model_dump(mode="json")
    )


@mcp.tool()
def viewport_mode_prepare(mode: ViewMode, apply_to_all: bool = False, ttl_seconds: float = 300) -> dict[str, Any]:
    """Prepare setting the active (or every) viewport visualizer mode; commit with change_commit."""
    return _prepare("view_mode", "system.view_mode_set", {"mode": mode, "apply_to_all": apply_to_all}, ttl_seconds)


@mcp.tool()
def feature_search(
    query: str = "",
    family: str | None = None,
    state: str | None = None,
    limit: int = 100,
    layer: Literal["product", "discovered", "all"] = "product",
) -> list[dict[str, Any]]:
    """Search product support by default, or explicitly query discovered inventory."""
    return service().feature_search(query, family, state, limit, layer)


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
    try:
        record = service().jobs.get(job_id)
    except ValueError:
        record = None
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
    except (KeyError, ValueError):
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
    action: Literal["get", "filter"],
    object_type: str | None = None,
    name_contains: str | None = None,
    selected_only: bool = True,
) -> dict[str, Any]:
    """Read or filter the current object selection; change it with selection_edit_prepare."""
    arguments: dict[str, Any] = {"ids": [], "selected_only": selected_only}
    if object_type is not None:
        arguments["type"] = object_type
    if name_contains is not None:
        arguments["name_contains"] = name_contains
    return service().execute(f"selection_{action}", f"selection.{action}", arguments).model_dump(mode="json")


@mcp.tool()
def selection_edit_prepare(
    action: Literal["set", "add", "remove"],
    ids: list[str],
    pivot_id: str | None = None,
    ttl_seconds: float = 300,
) -> dict[str, Any]:
    """Prepare replacing, extending, or reducing the object selection; commit with change_commit."""
    arguments: dict[str, Any] = {"ids": ids}
    if pivot_id is not None:
        arguments["pivot_id"] = pivot_id
    return _prepare(f"selection_{action}", f"selection.{action}", arguments, ttl_seconds)


@mcp.tool()
def object_delete_prepare(ids: list[str], ttl_seconds: float = 300) -> dict[str, Any]:
    """Snapshot and prepare deletion of exact objects (constraints are cleaned like the Delete command)."""
    if not ids:
        return {"ok": False, "error_code": ErrorCode.INVALID_REQUEST, "error_message": "ids cannot be empty"}
    return service().prepare_change("object_delete", "objects.delete", {"ids": ids}, ttl_seconds)


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
def object_write_prepare(
    action: Literal["rename", "create", "duplicate", "parent", "unparent", "delete"],
    ids: list[str] | None = None,
    object_id: str | None = None,
    name: str | None = None,
    parent_id: str | None = None,
    position: list[float] | None = None,
    size: float = 3.0,
    ttl_seconds: float = 300,
) -> dict[str, Any]:
    """Prepare an object rename, create, duplicate, reparent, unparent, or delete; commit with change_commit."""
    if action == "rename" and (not object_id or not name):
        return _invalid("id and name are required")
    if action in ("duplicate", "parent", "unparent", "delete") and not ids:
        return _invalid("ids are required")
    if action == "create" and position is not None and len(position) != 3:
        return _invalid("position must contain exactly three values")
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
    operation = {"delete": "objects.delete", "duplicate": "objects.duplicate"}.get(action, f"object.{action}")
    return _prepare(feature_id, operation, arguments, ttl_seconds)


@mcp.tool()
def operation_batch(
    feature_id: str,
    operations: list[dict[str, Any]],
    scene_id: str | None = None,
    expected_revision: str | None = None,
    timeout: float = 60,
) -> dict[str, Any]:
    """Execute multiple read-only bridge operations in one Cascadeur UI-thread entry."""
    return (
        service()
        .batch(
            feature_id,
            operations,
            scene_id=scene_id,
            expected_revision=expected_revision,
            timeout=timeout,
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
def feature_prepare(
    feature_id: str, arguments: dict[str, Any] | None = None, ttl_seconds: float = 300
) -> dict[str, Any]:
    """Snapshot and prepare any adapter-bound feature by id; see feature_describe for its arguments."""
    svc = service()
    try:
        feature = svc.feature(feature_id)
    except KeyError:
        return {"ok": False, "error_code": ErrorCode.INVALID_REQUEST, "error_message": "Unknown feature id"}
    if not feature.adapter_id:
        return {
            "ok": False,
            "feature_id": feature_id,
            "error_code": ErrorCode.INVALID_REQUEST,
            "error_message": f"{feature_id} has no dedicated adapter (state: {feature.state.value})",
        }
    return svc.prepare_change(feature_id, feature.route, dict(arguments or {}), ttl_seconds)


@mcp.tool()
def feature_read(feature_id: str, arguments: dict[str, Any] | None = None, timeout: float = 60) -> dict[str, Any]:
    """Run a read-only adapter-bound feature by id (mutating features must use feature_prepare)."""
    svc = service()
    try:
        feature = svc.feature(feature_id)
    except KeyError:
        return {"ok": False, "error_code": ErrorCode.INVALID_REQUEST, "error_message": "Unknown feature id"}
    return svc.execute(feature_id, feature.route, dict(arguments or {}), timeout=timeout).model_dump(mode="json")


@mcp.tool()
def change_commit(confirmation_token: str, timeout: float = 120) -> dict[str, Any]:
    """Commit exactly the prepared operation if scene revision and selection still match."""
    return service().commit_change(confirmation_token, timeout).model_dump(mode="json")


@mcp.tool()
def change_cancel(confirmation_token: str) -> dict[str, Any]:
    """Cancel an unused confirmation token without touching the scene."""
    return {"ok": service().changes.cancel(confirmation_token)}


@mcp.tool()
def change_rollback_prepare(snapshot_id: str, ttl_seconds: float = 300) -> dict[str, Any]:
    """Bind a snapshot rollback to the current scene/revision/selection and return a one-use token."""
    return service().prepare_rollback(snapshot_id, ttl_seconds)


@mcp.tool()
def change_rollback(confirmation_token: str, timeout: float = 120) -> dict[str, Any]:
    """Execute exactly the prepared snapshot rollback once."""
    return service().rollback(confirmation_token, timeout).model_dump(mode="json")


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
    try:
        feature_id, arguments = ui_file_flow_arguments(direction, format, path, preset, allow_overwrite)
    except ValueError as exc:
        return {"ok": False, "error_code": ErrorCode.INVALID_REQUEST, "error_message": str(exc)}
    return service().prepare_change(feature_id, "system.ui_file_flow", arguments, ttl_seconds)


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
def file_dialog_prepare(
    feature_id: Literal[
        "save_as_without_assets",
        "import_scene_to_current",
        "selection_groups_export",
        "scene_parts_export",
        "scene_parts_import",
        "import_image",
        "import_video",
        "export_video",
        "render_video",
    ],
    path: str,
    allow_overwrite: bool = False,
    ttl_seconds: float = 300,
    width: int = 320,
    height: int = 180,
    quality: Literal["LOW", "MEDIUM", "HIGH"] = "LOW",
) -> dict[str, Any]:
    """Prepare a registered Cascadeur file dialog flow (exact action and owned dialog); commit with change_commit.

    export_video/render_video fill Cascadeur's Export video window: ``path`` is the output folder plus
    file name without extension, and width/height/quality set the render.
    """
    try:
        arguments = dialog_flow_arguments(feature_id, path, allow_overwrite)
    except ValueError as exc:
        return {"ok": False, "error_code": ErrorCode.INVALID_REQUEST, "error_message": str(exc)}
    if arguments.get("form") == "export_video":
        arguments.update({"width": int(width), "height": int(height), "quality": quality})
    return service().prepare_change(feature_id, "system.ui_file_flow", arguments, ttl_seconds)


@mcp.tool()
def scene_file(action: Literal["list", "validate"]) -> dict[str, Any]:
    """List open scene tabs or validate the current scene; change scenes with scene_file_prepare."""
    return service().execute(f"scene_{action}", f"scene.{action}", {}).model_dump(mode="json")


@mcp.tool()
def scene_file_prepare(
    action: Literal["activate", "new", "open", "save", "save_as", "close"],
    path: str | None = None,
    tab_id: str | None = None,
    ttl_seconds: float = 300,
) -> dict[str, Any]:
    """Prepare activating, creating, opening, saving, or closing a CASC scene; commit with change_commit."""
    arguments: dict[str, Any] = {}
    if path:
        arguments["path"] = path
    if tab_id:
        arguments["tab_id"] = tab_id
    return _prepare(f"scene_{action}", f"scene.{action}", arguments, ttl_seconds)


@mcp.tool()
def io_transfer_prepare(
    feature_id: Literal[
        "import_fbx",
        "export_fbx",
        "blender_export",
        "import_dae",
        "export_dae",
        "import_audio",
        "export_image",
        "selection_groups_import",
    ],
    path: str,
    options: dict[str, Any] | None = None,
    ttl_seconds: float = 300,
) -> dict[str, Any]:
    """Prepare a native import/export with path validation; commit with change_commit.

    USD/GLB/GLTF/VRM use scene_exchange_prepare; image/video import, video export and
    the other dialog-driven transfers use file_dialog_prepare.
    """
    operation = PRODUCT_CATALOG.by_id[feature_id].operation or ""
    return _prepare(feature_id, operation, {"path": path, **(options or {})}, ttl_seconds)


@mcp.tool()
def timeline_set_frame_prepare(frame: int, ttl_seconds: float = 300) -> dict[str, Any]:
    """Prepare moving the playhead (verified with the domain scene getter); commit with change_commit."""
    return _prepare("timeline_set_frame", "timeline.set_frame", {"frame": frame}, ttl_seconds)


@mcp.tool()
def timeline_get() -> dict[str, Any]:
    """Read unclamped playhead, total layer frame count, and animation boundary."""
    return service().execute("timeline_get", "timeline.get").model_dump(mode="json")


@mcp.tool()
def transform_edit(
    action: Literal["get"] = "get",
    ids: list[str] | None = None,
    frame: int | None = None,
    space: Literal["local", "global"] = "local",
    refresh: bool = False,
) -> dict[str, Any]:
    """Read position, Euler rotation (radians), and local scale for explicit or selected objects.

    Cascadeur re-interpolates only up to the playhead after an edit; reads past it
    carry a warning. Pass refresh=true to recompute the whole timeline first.
    Write transforms with transform_edit_prepare.
    """
    arguments: dict[str, Any] = {"ids": ids or [], "space": space}
    if refresh:
        arguments["refresh"] = True
    if frame is not None:
        arguments["frame"] = frame
    return service().execute("transform_get", "animation.transform_get", arguments).model_dump(mode="json")


@mcp.tool()
def transform_edit_prepare(
    ids: list[str] | None = None,
    frame: int | None = None,
    space: Literal["local", "global"] = "local",
    position: list[float] | None = None,
    rotation_euler_xyz_radians: list[float] | None = None,
    scale: list[float] | None = None,
    ttl_seconds: float = 300,
) -> dict[str, Any]:
    """Prepare writing position, Euler rotation (radians), and local scale; commit with change_commit."""
    if all(value is None for value in (position, rotation_euler_xyz_radians, scale)):
        return _invalid("set requires at least one transform component")
    arguments: dict[str, Any] = {"ids": ids or [], "space": space}
    if frame is not None:
        arguments["frame"] = frame
    if position is not None:
        arguments["position"] = position
    if rotation_euler_xyz_radians is not None:
        arguments["rotation_euler_xyz_radians"] = rotation_euler_xyz_radians
    if scale is not None:
        arguments["scale"] = scale
    return _prepare("transform_set", "animation.transform_set", arguments, ttl_seconds)


@mcp.tool()
def layer_list() -> dict[str, Any]:
    """Read every animation layer with ID, name, parent, visibility, lock and keys."""
    return service().execute("layer_list", "layer.list").model_dump(mode="json")


@mcp.tool()
def layer_write_prepare(
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
    ttl_seconds: float = 300,
) -> dict[str, Any]:
    """Prepare a layer create/delete, visibility/lock/activate change, or folder edit; commit with change_commit."""
    if action == "create" and not name:
        return _invalid("name is required")
    if action in ("delete", "visibility", "lock", "activate") and not layer_id:
        return _invalid("layer_id is required")
    if action in ("visibility", "lock") and value is None:
        return _invalid("value is required")
    if action in ("folder_move", "folder_rename") and not item_id:
        return _invalid("item_id is required")
    if action in ("folder_create", "folder_rename") and not name:
        return _invalid("name is required")
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
    if action.startswith("folder_"):
        arguments["action"] = action.removeprefix("folder_")
    operation = "layer.folder" if action.startswith("folder_") else f"layer.{action}"
    return _prepare(feature_id, operation, arguments, ttl_seconds)


@mcp.tool()
def key_edit(action: Literal["list"] = "list", layer_id: str | None = None) -> dict[str, Any]:
    """List layer keys; add or delete keys with key_edit_prepare."""
    arguments: dict[str, Any] = {}
    if layer_id is not None:
        arguments["layer_id"] = layer_id
    return service().execute("key_list", "animation.key_list", arguments).model_dump(mode="json")


@mcp.tool()
def key_edit_prepare(
    action: Literal["add", "delete"], layer_id: str, frame: int, ttl_seconds: float = 300
) -> dict[str, Any]:
    """Prepare adding or deleting a key on one layer and frame; commit with change_commit."""
    return _prepare(f"key_{action}", f"animation.key_{action}", {"layer_id": layer_id, "frame": frame}, ttl_seconds)


@mcp.tool()
def animation_curve(
    action: Literal["query"] = "query",
    layer_id: str | None = None,
    layer_ids: list[str] | None = None,
    first_frame: int | None = None,
    last_frame: int | None = None,
) -> dict[str, Any]:
    """Query layer sections; set interpolation or tangent modes with animation_curve_prepare."""
    arguments: dict[str, Any] = {"layer_ids": layer_ids or ([layer_id] if layer_id else [])}
    if first_frame is not None:
        arguments["first_frame"] = first_frame
    if last_frame is not None:
        arguments["last_frame"] = last_frame
    return service().execute("graph_query", "animation.graph_query", arguments).model_dump(mode="json")


@mcp.tool()
def animation_curve_prepare(
    action: Literal["set_interpolation", "set_tangent"],
    layer_id: str,
    frame: int,
    value: str,
    ttl_seconds: float = 300,
) -> dict[str, Any]:
    """Prepare setting the interpolation or tangent mode of one key; commit with change_commit."""
    kind = "interpolation" if action == "set_interpolation" else "tangent"
    feature_id = f"{kind}_set"
    arguments = {"layer_id": layer_id, "frame": frame, "value": value, "operation": kind}
    return _prepare(feature_id, f"animation.{feature_id}", arguments, ttl_seconds)


@mcp.tool()
def viewport_camera(action: Literal["viewport_state", "camera_catalog"]) -> dict[str, Any]:
    """Read viewports or cameras; move or switch the viewport camera with viewport_camera_prepare."""
    return service().execute(action, f"render.{action}", {}).model_dump(mode="json")


@mcp.tool()
def viewport_camera_prepare(
    action: Literal["camera_view", "camera_activate"],
    position: list[float] | None = None,
    target: list[float] | None = None,
    camera_type: Literal["PERSPECTIVE", "ISOMETRIC"] | None = None,
    camera_id: str | None = None,
    ttl_seconds: float = 300,
) -> dict[str, Any]:
    """Prepare updating the active viewport camera or activating a camera; commit with change_commit."""
    if action == "camera_view" and all(value is None for value in (position, target, camera_type)):
        return _invalid("camera_view requires position, target, or camera_type")
    if action == "camera_activate" and not camera_id:
        return _invalid("camera_id is required")
    for label, value in (("position", position), ("target", target)):
        if value is not None and len(value) != 3:
            return _invalid(label + " must contain exactly three values")
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
    return _prepare(action, f"render.{action}", arguments, ttl_seconds)


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
def render_output_prepare(
    action: Literal["viewport_capture", "image"],
    path: str,
    width: int = 1920,
    height: int = 1080,
    samples: int = 64,
    ttl_seconds: float = 300,
) -> dict[str, Any]:
    """Prepare a viewport capture or still render to a validated path; commit with change_commit.

    Video renders fill Cascadeur's Export video window: use file_dialog_prepare(feature_id="render_video").
    """
    if width < 16 or height < 16 or samples < 1:
        return _invalid("width/height must be at least 16 and samples must be positive")
    feature_id = "viewport_capture" if action == "viewport_capture" else "render_image"
    arguments = {"path": path, "width": width, "height": height, "samples": samples}
    return _prepare(feature_id, f"render.{action}", arguments, ttl_seconds)


@mcp.tool()
def auto_posing_prepare(action: Literal["add", "update"], ttl_seconds: float = 300) -> dict[str, Any]:
    """Prepare adding or updating AutoPosing through Cascadeur's session API; commit with change_commit."""
    return _prepare("auto_posing", "generation.auto_posing", {"action": action}, ttl_seconds)


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
def auto_physics_enable_prepare(ttl_seconds: float = 300) -> dict[str, Any]:
    """Prepare selecting the main Center of Mass and enabling Physics Assistant; commit with change_commit."""
    return _prepare("auto_physics_enable", "physics.auto_enable", {}, ttl_seconds)


@mcp.tool()
def auto_physics_snap_prepare(ttl_seconds: float = 300) -> dict[str, Any]:
    """Prepare snapping a working AutoPhysics simulation (enable it first); commit with change_commit."""
    return _prepare("auto_physics", "physics.auto_snap", {}, ttl_seconds)


@mcp.tool()
def action_invoke_prepare(
    feature_id: str,
    action_id: str,
    expect_change: bool = True,
    postcondition: dict[str, Any] | None = None,
    ttl_seconds: float = 300,
) -> dict[str, Any]:
    """Prepare a known action that must change the scene or meet a postcondition; commit with change_commit."""
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
    arguments: dict[str, Any] = {"action_id": action_id, "expect_change": expect_change}
    if postcondition is not None:
        arguments["postcondition"] = postcondition
    return _prepare(feature_id, "system.action_invoke", arguments, ttl_seconds)


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
    return {
        "ok": False,
        "feature_id": feature_id,
        "execution_mode": feature.execution_mode,
        "error_code": ErrorCode.INVALID_REQUEST,
        "error_message": "No dedicated postcondition-safe external adapter is released for this feature",
        "configuration_received": bool(configuration),
    }


@mcp.tool()
def undo_prepare(expect_change: bool = True, ttl_seconds: float = 300) -> dict[str, Any]:
    """Prepare an undo that must change the scene revision; commit with change_commit."""
    return _prepare("undo", "system.undo", {"expect_change": expect_change}, ttl_seconds)


@mcp.tool()
def redo_prepare(expect_change: bool = True, ttl_seconds: float = 300) -> dict[str, Any]:
    """Prepare a redo that must change the scene revision; commit with change_commit."""
    return _prepare("redo", "system.redo", {"expect_change": expect_change}, ttl_seconds)


def _cleanup_error(exc: Exception) -> dict[str, Any]:
    from .cleanup_workflow import CleanupError

    code = ErrorCode.INVALID_REQUEST if isinstance(exc, CleanupError) else ErrorCode.DEPENDENCY_MISSING
    return {"ok": False, "error_code": code, "error_message": str(exc)}


def _segments(segments: list[list[int]] | None) -> list[tuple[int, int]] | None:
    return [(int(item[0]), int(item[1])) for item in segments] if segments else None


@mcp.tool()
def motion_cleanup_analyze(
    checks: list[Literal["feet", "fingers", "arms", "hands"]] | None = None,
    object_ids: list[str] | None = None,
    segments: list[list[int]] | None = None,
    spike_deg: float = 10.0,
    every_frame: bool = False,
) -> dict[str, Any]:
    """Measure a mocap clip over every frame: foot skating (cm/frame), slides, drags, finger spread/spikes/gaps.

    Read-only. Samples the active scene's Quick Rigging Tool character (pass
    object_ids to restrict to one character). segments are [first, last]
    frame pairs to report separately. Takes ~1-2 minutes for 1000 frames.
    checks defaults to feet and fingers; "arms" (opt-in, a few minutes)
    measures on the skinned mesh where each arm is inside the rest of the
    body, at the arm keys or with every_frame=true on all frames; "hands"
    (opt-in) reports wrist bend ranges and how closed the hands are.
    """
    from .cleanup_workflow import CleanupWorkflow

    wanted = checks or ["feet", "fingers"]
    try:
        workflow = CleanupWorkflow(service())
        result: dict[str, Any] = {"ok": True}
        if "feet" in wanted:
            result["feet"] = workflow.analyze_feet(object_ids, _segments(segments))
        if "fingers" in wanted:
            result["fingers"] = workflow.analyze_fingers(object_ids, spike_deg)
        if "hands" in wanted:
            result["hands"] = workflow.analyze_hands(object_ids)
        if "arms" in wanted:
            result["arms"] = workflow.analyze_arms(object_ids, every_frame=every_frame)
        result["scene_id"] = workflow.scene_id
        return result
    except (RuntimeError, ImportError) as exc:
        return _cleanup_error(exc)


@mcp.tool()
def motion_cleanup_prepare(
    kind: Literal[
        "foot_contacts",
        "fingers",
        "finger_fan",
        "arm_clearance",
        "wrist_soften",
        "hand_pose",
        "hand_rest",
        "wrist_accent",
    ],
    object_ids: list[str] | None = None,
    steps: bool = True,
    max_foot_offset_cm: float = 10.0,
    body_smoothness: float = 2.0,
    joints: list[str] | None = None,
    spike_deg: float = 10.0,
    index_gap_deg: float = 3.0,
    arm_allow_cm: float = 0.3,
    arm_margin_cm: float = 0.2,
    wrist_flex_limit_deg: float = 40.0,
    wrist_deviation_limit_deg: float = 22.0,
    hand_contrast: float = 2.2,
    hand_fixed_closure: float | None = None,
    wrap_thumb: bool = True,
    side: Literal["Left", "Right"] | None = None,
    pulses: list[list[int]] | None = None,
    accent_deg: float = 55.0,
    segments: list[list[int]] | None = None,
    ttl: float = 900,
) -> dict[str, Any]:
    """Snapshot and prepare a whole-clip cleanup as one protected key write; commit with change_commit.

    foot_contacts: one global solve over every frame for a whole-body offset
    and per-foot offsets that stop planted feet sliding, keeping legs within
    their original reach; with steps=true, remaining one-foot drags become
    short steps. fingers: soft-limit knuckle spread/twist and remove spikes,
    keeping curl (switch AutoPosing off for the finger controllers first).
    finger_fan: rotate each index knuckle about the palm normal so the
    index-middle gap settles near index_gap_deg (removes a claw-like splay
    that spread limits around the clip's own median pose cannot see).
    arm_clearance: one solve for elbow and wrist offsets that lift each arm
    out of the rest of the body, measured on the skinned mesh at every frame
    (overlap up to arm_allow_cm is treated as soft contact; bone lengths
    kept; takes several minutes).
    wrist_soften: smooths both wrists and squeezes flexion/extension and
    sideways bends under soft limits by turning the hand about the wrist.
    hand_pose: replaces noisy mocap fingers with coordinated poses between
    a relaxed open hand and a loose fist, timed by the mocap's own open/close
    (hand_contrast pushes half-closed hands toward one or the other); the
    thumb wraps over the fingers in a fist; hand_fixed_closure (0 open .. 1
    fist) holds one shape for the whole clip. Styling, not cleanup: use for
    dance or other clips where hand shape matters more than finger fidelity.
    hand_rest: a hand that holds still within ~14 cm of the waist, hips or thighs
    (a hand on the hip captured through a bulky glove) is moved into contact
    for that span; the elbow is re-solved to keep both bone lengths.
    wrist_accent: adds wrist flexion flicks (a "knock") of accent_deg to one
    hand (side) at the given pulses ([first, last] frames each): fast down,
    hold, softer return. For choreography a glove hid from the capture; time
    the pulses from the reference. The hand's layer needs a key on every
    frame the flicks cover (bake that span first).
    Writes only existing keys. The result carries predicted before/after
    metrics under "cleanup". Commit with a long timeout (e.g. 900 s).
    """
    from .cleanup_workflow import CleanupWorkflow
    from .motion_cleanup import ContactParams

    try:
        workflow = CleanupWorkflow(service())
        if kind == "foot_contacts":
            params = ContactParams(max_foot_offset=max_foot_offset_cm, body_smoothness=body_smoothness)
            return workflow.prepare_feet(object_ids, params, steps, _segments(segments), ttl)
        if kind == "arm_clearance":
            from .motion_cleanup import ArmParams

            return workflow.prepare_arm_clearance(object_ids, ArmParams(allow=arm_allow_cm, margin=arm_margin_cm), ttl)
        if kind == "wrist_accent":
            if side is None or not pulses:
                return {
                    "ok": False,
                    "error_code": ErrorCode.INVALID_REQUEST,
                    "error_message": "wrist_accent requires side and pulses ([first, last] frame pairs)",
                }
            return workflow.prepare_wrist_accent(side, pulses, accent_deg, object_ids, ttl)
        if kind == "hand_rest":
            return workflow.prepare_hand_rest(object_ids, ttl=ttl)
        if kind == "wrist_soften":
            from .motion_cleanup import WristParams

            limits = WristParams(flex_limit=wrist_flex_limit_deg, deviation_limit=wrist_deviation_limit_deg)
            return workflow.prepare_wrists(object_ids, limits, ttl)
        if kind == "hand_pose":
            from .motion_cleanup import HandPoseParams

            return workflow.prepare_hand_pose(
                object_ids,
                HandPoseParams(contrast=hand_contrast, wrap_thumb=wrap_thumb, fixed_closure=hand_fixed_closure),
                ttl,
            )
        if kind == "finger_fan":
            return workflow.prepare_finger_fan(object_ids, index_gap_deg, ttl=ttl)
        return workflow.prepare_fingers(object_ids, joints, spike_deg, ttl)
    except (RuntimeError, ImportError) as exc:
        return _cleanup_error(exc)


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
