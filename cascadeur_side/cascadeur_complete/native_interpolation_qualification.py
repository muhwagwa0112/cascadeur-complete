"""Explicit, bounded native LINEAR/STEP perturbation qualification.

No registration occurs on import or from request data. The explicit helper
creates its own disposable object and retains successful observations as
immutable process-local bytes tied to the loaded package, build and epoch.
"""
from __future__ import annotations

import json

_QUALIFICATION_BYTES = None
SUPPORTED_BUILD = "2026.2.3.0.16863"
_EXPORT_FLAGS = {"is_exported": True, "export_translate_animation": True,
                 "export_rotate_animation": True, "export_scale_animation": True,
                 "use_namespace": False}


def _metadata(bv, dv, behaviour, object_id):
    """Exact installed Add.Transform export metadata; not an arbitrary controller."""
    if set(map(str, bv.get_behaviour_property_names(behaviour))) != set(_EXPORT_FLAGS) | {"rotation_order"}:
        raise ValueError("EXPORT_METADATA_UNQUALIFIED: unknown FbxExport properties")
    contract = {}
    for name in sorted(set(_EXPORT_FLAGS) | {"rotation_order"}):
        if bv.get_property_type(behaviour, name).name != "DataType":
            raise ValueError("EXPORT_METADATA_UNQUALIFIED: static owned data links required")
        identifier = bv.get_behaviour_data(behaviour, name)
        if identifier.is_null():
            raise ValueError("EXPORT_METADATA_UNQUALIFIED: missing metadata link")
        data = dv.get_data(identifier)
        if data.mode.name != "Static" or str(data.object_id) != object_id:
            raise ValueError("EXPORT_METADATA_UNQUALIFIED: metadata is not static and owned")
        value = dv.get_data_value(identifier)
        if name == "rotation_order":
            if type(value) is not int or value != 0:
                raise ValueError("EXPORT_METADATA_UNQUALIFIED: only observed rotation_order=0 supported")
        elif type(value) is not bool or value != _EXPORT_FLAGS[name]:
            raise ValueError("EXPORT_METADATA_UNQUALIFIED: export flag differs from qualified fixture")
        contract[name] = {"mode": "Static", "type": type(value).__name__, "value": value}
    return contract


def qualification():
    from . import guarded_runtime as guards
    from .native_adapters import installed_build
    if _QUALIFICATION_BYTES is None:
        return None
    guards.assert_loaded_package()
    value = json.loads(_QUALIFICATION_BYTES)
    if (value["runtime_epoch"] != guards.RUNTIME_EPOCH or value["runtime_fingerprint"] != guards.LOADED_FINGERPRINT
            or value["native_build"] != installed_build()):
        return None
    return value


def qualified_models():
    value = qualification()
    return [] if value is None else list(value["qualified_models"])


def qualified_export_metadata(bv, dv, behaviour, object_id):
    value = qualification()
    if value is None:
        return False
    try:
        return _metadata(bv, dv, behaviour, object_id) == value["export_metadata_contract"]
    except (ValueError, AttributeError, TypeError, RuntimeError):
        return False


def independent_projection_identity(projection, object_id):
    """Inspect actual complete closure for identity ownership, not semantic roles."""
    value = qualification()
    return value is not None and _projection_identity(projection,object_id,value["export_metadata_contract"])


def _projection_identity(projection, object_id, metadata_contract):
    if len(projection.get("objects", [])) != 1 or projection["objects"][0]["id"] != object_id:
        return False
    if (projection.get("additive", {}).get("stacked_layers_count") != 0 or projection.get("cycles")
            or projection.get("assets") or projection.get("missing_data_references")
            or projection.get("missing_setting_references")):
        return False
    obj = projection["objects"][0]
    by_name = {row["name"]: row for row in obj["behaviours"]}
    if len(by_name) != len(obj["behaviours"]) or not {"Basic", "Node3d", "Transform"} <= set(by_name):
        return False
    if set(by_name)-{"Basic", "Node3d", "Transform", "FbxExport"}:
        return False
    data = {row["id"]: row for row in projection["data"]}
    settings = {row["id"]: row for row in projection["settings"]}
    parent_observed = False
    for behaviour in obj["behaviours"]:
        for prop in behaviour["properties"]:
            if behaviour["name"] == "Basic" and prop["name"] == "parent":
                if prop["kind"] != "ObjectType" or prop["value"] is not None:
                    return False
                parent_observed = True
            elif prop["kind"] == "DataType":
                row = data.get(prop["value"])
                if row is None or row["owner"] != object_id or row["mode"] not in ("Static", "Animation"):
                    return False
            elif prop["kind"] == "SettingType":
                row = settings.get(prop["value"])
                if row is None or row["owner"] != object_id or row["mode"] != "Static":
                    return False
            else:
                return False
    if not parent_observed:
        return False
    if "FbxExport" in by_name:
        observed = {}
        for prop in by_name["FbxExport"]["properties"]:
            row = data.get(prop["value"])
            if row is None or row["mode"] != "Static" or len(row["values"]) != 1:
                return False
            scalar = row["values"][0]
            observed[prop["name"]] = {"mode": "Static", "type": type(scalar).__name__, "value": scalar}
        if observed != metadata_contract:
            return False
    return True


def evaluate_independent_transform(scene, fixture):
    """Evaluate only the currently owned, at most 33-frame one-object fixture."""
    from .native_fixture import _owned, _modify
    import csc
    state, domain = _owned(scene)
    if (state["objects"] != {fixture["object_id"]}
            or int(domain.layers_viewer().frames_count()) != fixture["frames_count"]
            or not 1 <= fixture["frames_count"] <= 33):
        raise ValueError("FIXTURE_SCOPE_CHANGED: bounded fixture evaluation required")
    completed = []
    def refresh(_model, _update, updater):
        # Graph construction and interpolation are explicit evaluation effects.
        # Never append pycsc.Scene.edit's implicit full SceneUpdater.update.
        updater.generate_update()
        interpolator = updater.get_interpolator()
        interpolator.reload()
        interpolator.interpolate()
        completed.append("interpolation_returned")
    _modify(domain.modify_update, "Evaluate owned independent Transform fixture", refresh)
    if completed != ["interpolation_returned"]:
        raise ValueError("INTERPOLATION_COMPLETION_UNOBSERVED")
    dv = domain.data_viewer()
    rows = {}
    for space, text in fixture["position_data_ids"].items():
        identifier = csc.model.DataId(text)
        if dv.get_data(identifier).mode.name != "Animation":
            raise ValueError("FIXTURE_CHANNEL_UNAVAILABLE: observed position is not animated")
        values = []
        for frame in range(fixture["frames_count"]):
            raw = dv.get_data_value(identifier, frame)
            convert = getattr(raw, "tolist", None)
            vector = convert() if callable(convert) else raw
            import numpy as np
            array = np.asarray(vector, dtype=float)
            if array.shape == (3,1): array = array[:,0]
            if array.shape != (3,) or not np.isfinite(array).all():
                raise ValueError("FIXTURE_CHANNEL_UNAVAILABLE: invalid actual evaluated position")
            values.append(array.tolist())
        rows[space] = values
    return {"native_completion": "observed", "callbacks": completed, "positions": rows}


def _prediction(keys, modes, count):
    result = []
    for frame in range(count):
        left = max(0, min(len(keys)-1, sum(k[0] <= frame for k in keys)-1))
        if left == len(keys)-1 or modes[left] == "STEP":
            row = list(keys[left][1])
        else:
            alpha = (frame-keys[left][0])/(keys[left+1][0]-keys[left][0])
            row = [(1-alpha)*a+alpha*b for a,b in zip(keys[left][1],keys[left+1][1])]
        result.append(row)
    return result


def qualify_independent_models():
    """Run an explicit 5-frame native experiment; no caller proof can invoke it."""
    global _QUALIFICATION_BYTES
    import csc
    import numpy as np
    from . import guarded_runtime as guards
    from . import runtime as rt
    from .native_adapters import installed_build
    from .native_fixture import create_disposable_scene, create_independent_transform, set_independent_keys, release_disposable_scene
    from .native_key_layout import LINEAR_MODEL, STEP_MODEL, PIECEWISE_MODEL
    from .native_scene_reader import read_scene
    guards.assert_loaded_package()
    if installed_build() != SUPPORTED_BUILD:
        raise ValueError("UNSUPPORTED_VERSION: finite interpolation qualification requires " + SUPPORTED_BUILD)
    previous = csc.app.get_application().get_scene_manager().current_scene()
    if previous is not None and rt._domain_scene(previous).model_viewer().get_objects():
        raise ValueError("QUALIFICATION_REQUIRES_EMPTY_CURRENT_SCENE: populated scenes are not scanned or edited")
    scene = None
    programs = [(["LINEAR","LINEAR"], LINEAR_MODEL), (["STEP","STEP"], STEP_MODEL),
                (["LINEAR","STEP"], PIECEWISE_MODEL), (["STEP","LINEAR"], PIECEWISE_MODEL)]
    trials = []
    metadata = None
    try:
        scene = create_disposable_scene()
        baseline = [(0,[0.,0.,0.]), (2,[2.,1.,0.]), (4,[0.,2.,1.])]
        fixture = create_independent_transform(scene, "MCPInterpolationQualification", baseline, programs[0][0])
        domain = rt._domain_scene(scene)
        obj = next(iter(domain.model_viewer().get_objects()))
        bv, dv = domain.behaviour_viewer(), domain.data_viewer()
        names = {str(bv.get_behaviour_name(b)) for b in bv.get_behaviours(obj)}
        if names != {"Basic", "Node3d", "Transform", "FbxExport"}:
            raise ValueError("FIXTURE_DEPENDENCY_UNQUALIFIED: official fixture contains unexpected behaviours")
        parent = bv.get_behaviour_object(bv.get_behaviour_by_name(obj, "Basic"), "parent")
        if not parent.is_null():
            raise ValueError("FIXTURE_DEPENDENCY_UNQUALIFIED: official fixture has a parent")
        metadata = _metadata(bv, dv, bv.get_behaviour_by_name(obj, "FbxExport"), fixture["object_id"])
        for modes, model in programs:
            base_actual = None
            for perturb in [None] + [(key,axis) for key in range(3) for axis in range(3)]:
                keys = [(frame,list(position)) for frame,position in baseline]
                if perturb is not None: keys[perturb[0]][1][perturb[1]] += .25
                fixture = set_independent_keys(scene, fixture["object_id"], keys, modes)
                actual = evaluate_independent_transform(scene, fixture)
                expected = np.asarray(_prediction(keys,modes,5))
                residual = max(float(np.max(np.abs(np.asarray(rows)-expected))) for rows in actual["positions"].values())
                if residual > 1e-5:
                    raise ValueError("FINITE_MODEL_READBACK_MISMATCH: actual native " + model + " differs from its finite model")
                if perturb is None:
                    base_actual = actual
                    delta_residual = 0.
                else:
                    expected_delta = expected-np.asarray(_prediction(baseline,modes,5))
                    delta_residual = max(float(np.max(np.abs(
                        np.asarray(rows)-np.asarray(base_actual["positions"][space])-expected_delta)))
                        for space,rows in actual["positions"].items())
                    if delta_residual > 1e-5:
                        raise ValueError("FINITE_MODEL_PERTURBATION_MISMATCH: actual key influence differs")
                projection = read_scene(scene)
                if not _projection_identity(projection,fixture["object_id"],metadata):
                    raise ValueError("FIXTURE_DEPENDENCY_UNQUALIFIED: actual full native closure is outside independent domain")
                trials.append({"model":model,"segment_modes":modes,"keys":keys,"perturbation":perturb,
                    "actual":actual,"max_absolute_error_scene_units":residual,
                    "max_influence_error_scene_units":delta_residual,"projection_digest":guards.digest(projection)})
        evidence = {"schema_version":1,"native_build":installed_build(),"runtime_fingerprint":guards.LOADED_FINGERPRINT,
            "runtime_epoch":guards.RUNTIME_EPOCH,"reader_contract":"native_independent_position_v1",
            "qualified_models":[LINEAR_MODEL,STEP_MODEL,PIECEWISE_MODEL],"export_metadata_contract":metadata,
            "domain":{"channel":"position","spaces":["local","global"],"parent":None,
                      "controllers":False,"cycles":False,"additive":False,"key_id_kind":"layer_frame_locator",
                      "observation_frames":[0,1,2,3,4],"observation_keys":[0,2,4]},"trials":trials}
    finally:
        if scene is not None: release_disposable_scene(scene)
    # Publish only after every native readback and disposable cleanup succeeded.
    _QUALIFICATION_BYTES = json.dumps(evidence,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False).encode()
    return {"qualified_models":qualified_models(),"qualification_digest":guards.digest(evidence),
            "native_build":evidence["native_build"],"runtime_epoch":guards.RUNTIME_EPOCH,"trial_count":len(trials)}
