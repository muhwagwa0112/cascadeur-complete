from __future__ import annotations

import re
import hashlib
import uuid

from ..handler_registry import handler

MAX_MESH_FRAMES = 2000


def _value(owner, name):
    value = getattr(owner, name)
    return value() if callable(value) else value


def _mesh_object(domain, arguments, context):
    viewer = domain.model_viewer()
    requested = arguments.get("id")
    if requested:
        return context["object_id"](str(requested))
    meshes = [item for item in viewer.get_objects() if str(viewer.get_object_type_name(item)) == "Mesh Object"]
    if len(meshes) != 1:
        raise ValueError(f"Scene has {len(meshes)} mesh objects; pass id")
    return meshes[0]


@handler("animation.mesh_sample", postconditions=("mesh_sample_written",))
def mesh_sample(scene, arguments, _request, context):
    """Write a character's skinned mesh for a set of frames to an .npz file under the runtime state.

    Whole-clip cleanup needs the real surface (collision capsules miss hips,
    chest and fingers) to see an arm pass through the body. The file holds
    float32 positions per requested frame, the triangle list, the joint names
    the mesh is bound to and each vertex's dominant joint index.
    """
    import numpy

    from ..runtime import runtime_root

    csc = context["csc"]
    domain = context["domain_scene"](scene)
    viewer = domain.model_viewer()
    behaviours = viewer.behaviour_viewer()
    object_id = _mesh_object(domain, arguments, context)
    behaviour = behaviours.get_behaviour_by_name(object_id, "MeshObject")
    frames = arguments.get("frames") or []
    if not isinstance(frames, list) or not frames:
        raise ValueError("frames must be a non-empty list of frame numbers")
    if any(isinstance(item, bool) or not isinstance(item, int) or item < 0 for item in frames):
        raise ValueError("frames must contain nonnegative integers")
    if any(a >= b for a, b in zip(frames, frames[1:])):
        raise ValueError("frames must be unique and increasing")
    frame_count = int(domain.layers_viewer().frames_count())
    if any(frame >= frame_count for frame in frames):
        raise ValueError("frame is outside the active clip")
    if len(frames) > MAX_MESH_FRAMES:
        raise ValueError(f"At most {MAX_MESH_FRAMES} frames per call")
    name = str(arguments.get("name", "mesh"))
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", name):
        raise ValueError("name must be 1-64 characters of A-Z, a-z, 0-9, _ or -")
    manager = domain.assets_manager()
    mesh = manager.at(behaviours.get_behaviour_asset(behaviour, "mesh"))
    dependency = manager.at(behaviours.get_behaviour_asset(behaviour, "mesh_dependency"))
    per_polygon = int(_value(mesh, "vertices_in_polygon"))
    if per_polygon < 3:
        raise ValueError("mesh polygons require at least three vertices")
    corners = numpy.array([int(item.position_index) for item in _value(mesh, "vertices")], dtype=numpy.int32)
    polygons = corners.reshape(-1, per_polygon)
    # Fan-triangulate quads (or larger polygons) so the host always gets triangles.
    triangles = numpy.concatenate(
        [polygons[:, [0, corner, corner + 1]] for corner in range(1, per_polygon - 1)], axis=0
    )
    linked = list(behaviours.get_behaviour_objects_range(behaviour, "linked_objects"))
    joints = [str(viewer.get_object_name(item)) for item in linked]
    joint_ids = [str(item) for item in linked]
    weights = _value(dependency, "vertices_weights")
    weights = list(weights)
    if not len(weights) or numpy.any(triangles < 0) or numpy.any(triangles >= len(weights)):
        raise ValueError("mesh topology index is outside the vertex array")
    dominant = numpy.full(len(weights), -1, dtype=numpy.int32)
    offsets, weight_indices, weight_values = [0], [], []
    for index, items in enumerate(weights):
        best = None
        seen = set()
        for item in items:
            joint, weight = int(item.index), float(item.weight)
            if joint < 0 or joint >= len(joints) or joint in seen or not numpy.isfinite(weight) or weight < 0:
                raise ValueError("invalid skin weight index/value or duplicate influence")
            seen.add(joint)
            weight_indices.append(joint)
            weight_values.append(weight)
            if weight > 0 and (best is None or weight > best[1]):
                best = (joint, weight)
        if best is not None:
            dominant[index] = best[0]
        offsets.append(len(weight_indices))
    estimated_bytes = len(frames) * len(weights) * 3 * 4
    max_bytes = arguments.get("max_bytes", 256 * 1024 * 1024)
    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes <= 0 or estimated_bytes > max_bytes:
        raise ValueError("RESOURCE_BUDGET_EXCEEDED: mesh capture requires %s bytes" % estimated_bytes)
    positions = numpy.empty((len(frames), len(weights), 3), dtype=numpy.float32)
    for row, frame in enumerate(frames):
        skinned = _value(csc.domain.assets.calc_skinned_mesh(domain, object_id, frame), "positions")
        values = numpy.asarray(skinned, dtype=numpy.float32)
        if values.ndim != 2 or values.shape[0] != len(weights) or values.shape[1] < 3 or not numpy.isfinite(values[:, :3]).all():
            raise ValueError("INCOMPLETE_CAPTURE: evaluated mesh vertex coverage is invalid")
        positions[row] = values[:, :3]
    directory = runtime_root() / "state" / "mesh"
    directory.mkdir(parents=True, exist_ok=True)
    capture_id = uuid.uuid4().hex
    path = directory / (name + "-" + capture_id + ".npz")
    numpy.savez(
        str(path),
        positions=positions,
        triangles=triangles.astype(numpy.int32),
        dominant=dominant,
        joints=numpy.array(joints),
        joint_ids=numpy.array(joint_ids),
        known_weights=(dominant >= 0),
        weight_offsets=numpy.asarray(offsets, dtype=numpy.int64),
        weight_indices=numpy.asarray(weight_indices, dtype=numpy.int32),
        weight_values=numpy.asarray(weight_values, dtype=numpy.float64),
        frames=numpy.array(frames, dtype=numpy.int32),
    )
    if not path.is_file() or path.stat().st_size == 0:
        raise AssertionError("POSTCONDITION_FAILED: mesh sample file was not written")
    return {
        "capture_id": capture_id,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "path": str(path),
        "bytes": int(path.stat().st_size),
        "frame_count": len(frames),
        "vertex_count": int(positions.shape[1]),
        "triangle_count": int(len(triangles)),
        "joint_count": len(joints),
    }, []
