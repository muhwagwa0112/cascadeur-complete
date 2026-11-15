"""Signed immutable host outbox and authenticated runtime event observation."""
from __future__ import annotations

import hashlib
import json
import os
import uuid
from pathlib import Path

from .atomic_queue import atomic_write_json, read_json
from .models import RequestReceipt
from .queue_auth import QueueAuthenticationError, sign_payload, verify_payload
from .state_lock import file_lock


def canonical_digest(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":"), allow_nan=False).encode()).hexdigest()


class RequestLedger:
    def __init__(self, state: Path, secret: bytes):
        self.root = state / "request_records"
        self.secret = secret

    def directory(self, request_id: str) -> Path:
        if str(uuid.UUID(request_id)) != request_id:
            raise ValueError("Invalid request UUID")
        return self.root / request_id

    def read_request(self, request_id: str) -> dict | None:
        path = self.directory(request_id) / "request.json"
        if not path.is_file():
            return None
        record = read_json(path)
        verify_payload(record, self.secret)
        if record.get("request_id") != request_id:
            raise QueueAuthenticationError("Outbox request identity differs")
        return record

    def create(self, payload: dict) -> bool:
        path = self.directory(payload["request_id"]) / "request.json"
        with file_lock(path.parent / "outbox.lock"):
            previous = self.read_request(payload["request_id"])
            if previous is not None:
                if previous != payload:
                    raise QueueAuthenticationError("Request identity conflicts with immutable outbox")
                return False
            atomic_write_json(path, payload)
            return True

    def read_receipt(self, request_id: str) -> RequestReceipt | None:
        request = self.read_request(request_id)
        if request is None:
            return None
        events = self.directory(request_id) / "runtime_events"
        latest = None
        expected_seq = 1
        for path in sorted(events.glob("*.json")):
            payload = read_json(path)
            verify_payload(payload, self.secret)
            receipt = RequestReceipt.model_validate(payload)
            if (receipt.request_id != request_id or receipt.request_digest != canonical_digest(request)
                    or receipt.operation_digest != canonical_digest(request["operations"])
                    or receipt.session_id != request["session_id"] or receipt.seq != expected_seq
                    or receipt.host_instance_id != request.get("host_instance_id", "")
                    or (receipt.dispatched is True and request.get("runtime_epoch") and receipt.runtime_epoch != request["runtime_epoch"])):
                raise QueueAuthenticationError("Runtime receipt identity or sequence differs")
            if receipt.terminal_result is not None and canonical_digest(receipt.terminal_result) != receipt.result_digest:
                raise QueueAuthenticationError("Terminal result digest differs")
            context = request.get("execution_context") or {}
            if any(getattr(receipt, name) != context.get(name) for name in ("run_id", "step_id", "attempt_id", "lease_epoch")):
                raise QueueAuthenticationError("Runtime receipt execution context differs")
            if latest is not None and latest.phase == "terminal":
                raise QueueAuthenticationError("Runtime event follows terminal receipt")
            latest = receipt
            expected_seq += 1
        return latest

    def write_cancel_intent(self, request_id: str) -> dict:
        request = self.read_request(request_id)
        if request is None:
            raise ValueError("Unknown request")
        payload = {"request_id": request_id, "request_digest": canonical_digest(request), "mac": ""}
        payload["mac"] = sign_payload(payload, self.secret)
        path = self.directory(request_id) / "cancel_intent.json"
        atomic_write_json(path, payload)
        return payload

    def unresolved_effects(self) -> list[str]:
        from .effects import classify_effect
        unresolved = []
        for path in self.root.glob("*/request.json"):
            request = self.read_request(path.parent.name)
            if not any(classify_effect(item["name"], item.get("arguments")) != "none"
                       for item in request["operations"]):
                continue
            receipt = self.read_receipt(request["request_id"])
            canceled_path = path.parent / "host_canceled.json"
            if receipt is None and canceled_path.exists():
                canceled = read_json(canceled_path)
                verify_payload(canceled, self.secret)
                if canceled.get("request_digest") == canonical_digest(request):
                    continue
            if receipt is not None and receipt.phase == "terminal" and receipt.outcome != "outcome_unknown":
                continue
            # A signed terminal response is positive completion evidence even if
            # an older runtime did not write receipts. It cannot authorize v3 writes.
            unresolved.append(request["request_id"])
        return unresolved

    def record_unclaimed_cancel(self, request_id: str) -> None:
        request = self.read_request(request_id)
        if request is None:
            raise ValueError("Unknown request")
        payload = {"request_id": request_id, "request_digest": canonical_digest(request),
                   "outcome": "canceled_pre_dispatch", "mac": ""}
        payload["mac"] = sign_payload(payload, self.secret)
        atomic_write_json(self.directory(request_id) / "host_canceled.json", payload)
