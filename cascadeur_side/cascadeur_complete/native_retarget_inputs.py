"""Private, read-only retarget evidence for one qualified parentless Transform.

Mapping, intent and physical conversion remain explicit declarations. Native
evidence certifies actual model rest and direct controller identity, not the
correctness of a caller's motion asset or the quality of a proposed trajectory.
"""
from __future__ import annotations

import copy
import json

from . import guarded_runtime as guards

ADAPTER_ID = "independent-parentless-position-v1"
_INPUTS = {}
_CONTROLLERS = {}
_MAX_RECORDS = 32


def _bounded(request):
    if not isinstance(request, dict) or len(json.dumps(request, allow_nan=False).encode("utf-8")) > 2 * 1024 * 1024:
        raise ValueError("RESOURCE_BUDGET_EXCEEDED: bounded retarget request required")


def _sha(value):
    if not isinstance(value, str) or len(value) != 64 or set(value) - set("0123456789abcdef"):
        raise ValueError("INVALID_POLICY: exact source artifact digest required")


def _rotation(value):
    import numpy as np
    matrix = np.asarray(value, dtype=float)
    if (matrix.shape != (3, 3) or not np.isfinite(matrix).all()
            or not np.allclose(matrix.T @ matrix, np.eye(3), rtol=0, atol=1e-8)
            or not np.isclose(np.linalg.det(matrix), 1, rtol=0, atol=1e-8)):
        raise ValueError("INVALID_ROTATION: explicit proper rotation matrix required")
    return matrix


def _registered_controller():
    from . import native_independent_position as position
    guards.assert_loaded_package()
    adapter = guards._ADAPTERS.get("animation.position_keys_set")
    if (type(adapter) is not position.NativeIndependentPositionAdapter or position._PROBE is not None
            or position._WRITER_BYTES is None or adapter.evidence_bytes != position._WRITER_BYTES):
        raise ValueError("POSITION_WRITER_UNQUALIFIED: privately registered production writer required")
    model = adapter._assert_qualified()
    return adapter, model


def _qualified_controller(scene):
    """Inspect the registered, privately qualified writer without executing it."""
    import numpy as np
    from .native_scene_reader import read_scene
    from .native_model_pose import read_independent_model_pose_rest
    from .native_key_layout import read_key_layout

    adapter, _ = _registered_controller()
    projection = read_scene(scene)
    if len(projection["objects"]) != 1 or not 1 <= projection["frames"] <= 256:
        raise ValueError("RETARGET_TARGET_UNSUPPORTED: bounded independent Transform required")
    identifier = projection["objects"][0]["id"]
    rest = read_independent_model_pose_rest(projection, [identifier])
    descriptor = read_key_layout(scene, {"ids": [identifier], "space": "global", "channel": "position",
        "frames": list(range(projection["frames"])), "capture_digest": "0" * 64,
        "capture_object_ids": [identifier], "context": None})
    if len(descriptor["drivers"]) != 1:
        raise ValueError("RETARGET_TARGET_UNSUPPORTED: exact observed position driver required")
    driver = descriptor["drivers"][0]
    protected = {row["frame"] for row in driver["boundary_keys"] if row.get("event") or row.get("locked")}
    frame = next((value for value in driver["frames"] if value not in protected), None)
    if frame is None:
        raise ValueError("INTENT_LOCK_VIOLATION: no writable existing position key")
    data = next(row for row in projection["data"] if row["id"] == driver["data_id"])
    value = np.asarray(data["values"][frame], dtype=float).reshape(3).tolist()
    # _inspect checks actual active scene, key ownership, finite interpolation,
    # complete position graph and private writer closure. It performs no write.
    inspected, _, _ = adapter._inspect(scene, "animation.position_keys_set", {
        "space": "global", "writes": [{"id": identifier, "frame": frame, "position": value}]})
    if inspected != projection:
        raise ValueError("SCENE_CHANGED: controller qualification projection changed")
    return {"adapter_id": ADAPTER_ID, "object_ids": [identifier], "channels": ["position"],
            "space": "global", "existing_keys_only": True,
            "target_scope": "observed", "private_target_observation_required": True,
            "model_qualification_digest": rest["provenance"]["independent_qualification_digest"],
            "writer_qualification_digest": guards.digest(json.loads(adapter.evidence_bytes)),
            "native_projection_digest": guards.digest(projection),
            "runtime_epoch": guards.RUNTIME_EPOCH, "adapter_fingerprint": guards.LOADED_FINGERPRINT}


def qualified_capability(scene):
    """Advertise the qualified domain separately from actual target authority.

    A file recipe can bootstrap from an unrelated/empty tab. Its future target
    still needs both private input and controller observations after loading.
    """
    try:
        adapter, model = _registered_controller()
    except (ValueError, RuntimeError, TypeError, KeyError, IndexError, StopIteration):
        return None
    try:
        return _qualified_controller(scene)
    except (ValueError, RuntimeError, TypeError, KeyError, IndexError, StopIteration):
        return {"adapter_id": ADAPTER_ID, "channels": ["position"], "space": "global",
                "existing_keys_only": True, "target_scope": "unobserved", "object_ids": [],
                "private_target_observation_required": True,
                "model_qualification_digest": guards.digest(model),
                "writer_qualification_digest": guards.digest(json.loads(adapter.evidence_bytes)),
                "runtime_epoch": guards.RUNTIME_EPOCH, "adapter_fingerprint": guards.LOADED_FINGERPRINT}


def _read_inputs(scene, request):
    import numpy as np
    from .native_scene_reader import read_scene
    from .native_motion_capture import _context
    from .native_model_pose import read_independent_model_pose_rest
    from .native_adapters import installed_build

    _bounded(request)
    if set(request) != {"source_binding", "profile", "context", "source_artifact_digest", "declaration", "intent"}:
        raise ValueError("INVALID_POLICY: exact retarget observation request required")
    guards.assert_loaded_package()
    source, profile, declaration = request["source_binding"], request["profile"], request["declaration"]
    guards.assert_source(scene, source)
    context, basis, units = _context(request["context"])
    _sha(request["source_artifact_digest"])
    from .native_recipe_target import _PROFILE_FIELDS
    if (not isinstance(profile, dict) or set(profile) - _PROFILE_FIELDS
            or not isinstance(profile.get("role_ids"), dict) or set(profile["role_ids"]) != {"root"}):
        raise ValueError("RETARGET_TARGET_UNSUPPORTED: exact independent root profile required")
    identifier = profile["role_ids"]["root"]
    if (not isinstance(identifier, str) or not identifier or profile.get("character_id") != identifier
            or profile.get("writable_ids") != [identifier]
            or any(profile.get(key) for key in ("derived_ids", "dependency_ids", "joint_axes", "joint_limits_rad", "bone_lengths_m", "mesh_ids"))
            or profile.get("controller_adapter_id") != ADAPTER_ID
            or profile.get("parent_ids", {}) not in ({}, {identifier: None})
            or source["scope"].get("object_ids") != [identifier]):
        raise ValueError("RETARGET_TARGET_UNSUPPORTED: independent position controller scope required")
    fields = {"mapping", "root_role", "axis_alignment", "root_basis", "scale", "target_root_anchor_m", "target_channels"}
    if (not isinstance(declaration, dict) or set(declaration) != fields
            or declaration["root_role"] != "root" or declaration["target_channels"] != ["position"]
            or not isinstance(declaration["mapping"], dict) or set(declaration["mapping"]) != {"root"}
            or not isinstance(declaration["mapping"]["root"], str) or not declaration["mapping"]["root"]
            or not isinstance(declaration["axis_alignment"], dict) or set(declaration["axis_alignment"]) != {"root"}):
        raise ValueError("RETARGET_MAPPING_UNSUPPORTED: explicit one-root position mapping required")
    _rotation(declaration["axis_alignment"]["root"])
    _rotation(declaration["root_basis"])
    scale = declaration["scale"]
    anchor = np.asarray(declaration["target_root_anchor_m"], dtype=float)
    if (type(scale) not in (int, float) or not np.isfinite(scale) or scale <= 0
            or anchor.shape != (3,) or not np.isfinite(anchor).all()):
        raise ValueError("INVALID_POLICY: explicit positive scale and canonical root anchor required")
    intent = request["intent"]
    if (not isinstance(intent, dict) or intent.get("action") != "retarget"
            or intent.get("root_policy") != "explicit_mapped_trajectory"
            or intent.get("editable_frames") != [context["frames"][0], context["frames"][-1]]
            or intent.get("contacts") or intent.get("allow_key_insertion") or intent.get("allow_interpolation_change")):
        raise ValueError("RETARGET_INTENT_UNSUPPORTED: explicit existing-key mapped-root intent required")
    projection = read_scene(scene)
    if context["frames"][-1] >= projection["frames"]:
        raise ValueError("INCOMPLETE_CAPTURE: retarget grid exceeds native timeline")
    native = read_independent_model_pose_rest(projection, [identifier])
    rests = profile.get("rest_local_transforms", {})
    if not isinstance(rests, dict) or set(rests) - {identifier, "root"}:
        raise ValueError("RIG_REST_UNVERIFIED: rest scope differs")
    raw = np.asarray(native["rest_local_transforms"][identifier])
    if any(not np.array_equal(np.asarray(value), raw) for value in rests.values()):
        raise ValueError("RIG_REST_MISMATCH: supplied rest differs from observed native model pose")
    # Native scene-local rest converts once to the canonical solver basis/SI.
    rest = {"position_m": (basis @ raw[:3, 3] * units).tolist(),
            "rotation_matrix": (basis @ raw[:3, :3] @ basis.T).tolist()}
    projection_digest = guards.digest(projection)
    guards.assert_source(scene, source)
    if guards.digest(read_scene(scene)) != projection_digest:
        raise ValueError("SCENE_CHANGED: retarget target changed while reading")
    return {"schema_version": 1, "kind": "retarget_inputs", "adapter_id": ADAPTER_ID,
            "request_digest": guards.digest(request), "source_binding_digest": guards.digest(source),
            "profile_digest": guards.digest(profile), "context_digest": guards.digest(context),
            "source_artifact_digest": request["source_artifact_digest"],
            "declaration_digest": guards.digest(declaration), "intent_digest": guards.digest(intent),
            "runtime_epoch": guards.RUNTIME_EPOCH, "adapter_fingerprint": guards.LOADED_FINGERPRINT,
            "native_build": installed_build(), "native_projection_digest": projection_digest,
            "target_rest": {"root": rest}, "target_parents": {"root": None},
            "axis_alignment": copy.deepcopy(declaration["axis_alignment"]),
            "root_basis": copy.deepcopy(declaration["root_basis"]),
            "target_root_anchor_m": copy.deepcopy(declaration["target_root_anchor_m"]),
            "qualification_digest": native["provenance"]["independent_qualification_digest"],
            "native_rest_evidence": native,
            "provenance": {"rest": "native_node3d_model_pose", "controller": "requires_separate_private_writer_attestation",
                "semantic_roles": "explicit_declaration", "mapping_and_intent": "explicit_declaration",
                "physical_conversion": "explicit_declaration", "native_physical_metadata_verified": False,
                "source_asset_contents_native_verified": False, "quality_verified": False},
            "evidence_ref": "native-retarget-inputs:" + guards.RUNTIME_EPOCH + ":" + guards.digest(request)}


def _remember(records, value, request):
    key = guards.digest(value)
    if key not in records and len(records) >= _MAX_RECORDS:
        records.pop(next(iter(records)))
    records[key] = {"request": copy.deepcopy(request), "observation": copy.deepcopy(value)}
    return value


def observe_retarget_inputs(scene, request):
    return _remember(_INPUTS, _read_inputs(scene, request), request)


def _verified_inputs(scene, observation, digest):
    guards.assert_loaded_package()
    record = _INPUTS.get(digest)
    if record is None or guards.digest(observation) != digest or record["observation"] != observation:
        raise ValueError("RETARGET_TARGET_PROVENANCE_UNVERIFIED: observation not issued in this runtime")
    if _read_inputs(scene, record["request"]) != observation:
        raise ValueError("SCENE_CHANGED: retarget source or target changed")
    return record


def _read_controllers(scene, arguments):
    import numpy as np
    _bounded(arguments)
    if set(arguments) != {"retarget_observation", "controller_request", "controller_request_digest", "controller_targets"}:
        raise ValueError("INVALID_POLICY: exact controller attestation request required")
    observation, request = arguments["retarget_observation"], arguments["controller_request"]
    record = _verified_inputs(scene, observation, guards.digest(observation))
    if (not isinstance(request, dict) or set(request) != {"adapter_id", "profile", "targets", "planned_world"}
            or request["adapter_id"] != ADAPTER_ID
            or guards.digest(request) != arguments["controller_request_digest"]
            or request["profile"] != record["request"]["profile"]):
        raise ValueError("RETARGET_CONTROLLER_SCOPE_MISMATCH")
    targets = request["targets"]
    if (not isinstance(targets, dict) or set(targets) != {"local", "world"}
            or targets["local"] != targets["world"] or request["planned_world"] != targets["world"]
            or not isinstance(targets["world"], dict) or set(targets["world"]) != {"root"}):
        raise ValueError("RETARGET_CONTROLLER_SCOPE_MISMATCH: exact parentless root target required")
    value = targets["world"]["root"]
    if not isinstance(value, dict) or set(value) != {"position_m", "rotation_matrix"}:
        raise ValueError("RETARGET_CONTROLLER_SCOPE_MISMATCH: exact root pose required")
    count = len(record["request"]["context"]["frames"])
    positions, rotations = np.asarray(value["position_m"], dtype=float), np.asarray(value["rotation_matrix"], dtype=float)
    if (positions.shape != (count, 3) or rotations.shape != (count, 3, 3)
            or not np.isfinite(positions).all() or not np.isfinite(rotations).all()):
        raise ValueError("INCOMPLETE_CAPTURE: exact finite controller grid required")
    for rotation in rotations:
        _rotation(rotation)
    identifier = request["profile"]["role_ids"]["root"]
    capability = _qualified_controller(scene)
    if (capability["object_ids"] != [identifier]
            or capability["native_projection_digest"] != observation["native_projection_digest"]
            or capability["model_qualification_digest"] != observation["qualification_digest"]):
        raise ValueError("RETARGET_CONTROLLER_SCOPE_MISMATCH: current qualified writer differs")
    output = {"position_m": {identifier: positions.tolist()}, "space": "global"}
    if output != arguments["controller_targets"]:
        raise ValueError("RETARGET_CONTROLLER_OUTPUT_MISMATCH: direct global position mapping required")
    return {"schema_version": 1, "kind": "controller_targets", "adapter_id": ADAPTER_ID,
            "controller_request_digest": guards.digest(request), "controller_targets_digest": guards.digest(output),
            "retarget_inputs_digest": guards.digest(observation),
            "source_binding_digest": observation["source_binding_digest"],
            "profile_digest": observation["profile_digest"], "context_digest": observation["context_digest"],
            "native_projection_digest": observation["native_projection_digest"],
            "runtime_epoch": guards.RUNTIME_EPOCH, "adapter_fingerprint": guards.LOADED_FINGERPRINT,
            "controller_targets": output, "qualification_digest": observation["qualification_digest"],
            "writer_qualification_digest": capability["writer_qualification_digest"],
            "provenance": {"controller_identity": "native_qualified_independent_transform",
                "retarget_trajectory": "host_computed_explicit_mapping", "quality_verified": False},
            "evidence_ref": "native-retarget-controller:" + guards.RUNTIME_EPOCH + ":" + guards.digest(request)}


def observe_controller_targets(scene, request):
    return _remember(_CONTROLLERS, _read_controllers(scene, request), request)


def verify_observation(scene, observation, digest, kind):
    if kind == "retarget_inputs":
        _verified_inputs(scene, observation, digest)
        return {"retarget_inputs_digest": digest, "request_digest": observation["request_digest"]}
    guards.assert_loaded_package()
    record = _CONTROLLERS.get(digest)
    if (kind != "controller_targets" or record is None or guards.digest(observation) != digest
            or record["observation"] != observation or _read_controllers(scene, record["request"]) != observation):
        raise ValueError("RIG_ADAPTER_UNVERIFIED: controller observation not current and privately issued")
    return {"observation_digest": digest, "controller_request_digest": observation["controller_request_digest"],
            "controller_targets_digest": observation["controller_targets_digest"],
            "retarget_inputs_digest": observation["retarget_inputs_digest"]}
