"""Explicit contracts shared by export planning, validators and publication."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator, model_validator


class ExportModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, frozen=True)


class ArtifactRef(ExportModel):
    path: str
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    bytes: StrictInt = Field(ge=0)
    kind: str = "sealed_fbx"
    schema_version: Literal[1] = 1


class ExportBoneMap(ExportModel):
    role: str
    node_path: str
    parent_path: str | None = None
    source_id: str
    rest_length_m: float | None = Field(default=None, gt=0)


class ChannelSpec(ExportModel):
    node_path: str
    property: Literal["Lcl Translation", "Lcl Rotation", "Lcl Scaling"]
    axis: Literal["X", "Y", "Z"]
    animated: bool
    constant_value: float | None = None


class AxisConvention(ExportModel):
    up_axis: StrictInt = Field(ge=0, le=2)
    up_sign: Literal[-1, 1]
    front_axis: StrictInt = Field(ge=0, le=2)
    front_sign: Literal[-1, 1]
    coord_axis: StrictInt = Field(ge=0, le=2)
    coord_sign: Literal[-1, 1]

    @model_validator(mode="after")
    def orthogonal(self):
        if len({self.up_axis, self.front_axis, self.coord_axis}) != 3:
            raise ValueError("Export axes must be an orthogonal signed permutation")
        return self


class RootMotionProfile(ExportModel):
    node_path: str
    mode: Literal["preserve_world", "in_place", "extract_to_root"] = "preserve_world"
    translation_axes: tuple[Literal["X", "Y", "Z"], ...] = ("X", "Y", "Z")
    preserve_yaw: bool = True


class ExportTolerances(ExportModel):
    position_m: float = Field(default=0.0005, gt=0)
    rotation_rad: float = Field(default=math.pi / 1800, gt=0)
    bone_length_m: float = Field(default=0.0005, gt=0)
    ticks: StrictInt = Field(default=1, ge=0)
    fps_relative: float = Field(default=1e-8, ge=0)


class TargetImportSettings(ExportModel):
    """A pinned adapter's exact mapping, not an importer-name guessing rule."""

    blender_version: tuple[StrictInt, StrictInt, StrictInt]
    anim_offset: float = 1
    blender_to_canonical_basis: tuple[tuple[float, float, float], ...]
    bone_mapping: dict[str, tuple[str, str | None]]
    helper_mapping: dict[str, str] = Field(default_factory=dict)
    mesh_mapping: dict[str, str] = Field(default_factory=dict)
    blender_executable_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    importer_fingerprint: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    max_report_bytes: StrictInt = Field(default=64 * 1024**2, gt=0, le=256 * 1024**2)
    max_log_bytes: StrictInt = Field(default=4 * 1024**2, gt=0, le=16 * 1024**2)

    @model_validator(mode="after")
    def proper_basis(self):
        import numpy as np
        basis = np.asarray(self.blender_to_canonical_basis, dtype=float)
        if basis.shape != (3, 3) or not np.allclose(basis.T @ basis, np.eye(3), atol=1e-10) or not np.isclose(np.linalg.det(basis), 1):
            raise ValueError("Target decoder needs an explicit proper canonical basis")
        return self


class ExportProfile(ExportModel):
    schema_version: Literal[1] = 1
    character_ref: str
    skeleton_map: tuple[ExportBoneMap, ...]
    allowed_helper_nodes: tuple[str, ...] = ()
    include_mesh: bool = False
    mesh_refs: tuple[str, ...] = ()
    take_name: str
    first_frame: StrictInt
    last_frame: StrictInt
    max_samples: StrictInt = Field(default=1_000_000, gt=0, le=10_000_000)
    fps_num: StrictInt = Field(gt=0)
    fps_den: StrictInt = Field(default=1, gt=0)
    time_origin: Literal["preserve", "zero"] = "preserve"
    axes: AxisConvention
    metres_per_export_unit: float = Field(gt=0)
    bake: Literal["dense", "sparse_equivalent"] = "dense"
    required_channels: tuple[ChannelSpec, ...] = ()
    root_motion: RootMotionProfile
    target_adapter: str
    target_adapter_fingerprint: str
    target_import_settings_digest: str
    target_import_settings: TargetImportSettings | None = None
    tolerances: ExportTolerances = Field(default_factory=ExportTolerances)
    destination: str
    overwrite_mode: Literal["fail_if_exists", "replace_path"] = "fail_if_exists"
    overwrite_semantics: Literal["none", "replace_any_current_content"] = "none"
    weights_normalization: Literal["unit_sum", "nonnegative"] = "unit_sum"

    @model_validator(mode="after")
    def coherent(self):
        if self.first_frame > self.last_frame or not self.skeleton_map:
            raise ValueError("Export needs an ordered interval and a nonempty skeleton mapping")
        if self.last_frame - self.first_frame + 1 > self.max_samples:
            raise ValueError("Export interval exceeds declared sample budget")
        for field in ("role", "node_path", "source_id"):
            values = [getattr(bone, field) for bone in self.skeleton_map]
            if len(values) != len(set(values)):
                raise ValueError(f"Duplicate skeleton {field}")
        paths = {bone.node_path for bone in self.skeleton_map} | set(self.allowed_helper_nodes)
        if self.root_motion.node_path not in paths:
            raise ValueError("Root motion node must belong to the export skeleton")
        if any(channel.node_path not in paths for channel in self.required_channels):
            raise ValueError("A required channel is outside the export skeleton")
        if self.include_mesh != bool(self.mesh_refs):
            raise ValueError("Mesh export must declare exact mesh paths")
        if not Path(self.destination).is_absolute():
            raise ValueError("Export destination must be an absolute local path")
        if self.overwrite_mode == "replace_path" and self.overwrite_semantics != "replace_any_current_content":
            raise ValueError("Replacement requires explicit replace_any_current_content semantics")
        if self.overwrite_mode == "fail_if_exists" and self.overwrite_semantics != "none":
            raise ValueError("No-clobber publication cannot contain replacement permission")
        return self


class ExportExpectation(ExportModel):
    """Actual post-cleanup capture, with the original intent kept separately."""

    schema_version: Literal[1] = 1
    source_capture_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    intent_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    quality_policy_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_binding_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    settings_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    reference_digests: dict[str, str] = Field(default_factory=dict)
    time_s: tuple[float, ...]
    position_m: dict[str, tuple[tuple[float, float, float], ...]]
    rotation_delta_wxyz: dict[str, tuple[tuple[float, float, float, float], ...]]
    rest_rotation_wxyz: dict[str, tuple[float, float, float, float]] = Field(default_factory=dict)
    rest_position_m: dict[str, tuple[float, float, float]] = Field(default_factory=dict)
    parent_paths: dict[str, str | None]
    required_metrics: tuple[str, ...]
    runtime_quality: Literal["pass"]

    @model_validator(mode="after")
    def complete(self):
        count = len(self.time_s)
        if not count or any(b <= a for a, b in zip(self.time_s, self.time_s[1:])):
            raise ValueError("Expected capture times must be nonempty and strictly increasing")
        if set(self.position_m) != set(self.rotation_delta_wxyz) or set(self.position_m) != set(self.parent_paths):
            raise ValueError("Expected position/rotation/topology coverage must match")
        if not self.position_m or not self.required_metrics or len(set(self.required_metrics)) != len(self.required_metrics):
            raise ValueError("Expected capture needs targets and unique required quality metrics")
        for rows in (*self.position_m.values(), *self.rotation_delta_wxyz.values()):
            if len(rows) != count or any(not math.isfinite(v) for row in rows for v in row):
                raise ValueError("Expected capture coverage is incomplete or nonfinite")
        for rows in self.rotation_delta_wxyz.values():
            if any(abs(sum(v * v for v in q) - 1) > 0.002 for q in rows):
                raise ValueError("Expected orientation must be a unit quaternion")
        return self


class ValidationReport(ExportModel):
    schema_version: Literal[1] = 1
    status: Literal["pass", "fail", "unverified", "unsupported"]
    artifact_sha256: str
    checks: tuple[dict, ...] = ()
    reason_codes: tuple[str, ...] = ()
    coverage: str = "structure"
    capture: dict | None = None

    @property
    def ok(self) -> bool:
        return self.status == "pass"


class ValidationBundle(ExportModel):
    artifact_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    execution: Literal["succeeded"]
    quality: Literal["pass"]
    structure: ValidationReport
    target: ValidationReport
    source_capture_digest: str
    profile_digest: str

    @model_validator(mode="after")
    def all_pass(self):
        for report in (self.structure, self.target):
            if not report.ok or report.artifact_sha256 != self.artifact_sha256:
                raise ValueError("Publication requires successful validators bound to identical sealed bytes")
        return self


class PublishPermit(ExportModel):
    destination: str
    authorization_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    artifact_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    profile_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    expires_at: float
    run_id: str
    step_id: str
    overwrite_mode: Literal["fail_if_exists", "replace_path"] = "fail_if_exists"
    overwrite_semantics: Literal["none", "replace_any_current_content"] = "none"

    @field_validator("destination")
    @classmethod
    def absolute_destination(cls, value):
        if not Path(value).is_absolute():
            raise ValueError("Publication destination must be absolute")
        return value

