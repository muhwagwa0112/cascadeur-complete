"""Conditional recovery into a new owned tab; never replay the failed request.

Checkpoint recording and adapter qualification are code-owned calls. No wire
operation can supply a trusted projection, enable an adapter, or substitute an
unknown outcome for the authenticated terminal partial-write failure.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

import csc

from . import guarded_runtime as guards
from .native_scene_reader import read_scene

_CHECKPOINTS = {}
_CHECKPOINT_ANCHORS = {}
_RESTORED = {}
_COMPLETED = {}
_ARGUMENTS = {"path", "snapshot_id", "snapshot_manifest_digest", "post_source_digest",
              "failed_request_id", "working_id"}


def _copy(value):
    return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))


def _uuid(value):
    if not isinstance(value, str) or str(uuid.UUID(value)) != value:
        raise ValueError("RECOVERY_REQUEST_ID_INVALID")
    return value


def _owned_path(path, run_id=None):
    from . import runtime as rt
    value = Path(path)
    if not value.is_absolute() or value.suffix.lower() != ".casc":
        raise ValueError("RECOVERY_PATH_NOT_OWNED")
    root = rt.runtime_root().resolve()
    resolved = value.resolve()
    allowed = resolved.is_relative_to(root / "snapshots")
    if run_id is not None:
        run = root / "state" / "runs" / _uuid(run_id)
        allowed = allowed or resolved.parent in (run / "workspace", run / "checkpoints")
    # Reject junction/symlink aliases as well as an escaped resolved path.
    if not allowed or str(resolved) != str(value):
        raise ValueError("RECOVERY_PATH_NOT_OWNED")
    for parent in (value, *value.parents):
        if parent == root:
            break
        if parent.is_symlink() or (parent.exists() and getattr(parent.lstat(), "st_file_attributes", 0) & 0x400):
            raise ValueError("RECOVERY_PATH_ALIAS_FORBIDDEN")
    return value


def remember_checkpoint(scene, manifest, projection, *, run_id=None, immutable_anchor=None,
                        checkpoint_projection=None, checkpoint_observation=None, serialization_observation=None):
    """Anchor a native-completed checkpoint immediately after its observed save.

    The checkpoint executor must first install the exact manifest in
    native_adapters._WORKSPACES. This record survives only this runtime epoch.
    """
    from .native_adapters import _WORKSPACES, _locked_input
    guards.assert_loaded_package()
    identity = dict(guards.scene_instance(scene))
    if (not isinstance(manifest, dict) or manifest.get("runtime_epoch") != guards.RUNTIME_EPOCH
            or manifest.get("adapter_fingerprint") != guards.LOADED_FINGERPRINT
            or manifest.get("native_completion") != "observed"
            or manifest.get("working_scene_instance_id") != identity["scene_instance_id"]
            or manifest.get("document_lineage_id") != identity["document_lineage_id"]
            or manifest.get("authored_projection_digest") != guards.digest(projection)
            or _WORKSPACES.get(identity["scene_instance_id"]) != manifest
            or read_scene(scene) != projection):
        raise ValueError("RECOVERY_CHECKPOINT_NOT_OBSERVED")
    _uuid(manifest.get("snapshot_id"))
    path = _owned_path(manifest["path"], run_id)
    working = _owned_path(manifest["working_path"], run_id)
    if path == working or not working.is_file():
        raise ValueError("RECOVERY_CHECKPOINT_NOT_OBSERVED")
    with _locked_input(path) as observed:
        if (observed["sha256"] != manifest.get("sha256")
                or observed["length"] != manifest.get("bytes") or not observed["length"]):
            raise ValueError("SNAPSHOT_BYTES_CHANGED")
    raw = json.dumps(projection, ensure_ascii=False, allow_nan=False).encode()
    if len(raw) > 64 * 1024**2:
        raise ValueError("RECOVERY_PROJECTION_BUDGET_EXCEEDED")
    fixed = None
    if manifest.get("schema_version") == 2:
        from .native_serialization import require_anchor, verify_serialization_observation
        require_anchor(immutable_anchor)
        verify_serialization_observation(checkpoint_observation, anchor=immutable_anchor,
                                         projection=checkpoint_projection)
        verify_serialization_observation(serialization_observation, anchor=immutable_anchor, projection=projection)
        fixed_fields = {"reference_projection_digest": immutable_anchor.reference_projection_digest,
            "checkpoint_observed_projection_digest": guards.digest(checkpoint_projection),
            "checkpoint_file": {"schema_version": 1, "path": manifest["path"], "sha256": manifest["sha256"],
                                "length": manifest["bytes"]},
            "serialization_policy_digest": checkpoint_observation["serialization_policy_digest"],
            "runtime_epoch": guards.RUNTIME_EPOCH, "adapter_fingerprint": guards.LOADED_FINGERPRINT}
        anchor_digest = guards.digest(fixed_fields)
        if (manifest.get("checkpoint_anchor_digest") != anchor_digest
                or manifest.get("reference_projection_digest") != immutable_anchor.reference_projection_digest
                or manifest.get("checkpoint_observed_projection_digest") != guards.digest(checkpoint_projection)
                or manifest.get("working_projection_digest") != guards.digest(projection)
                or manifest.get("serialization_observation_digest") != guards.digest(serialization_observation)):
            raise ValueError("RECOVERY_IMMUTABLE_ANCHOR_CHANGED")
        fixed = {"fields": fixed_fields, "immutable_anchor": immutable_anchor,
                 "checkpoint_projection": _copy(checkpoint_projection),
                 "checkpoint_observation": _copy(checkpoint_observation)}
        prior = _CHECKPOINT_ANCHORS.get(anchor_digest)
        if prior is not None and prior != fixed:
            raise ValueError("RECOVERY_IMMUTABLE_ANCHOR_CONFLICT")
        if prior is not None:
            fixed = prior
        _CHECKPOINT_ANCHORS[anchor_digest] = fixed
    elif manifest.get("schema_version") != 1:
        raise ValueError("RECOVERY_MANIFEST_SCHEMA_UNSUPPORTED")
    record = {"manifest": _copy(manifest), "projection": _copy(projection),
              "projection_digest": guards.digest(projection), "run_id": run_id}
    if fixed is not None:
        record["fixed_anchor"] = fixed
    key = guards.digest(manifest)
    prior = _CHECKPOINTS.get(key)
    if prior is not None and prior != record:
        raise ValueError("RECOVERY_CHECKPOINT_ANCHOR_CONFLICT")
    _CHECKPOINTS[key] = record


def _anchor(arguments):
    from .native_adapters import _locked_input
    if not isinstance(arguments, dict) or set(arguments) != _ARGUMENTS:
        raise ValueError("RECOVERY_ARGUMENTS_INVALID")
    for field in ("snapshot_id", "failed_request_id", "working_id"):
        _uuid(arguments[field])
    record = _CHECKPOINTS.get(arguments["snapshot_manifest_digest"])
    if record is None:
        raise ValueError("RECOVERY_CHECKPOINT_ANCHOR_UNAVAILABLE")
    manifest = record["manifest"]
    if manifest.get("schema_version") == 2:
        fixed = record.get("fixed_anchor")
        if fixed is None or _CHECKPOINT_ANCHORS.get(manifest.get("checkpoint_anchor_digest")) is not fixed:
            raise ValueError("RECOVERY_IMMUTABLE_ANCHOR_UNAVAILABLE")
    if (arguments["path"] != manifest["path"] or arguments["snapshot_id"] != manifest["snapshot_id"]
            or manifest["runtime_epoch"] != guards.RUNTIME_EPOCH
            or manifest["adapter_fingerprint"] != guards.LOADED_FINGERPRINT):
        raise ValueError("RECOVERY_CHECKPOINT_CHANGED")
    path = _owned_path(manifest["path"], record["run_id"])
    with _locked_input(path) as observed:
        if observed["sha256"] != manifest["sha256"] or observed["length"] != manifest["bytes"]:
            raise ValueError("SNAPSHOT_BYTES_CHANGED")
    return record


def _recovery_context(arguments):
    return {"failed_request_id": arguments["failed_request_id"],
            "post_source_digest": arguments["post_source_digest"],
            "snapshot_manifest_digest": arguments["snapshot_manifest_digest"]}


def prepare_recovery_binding(scene, request, result, *, adapter=None):
    """Issue an exact restoration scope only for the observed terminal failure.

    Called by runtime before it seals that original terminal event. Execution
    separately requires the event to have become durable and authenticated.
    """
    from .native_adapters import _WORKSPACES
    if (result.get("outcome") != "failed_after_dispatch" or result.get("dispatched") is not True
            or result.get("write_phase") not in ("started", "completed")
            or result.get("failure_kind") == "guard_rejected_before_first_write"
            or len(request.get("operations", ())) != 1
            or request["operations"][0]["name"] in {"safety.rollback", "safety.rollback_internal"}):
        raise ValueError("RECOVERY_NOT_ELIGIBLE")
    post = (result.get("result") or {}).get("post_source_binding")
    guards.assert_source(scene, post)
    original = request.get("source_binding") or {}
    manifest = original.get("scope", {}).get("snapshot_manifest")
    identity = guards.scene_instance(scene)
    if (not isinstance(manifest, dict) or _WORKSPACES.get(identity["scene_instance_id"]) != manifest
            or post["binding"] != result.get("scene_after")
            or original.get("binding") != result.get("scene_before")
            or post["binding"]["scene_instance_id"] != original.get("binding", {}).get("scene_instance_id")
            or post.get("scope") != original.get("scope")
            or post.get("inputs_digest") != original.get("inputs_digest")):
        raise ValueError("RECOVERY_TARGET_CHANGED")
    arguments = {"path": manifest["path"], "snapshot_id": manifest["snapshot_id"],
                 "snapshot_manifest_digest": guards.digest(manifest), "post_source_digest": guards.digest(post),
                 "failed_request_id": _uuid(request["request_id"]), "working_id": str(uuid.uuid4())}
    _anchor(arguments)
    adapter = adapter or guards._ADAPTERS.get("safety.rollback")
    if not isinstance(adapter, NativeCheckpointRestoreAdapter):
        raise ValueError("RECOVERY_ADAPTER_UNVERIFIED")
    scope = adapter.required_scope(scene, {"operation_name": "safety.rollback", "operation_arguments": arguments})
    return guards._capture_with_adapter(scene, scope, post["inputs_digest"], post["sample_digest"],
                                        post["binding"].get("selection_digest"), adapter)


def _read_signed(path, key):
    from . import runtime as rt
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 8 * 1024**2:
        raise ValueError("RECOVERY_SIGNED_RECORD_UNAVAILABLE")
    value = json.loads(path.read_text(encoding="utf-8"))
    signature = value.get("mac")
    if (not isinstance(signature, str) or len(signature) != 64
            or not hmac.compare_digest(signature, rt._sign_message(value, key))):
        raise ValueError("RECOVERY_SIGNED_RECORD_INVALID")
    return value


def _original_terminal(root, request_id):
    from . import runtime as rt
    key = rt._bridge_key(root)
    directory = root / "state" / "request_records" / _uuid(request_id)
    request = _read_signed(directory / "request.json", key)
    rt._verify_message(request, key)
    if request.get("request_id") != request_id:
        raise ValueError("RECOVERY_ORIGINAL_REQUEST_INVALID")
    terminal = None
    context = request.get("execution_context") or {}
    paths = sorted((directory / "runtime_events").glob("*.json"))
    if len(paths) > 32:
        raise ValueError("RECOVERY_RECEIPT_BUDGET_EXCEEDED")
    for sequence, path in enumerate(paths, 1):
        item = _read_signed(path, key)
        if (terminal is not None or item.get("seq") != sequence or item.get("request_id") != request_id
                or item.get("request_digest") != guards.digest(request)
                or item.get("operation_digest") != guards.digest(request["operations"])
                or item.get("session_id") != request.get("session_id")
                or item.get("host_instance_id") != request.get("host_instance_id", "")
                or any(item.get(field) != context.get(field) for field in ("run_id", "step_id", "attempt_id", "lease_epoch"))
                or (item.get("dispatched") and item.get("runtime_epoch") != request.get("runtime_epoch"))):
            raise ValueError("RECOVERY_ORIGINAL_RECEIPT_INVALID")
        if item.get("phase") == "terminal":
            if not isinstance(item.get("terminal_result"), dict) or guards.digest(item["terminal_result"]) != item.get("result_digest"):
                raise ValueError("RECOVERY_ORIGINAL_RESULT_INVALID")
            terminal = item
    return request, terminal


def _assert_no_unresolved(root, instance_id, excluded):
    from . import runtime as rt
    paths = list((root / "state" / "request_records").glob("*/request.json"))
    if len(paths) > 4096:
        raise ValueError("RECOVERY_REQUEST_BUDGET_EXCEEDED")
    key = rt._bridge_key(root)
    for path in paths:
        if path.parent.name in excluded:
            continue
        request = _read_signed(path, key)
        if (request.get("source_binding") or {}).get("binding", {}).get("scene_instance_id") != instance_id:
            continue
        if not any(rt._operation_is_mutating(op) for op in request.get("operations", ())):
            continue
        _, terminal = _original_terminal(root, request["request_id"])
        if terminal is None or terminal.get("outcome") == "outcome_unknown":
            raise ValueError("RECOVERY_UNRESOLVED_REQUEST")


def _permit(request, arguments):
    from . import runtime as rt
    root = rt.runtime_root()
    failed_id = arguments["failed_request_id"]
    directory = root / "state" / "recovery" / _uuid(failed_id)
    key = (root / "state" / "confirmation.key").read_bytes()
    if len(key) < 32:
        raise ValueError("RECOVERY_SIGNING_KEY_UNAVAILABLE")
    permit = _read_signed(directory / "permit.json", key)
    context = request.get("execution_context") or {}
    original, receipt = _original_terminal(root, failed_id)
    if (permit.get("domain") != "cascadeur-recovery-v1" or permit.get("record_type") != "permit"
            or permit.get("schema_version") != 1 or permit.get("original_request_id") != failed_id
            or permit.get("recovery_request_id") != request.get("request_id")
            or permit.get("arguments") != arguments or permit.get("source_binding") != request.get("source_binding")
            or permit.get("snapshot_manifest_digest") != arguments["snapshot_manifest_digest"]
            or guards.digest(permit.get("snapshot_manifest")) != arguments["snapshot_manifest_digest"]
            or not isinstance(permit.get("expires_at"), (int, float)) or permit["expires_at"] < time.time()
            or context != {**(permit.get("original_execution_context") or {}), "request_id": request["request_id"],
                           "recovery_of": failed_id, "recovery_permit_digest": guards.digest(permit)}
            or permit.get("original_execution_context") != original.get("execution_context")
            or receipt is None or permit.get("original_receipt_digest") != guards.digest(receipt)):
        raise ValueError("RECOVERY_PERMIT_INVALID")
    failed = receipt["terminal_result"]
    data = failed.get("result") or {}
    post = data.get("post_source_binding")
    if (receipt.get("outcome") != "failed_after_dispatch" or receipt.get("dispatched") is not True
            or receipt.get("recovery_eligible") is not True or receipt.get("effect_class") not in {"scene", "mixed"}
            or receipt.get("write_phase") not in {"started", "completed"}
            or failed.get("outcome") != "failed_after_dispatch" or failed.get("recovery_eligible") is not True
            or failed.get("dispatched") is not True or failed.get("write_phase") not in {"started", "completed"}
            or failed.get("failure_kind") == "guard_rejected_before_first_write"
            or data.get("recovery_source_binding") != request.get("source_binding")
            or not isinstance(post, dict) or guards.digest(post) != arguments["post_source_digest"]
            or failed.get("scene_after") != post.get("binding")
            or receipt.get("scene_after") != post.get("binding")
            or failed.get("scene_before") != (original.get("source_binding") or {}).get("binding")
            or receipt.get("scene_before") != failed.get("scene_before")):
        raise ValueError("RECOVERY_NOT_ELIGIBLE")
    _assert_no_unresolved(root, post["binding"]["scene_instance_id"], {failed_id, request["request_id"]})
    return permit, receipt


@dataclass(frozen=True)
class NativeRestoreResult:
    target: object
    before: dict
    after: dict
    saved: dict
    failed_digest: str
    project_load: dict
    restored_projection: dict
    serialization_observation: dict | None
    successor_manifest: dict

    def __iter__(self):
        # Retain the previous six-value diagnostic API; actual projection is
        # explicit and is never inferred from the checkpoint's reference hash.
        return iter((self.target, self.before, self.after, self.saved, self.failed_digest, self.project_load))


def _restore_native(scene, anchor, working):
    """The same complete native primitive is used by qualification and dispatch."""
    from .native_adapters import _WORKSPACES, _save_observed
    from .native_project_io import load_project_copy
    original_projection, original_path = read_scene(scene), str(scene.get_path_name())
    def original_unchanged():
        if read_scene(scene) != original_projection or str(scene.get_path_name()) != original_path:
            raise ValueError("RECOVERY_FAILED_SCENE_CHANGED")
    before = dict(guards.scene_instance(scene))
    manager = csc.app.get_application().get_scene_manager()
    if manager.current_scene() is not scene or working.exists():
        raise ValueError("RECOVERY_CURRENT_SCENE_OR_TARGET_CHANGED")
    path = Path(anchor["manifest"]["path"])
    fixed = anchor.get("fixed_anchor")
    serialization = None
    try:
        target, load_observation = load_project_copy(path, working,
            expected_sha256=anchor["manifest"]["sha256"], expected_length=anchor["manifest"]["bytes"],
            source_guard=original_unchanged)
        if fixed is not None:
            from .native_serialization import compare_with_private_policy
            compare_with_private_policy(target, fixed["immutable_anchor"], phase="project_load")
        elif read_scene(target) != anchor["projection"]:
            raise ValueError("RECOVERY_NATIVE_READBACK_DIFFERS")
        from .incident_admission import assert_request_admission
        assert_request_admission()
        original_unchanged()
        saved = _save_observed(target, working)
        if fixed is not None:
            serialization = compare_with_private_policy(target, fixed["immutable_anchor"], phase="restored_save")
        restored_projection = read_scene(target)
        actual_path = str(target.get_path_name())
        if ((fixed is None and restored_projection != anchor["projection"])
                or (serialization is not None and restored_projection != serialization.projection) or not actual_path
                or Path(actual_path).resolve() != working.resolve()):
            raise ValueError("RECOVERY_NATIVE_SAVE_READBACK_DIFFERS")
    finally:
        # Creation/loading may activate the new tab. Keep failed attempts for
        # reconciliation, but restore the source tab even when readback fails.
        manager.set_current_scene(scene)
    if read_scene(scene) != original_projection or str(scene.get_path_name()) != original_path:
        raise ValueError("RECOVERY_FAILED_SCENE_CHANGED")
    guards.link_clone(scene, target)
    after = dict(guards.scene_instance(target))
    if after["scene_instance_id"] == before["scene_instance_id"] or after["document_lineage_id"] != before["document_lineage_id"]:
        raise ValueError("RECOVERY_SUCCESSOR_IDENTITY_INVALID")
    successor_manifest = {**anchor["manifest"], "working_path": str(working),
                          "working_scene_instance_id": after["scene_instance_id"]}
    if fixed is not None:
        successor_manifest.update(working_file_sha256=saved["sha256"], working_file_bytes=saved["length"],
            working_projection_digest=guards.digest(restored_projection),
            authored_projection_digest=guards.digest(restored_projection),
            serialization_observation_digest=guards.digest(serialization.as_dict()))
    _WORKSPACES[after["scene_instance_id"]] = successor_manifest
    kwargs = {} if fixed is None else {"immutable_anchor": fixed["immutable_anchor"],
        "checkpoint_projection": fixed["checkpoint_projection"],
        "checkpoint_observation": fixed["checkpoint_observation"], "serialization_observation": serialization.as_dict()}
    remember_checkpoint(target, successor_manifest, restored_projection, run_id=anchor["run_id"], **kwargs)
    return NativeRestoreResult(target, before, after, saved, guards.digest(original_projection), load_observation,
        restored_projection, None if serialization is None else serialization.as_dict(), successor_manifest)


def qualify_restore(scene, manifest, *, run_id=None):
    """Explicit code-owned SDK probe on an already owned, anchored checkpoint.

    This exercises no user failure or request, and cannot issue a recovery
    permit. Only the observed new-tab native primitive is qualified here;
    original adapters must separately observe their partial-write contract.
    """
    from .native_adapters import _WORKSPACES
    guards.assert_loaded_package()
    if _WORKSPACES.get(guards.scene_instance(scene)["scene_instance_id"]) != manifest:
        raise ValueError("RECOVERY_QUALIFICATION_SCENE_NOT_OWNED")
    anchor = _CHECKPOINTS.get(guards.digest(manifest))
    if anchor is None or anchor["run_id"] != run_id:
        raise ValueError("RECOVERY_CHECKPOINT_ANCHOR_UNAVAILABLE")
    current = read_scene(scene)
    path = _owned_path(manifest["path"], run_id)
    working = _owned_path(str(path.parent / (str(uuid.uuid4()) + ".working.casc")), run_id)
    def unchanged():
        if (read_scene(scene) != current
                or _WORKSPACES.get(guards.scene_instance(scene)["scene_instance_id"]) != manifest):
            raise ValueError("RECOVERY_QUALIFICATION_SOURCE_CHANGED")
    guards.before_write(unchanged)
    restored = _restore_native(scene, anchor, working)
    target, before, after, saved, failed_digest, load_observation = restored
    manager = csc.app.get_application().get_scene_manager()
    try:
        manager.set_current_scene(target)
        if manager.current_scene() is not target or read_scene(target) != restored.restored_projection:
            raise ValueError("RECOVERY_SUCCESSOR_ACTIVATION_UNOBSERVED")
    finally:
        manager.set_current_scene(scene)
    if manager.current_scene() is not scene or read_scene(scene) != current:
        raise ValueError("RECOVERY_QUALIFICATION_SOURCE_CHANGED")
    observation = {"schema_version": 1, "kind": "owned-checkpoint-restore-qualification",
        "installed_build": NativeCheckpointRestoreAdapter.observed_build(),
        "runtime_fingerprint": guards.LOADED_FINGERPRINT, "runtime_epoch": guards.RUNTIME_EPOCH,
        "dispatch_semantics": "synchronous_no_yield", "completion": "native_observed",
        "snapshot_manifest_digest": guards.digest(manifest), "restored_projection_digest": guards.digest(restored.restored_projection),
        "failed_projection_digest": failed_digest, "scene_before": before, "scene_after": after,
        "working_file": saved, "project_load": load_observation}
    if restored.serialization_observation is not None:
        observation.update(checkpoint_anchor_digest=manifest["checkpoint_anchor_digest"],
            reference_projection_digest=manifest["reference_projection_digest"],
            serialization_observation_digest=guards.digest(restored.serialization_observation))
    _COMPLETED[guards.digest(observation)] = _copy(observation)
    guards.finish_write()
    guards.observe_effect("safety.rollback", "completed", scene_before=before, scene_after=after, detail=observation)
    return json.dumps(observation, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()


class NativeCheckpointRestoreAdapter:
    """Candidate until an actual restore has produced local observation evidence."""

    def __init__(self, evidence_bytes=None, evidence_path=None):
        from .native_adapters import installed_build
        self.evidence_bytes = evidence_bytes or b"{}"
        observed = json.loads(self.evidence_bytes)
        key = guards.digest(observed)
        qualified = bool(observed) and _COMPLETED.get(key) == observed
        if evidence_bytes is not None and not qualified:
            raise ValueError("RECOVERY_QUALIFICATION_NOT_OBSERVED_IN_THIS_EPOCH")
        self.verification = {"runtime_fingerprint": guards.LOADED_FINGERPRINT,
            "installed_build": installed_build(), "identity_stable": True,
            "operations": ["safety.rollback"] if qualified else [],
            "dispatch_semantics": "synchronous_no_yield",
            "evidence_sha256": hashlib.sha256(self.evidence_bytes).hexdigest()}
        if evidence_path is not None:
            if Path(evidence_path).read_bytes() != self.evidence_bytes:
                raise ValueError("RECOVERY_QUALIFICATION_BYTES_CHANGED")
            self.verification["evidence_path"] = str(evidence_path)
        if qualified:
            self.verification["rollback_completion_observed"] = {
                "installed_build": installed_build(), "runtime_fingerprint": guards.LOADED_FINGERPRINT,
                "dispatch_semantics": "synchronous_no_yield",
                "evidence_sha256": self.verification["evidence_sha256"]}
        self._observed = observed if qualified else None

    @staticmethod
    def observed_build():
        from .native_adapters import installed_build
        return installed_build()

    def observed_evidence(self):
        if self._observed is None:
            raise ValueError("RECOVERY_QUALIFICATION_NOT_OBSERVED")
        return json.dumps(self._observed, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()

    def required_scope(self, scene, scope):
        from .native_adapters import _WORKSPACES
        if scope.get("operation_name") != "safety.rollback":
            raise ValueError("RECOVERY_OPERATION_INVALID")
        arguments = scope.get("operation_arguments")
        anchor = _anchor(arguments)
        identity = guards.scene_instance(scene)
        workspace = _WORKSPACES.get(identity["scene_instance_id"])
        restored = _RESTORED.get(identity["scene_instance_id"])
        if workspace != anchor["manifest"] and restored != guards.digest(arguments):
            raise ValueError("RECOVERY_CURRENT_SCENE_NOT_OWNED")
        if (not workspace or workspace.get("runtime_epoch") != guards.RUNTIME_EPOCH
                or workspace.get("working_scene_instance_id") != identity["scene_instance_id"]
                or workspace.get("document_lineage_id") != identity["document_lineage_id"]):
            raise ValueError("RECOVERY_CURRENT_SCENE_CHANGED")
        projection = read_scene(scene)
        return {"operation_name": "safety.rollback", "operation_arguments": arguments,
                "operation_arguments_digest": guards.digest(arguments), "adapter_id": "native-checkpoint-restore-v1",
                "object_ids": [row["id"] for row in projection["objects"]],
                "layer_ids": [row["id"] for row in projection["layers"]], "frames": [0, projection["frames"] - 1],
                "input_files": [{"schema_version": 1, "path": anchor["manifest"]["path"],
                                 "sha256": anchor["manifest"]["sha256"], "length": anchor["manifest"]["bytes"]}],
                "snapshot_manifest": _copy(workspace), "recovery": _recovery_context(arguments)}

    def capture(self, scene, scope):
        projection = read_scene(scene)
        return {"coverage_complete": True, "authored_projection": projection, "sample_projection": projection}

    def _assert_source(self, scene, source, arguments):
        if (not isinstance(source, dict) or guards._ISSUED_SOURCES.get(guards.digest(source)) != source
                or source.get("adapter_fingerprint") != guards.LOADED_FINGERPRINT or source.get("complete") is not True
                or source.get("binding", {}).get("runtime_epoch") != guards.RUNTIME_EPOCH
                or source["binding"]["scene_instance_id"] != guards.scene_instance(scene)["scene_instance_id"]
                or source.get("scope", {}).get("operation_arguments") != arguments):
            raise ValueError("RECOVERY_SOURCE_NOT_ISSUED")
        actual = guards._capture_with_adapter(scene, source["scope"], source["inputs_digest"], source["sample_digest"],
                                              source["binding"].get("selection_digest"), self)
        if actual != source:
            raise ValueError("RECOVERY_SOURCE_CHANGED")

    def approve_successor(self, request, source, successor, result, effect):
        """Accept only this executor's completed, permit-bound new-tab effect."""
        data = result.get("result") or {}
        observation = data.get("recovery_observation")
        if not isinstance(observation, dict):
            return False
        before, after = source.get("binding") or {}, successor.get("binding") or {}
        before_identity = {key: before.get(key) for key in ("scene_instance_id", "document_lineage_id")}
        after_identity = {key: after.get(key) for key in ("scene_instance_id", "document_lineage_id")}
        manifest = source.get("scope", {}).get("snapshot_manifest")
        if isinstance(manifest, dict) and manifest.get("schema_version") == 2:
            next_manifest = successor.get("scope", {}).get("snapshot_manifest")
            next_anchor = _CHECKPOINTS.get(guards.digest(next_manifest))
            original_anchor = _CHECKPOINTS.get(guards.digest(manifest))
            if (not next_anchor or not original_anchor
                    or next_anchor.get("fixed_anchor") is not original_anchor.get("fixed_anchor")
                    or observation.get("checkpoint_anchor_digest") != manifest.get("checkpoint_anchor_digest")
                    or observation.get("reference_projection_digest") != manifest.get("reference_projection_digest")
                    or observation.get("restored_projection_digest") != next_anchor["projection_digest"]
                    or observation.get("serialization_observation_digest") != next_manifest.get("serialization_observation_digest")
                    or next_manifest.get("working_projection_digest") != next_anchor["projection_digest"]):
                return False
        return bool(
            _COMPLETED.get(guards.digest(observation)) == observation
            and effect.get("completion") == "completed"
            and effect.get("scene_before") == before_identity and effect.get("scene_after") == after_identity
            and observation.get("scene_before") == before_identity and observation.get("scene_after") == after_identity
            and before.get("scene_instance_id") != after.get("scene_instance_id")
            and before.get("document_lineage_id") == after.get("document_lineage_id")
            and observation.get("runtime_epoch") == guards.RUNTIME_EPOCH
            and observation.get("runtime_fingerprint") == guards.LOADED_FINGERPRINT
            and observation.get("installed_build") == self.observed_build()
            and observation.get("recovery_request_id") == request.get("request_id")
            and observation.get("original_request_id") == (request.get("execution_context") or {}).get("recovery_of")
            and observation.get("permit_digest") == (request.get("execution_context") or {}).get("recovery_permit_digest")
            and observation.get("snapshot_manifest_digest") == guards.digest(manifest)
            and observation.get("source_before_digest") == guards.digest(source)
            and observation.get("source_after_digest") == guards.digest(successor)
            and data.get("native_completion") == "observed")

    def execute(self, scene, arguments, request):
        from . import runtime as rt
        guards.assert_loaded_package()
        if request.get("operations") != [{"name": "safety.rollback", "arguments": arguments}]:
            raise ValueError("RECOVERY_OPERATION_INVALID")
        source = request.get("source_binding")
        self._assert_source(scene, source, arguments)
        anchor = _anchor(arguments)
        permit, receipt = _permit(request, arguments)
        if permit["snapshot_manifest"] != anchor["manifest"]:
            raise ValueError("RECOVERY_CHECKPOINT_CHANGED")
        path = _owned_path(anchor["manifest"]["path"], anchor["run_id"])
        working = _owned_path(str(path.parent / (arguments["working_id"] + ".working.casc")), anchor["run_id"])
        if working.exists():
            raise ValueError("RECOVERY_WORKING_TARGET_NOT_FRESH")
        manager = csc.app.get_application().get_scene_manager()
        if manager.current_scene() is not scene:
            raise ValueError("RECOVERY_ACTIVE_SCENE_CHANGED")
        # Exclusive marker survives every failure. A new request cannot retry
        # a partially completed restore with the same signed authorization.
        marker = rt.runtime_root() / "state" / "recovery" / arguments["failed_request_id"] / "native-restore.claim"
        fd = os.open(marker, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "w", encoding="ascii") as stream:
            stream.write(request["request_id"])
            stream.flush()
            os.fsync(stream.fileno())
        guards.before_write(lambda: self._assert_source(scene, source, arguments))
        target = None
        try:
            restored = _restore_native(scene, anchor, working)
            target, before, after, saved, failed_digest, load_observation = restored
            _RESTORED[after["scene_instance_id"]] = guards.digest(arguments)
            scope = self.required_scope(target, source["scope"])
            successor = guards._capture_with_adapter(target, scope, source["inputs_digest"], guards.digest(restored.restored_projection), None, self)
            manager.set_current_scene(target)
            if manager.current_scene() is not target or read_scene(target) != restored.restored_projection:
                raise ValueError("RECOVERY_SUCCESSOR_ACTIVATION_UNOBSERVED")
        except Exception:
            # Never reload or modify the failed scene, remove unknown effects,
            # or retry. Keep any newly created tab/file for reconciliation.
            if target is not None and manager.current_scene() is target:
                manager.set_current_scene(scene)
            raise
        observation = {"schema_version": 1, "installed_build": self.observed_build(),
            "runtime_fingerprint": guards.LOADED_FINGERPRINT, "runtime_epoch": guards.RUNTIME_EPOCH,
            "dispatch_semantics": "synchronous_no_yield", "completion": "native_observed",
            "original_request_id": arguments["failed_request_id"], "recovery_request_id": request["request_id"],
            "original_receipt_digest": guards.digest(receipt), "permit_digest": guards.digest(permit),
            "snapshot_manifest_digest": guards.digest(anchor["manifest"]),
            "restored_projection_digest": guards.digest(restored.restored_projection), "failed_projection_digest": failed_digest,
            "scene_before": before, "scene_after": after, "working_file": saved, "project_load": load_observation,
            "source_before_digest": guards.digest(source), "source_after_digest": guards.digest(successor)}
        if restored.serialization_observation is not None:
            observation.update(schema_version=2, checkpoint_anchor_digest=anchor["manifest"]["checkpoint_anchor_digest"],
                reference_projection_digest=anchor["manifest"]["reference_projection_digest"],
                serialization_observation_digest=guards.digest(restored.serialization_observation))
        _COMPLETED[guards.digest(observation)] = _copy(observation)
        self._observed = _copy(observation)
        guards.finish_write()
        guards.observe_effect("safety.rollback", "completed", scene_before=before, scene_after=after, detail=observation)
        return {"native_completion": "observed", "restored_from": str(path), "working_path": str(working),
                "working_file": saved, "restored_projection_digest": guards.digest(restored.restored_projection),
                "snapshot_manifest_digest": guards.digest(anchor["manifest"]), "recovery_observation": observation,
                "source_binding": successor, "post_source_binding": successor}, []
