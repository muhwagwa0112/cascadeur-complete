"""Exact step authorization and finite cumulative resource accounting."""

from __future__ import annotations

import time
import math
from dataclasses import dataclass
from typing import Any

from .models import SourceBinding
from .recipe_models import BudgetUsage, RecipeRunRecord, ScopedAuthorization, StepPermit, WorkflowPlan, digest
from .recipe_store import RecipeConflict, RecipeRunStore
from .recipe_store import file_sha256
from .stage_contracts import StageEffect
from pathlib import Path


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
    stage_effect: StageEffect | None = None, topology_delta=None,
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
    if stage_effect is not None:
        if (stage_effect.step_id != step.step_id or stage_effect.declaration_digest != step.fixed_parameters_digest
                or stage_effect.lowering_rule_id != step.lowering_rule_id
                or stage_effect.lowering_rule_digest != step.lowering_rule_digest
                or stage_effect.operation_name != step.operation_name or stage_effect.feature_id != step.feature_id
                or stage_effect.effect_bounds_digest != digest(step.max_effect_from_baseline)
                or stage_effect.arguments_digest != digest(arguments) or stage_effect.source_binding != source):
            raise RecipeConflict("STAGE_EFFECT_SCOPE_MISMATCH")
        target_ids = set(step.target.object_ids)
        if step.target.derived_ref is not None:
            mapping = next((item for item in run.derived_targets if item.reference_digest == digest(step.target.derived_ref)), None)
            producer = step.target.derived_ref.producer_step_id == step.step_id
            before_producer = step.stage in {"initial_checkpoint"} and mapping is None
            if mapping is None and not (producer or before_producer):
                raise RecipeConflict("DERIVED_TARGET_UNRESOLVED")
            if mapping is not None:
                if stage_effect.derived_mapping_digest != digest(mapping):
                    raise RecipeConflict("DERIVED_TARGET_SCOPE_MISMATCH")
                target_ids = {mapping.role_ids[key] for key in step.target.object_ids} if step.target.object_ids else set(mapping.object_ids)
        if not set(stage_effect.target_object_ids) <= target_ids:
            raise RecipeConflict("LOWERED_TARGET_ESCAPES_DECLARATION")
        for manifest in stage_effect.input_files:
            sha, length = file_sha256(Path(manifest.path))
            if sha != manifest.sha256 or length != manifest.length:
                raise RecipeConflict("LOWERED_INPUT_BYTES_CHANGED")
            if source is None or manifest.model_dump(mode="json") not in source.scope.get("input_files", []):
                raise RecipeConflict("INPUT_MANIFEST_UNATTESTED")
        for output in stage_effect.output_paths:
            path = Path(output).resolve()
            policy = step.max_effect_from_baseline.owned_output_policy
            if policy == "run_workspace":
                root = store.run_dir(run.run_id).resolve()
                if not path.is_relative_to(root) or path == root:
                    raise RecipeConflict("LOWERED_OUTPUT_ESCAPES_WORKSPACE")
            elif policy == "export_stage":
                destination = Path(plan.spec.export.destination).resolve()
                if (path.parent.parent != destination.parent or not path.parent.name.startswith(f".cascadeur-export-{run.run_id}-{step.step_id}-")
                        or path.name not in {"raw.fbx", "sealed.fbx"}):
                    raise RecipeConflict("LOWERED_OUTPUT_ESCAPES_EXPORT_STAGE")
            elif output not in step.max_effect_from_baseline.output_paths:
                raise RecipeConflict("LOWERED_OUTPUT_NOT_AUTHORIZED")
    if step.effect in {"evaluation", "scene_mutation", "file_stage"} and step.stage != "initial_checkpoint":
        if source is None or not source.complete:
            raise RecipeConflict("BINDING_UNAVAILABLE: a complete runtime-issued source binding is required")
        expected_lineage = step.target.lineage_id
        if expected_lineage is not None and source.binding.document_lineage_id != expected_lineage:
            raise RecipeConflict("Target document lineage differs from the authorized plan")
    if step.stage == "motion" and plan.spec.motion.mode == "native_unbaking":
        from .unbaking_contract import UnbakingTopologyPolicy, unbaking_topology_policy
        motion = plan.spec.motion
        limits = motion.unbaking_limits
        policy = unbaking_topology_policy(limits, allow_key_insertion=plan.spec.intent.allow_key_insertion,
            allow_interpolation_change=plan.spec.intent.allow_interpolation_change)
        try:
            wire_policy = UnbakingTopologyPolicy.model_validate(arguments.get("topology_policy"))
        except ValueError as exc:
            raise RecipeConflict("UNBAKING_TOPOLOGY_POLICY_MISMATCH") from exc
        ids, layers = step.target.object_ids, step.target.layer_ids
        if step.target.derived_ref is not None:
            mapping = next((item for item in run.derived_targets
                if item.reference_digest == digest(step.target.derived_ref)), None)
            if mapping is None:
                raise RecipeConflict("DERIVED_TARGET_UNRESOLVED")
            ids = tuple(mapping.role_ids[key] for key in ids) if ids else mapping.object_ids
            layers = mapping.layer_ids
        if len(step.frame_ranges) != 1:
            raise RecipeConflict("UNBAKING_REQUIRES_ONE_EXACT_FRAME_RANGE")
        first, last = step.frame_ranges[0]
        expected = {"step": motion.unbaking_step, "object_ids": list(ids), "layer_ids": list(layers),
            "first_frame": first, "last_frame": last, "topology_policy": policy.model_dump(mode="json")}
        if (stage_effect is None or source is None or not ids or not layers or first >= last
                or step.feature_id != "unbaking" or step.operation_name != "generation.unbaking"
                or step.fixed_parameters != motion.model_dump(mode="json")
                or step.max_effect_from_baseline.maximum_added_keys != limits.maximum_added_keys
                or step.max_effect_from_baseline.maximum_written_keys != limits.maximum_written_keys
                or wire_policy != policy or arguments != expected
                or type(arguments.get("first_frame")) is not int or type(arguments.get("last_frame")) is not int
                or stage_effect.target_object_ids != tuple(ids) or stage_effect.target_layer_ids != tuple(layers)
                or source.scope.get("operation_name") != step.operation_name
                or source.scope.get("operation_arguments_digest") != digest(arguments)
                or source.scope.get("operation_arguments") != arguments):
            raise RecipeConflict("UNBAKING_AUTHORIZATION_MISMATCH")
        return
    if step.stage == "key_insert":
        from .motion_key_layout import KeyTopologyDelta
        delta = KeyTopologyDelta.model_validate(topology_delta)
        proof = delta.locator_insertion
        cap = step.max_effect_from_baseline.maximum_added_keys
        additions = delta.additions
        expected = {"object_id": additions[0].object_id, "layer_id": additions[0].layer_id,
            "additions": [{"frame": row.frame, "position": list(row.value), "mode": row.mode} for row in additions],
            "space": "local", "allow_key_insertion": True, "max_added_keys": cap} if additions else None
        approved_total = sum(item.max_effect_from_baseline.maximum_added_keys for item in plan.steps
            if item.stage == "key_insert" or (item.stage == "motion" and item.operation_name == "generation.unbaking"))
        original_cap = min(plan.spec.budgets.generated_keys, int(plan.spec.intent.correction_envelope.get("added_keys", 0)))
        if (not plan.spec.intent.allow_key_insertion or approved_total > original_cap
                or stage_effect is None or source is None or proof is None or not 1 <= len(additions) <= cap <= 8
                or arguments != expected or step.feature_id != "key_insert"
                or step.operation_name != "motion.key_topology_insert"
                or len({(row.object_id, row.channel, row.layer_id) for row in additions}) != 1
                or any(row.channel != "position" or row.object_id not in stage_effect.target_object_ids
                       or row.layer_id not in stage_effect.target_layer_ids
                       or not any(first <= row.frame <= last for first, last in step.frame_ranges) for row in additions)
                or proof.before_projection_digest != source.sample_digest
                or proof.runtime_epoch != source.binding.runtime_epoch
                or proof.runtime_fingerprint != source.adapter_fingerprint
                or proof.scene_instance_id != source.binding.scene_instance_id
                or proof.document_lineage_id != source.binding.document_lineage_id):
            raise RecipeConflict("KEY_INSERTION_AUTHORIZATION_MISMATCH")
        if measured_effect is None or any(
                name not in measured_effect or not math.isfinite(measured_effect[name])
                or measured_effect[name] < 0 or measured_effect[name] > limit
                for name, limit in (("position_m", step.max_effect_from_baseline.maximum_position_m),
                                    ("rotation_rad", step.max_effect_from_baseline.maximum_rotation_rad))):
            raise RecipeConflict("CORRECTION_ENVELOPE_EXCEEDED: insertion prediction")
        return
    writes = arguments.get("writes", [])
    if writes:
        creation = step.stage == "motion" and plan.spec.motion.mode == "keyposes"
        if creation:
            expected_writes = [item.model_dump(mode="json", exclude_none=True) for item in plan.spec.motion.keyposes]
            if plan.spec.character.derived_target is not None:
                mapping = next(item for item in run.derived_targets if item.reference_digest == digest(plan.spec.character.derived_target))
                expected_writes = [{**item, "id": mapping.role_ids[item["id"]]} for item in expected_writes]
            if arguments != {"writes": expected_writes, "space": "global"}:
                raise RecipeConflict("Keypose payload differs from the exact creation declaration")
        host_retarget = step.stage == "motion" and plan.spec.motion.mode == "retarget" and plan.spec.motion.route == "host"
        expected_space = "global" if creation else plan.spec.motion.host_space if host_retarget else step.fixed_parameters.get("space")
        if set(arguments) - {"writes", "space"} or arguments.get("space") != expected_space:
            raise RecipeConflict("Write coordinate space or arguments differ from the exact permit")
        if not isinstance(writes, list) or len(writes) > step.max_effect_from_baseline.maximum_written_keys:
            raise RecipeConflict("Write payload exceeds the approved finite budget")
        seen = set()
        for write in writes:
            allowed_ids = set(step.target.object_ids) if stage_effect is None else set(stage_effect.target_object_ids)
            if not isinstance(write, dict) or write.get("id") not in allowed_ids:
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
        if measured_effect is None and not creation:
            raise RecipeConflict("Measured cumulative effect from original baseline is required")
        for metric, cap in {
            "position_m": step.max_effect_from_baseline.maximum_position_m,
            "rotation_rad": step.max_effect_from_baseline.maximum_rotation_rad,
            "added_keys": step.max_effect_from_baseline.maximum_added_keys,
        }.items():
            if creation:
                continue
            value = measured_effect.get(metric)
            if value is None or isinstance(value, bool) or not math.isfinite(value) or value < 0 or value > cap:
                raise RecipeConflict(f"CORRECTION_ENVELOPE_EXCEEDED: {metric}")
    else:
        # Concrete non-solver operations are fully fixed at plan time.
        if stage_effect is None and digest(arguments) != step.fixed_parameters_digest:
            raise RecipeConflict("Operation arguments differ from the approved exact parameters")
    path = arguments.get("path") or arguments.get("destination")
    input_path = step.stage == "input" and path == step.fixed_parameters.get("path")
    if path is not None and not input_path and path not in step.max_effect_from_baseline.output_paths and (stage_effect is None or path not in stage_effect.output_paths):
        raise RecipeConflict("Output path is not part of the exact approved scope")
