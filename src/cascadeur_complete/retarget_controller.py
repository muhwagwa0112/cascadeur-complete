"""Code-owned lowering for the qualified independent position controller.

This module never grants native authority. The service must authenticate the
exact request and lowered result against the current private native observation.
"""
from __future__ import annotations

from dataclasses import asdict

import numpy as np

from .capture import canonical_data, canonical_digest
from .motion_context import MotionInputError, SolverResult

ADAPTER_ID = "independent-parentless-position-v1"


def controller_request(targets, profile, planned_world):
    return canonical_data({"adapter_id": profile.controller_adapter_id, "profile": asdict(profile),
                           "targets": targets, "planned_world": planned_world})


def lower_position_request(request):
    if (not isinstance(request, dict) or set(request) != {"adapter_id", "profile", "targets", "planned_world"}
            or request["adapter_id"] != ADAPTER_ID):
        raise MotionInputError("RIG_ADAPTER_UNVERIFIED", "qualified independent position adapter required")
    profile, targets = request["profile"], request["targets"]
    if not isinstance(profile, dict) or set(profile.get("role_ids", {})) != {"root"}:
        raise MotionInputError("RIG_ADAPTER_UNVERIFIED", "one explicit root role required")
    identifier = profile["role_ids"]["root"]
    if (profile.get("character_id") != identifier or profile.get("writable_ids") != [identifier]
            or profile.get("controller_adapter_id") != ADAPTER_ID
            or any(profile.get(field) for field in ("dependency_ids", "derived_ids", "mesh_ids"))
            or profile.get("parent_ids", {}) not in ({}, {identifier: None})
            or not isinstance(targets, dict) or set(targets) != {"local", "world"}
            or targets["local"] != targets["world"] or request["planned_world"] != targets["world"]
            or not isinstance(targets["world"], dict) or set(targets["world"]) != {"root"}):
        raise MotionInputError("RIG_ADAPTER_UNVERIFIED", "only a parentless direct root controller is implemented")
    pose = targets["world"]["root"]
    if not isinstance(pose, dict) or set(pose) != {"position_m", "rotation_matrix"}:
        raise MotionInputError("INCOMPLETE_CAPTURE", "complete canonical root targets required")
    position, rotation = np.asarray(pose["position_m"], dtype=float), np.asarray(pose["rotation_matrix"], dtype=float)
    if (position.ndim != 2 or position.shape[1:] != (3,) or not 0 < len(position) <= 256
            or rotation.shape != (len(position), 3, 3) or not np.isfinite(position).all()
            or not np.isfinite(rotation).all()
            or not np.allclose(np.swapaxes(rotation, -1, -2) @ rotation, np.eye(3), rtol=0, atol=1e-8)
            or not np.allclose(np.linalg.det(rotation), 1, rtol=0, atol=1e-8)):
        raise MotionInputError("INCOMPLETE_CAPTURE", "finite physical-grid root poses required")
    return {"position_m": {identifier: position.tolist()}, "space": "global"}


class IndependentPositionController:
    def __init__(self, verified_targets):
        self._verified_targets = verified_targets

    def controller_targets(self, targets, profile, *, planned_world=None):
        request = controller_request(targets, profile, planned_world)
        lowered = lower_position_request(request)
        proof = self._verified_targets(request, canonical_digest(request))
        if (not isinstance(proof, dict) or proof.get("controller_targets_digest") != canonical_digest(lowered)
                or proof.get("controller_targets") != lowered):
            raise MotionInputError("RIG_ADAPTER_UNVERIFIED", "exact controller output has no current native certification")
        return SolverResult("candidate", values=lowered,
            report={"controller_adapter_id": ADAPTER_ID, "controller_observation_digest": proof["observation_digest"],
                    "retarget_inputs_digest": proof["retarget_inputs_digest"], "runtime_quality": "unverified"})
