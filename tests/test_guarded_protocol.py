"""Protocol-3 queue/receipt boundaries, without a Cascadeur process."""
import time
import uuid

import pytest

from cascadeur_complete.atomic_queue import AtomicQueue, atomic_write_json, read_json
from cascadeur_complete.bridge_client import BridgeClient
from cascadeur_complete.effects import classify_effect
from cascadeur_complete.models import BridgeRequest, Operation, ResultEnvelope, ErrorCode, ExecutionMode
from cascadeur_complete.paths import RuntimePaths
from cascadeur_complete.queue_auth import QueueAuthenticationError, sign_payload
from tests.bridge_support import loaded_bridge


@pytest.fixture
def bridge(tmp_path, monkeypatch):
    paths = RuntimePaths.discover(tmp_path)
    queue = AtomicQueue(paths)
    with loaded_bridge("guarded_protocol_bridge") as (runtime, registry):
        scene = object()
        state = {"scene_id": "scene", "revision": "r", "selection_fingerprint": "s"}
        monkeypatch.setattr(runtime, "runtime_root", lambda: paths.root)
        monkeypatch.setattr(runtime, "_scene_view", lambda: scene)
        monkeypatch.setattr(runtime, "scene_state", lambda _: dict(state))
        calls = []
        monkeypatch.setattr(runtime, "dispatch_registered", lambda name, *_: (calls.append(name) is None, ({"observed": True}, [])))
        yield paths, queue, runtime, registry, scene, calls


def submit(queue, name, arguments=None, protocol="3.0"):
    request = BridgeRequest(request_id=str(uuid.uuid4()), feature_id="probe", protocol_version=protocol,
        operations=[Operation(name=name, arguments=arguments or {})], created_at=time.time(), expires_at=time.time()+60)
    queue.submit(request)
    return request


def test_replayed_original_is_observed_once_and_survives_host_restart(bridge):
    paths, queue, runtime, _, scene, calls = bridge
    request = submit(queue, "scene.list")
    runtime._drain_once(scene)
    original = queue.ledger.read_request(request.request_id)
    atomic_write_json(paths.requests / "repeated.json", original)
    runtime._drain_once(scene)
    assert calls == ["scene.list"]
    restarted = BridgeClient(paths)
    result = restarted.reconcile_request(request.request_id)
    assert result.ok and result.request_id == request.request_id
    assert result.outcome == "succeeded"
    assert restarted.queue.ledger.read_receipt(request.request_id).phase == "terminal"


@pytest.mark.parametrize(("protocol", "name", "arguments", "detail"), [
    ("2.0", "layer.create", {}, "PROTOCOL_MISMATCH"),
    ("3.0", "animation.transform_get", {"refresh": True}, "PROTOCOL_MISMATCH"),
])
def test_effects_never_downgrade_or_dispatch_without_binding(bridge, protocol, name, arguments, detail):
    _, queue, runtime, _, scene, calls = bridge
    request = submit(queue, name, arguments, protocol)
    runtime._drain_once(scene)
    receipt = queue.ledger.read_receipt(request.request_id)
    assert not calls and receipt.outcome == "rejected_pre_dispatch" and receipt.dispatched is False
    assert receipt.terminal_result["result"]["error_details"]["code"] == detail


def test_claimed_unknown_blocks_later_effect_without_requeue(bridge):
    paths, queue, _, _, _, _ = bridge
    request = submit(queue, "layer.create")
    pending = next(paths.requests.glob("*.json"))
    pending.replace(pending.with_suffix(".processing"))
    result = BridgeClient(paths).execute("second", [Operation(name="layer.create")], timeout=.1)
    assert result.outcome == "outcome_unknown" and result.request_id == request.request_id
    assert len(list(paths.requests.glob("*.processing"))) == 1
    assert not list(paths.requests.glob("*.json"))


def test_callback_permit_expires_and_cannot_be_reentered(bridge):
    _, _, runtime, registry, _, _ = bridge
    writes, late = [], []
    runtime.guards.begin_request({})
    with pytest.raises(RuntimeError, match="synchronously"):
        registry.transact(lambda _, callback: late.append(callback), "delayed", lambda: writes.append(1))
    with pytest.raises(RuntimeError, match="permit"):
        late[0]()
    assert writes == []
    def twice(_, callback):
        callback()
        callback()
    with pytest.raises(RuntimeError, match="permit"):
        registry.transact(twice, "twice", lambda: writes.append(1))
    assert writes == [1]


def test_signed_but_mismatched_terminal_payload_is_rejected(bridge):
    paths, queue, runtime, _, scene, _ = bridge
    request = submit(queue, "scene.list")
    runtime._drain_once(scene)
    path = next((queue.ledger.directory(request.request_id) / "runtime_events").glob("*-terminal.json"))
    receipt = read_json(path)
    receipt["terminal_result"]["ok"] = False
    receipt["mac"] = sign_payload(receipt, queue._secret)
    atomic_write_json(path, receipt)
    with pytest.raises(QueueAuthenticationError, match="digest"):
        BridgeClient(paths).reconcile_request(request.request_id)


def test_argument_aware_effect_classification():
    assert classify_effect("animation.transform_get", {"refresh": True}) == "evaluation"
    assert classify_effect("animation.transform_get", {"refresh": False}) == "none"
    assert classify_effect("system.view_mode_get", {"mode": "perspective"}) == "scene"


def test_only_status_can_fallback_to_legacy_read_protocol(tmp_path, monkeypatch):
    client = BridgeClient(RuntimePaths.discover(tmp_path), trigger=None)
    protocols = []
    def response(feature_id, operations, **kwargs):
        protocols.append(kwargs["protocol_version"])
        if len(protocols) == 1:
            return ResultEnvelope(ok=False, feature_id=feature_id, execution_mode=ExecutionMode.NATIVE, error_code=ErrorCode.UNSUPPORTED_VERSION)
        client.runtime_status = {"protocol_version": "2.0"}
        return ResultEnvelope(ok=True, feature_id=feature_id, execution_mode=ExecutionMode.NATIVE)
    monkeypatch.setattr(client, "_execute_once", response)
    assert client.execute("status", [Operation(name="system.status")]).ok
    assert protocols == ["3.0", "2.0"]
    refused = client.execute("write", [Operation(name="layer.create")])
    assert not refused.ok and refused.dispatched is False
    assert refused.result["error_details"]["code"] == "PROTOCOL_MISMATCH"
    assert protocols == ["3.0", "2.0"]


def test_changed_bridge_package_cannot_dispatch_mutation(tmp_path, monkeypatch):
    client = BridgeClient(RuntimePaths.discover(tmp_path), trigger=None)
    client.runtime_status = {"protocol_version": "3.0", "adapter_fingerprint": "other-package"}
    def forbidden(*args, **kwargs):
        raise AssertionError("Mismatched package must never queue effects")
    monkeypatch.setattr(client, "_execute_once", forbidden)
    refused = client.execute("write", [Operation(name="layer.create")])
    assert not refused.ok and refused.dispatched is False
    assert not list(client.paths.requests.glob("*.json"))


def test_original_effect_receipt_remains_observable_after_package_change(bridge):
    paths, queue, runtime, _, scene, calls = bridge
    request = submit(queue, "layer.create", protocol="2.0")
    runtime._drain_once(scene)
    client = BridgeClient(paths, trigger=None)
    client.runtime_status = {"protocol_version": "3.0", "adapter_fingerprint": "other-package"}
    observed = client.execute("probe", [Operation(name="layer.create")], request_id=request.request_id)
    assert observed.request_id == request.request_id and observed.phase == "terminal"
    assert observed.outcome == "rejected_pre_dispatch" and not calls
    assert not list(paths.requests.glob("*.json"))


def test_native_readback_rejects_nonfinite_and_incomplete_capture(bridge):
    _, _, runtime, registry, _, _ = bridge
    import importlib
    animation = importlib.import_module(runtime.__package__ + ".handlers.animation")
    with pytest.raises(ValueError, match="finite"):
        animation._position_error([float("nan"), 0, 0], [0, 0, 0])
    with pytest.raises(ValueError, match="coverage"):
        animation._complete_readback([{"id": "a"}, {"id": "a"}], ["a", "b"])
