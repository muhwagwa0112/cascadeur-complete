from threading import Event

from cascadeur_complete.atomic_queue import atomic_write_json, read_json
from cascadeur_complete.bridge_client import BridgeClient
from cascadeur_complete.models import BridgeRequest, ErrorCode, ExecutionMode, Operation, ResultEnvelope
from cascadeur_complete.paths import RuntimePaths
from cascadeur_complete.uia import UIAutomationError


def test_trigger_failure_cancels_unclaimed_request(tmp_path):
    paths = RuntimePaths.discover(tmp_path / "runtime")

    def fail():
        raise UIAutomationError("not running", not_running=True)

    client = BridgeClient(paths, trigger=fail)
    result = client.execute("status", [Operation(name="system.status")], timeout=1)
    assert not result.ok
    assert result.error_code.value == "CASCADEUR_NOT_RUNNING"
    assert client.queue.pending_count() == 0


def test_visible_but_locked_ui_is_not_reported_as_not_running(tmp_path):
    paths = RuntimePaths.discover(tmp_path / "runtime")

    def fail():
        raise UIAutomationError("menu unavailable")

    result = BridgeClient(paths, trigger=fail).execute("status", [Operation(name="system.status")], timeout=1)
    assert result.error_code == ErrorCode.UI_LOCKED
    assert BridgeClient(paths, trigger=None).queue.pending_count() == 0


def test_transient_ui_failure_is_retried_before_canceling(tmp_path):
    paths = RuntimePaths.discover(tmp_path / "runtime")
    calls = []

    def transient():
        calls.append(1)
        if len(calls) == 1:
            raise UIAutomationError("cold menu")

    client = BridgeClient(paths, trigger=transient)
    result = client.execute("status", [Operation(name="system.status")], timeout=0.03)
    assert len(calls) == 2
    assert result.error_code == ErrorCode.TIMEOUT
    assert client.queue.pending_count() == 0


def test_timeout_cancels_unclaimed_request(tmp_path):
    paths = RuntimePaths.discover(tmp_path / "runtime")
    client = BridgeClient(paths, trigger=lambda: None)

    result = client.execute("status", [Operation(name="system.status")], timeout=0.01)

    assert result.error_code == ErrorCode.TIMEOUT
    assert "canceled" in result.error_message
    assert client.queue.pending_count() == 0


def test_silent_unclaimed_dispatch_is_retried_without_duplicate_execution(tmp_path):
    paths = RuntimePaths.discover(tmp_path / "runtime")
    calls = []
    client = BridgeClient(paths, trigger=None)

    def process_on_second_attempt():
        calls.append(1)
        if len(calls) != 2:
            return
        request_path = next(paths.requests.glob("*.json"))
        request = read_json(request_path)
        request_path.unlink()
        response = ResultEnvelope(
            ok=True,
            feature_id=request["feature_id"],
            execution_mode=ExecutionMode.NATIVE,
        )
        client.queue.authenticate_response(BridgeRequest.model_validate(request), response)
        atomic_write_json(paths.responses / f"{request['request_id']}.json", response.model_dump(mode="json"))

    client.trigger = process_on_second_attempt
    result = client.execute("status", [Operation(name="system.status")], timeout=5)

    assert result.ok
    assert calls == [1, 1]
    assert result.warnings == ["UI dispatch succeeded after 2 attempts"]
    assert BridgeClient(paths, trigger=None).queue.pending_count() == 0


def test_hung_ui_trigger_is_bounded_and_request_is_canceled(tmp_path):
    paths = RuntimePaths.discover(tmp_path / "runtime")
    never = Event()
    calls = []

    def hang():
        calls.append(1)
        never.wait()

    client = BridgeClient(paths, trigger=hang)

    result = client.execute("status", [Operation(name="system.status")], timeout=0.02)

    assert result.error_code == ErrorCode.UI_LOCKED
    assert calls == [1]
    assert client.queue.pending_count() == 0
