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
