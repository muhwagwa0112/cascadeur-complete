"""Minimal binary FBX reader: report takes, time span, frame rate, curve and key counts.

    python fbx_check.py <file.fbx>

Use after an export to confirm the file carries the whole clip: one take, a key
on every frame of every curve (keys_per_curve == frame count), the expected
joints (limb_nodes) and the skinned mesh. Needs numpy only.
"""

import struct
import sys
import zlib
from pathlib import Path

import numpy as np

KTIME = 46186158000


def read(path):
    data = Path(path).read_bytes()
    version = struct.unpack("<I", data[23:27])[0]
    wide = version >= 7500
    head = struct.Struct("<QQQB" if wide else "<IIIB")

    def node(offset):
        end, count, _, name_len = head.unpack_from(data, offset)
        if end == 0:
            return None, offset + head.size
        pos = offset + head.size
        name = data[pos : pos + name_len].decode("ascii", "replace")
        pos += name_len
        props = []
        for _ in range(count):
            kind = chr(data[pos])
            pos += 1
            if kind in "YCIFDL":
                fmt = {"Y": "<h", "C": "<B", "I": "<i", "F": "<f", "D": "<d", "L": "<q"}[kind]
                props.append(struct.unpack_from(fmt, data, pos)[0])
                pos += struct.calcsize(fmt)
            elif kind in "fdlib":
                length, encoding, size = struct.unpack_from("<III", data, pos)
                pos += 12
                raw = data[pos : pos + size]
                pos += size
                if encoding == 1:
                    raw = zlib.decompress(raw)
                dtype = {"f": "<f4", "d": "<f8", "l": "<i8", "i": "<i4", "b": "u1"}[kind]
                props.append(np.frombuffer(raw, dtype=dtype, count=length))
            elif kind in "SR":
                (length,) = struct.unpack_from("<I", data, pos)
                pos += 4
                value = data[pos : pos + length]
                props.append(value.decode("utf-8", "replace") if kind == "S" else value)
                pos += length
            else:
                raise ValueError(f"unknown property type {kind!r} at {pos}")
        children = []
        while pos < end:
            child, pos = node(pos)
            if child is None:
                break
            children.append(child)
        return (name, props, children), end

    nodes = []
    pos = 27
    while pos < len(data) - 200:
        item, pos = node(pos)
        if item is None:
            break
        nodes.append(item)
    return version, nodes


def find(nodes, name):
    for item in nodes:
        if item[0] == name:
            yield item
        yield from find(item[2], name)


def main(path):
    version, nodes = read(path)
    out = {"version": version}
    settings = next(find(nodes, "GlobalSettings"), None)
    if settings:
        for prop in find(settings[2], "P"):
            if prop[1] and prop[1][0] in (
                "TimeMode",
                "CustomFrameRate",
                "TimeSpanStart",
                "TimeSpanStop",
                "UpAxis",
                "UnitScaleFactor",
            ):
                out[prop[1][0]] = prop[1][-1]
    stacks = list(find(nodes, "AnimationStack"))
    out["takes"] = [item[1][1].split("\x00")[0] for item in stacks if len(item[1]) > 1]
    for stack in stacks:
        for prop in find(stack[2], "P"):
            if prop[1] and prop[1][0] in ("LocalStart", "LocalStop"):
                out[prop[1][0] + "_s"] = round(prop[1][-1] / KTIME, 4)
    curves = list(find(nodes, "AnimationCurve"))
    counts, first, last = [], [], []
    for curve in curves:
        for key in find(curve[2], "KeyTime"):
            times = key[1][0]
            counts.append(len(times))
            first.append(times.min() / KTIME)
            last.append(times.max() / KTIME)
    out["curves"] = len(curves)
    if counts:
        out["keys_per_curve"] = {"min": int(min(counts)), "median": int(np.median(counts)), "max": int(max(counts))}
        out["key_time_s"] = [round(float(min(first)), 4), round(float(max(last)), 4)]
    out["models"] = sum(1 for _ in find(nodes, "Model"))
    out["limb_nodes"] = sum(1 for item in find(nodes, "Model") if len(item[1]) > 2 and item[1][2] == "LimbNode")
    out["meshes"] = sum(1 for item in find(nodes, "Model") if len(item[1]) > 2 and item[1][2] == "Mesh")
    out["skin_clusters"] = sum(1 for item in find(nodes, "Deformer") if len(item[1]) > 2 and item[1][2] == "Cluster")
    return out


if __name__ == "__main__":
    import json

    print(json.dumps(main(sys.argv[1]), indent=1, default=str))
