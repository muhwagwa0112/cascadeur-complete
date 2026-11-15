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


def run(manifest):
    import bpy
    import importlib
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
    importer_files = {}
    for name in ("io_scene_fbx", "io_scene_fbx.import_fbx", "io_scene_fbx.parse_fbx", "io_scene_fbx.fbx_utils"):
        module = importlib.import_module(name)
        importer_files[name] = _digest_file(module.__file__)
    if _canonical(importer_files) != settings.get("importer_fingerprint"):
        raise ValueError("TARGET_IMPORTER_FINGERPRINT_MISMATCH")
    if _digest_file(bpy.app.binary_path) != settings.get("blender_executable_sha256"):
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
    parent_paths, rest_rotations, rest_lengths = {}, {}, {}
    for path, (obj, bone) in resolved.items():
        # Object-level animated transforms need an independently decoded rest
        # transform. The classic adapter supports static armature containers;
        # silently using the first pose as rest would conceal root drift.
        action, curves = _action_binding(obj, bpy.app.version)
        if action and any(not curve.data_path.startswith('pose.bones[') for curve in curves):
            raise ValueError("TARGET_ANIMATED_CONTAINER_REST_UNSUPPORTED")
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
            matrix = obj.matrix_world
        parent_paths[path] = reverse.get(parent_key)
        rest_rotations[path] = (basis @ matrix.to_3x3().normalized() @ inverse).to_quaternion()
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
    capture = {"time_s": expected["time_s"], "position_m": {path: [] for path in paths},
               "rotation_delta_wxyz": {path: [] for path in paths}, "parent_paths": parent_paths,
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
            rotation = (basis @ matrix.to_3x3().normalized() @ inverse).to_quaternion()
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
    result = run(manifest)
    encoded = json.dumps(result, separators=(",", ":"), allow_nan=False).encode()
    if len(encoded) > manifest["profile"]["target_import_settings"]["max_report_bytes"]:
        raise ValueError("TARGET_REPORT_BUDGET_EXCEEDED")
    with Path(manifest["report_path"]).open("xb") as stream:
        stream.write(encoded)
