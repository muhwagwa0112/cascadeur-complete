"""Read-only, process-issued structural evidence for an explicit recipe target.

Role names, constraints and physical conversions remain declarations. This
module neither expands source scope nor qualifies a writer. Rest, when supplied,
must match actual native inverse-bind evidence, never the current pose.
"""
from __future__ import annotations

import copy
import json
import math

from . import guarded_runtime as guards

_RECORDS = {}
_MAX_RECORDS = 16
_TARGET_FIELDS = {"character_id", "root_id", "object_ids", "layer_ids", "role_ids",
                  "rig_profile", "rig_profile_digest", "required_mesh_ids", "optional_mesh_ids"}
_PROFILE_FIELDS = {"profile_id", "character_id", "role_ids", "writable_ids", "derived_ids",
                   "dependency_ids", "parent_ids", "rest_local_transforms", "joint_axes",
                   "joint_limits_rad", "bone_lengths_m", "mesh_ids", "controller_adapter_id"}


def _ids(value, name, *, empty=True):
    if (not isinstance(value, list) or len(value) > 5000 or (not empty and not value)
            or any(not isinstance(x, str) or not x or len(x) > 256 for x in value)
            or len(set(value)) != len(value)):
        raise ValueError("INVALID_POLICY: exact unique bounded " + name + " required")
    return list(value)


def _owner(projection, ids, source):
    from .native_motion_capture import _ownership
    try:
        return _ownership(projection, ids, source)
    except ValueError:
        # The other code-owned finite adapter independently qualifies a single
        # parentless Basic/Node3d/Transform. assert_source already reran its exact
        # reader; a wire claim cannot register this concrete adapter instance.
        from .native_adapters import TransformAdapter
        adapter = guards._ADAPTERS.get(source["scope"].get("operation_name"))
        if (type(adapter) is TransformAdapter and len(ids) == 1
                and source["scope"].get("object_ids") == ids):
            return {ids[0]: ids[0]}
        raise


def _read(scene, request):
    import numpy as np
    from .native_scene_reader import read_scene
    from .native_motion_capture import _context
    from .native_bind_rest import read_native_bind_rest, _matrix
    from .native_adapters import installed_build

    if not isinstance(request, dict) or set(request) != {"source_binding", "character", "context"}:
        raise ValueError("INVALID_POLICY: exact recipe target request required")
    if len(json.dumps(request, allow_nan=False).encode("utf-8")) > 2 * 1024 * 1024:
        raise ValueError("RESOURCE_BUDGET_EXCEEDED: recipe target metadata")
    source, target = request["source_binding"], request["character"]
    guards.assert_loaded_package()
    guards.assert_source(scene, source)
    context, _, scale = _context(request["context"])
    if not isinstance(target, dict) or set(target) != _TARGET_FIELDS:
        raise ValueError("INVALID_POLICY: exact character declaration required")
    ids = _ids(target["object_ids"], "target objects", empty=False)
    layers = _ids(target["layer_ids"], "target layers", empty=False)
    if (not set(ids) <= set(source["scope"].get("object_ids", []))
            or not set(layers) <= set(source["scope"].get("layer_ids", []))):
        raise ValueError("INVALID_WRITE_SCOPE: target outside authenticated source")
    profile, roles = target["rig_profile"], target["role_ids"]
    if (not isinstance(profile, dict) or set(profile) - _PROFILE_FIELDS
            or guards.digest(profile) != target["rig_profile_digest"]
            or profile.get("character_id") != target["character_id"]
            or profile.get("role_ids") != roles or not isinstance(roles, dict) or not roles
            or any(not isinstance(k, str) or not k for k in roles)
            or len(set(roles.values())) != len(roles) or not set(roles.values()) <= set(ids)
            or target["root_id"] not in ids):
        raise ValueError("RIG_MAPPING_AMBIGUOUS: exact declared profile and target required")
    profile_ids = set(ids)
    for field in ("writable_ids", "derived_ids", "dependency_ids"):
        profile_ids.update(_ids(profile.get(field, []), field))
    if set(profile.get("writable_ids", [])) & set(profile.get("derived_ids", [])):
        raise ValueError("INVALID_WRITE_SCOPE: writable and derived IDs overlap")
    parents = profile.get("parent_ids", {})
    rests, lengths = profile.get("rest_local_transforms", {}), profile.get("bone_lengths_m", {})
    if any(not isinstance(value, dict) for value in (parents, rests, lengths)):
        raise ValueError("INVALID_POLICY: profile maps required")
    profile_ids.update(parents)
    profile_ids.update(value for value in parents.values() if value is not None)
    def stable(key):
        identifier = roles.get(key, key)
        if not isinstance(identifier, str) or not identifier:
            raise ValueError("RIG_MAPPING_AMBIGUOUS: invalid stable profile reference")
        return identifier
    profile_ids.update(stable(key) for key in rests)
    profile_ids.update(stable(key) for key in lengths)
    if not profile_ids <= set(source["scope"].get("object_ids", [])):
        raise ValueError("INVALID_WRITE_SCOPE: profile dependencies outside source closure")
    projection = read_scene(scene)
    if context["frames"][-1] >= projection["frames"]:
        raise ValueError("INVALID_POLICY: clip exceeds observed frame range")
    objects = {row["id"]: row for row in projection["objects"]}
    layer_rows = {row["id"]: row for row in projection["layers"]}
    if not profile_ids <= set(objects) or not set(layers) <= set(layer_rows):
        raise ValueError("SCENE_CHANGED: declared object or layer is absent")
    if not set(ids) <= {key for layer in layers for key in layer_rows[layer]["object_ids"]}:
        raise ValueError("INVALID_WRITE_SCOPE: target objects are not in the declared native layers")
    ownership = _owner(projection, sorted(profile_ids), source)
    if any(value != target["character_id"] for value in ownership.values()):
        raise ValueError("CHARACTER_OWNERSHIP_UNVERIFIED: declared character differs")
    actual_parents = {}
    for identifier in profile_ids:
        rows = [p for b in objects[identifier]["behaviours"] if b["name"] == "Basic"
                for p in b["properties"] if p["name"] == "parent" and p["kind"] == "ObjectType"]
        if len(rows) != 1:
            raise ValueError("RIG_MAPPING_AMBIGUOUS: native Basic parent unavailable")
        actual_parents[identifier] = rows[0]["value"]
    if any(actual_parents[key] != value for key, value in parents.items()):
        raise ValueError("RIG_MAPPING_AMBIGUOUS: declared parent differs from native Basic")
    native_rest = None
    if rests or lengths:
        required = sorted({stable(key) for key in rests} | {stable(key) for key in lengths})
        native_rest = read_native_bind_rest(scene, required)
        if native_rest["errors"] or native_rest["unobserved"]:
            raise ValueError("RIG_REST_UNVERIFIED: complete native inverse-bind evidence required")
        for key, value in rests.items():
            matrix, _ = _matrix(value, "recipe rest:" + key)
            if not np.array_equal(matrix, np.asarray(native_rest["rest_local_transforms"][stable(key)])):
                raise ValueError("RIG_REST_MISMATCH: rest must equal native scene-local inverse-bind matrix")
        for key, value in lengths.items():
            expected = float(np.linalg.norm(np.asarray(native_rest["rest_local_transforms"][stable(key)])[:3, 3])) * scale
            if type(value) not in (int, float) or not math.isfinite(value) or value <= 0 or value != expected:
                raise ValueError("RIG_BONE_LENGTH_MISMATCH: declared conversion of native bind length differs")
    required_mesh = _ids(target["required_mesh_ids"], "required meshes")
    optional_mesh = _ids(target["optional_mesh_ids"], "optional meshes")
    profile_mesh = _ids(profile.get("mesh_ids", []), "profile meshes")
    meshes = set(required_mesh) | set(optional_mesh) | set(profile_mesh)
    if not (set(required_mesh) | set(profile_mesh)) <= set(objects):
        raise ValueError("MESH_CAPTURE_INCOMPLETE: required native mesh is absent")
    observed_mesh = sorted(meshes & set(objects))
    if observed_mesh:
        if not set(observed_mesh) <= set(source["scope"].get("object_ids", [])):
            raise ValueError("INVALID_WRITE_SCOPE: native mesh outside authenticated source closure")
        mesh_owners = _owner(projection, observed_mesh, source)
        if any(value != target["character_id"] for value in mesh_owners.values()):
            raise ValueError("CHARACTER_OWNERSHIP_UNVERIFIED: native mesh owner differs")
        if any(not any(b["name"] == "MeshObject" for b in objects[key]["behaviours"]) for key in observed_mesh):
            raise ValueError("MESH_CAPTURE_INCOMPLETE: declared mesh has no native MeshObject")
    projection_digest = guards.digest(projection)
    guards.assert_source(scene, source)
    if guards.digest(read_scene(scene)) != projection_digest:
        raise ValueError("SCENE_CHANGED: native target changed while reading")
    request_digest = guards.digest(request)
    return {"schema_version": 1, "kind": "recipe_target", "request_digest": request_digest,
            "source_binding_digest": guards.digest(source), "profile_digest": guards.digest(profile),
            "target_digest": guards.digest(target), "context_digest": guards.digest(context),
            "runtime_epoch": guards.RUNTIME_EPOCH, "adapter_fingerprint": guards.LOADED_FINGERPRINT,
            "native_build": installed_build(), "native_projection_digest": projection_digest,
            "ownership": {key: ownership[key] for key in ids}, "object_ids": ids, "layer_ids": layers,
            "structural_evidence": {"parent_ids": actual_parents, "profile_object_ids": sorted(profile_ids),
                "native_rest_digest": guards.digest(native_rest) if native_rest is not None else None,
                "observed_mesh_ids": observed_mesh, "missing_optional_mesh_ids": sorted(set(optional_mesh) - set(objects)),
                "layers": {key: {field: layer_rows[key][field] for field in ("locked", "visible", "object_ids")} for key in layers}},
            "provenance": {"structure": "native_model_and_private_current_source",
                "rest": "native_mesh_dependency_inverse_bind" if native_rest is not None else "not_requested",
                "semantic_roles": "explicit_declaration", "joint_constraints": "explicit_declaration",
                "conversion_policy": "explicit_declaration", "native_physical_metadata_verified": False,
                "write_capability_granted": False},
            "evidence_ref": "native-recipe-target:" + guards.RUNTIME_EPOCH + ":" + request_digest + ":" + projection_digest}


def observe_recipe_target(scene, request):
    value = _read(scene, request)
    key = guards.digest(value)
    if key not in _RECORDS and len(_RECORDS) >= _MAX_RECORDS:
        _RECORDS.pop(next(iter(_RECORDS)))
    _RECORDS[key] = {"request": copy.deepcopy(request), "observation": copy.deepcopy(value)}
    return value


def verify_recipe_target(observation, digest):
    import csc
    guards.assert_loaded_package()
    record = _RECORDS.get(digest)
    if record is None or guards.digest(observation) != digest or record["observation"] != observation:
        raise ValueError("RIG_ADAPTER_UNVERIFIED: target observation not issued in this runtime")
    scene = csc.app.get_application().get_scene_manager().current_scene()
    if _read(scene, record["request"]) != observation:
        raise ValueError("SCENE_CHANGED: recipe target structure differs")
    return {"observation_digest": digest, "request_digest": observation["request_digest"]}
