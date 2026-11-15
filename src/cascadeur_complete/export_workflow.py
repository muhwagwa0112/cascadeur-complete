"""Native export staging, sealing and the independent validation gates."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from pathlib import Path

from .export_models import ArtifactRef, ExportExpectation, ExportProfile, ValidationBundle, ValidationReport
from .export_publisher import ExportPublicationError, canonical_digest, copy_exclusive, write_immutable_json
from .fbx_validation import FbxError, ParseLimits, file_sha256, read_fbx_structure, validate_fbx_structure


@dataclass(frozen=True)
class ExportStage:
    directory: Path
    raw_path: Path
    sealed_path: Path
    profile_digest: str
    run_id: str
    step_id: str


def create_export_stage(profile: ExportProfile, run_id: str, step_id: str) -> ExportStage:
    for value in (run_id, step_id):
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value):
            raise ValueError("Invalid export run/step identity")
    destination = Path(profile.destination)
    if not destination.parent.is_dir() or destination.is_symlink():
        raise ExportPublicationError("DESTINATION_INVALID", "Destination parent is unavailable or target is a symlink")
    directory = destination.parent.resolve() / f".cascadeur-export-{run_id}-{step_id}-{uuid.uuid4().hex}"
    directory.mkdir()
    stage = ExportStage(directory, directory / "raw.fbx", directory / "sealed.fbx",
                        canonical_digest(profile), run_id, step_id)
    write_immutable_json(directory / "stage.json", {"schema_version": 1, "run_id": run_id, "step_id": step_id,
                         "profile_digest": stage.profile_digest, "raw_path": str(stage.raw_path),
                         "sealed_path": str(stage.sealed_path), "destination": profile.destination})
    return stage


def seal_export(stage: ExportStage, receipt, budget) -> ArtifactRef:
    receipt = receipt.model_dump(mode="json") if hasattr(receipt, "model_dump") else receipt
    terminal = receipt.get("terminal_result") or {}
    native = terminal.get("result") or {}
    if (receipt.get("phase") != "terminal" or receipt.get("outcome") != "succeeded"
            or not terminal.get("ok") or native.get("native_completion") != "observed"):
        raise ExportPublicationError("NATIVE_EXPORT_COMPLETION_UNVERIFIED", "Dispatch or file existence is not completion")
    if receipt.get("run_id") not in (None, stage.run_id) or receipt.get("step_id") not in (None, stage.step_id):
        raise ExportPublicationError("EXPORT_RECEIPT_MISMATCH", "Receipt belongs to another export stage")
    maximum = budget.get("output_bytes") if isinstance(budget, dict) else getattr(budget, "output_bytes", None)
    if type(maximum) is not int or maximum <= 0:
        raise ValueError("An explicit positive output_bytes budget is required")
    artifact = copy_exclusive(stage.raw_path, stage.sealed_path, max_bytes=maximum)
    if artifact.bytes == 0:
        raise ExportPublicationError("EMPTY_EXPORT", "Native exporter produced an empty artifact")
    write_immutable_json(stage.directory / "sealed.json", {"artifact": artifact.model_dump(mode="json"),
                         "receipt_digest": canonical_digest(receipt), "profile_digest": stage.profile_digest})
    return artifact


def validate_export(artifact: ArtifactRef, profile: ExportProfile, expected: ExportExpectation,
                    *, target_validator=None, roundtrip_validator=None, parse_limits: ParseLimits | None = None,
                    timeout: float = 240, cancel=None) -> dict:
    if file_sha256(artifact.path, artifact.bytes) != artifact.sha256:
        raise ExportPublicationError("ARTIFACT_CHANGED", "Sealed export changed before validation")
    if expected.settings_digest != canonical_digest(profile):
        raise ExportPublicationError("EXPORT_EXPECTATION_STALE", "Expected capture refers to another export profile")
    try:
        document = read_fbx_structure(artifact.path, parse_limits)
        if document.sha256 != artifact.sha256:
            raise ExportPublicationError("ARTIFACT_CHANGED", "Structure parse observed different sealed bytes")
        structure = validate_fbx_structure(document, profile, expected)
    except FbxError as exc:
        structure = ValidationReport(status="unsupported" if "UNSUPPORTED" in exc.code else "fail",
                                     artifact_sha256=artifact.sha256, reason_codes=(exc.code,))
    if not structure.ok:
        return {"export": "staged", "quality": "unverified", "structure": structure.model_dump(mode="json")}
    if target_validator is None:
        from .external import validate_target_import
        target_validator = validate_target_import
    target = target_validator(artifact, profile, expected, timeout=timeout, cancel=cancel,
                              roundtrip_validator=roundtrip_validator)
    target = ValidationReport.model_validate(target)
    if not target.ok:
        return {"export": "staged", "quality": "unverified" if target.status in ("unverified", "unsupported") else "fail",
                "structure": structure.model_dump(mode="json"), "target": target.model_dump(mode="json")}
    if file_sha256(artifact.path, artifact.bytes) != artifact.sha256:
        raise ExportPublicationError("ARTIFACT_CHANGED", "Sealed export changed during target validation")
    bundle = ValidationBundle(artifact_sha256=artifact.sha256, execution="succeeded", quality="pass",
                              structure=structure, target=target, source_capture_digest=expected.source_capture_digest,
                              profile_digest=canonical_digest(profile))
    write_immutable_json(Path(artifact.path).parent / "validated.json", bundle.model_dump(mode="json"))
    return {"export": "validated", "quality": "pass", "validation_bundle": bundle.model_dump(mode="json")}
