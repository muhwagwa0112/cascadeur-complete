"""Immutable capture projections and deterministic bounded transport plans."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

import numpy as np

from .motion_context import MotionInputError


def canonical_data(value):
    if hasattr(value, "model_dump"):
        return canonical_data(value.model_dump(mode="json"))
    if isinstance(value, np.ndarray):
        return canonical_data(value.tolist())
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, dict):
        return {str(key): canonical_data(item) for key,item in value.items()}
    if isinstance(value, (set,frozenset)):
        return sorted(canonical_data(item) for item in value)
    if isinstance(value, (tuple,list)):
        return [canonical_data(item) for item in value]
    return value


def canonical_digest(value):
    data = json.dumps(canonical_data(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def sample_projection(space, frames, ids, positions, quaternions):
    return {
        "space": space, "frames": [int(f) for f in frames],
        "samples": [
            {"frame": int(frame), "id": object_id,
             "position": np.asarray(positions[object_id][row], dtype=float).tolist(),
             "quaternion_wxyz": (np.asarray(quaternions[object_id][row], dtype=float).tolist()
                                  if np.isfinite(quaternions[object_id][row]).all() else None)}
            for row, frame in enumerate(frames) for object_id in sorted(ids)
        ],
    }


@dataclass(frozen=True)
class Window:
    first_row: int
    stop_row: int
    frames: tuple[int, ...]
    estimated_bytes: int


def capture_windows(frames, *, max_mesh_frames=2000, payload_budget_bytes, bytes_per_frame):
    frames = np.asarray(frames)
    if (frames.ndim != 1 or not len(frames) or frames.dtype.kind not in "iu"
            or np.any(np.diff(frames) <= 0) or np.any(frames < 0)):
        raise MotionInputError("INVALID_POLICY", "invalid capture frame grid")
    if any(isinstance(v, bool) or not isinstance(v, int) or v <= 0
           for v in (max_mesh_frames, payload_budget_bytes, bytes_per_frame)):
        raise MotionInputError("INVALID_POLICY", "positive integer capture budgets required")
    count = min(max_mesh_frames, payload_budget_bytes // bytes_per_frame)
    if count < 1:
        raise MotionInputError("RESOURCE_BUDGET_EXCEEDED", f"one frame requires {bytes_per_frame} bytes")
    return [Window(i, min(i + count, len(frames)), tuple(map(int, frames[i:i + count])),
                   min(count, len(frames) - i) * bytes_per_frame) for i in range(0, len(frames), count)]


def partition_writes(writes, *, max_writes=60000, payload_budget_bytes=8_000_000):
    """Do not split the coupled writes of one frame; preserve one global candidate hash."""
    if max_writes <= 0 or payload_budget_bytes <= 0:
        raise MotionInputError("INVALID_POLICY", "positive write budgets required")
    normalized, pairs = [], set()
    for item in writes:
        item = dict(item)
        frame = item.get("frame")
        if isinstance(frame, bool) or not isinstance(frame, (int, np.integer)) or frame < 0:
            raise MotionInputError("INVALID_POLICY", "write frames must be nonnegative integers")
        item["frame"] = int(frame)
        channels = [name for name in ("position", "rotation_euler_xyz_radians") if name in item]
        if len(channels) != 1 or not isinstance(item.get("id"), str):
            raise MotionInputError("INVALID_POLICY", "one channel and exact id required per write")
        channel = channels[0]
        values = np.asarray(item[channel], dtype=float)
        if values.shape != (3,) or not np.isfinite(values).all():
            raise MotionInputError("INVALID_POLICY", "finite write vector required")
        pair = (frame, item["id"], channel)
        if pair in pairs:
            raise MotionInputError("DUPLICATE_WRITE", "duplicate frame/id/channel")
        pairs.add(pair)
        item[channel] = values.tolist()
        normalized.append(item)
    normalized.sort(key=lambda w: (w["frame"], w["id"], "position" if "position" in w else "rotation"))
    candidate_digest = canonical_digest(normalized)
    from itertools import groupby
    chunks, current, current_bytes = [], [], 2
    for _, values in groupby(normalized, key=lambda w: w["frame"]):
        group = list(values)
        group_bytes = 2 + sum(len(json.dumps(w, allow_nan=False, separators=(",", ":")).encode("utf-8")) for w in group) + max(len(group)-1, 0)
        if len(group) > max_writes or group_bytes > payload_budget_bytes:
            raise MotionInputError("RESOURCE_BUDGET_EXCEEDED", "coupled frame write group exceeds payload budget")
        count = current_bytes + group_bytes - 2 + int(bool(current))
        if current and (len(current)+len(group) > max_writes or count > payload_budget_bytes):
            chunks.append(current)
            current = group
            current_bytes = group_bytes
        else:
            current.extend(group)
            current_bytes = count
    if current:
        chunks.append(current)
    return [{"candidate_digest": candidate_digest, "chunk_index": i, "chunk_count": len(chunks),
             "writes": chunk, "chunk_digest": canonical_digest(chunk)} for i, chunk in enumerate(chunks)]


def validate_write_scope(writes, profile, intent):
    first, last = intent.editable_frames
    for write in writes:
        if write["id"] not in profile.writable_ids:
            raise MotionInputError("INVALID_WRITE_SCOPE", "write is outside declared character drivers")
        if not first <= write["frame"] <= last:
            raise MotionInputError("INVALID_WRITE_SCOPE", "write outside editable interval")
        for role, frames in intent.locked_roles_frames.items():
            if profile.role_ids.get(role) == write["id"] and write["frame"] in frames:
                raise MotionInputError("INTENT_LOCK_VIOLATION", f"locked role/frame: {role}")
