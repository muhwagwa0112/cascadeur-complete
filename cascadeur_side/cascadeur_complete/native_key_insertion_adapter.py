"""Source-bound insertion on an owned checkpoint, qualified in this process.

This adapter is deliberately separate from recipe topology authorization. It
does not advertise key_topology_write or issue locator-planner attestations.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

from . import guarded_runtime as guards
from . import native_key_insertion as core
from .native_scene_adapter import NativeSceneAdapter

OPERATION = "motion.key_topology_insert"
_ADAPTER = None


def _arguments(arguments):
    fields = {"object_id", "layer_id", "additions", "space", "allow_key_insertion", "max_added_keys"}
    if (not isinstance(arguments, dict) or set(arguments) != fields
            or arguments["space"] != "local" or arguments["allow_key_insertion"] is not True
            or type(arguments["max_added_keys"]) is not int or not 1 <= arguments["max_added_keys"] <= 8
            or not isinstance(arguments["additions"], list)
            or not 1 <= len(arguments["additions"]) <= arguments["max_added_keys"]
            or any(not isinstance(arguments[key], str) or not arguments[key] for key in ("object_id", "layer_id"))):
        raise ValueError("INVALID_WRITE_SCOPE: explicit local insertion target, opt-in and one-to-eight key budget required")
    return arguments


class NativeKeyInsertionAdapter(NativeSceneAdapter):
    adapter_id = "native-independent-absent-position-keys-v1"
    file_bootstrap = False

    def __init__(self, proof):
        super().__init__(core._freeze({"operations": [OPERATION], "insertion_qualification": proof}))
        self.qualified_capabilities = {}
        self._completed = {}
        self._failure_records = {}

    def _qualified(self):
        proof = core.qualification()
        if proof is None or json.loads(self.evidence_bytes)["insertion_qualification"] != proof:
            raise ValueError("KEY_INSERTION_UNQUALIFIED: exact current-process insertion qualification required")
        return proof

    @staticmethod
    def _workspace(scene):
        from .native_adapters import _WORKSPACES
        identity = guards.scene_instance(scene)
        manifest = _WORKSPACES.get(identity["scene_instance_id"])
        if (not manifest or manifest.get("native_completion") != "observed"
                or manifest.get("working_scene_instance_id") != identity["scene_instance_id"]
                or manifest.get("document_lineage_id") != identity["document_lineage_id"]
                or manifest.get("runtime_epoch") != guards.RUNTIME_EPOCH
                or manifest.get("adapter_fingerprint") != guards.LOADED_FINGERPRINT
                or Path(str(scene.get_path_name())).resolve() != Path(manifest["working_path"]).resolve()):
            raise ValueError("CHECKPOINT_REQUIRED: exact native-owned working scene required")
        backup = Path(manifest["path"])
        if (not 0 < manifest["bytes"] <= 2 * 1024 * 1024
                or backup.resolve() == Path(manifest["working_path"]).resolve()
                or backup.stat().st_size != manifest["bytes"]
                or hashlib.sha256(backup.read_bytes()).hexdigest() != manifest["sha256"]):
            raise ValueError("CHECKPOINT_CHANGED: immutable checkpoint bytes differ")
        return copy.deepcopy(manifest)

    def _state(self, scene, scope):
        from . import runtime as rt
        self._qualified()
        if rt._scene_view() is not scene:
            raise ValueError("SCENE_CHANGED: insertion source must be the active scene")
        if scope.get("operation_name") != OPERATION:
            raise ValueError("INVALID_WRITE_SCOPE: insertion operation required")
        args = _arguments(scope.get("operation_arguments"))
        workspace = self._workspace(scene)
        key = (guards.scene_instance(scene)["scene_instance_id"], guards.digest(args))
        completed = self._completed.get(key)
        projection = self.read_scene(scene)
        # A completed topology no longer satisfies absent-key preconditions.
        # Admit only the exact private successful projection for successor
        # capture; this never grants a second insertion dispatch.
        if completed is not None:
            record = core._SOURCES.get(completed["private_source_id"])
            if record is None or workspace != completed["scope"]["snapshot_manifest"]:
                raise ValueError("SCENE_CHANGED: completed insertion projection no longer exact")
            if record["state"] in {"prepared", "dispatching"}:
                # The first-write guard may read the sealed before; it must not
                # acquire a second execution right from this consumed entry.
                if projection != record["before"]:
                    raise ValueError("SCENE_CHANGED: insertion before changed")
            elif record["state"] == "completed_failure":
                failure = core.validate_failure_observation(scene, record["bound_request"], record["failure_observation_ref"])
                if not failure["scope_contained"] or record["after"] != projection:
                    raise ValueError("KEY_INSERTION_FAILED_AFTER_OUTSIDE_SOURCE_SCOPE")
            elif record["state"] != "completed" or record.get("after") != projection:
                raise ValueError("KEY_INSERTION_RECONCILIATION_REQUIRED: consumed unresolved insertion")
            return projection, copy.deepcopy(completed["scope"]), True
        before, driver, additions = core._inspect(scene, args["object_id"], args["layer_id"], args["additions"])
        required = {"operation_name": OPERATION, "operation_arguments": copy.deepcopy(args),
            "operation_arguments_digest": guards.digest(args), "adapter_id": self.adapter_id,
            "object_ids": [args["object_id"]], "layer_ids": [row["id"] for row in before["layers"]],
            "frames": [0, before["frames"] - 1], "input_files": [],
            "write_frames": [row["frame"] for row in additions], "channel_space": "local",
            "value_space": "native_scene_units", "position_data_id": driver["data_id"],
            "position_closure": driver["position_closure"], "contract": core.CONTRACT,
            "insertion_qualification_digest": guards.digest(self._qualified()), "snapshot_manifest": workspace}
        return before, required, False

    def required_scope(self, scene, scope):
        return self._state(scene, scope)[1]

    def capture(self, scene, scope):
        projection, required, _ = self._state(scene, scope)
        if required != scope:
            raise ValueError("INCOMPLETE_CAPTURE: exact insertion closure required")
        return {"coverage_complete": True, "authored_projection": projection, "sample_projection": projection}

    def execute(self, scene, arguments, request):
        source = request.get("source_binding")
        guards.assert_source(scene, source, operation_name=OPERATION, arguments=arguments)
        _, scope, completed = self._state(scene, source["scope"])
        if completed:
            raise ValueError("KEY_INSERTION_SOURCE_CONSUMED: completed insertion cannot be replayed")
        private = core.prepare_insertion(scene, arguments["object_id"], arguments["layer_id"], arguments["additions"])
        key = (guards.scene_instance(scene)["scene_instance_id"], guards.digest(arguments))
        # Consume before entering native code, for success, known failure and
        # unknown alike. Read/capture rights never recreate dispatch rights.
        self._completed[key] = {"scope": copy.deepcopy(scope), "private_source_id": private["source_id"]}
        core._SOURCES[private["source_id"]]["bound_request"] = request
        from .native_key_insertion_evidence import bind_execution
        bind_execution(scene, arguments, request, private)
        try:
            result = core.insert_positions(scene, private, before_write=lambda: guards.assert_source(
                scene, source, operation_name=OPERATION, arguments=arguments))
        except Exception:
            record = core._SOURCES[private["source_id"]]
            ref = record.get("failure_observation_ref")
            if record["state"] == "completed_failure" and isinstance(ref, str):
                try:
                    base = core.validate_failure_observation(scene, request, ref)
                    failure = copy.deepcopy(base)
                    post = self.capture_known_failed_after(scene, request, ref) if base["scope_contained"] else None
                    failure["post_source_digest"] = None if post is None else guards.digest(post)
                    evidence = core._failure_lifetime_contract()
                    if (post is not None and failure["completion"] == "completed"
                            and evidence.get("recovery_contract") == "independent_insertion_exact_snapshot_scope_v1"):
                        failure["recovery_contract_digest"] = guards.digest({"evidence": evidence,
                            "post_source_digest": guards.digest(post), "scope": source["scope"]})
                    self._failure_records[ref] = {"bytes": core._freeze(failure), "core_bytes": core._freeze(base),
                        "post_source": copy.deepcopy(post), "request": request, "source_id": private["source_id"]}
                    guards.bind_failure_observation(guards.current_adapter_attempt(), ref)
                    if failure["recovery_contract_digest"] is not None:
                        self.verification["recovery_after_partial_write_observed"] = {
                            "runtime_fingerprint": guards.LOADED_FINGERPRINT, "installed_build": self.observed_build(),
                            "known_effect_classes": ["scene"], "evidence_sha256": guards.digest(failure),
                            "request_digest": guards.digest(request), "post_source_digest": guards.digest(post),
                            "contract": "independent_insertion_exact_snapshot_scope_v1"}
                except Exception as observation_error:
                    record["failure_binding_error"] = str(observation_error)[:2000]
            raise
        result["observed_postconditions"] = ["key_topology_inserted"]
        result["recipe_topology_authorization"] = "not_issued"
        return result, []

    def capture_known_failed_after(self, scene, request, record_ref):
        failure = core.validate_failure_observation(scene, request, record_ref)
        if not failure["scope_contained"]:
            raise ValueError("KEY_INSERTION_FAILED_AFTER_OUTSIDE_SOURCE_SCOPE")
        original = request["source_binding"]
        post = guards.capture_source(scene, original["scope"], original["inputs_digest"],
            selection_digest=original["binding"].get("selection_digest"))
        if post["sample_digest"] != failure["actual_after_digest"]:
            raise ValueError("KEY_INSERTION_FAILED_AFTER_CHANGED")
        return post

    def failure_observation_revoked(self, record_ref):
        entry = self._failure_records.get(record_ref)
        if entry is None:
            return True
        source = core._SOURCES.get(entry["source_id"])
        base = json.loads(entry["core_bytes"])
        return (source is None or source["state"] != "completed_failure"
            or source["trace"] != base["native_transaction"]
            or base["adapter_callback_generation"] != core._CALLBACK_GENERATION)

    def validate_failure_observation(self, scene, request, record_ref):
        entry = self._failure_records.get(record_ref)
        if entry is None or entry["request"] is not request or self.failure_observation_revoked(record_ref):
            raise ValueError("KEY_INSERTION_FAILURE_OBSERVATION_UNAVAILABLE")
        base = core.validate_failure_observation(scene, request, record_ref)
        if core._freeze(base) != entry["core_bytes"]:
            raise ValueError("KEY_INSERTION_FAILURE_OBSERVATION_CHANGED")
        failure = json.loads(entry["bytes"])
        post = entry["post_source"]
        if post is not None:
            guards.assert_source(scene, post, operation_name=OPERATION, arguments=request["operations"][0]["arguments"])
            if guards.digest(post) != failure["post_source_digest"] or post["sample_digest"] != failure["actual_after_digest"]:
                raise ValueError("KEY_INSERTION_FAILED_AFTER_CHANGED")
        elif failure["post_source_digest"] is not None or failure["scope_contained"]:
            raise ValueError("KEY_INSERTION_FAILED_AFTER_SOURCE_UNAVAILABLE")
        return failure

    def prepare_recovery_binding(self, scene, request, result):
        selected = guards.selected_effect_for_request(request, scene)
        private = (selected or {}).get("private_failure_observation") or {}
        failure = self.validate_failure_observation(scene, request, private.get("reference"))
        post = (result.get("result") or {}).get("post_source_binding")
        attestation = self.verification.get("recovery_after_partial_write_observed") or {}
        if (failure["completion"] != "completed" or failure["recovery_contract_digest"] is None
                or private.get("digest") != guards.digest(failure) or attestation.get("evidence_sha256") != guards.digest(failure)
                or attestation.get("request_digest") != guards.digest(request)
                or guards.digest(post) != failure["post_source_digest"]
                or (result.get("result") or {}).get("failed_after_observation") != selected):
            raise ValueError("KEY_INSERTION_RECOVERY_ATTESTATION_UNAVAILABLE")
        return super().prepare_recovery_binding(scene, request, result)


def register_key_insertion_adapter():
    """Explicit registration from immutable private actual SDK proof only."""
    global _ADAPTER
    proof = core.qualification()
    if proof is None:
        raise ValueError("KEY_INSERTION_UNQUALIFIED: run explicit disposable qualification first")
    if _ADAPTER is None:
        _ADAPTER = NativeKeyInsertionAdapter(proof)
    _ADAPTER._qualified()
    guards.register_adapter(OPERATION, _ADAPTER)
    return {"operation": OPERATION, "adapter_id": _ADAPTER.adapter_id,
            "insertion_qualification_digest": guards.digest(proof), "recipe_topology_write": False}
