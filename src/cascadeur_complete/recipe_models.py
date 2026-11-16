"""Strict public recipe input and durable finite workflow records.

The public recipe describes a motion operation; it never accepts a Python
program, arbitrary feature/operation name, or an authorization bypass.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, StrictInt, model_validator

from .export_models import ExportProfile
from .models import SceneBinding, SourceBinding
from .motion_context import IntentConstraints
from .motion_quality import QualityPolicy
from .geometry_contract import GeometryCapturePolicy
from .stage_contracts import BootstrapGrant, CheckpointObservation, DerivedTargetMapping, DerivedTargetRef, StageEffect
from .unbaking_contract import UnbakingKeyLimits

Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Identifier = Annotated[str, Field(min_length=1, max_length=256, pattern=r"^[^\x00-\x1f*?]+$")]
PositiveInt = Annotated[StrictInt, Field(gt=0)]
NonnegativeInt = Annotated[StrictInt, Field(ge=0)]
PositiveFloat = Annotated[float, Field(gt=0)]
RunState = Literal["planned", "authorized", "queued", "running", "cancel_requested", "blocked", "succeeded", "failed", "canceled"]
StepState = Literal[
    "pending", "ready", "preparing", "prepared", "dispatching", "awaiting_result", "verifying",
    "checkpointing", "succeeded", "no_change", "skipped", "failed", "canceled", "blocked",
]
ExecutionOutcome = Literal[
    "not_dispatched", "canceled_pre_dispatch", "rejected_pre_dispatch", "succeeded",
    "failed_after_dispatch", "outcome_unknown",
]
Effect = Literal["read", "host_compute", "evaluation", "scene_mutation", "file_stage", "publish"]


def canonical_bytes(value: Any) -> bytes:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


class RecipeModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, validate_default=True, frozen=True)


class ArtifactRef(RecipeModel):
    artifact_id: Identifier
    kind: Identifier
    path: str
    sha256: Sha256
    schema_version: PositiveInt = 1
    length: NonnegativeInt
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class InputSpec(RecipeModel):
    kind: Literal["active_scene", "casc_file", "fbx_file"]
    binding: SceneBinding | None = None
    source_binding: SourceBinding | None = None
    path: str | None = None
    sha256: Sha256 | None = None
    mode: Literal["new_working_scene", "merge_into_working"] = "new_working_scene"

    @model_validator(mode="after")
    def validate_input(self):
        if (self.source_binding is not None and self.binding is not None
                and self.source_binding.binding != self.binding):
            raise ValueError("source binding does not identify the input scene")
        if self.kind == "active_scene":
            if self.binding is None:
                raise ValueError("active_scene requires an exact SceneBinding")
            if self.path is not None or self.sha256 is not None:
                raise ValueError("active_scene cannot silently select a file")
        elif self.path is None or self.sha256 is None or not Path(self.path).is_absolute():
            raise ValueError("File inputs require an absolute path and content SHA256")
        return self


class CharacterSpec(RecipeModel):
    character_id: Identifier | None = None
    root_id: Identifier | None = None
    object_ids: tuple[Identifier, ...] = ()
    layer_ids: tuple[Identifier, ...] = ()
    role_ids: dict[str, Identifier] = Field(default_factory=dict)
    rig_profile_digest: Sha256 | None = None
    rig_profile: dict[str, JsonValue] = Field(default_factory=dict)
    required_mesh_ids: tuple[Identifier, ...] = ()
    optional_mesh_ids: tuple[Identifier, ...] = ()
    source_character_id: Identifier | None = None
    derived_target: DerivedTargetRef | None = None

    @model_validator(mode="after")
    def unique_scope(self):
        if self.derived_target is not None:
            if (self.character_id is not None or self.root_id is not None or self.object_ids or self.layer_ids
                    or self.role_ids or self.rig_profile or self.rig_profile_digest is not None):
                raise ValueError("Derived targets cannot contain invented concrete IDs/profile")
            return self
        if self.character_id is None or self.root_id is None or not self.object_ids:
            raise ValueError("Existing targets require exact character/root/object identities")
        if len(self.object_ids) != len(set(self.object_ids)):
            raise ValueError("Duplicate target objects")
        if self.root_id not in self.object_ids or not set(self.role_ids.values()) <= set(self.object_ids):
            raise ValueError("Root and semantic roles must belong to the explicit target objects")
        if digest(self.rig_profile) != self.rig_profile_digest:
            raise ValueError("Rig profile digest mismatch")
        return self


class ClipSpec(RecipeModel):
    first_frame: NonnegativeInt
    last_frame: NonnegativeInt
    fps_num: PositiveInt
    fps_den: PositiveInt
    time_origin_s: float = 0.0
    metres_per_scene_unit: PositiveFloat
    scene_to_solver_basis: tuple[tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]]

    @model_validator(mode="after")
    def validate_clip(self):
        import numpy as np

        if self.last_frame < self.first_frame:
            raise ValueError("Empty or reversed clip range")
        basis = np.asarray(self.scene_to_solver_basis, dtype=np.float64)
        if not np.allclose(basis.T @ basis, np.eye(3), atol=1e-8, rtol=0) or abs(np.linalg.det(basis) - 1) > 1e-8:
            raise ValueError("UNSUPPORTED_COORDINATE_SYSTEM: a proper orthonormal basis is required")
        return self


class RigStageSpec(RecipeModel):
    mode: Literal["existing", "template", "explicit_mapping"] = "existing"
    template: ArtifactRef | None = None
    role_mapping: dict[str, Identifier] = Field(default_factory=dict)
    controller_adapter_id: Identifier

    @model_validator(mode="after")
    def required_mapping(self):
        if self.mode == "template" and self.template is None:
            raise ValueError("Template rig stage requires immutable template bytes")
        if self.mode == "explicit_mapping" and not self.role_mapping:
            raise ValueError("Explicit rig mapping cannot be empty")
        return self


class PoseWrite(RecipeModel):
    id: Identifier
    frame: NonnegativeInt
    position: tuple[float, float, float] | None = None
    rotation_euler_xyz_radians: tuple[float, float, float] | None = None

    @model_validator(mode="after")
    def one_channel(self):
        if (self.position is None) == (self.rotation_euler_xyz_radians is None):
            raise ValueError("A pose write must contain exactly one channel")
        return self


class MotionStageSpec(RecipeModel):
    mode: Literal["existing", "retarget", "keyposes", "native_root_motion", "native_inbetweening", "external_motion_asset", "native_unbaking"] = "existing"
    route: Literal["native", "host"] | None = None
    source: ArtifactRef | None = None
    mapping: dict[str, JsonValue] = Field(default_factory=dict)
    keyposes: tuple[PoseWrite, ...] = ()
    settings: dict[str, JsonValue] = Field(default_factory=dict)
    unbaking_step: Literal["prepare_keys_by_fulcrums", "adjust_keys_and_interpolation", "adjust_autoposing_lock_state"] | None = None
    unbaking_limits: UnbakingKeyLimits | None = None
    host_channel: Literal["position", "rotation"] = "position"
    host_space: Literal["local", "global"] = "global"

    @model_validator(mode="after")
    def required_mode_inputs(self):
        if self.mode == "retarget" and (self.route is None or self.source is None or not self.mapping):
            raise ValueError("Retarget requires an explicit route, source and semantic mapping")
        if self.mode != "retarget" and self.route is not None:
            raise ValueError("route applies only to retargeting")
        if self.mode == "keyposes" and not self.keyposes:
            raise ValueError("keyposes mode requires explicit poses")
        if self.mode == "external_motion_asset" and self.source is None:
            raise ValueError("external_motion_asset requires an immutable input artifact")
        if self.mode == "native_unbaking" and self.unbaking_step is None:
            raise ValueError("native_unbaking requires one of the three registered steps")
        if self.mode != "native_unbaking" and self.unbaking_step is not None:
            raise ValueError("unbaking_step only applies to native_unbaking")
        if self.mode == "native_unbaking":
            if self.unbaking_limits is None:
                raise ValueError("native_unbaking requires explicit unbaking_limits")
            if self.settings:
                raise ValueError("native_unbaking settings are unsupported")
        elif self.unbaking_limits is not None:
            raise ValueError("unbaking_limits only applies to native_unbaking")
        return self


class ReferenceInputs(RecipeModel):
    support_tracks: tuple[ArtifactRef, ...] = ()
    geometry: tuple[ArtifactRef, ...] = ()
    prop_tracks: tuple[ArtifactRef, ...] = ()


class VariantEnvelope(RecipeModel):
    variant_id: Identifier
    parameters: dict[str, JsonValue] = Field(default_factory=dict)


class CleanupPassSpec(RecipeModel):
    kind: Literal["foot_contacts", "fingers", "finger_fan", "arm_clearance", "wrist_soften", "hand_pose", "hand_rest", "wrist_accent"]
    object_ids: tuple[Identifier, ...] = Field(min_length=1)
    intent: Literal["preserve_motion", "stylize_hands", "add_wrist_accent"] = "preserve_motion"
    parameters: dict[str, JsonValue] = Field(default_factory=dict)
    variants: tuple[VariantEnvelope, ...] = ()

    @model_validator(mode="after")
    def bounded_parameters(self):
        for parameters in (self.parameters, *(item.parameters for item in self.variants)):
            if self.kind == "fingers":
                if set(parameters) - {"spike_angle_rad", "spike_deg", "joint_ids"}:
                    raise ValueError("Unknown finger solver parameter")
                ids = parameters.get("joint_ids", list(self.object_ids))
                if not isinstance(ids, list) or not ids or not set(ids) <= set(self.object_ids):
                    raise ValueError("Finger joints escape the exact pass object scope")
            if self.kind == "foot_contacts":
                if set(parameters) - {"limits", "interpolation_capabilities"}:
                    raise ValueError("Unknown contact solver parameter")
                limits = parameters.get("limits", {})
                if not isinstance(limits, dict) or set(limits) - {
                    "iterations", "position_correction_m", "rotation_correction_rad", "contact_gap_m",
                    "contact_drift_m", "velocity_weight", "acceleration_weight", "fit_error_m",
                }:
                    raise ValueError("Unknown contact solver limit")
                iterations = limits.get("iterations", 8)
                if type(iterations) is not int or not 0 < iterations <= 100:
                    raise ValueError("Contact iterations must be an integer in 1..100")
        return self


class RunBudgets(RecipeModel):
    total_wall_seconds: PositiveFloat = 1800
    bridge_requests: PositiveInt = 1000
    read_retries: NonnegativeInt = 2
    solve_iterations: PositiveInt = 100
    max_correction_passes: PositiveInt = 2
    generated_keys: NonnegativeInt = 0
    written_keys: PositiveInt = 60000
    memory_bytes: PositiveInt = 536870912
    disk_bytes: PositiveInt = 2147483648
    output_bytes: PositiveInt = 1073741824
    geometry_calculations: NonnegativeInt = 0
    per_step_seconds: PositiveFloat = 120


class RecipeSpec(RecipeModel):
    schema_version: Literal[1] = 1
    input: InputSpec
    character: CharacterSpec
    clip: ClipSpec
    rig: RigStageSpec
    motion: MotionStageSpec = Field(default_factory=MotionStageSpec)
    intent: IntentConstraints
    references: ReferenceInputs = Field(default_factory=ReferenceInputs)
    cleanup: tuple[CleanupPassSpec, ...] = ()
    quality: QualityPolicy
    geometry_capture: "GeometryCapturePolicy | None" = None
    export: ExportProfile | None = None
    budgets: RunBudgets = Field(default_factory=RunBudgets)

    @model_validator(mode="after")
    def validate_permissions(self):
        scope = set(self.character.object_ids) if self.character.derived_target is None else set(self.character.derived_target.role_paths)
        if self.geometry_capture is not None:
            policy = self.geometry_capture
            required_meshes = set(self.character.required_mesh_ids) | set(self.character.rig_profile.get("mesh_ids", []))
            if (not required_meshes <= set(policy.mesh_ids)
                    or policy.max_array_bytes > self.budgets.memory_bytes
                    or policy.max_artifact_bytes > self.budgets.disk_bytes
                    or policy.max_calculations > self.budgets.geometry_calculations):
                raise ValueError("Geometry capture policy exceeds approved required-mesh/resource bounds")
        if tuple(self.intent.editable_frames) != (self.clip.first_frame, self.clip.last_frame):
            raise ValueError("Clip and editable intent range must match")
        if self.motion.mode == "native_unbaking":
            limits = self.motion.unbaking_limits
            added_cap = min(self.intent.correction_envelope.get("added_keys", 0), self.budgets.generated_keys)
            if (limits.maximum_added_keys > added_cap
                    or (not self.intent.allow_key_insertion and limits.maximum_added_keys != 0)):
                raise ValueError("Unbaking key additions exceed the original insertion intent or generated-key budget")
            if limits.maximum_written_keys > self.budgets.written_keys:
                raise ValueError("Unbaking writes exceed the written-key budget")
        for cleanup in self.cleanup:
            if not set(cleanup.object_ids) <= scope:
                raise ValueError("Cleanup pass escapes the target character scope")
            if cleanup.kind in {"finger_fan", "hand_pose", "hand_rest", "wrist_accent"}:
                if cleanup.intent == "preserve_motion" or self.intent.action != "styling":
                    raise ValueError("Styling passes require explicit styling intent")
            if len(cleanup.variants) > self.budgets.max_correction_passes:
                raise ValueError("Candidate variants exceed the finite correction budget")
        for write in self.motion.keyposes:
            if write.id not in scope or not self.clip.first_frame <= write.frame <= self.clip.last_frame:
                raise ValueError("Key pose escapes authorized object/frame scope")
        support_ids = {item.artifact_id for item in self.references.support_tracks}
        if any(contact.support_id not in support_ids for contact in self.intent.contacts):
            raise ValueError("Every contact requires an immutable support track reference")
        # Also rejects NaN/Infinity hidden inside untyped numeric parameters.
        canonical_bytes(self.model_dump(mode="json"))
        return self


class ExactTarget(RecipeModel):
    character_id: Identifier | None
    object_ids: tuple[Identifier, ...]
    layer_ids: tuple[Identifier, ...] = ()
    lineage_id: Identifier | None = None
    derived_ref: DerivedTargetRef | None = None


class EffectBounds(RecipeModel):
    maximum_position_m: Annotated[float, Field(ge=0)] = 0
    maximum_rotation_rad: Annotated[float, Field(ge=0)] = 0
    maximum_added_keys: NonnegativeInt = 0
    maximum_written_keys: PositiveInt = 60000
    output_paths: tuple[str, ...] = ()
    owned_output_policy: Literal["none", "run_workspace", "export_stage", "geometry_capture"] = "none"


class StepPermit(RecipeModel):
    step_id: Identifier
    stage: Identifier
    feature_id: Identifier
    operation_name: Identifier
    effect: Effect
    intent: str
    target: ExactTarget
    frame_ranges: tuple[tuple[NonnegativeInt, NonnegativeInt], ...]
    allowed_channels: tuple[Literal["position", "rotation", "scene", "file", "evaluation"], ...]
    fixed_parameters: dict[str, JsonValue] = Field(default_factory=dict)
    fixed_parameters_digest: Sha256
    candidate_variants: tuple[VariantEnvelope, ...] = ()
    max_effect_from_baseline: EffectBounds
    max_calls: PositiveInt = 1
    prerequisite_step_ids: tuple[Identifier, ...] = ()
    required_postconditions: tuple[Identifier, ...] = ()
    not_required_reason: str | None = None
    lowering_rule_id: str = "literal-v1"
    lowering_rule_digest: Sha256 | None = None

    @model_validator(mode="after")
    def parameters_match(self):
        if digest(self.fixed_parameters) != self.fixed_parameters_digest:
            raise ValueError("Step parameters digest mismatch")
        rule_digest = digest({"rule_id": self.lowering_rule_id, "declaration_digest": self.fixed_parameters_digest,
                              "operation_name": self.operation_name})
        if self.lowering_rule_digest is None:
            object.__setattr__(self, "lowering_rule_digest", rule_digest)
        elif self.lowering_rule_digest != rule_digest:
            raise ValueError("Lowering rule digest mismatch")
        return self


class WorkflowPlan(RecipeModel):
    schema_version: Literal[1] = 1
    plan_id: str
    created_at: float
    spec: RecipeSpec
    steps: tuple[StepPermit, ...]
    scope_digest: Sha256
    implementation_digest: Sha256
    runtime_fingerprints: dict[str, JsonValue] = Field(default_factory=dict)
    blocked_reasons: tuple[dict[str, JsonValue], ...] = ()
    plan_digest: Sha256

    @model_validator(mode="after")
    def dag_and_digest(self):
        seen = set()
        for step in self.steps:
            if step.step_id in seen or not set(step.prerequisite_step_ids) <= seen:
                raise ValueError("Steps must be a unique topologically ordered DAG")
            seen.add(step.step_id)
        if digest(self.model_dump(mode="json", exclude={"plan_digest"})) != self.plan_digest:
            raise ValueError("Immutable plan digest mismatch")
        return self


class ScopedAuthorization(RecipeModel):
    schema_version: Literal[1] = 1
    authorization_id: str
    plan_id: str
    plan_digest: Sha256
    scope_digest: Sha256
    issued_at: float
    expires_at: float
    mac: str


class BudgetUsage(RecipeModel):
    bridge_requests: NonnegativeInt = 0
    read_retries: NonnegativeInt = 0
    solve_iterations: NonnegativeInt = 0
    correction_passes: NonnegativeInt = 0
    generated_keys: NonnegativeInt = 0
    written_keys: NonnegativeInt = 0
    memory_bytes: NonnegativeInt = 0
    disk_bytes: NonnegativeInt = 0
    output_bytes: NonnegativeInt = 0
    geometry_calculations: NonnegativeInt = 0


class StepRecord(RecipeModel):
    step_id: str
    state: StepState = "pending"
    attempt_id: str | None = None
    execution_outcome: ExecutionOutcome = "not_dispatched"
    request_id: str | None = None
    request_digest: str | None = None
    dispatch_lease_epoch: PositiveInt | None = None
    token_ref: str | None = None
    source_binding: SourceBinding | None = None
    expected_successor: SourceBinding | None = None
    receipt_ref: str | None = None
    verification_status: Literal["pass", "fail", "unverified", "not_applicable"] = "unverified"
    verification_report_ref: str | None = None
    checkpoint_ref: str | None = None
    correction_id: str | None = None
    artifact_refs: tuple[ArtifactRef, ...] = ()
    calls_used: NonnegativeInt = 0
    error: dict[str, JsonValue] | None = None
    result: dict[str, JsonValue] | None = None
    stage_effect: StageEffect | None = None
    bootstrap_grant: BootstrapGrant | None = None
    checkpoint_observation: CheckpointObservation | None = None
    stage_data: dict[str, JsonValue] | None = None


class RecipeRunRecord(RecipeModel):
    schema_version: Literal[1] = 1
    run_id: str
    plan_id: str
    plan_digest: Sha256
    authorization_id: str
    idempotency_key: str
    owner_host_instance_id: str
    lease_epoch: PositiveInt
    seq: NonnegativeInt = 0
    state: RunState = "queued"
    blocked_reason: str | None = None
    cancel_requested: bool = False
    created_at: float
    updated_at: float
    deadline: float
    current_step_id: str | None = None
    current_binding: SourceBinding | None = None
    derived_targets: tuple[DerivedTargetMapping, ...] = ()
    budgets_used: BudgetUsage = Field(default_factory=BudgetUsage)
    steps: tuple[StepRecord, ...]
    artifacts: tuple[ArtifactRef, ...] = ()
    quality: Literal["pass", "fail", "unverified", "not_applicable"] = "unverified"
    export: Literal["not_requested", "staged", "validated", "published", "failed", "outcome_unknown"] = "not_requested"
    mac: str = ""


def run_view(run: RecipeRunRecord, after_seq: int | None = None) -> dict[str, Any]:
    workflow = ("outcome_unknown" if run.blocked_reason == "outcome_unknown" else "waiting") if run.state == "blocked" else run.state
    outcomes = {step.execution_outcome for step in run.steps}
    execution = ("outcome_unknown" if "outcome_unknown" in outcomes else "failed_after_dispatch"
                 if "failed_after_dispatch" in outcomes else "succeeded" if "succeeded" in outcomes
                 else "canceled_pre_dispatch" if run.state == "canceled" else "not_dispatched")
    return {
        **run.model_dump(mode="json"), "ok": run.state == "succeeded", "workflow": workflow,
        "run_state": run.state, "execution": execution,
        "unchanged": after_seq is not None and after_seq >= run.seq,
    }
