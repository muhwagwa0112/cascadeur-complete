"""Native export staging, sealing and the independent validation gates."""

from __future__ import annotations

import re
import json
import os
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

    def as_dict(self):
        return {key: str(value) if isinstance(value, Path) else value for key, value in vars(self).items()}

    @classmethod
    def from_dict(cls, value):
        stage = cls(**{key: Path(item) if key in ('directory', 'raw_path', 'sealed_path') else item for key, item in value.items()})
        if not stage.directory.is_absolute() or stage.directory.is_symlink():
            raise ExportPublicationError('EXPORT_STAGE_MISMATCH', 'Stage must be an owned absolute directory')
        record = json.loads((stage.directory / 'stage.json').read_text(encoding='utf-8'))
        if (stage.raw_path != stage.directory / 'raw.fbx' or stage.sealed_path != stage.directory / 'sealed.fbx'
                or any(record.get(key) != getattr(stage, key) for key in ('profile_digest', 'run_id', 'step_id'))
                or record.get('raw_path') != str(stage.raw_path) or record.get('sealed_path') != str(stage.sealed_path)):
            raise ExportPublicationError('EXPORT_STAGE_MISMATCH', 'Persisted stage identity differs')
        return stage


def bind_export_stage(stage: ExportStage, *, request_id, attempt_id, lease_epoch, operation_name,
                      arguments, source_binding):
    """Bind only after the raw pathname is present in the final native arguments."""
    source = source_binding.model_dump(mode='json') if hasattr(source_binding, 'model_dump') else source_binding
    if not request_id or not attempt_id or type(lease_epoch) is not int or lease_epoch < 0 or not source:
        raise ValueError('Complete dispatch and scene source identities are required')
    def paths(value):
        if isinstance(value, dict):
            return any(paths(item) for item in value.values())
        if isinstance(value, (list, tuple)):
            return any(paths(item) for item in value)
        return isinstance(value, str) and value == str(stage.raw_path)
    if not paths(arguments):
        raise ValueError('Final native arguments must contain the exact stage raw pathname')
    operations = [{'name': operation_name, 'arguments': arguments}]
    payload = {'schema_version': 1, **stage.as_dict(), 'request_id': request_id, 'attempt_id': attempt_id,
               'lease_epoch': lease_epoch, 'operation_name': operation_name,
               'operation_digest': canonical_digest(operations), 'arguments': arguments,
               'source_binding': source}
    path = stage.directory / 'stage-dispatch.json'
    if path.exists():
        if json.loads(path.read_text(encoding='utf-8')) != payload:
            raise ExportPublicationError('EXPORT_STAGE_REBOUND', 'Stage dispatch binding is immutable')
    else:
        write_immutable_json(path, payload)
    return payload


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
            or receipt.get('dispatched') is not True or receipt.get('write_phase') != 'completed'
            or not terminal.get("ok") or native.get("native_completion") != "observed"):
        raise ExportPublicationError("NATIVE_EXPORT_COMPLETION_UNVERIFIED", "Dispatch or file existence is not completion")
    binding = json.loads((stage.directory / 'stage-dispatch.json').read_text(encoding='utf-8'))
    if (any(receipt.get(key) != binding[key] for key in ('request_id', 'run_id', 'step_id', 'attempt_id', 'lease_epoch', 'operation_digest'))
            or receipt.get('scene_before') != binding['source_binding'].get('binding', binding['source_binding'])):
        raise ExportPublicationError("EXPORT_RECEIPT_MISMATCH", "Receipt belongs to another export stage")
    source = binding['source_binding']
    scope = source.get('scope', {})
    if scope.get('adapter_id') == 'native-selected-export-v1':
        observation = native.get('completion_observation')
        transition = native.get('selection_transition')
        if (not isinstance(observation, dict) or not isinstance(transition, dict)
                or observation.get('selection_transition') != transition
                or canonical_digest(observation) != native.get('completion_observation_digest')
                or transition.get('policy') != 'temporary_empty_selection_observed_restore'
                or transition.get('status') != 'observed_restored'
                or transition.get('policy') != scope.get('export_selection_policy')
                or transition.get('before') != scope.get('export_selection_before')
                or transition.get('after') != transition.get('before')
                or transition.get('before', {}).get('ids') != []
                or transition.get('export_selected_ids') != scope.get('export_selected_ids')
                or transition.get('during', {}).get('ids') != scope.get('export_selected_ids')
                or transition.get('authored_projection_before_digest') != source.get('sample_digest')
                or transition.get('authored_projection_after_digest') != source.get('sample_digest')):
            raise ExportPublicationError('EXPORT_SELECTION_RESTORATION_UNVERIFIED',
                'Native receipt must preserve the bound empty selector/pivot observations and full authored source')
    maximum = budget.get("output_bytes") if isinstance(budget, dict) else getattr(budget, "output_bytes", None)
    if type(maximum) is not int or maximum <= 0:
        raise ValueError("An explicit positive output_bytes budget is required")
    if stage.raw_path.is_symlink() or stage.directory.is_symlink():
        raise ExportPublicationError('EXPORT_STAGE_MISMATCH', 'Raw export must be owned by its stage')
    if (native.get('export_profile_digest') != stage.profile_digest or native.get('raw_path') != str(stage.raw_path)
            or type(native.get('artifact_bytes')) is not int or not 0 < native['artifact_bytes'] <= maximum
            or not re.fullmatch(r'[a-f0-9]{64}', str(native.get('artifact_sha256', '')))):
        raise ExportPublicationError('EXPORT_COMPLETION_IDENTITY_MISMATCH', 'Native completion lacks exact profile/path/bytes identity')
    artifact = ArtifactRef(path=str(stage.sealed_path), sha256=native['artifact_sha256'], bytes=native['artifact_bytes'])
    metadata = {'artifact': artifact.model_dump(mode='json'), 'receipt_digest': canonical_digest(receipt),
                'profile_digest': stage.profile_digest, 'dispatch_digest': canonical_digest(binding)}
    sealed_record = stage.directory / 'sealed.json'
    if sealed_record.exists() and json.loads(sealed_record.read_text(encoding='utf-8')) != metadata:
        raise ExportPublicationError('EXPORT_SEAL_REBOUND', 'Sealed receipt identity differs')
    if stage.sealed_path.exists():
        if (stage.sealed_path.is_symlink() or stage.sealed_path.stat().st_size != artifact.bytes
                or file_sha256(stage.sealed_path, maximum) != artifact.sha256
                or (stage.raw_path.exists() and os.path.samestat(stage.raw_path.stat(), stage.sealed_path.stat()))):
            raise ExportPublicationError('ARTIFACT_CHANGED', 'Existing retained artifact differs from native completion')
    else:
        copied = copy_exclusive(stage.raw_path, stage.sealed_path, max_bytes=maximum, expected_sha256=artifact.sha256)
        if copied.bytes != artifact.bytes:
            raise ExportPublicationError('ARTIFACT_CHANGED', 'Native completion byte count differs')
    if artifact.bytes == 0:
        raise ExportPublicationError("EMPTY_EXPORT", "Native exporter produced an empty artifact")
    if not sealed_record.exists():
        write_immutable_json(sealed_record, metadata)
    return artifact


def validate_export(artifact: ArtifactRef, profile: ExportProfile, expected: ExportExpectation,
                    *, target_validator=None, roundtrip_validator=None, parse_limits: ParseLimits | None = None,
                    timeout: float = 240, cancel=None, quality_context=None, provenance_key=None) -> dict:
    if file_sha256(artifact.path, artifact.bytes) != artifact.sha256:
        raise ExportPublicationError("ARTIFACT_CHANGED", "Sealed export changed before validation")
    if expected.settings_digest != canonical_digest(profile):
        raise ExportPublicationError("EXPORT_EXPECTATION_STALE", "Expected capture refers to another export profile")
    retained = Path(artifact.path).parent / 'validated.json'
    if retained.exists():
        from .external import blender_export_adapter_fingerprint
        if (profile.target_adapter != 'blender_fbx_classic_v1'
                or profile.target_adapter_fingerprint != blender_export_adapter_fingerprint()
                or profile.target_import_settings is None
                or canonical_digest(profile.target_import_settings) != profile.target_import_settings_digest):
            raise ExportPublicationError('EXPORT_VALIDATION_STALE', 'Retained validation is not bound to this installed decoder')
        from .target_capture import TargetCaptureEvidence, evaluate_target_capture
        from .motion_context import SampleBatch
        bundle = ValidationBundle.model_validate_json(retained.read_text(encoding='utf-8'))
        if (bundle.artifact_sha256 != artifact.sha256 or bundle.profile_digest != canonical_digest(profile)
                or bundle.source_capture_digest != expected.source_capture_digest):
            raise ExportPublicationError('EXPORT_VALIDATION_CONFLICT', 'Retained validation belongs to different inputs')
        proof = next((item.get('capture_provenance') for item in bundle.target.checks
                      if item.get('id') == 'original_intent_roundtrip'), None)
        if not proof:
            raise ExportPublicationError('EXPORT_VALIDATION_UNBOUND', 'Legacy validation has no immutable consumer provenance')
        proof = Path(proof)
        directory = proof.parent
        if proof.name != 'capture-provenance.json' or directory.parent != Path(artifact.path).parent or directory.is_symlink():
            raise ExportPublicationError('EXPORT_VALIDATION_UNBOUND', 'Retained provenance is outside this artifact stage')
        evidence = TargetCaptureEvidence(directory, provenance_key)
        batch = SampleBatch.from_dict(json.loads((directory / 'canonical-capture.json').read_text(encoding='utf-8')))
        from .capture import canonical_digest as capture_digest
        if not evidence.verify(batch, capture_digest(batch.as_dict())).ok:
            raise ExportPublicationError('EXPORT_VALIDATION_CHANGED', 'Retained raw/canonical provenance no longer verifies')
        manifest = json.loads((directory / 'manifest.json').read_text(encoding='utf-8'))
        raw = json.loads((directory / 'capture.json').read_text(encoding='utf-8'))['capture']
        quality = evaluate_target_capture(raw, expected, profile, quality_context, directory=directory,
                                          key=provenance_key, report_path=directory / 'capture.json', manifest=manifest)
        if not quality.passed or not quality.runtime_verified:
            return {'export':'staged', 'quality':quality.status, 'quality_report':quality.as_dict()}
        return {'export':'validated', 'quality':'pass', 'validation_bundle':bundle.model_dump(mode='json')}
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
    from .external import validate_target_import
    if target_validator is not None and target_validator is not validate_target_import:
        raise ExportPublicationError('TARGET_VALIDATOR_UNTRUSTED', 'Strict validation requires the installed consumer adapter')
    target_validator = validate_target_import
    target = target_validator(artifact, profile, expected, timeout=timeout, cancel=cancel,
                              quality_context=quality_context, provenance_key=provenance_key)
    target = ValidationReport.model_validate(target)
    if not target.ok:
        return {"export": "staged", "quality": "unverified" if target.status in ("unverified", "unsupported") else "fail",
                "structure": structure.model_dump(mode="json"), "target": target.model_dump(mode="json")}
    if file_sha256(artifact.path, artifact.bytes) != artifact.sha256:
        raise ExportPublicationError("ARTIFACT_CHANGED", "Sealed export changed during target validation")
    bundle = ValidationBundle(artifact_sha256=artifact.sha256, execution="succeeded", quality="pass",
                              structure=structure, target=target, source_capture_digest=expected.source_capture_digest,
                              profile_digest=canonical_digest(profile))
    record = Path(artifact.path).parent / 'validated.json'
    payload = bundle.model_dump(mode='json')
    if record.exists():
        if json.loads(record.read_text(encoding='utf-8')) != payload:
            raise ExportPublicationError('EXPORT_VALIDATION_CONFLICT', 'A different validation is already retained')
    else:
        write_immutable_json(record, payload)
    return {"export": "validated", "quality": "pass", "validation_bundle": bundle.model_dump(mode="json")}
