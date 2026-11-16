"""Private historical sources with a mandatory admitted fresh-Update gate.

A readonly source request never opens an Update. It may name a closed actual
snapshot, while only an executor's callback can establish current graph equality.
There is no wire snapshot/facts issuer and generic assert_source stays strict.
"""
from __future__ import annotations

import copy
import json

from .native_update_capture import UpdateSnapshot, frozen_json, _NATIVE_SNAPSHOT_STORES

MODE = "qualified_update_boundary"
_SOURCES = {}
_CHECKED = {}
_MAX_SOURCES = 1024


def is_graph_source(source):
    return isinstance(source, dict) and source.get("scope", {}).get("validation_mode") == MODE


def _snapshot(scene, snapshot):
    from . import guarded_runtime as guards, runtime as rt
    from .native_adapters import installed_build
    from .native_export import selection_observation
    guards.assert_loaded_package()
    if rt._scene_view() is not scene or not isinstance(snapshot, UpdateSnapshot):
        raise ValueError("UPDATE_PRIVATE_ACTIVE_SNAPSHOT_REQUIRED")
    key = (installed_build(), guards.RUNTIME_EPOCH, guards.LOADED_FINGERPRINT)
    if _NATIVE_SNAPSHOT_STORES.get(key, {}).get(id(snapshot)) is not snapshot:
        raise ValueError("UPDATE_SNAPSHOT_NOT_PRIVATELY_ISSUED")
    context = json.loads(snapshot.context_bytes)
    current = {"installed_build": key[0], "runtime_epoch": key[1], "runtime_fingerprint": key[2],
        "scene": dict(guards.scene_instance(scene)), "selection": selection_observation(scene),
        "frame": int(rt._domain_scene(scene).get_current_frame(False))}
    if frozen_json(current) != snapshot.context_bytes:
        raise ValueError("UPDATE_SNAPSHOT_CONTEXT_CHANGED")
    return context


def latest_closed_snapshot(scene, *, expected_graph_dtype_digest=None):
    from . import guarded_runtime as guards
    from .native_adapters import installed_build
    from .native_scene_reader import read_scene
    store = _NATIVE_SNAPSHOT_STORES.get((installed_build(), guards.RUNTIME_EPOCH, guards.LOADED_FINGERPRINT), {})
    raw = frozen_json(read_scene(scene))
    for snapshot in reversed(tuple(store.values())):
        if snapshot.projection_bytes != raw:
            continue
        try:
            _snapshot(scene, snapshot)
        except ValueError:
            continue
        if expected_graph_dtype_digest is None or guards.digest(snapshot.facts.material()) == expected_graph_dtype_digest:
            return snapshot
    raise ValueError("UPDATE_CLOSED_SOURCE_SNAPSHOT_UNAVAILABLE: explicit admitted evaluation is required")


def graph_scope(scope, graph_dtype_digest):
    return {**scope, "validation_mode": MODE, "expected_graph_dtype_digest": graph_dtype_digest}


def _registered_adapter(scene, scope):
    from . import guarded_runtime as guards
    adapter = guards._ADAPTERS.get(scope.get("operation_name"))
    if adapter is None or getattr(adapter, "accepts_update_boundary_source", lambda *_: False)(scene, scope) is not True:
        raise ValueError("UPDATE_BOUNDARY_ADAPTER_NOT_PRIVATELY_QUALIFIED")
    if adapter.required_scope(scene, scope) != scope:
        raise ValueError("UPDATE_BOUNDARY_SCOPE_DIFFERS")
    return adapter


def issue_operation_source_from_closed_snapshot(scene, scope, inputs_digest, snapshot,
                                                 selection_digest=None):
    """Native-only issuer. Preserve the actual closed graph/raw observation."""
    from . import guarded_runtime as guards
    from .native_scene_reader import read_scene
    context = _snapshot(scene, snapshot)
    if scope.get("validation_mode") != MODE:
        raise ValueError("UPDATE_BOUNDARY_SOURCE_MODE_REQUIRED")
    _registered_adapter(scene, scope)
    graph = guards.digest(snapshot.facts.material())
    if scope.get("expected_graph_dtype_digest") != graph or frozen_json(read_scene(scene)) != snapshot.projection_bytes:
        raise ValueError("UPDATE_BOUNDARY_HISTORICAL_RAW_OR_GRAPH_DIFFERS")
    if not isinstance(inputs_digest, str) or len(inputs_digest) != 64:
        raise ValueError("UPDATE_BOUNDARY_INPUTS_DIGEST_REQUIRED")
    scope = copy.deepcopy(scope)
    scope_digest = guards.digest(scope)
    binding = {"schema_version": 1, "runtime_epoch": context["runtime_epoch"], **context["scene"],
        "revision_kind": "scope_digest", "scope_digest": scope_digest,
        "content_revision": guards.digest({"scope_digest": scope_digest, "content": snapshot.projection}),
        "selection_digest": selection_digest}
    source = {"schema_version": 1, "binding": binding, "scope": scope,
        "sample_digest": guards.digest(snapshot.projection), "inputs_digest": inputs_digest,
        "adapter_fingerprint": context["runtime_fingerprint"], "complete": True}
    key = guards.digest(source)
    if key not in _SOURCES and len(_SOURCES) >= _MAX_SOURCES:
        raise ValueError("UPDATE_BOUNDARY_SOURCE_RECORD_BUDGET")
    _SOURCES[key] = (scene, source, snapshot)
    # This is the same code-owned registry used by existing source issuance;
    # caller dict equality cannot manufacture the accompanying private handle.
    guards._ISSUED_SOURCES[key] = copy.deepcopy(source)
    return copy.deepcopy(source)


def issue_source_from_latest_snapshot(scene, scope, inputs_digest, sample_digest=None, selection_digest=None):
    snapshot = latest_closed_snapshot(scene, expected_graph_dtype_digest=scope.get("expected_graph_dtype_digest"))
    from . import guarded_runtime as guards
    if sample_digest is not None and sample_digest != guards.digest(snapshot.projection):
        raise ValueError("UPDATE_BOUNDARY_SAMPLE_PROJECTION_DIFFERS")
    return issue_operation_source_from_closed_snapshot(scene, scope, inputs_digest, snapshot, selection_digest)


def assert_historical_source(scene, source, *, operation_name=None, arguments=None):
    """Identity/scope/actual raw check ONLY; no current-graph claim is made."""
    from . import guarded_runtime as guards
    from .native_scene_reader import read_scene
    if not is_graph_source(source):
        return guards.assert_source(scene, source, operation_name=operation_name, arguments=arguments)
    key = guards.digest(source)
    record = _SOURCES.get(key)
    if record is None or record[0] is not scene or record[1] != source or guards._ISSUED_SOURCES.get(key) != source:
        raise ValueError("UPDATE_SOURCE_NOT_PRIVATELY_ISSUED")
    snapshot = record[2]
    _snapshot(scene, snapshot)
    _registered_adapter(scene, source["scope"])
    if operation_name is not None and source["scope"].get("operation_name") != operation_name:
        raise ValueError("UPDATE_SOURCE_OPERATION_DIFFERS")
    if arguments is not None and source["scope"].get("operation_arguments_digest") != guards.digest(arguments):
        raise ValueError("UPDATE_SOURCE_ARGUMENTS_DIFFER")
    if frozen_json(read_scene(scene)) != snapshot.projection_bytes:
        raise ValueError("UPDATE_SOURCE_RAW_PROJECTION_CHANGED")
    return copy.deepcopy(source)


def assert_callback_source(scene, source, projection, facts):
    """Executor calls this before its FIRST calc/file/data effect in Update."""
    from . import guarded_runtime as guards
    assert_historical_source(scene, source)
    request = getattr(guards._LOCAL, "request", None)
    if request is None or request.get("source_binding") != source:
        raise ValueError("UPDATE_SOURCE_CURRENT_DISPATCH_REQUIRED")
    if request["request_id"] not in _CHECKED and len(_CHECKED) >= _MAX_SOURCES:
        raise ValueError("UPDATE_BOUNDARY_CHECK_RECORD_BUDGET")
    record = _SOURCES[guards.digest(source)]
    if (frozen_json(projection) != record[2].projection_bytes
            or frozen_json(facts.material()) != frozen_json(record[2].facts.material())):
        raise ValueError("UPDATE_CURRENT_PRODUCER_GRAPH_OR_DTYPE_CHANGED")
    _CHECKED[request["request_id"]] = (scene, request, source, facts)


def require_callback_check(scene, request):
    record = _CHECKED.get(request.get("request_id"))
    if record is None or record[0] is not scene or record[1] is not request or record[2] != request.get("source_binding"):
        raise ValueError("UPDATE_CURRENT_GRAPH_NOT_CHECKED_IN_DISPATCH")


def post_source_from_snapshot(scene, request, snapshot):
    """Full after snapshot, never a reread claiming cached graph is current."""
    require_callback_check(scene, request)
    source = request["source_binding"]
    return issue_operation_source_from_closed_snapshot(scene, source["scope"], source["inputs_digest"], snapshot,
                                                       source["binding"].get("selection_digest"))
