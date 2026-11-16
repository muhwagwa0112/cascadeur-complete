"""Authenticated incident persistence; original outbox/receipt bytes are read only.

This module is mirrored into embedded Python. New envelopes have strict schemas,
purpose-separated keys and a contiguous append-only chain. Evidence issuers live
outside this persistence layer: a signed assertion alone cannot close an incident.
"""
from __future__ import annotations

from contextlib import ExitStack, contextmanager
from dataclasses import asdict
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import uuid

from . import incident_policy as policy
from .installation_guard import hold_runtime_lease
from .state_lock import file_lock

REGISTRY_PURPOSE = b"cascadeur-complete/incident-registry/v1\0"
STORE_PURPOSE = b"cascadeur-complete/incident-store/v1\0"


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise policy.PolicyError("DUPLICATE_JSON_MEMBER")
        result[key] = value
    return result


def decode(raw):
    value = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs,
                       parse_constant=lambda _: (_ for _ in ()).throw(policy.PolicyError("NONFINITE_JSON")))
    if not isinstance(value, dict):
        raise policy.PolicyError("JSON_OBJECT_REQUIRED")
    return value


def read(path):
    return decode(Path(path).read_bytes())


def exact(value, fields):
    if not isinstance(value, dict) or set(value) != set(fields):
        raise policy.PolicyError("INCIDENT_SCHEMA_MISMATCH")
    return value


def key_for(secret, purpose, binding):
    if not isinstance(secret, bytes) or len(secret) < 32:
        raise policy.PolicyError("ORIGINAL_KEY_UNAVAILABLE")
    return hmac.new(secret, purpose + canonical(binding), hashlib.sha256).digest()


def seal(body, secret, purpose):
    result = dict(body)
    result["mac"] = hmac.new(key_for(secret, purpose, {}), canonical(body), hashlib.sha256).hexdigest()
    return result


def verify(value, secret, purpose):
    supplied = value.get("mac")
    expected = seal({k: v for k, v in value.items() if k != "mac"}, secret, purpose)["mac"]
    if not isinstance(supplied, str) or not hmac.compare_digest(supplied, expected):
        raise policy.PolicyError("INCIDENT_AUTHENTICATION_FAILED")


def verify_original(value, secret):
    supplied = value.get("mac")
    expected = hmac.new(secret, canonical({k: v for k, v in value.items() if k != "mac"}), hashlib.sha256).hexdigest()
    if not isinstance(supplied, str) or not hmac.compare_digest(supplied, expected):
        raise policy.PolicyError("ORIGINAL_AUTHENTICATION_FAILED")


def publish_new(path, value):
    """Publish without replacing a prior authority, including after a crash."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name("." + path.name + "." + secrets.token_hex(12) + ".tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(canonical(value))
            stream.flush()
            os.fsync(stream.fileno())
        # Hard-link publication is atomic and fails if the target already exists.
        os.link(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def replace_head(path, value):
    temporary = path.with_name("." + path.name + "." + secrets.token_hex(12) + ".tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(canonical(value)); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def physical_identity(path):
    """Pin existing file identities; aliases with unknown coverage are rejected."""
    path = Path(path).absolute()
    for part in (path, *path.parents):
        info = part.lstat()
        if part.is_symlink() or getattr(info, "st_file_attributes", 0) & 0x400:
            raise policy.EvidenceUnavailable("REPARSE_ALIAS_COVERAGE_UNAVAILABLE")
    resolved = path.resolve(strict=True)
    info = resolved.stat()
    if not info.st_ino or (resolved.is_file() and info.st_nlink != 1):
        raise policy.EvidenceUnavailable("PHYSICAL_ALIAS_COVERAGE_UNAVAILABLE")
    return {"path": os.path.normcase(str(resolved)), "device": info.st_dev, "file_id": info.st_ino}


def canonical_root():
    profile = os.environ.get("USERPROFILE")
    local = Path(profile) / "AppData" / "Local" if profile else Path(os.environ["LOCALAPPDATA"])
    return (local / "CascadeurMCP" / "cascadeur-complete").resolve()


def registry_path():
    # Never selected by CASCADEUR_MCP_ROOT or a request-supplied root list.
    return canonical_root() / "state" / "incidents" / "registry-v1.json"


class IncidentStore:
    def __init__(self, root):
        self.root = Path(root).resolve(strict=True)
        self.state = self.root / "state"
        self.secret = (self.state / "bridge.key").read_bytes()
        self.domain_id = policy.auth_domain_id(self.secret)
        self.directory = self.state / "incidents"
        self.identity = physical_identity(self.root)
        marker = read(self.directory / "store-v1.json")
        exact(marker, {"schema_version", "auth_domain_id", "store_instance_id", "physical_root", "mac"})
        verify(marker, self.secret, STORE_PURPOSE)
        if (marker["schema_version"] != 1 or marker["auth_domain_id"] != self.domain_id
                or marker["physical_root"] != self.identity):
            raise policy.PolicyError("ACTIVE_INCIDENT_STORE_DIFFERS")
        if str(uuid.UUID(marker["store_instance_id"])) != marker["store_instance_id"]:
            raise policy.PolicyError("INVALID_STORE_ID")
        self.domain = policy.DomainRef(self.domain_id, marker["store_instance_id"])

    def original_snapshot(self, classify, *, exclude=None):
        originals, unsealed, unresolved = [], [], []
        for path in sorted((self.state / "request_records").glob("*/request.json")):
            request = read(path)
            verify_original(request, self.secret)
            rid = path.parent.name
            if str(uuid.UUID(rid)) != rid or request.get("request_id") != rid:
                raise policy.PolicyError("OUTBOX_IDENTITY_DIFFERS")
            if exclude == (self.domain, rid, policy.digest(request)):
                continue
            if not classify(request):
                continue
            previous = None
            terminal_raw = None
            for seq, event_path in enumerate(sorted((path.parent / "runtime_events").glob("*.json")), 1):
                raw = event_path.read_bytes()
                event = decode(raw)
                verify_original(event, self.secret)
                context = request.get("execution_context") or {}
                if (event.get("seq") != seq or event.get("request_id") != rid
                        or event.get("request_digest") != policy.digest(request)
                        or event.get("operation_digest") != policy.digest(request["operations"])
                        or event.get("session_id") != request.get("session_id")
                        or event.get("host_instance_id", "") != request.get("host_instance_id", "")
                        or any(event.get(k) != context.get(k) for k in ("run_id", "step_id", "attempt_id", "lease_epoch"))
                        or previous is not None and previous.get("phase") == "terminal"
                        or event.get("dispatched") is True and request.get("runtime_epoch")
                        and event.get("runtime_epoch") != request["runtime_epoch"]):
                    raise policy.PolicyError("ORIGINAL_RECEIPT_CHAIN_DIFFERS")
                if event.get("terminal_result") is not None and policy.digest(event["terminal_result"]) != event.get("result_digest"):
                    raise policy.PolicyError("ORIGINAL_RESULT_DIGEST_DIFFERS")
                previous, terminal_raw = event, raw
            if previous is None:
                canceled = path.parent / "host_canceled.json"
                if canceled.is_file():
                    value = read(canceled); verify_original(value, self.secret)
                    if value.get("request_digest") == policy.digest(request) and value.get("outcome") == "canceled_pre_dispatch":
                        continue
            if previous and previous.get("phase") == "terminal" and previous.get("outcome") != "outcome_unknown":
                continue
            unresolved.append({"request_id": rid, "request_digest": policy.digest(request),
                               "receipt_digest": policy.digest(previous) if previous else None})
            if not previous or previous.get("phase") != "terminal":
                unsealed.append(rid)
                continue
            originals.append(policy.OriginalRef(self.domain, rid, policy.digest(request),
                policy.digest(request["operations"]), policy.digest(previous),
                hashlib.sha256(terminal_raw).hexdigest(), previous["runtime_epoch"], context.get("run_id")))
        return tuple(originals), tuple(unsealed), policy.digest(unresolved)

    def journal(self):
        entries = []
        for path in sorted((self.directory / "events").glob("*.json")):
            value = read(path)
            exact(value, {"body", "mac"})
            body = exact(value["body"], {"schema_version", "domain", "seq", "previous_event_digest", "kind", "original", "evidence_digest", "plan_digest"})
            domain = policy.DomainRef(**exact(body["domain"], {"auth_domain_id", "store_instance_id"}))
            original = dict(exact(body["original"], policy.OriginalRef.__dataclass_fields__))
            original["domain"] = policy.DomainRef(**exact(original["domain"], {"auth_domain_id", "store_instance_id"}))
            body = dict(body, domain=domain, original=policy.OriginalRef(**original), kind=policy.EventKind(body["kind"]))
            entry = policy.JournalEntry(policy.JournalBody(**body), value["mac"])
            if path.name != f"{entry.body.seq:012d}-{policy.entry_digest(entry)}.json":
                raise policy.PolicyError("JOURNAL_FILENAME_DIFFERS")
            entries.append(entry)
        actual = policy.Head(self.domain, len(entries), policy.entry_digest(entries[-1]) if entries else policy.ZERO_DIGEST)
        verified = policy.verify_chain(entries, original_bridge_secret=self.secret, expected_head=actual)
        head_path = self.directory / "head-v1.json"
        if head_path.is_file():
            head = read(head_path)
            exact(head, {"schema_version", "domain", "seq", "event_digest", "mac"})
            verify(head, self.secret, policy.JOURNAL_PURPOSE)
            seq = head["seq"]
            if (head["schema_version"] != 1 or head["domain"] != asdict(self.domain)
                    or type(seq) is not int or seq < 0 or seq > len(entries)
                    or head["event_digest"] != (policy.entry_digest(entries[seq-1]) if seq else policy.ZERO_DIGEST)):
                raise policy.PolicyError("ANCHORED_JOURNAL_HEAD_DIFFERS")
        elif entries:
            raise policy.PolicyError("JOURNAL_HEAD_ANCHOR_MISSING")
        return verified

    def anchor(self, head):
        replace_head(self.directory / "head-v1.json", seal({"schema_version": 1,
            **asdict(head)}, self.secret, policy.JOURNAL_PURPOSE))

    def append(self, kind, original, *, evidence_digest=None, plan_digest=None, evidence, classify):
        # Caller holds all admission locks; transition is checked BEFORE publication.
        journal = self.journal()
        originals, unsealed, unresolved = self.original_snapshot(classify)
        body = policy.JournalBody(1, self.domain, journal.head.seq+1, journal.head.event_digest,
                                 kind, original, evidence_digest, plan_digest)
        entry = policy.seal_new_entry(body, self.secret)
        head = policy.Head(self.domain, body.seq, policy.entry_digest(entry))
        candidate = policy.VerifiedJournal(head, journal.entries+(entry,))
        policy.project_domain(originals=originals, journal=candidate,
            unsealed_effect_request_ids=unsealed, unresolved_set_digest=unresolved, evidence=evidence)
        publish_new(self.directory / "events" / f"{body.seq:012d}-{head.event_digest}.json", asdict(entry))
        self.anchor(head)
        return head


def enroll_domains(roots):
    """Local control enrollment, never called by native requests or env discovery.

    Initial enrollment pins the canonical store plus explicitly identified original
    stores. Subsequent enrollment cannot omit a previously enrolled domain/store.
    """
    authority = canonical_root()
    secret = (authority / "state" / "bridge.key").read_bytes()
    roots = sorted({str(Path(root).resolve(strict=True)) for root in roots} | {str(authority)})
    with ExitStack() as stack:
        for root in roots:
            hold_runtime_lease(root)
        stack.enter_context(file_lock(authority / "state" / "incidents" / "registry.lock"))
        existing = read(registry_path()) if registry_path().is_file() else None
        if existing:
            verify(existing, secret, REGISTRY_PURPOSE)
            if not {item["root"] for item in existing["stores"]}.issubset(set(roots)):
                raise policy.PolicyError("ENROLLED_STORE_CANNOT_BE_OMITTED")
        stores = []
        for root in roots:
            state = Path(root) / "state"
            bridge_secret = (state / "bridge.key").read_bytes()
            marker_path = state / "incidents" / "store-v1.json"
            if not marker_path.exists():
                publish_new(marker_path, seal({"schema_version": 1,
                    "auth_domain_id": policy.auth_domain_id(bridge_secret), "store_instance_id": str(uuid.uuid4()),
                    "physical_root": physical_identity(root)}, bridge_secret, STORE_PURPOSE))
            store = IncidentStore(root)
            stack.enter_context(file_lock(store.directory / "admission.lock"))
            if not (store.directory / "head-v1.json").exists():
                store.anchor(policy.Head(store.domain, 0, policy.ZERO_DIGEST))
            store.journal()
            from .incident_effects import classify_effect
            store.original_snapshot(lambda request: any(classify_effect(op["name"], op.get("arguments")) != "none"
                                                        for op in request["operations"]))
            stores.append({"root": root, "domain": asdict(store.domain), "physical_root": store.identity})
        if len({item["domain"]["auth_domain_id"] for item in stores}) != len(stores):
            raise policy.PolicyError("DUPLICATE_ACTIVE_AUTH_DOMAIN")
        value = seal({"schema_version": 1, "stores": stores}, secret, REGISTRY_PURPOSE)
        replace_head(registry_path(), value)
        return {"registry_digest": policy.digest(value), "stores": stores}


@contextmanager
def locked_registry(active_root):
    authority = canonical_root()
    hold_runtime_lease(authority)
    with ExitStack() as stack:
        stack.enter_context(file_lock(authority / "state" / "incidents" / "registry.lock"))
        value = read(registry_path())
        exact(value, {"schema_version", "stores", "mac"})
        verify(value, (authority / "state" / "bridge.key").read_bytes(), REGISTRY_PURPOSE)
        if value["schema_version"] != 1 or not isinstance(value["stores"], list) or not value["stores"]:
            raise policy.PolicyError("INCIDENT_REGISTRY_UNAVAILABLE")
        stores = []
        for entry in value["stores"]:
            exact(entry, {"root", "domain", "physical_root"})
            hold_runtime_lease(entry["root"])
            store = IncidentStore(entry["root"])
            if asdict(store.domain) != entry["domain"] or store.identity != entry["physical_root"]:
                raise policy.PolicyError("REGISTERED_PHYSICAL_STORE_DIFFERS")
            stores.append(store)
        if (len({s.domain_id for s in stores}) != len(stores)
                or not any(s.root == authority for s in stores)
                or not any(s.root == Path(active_root).resolve() for s in stores)):
            raise policy.PolicyError("AUTH_DOMAIN_COVERAGE_UNAVAILABLE")
        for store in sorted(stores, key=lambda s: s.domain):
            stack.enter_context(file_lock(store.directory / "admission.lock"))
        yield value, tuple(stores)
