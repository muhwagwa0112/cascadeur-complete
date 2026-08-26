from __future__ import annotations

import json
import os
import re
import secrets
import time
from pathlib import Path
from typing import Any

from .models import BridgeRequest, ResultEnvelope
from .paths import RuntimePaths
from .queue_auth import QueueAuthenticationError, load_or_create_secret, session_id, sign_payload, verify_payload


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(payload, stream, ensure_ascii=False, separators=(",", ":"))
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return value


class AtomicQueue:
    def __init__(self, paths: RuntimePaths):
        self.paths = paths
        paths.ensure()
        self._secret = load_or_create_secret(paths.bridge_key)
        self.session_id = session_id(self._secret)
        self._outstanding: dict[str, str] = {}

    def submit(self, request: BridgeRequest) -> Path:
        request.session_id = self.session_id
        request.nonce = secrets.token_urlsafe(24)
        request.mac = ""
        request.mac = sign_payload(request.model_dump(mode="json"), self._secret)
        self._outstanding[request.request_id] = request.nonce
        target = self.paths.requests / f"{request.created_at:.6f}-{request.request_id}.json"
        atomic_write_json(target, request.model_dump(mode="json"))
        return target

    def response_path(self, request_id: str) -> Path:
        if not re.fullmatch(r"[A-Za-z0-9-]{1,128}", request_id):
            raise QueueAuthenticationError("Invalid request id")
        return self.paths.responses / f"{request_id}.json"

    def read_response(self, request_id: str, *, consume: bool = True) -> ResultEnvelope | None:
        path = self.response_path(request_id)
        if not path.is_file():
            return None
        payload = read_json(path)
        verify_payload(payload, self._secret)
        expected_nonce = self._outstanding.get(request_id)
        if payload.get("request_id") != request_id:
            raise QueueAuthenticationError("Response request id does not match")
        if payload.get("session_id") != self.session_id:
            raise QueueAuthenticationError("Response session does not match")
        if not expected_nonce or payload.get("nonce") != expected_nonce:
            raise QueueAuthenticationError("Response nonce does not match outstanding request")
        result = ResultEnvelope.model_validate(payload)
        if consume:
            path.unlink(missing_ok=True)
            self._outstanding.pop(request_id, None)
        return result

    def authenticate_response(self, request: BridgeRequest, result: ResultEnvelope) -> ResultEnvelope:
        """Test/embedded bridge helper; the Cascadeur runtime signs independently."""
        result.request_id = request.request_id
        result.session_id = request.session_id
        result.nonce = request.nonce
        result.mac = ""
        result.mac = sign_payload(result.model_dump(mode="json"), self._secret)
        return result

    def wait_response(self, request_id: str, timeout: float, poll_interval: float = 0.05) -> ResultEnvelope | None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            result = self.read_response(request_id)
            if result is not None:
                return result
            time.sleep(poll_interval)
        return None

    def pending_count(self) -> int:
        return sum(1 for path in self.paths.requests.glob("*.json") if path.is_file())

    def recover_stale_claims(self, stale_after: float = 60.0) -> int:
        recovered = 0
        now = time.time()
        for path in self.paths.requests.glob("*.processing"):
            try:
                if now - path.stat().st_mtime < stale_after:
                    continue
                target = path.with_suffix(".json")
                os.replace(path, target)
                recovered += 1
            except FileNotFoundError:
                continue
        return recovered
