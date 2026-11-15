"""Typed declaration lowering and runtime observations for finite recipe stages.

These DTOs describe evidence. Authenticity is checked against the request ledger
and source attestor; supplying a DTO never grants native access.
"""
from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, StrictInt, model_validator

from .models import SourceBinding
from .request_ledger import canonical_digest

Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Identifier = Annotated[str, Field(min_length=1, max_length=256, pattern=r"^[^\x00-\x1f*?]+$")]


class StageModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class FileManifest(StageModel):
    schema_version: Literal[1] = 1
    path: str
    sha256: Sha256
    length: Annotated[StrictInt, Field(ge=0)]

    @model_validator(mode="after")
    def local_path(self):
        if not Path(self.path).is_absolute():
            raise ValueError("File manifest needs an absolute path")
        return self


class DerivedTargetRef(StageModel):
    producer_step_id: Identifier
    selector_kind: Literal["role_path"] = "role_path"
    role_paths: dict[str, str]
    expected_character_count: Literal[1] = 1
    ownership_rule: Literal["producer_created_character"] = "producer_created_character"
    topology_policy_digest: Sha256

    @model_validator(mode="after")
    def exact_selectors(self):
        if not self.role_paths or any(not value or "*" in value or "?" in value for value in self.role_paths.values()):
            raise ValueError("Derived targets require exact unique role/path selectors")
        if len(set(self.role_paths.values())) != len(self.role_paths):
            raise ValueError("Derived role paths must be unique")
        return self


class DerivedTargetMapping(StageModel):
    reference_digest: Sha256
    producer_request_id: str
    producer_receipt_digest: Sha256
    character_id: Identifier
    root_id: Identifier
    role_ids: dict[str, Identifier]
    object_ids: tuple[Identifier, ...]
    layer_ids: tuple[Identifier, ...]
    ownership_digest: Sha256
    topology_digest: Sha256
    rig_profile: dict[str, JsonValue]
    rig_profile_digest: Sha256
    source_binding: SourceBinding

    @model_validator(mode="after")
    def exact_mapping(self):
        if (not self.object_ids or len(set(self.object_ids)) != len(self.object_ids)
                or self.root_id not in self.object_ids or not set(self.role_ids.values()) <= set(self.object_ids)
                or canonical_digest(self.rig_profile) != self.rig_profile_digest):
            raise ValueError("Derived target mapping is incomplete or inconsistent")
        return self


class BootstrapGrant(StageModel):
    schema_version: Literal[1] = 1
    grant_id: str
    authorization_id: str
    authorization_digest: Sha256
    plan_digest: Sha256
    declaration_digest: Sha256
    run_id: str
    step_id: str
    attempt_id: str
    lease_epoch: Annotated[StrictInt, Field(gt=0)]
    request_id: str
    operation_name: str
    arguments_digest: Sha256
    source_binding: SourceBinding | None = None
    input_file: FileManifest | None = None
    output_paths: tuple[str, ...]
    runtime_epoch: str
    adapter_fingerprint: str
    application_build: str
    expires_at: float
    mac: str

    @model_validator(mode="after")
    def initial_only(self):
        if self.source_binding is None and self.input_file is None:
            raise ValueError("Bootstrap needs an initial complete source or exact file")
        if self.source_binding is not None and not self.source_binding.complete:
            raise ValueError("Bootstrap initial source must be complete")
        if self.operation_name not in {"safety.bootstrap", "scene.open", "io.import_fbx"}:
            raise ValueError("Bootstrap grant cannot authorize a general mutation")
        if not self.output_paths or any(not Path(path).is_absolute() for path in self.output_paths):
            raise ValueError("Bootstrap must own explicit new paths")
        return self


class StageEffect(StageModel):
    schema_version: Literal[1] = 1
    step_id: str
    declaration_digest: Sha256
    lowering_rule_id: str
    lowering_rule_digest: Sha256
    feature_id: str
    operation_name: str
    effect_class: Literal["none", "evaluation", "scene", "file", "mixed"]
    arguments: dict[str, JsonValue]
    arguments_digest: Sha256
    operation_digest: Sha256
    effect_bounds_digest: Sha256
    source_binding: SourceBinding | None = None
    input_files: tuple[FileManifest, ...] = ()
    output_paths: tuple[str, ...] = ()
    target_object_ids: tuple[str, ...] = ()
    target_layer_ids: tuple[str, ...] = ()
    derived_mapping_digest: Sha256 | None = None
    expected_successor: Literal["same_instance", "working_clone", "new_instance"] = "same_instance"

    @model_validator(mode="after")
    def exact_effect(self):
        if canonical_digest(self.arguments) != self.arguments_digest:
            raise ValueError("Lowered argument digest mismatch")
        operations = [{"name": self.operation_name, "arguments": self.arguments}]
        if canonical_digest(operations) != self.operation_digest:
            raise ValueError("Lowered operation digest mismatch")
        if len(set(self.target_object_ids)) != len(self.target_object_ids):
            raise ValueError("Duplicate lowered target")
        return self


class CheckpointObservation(StageModel):
    schema_version: Literal[1] = 1
    request_id: str
    run_id: str
    step_id: str
    attempt_id: str
    lease_epoch: Annotated[StrictInt, Field(gt=0)]
    operation_digest: Sha256
    receipt_digest: Sha256
    completion: Literal["native_observed"]
    checkpoint: FileManifest
    working_file: FileManifest
    project_load: dict[str, JsonValue] | None = None
    source_before: SourceBinding | None
    source_after: SourceBinding
    parent_scene_instance_id: str | None
    working_scene_instance_id: str
    document_lineage_id: str
    authored_digest: Sha256
    sample_digest: Sha256

    @model_validator(mode="after")
    def successor_identity(self):
        binding = self.source_after.binding
        if (not self.source_after.complete or binding.scene_instance_id != self.working_scene_instance_id
                or binding.document_lineage_id != self.document_lineage_id
                or Path(self.checkpoint.path).resolve() == Path(self.working_file.path).resolve()):
            raise ValueError("Checkpoint has no isolated authenticated successor")
        return self
