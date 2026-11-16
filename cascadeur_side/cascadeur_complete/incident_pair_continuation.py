"""Explicit finite continuation of one actually completed owned-pair setup.

This module lowers only the fixed sequence below. Request values come from an
authenticated setup result and authenticated preceding terminals, never guessed
object IDs or caller-supplied success flags. The native adapters independently
check the live private pair, source, confirmation token and actual completion.
"""
from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
import math
from pathlib import Path
import sys
import time
import uuid

from . import incident_policy as p
from . import incident_store as store
from . import incident_manual_setup as manual

ROUTE = "manual_legacy_pair_continuation_v1"
PROFILE = "owned_two_identity_bind_dense_translation_joint_meshes_v5"
PLAN_PURPOSE = b"cascadeur-complete/owned-pair-continuation-plan/v1\0"
APPROVAL_PURPOSE = b"cascadeur-complete/owned-pair-continuation-approval/v1\0"
CLAIM_PURPOSE = b"cascadeur-complete/owned-pair-continuation-claim/v1\0"
_EFFECTS = frozenset(("activate", "position", "evaluate", "geometry", "restore"))


def _uuid(value):
    if not isinstance(value, str) or str(uuid.UUID(value)) != value:
        raise p.PolicyError("PAIR_CONTINUATION_UUID_INVALID")
    return value


def _steps(mutation):
    values = ["capture_activate", "activate"]
    if mutation is not None:
        values += ["capture_position", "position"]
    return values + ["capture_evaluate", "evaluate", "motion", "capture_geometry",
                     "geometry", "geometry_manifest", "capture_restore", "restore"]


def _request_id(plan, step):
    return str(uuid.uuid5(uuid.UUID(plan["run_id"]), "owned-pair/" + step))


def _successful(active, request_id):
    """Read the original MAC/sequence/request/result-bound terminal chain."""
    directory = active.state / "request_records" / _uuid(request_id)
    request = store.read(directory / "request.json")
    store.verify_original(request, active.secret)
    if request.get("request_id") != request_id:
        raise p.PolicyError("PAIR_ORIGINAL_REQUEST_ID_DIFFERS")
    latest = None
    raw = None
    for index, path in enumerate(sorted((directory / "runtime_events").glob("*.json")), 1):
        raw = path.read_bytes()
        value = store.decode(raw)
        store.verify_original(value, active.secret)
        context = request.get("execution_context") or {}
        if (value.get("seq") != index or value.get("request_id") != request_id
                or value.get("request_digest") != p.digest(request)
                or value.get("operation_digest") != p.digest(request["operations"])
                or value.get("session_id") != request.get("session_id")
                or value.get("host_instance_id", "") != request.get("host_instance_id", "")
                or any(value.get(key) != context.get(key) for key in ("run_id", "step_id", "attempt_id", "lease_epoch"))
                or latest is not None and latest.get("phase") == "terminal"
                or value.get("dispatched") is True and value.get("runtime_epoch") != request.get("runtime_epoch")
                or value.get("terminal_result") is not None
                and value.get("result_digest") != p.digest(value["terminal_result"])):
            raise p.PolicyError("PAIR_ORIGINAL_RECEIPT_CHAIN_DIFFERS")
        latest = value
    result = (latest or {}).get("terminal_result")
    if (latest is None or latest.get("phase") != "terminal" or latest.get("outcome") != "succeeded"
            or not isinstance(result, dict) or result.get("ok") is not True
            or result.get("outcome") != "succeeded" or latest.get("dispatched") is not True):
        raise p.EvidenceUnavailable("PAIR_PREDECESSOR_AUTHENTICATED_SUCCESS_REQUIRED: " + request_id)
    return {"request": request, "receipt": latest, "terminal_bytes_digest": hashlib.sha256(raw).hexdigest(),
            "data": result.get("result")}


def _setup_anchor_locked(active, registry, stores, setup_plan_digest):
    setup_plan = manual._stored_plan(active, setup_plan_digest)
    approval = manual._approval_locked(active, setup_plan, setup_plan_digest)
    success = _successful(active, setup_plan["request_id"])
    request, receipt, data = success["request"], success["receipt"], success["data"]
    if (request.get("feature_id") != "explicit_setup"
            or request.get("operations") != manual._operations(setup_plan, approval)
            or request.get("execution_context") != manual._execution_context(setup_plan, setup_plan_digest)
            or request.get("runtime_epoch") != setup_plan["runtime_epoch"]
            or request.get("adapter_fingerprint") != setup_plan["loaded_fingerprint"]
            or not isinstance(data, dict) or data.get("setup_invocation_ref") != request["request_id"]):
        raise p.PolicyError("PAIR_SUCCESSFUL_SETUP_ORIGIN_DIFFERS")
    outputs = [row["result"] for row in data.get("steps", [])
               if row.get("operation") == "setup.qualify_owned_pair_geometry"]
    if len(outputs) != 1:
        raise p.PolicyError("PAIR_OWNED_SETUP_RESULT_REQUIRED")
    pair = outputs[0]
    required = {"profile", "mesh_ids", "layer_ids", "frames", "fixture_scene", "original_scene",
                "fixture_tab_id", "original_tab_id", "setup_request_id", "fixture_projection_digest",
                "geometry_evidence_digest", "retention", "general_rig_supported"}
    if (not isinstance(pair, dict) or not required <= set(pair)
            or pair["profile"] != PROFILE or pair["setup_request_id"] != request["request_id"]
            or pair["general_rig_supported"] is not False or pair["frames"] != [0, 1, 2]
            or any(not isinstance(pair[key], list) or len(pair[key]) != 2 or len(set(pair[key])) != 2
                   or any(not isinstance(value, str) or not value for value in pair[key])
                   for key in ("mesh_ids", "layer_ids"))):
        raise p.PolicyError("PAIR_ACTUAL_FIXTURE_RESULT_DIFFERS")
    for key in ("fixture_scene", "original_scene"):
        store.exact(pair[key], {"scene_instance_id", "document_lineage_id"})
        if any(not isinstance(value, str) or not value for value in pair[key].values()):
            raise p.PolicyError("PAIR_SCENE_IDENTITY_UNAVAILABLE")
    if (pair["fixture_scene"]["scene_instance_id"] == pair["original_scene"]["scene_instance_id"]
            or pair["fixture_tab_id"] == pair["original_tab_id"]
            or any(not isinstance(pair[key], str) or not pair[key] for key in ("fixture_tab_id", "original_tab_id"))):
        raise p.PolicyError("PAIR_DISTINCT_LIVE_TABS_REQUIRED")
    retention = pair["retention"]
    tabs = retention.get("retained_tabs", []) if isinstance(retention, dict) else []
    if (not isinstance(retention, dict) or retention.get("retention_status") != "observed"
            or retention.get("original_inventory_preserved") is not True
            or retention.get("original_active_projection_preserved") is not True
            or not any(row.get("role") == "owned-geometry-pair" and row.get("presence") == "observed"
                       and all(row.get(key) == value for key, value in pair["fixture_scene"].items()) for row in tabs)):
        raise p.PolicyError("PAIR_RETAINED_FIXTURE_OBSERVATION_REQUIRED")
    for field in ("fixture_projection_digest", "geometry_evidence_digest"):
        p._digest_string(pair[field], field)
    originals, heads = manual._legacy_locked(registry, stores,
        reviewed_incident_ids=setup_plan.get("reviewed_incident_ids"))
    if (setup_plan["originals"] != [asdict(value) for value in originals]
            or setup_plan["heads"] != heads or setup_plan["registry_digest"] != p.digest(registry)):
        raise p.PolicyError("PAIR_LEGACY_STATE_CHANGED_SINCE_SETUP")
    anchor = {"setup_plan_digest": setup_plan_digest, "setup_request_id": request["request_id"],
        "setup_request_digest": p.digest(request), "setup_receipt_digest": p.digest(receipt),
        "setup_terminal_bytes_digest": success["terminal_bytes_digest"],
        "runtime_epoch": setup_plan["runtime_epoch"], "loaded_fingerprint": setup_plan["loaded_fingerprint"],
        "workspace_generation_id": setup_plan["workspace_generation_id"], "pair": pair}
    if setup_plan.get("schema_version") == 2:
        anchor["reviewed_incident_ids"] = setup_plan["reviewed_incident_ids"]
    return anchor, originals, heads


def _context_policy(value):
    store.exact(value, {"frames", "time_s", "time_source", "fps_num", "fps_den",
        "metres_per_scene_unit", "scene_to_solver_basis", "metadata_provenance"})
    if (not isinstance(value["frames"], list) or value["frames"] != [0, 1, 2]
            or any(type(frame) is not int for frame in value["frames"]) or value["time_source"] != "fps"
            or any(type(value[key]) is not int or value[key] <= 0 for key in ("fps_num", "fps_den"))
            or type(value["metres_per_scene_unit"]) not in (int, float)
            or not math.isfinite(value["metres_per_scene_unit"]) or value["metres_per_scene_unit"] <= 0
            or not isinstance(value["metadata_provenance"], dict) or not value["metadata_provenance"]):
        raise p.PolicyError("PAIR_EXPLICIT_THREE_FRAME_CONTEXT_REQUIRED")
    expected = [index * value["fps_den"] / value["fps_num"] for index in (0, 1, 2)]
    if (not isinstance(value["time_s"], list) or len(value["time_s"]) != 3
            or any(type(x) not in (int, float) or not math.isfinite(x) or abs(x-y) > 1e-12
                   for x, y in zip(value["time_s"], expected))):
        raise p.PolicyError("PAIR_CONTEXT_TIME_DIFFERS")
    basis = value["scene_to_solver_basis"]
    if (not isinstance(basis, list) or len(basis) != 3
            or any(not isinstance(row, list) or len(row) != 3
                   or any(type(x) not in (int, float) or not math.isfinite(x) for x in row) for row in basis)):
        raise p.PolicyError("PAIR_CONTEXT_BASIS_INVALID")
    if any(abs(sum(basis[k][i] * basis[k][j] for k in range(3)) - int(i == j)) > 1e-10
           for i in range(3) for j in range(3)):
        raise p.PolicyError("PAIR_CONTEXT_BASIS_NOT_ORTHONORMAL")
    determinant = sum(basis[0][i] * (basis[1][(i+1)%3]*basis[2][(i+2)%3]
        - basis[1][(i+2)%3]*basis[2][(i+1)%3]) for i in range(3))
    if abs(determinant - 1) > 1e-10:
        raise p.PolicyError("PAIR_CONTEXT_BASIS_NOT_PROPER")


def _mutation_policy(value, pair):
    if value is None:
        return
    store.exact(value, {"ids", "position", "frame", "space"})
    if (not isinstance(value["ids"], list) or len(value["ids"]) != 1 or value["ids"][0] not in pair["mesh_ids"]
            or type(value["frame"]) is not int or value["frame"] not in pair["frames"] or value["space"] != "local"
            or not isinstance(value["position"], list) or len(value["position"]) != 3
            or any(type(x) not in (int, float) or not math.isfinite(x) or abs(x) > 3.402823466e38 for x in value["position"])):
        raise p.PolicyError("PAIR_EXACT_EXISTING_KEY_POSITION_REQUIRED")


def prepare(root, setup_plan_digest, context, mutation=None):
    """Read an actual succeeded setup; persist an explicit, reviewable finite plan."""
    _context_policy(context)
    with store.locked_registry(root) as (registry, stores):
        active = manual._active(root, stores)
        anchor, originals, heads = _setup_anchor_locked(active, registry, stores, setup_plan_digest)
        _mutation_policy(mutation, anchor["pair"])
        now = time.time()
        body = {"schema_version": 1, "purpose": ROUTE, "domain": asdict(active.domain),
            "registry_digest": p.digest(registry), "heads": heads,
            "originals": [asdict(value) for value in originals], "setup": anchor,
            "run_id": str(uuid.uuid4()), "steps": _steps(mutation), "context": context,
            "mutation": mutation, "geometry_limits": {"max_calculations": 6,
                "max_array_bytes": 64 * 1024**2, "max_artifact_bytes": 16 * 1024**2},
            "baseline_digest": p.digest(anchor), "residuals": list(manual.RESIDUALS),
            "created_at": now, "expires_at": now + 600}
        sealed = store.seal(body, active.secret, PLAN_PURPOSE)
        plan_digest = p.digest(sealed)
        store.publish_new(active.directory / "pair-continuation-plans" / (plan_digest + ".json"), sealed)
        return {"plan_digest": plan_digest, "plan": body, "approval_required": True,
                "execution": "not_dispatched", "scope": "one_owned_pair_finite_continuation"}


def _stored_plan(active, plan_digest):
    p._digest_string(plan_digest, "pair continuation plan digest")
    plan = store.read(active.directory / "pair-continuation-plans" / (plan_digest + ".json"))
    store.verify(plan, active.secret, PLAN_PURPOSE)
    store.exact(plan, {"schema_version", "purpose", "domain", "registry_digest", "heads", "originals", "setup",
        "run_id", "steps", "context", "mutation", "geometry_limits", "baseline_digest", "residuals",
        "created_at", "expires_at", "mac"})
    if (p.digest(plan) != plan_digest or plan["schema_version"] != 1 or plan["purpose"] != ROUTE
            or plan["domain"] != asdict(active.domain) or plan["baseline_digest"] != p.digest(plan["setup"])
            or plan["residuals"] != list(manual.RESIDUALS) or plan["steps"] != _steps(plan["mutation"])
            or plan["geometry_limits"] != {"max_calculations": 6, "max_array_bytes": 64*1024**2,
                                          "max_artifact_bytes": 16*1024**2}):
        raise p.PolicyError("PAIR_CONTINUATION_STORED_PLAN_DIFFERS")
    _uuid(plan["run_id"])
    _context_policy(plan["context"])
    _mutation_policy(plan["mutation"], plan["setup"]["pair"])
    return plan


def _plan_locked(active, registry, stores, plan_digest, *, request=None, projections=None):
    plan = _stored_plan(active, plan_digest)
    originals, heads = manual._legacy_locked(registry, stores, request=request, active=active,
        projections=projections, reviewed_incident_ids=plan["setup"].get("reviewed_incident_ids"))
    if (p.digest(registry) != plan["registry_digest"] or heads != plan["heads"]
            or [asdict(value) for value in originals] != plan["originals"]
            or time.time() >= plan["expires_at"]
            or plan["run_id"] in {value.original_run_id for value in originals}):
        raise p.PolicyError("PAIR_CONTINUATION_EXPIRED_OR_LEGACY_CHANGED")
    setup_success = _successful(active, plan["setup"]["setup_request_id"])
    if (p.digest(setup_success["request"]) != plan["setup"]["setup_request_digest"]
            or p.digest(setup_success["receipt"]) != plan["setup"]["setup_receipt_digest"]
            or setup_success["terminal_bytes_digest"] != plan["setup"]["setup_terminal_bytes_digest"]):
        raise p.PolicyError("PAIR_CONTINUATION_SETUP_SUCCESS_CHANGED")
    return plan, originals


def _approval(active, plan, plan_digest):
    value = store.read(active.directory / "pair-continuation-approvals" / (plan_digest + ".json"))
    store.verify(value, active.secret, APPROVAL_PURPOSE)
    expected = {"schema_version": 1, "purpose": ROUTE, "plan_digest": plan_digest,
                "domain": asdict(active.domain), "expires_at": plan["expires_at"]}
    store.exact(value, set(expected) | {"approved_at", "mac"})
    if any(value[key] != item for key, item in expected.items()) or not plan["created_at"] <= value["approved_at"] < plan["expires_at"]:
        raise p.PolicyError("PAIR_CONTINUATION_APPROVAL_DIFFERS")
    return value


def approve_local(root, plan_digest):
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise p.PolicyError("PAIR_CONTINUATION_LOCAL_REVIEW_REQUIRED")
    with store.locked_registry(root) as (registry, stores):
        active = manual._active(root, stores)
        reviewed, _ = _plan_locked(active, registry, stores, plan_digest)
    print(json.dumps(reviewed, ensure_ascii=False, indent=2))
    print("실제 생성된 두 fixture의 표시된 유한 순서만 승인합니다. 원 legacy 결과는 미확정입니다.", file=sys.stderr)
    if input("승인할 continuation plan SHA-256 전체를 입력: ").strip() != plan_digest:
        raise p.PolicyError("PAIR_CONTINUATION_NOT_APPROVED")
    with store.locked_registry(root) as (registry, stores):
        active = manual._active(root, stores)
        plan, _ = _plan_locked(active, registry, stores, plan_digest)
        if plan != reviewed:
            raise p.PolicyError("PAIR_CONTINUATION_CHANGED_DURING_REVIEW")
        value = store.seal({"schema_version": 1, "purpose": ROUTE, "plan_digest": plan_digest,
            "domain": asdict(active.domain), "approved_at": time.time(), "expires_at": plan["expires_at"]},
            active.secret, APPROVAL_PURPOSE)
        store.publish_new(active.directory / "pair-continuation-approvals" / (plan_digest + ".json"), value)
        return {"plan_digest": plan_digest, "approval_digest": p.digest(value), "steps": plan["steps"]}


def _execution_context(plan, plan_digest, step):
    anchor, pair = plan["setup"], plan["setup"]["pair"]
    return {"run_id": plan["run_id"], "step_id": step, "request_id": _request_id(plan, step),
        "workspace_generation_id": anchor["workspace_generation_id"], "baseline_digest": plan["baseline_digest"],
        "incident_route": {"kind": ROUTE, "plan_digest": plan_digest},
        "finite_continuation": {"setup_request_id": anchor["setup_request_id"],
            "setup_receipt_digest": anchor["setup_receipt_digest"], "fixture_scene": pair["fixture_scene"],
            "original_scene": pair["original_scene"], "plan_digest": plan_digest}}


def _source(done, step, *, post=False):
    value = done[step]["data"]
    if post:
        value = value.get("post_source_binding") if isinstance(value, dict) else None
    if not isinstance(value, dict) or value.get("complete") is not True or not isinstance(value.get("binding"), dict):
        raise p.PolicyError("PAIR_RUNTIME_SOURCE_REQUIRED: " + step)
    if post and done[step]["receipt"].get("scene_after") != value["binding"]:
        raise p.PolicyError("PAIR_SUCCESSOR_RECEIPT_BINDING_DIFFERS: " + step)
    return value


def _geometry_arguments(plan, done):
    motion = done["motion"]["data"]
    if (not isinstance(motion, dict) or not isinstance(motion.get("canonical_batch"), dict)
            or motion.get("capture_digest") != p.digest(motion["canonical_batch"])):
        raise p.PolicyError("PAIR_AUTHENTICATED_MOTION_CAPTURE_REQUIRED")
    source = _source(done, "evaluate", post=True)
    if motion["canonical_batch"].get("source_binding") != source:
        raise p.PolicyError("PAIR_MOTION_EVALUATION_SOURCE_DIFFERS")
    ids = plan["setup"]["pair"]["mesh_ids"]
    return {"capture_id": str(uuid.uuid5(uuid.UUID(plan["run_id"]), "geometry")),
        "motion_source_binding": source, "motion_capture_digest": motion["capture_digest"],
        "origin_request_id": _request_id(plan, "position" if plan["mutation"] is not None else "evaluate"),
        "context": plan["context"], "mesh_ids": ids, "pairs": [ids], **plan["geometry_limits"]}


def _expected(plan, plan_digest, step, done):
    pair = plan["setup"]["pair"]
    source = None
    scene = pair["original_scene"] if step in ("capture_activate", "activate") else pair["fixture_scene"]
    if step.startswith("capture_"):
        target = step.removeprefix("capture_")
        if target in ("activate", "restore"):
            operation, args = "scene.activate", {"tab_id": pair["fixture_tab_id" if target == "activate" else "original_tab_id"]}
            source = None if target == "activate" else _source(done, "geometry", post=True)
        elif target == "position":
            operation, args, source = "animation.transform_set", plan["mutation"], _source(done, "activate", post=True)
        elif target == "evaluate":
            previous = "position" if plan["mutation"] is not None else "activate"
            operation, args, source = "animation.interpolation_refresh", {}, _source(done, previous, post=True)
        elif target == "geometry":
            operation, args, source = "system.observe_geometry_capture", _geometry_arguments(plan, done), _source(done, "evaluate", post=True)
        else:
            raise p.PolicyError("PAIR_UNKNOWN_SOURCE_STEP")
        operations = [{"name": "system.capture_source", "arguments": {
            "scope": {"operation_name": operation, "operation_arguments": args},
            "inputs_digest": plan["baseline_digest"]}}]
    elif step in ("activate", "restore", "position", "evaluate", "geometry"):
        source = _source(done, "capture_" + step)
        operation = {"activate": "scene.activate", "restore": "scene.activate", "position": "animation.transform_set",
                     "evaluate": "animation.interpolation_refresh", "geometry": "system.observe_geometry_capture"}[step]
        args = ({"tab_id": pair["fixture_tab_id" if step == "activate" else "original_tab_id"]}
                if step in ("activate", "restore") else plan["mutation"] if step == "position"
                else {} if step == "evaluate" else _geometry_arguments(plan, done))
        operations = [{"name": operation, "arguments": args}]
    elif step == "motion":
        source = _source(done, "evaluate", post=True)
        operations = [{"name": "system.observe_motion_capture", "arguments": {
            "ids": pair["mesh_ids"], "space": "global", "context": plan["context"],
            "source_binding": source, "required_rotation_ids": []}}]
    elif step == "geometry_manifest":
        source = _source(done, "geometry", post=True)
        operations = [{"name": "system.get_geometry_capture", "arguments": {
            "capture_id": str(uuid.uuid5(uuid.UUID(plan["run_id"]), "geometry"))}}]
    else:
        raise p.PolicyError("PAIR_UNKNOWN_FINITE_STEP")
    if source is not None and (any(source["binding"].get(key) != value for key, value in scene.items())
                               or source.get("inputs_digest") != plan["baseline_digest"]):
        raise p.PolicyError("PAIR_ACTUAL_SOURCE_ANCESTRY_DIFFERS")
    return {"request_id": _request_id(plan, step), "feature_id": "owned_pair_continuation",
        "scene_id": scene["scene_instance_id"], "expected_revision": None,
        "operations": operations, "source_binding": source,
        "execution_context": _execution_context(plan, plan_digest, step)}


def _match_request(plan, expected, request):
    if (any(request.get(key) != value for key, value in expected.items())
            or request.get("runtime_epoch") != plan["setup"]["runtime_epoch"]
            or request.get("adapter_fingerprint") != plan["setup"]["loaded_fingerprint"]
            or not plan["created_at"] <= request["created_at"] < request["expires_at"] <= plan["expires_at"]):
        raise p.PolicyError("PAIR_EXACT_APPROVED_REQUEST_DIFFERS")


def _predecessors(active, plan, plan_digest, before_step):
    done = {}
    for step in plan["steps"]:
        if step == before_step:
            return done
        success = _successful(active, _request_id(plan, step))
        _match_request(plan, _expected(plan, plan_digest, step, done), success["request"])
        done[step] = success
    raise p.PolicyError("PAIR_STEP_OUTSIDE_PLAN")


def disposition_locked(registry, stores, request, active, *, native=False,
                       bind_claim=False, require_claim=False, projections=None):
    reference = (request.get("execution_context") or {}).get("incident_route")
    store.exact(reference, {"kind", "plan_digest"})
    if reference["kind"] != ROUTE:
        raise p.PolicyError("PAIR_CONTINUATION_ROUTE_DIFFERS")
    store.verify_original(request, active.secret)
    plan_digest = reference["plan_digest"]
    plan, originals = _plan_locked(active, registry, stores, plan_digest, request=request, projections=projections)
    approval = _approval(active, plan, plan_digest)
    step = (request.get("execution_context") or {}).get("step_id")
    done = _predecessors(active, plan, plan_digest, step)
    expected = _expected(plan, plan_digest, step, done)
    _match_request(plan, expected, request)
    if native:
        from . import guarded_runtime as guards
        if (guards.RUNTIME_EPOCH != plan["setup"]["runtime_epoch"]
                or guards.LOADED_FINGERPRINT != plan["setup"]["loaded_fingerprint"]):
            raise p.PolicyError("PAIR_CURRENT_NATIVE_RUNTIME_DIFFERS")
    claim = {"schema_version": 1, "purpose": ROUTE, "plan_digest": plan_digest, "step_id": step,
        "request_digest": p.digest(request), "approval_digest": p.digest(approval)}
    path = active.directory / "pair-continuation-claims" / plan_digest / (step + ".json")
    if path.exists():
        value = store.read(path)
        store.verify(value, active.secret, CLAIM_PURPOSE)
        if {key: item for key, item in value.items() if key != "mac"} != claim:
            raise p.PolicyError("PAIR_STEP_ALREADY_BOUND_TO_DIFFERENT_REQUEST")
    elif bind_claim:
        store.publish_new(path, store.seal(claim, active.secret, CLAIM_PURPOSE))
    elif require_claim:
        raise p.PolicyError("PAIR_STEP_DURABLE_CLAIM_REQUIRED")
    from .incident_admission import intent_for
    intent = intent_for(request, active.domain)
    return p.ManualLegacyDisposition(plan_digest, p.digest(request), p.digest(request["operations"]),
        active.domain, plan["setup"]["runtime_epoch"], plan["setup"]["loaded_fingerprint"],
        plan["setup"]["workspace_generation_id"], plan["baseline_digest"], plan["run_id"], originals,
        work_kind=intent.kind)


def run(root, plan_digest):
    """Execute each authorized step once; observe existing requests without retry."""
    from .bridge_client import BridgeClient
    from .models import Operation, SafetyContext, SourceBinding
    from .paths import RuntimePaths
    from .safety import ChangeManager
    from .state_lock import file_lock
    paths = RuntimePaths.discover(Path(root))
    # Serializes only this finite controller. Native admission still checks all
    # existing registry locks and claims before every operation/effect.
    p._digest_string(plan_digest, "pair continuation plan digest")
    with file_lock(paths.state / ("pair-continuation-" + plan_digest + ".lock"), timeout=1.0):
        client = None
        with store.locked_registry(root) as (registry, stores):
            active = manual._active(root, stores)
            plan = _stored_plan(active, plan_digest)
            _approval(active, plan, plan_digest)
        done = {}
        for step in plan["steps"]:
            observe_request = None
            with store.locked_registry(root) as (registry, stores):
                active = manual._active(root, stores)
                existing = active.state / "request_records" / _request_id(plan, step) / "request.json"
                if existing.is_file():
                    request = store.read(existing)
                    store.verify_original(request, active.secret)
                    _match_request(plan, _expected(plan, plan_digest, step, done), request)
                    try:
                        done[step] = _successful(active, request["request_id"])
                    except p.EvidenceUnavailable:
                        observe_request = request["request_id"]
                    if observe_request is None:
                        continue
                else:
                    current, _ = _plan_locked(active, registry, stores, plan_digest)
                    if current != plan:
                        raise p.PolicyError("PAIR_PLAN_CHANGED_DURING_RUN")
                    _approval(active, plan, plan_digest)
                    expected = _expected(plan, plan_digest, step, done)
            if observe_request is not None:
                observed = BridgeClient(paths=paths).reconcile_request(observe_request)
                return {"complete": False, "stopped_step": step, "request": observed.model_dump(mode="json"),
                        "redispatched": False, "original_scene_restored": None}
            if client is None:
                client = manual._runtime_client(root)
            if (client.runtime_status["runtime_epoch"] != plan["setup"]["runtime_epoch"]
                    or client.runtime_status["adapter_fingerprint"] != plan["setup"]["loaded_fingerprint"]):
                raise p.PolicyError("PAIR_NATIVE_RUNTIME_CHANGED")
            remaining = plan["expires_at"] - time.time() - 1.0
            if remaining <= 0:
                raise p.PolicyError("PAIR_PLAN_EXPIRED_BEFORE_NEXT_STEP")
            source = None if expected["source_binding"] is None else SourceBinding.model_validate(expected["source_binding"])
            operation = Operation(**expected["operations"][0])
            safety = SafetyContext()
            if step in _EFFECTS:
                # The local operator already approved this complete finite plan.
                # Existing native confirmation still binds the exact source,
                # operation, request ID and context and is consumed only once.
                changes = ChangeManager(paths)
                token = changes.prepare(feature_id=expected["feature_id"], scene_id=expected["scene_id"],
                    scene_revision=None, selection_fingerprint=source.binding.selection_digest,
                    operation=operation, impact={"pair_plan_digest": plan_digest, "step_id": step,
                        "setup_receipt_digest": plan["setup"]["setup_receipt_digest"]},
                    backup_path=None, ttl=min(120.0, remaining), source_binding=source,
                    execution_context=expected["execution_context"], mutation_request_id=expected["request_id"])
                changes.consume(token.token, scene_id=expected["scene_id"], scene_revision=None,
                    selection_fingerprint=source.binding.selection_digest)
                safety = SafetyContext(destructive=True, confirmation_token=token.token,
                    snapshot_required=False, selection_fingerprint=source.binding.selection_digest)
            result = client.execute(expected["feature_id"], [operation], scene_id=expected["scene_id"],
                expected_revision=None, request_id=expected["request_id"], timeout=min(120.0, remaining),
                source_binding=source, execution_context=expected["execution_context"], safety_context=safety)
            if not result.ok or result.outcome != "succeeded":
                return {"complete": False, "stopped_step": step, "request": result.model_dump(mode="json"),
                        "redispatched": False, "original_scene_restored": None}
            with store.locked_registry(root) as (registry, stores):
                active = manual._active(root, stores)
                done[step] = _successful(active, expected["request_id"])
                _match_request(plan, expected, done[step]["request"])
        restored = _source(done, "restore", post=True)["binding"]
        original = plan["setup"]["pair"]["original_scene"]
        if any(restored.get(key) != value for key, value in original.items()):
            raise p.PolicyError("PAIR_ORIGINAL_SCENE_RESTORE_UNVERIFIED")
        return {"complete": True, "scope": PROFILE, "run_id": plan["run_id"],
            "motion_capture": done["motion"]["data"], "geometry_capture": done["geometry_manifest"]["data"],
            "original_scene_restored": True, "general_rig_supported": False,
            "step_receipt_digests": {step: p.digest(value["receipt"]) for step, value in done.items()}}
