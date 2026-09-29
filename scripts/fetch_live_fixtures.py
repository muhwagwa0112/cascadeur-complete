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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
