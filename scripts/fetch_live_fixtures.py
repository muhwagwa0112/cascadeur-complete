"""Download third-party live-validation fixtures that cannot ship in this repository.

VRM1_Constraint_Twist_Sample.vrm (c) pixiv Inc., VRM Public License 1.0, from
https://github.com/pixiv/three-vrm. It is only used to exercise VRM import.
"""

from __future__ import annotations

import hashlib
import subprocess
import urllib.request

from cascadeur_complete.external import find_blender
from cascadeur_complete.paths import RuntimePaths

# Renders a 12-frame 160x120 H.264 clip with the local Blender (video import fixture).
VIDEO_SCRIPT = r"""
import bpy, sys
out = sys.argv[sys.argv.index("--") + 1]
scene = bpy.context.scene
scene.render.engine = "BLENDER_WORKBENCH"
scene.render.resolution_x, scene.render.resolution_y = 160, 120
scene.frame_start, scene.frame_end = 1, 12
if hasattr(scene.render.image_settings, "media_type"):
    scene.render.image_settings.media_type = "VIDEO"  # Blender 5.x
scene.render.image_settings.file_format = "FFMPEG"
scene.render.ffmpeg.format = "MPEG4"
scene.render.ffmpeg.codec = "H264"
scene.render.filepath = out
cube = bpy.data.objects.get("Cube")
if cube:
    cube.rotation_euler = (0, 0, 0)
    cube.keyframe_insert("rotation_euler", frame=1)
    cube.rotation_euler = (0, 0, 3.14)
    cube.keyframe_insert("rotation_euler", frame=12)
bpy.ops.render.render(animation=True)
"""

# A cube with one "Stretch" shape key exported as FBX (blend shape fixture).
BLEND_SHAPE_SCRIPT = r"""
import bpy, sys
out = sys.argv[sys.argv.index("--") + 1]
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.mesh.primitive_cube_add(size=20)
cube = bpy.context.active_object
cube.name = "BlendCube"
cube.shape_key_add(name="Basis")
key = cube.shape_key_add(name="Stretch")
for point in key.data:
    point.co.z *= 2.0
bpy.ops.export_scene.fbx(filepath=out, use_selection=False, bake_anim=False)
"""

# A plain cube exported as USD (import fixture independent of USD export).
USD_SCRIPT = r"""
import bpy, sys
out = sys.argv[sys.argv.index("--") + 1]
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.mesh.primitive_cube_add(size=2)
bpy.context.active_object.name = "UsdCube"
bpy.ops.wm.usd_export(filepath=out)
"""

# The same cube as glTF binary and glTF JSON (import fixtures independent of export).
GLTF_SCRIPT = r"""
import bpy, sys
out, fmt = sys.argv[sys.argv.index("--") + 1 :]
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.mesh.primitive_cube_add(size=2)
bpy.context.active_object.name = "GltfCube"
bpy.ops.export_scene.gltf(filepath=out, export_format=fmt)
"""

FIXTURES = {
    "VRM1_Constraint_Twist_Sample.vrm": (
        "https://raw.githubusercontent.com/pixiv/three-vrm/dev/packages/three-vrm/examples/models/"
        "VRM1_Constraint_Twist_Sample.vrm"
    ),
}


def fixture_dir():
    path = RuntimePaths.discover().root / "live-fixtures"
    path.mkdir(parents=True, exist_ok=True)
    return path


def main() -> int:
    root = fixture_dir()
    for name, url in FIXTURES.items():
        target = root / name
        if not target.is_file():
            urllib.request.urlretrieve(url, target)
        print(name, target.stat().st_size, hashlib.sha256(target.read_bytes()).hexdigest())
    video = root / "reference.mp4"
    blender = find_blender()
    if not video.is_file() and blender is not None:
        subprocess.run(
            [str(blender), "--background", "--factory-startup", "--python-expr", VIDEO_SCRIPT, "--", str(video)],
            check=True,
            capture_output=True,
            timeout=300,
        )
    if video.is_file():
        print(video.name, video.stat().st_size)
    blend_shapes = root / "blendshape_cube.fbx"
    if not blend_shapes.is_file() and blender is not None:
        subprocess.run(
            [str(blender), "--background", "--factory-startup", "--python-expr", BLEND_SHAPE_SCRIPT, "--"]
            + [str(blend_shapes)],
            check=True,
            capture_output=True,
            timeout=300,
        )
    if blend_shapes.is_file():
        print(blend_shapes.name, blend_shapes.stat().st_size)
    usd = root / "cube.usd"
    if not usd.is_file() and blender is not None:
        subprocess.run(
            [str(blender), "--background", "--factory-startup", "--python-expr", USD_SCRIPT, "--", str(usd)],
            check=True,
            capture_output=True,
            timeout=300,
        )
    if usd.is_file():
        print(usd.name, usd.stat().st_size)
    for name, fmt in (("cube.glb", "GLB"), ("cube.gltf", "GLTF_SEPARATE")):
        target = root / name
        if not target.is_file() and blender is not None:
            subprocess.run(
                [str(blender), "--background", "--factory-startup", "--python-expr", GLTF_SCRIPT, "--"]
                + [str(target), fmt],
                check=True,
                capture_output=True,
                timeout=300,
            )
        if target.is_file():
            print(target.name, target.stat().st_size)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
