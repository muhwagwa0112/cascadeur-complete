"""Explicit complete-scene qualification for the finite independent Transform.

This is a separate domain from the shipped character qualification. It keeps
the complete projection, exact save equality and current interpolation proof;
no numerical channel is excluded to make a character checkpoint pass.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path

from . import guarded_runtime as guards
from .native_scene_adapter import NativeSceneAdapter
from .native_scene_reader import read_scene

_OPERATIONS = ["safety.bootstrap", "safety.checkpoint", "animation.interpolation_refresh"]
_PROFILE = "native-independent-complete-scene-v1"


class NativeIndependentSceneAdapter(NativeSceneAdapter):
    adapter_id = _PROFILE

    def __init__(self, evidence_bytes, evidence_path=None):
        from .native_interpolation_qualification import qualification
        model = qualification()
        evidence = json.loads(evidence_bytes)
        if (model is None or evidence.get("reader") != _PROFILE
                or evidence.get("model_qualification_digest") != guards.digest(model)
                or evidence.get("runtime_epoch") != guards.RUNTIME_EPOCH
                or evidence.get("runtime_fingerprint") != guards.LOADED_FINGERPRINT
                or evidence.get("build") != self.observed_build()
                or evidence.get("operations") not in ([], _OPERATIONS)
                or evidence.get("operations") and evidence_path is None):
            raise ValueError("RIG_ADAPTER_UNVERIFIED: current independent scene proof required")
        super().__init__(evidence_bytes, evidence_path)
        self._model_digest = guards.digest(model)
        self._empty_file_sources = set()
        self.qualified_capabilities["file_bootstrap"]["scene_profile"] = _PROFILE

    def read_scene(self, scene):
        from .native_interpolation_qualification import qualification, independent_projection_identity
        model = qualification()
        if model is None or guards.digest(model) != self._model_digest:
            raise ValueError("RIG_ADAPTER_UNVERIFIED: interpolation proof changed")
        projection = read_scene(scene)
        objects = projection["objects"]
        if not objects and guards.scene_instance(scene)["scene_instance_id"] in self._empty_file_sources:
            return projection
        if (not 1 <= projection["frames"] <= 33 or len(objects) != 1
                or not independent_projection_identity(projection, objects[0]["id"])):
            raise ValueError("RIG_ADAPTER_UNVERIFIED: complete scene is outside independent Transform domain")
        return projection

    def required_scope(self, scene, scope):
        # Only the original empty file-input tab may be empty. Loaded targets
        # get a new instance and must satisfy the complete one-object closure.
        projection = read_scene(scene)
        if not projection["objects"]:
            arguments = scope.get("operation_arguments") or {}
            if (scope.get("operation_name") != "safety.bootstrap"
                    or arguments.get("input_kind") != "casc_file"):
                raise ValueError("RIG_ADAPTER_UNVERIFIED: empty scene is only a file-bootstrap source")
            self._empty_file_sources.add(guards.scene_instance(scene)["scene_instance_id"])
        return super().required_scope(scene, scope)


def qualify_independent_scene_adapter():
    """Explicit owned fixture/save/load/evaluation/checkpoint observation.

    Requires a prior actual finite-model qualification in the same process.
    This helper is not a wire operation and never runs on import.
    """
    import csc
    from . import runtime as rt
    from .native_adapters import _locked_input, _save_observed, installed_build
    from .native_export import _QualificationProgress
    from .native_fixture import create_disposable_scene, create_independent_transform, release_disposable_scene
    from .native_interpolation_qualification import qualification, evaluate_independent_transform

    guards.assert_loaded_package()
    model = qualification()
    if model is None:
        raise ValueError("RIG_ADAPTER_UNVERIFIED: run explicit independent model qualification first")
    manager = csc.app.get_application().get_scene_manager()
    previous = manager.current_scene()
    if previous is None or rt._domain_scene(previous).model_viewer().get_objects():
        raise ValueError("QUALIFICATION_REQUIRES_EMPTY_CURRENT_SCENE")
    original_tabs = list(manager.scenes())
    original = read_scene(previous)
    local_before = dict(vars(guards._LOCAL))
    folder = rt.runtime_root() / "snapshots" / ("independent-scene-qualification-" + str(uuid.uuid4()))
    folder.mkdir(parents=True)
    progress = _QualificationProgress(folder)
    fixture_scene, source_scene, child = None, None, None
    proof = {"reader": _PROFILE, "model_qualification_digest": guards.digest(model),
        "runtime_epoch": guards.RUNTIME_EPOCH, "runtime_fingerprint": guards.LOADED_FINGERPRINT,
        "build": installed_build(), "operations": []}
    adapter = NativeIndependentSceneAdapter(json.dumps(proof).encode())
    succeeded = False
    try:
        progress.mark("fixture")
        fixture_scene = create_disposable_scene()
        fixture = create_independent_transform(fixture_scene, "MCPIndependentSceneQualification",
            [(0, [0., 0., 0.]), (2, [2., 1., 0.]), (4, [0., 2., 1.])], ["LINEAR", "STEP"])
        evaluate_independent_transform(fixture_scene, fixture)
        fixture_projection = adapter.read_scene(fixture_scene)
        saved_input = _save_observed(fixture_scene, folder / "source.casc")
        if adapter.read_scene(fixture_scene) != fixture_projection:
            raise ValueError("NATIVE_COMPLETION_UNKNOWN: fixture changed during first save")
        progress.mark("fixture", "complete")
        source_scene = manager.create_application_scene()
        manager.set_current_scene(source_scene)
        empty = read_scene(source_scene)
        with _locked_input(folder / "source.casc") as manifest:
            arguments = {"input_kind": "casc_file", "input_mode": "new_working_scene",
                "input_path": manifest["path"], "input_sha256": manifest["sha256"], "input_length": manifest["length"],
                "checkpoint_path": str(folder / "backup.casc"), "working_path": str(folder / "working.casc")}
        scope = adapter.required_scope(source_scene, {"operation_name": "safety.bootstrap", "operation_arguments": arguments})
        source = guards._capture_with_adapter(source_scene, scope, guards.digest(manifest), None, None, adapter)
        request = {"operations": [{"name": "safety.bootstrap", "arguments": arguments}], "source_binding": source}
        guards.begin_request(request)
        guards.set_write_guard(lambda: read_scene(source_scene) == empty or (_ for _ in ()).throw(ValueError("SCENE_CHANGED")))
        progress.mark("file_bootstrap")
        bootstrap, _ = adapter.execute(source_scene, arguments, request)
        child = manager.current_scene()
        if (adapter.read_scene(child) != fixture_projection
                or guards.scene_instance(child)["document_lineage_id"] == source["binding"]["document_lineage_id"]):
            raise ValueError("NATIVE_COMPLETION_UNKNOWN: file bootstrap projection or lineage differs")
        progress.mark("file_bootstrap", "complete")
        loaded = adapter.read_scene(child)
        eval_scope = adapter.required_scope(child, {"operation_name": "animation.interpolation_refresh", "operation_arguments": {}})
        eval_source = guards._capture_with_adapter(child, eval_scope, source["inputs_digest"], None, None, adapter)
        eval_request = {"operations": [{"name": "animation.interpolation_refresh", "arguments": {}}], "source_binding": eval_source}
        guards.begin_request(eval_request)
        guards.set_write_guard(lambda: adapter.read_scene(child) == loaded or (_ for _ in ()).throw(ValueError("SCENE_CHANGED")))
        progress.mark("evaluation")
        evaluation, _ = adapter.execute(child, {}, eval_request)
        evaluated = adapter.read_scene(child)
        progress.mark("evaluation", "complete")
        next_args = {"checkpoint_path": str(folder / "evaluated-backup.casc"), "working_path": str(folder / "evaluated-working.casc")}
        next_scope = adapter.required_scope(child, {"operation_name": "safety.checkpoint", "operation_arguments": next_args})
        next_source = guards._capture_with_adapter(child, next_scope, source["inputs_digest"], None, None, adapter)
        next_request = {"operations": [{"name": "safety.checkpoint", "arguments": next_args}], "source_binding": next_source}
        guards.begin_request(next_request)
        guards.set_write_guard(lambda: adapter.read_scene(child) == evaluated or (_ for _ in ()).throw(ValueError("SCENE_CHANGED")))
        progress.mark("checkpoint")
        checkpoint, _ = adapter.execute(child, next_args, next_request)
        if (adapter.read_scene(child) != evaluated or read_scene(source_scene) != empty
                or adapter.read_scene(fixture_scene) != fixture_projection or read_scene(previous) != original):
            raise ValueError("NATIVE_COMPLETION_UNKNOWN: qualification source or target changed")
        with _locked_input(folder / "source.casc") as after:
            if after != manifest:
                raise ValueError("INPUT_DIGEST_MISMATCH: qualification source bytes changed")
        proof.update({"operations": _OPERATIONS, "input": saved_input,
            "loaded_projection_digest": guards.digest(loaded), "evaluated_projection_digest": guards.digest(evaluated),
            "bootstrap": bootstrap, "evaluation": evaluation, "checkpoint": checkpoint})
        progress.mark("checkpoint", "complete")
        succeeded = True
    except Exception as error:
        progress.mark("qualification", "failed", detail=str(error)[:1000])
        raise
    finally:
        try:
            manager.set_current_scene(previous)
            # A failed load may own an unknown tab. Preserve it and its files;
            # remove only positively identified successful qualification tabs.
            if succeeded and child is not None:
                manager.remove_application_scene(child)
            if source_scene is not None:
                manager.remove_application_scene(source_scene)
            if fixture_scene is not None:
                release_disposable_scene(fixture_scene)
            manager.set_current_scene(previous)
            if any(not any(tab is item for item in manager.scenes()) for tab in original_tabs):
                raise ValueError("NATIVE_COMPLETION_UNKNOWN: original scene inventory changed")
        finally:
            vars(guards._LOCAL).clear()
            vars(guards._LOCAL).update(local_before)
    # Cleanup is part of the observation. Do not publish authority before the
    # original tab and inventory have actually been restored.
    path = folder / "qualification.json"
    with path.open("xb") as stream:
        stream.write(json.dumps(proof, sort_keys=True, separators=(",", ":"), allow_nan=False).encode())
    qualified = NativeIndependentSceneAdapter(path.read_bytes(), path)
    for operation in _OPERATIONS:
        guards.register_adapter(operation, qualified)
    progress.mark("qualification", "observed")
    return {"adapter_id": _PROFILE, "evidence_path": str(path),
        "evidence_sha256": qualified.verification["evidence_sha256"], "operations": list(_OPERATIONS)}
