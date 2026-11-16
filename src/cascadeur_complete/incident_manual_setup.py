"""One reviewed legacy disposition for one fresh, bounded setup invocation.

The original incidents remain unknown/open. This is an explicit policy choice,
not native completion, process retirement, or a noninterference certificate.
No approval function is called by prepare or dispatch. Only the local operator
command can approve a concrete plan, after interactive review outside locks.
"""
from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
import sys
import time
import uuid

from . import incident_policy as p
from . import incident_store as store
from . import incident_setup as setup

ROUTE = "manual_legacy_setup_v1"
PLAN_PURPOSE = b"cascadeur-complete/manual-legacy-setup-plan/v1\0"
APPROVAL_PURPOSE = b"cascadeur-complete/manual-legacy-setup-approval/v1\0"
CLAIM_PURPOSE = b"cascadeur-complete/manual-legacy-setup-claim/v1\0"
LEGACY_IDS = frozenset(("ffb7fc8e-417c-454c-a669-48625a086eda",
                        "fcf3352a-483c-4f9c-bc18-8b61a58822eb"))
RESIDUALS = (
    "Original operation outcomes remain unknown.",
    "Historical producer and consumer termination is unproven.",
    "Historical affected resources and future interference are unproven.",
    "This authorizes one fresh fixture setup, not an old run retry or publication.",
)


def _active(root, stores):
    return next(value for value in stores if value.root == Path(root).resolve())


def _legacy_locked(registry, stores, *, request=None, active=None, projections=None,
                   reviewed_incident_ids=None):
    from .incident_admission import collect_snapshot_locked, projection_heads
    if projections is None:
        _, projections, _ = collect_snapshot_locked(registry, stores, request, active)
    incidents = [item for projection in projections for item in projection.incidents]
    if any(projection.unsealed_effect_request_ids for projection in projections):
        raise p.EvidenceUnavailable("MANUAL_SETUP_OTHER_UNSEALED_EFFECTS_REMAIN")
    expected = LEGACY_IDS
    if reviewed_incident_ids is not None:
        if (not isinstance(reviewed_incident_ids, list) or not reviewed_incident_ids
                or len(set(reviewed_incident_ids)) != len(reviewed_incident_ids)
                or any(not isinstance(value, str) or str(uuid.UUID(value)) != value
                       for value in reviewed_incident_ids)):
            raise p.PolicyError("MANUAL_SETUP_EXPLICIT_INCIDENT_IDS_REQUIRED")
        expected = frozenset(reviewed_incident_ids)
    if (len(incidents) != len(expected)
            or {item.original.request_id for item in incidents} != expected
            or any(item.observation is not None or item.retirement_plan is not None
                   or item.retirement is not None for item in incidents)):
        raise p.EvidenceUnavailable("MANUAL_SETUP_REVIEWED_OPEN_INCIDENT_SET_DIFFERS"
            if reviewed_incident_ids is not None else "MANUAL_SETUP_REQUIRES_EXACT_TWO_OPEN_LEGACY_INCIDENTS")
    originals = tuple(sorted((item.original for item in incidents),
                             key=lambda item: (item.domain, item.request_id)))
    return originals, projection_heads(projections)


def _read_setup(active, plan_digest):
    p._digest_string(plan_digest, "setup plan digest")
    plan = store.read(active.directory / "setup-plans" / (plan_digest + ".json"))
    store.verify(plan, active.secret, setup.PURPOSE)
    if p.digest(plan) != plan_digest or plan.get("schema_version") != 1:
        raise p.PolicyError("MANUAL_SETUP_PLAN_DIFFERS")
    setup.validate_helper_bytes(plan)
    return plan


def _stored_plan(active, plan_digest):
    p._digest_string(plan_digest, "manual setup plan digest")
    plan = store.read(active.directory / "manual-setup-plans" / (plan_digest + ".json"))
    store.verify(plan, active.secret, PLAN_PURPOSE)
    fields = {"schema_version", "purpose", "domain", "registry_digest", "heads",
        "originals", "setup_plan_digest", "setup_plan", "request_id", "operation_plan",
        "runtime_epoch", "loaded_fingerprint", "run_id", "workspace_generation_id",
        "baseline", "residuals", "created_at", "expires_at", "mac"}
    if plan.get("schema_version") == 2:
        fields.add("reviewed_incident_ids")
    store.exact(plan, fields)
    if (p.digest(plan) != plan_digest or plan["schema_version"] not in (1, 2)
            or plan["purpose"] != ROUTE or plan["domain"] != asdict(active.domain)
            or plan["residuals"] != list(RESIDUALS)):
        raise p.PolicyError("MANUAL_SETUP_STORED_PLAN_CHANGED")
    for field in ("request_id", "run_id", "workspace_generation_id"):
        if str(uuid.UUID(plan[field])) != plan[field]:
            raise p.PolicyError("MANUAL_SETUP_INVALID_NEW_IDENTIFIER")
    return plan


def _plan_locked(active, registry, stores, plan_digest, *, request=None, projections=None):
    plan = _stored_plan(active, plan_digest)
    if plan["registry_digest"] != p.digest(registry) or time.time() >= plan["expires_at"]:
        raise p.PolicyError("MANUAL_SETUP_PLAN_EXPIRED_OR_CHANGED")
    original_refs, heads = _legacy_locked(registry, stores, request=request, active=active,
        projections=projections, reviewed_incident_ids=plan.get("reviewed_incident_ids"))
    if plan["originals"] != [asdict(item) for item in original_refs] or plan["heads"] != heads:
        raise p.PolicyError("MANUAL_SETUP_LEGACY_HEADS_CHANGED")
    native_plan = _read_setup(active, plan["setup_plan_digest"])
    if (native_plan != plan["setup_plan"] or native_plan["registry_digest"] != plan["registry_digest"]
            or native_plan["heads"] != heads or native_plan["plan_id"] != plan["request_id"]
            or native_plan["runtime_epoch"] != plan["runtime_epoch"]
            or native_plan["loaded_fingerprint"] != plan["loaded_fingerprint"]
            or native_plan["expires_at"] != plan["expires_at"]):
        raise p.PolicyError("MANUAL_SETUP_BOUND_PLAN_CHANGED")
    expected_operation = [{"name": native_plan["steps"][0]["operation"],
        "arguments": {"plan_digest": plan["setup_plan_digest"]}}]
    if plan["operation_plan"] != expected_operation:
        raise p.PolicyError("MANUAL_SETUP_OPERATION_PLAN_CHANGED")
    expected_baseline = {"origin_kind": "owned_fixture_from_installed_setup",
        "setup_plan_digest": plan["setup_plan_digest"],
        "helper_files_digest": p.digest(native_plan["helper_files"])}
    if plan["baseline"] != expected_baseline:
        raise p.PolicyError("MANUAL_SETUP_BASELINE_CHANGED")
    if (plan["runtime_epoch"] in {item.original_runtime_epoch for item in original_refs}
            or plan["run_id"] in {item.original_run_id for item in original_refs}
            or plan["request_id"] in {item.request_id for item in original_refs}):
        raise p.PolicyError("MANUAL_SETUP_REQUIRES_NEW_RUNTIME_AND_RUN")
    parent = Path(native_plan["workspace"]).parent
    if (parent != active.root / "snapshots"
            or store.physical_identity(parent) != native_plan["workspace_parent_identity"]):
        raise p.PolicyError("MANUAL_SETUP_WORKSPACE_PARENT_CHANGED")
    return plan, original_refs


def _approval_locked(active, plan, plan_digest):
    value = store.read(active.directory / "manual-setup-approvals" / (plan_digest + ".json"))
    store.verify(value, active.secret, APPROVAL_PURPOSE)
    store.exact(value, {"schema_version", "purpose", "plan_digest", "domain", "approved_at",
        "expires_at", "setup_authorization", "assurance", "mac"})
    if (value["schema_version"] != 1 or value["purpose"] != ROUTE
            or value["plan_digest"] != plan_digest or value["domain"] != asdict(active.domain)
            or value["expires_at"] != plan["expires_at"]
            or not plan["created_at"] <= value["approved_at"] < plan["expires_at"]
            or value["assurance"] != "operator_accepted_unproven_legacy_interference"):
        raise p.PolicyError("MANUAL_SETUP_APPROVAL_DIFFERS")
    authorization = store.exact(value["setup_authorization"],
        {"schema_version", "plan_digest", "domain", "expires_at", "mac"})
    store.verify(authorization, active.secret, setup.APPROVAL)
    if (authorization["schema_version"] != 1
            or authorization["plan_digest"] != plan["setup_plan_digest"]
            or authorization["domain"] != asdict(active.domain)
            or authorization["expires_at"] != plan["expires_at"]):
        raise p.PolicyError("MANUAL_SETUP_INNER_APPROVAL_DIFFERS")
    return value


def _operations(plan, approval):
    return [{"name": plan["operation_plan"][0]["name"], "arguments": {
        "plan_digest": plan["setup_plan_digest"],
        "operator_authorization": approval["setup_authorization"]}}]


def _execution_context(plan, plan_digest):
    return {"run_id": plan["run_id"], "step_id": "bounded_setup",
        "workspace_generation_id": plan["workspace_generation_id"],
        "baseline_digest": p.digest(plan["baseline"]),
        "incident_route": {"kind": ROUTE, "plan_digest": plan_digest}}


def _match_request(plan, plan_digest, approval, request):
    """Authenticate an original request without requiring a fresh admission.

    Reconciliation may outlive the plan, bridge bytes or current epoch. Those
    changes never relax the immutable request's original approved binding.
    """
    if (request.get("request_id") != plan["request_id"] or request.get("feature_id") != "explicit_setup"
            or request.get("source_binding") is not None or request.get("scene_id") is not None
            or request.get("expected_revision") is not None
            or request.get("runtime_epoch") != plan["runtime_epoch"]
            or request.get("adapter_fingerprint") != plan["loaded_fingerprint"]
            or request.get("execution_context") != _execution_context(plan, plan_digest)
            or request.get("operations") != _operations(plan, approval)
            or not plan["created_at"] <= request["created_at"] < request["expires_at"] <= plan["expires_at"]):
        raise p.PolicyError("MANUAL_SETUP_EXACT_NEW_REQUEST_DIFFERS")


def prepare(root, steps, runtime_epoch, loaded_fingerprint, workspace, *, reviewed_incident_ids=None):
    """Persist a reviewable draft only; no setup authority or app mutation."""
    # Native source capture is unnecessary: all new fixture contents are the
    # exact installed helper program, and every helper keeps its existing guard.
    draft = setup._prepare_metadata_only(root, steps, runtime_epoch,
                                          loaded_fingerprint, workspace)
    with store.locked_registry(root) as (registry, stores):
        active = _active(root, stores)
        originals, heads = _legacy_locked(registry, stores, reviewed_incident_ids=reviewed_incident_ids)
        native_plan = _read_setup(active, draft["plan_digest"])
        if (heads != native_plan["heads"] or native_plan["registry_digest"] != p.digest(registry)
                or runtime_epoch in {item.original_runtime_epoch for item in originals}):
            raise p.PolicyError("MANUAL_SETUP_NEW_EPOCH_AND_UNCHANGED_LEGACY_REQUIRED")
        now = time.time()
        body = {"schema_version": 1, "purpose": ROUTE, "domain": asdict(active.domain),
            "registry_digest": p.digest(registry), "heads": heads,
            "originals": [asdict(item) for item in originals],
            "setup_plan_digest": draft["plan_digest"], "setup_plan": native_plan,
            "request_id": native_plan["plan_id"],
            "operation_plan": [{"name": native_plan["steps"][0]["operation"],
                "arguments": {"plan_digest": draft["plan_digest"]}}],
            "runtime_epoch": runtime_epoch, "loaded_fingerprint": loaded_fingerprint,
            "run_id": str(uuid.uuid4()), "workspace_generation_id": str(uuid.uuid4()),
            "baseline": {"origin_kind": "owned_fixture_from_installed_setup",
                "setup_plan_digest": draft["plan_digest"],
                "helper_files_digest": p.digest(native_plan["helper_files"])},
            "residuals": list(RESIDUALS), "created_at": now, "expires_at": native_plan["expires_at"]}
        if reviewed_incident_ids is not None:
            body.update(schema_version=2, reviewed_incident_ids=sorted(reviewed_incident_ids))
        sealed = store.seal(body, active.secret, PLAN_PURPOSE)
        plan_digest = p.digest(sealed)
        store.publish_new(active.directory / "manual-setup-plans" / (plan_digest + ".json"), sealed)
        return {"plan_digest": plan_digest, "plan": body, "approval_required": True,
            "admission_issued": False, "scope": "one_new_bounded_setup_only"}


def approve_local(root, plan_digest):
    """Local TTY review; the displayed plan is rechecked after reacquiring locks."""
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise p.PolicyError("MANUAL_SETUP_LOCAL_INTERACTIVE_OPERATOR_REQUIRED")
    with store.locked_registry(root) as (registry, stores):
        active = _active(root, stores)
        reviewed, _ = _plan_locked(active, registry, stores, plan_digest)
    print(json.dumps(reviewed, ensure_ascii=False, indent=2))
    print(f"기존 {len(reviewed['originals'])}건의 결과·종료·간섭 여부는 미증명입니다. 표시된 새 fixture setup 1회만 승인합니다.", file=sys.stderr)
    if input("승인할 plan SHA-256 전체를 입력: ").strip() != plan_digest:
        raise p.PolicyError("MANUAL_SETUP_NOT_APPROVED")
    with store.locked_registry(root) as (registry, stores):
        active = _active(root, stores)
        current, _ = _plan_locked(active, registry, stores, plan_digest)
        if current != reviewed or Path(current["setup_plan"]["workspace"]).exists():
            raise p.PolicyError("MANUAL_SETUP_PLAN_OR_WORKSPACE_CHANGED_DURING_REVIEW")
        approval = store.seal({"schema_version": 1, "purpose": ROUTE,
            "plan_digest": plan_digest, "domain": asdict(active.domain),
            "approved_at": time.time(), "expires_at": current["expires_at"],
            "setup_authorization": setup.approve_local(root, current["setup_plan_digest"]),
            "assurance": "operator_accepted_unproven_legacy_interference"},
            active.secret, APPROVAL_PURPOSE)
        store.publish_new(active.directory / "manual-setup-approvals" / (plan_digest + ".json"), approval)
        return {"plan_digest": plan_digest, "approval_digest": p.digest(approval),
            "scope": "one_new_bounded_setup_only", "original_incidents": "outcome_unknown/open"}


def disposition_locked(registry, stores, request, active, *, native=False,
                       bind_claim=False, require_claim=False, projections=None):
    """Resolve authenticated policy choice while the caller holds registry locks."""
    context = request.get("execution_context") or {}
    reference = context.get("incident_route")
    if reference is None:
        return None
    store.exact(reference, {"kind", "plan_digest"})
    if reference["kind"] != ROUTE:
        raise p.PolicyError("UNSUPPORTED_INCIDENT_POLICY_ROUTE")
    store.verify_original(request, active.secret)
    plan_digest = p._digest_string(reference["plan_digest"], "manual setup plan digest")
    plan, originals = _plan_locked(active, registry, stores, plan_digest, request=request,
                                    projections=projections)
    approval = _approval_locked(active, plan, plan_digest)
    if native:
        from . import guarded_runtime as guards
        epoch, fingerprint = guards.RUNTIME_EPOCH, guards.LOADED_FINGERPRINT
    else:
        epoch, fingerprint = request.get("runtime_epoch"), request.get("adapter_fingerprint")
    _match_request(plan, plan_digest, approval, request)
    if (request.get("runtime_epoch") != epoch or epoch != plan["runtime_epoch"]
            or request.get("adapter_fingerprint") != fingerprint or fingerprint != plan["loaded_fingerprint"]):
        raise p.PolicyError("MANUAL_SETUP_EXACT_NEW_REQUEST_DIFFERS")
    claim_body = {"schema_version": 1, "purpose": ROUTE, "plan_digest": plan_digest,
        "request_id": request["request_id"], "request_digest": p.digest(request),
        "operation_digest": p.digest(request["operations"]), "approval_digest": p.digest(approval)}
    path = active.directory / "manual-setup-claims" / (plan_digest + ".json")
    if path.exists():
        value = store.read(path)
        store.verify(value, active.secret, CLAIM_PURPOSE)
        if {key: value for key, value in value.items() if key != "mac"} != claim_body:
            raise p.PolicyError("MANUAL_SETUP_ALREADY_BOUND_TO_DIFFERENT_REQUEST")
    elif bind_claim:
        if Path(plan["setup_plan"]["workspace"]).exists():
            raise p.PolicyError("MANUAL_SETUP_WORKSPACE_ALREADY_EXISTS")
        store.publish_new(path, store.seal(claim_body, active.secret, CLAIM_PURPOSE))
    elif require_claim:
        raise p.PolicyError("MANUAL_SETUP_DURABLE_REQUEST_CLAIM_REQUIRED")
    return p.ManualLegacyDisposition(plan_digest, p.digest(request), p.digest(request["operations"]),
        active.domain, epoch, fingerprint, context["workspace_generation_id"],
        context["baseline_digest"], context["run_id"], originals)


def _runtime_client(root):
    from .bridge_client import BridgeClient
    from .models import Operation
    from .paths import RuntimePaths
    client = BridgeClient(paths=RuntimePaths.discover(Path(root)))
    result = client.execute("incident_diagnostic", [Operation(name="system.incident_diagnostic", arguments={})])
    status = client.runtime_status
    if (not result.ok or result.outcome != "succeeded" or status.get("diagnostic_scope") != "bridge_metadata_only"
            or not status.get("runtime_epoch") or status.get("adapter_fingerprint") != client.expected_adapter_fingerprint):
        raise p.EvidenceUnavailable("MANUAL_SETUP_AUTHENTICATED_RUNTIME_DIAGNOSTIC_REQUIRED")
    return client


def prepare_with_runtime(root, steps, workspace, *, reviewed_incident_ids=None):
    """Read only the existing signed runtime diagnostic, then create a draft."""
    client = _runtime_client(root)
    return prepare(root, steps, client.runtime_status["runtime_epoch"],
        client.runtime_status["adapter_fingerprint"], workspace,
        reviewed_incident_ids=reviewed_incident_ids)


def dispatch(root, plan_digest):
    """Send the approved exact request via the normal outbox/admission route once."""
    from .models import Operation
    # Read approvals under locks, then release them before any bridge wait.
    with store.locked_registry(root) as (registry, stores):
        active = _active(root, stores)
        plan = _stored_plan(active, plan_digest)
        approval = _approval_locked(active, plan, plan_digest)
        operations = [Operation(**value) for value in _operations(plan, approval)]
        context = _execution_context(plan, plan_digest)
        # An expired plan or a new incident cannot prevent observation of a
        # previously published request. Neither path can republish that request.
        existing = active.state / "request_records" / plan["request_id"] / "request.json"
        already_submitted = existing.is_file()
        if already_submitted:
            original = store.read(existing)
            store.verify_original(original, active.secret)
            _match_request(plan, plan_digest, approval, original)
        else:
            plan, _ = _plan_locked(active, registry, stores, plan_digest)
    from .bridge_client import BridgeClient
    from .paths import RuntimePaths
    if already_submitted:
        client = BridgeClient(paths=RuntimePaths.discover(Path(root)))
        return client.reconcile_request(plan["request_id"]).model_dump(mode="json")
    client = _runtime_client(root)
    if (client.runtime_status["runtime_epoch"] != plan["runtime_epoch"]
            or client.runtime_status["adapter_fingerprint"] != plan["loaded_fingerprint"]):
        raise p.PolicyError("MANUAL_SETUP_RUNTIME_CHANGED_BEFORE_DISPATCH")
    remaining = plan["expires_at"] - time.time() - 1.0
    if remaining <= 0:
        raise p.PolicyError("MANUAL_SETUP_PLAN_EXPIRED_BEFORE_DISPATCH")
    return client.execute("explicit_setup", operations, request_id=plan["request_id"],
        timeout=min(120.0, remaining), execution_context=context).model_dump(mode="json")
