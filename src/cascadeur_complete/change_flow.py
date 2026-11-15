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
        "safety.rollback",
        "io.selection_groups_import",
        "rig.json_import",
        "rig.quick_rig",
    }
)


class ChangeFlowMixin:
    """CascadeurService methods; they rely on the service's state and helpers."""

    def prepare_change(
        self, feature_id: str, operation_name: str, arguments: dict[str, Any], ttl: float = 300.0, *, source_binding=None, execution_context=None
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
        if not self._operation_is_mutating(operation_name, arguments):
            return self._host_error(
                feature_id,
                ErrorCode.INVALID_REQUEST,
                "Read-only operations must be executed directly and cannot mint change tokens",
            ).model_dump(mode="json")
        status = self._checked_status(self.refresh_live())
        if not status.ok:
            return status.model_dump(mode="json")
        state = status.result
        if state.get("protocol_version") != "3.0":
            return self._host_error(feature_id, ErrorCode.UNSUPPORTED_VERSION,
                "PROTOCOL_MISMATCH: mutation requires the matching protocol-3 bridge").model_dump(mode="json")
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
        from .models import SourceBinding
        from .request_ledger import canonical_digest
        from .effects import classify_effect
        try:
            source_binding = SourceBinding.model_validate(source_binding)
        except (ValueError, TypeError):
            return self._host_error(feature_id, ErrorCode.INVALID_REQUEST,
                "BINDING_UNAVAILABLE: prepare requires a runtime-issued complete SourceBinding").model_dump(mode="json")
        checked = self.validate_source(source_binding, operation_name=operation_name, arguments=arguments)
        if not checked.ok:
            return checked.model_dump(mode="json")
        if not source_binding.complete or source_binding.scope.get("operation_arguments_digest") != canonical_digest(arguments):
            return self._host_error(feature_id, ErrorCode.INVALID_REQUEST,
                "BINDING_UNAVAILABLE: exact normalized operation arguments were not captured").model_dump(mode="json")
        # A checkpoint is a runtime-attested artifact, never an implicit untokened
        # save/open side effect of preparation.
        manifest = source_binding.scope.get("snapshot_manifest")
        backup_path = working_path = snapshot_id = None
        playhead_only = False
        if classify_effect(operation_name, arguments) in ("scene", "mixed"):
            if not isinstance(manifest, dict):
                return self._host_error(feature_id, ErrorCode.INVALID_REQUEST,
                    "CHECKPOINT_UNAVAILABLE: a verified isolated working clone and snapshot manifest are required").model_dump(mode="json")
            backup_path, working_path = manifest.get("path"), manifest.get("working_path")
            if (not backup_path or not working_path or Path(backup_path).resolve() == Path(working_path).resolve()
                    or manifest.get("document_lineage_id") != source_binding.binding.document_lineage_id
                    or manifest.get("working_scene_instance_id") != source_binding.binding.scene_instance_id
                    or not Path(backup_path).is_file()
                    or __import__("hashlib").sha256(Path(backup_path).read_bytes()).hexdigest() != manifest.get("sha256")):
                return self._host_error(feature_id, ErrorCode.INVALID_REQUEST,
                    "CHECKPOINT_UNAVAILABLE: snapshot hash, clone identity or lineage differs").model_dump(mode="json")
            snapshot_id = manifest.get("snapshot_id")
        state["scene_id"] = source_binding.binding.scene_instance_id
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
            selection_fingerprint=source_binding.binding.selection_digest,
            operation=Operation(name=operation_name, arguments=arguments),
            impact=impact,
            backup_path=backup_path,
            ttl=ttl,
            source_binding=source_binding,
            execution_context=execution_context,
            mutation_request_id=(execution_context or {}).get("request_id") or str(uuid.uuid4()),
            snapshot_manifest_id=canonical_digest(manifest) if manifest else None,
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
            try:
                consumed = self.changes.consumed(token)
                if consumed and consumed.schema_version == 3 and consumed.mutation_request_id:
                    return self.reconcile_consumed_change(token,
                        expected_request_id=consumed.mutation_request_id,
                        expected_execution_context=consumed.execution_context)
            except (SafetyError, ValueError):
                pass
            return self._host_error("change_commit", ErrorCode.INVALID_REQUEST, str(exc))
        if record.schema_version != 3 or record.source_binding is None:
            return self._host_error(record.feature_id, ErrorCode.UNSUPPORTED_VERSION, "PROTOCOL_MISMATCH: legacy change token cannot mutate")
        checked = self.validate_source(record.source_binding, operation_name=record.operation.name, arguments=record.operation.arguments)
        if not checked.ok:
            return checked
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
        result = self.client.execute(
            record.feature_id,
            [record.operation],
            scene_id=record.scene_id,
            expected_revision=None,
            timeout=timeout,
            request_id=record.mutation_request_id,
            source_binding=record.source_binding,
            execution_context=record.execution_context,
            safety_context=SafetyContext(
                destructive=True,
                confirmation_token=token,
                snapshot_required=False,
                selection_fingerprint=record.selection_fingerprint,
                allow_overwrite=bool(record.operation.arguments.get("allow_overwrite")),
            ),
        )
        result.snapshot_id = ((record.source_binding.scope.get("snapshot_manifest") or {}).get("snapshot_id")
                              if record.backup_path else None)
        result.operation_id = record.operation.name
        result.status = "outcome_unknown" if result.outcome == "outcome_unknown" else ("succeeded" if result.ok else "failed")
        result.scene_revision_before = record.scene_revision
        result.scene_revision_after = result.scene_revision
        if result.outcome == "outcome_unknown":
            result.recovery_state = "blocked_outcome_unknown"
            return result
        try:
            result = self._apply_host_postconditions(record, result, observed)
        except Exception as exc:
            result = result.model_copy(update={"ok": False, "error_code": ErrorCode.POSTCONDITION_FAILED,
                "error_message": f"Host postcondition failed: {exc}", "quality": "unverified"})
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
        elif record.backup_path and result.recovery_eligible:
            result = self._restore_failed_change(record, result)
        result.operation_id = record.operation.name
        result.status = "outcome_unknown" if result.outcome == "outcome_unknown" else ("succeeded" if result.ok else "failed")
        result.scene_revision_before = record.scene_revision
        result.scene_revision_after = result.scene_revision
        self._remember_scene_result(result)
        return result

    def reconcile_consumed_change(self, token: str, *, expected_request_id: str,
                                  expected_execution_context) -> ResultEnvelope:
        """Observe a consumed approval and finish only its conditional recovery.

        This is an execution-service continuation, not the read-only request
        reconciliation API. It cannot dispatch the approved original operation.
        Expired approvals remain authentic evidence for that original request.
        """
        try:
            record = self.changes.consumed(token)
            if (record is None or record.schema_version != 3 or record.source_binding is None
                    or not record.mutation_request_id
                    or record.mutation_request_id != expected_request_id
                    or record.execution_context != expected_execution_context):
                raise SafetyError("CONSUMED_CHANGE_BINDING_MISMATCH")
            original = self.client.queue.ledger.read_request(expected_request_id)
            if (original is None or original.get("request_id") != expected_request_id
                    or original.get("feature_id") != record.feature_id
                    or original.get("operations") != [record.operation.model_dump(mode="json")]
                    or original.get("source_binding") != record.source_binding.model_dump(mode="json")
                    or original.get("execution_context") != record.execution_context
                    or original.get("scene_id") != record.scene_id
                    or (original.get("safety_context") or {}).get("confirmation_token") != token):
                raise SafetyError("CONSUMED_CHANGE_REQUEST_MISMATCH")
            result = self.client.reconcile_request(expected_request_id)
            if result.request_id != expected_request_id:
                raise SafetyError("CONSUMED_CHANGE_RESULT_MISMATCH")
            if (result.phase == "terminal" and result.outcome == "failed_after_dispatch"
                    and result.recovery_eligible and record.backup_path):
                result = self._restore_failed_change(record, result)
            return result
        except (SafetyError, OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
            return self._host_error("change_commit", ErrorCode.INVALID_REQUEST,
                "Consumed change continuation blocked: " + str(exc)[:500])

    def commit_initial_checkpoint(self, grant, token: str, timeout: float = 120.0) -> ResultEnvelope:
        """Initial checkpoint uses only the exact persisted bootstrap grant."""
        try:
            from .stage_contracts import BootstrapGrant
            supplied = BootstrapGrant.model_validate(grant)
            try:
                record = self.changes.load(token)
            except SafetyError:
                record = self.changes.consumed(token)
            if (record.operation.name != "safety.bootstrap"
                    or record.mutation_request_id != supplied.request_id
                    or record.impact.get("bootstrap_grant") != supplied.model_dump(mode="json")):
                raise ValueError("BOOTSTRAP_GRANT_MISMATCH")
            if record.used:
                return self.reconcile_consumed_change(token,
                    expected_request_id=record.mutation_request_id,
                    expected_execution_context=record.execution_context)
            self.recipes.store.verify_bootstrap(supplied)
            return self.commit_change(token, timeout)
        except (ValueError, SafetyError) as exc:
            return self._host_error("snapshot", ErrorCode.INVALID_REQUEST, str(exc))

    def _restore_failed_change(self, record, failed: ResultEnvelope) -> ResultEnvelope:
        """Attempt one separately authorized recovery; retain the original failure."""
        if (failed.phase != "terminal" or failed.outcome != "failed_after_dispatch"
                or failed.dispatched is not True or not failed.recovery_eligible or failed.write_phase not in ("started", "completed")
                or failed.scene_after is None or failed.failure_kind == "guard_rejected_before_first_write"):
            failed.recovery_state = "not_eligible"
            return failed
        if record.operation.name in {"safety.rollback", "safety.rollback_internal"}:
            failed.recovery_state = "blocked_recursive_recovery"
            return failed
        from .recovery import RecoveryJournal, recovery_candidate, verify_snapshot, make_recovery_permit, recovery_succeeded
        from .request_ledger import canonical_digest
        try:
            journal = RecoveryJournal(self.paths, record.mutation_request_id)
            # Claim precedes any prepare/dispatch. An interrupted owner can only
            # be observed; an unknown attempt never gets a replacement request.
            if not journal.claim():
                result = journal.read("result")
                permit = journal.read("permit")
                if permit:
                    data = failed.result if isinstance(failed.result, dict) else {}
                    if (permit["original_request_id"] != record.mutation_request_id
                            or permit["snapshot_manifest_digest"] != record.snapshot_manifest_id
                            or canonical_digest(data.get("post_source_binding")) != permit["arguments"]["post_source_digest"]
                            or data.get("post_source_binding", {}).get("binding") != failed.scene_after.model_dump(mode="json")):
                        raise ValueError("RECOVERY_JOURNAL_TARGET_DIFFERS")
                if result:
                    if not permit or result["permit_digest"] != canonical_digest(permit):
                        raise ValueError("RECOVERY_JOURNAL_PERMIT_DIFFERS")
                    if result["state"] == "blocked_recovery_outcome_unknown":
                        # The immutable record describes what that owner knew,
                        # not a permanent verdict on a later original receipt.
                        # Reconcile only that same request; never prepare again.
                        observed = self.client.reconcile_request(permit["recovery_request_id"])
                        failed.recovery_state = ("recovered" if recovery_succeeded(observed, permit)
                            else "blocked_recovery_outcome_unknown" if observed.outcome == "outcome_unknown"
                            else "recovery_failed")
                    else:
                        failed.recovery_state = result["state"]
                elif permit:
                    observed = self.client.reconcile_request(permit["recovery_request_id"])
                    failed.recovery_state = "recovered" if recovery_succeeded(observed, permit) else "blocked_recovery_outcome_unknown"
                else:
                    failed.recovery_state = "blocked_recovery_owner_unresolved"
                return failed
            receipt = self.client.queue.ledger.read_receipt(record.mutation_request_id)
            if receipt is None:
                raise ValueError("RECOVERY_TERMINAL_RECEIPT_UNAVAILABLE")
            post, recovery, manifest, arguments = recovery_candidate(record, failed, receipt)
            if not self.validate_source(post).ok:
                raise ValueError("RECOVERY_POST_SOURCE_STALE")
            if not self.validate_source(recovery, operation_name="safety.rollback", arguments=arguments).ok:
                raise ValueError("RECOVERY_SOURCE_STALE")
            verify_snapshot(manifest, post, self.paths.snapshots, expected_digest=record.snapshot_manifest_id)
            permit = journal.write("permit", make_recovery_permit(record, failed, receipt, recovery, manifest, arguments))
            recovered = self._rollback_internal(manifest["snapshot_id"], source_binding=recovery,
                                                recovery_permit=permit, recovery_journal=journal)
            state = ("recovered" if recovery_succeeded(recovered, permit)
                     else "blocked_recovery_outcome_unknown" if recovered.outcome == "outcome_unknown"
                     else "recovery_failed")
            journal.write("result", {"state": state, "original_request_id": record.mutation_request_id,
                                      "permit_digest": canonical_digest(permit),
                                      "recovery_result": recovered.model_dump(mode="json")})
            failed.recovery_state = state
            failed.evidence.append(Evidence(kind="recovery", detail=f"{state}; request {permit['recovery_request_id']}",
                                            observed_at=time.time()))
        except (OSError, ValueError, AttributeError, TypeError, KeyError) as exc:
            failed.recovery_state = "blocked_recovery_guard"
            failed.warnings.append("Recovery was not confirmed: " + str(exc)[:500])
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

    def prepare_rollback(self, snapshot_id: str, ttl: float = 300.0, *, source_binding=None,
                         recovery_permit=None, recovery_journal=None) -> dict[str, Any]:
        from .models import SourceBinding
        from .recovery import RecoveryJournal, recovery_candidate, verify_snapshot, make_recovery_permit
        from .request_ledger import canonical_digest
        from types import SimpleNamespace
        try:
            source = SourceBinding.model_validate(source_binding)
            failed_id = source.scope.get("recovery", {}).get("failed_request_id")
            journal = recovery_journal or RecoveryJournal(self.paths, failed_id)
            original = self.client.queue.ledger.read_request(failed_id)
            receipt = self.client.queue.ledger.read_receipt(failed_id)
            if original is None or receipt is None or not receipt.terminal_result:
                raise ValueError("RECOVERY_TERMINAL_RECEIPT_UNAVAILABLE")
            original_source = SourceBinding.model_validate(original.get("source_binding"))
            manifest = original_source.scope.get("snapshot_manifest")
            record = SimpleNamespace(mutation_request_id=failed_id, source_binding=original_source,
                                     snapshot_manifest_id=canonical_digest(manifest),
                                     execution_context=original.get("execution_context"))
            failed = ResultEnvelope.model_validate({**receipt.terminal_result, "request_id": failed_id})
            post, issued, manifest, arguments = recovery_candidate(record, failed, receipt)
            if source != issued or str(snapshot_id) != manifest.get("snapshot_id"):
                raise ValueError("RECOVERY_SOURCE_OR_SNAPSHOT_DIFFERS")
            if not self.validate_source(post).ok or not self.validate_source(source,
                    operation_name="safety.rollback", arguments=arguments).ok:
                raise ValueError("RECOVERY_CURRENT_TARGET_CHANGED")
            verify_snapshot(manifest, post, self.paths.snapshots, expected_digest=record.snapshot_manifest_id)
            if recovery_permit is None:
                if not journal.claim():
                    raise ValueError("RECOVERY_ALREADY_CLAIMED: observe its original request")
                recovery_permit = journal.write("permit", make_recovery_permit(
                    record, failed, receipt, source, manifest, arguments))
            stored = journal.read("permit")
            if (stored != recovery_permit or stored["expires_at"] <= time.time()
                    or stored["source_binding"] != source.model_dump(mode="json")
                    or stored["snapshot_manifest_digest"] != canonical_digest(manifest)
                    or stored["arguments"] != arguments
                    or stored["original_receipt_digest"] != canonical_digest(receipt.model_dump(mode="json"))):
                raise ValueError("RECOVERY_PERMIT_INVALID_OR_EXPIRED")
            remaining = stored["expires_at"] - time.time()
            if remaining < 31:
                raise ValueError("RECOVERY_PERMIT_TOO_CLOSE_TO_EXPIRY")
            context = {**(record.execution_context or {}), "request_id": stored["recovery_request_id"],
                       "recovery_of": failed_id, "recovery_permit_digest": canonical_digest(stored)}
            prepared = self.prepare_change("change_rollback", "safety.rollback", arguments,
                min(ttl, remaining - 1), source_binding=source, execution_context=context)
            if prepared.get("ok"):
                journal.write("prepared", {"original_request_id": failed_id,
                    "recovery_request_id": stored["recovery_request_id"], "permit_digest": canonical_digest(stored),
                    "confirmation_token": prepared["confirmation_token"]})
            return prepared
        except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
            return self._host_error("change_rollback", ErrorCode.INVALID_REQUEST,
                "RECOVERY_UNAVAILABLE: " + str(exc)[:500]).model_dump(mode="json")

    def rollback(self, confirmation_token: str, timeout: float = 120.0) -> ResultEnvelope:
        try:
            try:
                record = self.changes.load(confirmation_token)
            except SafetyError:
                record = self.changes.consumed(confirmation_token)
                if record is None:
                    raise SafetyError("Unknown rollback confirmation token")
        except SafetyError as exc:
            return self._host_error("change_rollback", ErrorCode.INVALID_REQUEST, str(exc))
        if record.feature_id != "change_rollback" or record.operation.name != "safety.rollback":
            return self._host_error(
                "change_rollback", ErrorCode.INVALID_REQUEST, "Token is not bound to a rollback operation"
            )
        if record.used:
            return self.client.reconcile_request(record.mutation_request_id)
        return self.commit_change(confirmation_token, timeout)

    def _rollback_internal(self, snapshot_id: str, *, source_binding=None, recovery_permit=None,
                           recovery_journal=None) -> ResultEnvelope:
        if recovery_permit is None or recovery_journal is None:
            return self._host_error("change_rollback", ErrorCode.CONFIRMATION_REQUIRED,
                "Internal rollback requires the source-bound signed recovery permit")
        prepared = self.prepare_rollback(snapshot_id, source_binding=source_binding,
            recovery_permit=recovery_permit, recovery_journal=recovery_journal)
        if not prepared.get("ok"):
            return ResultEnvelope.model_validate(prepared)
        from .request_ledger import canonical_digest
        try:
            recovery_journal.write("dispatch", {"recovery_request_id": recovery_permit["recovery_request_id"],
                                                 "permit_digest": canonical_digest(recovery_permit)})
        except FileExistsError:
            return self.client.reconcile_request(recovery_permit["recovery_request_id"])
        return self.commit_change(prepared["confirmation_token"], timeout=120)
