import json
import os
import time

from cascadeur_complete.atomic_queue import AtomicQueue, atomic_write_json
from cascadeur_complete.models import BridgeRequest, Operation, ResultEnvelope, SafetyContext
from cascadeur_complete.paths import RuntimePaths


def make_request(request_id="abc"):
    now = time.time()
    return BridgeRequest(
        request_id=request_id,
        feature_id="status",
        operations=[Operation(name="system.status")],
        created_at=now,
        expires_at=now + 30,
        safety_context=SafetyContext(),
    )


def test_atomic_queue_round_trip(tmp_path):
    paths = RuntimePaths.discover(tmp_path / "runtime")
    queue = AtomicQueue(paths)
    request_path = queue.submit(make_request())
    assert request_path.is_file()
    payload = json.loads(request_path.read_text(encoding="utf-8"))
    assert payload["protocol_version"] == "1.0"
    response = ResultEnvelope(ok=True, feature_id="status", execution_mode="Native", result={"alive": True})
    atomic_write_json(queue.response_path("abc"), response.model_dump(mode="json"))
    observed = queue.read_response("abc")
    assert observed and observed.ok and observed.result == {"alive": True}
    assert not queue.response_path("abc").exists()


def test_stale_claim_recovery(tmp_path):
    paths = RuntimePaths.discover(tmp_path / "runtime")
    queue = AtomicQueue(paths)
    claimed = paths.requests / "stale.processing"
    claimed.write_text("{}", encoding="utf-8")
    old = time.time() - 120
    os.utime(claimed, (old, old))
    assert queue.recover_stale_claims(stale_after=60) == 1
    assert (paths.requests / "stale.json").is_file()
