"""One-attempt, signed recovery permits for authenticated partial-write failures.

This module never manufactures a target binding or invokes a native loader.
The runtime's verified adapter must issue the exact rollback source first.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from pathlib import Path

from .models import SourceBinding
from .queue_auth import sign_payload, verify_payload
from .request_ledger import canonical_digest


class RecoveryError(ValueError):
    pass


def _json(value):
    return value.model_dump(mode="json") if hasattr(value, "model_dump") else value


def verify_snapshot(manifest, source: SourceBinding, snapshots: Path, *, expected_digest=None):
    if not isinstance(manifest, dict) or not manifest.get("snapshot_id"):
        raise RecoveryError("SNAPSHOT_MANIFEST_UNAVAILABLE")
    if expected_digest is not None and canonical_digest(manifest) != expected_digest:
        raise RecoveryError("SNAPSHOT_MANIFEST_CHANGED")
    snapshot_id = str(uuid.UUID(str(manifest["snapshot_id"])))
    if snapshot_id != manifest["snapshot_id"]:
        raise RecoveryError("SNAPSHOT_ID_INVALID")
    root = snapshots.resolve()
    path = Path(str(manifest.get("path", "")))
    run_root = root.parent / "state" / "runs"
    def owned(candidate):
        if not candidate.is_absolute() or candidate.suffix.lower() != ".casc":
            return False
        resolved = candidate.resolve()
        if candidate != resolved or any(
                parent.is_symlink() or (parent.exists() and getattr(parent.lstat(), "st_file_attributes", 0) & 0x400)
                for parent in (candidate, *candidate.parents)):
            return False
        if resolved.is_relative_to(root):
            return True
        if resolved.is_relative_to(run_root):
            parts = resolved.relative_to(run_root).parts
            try:
                return (len(parts) == 3 and str(uuid.UUID(parts[0])) == parts[0]
                        and parts[1] in ("workspace", "checkpoints"))
            except ValueError:
                return False
        return False
    if (not owned(path) or not path.is_file()
            or manifest.get("document_lineage_id") != source.binding.document_lineage_id
            or manifest.get("working_scene_instance_id") != source.binding.scene_instance_id):
        raise RecoveryError("SNAPSHOT_TARGET_OR_LINEAGE_CHANGED")
    working = Path(str(manifest.get("working_path", "")))
    if (not owned(working)
            or working.resolve() == path.resolve() or not working.is_file()):
        raise RecoveryError("FAILED_WORKING_SCENE_UNAVAILABLE")
    digest, count = hashlib.sha256(), 0
    with path.open("rb") as stream:
        before = os.fstat(stream.fileno())
        while block := stream.read(1024 * 1024):
            count += len(block)
            if count > 2 * 1024**3:
                raise RecoveryError("SNAPSHOT_BUDGET_EXCEEDED")
            digest.update(block)
        after = os.fstat(stream.fileno())
    if ((before.st_size, before.st_mtime_ns, before.st_ctime_ns) !=
            (after.st_size, after.st_mtime_ns, after.st_ctime_ns)
            or not count or digest.hexdigest() != manifest.get("sha256")
            or ("bytes" in manifest and count != manifest["bytes"])):
        raise RecoveryError("SNAPSHOT_BYTES_CHANGED")
    return path


def recovery_candidate(record, failed, receipt):
    """Cross-check host failure against its authenticated original terminal event."""
    terminal = receipt.terminal_result or {}
    if (failed.phase != "terminal" or failed.outcome != "failed_after_dispatch"
            or failed.dispatched is not True or not failed.recovery_eligible
            or failed.write_phase not in ("started", "completed")
            or failed.failure_kind == "guard_rejected_before_first_write"
            or failed.scene_after is None
            or receipt.phase != "terminal" or receipt.outcome != "failed_after_dispatch"
            or receipt.dispatched is not True or receipt.effect_class not in ("scene", "mixed")
            or receipt.write_phase not in ("started", "completed")
            or receipt.failure_kind == "guard_rejected_before_first_write"
            or terminal.get("phase") != "terminal" or terminal.get("outcome") != "failed_after_dispatch"
            or terminal.get("dispatched") is not True or terminal.get("write_phase") not in ("started", "completed")
            or terminal.get("failure_kind") == "guard_rejected_before_first_write"
            or terminal.get("recovery_eligible") is not True
            or failed.request_id != record.mutation_request_id
            or receipt.request_id != record.mutation_request_id
            or terminal.get("request_id", receipt.request_id) != receipt.request_id
            or _json(failed.scene_after) != _json(receipt.scene_after)):
        raise RecoveryError("RECOVERY_NOT_ELIGIBLE")
    data = failed.result if isinstance(failed.result, dict) else {}
    runtime_data = terminal.get("result") or {}
    if data.get("post_source_binding") != runtime_data.get("post_source_binding"):
        raise RecoveryError("FAILED_POST_SOURCE_CHANGED")
    if data.get("recovery_source_binding") != runtime_data.get("recovery_source_binding"):
        raise RecoveryError("RECOVERY_SOURCE_CHANGED")
    post = SourceBinding.model_validate(data.get("post_source_binding"))
    recovery = SourceBinding.model_validate(data.get("recovery_source_binding"))
    if (not post.complete or post.binding != failed.scene_after or record.source_binding is None
            or failed.scene_before != record.source_binding.binding
            or receipt.scene_before != record.source_binding.binding
            or post.scope != record.source_binding.scope
            or post.inputs_digest != record.source_binding.inputs_digest
            or post.adapter_fingerprint != record.source_binding.adapter_fingerprint
            or post.binding.runtime_epoch != record.source_binding.binding.runtime_epoch
            or post.binding.scene_instance_id != record.source_binding.binding.scene_instance_id
            or post.binding.document_lineage_id != record.source_binding.binding.document_lineage_id):
        raise RecoveryError("FAILED_TARGET_CHANGED")
    manifest = record.source_binding.scope.get("snapshot_manifest")
    if (not isinstance(manifest, dict) or canonical_digest(manifest) != record.snapshot_manifest_id
            or getattr(record, "backup_path", manifest.get("path")) != manifest.get("path")):
        raise RecoveryError("SNAPSHOT_MANIFEST_CHANGED")
    args = validate_recovery_source(recovery, post, manifest, receipt.request_id)
    return post, recovery, manifest, args


def validate_recovery_source(source, post, manifest, failed_request_id):
    source, post = SourceBinding.model_validate(source), SourceBinding.model_validate(post)
    scope = source.scope
    args = scope.get("operation_arguments")
    binding = source.binding
    if (not source.complete or scope.get("operation_name") != "safety.rollback"
            or not post.complete or not isinstance(args, dict)
            or set(args) != {"path", "snapshot_id", "working_id", "failed_request_id", "snapshot_manifest_digest", "post_source_digest"}
            or scope.get("operation_arguments_digest") != canonical_digest(args)
            or source.adapter_fingerprint != post.adapter_fingerprint
            or binding.runtime_epoch != post.binding.runtime_epoch
            or binding.scene_instance_id != post.binding.scene_instance_id
            or binding.document_lineage_id != post.binding.document_lineage_id
            or scope.get("snapshot_manifest") != manifest
            or scope.get("recovery") != {"failed_request_id": failed_request_id,
                "post_source_digest": canonical_digest(_json(post)),
                "snapshot_manifest_digest": canonical_digest(manifest)}
            or args.get("failed_request_id") != failed_request_id
            or args.get("snapshot_manifest_digest") != canonical_digest(manifest)
            or args.get("post_source_digest") != canonical_digest(_json(post))
            or args.get("path") != manifest.get("path")
            or args.get("snapshot_id") != manifest.get("snapshot_id")):
        raise RecoveryError("RECOVERY_TARGET_BINDING_INVALID")
    working_id = str(uuid.UUID(str(args.get("working_id"))))
    working_path = Path(manifest["path"]).parent / (working_id + ".working.casc")
    if working_id != args["working_id"] or working_path.exists():
        raise RecoveryError("RECOVERY_WORKING_TARGET_NOT_FRESH")
    return args


class RecoveryJournal:
    """Signed immutable records; a claimed attempt is observed, never replayed."""
    def __init__(self, paths, original_request_id):
        request_id = str(uuid.UUID(str(original_request_id)))
        if request_id != original_request_id:
            raise RecoveryError("RECOVERY_REQUEST_ID_INVALID")
        self.directory = paths.state / "recovery" / request_id
        self.key = paths.confirmation_key.read_bytes()
        if len(self.key) < 32:
            raise RecoveryError("RECOVERY_SIGNING_KEY_UNAVAILABLE")

    def read(self, name):
        path = self.directory / (name + ".json")
        if not path.is_file():
            return None
        if path.stat().st_size > 8 * 1024**2:
            raise RecoveryError("RECOVERY_RECORD_BUDGET_EXCEEDED")
        value = json.loads(path.read_text(encoding="utf-8"))
        verify_payload(value, self.key)
        if (value.get("domain") != "cascadeur-recovery-v1" or value.get("record_type") != name
                or value.get("original_request_id") != self.directory.name):
            raise RecoveryError("RECOVERY_RECORD_DOMAIN_INVALID")
        return value

    def write(self, name, value):
        self.directory.mkdir(parents=True, exist_ok=True)
        value = {**value, "domain": "cascadeur-recovery-v1", "record_type": name,
                 "original_request_id": self.directory.name, "mac": ""}
        value["mac"] = sign_payload(value, self.key)
        path = self.directory / (name + ".json")
        temporary = path.with_name("." + path.name + "." + uuid.uuid4().hex)
        try:
            with temporary.open("x", encoding="utf-8") as stream:
                json.dump(value, stream, sort_keys=True, separators=(",", ":"), allow_nan=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.link(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
        return value

    def claim(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(self.directory / "attempt.claim", os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            return False
        with os.fdopen(fd, "w") as stream:
            stream.write(str(time.time()))
            stream.flush()
            os.fsync(stream.fileno())
        return True


def make_recovery_permit(record, failed, receipt, recovery, manifest, arguments):
    return {"schema_version": 1, "original_request_id": record.mutation_request_id,
            "original_receipt_digest": canonical_digest(_json(receipt)),
            "original_failure_digest": canonical_digest(_json(failed)),
            "snapshot_manifest": manifest, "snapshot_manifest_digest": canonical_digest(manifest),
            "source_binding": _json(recovery), "arguments": arguments,
            "recovery_request_id": str(uuid.uuid4()), "expires_at": time.time() + 120,
            "original_execution_context": record.execution_context}


def recovery_succeeded(result, permit):
    source = SourceBinding.model_validate(permit["source_binding"])
    data = result.result if isinstance(result.result, dict) else {}
    expected_working = str(Path(permit["snapshot_manifest"]["path"]).parent /
                           (permit["arguments"]["working_id"] + ".working.casc"))
    verified = (result.ok and result.phase == "terminal" and result.outcome == "succeeded"
            and result.request_id == permit["recovery_request_id"]
            and result.receipt_id == permit["recovery_request_id"]
            and result.dispatched is True and result.write_phase == "completed"
            and result.scene_after is not None
            and result.scene_after.document_lineage_id == source.binding.document_lineage_id
            and result.scene_after.runtime_epoch == source.binding.runtime_epoch
            and result.scene_after.scene_instance_id != source.binding.scene_instance_id
            and data.get("restored_from") == permit["snapshot_manifest"]["path"]
            and data.get("working_path") == expected_working)
    if not verified:
        return False
    observation = data.get("recovery_observation")
    saved = data.get("working_file")
    manifest = permit["snapshot_manifest"]
    # An observed native save may serialize different bytes. Its full readback
    # contract is mandatory; matching bytes alone must not downgrade it to the
    # older copy-only protocol when native completion evidence is missing.
    if observation is None and (manifest.get("native_completion") == "observed" or "authored_projection_digest" in manifest):
        return False
    if observation is not None:
        try:
            successor = SourceBinding.model_validate(data.get("post_source_binding"))
        except (TypeError, ValueError):
            return False
        projection = manifest.get("authored_projection_digest")
        before_identity = {key: getattr(source.binding, key) for key in ("scene_instance_id", "document_lineage_id")}
        after_identity = {key: getattr(successor.binding, key) for key in ("scene_instance_id", "document_lineage_id")}
        successor_manifest = {**manifest, "working_path": expected_working,
                              "working_scene_instance_id": successor.binding.scene_instance_id}
        if (not isinstance(observation, dict) or not isinstance(saved, dict)
                or not isinstance(projection, str) or len(projection) != 64
                or any(character not in "0123456789abcdef" for character in projection)
                or data.get("native_completion") != "observed" or not successor.complete
                or successor.binding != result.scene_after
                or result.scene_before != source.binding
                or successor.binding.scope_digest != canonical_digest(successor.scope)
                or successor.inputs_digest != source.inputs_digest
                or successor.adapter_fingerprint != source.adapter_fingerprint
                or successor.scope.get("snapshot_manifest") != successor_manifest
                or successor.scope.get("operation_name") != "safety.rollback"
                or successor.scope.get("operation_arguments") != permit["arguments"]
                or successor.scope.get("operation_arguments_digest") != canonical_digest(permit["arguments"])
                or successor.scope.get("recovery") != source.scope.get("recovery")
                or data.get("source_binding") != _json(successor)
                or successor.sample_digest != projection or data.get("restored_projection_digest") != projection
                or data.get("snapshot_manifest_digest") != canonical_digest(permit["snapshot_manifest"])
                or observation.get("completion") != "native_observed"
                or observation.get("schema_version") != 1 or saved.get("schema_version") != 1
                or observation.get("scene_before") != before_identity or observation.get("scene_after") != after_identity
                or observation.get("dispatch_semantics") != "synchronous_no_yield"
                or observation.get("runtime_epoch") != source.binding.runtime_epoch
                or observation.get("runtime_fingerprint") != source.adapter_fingerprint
                or observation.get("original_request_id") != permit["original_request_id"]
                or observation.get("recovery_request_id") != result.request_id
                or observation.get("original_receipt_digest") != permit["original_receipt_digest"]
                or observation.get("permit_digest") != canonical_digest(permit)
                or observation.get("snapshot_manifest_digest") != canonical_digest(permit["snapshot_manifest"])
                or observation.get("restored_projection_digest") != projection
                or observation.get("working_file") != saved or saved.get("path") != expected_working
                or observation.get("source_before_digest") != canonical_digest(_json(source))
                or observation.get("source_after_digest") != canonical_digest(_json(successor))):
            return False
    path = Path(expected_working)
    if (not path.is_absolute() or path != path.resolve() or not path.is_file()
            or any(parent.is_symlink() or (parent.exists() and getattr(parent.lstat(), "st_file_attributes", 0) & 0x400)
                   for parent in (path, *path.parents))):
        return False
    digest, count = hashlib.sha256(), 0
    with path.open("rb") as stream:
        before = os.fstat(stream.fileno())
        while block := stream.read(1024 * 1024):
            count += len(block)
            if count > 2 * 1024**3:
                return False
            digest.update(block)
        after = os.fstat(stream.fileno())
    if ((before.st_size, before.st_mtime_ns, before.st_ctime_ns) !=
            (after.st_size, after.st_mtime_ns, after.st_ctime_ns)):
        return False
    if observation is not None:
        return count > 0 and count == saved.get("length") and digest.hexdigest() == saved.get("sha256")
    return count > 0 and digest.hexdigest() == permit["snapshot_manifest"]["sha256"]
