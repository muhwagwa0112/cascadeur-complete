from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field

PROTOCOL_VERSION = "2.0"


class ExecutionMode(StrEnum):
    NATIVE = "Native"
    ACTION = "Action"
    UIA = "UIA"
    EXTERNAL = "External"
    GATED = "Gated"


class CapabilityState(StrEnum):
    AVAILABLE = "available"
    LICENSE_GATED = "license_gated"
    MISSING_DEPENDENCY = "missing_dependency"
    NEEDS_SCENE = "needs_scene"
    UI_ONLY = "ui_only"
    UNSUPPORTED_VERSION = "unsupported_version"
    UNHEALTHY = "unhealthy"
    NOT_IMPLEMENTED = "not_implemented"
    UNSUPPORTED = "unsupported"


class VerificationState(StrEnum):
    DISCOVERED = "discovered"
    CONTRACT = "contract"
    IMPLEMENTED = "implemented"
    VERIFIED_LIVE = "verified_live"
    GATED = "gated"


class ErrorCode(StrEnum):
    CASCADEUR_NOT_RUNNING = "CASCADEUR_NOT_RUNNING"
    SCENE_CHANGED = "SCENE_CHANGED"
    LICENSE_GATED = "LICENSE_GATED"
    DEPENDENCY_MISSING = "DEPENDENCY_MISSING"
    UI_LOCKED = "UI_LOCKED"
    TIMEOUT = "TIMEOUT"
    POSTCONDITION_FAILED = "POSTCONDITION_FAILED"
    UNSUPPORTED_VERSION = "UNSUPPORTED_VERSION"
    INVALID_REQUEST = "INVALID_REQUEST"
    CONFIRMATION_REQUIRED = "CONFIRMATION_REQUIRED"


class Operation(BaseModel):
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class SafetyContext(BaseModel):
    destructive: bool = False
    confirmation_token: str | None = None
    allow_overwrite: bool = False
    snapshot_required: bool = False
    selection_fingerprint: str | None = None


class BridgeRequest(BaseModel):
    protocol_version: str = PROTOCOL_VERSION
    request_id: str
    feature_id: str
    scene_id: str | None = None
    expected_revision: str | None = None
    operations: list[Operation]
    timeout: float = Field(default=30.0, gt=0, le=1800)
    safety_context: SafetyContext = Field(default_factory=SafetyContext)
    created_at: float
    expires_at: float
    session_id: str = ""
    nonce: str = ""
    mac: str = ""


class Evidence(BaseModel):
    kind: str
    detail: str
    observed_at: float


class ResultEnvelope(BaseModel):
    ok: bool
    feature_id: str
    execution_mode: ExecutionMode
    scene_id: str | None = None
    scene_revision: str | None = None
    result: Any = None
    warnings: list[str] = Field(default_factory=list)
    changed_entities: list[str] = Field(default_factory=list)
    snapshot_id: str | None = None
    job_id: str | None = None
    evidence: list[Evidence] = Field(default_factory=list)
    duration_ms: int = 0
    error_code: ErrorCode | None = None
    error_message: str | None = None
    operation_id: str | None = None
    status: str | None = None
    scene_revision_before: str | None = None
    scene_revision_after: str | None = None
    postconditions: list[dict[str, Any]] = Field(default_factory=list)
    evidence_id: str | None = None
    request_id: str | None = None
    session_id: str | None = None
    nonce: str | None = None
    mac: str | None = None


class FeatureRecord(BaseModel):
    id: str
    family: str
    name: str
    description: str
    execution_mode: ExecutionMode
    state: CapabilityState
    route: str
    test_id: str
    test_ids: list[str] = Field(default_factory=list)
    adapter_id: str | None = None
    preconditions: list[str] = Field(default_factory=list)
    postconditions: list[str] = Field(default_factory=list)
    verification: VerificationState = VerificationState.DISCOVERED
    evidence_kind: Literal["none", "schema", "contract", "handler", "live", "gate"] = "none"
    last_verified_version: str | None = None
    requires_scene: bool = True
    destructive: bool = False
    license: Literal["basic", "pro", "any"] = "any"
    dependency: str | None = None
    source: str
    since: str = "2026.1"
    source_url: str | None = None
    public_action: str | None = None
    operation_id: str | None = None
    fixture_id: str | None = None
    mutation: bool = False
    contract_status: Literal["bound", "gate", "not_implemented", "discovered"] = "discovered"
    truth_layer: Literal["product", "discovered"] = "discovered"


class ChangeToken(BaseModel):
    schema_version: int = 2
    token: str
    feature_id: str
    scene_id: str | None
    scene_revision: str | None
    selection_fingerprint: str | None
    operation: Operation
    impact: dict[str, Any]
    backup_path: str | None
    expires_at: float
    used: bool = False
    used_at: float | None = None


class JobRecord(BaseModel):
    job_id: str
    status: Literal["queued", "running", "succeeded", "failed", "canceled"]
    progress: float = Field(default=0, ge=0, le=1)
    feature_id: str
    created_at: float
    updated_at: float
    logs: list[str] = Field(default_factory=list)
    result: ResultEnvelope | None = None
    cancel_requested: bool = False
    owner_pid: int | None = None
    operation_name: str | None = None
    arguments: dict[str, Any] = Field(default_factory=dict)
    scene_id: str | None = None
    expected_revision: str | None = None
    timeout: float = 300
    attempt: int = 1
    retry_of: str | None = None
