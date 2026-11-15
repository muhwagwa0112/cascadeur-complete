"""Local, journaled publication of already validated sealed export bytes."""

from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from pathlib import Path

from .export_models import ArtifactRef, PublishPermit, ValidationBundle
from .fbx_validation import file_sha256


class ExportPublicationError(RuntimeError):
    def __init__(self, code: str, detail: str):
        self.code = code
        super().__init__(f"{code}: {detail}")


def canonical_digest(value) -> str:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def write_immutable_json(path: Path, payload: dict) -> None:
    """Create an owned record once, with no overwrite or partially visible JSON."""
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, sort_keys=True, separators=(",", ":"), allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)
        _flush_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def _flush_directory(path: Path) -> None:
    # Windows has no portable stdlib directory-fsync primitive. File buffers are
    # flushed before atomic publication; power-loss durability is not asserted.
    if os.name != "nt":
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def copy_exclusive(source: Path, destination: Path, *, max_bytes: int,
                   expected_sha256: str | None = None) -> ArtifactRef:
    digest, count = hashlib.sha256(), 0
    created = False
    try:
        with source.open("rb") as reader, destination.open("xb") as writer:
            created = True
            while block := reader.read(1024 * 1024):
                count += len(block)
                if count > max_bytes:
                    raise ExportPublicationError("OUTPUT_BUDGET_EXCEEDED", "Artifact exceeded output byte budget")
                writer.write(block)
                digest.update(block)
            writer.flush()
            os.fsync(writer.fileno())
        actual = digest.hexdigest()
        if expected_sha256 is not None and actual != expected_sha256:
            raise ExportPublicationError("ARTIFACT_CHANGED", "Copied bytes do not match validated artifact")
        if os.path.samestat(source.stat(), destination.stat()):
            raise ExportPublicationError("ARTIFACT_IDENTITY_CONFLICT", "Sealed and published artifact must be separate inodes")
        return ArtifactRef(path=str(destination), sha256=actual, bytes=count)
    except Exception:
        if created:
            destination.unlink(missing_ok=True)
        raise


def _identity(path: Path) -> dict:
    value = path.stat()
    return {"device": value.st_dev, "inode": value.st_ino, "bytes": value.st_size}


def _validate_permit(artifact: ArtifactRef, bundle: ValidationBundle, permit: PublishPermit) -> Path:
    if time.time() >= permit.expires_at:
        raise ExportPublicationError("AUTHORIZATION_EXPIRED", "Publication authorization expired")
    if artifact.sha256 != permit.artifact_sha256 or artifact.sha256 != bundle.artifact_sha256:
        raise ExportPublicationError("ARTIFACT_PERMISSION_MISMATCH", "Artifact is outside publication permission")
    if permit.profile_digest != bundle.profile_digest:
        raise ExportPublicationError("PROFILE_PERMISSION_MISMATCH", "Validation and publication profile differ")
    if permit.overwrite_mode == "replace_path":
        if permit.overwrite_semantics != "replace_any_current_content":
            raise ExportPublicationError("OVERWRITE_NOT_AUTHORIZED", "Replacement semantics were not explicitly authorized")
    elif permit.overwrite_semantics != "none":
        raise ExportPublicationError("OVERWRITE_NOT_AUTHORIZED", "No-clobber permission contains replacement semantics")
    destination = Path(permit.destination)
    if not destination.is_absolute() or destination.is_symlink() or not destination.parent.is_dir():
        raise ExportPublicationError("DESTINATION_INVALID", "Publication requires an exact local regular-file destination")
    destination = destination.parent.resolve() / destination.name
    if str(destination) != permit.destination:
        raise ExportPublicationError("DESTINATION_CHANGED", "Permission must name the resolved exact destination")
    if destination == Path(artifact.path).resolve():
        raise ExportPublicationError("DESTINATION_INVALID", "Retained evidence cannot be the published destination")
    if artifact.bytes <= 0 or Path(artifact.path).stat().st_size != artifact.bytes:
        raise ExportPublicationError("ARTIFACT_CHANGED", "Sealed artifact size changed")
    if file_sha256(artifact.path, artifact.bytes) != artifact.sha256:
        raise ExportPublicationError("ARTIFACT_CHANGED", "Sealed artifact bytes changed")
    return destination


def publish_verified(artifact: ArtifactRef, validation_bundle: ValidationBundle,
                     permit: PublishPermit, *, journal_directory: str | Path | None = None) -> dict:
    """Publish exact validated bytes once. Repeated calls reconcile an existing intent.

    This internal API consumes a recipe-validated permit. It is not exposed as an
    unscoped MCP file-writing tool.
    """
    artifact = ArtifactRef.model_validate(artifact)
    validation_bundle = ValidationBundle.model_validate(validation_bundle)
    permit = PublishPermit.model_validate(permit)
    destination = _validate_permit(artifact, validation_bundle, permit)
    journal = Path(journal_directory) if journal_directory else Path(artifact.path).parent
    journal = journal.resolve()
    journal.mkdir(parents=True, exist_ok=True)
    key = canonical_digest({"run_id": permit.run_id, "step_id": permit.step_id,
                            "authorization_digest": permit.authorization_digest})[:32]
    intent_path = journal / f"publish-{key}.intent.json"
    if intent_path.exists():
        return reconcile_publish(intent_path, expected_permit=permit)
    claim = journal / f"publish-{key}.claim"
    try:
        descriptor = os.open(claim, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        if intent_path.exists():
            return reconcile_publish(intent_path, expected_permit=permit)
        return {"status": "outcome_unknown", "reason": "publish_owner_unresolved", "intent_path": str(intent_path)}
    os.close(descriptor)
    temporary = destination.parent / f".{destination.name}.{uuid.uuid4().hex}.publish"
    copy_exclusive(Path(artifact.path), temporary, max_bytes=artifact.bytes, expected_sha256=artifact.sha256)
    intent = {"schema_version": 1, "run_id": permit.run_id, "step_id": permit.step_id,
              "artifact_sha256": artifact.sha256, "artifact_path": artifact.path,
              "artifact_bytes": artifact.bytes,
              "publish_temp": str(temporary), "publish_temp_identity": _identity(temporary),
              "destination": str(destination), "overwrite_mode": permit.overwrite_mode,
              "overwrite_semantics": permit.overwrite_semantics,
              "authorization_digest": permit.authorization_digest, "permit_digest": canonical_digest(permit),
              "validation_digest": canonical_digest(validation_bundle), "created_at": time.time()}
    write_immutable_json(intent_path, intent)
    # Recheck after copy and immediately before the atomic operation.
    if time.time() >= permit.expires_at:
        return {"status": "failed", "reason": "authorization_expired", "intent_path": str(intent_path)}
    try:
        if permit.overwrite_mode == "replace_path":
            os.replace(temporary, destination)
        else:
            os.link(temporary, destination)
            temporary.unlink()
        _flush_directory(destination.parent)
    except FileExistsError:
        return {"status": "failed", "reason": "destination_exists", "intent_path": str(intent_path)}
    except OSError as exc:
        # Never emulate no-replace with exists()+replace() or copy/delete.
        return {"status": "outcome_unknown", "reason": "atomic_publish_not_confirmed",
                "os_error": exc.errno, "intent_path": str(intent_path)}
    result = reconcile_publish(intent_path, expected_permit=permit)
    if result["status"] == "published":
        receipt_path = intent_path.with_name(intent_path.name.replace(".intent.json", ".published.json"))
        if not receipt_path.exists():
            write_immutable_json(receipt_path, result)
    return result


def reconcile_publish(intent_path: str | Path, *, expected_permit: PublishPermit | None = None) -> dict:
    path = Path(intent_path)
    if path.stat().st_size > 65536:
        raise ExportPublicationError("PUBLISH_INTENT_INVALID", "Publish intent exceeds budget")
    intent = json.loads(path.read_text(encoding="utf-8"))
    if expected_permit is not None and intent.get("permit_digest") != canonical_digest(expected_permit):
        raise ExportPublicationError("PUBLISH_INTENT_CONFLICT", "Existing intent belongs to another permission")
    destination = Path(intent["destination"])
    if not destination.is_file() or destination.is_symlink():
        return {"status": "outcome_unknown", "reason": "destination_not_observed", "intent_path": str(path)}
    if destination.stat().st_size != intent["artifact_bytes"] or file_sha256(destination, intent["artifact_bytes"]) != intent["artifact_sha256"]:
        return {"status": "blocked", "reason": "destination_content_conflict", "intent_path": str(path)}
    observed = _identity(destination)
    original = intent["publish_temp_identity"]
    if observed["device"] != original["device"] or observed["inode"] != original["inode"]:
        return {"status": "blocked", "reason": "destination_identity_conflict", "intent_path": str(path)}
    return {"status": "published", "destination": str(destination), "artifact_sha256": intent["artifact_sha256"],
            "artifact_path": intent["artifact_path"], "run_id": intent["run_id"], "step_id": intent["step_id"],
            "intent_path": str(path), "observed_at": time.time(), "identity": observed,
            "durability": "file_buffers_flushed_atomic_namespace"}
