"""Private prediction and durable completion evidence for explicit insertions.

These read-only observations grant no mutation or recipe authority. A planner
must start with this epoch's evaluated capture/layout; completion can only be
sealed by the runtime after the original authenticated terminal event exists.
"""
from __future__ import annotations

import copy
import json

from . import guarded_runtime as guards
from . import native_key_insertion as core

_PLANS = {}
_ATTEMPTS = {}
_LIMIT = 16


def _hash(value):
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def _adapter(scene):
    from .native_key_insertion_adapter import NativeKeyInsertionAdapter, OPERATION
    adapter = guards._ADAPTERS.get(OPERATION)
    if not isinstance(adapter, NativeKeyInsertionAdapter):
        raise ValueError("KEY_INSERTION_UNQUALIFIED: current private adapter registration required")
    proof = adapter._qualified()
    adapter._workspace(scene)
    return adapter, proof


def _layout(scene, observation, capture):
    from .native_key_layout import read_key_layout
    from .native_motion_capture import lookup_capture
    context = capture["canonical_batch"]["context"]
    native = observation["native_source_scope"]
    arguments = {key: copy.deepcopy(native[key]) for key in ("ids", "capture_object_ids", "space", "channel", "frames")}
    arguments.update(capture_digest=observation["capture_digest"], context=context)
    fresh = read_key_layout(scene, arguments, capture_lookup=lambda key: lookup_capture(key, arguments))
    fresh["evidence_ref"] = "native-key-layout:" + guards.RUNTIME_EPOCH + ":" + fresh["source_fingerprint"]
    if fresh != observation or fresh["support_status"] != "supported" or fresh["reason_codes"]:
        raise ValueError("KEY_INSERTION_ADAPTER_UNVERIFIED: exact current privately evaluated layout required")


def _prediction(driver, expected, additions):
    """Project the executor's full expected state into public driver fields."""
    import numpy as np
    after = copy.deepcopy(driver)
    layer = next(row for row in expected["layers"] if row["id"] == driver["layer_id"])
    data = next(row for row in expected["data"] if row["id"] == driver["data_id"])
    frames = layer["keys"]
    sections = {row["frame"]: row for row in layer["sections"]}
    old_sections = {row["frame"]: row for row in driver["sections"]}
    public_sections = []
    tangents, boundaries = [], []
    for frame, section in sorted(sections.items()):
        if frame in old_sections:
            public = copy.deepcopy(old_sections[frame])
        else:
            # All fields below are the explicit values created by _section;
            # no caller-provided event, tangent or native ID is accepted.
            public = {"frame": frame, "is_key": True, "interval_mode": section["interpolation"],
                "interval_common": copy.deepcopy(section["interval_common"]),
                "tangent": {"mode": section["tangents"],
                    "left_weight_velocity": section["left_weight_velocity"],
                    "right_weight_velocity": section["right_weight_velocity"]},
                "key_common": copy.deepcopy(section["key_common"]), "label": None}
        public_sections.append(public)
    by_frame = {row["frame"]: row for row in public_sections}
    for frame in frames:
        row = by_frame[frame]
        tangents.append({**row["tangent"], "key_common": row["key_common"], "label": row["label"]})
        boundaries.append({"frame": frame, "key_id": driver["layer_id"] + ":" + str(frame),
            "key_id_kind": "layer_frame_locator", "locked": layer["locked"],
            "event": row["label"] is not None, "label": row["label"]})
    after.update(frames=frames, key_ids=[driver["layer_id"] + ":" + str(frame) for frame in frames],
        values=[np.asarray(data["values"][frame], dtype=float).reshape(3).tolist() for frame in frames],
        segment_modes=[by_frame[frame]["interval_mode"] for frame in frames[:-1]],
        tangents=tangents, boundary_keys=boundaries, sections=public_sections)
    for addition in additions:
        index = frames.index(addition["frame"])
        if (addition["value"] != after["values"][index]
                or addition["tangent"] != after["tangents"][index]):
            raise ValueError("KEY_INSERTION_ADAPTER_UNVERIFIED: exact native float32 values and section tangents required")
    return after


def verify_key_insertion(scene, arguments):
    from .native_adapters import _OBSERVATIONS
    from .native_motion_capture import lookup_capture
    if (not isinstance(arguments, dict) or set(arguments) != {"request", "digest"}
            or not isinstance(arguments["request"], dict)
            or set(arguments["request"]) != {"key_layout_digest", "additions"}
            or arguments["digest"] != guards.digest(arguments["request"])):
        raise ValueError("KEY_INSERTION_ADAPTER_UNVERIFIED: exact insertion request digest required")
    request = arguments["request"]
    if not _hash(request["key_layout_digest"]):
        raise ValueError("KEY_INSERTION_ADAPTER_UNVERIFIED: native layout digest required")
    observation = _OBSERVATIONS.get(("key_layout", request["key_layout_digest"]))
    if observation is None or guards.digest(observation) != request["key_layout_digest"]:
        raise ValueError("KEY_INSERTION_ADAPTER_UNVERIFIED: layout was not issued by this runtime")
    capture = lookup_capture(observation["capture_digest"])
    if capture is None:
        raise ValueError("KEY_INSERTION_ADAPTER_UNVERIFIED: original private evaluated capture unavailable")
    _layout(scene, observation, capture)
    adapter, qualification = _adapter(scene)
    if len(observation["drivers"]) != 1 or capture["canonical_batch"]["space"] != "local":
        raise ValueError("KEY_INSERTION_SCOPE_UNQUALIFIED: one local position driver required")
    driver = observation["drivers"][0]
    additions = request["additions"]
    if not isinstance(additions, list) or not 1 <= len(additions) <= 8:
        raise ValueError("KEY_INSERTION_BUDGET_EXCEEDED: one to eight explicit additions required")
    rows = []
    for row in additions:
        if (not isinstance(row, dict) or set(row) != {"object_id", "channel", "layer_id", "frame", "value", "mode", "tangent"}
                or (row["object_id"], row["channel"], row["layer_id"]) != (driver["object_id"], "position", driver["layer_id"])):
            raise ValueError("KEY_INSERTION_SCOPE_UNQUALIFIED: additions must match the privately observed driver")
        rows.append({"frame": row["frame"], "position": row["value"], "mode": row["mode"]})
    before, inspected, values = core._inspect(scene, driver["object_id"], driver["layer_id"], rows)
    if (capture["full_projection_digest"] != guards.digest(before)
            or capture["canonical_batch"]["context"]["frames"] != list(range(before["frames"]))):
        raise ValueError("KEY_INSERTION_SCOPE_UNQUALIFIED: complete original evaluation grid required")
    _, expected = core.predict_insertion(before, inspected, values)
    predicted = _prediction(driver, expected, additions)
    source = capture["canonical_batch"]["source_binding"]
    identity = guards.scene_instance(scene)
    proof = {"contract": core.CONTRACT, "key_id_kind": "layer_frame_locator", "value_space": "native_scene_units",
        "request_digest": arguments["digest"], "key_layout_digest": request["key_layout_digest"],
        "original_topology_digest": guards.digest(observation["drivers"]), "capture_digest": observation["capture_digest"],
        "context_digest": guards.digest(capture["canonical_batch"]["context"]), "source_binding_digest": guards.digest(source),
        "runtime_epoch": guards.RUNTIME_EPOCH, "runtime_fingerprint": guards.LOADED_FINGERPRINT,
        **identity, "before_projection_digest": guards.digest(before),
        "model_qualification_digest": qualification["model_qualification_digest"],
        "insertion_qualification_digest": guards.digest(qualification), "expected_driver": predicted}
    ref = "native-key-insertion:" + guards.RUNTIME_EPOCH + ":" + guards.digest(proof)
    result = {"request_digest": arguments["digest"], "shared_layer_effects_observed": True,
        "non_target_effects": [], "adapter_evidence_ref": ref, "locator_insertion": proof}
    existing = _PLANS.get(ref)
    if existing is not None:
        if existing["state"] != "planned" or existing["result"] != result:
            raise ValueError("KEY_INSERTION_SOURCE_CONSUMED: plan already bound to an insertion attempt")
        return copy.deepcopy(result)
    if len(_PLANS) >= _LIMIT:
        raise ValueError("KEY_INSERTION_BUDGET_EXCEEDED: private prediction capacity reached")
    _PLANS[ref] = {"scene": scene, "state": "planned", "result": copy.deepcopy(result),
        "source": copy.deepcopy(source), "expected": expected, "rows": values,
        "workspace": adapter._workspace(scene)}
    return copy.deepcopy(result)


def bind_execution(scene, arguments, request, private_source):
    """Associate existing predictions before the first setter; never issue one."""
    request_id = request.get("request_id")
    if not request_id:
        return
    refs = []
    for ref, record in _PLANS.items():
        proof = record["result"]["locator_insertion"]
        if (record["scene"] is scene and record["state"] == "planned"
                and record["rows"] == private_source["additions"]
                and proof["before_projection_digest"] == private_source["before_projection_digest"]
                and proof["expected_driver"]["object_id"] == arguments["object_id"]
                and proof["expected_driver"]["layer_id"] == arguments["layer_id"]):
            guards.assert_source(scene, record["source"])
            refs.append(ref)
    if not refs:
        return
    if request_id in _ATTEMPTS or len(_ATTEMPTS) >= _LIMIT:
        raise ValueError("KEY_INSERTION_SOURCE_CONSUMED: bounded private attempt identity required")
    _ATTEMPTS[request_id] = {"request": copy.deepcopy(request), "source_id": private_source["source_id"], "refs": refs}
    for ref in refs:
        _PLANS[ref]["state"] = "bound"


def finalize_insertion(scene, request, result, receipt):
    """Called only after receipt_event durably writes the original terminal."""
    attempt = _ATTEMPTS.get(request.get("request_id"))
    if attempt is None or attempt["request"] != request:
        return
    private = core._SOURCES.get(attempt["source_id"])
    source = (result.get("result") or {}).get("post_source_binding")
    if (private is None or private["state"] != "completed" or private["scene"] is not scene
            or result.get("ok") is not True or result.get("outcome") != "succeeded"
            or receipt.get("phase") != "terminal" or receipt.get("outcome") != "succeeded"
            or receipt.get("request_digest") != guards.digest(request)
            or receipt.get("result_digest") != guards.digest(result)
            or receipt.get("terminal_result") != result
            or not isinstance(source, dict) or source.get("sample_digest") != guards.digest(private["after"])):
        return
    for ref in attempt["refs"]:
        record = _PLANS[ref]
        if record["expected"] == private["after"]:
            record.update(state="completed", request=copy.deepcopy(request), terminal=copy.deepcopy(result),
                receipt=copy.deepcopy(receipt), source_id=attempt["source_id"], post_source=copy.deepcopy(source),
                receipt_bytes=json.dumps(receipt, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode())


def _terminal_current(record):
    from . import runtime as rt
    root = rt.runtime_root()
    if guards.previous_terminal(root, record["request"]) != record["terminal"]:
        return False
    path = (root / "state" / "request_records" / record["request"]["request_id"] / "runtime_events"
        / (f"{record['receipt']['seq']:04d}-terminal.json"))
    with path.open("rb") as stream:
        return stream.read(len(record["receipt_bytes"]) + 1) == record["receipt_bytes"]


def verify_key_topology(scene, arguments):
    from .native_adapters import _OBSERVATIONS
    from .native_motion_capture import lookup_capture
    if (not isinstance(arguments, dict) or set(arguments) != {"observation", "digest", "adapter_evidence_ref"}
            or not isinstance(arguments["observation"], dict)
            or not isinstance(arguments["adapter_evidence_ref"], str)
            or arguments["digest"] != guards.digest(arguments["observation"])):
        raise ValueError("KEY_TOPOLOGY_READBACK_UNVERIFIED: exact observation and private evidence reference required")
    record = _PLANS.get(arguments["adapter_evidence_ref"])
    if record is None or record["state"] != "completed" or record["scene"] is not scene:
        raise ValueError("KEY_TOPOLOGY_READBACK_UNVERIFIED: original successful native attempt unavailable")
    adapter, qualification = _adapter(scene)
    proof = record["result"]["locator_insertion"]
    private = core._SOURCES.get(record["source_id"])
    if (private is None or private["state"] != "completed" or private["scene"] is not scene
            or proof["runtime_epoch"] != guards.RUNTIME_EPOCH
            or proof["runtime_fingerprint"] != guards.LOADED_FINGERPRINT
            or proof["insertion_qualification_digest"] != guards.digest(qualification)
            or adapter._workspace(scene) != record["workspace"]
            or adapter.read_scene(scene) != record["expected"] or private["after"] != record["expected"]
            or not _terminal_current(record)):
        raise ValueError("KEY_TOPOLOGY_READBACK_UNVERIFIED: exact private completion, scene and durable terminal required")
    guards.assert_source(scene, record["post_source"])
    observation = arguments["observation"]
    if _OBSERVATIONS.get(("key_layout", arguments["digest"])) != observation:
        raise ValueError("KEY_TOPOLOGY_READBACK_UNVERIFIED: readback was not issued by this runtime")
    capture = lookup_capture(observation["capture_digest"])
    if capture is None or capture["full_projection_digest"] != guards.digest(record["expected"]):
        raise ValueError("KEY_TOPOLOGY_READBACK_UNVERIFIED: fresh explicit evaluated capture required")
    _layout(scene, observation, capture)
    if observation["drivers"] != [proof["expected_driver"]]:
        raise ValueError("KEY_TOPOLOGY_MISMATCH: actual driver differs from the entire private prediction")
    completion = {key: proof[key] for key in ("contract", "request_digest", "source_binding_digest",
        "runtime_epoch", "runtime_fingerprint", "scene_instance_id", "document_lineage_id", "before_projection_digest")}
    completion.update(key_layout_digest=arguments["digest"], adapter_evidence_ref=arguments["adapter_evidence_ref"],
        after_projection_digest=guards.digest(record["expected"]), completion_receipt_digest=guards.digest(record["receipt"]))
    return {"key_layout_digest": arguments["digest"], "completion_receipt_digest": completion["completion_receipt_digest"],
        "locator_insertion_completion": completion}
