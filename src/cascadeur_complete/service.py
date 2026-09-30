from __future__ import annotations

import json
import math
import os
import re
import time
import uuid
from glob import escape as glob_escape
from pathlib import Path
from threading import Thread
from typing import Any

from .atomic_queue import atomic_write_json
from .bridge_client import BridgeClient
from .build_profile import DEVELOPER_BUILD
from .discovery import BASELINE_TOOLS, discover_commands, discover_installation, load_csc_schema
from .external import available_dependencies, verify_blender_fbx
from .feature_registry import build_registry, registry_json
from .jobs import JobStore
from .models import (
    PROTOCOL_VERSION,
    CapabilityState,
    ErrorCode,
    Evidence,
    ExecutionMode,
    FeatureRecord,
    Operation,
    ResultEnvelope,
    SafetyContext,
)
from .paths import RuntimePaths
from .product_catalog import PRODUCT_CATALOG
from .safety import ChangeManager, SafetyError, validate_local_input_path, validate_local_path
from .uia import (
    UIAutomationError,
    active_scene_title,
    cancel_file_flow,
    cancel_owned_file_dialogs,
    capture_window_sample,
    complete_export_video_form,
    complete_file_dialog,
    cycle_scene_tab,
    finish_export_video_form,
    resolve_autophysics_snap_warning,
    resolve_optional_rig_mode_helper,
    sample_difference,
)
from .verification import LiveEvidenceStore

# View toggles only change what Cascadeur draws; the host proves the effect by
# comparing captures of the Cascadeur window before and after the action.
# Writes whose values Cascadeur may re-solve after the transaction (AutoPosing,
# rig updates). The bridge verifies them inside its own request; the host
# re-reads a sample in a separate request so an override is not reported as
# success.
SETTLED_ROTATION_OPERATIONS = frozenset({"animation.rotation_keys_set", "animation.transform_set"})
SETTLED_SAMPLE_LIMIT = 64
SETTLED_TOLERANCE_DEGREES = 0.05


def euler_xyz_to_quaternion(euler: list[float]) -> list[float]:
    """Cascadeur's rotation_euler_xyz_radians (extrinsic x, y, z) as wxyz."""
    half = [value / 2.0 for value in euler]
    cx, cy, cz = (math.cos(value) for value in half)
    sx, sy, sz = (math.sin(value) for value in half)
    return [
        cx * cy * cz + sx * sy * sz,
        sx * cy * cz - cx * sy * sz,
        cx * sy * cz + sx * cy * sz,
        cx * cy * sz - sx * sy * cz,
    ]


def quaternion_angle_degrees(first: list[float], second: list[float]) -> float:
    dot = min(1.0, abs(sum(a * b for a, b in zip(first, second, strict=True))))
    return math.degrees(2.0 * math.acos(dot))


def settled_rotation_samples(operation_name: str, arguments: dict[str, Any], frame: int | None) -> list[tuple]:
    """(object id, frame, expected wxyz) pairs to re-read after a rotation write."""
    if operation_name == "animation.rotation_keys_set":
        writes = list(arguments.get("writes") or [])
        step = max(1, len(writes) // SETTLED_SAMPLE_LIMIT)
        return [
            (str(item["id"]), int(item["frame"]), euler_xyz_to_quaternion(item["rotation_euler_xyz_radians"]))
            for item in writes[::step][:SETTLED_SAMPLE_LIMIT]
        ]
    euler = arguments.get("rotation_euler_xyz_radians")
    ids = [str(item) for item in arguments.get("ids") or []]
    if euler is None or not ids or frame is None:
        return []
    expected = euler_xyz_to_quaternion([float(value) for value in euler])
    return [(object_id, int(arguments.get("frame", frame)), expected) for object_id in ids[:SETTLED_SAMPLE_LIMIT]]


VIEW_OPERATIONS = frozenset(
    {
        "view.silhouette",
        "view.isometric_grid",
        "view.composition",
        "view.trajectory",
        "view.trajectory_translate",
        "view.trajectory_rotate",
        "view.trajectory_direction",
        "view.trajectory_edit",
        "view.ballistic_ghosts",
        "view.fingers_drawing",
        "physics.autophysics_freeze",
        "view.ghost",
        "view.node_editor",
        "view.control_picker",
    }
)
VIEW_CHANGE_FRACTION = 0.002

# Operations whose success is a new or replaced file at arguments["path"].
OUTPUT_OPERATIONS = frozenset(
    {
        "render.viewport_capture",
        "render.image",
        "render.video",
        "io.export_image",
        "io.export_video",
        "io.export_fbx",
        "io.export_dae",
        "scene.save_as",
    }
)

# Postconditions verified by the host itself (file system, native windows,
# UI Automation or the persisted registry) after the bridge response.
HOST_POSTCONDITIONS = {
    **{operation: ("output_file", "nonzero_bytes") for operation in OUTPUT_OPERATIONS},
    "scene.open": ("stable_scene_path",),
    "scene.open_autosave": ("stable_scene_path",),
    "scene.activate": ("stable_scene_path",),
    "scene.new": ("stable_scene_path",),
    "safety.rollback": ("stable_scene_path",),
    "system.ui_file_flow": (
        "exact_file_dialog",
        "exact_options_window",
        "registered_uia_flow_token",
        "scene_revision_changed",
        "output_file",
        "nonzero_bytes",
    ),
    "system.action_invoke": ("registered_action_binding",),
    "physics.auto_snap": ("scene_revision_changed",),
    "system.introspect": ("feature_registry",),
    "io.export_fbx": ("output_file", "nonzero_bytes", "target_import_verified"),
    "timeline.playback": ("playback_frames_advance", "playback_frame_stable"),
    **{operation: ("viewport_render_changed",) for operation in VIEW_OPERATIONS},
}

# Operations that only move the playhead (part of the revision) and edit no data.
PLAYHEAD_ONLY_OPERATIONS = frozenset({"timeline.playback"})

# Operations whose "path" argument names an existing file to read, not an output.
INPUT_PATH_OPERATIONS = frozenset(
    {
        "scene.open",
        "scene.open_autosave",
        "io.selection_groups_import",
        "rig.json_import",
        "rig.quick_rig",
    }
)

MUTATION_VERBS = (
    "add",
    "apply",
    "bake",
    "bind",
    "change",
    "clear",
    "close",
    "copy",
    "create",
    "delete",
    "erase",
    "export",
    "generate",
    "hide",
    "import",
    "load",
    "modify",
    "move",
    "open",
    "remove",
    "reset",
    "run",
    "save",
    "select",
    "set",
    "switch",
    "unbind",
    "unset",
    "update",
)


def ui_file_flow_arguments(
    direction: str, format: str, path: str, preset: str = "scene", allow_overwrite: bool = False
) -> tuple[str, dict[str, Any]]:
    """Return the feature id and exact action/dialog contract for a UI file flow on the pinned build."""
    if direction not in ("import", "export"):
        raise ValueError("direction must be import or export")
    if format not in ("usd", "glb", "gltf", "vrm"):
        raise ValueError("format must be usd, glb, gltf, or vrm")
    suffix = "." + format
    if not path.casefold().endswith(suffix):
        raise ValueError(f"{format} path must end with {suffix}")
    if format == "vrm" and direction == "export":
        raise ValueError("Cascadeur 2026.1 exposes VRM import but no VRM export action")
    if format == "usd":
        allowed = {"import": {"animation", "model", "scene"}, "export": {"model", "scene"}}[direction]
        if preset not in allowed:
            raise ValueError(f"USD {direction} supports presets: {', '.join(sorted(allowed))}")
        action_id = f"File.{direction.title()}.{preset.title()}.Usd..."
        dialog_title = f"{direction.title()}. preset: {preset}"
        options_title = None
        options_accept_title = None
        file_type_extension = None
    else:
        action_id = "File.Import.Glb" if direction == "import" else "File.Export.Glb"
        dialog_title = f"{direction.title()}. preset: default"
        options_title = "Glb/Gltf/Vrm(a) Import" if direction == "import" else "Glb/Gltf Export"
        options_accept_title = direction.title()
        file_type_extension = None if format == "glb" else suffix
    return f"{direction}_{format}", {
        "action_id": action_id,
        "path": path,
        "dialog_title": dialog_title,
        "options_title": options_title,
        "options_accept_title": options_accept_title,
        "options_accept_index": 0,
        "after_accept_title": None,
        "form": None,
        "file_type_extension": file_type_extension,
        "input": direction == "import",
        "output": direction == "export",
        "allow_overwrite": allow_overwrite,
    }


# Dialog-driven Cascadeur 2026.1 file flows beyond USD/GLB/GLTF/VRM. Each
# feature is bound to one exact action id and owned dialog title; the host only
# fills that dialog and verifies a file or scene postcondition afterwards.
UI_FILE_FLOWS: dict[str, dict[str, Any]] = {
    "save_as_without_assets": {
        "action_id": "File.Save as (no assets)",
        "dialog_title": "Save Scene *",
        "extension": ".casc",
        "direction": "export",
    },
    "import_scene_to_current": {
        "action_id": "File.Import.Scene to current...",
        "dialog_title": "Import scene",
        "extension": ".casc",
        "direction": "import",
    },
    "selection_groups_export": {
        "action_id": "File.Export.Selection groups...",
        "dialog_title": "Export selection groups",
        "extension": ".json",
        "direction": "export",
    },
    "scene_parts_export": {
        "action_id": "File.Export.PartsCasc",
        "dialog_title": "Export to parts file: *",
        "extension": ".partscasc",
        "direction": "export",
    },
    "scene_parts_import": {
        "action_id": "File.Import.PartsCasc",
        "dialog_title": "Import parts file",
        "extension": ".partscasc",
        "direction": "import",
    },
    # File > Export > Video opens Cascadeur's own "Export video" form; "path"
    # is the output folder plus file name without extension (the host waits for
    # the rendered file of that name). render_video is the same product route.
    "export_video": {
        "action_id": "File.Export.Video...",
        "dialog_title": "Export video",
        "form": "export_video",
        "extension": None,
        "direction": "export",
    },
    "render_video": {
        "action_id": "File.Export.Video...",
        "dialog_title": "Export video",
        "form": "export_video",
        "extension": None,
        "direction": "export",
    },
    "import_image": {
        "action_id": "View.Reference image",
        "dialog_title": "Load image",
        "extension": None,
        "direction": "import",
    },
    "import_video": {
        # Cascadeur's "Load video" window: first "Choose..." opens a native
        # file dialog with the same title, then "Import" applies the video.
        "action_id": "View.Bind video",
        "dialog_title": "Load video",
        "options_title": "Load video",
        "options_accept_title": "Choose...",
        "options_accept_index": 0,
        "after_accept_title": "Import",
        "extension": ".mp4",
        "direction": "import",
    },
}


def dialog_flow_arguments(feature_id: str, path: str, allow_overwrite: bool = False) -> dict[str, Any]:
    """Return the exact action/dialog contract for a registered dialog file flow."""
    try:
        flow = UI_FILE_FLOWS[feature_id]
    except KeyError as exc:
        raise ValueError(f"{feature_id} has no registered dialog file flow") from exc
    extension = flow["extension"]
    if extension and not path.casefold().endswith(extension):
        raise ValueError(f"{feature_id} path must end with {extension}")
    return {
        "action_id": flow["action_id"],
        "path": path,
        "dialog_title": flow["dialog_title"],
        "options_title": flow.get("options_title"),
        "options_accept_title": flow.get("options_accept_title"),
        "options_accept_index": int(flow.get("options_accept_index", 0)),
        "after_accept_title": flow.get("after_accept_title"),
        "form": flow.get("form"),
        "file_type_extension": None,
        "input": flow["direction"] == "import",
        "output": flow["direction"] == "export",
        "allow_overwrite": allow_overwrite,
    }


def _expected_ui_flow(feature_id: str, arguments: dict[str, Any]) -> dict[str, Any] | None:
    """Recompute the only allowed UI flow contract for a feature and path."""
    path = str(arguments.get("path", ""))
    if feature_id in UI_FILE_FLOWS:
        return dialog_flow_arguments(feature_id, path, bool(arguments.get("allow_overwrite")))
    direction, _, format_name = feature_id.partition("_")
    if format_name not in ("usd", "glb", "gltf", "vrm"):
        return None
    presets = ("scene", "model", "animation") if format_name == "usd" else ("scene",)
    for preset in presets:
        try:
            _feature, expected = ui_file_flow_arguments(
                direction, format_name, path, preset, bool(arguments.get("allow_overwrite"))
            )
        except ValueError:
            continue
        if expected["action_id"] == arguments.get("action_id"):
            return expected
    return None


def add_postconditions(result: ResultEnvelope, detail: str, *identifiers: str) -> None:
    """Record host-verified postconditions next to the bridge-asserted ones."""
    present = {str(item.get("id")) for item in result.postconditions if isinstance(item, dict)}
    for identifier in identifiers:
        if identifier not in present:
            result.postconditions.append({"id": identifier, "ok": True, "detail": detail})
            present.add(identifier)


class CascadeurService:
    def __init__(self, paths: RuntimePaths | None = None, client: BridgeClient | None = None):
        self.paths = paths or RuntimePaths.discover()
        self.paths.ensure()
        self.client = client or BridgeClient(self.paths)
        self.changes = ChangeManager(self.paths)
        self.evidence_store = LiveEvidenceStore(self.paths.evidence_manifest)
        self.jobs = JobStore(self.paths)
        self.jobs.recover_incomplete()
        self.installation = discover_installation()
        self.schema = load_csc_schema()
        self.commands = discover_commands()
        self._live_tools = list(BASELINE_TOOLS)
        self._license_name = "Basic"
        self._scene_available = False
        self._live_scene_id: str | None = None
        self._live_scene_revision: str | None = None
        self._dependencies = available_dependencies()
        self._features = []
        self._rebuild_features()
        self._write_registry()

    @property
    def _version_name(self) -> str:
        return self.installation.get("version") or "unknown"

    def _rebuild_features(self) -> None:
        self._features = build_registry(
            self.schema,
            self.commands,
            self._live_tools,
            license_name=self._license_name,
            scene_available=self._scene_available,
            version_name=self._version_name,
            verified_features=self.evidence_store.verified_features(
                self._version_name,
                license_name=self._license_name,
            ),
            developer_enabled=self._developer_policy(),
            available_dependencies=self._dependencies,
        )

    def _write_registry(self) -> None:
        payload = json.loads(registry_json(self._features))
        atomic_write_json(self.paths.registry, payload)

    def _remember_scene_result(self, result: ResultEnvelope, *, clear_missing: bool = False) -> None:
        """Keep later scene-bound requests attached to the document just observed.

        Scene-changing bridge operations return the new identity in the common
        envelope, while status also repeats it in its payload.  Remember both
        forms so a scene.open result cannot be followed by a request carrying
        the identity of the document that was just replaced.
        """
        if not result.ok:
            return
        payload = result.result if isinstance(result.result, dict) else {}
        scene_id = result.scene_id or payload.get("scene_id")
        revision = result.scene_revision or payload.get("revision")
        if scene_id:
            self._scene_available = True
            self._live_scene_id = str(scene_id)
            self._live_scene_revision = str(revision) if revision is not None else None
        elif clear_missing:
            self._scene_available = False
            self._live_scene_id = None
            self._live_scene_revision = None

    def refresh_live(self, timeout: float = 45.0, *, bind_to_cached: bool = False) -> ResultEnvelope:
        """Re-read live state and resynchronize the cached scene identity.

        Status is the resynchronization primitive, so it is unbound by
        default: binding it to the cached revision would make every later
        status (and therefore every prepare/commit) fail permanently after a
        scene finished loading or the user edited the scene in the UI.
        """
        result = self.client.execute(
            "status",
            [Operation(name="system.status")],
            scene_id=self._live_scene_id if bind_to_cached else None,
            expected_revision=self._live_scene_revision if bind_to_cached else None,
            timeout=timeout,
        )
        if result.ok and isinstance(result.result, dict):
            self._live_tools = result.result.get("tools") or list(BASELINE_TOOLS)
            self._license_name = result.result.get("license", "Basic")
            self._remember_scene_result(result, clear_missing=True)
            self._record_live_evidence("status", "system.status", result)
            self._rebuild_features()
            self._write_registry()
        return result

    def refresh_inventory(self, timeout: float = 120.0) -> dict[str, Any]:
        result = self.client.execute("inventory_refresh", [Operation(name="system.introspect")], timeout=timeout)
        if not result.ok or not isinstance(result.result, dict) or "schema" not in result.result:
            return result.model_dump(mode="json")
        self.schema = result.result["schema"]
        schema_path = self.paths.state / "csc_schema.json"
        atomic_write_json(schema_path, self.schema)
        status = self.refresh_live(timeout=30)
        live = status.result if status.ok and isinstance(status.result, dict) else {}
        self._live_tools = live.get("tools", BASELINE_TOOLS)
        self._license_name = live.get("license", "Basic")
        self._scene_available = bool(live.get("scene_id"))
        self._rebuild_features()
        self._write_registry()
        if self.paths.registry.is_file() and self.paths.registry.stat().st_size > 0:
            add_postconditions(result, "Host rebuilt and persisted the feature registry", "feature_registry")
        self._record_live_evidence("inventory_refresh", "system.introspect", result)
        self._rebuild_features()
        self._write_registry()
        return {
            "ok": True,
            "schema_path": str(schema_path),
            "counts": result.result.get("counts"),
            "feature_count": len(self._features),
        }

    def capabilities(self, live: bool = True) -> dict[str, Any]:
        status = self.refresh_live() if live else None
        states: dict[str, int] = {}
        modes: dict[str, int] = {}
        for item in self._features:
            states[item.state.value] = states.get(item.state.value, 0) + 1
            modes[item.execution_mode.value] = modes.get(item.execution_mode.value, 0) + 1
        product_features = [item for item in self._features if item.truth_layer == "product"]
        product_states: dict[str, int] = {}
        for item in product_features:
            product_states[item.state.value] = product_states.get(item.state.value, 0) + 1
        # Supported: live evidence on this build, or a host-only feature (feature
        # search/describe) that never reaches Cascadeur and is proven by contract.
        supported = sum(
            item.state == CapabilityState.AVAILABLE
            and (
                item.verification.value == "verified_live"
                or (item.verification.value == "contract" and item.route.startswith("host."))
            )
            for item in product_features
        )
        return {
            "server": "cascadeur-complete",
            "server_version": "0.1.0",
            "baseline": PRODUCT_CATALOG.supported_build,
            "installation": self.installation,
            "bridge_protocol": PROTOCOL_VERSION,
            "transport": "stdio",
            "feature_count": len(self._features),
            "product_coverage": {
                "catalog_count": len(product_features),
                "supported": supported,
                "support_percent": round((supported / len(product_features)) * 100, 2) if product_features else 0,
                "states": product_states,
                "definition": (
                    "dedicated adapter + exact postconditions + live evidence on this build "
                    "(host-only features: contract evidence)"
                ),
            },
            "discovered_inventory_count": len(self._features) - len(product_features),
            "states": states,
            "execution_modes": modes,
            "connection": status.model_dump(mode="json") if status else {"live_checked": False},
            "ui_pump": self._pump_state(),
            "developer_execute_python": self._developer_policy(),
        }

    def _pump_state(self) -> dict[str, object]:
        probe = getattr(self.client, "pump_state", None)
        return probe() if callable(probe) else {"active": False}

    def _developer_policy(self) -> bool:
        if not self.paths.policy.is_file():
            return False
        try:
            return bool(json.loads(self.paths.policy.read_text(encoding="utf-8")).get("developer_execute_python"))
        except (OSError, ValueError):
            return False

    def _supported_build_error(self, feature_id: str) -> ResultEnvelope | None:
        if self._version_name == PRODUCT_CATALOG.supported_build:
            return None
        return self._host_error(
            feature_id,
            ErrorCode.UNSUPPORTED_VERSION,
            (
                f"Cascadeur {PRODUCT_CATALOG.supported_build} is required; "
                f"installed build is {self._version_name}"
            ),
            mode=ExecutionMode.GATED,
        )

    @property
    def features(self) -> list[FeatureRecord]:
        return list(self._features)

    def feature(self, feature_id: str) -> FeatureRecord:
        for feature in self._features:
            if feature.id == feature_id:
                return feature
        raise KeyError(feature_id)

    @staticmethod
    def _action_slug(value: str) -> str:
        return re.sub(r"[^a-z0-9]+", ".", value.casefold()).strip(".")

    def action_allowed(self, feature_id: str, action_id: str) -> bool:
        """Bind ActionManager calls to an installed Python command record.

        C++/GUI actions that are not exported by the installed API remain
        UI-only until a version adapter provides an exact ID and postcondition.
        """
        feature = self.feature(feature_id)
        installed_names = {item["name"] for item in self.commands}
        if feature.route.startswith("action_invoke:"):
            expected = feature.route.removeprefix("action_invoke:")
            return action_id == expected and action_id in installed_names
        if feature.route.startswith("command."):
            target_slug = self._action_slug(feature.route.removeprefix("command."))
            matches = [name for name in installed_names if self._action_slug(name) == target_slug]
            return len(matches) == 1 and action_id == matches[0]
        return False

    def _generic_api_enabled(self) -> bool:
        if not DEVELOPER_BUILD:
            return False
        if not self.paths.policy.is_file():
            return False
        try:
            policy = json.loads(self.paths.policy.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False
        return bool(policy.get("developer_mode")) and bool(policy.get("generic_api"))

    def _path_policy(self) -> dict[str, bool]:
        try:
            policy = json.loads(self.paths.policy.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            policy = {}
        return {
            "allow_unc_paths": bool(policy.get("allow_unc_paths", False)),
            "allow_device_paths": bool(policy.get("allow_device_paths", False)),
            "require_confirmation_for_overwrite": bool(
                policy.get("require_confirmation_for_overwrite", True)
            ),
        }

    def _operation_binding_error(
        self, feature: FeatureRecord, operation_name: str, arguments: dict[str, Any] | None = None
    ) -> str | None:
        arguments = arguments or {}
        generic_operations = {
            "system.csc_query",
            "system.csc_mutate",
            "system.tool_call",
            "system.developer_execute_python",
        }
        if operation_name in generic_operations:
            if not self._generic_api_enabled():
                return "Generic csc/tool/Python execution is disabled in production policy"
            expected_feature = {
                "system.csc_query": "csc_query",
                "system.csc_mutate": "csc_mutate",
                "system.developer_execute_python": "developer_execute_python",
            }.get(operation_name)
            if expected_feature and feature.id != expected_feature:
                return "Generic operation is not bound to this feature id"
            return None
        if operation_name == "system.action_invoke":
            action_id = str(arguments.get("action_id", ""))
            return None if self.action_allowed(feature.id, action_id) else "Action id is not bound to this feature"
        if operation_name == "system.ui_file_flow":
            expected = _expected_ui_flow(feature.id, arguments)
            if expected is None:
                return "UI file flow is not bound to this feature"
            keys = (
                "action_id",
                "dialog_title",
                "options_title",
                "options_accept_title",
                "options_accept_index",
                "after_accept_title",
                "form",
                "file_type_extension",
            )
            if any(arguments.get(key) != expected[key] for key in keys):
                return "UI file flow arguments differ from the registered action and dialog for this feature"
            return None
        if feature.id == "view_mode" and operation_name in {"system.view_mode_get", "system.view_mode_set"}:
            return None
        aliases = {
            "auto_posing": "generation.auto_posing",
            "auto_physics": "physics.auto_snap",
        }
        expected = aliases.get(feature.id, feature.route)
        if operation_name != expected:
            return f"Operation {operation_name!r} is not bound to feature {feature.id!r}; expected {expected!r}"
        for name, value in feature.fixed_arguments.items():
            if name in arguments and arguments[name] != value:
                return f"Feature {feature.id!r} fixes argument {name!r} to {value!r}"
        return None

    def _bound_arguments(self, feature_id: str, arguments: dict[str, Any] | None) -> dict[str, Any]:
        """Merge the arguments a feature fixes (shared operations are feature-specific)."""
        merged = dict(arguments or {})
        try:
            feature = self.feature(feature_id)
        except KeyError:
            return merged
        for name, value in feature.fixed_arguments.items():
            merged.setdefault(name, value)
        if feature.route.startswith(("action_invoke:", "command.")):
            merged["command"] = True  # dispatch through the Commands.* ActionManager id
        return merged

    def feature_search(
        self,
        query: str,
        family: str | None = None,
        state: str | None = None,
        limit: int = 100,
        layer: str = "product",
    ) -> list[dict[str, Any]]:
        needle = query.casefold()
        result = []
        for feature in self._features:
            if layer not in {"product", "discovered", "all"}:
                raise ValueError("layer must be product, discovered, or all")
            if layer != "all" and feature.truth_layer != layer:
                continue
            if family and feature.family != family:
                continue
            if state and feature.state.value != state:
                continue
            haystack = f"{feature.id} {feature.name} {feature.description} {feature.route}".casefold()
            if needle and needle not in haystack:
                continue
            result.append(feature.model_dump(mode="json"))
            if len(result) >= min(max(limit, 1), 500):
                break
        return result

    def submit_job(
        self,
        feature_id: str,
        operation_name: str,
        arguments: dict[str, Any] | None = None,
        *,
        scene_id: str | None = None,
        expected_revision: str | None = None,
        timeout: float = 300,
        retry_of: str | None = None,
        attempt: int = 1,
    ) -> dict[str, Any]:
        feature = self.feature(feature_id)
        binding_error = self._operation_binding_error(feature, operation_name, arguments)
        if binding_error:
            return self._host_error(feature_id, ErrorCode.INVALID_REQUEST, binding_error).model_dump(mode="json")
        arguments = self._bound_arguments(feature_id, arguments)
        if self._operation_is_mutating(operation_name):
            return self._host_error(
                feature_id,
                ErrorCode.CONFIRMATION_REQUIRED,
                "Destructive operations cannot be submitted as background jobs; use change_prepare/change_commit",
            ).model_dump(mode="json")
        record = self.jobs.create(
            feature_id,
            operation_name=operation_name,
            arguments=arguments or {},
            scene_id=scene_id,
            expected_revision=expected_revision,
            timeout=timeout,
            retry_of=retry_of,
            attempt=attempt,
        )

        def run() -> None:
            current = self.jobs.get(record.job_id)
            if current is None or current.status == "canceled":
                return
            self.jobs.update(record.job_id, status="running", progress=0.05, log="Bridge dispatch started")
            result = self.execute(
                feature_id,
                operation_name,
                arguments or {},
                scene_id=scene_id,
                expected_revision=expected_revision,
                timeout=timeout,
            )
            current = self.jobs.get(record.job_id)
            if current is None:
                return
            if current.cancel_requested:
                self.jobs.update(
                    record.job_id,
                    status="canceled",
                    progress=1,
                    log="Claimed operation completed after cancellation request; result retained",
                    result=result,
                )
            else:
                self.jobs.update(
                    record.job_id,
                    status="succeeded" if result.ok else "failed",
                    progress=1,
                    log="Bridge operation completed",
                    result=result,
                )

        Thread(target=run, name=f"cascadeur-job-{record.job_id}", daemon=True).start()
        return record.model_dump(mode="json")

    def retry_job(self, job_id: str) -> dict[str, Any]:
        try:
            record = self.jobs.get(job_id)
        except ValueError:
            record = None
        if record is None:
            return {"ok": False, "error_code": ErrorCode.INVALID_REQUEST, "error_message": "Unknown job id"}
        if record.status not in ("failed", "canceled"):
            return {
                "ok": False,
                "error_code": ErrorCode.INVALID_REQUEST,
                "error_message": "Only failed or canceled jobs can be retried",
            }
        if not record.operation_name:
            return {
                "ok": False,
                "error_code": ErrorCode.INVALID_REQUEST,
                "error_message": "Legacy job does not retain an operation for retry",
            }
        return self.submit_job(
            record.feature_id,
            record.operation_name,
            record.arguments,
            scene_id=record.scene_id,
            expected_revision=record.expected_revision,
            timeout=record.timeout,
            retry_of=record.job_id,
            attempt=record.attempt + 1,
        )

    def execute(
        self,
        feature_id: str,
        operation_name: str,
        arguments: dict[str, Any] | None = None,
        *,
        scene_id: str | None = None,
        expected_revision: str | None = None,
        timeout: float = 30.0,
        confirmation_token: str | None = None,
    ) -> ResultEnvelope:
        build_error = self._supported_build_error(feature_id)
        if build_error and not (feature_id == "status" and operation_name == "system.status"):
            return build_error
        try:
            feature = self.feature(feature_id)
        except KeyError:
            return self._host_error(feature_id, ErrorCode.INVALID_REQUEST, "Unknown feature id")
        if operation_name in {
            "system.csc_query",
            "system.csc_mutate",
            "system.tool_call",
            "system.developer_execute_python",
        }:
            binding_error = self._operation_binding_error(feature, operation_name, arguments)
            if binding_error:
                return self._host_error(feature_id, ErrorCode.INVALID_REQUEST, binding_error)
        if feature.state == CapabilityState.LICENSE_GATED:
            return self._host_error(
                feature_id, ErrorCode.LICENSE_GATED, f"{feature.name} requires {feature.license} license"
            )
        if feature.state == CapabilityState.MISSING_DEPENDENCY:
            return self._host_error(
                feature_id,
                ErrorCode.DEPENDENCY_MISSING,
                feature.dependency or "Required integration is unavailable",
                mode=ExecutionMode.EXTERNAL,
            )
        if feature.state == CapabilityState.UNSUPPORTED_VERSION:
            return self._host_error(
                feature_id,
                ErrorCode.UNSUPPORTED_VERSION,
                f"No verified adapter for installed Cascadeur {self.installation.get('version') or 'unknown'}",
                mode=ExecutionMode.GATED,
            )
        if feature.state == CapabilityState.UI_ONLY and not feature.adapter_id:
            return self._host_error(
                feature_id,
                ErrorCode.UI_LOCKED,
                f"{feature.name} is identified as UI-only in Cascadeur {self._version_name}; "
                f"no postcondition-safe adapter is available (route: {feature.route})",
                mode=ExecutionMode.UIA,
            )
        if feature.state == CapabilityState.UNHEALTHY and not feature.adapter_id:
            return self._host_error(
                feature_id,
                ErrorCode.POSTCONDITION_FAILED,
                "Capability was inventoried but its dedicated execution adapter is not implemented",
                mode=feature.execution_mode,
            )
        binding_error = self._operation_binding_error(feature, operation_name, arguments)
        if binding_error:
            return self._host_error(feature_id, ErrorCode.INVALID_REQUEST, binding_error)
        arguments = self._bound_arguments(feature_id, arguments)
        if feature.requires_scene and scene_id is None and self._live_scene_id:
            scene_id = self._live_scene_id
            if expected_revision is None:
                expected_revision = self._live_scene_revision
        if self._operation_is_mutating(operation_name):
            return self._host_error(
                feature_id,
                ErrorCode.CONFIRMATION_REQUIRED,
                "All scene and file mutations require change_prepare and change_commit",
            )
        if operation_name == "system.action_invoke" and not feature.route.startswith(
            ("action_invoke:", "command.")
        ):
            return self._host_error(
                feature_id, ErrorCode.INVALID_REQUEST, "Feature is not registered as an action or GUI tool"
            )
        if (
            operation_name == "system.action_invoke"
            and not bool((arguments or {}).get("expect_change", True))
            and not (arguments or {}).get("postcondition")
        ):
            return self._host_error(
                feature_id,
                ErrorCode.INVALID_REQUEST,
                "Actions must require an observable scene change or provide an explicit postcondition",
            )
        safety = SafetyContext(
            destructive=False,
            confirmation_token=confirmation_token,
            snapshot_required=False,
        )
        output_path = (arguments or {}).get("path") if operation_name == "render.viewport_capture" else None
        before_output = self._file_signature(output_path) if output_path else None
        result = self.client.execute(
            feature_id,
            [Operation(name=operation_name, arguments=arguments or {})],
            scene_id=scene_id,
            expected_revision=expected_revision,
            timeout=timeout,
            safety_context=safety,
        )
        result.operation_id = operation_name
        result.status = "succeeded" if result.ok else "failed"
        result.scene_revision_before = expected_revision
        result.scene_revision_after = result.scene_revision
        if result.ok and output_path:
            result = self._wait_for_output_file(result, str(output_path), timeout, before_output)
        if result.ok and operation_name == "system.action_invoke":
            add_postconditions(
                result, "Host bound the action id to an installed command record", "registered_action_binding"
            )
        self._remember_scene_result(result)
        if result.ok and feature.adapter_id:
            self._record_live_evidence(feature_id, operation_name, result)
            self._rebuild_features()
            self._write_registry()
        return result

    def _record_live_evidence(self, feature_id: str, operation_name: str, result: ResultEnvelope) -> None:
        try:
            feature = self.feature(feature_id)
        except KeyError:
            return
        product = PRODUCT_CATALOG.by_id.get(feature_id)
        if not feature.adapter_id or not result.ok or product is None:
            return
        observed = {
            str(item.get("id")): bool(item.get("ok"))
            for item in result.postconditions
            if isinstance(item, dict) and item.get("id")
        }
        if not product.live_test_id or not product.fixture_id:
            return
        if not product.postconditions or not all(observed.get(item) is True for item in product.postconditions):
            return
        self.evidence_store.record(
            feature_id,
            version=self._version_name,
            adapter_id=feature.adapter_id,
            operation=operation_name,
            scene_id=result.scene_id,
            evidence=[item.model_dump(mode="json") for item in result.evidence],
            license_name=self._license_name,
            dependencies={product.dependency: True} if product.dependency in self._dependencies else None,
            observed_postconditions=observed,
            fixture_id=product.fixture_id,
            test_id=product.live_test_id,
        )

    def batch(
        self,
        feature_id: str,
        operations: list[dict[str, Any]],
        *,
        scene_id: str | None,
        expected_revision: str | None,
        timeout: float = 60.0,
        confirmation_token: str | None = None,
    ) -> ResultEnvelope:
        build_error = self._supported_build_error(feature_id)
        if build_error:
            return build_error
        parsed = [Operation.model_validate(item) for item in operations]
        for item in parsed:
            item.arguments = self._bound_arguments(feature_id, item.arguments)
        try:
            feature = self.feature(feature_id)
        except KeyError:
            return self._host_error(feature_id, ErrorCode.INVALID_REQUEST, "Unknown feature id")
        binding_errors = [self._operation_binding_error(feature, item.name, item.arguments) for item in parsed]
        if any(binding_errors):
            return self._host_error(
                feature_id,
                ErrorCode.INVALID_REQUEST,
                next(item for item in binding_errors if item),
            )
        mutating = any(self._operation_is_mutating(item.name) for item in parsed)
        if mutating:
            return self._host_error(
                feature_id,
                ErrorCode.CONFIRMATION_REQUIRED,
                "Mutating batches must be split into individually prepared changes",
            )
        if any(self._operation_is_mutating(item.name) for item in parsed) and expected_revision is None:
            return self._host_error(
                feature_id, ErrorCode.INVALID_REQUEST, "expected_revision is required for mutating batches"
            )
        result = self.client.execute(
            feature_id,
            parsed,
            scene_id=scene_id,
            expected_revision=expected_revision,
            timeout=timeout,
            safety_context=SafetyContext(destructive=False, confirmation_token=confirmation_token),
        )
        result.operation_id = "batch"
        result.status = "succeeded" if result.ok else "failed"
        result.scene_revision_before = expected_revision
        result.scene_revision_after = result.scene_revision
        self._remember_scene_result(result)
        return result

    def prepare_change(
        self, feature_id: str, operation_name: str, arguments: dict[str, Any], ttl: float = 300.0
    ) -> dict[str, Any]:
        build_error = self._supported_build_error(feature_id)
        if build_error:
            return build_error.model_dump(mode="json")
        feature = self.feature(feature_id)
        if operation_name in {
            "system.csc_query",
            "system.csc_mutate",
            "system.tool_call",
            "system.developer_execute_python",
        }:
            binding_error = self._operation_binding_error(feature, operation_name, arguments)
            if binding_error:
                return self._host_error(feature_id, ErrorCode.INVALID_REQUEST, binding_error).model_dump(mode="json")
        if feature.state == CapabilityState.LICENSE_GATED:
            return self._host_error(
                feature_id, ErrorCode.LICENSE_GATED, f"{feature.name} requires {feature.license} license"
            ).model_dump(mode="json")
        if feature.state == CapabilityState.MISSING_DEPENDENCY:
            return self._host_error(
                feature_id,
                ErrorCode.DEPENDENCY_MISSING,
                feature.dependency or "Required integration is unavailable",
                mode=ExecutionMode.EXTERNAL,
            ).model_dump(mode="json")
        if feature.state == CapabilityState.UNSUPPORTED_VERSION:
            return self._host_error(
                feature_id,
                ErrorCode.UNSUPPORTED_VERSION,
                f"No verified adapter for installed Cascadeur {self.installation.get('version') or 'unknown'}",
                mode=ExecutionMode.GATED,
            ).model_dump(mode="json")
        if feature.state == CapabilityState.UI_ONLY and not feature.adapter_id:
            return self._host_error(
                feature_id,
                ErrorCode.UI_LOCKED,
                f"{feature.name} is identified as UI-only in Cascadeur {self._version_name}; "
                f"no postcondition-safe adapter is available (route: {feature.route})",
                mode=ExecutionMode.UIA,
            ).model_dump(mode="json")
        if feature.state == CapabilityState.UNHEALTHY and not feature.adapter_id:
            return self._host_error(
                feature_id,
                ErrorCode.POSTCONDITION_FAILED,
                "Capability was inventoried but its dedicated execution adapter is not implemented",
                mode=feature.execution_mode,
            ).model_dump(mode="json")
        binding_error = self._operation_binding_error(feature, operation_name, arguments)
        if binding_error:
            return self._host_error(feature_id, ErrorCode.INVALID_REQUEST, binding_error).model_dump(mode="json")
        arguments = self._bound_arguments(feature_id, arguments)
        if operation_name == "timeline.playback":
            moving = self._playback_moving()
            wants_play = arguments.get("state") == "play"
            if moving is None or moving == wants_play:
                return self._host_error(
                    feature_id,
                    ErrorCode.INVALID_REQUEST,
                    "Playback is already " + ("running" if moving else "stopped")
                    if moving is not None
                    else "The playhead could not be sampled",
                ).model_dump(mode="json")
        if not self._operation_is_mutating(operation_name):
            return self._host_error(
                feature_id,
                ErrorCode.INVALID_REQUEST,
                "Read-only operations must be executed directly and cannot mint change tokens",
            ).model_dump(mode="json")
        status = self.refresh_live()
        if not status.ok:
            return status.model_dump(mode="json")
        state = status.result
        if feature.requires_scene and not state.get("scene_id"):
            return self._host_error(
                feature_id,
                ErrorCode.POSTCONDITION_FAILED,
                f"{feature.name} requires an active Cascadeur scene",
                mode=feature.execution_mode,
            ).model_dump(mode="json")
        destination = arguments.get("path") or arguments.get("destination")
        if destination:
            path_policy = self._path_policy()
            if (
                operation_name in INPUT_PATH_OPERATIONS
                or operation_name.startswith("io.import_")
                or bool(arguments.get("input"))
            ):
                validated = validate_local_input_path(
                    str(destination),
                    allow_unc_paths=path_policy["allow_unc_paths"],
                    allow_device_paths=path_policy["allow_device_paths"],
                )
            else:
                validated = validate_local_path(
                    str(destination),
                    allow_overwrite=(
                        bool(arguments.get("allow_overwrite"))
                        or not path_policy["require_confirmation_for_overwrite"]
                    ),
                    allow_unc_paths=path_policy["allow_unc_paths"],
                    allow_device_paths=path_policy["allow_device_paths"],
                )
            arguments = {**arguments, "path": str(validated)}
        snapshot_id = str(uuid.uuid4())
        working_id = str(uuid.uuid4())
        backup_path = None
        working_path = None
        # Playback only moves the playhead and edits no scene data, while the
        # playhead is part of the revision; bind it to the scene identity only.
        playhead_only = operation_name in PLAYHEAD_ONLY_OPERATIONS
        if state.get("scene_id") and not playhead_only:
            snapshot = self.client.execute(
                "snapshot",
                [
                    Operation(
                        name="safety.snapshot",
                        arguments={"snapshot_id": snapshot_id, "working_id": working_id},
                    )
                ],
                scene_id=state["scene_id"],
                expected_revision=state["revision"],
                timeout=120,
            )
            if not snapshot.ok:
                return snapshot.model_dump(mode="json")
            # safety.snapshot saves and activates a distinct writable working
            # document. Bind the post-snapshot status check to that returned
            # identity, not to the immutable source document cached above.
            self._remember_scene_result(snapshot)
            backup_path = snapshot.result["path"]
            working_path = snapshot.result.get("working_path", backup_path)
            if Path(backup_path).resolve() == Path(working_path).resolve():
                return self._host_error(
                    feature_id,
                    ErrorCode.POSTCONDITION_FAILED,
                    "Snapshot safety invariant failed: recovery and working paths are identical",
                ).model_dump(mode="json")
            # Bind the token to the writable working document created by the
            # snapshot operation, never to the original or immutable backup.
            post_snapshot = self.refresh_live(bind_to_cached=True)
            if not post_snapshot.ok:
                return post_snapshot.model_dump(mode="json")
            state = post_snapshot.result
        impact = {
            "feature": feature.name,
            "destructive": True,
            "selected_entities": len(state.get("selection", [])),
            "object_count": len(state.get("objects", [])),
            "destination": arguments.get("path"),
            "working_scene": working_path,
            "expected_result": "Operation-specific postconditions must pass",
        }
        record = self.changes.prepare(
            feature_id=feature_id,
            scene_id=state.get("scene_id"),
            scene_revision=None if playhead_only else state.get("revision"),
            selection_fingerprint=state.get("selection_fingerprint"),
            operation=Operation(name=operation_name, arguments=arguments),
            impact=impact,
            backup_path=backup_path,
            ttl=ttl,
        )
        return {
            "ok": True,
            "confirmation_token": record.token,
            "feature_id": feature_id,
            "scene_id": record.scene_id,
            "scene_revision": record.scene_revision,
            "selection_fingerprint": record.selection_fingerprint,
            "operation": record.operation.model_dump(mode="json"),
            "impact": impact,
            "backup_path": backup_path,
            "working_path": working_path,
            "snapshot_id": snapshot_id if backup_path else None,
            "expires_at": record.expires_at,
        }

    def commit_change(self, token: str, timeout: float = 120.0) -> ResultEnvelope:
        build_error = self._supported_build_error("change_commit")
        if build_error:
            return build_error
        try:
            record = self.changes.load(token)
        except SafetyError as exc:
            return self._host_error("change_commit", ErrorCode.INVALID_REQUEST, str(exc))
        status = self.refresh_live()
        if not status.ok:
            return status
        state = status.result
        try:
            self.changes.consume(
                token,
                scene_id=state.get("scene_id"),
                scene_revision=state.get("revision"),
                selection_fingerprint=state.get("selection_fingerprint"),
            )
        except SafetyError as exc:
            return self._host_error(record.feature_id, ErrorCode.SCENE_CHANGED, str(exc))
        output_path = record.operation.arguments.get("path")
        before_output = self._file_signature(output_path) if output_path else None
        before_view = None
        if record.operation.name in VIEW_OPERATIONS:
            self._wait_for_bridge_idle()
            before_view = capture_window_sample()
        if record.operation.name == "system.ui_file_flow":
            result = self._execute_ui_file_flow(record, timeout, before_output)
        else:
            result = self.client.execute(
                record.feature_id,
                [record.operation],
                scene_id=record.scene_id,
                expected_revision=record.scene_revision,
                timeout=timeout,
                safety_context=SafetyContext(
                    destructive=True,
                    confirmation_token=token,
                    snapshot_required=False,
                    selection_fingerprint=record.selection_fingerprint,
                    allow_overwrite=bool(record.operation.arguments.get("allow_overwrite")),
                ),
            )
        result.snapshot_id = Path(record.backup_path).stem if record.backup_path else None
        result.operation_id = record.operation.name
        result.status = "succeeded" if result.ok else "failed"
        result.scene_revision_before = record.scene_revision
        result.scene_revision_after = result.scene_revision
        try:
            if result.ok and record.operation.name == "scene.open":
                result = self._wait_for_open_scene(result, str(record.operation.arguments["path"]), timeout)
            if result.ok and record.operation.name == "scene.open_autosave":
                result = self._wait_for_open_scene(result, str(result.result["path"]), timeout)
            if result.ok and record.operation.name in {"scene.activate", "scene.new"}:
                payload = result.result if isinstance(result.result, dict) else {}
                if not payload.get("tab_id"):
                    raise RuntimeError("Scene change result does not identify the target tab")
                result = self._wait_for_open_scene(
                    result, str(payload.get("path") or ""), timeout, expected_tab_id=str(payload["tab_id"])
                )
            if result.ok and record.operation.name == "safety.rollback":
                working_path = self.paths.snapshots / (
                    str(record.operation.arguments["working_id"]) + ".working.casc"
                )
                result = self._wait_for_open_scene(result, str(working_path), timeout)
            if result.ok and record.operation.name == "physics.auto_snap":
                result = self._complete_auto_physics_snap(result, timeout)
            if result.ok and record.operation.name in SETTLED_ROTATION_OPERATIONS:
                checked = self._verify_settled_rotations(record, result)
                if checked:
                    add_postconditions(
                        result,
                        f"{checked} written rotation(s) re-read unchanged in a separate request",
                        "rotations_persist_after_update",
                    )
            if result.ok and record.feature_id == "blender_export":
                report = verify_blender_fbx(str(record.operation.arguments["path"]))
                if report["armatures"] < 1 or not report["actions"]:
                    raise RuntimeError(f"Blender imported no armature/animation: {report}")
                result.result = {**(result.result if isinstance(result.result, dict) else {}), "blender": report}
                add_postconditions(
                    result,
                    f"Blender {report['blender']} imported {report['armatures']} armature(s), "
                    f"{report['bones']} bones and {len(report['actions'])} action(s)",
                    "target_import_verified",
                )
            if result.ok and record.operation.name in VIEW_OPERATIONS:
                self._wait_for_bridge_idle()
                time.sleep(1.0)
                changed = sample_difference(before_view, capture_window_sample())
                if changed < VIEW_CHANGE_FRACTION:
                    raise RuntimeError(f"the rendered window did not change after the view action ({changed:.4%})")
                add_postconditions(
                    result, f"{changed:.2%} of sampled window pixels changed", "viewport_render_changed"
                )
            if result.ok and record.operation.name == "timeline.playback":
                wants_play = record.operation.arguments.get("state") == "play"
                moving = self._playback_moving()
                if moving is None or moving != wants_play:
                    raise RuntimeError("playhead motion after the toggle does not match the requested state")
                add_postconditions(
                    result,
                    "Playhead sampled twice after the UI thread was released",
                    "playback_frames_advance" if wants_play else "playback_frame_stable",
                )
            if result.ok and record.operation.name in OUTPUT_OPERATIONS:
                result = self._wait_for_output_file(
                    result,
                    str(record.operation.arguments["path"]),
                    timeout,
                    before_output,
                    stable_seconds=3.0 if record.operation.name == "render.video" else 0.0,
                )
        except Exception as exc:
            bridge_evidence = list(result.evidence)
            result = self._host_error(
                record.feature_id,
                ErrorCode.POSTCONDITION_FAILED,
                f"Host postcondition failed: {exc}",
                mode=result.execution_mode,
            )
            result.snapshot_id = Path(record.backup_path).stem if record.backup_path else None
            result.evidence = bridge_evidence
        if result.ok and record.operation.name == "system.action_invoke":
            add_postconditions(
                result, "Host bound the action id to an installed command record", "registered_action_binding"
            )
        if result.ok:
            self._record_live_evidence(record.feature_id, record.operation.name, result)
            # The generic dispatchers are proven by any concrete bound dispatch.
            if record.operation.name == "system.ui_file_flow":
                self._record_live_evidence("ui_flow_run", record.operation.name, result)
            if record.operation.name == "system.action_invoke" and record.feature_id.startswith("command."):
                self._record_live_evidence("action_invoke", record.operation.name, result)
            self._rebuild_features()
            self._write_registry()
        elif record.backup_path:
            result = self._restore_failed_change(record, result)
        result.operation_id = record.operation.name
        result.status = "succeeded" if result.ok else "failed"
        result.scene_revision_before = record.scene_revision
        result.scene_revision_after = result.scene_revision
        self._remember_scene_result(result)
        return result

    def _execute_ui_file_flow(self, record, timeout: float, before_output: tuple[int, int] | None) -> ResultEnvelope:
        """Coordinate a blocking Cascadeur action with its owned file dialog."""
        arguments = record.operation.arguments
        action_id = str(arguments["action_id"])
        responses: list[ResultEnvelope] = []
        failures: list[BaseException] = []

        def dispatch() -> None:
            try:
                responses.append(
                    self.client.execute(
                        record.feature_id,
                        [Operation(name="system.action_dispatch", arguments={"action_id": action_id})],
                        scene_id=record.scene_id,
                        expected_revision=record.scene_revision,
                        timeout=timeout,
                        safety_context=SafetyContext(
                            destructive=True,
                            confirmation_token=record.token,
                            selection_fingerprint=record.selection_fingerprint,
                            allow_overwrite=bool(arguments.get("allow_overwrite")),
                        ),
                    )
                )
            except BaseException as exc:  # pragma: no cover - thread boundary
                failures.append(exc)

        worker = Thread(target=dispatch, name="cascadeur-ui-file-flow", daemon=True)
        worker.start()
        started = time.time()
        try:
            if arguments.get("form") == "export_video":
                target = Path(str(arguments["path"]))
                dialog = complete_export_video_form(
                    action_id=action_id,
                    folder=str(target.parent).replace("\\", "/"),
                    name=target.name,
                    width=int(arguments.get("width", 320)),
                    height=int(arguments.get("height", 180)),
                    quality=str(arguments.get("quality", "LOW")),
                    timeout=min(timeout, 30.0),
                )
            else:
                dialog = complete_file_dialog(
                    action_id=action_id,
                    path=str(arguments["path"]),
                    expected_dialog_title=str(arguments["dialog_title"]),
                    options_title=arguments.get("options_title"),
                    options_accept_title=arguments.get("options_accept_title"),
                    file_type_extension=arguments.get("file_type_extension"),
                    timeout=min(timeout, 30.0),
                    options_accept_index=int(arguments.get("options_accept_index") or 0),
                    after_accept_title=arguments.get("after_accept_title"),
                )
        except Exception as exc:
            if not cancel_file_flow(
                expected_dialog_title=str(arguments["dialog_title"]),
                options_title=arguments.get("options_title"),
            ):
                # Never leave an unexpected modal file dialog blocking Cascadeur.
                cancel_owned_file_dialogs()
            worker.join(min(10.0, max(0.1, timeout)))
            is_uia = isinstance(exc, UIAutomationError)
            gated = responses and responses[0].error_code == ErrorCode.LICENSE_GATED
            if is_uia and exc.license_gated or gated:
                return self._host_error(
                    record.feature_id,
                    ErrorCode.LICENSE_GATED,
                    str(exc) if is_uia and exc.license_gated else str(responses[0].error_message),
                    mode=ExecutionMode.GATED,
                )
            return self._host_error(
                record.feature_id,
                (ErrorCode.CASCADEUR_NOT_RUNNING if is_uia and exc.not_running else ErrorCode.UI_LOCKED),
                f"UI file flow failed: {exc}",
                mode=ExecutionMode.UIA,
            )
        worker.join(max(0.1, timeout))
        if worker.is_alive():
            return self._host_error(
                record.feature_id,
                ErrorCode.TIMEOUT,
                f"Cascadeur action did not finish after file dialog acceptance: {action_id}",
                mode=ExecutionMode.UIA,
            )
        if failures:
            return self._host_error(
                record.feature_id,
                ErrorCode.UI_LOCKED,
                f"UI file flow dispatch failed: {failures[0]}",
                mode=ExecutionMode.UIA,
            )
        if not responses:
            return self._host_error(
                record.feature_id,
                ErrorCode.POSTCONDITION_FAILED,
                "UI file flow produced no bridge response",
                mode=ExecutionMode.UIA,
            )
        result = responses[0]
        result.execution_mode = ExecutionMode.UIA
        result.evidence.append(
            Evidence(
                kind="host_ui_file_dialog",
                detail=(
                    f"Invoked {dialog.action_id}; matched {dialog.dialog_title}; "
                    f"set Edit {dialog.file_name_automation_id}; accepted Button {dialog.accept_automation_id}; "
                    f"file type {dialog.file_type or 'dialog default'}"
                ),
                observed_at=dialog.completed_at,
            )
        )
        if not result.ok:
            return result
        add_postconditions(
            result,
            f"Host completed the exact owned dialog {dialog.dialog_title}",
            "exact_file_dialog",
            "registered_uia_flow_token",
        )
        if arguments.get("options_title"):
            add_postconditions(
                result, f"Host accepted the exact options window {arguments['options_title']}", "exact_options_window"
            )
        if arguments.get("form") == "export_video":
            result = self._wait_for_rendered_video(result, Path(str(arguments["path"])), timeout, started)
            try:
                closed = finish_export_video_form(timeout=min(120.0, timeout))
            except UIAutomationError as exc:
                return self._host_error(
                    record.feature_id, ErrorCode.UI_LOCKED, f"Rendered, but {exc}", mode=ExecutionMode.UIA
                )
            if result.ok and closed:
                result.evidence.append(
                    Evidence(
                        kind="host_ui_file_dialog",
                        detail="Export video reached its completion screen; host pressed Ok",
                        observed_at=time.time(),
                    )
                )
            return result
        if bool(arguments.get("output")):
            return self._wait_for_output_file(result, str(arguments["path"]), timeout, before_output)
        before_revision = record.scene_revision
        try:
            helper = resolve_optional_rig_mode_helper(enter_rig_mode=False, timeout=min(12.0, timeout))
        except UIAutomationError as exc:
            failed = self._host_error(
                record.feature_id,
                ErrorCode.UI_LOCKED,
                f"Imported scene is waiting for an unresolved Rig Mode Helper: {exc}",
                mode=ExecutionMode.UIA,
            )
            failed.evidence = list(result.evidence)
            return failed
        if helper is not None:
            result.evidence.append(
                Evidence(
                    kind="host_ui_postcondition",
                    detail=f"Dismissed optional {helper.window_title} with {helper.button}",
                    observed_at=helper.dismissed_at,
                )
            )
        deadline = time.monotonic() + max(1.0, timeout)
        after = None
        while time.monotonic() < deadline:
            # Let Cascadeur's event loop finish the asynchronous import between
            # polls; a lingering drain would otherwise keep the UI thread busy.
            self._wait_for_bridge_idle()
            after = self.refresh_live(timeout=min(20.0, max(1.0, deadline - time.monotonic())))
            if after.ok and after.scene_revision and after.scene_revision != before_revision:
                break
            time.sleep(0.2)
        if after is None or not after.ok or not after.scene_revision or after.scene_revision == before_revision:
            failed = self._host_error(
                record.feature_id,
                ErrorCode.POSTCONDITION_FAILED,
                "Import file dialog completed but the scene revision did not change",
                mode=ExecutionMode.UIA,
            )
            failed.evidence = list(result.evidence) + (list(after.evidence) if after is not None else [])
            return failed
        result.scene_id = after.scene_id
        result.scene_revision = after.scene_revision
        result.changed_entities = sorted(set(result.changed_entities + ["scene"]))
        result.evidence.extend(after.evidence)
        result.evidence.append(
            Evidence(
                kind="host_scene_postcondition",
                detail="Scene revision changed after UI file import",
                observed_at=time.time(),
            )
        )
        add_postconditions(result, "Scene revision changed after UI file import", "scene_revision_changed")
        return result

    def _restore_failed_change(self, record, failed: ResultEnvelope) -> ResultEnvelope:
        """Restore the prepared snapshot after any failed destructive commit.

        A Cascadeur command may modify static update-graph data before its own
        postcondition fails.  Those partial writes are not always represented
        by the normal scene fingerprint, so every failed prepared change is
        restored from its already-created snapshot instead of guessing whether
        the scene is still clean.
        """
        snapshot_id = Path(record.backup_path).stem
        restored = self._rollback_internal(snapshot_id)
        if restored.ok:
            failed.scene_id = restored.scene_id
            failed.scene_revision = restored.scene_revision
            failed.warnings.append(f"Failed change was automatically restored from snapshot {snapshot_id}")
            failed.evidence.extend(restored.evidence)
            failed.evidence.append(
                Evidence(
                    kind="automatic_rollback",
                    detail=f"Restored prepared snapshot {snapshot_id} after failed commit",
                    observed_at=time.time(),
                )
            )
        else:
            failed.warnings.append(
                "Automatic rollback failed; use change_rollback with snapshot "
                f"{snapshot_id}. Rollback error: {restored.error_message or restored.error_code}"
            )
            failed.evidence.extend(restored.evidence)
        return failed

    def _verify_settled_rotations(self, record, result: ResultEnvelope) -> int:
        payload = result.result if isinstance(result.result, dict) else {}
        frame = payload.get("frame") if isinstance(payload, dict) else None
        samples = settled_rotation_samples(record.operation.name, dict(record.operation.arguments), frame)
        if not samples:
            return 0
        space = str(record.operation.arguments.get("space", "local"))
        time.sleep(0.3)
        by_frame: dict[int, list[tuple[str, list[float]]]] = {}
        for object_id, sample_frame, expected in samples:
            by_frame.setdefault(sample_frame, []).append((object_id, expected))
        operations = [
            Operation(
                name="animation.transform_get",
                arguments={"ids": [item[0] for item in items], "frame": sample_frame, "space": space},
            )
            for sample_frame, items in sorted(by_frame.items())
        ]
        reread = self.client.execute("transform_get", operations, timeout=120)
        if not reread.ok:
            raise RuntimeError(f"settled read-back failed: {reread.error_code}: {reread.error_message}")
        rows = reread.result if len(operations) > 1 else [{"result": reread.result}]
        worst = (0.0, None, None)
        for (sample_frame, items), row in zip(sorted(by_frame.items()), rows, strict=True):
            observed = {str(item["id"]): item["rotation"]["quaternion_wxyz"] for item in row["result"]}
            for object_id, expected in items:
                angle = quaternion_angle_degrees(expected, observed[object_id])
                if angle > worst[0]:
                    worst = (angle, object_id, sample_frame)
        if worst[0] > SETTLED_TOLERANCE_DEGREES:
            raise RuntimeError(
                f"written rotation did not persist: {worst[1]} at frame {worst[2]} differs by {worst[0]:.2f} deg "
                "after the update (AutoPosing or the rig re-solved it; deactivate AutoPosing first)"
            )
        return len(samples)

    def _complete_auto_physics_snap(self, initial: ResultEnvelope, timeout: float) -> ResultEnvelope:
        payload = dict(initial.result) if isinstance(initial.result, dict) else {}
        before_revision = payload.get("before_revision") or initial.scene_revision
        if payload.get("completed_synchronously"):
            initial.changed_entities = sorted(set(initial.changed_entities + ["scene.animation"]))
            return initial
        try:
            modal = resolve_autophysics_snap_warning(turn_off_single_use_features=True)
        except UIAutomationError as exc:
            failed = self._host_error(
                initial.feature_id,
                ErrorCode.POSTCONDITION_FAILED,
                "AutoPhysics produced no synchronous change and its confirmation could not be completed: " + str(exc),
            )
            failed.snapshot_id = initial.snapshot_id
            failed.scene_id = initial.scene_id
            failed.scene_revision = initial.scene_revision
            failed.evidence = list(initial.evidence)
            return failed

        deadline = time.monotonic() + max(1.0, timeout)
        latest = None
        while time.monotonic() < deadline:
            self._wait_for_bridge_idle()
            latest = self.client.execute("auto_physics", [Operation(name="system.status")], timeout=15)
            if latest.ok and latest.scene_revision and latest.scene_revision != before_revision:
                payload.update(
                    {
                        "after_revision": latest.scene_revision,
                        "completed_synchronously": False,
                        "confirmation_may_be_pending": False,
                        "confirmation_button": modal.button,
                    }
                )
                initial.result = payload
                initial.scene_id = latest.scene_id
                initial.scene_revision = latest.scene_revision
                initial.warnings = [
                    warning
                    for warning in initial.warnings
                    if warning != "Cascadeur may be waiting for the known AutoPhysics single-use-feature confirmation"
                ]
                initial.changed_entities = sorted(set(initial.changed_entities + ["scene.animation"]))
                add_postconditions(
                    initial, "Scene revision changed after the AutoPhysics confirmation", "scene_revision_changed"
                )
                initial.evidence.extend(latest.evidence)
                initial.evidence.append(
                    Evidence(
                        kind="host_ui_postcondition",
                        detail="; ".join(
                            (
                                f"Dismissed AutoPhysics {modal.window_title} with {modal.button}",
                                "scene revision changed",
                            )
                        ),
                        observed_at=modal.dismissed_at,
                    )
                )
                return initial
            time.sleep(0.1)
        failed = self._host_error(
            initial.feature_id,
            ErrorCode.POSTCONDITION_FAILED,
            "AutoPhysics confirmation closed but the animation revision did not change before timeout",
        )
        failed.snapshot_id = initial.snapshot_id
        failed.scene_id = latest.scene_id if latest else initial.scene_id
        failed.scene_revision = latest.scene_revision if latest else initial.scene_revision
        failed.evidence = list(initial.evidence)
        return failed

    @staticmethod
    def _file_signature(path: str | None) -> tuple[int, int] | None:
        if not path:
            return None
        candidate = Path(path)
        if not candidate.is_file():
            return None
        stat = candidate.stat()
        return stat.st_size, stat.st_mtime_ns

    def _wait_for_rendered_video(
        self, initial: ResultEnvelope, stem_path: Path, timeout: float, started: float
    ) -> ResultEnvelope:
        """Wait for the file Cascadeur renders under the requested name (extension set by its format)."""
        deadline = time.monotonic() + max(1.0, timeout)
        while time.monotonic() < deadline:
            candidates = sorted(
                (
                    item
                    for item in stem_path.parent.glob(glob_escape(stem_path.name) + ".*")
                    if item.is_file() and item.stat().st_mtime >= started - 1.0
                ),
                key=lambda item: item.stat().st_mtime,
            )
            if candidates:
                remaining = max(1.0, deadline - time.monotonic())
                return self._wait_for_output_file(
                    initial, str(candidates[-1]), remaining, None, stable_seconds=3.0
                )
            time.sleep(0.5)
        return self._host_error(
            initial.feature_id,
            ErrorCode.POSTCONDITION_FAILED,
            f"No rendered video named {stem_path.name}.* appeared in {stem_path.parent}",
            mode=ExecutionMode.UIA,
        )

    def _wait_for_output_file(
        self,
        initial: ResultEnvelope,
        output_path: str,
        timeout: float,
        before_signature: tuple[int, int] | None,
        *,
        stable_seconds: float = 0.0,
    ) -> ResultEnvelope:
        path = Path(output_path)
        deadline = time.monotonic() + max(1.0, timeout)
        previous = None
        stable_observations = 0
        stable_since = time.monotonic()
        while time.monotonic() < deadline:
            signature = self._file_signature(output_path)
            if signature is not None and signature[0] > 0 and signature != before_signature:
                if signature != previous:
                    stable_since = time.monotonic()
                stable_observations = stable_observations + 1 if signature == previous else 1
                previous = signature
                if stable_observations >= 2 and time.monotonic() - stable_since >= stable_seconds:
                    payload = dict(initial.result) if isinstance(initial.result, dict) else {}
                    payload.update(
                        {
                            "path": str(path),
                            "bytes": signature[0],
                            "stable_observations": stable_observations,
                            "scheduled": False,
                        }
                    )
                    initial.result = payload
                    initial.evidence.append(
                        Evidence(
                            kind="host_file_postcondition",
                            detail=f"Output file became stable with {signature[0]} bytes",
                            observed_at=time.time(),
                        )
                    )
                    add_postconditions(
                        initial,
                        f"Output file became stable with {signature[0]} bytes",
                        "output_file",
                        "nonzero_bytes",
                    )
                    return initial
            time.sleep(0.2)
        failed = self._host_error(
            initial.feature_id,
            ErrorCode.POSTCONDITION_FAILED,
            f"Render output did not become stable before timeout: {output_path}",
        )
        failed.snapshot_id = initial.snapshot_id
        failed.scene_id = initial.scene_id
        failed.scene_revision = initial.scene_revision
        failed.evidence = list(initial.evidence)
        return failed

    @staticmethod
    def _same_path(left: str | None, right: str | None) -> bool:
        """Compare scene labels: absolute paths by file identity, untitled tabs by name."""
        if not left or not right:
            return False
        if os.path.isabs(left) and os.path.isabs(right):
            return os.path.normcase(os.path.abspath(left)) == os.path.normcase(os.path.abspath(right))
        return left.strip().casefold() == right.strip().casefold()

    @staticmethod
    def _scene_label(state: dict[str, Any]) -> str | None:
        return state.get("path") or state.get("name")

    def _timeline_frame(self) -> int | None:
        observed = self.client.execute("timeline_get", [Operation(name="timeline.get")], timeout=30)
        if not observed.ok or not isinstance(observed.result, dict):
            return None
        return int(observed.result.get("current_frame", -1))

    def _playback_moving(self, interval: float = 1.2) -> bool | None:
        """Sample the playhead twice after the UI thread is free; None if unreadable."""
        self._wait_for_bridge_idle()
        first = self._timeline_frame()
        self._wait_for_bridge_idle()
        time.sleep(interval)
        second = self._timeline_frame()
        if first is None or second is None:
            return None
        return first != second

    def _active_tab_id(self) -> str | None:
        listed = self.client.execute("scene_list", [Operation(name="scene.list")], timeout=30)
        if not listed.ok or not isinstance(listed.result, list):
            return None
        return next((str(item.get("tab_id")) for item in listed.result if item.get("active")), None)

    def _wait_for_bridge_idle(self, limit: float = 3.0) -> None:
        """Wait until a lingering bridge drain released the UI thread."""
        deadline = time.monotonic() + limit
        while time.monotonic() < deadline and self.client.lingering_until() is not None:
            time.sleep(0.1)

    def _wait_for_open_scene(
        self,
        initial: ResultEnvelope,
        expected_path: str,
        timeout: float,
        *,
        expected_tab_id: str | None = None,
    ) -> ResultEnvelope:
        """Require the expected scene to stay active after Cascadeur's UI settles.

        The bridge verifies the target inside the command, but Cascadeur's tab
        bar re-asserts its previous selection once the command returns. The
        host therefore re-observes the active scene with fresh reads (each
        dispatched after the event loop ran) and, when the UI reverted,
        selects tabs through the UI with Ctrl+Tab until the target is active.
        Untitled scenes are matched by session tab id instead of path.
        """
        deadline = time.monotonic() + max(5.0, timeout)
        tab_cycles = 0
        listed = self.client.execute("scene_list", [Operation(name="scene.list")], timeout=30)
        tab_count = len(listed.result) if listed.ok and isinstance(listed.result, list) else 40
        max_tab_cycles = tab_count + 2
        stable = 0
        latest = None
        while time.monotonic() < deadline:
            if expected_tab_id is not None:
                matched = self._active_tab_id() == expected_tab_id
            else:
                matched = self._same_path(active_scene_title(), expected_path)
            if matched:
                latest = self.refresh_live(timeout=min(30.0, max(1.0, deadline - time.monotonic())))
                label_ok = expected_tab_id is not None or (
                    latest.ok
                    and isinstance(latest.result, dict)
                    and self._same_path(self._scene_label(latest.result), expected_path)
                )
                if latest.ok and label_ok:
                    stable += 1
                    if stable >= 2:
                        break
                    self._wait_for_bridge_idle()
                    time.sleep(0.5)
                    continue
            stable = 0
            if tab_cycles >= max_tab_cycles:
                break
            self._wait_for_bridge_idle()
            try:
                cycle_scene_tab()
            except UIAutomationError:
                break
            tab_cycles += 1
            time.sleep(0.8)
        if stable < 2 or latest is None:
            failed = self._host_error(
                initial.feature_id,
                ErrorCode.POSTCONDITION_FAILED,
                "Scene did not stay active after the UI settled: " + (expected_tab_id or expected_path),
            )
            failed.snapshot_id = initial.snapshot_id
            if latest is not None:
                failed.evidence = list(latest.evidence)
            return failed
        initial.scene_id = latest.scene_id
        initial.scene_revision = latest.scene_revision
        initial.changed_entities = sorted(set(initial.changed_entities + ["scene"]))
        payload = dict(initial.result) if isinstance(initial.result, dict) else {}
        payload.update(
            {
                "path": latest.result.get("path"),
                "loaded": True,
                "stable_observations": stable,
                "ui_tab_cycles": tab_cycles,
            }
        )
        initial.result = payload
        initial.evidence.extend(latest.evidence)
        target = expected_tab_id or expected_path
        initial.evidence.append(
            Evidence(
                kind="host_window_postcondition",
                detail=f"Scene stayed active after UI settle ({tab_cycles} UI tab cycles): {target}",
                observed_at=time.time(),
            )
        )
        add_postconditions(initial, f"Active scene settled at {target}", "stable_scene_path")
        return initial

    def _snapshot_path(self, snapshot_id: str) -> Path | None:
        try:
            canonical = str(uuid.UUID(str(snapshot_id)))
        except (ValueError, TypeError, AttributeError):
            return None
        if canonical != str(snapshot_id).casefold():
            return None
        path = (self.paths.snapshots / f"{canonical}.casc").resolve()
        if path.parent != self.paths.snapshots.resolve() or not path.is_file():
            return None
        return path

    def prepare_rollback(self, snapshot_id: str, ttl: float = 300.0) -> dict[str, Any]:
        build_error = self._supported_build_error("change_rollback")
        if build_error:
            return build_error.model_dump(mode="json")
        path = self._snapshot_path(snapshot_id)
        if path is None:
            return self._host_error(
                "change_rollback", ErrorCode.INVALID_REQUEST, "Unknown snapshot"
            ).model_dump(mode="json")
        status = self.refresh_live()
        if not status.ok or not isinstance(status.result, dict):
            return status.model_dump(mode="json")
        state = status.result
        working_id = str(uuid.uuid4())
        operation = Operation(
            name="safety.rollback",
            arguments={"path": str(path), "working_id": working_id, "snapshot_id": snapshot_id},
        )
        impact = {
            "feature": "Rollback",
            "destructive": True,
            "snapshot_id": snapshot_id,
            "expected_result": "Replace the active document with a writable clone of the snapshot",
        }
        record = self.changes.prepare(
            feature_id="change_rollback",
            scene_id=state.get("scene_id"),
            scene_revision=state.get("revision"),
            selection_fingerprint=state.get("selection_fingerprint"),
            operation=operation,
            impact=impact,
            backup_path=str(path),
            ttl=ttl,
        )
        return {
            "ok": True,
            "confirmation_token": record.token,
            "feature_id": record.feature_id,
            "scene_id": record.scene_id,
            "scene_revision": record.scene_revision,
            "selection_fingerprint": record.selection_fingerprint,
            "operation": record.operation.model_dump(mode="json"),
            "impact": impact,
            "snapshot_id": snapshot_id,
            "working_id": working_id,
            "expires_at": record.expires_at,
        }

    def rollback(self, confirmation_token: str, timeout: float = 120.0) -> ResultEnvelope:
        try:
            record = self.changes.load(confirmation_token)
        except SafetyError as exc:
            return self._host_error("change_rollback", ErrorCode.INVALID_REQUEST, str(exc))
        if record.feature_id != "change_rollback" or record.operation.name != "safety.rollback":
            return self._host_error(
                "change_rollback", ErrorCode.INVALID_REQUEST, "Token is not bound to a rollback operation"
            )
        return self.commit_change(confirmation_token, timeout)

    def _rollback_internal(self, snapshot_id: str) -> ResultEnvelope:
        path = self._snapshot_path(snapshot_id)
        if path is None:
            return self._host_error("change_rollback", ErrorCode.INVALID_REQUEST, "Unknown snapshot")
        working_id = str(uuid.uuid4())
        working_path = (self.paths.snapshots / f"{working_id}.working.casc").resolve()
        result = self.client.execute(
            "change_rollback",
            [
                Operation(
                    name="safety.rollback_internal",
                    arguments={"path": str(path), "working_id": working_id},
                )
            ],
            timeout=120,
            safety_context=SafetyContext(destructive=True),
        )
        result.snapshot_id = snapshot_id
        if result.ok:
            result = self._wait_for_open_scene(result, str(working_path), 120)
        self._remember_scene_result(result)
        return result

    def csc_mutate_allowed(self, chain: list[dict[str, Any]]) -> bool:
        if not chain:
            return False
        final = str(chain[-1].get("attr", "")).lower()
        if not final.startswith(MUTATION_VERBS):
            return False
        schema_methods = {
            method.lower()
            for feature in self._features
            if feature.family == "csc_api"
            for method in [feature.name.rsplit(".", 1)[-1]]
        }
        return final in schema_methods

    def _operation_is_mutating(self, name: str) -> bool:
        lowered = name.casefold()
        product_bindings = [item for item in PRODUCT_CATALOG.features if item.operation == name]
        if product_bindings:
            return any(item.mutation for item in product_bindings)
        return lowered not in {
            "system.status",
            "system.logs",
            "system.view_mode_get",
            "physics.auto_state",
            "physics.state",
            "rig.state",
            "rig.constraint_drivers",
            "generation.state",
            "system.tools",
            "system.introspect",
            "scene.summary",
            "scene.objects",
            "scene.list",
            "scene.validate",
            "object.hierarchy",
            "object.properties",
            "object.behaviors",
            "selection.get",
            "selection.filter",
            "timeline.get",
            "animation.transform_get",
            "layer.list",
            "animation.key_list",
            "animation.graph_query",
            "animation.cycle_query",
            "render.viewport_state",
            "render.camera_catalog",
        }

    @staticmethod
    def _host_error(
        feature_id: str, code: ErrorCode, message: str, mode: ExecutionMode = ExecutionMode.NATIVE
    ) -> ResultEnvelope:
        return ResultEnvelope(
            ok=False,
            feature_id=feature_id,
            execution_mode=mode,
            status="failed",
            error_code=code,
            error_message=message,
        )
