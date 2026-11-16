"""Process-private failed-execution observations, never wire authority.

Adapters own the native lifetime/scope verifier. This registry binds its output
to the original attempt and rechecks the live verifier before terminal sealing.
Successful adapters retain their existing completion contracts.
"""
from __future__ import annotations

import copy
import hashlib
import json
import threading

_LOCK = threading.RLock()
_ATTEMPTS = {}
_REQUESTS = {}
_NEXT_GENERATION = 0
_QUARANTINE = []


def _freeze(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False).encode()


def _sha(value):
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


class _Attempt:
    pass


def epoch_status():
    with _LOCK:
        return {"quarantined": bool(_QUARANTINE), "incidents": copy.deepcopy(_QUARANTINE)}


def assert_epoch_usable():
    if epoch_status()["quarantined"]:
        raise ValueError("NATIVE_COMPLETION_EPOCH_QUARANTINED: retained callback violated a sealed native contract")


def _revoke(item, reason):
    item["revoked"] = True
    item["reason"] = str(reason)[:500]
    if (item.get("receipt_digest") and (item.get("sealed_completion") or item.get("incident_closure_refs"))
            and not item.get("quarantined")):
        item["quarantined"] = True
        _QUARANTINE.append({"request_digest": item["request_digest"],
            "observation_ref": item.get("record_ref"), "receipt_digest": item["receipt_digest"],
            "runtime_epoch": item["runtime_epoch"], "reason": item["reason"]})


def poll_revocations():
    """Inspect retained live traces without rereading a changed scene/source."""
    with _LOCK:
        for item in _ATTEMPTS.values():
            if item.get("record_ref") is None or item["revoked"]:
                continue
            checker = getattr(item["adapter"], "failure_observation_revoked", None)
            try:
                revoked = not callable(checker) or checker(item["record_ref"]) is not False
            except Exception:
                revoked = True
            if revoked:
                _revoke(item, "NATIVE_FAILURE_CALLBACK_BOUNDARY_CHANGED")


def begin_adapter_attempt(request, operation, adapter, scene):
    from . import guarded_runtime as guards
    global _NEXT_GENERATION
    poll_revocations()
    assert_epoch_usable()
    if (getattr(guards._LOCAL, "request", None) is not request
            or guards._ADAPTERS.get(operation.get("name")) is not adapter
            or request.get("operations") != [operation]
            or not isinstance(request.get("source_binding"), dict)):
        raise ValueError("NATIVE_ATTEMPT_BINDING_UNAVAILABLE")
    guards.assert_loaded_package()
    proof = adapter.verification
    evidence = getattr(adapter, "evidence_bytes", None)
    if (not isinstance(evidence, bytes) or hashlib.sha256(evidence).hexdigest() != proof.get("evidence_sha256")
            or proof.get("runtime_fingerprint") != guards.LOADED_FINGERPRINT
            or proof.get("installed_build") != adapter.observed_build()):
        raise ValueError("NATIVE_ATTEMPT_ADAPTER_CHANGED")
    request_digest = guards.digest(request)
    with _LOCK:
        if request_digest in _REQUESTS:
            raise ValueError("NATIVE_ATTEMPT_CONSUMED: original native effect cannot be replayed")
        if len(_ATTEMPTS) >= 4096:
            raise ValueError("NATIVE_COMPLETION_CAPACITY_EXCEEDED")
        _NEXT_GENERATION += 1
        handle = _Attempt()
        _ATTEMPTS[handle] = {"request": request, "request_bytes": _freeze(request),
            "request_digest": request_digest, "operation": copy.deepcopy(operation),
            "operation_digest": guards.digest(request["operations"]),
            "original_source_digest": guards.digest(request["source_binding"]),
            "runtime_epoch": guards.RUNTIME_EPOCH, "runtime_fingerprint": guards.LOADED_FINGERPRINT,
            "installed_build": proof["installed_build"], "scene": scene,
            "scene_before": dict(guards.scene_instance(scene)), "adapter": adapter,
            "evidence_digest": hashlib.sha256(evidence).hexdigest(),
            "adapter_verification_bytes": _freeze(proof), "thread": threading.get_ident(),
            "callback_generation": _NEXT_GENERATION, "effect_start": len(guards.effect_observations()),
            "record_ref": None, "record_bytes": None, "revoked": False, "closed": False}
        _REQUESTS[request_digest] = handle
        guards._LOCAL.adapter_attempt = handle
        return handle


def current_adapter_attempt():
    from . import guarded_runtime as guards
    return getattr(guards._LOCAL, "adapter_attempt", None)


def adapter_attempt_identity(handle):
    with _LOCK:
        item = _ATTEMPTS.get(handle)
        if item is None or item["closed"] or item["revoked"]:
            raise ValueError("NATIVE_ATTEMPT_UNAVAILABLE")
        return copy.deepcopy({key: item[key] for key in ("request_digest", "operation_digest",
            "original_source_digest", "runtime_epoch", "runtime_fingerprint", "installed_build",
            "scene_before", "callback_generation")})


def _checked_record(handle, scene, request, record_ref):
    from . import guarded_runtime as guards
    item = _ATTEMPTS.get(handle)
    if (item is None or item["revoked"] or item["scene"] is not scene
            or item["request"] is not request or _freeze(request) != item["request_bytes"]
            or getattr(guards._LOCAL, "request", None) is not request
            or threading.get_ident() != item["thread"]
            or guards._ADAPTERS.get(item["operation"]["name"]) is not item["adapter"]
            or guards.RUNTIME_EPOCH != item["runtime_epoch"] or guards.LOADED_FINGERPRINT != item["runtime_fingerprint"]
            or dict(guards.scene_instance(scene)) != item["scene_before"]):
        raise ValueError("NATIVE_FAILURE_ATTEMPT_CHANGED")
    adapter = item["adapter"]
    guards.assert_loaded_package()
    if (hashlib.sha256(adapter.evidence_bytes).hexdigest() != item["evidence_digest"]
            or adapter.observed_build() != item["installed_build"]):
        raise ValueError("NATIVE_FAILURE_ADAPTER_CHANGED")
    validator = getattr(adapter, "validate_failure_observation", None)
    if not callable(validator):
        raise ValueError("PRIVATE_FAILURE_VALIDATOR_UNAVAILABLE")
    record = validator(scene, request, record_ref)
    if not isinstance(record, dict):
        raise ValueError("PRIVATE_FAILURE_RECORD_UNAVAILABLE")
    identity = {key: item[key] for key in ("request_digest", "operation_digest", "original_source_digest",
        "runtime_epoch", "runtime_fingerprint", "installed_build", "scene_before", "callback_generation")}
    if (record.get("contract") != "completed_native_failure_v1"
            or any(record.get(key) != value for key, value in identity.items())
            or record.get("scene_after") != dict(guards.scene_instance(scene))
            or record.get("completion") not in {"completed", "no_effect"}
            or record.get("postcondition") != "mismatched"
            or any(not _sha(record.get(key)) for key in ("before_projection_digest", "expected_projection_digest",
                "actual_after_digest", "actual_effect_scope_digest", "native_contract_evidence_digest"))
            or (record.get("completion") == "no_effect"
                and record["before_projection_digest"] != record["actual_after_digest"])
            or not isinstance(record.get("primary_error"), dict)):
        raise ValueError("PRIVATE_FAILURE_RECORD_DIFFERS")
    observation = record.get("effect_observation")
    if (not isinstance(observation, dict) or observation.get("operation_name") != item["operation"]["name"]
            or observation.get("completion") != record["completion"]
            or observation.get("scene_before") != record["scene_before"]
            or observation.get("scene_after") != record["scene_after"]):
        raise ValueError("PRIVATE_FAILURE_EFFECT_DIFFERS")
    return record


def bind_failure_observation(handle, adapter_record_ref):
    """The reference is an index only; the registered adapter supplies authority."""
    with _LOCK:
        item = _ATTEMPTS.get(handle)
        if item is None or item["closed"] or not isinstance(adapter_record_ref, str):
            raise ValueError("NATIVE_FAILURE_ATTEMPT_UNAVAILABLE")
        if item["record_ref"] is not None and item["record_ref"] != adapter_record_ref:
            _revoke(item, "CONFLICTING_PRIVATE_FAILURE_OBSERVATIONS")
            raise ValueError("CONFLICTING_PRIVATE_FAILURE_OBSERVATIONS")
        record = _checked_record(handle, item["scene"], item["request"], adapter_record_ref)
        frozen = _freeze(record)
        if item["record_bytes"] is not None and item["record_bytes"] != frozen:
            _revoke(item, "PRIVATE_FAILURE_RECORD_MUTATED")
            raise ValueError("PRIVATE_FAILURE_RECORD_MUTATED")
        item.update(record_ref=adapter_record_ref, record_bytes=frozen)
        return handle


def lookup_failure_observation(handle, scene, request):
    """Validation errors are diagnostic; never replace the executor exception."""
    with _LOCK:
        item = _ATTEMPTS.get(handle)
        if item is None or item["record_ref"] is None or item["revoked"]:
            return None
        try:
            record = _checked_record(handle, scene, request, item["record_ref"])
            if _freeze(record) != item["record_bytes"]:
                raise ValueError("PRIVATE_FAILURE_RECORD_MUTATED")
            observation = copy.deepcopy(record["effect_observation"])
            observation["private_failure_observation"] = {"reference": item["record_ref"],
                "digest": hashlib.sha256(item["record_bytes"]).hexdigest()}
            return observation
        except Exception as exc:
            _revoke(item, str(exc))
            return None


def selected_effect_for_request(request, scene):
    from . import guarded_runtime as guards
    poll_revocations()
    if getattr(guards._LOCAL, "request", None) is not request or len(request.get("operations", ())) != 1:
        return None
    name = request["operations"][0]["name"]
    unknown = {"operation_name": name, "completion": "unknown", "scene_before": None,
               "scene_after": None, "detail": {"reason": "PRIVATE_NATIVE_COMPLETION_UNAVAILABLE"}}
    with _LOCK:
        handle = _REQUESTS.get(guards.digest(request))
        item = _ATTEMPTS.get(handle)
        if item is not None and (item["revoked"] or item["request_bytes"] != _freeze(request)):
            return unknown
        effects = guards.effect_observations()
        # Unknown/revocation cannot be hidden by a later completed dictionary.
        if any(effect.get("completion") == "unknown" for effect in effects):
            return unknown
        if item is not None and item["record_ref"] is not None:
            observation = lookup_failure_observation(handle, scene, request)
            if observation is None:
                return unknown
            raw = {key: value for key, value in observation.items() if key != "private_failure_observation"}
            if any(guards.digest(effect) != guards.digest(raw) for effect in effects):
                return unknown
            return observation
        # Existing success adapters are not rewritten into the failure contract.
        return effects[-1] if effects and effects[-1].get("operation_name") == name else None


def revoke_adapter_observation(request, reason):
    from . import guarded_runtime as guards
    with _LOCK:
        handle = _REQUESTS.get(guards.digest(request))
        item = _ATTEMPTS.get(handle)
        if item is not None and item["request"] is request:
            _revoke(item, reason)


def close_adapter_attempt(handle):
    with _LOCK:
        item = _ATTEMPTS.get(handle)
        if item is not None:
            item["closed"] = True


def finalize_failure_observation(request, result, receipt):
    """Link a durable terminal after sealing; never insert its digest into itself."""
    from . import guarded_runtime as guards
    with _LOCK:
        handle = _REQUESTS.get(guards.digest(request))
        item = _ATTEMPTS.get(handle)
        if item is None:
            return
        if (receipt.get("phase") != "terminal" or receipt.get("request_digest") != item["request_digest"]
                or receipt.get("result_digest") != guards.digest(result) or receipt.get("terminal_result") != result):
            _revoke(item, "NATIVE_TERMINAL_BINDING_DIFFERS")
            raise ValueError("NATIVE_TERMINAL_BINDING_DIFFERS")
        item["receipt_digest"] = guards.digest(receipt)
        item["sealed_completion"] = receipt.get("outcome") == "succeeded" or (
            receipt.get("outcome") == "failed_after_dispatch" and item["record_ref"] is not None)
        item["closed"] = True
        if item["revoked"]:
            _revoke(item, item["reason"])
        elif item["record_ref"] is not None and lookup_failure_observation(handle, item["scene"], request) is None:
            _revoke(item, "NATIVE_FAILURE_REVOKED_AFTER_TERMINAL")


def retained_original_closure(request_digest, terminal_payload_digest, *, observation_ref=None):
    """Read a historical, privately validated closure without touching its scene.

    The original source has been consumed and the scene may since have changed.
    Only the retained immutable record and its still-live callback boundary are
    eligible here. Recovery availability, current source and client flags confer
    no completion authority. A missing private record remains unavailable.
    """
    from . import guarded_runtime as guards
    poll_revocations()
    guards.assert_loaded_package()
    with _LOCK:
        item = _ATTEMPTS.get(_REQUESTS.get(request_digest))
        if (item is None or not item["closed"] or item["revoked"]
                or item.get("receipt_digest") != terminal_payload_digest
                or not item.get("record_ref") or not isinstance(item.get("record_bytes"), bytes)
                or item["request_bytes"] != _freeze(item["request"])
                or item["runtime_epoch"] != guards.RUNTIME_EPOCH
                or item["runtime_fingerprint"] != guards.LOADED_FINGERPRINT
                or guards._ADAPTERS.get(item["operation"]["name"]) is not item["adapter"]):
            raise ValueError("ORIGINAL_ATTEMPT_PRIVATE_CLOSURE_UNAVAILABLE")
        adapter = item["adapter"]
        if (not isinstance(getattr(adapter, "evidence_bytes", None), bytes)
                or hashlib.sha256(adapter.evidence_bytes).hexdigest() != item["evidence_digest"]
                or _freeze(adapter.verification) != item.get("adapter_verification_bytes")):
            _revoke(item, "ORIGINAL_ATTEMPT_ADAPTER_CHANGED")
            raise ValueError("ORIGINAL_ATTEMPT_ADAPTER_CHANGED")
        # _checked_record authenticated this exact frozen record at issuance.
        # poll_revocations rechecks retained private traces, never the SDK.
        record = json.loads(item["record_bytes"])
        summary = {
            "request_digest": item["request_digest"], "operation_digest": item["operation_digest"],
            "original_source_digest": item["original_source_digest"],
            "runtime_epoch": item["runtime_epoch"], "loaded_fingerprint": item["runtime_fingerprint"],
            "installed_build": item["installed_build"], "callback_generation": item["callback_generation"],
            "private_record_digest": hashlib.sha256(item["record_bytes"]).hexdigest(),
            "observed_completion": "proved_no_effect" if record["completion"] == "no_effect" else "proved_completed_failure",
            "actual_effect_closure_digest": record["actual_effect_scope_digest"],
            "actual_after_digest": record["actual_after_digest"],
            "native_contract_evidence_digest": record["native_contract_evidence_digest"],
        }
        # A later trace violation revokes an issued incident observation even
        # when the preserved original terminal was outcome_unknown.
        if observation_ref is not None:
            if not isinstance(observation_ref, str) or not observation_ref:
                raise ValueError("INVALID_INCIDENT_OBSERVATION_REFERENCE")
            item.setdefault("incident_closure_refs", set()).add(observation_ref)
        return copy.deepcopy(summary)
