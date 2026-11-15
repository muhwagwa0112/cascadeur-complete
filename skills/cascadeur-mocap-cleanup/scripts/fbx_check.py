"""Report binary FBX structure without claiming motion or export validation.

    python fbx_check.py <file.fbx>

The host's bounded parser is shared with strict export validation. This CLI is a
structural diagnostic: key counts alone do not prove the requested take,
character, timing, units, or roundtrip quality. Constant channels may be sparse.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

try:
    from cascadeur_complete.fbx_validation import (
        LEGACY_KTIME,
        ParseLimits,
        read_fbx_structure,
        timebase,
    )
except ModuleNotFoundError:
    # Source-checkout invocation; installed hosts import their bundled module.
    sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))
    from cascadeur_complete.fbx_validation import (
        LEGACY_KTIME,
        ParseLimits,
        read_fbx_structure,
        timebase,
    )

KTIME = LEGACY_KTIME  # Backwards-compatible constant, not a universal FBX clock.


def _legacy(node):
    return node.name, list(node.properties), [_legacy(child) for child in node.children]


def read(path):
    document = read_fbx_structure(path, ParseLimits(require_footer=False))
    return document.version, [_legacy(node) for node in document.nodes]


def find(nodes, name):
    for item in nodes:
        if item[0] == name:
            yield item
        yield from find(item[2], name)


def main(path):
    document = read_fbx_structure(path, ParseLimits(require_footer=False))
    nodes = [_legacy(node) for node in document.nodes]
    ticks = timebase(document)
    out = {"version": document.version, "ticks_per_second": ticks,
           "verification_grade": "structure_report_only", "footer_verified": document.footer_verified}
    settings = next(find(nodes, "GlobalSettings"), None)
    if settings:
        for prop in find(settings[2], "P"):
            if prop[1] and prop[1][0] in (
                "TimeMode", "CustomFrameRate", "TimeSpanStart", "TimeSpanStop", "UpAxis",
                "UpAxisSign", "FrontAxis", "FrontAxisSign", "CoordAxis", "CoordAxisSign", "UnitScaleFactor",
            ):
                out[prop[1][0]] = prop[1][-1]
    stacks = list(find(nodes, "AnimationStack"))
    out["takes"] = [item[1][1].split("\x00")[0].removeprefix("AnimationStack::")
                    for item in stacks if len(item[1]) > 1]
    for stack in stacks:
        for prop in find(stack[2], "P"):
            if prop[1] and prop[1][0] in ("LocalStart", "LocalStop"):
                out[prop[1][0] + "_s"] = round(prop[1][-1] / ticks, 4)
    curves = list(find(nodes, "AnimationCurve"))
    counts, first, last, empty = [], [], [], 0
    for curve in curves:
        for key in find(curve[2], "KeyTime"):
            times = key[1][0]
            counts.append(len(times))
            if len(times):
                first.append(times.min() / ticks)
                last.append(times.max() / ticks)
            else:
                empty += 1
    out["curves"] = len(curves)
    out["empty_curves"] = empty
    if counts:
        out["keys_per_curve"] = {"min": int(min(counts)), "median": int(np.median(counts)), "max": int(max(counts))}
    if first:
        out["key_time_s"] = [round(float(min(first)), 4), round(float(max(last)), 4)]
    out["models"] = sum(1 for _ in find(nodes, "Model"))
    out["limb_nodes"] = sum(1 for item in find(nodes, "Model") if len(item[1]) > 2 and item[1][2] == "LimbNode")
    out["meshes"] = sum(1 for item in find(nodes, "Model") if len(item[1]) > 2 and item[1][2] == "Mesh")
    out["skin_clusters"] = sum(1 for item in find(nodes, "Deformer") if len(item[1]) > 2 and item[1][2] == "Cluster")
    return out


if __name__ == "__main__":
    print(json.dumps(main(sys.argv[1]), indent=1, default=str))
