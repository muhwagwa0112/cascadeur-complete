"""Python 3.11-compatible runtime identities, source guards and durable receipts.

Native adapter registration is internal. A client-provided complete=True never
creates an adapter or proves dependency coverage or native completion semantics.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import uuid
from pathlib import Path

RUNTIME_EPOCH = str(uuid.uuid4())
_SCENES = []
_ADAPTERS = {}
_ISSUED_SOURCES = {}
_LOCAL = threading.local()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _loaded_fingerprint():
    root = Path(__file__).parent
    material = {str(p.relative_to(root)).replace("\\", "/"): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(root.rglob("*.py"))}
    return digest(material)


LOADED_FINGERPRINT = _loaded_fingerprint()


def scene_instance(scene):
    for value, instance in _SCENES:
        if value is scene:
            return instance
    instance = {"scene_instance_id": str(uuid.uuid4()), "document_lineage_id": str(uuid.uuid4())}
    _SCENES.append((scene, instance))
    return instance


def link_clone(parent, child):
    scene_instance(child)["document_lineage_id"] = scene_instance(parent)["document_lineage_id"]


def register_adapter(operation_name, adapter):
    """Install code-owned reader/closure/effect semantics, never a wire capability.

    Adapter implements required_scope(scene, scope), capture(scene, scope),
    and carries verification describing the exact installed build and loaded
    bytes. Unsupported native APIs must not be filled in with defaults.
    """
    proof = adapter.verification
    evidence = getattr(adapter, "evidence_bytes", None)
    executor = getattr(adapter, "execute", None)
    if (proof.get("runtime_fingerprint") != LOADED_FINGERPRINT
            or _loaded_fingerprint() != LOADED_FINGERPRINT
            or proof.get("dispatch_semantics") != "synchronous_no_yield"
            or proof.get("identity_stable") is not True
            or not isinstance(evidence, bytes)
            or hashlib.sha256(evidence).hexdigest() != proof.get("evidence_sha256")
            or not callable(executor)
            or operation_name not in proof.get("operations", ())
            or proof.get("installed_build") != adapter.observed_build()):
        raise ValueError("RIG_ADAPTER_UNVERIFIED")
    _ADAPTERS[operation_name] = adapter


def capabilities():
    return {"guarded_mutation": bool(_ADAPTERS), "source_binding": bool(_ADAPTERS),
            "identity_verified": bool(_ADAPTERS), "dispatch_semantics": "unverified" if not _ADAPTERS else "synchronous_no_yield",
            "operations": sorted(_ADAPTERS), "protocols": ["3.0"], "legacy_read_protocols": ["2.0"]}


def capture_source(scene, scope, inputs_digest, sample_digest=None, selection_digest=None):
    assert_loaded_package()
    operation = scope.get("operation_name")
    adapter = _ADAPTERS.get(operation)
    if adapter is None:
        raise ValueError("BINDING_UNAVAILABLE: no verified dependency reader for " + str(operation))
    return _capture_with_adapter(scene, scope, inputs_digest, sample_digest, selection_digest, adapter)


def _capture_with_adapter(scene, scope, inputs_digest, sample_digest, selection_digest, adapter):
    required = adapter.required_scope(scene, scope)
    if digest(required) != digest(scope):
        raise ValueError("INCOMPLETE_CAPTURE: requested scope differs from required dependency closure")
    captured = adapter.capture(scene, required)
    if captured.get("coverage_complete") is not True:
        raise ValueError("INCOMPLETE_CAPTURE")
    evaluated = digest(captured["sample_projection"])
    if sample_digest is not None and sample_digest != evaluated:
        raise ValueError("SCENE_CHANGED: evaluated source projection differs")
    binding = {"schema_version": 1, "runtime_epoch": RUNTIME_EPOCH, **scene_instance(scene),
               "revision_kind": "scope_digest", "scope_digest": digest(required),
               "content_revision": digest({"scope_digest": digest(required), "content": captured["authored_projection"]}),
               "selection_digest": selection_digest}
    source = {"schema_version": 1, "binding": binding, "scope": required,
              "sample_digest": evaluated, "inputs_digest": inputs_digest,
              "adapter_fingerprint": LOADED_FINGERPRINT, "complete": True}
    _ISSUED_SOURCES[digest(source)] = source
    return source


def assert_source(scene, source, *, operation_name=None, arguments=None):
    if not isinstance(source, dict) or digest(source) not in _ISSUED_SOURCES:
        raise ValueError("BINDING_UNAVAILABLE: source was not issued by this runtime")
    if not source.get("complete") or source.get("adapter_fingerprint") != LOADED_FINGERPRINT:
        raise ValueError("BINDING_UNAVAILABLE")
    expected = source["binding"]
    if expected["runtime_epoch"] != RUNTIME_EPOCH or expected["scene_instance_id"] != scene_instance(scene)["scene_instance_id"]:
        raise ValueError("SCENE_CHANGED: scene instance or epoch differs")
    if operation_name is not None and source["scope"].get("operation_name") != operation_name:
        raise ValueError("BINDING_UNAVAILABLE: operation scope differs")
    if arguments is not None and source["scope"].get("operation_arguments_digest") != digest(arguments):
        raise ValueError("BINDING_UNAVAILABLE: operation arguments differ")
    actual = capture_source(scene, source["scope"], source["inputs_digest"], source["sample_digest"], expected.get("selection_digest"))
    if actual != source:
        raise ValueError("SCENE_CHANGED: authored source differs")
    return actual


def begin_request(request):
    _LOCAL.request = request
    _LOCAL.write_phase = "not_started"
    _LOCAL.failure_kind = None
    _LOCAL.guard = None
    _LOCAL.effects = []


def assert_loaded_package():
    if _loaded_fingerprint() != LOADED_FINGERPRINT:
        raise ValueError("PROTOCOL_MISMATCH: package changed; clean runtime restart required")


def observe_effect(operation_name, completion, *, scene_before, scene_after, detail=None):
    if completion not in {"completed", "no_effect", "unknown"}:
        raise ValueError("Invalid native completion observation")
    item = {"operation_name": operation_name, "completion": completion,
            "scene_before": scene_before, "scene_after": scene_after, "detail": detail or {}}
    _LOCAL.effects = getattr(_LOCAL, "effects", []) + [item]
    return item


def effect_observations():
    return list(getattr(_LOCAL, "effects", ()))


def set_write_guard(guard):
    _LOCAL.guard = guard


def before_write(source_guard=None):
    try:
        source_guard = source_guard or getattr(_LOCAL, "guard", None)
        if source_guard is not None:
            source_guard()
    except Exception:
        _LOCAL.failure_kind = ("guard_rejected_before_first_write"
            if getattr(_LOCAL, "write_phase", "not_started") == "not_started"
            else "guard_rejected_after_partial_write")
        raise
    _LOCAL.write_phase = "started"


def finish_write():
    _LOCAL.write_phase = "completed"


def write_observation():
    return getattr(_LOCAL, "write_phase", "unknown"), getattr(_LOCAL, "failure_kind", None)


def previous_terminal(root, request):
    from .runtime import _bridge_key, _sign_message
    import hmac
    directory = root / "state" / "request_records" / request["request_id"]
    original_path = directory / "request.json"
    if original_path.is_file() and json.loads(original_path.read_text(encoding="utf-8")) != request:
        raise ValueError("REQUEST_ID_CONFLICT")
    for index, path in enumerate(sorted((directory / "runtime_events").glob("*.json")), 1):
        item = json.loads(path.read_text(encoding="utf-8"))
        if (not hmac.compare_digest(item.get("mac", ""), _sign_message(item, _bridge_key(root)))
                or item.get("request_digest") != digest(request) or item.get("seq") != index):
            raise ValueError("INVALID_RECEIPT")
        if item["phase"] == "terminal":
            result = item.get("terminal_result")
            if not isinstance(result, dict) or digest(result) != item.get("result_digest"):
                raise ValueError("INVALID_RECEIPT")
            return result
    return None


def canceled(root, request):
    from .runtime import _bridge_key, _sign_message
    import hmac
    directory = root / "state" / "request_records" / request["request_id"]
    for name in ("cancel_intent.json", "host_canceled.json"):
        path = directory / name
        if not path.is_file():
            continue
        item = json.loads(path.read_text(encoding="utf-8"))
        if (hmac.compare_digest(item.get("mac", ""), _sign_message(item, _bridge_key(root)))
                and item.get("request_digest") == digest(request)):
            return True
    return False


def receipt_event(root, request, phase, *, outcome="pending", result=None, effect_class="none", dispatched=None):
    from .runtime import _bridge_key, _sign_message, _verify_message, atomic_json
    directory = root / "state" / "request_records" / request["request_id"]
    original_path = directory / "request.json"
    if not original_path.is_file():
        # A legacy sender can be read, but cannot bootstrap a guarded mutation.
        atomic_json(original_path, request)
    original = json.loads(original_path.read_text(encoding="utf-8"))
    _verify_message(original, _bridge_key(root))
    if original != request:
        raise ValueError("REQUEST_ID_CONFLICT")
    events = directory / "runtime_events"
    events.mkdir(parents=True, exist_ok=True)
    existing = sorted(events.glob("*.json"))
    if existing:
        latest = json.loads(existing[-1].read_text(encoding="utf-8"))
        if latest.get("phase") == "terminal":
            raise ValueError("Request already terminal")
    seq = len(existing) + 1
    write_phase, failure = write_observation()
    payload = {"schema_version": 1, "request_id": request["request_id"], "request_digest": digest(request),
               "operation_digest": digest(request.get("operations", [])), "session_id": request["session_id"],
               "runtime_epoch": RUNTIME_EPOCH, "host_instance_id": request.get("host_instance_id", ""),
               "run_id": (request.get("execution_context") or {}).get("run_id"),
               "step_id": (request.get("execution_context") or {}).get("step_id"),
               "attempt_id": (request.get("execution_context") or {}).get("attempt_id"),
               "lease_epoch": (request.get("execution_context") or {}).get("lease_epoch"),
               "phase": phase, "outcome": outcome, "dispatched": dispatched,
               "scene_before": (result or {}).get("scene_before"), "scene_after": (result or {}).get("scene_after"),
               "effect_class": effect_class, "write_phase": (result or {}).get("write_phase", write_phase),
               "failure_kind": (result or {}).get("failure_kind", failure),
               "recovery_eligible": phase == "terminal" and (result or {}).get("recovery_eligible") is True,
               "mutation_observed": None, "terminal_result": result if phase == "terminal" else None,
               "result_digest": digest(result) if result is not None else None,
               "recovery": None, "seq": seq, "mac": ""}
    payload["mac"] = _sign_message(payload, _bridge_key(root))
    target = events / (f"{seq:04d}-" + phase + ".json")
    if target.exists():
        raise ValueError("Receipt sequence already exists")
    atomic_json(target, payload)
    return payload
