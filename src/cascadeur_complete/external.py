"""Target-side verification for external DCC workflows.

An external route only counts when the target application accepted the data.
For Blender this means a background Blender process imported the exported FBX
and reported armatures, meshes and animation actions.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

BLENDER_DEPENDENCY = "Blender integration"
_MARKER = "CASCADEUR_COMPLETE_BLENDER_REPORT="
_SCRIPT = r"""
import bpy, json, sys
path = sys.argv[sys.argv.index("--") + 1]
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.fbx(filepath=path)
armatures = [o for o in bpy.data.objects if o.type == "ARMATURE"]
report = {
    "objects": len(bpy.data.objects),
    "armatures": len(armatures),
    "bones": sum(len(o.data.bones) for o in armatures),
    "meshes": sum(1 for o in bpy.data.objects if o.type == "MESH"),
    "actions": [
        {"name": a.name, "frame_range": [float(a.frame_range[0]), float(a.frame_range[1])]}
        for a in bpy.data.actions
    ],
    "blender": bpy.app.version_string,
}
print("CASCADEUR_COMPLETE_BLENDER_REPORT=" + json.dumps(report))
"""


def find_blender() -> Path | None:
    """Return the newest installed Blender executable, if any."""
    configured = os.environ.get("CASCADEUR_MCP_BLENDER")
    if configured and Path(configured).is_file():
        return Path(configured)
    root = Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Blender Foundation"
    candidates = []
    for folder in root.glob("Blender *"):
        executable = folder / "blender.exe"
        match = re.search(r"(\d+)\.(\d+)", folder.name)
        if executable.is_file() and match:
            candidates.append(((int(match.group(1)), int(match.group(2))), executable))
    return max(candidates)[1] if candidates else None


def available_dependencies() -> set[str]:
    return {BLENDER_DEPENDENCY} if find_blender() else set()


def verify_blender_fbx(path: str, timeout: float = 240.0) -> dict:
    """Import an FBX into a background Blender and return what Blender observed."""
    blender = find_blender()
    if blender is None:
        raise RuntimeError("Blender is not installed")
    completed = subprocess.run(
        [str(blender), "--background", "--factory-startup", "--python-expr", _SCRIPT, "--", str(path)],
        capture_output=True,
        text=True,
        timeout=timeout,
        creationflags=0x08000000 if os.name == "nt" else 0,
        check=False,
    )
    line = next((item for item in completed.stdout.splitlines() if item.startswith(_MARKER)), None)
    if line is None:
        raise RuntimeError(
            "Blender did not report an import result: " + (completed.stderr or completed.stdout)[-1500:]
        )
    report = json.loads(line[len(_MARKER) :])
    report["executable"] = str(blender)
    return report
