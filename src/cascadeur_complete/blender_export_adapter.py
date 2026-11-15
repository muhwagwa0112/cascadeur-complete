"""Fixed subprocess adapter. Run by Blender with a host-owned JSON manifest.

No host package imports are required inside Blender. This adapter deliberately
supports classic Actions in Blender 4.2/4.3 and the exact single-slot FBX
importer binding in Blender 4.5. Other layouts fail closed.
"""

from __future__ import annotations

import hashlib
import json
import math
import sys
from pathlib import Path


def _digest_file(path, max_bytes=512 * 1024**2):
    digest, count = hashlib.sha256(), 0
    with Path(path).open("rb") as stream:
        while block := stream.read(1024 * 1024):
            count += len(block)
            if count > max_bytes:
                raise ValueError("TARGET_FILE_BUDGET_EXCEEDED")
            digest.update(block)
    return digest.hexdigest()


def _canonical(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def _installed_bytes():
    import bpy
    import importlib
    files = {name: _digest_file(importlib.import_module(name).__file__) for name in (
        'io_scene_fbx', 'io_scene_fbx.import_fbx', 'io_scene_fbx.parse_fbx', 'io_scene_fbx.fbx_utils')}
    return {'blender_version': list(bpy.app.version[:3]),
            'blender_executable_sha256': _digest_file(bpy.app.binary_path),
            'importer_fingerprint': _canonical(files), 'importer_files': files,
            'adapter_fingerprint': _digest_file(__file__)}


def describe_installation(manifest):
    """Observe the actual consumer bytes; never import an artifact or issue quality."""
    if (set(manifest) != {'mode', 'nonce', 'report_path'} or manifest['mode'] != 'installation'
            or not isinstance(manifest['nonce'], str) or len(manifest['nonce']) != 48):
        raise ValueError('TARGET_INSTALLATION_REQUEST_INVALID')
    return {'schema_version': 1, 'kind': 'installed_consumer', 'nonce': manifest['nonce'],
            **_installed_bytes()}


def _action_binding(obj, version):
    animation = obj.animation_data
    action = animation.action if animation else None
    if action is None:
        return None, ()
    if tuple(version[:2]) in ((4, 2), (4, 3)):
        return action, tuple(action.fcurves)
    if tuple(version[:2]) != (4, 5):
        raise ValueError("TARGET_ACTION_ADAPTER_UNSUPPORTED")
    slot = animation.action_slot
    if slot is None or len(action.slots) != 1 or slot != action.slots[0]:
        raise ValueError("TARGET_ACTION_SLOT_AMBIGUOUS")
    if len(action.layers) != 1 or len(action.layers[0].strips) != 1:
        raise ValueError("TARGET_ACTION_LAYER_UNSUPPORTED")
    bag = action.layers[0].strips[0].channelbag(slot)
    if bag is None:
        raise ValueError("TARGET_ACTION_SLOT_UNBOUND")
    return action, tuple(bag.fcurves)


def _artifact_object_rest(manifest, scene):
    """Decode static FBX defaults for independent root Nulls, never an Action.

    The fingerprint-pinned Blender importer supplies the same explicit FBX
    transform formula used by its animation decoder. No evaluated pose enters
    this path. Parented models, armatures and meshes remain outside its scope.
    """
    from io_scene_fbx import import_fbx as reader, parse_fbx, fbx_utils
    from bpy_extras.io_utils import axis_conversion
    from mathutils import Matrix
    profile = manifest['profile']
    mapping = profile['target_import_settings']['bone_mapping']
    if (profile['include_mesh'] or profile['allowed_helper_nodes'] or not mapping
            or any(value[1] is not None for value in mapping.values())):
        raise ValueError('TARGET_ANIMATED_CONTAINER_REST_UNSUPPORTED')
    root, version = parse_fbx.parse(manifest['artifact']['path'])
    if version not in (7400, 7500, 7700):
        raise ValueError('TARGET_OBJECT_REST_VERSION_UNSUPPORTED')

    def one(parent, name, *, optional=False):
        found = [node for node in parent.elems if node.id == name]
        if len(found) > 1 or (not found and not optional):
            raise ValueError('TARGET_OBJECT_REST_METADATA_AMBIGUOUS')
        return found[0] if found else reader.fbx_elem_nil

    settings = one(one(root, b'GlobalSettings'), b'Properties70')
    objects, connections = one(root, b'Objects'), one(root, b'Connections')
    models = [node for node in objects.elems if node.id == b'Model']
    if not 0 < len(models) <= 256 or len(models) != len(mapping):
        raise ValueError('TARGET_OBJECT_REST_SCOPE_UNSUPPORTED')
    by_name, model_ids = {}, set()
    for node in models:
        if (len(node.props) != 3 or node.props_type != b'LSS' or node.props[2] != b'Null'
                or node.props[0] in model_ids):
            raise ValueError('TARGET_OBJECT_REST_SCOPE_UNSUPPORTED')
        name = node.props[1].split(b'\x00', 1)[0].removeprefix(b'Model::').decode('utf-8')
        if not name or '/' in name or '\\' in name or name in by_name:
            raise ValueError('TARGET_OBJECT_REST_SCOPE_UNSUPPORTED')
        by_name[name] = node
        model_ids.add(node.props[0])
    if set(by_name) != set(mapping) or any(mapping[name][0] != name for name in mapping):
        raise ValueError('TARGET_OBJECT_REST_MAPPING_AMBIGUOUS')
    parents = {identity: [] for identity in model_ids}
    for edge in connections.elems:
        if edge.id == b'C' and len(edge.props) >= 3 and edge.props[0] == b'OO' and edge.props[1] in model_ids:
            parents[edge.props[1]].append(edge.props[2])
    if any(value != [0] for value in parents.values()):
        raise ValueError('TARGET_PARENTED_OBJECT_REST_UNSUPPORTED')
    if any(row['parent_path'] is not None for row in profile['skeleton_map']):
        raise ValueError('TARGET_PARENTED_OBJECT_REST_UNSUPPORTED')
    # Match the importer's Model/KFbxNode -> Model/FbxNode template lookup.
    definitions = one(root, b'Definitions', optional=True)
    object_types = [node for node in definitions.elems
                    if node.id == b'ObjectType' and node.props == [b'Model']]
    if len(object_types) > 1:
        raise ValueError('TARGET_OBJECT_REST_METADATA_AMBIGUOUS')
    template = reader.fbx_elem_nil
    if object_types:
        for kind in (b'KFbxNode', b'FbxNode'):
            candidates = [node for node in object_types[0].elems
                          if node.id == b'PropertyTemplate' and node.props == [kind]]
            if len(candidates) > 1:
                raise ValueError('TARGET_OBJECT_REST_METADATA_AMBIGUOUS')
            if candidates:
                template = candidates[0]
                break
    template_props = one(template, b'Properties70', optional=True)
    up = (reader.elem_props_get_integer(settings, b'UpAxis'), reader.elem_props_get_integer(settings, b'UpAxisSign'))
    front = (reader.elem_props_get_integer(settings, b'FrontAxis'), reader.elem_props_get_integer(settings, b'FrontAxisSign'))
    coord = (reader.elem_props_get_integer(settings, b'CoordAxis'), reader.elem_props_get_integer(settings, b'CoordAxisSign'))
    axes = {value: key for key, value in fbx_utils.RIGHT_HAND_AXES.items()}.get((up, front, coord))
    unit = reader.elem_props_get_number(settings, b'UnitScaleFactor')
    if axes is None or type(unit) not in (float, int) or not math.isfinite(unit) or unit <= 0:
        raise ValueError('TARGET_OBJECT_REST_BASIS_UNSUPPORTED')
    if not math.isclose(unit / 100, profile['metres_per_export_unit'], rel_tol=1e-10):
        raise ValueError('TARGET_OBJECT_REST_UNITS_MISMATCH')
    axis_up, axis_forward = axes
    global_matrix = (Matrix.Scale(unit / fbx_utils.units_blender_to_fbx_factor(scene), 4)
                     @ axis_conversion(from_forward=axis_forward, from_up=axis_up).to_4x4())
    # The importer prepends this frame to root objects. It changes world
    # coordinates but leaves the object's local axes in the FBX frame (it is
    # not a change-of-basis conjugation). Keep it separate from authored rest.
    root_frame = global_matrix.to_3x3().normalized()
    matrices, provenance = {}, {}
    for name, node in by_name.items():
        props = (one(node, b'Properties70', optional=True), template_props)
        # The importer approximates spherical Euler order; this adapter does not.
        if reader.elem_props_get_enum(props, b'RotationOrder', 0) not in range(6):
            raise ValueError('TARGET_OBJECT_REST_ROTATION_ORDER_UNSUPPORTED')
        transform = reader.blen_read_object_transform_preprocess(props, node, Matrix(), True)
        local, _, _ = reader.blen_read_object_transform_do(transform)
        matrix = global_matrix @ local
        rotation = matrix.to_3x3()
        gram = rotation.transposed() @ rotation
        scale2 = sum(gram[index][index] for index in range(3)) / 3
        if (not all(math.isfinite(value) for row in matrix for value in row) or scale2 <= 0
                or rotation.determinant() <= 0 or any(abs(gram[i][j] - (scale2 if i == j else 0)) > 1e-7 * scale2
                                                     for i in range(3) for j in range(3))):
            raise ValueError('TARGET_OBJECT_REST_NONRIGID_UNSUPPORTED')
        matrices[name] = matrix
        provenance[name] = {'source': 'artifact_static_model_and_template', 'model_id': node.props[0],
                            'artifact_sha256': manifest['artifact']['sha256'],
                            'domain': 'independent_parentless_fbx_null',
                            'fbx_static_rest_matrix': [list(row) for row in local],
                            'importer_root_frame': [list(row) for row in root_frame],
                            'blender_rest_matrix': [list(row) for row in matrix]}
    return matrices, provenance, root_frame


def run(manifest):
    import bpy
    from mathutils import Matrix

    profile, expected = manifest["profile"], manifest["expected"]
    settings = profile["target_import_settings"]
    if tuple(bpy.app.version[:3]) != tuple(settings["blender_version"]):
        raise ValueError("TARGET_VERSION_MISMATCH")
    if tuple(bpy.app.version[:2]) not in ((4, 2), (4, 3), (4, 5)):
        raise ValueError("TARGET_ACTION_ADAPTER_UNSUPPORTED")
    if _canonical(settings) != profile["target_import_settings_digest"]:
        raise ValueError("TARGET_SETTINGS_MISMATCH")
    if _digest_file(manifest["artifact"]["path"], manifest["artifact"]["bytes"]) != manifest["artifact"]["sha256"]:
        raise ValueError("ARTIFACT_CHANGED")
    if _digest_file(__file__) != profile["target_adapter_fingerprint"]:
        raise ValueError("TARGET_ADAPTER_MISMATCH")
    installed = _installed_bytes()
    if installed['importer_fingerprint'] != settings.get("importer_fingerprint"):
        raise ValueError("TARGET_IMPORTER_FINGERPRINT_MISMATCH")
    if installed['blender_executable_sha256'] != settings.get("blender_executable_sha256"):
        raise ValueError("TARGET_EXECUTABLE_FINGERPRINT_MISMATCH")
    paths = {entry["node_path"] for entry in profile["skeleton_map"]}
    if paths != set(settings["bone_mapping"]) or paths != set(expected["position_m"]):
        raise ValueError("EXPORT_RIG_MAPPING_AMBIGUOUS")
    estimated = len(expected["time_s"]) * max(len(paths), 1) * 7 * 26
    if estimated > settings["max_report_bytes"]:
        raise ValueError("TARGET_CAPTURE_BUDGET_EXCEEDED")
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    # This classic importer converts seconds to scene.render.fps frames. Keep
    # fps_base at one and evaluate the same physical timestamps explicitly.
    scene.render.fps = min(32767, max(1, round(profile["fps_num"] / profile["fps_den"])))
    scene.render.fps_base = 1
    outcome = bpy.ops.import_scene.fbx(filepath=manifest["artifact"]["path"], use_anim=True,
                                      anim_offset=settings["anim_offset"], use_image_search=False,
                                      automatic_bone_orientation=False, use_manual_orientation=False,
                                      global_scale=1, bake_space_transform=False)
    if "FINISHED" not in outcome:
        raise ValueError("TARGET_IMPORT_FAILED")
    basis = Matrix(settings["blender_to_canonical_basis"])
    inverse = basis.transposed()
    resolved, reverse = {}, {}
    if set(settings["helper_mapping"]) != set(profile["allowed_helper_nodes"]):
        raise ValueError("TARGET_HELPER_MAPPING_INCOMPLETE")
    for helper, object_name in settings["helper_mapping"].items():
        if bpy.data.objects.get(object_name) is None:
            raise ValueError("TARGET_HELPER_MAPPING_INCOMPLETE")
        reverse[(object_name, None)] = helper
    for path, (object_name, bone_path) in settings["bone_mapping"].items():
        obj = bpy.data.objects.get(object_name)
        if obj is None:
            raise ValueError("EXPORT_RIG_MAPPING_AMBIGUOUS")
        bone = None
        if bone_path is not None:
            if obj.type != "ARMATURE":
                raise ValueError("EXPORT_RIG_MAPPING_AMBIGUOUS")
            names = bone_path.split("/")
            bone = obj.pose.bones.get(names[-1])
            if bone is None:
                raise ValueError("EXPORT_RIG_MAPPING_AMBIGUOUS")
            actual, current = [], bone
            while current:
                actual.append(current.name)
                current = current.parent
            if "/".join(reversed(actual)) != bone_path:
                raise ValueError("EXPORT_RIG_MAPPING_AMBIGUOUS")
        key = (object_name, bone_path)
        if key in reverse:
            raise ValueError("EXPORT_RIG_MAPPING_AMBIGUOUS")
        reverse[key] = path
        resolved[path] = (obj, bone)
    parent_paths, rest_rotations, rest_lengths, rest_positions = {}, {}, {}, {}
    object_rest, object_rest_provenance, object_local_inverse = {}, {}, {}
    animated_containers = []
    for path, (obj, bone) in resolved.items():
        # An animated object's static defaults come from a separate artifact
        # decode. An evaluated/imported first pose is never used as its rest.
        action, curves = _action_binding(obj, bpy.app.version)
        if action and any(not curve.data_path.startswith('pose.bones[') for curve in curves):
            if bone is not None:
                raise ValueError('TARGET_ANIMATED_CONTAINER_REST_UNSUPPORTED')
            animated_containers.append(path)
    if animated_containers:
        object_rest, object_rest_provenance, root_frame = _artifact_object_rest(manifest, scene)
        # B maps Blender world vectors to canonical vectors. G maps FBX world
        # vectors to Blender world, so B G maps the unchanged FBX local axes to
        # canonical axes. R_blender = G R_fbx for these root Nulls, therefore
        # R_canonical = B R_blender (B G)^T, not B R_blender B^T. Both the
        # independently decoded static rest and evaluated animation use this
        # same frame rule; neither is substituted for native source rest.
        local_to_canonical = basis @ root_frame
        for path, (obj, bone) in resolved.items():
            if bone is not None or obj.type != 'EMPTY' or obj.parent is not None:
                raise ValueError('TARGET_OBJECT_REST_SCOPE_UNSUPPORTED')
            object_local_inverse[path] = local_to_canonical.transposed()
            object_rest_provenance[path].update({
                'canonical_rotation_formula': 'B @ R_blender @ (B @ G).T',
                'blender_world_to_canonical_basis': [list(row) for row in basis],
                'fbx_local_to_canonical_basis': [list(row) for row in local_to_canonical],
                'native_source_rest_requirement': 'independent_host_observation_and_comparison',
            })
    for path, (obj, bone) in resolved.items():
        if bone is not None:
            parent_bone = bone.parent
            if parent_bone:
                names, current = [], parent_bone
                while current:
                    names.append(current.name)
                    current = current.parent
                parent_key = (obj.name, "/".join(reversed(names)))
            else:
                parent_key = (obj.name, None)
            matrix = obj.matrix_world @ bone.bone.matrix_local
            rest_lengths[path] = (obj.matrix_world.to_3x3() @ (bone.bone.tail_local - bone.bone.head_local)).length
        else:
            parent_key = (obj.parent.name, None) if obj.parent else None
            matrix = object_rest.get(path, obj.matrix_world)
        parent_paths[path] = reverse.get(parent_key)
        rest_rotations[path] = (basis @ matrix.to_3x3().normalized()
                                @ object_local_inverse.get(path, inverse)).to_quaternion()
        rest_positions[path] = list(basis @ matrix.translation)
        if parent_paths[path] != expected["parent_paths"][path]:
            raise ValueError("EXPORT_SKELETON_TOPOLOGY")
    for item in profile["skeleton_map"]:
        length = item.get("rest_length_m")
        if length is not None and abs(rest_lengths.get(item["node_path"], -1) - length) > profile["tolerances"]["bone_length_m"]:
            raise ValueError("EXPORT_BIND_POSE_MISMATCH")
    animated_objects = {settings["bone_mapping"][channel["node_path"]][0]
                        for channel in profile["required_channels"] if channel["animated"]}
    actions = {}
    for object_name in animated_objects:
        obj = bpy.data.objects[object_name]
        animation = obj.animation_data
        action, curves = _action_binding(obj, bpy.app.version)
        if action is None or not curves or profile["take_name"] not in action.name.split("|"):
            raise ValueError("EXPORT_TARGET_ACTION_BINDING")
        if animation.nla_tracks and any(not track.mute for track in animation.nla_tracks):
            raise ValueError("EXPORT_TARGET_NLA_UNSUPPORTED")
        actions[object_name] = action.name
    meshes = {}
    if profile["include_mesh"]:
        if set(settings["mesh_mapping"]) != set(profile["mesh_refs"]):
            raise ValueError("EXPORT_MESH_MAPPING_AMBIGUOUS")
        for path, name in settings["mesh_mapping"].items():
            obj = bpy.data.objects.get(name)
            if obj is None or obj.type != "MESH":
                raise ValueError("EXPORT_MESH_MAPPING_AMBIGUOUS")
            meshes[path] = obj
        estimated += len(expected["time_s"]) * sum(len(obj.data.vertices) for obj in meshes.values()) * 3 * 26
        if estimated > settings["max_report_bytes"]:
            raise ValueError("TARGET_CAPTURE_BUDGET_EXCEEDED")
    skin_binding = {}
    for path, obj in meshes.items():
        modifiers = []
        for modifier in obj.modifiers:
            if modifier.type == 'ARMATURE':
                if modifier.object is None:
                    raise ValueError('EXPORT_SKIN_ARMATURE_UNBOUND')
                modifiers.append({'type': modifier.type, 'armature': modifier.object.name,
                                  'bones': [bone.name for bone in modifier.object.data.bones],
                                  'use_vertex_groups': modifier.use_vertex_groups,
                                  'use_bone_envelopes': modifier.use_bone_envelopes})
        skin_binding[path] = {'modifiers': modifiers, 'groups': [group.name for group in obj.vertex_groups],
                              'weights': [[[group.group, group.weight] for group in vertex.groups]
                                          for vertex in obj.data.vertices]}
    capture = {'space': 'global', 'units': 'metres', 'rotation_semantics': 'global_rest_delta',
               'basis_digest': _canonical(settings['blender_to_canonical_basis']),
               "time_s": expected["time_s"], "position_m": {path: [] for path in paths},
               "rotation_delta_wxyz": {path: [] for path in paths}, "parent_paths": parent_paths,
               "rest_rotation_wxyz": {path: list(value) for path, value in rest_rotations.items()},
               "rest_position_m": rest_positions,
               'object_rest_provenance': object_rest_provenance,
               "mesh_skin_digest": _canonical(skin_binding) if meshes else None,
               "rest_lengths_m": rest_lengths, "mesh": {path: {"positions_m": [], "triangles": None} for path in meshes}}
    file_start = profile["first_frame"] * profile["fps_den"] / profile["fps_num"] if profile["time_origin"] == "preserve" else 0
    for seconds in expected["time_s"]:
        frame = (file_start + seconds - expected["time_s"][0]) * scene.render.fps + settings["anim_offset"]
        integer = math.floor(frame)
        scene.frame_set(integer, subframe=frame - integer)
        graph = bpy.context.evaluated_depsgraph_get()
        for path, (obj, bone) in resolved.items():
            evaluated = obj.evaluated_get(graph)
            matrix = evaluated.matrix_world @ evaluated.pose.bones[bone.name].matrix if bone else evaluated.matrix_world
            scale = matrix.to_scale()
            if any(not math.isfinite(value) or value <= 0 for value in scale) or max(scale) - min(scale) > 1e-6:
                raise ValueError("EXPORT_NONRIGID_TRANSFORM")
            position = basis @ matrix.translation
            rotation = (basis @ matrix.to_3x3().normalized()
                        @ object_local_inverse.get(path, inverse)).to_quaternion()
            delta = rotation @ rest_rotations[path].inverted()
            capture["position_m"][path].append(list(position))
            capture["rotation_delta_wxyz"][path].append(list(delta))
        for path, obj in meshes.items():
            evaluated = obj.evaluated_get(graph)
            mesh = evaluated.to_mesh()
            try:
                mesh.calc_loop_triangles()
                triangles = [list(triangle.vertices) for triangle in mesh.loop_triangles]
                previous = capture["mesh"][path]["triangles"]
                if previous is not None and previous != triangles:
                    raise ValueError("EXPORT_MESH_TOPOLOGY_CHANGED")
                capture["mesh"][path]["triangles"] = triangles
                capture["mesh"][path]["positions_m"].append([list(basis @ (evaluated.matrix_world @ vertex.co))
                                                            for vertex in mesh.vertices])
            finally:
                evaluated.to_mesh_clear()
    return {"schema_version": 1, "nonce": manifest["nonce"], "artifact_sha256": manifest["artifact"]["sha256"],
            "adapter_fingerprint": profile["target_adapter_fingerprint"], "blender_version": list(bpy.app.version[:3]),
            "settings_digest": profile["target_import_settings_digest"], "actions": actions, "capture": capture}


if __name__ == "__main__":
    manifest_path = Path(sys.argv[sys.argv.index("--") + 1])
    if manifest_path.stat().st_size > 128 * 1024**2:
        raise ValueError("TARGET_MANIFEST_BUDGET_EXCEEDED")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    installation = manifest.get('mode') == 'installation'
    if installation:
        output = Path(manifest['report_path'])
        if (not output.is_absolute() or output.parent != manifest_path.parent or output.exists()
                or output.is_symlink()):
            raise ValueError('TARGET_INSTALLATION_OUTPUT_INVALID')
    result = describe_installation(manifest) if installation else run(manifest)
    encoded = json.dumps(result, separators=(",", ":"), allow_nan=False).encode()
    if len(encoded) > (32768 if installation else manifest["profile"]["target_import_settings"]["max_report_bytes"]):
        raise ValueError("TARGET_REPORT_BUDGET_EXCEEDED")
    with Path(manifest["report_path"]).open("xb") as stream:
        stream.write(encoded)
