"""Protected changes: snapshot and token on prepare, one bound execution on commit, rollback."""

from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import Any

from .host_postconditions import add_postconditions
from .models import (
    ErrorCode,
    Evidence,
    Operation,
    ResultEnvelope,
    SafetyContext,
)
from .safety import SafetyError, validate_local_input_path, validate_local_path

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


class ChangeFlowMixin:
    """CascadeurService methods; they rely on the service's state and helpers."""

    def prepare_change(
        self, feature_id: str, operation_name: str, arguments: dict[str, Any], ttl: float = 300.0
    ) -> dict[str, Any]:
        build_error = self._supported_build_error(feature_id)
        if build_error:
            return build_error.model_dump(mode="json")
        feature = self.feature(feature_id)
        gate_error = self._feature_gate_error(feature, operation_name, arguments)
        if gate_error:
            return gate_error.model_dump(mode="json")
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
        status = self._checked_status(self.refresh_live())
        if not status.ok:
            return status.model_dump(mode="json")
        state = status.result
        # The live status may change the license (or tools) the first gate saw, e.g.
        # a cached Pro license on a machine that now reports Basic: gate again.
        feature = self.feature(feature_id)
        gate_error = self._feature_gate_error(feature, operation_name, arguments)
        if gate_error:
            return gate_error.model_dump(mode="json")
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
                        bool(arguments.get("allow_overwrite")) or not path_policy["require_confirmation_for_overwrite"]
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
            post_snapshot = self._checked_status(self.refresh_live(bind_to_cached=True))
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
        status = self._checked_status(self.refresh_live())
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
        observed = self._observe_before_commit(record, timeout)
        if record.operation.name == "system.ui_file_flow":
            result = self._execute_ui_file_flow(record, timeout, observed.output)
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
            result = self._apply_host_postconditions(record, result, observed)
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
            return self._host_error("change_rollback", ErrorCode.INVALID_REQUEST, "Unknown snapshot").model_dump(
                mode="json"
            )
        status = self._checked_status(self.refresh_live())
        if not status.ok:
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
