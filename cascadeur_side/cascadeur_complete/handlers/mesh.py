from __future__ import annotations

import re

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
    frames = [int(item) for item in arguments.get("frames") or []]
    if not frames:
        raise ValueError("frames must be a non-empty list of frame numbers")
    if len(frames) > MAX_MESH_FRAMES:
        raise ValueError(f"At most {MAX_MESH_FRAMES} frames per call")
    name = str(arguments.get("name", "mesh"))
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", name):
        raise ValueError("name must be 1-64 characters of A-Z, a-z, 0-9, _ or -")
    manager = domain.assets_manager()
    mesh = manager.at(behaviours.get_behaviour_asset(behaviour, "mesh"))
    dependency = manager.at(behaviours.get_behaviour_asset(behaviour, "mesh_dependency"))
    per_polygon = int(_value(mesh, "vertices_in_polygon"))
    corners = numpy.array([int(item.position_index) for item in _value(mesh, "vertices")], dtype=numpy.int32)
    polygons = corners.reshape(-1, per_polygon)
    # Fan-triangulate quads (or larger polygons) so the host always gets triangles.
    triangles = numpy.concatenate(
        [polygons[:, [0, corner, corner + 1]] for corner in range(1, per_polygon - 1)], axis=0
    )
    joints = [
        str(viewer.get_object_name(item)) for item in behaviours.get_behaviour_objects_range(behaviour, "linked_objects")
    ]
    weights = _value(dependency, "vertices_weights")
    dominant = numpy.full(len(weights), -1, dtype=numpy.int16)
    for index, items in enumerate(weights):
        best = None
        for item in items:
            if best is None or float(item.weight) > best[1]:
                best = (int(item.index), float(item.weight))
        if best is not None:
            dominant[index] = best[0]
    positions = numpy.zeros((len(frames), len(weights), 3), dtype=numpy.float32)
    for row, frame in enumerate(frames):
        skinned = _value(csc.domain.assets.calc_skinned_mesh(domain, object_id, frame), "positions")
        positions[row] = numpy.asarray(skinned, dtype=numpy.float32)[:, :3]
    directory = runtime_root() / "state" / "mesh"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (name + ".npz")
    numpy.savez(
        str(path),
        positions=positions,
        triangles=triangles.astype(numpy.int32),
        dominant=dominant,
        joints=numpy.array(joints),
        frames=numpy.array(frames, dtype=numpy.int32),
    )
    if not path.is_file() or path.stat().st_size == 0:
        raise AssertionError("POSTCONDITION_FAILED: mesh sample file was not written")
    return {
        "path": str(path),
        "bytes": int(path.stat().st_size),
        "frame_count": len(frames),
        "vertex_count": int(positions.shape[1]),
        "triangle_count": int(len(triangles)),
        "joint_count": len(joints),
    }, []
