"""Rest-relative host retarget math and explicit controller adapter boundary."""
from __future__ import annotations

import numpy as np
from scipy.spatial.transform import Rotation

from .motion_context import MotionInputError, SolverResult
from .motion_math import normalise_quaternions, solve_two_bone


def _matrix(value):
    array = np.asarray(value, dtype=float)
    if array.shape[-2:] == (3, 3):
        if (not np.isfinite(array).all() or not np.allclose(np.swapaxes(array, -1, -2) @ array, np.eye(3), atol=1e-8)
                or not np.allclose(np.linalg.det(array), 1, atol=1e-8)):
            raise MotionInputError("INVALID_ROTATION", "proper orthogonal rotations required")
        return array
    scalar = array.ndim == 1
    q = normalise_quaternions(array.reshape(-1, 4))
    matrix = Rotation.from_quat(q[:, [1, 2, 3, 0]]).as_matrix()
    return matrix[0] if scalar else matrix


def world_to_local(position_world, rotation_world, parent_position_world, parent_rotation_world, parent_scale=1.0):
    """Use the planned parent transform, including scale, for every child."""
    parent = _matrix(parent_rotation_world)
    rotation = _matrix(rotation_world)
    position, origin, scale = map(lambda v: np.asarray(v, dtype=float),
                                  (position_world, parent_position_world, parent_scale))
    if not np.isfinite(position).all() or not np.isfinite(origin).all() or not np.isfinite(scale).all() or np.any(scale <= 0):
        raise MotionInputError("UNSUPPORTED_COORDINATE_SYSTEM", "finite positions and positive parent scale required")
    if scale.ndim and scale.shape!=position.shape[:-1]:
        raise MotionInputError("UNSUPPORTED_NONRIGID_PARENT","only uniform parent scale is supported")
    inverse = np.swapaxes(parent, -1, -2)
    local_position = np.einsum("...ij,...j->...i", inverse, position - origin) / (scale[..., None] if scale.ndim else scale)
    return {"position_m": local_position, "rotation_matrix": inverse @ rotation}


def forward_kinematics(local, parents):
    world, visiting = {}, set()
    def visit(role):
        if role in world:
            return world[role]
        if role in visiting or role not in local:
            raise MotionInputError("RIG_MAPPING_AMBIGUOUS", "cyclic or missing FK parent")
        visiting.add(role)
        value = local[role]
        p, r = np.asarray(value["position_m"], dtype=float), _matrix(value["rotation_matrix"])
        parent = parents.get(role)
        if parent is not None:
            transform = visit(parent)
            p = transform["position_m"] + np.einsum("...ij,...j->...i", transform["rotation_matrix"], p)
            r = transform["rotation_matrix"] @ r
        world[role] = {"position_m": p, "rotation_matrix": r}
        visiting.remove(role)
        return world[role]
    for role in local:
        visit(role)
    return world


def retarget_pose(source_local, source_rest, target_rest, role_mapping, axis_alignment,
                  target_parents, *, root_role, source_root_position_m, target_root_anchor_m,
                  root_basis, scale=None, source_leg_length_m=None, target_leg_length_m=None,
                  required_roles=(), end_effector_constraints=()):
    """Map rest-relative rotations then enforce declared target-space limb goals.

    Target rest translations are retained; this function never copies source
    world joint positions onto a skeleton with different lengths.
    """
    missing = set(required_roles) - set(role_mapping)
    if missing:
        return SolverResult("unsupported", ["RIG_MAPPING_AMBIGUOUS"], report={"missing_roles": sorted(missing)})
    if scale is None:
        if not source_leg_length_m or not target_leg_length_m:
            return SolverResult("unsupported", ["MISSING_RETARGET_SCALE"])
        scale = target_leg_length_m / source_leg_length_m
    if not np.isfinite(scale) or scale <= 0:
        raise MotionInputError("INVALID_POLICY", "retarget scale must be finite and positive")
    basis = _matrix(root_basis)
    local = {}
    for target, source in role_mapping.items():
        if source not in source_local or source not in source_rest or target not in target_rest or target not in axis_alignment:
            return SolverResult("unsupported", ["RIG_MAPPING_AMBIGUOUS"], report={"role": target})
        source_r = _matrix(source_local[source]["rotation_matrix"])
        source_r0 = _matrix(source_rest[source]["rotation_matrix"])
        target_r0 = _matrix(target_rest[target]["rotation_matrix"])
        alignment = _matrix(axis_alignment[target])
        delta = np.swapaxes(source_r0, -1, -2) @ source_r
        local[target] = {"position_m": np.array(target_rest[target]["position_m"], dtype=float, copy=True),
                         "rotation_matrix": target_r0 @ alignment @ delta @ np.swapaxes(alignment, -1, -2)}
    if root_role not in local or target_parents.get(root_role) is not None:
        return SolverResult("unsupported", ["RIG_MAPPING_AMBIGUOUS"])
    trajectory = np.asarray(source_root_position_m, dtype=float)
    if trajectory.ndim != 2 or trajectory.shape[1] != 3 or not len(trajectory) or not np.isfinite(trajectory).all():
        raise MotionInputError("INCOMPLETE_CAPTURE", "invalid source root trajectory")
    local[root_role]["position_m"] = np.asarray(target_root_anchor_m, dtype=float) + scale * ((trajectory - trajectory[0]) @ basis.T)
    world = forward_kinematics(local, target_parents)
    for constraint in end_effector_constraints:
        upper, middle, end = [constraint[name] for name in ("upper_role", "middle_role", "end_role")]
        if any(role not in world for role in (upper, middle, end)):
            return SolverResult("unsupported", ["RIG_MAPPING_AMBIGUOUS"])
        goals = np.asarray(constraint["position_m"], dtype=float)
        if goals.shape != trajectory.shape or not np.isfinite(goals).all():
            raise MotionInputError("INCOMPLETE_CAPTURE", "target IK goals must cover the complete time grid")
        for row in range(len(trajectory)):
            def at(role, channel):
                value = np.asarray(world[role][channel])
                return value[row] if value.ndim == (2 if channel == "position_m" else 3) else value
            result = solve_two_bone(at(upper, "position_m"), at(middle, "position_m"), goals[row],
                                    float(constraint["upper_length_m"]), float(constraint["lower_length_m"]),
                                    pole_axis=constraint.get("pole"), reach_policy="fail")
            if result.status != "candidate":
                return SolverResult("failed", ["CONTACT_REACH_CONFLICT"], report={"frame_row": row, "role": end, "detail": result.reason})
            for role, position in ((middle, result.elbow_m), (end, result.wrist_m)):
                parent = target_parents[role]
                p = world[parent]["position_m"]
                r = world[parent]["rotation_matrix"]
                parent_p = p[row] if np.asarray(p).ndim == 2 else p
                parent_r = r[row] if np.asarray(r).ndim == 3 else r
                old = np.asarray(local[role]["position_m"])
                if old.ndim == 1:
                    local[role]["position_m"] = np.tile(old, (len(trajectory), 1))
                local[role]["position_m"][row] = parent_r.T @ (position - parent_p)
                world = forward_kinematics(local, target_parents)
    return SolverResult("candidate", values={"local": local, "world": world},
                        report={"scale": float(scale), "runtime_quality": "unverified", "coverage": "sampled_frames"})


def controller_targets(retarget_result, target_profile, adapter, *, planned_world=None):
    if retarget_result.status != "candidate":
        return retarget_result
    if not target_profile.controller_adapter_id or adapter is None or not getattr(adapter, "verified", False):
        return SolverResult("unsupported", ["RIG_ADAPTER_UNVERIFIED"])
    result = adapter.controller_targets(retarget_result.values, target_profile, planned_world=planned_world)
    if not isinstance(result, SolverResult):
        raise MotionInputError("RIG_ADAPTER_UNVERIFIED", "adapter did not return an explicit solver outcome")
    return result
