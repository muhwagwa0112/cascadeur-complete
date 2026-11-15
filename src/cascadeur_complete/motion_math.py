"""Finite quaternion, exact IK and physical-time operators for host solvers."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.spatial.transform import Rotation

from .motion_context import MotionInputError


def normalise_quaternions(wxyz, *, valid_mask=None, norm_tolerance=1e-3):
    q = np.asarray(wxyz, dtype=np.float64)
    if q.ndim != 2 or q.shape[1] != 4 or not len(q) or not np.isfinite(q).all():
        raise MotionInputError("INCOMPLETE_CAPTURE", "expected finite N x 4 quaternions")
    if valid_mask is not None and (np.asarray(valid_mask).shape != (len(q),) or not np.all(valid_mask)):
        raise MotionInputError("INCOMPLETE_CAPTURE", "missing quaternion")
    norms = np.linalg.norm(q, axis=1)
    if np.any(norms < 1e-12) or np.any(np.abs(norms - 1) > norm_tolerance):
        raise MotionInputError("INVALID_QUATERNION", "quaternion norm outside tolerance")
    return q / norms[:, None]


def hemisphere_continuous(wxyz, reference_wxyz=None):
    q = normalise_quaternions(wxyz).copy()
    if reference_wxyz is not None and q[0] @ np.asarray(reference_wxyz) < 0:
        q[0] *= -1
    for i in range(1, len(q)):
        if q[i] @ q[i - 1] < 0:
            q[i] *= -1
    return q


def rotation_mean(wxyz, weights=None, reference_wxyz=None):
    q = normalise_quaternions(wxyz)
    weights = np.ones(len(q)) if weights is None else np.asarray(weights, dtype=float)
    if weights.shape != (len(q),) or not np.isfinite(weights).all() or np.any(weights < 0) or weights.sum() <= 0:
        raise MotionInputError("INVALID_POLICY", "invalid rotation weights")
    matrix = (q.T * weights) @ q
    values, vectors = np.linalg.eigh(matrix)
    if values[-1] - values[-2] <= 1e-8 * np.trace(matrix):
        if reference_wxyz is None:
            raise MotionInputError("AMBIGUOUS_ROTATION_REFERENCE", "rotation mean has no unique principal axis")
        mean = normalise_quaternions(np.asarray(reference_wxyz).reshape(1, 4))[0]
    else:
        mean = vectors[:, -1]
    reference = q[0] if reference_wxyz is None else np.asarray(reference_wxyz)
    return -mean if mean @ reference < 0 else mean


def relative_angles(wxyz):
    q = normalise_quaternions(wxyz)
    rotation = Rotation.from_quat(q[:, [1, 2, 3, 0]])
    if len(q) < 2:
        return np.empty(0)
    return (rotation[:-1].inv() * rotation[1:]).magnitude()


def angular_velocity(wxyz, time_s):
    q = normalise_quaternions(wxyz)
    time_s = validate_time(time_s, len(q))
    if len(q) < 2:
        return np.empty((0, 3))
    rotation = Rotation.from_quat(q[:, [1, 2, 3, 0]])
    return (rotation[:-1].inv() * rotation[1:]).as_rotvec() / np.diff(time_s)[:, None]


def validate_time(time_s, n=None):
    time_s = np.asarray(time_s, dtype=float)
    if (time_s.ndim != 1 or not len(time_s) or (n is not None and len(time_s) != n)
            or not np.isfinite(time_s).all() or np.any(np.diff(time_s) <= 0)):
        raise MotionInputError("INVALID_POLICY", "time grid must be finite and increasing")
    return time_s


def temporal_operators(time_s, *, integral_weights=True):
    import scipy.sparse as sp
    time_s = validate_time(time_s)
    n = len(time_s)
    dt = np.diff(time_s)
    if n == 1:
        return sp.csr_matrix((0, 1)), sp.csr_matrix((0, 1))
    d1 = sp.diags((-1 / dt, 1 / dt), (0, 1), shape=(n - 1, n), format="csr")
    if n < 3:
        d2 = sp.csr_matrix((0, n))
    else:
        scale = 2 / (dt[:-1] + dt[1:])
        d2 = sp.diags(scale) @ (d1[1:] - d1[:-1])
        if integral_weights:
            d2 = sp.diags(np.sqrt((dt[:-1] + dt[1:]) / 2)) @ d2
    if integral_weights:
        d1 = sp.diags(np.sqrt(dt)) @ d1
    return d1.tocsr(), d2.tocsr()


def smooth_values(values, time_s, *, sigma_s):
    values = np.asarray(values, dtype=float)
    times = validate_time(time_s, len(values))
    if not np.isfinite(values).all() or not np.isfinite(sigma_s) or sigma_s < 0:
        raise MotionInputError("INVALID_POLICY", "invalid smoothing input")
    if sigma_s == 0:
        return values.copy()
    out = np.empty_like(values)
    for i, t in enumerate(times):
        lo, hi = np.searchsorted(times, (t - 4 * sigma_s, t + 4 * sigma_s), side="left")
        hi = max(hi, i + 1)
        weights = np.exp(-0.5 * ((times[lo:hi] - t) / sigma_s) ** 2)
        out[i] = np.tensordot(weights / weights.sum(), values[lo:hi], axes=(0, 0))
    return out


def smooth_rotations(wxyz, time_s, *, sigma_s, editable_mask=None, locks=None):
    q = hemisphere_continuous(wxyz)
    times = validate_time(time_s, len(q))
    if not np.isfinite(sigma_s) or sigma_s < 0:
        raise MotionInputError("INVALID_POLICY", "sigma_s must be finite and nonnegative")
    editable = np.ones(len(q), dtype=bool) if editable_mask is None else np.asarray(editable_mask, dtype=bool)
    locked = np.zeros(len(q), dtype=bool) if locks is None else np.asarray(locks, dtype=bool)
    if editable.shape != (len(q),) or locked.shape != (len(q),):
        raise MotionInputError("INVALID_POLICY", "invalid rotation lock coverage")
    rotations = Rotation.from_quat(q[:, [1, 2, 3, 0]])
    out = q.copy()
    if sigma_s == 0:
        return out
    for i, t in enumerate(times):
        if not editable[i] or locked[i]:
            continue
        lo, hi = np.searchsorted(times, (t - 4 * sigma_s, t + 4 * sigma_s))
        lo = max(lo, max(np.where(locked[:i] | ~editable[:i])[0], default=-1) + 1)
        future = np.where(locked[i + 1:] | ~editable[i + 1:])[0]
        hi = min(max(hi, i + 1), i + 1 + (future[0] if len(future) else len(q)))
        relative = (rotations[i].inv() * rotations[lo:hi]).as_rotvec()
        if np.any(np.linalg.norm(relative, axis=1) >= np.pi - 1e-6):
            continue  # A pi log has no unique axis; retain the observed pose.
        weights = np.exp(-0.5 * ((times[lo:hi] - t) / sigma_s) ** 2)
        tangent = (weights[:, None] * relative).sum(0) / weights.sum()
        out[i] = (rotations[i] * Rotation.from_rotvec(tangent)).as_quat()[[3, 0, 1, 2]]
    return hemisphere_continuous(out, q[0])


def _unit_vector(value):
    value = np.asarray(value, dtype=float)
    if value.shape != (3,) or not np.isfinite(value).all() or np.linalg.norm(value) < 1e-12:
        raise MotionInputError("INVALID_VECTOR", "expected nonzero finite 3-vector")
    return value / np.linalg.norm(value)


def orthogonal_axis(axis, *preferences):
    axis = _unit_vector(axis)
    for value in preferences:
        if value is None:
            continue
        value = np.asarray(value, dtype=float)
        if value.shape != (3,) or not np.isfinite(value).all():
            continue
        projected = value - (value @ axis) * axis
        if np.linalg.norm(projected) > 1e-10:
            return projected / np.linalg.norm(projected)
    basis = np.eye(3)[np.argmin(np.abs(axis))]
    return _unit_vector(np.cross(axis, basis))


def align_vectors(a, b, *, previous_axis=None, rest_axis=None):
    a, b = _unit_vector(a), _unit_vector(b)
    cross = np.cross(a, b)
    sine, cosine = np.linalg.norm(cross), np.clip(a @ b, -1, 1)
    if sine < 1e-12:
        if cosine > 0:
            return Rotation.identity()
        axis = orthogonal_axis(a, previous_axis, rest_axis)
        if previous_axis is not None and axis @ np.asarray(previous_axis) < 0:
            axis *= -1
        return Rotation.from_rotvec(axis * np.pi)
    return Rotation.from_rotvec(cross / sine * np.arctan2(sine, cosine))


@dataclass(frozen=True)
class TwoBoneResult:
    status: str
    elbow_m: np.ndarray | None
    wrist_m: np.ndarray | None
    requested_wrist_m: np.ndarray
    reached_target: bool
    upper_error_m: float | None
    fore_error_m: float | None
    reason: str | None = None
    projection_distance_m: float = 0.0


def solve_two_bone(shoulder_m, original_elbow_m, target_wrist_m, upper_length_m, fore_length_m,
                   *, pole_axis=None, previous_bend_axis=None, reach_policy="fail"):
    shoulder, elbow, requested = (np.asarray(x, dtype=float) for x in (shoulder_m, original_elbow_m, target_wrist_m))
    if any(x.shape != (3,) or not np.isfinite(x).all() for x in (shoulder, elbow, requested)):
        raise MotionInputError("INVALID_POLICY", "invalid two bone positions")
    l1, l2 = float(upper_length_m), float(fore_length_m)
    if not np.isfinite([l1, l2]).all() or min(l1, l2) <= 0 or reach_policy not in ("fail", "project"):
        raise MotionInputError("INVALID_POLICY", "invalid bone lengths/reach policy")
    delta = requested - shoulder
    distance = float(np.linalg.norm(delta))
    low, high = abs(l1 - l2), l1 + l2
    tolerance = 1e-12 * max(high, 1.0)
    reachable = low - tolerance <= distance <= high + tolerance
    if not reachable and reach_policy == "fail":
        return TwoBoneResult("failed", None, None, requested, False, None, None, "UNREACHABLE_TARGET")
    if distance < tolerance:
        if low <= tolerance:
            candidate = np.asarray(pole_axis if pole_axis is not None else elbow - shoulder)
            direction = _unit_vector(candidate if np.linalg.norm(candidate) > 1e-12 else np.array([1., 0., 0.]))
            solved_wrist, solved_elbow = shoulder.copy(), shoulder + l1 * direction
        else:
            candidate = np.asarray(pole_axis if pole_axis is not None else elbow - shoulder)
            direction = _unit_vector(candidate if np.linalg.norm(candidate) > 1e-12 else np.array([1., 0., 0.]))
            solved_wrist = shoulder + direction * low
            along = (l1 * l1 - l2 * l2 + low * low) / (2 * low)
            solved_elbow = shoulder + direction * along
    else:
        axis = delta / distance
        projected_distance = float(np.clip(distance, low, high))
        solved_wrist = shoulder + projected_distance * axis
        along = (l1 * l1 - l2 * l2 + projected_distance * projected_distance) / (2 * projected_distance)
        height = np.sqrt(max(l1 * l1 - along * along, 0.0))
        center = shoulder + along * axis
        bend = orthogonal_axis(axis, elbow - center, previous_bend_axis, pole_axis)
        solved_elbow = center + height * bend
    upper_error = abs(float(np.linalg.norm(solved_elbow - shoulder)) - l1)
    fore_error = abs(float(np.linalg.norm(solved_wrist - solved_elbow)) - l2)
    projection = float(np.linalg.norm(solved_wrist - requested))
    if max(upper_error, fore_error) > 1e-9 * max(high, 1.0):
        return TwoBoneResult("failed", None, None, requested, False, upper_error, fore_error, "IK_RESIDUAL")
    return TwoBoneResult("candidate", solved_elbow, solved_wrist, requested, projection <= tolerance,
                         upper_error, fore_error, None if reachable else "TARGET_PROJECTED", projection)
