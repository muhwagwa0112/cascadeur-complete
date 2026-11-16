"""PROPOSED project contracts, not installed SDK APIs or evidence issuers.

This .pyi specifies future internal/wire shapes. It is not an implementation,
cannot be imported to issue trusted evidence, and changes no current schema.
"""
from typing import Any, Literal, NotRequired, TypedDict

class GeometryCaptureArguments(TypedDict):
    capture_id: str
    motion_source_binding: dict[str, Any]
    motion_capture_digest: str
    origin_request_id: str
    context: dict[str, Any]
    mesh_ids: list[str]
    pairs: list[list[str]]
    max_calculations: int
    max_array_bytes: int
    max_artifact_bytes: int

class GeometryCandidateResult(TypedDict):
    geometry_capture_id: str
    candidate_digest: str
    request_id: str
    state: Literal["awaiting_terminal_receipt"]

class GeometryWindowV1(TypedDict):
    path: str
    sha256: str
    bytes: int
    frames: list[int]
    position_field: Literal["canonical_positions_m"]
    canonical_metres: Literal[True]
    vertices_shape: list[int]
    raw_vertices_sha256: str
    canonical_vertices_sha256: str
    triangles_shape: list[int]
    triangles_sha256: str

class GeometryManifestV1(TypedDict):
    schema_version: Literal[1]
    capture_kind: Literal["native_actual"]
    geometry_capture_id: str
    source_digest: str
    successor_digest: str
    capture_source_digest: str
    geometry_operation_source_digest: str
    geometry_operation_successor_digest: str
    completion_receipt_digest: str
    origin_completion_receipt_digest: str
    evaluation_receipt_digest: str
    motion_capture_digest: str
    topology_digest: str
    skin_digest: str
    transform_projection_digest: str
    context_digest: str
    frames: list[int]
    time_s: list[float]
    space: Literal["global"]
    units: Literal["metres"]
    windows: dict[str, list[GeometryWindowV1]]
    pairs: list[list[str]]
    coordinate_evidence_digest: str
    synchronous_calculation_evidence_digest: str
    full_projection_digest: str
    runtime_epoch: str
    installed_build: str
    runtime_fingerprint: str
    context_authority: Literal["explicit_declared_conversion_policy"]
    native_physical_metadata_verified: Literal[False]
    orientation_evidence: NotRequired[dict[str, str]]

class SealedGeometryResult(TypedDict):
    manifest: GeometryManifestV1
    geometry_digest: str

class GeometryVerificationResult(TypedDict):
    geometry_digest: str
    completion_receipt_digest: str
    evaluation_receipt_digest: str

class CheckpointManifestV2(TypedDict):
    """Breaking storage/wire proposal; v1 is never silently reinterpreted."""
    schema_version: Literal[2]
    snapshot_id: str
    path: str
    sha256: str
    bytes: int
    checkpoint_anchor_digest: str
    reference_projection_digest: str
    checkpoint_observed_projection_digest: str
    working_path: str
    working_file_sha256: str
    working_file_bytes: int
    working_projection_digest: str
    working_scene_instance_id: str
    document_lineage_id: str
    runtime_epoch: str
    adapter_fingerprint: str
    native_completion: Literal["observed"]
    serialization_policy_digest: str | None
    serialization_observation_digest: str

class ImmutableCheckpointAnchor:
    """Private native object; constructor/issuer deliberately not specified."""
    reference_projection: dict[str, Any]
    reference_projection_digest: str
    checkpoint_observed_projection: dict[str, Any]
    checkpoint_observed_projection_digest: str
    checkpoint_file: dict[str, Any]
    checkpoint_anchor_digest: str
    serialization_policy_digest: str | None
    run_id: str | None

class NativeRestoreObservationV2(TypedDict):
    schema_version: Literal[2]
    checkpoint_anchor_digest: str
    snapshot_manifest_digest: str
    restored_projection_digest: str
    reference_projection_digest: str
    serialization_observation_digest: str
    source_before_digest: str
    source_after_digest: str
    runtime_epoch: str
    runtime_fingerprint: str
    installed_build: str
    recovery_request_id: str
    original_request_id: str
    original_receipt_digest: str
    permit_digest: str
    scene_before: dict[str, str]
    scene_after: dict[str, str]
    working_file: dict[str, Any]
    project_load: dict[str, Any]

