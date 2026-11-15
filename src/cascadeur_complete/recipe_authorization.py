"""Exact step authorization and finite cumulative resource accounting."""

from __future__ import annotations

import time
import math
from dataclasses import dataclass
from typing import Any

from .models import SourceBinding
from .recipe_models import BudgetUsage, RecipeRunRecord, ScopedAuthorization, StepPermit, WorkflowPlan, digest
from .recipe_store import RecipeConflict, RecipeRunStore


@dataclass(frozen=True)
class AuthorizedStep:
    plan: WorkflowPlan
    grant: ScopedAuthorization
    run_id: str
    step: StepPermit
    source: SourceBinding | None
    arguments: dict[str, Any]
    attempt_id: str
    request_id: str
    lease_epoch: int


def validate_usage(plan: WorkflowPlan, usage: BudgetUsage, deadline: float) -> None:
    if time.time() >= deadline:
        raise RecipeConflict("RESOURCE_BUDGET_EXCEEDED: total wall time")
    limits = plan.spec.budgets
    for name, cap in {
        "bridge_requests": limits.bridge_requests, "read_retries": limits.read_retries,
        "solve_iterations": limits.solve_iterations, "correction_passes": limits.max_correction_passes,
        "generated_keys": limits.generated_keys, "written_keys": limits.written_keys,
        "memory_bytes": limits.memory_bytes, "disk_bytes": limits.disk_bytes, "output_bytes": limits.output_bytes,
    }.items():
        if getattr(usage, name) > cap:
            raise RecipeConflict(f"RESOURCE_BUDGET_EXCEEDED: {name}")


def validate_step_authorization(
    store: RecipeRunStore, grant: ScopedAuthorization, plan: WorkflowPlan,
    run: RecipeRunRecord, step: StepPermit, *, source: SourceBinding | None,
    arguments: dict[str, Any], measured_effect: dict[str, float] | None = None,
) -> None:
    store.verify_grant(grant, plan)
    if run.plan_digest != plan.plan_digest or run.authorization_id != grant.authorization_id:
        raise RecipeConflict("Authorization run binding mismatch")
    if run.cancel_requested:
        raise RecipeConflict("Cancellation forbids preparing or dispatching a new step")
    validate_usage(plan, run.budgets_used, run.deadline)
    planned = next((item for item in plan.steps if item.step_id == step.step_id), None)
    if planned is None or planned != step:
        raise RecipeConflict("Step is not part of the immutable approved plan")
    record = next(item for item in run.steps if item.step_id == step.step_id)
    if record.calls_used >= step.max_calls:
        raise RecipeConflict("Step call budget exhausted")
    if step.effect in {"evaluation", "scene_mutation", "file_stage"}:
        if source is None or not source.complete:
            raise RecipeConflict("BINDING_UNAVAILABLE: a complete runtime-issued source binding is required")
        expected_lineage = step.target.lineage_id
        if expected_lineage is not None and source.binding.document_lineage_id != expected_lineage:
            raise RecipeConflict("Target document lineage differs from the authorized plan")
    writes = arguments.get("writes", [])
    if writes:
        if set(arguments) - {"writes", "space"} or arguments.get("space") != step.fixed_parameters.get("space"):
            raise RecipeConflict("Write coordinate space or arguments differ from the exact permit")
        if not isinstance(writes, list) or len(writes) > step.max_effect_from_baseline.maximum_written_keys:
            raise RecipeConflict("Write payload exceeds the approved finite budget")
        seen = set()
        for write in writes:
            if not isinstance(write, dict) or write.get("id") not in step.target.object_ids:
                raise RecipeConflict("Write escapes exact target objects")
            frame = write.get("frame")
            if type(frame) is not int or not any(first <= frame <= last for first, last in step.frame_ranges):
                raise RecipeConflict("Write escapes exact frame scope")
            channels = set(write) - {"id", "frame"}
            if "expected_quaternion_wxyz" in channels:
                if "rotation_euler_xyz_radians" not in channels:
                    raise RecipeConflict("Expected quaternion requires an explicit rotation write")
                quaternion = write["expected_quaternion_wxyz"]
                if (not isinstance(quaternion, (list, tuple)) or len(quaternion) != 4
                        or any(not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value) for value in quaternion)
                        or abs(sum(value * value for value in quaternion) - 1) > 1e-6):
                    raise RecipeConflict("Rotation write requires a finite unit expected quaternion")
                channels.remove("expected_quaternion_wxyz")
            expected_channels = set()
            if "position" in step.allowed_channels:
                expected_channels.add("position")
            if "rotation" in step.allowed_channels:
                expected_channels.add("rotation_euler_xyz_radians")
            if not channels or not channels <= expected_channels:
                raise RecipeConflict("Write escapes exact channel scope")
            for channel in channels:
                vector = write[channel]
                if (not isinstance(vector, (list, tuple)) or len(vector) != 3
                        or any(not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value) for value in vector)):
                    raise RecipeConflict("Write channel requires a finite numeric vector3")
                key = (frame, write["id"], channel)
                if key in seen:
                    raise RecipeConflict("Duplicate frame/object/channel write")
                seen.add(key)
        if measured_effect is None:
            raise RecipeConflict("Measured cumulative effect from original baseline is required")
        for metric, cap in {
            "position_m": step.max_effect_from_baseline.maximum_position_m,
            "rotation_rad": step.max_effect_from_baseline.maximum_rotation_rad,
            "added_keys": step.max_effect_from_baseline.maximum_added_keys,
        }.items():
            value = measured_effect.get(metric)
            if value is None or isinstance(value, bool) or not math.isfinite(value) or value < 0 or value > cap:
                raise RecipeConflict(f"CORRECTION_ENVELOPE_EXCEEDED: {metric}")
    else:
        # Concrete non-solver operations are fully fixed at plan time.
        if digest(arguments) != step.fixed_parameters_digest:
            raise RecipeConflict("Operation arguments differ from the approved exact parameters")
    path = arguments.get("path") or arguments.get("destination")
    input_path = step.stage == "input" and path == step.fixed_parameters.get("path")
    if path is not None and not input_path and path not in step.max_effect_from_baseline.output_paths:
        raise RecipeConflict("Output path is not part of the exact approved scope")
