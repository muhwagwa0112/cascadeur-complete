"""Code-owned checkpoint/evaluation adapter using the complete native reader."""
from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path

import csc

from . import guarded_runtime as guards
from .native_scene_reader import read_scene

_EVALUATIONS = {}


def finalize_evaluation(scene, request, result, receipt):
    """Seal only the completed SDK evaluation whose terminal event is durable."""
    if request.get("operations") != [{"name": "animation.interpolation_refresh", "arguments": {}}]:
        return
    instance = guards.scene_instance(scene)["scene_instance_id"]
    observed = _EVALUATIONS.get(instance)
    source = (result.get("result") or {}).get("post_source_binding")
    if (not observed or not request.get("request_id") or observed.get("request_id") != request["request_id"]
            or not result.get("ok") or result.get("outcome") != "succeeded"
            or receipt.get("phase") != "terminal" or receipt.get("outcome") != "succeeded"
            or receipt.get("request_digest") != guards.digest(request)
            or receipt.get("result_digest") != guards.digest(result)
            or not isinstance(source, dict) or source.get("sample_digest") != observed["projection_digest"]
            or source.get("binding", {}).get("scene_instance_id") != instance):
        return
    observed["evaluation_receipt_digest"] = guards.digest(receipt)
    observed["post_source_digest"] = guards.digest(source)


class NativeSceneAdapter:
    read_scene = staticmethod(read_scene)
    adapter_id = "native-model-assets-v1"
    file_bootstrap = True

    def __init__(self, evidence_bytes, evidence_path=None):
        from .native_adapters import installed_build
        evidence = json.loads(evidence_bytes)
        self.evidence_bytes = evidence_bytes
        self.verification = {"runtime_fingerprint": guards.LOADED_FINGERPRINT,
            "installed_build": installed_build(), "identity_stable": True,
            "operations": evidence.get("operations", []), "dispatch_semantics": "synchronous_no_yield",
            "evidence_sha256": hashlib.sha256(evidence_bytes).hexdigest()}
        if evidence_path is not None:
            self.verification["evidence_path"] = str(evidence_path)
        self.qualified_capabilities = {"file_bootstrap": {"kinds": ["casc_file"], "modes": ["new_working_scene"]}}

    @staticmethod
    def observed_build():
        from .native_adapters import installed_build
        return installed_build()

    def required_scope(self, scene, scope):
        from .native_adapters import _WORKSPACES, _locked_input
        operation, arguments = scope.get("operation_name"), scope.get("operation_arguments")
        if self.verification.get("evidence_path") and Path(self.verification["evidence_path"]).read_bytes() != self.evidence_bytes:
            raise ValueError("RIG_ADAPTER_UNVERIFIED: native qualification evidence changed")
        if not isinstance(arguments, dict) or operation not in {"safety.bootstrap", "safety.checkpoint", "animation.interpolation_refresh"}:
            raise ValueError("BINDING_UNAVAILABLE: unsupported native scene operation")
        projection = self.read_scene(scene)
        files = []
        if operation == "safety.bootstrap":
            allowed = {"input_kind", "input_mode", "input_path", "input_sha256", "input_length", "checkpoint_path", "working_path"}
            if set(arguments) - allowed or arguments.get("input_mode", "new_working_scene") != "new_working_scene":
                raise ValueError("INVALID_POLICY: bootstrap arguments/mode outside the qualified loader")
            kind = arguments.get("input_kind", "active_scene")
            if kind == "casc_file":
                path = Path(arguments["input_path"])
                if not path.is_absolute() or path.suffix.lower() != ".casc":
                    raise ValueError("INVALID_POLICY: bootstrap input must be an absolute .casc file")
                with _locked_input(path) as manifest:
                    if manifest["sha256"] != arguments.get("input_sha256") or manifest["length"] != arguments.get("input_length"):
                        raise ValueError("INPUT_DIGEST_MISMATCH")
                files.append({"schema_version": 1, **manifest})
            elif kind != "active_scene" or any(key in arguments for key in ("input_path", "input_sha256", "input_length")):
                raise ValueError("RIG_ADAPTER_UNVERIFIED: bootstrap input kind")
        elif operation == "safety.checkpoint" and set(arguments) != {"checkpoint_path", "working_path"}:
            raise ValueError("INVALID_POLICY: exact checkpoint paths required")
        elif operation == "animation.interpolation_refresh" and arguments:
            raise ValueError("INVALID_POLICY: evaluation refresh has no arbitrary settings")
        required = {"operation_name": operation, "operation_arguments": arguments,
            "operation_arguments_digest": guards.digest(arguments), "adapter_id": self.adapter_id,
            "object_ids": [row["id"] for row in projection["objects"]],
            "layer_ids": [row["id"] for row in projection["layers"]], "frames": [0, projection["frames"] - 1],
            "input_files": files}
        manifest = _WORKSPACES.get(guards.scene_instance(scene)["scene_instance_id"])
        if manifest is not None:
            required["snapshot_manifest"] = manifest
        return required

    def capture(self, scene, scope):
        projection = self.read_scene(scene)
        return {"coverage_complete": True, "authored_projection": projection, "sample_projection": projection}

    def prepare_recovery_binding(self, scene, request, result):
        from .native_checkpoint_restore import prepare_recovery_binding
        return prepare_recovery_binding(scene, request, result)

    def execute(self, scene, arguments, request):
        from .native_adapters import checkpoint
        from . import runtime as rt
        operation = request["operations"][0]["name"]
        if operation != "animation.interpolation_refresh":
            return checkpoint(scene, arguments, request, self)
        from .handler_registry import transact
        before = dict(guards.scene_instance(scene))
        callbacks = []
        def refresh(_model, _update, updater):
            interpolator = updater.get_interpolator()
            interpolator.reload()
            interpolator.interpolate()
            callbacks.append("interpolation_returned")
        transact(rt._domain_scene(scene).modify_update, "Cascadeur Complete: observed evaluation", refresh)
        if callbacks != ["interpolation_returned"]:
            raise ValueError("NATIVE_COMPLETION_UNKNOWN: evaluation callback did not complete exactly once")
        projection = self.read_scene(scene)
        _EVALUATIONS[before["scene_instance_id"]] = {"projection_digest": guards.digest(projection),
            "runtime_epoch": guards.RUNTIME_EPOCH, "request_id": request.get("request_id"),
            "frames": [0, projection["frames"] - 1], "native_completion": "observed"}
        guards.observe_effect(operation, "completed", scene_before=before, scene_after=dict(guards.scene_instance(scene)),
            detail={"callbacks": callbacks, "projection_digest": guards.digest(projection)})
        return {"native_completion": "observed", "evaluation": json.loads(json.dumps(_EVALUATIONS[before["scene_instance_id"]]))}, []


def qualify_scene_adapter():
    """Observe a shipped humanoid input in new tabs, preserving the active tab."""
    from .native_adapters import installed_build, _locked_input
    from . import runtime as rt
    guards.assert_loaded_package()
    if installed_build() != "2026.2.3.0.16863":
        raise ValueError("No observed scene SDK contract for installed build")
    sample = Path(r"C:\Program Files\Cascadeur\samples\Cascy.casc")
    from .native_export import _QualificationProgress
    folder = rt.runtime_root() / "snapshots" / ("scene-qualification-" + str(uuid.uuid4()))
    folder.mkdir(parents=True)
    progress = _QualificationProgress(folder)
    progress.mark("scene_manager")
    manager = csc.app.get_application().get_scene_manager()
    previous = manager.current_scene()
    if previous is not None and rt._domain_scene(previous).model_viewer().get_objects():
        raise ValueError("QUALIFICATION_REQUIRES_EMPTY_CURRENT_SCENE: populated tabs are not setup inputs")
    progress.mark("scene_manager", "complete")
    local_before = dict(vars(guards._LOCAL))
    progress.mark("create_application_scene")
    disposable = manager.create_application_scene()
    progress.mark("create_application_scene", "complete")
    created = [disposable]
    try:
        manager.set_current_scene(disposable)
        progress.mark("empty_source_capture")
        original = read_scene(disposable)
        progress.mark("empty_source_capture", "complete")
        with _locked_input(sample) as manifest:
            arguments = {"input_kind": "casc_file", "input_mode": "new_working_scene", "input_path": str(sample),
                         "input_sha256": manifest["sha256"], "input_length": manifest["length"],
                         "checkpoint_path": str(folder / "backup.casc"), "working_path": str(folder / "working.casc")}
        adapter = NativeSceneAdapter(b'{"operations":[]}')
        scope = adapter.required_scope(disposable, {"operation_name": "safety.bootstrap", "operation_arguments": arguments})
        source = guards._capture_with_adapter(disposable, scope, guards.digest(manifest), None, None, adapter)
        request = {"operations": [{"name": "safety.bootstrap", "arguments": arguments}], "source_binding": source}
        guards.begin_request(request)
        guards.set_write_guard(lambda: read_scene(disposable) == original or (_ for _ in ()).throw(ValueError("SCENE_CHANGED")))
        progress.mark("file_bootstrap_load_capture_save")
        result, _ = adapter.execute(disposable, arguments, request)
        progress.mark("file_bootstrap_load_capture_save", "complete")
        child = manager.current_scene()
        created.append(child)
        if guards.scene_instance(child)["document_lineage_id"] == guards.scene_instance(disposable)["document_lineage_id"]:
            raise ValueError("File input falsely inherited unrelated document lineage")
        progress.mark("loaded_scene_capture")
        loaded = read_scene(child)
        progress.mark("loaded_scene_capture", "complete")
        evaluation_scope = adapter.required_scope(child, {"operation_name": "animation.interpolation_refresh", "operation_arguments": {}})
        evaluation_source = guards._capture_with_adapter(child, evaluation_scope, source["inputs_digest"], None, None, adapter)
        evaluation_request = {"operations": [{"name": "animation.interpolation_refresh", "arguments": {}}], "source_binding": evaluation_source}
        guards.begin_request(evaluation_request)
        guards.set_write_guard(lambda: read_scene(child) == loaded or (_ for _ in ()).throw(ValueError("SCENE_CHANGED")))
        progress.mark("native_interpolation")
        evaluation, _ = adapter.execute(child, {}, evaluation_request)
        progress.mark("native_interpolation", "complete")
        evaluated = read_scene(child)
        next_args = {"checkpoint_path": str(folder / "evaluated-backup.casc"), "working_path": str(folder / "evaluated-working.casc")}
        next_scope = adapter.required_scope(child, {"operation_name": "safety.checkpoint", "operation_arguments": next_args})
        next_source = guards._capture_with_adapter(child, next_scope, source["inputs_digest"], None, None, adapter)
        guards.begin_request({"operations": [{"name": "safety.checkpoint", "arguments": next_args}], "source_binding": next_source})
        guards.set_write_guard(lambda: read_scene(child) == evaluated or (_ for _ in ()).throw(ValueError("SCENE_CHANGED")))
        progress.mark("successor_checkpoint")
        successor, _ = adapter.execute(child, next_args, {"operations": [{"name": "safety.checkpoint", "arguments": next_args}], "source_binding": next_source})
        progress.mark("successor_checkpoint", "complete")
        with _locked_input(sample) as after_manifest:
            if after_manifest != manifest or read_scene(disposable) != original:
                raise ValueError("Original source changed during scene qualification")
        evidence = {"build": installed_build(), "runtime_fingerprint": guards.LOADED_FINGERPRINT,
            "reader": "native-model-assets-v1", "input": manifest,
            "loaded_projection_digest": guards.digest(loaded), "evaluated_projection_digest": guards.digest(evaluated),
            "objects": len(loaded["objects"]), "data": len(loaded["data"]), "asset_kinds": [row["kind"] for row in loaded["assets"]],
            "bootstrap": result, "evaluation": evaluation, "checkpoint": successor,
            "operations": ["safety.bootstrap", "safety.checkpoint", "animation.interpolation_refresh"]}
        path = folder / "qualification.json"
        with path.open("xb") as stream:
            stream.write(json.dumps(evidence, sort_keys=True, separators=(",", ":"), allow_nan=False).encode())
        qualified = NativeSceneAdapter(path.read_bytes(), path)
        for operation in evidence["operations"]:
            guards.register_adapter(operation, qualified)
        progress.mark("qualification", "observed")
        return {"adapter_id": "native-model-assets-v1", "evidence_path": str(path),
                "evidence_sha256": qualified.verification["evidence_sha256"], "operations": evidence["operations"]}
    except Exception as exc:
        progress.mark("qualification", "failed", detail=str(exc)[:1000])
        raise
    finally:
        try:
            progress.mark("restore_owned_tabs")
            if previous is not None:
                manager.set_current_scene(previous)
            for scene in reversed(created):
                manager.remove_application_scene(scene)
            progress.mark("restore_owned_tabs", "complete")
        finally:
            vars(guards._LOCAL).clear()
            vars(guards._LOCAL).update(local_before)
