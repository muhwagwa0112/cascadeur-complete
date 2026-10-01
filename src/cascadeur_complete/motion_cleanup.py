"""Whole-clip mocap cleanup math: foot-skate metric, slide survey, global contact solve, finger smoothing.

Everything here is pure numpy/scipy on sampled tracks, so it runs on the host
and is testable without Cascadeur. ``cleanup_workflow`` reads the tracks from
the live scene and turns the results into protected key writes.

Conventions: Cascadeur units (cm), Y up, one sample per frame. A *track* maps
an object name to an ``(N, 3)`` array of global positions.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

SIDES = ("Left", "Right")
FINGERS = ("Thumb", "Index", "Middle", "Ring", "Pinky")


@dataclass(frozen=True)
class FootRig:
    """Object names of the Quick Rigging Tool (Mixamo-style) leg points."""

    heel: str = "{side}Foot_Self0Point"
    ball: str = "{side}ToeBase_MainPoint"
    toe: str = "{side}ToeBase_DirectionPoint"
    hip: str = "{side}UpLeg_MainPoint"
    ankle: str = "{side}Foot_MainPoint"
    # Points whose names contain one of these after the side prefix move with the foot.
    foot_parts: tuple[str, ...] = ("Foot", "ToeBase")
    # Points the rig re-derives after a write (the leg direction helper).
    rig_solved: tuple[str, ...] = ("Leg_AdditionalPoint",)

    def contacts(self, side: str) -> list[str]:
        return [self.heel.format(side=side), self.ball.format(side=side), self.toe.format(side=side)]

    def required(self) -> list[str]:
        names = []
        for side in SIDES:
            names += self.contacts(side) + [self.hip.format(side=side), self.ankle.format(side=side)]
        return names

    def foot_side(self, name: str) -> str | None:
        for side in SIDES:
            if name.startswith(side) and any(part in name[len(side) :] for part in self.foot_parts):
                return side
        return None

    def is_rig_solved(self, name: str) -> bool:
        return any(name.endswith(suffix) for suffix in self.rig_solved)


@dataclass(frozen=True)
class ContactParams:
    height_scale: float = 4.0  # cm; contact weight halves ~4 cm above the floor
    speed_scale: float = 8.0  # cm/frame; fast feet are stepping, not planted
    body_smoothness: float = 2.0  # acceleration penalty on the whole-body offset
    foot_smoothness: float = 0.5  # acceleration penalty on per-foot offsets
    foot_anchor: float = 0.02  # keeps per-foot offsets small
    body_anchor: float = 0.02  # keeps the whole-body offset small
    max_foot_offset: float = 10.0  # cm, hard box on each foot's own offset
    leg_margin: float = 0.3  # cm under the longest original hip-ankle distance
    iterations: int = 6


# ---------------------------------------------------------------------------
# Metric and survey


def floors(track: dict[str, np.ndarray], rig: FootRig) -> dict[str, np.ndarray]:
    """Per contact point floor height (3rd percentile), robust to jumps."""
    return {side: np.array([np.percentile(track[name][:, 1], 3) for name in rig.contacts(side)]) for side in SIDES}


def _contact_stack(track, rig, side):
    return np.stack([track[name] for name in rig.contacts(side)])  # 3 x N x 3


def skate_per_frame(
    track: dict[str, np.ndarray], rig: FootRig, floor: dict[str, np.ndarray] | None = None, height_scale: float = 4.0
) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    """Foot skating per frame (cm/frame), summed over both feet.

    Horizontal speed of each contact point weighted by clip(2 - 2^(h/H), 0, 1)
    (the metric used in motion generation papers); each foot contributes its
    worst contact point.
    """
    floor = floor or floors(track, rig)
    total = None
    for side in SIDES:
        points = _contact_stack(track, rig, side)
        height = np.maximum(points[:, :, 1] - floor[side][:, None], 0)
        speed = np.linalg.norm(np.diff(points[:, :, [0, 2]], axis=1), axis=2)
        speed = np.concatenate([speed, np.zeros((3, 1))], axis=1)
        weight = np.clip(2 - 2 ** (height / height_scale), 0, 1)
        worst = (weight * speed).max(0)
        total = worst if total is None else total + worst
    return total, floor


def _runs(mask: np.ndarray, min_length: int, gap: int = 2) -> list[tuple[int, int]]:
    index = np.where(mask)[0]
    if not len(index):
        return []
    out = []
    start = previous = index[0]
    for item in index[1:]:
        if item - previous > gap + 1:
            out.append((start, previous))
            start = item
        previous = item
    out.append((start, previous))
    return [(int(a), int(b)) for a, b in out if b - a + 1 >= min_length]


def skate_summary(
    skate: np.ndarray,
    segments: list[tuple[int, int]] | None = None,
    hot_threshold: float = 1.0,
    window: int = 10,
) -> dict[str, Any]:
    """Mean/p95, the worst frames and the spans where a sliding window stays hot."""
    frames = len(skate)
    smoothed = np.convolve(skate, np.ones(window) / window, mode="same") if frames >= window else skate
    hot = _runs(smoothed > hot_threshold, 3, gap=1)
    order = np.argsort(-skate)[:10]
    summary: dict[str, Any] = {
        "mean_cm_per_frame": round(float(skate.mean()), 3),
        "p95_cm_per_frame": round(float(np.percentile(skate, 95)), 3),
        "worst_frames": [{"frame": int(f), "skate": round(float(skate[f]), 2)} for f in order],
        "hot_spans": [{"first": a, "last": b, "mean": round(float(skate[a : b + 1].mean()), 2)} for a, b in hot],
    }
    if segments:
        summary["segments"] = [
            {"first": int(a), "last": int(b), "mean": round(float(skate[a : b + 1].mean()), 3)}
            for a, b in segments
            if 0 <= a <= b < frames
        ]
    return summary


def _foot_motion(track, rig, side):
    """Lowest contact point height above its floor and that point's horizontal velocity."""
    names = rig.contacts(side)
    points = {name: track[name] for name in names}
    rel = np.stack([points[name][:, 1] - np.percentile(points[name][:, 1], 3) for name in names], 1)
    low = rel.min(1)
    lowest = rel.argmin(1)
    frames = len(low)
    velocity = np.zeros((frames, 2))
    for f in range(frames - 1):
        point = points[names[lowest[f]]]
        velocity[f] = point[f + 1][[0, 2]] - point[f][[0, 2]]
    return low, velocity, np.linalg.norm(velocity, axis=1)


def survey(track: dict[str, np.ndarray], rig: FootRig) -> dict[str, Any]:
    """Find the two slide patterns a viewer notices.

    - double slides: both feet on the floor moving together (the body glides
      with no step, e.g. root motion while standing);
    - drags: one foot sliding along the floor while the other is planted.
    """
    info = {side: _foot_motion(track, rig, side) for side in SIDES}
    (low_l, vel_l, speed_l), (low_r, vel_r, speed_r) = info["Left"], info["Right"]
    cosine = (vel_l * vel_r).sum(1) / np.maximum(speed_l * speed_r, 1e-6)
    double = (low_l < 5) & (low_r < 5) & (speed_l > 0.5) & (speed_r > 0.5) & (cosine > 0.3)
    doubles = []
    for a, b in _runs(double, 4):
        together = (vel_l[a : b + 1] + vel_r[a : b + 1]) / 2
        doubles.append({"first": a, "last": b, "distance_cm": round(float(np.linalg.norm(together.sum(0))), 1)})
    drags = []
    for side, other in (("Left", "Right"), ("Right", "Left")):
        low, _, speed = info[side]
        low_o, _, speed_o = info[other]
        mask = (low < 1.5) & (speed > 0.8) & (speed_o < 0.4) & (low_o < 3)
        for a, b in _runs(mask, 4):
            drags.append(
                {
                    "side": side,
                    "first": a,
                    "last": b,
                    "distance_cm": round(float(speed[a : b + 1].sum()), 1),
                    "max_height_cm": round(float(low[a : b + 1].max()), 1),
                }
            )
    return {"double_slides": doubles, "drags": drags, "_info": info}


# ---------------------------------------------------------------------------
# Global contact solve


def contact_weights(track, rig, params: ContactParams):
    """Soft 'planted' weight per contact point and frame transition, plus velocities."""
    floor = floors(track, rig)
    out = {}
    for side in SIDES:
        points = _contact_stack(track, rig, side)
        height = np.maximum(points[:, :, 1] - floor[side][:, None], 0)
        velocity = np.diff(points[:, :, [0, 2]], axis=1)
        speed = np.linalg.norm(velocity, axis=2)
        weight = np.clip(2 - 2 ** (height[:, :-1] / params.height_scale), 0, 1) * np.exp(
            -((speed / params.speed_scale) ** 2)
        )
        out[side] = (velocity, weight)
    return out


def solve_contacts(track: dict[str, np.ndarray], rig: FootRig, params: ContactParams | None = None) -> dict[str, Any]:
    """Solve one QP over the whole clip for a whole-body offset and per-foot offsets (XZ).

    Minimises the weighted horizontal velocity of every contact point plus
    smoothness and anchor terms, subject to each leg never reaching further
    than its longest original hip-ankle distance (linearised, tightened
    iteratively) and a box on the per-foot offsets.
    """
    import osqp
    import scipy.sparse as sp

    params = params or ContactParams()
    frames = len(track[rig.heel.format(side="Left")])
    weights = contact_weights(track, rig, params)
    legs = {}
    for side in SIDES:
        hip = track[rig.hip.format(side=side)]
        ankle = track[rig.ankle.format(side=side)]
        legs[side] = (hip, ankle, float(np.linalg.norm(ankle - hip, axis=1).max()))

    def var(block, axis, frame):
        return (block * 2 + axis) * frames + frame

    rows, cols, vals, rhs = [], [], [], []

    def add(entries, target):
        row = len(rhs)
        for col, value in entries:
            rows.append(row)
            cols.append(col)
            vals.append(value)
        rhs.append(target)

    for block, side in enumerate(SIDES, start=1):
        velocity, weight = weights[side]
        for c in range(3):
            for f in range(frames - 1):
                if weight[c, f] < 1e-3:
                    continue
                sw = float(np.sqrt(weight[c, f]))
                for axis in (0, 1):
                    add(
                        [
                            (var(0, axis, f + 1), sw),
                            (var(0, axis, f), -sw),
                            (var(block, axis, f + 1), sw),
                            (var(block, axis, f), -sw),
                        ],
                        -sw * float(velocity[c, f, axis]),
                    )
    for block, lam in ((0, params.body_smoothness), (1, params.foot_smoothness), (2, params.foot_smoothness)):
        for axis in (0, 1):
            for f in range(1, frames - 1):
                add(
                    [(var(block, axis, f - 1), lam), (var(block, axis, f), -2 * lam), (var(block, axis, f + 1), lam)],
                    0.0,
                )
    for block, lam in ((0, params.body_anchor), (1, params.foot_anchor), (2, params.foot_anchor)):
        for axis in (0, 1):
            for f in range(frames):
                add([(var(block, axis, f), lam)], 0.0)
    matrix = sp.csr_matrix((vals, (rows, cols)), shape=(len(rhs), 6 * frames))
    target = np.array(rhs)
    hessian = sp.triu((matrix.T @ matrix) * 2).tocsc()
    linear = -2 * (matrix.T @ target)

    margin = {side: np.full(frames, params.leg_margin) for side in SIDES}
    best = None
    log = []
    for iteration in range(params.iterations):
        g_rows, g_cols, g_vals, lower, upper = [], [], [], [], []
        k = 0
        for block, side in enumerate(SIDES, start=1):
            hip, ankle, cap = legs[side]
            for f in range(frames):
                direction = ankle[f] - hip[f]
                length = float(np.linalg.norm(direction))
                direction = direction / max(length, 1e-6)
                g_rows += [k, k]
                g_cols += [var(block, 0, f), var(block, 1, f)]
                g_vals += [float(direction[0]), float(direction[2])]
                lower.append(-np.inf)
                # Keep the bound reachable inside the foot-offset box: a nearly
                # vertical leg cannot be shortened by moving the foot sideways.
                reachable = -0.9 * params.max_foot_offset * (abs(direction[0]) + abs(direction[2]))
                upper.append(max(cap - length - margin[side][f], reachable))
                k += 1
        for block in (1, 2):
            for axis in (0, 1):
                for f in range(frames):
                    g_rows.append(k)
                    g_cols.append(var(block, axis, f))
                    g_vals.append(1.0)
                    lower.append(-params.max_foot_offset)
                    upper.append(params.max_foot_offset)
                    k += 1
        constraints = sp.csc_matrix((g_vals, (g_rows, g_cols)), shape=(k, 6 * frames))
        solver = osqp.OSQP()
        solver.setup(
            hessian,
            linear,
            constraints,
            np.array(lower),
            np.array(upper),
            verbose=False,
            eps_abs=1e-5,
            eps_rel=1e-5,
            max_iter=40000,
            polishing=True,
        )
        result = solver.solve(raise_error=False)
        status = str(result.info.status)
        if status != "solved":
            log.append({"iteration": iteration, "status": status})
            break
        solution = result.x.reshape(3, 2, frames).transpose(0, 2, 1)
        worst = 0.0
        tightened = 0
        for block, side in enumerate(SIDES, start=1):
            hip, ankle, cap = legs[side]
            moved = ankle.copy()
            moved[:, 0] += solution[block][:, 0]
            moved[:, 2] += solution[block][:, 1]
            over = np.linalg.norm(moved - hip, axis=1) - cap
            worst = max(worst, float(over.max()))
            mask = over > 0.1
            margin[side][mask] += over[mask] + 0.2
            tightened += int(mask.sum())
        log.append({"iteration": iteration, "status": status, "worst_leg_over_cm": round(worst, 2)})
        if best is None or worst < best[0]:
            best = (worst, solution.copy())
        if worst < 0.3:
            break
    if best is None:
        raise RuntimeError(f"contact solve failed: {log}")
    solution = best[1]
    return {
        "body": solution[0],
        "feet": {"Left": solution[1], "Right": solution[2]},
        "leg_over_cm": round(best[0], 2),
        "iterations": log,
    }


def apply_offsets(
    track: dict[str, np.ndarray],
    rig: FootRig,
    body: np.ndarray,
    feet: dict[str, np.ndarray] | None = None,
    lifts: dict[str, np.ndarray] | None = None,
) -> dict[str, np.ndarray]:
    """Move every point by the body offset; foot points also by their foot's offset and lift."""
    out = {}
    for name, positions in track.items():
        moved = positions.copy()
        offset = body.copy()
        side = rig.foot_side(name)
        if side and feet is not None:
            offset = offset + feet[side]
        moved[:, 0] += offset[:, 0]
        moved[:, 2] += offset[:, 1]
        if side and lifts is not None:
            moved[:, 1] += lifts[side]
        out[name] = moved
    return out


def step_pass(track: dict[str, np.ndarray], rig: FootRig) -> dict[str, Any]:
    """Turn what the solve could not absorb into motion a viewer reads as intended.

    Double slides left over are cancelled by a whole-body offset carried
    forward; one-foot drags become short steps (a sine lift of 3-8 cm on that
    foot's points, horizontal path unchanged).
    """
    from scipy.ndimage import gaussian_filter1d

    found = survey(track, rig)
    info = found.pop("_info")
    frames = len(info["Left"][0])
    vel_l, vel_r = info["Left"][1], info["Right"][1]
    step = np.zeros((frames, 2))
    for item in found["double_slides"]:
        for f in range(item["first"], item["last"] + 1):
            step[f] = -(vel_l[f] + vel_r[f]) / 2
    offset = np.cumsum(np.concatenate([np.zeros((1, 2)), step[:-1]]), axis=0)
    offset = gaussian_filter1d(offset, 1.0, axis=0, mode="nearest")
    lifts = {side: np.zeros(frames) for side in SIDES}
    steps = []
    for item in found["drags"]:
        side, a, b = item["side"], item["first"], item["last"]
        height = float(np.clip(0.25 * item["distance_cm"], 3, 8))
        a0, b0 = a - 1, b + 1
        for f in range(max(0, a0), min(frames - 1, b0) + 1):
            lifts[side][f] = max(lifts[side][f], height * np.sin(np.pi * (f - a0) / (b0 - a0)))
        steps.append({**item, "lift_cm": round(height, 1)})
    return {
        "body": offset,
        "lifts": lifts,
        "double_slides_cancelled": found["double_slides"],
        "drags_to_steps": steps,
    }


# ---------------------------------------------------------------------------
# Fingers

FINGER_SPREAD_LIMIT = {"Index": 15.0, "Middle": 8.0, "Ring": 10.0, "Pinky": 18.0}


def finger_parts(name: str) -> tuple[str, str, int] | None:
    """(side, finger, segment) for names like RightHandIndex1_Box."""
    import re

    match = re.match(r"^(Left|Right)Hand(Thumb|Index|Middle|Ring|Pinky)(\d)_Box$", name)
    if not match:
        return None
    return match.group(1), match.group(2), int(match.group(3))


def _smooth(values, median, sigma):
    from scipy.ndimage import gaussian_filter1d, median_filter

    return gaussian_filter1d(median_filter(values, size=median, mode="nearest"), sigma, mode="nearest")


def _soft_limit(values, limit):
    return limit * np.tanh(values / limit)


def _steps_deg(rest, rotation):
    rotvec = (rest.inv() * rotation).as_rotvec()
    return np.degrees(np.linalg.norm(np.diff(rotvec, axis=0), axis=1))


def _range(values):
    return float(np.percentile(values, 99) - np.percentile(values, 1))


def finger_cleanup(quaternions_wxyz: dict[str, np.ndarray], spike_deg: float = 10.0) -> dict[str, Any]:
    """Limit mocap finger spread/twist and remove spikes, keeping curl.

    Each joint is expressed relative to its median (rest) pose as ZYX Euler
    angles: Z = curl, Y = spread, X = twist on the QRT finger boxes.
    Knuckles get a per-finger soft spread limit, middle/tip joints a tight
    one; thumbs are only smoothed. Joints that still jump more than
    ``spike_deg`` per frame get a stronger median+Gaussian pass. Returns
    Cascadeur Euler XYZ radians (the convention transform reads report).
    """
    from scipy.spatial.transform import Rotation

    rotations = {}
    report = []
    for name, quaternion in sorted(quaternions_wxyz.items()):
        parts = finger_parts(name)
        if parts is None:
            continue
        _, finger, segment = parts
        xyzw = np.asarray(quaternion, dtype=float)[:, [1, 2, 3, 0]]
        rotation = Rotation.from_quat(xyzw)
        rest_quat = np.median(xyzw * np.sign(xyzw[:, [3]]), axis=0)
        rest = Rotation.from_quat(rest_quat / np.linalg.norm(rest_quat))
        curl, spread, twist = np.degrees((rest.inv() * rotation).as_euler("ZYX")).T
        if finger == "Thumb":
            new = [_smooth(curl, 3, 1.0), _smooth(spread, 3, 1.0), _smooth(twist, 3, 1.0)]
        elif segment == 1:
            new = [
                _smooth(curl, 3, 1.0),
                _soft_limit(_smooth(spread, 7, 3.0), FINGER_SPREAD_LIMIT[finger]),
                _soft_limit(_smooth(twist, 7, 3.0), 5.0),
            ]
        else:
            new = [
                _smooth(curl, 3, 1.0),
                _soft_limit(_smooth(spread, 7, 3.0), 3.0),
                _soft_limit(_smooth(twist, 7, 3.0), 3.0),
            ]
        cleaned = rest * Rotation.from_euler("ZYX", np.radians(np.stack(new, 1)))
        despiked = False
        if _steps_deg(rest, cleaned).max() > spike_deg:
            new = [_smooth(values, 5, 1.5) for values in new]
            cleaned = rest * Rotation.from_euler("ZYX", np.radians(np.stack(new, 1)))
            despiked = True
        before = _steps_deg(rest, rotation)
        after = _steps_deg(rest, cleaned)
        change = np.degrees((rotation.inv() * cleaned).magnitude())
        rotations[name] = cleaned.as_euler("xyz")
        report.append(
            {
                "joint": name[:-4],
                "spread_range_deg": [round(_range(spread), 1), round(_range(new[1]), 1)],
                "twist_range_deg": [round(_range(twist), 1), round(_range(new[2]), 1)],
                "max_step_deg": [round(float(before.max()), 1), round(float(after.max()), 1)],
                "steps_over_spike": [int((before > spike_deg).sum()), int((after > spike_deg).sum())],
                "change_p95_deg": round(float(np.percentile(change, 95)), 1),
                "change_max_deg": round(float(change.max()), 1),
                "despiked": despiked,
            }
        )
    return {"euler_xyz": rotations, "joints": report}


def finger_stats(quaternions_wxyz: dict[str, np.ndarray], spike_deg: float = 10.0) -> list[dict[str, Any]]:
    """Read-only per joint stats: spread/twist range and frame-to-frame jumps."""
    from scipy.spatial.transform import Rotation

    rows = []
    for name, quaternion in sorted(quaternions_wxyz.items()):
        if finger_parts(name) is None:
            continue
        xyzw = np.asarray(quaternion, dtype=float)[:, [1, 2, 3, 0]]
        rotation = Rotation.from_quat(xyzw)
        rest_quat = np.median(xyzw * np.sign(xyzw[:, [3]]), axis=0)
        rest = Rotation.from_quat(rest_quat / np.linalg.norm(rest_quat))
        _, spread, twist = np.degrees((rest.inv() * rotation).as_euler("ZYX")).T
        steps = _steps_deg(rest, rotation)
        rows.append(
            {
                "joint": name[:-4],
                "spread_range_deg": round(_range(spread), 1),
                "twist_range_deg": round(_range(twist), 1),
                "max_step_deg": round(float(steps.max()), 1),
                "steps_over_spike": int((steps > spike_deg).sum()),
            }
        )
    return rows


# ---------------------------------------------------------------------------
# Finger fan (gaps between neighbouring fingers)

FAN_FINGERS = ("Index", "Middle", "Ring", "Pinky")
FAN_PAIRS = (("Index", "Middle"), ("Middle", "Ring"), ("Ring", "Pinky"))


def _unit(vectors):
    return vectors / np.maximum(np.linalg.norm(vectors, axis=-1, keepdims=True), 1e-9)


def fan_joint_names(side: str) -> list[str]:
    """Skeleton joints that define the palm plane and each finger's proximal bone."""
    return [f"{side}Hand"] + [f"{side}Hand{finger}{index}" for finger in FAN_FINGERS for index in (1, 2)]


def finger_gaps(joints: dict[str, np.ndarray], side: str) -> dict[str, Any]:
    """Signed angles (deg) between neighbouring proximal finger bones in the palm plane.

    The palm normal comes from the knuckle line (index to pinky) and the wrist
    to knuckle direction. Positive means the pair spreads apart. A static
    offset here is what a spread limit around the clip's own median pose
    cannot see (e.g. an index finger held away from the middle finger for
    the whole clip, which reads as a claw).
    """
    knuckle = {finger: joints[f"{side}Hand{finger}1"] for finger in FAN_FINGERS}
    direction = {finger: _unit(joints[f"{side}Hand{finger}2"] - knuckle[finger]) for finger in FAN_FINGERS}
    across = _unit(knuckle["Pinky"] - knuckle["Index"])
    along = _unit((knuckle["Index"] + knuckle["Pinky"]) / 2 - joints[f"{side}Hand"])
    normal = _unit(np.cross(across, along))

    def planar(vectors):
        return _unit(vectors - (vectors * normal).sum(1, keepdims=True) * normal)

    gaps = {}
    for first, second in FAN_PAIRS:
        a, b = planar(direction[first]), planar(direction[second])
        gaps[first + second] = np.degrees(np.arctan2((np.cross(b, a) * normal).sum(1), (a * b).sum(1)))
    return {"gaps": gaps, "normal": normal}


def gap_summary(gaps: dict[str, np.ndarray]) -> dict[str, Any]:
    return {
        pair: {
            "median_deg": round(float(np.median(values)), 1),
            "p5_deg": round(float(np.percentile(values, 5)), 1),
            "p95_deg": round(float(np.percentile(values, 95)), 1),
        }
        for pair, values in gaps.items()
    }


def close_index_gap(
    joints: dict[str, np.ndarray],
    hand_box_wxyz: np.ndarray,
    index_box_wxyz: np.ndarray,
    side: str,
    target_deg: float = 3.0,
    keep: float = 0.2,
    sigma: float = 3.0,
) -> dict[str, Any]:
    """Rotate the index knuckle box about the palm normal so the index-middle gap becomes natural.

    New gap = ``target_deg`` + ``keep`` x (smoothed gap - its median): the
    static splay goes, a little of the slow spread motion stays, frame noise
    goes. The box's children follow through the hierarchy. Returns the new
    local rotation (relative to the hand box) as Cascadeur Euler XYZ radians.
    """
    from scipy.ndimage import gaussian_filter1d
    from scipy.spatial.transform import Rotation

    measured = finger_gaps(joints, side)
    gap = measured["gaps"]["IndexMiddle"]
    wanted = target_deg + keep * (gaussian_filter1d(gap, sigma, mode="nearest") - np.median(gap))
    correction = Rotation.from_rotvec(measured["normal"] * np.radians(wanted - gap)[:, None])
    hand = Rotation.from_quat(np.asarray(hand_box_wxyz, dtype=float)[:, [1, 2, 3, 0]])
    index = Rotation.from_quat(np.asarray(index_box_wxyz, dtype=float)[:, [1, 2, 3, 0]])
    local = hand.inv() * correction * index
    return {
        "euler_xyz": local.as_euler("xyz"),
        "gap_before": gap,
        "gap_after": wanted,
        "rotation_deg": {
            "median": round(float(np.median(np.abs(gap - wanted))), 1),
            "max": round(float(np.abs(gap - wanted).max()), 1),
        },
    }


# ---------------------------------------------------------------------------
# Arm clearance (arms passing through the torso, hips, head or the other arm)


@dataclass(frozen=True)
class ArmParams:
    margin: float = 0.2  # cm of clearance to restore outside the surface
    allow: float = 0.3  # cm of overlap tolerated as soft contact
    band: float = 0.5  # cm; samples closer than this to the surface are constrained too
    smoothness: float = 2000.0  # second-difference penalty on the offsets (per frame units)
    velocity: float = 20.0  # first-difference penalty on the offsets
    hand_radius: float = 2.5  # capsule mode only
    reach: float = 8.0  # cm; a vertex further than this from the surface is not "inside"
    per_frame: int = 40  # mesh mode: new constraints added per frame and iteration
    step: float = 3.0  # cm an offset may change per iteration (per axis)
    slack_penalty: float = 1000.0  # weight on contacts the solve could not satisfy
    iterations: int = 8


def capsule_segment(position, rotation_wxyz, length):
    """World-space axis endpoints of a capsule lying on the rigid body's local Z axis, centred on its origin."""
    from scipy.spatial.transform import Rotation

    axis = Rotation.from_quat(np.asarray(rotation_wxyz, dtype=float)[:, [1, 2, 3, 0]]).apply([0.0, 0.0, 1.0])
    position = np.asarray(position, dtype=float)
    return position - axis * length / 2, position + axis * length / 2


def _closest_on_segment(a, b, x):
    ab = b - a
    t = np.clip(((x - a) * ab).sum(-1) / np.maximum((ab * ab).sum(-1), 1e-9), 0, 1)
    return a + ab * t[..., None]


class CapsuleSurface:
    """Arm clearance against the rig's collision capsules (coarse: misses hips, chest and fingers)."""

    def __init__(self, shoulder, elbow, wrist, hand, radii, body, params: ArmParams):
        self.shoulder, self.elbow, self.wrist, self.hand = shoulder, elbow, wrist, hand
        self.upper_radius, self.fore_radius = radii
        self.body = body
        self.params = params

    def _samples(self, offsets):
        elbow, wrist = self.elbow + offsets[0], self.wrist + offsets[1]
        out = []
        for t in (0.5, 0.65, 0.8, 0.95):
            out.append((self.shoulder + (elbow - self.shoulder) * t, self.upper_radius, t, 0.0))
        for t in np.linspace(0.0, 1.0, 6):
            out.append((elbow + (wrist - elbow) * t, self.fore_radius, 1.0 - t, float(t)))
        out.append((self.hand + offsets[1], self.params.hand_radius, 0.0, 1.0))
        return out

    def depth(self, offsets) -> np.ndarray:
        """Deepest penetration (cm, 0 when clear) per frame."""
        worst = np.zeros(len(self.shoulder))
        for a, b, radius in self.body.values():
            for x, r, _, _ in self._samples(offsets):
                clearance = np.linalg.norm(x - _closest_on_segment(a, b, x), axis=1) - radius - r
                worst = np.maximum(worst, -clearance)
        return worst

    def constraints(self, offsets):
        rows = []
        for a, b, radius in self.body.values():
            for x, r, we, ww in self._samples(offsets):
                gap = x - _closest_on_segment(a, b, x)
                distance = np.linalg.norm(gap, axis=1)
                clearance = distance - radius - r
                normal = gap / np.maximum(distance, 1e-6)[:, None]
                for f in np.where(clearance < max(self.params.band, 4.0))[0]:
                    rows.append((int(f), we, ww, normal[f], self.params.margin - clearance[f]))
        return rows


class MeshSurface:
    """Arm clearance against the character's own skinned mesh.

    The obstacle is every vertex not bound to this arm (or its shoulder), so
    the torso, hips, head, legs and the other arm all count. A test vertex is
    inside when it lies behind the nearest obstacle vertex's outward normal.
    Arm vertices follow the solve by blending the elbow and wrist offsets
    along the bones; the mesh is re-sampled after the write to verify.
    """

    def __init__(self, positions, triangles, dominant, joints, side, shoulder, elbow, wrist, params: ArmParams):
        from scipy.spatial import cKDTree

        self.params = params
        names = np.array([str(item) for item in joints])[np.asarray(dominant)]
        upper = np.char.startswith(names, side + "Arm")
        fore = np.char.startswith(names, side + "ForeArm") | np.char.startswith(names, side + "WristTwist")
        hand = np.char.startswith(names, side + "Hand")
        own = upper | fore | hand | np.char.startswith(names, side + "Shoulder")
        obstacle = np.where(~own)[0]
        faces = triangles[(~own)[triangles].all(1)]
        first = positions[0].astype(float)
        volume = np.einsum("ij,ij->i", first[triangles[:, 0]], np.cross(first[triangles[:, 1]], first[triangles[:, 2]]))
        sign = 1.0 if volume.sum() > 0 else -1.0
        import scipy.sparse as sp

        corner_count = len(faces)
        gather = sp.csr_matrix(
            (np.ones(3 * corner_count), (faces.T.reshape(-1), np.tile(np.arange(corner_count), 3))),
            shape=(len(first), corner_count),
        )
        self.frames = []
        # Vertices constrained once stay constrained: dropping one as soon as it
        # clears the surface lets the next solve relax straight back inside.
        self.active: list[np.ndarray] = []
        for f in range(len(positions)):
            vertices = positions[f].astype(float)
            face_normal = sign * np.cross(
                vertices[faces[:, 1]] - vertices[faces[:, 0]], vertices[faces[:, 2]] - vertices[faces[:, 0]]
            )
            normal = _unit(gather @ face_normal)[obstacle]
            groups = []
            upper_axis = elbow[f] - shoulder[f]
            fore_axis = wrist[f] - elbow[f]
            index = np.where(upper)[0]
            t = ((vertices[index] - shoulder[f]) @ upper_axis) / (upper_axis @ upper_axis)
            keep = t >= 0.5  # the half next to the shoulder always touches the torso
            groups.append((vertices[index[keep]], np.clip(t[keep], 0, 1), np.zeros(int(keep.sum()))))
            index = np.where(fore)[0]
            t = np.clip(((vertices[index] - elbow[f]) @ fore_axis) / (fore_axis @ fore_axis), 0, 1)
            groups.append((vertices[index], 1.0 - t, t))
            index = np.where(hand)[0]
            groups.append((vertices[index], np.zeros(len(index)), np.ones(len(index))))
            self.frames.append(
                {
                    "tree": cKDTree(vertices[obstacle]),
                    "surface": vertices[obstacle],
                    "normal": normal,
                    "points": np.concatenate([g[0] for g in groups]),
                    "we": np.concatenate([g[1] for g in groups]),
                    "ww": np.concatenate([g[2] for g in groups]),
                }
            )
            self.active.append(np.zeros(0, dtype=int))

    def _signed(self, frame, offsets, f):
        moved = frame["points"] + frame["we"][:, None] * offsets[0][f] + frame["ww"][:, None] * offsets[1][f]
        distance, nearest = frame["tree"].query(moved)
        normal = frame["normal"][nearest]
        signed = np.einsum("ij,ij->i", moved - frame["surface"][nearest], normal)
        # Further than ``reach`` from any surface is outside, whatever the nearest normal says.
        signed[distance > self.params.reach] = self.params.reach
        return signed, normal

    def depth(self, offsets) -> np.ndarray:
        out = np.zeros(len(self.frames))
        for f, frame in enumerate(self.frames):
            signed, _ = self._signed(frame, offsets, f)
            if len(signed):
                out[f] = max(0.0, float(-signed.min()))
        return out

    def constraints(self, offsets):
        rows = []
        params = self.params
        for f, frame in enumerate(self.frames):
            signed, normal = self._signed(frame, offsets, f)
            if not len(signed):
                continue
            if signed.min() <= -params.allow:
                near = np.where(signed < params.band)[0]
                order = near[np.argsort(signed[near])]
                deepest = order[: params.per_frame // 2]
                rest = order[params.per_frame // 2 :]
                spread = rest[:: max(1, len(rest) // max(1, params.per_frame // 2))]
                self.active[f] = np.union1d(self.active[f], np.concatenate([deepest, spread])).astype(int)
            for i in self.active[f]:
                rows.append((f, float(frame["we"][i]), float(frame["ww"][i]), normal[i], params.margin - signed[i]))
        return rows


def solve_arm_offsets(
    shoulder: np.ndarray,
    elbow: np.ndarray,
    wrist: np.ndarray,
    surface,
    params: ArmParams | None = None,
    spacing: float = 1.0,
    interpolation=None,
) -> dict[str, Any]:
    """One QP over the key samples for elbow and wrist offsets that lift the arm out of the body.

    Minimises the offsets plus their first and second differences (a
    correction ramps in and out over neighbouring samples) subject to the
    constraints ``surface`` reports (each: outward normal . sample offset >=
    needed distance, re-evaluated every iteration at the moved pose) and both
    bone lengths staying constant to first order. The shoulder stays put.
    ``spacing`` is the number of frames between samples.

    ``shoulder``/``elbow``/``wrist`` are the key samples the offsets are
    solved (and later written) at. ``surface`` may cover more frames than
    that: ``interpolation`` is then the (frames x keys) matrix that spreads
    key offsets onto its frames, so a fast arm whose interpolated path cuts
    through the body between two clear keys is pushed out as well.
    """
    import osqp
    import scipy.sparse as sp

    params = params or ArmParams()
    frames = len(shoulder)
    size = 6 * frames

    def var(block, frame, axis):
        return block * 3 * frames + frame * 3 + axis

    second = sp.diags([1.0, -2.0, 1.0], [0, 1, 2], shape=(frames - 2, frames))
    first = sp.diags([-1.0, 1.0], [0, 1], shape=(frames - 1, frames))
    smooth = (params.smoothness / spacing**3) * (second.T @ second) + (params.velocity / spacing) * (first.T @ first)
    per_block = spacing * sp.identity(3 * frames) + sp.kron(smooth, sp.identity(3))
    hessian = sp.triu(sp.block_diag([per_block, per_block]) * 2).tocsc()

    spread = sp.identity(frames, format="csr") if interpolation is None else sp.csr_matrix(interpolation)

    def on_frames(values):
        return np.stack([spread @ values[0], spread @ values[1]])

    offsets = np.zeros((2, frames, 3))
    before = surface.depth(on_frames(offsets))
    log = []
    for iteration in range(params.iterations):
        applied = on_frames(offsets)
        found = surface.constraints(applied)
        depth = surface.depth(applied)
        log.append({"iteration": iteration, "max_depth_cm": round(float(depth.max()), 2), "constraints": len(found)})
        stalled = len(log) > 2 and log[-2]["max_depth_cm"] - log[-1]["max_depth_cm"] < 0.05
        if not found or (iteration > 0 and (depth.max() <= params.allow or stalled)):
            break
        g_rows, g_cols, g_vals, lower, upper = [], [], [], [], []
        k = 0
        for f, we, ww, normal, need in found:
            already = we * (normal @ applied[0][f]) + ww * (normal @ applied[1][f])
            keys = spread.indices[spread.indptr[f] : spread.indptr[f + 1]]
            shares = spread.data[spread.indptr[f] : spread.indptr[f + 1]]
            for block, weight in ((0, we), (1, ww)):
                if weight == 0.0:
                    continue
                for key, share in zip(keys, shares, strict=True):
                    for axis in range(3):
                        g_rows.append(k)
                        g_cols.append(var(block, int(key), axis))
                        g_vals.append(weight * share * normal[axis])
            # One slack per contact keeps the QP feasible when normals disagree;
            # the push is capped to what the trust region allows this iteration.
            g_rows.append(k)
            g_cols.append(size + k)
            g_vals.append(1.0)
            lower.append(already + min(need, 0.8 * params.step * (we + ww)))
            upper.append(np.inf)
            k += 1
        contacts = k
        moved_elbow, moved_wrist = elbow + offsets[0], wrist + offsets[1]
        for f in range(frames):  # bone lengths, linearised at the current pose
            upper_dir = moved_elbow[f] - shoulder[f]
            upper_len = float(np.linalg.norm(upper_dir))
            fore_dir = moved_wrist[f] - moved_elbow[f]
            fore_len = float(np.linalg.norm(fore_dir))
            upper_dir, fore_dir = upper_dir / upper_len, fore_dir / fore_len
            target = float(np.linalg.norm(elbow[f] - shoulder[f])) - upper_len + upper_dir @ offsets[0][f]
            for axis in range(3):
                g_rows.append(k)
                g_cols.append(var(0, f, axis))
                g_vals.append(upper_dir[axis])
            lower.append(target)
            upper.append(target)
            k += 1
            target = float(np.linalg.norm(wrist[f] - elbow[f])) - fore_len + fore_dir @ (offsets[1][f] - offsets[0][f])
            for axis in range(3):
                g_rows += [k, k]
                g_cols += [var(1, f, axis), var(0, f, axis)]
                g_vals += [fore_dir[axis], -fore_dir[axis]]
            lower.append(target)
            upper.append(target)
            k += 1
        # Trust region: the contact normals are only valid near the current pose.
        flat = offsets.reshape(-1)
        for index in range(size):
            g_rows.append(k)
            g_cols.append(index)
            g_vals.append(1.0)
            lower.append(flat[index] - params.step)
            upper.append(flat[index] + params.step)
            k += 1
        for index in range(contacts):  # slacks are non-negative
            g_rows.append(k)
            g_cols.append(size + index)
            g_vals.append(1.0)
            lower.append(0.0)
            upper.append(np.inf)
            k += 1
        constraints = sp.csc_matrix((g_vals, (g_rows, g_cols)), shape=(k, size + contacts))
        penalty = sp.identity(contacts) * (2 * params.slack_penalty)
        solver = osqp.OSQP()
        solver.setup(
            sp.block_diag([hessian, penalty]).tocsc(),
            np.zeros(size + contacts),
            constraints,
            np.array(lower),
            np.array(upper),
            verbose=False,
            eps_abs=1e-4,
            eps_rel=1e-4,
            max_iter=60000,
            polishing=True,
        )
        result = solver.solve(raise_error=False)
        log[-1]["status"] = str(result.info.status)
        if log[-1]["status"] not in ("solved", "solved inaccurate"):
            break
        offsets = result.x[:size].reshape(2, frames, 3)
    return {
        "elbow": offsets[0],
        "wrist": offsets[1],
        "depth_before": before,
        "depth_after": surface.depth(on_frames(offsets)),
        "iterations": log,
    }


def depth_summary(depth: np.ndarray, frames: np.ndarray | None = None, allow: float = 0.3) -> dict[str, Any]:
    """Frames where the arm is inside the body deeper than ``allow`` and the worst case."""
    frames = np.arange(len(depth)) if frames is None else np.asarray(frames)
    worst = int(np.argmax(depth)) if len(depth) else 0
    return {
        "penetrating_samples": int((depth > allow).sum()),
        "sample_count": int(len(depth)),
        "max_depth_cm": round(float(depth.max()), 1) if len(depth) else 0.0,
        "worst_frame": int(frames[worst]) if len(depth) else None,
        "spans": [
            {"first": int(frames[a]), "last": int(frames[b]), "max_depth_cm": round(float(depth[a : b + 1].max()), 1)}
            for a, b in _runs(depth > allow, 1, gap=1)
        ],
    }


def linear_interpolation(frames: np.ndarray, keys: np.ndarray):
    """Sparse (frames x keys) matrix spreading values at ``keys`` onto ``frames`` linearly (clamped at the ends)."""
    import scipy.sparse as sp

    frames = np.asarray(frames, dtype=float)
    keys = np.asarray(keys, dtype=float)
    right = np.clip(np.searchsorted(keys, frames, side="left"), 1, len(keys) - 1)
    left = right - 1
    share = np.clip((frames - keys[left]) / np.maximum(keys[right] - keys[left], 1e-9), 0.0, 1.0)
    rows = np.concatenate([np.arange(len(frames)), np.arange(len(frames))])
    return sp.csr_matrix(
        (np.concatenate([1.0 - share, share]), (rows, np.concatenate([left, right]))), shape=(len(frames), len(keys))
    )
