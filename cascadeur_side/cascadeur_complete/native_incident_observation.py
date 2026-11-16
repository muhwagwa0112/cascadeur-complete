"""Bounded original-attempt completion observation, with no scene/SDK access.

A wire reference indexes an existing private original attempt. It never supplies
the proposition being proved, a replacement source, or recovery authority.
"""

from dataclasses import asdict
import hashlib
import uuid

from . import incident_policy as p
from . import incident_store as store

EVIDENCE_PURPOSE = b"cascadeur-complete/incident-evidence/v1\0"
OBSERVER_CONTRACT = "retained_original_attempt_closure_v1"
_OBSERVATION_FIELDS = {"schema_version", "kind", "original", "diagnostic_request_id",
    "diagnostic_request_digest", "diagnostic_operation_digest", "observer_contract",
    "observer_implementation_digest", "observation_ref", "producer_completion_digest",
    "closure"}
_CLOSURE_FIELDS = {"request_digest", "operation_digest", "original_source_digest",
    "runtime_epoch", "loaded_fingerprint", "installed_build", "callback_generation",
    "private_record_digest", "observed_completion", "actual_effect_closure_digest",
    "actual_after_digest", "native_contract_evidence_digest"}


def _uuid(value):
    if not isinstance(value, str) or str(uuid.UUID(value)) != value:
        raise p.PolicyError("INVALID_ORIGINAL_OR_DIAGNOSTIC_ID")
    return value


def _original(value):
    if isinstance(value, p.OriginalRef):
        value = asdict(value)
    fields = dict(store.exact(value, p.OriginalRef.__dataclass_fields__))
    domain = p.DomainRef(**store.exact(fields["domain"], p.DomainRef.__dataclass_fields__))
    p._digest_string(domain.auth_domain_id, "auth domain")
    _uuid(domain.store_instance_id)
    for key in ("request_digest", "operation_digest", "terminal_payload_digest", "terminal_bytes_digest"):
        p._digest_string(fields[key], key)
    _uuid(fields["request_id"])
    _uuid(fields["original_runtime_epoch"])
    if fields["original_run_id"] is not None and (not isinstance(fields["original_run_id"], str) or not fields["original_run_id"]):
        raise p.PolicyError("INVALID_ORIGINAL_RUN_ID")
    return p.OriginalRef(**dict(fields, domain=domain))


def _bounded(path):
    store.physical_identity(path)
    with path.open("rb") as stream:
        raw = stream.read(8 * 1024 * 1024 + 1)
    if len(raw) > 8 * 1024 * 1024:
        raise p.EvidenceUnavailable("INCIDENT_DIAGNOSTIC_FILE_BOUND_EXCEEDED")
    return raw, store.decode(raw)


def _chain(domain, request_id):
    """Read one immutable signed outbox/receipt chain; never scan other effects."""
    directory = domain.state / "request_records" / _uuid(request_id)
    store.physical_identity(directory)
    _, request = _bounded(directory / "request.json")
    store.verify_original(request, domain.secret)
    if request.get("request_id") != request_id:
        raise p.PolicyError("ORIGINAL_OUTBOX_IDENTITY_DIFFERS")
    operations = request.get("operations")
    if not isinstance(operations, list) or not operations:
        raise p.PolicyError("ORIGINAL_OPERATIONS_UNAVAILABLE")
    event_directory = directory / "runtime_events"
    store.physical_identity(event_directory)
    paths = []
    for path in event_directory.iterdir():
        if path.suffix == ".json":
            paths.append(path)
            if len(paths) > 64:
                raise p.EvidenceUnavailable("INCIDENT_RECEIPT_CHAIN_BOUND_EXCEEDED")
    previous, terminal_raw = None, None
    for seq, path in enumerate(sorted(paths), 1):
        raw, event = _bounded(path)
        store.verify_original(event, domain.secret)
        context = request.get("execution_context") or {}
        if (type(event.get("schema_version")) is not int or event["schema_version"] != 1 or type(event.get("seq")) is not int or event["seq"] != seq
                or event.get("request_id") != request_id or event.get("request_digest") != p.digest(request)
                or event.get("operation_digest") != p.digest(operations)
                or event.get("session_id") != request.get("session_id")
                or event.get("host_instance_id", "") != request.get("host_instance_id", "")
                or any(event.get(k) != context.get(k) for k in ("run_id", "step_id", "attempt_id", "lease_epoch"))
                or previous is not None and previous.get("phase") == "terminal"
                or event.get("dispatched") is True and request.get("runtime_epoch")
                and event.get("runtime_epoch") != request["runtime_epoch"]):
            raise p.PolicyError("ORIGINAL_RECEIPT_CHAIN_DIFFERS")
        if event.get("terminal_result") is not None and p.digest(event["terminal_result"]) != event.get("result_digest"):
            raise p.PolicyError("ORIGINAL_RESULT_DIGEST_DIFFERS")
        previous, terminal_raw = event, raw
    if previous is None or previous.get("phase") != "terminal" or not isinstance(previous.get("terminal_result"), dict):
        raise p.EvidenceUnavailable("ORIGINAL_AUTHENTICATED_TERMINAL_UNAVAILABLE")
    return request, previous, terminal_raw


def _original_chain(stores, original):
    matches = [domain for domain in stores if domain.domain == original.domain]
    if len(matches) != 1:
        raise p.EvidenceUnavailable("ORIGINAL_DOMAIN_NOT_ENROLLED")
    request, terminal, raw = _chain(matches[0], original.request_id)
    if (p.digest(request) != original.request_digest
            or p.digest(request["operations"]) != original.operation_digest
            or p.digest(terminal) != original.terminal_payload_digest
            or hashlib.sha256(raw).hexdigest() != original.terminal_bytes_digest
            or terminal.get("runtime_epoch") != original.original_runtime_epoch
            or terminal.get("outcome") != "outcome_unknown"
            or terminal.get("dispatched") is not True
            or terminal["terminal_result"].get("outcome") != "outcome_unknown"
            or (request.get("execution_context") or {}).get("run_id") != original.original_run_id):
        raise p.PolicyError("ORIGINAL_UNKNOWN_TERMINAL_DIFFERS")
    return matches[0], request, terminal


def _check_observation(value, original, request):
    store.exact(value, _OBSERVATION_FIELDS)
    closure = store.exact(value["closure"], _CLOSURE_FIELDS)
    if (type(value["schema_version"]) is not int or value["schema_version"] != 1
            or value["kind"] != "incident_original_closure"
            or value["original"] != asdict(original) or value["observer_contract"] != OBSERVER_CONTRACT
            or value["diagnostic_request_id"] != request["request_id"]
            or value["diagnostic_request_digest"] != p.digest(request)
            or value["diagnostic_operation_digest"] != p.digest(request["operations"])
            or closure["request_digest"] != original.request_digest
            or closure["operation_digest"] != original.operation_digest
            or closure["runtime_epoch"] != original.original_runtime_epoch
            or closure["observed_completion"] not in {"proved_no_effect", "proved_completed_failure"}
            or type(closure["callback_generation"]) is not int or closure["callback_generation"] < 1
            or not isinstance(closure["installed_build"], str) or not closure["installed_build"]):
        raise p.PolicyError("INCIDENT_NATIVE_PRODUCER_BINDING_DIFFERS")
    _uuid(value["observation_ref"])
    for key in ("observer_implementation_digest", "producer_completion_digest"):
        p._digest_string(value[key], key)
    for key in ("request_digest", "operation_digest", "original_source_digest", "loaded_fingerprint",
                "private_record_digest", "actual_effect_closure_digest", "actual_after_digest",
                "native_contract_evidence_digest"):
        p._digest_string(closure[key], key)
    producer = {key: item for key, item in value.items() if key != "producer_completion_digest"}
    if value["producer_completion_digest"] != p.digest(producer):
        raise p.PolicyError("INCIDENT_NATIVE_PRODUCER_DIGEST_DIFFERS")
    return closure


def _diagnostic_chain(stores, original, diagnostic_request_id):
    _uuid(diagnostic_request_id)
    matches = [domain for domain in stores
               if (domain.state / "request_records" / diagnostic_request_id / "request.json").is_file()]
    if len(matches) != 1:
        raise p.EvidenceUnavailable("EXACT_INCIDENT_DIAGNOSTIC_UNAVAILABLE")
    domain = matches[0]
    request, terminal, raw = _chain(domain, diagnostic_request_id)
    if (request["operations"] != [{"name": "system.incident_observe_original",
                                  "arguments": {"original": asdict(original)}}]
            or terminal.get("outcome") != "succeeded" or terminal.get("dispatched") is not True
            or terminal.get("effect_class") != "none"
            or terminal.get("runtime_epoch") != original.original_runtime_epoch
            or terminal["terminal_result"].get("ok") is not True
            or terminal["terminal_result"].get("outcome") != "succeeded"
            or terminal["terminal_result"].get("dispatched") is not True):
        raise p.EvidenceUnavailable("INCIDENT_DIAGNOSTIC_NOT_A_SUCCESSFUL_ORIGINAL_OBSERVATION")
    value = terminal["terminal_result"].get("result")
    closure = _check_observation(value, original, request)
    _, original_request, _ = _original_chain(stores, original)
    source = original_request.get("source_binding")
    if (not isinstance(source, dict) or closure["original_source_digest"] != p.digest(source)
            or closure["loaded_fingerprint"] != original_request.get("adapter_fingerprint")):
        raise p.PolicyError("ORIGINAL_NATIVE_SOURCE_OR_IMPLEMENTATION_DIFFERS")
    descriptor = {"domain": asdict(domain.domain), "request_id": diagnostic_request_id,
        "request_digest": p.digest(request), "terminal_payload_digest": p.digest(terminal),
        "terminal_bytes_digest": hashlib.sha256(raw).hexdigest()}
    return descriptor, value


def _persisted(stores, evidence_digest, original, payload):
    original = _original(original)
    store.exact(payload, {"original", "diagnostic", "observation"})
    if payload["original"] != asdict(original):
        raise p.PolicyError("INCIDENT_EVIDENCE_ORIGINAL_DIFFERS")
    descriptor = store.exact(payload["diagnostic"], {"domain", "request_id", "request_digest",
                                                   "terminal_payload_digest", "terminal_bytes_digest"})
    current_descriptor, observation = _diagnostic_chain(stores, original, descriptor["request_id"])
    if descriptor != current_descriptor or payload["observation"] != observation:
        raise p.PolicyError("IMMUTABLE_INCIDENT_PRODUCER_DIFFERS")
    # Independently reauthenticate the evidence envelope, including its purpose.
    matches = [domain for domain in stores if domain.domain == original.domain]
    if len(matches) != 1:
        raise p.EvidenceUnavailable("ORIGINAL_DOMAIN_NOT_ENROLLED")
    p._digest_string(evidence_digest, "evidence digest")
    _, envelope = _bounded(matches[0].directory / "evidence" / (evidence_digest + ".json"))
    store.exact(envelope, {"schema_version", "kind", "domain", "payload", "mac"})
    store.verify(envelope, matches[0].secret, EVIDENCE_PURPOSE)
    if (envelope["schema_version"] != 1 or envelope["kind"] != "native_closure"
            or envelope["domain"] != asdict(original.domain) or envelope["payload"] != payload
            or p.digest(envelope) != evidence_digest):
        raise p.PolicyError("INCIDENT_EVIDENCE_PURPOSE_OR_DIGEST_DIFFERS")
    closure = observation["closure"]
    return p.NativeClosure(original, evidence_digest, p.ObservedCompletion(closure["observed_completion"]),
        observation["producer_completion_digest"], closure["actual_effect_closure_digest"],
        closure["actual_after_digest"])

from pathlib import Path
import threading

_LOCK = threading.RLock()
_ISSUED = {}
_LOADED_OBSERVER_DIGEST = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def observe_original(root, original_dict, diagnostic_request):
    from . import guarded_runtime as guards
    from .native_completion import retained_original_closure
    original = _original(original_dict)
    operations = [{"name": "system.incident_observe_original",
                   "arguments": {"original": asdict(original)}}]
    if (getattr(guards._LOCAL, "request", None) is not diagnostic_request
            or diagnostic_request.get("operations") != operations
            or guards.RUNTIME_EPOCH != original.original_runtime_epoch):
        raise p.EvidenceUnavailable("AUTHENTICATED_ORIGINAL_ATTEMPT_DIAGNOSTIC_REQUIRED")
    _uuid(diagnostic_request.get("request_id"))
    guards.assert_loaded_package()
    with store.locked_registry(root) as (_, stores):
        _original_chain(stores, original)
        active = [domain for domain in stores if domain.root == Path(root).resolve()]
        if len(active) != 1:
            raise p.EvidenceUnavailable("ACTIVE_DIAGNOSTIC_DOMAIN_UNAVAILABLE")
        _, outbox = _bounded(active[0].state / "request_records" / diagnostic_request["request_id"] / "request.json")
        store.verify_original(outbox, active[0].secret)
        if outbox != diagnostic_request:
            raise p.PolicyError("IMMUTABLE_DIAGNOSTIC_REQUEST_DIFFERS")
        closure = retained_original_closure(original.request_digest, original.terminal_payload_digest)
        value = {"schema_version": 1, "kind": "incident_original_closure", "original": asdict(original),
            "diagnostic_request_id": diagnostic_request["request_id"],
            "diagnostic_request_digest": p.digest(diagnostic_request),
            "diagnostic_operation_digest": p.digest(operations), "observer_contract": OBSERVER_CONTRACT,
            "observer_implementation_digest": _LOADED_OBSERVER_DIGEST,
            "observation_ref": str(uuid.uuid4()), "closure": closure}
        value["producer_completion_digest"] = p.digest(value)
        _check_observation(value, original, diagnostic_request)
        # Frozen private issuance, not the signed JSON payload, grants authority.
        with _LOCK:
            if len(_ISSUED) >= 4096:
                raise p.EvidenceUnavailable("INCIDENT_OBSERVATION_CAPACITY_EXCEEDED")
            current = retained_original_closure(original.request_digest, original.terminal_payload_digest,
                                                observation_ref=value["observation_ref"])
            if current != closure:
                raise p.EvidenceUnavailable("ORIGINAL_PRIVATE_CLOSURE_CHANGED")
            _ISSUED[value["observation_ref"]] = store.canonical(value)
        return value


def verify_persisted_closure(stores, evidence_digest, original, payload):
    """Project only while the exact retained original-attempt proof is live."""
    from . import guarded_runtime as guards
    from .native_completion import retained_original_closure
    stores = tuple(stores)
    original = _original(original)
    result = _persisted(stores, evidence_digest, original, payload)
    value = payload["observation"]
    with _LOCK:
        issued = _ISSUED.get(value["observation_ref"])
        if (issued is None or issued != store.canonical(value)
                or value["observer_implementation_digest"] != _LOADED_OBSERVER_DIGEST
                or guards.RUNTIME_EPOCH != original.original_runtime_epoch):
            raise p.EvidenceUnavailable("ORIGINAL_PRIVATE_OBSERVATION_ISSUER_UNAVAILABLE")
        current = retained_original_closure(original.request_digest, original.terminal_payload_digest)
        if current != value["closure"]:
            raise p.EvidenceUnavailable("ORIGINAL_PRIVATE_CLOSURE_REVOKED_OR_CHANGED")
    return result

