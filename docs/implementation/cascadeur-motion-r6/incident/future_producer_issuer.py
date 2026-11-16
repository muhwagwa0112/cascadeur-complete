"""R6 reference issuer: real capture, request authentication and durable binding.

Not installed or executed. Hyper-V operations run only if these functions are
explicitly invoked later on a separately trusted supervisor. No old bridge key
is imported. A current native process observation is labelled partial; only the
measured independent realm produces a realm-scope closure manifest.
"""
from __future__ import annotations

from dataclasses import dataclass
import ctypes
import hashlib
import hmac
import inspect
import os
from pathlib import Path
import subprocess
import time
import uuid

from .independent_target import (CryptoTrust, Unavailable, _bound_measurement,
    canonical, check_hash, decode, digest, process_lock, publish_bytes, sha,
    standard_verify)

DOMAIN_PURPOSE = b"cascadeur-complete/incident-auth-domain/v1\0"
CLOSURE_PURPOSE = b"cascadeur-complete/incident-producer-closure/v1\0"
DISPATCH_PURPOSE = b"cascadeur-complete/realm-dispatch/v1\0"
PARTIAL_PURPOSE = b"cascadeur-complete/observed-native-producer/v1\0"
OFF_PURPOSE = b"cascadeur-complete/future-realm-off-observation/v1\0"
_CONFIGS: dict[str, "SupervisorConfig"] = {}


def auth_domain_id(secret: bytes) -> str:
    if len(secret) < 32:
        raise Unavailable("NEW_TARGET_DOMAIN_KEY_UNAVAILABLE")
    return hmac.new(secret, DOMAIN_PURPOSE, hashlib.sha256).hexdigest()


def verify_original(value: dict, secret: bytes):
    body = {key: val for key, val in value.items() if key != "mac"}
    actual = hmac.new(secret, canonical(body), hashlib.sha256).hexdigest()
    if not isinstance(value.get("mac"), str) or not hmac.compare_digest(value["mac"], actual):
        raise Unavailable("ORIGINAL_NEW_TARGET_MAC_DIFFERS")


def seal(value: dict, secret: bytes, purpose: bytes) -> dict:
    key = hmac.new(secret, purpose + b"{}", hashlib.sha256).digest()
    return dict(value, mac=hmac.new(key, canonical(value), hashlib.sha256).hexdigest())


def verify(value: dict, secret: bytes, purpose: bytes):
    expected = seal({k: v for k, v in value.items() if k != "mac"}, secret, purpose)["mac"]
    if not isinstance(value.get("mac"), str) or not hmac.compare_digest(expected, value["mac"]):
        raise Unavailable("PRODUCER_RECORD_MAC_DIFFERS")


@dataclass(frozen=True)
class SupervisorConfig:
    # Configuration is installed locally, not deserialized from request arguments.
    authority_id: str
    state: Path
    approved_plan: Path
    approved_plan_sha256: str
    signing_certificate_thumbprint: str
    crypto: CryptoTrust
    new_target_secret: bytes

    def plan(self):
        raw = self.approved_plan.read_bytes()
        if sha(raw) != check_hash(self.approved_plan_sha256):
            raise Unavailable("TRUSTED_PLAN_BYTES_DIFFER")
        value = decode(raw)
        if value["target"]["auth_domain_id"] != auth_domain_id(self.new_target_secret):
            raise Unavailable("ONLY_NEW_TARGET_AUTH_DOMAIN_KEY_MAY_BE_ENROLLED")
        return value


class RealmSupervisor:
    """Finite reference coordinator. It does not provision/stop a VM itself.

    The control transport releases a request only after record_dispatch returns.
    The supervisor controls reconfiguration and permits only fixed import/status
    messages. VHD output stays quarantined; there is no publish/export RPC here.
    """
    def __init__(self, config: SupervisorConfig):
        self.config = config

    def _capture_locked(self, *, kind: str, challenge: str, scope: dict,
                        request: dict | None):
        cfg, plan = self.config, self.config.plan()
        check_hash(challenge)
        if scope["target"] != plan["target"]:
            raise Unavailable("TARGET_DOMAIN_DIFFERS")
        binding = {"schema_version": 1, "purpose": "realm_capture_binding_v1",
            "approved_plan_sha256": cfg.approved_plan_sha256, "kind": kind,
            "challenge": challenge, "scope_digest": digest(scope),
            "request_digest": digest(request) if request else None,
            "operation_digest": digest(request["operations"]) if request else None}
        binding_bytes = canonical(binding)
        bind_path = cfg.state / "bindings" / (sha(binding_bytes) + ".json")
        publish_bytes(bind_path, binding_bytes)
        capture_path = cfg.state / "measurements" / (challenge + ".json")
        capture_path.parent.mkdir(parents=True, exist_ok=True)
        if os.name != "nt" or sha(cfg.crypto.verifier_script.read_bytes()) != cfg.crypto.verifier_script_sha256:
            raise Unavailable("PINNED_WINDOWS_COLLECTOR_REQUIRED")
        result = subprocess.run([str(cfg.crypto.powershell_exe), "-NoProfile", "-NonInteractive",
            "-File", str(cfg.crypto.verifier_script), "-Mode", "Capture",
            "-EnvelopePath", str(capture_path), "-ApprovedPlanPath", str(cfg.approved_plan),
            "-ExpectedPlanSha256", cfg.approved_plan_sha256,
            "-BindingPath", str(bind_path), "-ExpectedBindingSha256", sha(binding_bytes),
            "-Challenge", challenge, "-CertificateThumbprint", cfg.signing_certificate_thumbprint,
            "-ExpectedCertificateSha256", cfg.crypto.certificate_sha256],
            stdin=subprocess.DEVNULL, capture_output=True, timeout=45, check=False)
        if result.returncode != 0:
            raise Unavailable("REAL_OS_CAPTURE_UNAVAILABLE")
        measured = standard_verify(capture_path, cfg.crypto)
        _bound_measurement(measured, plan, cfg.approved_plan_sha256, binding_bytes,
                           challenge, kind, fresh=True)
        return {"binding_sha256": sha(binding_bytes), "measurement_sha256": measured.envelope_digest,
                "challenge": challenge, "kind": kind}, measured

    def capture_admission(self, *, kind: str, challenge: str, scope: dict,
                          request: dict | None = None) -> dict:
        if kind not in ("coverage", "prepare", "first_effect"):
            raise Unavailable("USE_RECORD_DISPATCH_FOR_EXECUTION")
        if request is not None:
            verify_original(request, self.config.new_target_secret)
        with process_lock(self.config.state / "realm-control.lock"):
            reference, _ = self._capture_locked(kind=kind, challenge=challenge, scope=scope, request=request)
            return reference

    def record_dispatch(self, *, request_bytes: bytes, scope: dict, challenge: str,
                        off_observations: tuple[dict, ...] = ()) -> dict:
        """Before queue/native release, preserve actual signed request + capture.

        A committed entry is not proof that dispatch happened. If a crash follows,
        observe that original attempt; never turn this into same-request retry.
        """
        cfg, plan = self.config, self.config.plan()
        request = decode(request_bytes)
        verify_original(request, cfg.new_target_secret)
        if str(uuid.UUID(request["request_id"])) != request["request_id"]:
            raise Unavailable("CANONICAL_REQUEST_ID_REQUIRED")
        if (request.get("runtime_epoch") != scope["runtime_epoch"]
                or request.get("adapter_fingerprint") != scope["loaded_fingerprint"]
                or (request.get("execution_context") or {}).get("run_id") != scope["run_id"]
                or scope["target"] != plan["target"]):
            raise Unavailable("SIGNED_NEW_REQUEST_SCOPE_DIFFERS")
        with process_lock(cfg.state / "realm-control.lock"):
            directory = cfg.state / "dispatches" / request["request_id"]
            if directory.exists():
                raise Unavailable("EXISTING_ATTEMPT_IS_OBSERVE_ONLY")
            directory.mkdir(parents=True, exist_ok=False)
            publish_bytes(directory / "request.json", request_bytes)
            reference, measured = self._capture_locked(kind="dispatch", challenge=challenge,
                                                       scope=scope, request=request)
            new_disks = {(d["identity"]["volume"], d["identity"]["file_id"]) for d in measured.payload["profile"]["disks"]}
            for observation in off_observations:
                old = verify_realm_off(observation, fresh=True)
                if old["realm"]["vm_id"] == plan["realm"]["vm_id"]:
                    raise Unavailable("OLD_REALM_CANNOT_BE_NEW_WORKSPACE")
                if new_disks & {(d["identity"]["volume"], d["identity"]["file_id"]) for d in old["disks"]}:
                    raise Unavailable("OLD_VHD_ALIAS_IN_NEW_WORKSPACE")
            body = {"schema_version": 1, "scope_kind": "hyperv_realm_v1",
                "authority_id": cfg.authority_id, "target": plan["target"], "realm": plan["realm"],
                "request_id": request["request_id"], "request_digest": digest(request),
                "raw_request_sha256": sha(request_bytes), "operation_digest": digest(request["operations"]),
                "runtime_epoch": request["runtime_epoch"], "scope": scope, "capture": reference,
                "measured_profile": measured.payload["profile"], "baseline": plan["baseline"],
                "off_observations": list(off_observations)}
            record = seal(body, cfg.new_target_secret, DISPATCH_PURPOSE)
            publish_bytes(directory / "committed.json", canonical(record))
            # The actual fixed transport call belongs AFTER this durable marker.
            return record

    def finalize_original(self, *, request_id: str, runtime_event_bytes: list[bytes]) -> dict:
        """Actual authenticated ordered receipts; result bytes persist outside VM.

        For unknown only, issue the manifest read by existing retirement_prepare.
        Never capture a replacement process now to fill historical dispatch data.
        """
        cfg, plan = self.config, self.config.plan()
        if str(uuid.UUID(request_id)) != request_id:
            raise Unavailable("CANONICAL_REQUEST_ID_REQUIRED")
        with process_lock(cfg.state / "realm-control.lock"):
            directory = cfg.state / "dispatches" / request_id
            dispatch = decode((directory / "committed.json").read_bytes())
            verify(dispatch, cfg.new_target_secret, DISPATCH_PURPOSE)
            request_raw = (directory / "request.json").read_bytes()
            request = decode(request_raw)
            verify_original(request, cfg.new_target_secret)
            if sha(request_raw) != dispatch["raw_request_sha256"] or digest(request) != dispatch["request_digest"]:
                raise Unavailable("ORIGINAL_DISPATCH_REQUEST_DIFFERS")
            previous = None
            context = request.get("execution_context") or {}
            for seq, raw in enumerate(runtime_event_bytes, 1):
                event = decode(raw)
                verify_original(event, cfg.new_target_secret)
                if (event.get("seq") != seq or event.get("request_id") != request_id
                        or event.get("request_digest") != digest(request)
                        or event.get("operation_digest") != digest(request["operations"])
                        or event.get("session_id") != request.get("session_id")
                        or event.get("host_instance_id", "") != request.get("host_instance_id", "")
                        or any(event.get(k) != context.get(k) for k in ("run_id", "step_id", "attempt_id", "lease_epoch"))
                        or previous is not None and previous.get("phase") == "terminal"
                        or event.get("dispatched") is True and event.get("runtime_epoch") != request["runtime_epoch"]):
                    raise Unavailable("ORIGINAL_NEW_TARGET_RECEIPT_CHAIN_DIFFERS")
                if event.get("terminal_result") is not None and digest(event["terminal_result"]) != event.get("result_digest"):
                    raise Unavailable("ORIGINAL_RESULT_DIGEST_DIFFERS")
                previous = event
            if previous is None or previous.get("phase") != "terminal":
                raise Unavailable("TERMINAL_NOT_YET_OBSERVED")
            archive = directory / "terminal-archive"
            if archive.exists():
                # Crash/reconnect observation, not native retry. Existing exact
                # prefix is read, never overwritten or reclassified.
                for seq, raw in enumerate(runtime_event_bytes, 1):
                    path = archive / f"{seq:012d}.json"
                    if path.exists() and path.read_bytes() != raw:
                        raise Unavailable("PERSISTED_ORIGINAL_RECEIPT_DIFFERS")
                    if not path.exists():
                        publish_bytes(path, raw)
            else:
                for seq, raw in enumerate(runtime_event_bytes, 1):
                    publish_bytes(archive / f"{seq:012d}.json", raw)
            terminal_reference = {"request_id": request_id, "terminal_bytes_sha256": sha(runtime_event_bytes[-1]),
                                  "terminal_payload_digest": digest(previous), "outcome": previous["outcome"]}
            if previous["outcome"] != "outcome_unknown":
                return terminal_reference
            original = {"domain": plan["target"], "request_id": request_id,
                "request_digest": digest(request), "operation_digest": digest(request["operations"]),
                "terminal_payload_digest": digest(previous), "terminal_bytes_digest": sha(runtime_event_bytes[-1]),
                "original_runtime_epoch": previous["runtime_epoch"], "original_run_id": context.get("run_id")}
            manifest = seal({"schema_version": 1, "scope_kind": "hyperv_realm_v1",
                "authority_id": cfg.authority_id, "original": original,
                "dispatch_record_digest": digest(dispatch), "capture": dispatch["capture"],
                "realm": dispatch["realm"], "baseline": dispatch["baseline"]}, cfg.new_target_secret, CLOSURE_PURPOSE)
            path = cfg.state / "producer-closures" / (request_id + ".json")
            if path.exists():
                if path.read_bytes() != canonical(manifest):
                    raise Unavailable("ORIGINAL_PRODUCER_CLOSURE_ALREADY_DIFFERS")
            else:
                publish_bytes(path, canonical(manifest))
            return dict(terminal_reference, producer_closure_digest=digest(manifest))

    def observe_original_realm_off(self, *, original_request_id: str, challenge: str) -> dict:
        """Current cessation observation for a FUTURE instrumented original.

        Read-only observation; this does not issue/approve/perform Stop-VM and
        never proves SDK success. It cannot operate on either legacy request,
        because those have no committed pre-dispatch realm manifest.
        """
        cfg = self.config
        if str(uuid.UUID(original_request_id)) != original_request_id:
            raise Unavailable("CANONICAL_REQUEST_ID_REQUIRED")
        with process_lock(cfg.state / "realm-control.lock"):
            manifest = decode((cfg.state / "producer-closures" / (original_request_id + ".json")).read_bytes())
            original = manifest["original"]
            initial = verify_scope(manifest, original)
            scope = {"target": original["domain"], "original_digest": digest(original),
                     "producer_manifest_digest": digest(manifest)}
            reference, measured = self._capture_locked(kind="observe_off", challenge=challenge,
                                                       scope=scope, request=None)
            if measured.payload["profile"]["disks"] != initial["profile"]["disks"]:
                raise Unavailable("ORIGINAL_REALM_STORAGE_IDENTITY_CHANGED")
            receipt = seal({"schema_version": 1, "purpose": "future_realm_cessation_observation_v1",
                "original": original, "producer_manifest_digest": digest(manifest),
                "realm": initial["realm"], "capture": reference,
                "disks": measured.payload["profile"]["disks"],
                "claim": "current_vm_off_no_historical_result_inference"}, cfg.new_target_secret, OFF_PURPOSE)
            publish_bytes(cfg.state / "realm-off" / (digest(receipt) + ".json"), canonical(receipt))
            return receipt


def _config(original: dict) -> SupervisorConfig:
    try:
        return _CONFIGS[original["domain"]["auth_domain_id"]]
    except KeyError as exc:
        raise Unavailable("TARGET_AUTHORITY_NOT_INSTALLED") from exc


def verify_scope(manifest: dict, original: dict) -> dict:
    """Real enrolled callback: union scope, NEVER finite process-list fiction."""
    cfg = _config(original)
    verify(manifest, cfg.new_target_secret, CLOSURE_PURPOSE)
    if manifest.get("original") != original or manifest.get("scope_kind") != "hyperv_realm_v1":
        raise Unavailable("ORIGINAL_REALM_MANIFEST_DIFFERS")
    directory = cfg.state / "dispatches" / original["request_id"]
    dispatch = decode((directory / "committed.json").read_bytes())
    verify(dispatch, cfg.new_target_secret, DISPATCH_PURPOSE)
    if (digest(dispatch) != manifest["dispatch_record_digest"]
            or dispatch["request_digest"] != original["request_digest"]
            or dispatch["operation_digest"] != original["operation_digest"]
            or dispatch["runtime_epoch"] != original["original_runtime_epoch"]):
        raise Unavailable("ORIGINAL_PREDISPATCH_RECORD_DIFFERS")
    ref = dispatch["capture"]
    binding_raw = (cfg.state / "bindings" / (ref["binding_sha256"] + ".json")).read_bytes()
    measured = standard_verify(cfg.state / "measurements" / (ref["challenge"] + ".json"), cfg.crypto)
    _bound_measurement(measured, cfg.plan(), cfg.approved_plan_sha256, binding_raw,
                       ref["challenge"], "dispatch", fresh=False)
    if measured.envelope_digest != ref["measurement_sha256"]:
        raise Unavailable("ORIGINAL_MEASUREMENT_BYTES_DIFFER")
    return {"scope_kind": "hyperv_realm_v1", "scope_revision": 1, "original": original,
        "manifest_digest": digest(manifest), "closure_evidence_digest": measured.envelope_digest,
        "realm": manifest["realm"], "profile": measured.payload["profile"],
        "producer_boundary": "entire_guest_with_fixed_supervisor_transport",
        "output_policy": "quarantine_vhd_no_export_until_off"}


def verify_baseline(ref: dict, original: dict) -> dict:
    from cascadeur_complete import incident_store as store
    cfg, plan = _config(original), _config(original).plan()
    expected = plan["baseline"]
    if ref != expected or expected["origin_kind"] != "immutable_fixture_generator":
        raise Unavailable("TRUSTED_FIXTURE_BASELINE_DIFFERS")
    path = Path(expected["path"])
    store.physical_identity(path)
    raw = path.read_bytes()
    if sha(raw) != expected["sha256"] or len(raw) != expected["size"]:
        raise Unavailable("TRUSTED_FIXTURE_BYTES_DIFFER")
    return {"path": str(path), "size": len(raw), "sha256": sha(raw),
        "origin_kind": expected["origin_kind"], "provenance_path": str(cfg.approved_plan),
        "provenance_sha256": cfg.approved_plan_sha256, "provenance_digest": cfg.approved_plan_sha256}


def verify_approval(component: dict, authorization: dict):
    # Reuse the existing durable retirement-started/control approval verifier.
    from cascadeur_complete.incident_control import verify_component_operator_approval
    return verify_component_operator_approval(component, authorization)


def verify_realm_off(receipt: dict, *, fresh: bool) -> dict:
    cfg = _config(receipt["original"])
    verify(receipt, cfg.new_target_secret, OFF_PURPOSE)
    if receipt.get("claim") != "current_vm_off_no_historical_result_inference":
        raise Unavailable("CESSATION_CLAIM_DIFFERS")
    manifest = decode((cfg.state / "producer-closures" / (receipt["original"]["request_id"] + ".json")).read_bytes())
    initial = verify_scope(manifest, receipt["original"])
    if digest(manifest) != receipt["producer_manifest_digest"] or receipt["realm"] != initial["realm"]:
        raise Unavailable("ORIGINAL_REALM_DIFFERS")
    ref = receipt["capture"]
    raw = (cfg.state / "bindings" / (check_hash(ref["binding_sha256"]) + ".json")).read_bytes()
    measured = standard_verify(cfg.state / "measurements" / (check_hash(ref["challenge"]) + ".json"), cfg.crypto)
    _bound_measurement(measured, cfg.plan(), cfg.approved_plan_sha256, raw, ref["challenge"], "observe_off", fresh=fresh)
    if (measured.envelope_digest != ref["measurement_sha256"]
            or measured.payload["profile"]["disks"] != receipt["disks"]
            or receipt["disks"] != initial["profile"]["disks"]
            or decode(raw)["scope_digest"] != digest({"target": receipt["original"]["domain"],
                "original_digest": digest(receipt["original"]), "producer_manifest_digest": digest(manifest)})):
        raise Unavailable("ACTUAL_OFF_OBSERVATION_DIFFERS")
    return receipt


def verify_workspace(payload, intent, retirements):
    """Realm backend owns fresh-target separation, not the finite file executor.

    Existing _enroll_authority requires a workspace callback. This adapter only
    accepts the already authenticated *new* target's captured realm comparison;
    all real envelopes are loaded by hash, not caller closed/verified flags.
    """
    cfg = _CONFIGS.get(intent.domain.auth_domain_id)
    if cfg is None or payload.get("intent") != asdict_intent(intent):
        raise Unavailable("NEW_WORK_INTENT_DIFFERS")
    request_id = payload["request_id"]
    if str(uuid.UUID(request_id)) != request_id:
        raise Unavailable("CANONICAL_REQUEST_ID_REQUIRED")
    directory = cfg.state / "dispatches" / request_id
    bundle = decode((directory / "committed.json").read_bytes())
    verify(bundle, cfg.new_target_secret, DISPATCH_PURPOSE)
    request = decode((directory / "request.json").read_bytes())
    verify_original(request, cfg.new_target_secret)
    from cascadeur_complete.incident_admission import intent_for
    if (asdict_intent(intent_for(request, intent.domain)) != payload["intent"]
            or digest(bundle) != payload["evidence_digest"] or digest(request) != bundle["request_digest"]):
        raise Unavailable("NEW_WORKSPACE_BUNDLE_DIFFERS")
    ref = bundle["capture"]
    raw = (cfg.state / "bindings" / (ref["binding_sha256"] + ".json")).read_bytes()
    measured = standard_verify(cfg.state / "measurements" / (ref["challenge"] + ".json"), cfg.crypto)
    _bound_measurement(measured, cfg.plan(), cfg.approved_plan_sha256, raw, ref["challenge"], "dispatch", fresh=True)
    # Proposed realm backend returns digest(actual Off receipt) in the existing
    # RetirementClosure.termination_evidence_digest field. No outer proof IDs
    # are equated with unrelated resource digests.
    if sorted(digest(item) for item in bundle["off_observations"]) != sorted(r.termination_evidence_digest for r in retirements):
        raise Unavailable("ALL_ORIGINAL_REALM_RETIREMENTS_REQUIRED")
    # The new realm must differ physically from each retained old realm. The
    # realm retirement backend validates signed Off observations before calling.
    new_disks = {(d["identity"]["volume"], d["identity"]["file_id"]) for d in measured.payload["profile"]["disks"]}
    for observation in bundle["off_observations"]:
        retired = verify_realm_off(observation, fresh=True)
        if retired["realm"]["vm_id"] == cfg.plan()["realm"]["vm_id"]:
            raise Unavailable("OLD_VM_CANNOT_BE_THE_NEW_WORKSPACE")
        if new_disks & {(d["identity"]["volume"], d["identity"]["file_id"]) for d in retired["disks"]}:
            raise Unavailable("OLD_VHD_ALIAS_IN_NEW_WORKSPACE")
    return {"scope_kind": "hyperv_realm_v1", "workspace_path": bundle["scope"]["workspace_path"],
        "baseline_digest": intent.baseline_digest, "resources": [],
        "realm": cfg.plan()["realm"], "current_measurement_digest": measured.envelope_digest}


def asdict_intent(intent):
    from dataclasses import asdict
    return asdict(intent)


def install_authority(config: SupervisorConfig):
    """Actual startup caller, proposed product+embedded module installation.

    Old _enroll_authority cannot handle realm scope and must reject, not silently
    pass this scope through _process or require invented process entries.
    """
    from cascadeur_complete import incident_resources as resources
    if "scope_kind" not in inspect.signature(resources._enroll_authority).parameters:
        raise Unavailable("R6_REALM_BACKEND_NOT_INSTALLED")
    domain_id = auth_domain_id(config.new_target_secret)
    if domain_id in _CONFIGS and _CONFIGS[domain_id] != config:
        raise Unavailable("TARGET_AUTHORITY_ALREADY_DIFFERS")
    config.plan()
    _CONFIGS[domain_id] = config
    resources._enroll_authority(config.authority_id, scope_kind="hyperv_realm_v1",
        receipt_secret=config.new_target_secret, verify_scope=verify_scope,
        verify_baseline=verify_baseline, verify_approval=verify_approval,
        verify_workspace=verify_workspace)


def capture_current_native_process() -> dict:
    """Future local metadata, not sufficient producer/resource closure by itself."""
    if os.name != "nt":
        raise Unavailable("WINDOWS_NATIVE_PROCESS_OBSERVATION_REQUIRED")
    from ctypes import wintypes as w
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetCurrentProcess.restype = w.HANDLE
    kernel.GetProcessTimes.argtypes = (w.HANDLE, ctypes.POINTER(w.FILETIME), ctypes.POINTER(w.FILETIME), ctypes.POINTER(w.FILETIME), ctypes.POINTER(w.FILETIME))
    kernel.GetProcessTimes.restype = w.BOOL
    kernel.GetModuleFileNameW.argtypes = (w.HMODULE, w.LPWSTR, w.DWORD)
    kernel.GetModuleFileNameW.restype = w.DWORD
    created, exited, kernel_time, user_time = (w.FILETIME() for _ in range(4))
    if not kernel.GetProcessTimes(kernel.GetCurrentProcess(), ctypes.byref(created), ctypes.byref(exited), ctypes.byref(kernel_time), ctypes.byref(user_time)):
        raise ctypes.WinError(ctypes.get_last_error())
    buffer = ctypes.create_unicode_buffer(32768)
    length = kernel.GetModuleFileNameW(None, buffer, len(buffer))
    if not length or length == len(buffer):
        raise Unavailable("NATIVE_IMAGE_PATH_UNAVAILABLE")
    image = Path(buffer.value)
    return {"scope_kind": "observed_partial_v1", "pid": os.getpid(),
        "creation_time_100ns": created.dwLowDateTime | created.dwHighDateTime << 32,
        "image_path": str(image), "image_sha256": sha(image.read_bytes()),
        "observed_at_ns": time.time_ns(), "closure_authority": "none"}


def record_local_dispatch_metadata(path: Path, request: dict, new_domain_secret: bytes):
    """Native pre-dispatch hook; an actual producer that never claims full scope."""
    verify_original(request, new_domain_secret)
    value = seal({"schema_version": 1, "request_digest": digest(request),
        "operation_digest": digest(request["operations"]), "runtime_epoch": request["runtime_epoch"],
        "native_process": capture_current_native_process()}, new_domain_secret, PARTIAL_PURPOSE)
    publish_bytes(path, canonical(value))
    return value
