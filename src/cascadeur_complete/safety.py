from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import stat
import threading
import time
from contextlib import suppress
from pathlib import Path, PureWindowsPath
from typing import Any

from .atomic_queue import atomic_write_json, read_json
from .models import ChangeToken, Operation
from .paths import RuntimePaths


class SafetyError(ValueError):
    pass


def _absolute_local_path(
    value: str, *, allow_unc_paths: bool = False, allow_device_paths: bool = False
) -> Path:
    raw = value.strip()
    lowered = raw.lower()
    if not raw:
        raise SafetyError("Path is empty")
    if lowered.startswith(("\\\\?\\", "\\\\.\\")) and not allow_device_paths:
        raise SafetyError("Windows device paths are disabled")
    if raw.startswith("\\\\") and not allow_unc_paths:
        raise SafetyError("UNC paths are disabled")
    if re.match(r"^[A-Za-z]:", raw) and ":" in raw[2:]:
        raise SafetyError("NTFS alternate data streams are disabled")
    path = Path(PureWindowsPath(raw))
    if not path.is_absolute():
        raise SafetyError("An absolute local path is required")
    resolved = path.resolve(strict=False)
    canonical = str(resolved)
    canonical_lower = canonical.lower()
    if canonical_lower.startswith(("\\\\?\\", "\\\\.\\")) and not allow_device_paths:
        raise SafetyError("Resolved target is a Windows device path")
    if canonical.startswith("\\\\") and not allow_unc_paths:
        raise SafetyError("Resolved target is a UNC path")
    return resolved


def validate_local_input_path(
    value: str, *, allow_unc_paths: bool = False, allow_device_paths: bool = False
) -> Path:
    resolved = _absolute_local_path(
        value, allow_unc_paths=allow_unc_paths, allow_device_paths=allow_device_paths
    )
    if not resolved.is_file():
        raise SafetyError("Input file does not exist")
    return resolved


def validate_local_path(
    value: str,
    *,
    allow_overwrite: bool = False,
    allow_unc_paths: bool = False,
    allow_device_paths: bool = False,
) -> Path:
    resolved = _absolute_local_path(
        value, allow_unc_paths=allow_unc_paths, allow_device_paths=allow_device_paths
    )
    if resolved.exists() and not allow_overwrite:
        raise SafetyError("Existing destination requires explicit overwrite confirmation")
    return resolved


class ChangeManager:
    def __init__(self, paths: RuntimePaths, secret: bytes | None = None):
        self.paths = paths
        paths.ensure()
        self._secret = secret or self._load_or_create_secret()

    def _load_or_create_secret(self) -> bytes:
        secret_path = self.paths.confirmation_key
        if secret_path.is_file():
            value = secret_path.read_bytes()
            if len(value) < 32:
                raise SafetyError("Confirmation key is invalid")
            return value
        value = secrets.token_bytes(32)
        try:
            descriptor = os.open(secret_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            value = secret_path.read_bytes()
        else:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(value)
                stream.flush()
                os.fsync(stream.fileno())
        with suppress(OSError):
            os.chmod(secret_path, stat.S_IRUSR | stat.S_IWUSR)
        return value

    @staticmethod
    def _approval_payload(record: ChangeToken) -> dict[str, Any]:
        return {
            "schema_version": record.schema_version,
            "feature_id": record.feature_id,
            "scene_id": record.scene_id,
            "scene_revision": record.scene_revision,
            "selection_fingerprint": record.selection_fingerprint,
            "operation": record.operation.model_dump(mode="json"),
            "impact": record.impact,
            "backup_path": record.backup_path,
            "expires_at": record.expires_at,
        }

    def _signature(self, nonce: str, record: ChangeToken) -> str:
        canonical = json.dumps(
            self._approval_payload(record),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        message = f"cascadeur-complete-change-v2:{nonce}:".encode() + canonical.encode("utf-8")
        return hmac.new(self._secret, message, hashlib.sha256).hexdigest()

    @staticmethod
    def _parts(token: str) -> tuple[str, str]:
        try:
            nonce, signature = token.split(".", 1)
        except ValueError as exc:
            raise SafetyError("Malformed confirmation token") from exc
        if not re.fullmatch(r"[A-Za-z0-9_-]{20,64}", nonce) or not re.fullmatch(r"[0-9a-f]{64}", signature):
            raise SafetyError("Malformed confirmation token")
        return nonce, signature

    def _verify_record(self, nonce: str, signature: str, path: Path) -> ChangeToken:
        record = ChangeToken.model_validate(read_json(path))
        if record.token != f"{nonce}.{signature}":
            raise SafetyError("Confirmation token record does not match token")
        expected = self._signature(nonce, record)
        if not hmac.compare_digest(signature, expected):
            raise SafetyError("Invalid confirmation token signature")
        if record.used:
            raise SafetyError("Confirmation token was already used")
        if record.expires_at < time.time():
            raise SafetyError("Confirmation token expired")
        return record

    def prepare(
        self,
        *,
        feature_id: str,
        scene_id: str | None,
        scene_revision: str | None,
        selection_fingerprint: str | None,
        operation: Operation,
        impact: dict[str, Any],
        backup_path: str | None,
        ttl: float = 300.0,
    ) -> ChangeToken:
        nonce = secrets.token_urlsafe(24)
        expires_at = time.time() + min(max(ttl, 30.0), 1800.0)
        record = ChangeToken(
            token="",
            feature_id=feature_id,
            scene_id=scene_id,
            scene_revision=scene_revision,
            selection_fingerprint=selection_fingerprint,
            operation=operation,
            impact=impact,
            backup_path=backup_path,
            expires_at=expires_at,
        )
        token_value = f"{nonce}.{self._signature(nonce, record)}"
        record.token = token_value
        atomic_write_json(self.paths.tokens / f"{nonce}.json", record.model_dump(mode="json"))
        return record

    def load(self, token: str) -> ChangeToken:
        nonce, signature = self._parts(token)
        if (self.paths.seen / f"change-{nonce}").exists():
            raise SafetyError("Confirmation token was already used")
        path = self.paths.tokens / f"{nonce}.json"
        if not path.is_file():
            raise SafetyError("Unknown confirmation token")
        return self._verify_record(nonce, signature, path)

    def consume(
        self, token: str, *, scene_id: str | None, scene_revision: str | None, selection_fingerprint: str | None
    ) -> ChangeToken:
        nonce, signature = self._parts(token)
        record = self.load(token)
        if record.scene_id != scene_id or record.scene_revision != scene_revision:
            raise SafetyError("Scene identity or revision changed after preparation")
        if record.selection_fingerprint != selection_fingerprint:
            raise SafetyError("Selection changed after preparation")
        marker = self.paths.seen / f"change-{nonce}"
        try:
            marker_fd = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError as exc:
            raise SafetyError("Confirmation token was already used") from exc
        else:
            with os.fdopen(marker_fd, "w", encoding="ascii") as stream:
                stream.write(f"{os.getpid()}:{threading.get_ident()}:{time.time():.6f}\n")
                stream.flush()
                os.fsync(stream.fileno())
        source = self.paths.tokens / f"{nonce}.json"
        claimed = self.paths.tokens / f"{nonce}.claimed"
        try:
            os.replace(source, claimed)
        except FileNotFoundError as exc:
            raise SafetyError("Confirmation token was already claimed") from exc
        try:
            record = self._verify_record(nonce, signature, claimed)
            if record.scene_id != scene_id or record.scene_revision != scene_revision:
                raise SafetyError("Scene identity or revision changed during token claim")
            if record.selection_fingerprint != selection_fingerprint:
                raise SafetyError("Selection changed during token claim")
            record.used = True
            record.used_at = time.time()
            atomic_write_json(self.paths.tokens / f"{nonce}.used", record.model_dump(mode="json"))
            return record
        finally:
            claimed.unlink(missing_ok=True)

    def cancel(self, token: str) -> bool:
        nonce, _signature = self._parts(token)
        path = self.paths.tokens / f"{nonce}.json"
        if not path.is_file():
            return False
        path.unlink()
        return True
