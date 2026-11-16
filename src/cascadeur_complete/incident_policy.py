"""Pure incident projection and admission decisions used by both runtimes.

NOT A PRODUCT ADAPTER, OS VERIFIER, OR AUTHORIZATION ISSUER. No file, process,
network, SDK, queue, or native operation is performed. A *_CANDIDATE result is
not an executable permit. Product code must still verify its original request,
source binding, confirmation, resource handles, loaded bytes and epoch.

VerifiedEvidenceSource is a trusted in-process boundary, NOT a wire interface.
There is deliberately no default implementation, fake proof, boolean completion
flag, or automatic conversion of a caller's dictionary into verified evidence.
An implementation must independently verify the evidence described in
docs/implementation/cascadeur-motion-r5/incident/INTEGRATION.md.
Python type names and HMACs do not prove native semantics.

Standard library only; Python 3.11+. No native or product execution.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from enum import Enum
import hashlib
import hmac
import json
from typing import Protocol, Sequence


ZERO_DIGEST = "0" * 64
JOURNAL_SCHEMA = 1
JOURNAL_PURPOSE = b"cascadeur-complete/incident-journal/v1\0"
DOMAIN_PURPOSE = b"cascadeur-complete/incident-auth-domain/v1\0"


class PolicyError(ValueError):
    """No candidate may be issued after this error."""


class EvidenceUnavailable(PolicyError):
    """The trusted verifier cannot establish the requested proposition."""


def _digest_string(value: object, field: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(
        c not in "0123456789abcdef" for c in value
    ):
        raise PolicyError(f"Invalid {field}")
    return value


def _canonical(value: object) -> bytes:
    # The product decoder must also reject duplicate JSON members before this.
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def auth_domain_id(original_bridge_secret: bytes) -> str:
    """A copied key is the SAME auth domain; a new path is not a new domain."""
    if not isinstance(original_bridge_secret, bytes) or len(original_bridge_secret) < 32:
        raise PolicyError("Original bridge key unavailable")
    return hmac.new(original_bridge_secret, DOMAIN_PURPOSE, hashlib.sha256).hexdigest()


@dataclass(frozen=True, order=True)
class DomainRef:
    auth_domain_id: str
    store_instance_id: str


@dataclass(frozen=True, order=True)
class Head:
    domain: DomainRef
    seq: int
    event_digest: str


@dataclass(frozen=True)
class OriginalRef:
    """Constructed only from the original authenticated terminal unknown chain."""
    domain: DomainRef
    request_id: str
    request_digest: str
    operation_digest: str
    terminal_payload_digest: str
    terminal_bytes_digest: str
    original_runtime_epoch: str
    original_run_id: str | None


class EventKind(str, Enum):
    REGISTER = "incident_registered"
    OBSERVE = "authoritative_observation_recorded"
    RETIRE_BEGIN = "retirement_started"
    RETIRE_COMMIT = "retirement_committed"


@dataclass(frozen=True)
class JournalBody:
    schema_version: int
    domain: DomainRef
    seq: int
    previous_event_digest: str
    kind: EventKind
    original: OriginalRef
    evidence_digest: str | None = None
    plan_digest: str | None = None


@dataclass(frozen=True)
class JournalEntry:
    body: JournalBody
    mac: str


def entry_digest(entry: JournalEntry) -> str:
    """The next link covers the entire prior envelope, including its MAC."""
    return digest(asdict(entry))


def _journal_key(original_bridge_secret: bytes, domain: DomainRef) -> bytes:
    if auth_domain_id(original_bridge_secret) != domain.auth_domain_id:
        raise PolicyError("Wrong original authentication domain")
    material = JOURNAL_PURPOSE + _canonical(asdict(domain))
    return hmac.new(original_bridge_secret, material, hashlib.sha256).digest()


def seal_new_entry(body: JournalBody, original_bridge_secret: bytes) -> JournalEntry:
    """Reference encoding for NEW journal events, never for original receipts.

    The product writer calls this only after verifying the semantic transition
    under its writer lock. The MAC alone does not validate that transition.
    """
    if (type(body.schema_version) is not int or body.schema_version != JOURNAL_SCHEMA
            or type(body.seq) is not int or body.seq < 1 or body.domain != body.original.domain):
        raise PolicyError("Journal schema/domain mismatch")
    mac = hmac.new(_journal_key(original_bridge_secret, body.domain),
                   _canonical(asdict(body)), hashlib.sha256).hexdigest()
    return JournalEntry(body, mac)


@dataclass(frozen=True)
class VerifiedJournal:
    """Internal result of verify_chain; never deserialize this type from wire."""
    head: Head
    entries: tuple[JournalEntry, ...]


def verify_chain(entries: Sequence[JournalEntry], *, original_bridge_secret: bytes,
                 expected_head: Head) -> VerifiedJournal:
    """Verify a complete snapshot against a trusted, locked head anchor.

    Detects gaps, reordering, changed payloads, wrong keys/domains and a suffix
    differing from the supplied anchor. It cannot itself prove that an anchor
    has not been rolled back; see the persistence boundary in INTEGRATION.md.
    """
    if type(expected_head.seq) is not int or expected_head.seq < 0:
        raise PolicyError("Invalid head sequence")
    _digest_string(expected_head.event_digest, "head digest")
    key = _journal_key(original_bridge_secret, expected_head.domain)
    previous = ZERO_DIGEST
    frozen = tuple(entries)
    for seq, entry in enumerate(frozen, 1):
        body = entry.body
        if (type(body.schema_version) is not int or body.schema_version != JOURNAL_SCHEMA
                or type(body.seq) is not int or body.seq != seq
                or body.domain != expected_head.domain or body.original.domain != body.domain
                or body.previous_event_digest != previous):
            raise PolicyError("Journal identity, sequence or predecessor differs")
        for name in ("request_digest", "operation_digest", "terminal_payload_digest",
                     "terminal_bytes_digest"):
            _digest_string(getattr(body.original, name), name)
        _digest_string(entry.mac, "journal MAC")
        expected = hmac.new(key, _canonical(asdict(body)), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(entry.mac, expected):
            raise PolicyError("Journal authentication failed")
        previous = entry_digest(entry)
    if expected_head.seq != len(frozen) or expected_head.event_digest != previous:
        raise PolicyError("Journal does not match the anchored head")
    return VerifiedJournal(expected_head, frozen)


class ObservedCompletion(str, Enum):
    NO_EFFECT = "proved_no_effect"
    SUCCEEDED = "proved_completed_success"
    FAILED = "proved_completed_failure"


@dataclass(frozen=True)
class NativeClosure:
    original: OriginalRef
    evidence_digest: str
    observed_completion: ObservedCompletion
    producer_completion_digest: str
    actual_effect_closure_digest: str
    actual_after_digest: str | None


@dataclass(frozen=True)
class ApprovedRetirementPlan:
    original: OriginalRef
    evidence_digest: str
    plan_digest: str
    operator_approval_digest: str
    proposed_resource_manifest_digest: str


@dataclass(frozen=True)
class RetirementClosure:
    original: OriginalRef
    evidence_digest: str
    plan_digest: str
    producer_set_digest: str
    termination_evidence_digest: str
    retired_resource_manifest_digest: str
    quarantined_output_manifest_digest: str


class WorkKind(str, Enum):
    NATIVE_DIAGNOSTIC = "bounded_native_diagnostic"
    EXPLICIT_SETUP = "explicit_setup"
    SOURCE_CAPTURE = "source_capture"
    SCENE_READ = "scene_read"
    EVALUATION = "evaluation"
    EFFECT = "effect"


@dataclass(frozen=True)
class WorkIntent:
    """Code-owned classification of a signed request, never a caller opt-out."""
    domain: DomainRef
    request_id: str
    request_digest: str
    operation_digest: str
    runtime_epoch: str
    loaded_fingerprint: str
    kind: WorkKind
    resource_manifest_digest: str
    workspace_generation_id: str | None
    baseline_digest: str | None
    run_id: str | None


@dataclass(frozen=True)
class DiagnosticClosure:
    evidence_digest: str
    request_digest: str
    operation_digest: str
    runtime_epoch: str
    loaded_fingerprint: str
    code_owned_reader_digest: str
    maximum_read_set_digest: str


@dataclass(frozen=True)
class SeparationClosure:
    evidence_digest: str
    request_digest: str
    operation_digest: str
    domain: DomainRef
    runtime_epoch: str
    workspace_generation_id: str
    baseline_digest: str
    resource_manifest_digest: str
    registry_digest: str
    heads: tuple[Head, ...]
    retirement_evidence_digests: tuple[str, ...]


class VerifiedEvidenceSource(Protocol):
    """Trusted implementation is intentionally outside this pure reference.

    Methods must verify real evidence, not accept an operator's assertions.
    Native closure requires original-attempt completion/effect evidence.
    Retirement requires producer termination and resource containment.
    Separation resolves real file identities/aliases and immutable baseline
    provenance. Unknown coverage raises EvidenceUnavailable.
    """

    def native_closure(self, evidence_digest: str, original: OriginalRef) -> NativeClosure: ...

    def approved_plan(self, evidence_digest: str, original: OriginalRef) -> ApprovedRetirementPlan: ...

    def retirement_closure(self, evidence_digest: str,
                           plan: ApprovedRetirementPlan) -> RetirementClosure: ...

    def diagnostic_closure(self, evidence_digest: str, intent: WorkIntent) -> DiagnosticClosure: ...

    def separation_closure(self, evidence_digest: str, intent: WorkIntent,
                           retirements: tuple[RetirementClosure, ...]) -> SeparationClosure: ...


@dataclass(frozen=True)
class Incident:
    original: OriginalRef
    observation: NativeClosure | None = None
    retirement_plan: ApprovedRetirementPlan | None = None
    retirement: RetirementClosure | None = None


@dataclass(frozen=True)
class DomainProjection:
    head: Head
    incidents: tuple[Incident, ...]
    # Other pending/missing-terminal effects are not silently omitted. V1 does
    # not purport to retire those using a terminal-unknown incident contract.
    unsealed_effect_request_ids: tuple[str, ...]
    unresolved_set_digest: str


def _bound_evidence(actual: object, expected_type: type, original: OriginalRef,
                    evidence_digest: str) -> None:
    if (not isinstance(actual, expected_type)
            or getattr(actual, "original", None) != original
            or getattr(actual, "evidence_digest", None) != evidence_digest):
        raise PolicyError("Evidence is not bound to this original request")
    _digest_string(evidence_digest, "evidence digest")


def project_domain(*, originals: Sequence[OriginalRef], journal: VerifiedJournal,
                   unsealed_effect_request_ids: Sequence[str], unresolved_set_digest: str,
                   evidence: VerifiedEvidenceSource) -> DomainProjection:
    """Reduce a verified snapshot without altering an original receipt.

    `originals` and the unresolved digest must come from a complete authenticated
    RequestLedger snapshot, excluding only the exact proposed request itself.
    Unregistered legacy terminal unknowns start OPEN, never implicitly cleared.
    """
    by_id: dict[str, Incident] = {}
    for original in originals:
        if original.domain != journal.head.domain or original.request_id in by_id:
            raise PolicyError("Original request domain/identity differs")
        by_id[original.request_id] = Incident(original)
    registered: set[str] = set()
    for entry in journal.entries:
        body = entry.body
        current = by_id.get(body.original.request_id)
        if current is None or current.original != body.original:
            raise PolicyError("Journal references a missing or different original")
        if body.kind == EventKind.REGISTER:
            if body.original.request_id in registered or body.evidence_digest or body.plan_digest:
                raise PolicyError("Invalid registration event")
            registered.add(body.original.request_id)
            continue
        if body.original.request_id not in registered or body.evidence_digest is None:
            raise PolicyError("Unregistered transition or missing evidence")
        if body.kind == EventKind.OBSERVE:
            if body.plan_digest is not None or current.observation is not None:
                raise PolicyError("Duplicate/invalid completion observation")
            proof = evidence.native_closure(body.evidence_digest, current.original)
            _bound_evidence(proof, NativeClosure, current.original, body.evidence_digest)
            if proof.observed_completion not in tuple(ObservedCompletion):
                raise PolicyError("No authoritative completion disposition")
            _digest_string(proof.producer_completion_digest, "producer completion evidence")
            _digest_string(proof.actual_effect_closure_digest, "actual effect closure")
            if proof.observed_completion != ObservedCompletion.NO_EFFECT or proof.actual_after_digest is not None:
                _digest_string(proof.actual_after_digest, "actual after digest")
            # Recording a late observation NEVER removes an existing retirement.
            current = replace(current, observation=proof)
        elif body.kind == EventKind.RETIRE_BEGIN:
            if current.retirement_plan is not None or current.retirement is not None:
                raise PolicyError("Retirement already started")
            plan = evidence.approved_plan(body.evidence_digest, current.original)
            _bound_evidence(plan, ApprovedRetirementPlan, current.original, body.evidence_digest)
            if not body.plan_digest or plan.plan_digest != body.plan_digest:
                raise PolicyError("Approved retirement plan differs")
            _digest_string(plan.operator_approval_digest, "operator approval")
            current = replace(current, retirement_plan=plan)
        elif body.kind == EventKind.RETIRE_COMMIT:
            plan = current.retirement_plan
            if plan is None or current.retirement is not None or body.plan_digest != plan.plan_digest:
                raise PolicyError("Retirement has no matching pending plan")
            proof = evidence.retirement_closure(body.evidence_digest, plan)
            _bound_evidence(proof, RetirementClosure, current.original, body.evidence_digest)
            if (proof.plan_digest != plan.plan_digest
                    or proof.retired_resource_manifest_digest != plan.proposed_resource_manifest_digest):
                raise PolicyError("Retirement scope differs from approval")
            current = replace(current, retirement=proof)
        else:
            raise PolicyError("Unsupported incident event")
        by_id[current.original.request_id] = current
    _digest_string(unresolved_set_digest, "unresolved set digest")
    return DomainProjection(journal.head, tuple(by_id[k] for k in sorted(by_id)),
                            tuple(sorted(set(unsealed_effect_request_ids))), unresolved_set_digest)


@dataclass(frozen=True)
class RegistrySnapshot:
    """Verified enrollment of supported auth domains and physical stores.

    This registry is supplied by the installation/control authority, not by
    CASCADEUR_MCP_ROOT or a client-provided list of convenient roots.
    """
    registry_digest: str
    required_domains: tuple[DomainRef, ...]


class Verdict(str, Enum):
    DENY = "deny"
    OBSERVE_ORIGINAL_ONLY = "observe_original_only"
    DIAGNOSTIC_CANDIDATE = "diagnostic_only_candidate"
    NEW_WORK_CANDIDATE = "new_work_candidate"


@dataclass(frozen=True)
class Decision:
    verdict: Verdict
    reason: str
    incident_request_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class ManualLegacyDisposition:
    """Authenticated local policy choice; never native or OS closure evidence."""
    plan_digest: str
    request_digest: str
    operation_digest: str
    domain: DomainRef
    runtime_epoch: str
    loaded_fingerprint: str
    workspace_generation_id: str
    baseline_digest: str
    run_id: str
    originals: tuple[OriginalRef, ...]
    work_kind: WorkKind = WorkKind.EXPLICIT_SETUP


def decide(*, intent: WorkIntent, registry: RegistrySnapshot,
           domains: Sequence[DomainProjection], evidence: VerifiedEvidenceSource,
           diagnostic_evidence_digest: str | None = None,
           separation_evidence_digest: str | None = None,
           manual_disposition: ManualLegacyDisposition | None = None) -> Decision:
    """Pure decision; does not sign, persist, or consume an admission sidecar.

    Product caller must perform it on locked snapshots, then bind the candidate
    to the original signed request. Native repeats the binding/head/footprint
    checks at dispatch and before the first write. Any PolicyError means deny.
    """
    projections = tuple(domains)
    actual_domains = tuple(sorted(d.head.domain for d in projections))
    required = tuple(sorted(registry.required_domains))
    if (not required or len(set(required)) != len(required)
            or len(set(actual_domains)) != len(actual_domains)
            or actual_domains != required or intent.domain not in required):
        return Decision(Verdict.DENY, "AUTH_DOMAIN_COVERAGE_UNAVAILABLE")
    _digest_string(registry.registry_digest, "registry digest")
    heads = tuple(sorted((d.head for d in projections), key=lambda h: h.domain))
    incidents = tuple(item for domain in projections for item in domain.incidents)
    for item in incidents:
        original = item.original
        if original.domain != intent.domain and original.request_id == intent.request_id:
            return Decision(Verdict.DENY, "INCIDENT_REQUEST_ID_REUSED_ACROSS_DOMAINS", (original.request_id,))
        if original.domain == intent.domain and original.request_id == intent.request_id:
            if original.request_digest != intent.request_digest:
                return Decision(Verdict.DENY, "REQUEST_ID_CONFLICT", (original.request_id,))
            return Decision(Verdict.OBSERVE_ORIGINAL_ONLY, "IMMUTABLE_REQUEST_NEVER_REDISPATCHED",
                            (original.request_id,))
    if intent.kind == WorkKind.NATIVE_DIAGNOSTIC:
        if diagnostic_evidence_digest is None:
            return Decision(Verdict.DENY, "NONMUTATING_DIAGNOSTIC_READER_UNVERIFIED")
        proof = evidence.diagnostic_closure(diagnostic_evidence_digest, intent)
        if (not isinstance(proof, DiagnosticClosure)
                or proof.evidence_digest != diagnostic_evidence_digest
                or proof.request_digest != intent.request_digest
                or proof.operation_digest != intent.operation_digest
                or proof.runtime_epoch != intent.runtime_epoch
                or proof.loaded_fingerprint != intent.loaded_fingerprint):
            return Decision(Verdict.DENY, "DIAGNOSTIC_BINDING_MISMATCH")
        return Decision(Verdict.DIAGNOSTIC_CANDIDATE, "NO_SOURCE_TOKEN_EVALUATION_OR_WRITE")
    if intent.kind not in (WorkKind.EXPLICIT_SETUP, WorkKind.SOURCE_CAPTURE, WorkKind.SCENE_READ,
                           WorkKind.EVALUATION, WorkKind.EFFECT):
        return Decision(Verdict.DENY, "UNSUPPORTED_OPERATION_CLASS")
    unsealed = tuple(sorted({rid for d in projections for rid in d.unsealed_effect_request_ids}))
    if unsealed:
        return Decision(Verdict.DENY, "OTHER_UNSEALED_EFFECTS_REMAIN", unsealed)
    pending = tuple(i.original.request_id for i in incidents
                    if i.retirement_plan is not None and i.retirement is None)
    if pending:
        return Decision(Verdict.DENY, "RETIREMENT_NOT_DURABLY_COMPLETE", pending)
    unresolved = tuple(i.original.request_id for i in incidents
                       if i.observation is None and i.retirement is None)
    if intent.run_id is not None and any(i.original.original_run_id == intent.run_id for i in incidents):
        return Decision(Verdict.DENY, "ORIGINAL_INCIDENT_RUN_NOT_AUTOMATICALLY_RESUMABLE")
    if unresolved and manual_disposition is not None:
        choice = manual_disposition
        exact_open = tuple(i.original for i in incidents if i.observation is None and i.retirement is None)
        if (not isinstance(choice, ManualLegacyDisposition) or intent.kind != choice.work_kind
                or len(incidents) != len(exact_open)
                or sorted(digest(asdict(i)) for i in exact_open) != sorted(digest(asdict(i)) for i in choice.originals)
                or choice.request_digest != intent.request_digest or choice.operation_digest != intent.operation_digest
                or choice.domain != intent.domain or choice.runtime_epoch != intent.runtime_epoch
                or choice.loaded_fingerprint != intent.loaded_fingerprint or choice.run_id != intent.run_id
                or choice.workspace_generation_id != intent.workspace_generation_id
                or choice.baseline_digest != intent.baseline_digest):
            return Decision(Verdict.DENY, "MANUAL_LEGACY_SETUP_BINDING_DIFFERS", unresolved)
        _digest_string(choice.plan_digest, "manual setup plan digest")
        return Decision(Verdict.NEW_WORK_CANDIDATE,
            "MANUAL_LEGACY_RISK_ACCEPTED_EXACT_SETUP_GUARDS_STILL_REQUIRED", unresolved)
    if unresolved:
        return Decision(Verdict.DENY, "AUTHORITATIVE_COMPLETION_OR_CONTAINMENT_REQUIRED", unresolved)
    retired = tuple(i.retirement for i in incidents if i.retirement is not None)
    if retired:
        if (intent.workspace_generation_id is None or intent.baseline_digest is None
                or separation_evidence_digest is None):
            return Decision(Verdict.DENY, "NEW_WORKSPACE_BASELINE_AND_SEPARATION_REQUIRED")
        if any(p.original.original_runtime_epoch == intent.runtime_epoch for p in retired):
            return Decision(Verdict.DENY, "RETIRED_RUNTIME_EPOCH")
        proof = evidence.separation_closure(separation_evidence_digest, intent, retired)
        expected_retirements = tuple(sorted(p.evidence_digest for p in retired))
        if (not isinstance(proof, SeparationClosure)
                or proof.evidence_digest != separation_evidence_digest
                or proof.request_digest != intent.request_digest
                or proof.operation_digest != intent.operation_digest
                or proof.domain != intent.domain or proof.runtime_epoch != intent.runtime_epoch
                or proof.workspace_generation_id != intent.workspace_generation_id
                or proof.baseline_digest != intent.baseline_digest
                or proof.resource_manifest_digest != intent.resource_manifest_digest
                or proof.registry_digest != registry.registry_digest
                or tuple(sorted(proof.heads, key=lambda h: h.domain)) != heads
                or tuple(sorted(proof.retirement_evidence_digests)) != expected_retirements):
            return Decision(Verdict.DENY, "WORKSPACE_SEPARATION_BINDING_MISMATCH")
    return Decision(Verdict.NEW_WORK_CANDIDATE, "EXISTING_OPERATION_AUTHORIZATION_AND_NATIVE_GUARDS_STILL_REQUIRED")
