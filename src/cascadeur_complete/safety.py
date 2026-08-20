from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time
from pathlib import Path, PureWindowsPath
from typing import Any

from .atomic_queue import atomic_write_json, read_json
from .models import ChangeToken, Operation
from .paths import RuntimePaths


class SafetyError(ValueError):
    pass


def _absolute_local_path(value: str) -> Path:
    raw = value.strip()
    lowered = raw.lower()
    if not raw:
        raise SafetyError("Path is empty")
    if raw.startswith("\\\\") or lowered.startswith(("\\\\?\\", "\\\\.\\")):
        raise SafetyError("UNC and Windows device paths are disabled")
    path = Path(PureWindowsPath(raw))
    if not path.is_absolute():
        raise SafetyError("An absolute local path is required")
    return path.resolve(strict=False)


def validate_local_input_path(value: str) -> Path:
    resolved = _absolute_local_path(value)
    if not resolved.is_file():
        raise SafetyError("Input file does not exist")
    return resolved


def validate_local_path(value: str, *, allow_overwrite: bool = False) -> Path:
    resolved = _absolute_local_path(value)
    if resolved.exists() and not allow_overwrite:
        raise SafetyError("Existing destination requires explicit overwrite confirmation")
    return resolved


class ChangeManager:
    def __init__(self, paths: RuntimePaths, secret: bytes | None = None):
        self.paths = paths
        paths.ensure()
        self._secret = secret or self._load_or_create_secret()

    def _load_or_create_secret(self) -> bytes:
        secret_path = self.paths.state / "confirmation.key"
        if secret_path.is_file():
            return secret_path.read_bytes()
        value = secrets.token_bytes(32)
        temporary = secret_path.with_suffix(".tmp")
        temporary.write_bytes(value)
        os.replace(temporary, secret_path)
        return value

    def _signature(self, nonce: str, expires_at: float) -> str:
        message = f"{nonce}:{expires_at:.6f}".encode()
        return hmac.new(self._secret, message, hashlib.sha256).hexdigest()

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
        token_value = f"{nonce}.{self._signature(nonce, expires_at)}"
        record = ChangeToken(
            token=token_value,
            feature_id=feature_id,
            scene_id=scene_id,
            scene_revision=scene_revision,
            selection_fingerprint=selection_fingerprint,
            operation=operation,
            impact=impact,
            backup_path=backup_path,
            expires_at=expires_at,
        )
        atomic_write_json(self.paths.tokens / f"{nonce}.json", record.model_dump(mode="json"))
        return record

    def load(self, token: str) -> ChangeToken:
        try:
            nonce, signature = token.split(".", 1)
        except ValueError as exc:
            raise SafetyError("Malformed confirmation token") from exc
        path = self.paths.tokens / f"{nonce}.json"
        if not path.is_file():
            raise SafetyError("Unknown confirmation token")
        record = ChangeToken.model_validate(read_json(path))
        expected = self._signature(nonce, record.expires_at)
        if not hmac.compare_digest(signature, expected):
            raise SafetyError("Invalid confirmation token signature")
        if record.used:
            raise SafetyError("Confirmation token was already used")
        if record.expires_at < time.time():
            raise SafetyError("Confirmation token expired")
        return record

    def consume(
        self, token: str, *, scene_id: str | None, scene_revision: str | None, selection_fingerprint: str | None
    ) -> ChangeToken:
        record = self.load(token)
        if record.scene_id != scene_id or record.scene_revision != scene_revision:
            raise SafetyError("Scene identity or revision changed after preparation")
        if record.selection_fingerprint != selection_fingerprint:
            raise SafetyError("Selection changed after preparation")
        nonce = token.split(".", 1)[0]
        record.used = True
        atomic_write_json(self.paths.tokens / f"{nonce}.json", record.model_dump(mode="json"))
        return record

    def cancel(self, token: str) -> bool:
        nonce = token.split(".", 1)[0]
        path = self.paths.tokens / f"{nonce}.json"
        if not path.is_file():
            return False
        path.unlink()
        return True
