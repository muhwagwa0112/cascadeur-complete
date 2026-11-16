"""Host-local incident inspection and retirement control.

Plans describe exact operations; preparing a plan neither approves nor executes
them. Legacy attempts without a producer/resource closure remain non-executable.
"""
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
import time
import threading
import uuid

from . import incident_policy as p
from . import incident_store as store
from .incident_admission import PersistedEvidence, classify, EVIDENCE_PURPOSE

PLAN_PURPOSE = b"cascadeur-complete/incident-retirement-plan/v1\0"
APPROVAL_PURPOSE = b"cascadeur-complete/incident-operator-approval/v1\0"
_CONTROL = threading.local()


def _projections(registry, stores):
    evidence = PersistedEvidence(stores)
    result = []
    for domain in stores:
        originals, unsealed, unresolved = domain.original_snapshot(classify)
        journal = domain.journal()
        result.append(p.project_domain(originals=originals, journal=journal,
            unsealed_effect_request_ids=unsealed, unresolved_set_digest=unresolved, evidence=evidence))
    return result


def inspect(root, request_ref=None):
    with store.locked_registry(root) as (registry, stores):
        projections = _projections(registry, stores)
        if request_ref is not None:
            store.exact(request_ref, p.OriginalRef.__dataclass_fields__)
        domains = []
        found = request_ref is None
        for value in projections:
            incidents = []
            for incident in value.incidents:
                if request_ref is not None and asdict(incident.original) != request_ref:
                    continue
                found = True
                incidents.append({"original": asdict(incident.original),
                    "observation": asdict(incident.observation) if incident.observation else None,
                    "retirement_plan": asdict(incident.retirement_plan) if incident.retirement_plan else None,
                    "retirement": asdict(incident.retirement) if incident.retirement else None,
                    "disposition": "retired_unresolved" if incident.retirement and not incident.observation else
                        incident.observation.observed_completion.value if incident.observation else "open"})
            domains.append({"head": asdict(value.head), "incidents": incidents,
                "unsealed_effect_request_ids": list(value.unsealed_effect_request_ids),
                "unresolved_set_digest": value.unresolved_set_digest})
        if not found:
            raise p.PolicyError("ORIGINAL_INCIDENT_NOT_FOUND_OR_DIFFERS")
        return {"schema_version": 1, "registry_digest": p.digest(registry), "domains": domains,
                "original_receipts_immutable": True}


def observe(root, request_ref, expected_incident_head, evidence_ref):
    with store.locked_registry(root) as (registry, stores):
        projections = _projections(registry, stores)
        evidence = PersistedEvidence(stores)
        matches = [(domain, projection, item) for domain, projection in zip(stores, projections)
                   for item in projection.incidents if asdict(item.original) == request_ref]
        if len(matches) != 1:
            raise p.PolicyError("ORIGINAL_INCIDENT_NOT_FOUND_OR_DIFFERS")
        domain, projection, incident = matches[0]
        if asdict(projection.head) != expected_incident_head:
            raise p.PolicyError("INCIDENT_HEAD_CHANGED")
        if len(evidence_ref) == 36:
            from .incident_native_evidence import ingest
            evidence_ref = ingest(stores, incident.original, evidence_ref)
        evidence.native_closure(evidence_ref, incident.original)  # Never register before proof validation.
        if not any(e.body.kind == p.EventKind.REGISTER and e.body.original == incident.original
                   for e in domain.journal().entries):
            domain.append(p.EventKind.REGISTER, incident.original, evidence=evidence, classify=classify)
        head = domain.append(p.EventKind.OBSERVE, incident.original, evidence_digest=evidence_ref,
                             evidence=evidence, classify=classify)
        return {"head": asdict(head), "original": asdict(incident.original), "original_terminal_modified": False}


def _owned_directory(path):
    candidate = Path(path).absolute()
    if candidate.exists():
        raise p.EvidenceUnavailable("NEW_WORKSPACE_MUST_NOT_ALREADY_EXIST")
    identity = store.physical_identity(candidate.parent)
    return {"path": str(candidate), "parent_identity": identity, "create": "exclusive_new_directory"}


def retirement_prepare(root, request_refs, baseline_ref, new_workspace):
    if not isinstance(request_refs, list) or not request_refs:
        raise p.PolicyError("EXACT_ORIGINAL_REFS_REQUIRED")
    with store.locked_registry(root) as (registry, stores):
        projections = _projections(registry, stores)
        selected = []
        for ref in request_refs:
            matches = [(domain, item) for domain, projection in zip(stores, projections)
                       for item in projection.incidents if asdict(item.original) == ref]
            if len(matches) != 1 or any(asdict(item.original) == ref for _, item in selected):
                raise p.PolicyError("ORIGINAL_INCIDENT_NOT_FOUND_DUPLICATED_OR_DIFFERS")
            selected.extend(matches)
        blockers, footprints, components = [], [], []
        for domain, incident in selected:
            # This record can only be emitted by a native producer that actually
            # observed the entire execution/consumer/resource closure. Legacy
            # PID inference from runtime epoch or process absence is forbidden.
            path = domain.directory / "producer-closures" / (incident.original.request_id + ".json")
            if not path.is_file():
                blockers.append({"request_id": incident.original.request_id,
                    "code": "ORIGINAL_PRODUCER_RESOURCE_CONSUMER_CLOSURE_UNAVAILABLE"})
                continue
            value = store.read(path)
            store.verify(value, domain.secret, b"cascadeur-complete/incident-producer-closure/v1\0")
            if value.get("original") != asdict(incident.original):
                raise p.PolicyError("PRODUCER_CLOSURE_ORIGINAL_DIFFERS")
            footprints.append({"request_id": incident.original.request_id, "manifest_digest": p.digest(value)})
            from .incident_resources import inspect_retirement_scope
            try:
                components.append(inspect_retirement_scope(value, incident.original, baseline_ref, new_workspace))
            except p.EvidenceUnavailable as exc:
                blockers.append({"request_id": incident.original.request_id,
                    "code": "PRODUCER_BASELINE_OR_PHYSICAL_CLOSURE_UNAVAILABLE", "detail": str(exc)})
        baseline = None
        if components:
            baseline = components[0]["baseline"]
            if any(c["baseline_digest"] != components[0]["baseline_digest"] for c in components):
                blockers.append({"code": "CROSS_DOMAIN_BASELINE_LINEAGE_DIFFERS"})
            identities = [(process["pid"], process["creation_time_100ns"])
                          for component in components for process in component["processes"]]
            if len(set(identities)) != len(identities):
                blockers.append({"code": "OVERLAPPING_PRODUCERS_REQUIRE_JOINT_CLOSURE"})
        workspace = None
        try:
            workspace = _owned_directory(new_workspace)
        except (OSError, ValueError) as exc:
            blockers.append({"code": "WORKSPACE_PHYSICAL_SEPARATION_UNAVAILABLE", "detail": str(exc)})
        plan = {"schema_version": 1, "plan_id": str(uuid.uuid4()), "created_at": time.time(),
            "expires_at": time.time()+300, "registry_digest": p.digest(registry),
            "heads": [asdict(value.head) for value in projections], "originals": request_refs,
            "snapshots": [{"domain": asdict(value.head.domain), "unresolved_set_digest": value.unresolved_set_digest,
                           "unsealed_effect_request_ids": list(value.unsealed_effect_request_ids)} for value in projections],
            "baseline": baseline, "new_workspace": workspace, "producer_resource_footprints": footprints,
            "components": components, "operations": [operation for component in components for operation in component["operations"]],
            "blockers": blockers, "executable": not blockers and len(components) == len(selected)}
        # No executable plan or approval token is manufactured from missing
        # OS/resource evidence. This immutable draft makes the gap reviewable.
        active = next(s for s in stores if s.root == Path(root).resolve())
        envelope = store.seal(plan, active.secret, PLAN_PURPOSE)
        digest = p.digest(envelope)
        store.publish_new(active.directory / "retirement-plans" / (digest+".json"), envelope)
        return {"plan_digest": digest, "plan": plan, "approval_required": plan["executable"],
                "status": "awaiting_exact_operator_approval" if plan["executable"] else "evidence_unavailable"}


def verify_approved_plan(stores, evidence_digest, original, payload):
    store.exact(payload, {"original", "plan_digest", "operator_authorization", "component"})
    if payload["original"] != asdict(original):
        raise p.PolicyError("APPROVED_RETIREMENT_ORIGINAL_DIFFERS")
    _, plan = _find_plan(stores, payload["plan_digest"])
    approval = _verify_operator(stores, payload["plan_digest"], plan, payload["operator_authorization"])
    component = payload["component"]
    if component not in plan["components"] or component["original"] != asdict(original):
        raise p.PolicyError("APPROVED_RETIREMENT_COMPONENT_DIFFERS")
    return p.ApprovedRetirementPlan(original, evidence_digest, payload["plan_digest"],
                                    p.digest(approval), p.digest(component["resources"]))


def verify_retirement_closure(stores, evidence_digest, plan, payload):
    store.exact(payload, {"original", "plan_digest", "approved_evidence_digest", "component", "os_receipt"})
    if (payload["original"] != asdict(plan.original) or payload["plan_digest"] != plan.plan_digest
            or payload["approved_evidence_digest"] != plan.evidence_digest):
        raise p.PolicyError("RETIREMENT_CLOSURE_PLAN_DIFFERS")
    _, outer = _find_plan(stores, plan.plan_digest)
    if payload["component"] not in outer["components"]:
        raise p.PolicyError("RETIREMENT_CLOSURE_COMPONENT_DIFFERS")
    from .incident_resources import verify_retirement_evidence
    checked = verify_retirement_evidence(payload["os_receipt"], payload["component"])
    if payload["os_receipt"]["approval_digest"] != plan.operator_approval_digest:
        raise p.PolicyError("OS_RECEIPT_APPROVAL_DIFFERS")
    return p.RetirementClosure(plan.original, evidence_digest, plan.plan_digest,
        checked["producer_set_digest"], checked["termination_evidence_digest"],
        checked["retired_resource_manifest_digest"], checked["quarantined_output_manifest_digest"])


def verify_workspace_separation(stores, evidence_digest, intent, retirements, payload):
    store.exact(payload, {"intent", "registry_digest", "heads", "retirement_evidence_digests", "resources"})
    if payload["intent"] != asdict(intent):
        raise p.PolicyError("SEPARATION_INTENT_DIFFERS")
    expected = tuple(sorted(r.evidence_digest for r in retirements))
    if tuple(sorted(payload["retirement_evidence_digests"])) != expected:
        raise p.PolicyError("SEPARATION_RETIREMENT_SET_DIFFERS")
    from .incident_resources import verify_separation
    verify_separation(payload["resources"], intent, retirements)
    heads = tuple(p.Head(p.DomainRef(**item["domain"]), item["seq"], item["event_digest"]) for item in payload["heads"])
    return p.SeparationClosure(evidence_digest, intent.request_digest, intent.operation_digest, intent.domain,
        intent.runtime_epoch, intent.workspace_generation_id, intent.baseline_digest,
        intent.resource_manifest_digest, payload["registry_digest"], heads, expected)


def _find_plan(stores, digest):
    p._digest_string(digest, "plan digest")
    matches = [(s, s.directory / "retirement-plans" / (digest+".json")) for s in stores]
    matches = [(s, path) for s, path in matches if path.is_file()]
    if len(matches) != 1:
        raise p.PolicyError("RETIREMENT_PLAN_UNAVAILABLE")
    domain, path = matches[0]
    plan = store.read(path); store.verify(plan, domain.secret, PLAN_PURPOSE)
    if p.digest(plan) != digest:
        raise p.PolicyError("RETIREMENT_PLAN_DIGEST_DIFFERS")
    return domain, plan


def _verify_operator(stores, digest, plan, authorization):
    store.exact(authorization, {"schema_version", "plan_digest", "registry_digest", "component_digests", "approved_at", "expires_at", "mac"})
    authority = next(s for s in stores if s.root == store.canonical_root())
    store.verify(authorization, authority.secret, APPROVAL_PURPOSE)
    if (authorization["schema_version"] != 1 or authorization["plan_digest"] != digest
            or authorization["registry_digest"] != plan["registry_digest"]
            or authorization["component_digests"] != [c["component_digest"] for c in plan["components"]]
            or authorization["expires_at"] != plan["expires_at"]
            or not plan["created_at"] <= authorization["approved_at"] < plan["expires_at"]
            or not plan["executable"] or plan["blockers"]):
        raise p.PolicyError("EXACT_OPERATOR_APPROVAL_DIFFERS")
    return authorization


def approve_retirement_local(root, plan_digest):
    """Operator command only, after review; never called automatically by MCP."""
    with store.locked_registry(root) as (registry, stores):
        _, plan = _find_plan(stores, plan_digest)
        if time.time() >= plan["expires_at"] or not plan["executable"] or plan["blockers"]:
            raise p.EvidenceUnavailable("RETIREMENT_PLAN_NOT_READY_FOR_OPERATOR_APPROVAL")
        authority = next(s for s in stores if s.root == store.canonical_root())
        approval = store.seal({"schema_version": 1, "plan_digest": plan_digest,
            "registry_digest": plan["registry_digest"], "component_digests": [c["component_digest"] for c in plan["components"]],
            "approved_at": time.time(), "expires_at": plan["expires_at"]}, authority.secret, APPROVAL_PURPOSE)
        _verify_operator(stores, plan_digest, plan, approval)
        return approval


def verify_component_operator_approval(component, authorization):
    """Private resource authority callback, valid only inside durable control."""
    context = getattr(_CONTROL, "retirement", None)
    if (context is None or context["component_digest"] != component["component_digest"]
            or context["authorization"] != authorization):
        raise p.EvidenceUnavailable("DURABLE_RETIREMENT_STARTED_CONTEXT_REQUIRED")
    if not context["observation_only"] and time.time() >= context["expires_at"]:
        raise p.EvidenceUnavailable("RETIREMENT_NEW_OS_EFFECT_AUTHORITY_EXPIRED")
    return context["operator_approval_digest"]


def _evidence_envelope(domain, kind, payload):
    return store.seal({"schema_version": 1, "kind": kind, "domain": asdict(domain.domain), "payload": payload},
                      domain.secret, EVIDENCE_PURPOSE)


def _publish_evidence(domain, kind, payload):
    value = _evidence_envelope(domain, kind, payload)
    digest = p.digest(value)
    target = domain.directory / "evidence" / (digest+".json")
    if target.exists():
        if store.read(target) != value:
            raise p.PolicyError("IMMUTABLE_INCIDENT_EVIDENCE_CONFLICT")
    else:
        store.publish_new(target, value)
    return digest


def _component_result_path(domain, plan_digest, component):
    p._digest_string(plan_digest, "retirement plan digest")
    component_digest = p._digest_string(component["component_digest"], "retirement component digest")
    return domain.directory / "retirement-results" / plan_digest / (component_digest + ".json")


def _validate_component_result(domain, plan_digest, approved_ref, component, approval, value):
    store.exact(value, {"schema_version", "kind", "domain", "payload", "mac"})
    store.verify(value, domain.secret, EVIDENCE_PURPOSE)
    payload = store.exact(value["payload"],
        {"original", "plan_digest", "approved_evidence_digest", "component", "os_receipt"})
    if (value["schema_version"] != 1 or value["kind"] != "retirement_component_result"
            or value["domain"] != asdict(domain.domain) or payload["original"] != component["original"]
            or payload["plan_digest"] != plan_digest or payload["approved_evidence_digest"] != approved_ref
            or payload["component"] != component or payload["os_receipt"].get("approval_digest") != p.digest(approval)):
        raise p.PolicyError("DURABLE_RETIREMENT_RESULT_BINDING_DIFFERS")
    from .incident_resources import verify_retirement_evidence
    verify_retirement_evidence(payload["os_receipt"], component)
    return payload


def _read_component_result(domain, plan_digest, approved_ref, component, approval):
    path = _component_result_path(domain, plan_digest, component)
    if not path.exists():
        return None
    store.physical_identity(path)
    return _validate_component_result(domain, plan_digest, approved_ref, component, approval, store.read(path))


def _retain_component_result(domain, plan_digest, approved_ref, component, approval, os_receipt):
    payload = {"original": component["original"], "plan_digest": plan_digest,
               "approved_evidence_digest": approved_ref, "component": component, "os_receipt": os_receipt}
    value = _evidence_envelope(domain, "retirement_component_result", payload)
    _validate_component_result(domain, plan_digest, approved_ref, component, approval, value)
    path = _component_result_path(domain, plan_digest, component)
    try:
        store.publish_new(path, value)
    except FileExistsError:
        previous = _read_component_result(domain, plan_digest, approved_ref, component, approval)
        if previous != payload:
            raise p.PolicyError("IMMUTABLE_RETIREMENT_RESULT_DIFFERS")
    return payload


def retirement_commit(root, plan_digest, operator_authorization):
    p._digest_string(plan_digest, "plan digest")
    with store.locked_registry(root) as (registry, stores):
        domain, plan = _find_plan(stores, plan_digest)
        projections = _projections(registry, stores)
        if (plan["registry_digest"] != p.digest(registry)
                or plan["snapshots"] != [{"domain": asdict(value.head.domain), "unresolved_set_digest": value.unresolved_set_digest,
                    "unsealed_effect_request_ids": list(value.unsealed_effect_request_ids)} for value in projections]):
            raise p.PolicyError("RETIREMENT_PLAN_EXPIRED_OR_SNAPSHOT_CHANGED")
        if not plan.get("executable") or plan.get("blockers"):
            raise p.EvidenceUnavailable("RETIREMENT_PLAN_NOT_EXECUTABLE: " +
                ",".join(item["code"] for item in plan["blockers"]))
        approval = _verify_operator(stores, plan_digest, plan, operator_authorization)
        selected = [(active, item, component) for active, projection in zip(stores, projections)
                    for item in projection.incidents for component in plan["components"]
                    if component["original"] == asdict(item.original)]
        if (not selected or len(selected) != len(plan["components"])
                or len({item.original for _, item, _ in selected}) != len(selected)
                or [component["original"] for component in plan["components"]] != plan["originals"]):
            raise p.PolicyError("RETIREMENT_SELECTED_COMPONENTS_DIFFER")
        approved = {}
        resuming = False
        for active, item, component in selected:
            ref = p.digest(_evidence_envelope(active, "approved_retirement_plan", {
                "original": asdict(item.original), "plan_digest": plan_digest,
                "operator_authorization": approval, "component": component}))
            approved[item.original] = ref
            if item.retirement_plan is not None:
                expected = p.ApprovedRetirementPlan(item.original, ref, plan_digest,
                    p.digest(approval), p.digest(component["resources"]))
                if item.retirement_plan != expected:
                    raise p.PolicyError("RETIREMENT_ALREADY_STARTED_WITH_DIFFERENT_APPROVAL")
                resuming = True
        if len(plan["heads"]) != len(stores):
            raise p.PolicyError("RETIREMENT_PLAN_HEAD_COVERAGE_DIFFERS")
        for active, projection, baseline_head in zip(stores, projections, plan["heads"]):
            journal = active.journal()
            seq = baseline_head["seq"]
            if (baseline_head["domain"] != asdict(active.domain) or type(seq) is not int
                    or not 0 <= seq <= len(journal.entries) or journal.head != projection.head):
                raise p.PolicyError("RETIREMENT_PLAN_HEAD_CHANGED")
            anchor = p.entry_digest(journal.entries[seq-1]) if seq else p.ZERO_DIGEST
            if anchor != baseline_head["event_digest"]:
                raise p.PolicyError("RETIREMENT_PLAN_HEAD_CHANGED")
            for event in journal.entries[seq:]:
                if (asdict(event.body.original) not in plan["originals"] or event.body.kind not in
                    (p.EventKind.REGISTER, p.EventKind.RETIRE_BEGIN, p.EventKind.RETIRE_COMMIT)
                        or event.body.kind != p.EventKind.REGISTER and event.body.plan_digest != plan_digest):
                    raise p.PolicyError("UNRELATED_INCIDENT_EVENT_AFTER_PLAN")
        if not resuming and plan["expires_at"] <= time.time():
            raise p.PolicyError("RETIREMENT_PLAN_EXPIRED_OR_SNAPSHOT_CHANGED")
        evidence = PersistedEvidence(stores)
        # Every domain is durably fenced before the first approved OS effect.
        fenced = resuming
        for active, item, component in selected:
            if not fenced and plan["expires_at"] <= time.time():
                raise p.PolicyError("RETIREMENT_PLAN_EXPIRED_OR_SNAPSHOT_CHANGED")
            ref = _publish_evidence(active, "approved_retirement_plan", {"original": asdict(item.original),
                "plan_digest": plan_digest, "operator_authorization": approval, "component": component})
            if ref != approved[item.original]:
                raise p.PolicyError("APPROVED_RETIREMENT_EVIDENCE_DIFFERS")
            if item.retirement_plan is not None:
                if item.retirement_plan.evidence_digest != ref:
                    raise p.PolicyError("RETIREMENT_ALREADY_STARTED_WITH_DIFFERENT_APPROVAL")
                continue
            if not any(e.body.kind == p.EventKind.REGISTER and e.body.original == item.original for e in active.journal().entries):
                active.append(p.EventKind.REGISTER, item.original, evidence=evidence, classify=classify)
            if not fenced and plan["expires_at"] <= time.time():
                raise p.PolicyError("RETIREMENT_PLAN_EXPIRED_OR_SNAPSHOT_CHANGED")
            active.append(p.EventKind.RETIRE_BEGIN, item.original, evidence_digest=ref, plan_digest=plan_digest,
                          evidence=evidence, classify=classify)
            fenced = True
        from .incident_resources import execute_approved_retirement, observe_approved_retirement
        results = []
        for active, item, component in selected:
            if item.retirement is not None:
                results.append(asdict(item.retirement))
                continue
            payload = _read_component_result(active, plan_digest, approved[item.original], component, approval)
            if payload is None:
                _CONTROL.retirement = {"component_digest": component["component_digest"],
                    "authorization": approval, "operator_approval_digest": p.digest(approval),
                    "observation_only": resuming, "expires_at": plan["expires_at"]}
                try:
                    executor = observe_approved_retirement if resuming else execute_approved_retirement
                    os_receipt = executor(component, approval)
                finally:
                    _CONTROL.retirement = None
                payload = _retain_component_result(active, plan_digest, approved[item.original], component, approval, os_receipt)
            ref = _publish_evidence(active, "retirement_closure", payload)
            active.append(p.EventKind.RETIRE_COMMIT, item.original, evidence_digest=ref, plan_digest=plan_digest,
                          evidence=evidence, classify=classify)
            results.append({"original": asdict(item.original), "evidence_digest": ref, "disposition": "retired_unresolved"})
        return {"plan_digest": plan_digest, "retirements": results, "original_terminals_modified": False,
                "new_work_requires_verified_separation": True}


class IncidentControlMixin:
    def incident_inspect(self, request_ref=None):
        return inspect(self.paths.root, request_ref)

    def incident_observe(self, request_ref, expected_incident_head, evidence_ref):
        return observe(self.paths.root, request_ref, expected_incident_head, evidence_ref)

    def incident_retirement_prepare(self, request_refs, baseline_ref, new_workspace):
        return retirement_prepare(self.paths.root, request_refs, baseline_ref, new_workspace)

    def incident_retirement_commit(self, plan_digest, operator_authorization):
        return retirement_commit(self.paths.root, plan_digest, operator_authorization)
