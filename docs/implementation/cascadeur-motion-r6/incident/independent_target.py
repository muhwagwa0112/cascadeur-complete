"""R6 reference; no native/product execution. See ../VERIFICATION.md.

Proposed product placement: cascadeur_complete/independent_target.py and its
embedded mirror. No import-time actions, default grants, custom crypto, or new
dependency. The Hyper-V path requires independently provisioned host custody;
the separate manual path is a POLICY DISPOSITION, never isolation/completion
evidence. Neither path changes an original terminal or retries an old request.
"""
from __future__ import annotations

from contextlib import contextmanager, nullcontext
from dataclasses import asdict, dataclass
import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time
import uuid

LEGACY_IDS = frozenset({"ffb7fc8e-417c-454c-a669-48625a086eda",
                        "fcf3352a-483c-4f9c-bc18-8b61a58822eb"})
MAX_DOCUMENT = 2 * 1024 * 1024
_VERIFIED = object()
REGISTRY_V2_PURPOSE = b"cascadeur-complete/incident-registry/v2\0"
MANUAL_PLAN_PURPOSE = b"cascadeur-complete/manual-legacy-plan/v1\0"
MANUAL_APPROVAL_PURPOSE = b"cascadeur-complete/manual-legacy-approval/v1\0"
MANUAL_CLAIM_PURPOSE = b"cascadeur-complete/manual-legacy-claim/v1\0"
RESIDUALS = (
    "original_outcomes_remain_unknown_and_incidents_remain_open",
    "historical_producer_and_consumer_closure_is_not_proven",
    "historical_resource_footprint_is_not_known_and_interference_is_not_excluded",
    "new_run_is_deliberate_work_abandonment_not_recovery_or_verified_containment",
    "no_old_run_retry_no_old_outputs_or_current_scene_as_baseline_no_auto_publication",
)


class Unavailable(ValueError):
    pass


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise Unavailable("DUPLICATE_JSON_MEMBER")
        result[key] = value
    return result


def decode(raw: bytes) -> dict:
    if len(raw) > MAX_DOCUMENT:
        raise Unavailable("DOCUMENT_TOO_LARGE")
    value = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs,
        parse_constant=lambda _: (_ for _ in ()).throw(Unavailable("NONFINITE_JSON")))
    if not isinstance(value, dict):
        raise Unavailable("OBJECT_REQUIRED")
    return value


def canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def digest(value) -> str:
    return sha(canonical(value))


def check_hash(value):
    if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise Unavailable("INVALID_SHA256")
    return value


def exact(value, fields):
    if not isinstance(value, dict) or set(value) != set(fields):
        raise Unavailable("SCHEMA_DIFFERS")
    return value


def publish_bytes(path: Path, raw: bytes):
    """New files only; fsync before atomic no-replace hard-link publication."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name("." + path.name + "." + secrets.token_hex(12) + ".pending")
    try:
        with temporary.open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def process_lock(path: Path):
    """Real OS lock for the standalone supervisor; never PID/TTL ownership."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as stream:
        if stream.tell() == 0:
            stream.write(b"\0")
            stream.flush()
        stream.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            try:
                yield
            finally:
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            # Useful to read/reference on another OS, not Hyper-V proof.
            import fcntl
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            try:
                yield
            finally:
                fcntl.flock(stream, fcntl.LOCK_UN)


@dataclass(frozen=True)
class CryptoTrust:
    """Installed/protected trust configuration, NEVER request parameters."""
    powershell_exe: Path
    verifier_script: Path
    verifier_script_sha256: str
    public_certificate: Path
    certificate_sha256: str


@dataclass(frozen=True)
class _Measurement:
    payload: dict
    payload_bytes: bytes
    envelope_digest: str
    token: object


def standard_verify(envelope_path: Path, trust: CryptoTrust) -> _Measurement:
    """Execute pinned Windows/.NET RSA verifier; no caller 'verified' flag."""
    if os.name != "nt":
        raise Unavailable("WINDOWS_STANDARD_CRYPTO_BACKEND_REQUIRED")
    if not trust.powershell_exe.is_absolute() or not trust.verifier_script.is_absolute():
        raise Unavailable("INSTALLED_ABSOLUTE_TOOL_PATH_REQUIRED")
    if sha(trust.verifier_script.read_bytes()) != check_hash(trust.verifier_script_sha256):
        raise Unavailable("VERIFIER_SCRIPT_BYTES_DIFFER")
    if sha(trust.public_certificate.read_bytes()) != check_hash(trust.certificate_sha256):
        raise Unavailable("SUPERVISOR_PUBLIC_PIN_DIFFERS")
    raw = Path(envelope_path).read_bytes()
    envelope = exact(decode(raw), {"schema_version", "algorithm", "certificate_sha256",
                                   "payload_b64", "signature_b64"})
    if (envelope["schema_version"] != 1 or envelope["algorithm"] != "RS256-PKCS1"
            or envelope["certificate_sha256"] != trust.certificate_sha256):
        raise Unavailable("SIGNATURE_ENVELOPE_DIFFERS")
    payload = base64.b64decode(envelope["payload_b64"], validate=True)
    base64.b64decode(envelope["signature_b64"], validate=True)
    # No shell, ExecutionPolicy bypass, caller executable or arbitrary script.
    checked = subprocess.run([str(trust.powershell_exe), "-NoProfile", "-NonInteractive",
        "-File", str(trust.verifier_script), "-Mode", "Verify",
        "-EnvelopePath", str(Path(envelope_path).resolve()),
        "-CertificatePath", str(trust.public_certificate),
        "-ExpectedCertificateSha256", trust.certificate_sha256],
        stdin=subprocess.DEVNULL, capture_output=True, timeout=30, check=False)
    if checked.returncode != 0:
        raise Unavailable("STANDARD_CRYPTO_VERIFIER_REJECTED")
    verified = base64.b64decode(checked.stdout.strip(), validate=True)
    if not hmac.compare_digest(payload, verified):
        raise Unavailable("VERIFIED_BYTES_DIFFER")
    return _Measurement(decode(verified), verified, sha(raw), _VERIFIED)


def export_legacy_snapshot(root: Path) -> dict:
    """Run ONLY on original host. Uses actual existing original-key verifiers.

    Output contains no key. The independently provisioned supervisor accepts its
    digest through explicit initial trust transfer, not a self-signed old key.
    """
    from cascadeur_complete import incident_store as store
    from cascadeur_complete.incident_admission import classify
    with store.locked_registry(root) as (registry, stores):
        domains = []
        found = set()
        for domain in stores:
            originals, unsealed, unresolved = domain.original_snapshot(classify)
            if unsealed:
                raise Unavailable("UNSEALED_REQUEST_REQUIRES_SEPARATE_SCOPE")
            if any(original.request_id not in LEGACY_IDS for original in originals):
                raise Unavailable("NEW_OR_OTHER_INCIDENT_NOT_IN_LEGACY_MIGRATION")
            journal = domain.journal()
            found.update(original.request_id for original in originals)
            domains.append({"domain": asdict(domain.domain), "head": asdict(journal.head),
                "unresolved_set_digest": unresolved,
                "originals": [asdict(original) for original in originals]})
        if found != LEGACY_IDS:
            raise Unavailable("EXACT_TWO_LEGACY_ORIGINALS_REQUIRED")
        return {"schema_version": 1, "purpose": "legacy_incident_export_v1",
            "registry_digest": digest(registry), "domains": domains}


def load_coverage(*, plan_bytes: bytes, source_export_bytes: bytes,
                  anchor_path: Path, anchor_binding_bytes: bytes,
                  trusted_plan_sha256: str, expected_target: dict,
                  trust: CryptoTrust) -> dict:
    """Verify a migration anchor. It is NOT a fresh execution permit."""
    if sha(plan_bytes) != check_hash(trusted_plan_sha256):
        raise Unavailable("APPROVED_PLAN_DIFFERS")
    plan = decode(plan_bytes)
    if (plan.get("schema_version") != 1 or plan.get("purpose") != "independent_target_plan_v1"
            or plan.get("target") != expected_target
            or plan.get("source_export_sha256") != sha(source_export_bytes)):
        raise Unavailable("TARGET_OR_COMPLETE_LEGACY_EXPORT_DIFFERS")
    exported = decode(source_export_bytes)
    originals = [original for domain in exported["domains"] for original in domain["originals"]]
    if ({item["request_id"] for item in originals} != LEGACY_IDS or len(originals) != 2
            or any(item["domain"] == expected_target for item in originals)):
        raise Unavailable("FOREIGN_ORIGINAL_SET_DIFFERS")
    anchor = standard_verify(anchor_path, trust)
    binding = decode(anchor_binding_bytes)
    _bound_measurement(anchor, plan, trusted_plan_sha256, anchor_binding_bytes,
                       binding["challenge"], "coverage", fresh=False)
    return {"schema_version": 1, "kind": "foreign_incident_anchor",
        "state": "unresolved_with_target_scoped_coverage", "target": expected_target,
        "source_export_sha256": sha(source_export_bytes), "domains": exported["domains"],
        "approved_plan_sha256": trusted_plan_sha256,
        "coverage_anchor_sha256": anchor.envelope_digest,
        "supervisor_certificate_sha256": trust.certificate_sha256,
        "realm": plan["realm"], "baseline": plan["baseline"]}


def _bound_measurement(measurement: _Measurement, plan: dict, plan_sha: str,
                       binding_bytes: bytes, challenge: str, kind: str, *, fresh: bool):
    if measurement.token is not _VERIFIED:
        raise Unavailable("STANDARD_VERIFIER_RESULT_REQUIRED")
    value = measurement.payload
    binding = decode(binding_bytes)
    if (value.get("schema_version") != 1 or value.get("purpose") != "hyperv_realm_measurement_v1"
            or value.get("approved_plan_sha256") != plan_sha
            or value.get("binding_sha256") != sha(binding_bytes)
            or value.get("challenge") != check_hash(challenge) or value.get("kind") != kind
            or binding.get("challenge") != challenge or binding.get("kind") != kind
            or binding.get("approved_plan_sha256") != plan_sha
            or value.get("target") != plan["target"] or value.get("realm") != plan["realm"]):
        raise Unavailable("SIGNED_MEASUREMENT_BINDING_DIFFERS")
    profile = value["profile"]
    if profile["state"] != ("Off" if kind == "observe_off" else "Running"):
        raise Unavailable("CURRENT_REALM_STATE_DIFFERS")
    for name in ("network_adapters", "dda", "gpu_partition", "fibre_channel", "checkpoints",
                 "com_pipes", "dvd_media", "enabled_integration_services", "replication_mode"):
        if type(profile.get(name)) is not int or profile[name] != 0:
            raise Unavailable("ISOLATION_PROFILE_DIFFERS")
    if (profile.get("generation") != 2 or profile.get("enhanced_session") is not False
            or profile.get("host_uuid") != plan["realm"]["host_uuid"]
            or profile.get("control_transport") != "powershell_direct_fixed_files_v1"
            or profile.get("output_policy") != "quarantine_vhd_no_export_until_off"
            or profile.get("controller_sid") != plan["controller_sid"]
            or value["baseline"]["sha256"] != plan["baseline"]["sha256"]
            or value["baseline"]["origin_kind"] != "immutable_fixture_generator"):
        raise Unavailable("MEASURED_CHANNEL_BASELINE_OR_HOST_DIFFERS")
    now = int(time.time() * 1000)
    if fresh and (not value["issued_at_ms"] <= now < value["expires_at_ms"]
                  or value["expires_at_ms"] - value["issued_at_ms"] > 60000
                  or now >= plan["expires_at_ms"]):
        raise Unavailable("FRESH_MEASUREMENT_REQUIRED")


def prepare_target_context(*, plan_bytes: bytes, coverage: dict,
                           lease_path: Path, binding_bytes: bytes,
                           expected_challenge: str, scope: dict,
                           phase: str, request: dict | None,
                           trust: CryptoTrust) -> dict:
    """Internal snapshot context, not a wire replacement for BridgeRequest.

    prepare: request=None and exact setup helper sequence/budgets in scope.
    dispatch/first_effect: exact already signed request and actual runtime epoch.
    Claims/confirmation/source checks remain in existing native admission code.
    """
    if phase not in ("prepare", "dispatch", "first_effect"):
        raise Unavailable("ADMISSION_PHASE_DIFFERS")
    plan = decode(plan_bytes)
    if (sha(plan_bytes) != coverage["approved_plan_sha256"]
            or plan["target"] != coverage["target"] or plan["realm"] != coverage["realm"]
            or scope["target"] != plan["target"]
            or scope["workspace_generation_id"] != plan["workspace_generation_id"]
            or scope["baseline_digest"] != digest(plan["baseline"])
            or scope["run_id"] in {item["original_run_id"] for domain in coverage["domains"] for item in domain["originals"]}
            or scope["operation_plan_digest"] != plan["operation_plan_digest"]
            or scope["helper_sequence_digest"] != digest(plan["setup_steps"])):
        raise Unavailable("APPROVED_WORK_SCOPE_DIFFERS")
    binding = decode(binding_bytes)
    if binding.get("scope_digest") != digest(scope):
        raise Unavailable("LEASE_SCOPE_DIFFERS")
    if phase == "prepare":
        if request is not None or binding.get("request_digest") is not None:
            raise Unavailable("PREPARE_IS_NOT_AN_EXECUTION_PERMIT")
    elif (request is None or request["request_id"] in LEGACY_IDS
            or binding.get("request_digest") != digest(request)
            or binding.get("operation_digest") != digest(request["operations"])
            or request.get("runtime_epoch") != scope["runtime_epoch"]
            or request.get("adapter_fingerprint") != scope["loaded_fingerprint"]
            or (request.get("execution_context") or {}).get("run_id") != scope["run_id"]):
        raise Unavailable("EXACT_NEW_SIGNED_REQUEST_REQUIRED")
    measured = standard_verify(lease_path, trust)
    _bound_measurement(measured, plan, sha(plan_bytes), binding_bytes,
                       expected_challenge, phase, fresh=True)
    return {"kind": "independent_target_coverage_v1", "phase": phase,
        "coverage_anchor_sha256": coverage["coverage_anchor_sha256"],
        "lease_sha256": measured.envelope_digest, "scope_digest": digest(scope),
        "request_digest": digest(request) if request else None,
        "foreign_originals": [item for d in coverage["domains"] for item in d["originals"]],
        "original_status": "outcome_unknown/open", "realm": plan["realm"]}


def install_target_registry(root: Path, coverage: dict):
    """Proposed bootstrap only: fresh local marker already exists, admission shut.

    Runtime v2 must read this explicit union instead of locked_registry(v1).
    Loading v1 still opens every original physical store exactly as before.
    """
    from cascadeur_complete import incident_store as store
    local = store.IncidentStore(root)
    if asdict(local.domain) != coverage["target"]:
        raise Unavailable("NEW_TARGET_AUTH_DOMAIN_DIFFERS")
    body = {"schema_version": 2, "stores": [{"kind": "local_store", "root": str(local.root),
        "domain": asdict(local.domain), "physical_root": local.identity}],
        "foreign_incident_anchors": [coverage]}
    store.publish_new(local.directory / "registry-v2.json",
                      store.seal(body, local.secret, REGISTRY_V2_PURPOSE))


def _manual_current(root: Path):
    # Must be called while the existing locked_registry context is held.
    from cascadeur_complete import incident_store as store
    return store.IncidentStore(root)


def prepare_manual_legacy(root: Path, *, new_scope: dict, steps: list[dict],
                          generator_path: Path, installed_generator_sha256: str,
                          installed_package_digest: str) -> str:
    """New LOCAL control plan. installed_* comes from trusted package manifest.

    This changes policy only after separate explicit approval. It does not
    certify noninterference, absence of old processes, or historical completion.
    Public API/schema are proposals; no product call is made by this file itself.
    """
    from cascadeur_complete import incident_store as store
    from cascadeur_complete.incident_admission import classify
    with store.locked_registry(root) as (registry, stores):
        originals, heads = [], []
        for domain in stores:
            selected, unsealed, unresolved = domain.original_snapshot(classify)
            if unsealed:
                raise Unavailable("UNSEALED_OR_CURRENT_REQUEST_BLOCKS_MANUAL_LEGACY_PATH")
            originals.extend(asdict(item) for item in selected)
            heads.append({"head": asdict(domain.journal().head), "unresolved_set_digest": unresolved})
        if {item["request_id"] for item in originals} != LEGACY_IDS or len(originals) != 2:
            raise Unavailable("ONLY_EXACT_TWO_LEGACY_INCIDENTS_SUPPORTED")
        active = next(item for item in stores if item.root == Path(root).resolve())
        exact(new_scope, {"target", "runtime_epoch", "loaded_fingerprint", "run_id",
            "workspace_generation_id", "workspace_path", "operation_plan_digest"})
        if (new_scope["target"] != asdict(active.domain)
                or new_scope["runtime_epoch"] in {item["original_runtime_epoch"] for item in originals}
                or new_scope["run_id"] in {item["original_run_id"] for item in originals}):
            raise Unavailable("NEW_RUN_AND_LOADED_EPOCH_REQUIRED")
        for key in ("run_id", "workspace_generation_id"):
            if str(uuid.UUID(new_scope[key])) != new_scope[key]:
                raise Unavailable("CANONICAL_NEW_ID_REQUIRED")
        workspace = Path(new_scope["workspace_path"])
        if not workspace.is_absolute() or workspace.exists() or workspace.parent.resolve() != (active.root / "snapshots").resolve():
            raise Unavailable("NEW_OWNED_WORKSPACE_REQUIRED")
        parent_identity = store.physical_identity(workspace.parent)
        generator_identity = store.physical_identity(generator_path)
        raw = Path(generator_path).read_bytes()
        if sha(raw) != check_hash(installed_generator_sha256):
            raise Unavailable("INSTALLED_FIXTURE_GENERATOR_DIFFERS")
        if not steps or len({item["step_id"] for item in steps}) != len(steps):
            raise Unavailable("EXACT_FINITE_NEW_STEP_PLAN_REQUIRED")
        concrete_steps = []
        for step in steps:
            exact(step, {"step_id", "operations", "source_rule"})
            if not isinstance(step["operations"], list) or not step["operations"]:
                raise Unavailable("REVIEWABLE_CONCRETE_OPERATIONS_REQUIRED")
            if step["source_rule"] not in ("fresh_fixture", "previous_succeeded_new_run_step"):
                raise Unavailable("OLD_SCENE_OR_UNKNOWN_OUTPUT_BASELINE_FORBIDDEN")
            concrete_steps.append(dict(step, operation_digest=digest(step["operations"])))
        now = int(time.time() * 1000)
        body = {"schema_version": 1, "purpose": "manual_legacy_disposition_plan_v1",
            "originals": originals, "registry_digest": digest(registry), "heads": heads,
            "scope": new_scope, "workspace_parent_identity": parent_identity,
            "baseline": {"origin_kind": "immutable_fixture_generator", "identity": generator_identity,
                "sha256": sha(raw), "size": len(raw), "installed_package_digest": check_hash(installed_package_digest)},
            "steps": concrete_steps, "residuals": list(RESIDUALS), "created_at_ms": now,
            "approve_before_ms": now + 600000}
        sealed = store.seal(body, active.secret, MANUAL_PLAN_PURPOSE)
        plan_sha = digest(sealed)
        store.publish_new(active.directory / "manual-legacy-plans" / (plan_sha + ".json"), sealed)
        return plan_sha


def approve_manual_legacy_local(root: Path, plan_sha256: str) -> dict:
    """Interactive local operator ONLY. Never an MCP route or auto-approval.

    Approves a concrete disclosed policy exception, not a proof predicate.
    Issuance was not performed while preparing this packet.
    """
    from cascadeur_complete import incident_store as store
    from cascadeur_complete.incident_admission import classify
    check_hash(plan_sha256)
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise Unavailable("LOCAL_INTERACTIVE_OPERATOR_REQUIRED")
    with store.locked_registry(root):
        active = _manual_current(root)
        path = active.directory / "manual-legacy-plans" / (plan_sha256 + ".json")
        plan = store.read(path)
        store.verify(plan, active.secret, MANUAL_PLAN_PURPOSE)
        if digest(plan) != plan_sha256 or int(time.time()*1000) >= plan["approve_before_ms"]:
            raise Unavailable("PLAN_CHANGED_OR_EXPIRED")
    # Human review must not hold the global registry/admission locks.
    print(json.dumps(plan, ensure_ascii=False, indent=2))
    print("과거 결과/종료/영향 범위가 미증명인 상태를 수용하고 이 새 run만 시작하는 정책 선택입니다.")
    if input("승인하려면 표시된 plan SHA-256 전체를 입력: ").strip() != plan_sha256:
        raise Unavailable("EXACT_MANUAL_DISPOSITION_NOT_APPROVED")
    with store.locked_registry(root) as (registry, stores):
        active = next(item for item in stores if item.root == Path(root).resolve())
        current = store.read(active.directory / "manual-legacy-plans" / (plan_sha256 + ".json"))
        store.verify(current, active.secret, MANUAL_PLAN_PURPOSE)
        if current != plan or digest(current) != plan_sha256 or int(time.time()*1000) >= plan["approve_before_ms"]:
            raise Unavailable("PLAN_CHANGED_OR_EXPIRED_DURING_REVIEW")
        originals, heads = [], []
        for domain in stores:
            selected, unsealed, unresolved = domain.original_snapshot(classify)
            if unsealed:
                raise Unavailable("NEW_UNSEALED_REQUEST_DURING_REVIEW")
            originals.extend(asdict(item) for item in selected)
            heads.append({"head": asdict(domain.journal().head), "unresolved_set_digest": unresolved})
        if (originals != plan["originals"] or heads != plan["heads"] or digest(registry) != plan["registry_digest"]):
            raise Unavailable("INCIDENT_OR_REGISTRY_CHANGED_DURING_REVIEW")
        approved = store.seal({"schema_version": 1, "purpose": "manual_legacy_disposition_v1",
            "plan_sha256": plan_sha256, "originals_digest": digest(plan["originals"]),
            "scope_digest": digest(plan["scope"]), "residuals_digest": digest(plan["residuals"]),
            "approved_at_ms": int(time.time()*1000)}, active.secret, MANUAL_APPROVAL_PURPOSE)
        store.publish_new(active.directory / "manual-legacy-approvals" / (plan_sha256 + ".json"), approved)
        return approved


def _consume_manual_step(root: Path, *, plan_sha256: str, request: dict,
                         actual_runtime_epoch: str, actual_loaded_fingerprint: str,
                         locked_state=None) -> dict:
    """Internal dispatch assertion; actual_* comes from loaded native runtime.

    New operation/source/confirmation and recipe ancestry checks are still
    mandatory. Return value is a policy context, never retirement evidence.
    Native repeats it at first effect; exact existing claim is not reconsumed.
    """
    from cascadeur_complete import incident_store as store
    from cascadeur_complete.incident_admission import classify
    held = nullcontext(locked_state) if locked_state is not None else store.locked_registry(root)
    with held as (registry, stores):
        active = next(item for item in stores if item.root == Path(root).resolve())
        plan = store.read(active.directory / "manual-legacy-plans" / (check_hash(plan_sha256) + ".json"))
        approval = store.read(active.directory / "manual-legacy-approvals" / (plan_sha256 + ".json"))
        store.verify(plan, active.secret, MANUAL_PLAN_PURPOSE)
        store.verify(approval, active.secret, MANUAL_APPROVAL_PURPOSE)
        store.verify_original(request, active.secret)
        if (digest(plan) != plan_sha256 or approval["plan_sha256"] != plan_sha256
                or approval["scope_digest"] != digest(plan["scope"])
                or approval["originals_digest"] != digest(plan["originals"])
                or approval["residuals_digest"] != digest(list(RESIDUALS))
                or not plan["created_at_ms"] <= approval["approved_at_ms"] < plan["approve_before_ms"]):
            raise Unavailable("EXACT_MANUAL_AUTHORIZATION_DIFFERS")
        originals, heads = [], []
        for domain in stores:
            selected, unsealed, unresolved = domain.original_snapshot(classify,
                exclude=(active.domain, request["request_id"], digest(request)))
            if unsealed:
                raise Unavailable("NEW_UNSEALED_REQUEST_BLOCKS")
            originals.extend(asdict(item) for item in selected)
            heads.append({"head": asdict(domain.journal().head), "unresolved_set_digest": unresolved})
        if (originals != plan["originals"] or heads != plan["heads"] or digest(registry) != plan["registry_digest"]):
            raise Unavailable("NEW_INCIDENT_OR_REGISTRY_CHANGE_REQUIRES_NORMAL_HANDLING")
        scope, context = plan["scope"], request.get("execution_context") or {}
        if store.physical_identity(Path(scope["workspace_path"]).parent) != plan["workspace_parent_identity"]:
            raise Unavailable("APPROVED_WORKSPACE_PARENT_CHANGED")
        baseline_path = Path(plan["baseline"]["identity"]["path"])
        if (store.physical_identity(baseline_path) != plan["baseline"]["identity"]
                or sha(baseline_path.read_bytes()) != plan["baseline"]["sha256"]):
            raise Unavailable("APPROVED_BASELINE_CHANGED")
        if (request["request_id"] in LEGACY_IDS or request.get("runtime_epoch") != actual_runtime_epoch
                or actual_runtime_epoch != scope["runtime_epoch"]
                or request.get("adapter_fingerprint") != actual_loaded_fingerprint
                or actual_loaded_fingerprint != scope["loaded_fingerprint"]
                or context.get("run_id") != scope["run_id"]
                or context.get("workspace_generation_id") != scope["workspace_generation_id"]
                or context.get("baseline_digest") != digest(plan["baseline"])):
            raise Unavailable("NEW_SCOPED_RUN_DIFFERS")
        steps = [item for item in plan["steps"] if item["step_id"] == context.get("step_id")]
        if (len(steps) != 1 or request["operations"] != steps[0]["operations"]
                or digest(request["operations"]) != steps[0]["operation_digest"]):
            raise Unavailable("APPROVED_STEP_DIFFERS")
        # Existing recipe runner/native guards must authenticate source_rule:
        # fixture OR an exact succeeded predecessor of this new run. The policy
        # context does not authorize old/current scene material by itself.
        claim = {"schema_version": 1, "plan_sha256": plan_sha256,
            "step_id": steps[0]["step_id"], "request_digest": digest(request),
            "request_id": request["request_id"], "scope_digest": digest(scope)}
        claim_path = active.directory / "manual-legacy-claims" / plan_sha256 / (digest(steps[0]) + ".json")
        if claim_path.exists():
            old = store.read(claim_path)
            store.verify(old, active.secret, MANUAL_CLAIM_PURPOSE)
            if {key: value for key, value in old.items() if key != "mac"} != claim:
                raise Unavailable("MANUAL_STEP_ALREADY_BOUND_TO_ANOTHER_REQUEST")
        else:
            store.publish_new(claim_path, store.seal(claim, active.secret, MANUAL_CLAIM_PURPOSE))
        return {"kind": "manual_legacy_disposition_v1", "plan_sha256": plan_sha256,
            "claim_digest": digest(claim), "originals": originals, "original_status": "outcome_unknown/open",
            "source_rule": steps[0]["source_rule"], "assurance": "operator_accepted_unproven_legacy_interference"}


def consume_manual_step(root: Path, *, plan_sha256: str, request: dict,
                        actual_runtime_epoch: str, actual_loaded_fingerprint: str) -> dict:
    return _consume_manual_step(root, plan_sha256=plan_sha256, request=request,
        actual_runtime_epoch=actual_runtime_epoch, actual_loaded_fingerprint=actual_loaded_fingerprint)


def consume_manual_step_locked(root: Path, registry: dict, stores: tuple, *,
                               plan_sha256: str, request: dict,
                               actual_runtime_epoch: str, actual_loaded_fingerprint: str) -> dict:
    """Called from snapshot while its exact registry/admission locks are held."""
    return _consume_manual_step(root, plan_sha256=plan_sha256, request=request,
        actual_runtime_epoch=actual_runtime_epoch, actual_loaded_fingerprint=actual_loaded_fingerprint,
        locked_state=(registry, stores))
