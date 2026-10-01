"""Render contact sheets from a `mesh_sample` .npz on the host (numpy + Pillow, ~10 images per second).

    python mesh_preview.py <mesh.npz> body  out.png [--frames 0:986:14] [--view front]
    python mesh_preview.py <mesh.npz> hands out.png [--frames 10:986:42] [--side Left]

`body` draws the whole character facing the camera (or back/left/right);
`hands` draws thumb-side, back and palm close-ups of one hand. The renderer is
a painter's algorithm with back-face culling: good enough to judge poses,
contacts and hand shapes, not a beauty render.
"""

from __future__ import annotations

import argparse

import numpy as np
from PIL import Image, ImageDraw


def unit(v):
    return v / max(np.linalg.norm(v), 1e-9)


class Mesh:
    def __init__(self, path):
        data = np.load(path)
        self.positions = data["positions"]
        self.triangles = data["triangles"]
        self.frames = data["frames"]
        self.names = np.array([str(j) for j in data["joints"]])[data["dominant"]]
        first = self.positions[0].astype(float)
        t = self.triangles
        volume = np.einsum("ij,ij->i", first[t[:, 0]], np.cross(first[t[:, 1]], first[t[:, 2]])).sum()
        self.sign = 1.0 if volume > 0 else -1.0
        self.index = {int(f): i for i, f in enumerate(self.frames)}

    def verts(self, frame):
        return self.positions[self.index[int(frame)]].astype(float)

    def group(self, prefix):
        return np.char.startswith(self.names, prefix)

    def facing(self, frame):
        """(toward the character's left, up, front) from the shoulders and a foot."""
        v = self.verts(frame)
        lateral = unit(v[self.group("LeftArm")].mean(0) - v[self.group("RightArm")].mean(0))
        up = np.array([0.0, 1.0, 0.0])
        front = unit(np.cross(lateral, up))
        toes = v[self.group("LeftToeBase")].mean(0) - v[self.group("LeftFoot")].mean(0)
        if front @ unit(np.array([toes[0], 0.0, toes[2]])) < 0:
            front = -front
        return lateral, up, front


def render(mesh, frame, position, target, size=(420, 420), fov=32.0, up=(0.0, 1.0, 0.0), label=None, only=None):
    v = mesh.verts(frame)
    t = mesh.triangles
    if only is not None:
        keep = np.zeros(len(mesh.names), bool)
        for prefix in only:
            keep |= mesh.group(prefix)
        t = t[keep[t].all(1)]
    position = np.asarray(position, float)
    forward = unit(np.asarray(target, float) - position)
    right = unit(np.cross(forward, np.asarray(up, float)))
    upward = np.cross(right, forward)
    p = v - position
    x, y, z = p @ right, p @ upward, p @ forward
    scale = (size[1] / 2) / np.tan(np.radians(fov) / 2)
    depth_safe = np.maximum(z, 1e-3)
    points = np.stack([size[0] / 2 + x / depth_safe * scale, size[1] / 2 - y / depth_safe * scale], 1)
    a, b, c = v[t[:, 0]], v[t[:, 1]], v[t[:, 2]]
    normal = mesh.sign * np.cross(b - a, c - a)
    normal /= np.maximum(np.linalg.norm(normal, axis=1, keepdims=True), 1e-9)
    centre = (a + b + c) / 3
    depth = (centre - position) @ forward
    visible = (np.einsum("ij,ij->i", normal, centre - position) < 0) & (z[t].min(1) > 1.0)
    shade = np.clip(normal @ unit(-forward * 0.8 + upward * 0.5 + right * 0.3), 0, 1) * 0.75 + 0.2
    order = np.where(visible)[0]
    order = order[np.argsort(-depth[order])]
    image = Image.new("RGB", size, (58, 60, 64))
    draw = ImageDraw.Draw(image)
    for i in order:
        grey = int(shade[i] * 255)
        draw.polygon([tuple(points[k]) for k in t[i]], fill=(grey, grey, grey))
    if label:
        draw.text((6, 4), str(label), fill=(120, 200, 255))
    return image


def body_view(mesh, frame, direction="front", distance=330.0, size=(250, 360)):
    lateral, up, front = mesh.facing(frame)
    v = mesh.verts(frame)
    target = np.array([v[:, 0].mean(), (v[:, 1].min() + v[:, 1].max()) / 2, v[:, 2].mean()])
    d = {"front": front, "back": -front, "left": lateral, "right": -lateral}[direction]
    return render(mesh, frame, target + d * distance + up * 10, target, size=size, fov=30, label=f"{frame}")


def hand_view(mesh, frame, side, view="thumb", distance=42.0, size=(260, 260)):
    v = mesh.verts(frame)
    wrist = v[mesh.group(side + "WristTwist") | mesh.group(side + "ForeArm")].mean(0)
    centre = v[mesh.group(side + "Hand")].mean(0)
    along = unit(centre - wrist)
    across = unit(v[mesh.group(side + "HandIndex")].mean(0) - v[mesh.group(side + "HandPinky")].mean(0))
    normal = unit(np.cross(across, along)) * (-1.0 if side == "Left" else 1.0)
    d = {"back": -normal, "palm": normal, "thumb": across}[view]
    only = [side + "Hand", side + "WristTwist", side + "ForeArm"]
    centre = centre - along * 4
    return render(
        mesh,
        frame,
        centre + d * distance,
        centre,
        size=size,
        fov=30,
        up=along,
        label=f"{side[0]} {frame} {view}",
        only=only,
    )


def sheet(images, columns, path):
    w, h = images[0].size
    rows = (len(images) + columns - 1) // columns
    out = Image.new("RGB", (w * columns, h * rows), "white")
    for i, image in enumerate(images):
        out.paste(image, ((i % columns) * w, (i // columns) * h))
    out.save(path)
    return path


def _frames(spec, mesh):
    parts = [int(item) for item in spec.split(":")]
    wanted = range(*parts) if len(parts) > 1 else parts
    return [frame for frame in wanted if frame in mesh.index]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("mesh")
    parser.add_argument("kind", choices=("body", "hands"))
    parser.add_argument("output")
    parser.add_argument("--frames", default="0:100000:30", help="start:stop:step or one frame")
    parser.add_argument("--view", default="front", choices=("front", "back", "left", "right"))
    parser.add_argument("--side", default="Right", choices=("Left", "Right"))
    parser.add_argument("--columns", type=int, default=12)
    args = parser.parse_args()
    mesh = Mesh(args.mesh)
    frames = _frames(args.frames, mesh)
    if args.kind == "body":
        images = [body_view(mesh, frame, args.view) for frame in frames]
        columns = args.columns
    else:
        images = [hand_view(mesh, frame, args.side, view) for view in ("thumb", "back", "palm") for frame in frames]
        columns = len(frames)
    print(sheet(images, columns, args.output), len(images), "images")


if __name__ == "__main__":
    main()
