"""Runtime-issued evaluated motion, read independently from the native model.

The context is an explicit conversion policy, not proof of native physical
metadata. Neither a caller's batch nor its digest can issue a capture here.
Interpolation-model qualification is deliberately separate from evaluation.
"""
from __future__ import annotations

import copy
import math


_CAPTURES = {}
_MAX_RECORDS = 16
_CONTEXT_FIELDS = {"frames", "time_s", "time_source", "fps_num", "fps_den",
                   "metres_per_scene_unit", "scene_to_solver_basis", "metadata_provenance"}


def _context(value):
    import numpy as np
    if not isinstance(value, dict) or set(value) != _CONTEXT_FIELDS:
        raise ValueError("MISSING_CLIP_METADATA: complete explicit MotionContext required")
    frames = value["frames"]
    if (not isinstance(frames, list) or not frames or len(frames) > 256
            or any(type(f) is not int or f < 0 for f in frames)
            or any(b <= a for a, b in zip(frames, frames[1:]))):
        raise ValueError("RESOURCE_BUDGET_EXCEEDED: exact increasing capture grid of at most 256 frames required")
    for key in ("fps_num", "fps_den"):
        if type(value[key]) is not int or value[key] <= 0:
            raise ValueError("MISSING_CLIP_METADATA: explicit positive rational FPS required")
    if value["time_source"] not in ("fps", "explicit"):
        raise ValueError("MISSING_CLIP_METADATA: explicit time source required")
    times = np.asarray(value["time_s"], dtype=float)
    scale = value["metres_per_scene_unit"]
    if (times.shape != (len(frames),) or not np.isfinite(times).all()
            or np.any(np.diff(times) <= 0) or isinstance(scale, bool)
            or not isinstance(scale, (int, float)) or not math.isfinite(scale) or scale <= 0):
        raise ValueError("MISSING_CLIP_METADATA: finite time grid and positive length conversion required")
    if value["time_source"] == "fps" and not np.allclose(
            times, (np.asarray(frames)-frames[0])*value["fps_den"]/value["fps_num"], rtol=0, atol=1e-12):
        raise ValueError("MISSING_CLIP_METADATA: explicit time grid disagrees with rational FPS")
    basis = np.asarray(value["scene_to_solver_basis"], dtype=float)
    if (basis.shape != (3, 3) or not np.isfinite(basis).all()
            or not np.allclose(basis.T @ basis, np.eye(3), rtol=0, atol=1e-10)
            or not np.isclose(np.linalg.det(basis), 1, rtol=0, atol=1e-10)):
        raise ValueError("UNSUPPORTED_COORDINATE_SYSTEM: explicit proper orthogonal basis required")
    if not isinstance(value["metadata_provenance"], dict) or not value["metadata_provenance"]:
        raise ValueError("MISSING_CLIP_METADATA: declared conversion-policy provenance required")
    return copy.deepcopy(value), basis, float(scale)


def _ids(value, label, maximum=128):
    if (not isinstance(value, list) or not value or len(value) > maximum
            or any(not isinstance(x, str) or not x for x in value) or len(set(value)) != len(value)):
        raise ValueError("INVALID_POLICY: unique bounded " + label + " required")
    return list(value)


def _evaluation(scene, projection):
    from . import guarded_runtime as guards
    from .native_scene_adapter import _EVALUATIONS
    identity = dict(guards.scene_instance(scene))
    receipt = _EVALUATIONS.get(identity["scene_instance_id"])
    if (not isinstance(receipt, dict) or receipt.get("native_completion") != "observed"
            or receipt.get("runtime_epoch") != guards.RUNTIME_EPOCH
            or not receipt.get("request_id") or not receipt.get("evaluation_receipt_digest")):
        raise ValueError("EVALUATION_RECEIPT_UNAVAILABLE: durable runtime evaluation completion required")
    if (receipt.get("projection_digest") != guards.digest(projection)
            or receipt.get("frames") != [0, projection["frames"]-1]):
        raise ValueError("STALE_EVALUATION: current full native projection differs from completed evaluation")
    return identity, copy.deepcopy(receipt)


def _ownership(projection, ids, source):
    owners = {}
    for obj in projection["objects"]:
        for behaviour in obj["behaviours"]:
            if behaviour["name"] != "RigInfo":
                continue
            members = {obj["id"]}
            for prop in behaviour["properties"]:
                if prop["name"] in ("rig_objects", "related_joints", "related_objects"):
                    if prop["kind"] != "ObjectRangeType":
                        raise ValueError("CHARACTER_OWNERSHIP_UNVERIFIED: RigInfo membership is not an observed object range")
                    members.update(x for x in prop["value"] if x is not None)
            for member in members:
                owners.setdefault(member, set()).add(obj["id"])
    selected = [owners.get(identifier, set()) for identifier in ids]
    if any(len(found) != 1 for found in selected) or len(set(next(iter(x)) for x in selected)) != 1:
        # A qualified independent object has identity ownership only. This
        # does not invent a RigInfo, semantic rig roles or physical metadata.
        from .native_interpolation_qualification import independent_projection_identity
        declared = source.get("scope", {}).get("profile", {}).get("character_id")
        if (len(ids)==1 and source.get("scope", {}).get("object_ids")==ids
                and declared in (None,ids[0]) and independent_projection_identity(projection,ids[0])):
            return {ids[0]:ids[0]}
        raise ValueError("CHARACTER_OWNERSHIP_UNVERIFIED: capture requires one unique actual RigInfo owner")
    owner = next(iter(selected[0]))
    declared = source.get("scope", {}).get("profile", {}).get("character_id")
    if declared is not None and declared != owner:
        raise ValueError("INVALID_WRITE_SCOPE: source profile differs from actual RigInfo ownership")
    return {identifier: owner for identifier in ids}


def _canonical_rotation(raw, basis):
    """Stable positive-hemisphere wxyz from an observed native quaternion."""
    import numpy as np
    q = np.asarray(raw, dtype=float)
    if q.shape != (4,) or not np.isfinite(q).all() or abs(float(q @ q)-1) > 1e-4:
        raise ValueError("INVALID_ROTATION: observed native quaternion is not finite and unit length")
    w, x, y, z = q / np.linalg.norm(q)
    matrix = np.array([[1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)],
                       [2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w)],
                       [2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y)]])
    m = basis @ matrix @ basis.T
    # The largest diagonal branch avoids cancellation near a half turn.
    candidates = np.array([1+np.trace(m), 1+m[0,0]-m[1,1]-m[2,2],
                           1-m[0,0]+m[1,1]-m[2,2], 1-m[0,0]-m[1,1]+m[2,2]])
    branch = int(np.argmax(candidates))
    d = 2*math.sqrt(max(0., float(candidates[branch])))
    if d <= 0:
        raise ValueError("INVALID_ROTATION: canonical quaternion extraction failed")
    if branch == 0: result = np.array([d/4, (m[2,1]-m[1,2])/d, (m[0,2]-m[2,0])/d, (m[1,0]-m[0,1])/d])
    elif branch == 1: result = np.array([(m[2,1]-m[1,2])/d, d/4, (m[0,1]+m[1,0])/d, (m[0,2]+m[2,0])/d])
    elif branch == 2: result = np.array([(m[0,2]-m[2,0])/d, (m[0,1]+m[1,0])/d, d/4, (m[1,2]+m[2,1])/d])
    else: result = np.array([(m[1,0]-m[0,1])/d, (m[0,2]+m[2,0])/d, (m[1,2]+m[2,1])/d, d/4])
    result /= np.linalg.norm(result)
    for component in result:
        if component != 0:
            if component < 0: result = -result
            break
    return result.tolist()


def _samples(projection, ids, context, space, basis, scale, required_rotations):
    import numpy as np
    objects = {row["id"]: row for row in projection["objects"]}
    data = {row["id"]: row for row in projection["data"]}
    positions, rotations, validity, raw_samples = {}, {}, {}, []
    raw_by_id = {}
    for identifier in ids:
        obj = objects.get(identifier)
        if obj is None:
            raise ValueError("INCOMPLETE_CAPTURE: native capture object does not exist")
        transforms = [row for row in obj["behaviours"] if row["name"] == "Transform"]
        if len(transforms) != 1:
            raise ValueError("INCOMPLETE_CAPTURE: unique observed Transform behaviour required")
        properties = {p["name"]: p for p in transforms[0]["properties"]}
        channels = {}
        for name in ("position", "rotation"):
            prop = properties.get(space+"_"+name)
            if prop is None or prop["kind"] != "DataType":
                raise ValueError("INCOMPLETE_CAPTURE: native Transform channel declaration unavailable")
            linked = prop["value"]
            if linked is None and name == "rotation":
                continue
            row = data.get(linked)
            if row is None or row["owner"] != identifier or row["mode"] not in ("Static", "Animation"):
                raise ValueError("INCOMPLETE_CAPTURE: native transform data ownership/mode unavailable")
            channels[name] = row
        if "position" not in channels or (identifier in required_rotations and "rotation" not in channels):
            raise ValueError("INCOMPLETE_CAPTURE: required native transform channel unavailable")
        raw_positions, raw_rotations = [], []
        for frame in context["frames"]:
            values = {}
            for name, row in channels.items():
                index = frame if row["mode"] == "Animation" else 0
                if index >= len(row["values"]):
                    raise ValueError("INCOMPLETE_CAPTURE: native data frame coverage missing")
                array = np.asarray(row["values"][index], dtype=float)
                if name == "position" and array.shape == (3, 1): array = array[:, 0]
                if array.shape != ((3,) if name == "position" else (4,)) or not np.isfinite(array).all():
                    raise ValueError("INCOMPLETE_CAPTURE: native transform has invalid finite shape")
                values[name] = array.tolist()
            raw_positions.append(values["position"])
            raw_rotations.append(values.get("rotation"))
        positions[identifier] = (np.asarray(raw_positions) @ basis.T * scale).tolist()
        has_rotation = "rotation" in channels
        if has_rotation: rotations[identifier] = [_canonical_rotation(q, basis) for q in raw_rotations]
        validity[identifier] = [[True, has_rotation] for _ in context["frames"]]
        raw_by_id[identifier] = (raw_positions, raw_rotations)
    for index, frame in enumerate(context["frames"]):
        for identifier in sorted(ids):
            p, q = raw_by_id[identifier]
            raw_samples.append({"frame": frame, "id": identifier, "position": p[index], "quaternion_wxyz": q[index]})
    return positions, rotations, validity, {"space": space, "frames": context["frames"], "samples": raw_samples}


def _layout_record(scene, record, arguments):
    from .native_key_layout import read_key_layout
    requested = copy.deepcopy(arguments)
    canonical = record["canonical_batch"]
    if (requested.get("capture_digest") != record["capture_digest"]
            or requested.get("capture_object_ids", requested.get("ids")) != canonical["object_ids"]
            or requested.get("context") != canonical["context"] or requested.get("space") != canonical["space"]
            or requested.get("frames") != canonical["context"]["frames"]):
        raise ValueError("CAPTURE_SCOPE_MISMATCH: key-layout request differs from privately issued capture")
    observed = read_key_layout(scene, requested)
    if observed["raw_sample_projection"] != record["sample_projection"]:
        raise ValueError("STALE_EVALUATION: native key-layout values differ from issued capture")
    record["key_layout_source_fingerprint"] = observed["source_fingerprint"]
    record["key_layout_arguments"] = requested
    return record


def observe_motion_capture(scene, arguments):
    """Issue only independently read values bound to a durable evaluation."""
    from . import guarded_runtime as guards
    from .native_adapters import installed_build
    from .native_scene_reader import read_scene
    allowed = {"ids", "space", "context", "source_binding", "required_rotation_ids", "key_layout_ids", "key_layout_channel"}
    if not isinstance(arguments, dict) or set(arguments)-allowed:
        raise ValueError("INVALID_POLICY: unknown native motion-capture arguments")
    guards.assert_loaded_package()
    ids = _ids(arguments.get("ids"), "capture IDs")
    context, basis, scale = _context(arguments.get("context"))
    if len(ids)*len(context["frames"]) > 16384:
        raise ValueError("RESOURCE_BUDGET_EXCEEDED: native motion-capture sample count")
    space = arguments.get("space")
    if space not in ("local", "global"):
        raise ValueError("INVALID_POLICY: explicit capture space required")
    required = arguments.get("required_rotation_ids", [])
    if required:
        required = _ids(required, "required rotation IDs")
    if not isinstance(required, list) or not set(required) <= set(ids):
        raise ValueError("INVALID_POLICY: rotation requirements escape capture scope")
    source = copy.deepcopy(arguments.get("source_binding"))
    guards.assert_source(scene, source)
    if source.get("scope", {}).get("context", context) != context:
        raise ValueError("CAPTURE_SCOPE_MISMATCH: source binding context differs")
    projection = read_scene(scene)
    if context["frames"][-1] >= projection["frames"]:
        raise ValueError("INCOMPLETE_CAPTURE: context frames exceed actual native timeline")
    identity, evaluation = _evaluation(scene, projection)
    ownership = _ownership(projection, ids, source)
    positions, rotations, validity, raw = _samples(projection, ids, context, space, basis, scale, set(required))
    canonical = {"context": context, "object_ids": ids, "space": space, "position_m": positions,
                 "rotation_wxyz": rotations, "channel_valid": validity, "source_binding": source}
    capture_digest = guards.digest(canonical)
    from .native_interpolation_qualification import independent_projection_identity, qualified_models, qualification
    model_qualification=qualification()
    qualified=(qualified_models() if len(ids)==1 and independent_projection_identity(projection,ids[0]) else [])
    record = {"canonical_batch": canonical, "capture_digest": capture_digest, "sample_projection": raw,
              "key_layout_source_fingerprint": None, **identity, "runtime_epoch": guards.RUNTIME_EPOCH,
              "native_build": installed_build(), "evaluation_receipt_digest": evaluation["evaluation_receipt_digest"],
              "evaluation": evaluation, "full_projection_digest": guards.digest(projection),
              "qualified_models": qualified, "ownership": ownership,
              "model_qualification_digest": guards.digest(model_qualification) if qualified else None,
              "provenance": {"reader": "native-model-assets-v1", "rotation_conversion": "basis_matrix_positive_wxyz_v1",
                             "context_authority": "explicit_declared_conversion_policy", "native_physical_metadata_verified": False,
                             "runtime_fingerprint": guards.LOADED_FINGERPRINT}}
    # Authored-key inspection is a separate bounded observation. A caller
    # requesting evaluated values alone must not implicitly invoke it.
    layout_ids = arguments.get("key_layout_ids")
    if layout_ids is not None:
        _ids(layout_ids, "key-layout driver IDs", 64)
        if not set(layout_ids) <= set(ids):
            raise ValueError("INVALID_POLICY: key-layout drivers escape capture scope")
        record = _layout_record(scene, record, {"ids": layout_ids, "space": space,
            "channel": arguments.get("key_layout_channel", "position"), "frames": context["frames"],
            "capture_digest": capture_digest, "capture_object_ids": ids, "context": context})
    # No callback or serialized flag can grant finite-model qualification.
    if len(_CAPTURES) >= _MAX_RECORDS and capture_digest not in _CAPTURES:
        del _CAPTURES[next(iter(_CAPTURES))]
    _CAPTURES[capture_digest] = (scene, copy.deepcopy(record))
    return copy.deepcopy(record)


def lookup_capture(capture_digest, key_layout_arguments=None):
    """Revalidate current native state before exposing a private issued record."""
    from . import guarded_runtime as guards
    from . import runtime as rt
    from .native_adapters import installed_build
    from .native_scene_reader import read_scene
    stored = _CAPTURES.get(capture_digest)
    if stored is None:
        return None
    guards.assert_loaded_package()
    scene, retained = stored
    if rt._scene_view() is not scene:
        raise ValueError("SCENE_CHANGED: issued capture belongs to an inactive scene tab")
    record = copy.deepcopy(retained)
    guards.assert_source(scene, record["canonical_batch"]["source_binding"])
    projection = read_scene(scene)
    identity, evaluation = _evaluation(scene, projection)
    if (record["runtime_epoch"] != guards.RUNTIME_EPOCH or record["native_build"] != installed_build()
            or any(record[key] != identity[key] for key in identity)
            or record["full_projection_digest"] != guards.digest(projection)
            or record["evaluation"] != evaluation or guards.digest(record["canonical_batch"]) != capture_digest):
        raise ValueError("STALE_EVALUATION: issued native capture no longer matches current scene/evaluation")
    requested = key_layout_arguments if key_layout_arguments is not None else record.get("key_layout_arguments")
    if requested is not None:
        record = _layout_record(scene, record, requested)
    return record


def verify_capture(canonical_batch, capture_digest):
    """Authenticate exact batch bytes against current process-private evidence."""
    from . import guarded_runtime as guards
    record = lookup_capture(capture_digest)
    if (record is None or guards.digest(canonical_batch) != capture_digest
            or record["canonical_batch"] != canonical_batch):
        raise ValueError("CAPTURE_UNVERIFIED: exact current runtime-issued canonical batch required")
    return {"capture_digest": capture_digest, "evaluation_receipt_digest": record["evaluation_receipt_digest"]}
