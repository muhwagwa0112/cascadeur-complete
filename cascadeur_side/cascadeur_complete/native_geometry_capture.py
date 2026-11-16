"""Guarded evaluated-geometry files, sealed only after the terminal receipt.

Coordinate/synchronous contracts are process-private actual SDK observations.
No such contract has been qualified for this installed build yet. The raw SDK
reader remains useful independently, but cannot issue canonical actual proof.
"""
from __future__ import annotations

import copy
import hashlib
import hmac
import json
import os
import uuid
from dataclasses import asdict
from pathlib import Path

from . import guarded_runtime as guards
from .geometry_policy import CoordinateContract, ReadBoundary, assert_read_compute_read, plan_capture, _validated_basis

OPERATION = "system.observe_geometry_capture"
_FIELDS = {"capture_id", "motion_source_binding", "motion_capture_digest", "origin_request_id", "context",
           "mesh_ids", "pairs", "max_calculations", "max_array_bytes", "max_artifact_bytes"}
_CONTRACTS = {}  # No wire issuer. Actual owned-fixture calibration is still required.
_PENDING = {}
_SEALED = {}
_DOMAIN = b"cascadeur.geometry-candidate-completion-v1\0"


def _uuid(value):
    if not isinstance(value, str) or str(uuid.UUID(value)) != value:
        raise ValueError("GEOMETRY_UUID_INVALID")
    return value


def _bytes(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def _sha_array(value):
    return hashlib.sha256(memoryview(value).cast("B")).hexdigest()


def validate_arguments(arguments):
    from .native_motion_capture import _context, _ids
    if not isinstance(arguments, dict) or set(arguments) != _FIELDS:
        raise ValueError("GEOMETRY_ARGUMENTS_INVALID: exact finite capture policy required")
    _uuid(arguments["capture_id"]); _uuid(arguments["origin_request_id"])
    _context(arguments["context"])
    ids = _ids(arguments["mesh_ids"], "geometry mesh IDs")
    pairs = arguments["pairs"]
    if (not isinstance(pairs, list) or not pairs or any(not isinstance(pair, list) or len(pair) != 2
            or any(type(key) is not str or key not in ids for key in pair) or pair[0] == pair[1] for pair in pairs)
            or len({tuple(sorted(pair)) for pair in pairs}) != len(pairs)
            or {key for pair in pairs for key in pair} != set(ids)):
        raise ValueError("GEOMETRY_PAIR_CLOSURE_MISSING")
    for name, cap in (("max_calculations", 32768), ("max_array_bytes", 1024**3), ("max_artifact_bytes", 2*1024**3)):
        if type(arguments[name]) is not int or not 0 < arguments[name] <= cap:
            raise ValueError("GEOMETRY_BUDGET_INVALID: " + name)
    return arguments


def geometry_contract_status():
    from .native_geometry_qualification import calibration_status
    return {"qualified": False, "code": "GEOMETRY_CALCULATION_CONTRACT_UNQUALIFIED",
        "missing": ["known_transform_coordinate_calibration", "operation_correlated_synchronous_calculation",
                    "qualified_dependency_and_transform_readers"],
        "runtime_epoch": guards.RUNTIME_EPOCH, "runtime_fingerprint": guards.LOADED_FINGERPRINT,
        "prerequisite_calibration": calibration_status()}


def require_geometry_contract(scene, projection, arguments):
    """Caller hashes, declared context and returned array shape are not proof."""
    from .native_adapters import installed_build
    # This lookup is intentionally private and currently empty. A future
    # code-owned calibration must bind actual SDK producer/dependency semantics
    # before populating it; there is no generic registration/public flag here.
    key = (installed_build(), guards.LOADED_FINGERPRINT, guards.RUNTIME_EPOCH)
    contract = _CONTRACTS.get(key)
    if contract is None:
        status = geometry_contract_status()
        raise ValueError(status["code"] + ": " + ",".join(status["missing"]))
    contract.assert_current(scene, projection, arguments)
    return contract


def _origin(scene, arguments, capture):
    from . import runtime as rt
    from .native_checkpoint_restore import _original_terminal
    request, receipt = _original_terminal(rt.runtime_root(), arguments["origin_request_id"])
    result = (receipt or {}).get("terminal_result") or {}
    data = result.get("result") or {}
    source = request.get("source_binding")
    successor = data.get("post_source_binding")
    if (receipt is None or receipt.get("outcome") != "succeeded" or not result.get("ok")
            or result.get("outcome") != "succeeded" or receipt.get("runtime_epoch") != guards.RUNTIME_EPOCH
            or not isinstance(source, dict) or not isinstance(successor, dict)
            or receipt.get("scene_after") != successor.get("binding")
            or data.get("native_completion") != "observed"
            or capture["evaluation"].get("post_source_digest") != guards.digest(arguments["motion_source_binding"])):
        raise ValueError("GEOMETRY_ORIGIN_COMPLETION_UNVERIFIED")
    # Historical origin source is authenticated by its signed request, not
    # asserted as current. The private evaluation/capture proves current raw
    # state; an unrelated historical scene cannot be rebound by a caller.
    current = guards.scene_instance(scene)
    if any(successor.get("binding", {}).get(key) != current[key] for key in ("scene_instance_id", "document_lineage_id")):
        raise ValueError("GEOMETRY_ORIGIN_SCENE_CHANGED")
    if arguments["origin_request_id"] != capture["evaluation"].get("request_id"):
        # Mutation origins need an explicit authenticated successor -> current
        # evaluation full-projection rebind. No such issuer exists yet.
        raise ValueError("GEOMETRY_ORIGIN_SUCCESSOR_REBIND_UNAVAILABLE")
    if guards.digest(receipt) != capture["evaluation_receipt_digest"]:
        raise ValueError("GEOMETRY_ORIGIN_RECEIPT_DIFFERS")
    return request, receipt, source, successor


def _inputs(scene, arguments):
    from .native_scene_reader import read_scene
    from .native_motion_capture import lookup_capture
    validate_arguments(arguments)
    guards.assert_loaded_package()
    guards.assert_source(scene, arguments["motion_source_binding"])
    capture = lookup_capture(arguments["motion_capture_digest"])
    if (capture is None or capture["canonical_batch"]["context"] != arguments["context"]
            or capture["canonical_batch"]["source_binding"] != arguments["motion_source_binding"]):
        raise ValueError("GEOMETRY_MOTION_CAPTURE_UNVERIFIED")
    projection = read_scene(scene)
    if capture["full_projection_digest"] != guards.digest(projection):
        raise ValueError("GEOMETRY_MOTION_CAPTURE_STALE")
    actual = {row["id"]: row for row in projection["objects"]}
    if any(key not in actual or len([b for b in actual[key]["behaviours"] if b["name"] == "MeshObject"]) != 1
           for key in arguments["mesh_ids"]):
        raise ValueError("GEOMETRY_MESH_OWNERSHIP_UNVERIFIED")
    origin = _origin(scene, arguments, capture)
    contract = require_geometry_contract(scene, projection, arguments)
    return projection, capture, origin, contract


def _boundary(scene, arguments, capture, projection, contract):
    from . import runtime as rt
    from .native_adapters import installed_build
    from .native_export import selection_observation
    if rt._scene_view() is not scene:
        raise ValueError("GEOMETRY_SCENE_NOT_ACTIVE")
    identity = guards.scene_instance(scene)
    # Closure digests include all observed assets/data/settings/links, rather
    # than assuming the requested mesh alone contains its skin dependencies.
    topology = guards.digest({"assets": projection["assets"], "meshes": arguments["mesh_ids"]})
    skin = guards.digest({"assets": projection["assets"], "objects": projection["objects"]})
    transforms = guards.digest({key: projection[key] for key in ("objects", "data", "settings")})
    return ReadBoundary(installed_build(), guards.RUNTIME_EPOCH, guards.LOADED_FINGERPRINT,
        identity["scene_instance_id"], guards.scene_instance(rt._scene_view())["scene_instance_id"],
        identity["document_lineage_id"], guards.digest(arguments["motion_source_binding"]),
        arguments["motion_capture_digest"], capture["evaluation_receipt_digest"],
        capture["full_projection_digest"], guards.digest(projection), topology, skin, transforms,
        guards.digest(arguments["context"]), guards.digest(selection_observation(scene)),
        int(rt._domain_scene(scene).get_current_frame(False)))


def _write_file(path, write, *, remaining):
    """Every byte is fresh, owned and bounded; partial files are retained."""
    class BoundedWriter:
        def __init__(self, stream): self.stream = stream
        def write(self, value):
            if self.stream.tell() + len(value) > remaining:
                raise ValueError("GEOMETRY_ARTIFACT_BUDGET_EXCEEDED")
            return self.stream.write(value)
        def __getattr__(self, name): return getattr(self.stream, name)
    with path.open("xb") as stream:
        write(BoundedWriter(stream))
        if stream.tell() > remaining:
            raise ValueError("GEOMETRY_ARTIFACT_BUDGET_EXCEEDED")
        stream.flush(); os.fsync(stream.fileno())
    with path.open("rb") as stream:
        return {"path": str(path), "sha256": hashlib.file_digest(stream, "sha256").hexdigest(), "bytes": path.stat().st_size}


class NativeGeometryCaptureAdapter:
    """Adapter-only file effect. No legacy observer may execute this route."""
    adapter_id = "native-actual-geometry-v1"

    def required_scope(self, scene, scope):
        arguments = scope.get("operation_arguments")
        if scope.get("operation_name") != OPERATION:
            raise ValueError("GEOMETRY_OPERATION_INVALID")
        projection, _capture, _origin_value, _contract = _inputs(scene, arguments)
        return {"adapter_id": self.adapter_id, "operation_name": OPERATION,
            "operation_arguments": copy.deepcopy(arguments), "operation_arguments_digest": guards.digest(arguments),
            "object_ids": [row["id"] for row in projection["objects"]],
            "layer_ids": [row["id"] for row in projection["layers"]], "frames": [0, projection["frames"]-1]}

    def capture(self, scene, scope):
        projection, _capture, _origin_value, _contract = _inputs(scene, scope["operation_arguments"])
        return {"coverage_complete": True, "authored_projection": projection, "sample_projection": projection}

    def execute(self, scene, arguments, request):
        import numpy as np
        from . import runtime as rt
        from .handlers.mesh import _read_mesh_arrays, _sample_mesh_positions
        from .native_scene_reader import read_scene
        if request.get("operations") != [{"name": OPERATION, "arguments": arguments}]:
            raise ValueError("GEOMETRY_OPERATION_INVALID")
        source = request.get("source_binding")
        guards.assert_source(scene, source, operation_name=OPERATION, arguments=arguments)
        projection, capture, origin, contract = _inputs(scene, arguments)
        before = _boundary(scene, arguments, capture, projection, contract)
        assert_read_compute_read(before, before, expected_source_digest=guards.digest(arguments["motion_source_binding"]),
            expected_motion_capture_digest=arguments["motion_capture_digest"], expected_context_digest=guards.digest(arguments["context"]))
        context = {"csc": rt.csc, "strict_geometry_shape": True}
        domain = rt._domain_scene(scene)
        native_ids = {str(key): key for key in domain.model_viewer().get_objects()}
        # Bound raw topology/skin conversion before allocating its arrays.
        # The full reader's independently bounded serialized assets contain
        # every weight/index/name. Reserve conservative Python-list overhead
        # as well as dense NumPy conversion, not only the final f32 samples.
        static_reservation = len(_bytes({"assets":projection["assets"],"objects":projection["objects"]}))*64
        if static_reservation >= arguments["max_array_bytes"]:
            raise ValueError("GEOMETRY_STATIC_ARRAY_BUDGET_EXCEEDED")
        arrays = {key: _read_mesh_arrays(domain, native_ids[key], context) for key in arguments["mesh_ids"]}
        counts = {key: len(value["dominant"]) for key,value in arrays.items()}
        static = {key: sum(np.asarray(a).nbytes for a in value.values()) for key,value in arrays.items()}
        retained_static = max(static_reservation,sum(static.values()))
        grid = arguments["context"]
        plan = plan_capture(frames=tuple(grid["frames"]), time_s=tuple(grid["time_s"]), vertex_counts=counts,
            static_array_bytes={key:retained_static+counts[key]*3*8 for key in arrays}, pairs=tuple(tuple(pair) for pair in arguments["pairs"]),
            required_mesh_ids=tuple(arguments["mesh_ids"]), max_calculations=arguments["max_calculations"],
            max_array_bytes=arguments["max_array_bytes"])
        # Stored uncompressed arrays plus conservative NPY/ZIP headers and
        # bounded candidate+sidecar JSON are reserved before the first mkdir.
        estimate = sum(counts[w.mesh_id]*len(w.frames)*3*12 + static[w.mesh_id] + 65536 for w in plan.windows) + 2*1024**2 + len(plan.windows)*2048
        if estimate > arguments["max_artifact_bytes"]:
            raise ValueError("GEOMETRY_ARTIFACT_BUDGET_EXCEEDED")
        identifier = arguments["capture_id"]
        folder = rt.runtime_root() / "state" / "geometry" / identifier
        if folder.exists() or identifier in _PENDING or identifier in _SEALED or len(_PENDING)+len(_SEALED) >= 64:
            raise ValueError("GEOMETRY_CAPTURE_NOT_FRESH_OR_RECORD_BUDGET_EXCEEDED")
        for parent in (folder,*folder.parents):
            if parent.is_symlink() or (parent.exists() and getattr(parent.lstat(),"st_file_attributes",0)&0x400):
                raise ValueError("GEOMETRY_PATH_ALIAS_FORBIDDEN")
            if parent == rt.runtime_root():
                break
        coordinate = contract.coordinate_contract(arguments["context"])
        basis = np.asarray(_validated_basis(coordinate), dtype=np.float64)
        if (coordinate.conversion_policy_digest != guards.digest(arguments["context"])
                or coordinate.metres_per_native_unit != arguments["context"]["metres_per_scene_unit"]
                or not np.array_equal(basis,arguments["context"]["scene_to_solver_basis"])):
            raise ValueError("GEOMETRY_DECLARED_CONVERSION_POLICY_DIFFERS")
        def unchanged():
            guards.assert_source(scene, source, operation_name=OPERATION, arguments=arguments)
            current_projection, current_capture, _, _ = _inputs(scene, arguments)
            after = _boundary(scene, arguments, current_capture, current_projection, contract)
            assert_read_compute_read(before, after, expected_source_digest=before.source_digest,
                expected_motion_capture_digest=before.motion_capture_digest, expected_context_digest=before.context_digest)
        guards.before_write(unchanged)
        folder.mkdir(parents=True, exist_ok=False)
        windows = {key: [] for key in plan.mesh_ids}
        retained = 0
        for index, window in enumerate(plan.windows):
            unchanged()
            raw = np.ascontiguousarray(_sample_mesh_positions(domain, native_ids[window.mesh_id], list(window.frames), counts[window.mesh_id], context), dtype="<f4")
            canonical = np.empty(raw.shape, dtype="<f8")
            for row, frame in enumerate(window.frames):
                world = np.empty(raw[row].shape, dtype="<f8")
                np.copyto(world, raw[row])
                if coordinate.raw_space == "native_global":
                    np.matmul(world, basis.T, out=canonical[row])
                else:
                    matrix = np.asarray(contract.mesh_to_world(scene, window.mesh_id, frame), dtype=np.float64)
                    if matrix.shape != (4,4) or not np.isfinite(matrix).all() or not np.array_equal(matrix[3], [0,0,0,1]):
                        raise ValueError("GEOMETRY_AFFINE_TRANSFORM_UNVERIFIED")
                    np.matmul(world, matrix[:3,:3].T, out=canonical[row])
                    canonical[row] += matrix[:3,3]
                    np.matmul(canonical[row], basis.T, out=world)
                    np.copyto(canonical[row], world)
                canonical[row] *= coordinate.metres_per_native_unit
            if not np.isfinite(canonical).all():
                raise ValueError("GEOMETRY_CANONICAL_OVERFLOW")
            triangles = np.ascontiguousarray(arrays[window.mesh_id]["triangles"], dtype="<i8")
            guards.before_write(unchanged)
            def write(stream):
                np.savez(stream, raw_positions=raw, canonical_positions_m=canonical, triangles=triangles,
                    frames=np.asarray(window.frames,dtype="<i8"))
            file = _write_file(folder/(str(index)+".npz"), write, remaining=arguments["max_artifact_bytes"]-retained)
            retained += file["bytes"]
            windows[window.mesh_id].append({**file, "frames": list(window.frames), "position_field": "canonical_positions_m",
                "canonical_metres": True, "vertices_shape": list(canonical.shape), "raw_vertices_sha256": _sha_array(raw),
                "canonical_vertices_sha256": _sha_array(canonical), "triangles_shape": list(triangles.shape), "triangles_sha256": _sha_array(triangles)})
            # No prior window may remain resident while the next SDK sample
            # allocation is being constructed.
            del raw, canonical, triangles, world
        unchanged()
        _origin_request, origin_receipt, origin_source, origin_successor = origin
        manifest = {"schema_version": 1, "capture_kind": "native_actual", "geometry_capture_id": identifier,
            "source_digest": guards.digest(origin_source), "successor_digest": guards.digest(origin_successor),
            "capture_source_digest": before.source_digest, "geometry_operation_source_digest": guards.digest(source),
            "origin_completion_receipt_digest": guards.digest(origin_receipt), "evaluation_receipt_digest": before.evaluation_receipt_digest,
            "motion_capture_digest": before.motion_capture_digest, "topology_digest": before.topology_digest,
            "skin_digest": before.skin_digest, "transform_projection_digest": before.transform_projection_digest,
            "context_digest": before.context_digest, "frames": list(plan.frames), "time_s": list(plan.time_s),
            "space": "global", "units": "metres", "windows": windows, "pairs": copy.deepcopy(arguments["pairs"]),
            "coordinate_evidence_digest": coordinate.coordinate_evidence_digest,
            "synchronous_calculation_evidence_digest": contract.synchronous_calculation_evidence_digest,
            "full_projection_digest": before.full_projection_digest, "runtime_epoch": before.runtime_epoch,
            "installed_build": before.installed_build, "runtime_fingerprint": before.loaded_fingerprint,
            "context_authority": "explicit_declared_conversion_policy", "native_physical_metadata_verified": False}
        candidate = {"manifest": manifest, "request_id": request["request_id"], "request_digest": guards.digest(request),
            "boundary": asdict(before)}
        guards.before_write(unchanged)
        candidate_file = _write_file(folder/"candidate.json", lambda stream: stream.write(_bytes(candidate)),
            remaining=arguments["max_artifact_bytes"]-retained)
        retained += candidate_file["bytes"]
        sidecar = {"purpose": "geometry-candidate-completion-v1", "geometry_capture_id": identifier,
            "request_id": request["request_id"], "candidate_digest": guards.digest(candidate), "candidate_file": candidate_file}
        sidecar["mac"] = hmac.new(rt._bridge_key(rt.runtime_root()), _DOMAIN+_bytes(sidecar), hashlib.sha256).hexdigest()
        guards.before_write(unchanged)
        completion_file = _write_file(folder/"completion.json", lambda stream: stream.write(_bytes(sidecar)),
            remaining=arguments["max_artifact_bytes"]-retained)
        unchanged()
        _PENDING[identifier] = (scene, copy.deepcopy(request), copy.deepcopy(candidate), candidate_file, completion_file)
        guards.finish_write()
        identity = dict(guards.scene_instance(scene))
        guards.observe_effect(OPERATION, "completed", scene_before=identity, scene_after=identity,
                              detail={"candidate_digest": guards.digest(candidate), "calculation_count": plan.calculation_count})
        return {"geometry_capture_id": identifier, "candidate_digest": guards.digest(candidate),
                "request_id": request["request_id"], "state": "awaiting_terminal_receipt"}, []


def _validate_file(file):
    path = Path(file["path"])
    if path.is_symlink() or not path.is_file():
        raise ValueError("GEOMETRY_ARTIFACT_CHANGED")
    with path.open("rb") as stream:
        if os.fstat(stream.fileno()).st_size != file["bytes"] or hashlib.file_digest(stream,"sha256").hexdigest()!=file["sha256"]:
            raise ValueError("GEOMETRY_ARTIFACT_CHANGED")


def _validate_completion(file, candidate, candidate_file):
    from . import runtime as rt
    path = Path(file["path"])
    if path.is_symlink() or file["bytes"] > 65536:
        raise ValueError("GEOMETRY_COMPLETION_SIDECAR_INVALID")
    with path.open("rb") as stream:
        raw = stream.read(65537)
    if len(raw) != file["bytes"] or hashlib.sha256(raw).hexdigest() != file["sha256"]:
        raise ValueError("GEOMETRY_COMPLETION_SIDECAR_CHANGED")
    value = json.loads(raw)
    mac = value.pop("mac", None)
    expected = {"purpose":"geometry-candidate-completion-v1", "geometry_capture_id":candidate["manifest"]["geometry_capture_id"],
        "request_id":candidate["request_id"], "candidate_digest":guards.digest(candidate), "candidate_file":candidate_file}
    if (value != expected or not isinstance(mac,str) or not hmac.compare_digest(mac,
            hmac.new(rt._bridge_key(rt.runtime_root()),_DOMAIN+_bytes(value),hashlib.sha256).hexdigest())):
        raise ValueError("GEOMETRY_COMPLETION_SIDECAR_UNAUTHENTICATED")


def finalize_geometry_capture(scene, request, result, receipt):
    """Memory-only sealing after an authenticated durable terminal success."""
    operations = request.get("operations") or []
    if len(operations) != 1 or operations[0].get("name") != OPERATION:
        return
    identifier = operations[0]["arguments"]["capture_id"]
    pending = _PENDING.get(identifier)
    if pending is None:
        raise ValueError("GEOMETRY_CANDIDATE_UNAVAILABLE")
    stored_scene, original, candidate, candidate_file, completion_file = pending
    data = result.get("result") or {}
    if (scene is not stored_scene or request != original or not result.get("ok") or result.get("outcome") != "succeeded"
            or receipt.get("phase") != "terminal" or receipt.get("outcome") != "succeeded"
            or receipt.get("request_digest") != guards.digest(request) or receipt.get("result_digest") != guards.digest(result)
            or data.get("geometry_capture_id") != identifier or data.get("candidate_digest") != guards.digest(candidate)
            or not isinstance(data.get("post_source_binding"),dict)):
        raise ValueError("GEOMETRY_TERMINAL_RECEIPT_UNVERIFIED")
    _validate_file(candidate_file); _validate_completion(completion_file,candidate,candidate_file)
    projection, capture, _, contract = _inputs(scene, operations[0]["arguments"])
    if asdict(_boundary(scene,operations[0]["arguments"],capture,projection,contract)) != candidate["boundary"]:
        raise ValueError("GEOMETRY_SOURCE_CHANGED_BEFORE_TERMINAL_SEAL")
    manifest = copy.deepcopy(candidate["manifest"])
    manifest.update(completion_receipt_digest=guards.digest(receipt),
        geometry_operation_successor_digest=guards.digest(data["post_source_binding"]))
    _SEALED[identifier] = (stored_scene, manifest, operations[0]["arguments"], candidate_file, completion_file,candidate)
    del _PENDING[identifier]


def get_geometry_capture(capture_id):
    record = _SEALED.get(_uuid(capture_id))
    if record is None:
        raise ValueError("GEOMETRY_TERMINAL_SEAL_UNAVAILABLE")
    scene, manifest, arguments, candidate_file, completion_file,candidate = record
    from . import runtime as rt
    if rt._scene_view() is not scene:
        raise ValueError("GEOMETRY_SCENE_CHANGED")
    projection, capture, _, contract = _inputs(scene, arguments)
    boundary = _boundary(scene, arguments, capture, projection, contract)
    if asdict(boundary) != candidate["boundary"]:
        raise ValueError("GEOMETRY_SOURCE_CHANGED")
    _validate_file(candidate_file); _validate_completion(completion_file,candidate,candidate_file)
    for windows in manifest["windows"].values():
        for window in windows:
            _validate_file(window)
    return {"manifest": copy.deepcopy(manifest), "geometry_digest": guards.digest(manifest)}


def verify_geometry_capture(manifest, digest):
    if not isinstance(manifest, dict) or guards.digest(manifest) != digest:
        raise ValueError("GEOMETRY_MANIFEST_DIGEST_DIFFERS")
    current = get_geometry_capture(manifest.get("geometry_capture_id"))
    if current["manifest"] != manifest or current["geometry_digest"] != digest:
        raise ValueError("GEOMETRY_MANIFEST_NOT_PRIVATELY_ISSUED")
    return {"geometry_digest": digest, "completion_receipt_digest": manifest["completion_receipt_digest"],
            "evaluation_receipt_digest": manifest["evaluation_receipt_digest"]}
