"""Explicit, retained SDK cube calibration; never general geometry authority.

The owned fixture observes the installed calculation's coordinate convention
and sequential return behavior. A self-bound cube cannot qualify arbitrary
skinning, blendshape, parent or graph dependencies. No production contract is
registered here, and no caller options/evidence can be supplied.
"""
from __future__ import annotations

import copy
import hashlib
import json

SUPPORTED_BUILD = "2026.2.3.0.16863"
SETUP_OPERATION = "setup.qualify_geometry_calculation"
CALCULATION_FRAMES = (0, 2, 1, 0, 1)
_OBSERVATION_BYTES = None
_LIMITS = {"calculations": 5, "evaluations": 2, "driver_mutations": 1,
           "maximum_vertices": 64, "maximum_projection_bytes": 2 * 1024**2}


def _bytes(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False,
                      separators=(",", ":")).encode("utf-8")


def calibration_status():
    """Expose identifiers of an actual current-epoch diagnostic, not authority."""
    from . import guarded_runtime as guards
    from .native_adapters import installed_build
    if _OBSERVATION_BYTES is None:
        return {"observed": False, "code": "GEOMETRY_COORDINATE_CALIBRATION_UNOBSERVED"}
    value = json.loads(_OBSERVATION_BYTES)
    if (value["runtime_epoch"] != guards.RUNTIME_EPOCH
            or value["runtime_fingerprint"] != guards.LOADED_FINGERPRINT
            or value["installed_build"] != installed_build()):
        return {"observed": False, "code": "GEOMETRY_CALIBRATION_CONTEXT_CHANGED"}
    return {"observed": True, "calibration_digest": hashlib.sha256(_OBSERVATION_BYTES).hexdigest(),
            "raw_space": value["raw_space"], "profile": "owned_self_bound_cube_only",
            "production_geometry_qualified": False}


def _boundary(scene):
    from . import runtime as rt
    from . import guarded_runtime as guards
    from .native_export import selection_observation
    from .native_scene_reader import read_scene
    if rt._scene_view() is not scene:
        raise ValueError("GEOMETRY_CALIBRATION_SCENE_CHANGED")
    projection = read_scene(scene)
    if len(_bytes(projection)) > _LIMITS["maximum_projection_bytes"]:
        raise ValueError("GEOMETRY_CALIBRATION_PROJECTION_BUDGET_EXCEEDED")
    return {"scene": dict(guards.scene_instance(scene)), "projection": projection,
            "selection": selection_observation(scene),
            "current_frame": int(rt._domain_scene(scene).get_current_frame(False)),
            "runtime_epoch": guards.RUNTIME_EPOCH, "runtime_fingerprint": guards.LOADED_FINGERPRINT}


def _fixture_inputs(scene, fixture):
    """Observe exact typed assets/linkage, never infer from display names."""
    import csc
    import numpy as np
    from . import runtime as rt
    from .native_scene_reader import native_value
    domain = rt._domain_scene(scene)
    mv, bv, dv = domain.model_viewer(), domain.behaviour_viewer(), domain.data_viewer()
    objects = list(mv.get_objects())
    if len(objects) != 1 or str(objects[0]) != fixture["object_id"]:
        raise ValueError("GEOMETRY_CALIBRATION_OBJECT_CLOSURE_DIFFERS")
    obj = objects[0]
    names = [str(bv.get_behaviour_name(item)) for item in bv.get_behaviours(obj)]
    if len(set(names)) != len(names) or set(names) != {"Basic", "Node3d", "Transform", "FbxExport", "MeshObject"}:
        raise ValueError("GEOMETRY_CALIBRATION_BEHAVIOUR_CLOSURE_UNSUPPORTED")
    basic = bv.get_behaviour_by_name(obj, "Basic")
    if not bv.get_behaviour_object(basic, "parent").is_null():
        raise ValueError("GEOMETRY_CALIBRATION_PARENT_UNSUPPORTED")
    node = bv.get_behaviour_by_name(obj, "Node3d")
    matrix_id = bv.get_behaviour_data(node, "global_matrix")
    if matrix_id.is_null() or dv.get_data(matrix_id).object_id != obj or dv.get_data(matrix_id).mode.name != "Animation":
        raise ValueError("GEOMETRY_CALIBRATION_GLOBAL_MATRIX_OWNERSHIP_UNSUPPORTED")
    mesh_b = bv.get_behaviour_by_name(obj, "MeshObject")
    if list(bv.get_behaviour_objects_range(mesh_b, "linked_objects")) != [obj]:
        raise ValueError("GEOMETRY_CALIBRATION_SKIN_PROFILE_UNSUPPORTED")
    if bv.get_behaviour_data(mesh_b, "bindShapeMatrix") != matrix_id:
        raise ValueError("GEOMETRY_CALIBRATION_BIND_SHAPE_LINK_UNSUPPORTED")
    manager = domain.assets_manager()
    mesh_id, dependency_id = (bv.get_behaviour_asset(mesh_b, key) for key in ("mesh", "mesh_dependency"))
    mesh, dependency = manager.at(mesh_id), manager.at(dependency_id)
    if not isinstance(mesh, csc.domain.assets.Mesh) or not isinstance(dependency, csc.domain.assets.MeshDependency):
        raise ValueError("GEOMETRY_CALIBRATION_ASSET_TYPE_UNSUPPORTED")
    asset_positions = np.asarray(mesh.positions())
    asset_position_shape = list(asset_positions.shape)
    # The installed Eigen bindings may expose each Vector4f as a column, as
    # they do for SkinnedMeshCalcResult's documented Vector3f columns.
    if asset_positions.ndim == 3 and asset_positions.shape[1:] == (4,1):
        asset_positions = asset_positions[:,:,0]
    if (asset_positions.dtype != np.dtype("float32") or asset_positions.ndim != 2
            or asset_positions.shape[1] != 4 or not 3 <= len(asset_positions) <= _LIMITS["maximum_vertices"]
            or not np.isfinite(asset_positions).all() or not np.array_equal(asset_positions[:,3], np.ones(len(asset_positions)))):
        raise ValueError("GEOMETRY_CALIBRATION_NATIVE_ASSET_POSITION_TYPE_UNSUPPORTED")
    inverse = np.asarray(dependency.inverse_bind_matrices())
    if (inverse.dtype != np.dtype("float32") or inverse.shape != (1,4,4)
            or not np.array_equal(inverse[0], np.eye(4))):
        raise ValueError("GEOMETRY_CALIBRATION_INVERSE_BIND_PROFILE_UNSUPPORTED")
    weights = list(dependency.vertices_weights())
    if len(weights) != len(asset_positions) or any(len(row) != 1 or row[0].index != 0 or row[0].weight != 1.0 for row in weights):
        raise ValueError("GEOMETRY_CALIBRATION_VERTEX_WEIGHT_PROFILE_UNSUPPORTED")
    matrices = []
    for frame in range(fixture["frames_count"]):
        value = np.asarray(dv.get_data_value(matrix_id, frame))
        if (value.dtype != np.dtype("float32") or value.shape != (4,4)
                or not np.isfinite(value).all() or not np.array_equal(value[3], [0,0,0,1])
                or not np.array_equal(value[:3,:3], np.eye(3))):
            raise ValueError("GEOMETRY_CALIBRATION_NON_TRANSLATION_TRANSFORM_UNSUPPORTED")
        matrices.append(value.copy())
    if all(np.array_equal(matrix, np.eye(4)) for matrix in matrices):
        raise ValueError("GEOMETRY_CALIBRATION_NONIDENTITY_TRANSFORM_REQUIRED")
    return domain, obj, asset_positions.copy(), matrices, {
        "object_id": str(obj), "mesh_behaviour_id": str(mesh_b), "mesh_asset_id": str(mesh_id),
        "dependency_asset_id": str(dependency_id), "global_matrix_data_id": str(matrix_id),
        "asset_position_native_shape": asset_position_shape,
        "asset_positions": native_value(asset_positions), "inverse_bind_matrices": native_value(inverse),
        "vertex_weights": [[[int(item.index),float(item.weight)] for item in row] for row in weights],
        "global_matrices": native_value(matrices)}


def _calculate(scene, fixture, frames, retained):
    import csc
    import numpy as np
    from .native_scene_reader import native_value
    domain, obj, positions, matrices, inputs = _fixture_inputs(scene, fixture)
    before = _boundary(scene)
    trials = []
    for frame in frames:
        retained.before_effect()
        if _boundary(scene) != before:
            raise ValueError("GEOMETRY_CALIBRATION_SOURCE_CHANGED_BEFORE_CALCULATION")
        # Direct official SDK return; no UI queue, reskin ActionManager call,
        # inferred idle state, or interpolation receipt is used as completion.
        returned = csc.domain.calc_skinned_mesh(domain, obj, frame)
        raw = np.asarray(returned.positions)
        if raw.shape == (len(positions),3,1):
            raw = raw[:,:,0]
        if raw.dtype != np.dtype("float32") or raw.shape != (len(positions),3) or not np.isfinite(raw).all():
            raise ValueError("GEOMETRY_CALIBRATION_NATIVE_RESULT_TYPE_UNSUPPORTED")
        owned = np.array(raw, dtype=np.float32, copy=True, order="C")
        if _boundary(scene) != before:
            raise ValueError("GEOMETRY_CALIBRATION_CALCULATION_CHANGED_NATIVE_CLOSURE")
        # The fixture uses dyadic translations and unit rotation/scale. This
        # deliberately permits exact comparison; no observed failure is used
        # to fit a numeric tolerance or an arbitrary affine convention.
        local = positions[:,:3].copy()
        world = local + matrices[frame][:3,3]
        trials.append({"frame": frame, "raw": native_value(owned),
            "raw_sha256": hashlib.sha256(memoryview(owned).cast("B")).hexdigest(),
            "matches_native_mesh_local": bool(np.array_equal(owned,local)),
            "matches_native_global": bool(np.array_equal(owned,world)),
            "before_boundary_digest": hashlib.sha256(_bytes(before)).hexdigest(),
            "after_boundary_digest": hashlib.sha256(_bytes(_boundary(scene))).hexdigest(),
            "return_observation": "direct_typed_result_copied_before_next_call"})
    return inputs, trials


def qualify_geometry_calculation():
    """Explicit setup prerequisite: one retained tab, two files, five calls.

    Failure retains artifacts/tabs and restores the original active tab through
    RetainedProbe. Repeated calls return only the prior retained result. This
    helper never inserts an entry into native_geometry_capture._CONTRACTS.
    """
    global _OBSERVATION_BYTES
    import csc
    import numpy as np
    from . import guarded_runtime as guards
    from . import runtime as rt
    from .incident_admission import assert_setup_admission
    from .native_adapters import installed_build
    from .native_fixture import create_disposable_scene, create_independent_transform, _modify
    from .native_interpolation_qualification import evaluate_independent_transform
    from .native_probe_retention import RetainedProbe, retained_probe_result
    from .native_scene_reader import read_scene
    admission = assert_setup_admission(SETUP_OPERATION)
    semantic_limits = {"maximum_geometry_calculations": 5, "maximum_evaluations": 2,
                       "maximum_driver_mutations": 1}
    if any(getattr(admission, key, None) != value for key,value in semantic_limits.items()):
        raise ValueError("GEOMETRY_CALIBRATION_SETUP_SEMANTIC_LIMITS_DIFFER")
    guards.assert_loaded_package()
    if installed_build() != SUPPORTED_BUILD:
        raise ValueError("UNSUPPORTED_VERSION: geometry calibration requires " + SUPPORTED_BUILD)
    prior = retained_probe_result("geometry_calculation")
    if prior is not None:
        if not calibration_status()["observed"]:
            raise ValueError("GEOMETRY_CALIBRATION_PRIVATE_OBSERVATION_UNAVAILABLE")
        return prior
    retained = RetainedProbe("geometry_calculation")
    error = None
    try:
        retained.before_new_tab()
        scene = create_disposable_scene(retain_on_failure=True)
        retained.track(scene, "geometry-calibration-fixture")
        retained.before_effect()
        fixture = create_independent_transform(scene, "MCPGeometryCalibration",
            [(0,[0.,0.,0.]),(1,[2.,1.,0.]),(2,[0.,2.,1.])], ["LINEAR","LINEAR"])
        domain = rt._domain_scene(scene)
        def attach(_model, update, callback_scene):
            from common.mesh import set_mesh_object_data
            retained.before_effect()
            mesh = csc.domain.assets.AssetsManager.get_cube_mesh(2.0)
            dependency = csc.domain.assets.MeshDependency(mesh)
            obj = next(iter(domain.model_viewer().get_objects()))
            set_mesh_object_data(callback_scene, _model, update, update.get_object_by_id(obj),
                                 mesh, dependency, [obj], create_default_material=False)
        retained.before_effect()
        _modify(domain.modify, "Attach owned geometry calibration cube", attach)
        retained.before_effect()
        first_evaluation = evaluate_independent_transform(scene, fixture)
        retained.save_fixture(scene, "fixture-before.casc", read_scene)
        first_inputs, trials = _calculate(scene, fixture, CALCULATION_FRAMES[:4], retained)
        if trials[0]["raw_sha256"] != trials[3]["raw_sha256"]:
            raise ValueError("GEOMETRY_CALIBRATION_FRAME_ORDER_DEPENDENCY")
        candidates = [space for space,key in (("native_global","matches_native_global"),
            ("native_mesh_local","matches_native_mesh_local")) if all(trial[key] for trial in trials)]
        if len(candidates) != 1:
            raise ValueError("GEOMETRY_CALIBRATION_COORDINATE_CONVENTION_UNRESOLVED")
        raw_space = candidates[0]
        before_mutation = _boundary(scene)
        def mutate(model, _update, _scene):
            retained.before_effect()
            if _boundary(scene) != before_mutation:
                raise ValueError("GEOMETRY_CALIBRATION_SOURCE_CHANGED_BEFORE_DRIVER_MUTATION")
            model.data_editor().set_data_value(csc.model.DataId(fixture["position_data_ids"]["local"]),
                                               1, np.asarray([2.25,.75,.25],dtype=np.float32).reshape(3,1))
        retained.before_effect()
        _modify(domain.modify, "Perturb one owned geometry driver key", mutate)
        retained.before_effect()
        second_evaluation = evaluate_independent_transform(scene, fixture)
        second_inputs, changed = _calculate(scene, fixture, CALCULATION_FRAMES[4:], retained)
        first_matrix = np.asarray(first_inputs["global_matrices"][1])
        second_matrix = np.asarray(second_inputs["global_matrices"][1])
        if (not np.array_equal(first_matrix[:3,3], [2.,1.,0.])
                or not np.array_equal(second_matrix[:3,3], [2.25,.75,.25])
                or not np.array_equal(first_matrix[:3,:3], second_matrix[:3,:3])):
            raise ValueError("GEOMETRY_CALIBRATION_AUTHORITATIVE_DRIVER_EFFECT_UNOBSERVED")
        key = "matches_native_global" if raw_space == "native_global" else "matches_native_mesh_local"
        if not changed[0][key]:
            raise ValueError("GEOMETRY_CALIBRATION_PERTURBATION_CONVENTION_CHANGED")
        baseline_frame_one = next(trial for trial in trials if trial["frame"] == 1)
        if (raw_space == "native_global" and changed[0]["raw_sha256"] == baseline_frame_one["raw_sha256"]):
            raise ValueError("GEOMETRY_CALIBRATION_DRIVER_PERTURBATION_NOT_OBSERVED")
        trials.extend(changed)
        retained.save_fixture(scene, "fixture-after.casc", read_scene)
        evidence = {"schema_version": 1, "kind": "owned-geometry-calculation-calibration",
            "helper_id": "owned_cube_coordinate_and_sequential_return_v1",
            "setup_operation": SETUP_OPERATION, "granted_semantic_limits": semantic_limits,
            "generator": {"method": "csc.domain.assets.AssetsManager.get_cube_mesh", "size": 2.0,
                "dependency_method": "csc.domain.assets.MeshDependency",
                "attachment_method": "common.mesh.set_mesh_object_data", "create_default_material": False,
                "initial_keys": [[0,[0.,0.,0.]],[1,[2.,1.,0.]],[2,[0.,2.,1.]]],
                "segment_modes": ["LINEAR","LINEAR"]},
            "calculation_method": "csc.domain.calc_skinned_mesh",
            "evaluation_method": "native_interpolation_qualification.evaluate_independent_transform",
            "installed_build": installed_build(), "runtime_epoch": guards.RUNTIME_EPOCH,
            "runtime_fingerprint": guards.LOADED_FINGERPRINT, "profile": "owned_self_bound_cube_only",
            "raw_space": raw_space, "limits": dict(_LIMITS), "calculation_schedule": list(CALCULATION_FRAMES),
            "first_inputs": first_inputs, "perturbed_inputs": second_inputs,
            "evaluations": [first_evaluation,second_evaluation], "driver_mutation": {
                "data_id": fixture["position_data_ids"]["local"], "existing_frame": 1,
                "value_scene_units": [2.25,.75,.25]}, "trials": trials,
            "production_geometry_qualified": False,
            "unqualified_profiles": ["skinned_mesh", "blendshape", "parented_mesh", "arbitrary_update_graph"],
            "remaining_requirements": ["current_complete_dependency_and_transform_authority",
                "production_profile_specific_synchronous_calculation_qualification"]}
    except Exception as exc:
        error = exc
        raise
    finally:
        retention = retained.finish(error)
    retained.before_effect()
    evidence["retention"] = retention
    raw = _bytes(evidence)
    result = retained.complete({"calibration_digest": hashlib.sha256(raw).hexdigest(),
        "raw_space": raw_space, "calculation_count": len(trials), "evaluation_count": 2,
        "driver_mutation_count": 1, "production_geometry_qualified": False, "retention": retention})
    _OBSERVATION_BYTES = raw
    return copy.deepcopy(result)
