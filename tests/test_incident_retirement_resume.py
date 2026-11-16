"""Retirement control only: authenticated temporary journals, no OS executor."""
from dataclasses import asdict
from types import SimpleNamespace

import pytest

from cascadeur_complete import incident_control as control
from cascadeur_complete import incident_resources as resources
from cascadeur_complete import incident_store as store
from cascadeur_complete import incident_policy as p
from tests.test_incident_admission import _fixture, _unknown


def test_started_retirement_expiry_resumes_evidence_without_os_replay(tmp_path, monkeypatch):
    root, peer_root = _fixture(tmp_path, monkeypatch)
    _, terminal_path, terminal_bytes = _unknown(root)
    _unknown(peer_root)
    clock = [1000.0]
    monkeypatch.setattr(control, "time", SimpleNamespace(time=lambda: clock[0]))
    with store.locked_registry(root) as (registry, domains):
        projections = control._projections(registry, domains)
        active = next(s for s in domains if s.root == root)
        original = active.original_snapshot(control.classify)[0][0]
        component = {"component_digest": "c" * 64, "original": asdict(original), "resources": []}
        plan = {"schema_version": 1, "created_at": 990.0, "expires_at": 1010.0,
            "registry_digest": p.digest(registry), "heads": [asdict(v.head) for v in projections],
            "snapshots": [{"domain": asdict(v.head.domain), "unresolved_set_digest": v.unresolved_set_digest,
                           "unsealed_effect_request_ids": list(v.unsealed_effect_request_ids)} for v in projections],
            "originals": [asdict(original)], "components": [component], "executable": True, "blockers": []}
        envelope = store.seal(plan, active.secret, control.PLAN_PURPOSE)
        plan_digest = p.digest(envelope)
        store.publish_new(active.directory / "retirement-plans" / (plan_digest + ".json"), envelope)
    approval = control.approve_retirement_local(root, plan_digest)

    def forbidden_executor(*args, **kwargs):
        pytest.fail("retirement control attempted a fresh OS effect")

    monkeypatch.setattr(resources, "execute_approved_retirement", forbidden_executor)
    monkeypatch.setattr(resources, "_EXECUTIONS", {})
    clock[0] = 1020.0
    with pytest.raises(p.PolicyError, match="PLAN_EXPIRED"):
        control.retirement_commit(root, plan_digest, approval)

    # Persist a genuine control fence/approval. This is not OS completion proof.
    with store.locked_registry(root) as (_, domains):
        active = next(s for s in domains if s.root == root)
        evidence = control.PersistedEvidence(domains)
        approved_ref = control._publish_evidence(active, "approved_retirement_plan", {
            "original": asdict(original), "plan_digest": plan_digest,
            "operator_authorization": approval, "component": component})
        active.append(p.EventKind.REGISTER, original, evidence=evidence, classify=control.classify)
        active.append(p.EventKind.RETIRE_BEGIN, original, evidence_digest=approved_ref,
                      plan_digest=plan_digest, evidence=evidence, classify=control.classify)

    # The real observation-only function rejects its absent private attempt
    # before touching any Win32 handle. Stub only scope validation for this
    # control fixture; its deliberately minimal component is not an OS plan.
    monkeypatch.setattr(resources, "_validate_plan", lambda value: (value, None))
    for now in (1005.0, 1020.0):
        clock[0] = now
        with pytest.raises(p.EvidenceUnavailable, match="ATTEMPT_OBSERVATION_UNAVAILABLE"):
            control.retirement_commit(root, plan_digest, approval)
    changed_approval = store.seal({k: (1001.0 if k == "approved_at" else v)
        for k, v in approval.items() if k != "mac"},
        (root / "state" / "bridge.key").read_bytes(), control.APPROVAL_PURPOSE)
    with pytest.raises(p.PolicyError, match="DIFFERENT_APPROVAL"):
        control.retirement_commit(root, plan_digest, changed_approval)

    # The OS verifier is a boundary fixture, not an asserted real termination.
    # Actual envelope MAC/path and journal append/reload remain exercised.
    receipt = {"approval_digest": p.digest(approval), "fixture": "not_native_evidence"}
    def checked_receipt(value, bound_component):
        assert value == receipt and bound_component == component
        return {"producer_set_digest": "1" * 64, "termination_evidence_digest": "2" * 64,
                "retired_resource_manifest_digest": p.digest([]),
                "quarantined_output_manifest_digest": "3" * 64}
    monkeypatch.setattr(resources, "verify_retirement_evidence", checked_receipt)
    with store.locked_registry(root) as (_, domains):
        active = next(s for s in domains if s.root == root)
        control._retain_component_result(active, plan_digest, approved_ref, component, approval, receipt)
    monkeypatch.setattr(resources, "observe_approved_retirement", forbidden_executor)
    result = control.retirement_commit(root, plan_digest, approval)
    assert result["retirements"][0]["disposition"] == "retired_unresolved"
    assert control.retirement_commit(root, plan_digest, approval)["retirements"]
    assert terminal_path.read_bytes() == terminal_bytes

    # An unrelated authenticated suffix still invalidates the original heads.
    with store.locked_registry(root) as (_, domains):
        peer = next(s for s in domains if s.root == peer_root)
        peer_original = peer.original_snapshot(control.classify)[0][0]
        peer.append(p.EventKind.REGISTER, peer_original,
                    evidence=control.PersistedEvidence(domains), classify=control.classify)
    with pytest.raises(p.PolicyError, match="UNRELATED_INCIDENT_EVENT"):
        control.retirement_commit(root, plan_digest, approval)
