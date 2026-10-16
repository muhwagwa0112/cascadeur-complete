import json
import time
import uuid

import pytest

from cascadeur_complete.atomic_queue import AtomicQueue, atomic_write_json
from cascadeur_complete.models import BridgeRequest, Operation, ResultEnvelope, SafetyContext
from cascadeur_complete.paths import RuntimePaths
from cascadeur_complete.queue_auth import QueueAuthenticationError


def make_request(request_id=None):
    now = time.time()
    return BridgeRequest(
        request_id=request_id or str(uuid.uuid4()),
        feature_id="status",
        operations=[Operation(name="system.status")],
        created_at=now,
        expires_at=now + 30,
        safety_context=SafetyContext(),
    )


def test_atomic_queue_round_trip(tmp_path):
    paths = RuntimePaths.discover(tmp_path / "runtime")
    queue = AtomicQueue(paths)
    request = make_request()
    request_path = queue.submit(request)
    assert request_path.is_file()
    payload = json.loads(request_path.read_text(encoding="utf-8"))
    assert payload["protocol_version"] == "2.0"
    assert payload["session_id"] == queue.session_id
    assert payload["nonce"] and payload["mac"]
    response = ResultEnvelope(ok=True, feature_id="status", execution_mode="Native", result={"alive": True})
    queue.authenticate_response(request, response)
    atomic_write_json(queue.response_path(request.request_id), response.model_dump(mode="json"))
    observed = queue.read_response(request.request_id)
    assert observed and observed.ok and observed.result == {"alive": True}
    assert not queue.response_path(request.request_id).exists()


def test_forged_or_replayed_response_is_rejected(tmp_path):
    paths = RuntimePaths.discover(tmp_path / "runtime")
    queue = AtomicQueue(paths)
    request = make_request()
    queue.submit(request)
    forged = ResultEnvelope(ok=True, feature_id="status", execution_mode="Native")
    atomic_write_json(queue.response_path(request.request_id), forged.model_dump(mode="json"))
    with pytest.raises(QueueAuthenticationError):
        queue.read_response(request.request_id)

    queue.response_path(request.request_id).unlink()
    queue.authenticate_response(request, forged)
    forged.nonce = "different-nonce"
    atomic_write_json(queue.response_path(request.request_id), forged.model_dump(mode="json"))
    with pytest.raises(QueueAuthenticationError):
        queue.read_response(request.request_id)


def test_atomic_write_json_survives_concurrent_writers_in_one_process(tmp_path):
    import threading

    target = tmp_path / "registry.json"
    errors = []

    def write(writer):
        try:
            for index in range(40):
                atomic_write_json(target, {"writer": writer, "index": index, "padding": "x" * 4096})
        except Exception as exc:  # pragma: no cover - reported by the assertion below
            errors.append(repr(exc))

    threads = [threading.Thread(target=write, args=(writer,)) for writer in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
    assert json.loads(target.read_text(encoding="utf-8"))["index"] == 39
    assert [path.name for path in tmp_path.iterdir()] == ["registry.json"]
