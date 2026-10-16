"""Exact, version-registered Cascadeur file flows: an action id plus the file dialog it owns."""

from __future__ import annotations

import time
from pathlib import Path
from threading import Thread
from typing import Any

from .host_postconditions import add_postconditions
from .models import (
    ErrorCode,
    Evidence,
    ExecutionMode,
    Operation,
    ResultEnvelope,
    SafetyContext,
)
from .uia import (
    UIAutomationError,
    cancel_file_flow,
    cancel_owned_file_dialogs,
    complete_export_video_form,
    complete_file_dialog,
    finish_export_video_form,
    resolve_optional_rig_mode_helper,
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


def expected_ui_flow(feature_id: str, arguments: dict[str, Any]) -> dict[str, Any] | None:
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


class UiFileFlowMixin:
    """CascadeurService methods; they rely on the service's state and helpers."""

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
