"""Immutable sidecar admission shared with the embedded runtime (Python 3.11).

No request/receipt schema is changed. Admission is a separate, short-lived,
single-use authority over a complete locked registry snapshot.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import threading
import time
import uuid

from . import incident_policy as p
from . import incident_store as store

ADMISSION_PURPOSE = b"cascadeur-complete/incident-admission/v1\0"
ADMISSION_V2_PURPOSE = b"cascadeur-complete/incident-admission/v2\0"
CLAIM_PURPOSE = b"cascadeur-complete/incident-admission-claim/v1\0"
EVIDENCE_PURPOSE = b"cascadeur-complete/incident-evidence/v1\0"
_LOCAL = threading.local()
SETUP_IDS = {"setup.qualify_native_adapter": (2, 5),
             "setup.qualify_independent_models": (1, 2),
             "setup.qualify_independent_position_writer": (1, 2),
             "setup.qualify_geometry_calculation": (1, 2)}


class PersistedEvidence:
    """Load only evidence issued by the appropriate code-owned producer.

    This verifier authenticates immutable evidence and exact identities. Native
    completion is additionally tied to the original attempt's private validator;
    it cannot be imported from client JSON or reconstructed after process loss.
    """
    def __init__(self, stores):
        self.stores = tuple(stores)

    def _read(self, evidence_digest, kind):
        p._digest_string(evidence_digest, "evidence digest")
        matches = []
        for domain in self.stores:
            path = domain.directory / "evidence" / (evidence_digest + ".json")
            if path.is_file():
                value = store.read(path)
                store.exact(value, {"schema_version", "kind", "domain", "payload", "mac"})
                store.verify(value, domain.secret, EVIDENCE_PURPOSE)
                if (p.digest(value) != evidence_digest or value["schema_version"] != 1
                        or value["kind"] != kind or value["domain"] != asdict(domain.domain)):
                    raise p.PolicyError("EVIDENCE_PURPOSE_OR_IDENTITY_DIFFERS")
                matches.append((domain, value["payload"]))
        if len(matches) != 1:
            raise p.EvidenceUnavailable("INDEPENDENT_EVIDENCE_UNAVAILABLE: " + kind)
        return matches[0]

    def native_closure(self, evidence_digest, original):
        domain, payload = self._read(evidence_digest, "native_closure")
        if domain.domain != original.domain or payload.get("original") != asdict(original):
            raise p.PolicyError("ORIGINAL_ATTEMPT_DIFFERS")
        # Live private closure revalidation is mandatory, not a persisted boolean.
        if Path(__file__).with_name("guarded_runtime.py").is_file():
            from .native_incident_observation import verify_persisted_closure
        else:
            from .incident_native_evidence import verify_persisted_closure
        return verify_persisted_closure(self.stores, evidence_digest, original, payload)

    def approved_plan(self, evidence_digest, original):
        _, payload = self._read(evidence_digest, "approved_retirement_plan")
        if payload.get("original") != asdict(original):
            raise p.PolicyError("RETIREMENT_ORIGINAL_DIFFERS")
        from .incident_control import verify_approved_plan
        return verify_approved_plan(self.stores, evidence_digest, original, payload)

    def retirement_closure(self, evidence_digest, plan):
        _, payload = self._read(evidence_digest, "retirement_closure")
        from .incident_control import verify_retirement_closure
        return verify_retirement_closure(self.stores, evidence_digest, plan, payload)

    def diagnostic_closure(self, evidence_digest, intent):
        if intent.kind != p.WorkKind.NATIVE_DIAGNOSTIC or evidence_digest != diagnostic_digest():
            raise p.EvidenceUnavailable("UNVERIFIED_DIAGNOSTIC_READER")
        return p.DiagnosticClosure(evidence_digest, intent.request_digest, intent.operation_digest,
            intent.runtime_epoch, intent.loaded_fingerprint, diagnostic_digest(), p.digest([]))

    def separation_closure(self, evidence_digest, intent, retirements):
        _, payload = self._read(evidence_digest, "workspace_separation")
        from .incident_control import verify_workspace_separation
        return verify_workspace_separation(self.stores, evidence_digest, intent, retirements, payload)


def diagnostic_digest():
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def diagnostic_request(request):
    operations = request.get("operations")
    if operations == [{"name": "system.incident_diagnostic", "arguments": {}}]:
        return True
    if not isinstance(operations, list) or len(operations) != 1:
        return False
    op = operations[0]
    if op.get("name") != "system.incident_observe_original":
        return False
    args = op.get("arguments")
    if not isinstance(args, dict) or set(args) != {"original"}:
        return False
    original = args["original"]
    if not isinstance(original, dict) or set(original) != set(p.OriginalRef.__dataclass_fields__):
        return False
    domain = original.get("domain")
    return isinstance(domain, dict) and set(domain) == {"auth_domain_id", "store_instance_id"}


def classify(request):
    from .incident_effects import classify_effect
    return any(classify_effect(op["name"], op.get("arguments")) != "none" for op in request["operations"])


def intent_for(request, domain):
    operations = request["operations"]
    names = [op["name"] for op in operations]
    if diagnostic_request(request):
        kind = p.WorkKind.NATIVE_DIAGNOSTIC
    elif len(names) == 1 and names[0] in SETUP_IDS:
        kind = p.WorkKind.EXPLICIT_SETUP
    elif "system.capture_source" in names or "system.rebind_source" in names:
        kind = p.WorkKind.SOURCE_CAPTURE
    elif any(name == "animation.interpolation_refresh" or name == "animation.transform_get"
             and op.get("arguments", {}).get("refresh") for name, op in zip(names, operations)):
        kind = p.WorkKind.EVALUATION
    else:
        kind = p.WorkKind.EFFECT if classify(request) else p.WorkKind.SCENE_READ
    context = request.get("execution_context") or {}
    return p.WorkIntent(domain, request["request_id"], p.digest(request), p.digest(operations),
        request.get("runtime_epoch") or "unbound", request.get("adapter_fingerprint") or "unbound",
        kind, p.digest({"operations": operations, "source": request.get("source_binding")}),
        context.get("workspace_generation_id"), context.get("baseline_digest"), context.get("run_id"))


def collect_snapshot_locked(registry, stores, request=None, active=None):
    """Read complete projections under the caller's existing registry locks."""
    evidence = PersistedEvidence(stores)
    projections = []
    for domain in stores:
        excluded = (active.domain, request["request_id"], p.digest(request)) if request is not None else None
        originals, unsealed, unresolved = domain.original_snapshot(classify, exclude=excluded)
        journal = domain.journal()
        projection = p.project_domain(originals=originals, journal=journal,
            unsealed_effect_request_ids=unsealed, unresolved_set_digest=unresolved, evidence=evidence)
        # Recover a verified crash suffix only after semantic validation.
        projections.append(projection)
    registry_snapshot = p.RegistrySnapshot(p.digest(registry), tuple(s.domain for s in stores))
    return evidence, tuple(projections), registry_snapshot


def projection_heads(projections):
    return [{"head": asdict(item.head), "unresolved_set_digest": item.unresolved_set_digest}
            for item in sorted(projections, key=lambda item: item.head.domain)]


def _manual_disposition_locked(registry, stores, request, active, **options):
    if (request.get("execution_context") or {}).get("incident_route") is None:
        return None
    route = (request.get("execution_context") or {})["incident_route"]
    from .incident_manual_setup import ROUTE as SETUP_ROUTE
    from .incident_pair_continuation import ROUTE as PAIR_ROUTE
    if route.get("kind") == SETUP_ROUTE:
        from .incident_manual_setup import disposition_locked
    elif route.get("kind") == PAIR_ROUTE:
        from .incident_pair_continuation import disposition_locked
    else:
        raise p.PolicyError("UNSUPPORTED_INCIDENT_POLICY_ROUTE")
    return disposition_locked(registry, stores, request, active, **options)


def snapshot(registry, stores, request, active, *, native=False, require_manual_claim=False):
    evidence, projections, registry_snapshot = collect_snapshot_locked(registry, stores, request, active)
    intent = intent_for(request, active.domain)
    manual = _manual_disposition_locked(registry, stores, request, active,
        native=native, require_claim=require_manual_claim, projections=projections)
    decision = p.decide(intent=intent, registry=registry_snapshot, domains=projections, evidence=evidence,
        manual_disposition=manual,
        diagnostic_evidence_digest=diagnostic_digest() if diagnostic_request(request) else None,
        separation_evidence_digest=(request.get("execution_context") or {}).get("separation_evidence_digest"))
    if decision.verdict not in (p.Verdict.NEW_WORK_CANDIDATE, p.Verdict.DIAGNOSTIC_CANDIDATE):
        raise p.EvidenceUnavailable(decision.reason + ": " + ",".join(decision.incident_request_ids))
    return intent, projection_heads(projections)


def _sidecar_format(request):
    route = (request.get("execution_context") or {}).get("incident_route")
    if route is None:
        return "admission-v1.json", ADMISSION_PURPOSE, "admission-claim-v1.json"
    from .incident_manual_setup import ROUTE as SETUP_ROUTE
    from .incident_pair_continuation import ROUTE as PAIR_ROUTE
    store.exact(route, {"kind", "plan_digest"})
    if route["kind"] not in (SETUP_ROUTE, PAIR_ROUTE):
        raise p.PolicyError("UNSUPPORTED_INCIDENT_POLICY_ROUTE")
    p._digest_string(route["plan_digest"], "manual setup plan digest")
    return "admission-v2.json", ADMISSION_V2_PURPOSE, "admission-claim-v2.json"


def _body(request, active, registry, intent, heads):
    body = {"schema_version": 1, "purpose": "incident_admission_v1", "domain": asdict(active.domain),
        "registry_digest": p.digest(registry), "request_id": request["request_id"],
        "request_digest": p.digest(request), "operation_digest": p.digest(request["operations"]),
        "runtime_epoch": request.get("runtime_epoch"), "loaded_fingerprint": request.get("adapter_fingerprint"),
        "source_digest": p.digest(request["source_binding"]) if request.get("source_binding") is not None else None,
        "safety_context_digest": p.digest(request.get("safety_context") or {}), "heads": heads,
        "resource_manifest_digest": intent.resource_manifest_digest,
        "workspace_generation_id": intent.workspace_generation_id, "baseline_digest": intent.baseline_digest,
        "separation_evidence_digest": (request.get("execution_context") or {}).get("separation_evidence_digest"),
        "work_kind": intent.kind.value, "expires_at": request["expires_at"]}
    route = (request.get("execution_context") or {}).get("incident_route")
    if route is not None:
        body.update(schema_version=2, purpose="incident_admission_v2", policy_route=route)
    return body


def issue(root, request):
    # Caller has already durably published the signed immutable outbox.
    with store.locked_registry(root) as (registry, stores):
        active = next(s for s in stores if s.root == Path(root).resolve())
        store.verify_original(request, active.secret)
        original = store.read(active.state / "request_records" / request["request_id"] / "request.json")
        if original != request:
            raise p.PolicyError("IMMUTABLE_OUTBOX_DIFFERS")
        intent, heads = snapshot(registry, stores, request, active)
        if intent.kind != p.WorkKind.NATIVE_DIAGNOSTIC and (not request.get("runtime_epoch") or not request.get("adapter_fingerprint")):
            raise p.EvidenceUnavailable("INCIDENT_ADMISSION_RUNTIME_HANDSHAKE_REQUIRED")
        setup = _setup_plan(active, request, registry, heads) if intent.kind == p.WorkKind.EXPLICIT_SETUP else None
        filename, purpose, _ = _sidecar_format(request)
        # The manual step binds only after all original/setup checks pass.
        _manual_disposition_locked(registry, stores, request, active, bind_claim=True)
        value = store.seal({**_body(request, active, registry, intent, heads), "setup": setup, "ticket": str(uuid.uuid4())},
                           active.secret, purpose)
        store.publish_new(active.state / "request_records" / request["request_id"] / filename, value)
        return value


def _validate(root, request, *, claim=False, require_claim=True):
    with store.locked_registry(root) as (registry, stores):
        active = next(s for s in stores if s.root == Path(root).resolve())
        store.verify_original(request, active.secret)
        directory = active.state / "request_records" / request["request_id"]
        if store.read(directory / "request.json") != request:
            raise p.PolicyError("IMMUTABLE_OUTBOX_DIFFERS")
        filename, purpose, claim_filename = _sidecar_format(request)
        value = store.read(directory / filename)
        store.verify(value, active.secret, purpose)
        intent, heads = snapshot(registry, stores, request, active,
            native=True, require_manual_claim=True)
        expected = _body(request, active, registry, intent, heads)
        store.exact(value, set(expected) | {"ticket", "mac", "setup"})
        if any(value[k] != v for k, v in expected.items()) or time.time() >= value["expires_at"]:
            raise p.PolicyError("STALE_OR_DIFFERENT_INCIDENT_ADMISSION")
        if str(uuid.UUID(value["ticket"])) != value["ticket"]:
            raise p.PolicyError("INVALID_ADMISSION_TICKET")
        if not diagnostic_request(request):
            from . import guarded_runtime as guards
            if request.get("runtime_epoch") != guards.RUNTIME_EPOCH or request.get("adapter_fingerprint") != guards.LOADED_FINGERPRINT:
                raise p.PolicyError("INCIDENT_ADMISSION_RUNTIME_DIFFERS")
            from .native_completion import assert_epoch_usable
            assert_epoch_usable()
        expected_setup = _setup_plan(active, request, registry, heads) if intent.kind == p.WorkKind.EXPLICIT_SETUP else None
        if value["setup"] != expected_setup:
            raise p.PolicyError("SETUP_APPROVAL_OR_PLAN_DIFFERS")
        if claim and expected_setup is not None and Path(expected_setup["workspace"]).exists():
            raise p.PolicyError("SETUP_WORKSPACE_ALREADY_EXISTS_BEFORE_CLAIM")
        claimed = store.seal({"schema_version": 1, "ticket": value["ticket"],
                              "admission_digest": p.digest(value), "request_digest": p.digest(request)},
                             active.secret, CLAIM_PURPOSE)
        if claim:
            store.publish_new(directory / claim_filename, claimed)
        elif require_claim and store.read(directory / claim_filename) != claimed:
            raise p.PolicyError("ADMISSION_CLAIM_DIFFERS")
        return value


def validate_unclaimed(root, request):
    """Routing preview: validate authority without consuming its ticket."""
    return _validate(root, request, require_claim=False)


@contextmanager
def admitted_request(root, request):
    if getattr(_LOCAL, "request", None) is not None:
        raise p.PolicyError("NESTED_ADMISSION_FORBIDDEN")
    value = _validate(root, request, claim=True)
    _LOCAL.request = (Path(root), request, threading.get_ident())
    try:
        yield value
    finally:
        _LOCAL.request = None
        _LOCAL.setup = None


def assert_request_admission():
    current = getattr(_LOCAL, "request", None)
    if current is None or current[2] != threading.get_ident():
        raise p.PolicyError("NATIVE_ADMISSION_CONTEXT_REQUIRED")
    return _validate(current[0], current[1])


@dataclass(frozen=True)
class VerifiedSetupStepGrant:
    workspace_path: str
    maximum_new_tabs: int
    maximum_casc_files: int
    maximum_geometry_calculations: int | None = None
    maximum_evaluations: int | None = None
    maximum_driver_mutations: int | None = None


def assert_setup_admission(setup_id, setup_invocation_ref=None):
    # Only dispatcher-created, same-thread private contexts can reach qualifiers.
    assert_request_admission()
    context = getattr(_LOCAL, "setup", None)
    if (setup_id not in SETUP_IDS or context is None or context["step"] != setup_id
            or setup_invocation_ref is not None and setup_invocation_ref != context["invocation_ref"]
            or not isinstance(context["grant"], VerifiedSetupStepGrant)):
        raise p.EvidenceUnavailable("AUTHENTICATED_SETUP_INVOCATION_REQUIRED")
    if store.physical_identity(context["plan_workspace"]) != context["plan_workspace_identity"]:
        raise p.PolicyError("SETUP_PLAN_WORKSPACE_IDENTITY_CHANGED")
    workspace = Path(context["grant"].workspace_path)
    if workspace.parent != Path(context["plan_workspace"]):
        raise p.PolicyError("SETUP_STEP_OUTSIDE_PLAN_WORKSPACE")
    if workspace.exists():
        identity = store.physical_identity(workspace)
        if context.get("workspace_identity") is None:
            context["workspace_identity"] = identity
        elif context["workspace_identity"] != identity:
            raise p.PolicyError("SETUP_WORKSPACE_IDENTITY_CHANGED")
    elif context.get("workspace_identity") is not None:
        raise p.PolicyError("SETUP_WORKSPACE_REMOVED")
    source_guard = context.get("source_guard")
    if source_guard is not None:
        source_guard()
    return context["grant"]


def _bind_setup_source_guard(setup_id, guard):
    """Install the retained helper's private original-scene guard once.

    No caller-supplied callable crosses a wire boundary. Fixture callbacks use
    this same guard through assert_current_setup_admission, independently of
    the ordinary guarded_runtime request/source context.
    """
    assert_setup_admission(setup_id)
    context = _LOCAL.setup
    if not callable(guard) or context.get("source_guard") is not None:
        raise p.PolicyError("SETUP_SOURCE_GUARD_ALREADY_BOUND_OR_INVALID")
    guard()
    context["source_guard"] = guard


def assert_current_setup_admission():
    context = getattr(_LOCAL, "setup", None)
    if context is None:
        raise p.EvidenceUnavailable("AUTHENTICATED_SETUP_INVOCATION_REQUIRED")
    return assert_setup_admission(context["step"])


def _setup_plan(active, request, registry, heads):
    from .incident_setup import validate_setup_plan
    return validate_setup_plan(active, request, registry, heads)


def dispatch_setup(request, sidecar):
    """The sole fixture setup dispatcher; no queue/menu duplicate execution."""
    from . import guarded_runtime as guards
    from .incident_setup import validate_helper_bytes
    if getattr(_LOCAL, "setup", None) is not None:
        raise p.PolicyError("NESTED_SETUP_INVOCATION_FORBIDDEN")
    plan = sidecar.get("setup")
    if not isinstance(plan, dict):
        raise p.PolicyError("SETUP_PLAN_REQUIRED")
    validate_helper_bytes(plan)
    # The exact fresh plan directory is an approved effect. Each helper owns
    # one finite child, so its fixture paths remain under runtime snapshots.
    assert_request_admission()
    plan_workspace = Path(plan["workspace"])
    plan_workspace.mkdir()
    plan_workspace_identity = store.physical_identity(plan_workspace)
    results = []
    try:
        for step in plan["steps"]:
            setup_id = step["operation"]
            _LOCAL.setup = {"step": setup_id, "invocation_ref": request["request_id"],
                "workspace_identity": None, "source_guard": None,
                "plan_workspace": str(plan_workspace), "plan_workspace_identity": plan_workspace_identity,
                "grant": VerifiedSetupStepGrant(step["workspace_path"], step["maximum_new_tabs"],
                    step["maximum_casc_files"], **(step["semantic_limits"] or {}))}
            assert_setup_admission(setup_id)
            if setup_id == "setup.qualify_native_adapter":
                from .native_adapters import qualify_disposable
                result = qualify_disposable(include_scene_adapter=False)
            elif setup_id == "setup.qualify_independent_models":
                from .native_interpolation_qualification import ensure_independent_models
                result = ensure_independent_models()
            elif setup_id == "setup.qualify_independent_position_writer":
                from .native_independent_position import qualify_independent_position_writer
                result = qualify_independent_position_writer()
            elif setup_id == "setup.qualify_geometry_calculation":
                from .native_geometry_qualification import qualify_geometry_calculation
                result = qualify_geometry_calculation()
            else:
                raise p.PolicyError("UNKNOWN_SETUP_HELPER")
            results.append({"operation": setup_id, "result": result})
        return results
    finally:
        _LOCAL.setup = None


def capability(root, runtime_epoch, fingerprint):
    try:
        with store.locked_registry(root) as (registry, stores):
            return {"schema_version": 1, "capability": "incident_admission_v1", "available": True,
                    "runtime_epoch": runtime_epoch, "loaded_fingerprint": fingerprint,
                    "registry_digest": p.digest(registry), "domains": [asdict(s.domain) for s in stores]}
    except (OSError, ValueError, RuntimeError) as exc:
        return {"schema_version": 1, "capability": "incident_admission_v1", "available": False,
                "runtime_epoch": runtime_epoch, "loaded_fingerprint": fingerprint,
                "reason": str(exc)}
