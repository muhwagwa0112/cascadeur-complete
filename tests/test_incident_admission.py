"""Focused two-domain queue/admission boundary, without the Cascadeur SDK."""
from __future__ import annotations

import importlib
import json
from pathlib import Path
import time
import uuid

import pytest

from tests.bridge_support import loaded_bridge
from cascadeur_complete.atomic_queue import AtomicQueue
from cascadeur_complete import incident_admission as admission, incident_store as persistence
from cascadeur_complete.incident_control import inspect
from cascadeur_complete.models import BridgeRequest, Operation
from cascadeur_complete.paths import RuntimePaths
from cascadeur_complete.queue_auth import load_or_create_secret, sign_payload


def _fixture(tmp_path, monkeypatch):
    profile = tmp_path / "user"
    (profile / "AppData" / "Local").mkdir(parents=True)
    monkeypatch.setenv("USERPROFILE", str(profile))
    root = persistence.canonical_root()
    other = tmp_path / "isolated"
    for directory in (root, other):
        load_or_create_secret(directory / "state" / "bridge.key")
    persistence.enroll_domains([root, other])
    return root, other


def _request(name, *, epoch=None, fingerprint=None):
    return BridgeRequest(request_id=str(uuid.uuid4()), feature_id="admission-boundary", operations=[Operation(name=name, arguments={})],
        runtime_epoch=epoch, adapter_fingerprint=fingerprint, created_at=time.time(), expires_at=time.time()+60)


def _unknown(root):
    secret = (root / "state" / "bridge.key").read_bytes()
    request = _request("animation.position_keys_set").model_dump(mode="json")
    request.update(session_id="original-session", nonce="original-nonce", mac="")
    request["mac"] = sign_payload(request, secret)
    directory = root / "state" / "request_records" / request["request_id"]
    persistence.publish_new(directory / "request.json", request)
    event = {"request_id": request["request_id"], "request_digest": admission.p.digest(request),
        "operation_digest": admission.p.digest(request["operations"]), "session_id": request["session_id"],
        "host_instance_id": request["host_instance_id"], "runtime_epoch": str(uuid.uuid4()),
        "seq": 1, "phase": "terminal", "outcome": "outcome_unknown", "dispatched": True,
        "run_id": None, "step_id": None, "attempt_id": None, "lease_epoch": None,
        "terminal_result": {"ok": False}, "result_digest": admission.p.digest({"ok": False}), "mac": ""}
    event["mac"] = sign_payload(event, secret)
    path = directory / "runtime_events" / "0001-terminal.json"
    persistence.publish_new(path, event)
    return request, path, path.read_bytes()


def test_two_domain_admission_and_bounded_diagnostic(tmp_path, monkeypatch):
    root, other = _fixture(tmp_path, monkeypatch)
    original, terminal_path, original_bytes = _unknown(other)
    queue = AtomicQueue(RuntimePaths.discover(root))
    denied = _request("system.capture_source", epoch="new-epoch", fingerprint="a"*64)
    with pytest.raises(admission.p.EvidenceUnavailable, match="AUTHORITATIVE_COMPLETION_OR_CONTAINMENT_REQUIRED"):
        queue.submit(denied)
    assert queue.ledger.read_request(denied.request_id) is not None
    assert not list(queue.paths.requests.glob("*.json"))
    assert not (queue.ledger.directory(denied.request_id) / "admission-v1.json").exists()

    diagnostic = _request("system.incident_diagnostic")
    queued = queue.submit(diagnostic)
    assert queued.is_file()
    assert (queue.ledger.directory(diagnostic.request_id) / "admission-v1.json").is_file()
    monkeypatch.setenv("CASCADEUR_MCP_ROOT", str(root))
    with loaded_bridge("_incident_boundary_bridge") as (runtime, _):
        # Any scene access would fail this exact bounded public execution path.
        def forbidden(*args, **kwargs):
            raise AssertionError("bounded diagnostic queried a scene")
        monkeypatch.setattr(runtime, "_scene_view", forbidden)
        monkeypatch.setattr(runtime, "scene_state", forbidden)
        assert runtime._drain_once(None, matching_scene_only=True) == (1, False)
        result = queue.ledger.read_receipt(diagnostic.request_id).terminal_result
        assert result["ok"] and result["outcome"] == "succeeded"
        assert result["result"]["diagnostic_scope"] == "bridge_metadata_only"
        assert result["result"]["incident_admission_v1"]["available"] is True
        # Same original request is observation-only, even if its sidecar vanishes.
        (queue.ledger.directory(diagnostic.request_id) / "admission-v1.json").unlink()
        assert runtime.execute_request(None, diagnostic.model_dump(mode="json")) == result
        # An old sender with a scene target and no sidecar is rejected before
        # scene-routing reads, source consumption or ordinary dispatch.
        legacy = _request("scene.summary").model_dump(mode="json")
        legacy.update(scene_id="untrusted-scene", session_id=queue.session_id, nonce="legacy-nonce-0123456789abcdef", mac="")
        legacy["mac"] = sign_payload(legacy, queue._secret)
        queue.ledger.create(legacy)
        persistence.publish_new(queue.paths.requests / "legacy.json", legacy)
        assert runtime._drain_once(None, matching_scene_only=True) == (1, False)
        rejected = queue.ledger.read_receipt(legacy["request_id"])
        assert rejected.outcome == "rejected_pre_dispatch" and rejected.dispatched is False
    assert terminal_path.read_bytes() == original_bytes
    assert [item["original"]["request_id"] for domain in inspect(root)["domains"]
            for item in domain["incidents"]] == [original["request_id"]]
    # Real append/reload must preserve the original terminal and keep an open
    # incident open. A changed event cannot be hidden by its trusted head.
    with persistence.locked_registry(root) as (_, stores):
        peer = next(s for s in stores if s.root == other)
        originals, _, _ = peer.original_snapshot(admission.classify)
        head = peer.append(admission.p.EventKind.REGISTER, originals[0],
            evidence=admission.PersistedEvidence(stores), classify=admission.classify)
        assert peer.journal().head == head and head.seq == 1
    assert next(d for d in inspect(root)["domains"] if d["incidents"])["incidents"][0]["disposition"] == "open"
    assert terminal_path.read_bytes() == original_bytes
    event_path = next((peer.directory / "events").glob("*.json"))
    event = persistence.read(event_path)
    event["body"]["seq"] = 2
    event_path.write_bytes(persistence.canonical(event))
    with pytest.raises(ValueError, match="JOURNAL_FILENAME_DIFFERS"):
        inspect(root)


def test_changed_head_and_copied_auth_domain_fail_closed(tmp_path, monkeypatch):
    root, other = _fixture(tmp_path, monkeypatch)
    queue = AtomicQueue(RuntimePaths.discover(root))
    request = _request("system.incident_diagnostic")
    queue.submit(request)
    active = persistence.IncidentStore(root)
    # A newly discovered peer unresolved effect invalidates the old sidecar.
    _unknown(other)
    with loaded_bridge("_incident_stale_bridge") as (runtime, _):
        native = importlib.import_module("_incident_stale_bridge.incident_admission")
        with pytest.raises(ValueError, match="STALE_OR_DIFFERENT"):
            native._validate(root, request.model_dump(mode="json"), claim=True)
    assert not (queue.ledger.directory(request.request_id) / "admission-claim-v1.json").exists()
    # Copying a secret into another directory must not create a second domain.
    duplicate = tmp_path / "duplicate"
    (duplicate / "state").mkdir(parents=True)
    (duplicate / "state" / "bridge.key").write_bytes(active.secret)
    with pytest.raises(ValueError, match="DUPLICATE_ACTIVE_AUTH_DOMAIN"):
        persistence.enroll_domains([root, other, duplicate])


@pytest.mark.parametrize("replace_parent", [False, True])
def test_exact_setup_dispatch_owns_parent_and_step_directory(tmp_path, monkeypatch, replace_parent):
    from cascadeur_complete.incident_setup import prepare, approve_local
    root, _ = _fixture(tmp_path, monkeypatch)
    queue = AtomicQueue(RuntimePaths.discover(root))
    monkeypatch.setenv("CASCADEUR_MCP_ROOT", str(root))
    with loaded_bridge("_finite_setup_bridge") as (runtime, _):
        guards = importlib.import_module("_finite_setup_bridge.guarded_runtime")
        native = importlib.import_module("_finite_setup_bridge.incident_admission")
        adapters = importlib.import_module("_finite_setup_bridge.native_adapters")
        models = importlib.import_module("_finite_setup_bridge.native_interpolation_qualification")
        writer = importlib.import_module("_finite_setup_bridge.native_independent_position")
        geometry = importlib.import_module("_finite_setup_bridge.native_geometry_qualification")
        for helper in (adapters.qualify_disposable, models.ensure_independent_models,
                       models.qualify_independent_models, writer.qualify_independent_position_writer,
                       geometry.qualify_geometry_calculation):
            with pytest.raises(ValueError, match="NATIVE_ADMISSION_CONTEXT_REQUIRED"):
                helper()
        workspace = root / "snapshots" / "approved-setup"
        prepared = prepare(root, ["setup.qualify_native_adapter"], guards.RUNTIME_EPOCH,
                           guards.LOADED_FINGERPRINT, workspace)
        approval = approve_local(root, prepared["plan_digest"])
        calls = []

        def finite_helper(*, include_scene_adapter):
            assert include_scene_adapter is False
            grant = native.assert_setup_admission("setup.qualify_native_adapter")
            path = Path(grant.workspace_path)
            assert path == workspace / "0" and path.parent.is_dir() and not path.exists()
            assert (grant.maximum_new_tabs, grant.maximum_casc_files) == (2, 5)
            calls.append(str(path))
            if replace_parent:
                workspace.rename(workspace.with_name("retained-original-workspace"))
                workspace.mkdir()
                # Same lexical approved path cannot substitute another directory.
                native.assert_setup_admission("setup.qualify_native_adapter")
            path.mkdir()
            native.assert_setup_admission("setup.qualify_native_adapter")
            return {"fixture_boundary_only": True}

        monkeypatch.setattr(adapters, "qualify_disposable", finite_helper)
        request = BridgeRequest(request_id=prepared["plan"]["plan_id"], feature_id="explicit_setup",
            operations=[Operation(name="setup.qualify_native_adapter", arguments={
                "plan_digest": prepared["plan_digest"], "operator_authorization": approval})],
            runtime_epoch=guards.RUNTIME_EPOCH, adapter_fingerprint=guards.LOADED_FINGERPRINT,
            created_at=time.time(), expires_at=time.time()+60)
        queue.submit(request)
        payload = request.model_dump(mode="json")
        result = runtime.execute_request(None, payload)
        if replace_parent:
            assert not result["ok"] and result["outcome"] == "outcome_unknown"
            assert "SETUP_PLAN_WORKSPACE_IDENTITY_CHANGED" in result["error_message"]
            assert not (workspace / "0").exists()
            # The approved workspace was already created. A retained failure
            # must not claim that writes never started, or certify completion.
            assert result["write_phase"] == "started"
        else:
            assert result["ok"] and result["outcome"] == "succeeded"
            assert result["write_phase"] == "completed"
        assert queue.ledger.read_receipt(request.request_id).terminal_result == result
        assert runtime.execute_request(None, payload) == result and len(calls) == 1
