"""Characterization of the bridge request pipeline outside Cascadeur.

``execute_request`` and ``_drain_once`` run with the scene-facing helpers
stubbed: ``scene_state`` returns a fixed state, ``_scene_view`` a placeholder
scene and ``dispatch_registered`` a scripted handler. Everything else (HMAC,
nonce claim, TTL, protocol, confirmation gate, response signing, yielding) is
the real bridge code.

Tests marked ``xfail(strict=True)`` describe the intended behaviour of a known
bug (docs/REFACTOR_PREP.md §5); fixing the bug makes them pass, and the marker
must then be removed.
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

import pytest

from tests.bridge_support import loaded_bridge

SECRET = b"k" * 32
STATE = {
    "scene_id": "scene-1",
    "revision": "rev-1",
    "selection_fingerprint": "sel-1",
    "current_frame": 0,
    "selection": [],
    "objects": [],
}


@pytest.fixture(scope="module")
def runtime():
    with loaded_bridge("cascadeur_complete_bridge_request_flow") as (loaded, _registry):
        yield loaded


@pytest.fixture
def bridge(runtime, tmp_path, monkeypatch):
    """The bridge rooted in ``tmp_path`` with a scripted handler table."""
    handlers: dict[str, object] = {}
    calls: list[str] = []

    def dispatch(name, _scene, arguments, _request, _context):
        if name not in handlers:
            return False, None
        calls.append(name)
        handler = handlers[name]
        return True, handler(arguments) if callable(handler) else handler

    monkeypatch.setattr(runtime, "runtime_root", lambda: tmp_path)
    monkeypatch.setattr(runtime, "scene_state", lambda _scene: dict(STATE))
    monkeypatch.setattr(runtime, "_scene_view", lambda: object())
    monkeypatch.setattr(runtime, "dispatch_registered", dispatch)
    root = runtime.ensure_dirs()
    (root / "state" / "bridge.key").write_bytes(SECRET)
    runtime._test_handlers = handlers
    runtime._test_calls = calls
    yield runtime
    del runtime._test_handlers, runtime._test_calls


def _request(runtime, operations, **overrides) -> dict:
    request = {
        "protocol_version": runtime.PROTOCOL_VERSION,
        "request_id": str(uuid.uuid4()),
        "session_id": runtime._session_id(SECRET),
        "nonce": uuid.uuid4().hex,
        "expires_at": time.time() + 60,
        "feature_id": "probe",
        "operations": operations,
        "safety_context": {},
        **overrides,
    }
    request["mac"] = runtime._sign_message(request, SECRET)
    return request


def _queue(runtime, request: dict, name: str | None = None) -> Path:
    path = runtime.runtime_root() / "state" / "requests" / (name or f"{time.time_ns()}-{request['request_id']}.json")
    path.write_text(json.dumps(request), encoding="utf-8")
    return path


def _response(runtime, request: dict) -> dict:
    path = runtime.runtime_root() / "state" / "responses" / (request["request_id"] + ".json")
    return json.loads(path.read_text(encoding="utf-8"))


READ = {"name": "scene.list", "arguments": {}}
MUTATE = {"name": "layer.create", "arguments": {"name": "probe"}}


# --- execute_request -------------------------------------------------------


def test_read_only_request_runs_and_reports_declared_postconditions(bridge, monkeypatch):
    bridge._test_handlers["scene.list"] = ({"scenes": []}, ["note"])
    monkeypatch.setattr(bridge, "declared_postconditions", lambda name: ("scene_list_payload",))
    result = bridge.execute_request(object(), _request(bridge, [READ]))
    assert result["ok"] is True
    assert result["status"] == "succeeded"
    assert result["result"] == {"scenes": []}
    assert result["warnings"] == ["note"]
    assert [item["id"] for item in result["postconditions"]] == ["bridge_execution", "scene_list_payload"]


def test_batch_returns_one_result_per_operation(bridge):
    bridge._test_handlers["scene.list"] = ({"n": 1}, [])
    bridge._test_handlers["layer.list"] = ({"n": 2}, [])
    result = bridge.execute_request(object(), _request(bridge, [READ, {"name": "layer.list", "arguments": {}}]))
    assert result["operation_id"] == "batch"
    assert result["result"] == [
        {"operation": "scene.list", "result": {"n": 1}},
        {"operation": "layer.list", "result": {"n": 2}},
    ]


@pytest.mark.parametrize(
    ("override", "message"),
    [({"scene_id": "other"}, "Scene identity changed"), ({"expected_revision": "old"}, "Scene revision changed")],
)
def test_scene_guard_rejects_before_dispatch(bridge, override, message):
    bridge._test_handlers["scene.list"] = ({}, [])
    result = bridge.execute_request(object(), _request(bridge, [READ], **override))
    assert (result["error_code"], result["error_message"]) == ("SCENE_CHANGED", message)
    assert bridge._test_calls == []


def test_mutation_without_confirmation_token_is_rejected_before_dispatch(bridge):
    bridge._test_handlers["layer.create"] = ({}, [])
    result = bridge.execute_request(object(), _request(bridge, [MUTATE]))
    assert result["error_code"] == "INVALID_REQUEST"
    assert "confirmation token" in result["error_message"]
    assert bridge._test_calls == []


def test_mutation_with_unknown_token_is_rejected(bridge):
    bridge._test_handlers["layer.create"] = ({}, [])
    token = "n" * 24 + "." + "0" * 64
    result = bridge.execute_request(object(), _request(bridge, [MUTATE], safety_context={"confirmation_token": token}))
    assert result["error_code"] == "INVALID_REQUEST"
    assert result["error_message"] == "Consumed confirmation token is unavailable"


@pytest.mark.parametrize(
    ("raised", "code"),
    [
        (AssertionError("postcondition"), "POSTCONDITION_FAILED"),
        (PermissionError("pro only"), "LICENSE_GATED"),
        (RuntimeError("boom"), "POSTCONDITION_FAILED"),
    ],
)
def test_handler_exceptions_map_to_error_codes(bridge, raised, code):
    def fail(_arguments):
        raise raised

    bridge._test_handlers["scene.list"] = fail
    result = bridge.execute_request(object(), _request(bridge, [READ]))
    assert result["ok"] is False
    assert result["error_code"] == code
    assert str(raised) in result["error_message"]


def test_unknown_operation_fails_as_postcondition(bridge, monkeypatch):
    # Treat it as read-only so the request gets past the confirmation gate.
    monkeypatch.setattr(bridge, "READ_ONLY_OPERATIONS", bridge.READ_ONLY_OPERATIONS | {"scene.no_such_operation"})
    result = bridge.execute_request(object(), _request(bridge, [{"name": "scene.no_such_operation"}]))
    assert result["ok"] is False
    assert result["error_code"] == "POSTCONDITION_FAILED"
    assert "Unknown operation: scene.no_such_operation" in result["error_message"]


@pytest.mark.xfail(strict=True, reason="§5-2: system.view_mode_get is missing from READ_ONLY_OPERATIONS")
def test_view_mode_get_needs_no_confirmation_token(bridge):
    bridge._test_handlers["system.view_mode_get"] = ({"mode": "View"}, [])
    result = bridge.execute_request(object(), _request(bridge, [{"name": "system.view_mode_get", "arguments": {}}]))
    assert result["ok"] is True


@pytest.mark.xfail(strict=True, reason="§5-3: _save_snapshot is called without working_id")
def test_snapshot_required_saves_a_snapshot(bridge, monkeypatch):
    saved = []

    def record(scene, snapshot_id, working_id):
        saved.append((snapshot_id, working_id))

    monkeypatch.setattr(bridge, "_save_snapshot", record)
    bridge._test_handlers["scene.list"] = ({}, [])
    request = _request(bridge, [READ], safety_context={"snapshot_required": True})
    result = bridge.execute_request(object(), request)
    assert result["ok"] is True
    assert saved and saved[0][0] == request["request_id"]


# --- _drain_once -----------------------------------------------------------


def test_drain_writes_a_signed_response_and_removes_the_claim(bridge):
    bridge._test_handlers["scene.list"] = ({"scenes": []}, [])
    request = _request(bridge, [READ])
    queued = _queue(bridge, request)
    processed, must_yield = bridge._drain_once(object())
    assert (processed, must_yield) == (1, False)
    response = _response(bridge, request)
    assert response["ok"] is True
    assert (response["request_id"], response["nonce"]) == (request["request_id"], request["nonce"])
    assert response["mac"] == bridge._sign_message(response, SECRET)
    assert not queued.exists()
    assert not list((bridge.runtime_root() / "state" / "requests").iterdir())


def test_drain_rejects_a_tampered_request(bridge):
    bridge._test_handlers["scene.list"] = ({}, [])
    request = _request(bridge, [READ])
    request["feature_id"] = "tampered"
    _queue(bridge, request)
    assert bridge._drain_once(object()) == (1, False)
    response = _response(bridge, request)
    assert response["error_code"] == "INVALID_REQUEST"
    assert response["error_message"] == "Queue message authentication failed"
    assert bridge._test_calls == []


def test_drain_rejects_a_replayed_nonce(bridge):
    bridge._test_handlers["scene.list"] = ({}, [])
    request = _request(bridge, [READ])
    _queue(bridge, request)
    bridge._drain_once(object())
    _queue(bridge, request)
    bridge._drain_once(object())
    assert _response(bridge, request)["error_message"] == "Queue request was already processed"
    assert bridge._test_calls == ["scene.list"]


@pytest.mark.parametrize(
    ("override", "code"),
    [({"protocol_version": "1.0"}, "UNSUPPORTED_VERSION"), ({"expires_at": 1.0}, "TIMEOUT")],
)
def test_drain_rejects_wrong_protocol_and_expired_requests(bridge, override, code):
    bridge._test_handlers["scene.list"] = ({}, [])
    request = _request(bridge, [READ], **override)
    _queue(bridge, request)
    bridge._drain_once(object())
    assert _response(bridge, request)["error_code"] == code
    assert bridge._test_calls == []


def test_drain_without_a_bridge_key_yields_without_claiming(bridge):
    (bridge.runtime_root() / "state" / "bridge.key").unlink()
    queued = _queue(bridge, _request(bridge, [READ]))
    assert bridge._drain_once(object()) == (0, True)
    assert queued.exists()


def test_drain_stops_after_a_yielding_operation(bridge):
    bridge._test_handlers["scene.new"] = ({}, [])
    bridge._test_handlers["scene.list"] = ({}, [])
    first = _request(bridge, [{"name": "scene.new", "arguments": {}}])
    second = _request(bridge, [READ])
    _queue(bridge, first, "1-first.json")
    pending = _queue(bridge, second, "2-second.json")
    assert bridge._drain_once(object()) == (1, True)
    assert pending.exists()


def test_drain_matching_scene_only_leaves_other_scene_requests(bridge):
    bridge._test_handlers["scene.list"] = ({}, [])
    other = _queue(bridge, _request(bridge, [READ], scene_id="other"), "1-other.json")
    mine = _request(bridge, [READ], scene_id=STATE["scene_id"])
    _queue(bridge, mine, "2-mine.json")
    assert bridge._drain_once(object(), matching_scene_only=True) == (1, False)
    assert other.exists()
    assert _response(bridge, mine)["ok"] is True


@pytest.mark.xfail(strict=True, reason="§5-4: a malformed request aborts the drain and skips the rest of the queue")
def test_drain_skips_a_malformed_request_and_continues(bridge):
    bridge._test_handlers["scene.list"] = ({}, [])
    (bridge.runtime_root() / "state" / "requests" / "1-broken.json").write_text("{not json", encoding="utf-8")
    good = _request(bridge, [READ])
    _queue(bridge, good, "2-good.json")
    bridge._drain_once(object())
    assert _response(bridge, good)["ok"] is True
