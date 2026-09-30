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


def test_feature_gate_is_reported_as_license_gated_and_cancels_the_request(tmp_path):
    paths = RuntimePaths.discover(tmp_path / "runtime")
    probes = []

    def gate():
        probes.append(1)
        return "USD export"

    client = BridgeClient(paths, trigger=None, gate_probe=gate)
    result = client.execute("export_usd", [Operation(name="system.status")], timeout=2.5)
    assert result.error_code == ErrorCode.LICENSE_GATED
    assert "USD export" in result.error_message
    assert probes == [1]
    assert client.queue.pending_count() == 0


def _publish_pump(paths, *, age=0.0, busy=False):
    import os
    import time

    paths.state.mkdir(parents=True, exist_ok=True)
    atomic_write_json(
        paths.state / "pump.json",
        {
            "schema": 1,
            "pid": os.getpid(),
            "hwnd": 0,
            "wake_message": 0,
            "heartbeat": time.time() - age,
            "busy": busy,
        },
    )


def _serve_one_request(client, paths, stop):
    import time

    while not stop.is_set():
        pending = list(paths.requests.glob("*.json"))
        if not pending:
            time.sleep(0.01)
            continue
        request = read_json(pending[0])
        pending[0].unlink()
        response = ResultEnvelope(ok=True, feature_id=request["feature_id"], execution_mode=ExecutionMode.NATIVE)
        client.queue.authenticate_response(BridgeRequest.model_validate(request), response)
        atomic_write_json(paths.responses / f"{request['request_id']}.json", response.model_dump(mode="json"))
        return


def test_live_pump_drains_without_ui_trigger(tmp_path):
    from threading import Thread

    paths = RuntimePaths.discover(tmp_path / "runtime")
    triggers = []
    client = BridgeClient(paths, trigger=lambda: triggers.append(1))
    _publish_pump(paths)
    stop = Event()
    pump = Thread(target=_serve_one_request, args=(client, paths, stop), daemon=True)
    pump.start()

    result = client.execute("status", [Operation(name="system.status")], timeout=5)
    stop.set()

    assert result.ok
    assert triggers == []
    assert client.pump_state()["active"] is True


def test_pump_that_does_not_claim_falls_back_to_ui_trigger(tmp_path, monkeypatch):
    import cascadeur_complete.bridge_client as bridge_client

    monkeypatch.setattr(bridge_client, "PUMP_CLAIM_SECONDS", 0.05)
    paths = RuntimePaths.discover(tmp_path / "runtime")
    client = BridgeClient(paths, trigger=None)
    _publish_pump(paths)
    triggers = []

    def trigger():
        triggers.append(1)
        _serve_one_request(client, paths, Event())

    client.trigger = trigger
    result = client.execute("status", [Operation(name="system.status")], timeout=5)

    assert result.ok
    assert triggers == [1]


def test_stale_or_disabled_pump_is_ignored(tmp_path):
    paths = RuntimePaths.discover(tmp_path / "runtime")
    client = BridgeClient(paths, trigger=None)
    _publish_pump(paths, age=30.0)
    assert client.pump_state() == {"active": False}
    _publish_pump(paths)
    assert client.pump_state()["active"] is True
    (paths.state / "pump.disabled").write_text("", encoding="utf-8")
    assert client.pump_state() == {"active": False}


def test_busy_pump_keeps_the_host_waiting_instead_of_falling_back(tmp_path, monkeypatch):
    import time
    from threading import Thread

    import cascadeur_complete.bridge_client as bridge_client

    monkeypatch.setattr(bridge_client, "PUMP_CLAIM_SECONDS", 0.05)
    paths = RuntimePaths.discover(tmp_path / "runtime")
    triggers = []
    client = BridgeClient(paths, trigger=lambda: triggers.append(1))
    # Busy with an earlier request: the heartbeat is stale but the owner lives.
    _publish_pump(paths, age=10.0, busy=True)

    def finish_earlier_request_then_serve():
        time.sleep(0.4)
        _serve_one_request(client, paths, Event())

    Thread(target=finish_earlier_request_then_serve, daemon=True).start()
    result = client.execute("status", [Operation(name="system.status")], timeout=5)

    assert result.ok
    assert triggers == []
