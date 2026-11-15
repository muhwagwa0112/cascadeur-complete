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
            if (record is None or record["state"] != "completed" or record.get("after") != projection
                    or workspace != completed["scope"]["snapshot_manifest"]):
                raise ValueError("SCENE_CHANGED: completed insertion projection no longer exact")
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
        from .native_key_insertion_evidence import bind_execution
        bind_execution(scene, arguments, request, private)
        result = core.insert_positions(scene, private, before_write=lambda: guards.assert_source(
            scene, source, operation_name=OPERATION, arguments=arguments))
        key = (guards.scene_instance(scene)["scene_instance_id"], guards.digest(arguments))
        self._completed[key] = {"scope": copy.deepcopy(scope), "private_source_id": private["source_id"]}
        result["observed_postconditions"] = ["key_topology_inserted"]
        result["recipe_topology_authorization"] = "not_issued"
        return result, []


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
