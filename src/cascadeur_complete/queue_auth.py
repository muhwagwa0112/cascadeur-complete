from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import stat
from contextlib import suppress
from pathlib import Path
from typing import Any


class QueueAuthenticationError(ValueError):
    pass


def canonical_payload(payload: dict[str, Any]) -> bytes:
    unsigned = {key: value for key, value in payload.items() if key != "mac"}
    return json.dumps(
        unsigned,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def sign_payload(payload: dict[str, Any], secret: bytes) -> str:
    return hmac.new(secret, canonical_payload(payload), hashlib.sha256).hexdigest()


def verify_payload(payload: dict[str, Any], secret: bytes) -> None:
    supplied = payload.get("mac")
    if not isinstance(supplied, str) or len(supplied) != 64:
        raise QueueAuthenticationError("Queue message is unsigned")
    expected = sign_payload(payload, secret)
    if not hmac.compare_digest(supplied, expected):
        raise QueueAuthenticationError("Queue message authentication failed")


def session_id(secret: bytes) -> str:
    return hashlib.sha256(b"cascadeur-complete-bridge-session\0" + secret).hexdigest()[:32]


def load_or_create_secret(path: Path) -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        value = path.read_bytes()
    except FileNotFoundError:
        value = secrets.token_bytes(32)
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            value = path.read_bytes()
        else:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(value)
                stream.flush()
                os.fsync(stream.fileno())
    if len(value) < 32:
        raise QueueAuthenticationError("Bridge authentication key is invalid")
    with suppress(OSError):
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    return value
