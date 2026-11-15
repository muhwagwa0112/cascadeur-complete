"""Explicit independent-position insertion experiment; no production registration.

Keys are identified honestly by (layer GUID, frame). The source and completion
records below are process-local, single-use observations, not wire authority.
No function runs on import. A terminal runtime evaluation/quality receipt is a
separate requirement before any future recipe can use this primitive.
"""
from __future__ import annotations

import copy
import json
import threading
import uuid

from . import guarded_runtime as guards

SUPPORTED_BUILD = "2026.2.3.0.16863"
CONTRACT = "independent_absent_layer_frame_position_v1"
_QUALIFICATION_BYTES = None
_CALLBACK_GENERATION = 0
_SOURCES = {}
_RUNS = {}
_PROBE_SCENE = None


def _freeze(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _model():
    from .native_adapters import installed_build
    from .native_interpolation_qualification import qualification as model_qualification
    guards.assert_loaded_package()
    model = model_qualification()
    if installed_build() != SUPPORTED_BUILD or model is None:
        raise ValueError("KEY_INSERTION_MODEL_UNQUALIFIED: explicit current-build finite-model proof required")
    return model


def qualification():
    """Read private proof; do not run a model or insertion experiment."""
    if _QUALIFICATION_BYTES is None:
        return None
    model = _model()
    proof = json.loads(_QUALIFICATION_BYTES)
    if (proof["runtime_epoch"] != guards.RUNTIME_EPOCH
            or proof["runtime_fingerprint"] != guards.LOADED_FINGERPRINT
            or proof["model_qualification_digest"] != guards.digest(model)
            or proof["callback_generation"] != _CALLBACK_GENERATION):
        raise ValueError("KEY_INSERTION_QUALIFICATION_STALE")
    return proof


def qualification_status(run_id=None):
    """Inspect retained experiment records without accessing or changing scenes."""
    if run_id is None:
        run_id = next(reversed(_RUNS), None)
    if run_id not in _RUNS:
        return {"status": "not_qualified", "run_id": run_id, "production_registered": False}
    return copy.deepcopy(_RUNS[run_id])


def _inspect(scene, object_id, layer_id, additions):
    from bisect import bisect_right
    from . import runtime as rt
    from .native_scene_reader import read_scene
    from .native_key_layout import read_key_layout
    from .native_interpolation_qualification import independent_projection_identity
    from .native_independent_position import _position, _position_closure, _ALLOWED_DIAGNOSTICS
    _model()
    if rt._scene_view() is not scene:
        raise ValueError("SCENE_CHANGED: insertion requires the exact active scene")
    before = read_scene(scene)
    if (not independent_projection_identity(before, object_id) or not 1 <= len(before["layers"]) <= 8
            or not 3 <= before["frames"] <= 33 or len(_freeze(before)) > 1024 * 1024):
        raise ValueError("KEY_INSERTION_SCOPE_UNQUALIFIED: one independent Transform and bounded layer inventory required")
    owning = [layer for layer in before["layers"] if layer["id"] == layer_id]
    if len(owning) != 1:
        raise ValueError("KEY_INSERTION_SCOPE_UNQUALIFIED: unique exact owning layer ID required")
    layer = owning[0]
    if (layer["object_ids"] != [object_id] or layer["locked"] or not layer["visible"]
            or any(other["object_ids"] for other in before["layers"] if other["id"] != layer_id)):
        raise ValueError("KEY_INSERTION_SCOPE_UNQUALIFIED: exact editable unshared owning layer required")
    layout = read_key_layout(scene, {"ids": [object_id], "capture_object_ids": [object_id],
        "channel": "position", "space": "local", "frames": list(range(before["frames"])),
        "capture_digest": "0" * 64, "context": None})
    blockers = set(layout["reason_codes"]) - _ALLOWED_DIAGNOSTICS
    if blockers or len(layout["drivers"]) != 1:
        raise ValueError("KEY_INSERTION_SCOPE_UNQUALIFIED: " + ", ".join(sorted(blockers)))
    driver = layout["drivers"][0]
    if driver["layer_id"] != layer_id or driver["frames"] != layer["keys"] or driver["key_id_kind"] != "layer_frame_locator":
        raise ValueError("KEY_INSERTION_SCOPE_UNQUALIFIED: exact complete layer-frame topology required")
    if driver["native_model"] not in _model()["qualified_models"]:
        raise ValueError("KEY_INSERTION_MODEL_UNQUALIFIED: actual finite model was not privately qualified")
    driver["position_closure"] = _position_closure(before, driver)
    if (not isinstance(additions, list) or not 1 <= len(additions) <= 8
            or len(driver["frames"]) + len(additions) > 16):
        raise ValueError("KEY_INSERTION_BUDGET_EXCEEDED: one to eight new keys within sixteen total keys required")
    seen, values = set(), []
    for row in additions:
        if (not isinstance(row, dict) or set(row) != {"frame", "position", "mode"}
                or type(row["frame"]) is not int or row["frame"] in seen
                or row["frame"] in driver["frames"]
                or row["frame"] in {section["frame"] for section in layer["sections"]}
                or not driver["frames"][0] < row["frame"] < driver["frames"][-1]):
            raise ValueError("KEY_INSERTION_SCOPE_UNQUALIFIED: unique absent interior key AND section frames required")
        index = bisect_right(driver["frames"], row["frame"]) - 1
        if row["mode"] not in ("LINEAR", "STEP") or row["mode"] != driver["segment_modes"][index]:
            raise ValueError("KEY_INSERTION_MODE_UNQUALIFIED: preserve the original segment mode")
        _position(row["position"])
        seen.add(row["frame"])
        values.append(copy.deepcopy(row))
    return before, driver, sorted(values, key=lambda row: row["frame"])


def prepare_insertion(scene, object_id, layer_id, additions):
    """Issue a single-use exact source in local scene units; caller owns permits.

    This is not a SourceBinding and cannot replace runtime authorization. A
    future registered adapter must bind this private source to that operation's
    actual SourceBinding, intent, key-count budget and durable working scene.
    """
    if _PROBE_SCENE is not scene and qualification() is None:
        raise ValueError("KEY_INSERTION_UNQUALIFIED: explicit disposable insertion observation required")
    if len(_SOURCES) >= 32:
        raise ValueError("KEY_INSERTION_BUDGET_EXCEEDED: private insertion source capacity reached")
    if any(record["scene"] is scene and record["state"] in ("dispatching", "unknown") for record in _SOURCES.values()):
        raise ValueError("KEY_INSERTION_RECONCILIATION_REQUIRED: unresolved insertion forbids a new source or replay")
    before, driver, values = _inspect(scene, object_id, layer_id, additions)
    source = {"contract": CONTRACT, "source_id": str(uuid.uuid4()), "key_id_kind": "layer_frame_locator",
        "runtime_epoch": guards.RUNTIME_EPOCH, "runtime_fingerprint": guards.LOADED_FINGERPRINT,
        "callback_generation": _CALLBACK_GENERATION,
        "scene_identity": dict(guards.scene_instance(scene)), "object_id": object_id, "layer_id": layer_id,
        "preserved_empty_layer_ids": [layer["id"] for layer in before["layers"] if layer["id"] != layer_id],
        "additions": values, "space": "local", "units": "scene_units",
        "before_projection_digest": guards.digest(before), "model_qualification_digest": guards.digest(_model())}
    _SOURCES[source["source_id"]] = {"scene": scene, "source_bytes": _freeze(source),
        "before": before, "driver": driver, "state": "prepared"}
    return source


def _section(row, original):
    """Set every observable new-section field explicitly; never edit an old one."""
    import csc
    from .native_scene_reader import member, native_value
    section = csc.layers.layer.Section()
    section.interval.interpolation = getattr(csc.layers.layer.Interpolation, row["mode"])
    section.interval.description_for_ai_interpolation = original["description_for_ai_interpolation"]
    section.interval.common.fixation = csc.layers.layer.Fixation.Free
    section.interval.common.ik_fk = csc.layers.layer.IkFk.FK
    section.key.common.fixation = csc.layers.layer.Fixation.Free
    section.key.common.ik_fk = csc.layers.layer.IkFk.FK
    section.key.label = csc.layers.layer.Key.no_label_id()
    section.key.tangents = csc.layers.layer.Tangents.Continuous
    section.key.left_weight_velocity = original["left_weight_velocity"]
    section.key.right_weight_velocity = original["right_weight_velocity"]
    encoded = {"frame": row["frame"], "interpolation": member(section.interval.interpolation, "name"),
        "description_for_ai_interpolation": str(section.interval.description_for_ai_interpolation),
        "tangents": member(section.key.tangents, "name"), "label": native_value(section.key.label),
        "left_weight_velocity": float(section.key.left_weight_velocity),
        "right_weight_velocity": float(section.key.right_weight_velocity),
        "key_common": {"ik_fk": "FK", "fixation": "Free"},
        "interval_common": {"ik_fk": "FK", "fixation": "Free"}}
    return section, encoded


def insert_positions(scene, source, *, before_write=None):
    """Insert only absent keys using the same primitive exercised by the probe.

    Unknown completion consumes the source. Reconciliation reads status and the
    retained scene; it never replays this call with the consumed source.
    """
    import csc
    from bisect import bisect_right
    from . import runtime as rt
    from .native_scene_reader import read_scene
    from .native_independent_position import _position, _expected_projection, _scope_failure
    record = _SOURCES.get(source.get("source_id")) if isinstance(source, dict) else None
    if (record is None or record["scene"] is not scene or record["source_bytes"] != _freeze(source)
            or record["state"] != "prepared"):
        raise ValueError("KEY_INSERTION_SOURCE_UNAVAILABLE: exact unconsumed private source required")
    before, driver, additions = _inspect(scene, source["object_id"], source["layer_id"], source["additions"])
    if (source["scene_identity"] != guards.scene_instance(scene)
            or source["runtime_epoch"] != guards.RUNTIME_EPOCH
            or source["runtime_fingerprint"] != guards.LOADED_FINGERPRINT
            or source["model_qualification_digest"] != guards.digest(_model())
            or before != record["before"] or guards.digest(before) != source["before_projection_digest"]):
        raise ValueError("SCENE_CHANGED: insertion source differs")
    if _PROBE_SCENE is not scene and qualification() is None:
        raise ValueError("KEY_INSERTION_UNQUALIFIED")
    layer_index = next(index for index, layer in enumerate(before["layers"]) if layer["id"] == source["layer_id"])
    owning_layer = before["layers"][layer_index]
    old_sections = {row["frame"]: row for row in owning_layer["sections"]}
    authored, new_sections = [], []
    for row in additions:
        left = driver["frames"][bisect_right(driver["frames"], row["frame"]) - 1]
        section, encoded = _section(row, old_sections[left])
        authored.append((row, section, _position(row["position"])))
        new_sections.append(encoded)
    modes = dict(zip(driver["frames"][:-1], driver["segment_modes"], strict=True))
    modes.update({row["frame"]: row["mode"] for row in additions})
    target_driver = copy.deepcopy(driver)
    target_driver["frames"] = sorted(driver["frames"] + [row["frame"] for row in additions])
    target_driver["segment_modes"] = [modes[frame] for frame in target_driver["frames"][:-1]]
    expected = _expected_projection(before, target_driver, additions)
    expected["layers"][layer_index]["keys"] = target_driver["frames"]
    expected["layers"][layer_index]["sections"] = sorted(owning_layer["sections"] + new_sections, key=lambda row: row["frame"])
    domain = rt._domain_scene(scene)
    data_id = csc.model.DataId(driver["position_closure"]["data_ids"]["local_position"])
    layer_id = rt._guid(source["layer_id"])
    identity = dict(guards.scene_instance(scene))
    thread = threading.get_ident()
    trace = {"active": False, "attempts": 0, "callback_completed": False,
        "native_returned": False, "native_true": False, "unbounded": False,
        "sections_started": [], "sections_returned": [], "values_started": [], "values_returned": []}
    errors, observed_effect = [], [None]
    def guard():
        guards.assert_loaded_package()
        current_guard = getattr(guards._LOCAL, "guard", None)
        if current_guard is not None: current_guard()
        if callable(before_write): before_write()
        if (rt._scene_view() is not scene or guards.scene_instance(scene) != identity
                or guards.RUNTIME_EPOCH != source["runtime_epoch"]
                or _CALLBACK_GENERATION != source["callback_generation"] or read_scene(scene) != before):
            raise ValueError("SCENE_CHANGED: exact full insertion source changed before first setter")
    def author(model, _update, _callback_scene):
        global _CALLBACK_GENERATION, _QUALIFICATION_BYTES
        trace["attempts"] += 1
        if not trace["active"] or trace["attempts"] != 1 or threading.get_ident() != thread:
            trace["unbounded"] = True
            _CALLBACK_GENERATION += 1
            _QUALIFICATION_BYTES = None
            record["state"] = "unknown"
            if record.get("run_id") in _RUNS:
                _RUNS[record["run_id"]].update(status="unknown", phase="late_callback_rejected")
            if observed_effect[0] is not None: observed_effect[0]["completion"] = "unknown"
            raise RuntimeError("NATIVE_COMPLETION_UNKNOWN: late, replayed or cross-thread insertion callback")
        try:
            guards.before_write(guard)
            for row, section, position in authored:
                frame = row["frame"]
                trace["sections_started"].append(frame)
                model.layers_editor().set_section(section, frame, layer_id)
                trace["sections_returned"].append(frame)
                trace["values_started"].append(frame)
                model.data_editor().set_data_value(data_id, frame, position)
                trace["values_returned"].append(frame)
            guards.finish_write()
            trace["callback_completed"] = True
        except Exception as exc:
            errors.append(exc)
            raise
    record["state"] = "dispatching"
    record["trace"] = trace
    try:
        trace["active"] = True
        try:
            result = domain.modify("Cascadeur Complete: insert bounded absent position keys", author)
            trace["native_returned"] = True
            trace["native_true"] = result is True
        finally:
            trace["active"] = False
        if errors: raise errors[0]
        if not trace["native_true"] or not trace["callback_completed"] or trace["attempts"] != 1 or trace["unbounded"]:
            raise RuntimeError("NATIVE_COMPLETION_UNKNOWN: exactly one synchronous successful insertion callback required")
        after = read_scene(scene)
        if after != expected or rt._scene_view() is not scene:
            raise ValueError(_scope_failure(before, expected, after, operation="motion.key_topology_insert",
                space="local", data_id=str(data_id), callbacks=[], active_scene=rt._scene_view() is scene))
        result = {"status": "observed", "native_completion": "observed", "contract": CONTRACT,
            "key_id_kind": "layer_frame_locator", "added_keys": len(additions),
            "source_id": source["source_id"], "before_projection_digest": guards.digest(before),
            "after_projection_digest": guards.digest(after), "expected_projection_digest": guards.digest(expected),
            "old_keys_and_sections_preserved": True, "non_target_data_preserved": True,
            "preserved_empty_layer_ids": list(source["preserved_empty_layer_ids"]),
            "native_transaction": copy.deepcopy(trace), "durable_evaluation_receipt": "separate_operation_required"}
        observed_effect[0] = guards.observe_effect("motion.key_topology_insert", "completed", scene_before=identity,
            scene_after=dict(guards.scene_instance(scene)), detail=copy.deepcopy(result))
        record.update(state="completed", result=result, after=after)
        return copy.deepcopy(result)
    except Exception as exc:
        record.update(state="unknown", error=str(exc)[:2048])
        observed_effect[0] = guards.observe_effect("motion.key_topology_insert", "unknown", scene_before=identity,
            scene_after=dict(guards.scene_instance(scene)), detail={"source_id": source["source_id"],
                "native_transaction": copy.deepcopy(trace), "reason": str(exc)[:2048], "retry": "forbidden"})
        raise


def qualify_key_insertion():
    """Explicit four-scene experiment, retaining every tab and small .casc file.

    Prerequisite: already observed finite models in this process and an empty
    active setup scene. This never calls a prerequisite's mutating qualifier.
    """
    global _PROBE_SCENE, _QUALIFICATION_BYTES
    import csc
    from . import runtime as rt
    from .native_fixture import create_disposable_scene, create_independent_transform, _OWNED
    from .native_interpolation_qualification import evaluate_independent_transform
    from .native_scene_reader import read_scene
    from .native_adapters import _save_observed
    model = _model()
    manager = csc.app.get_application().get_scene_manager()
    previous = manager.current_scene()
    if previous is None or rt._domain_scene(previous).model_viewer().get_objects():
        raise ValueError("KEY_INSERTION_QUALIFICATION_REQUIRES_EMPTY_CURRENT_SCENE")
    if _PROBE_SCENE is not None:
        raise ValueError("KEY_INSERTION_QUALIFICATION_ALREADY_RUNNING")
    run_id = str(uuid.uuid4())
    folder = rt.runtime_root() / "snapshots" / ("key-insertion-qualification-" + run_id)
    folder.mkdir(parents=True, exist_ok=False)
    run = {"run_id": run_id, "status": "running", "phase": "starting", "retained_directory": str(folder),
        "production_registered": False, "trials": []}
    _RUNS[run_id] = run
    local_before = dict(vars(guards._LOCAL))
    generation = _CALLBACK_GENERATION
    _QUALIFICATION_BYTES = None
    try:
        previous_projection = read_scene(previous)
        for index, modes in enumerate((("LINEAR", "LINEAR"), ("STEP", "STEP"), ("LINEAR", "STEP"), ("STEP", "LINEAR"))):
            run["phase"] = "create_trial_" + str(index)
            owned_before = set(_OWNED)
            try:
                scene = create_disposable_scene(retain_on_failure=True)
            except Exception:
                for key in set(_OWNED) - owned_before:
                    run["trials"].append({"index": index, "status": "creation_failed_retained",
                        "scene_identity": dict(guards.scene_instance(_OWNED[key]["scene"])),
                        "saved_artifact": None, "save_reason": "activation_did_not_complete"})
                raise
            _PROBE_SCENE = scene
            trial = {"index": index, "segment_modes": list(modes), "status": "running",
                "scene_identity": dict(guards.scene_instance(scene)), "saved_path": str(folder / ("trial-" + str(index) + ".casc"))}
            run["trials"].append(trial)
            primary_error = None
            try:
                fixture = create_independent_transform(scene, "MCPKeyInsertionQualification",
                    [(0, [0., 0., 0.]), (4, [2., 1., 0.]), (8, [0., 2., 1.])], list(modes))
                run["phase"] = "baseline_evaluation_" + str(index)
                trial["baseline_evaluation"] = evaluate_independent_transform(scene, fixture)
                additions = [{"frame": 2, "position": [1.25, .25, .125], "mode": modes[0]},
                             {"frame": 6, "position": [.75, 1.75, .25], "mode": modes[1]}]
                source = prepare_insertion(scene, fixture["object_id"], fixture["layer_id"], additions)
                _SOURCES[source["source_id"]]["run_id"] = run_id
                guards.begin_request({"request_id": run_id + ":" + str(index)})
                run["phase"] = "insertion_" + str(index)
                trial["insertion"] = insert_positions(scene, source)
                expected = copy.deepcopy(_SOURCES[source["source_id"]]["after"])
                run["phase"] = "actual_evaluation_" + str(index)
                trial["actual_evaluation"] = evaluate_independent_transform(scene, fixture)
                actual = read_scene(scene)
                if actual != expected:
                    raise ValueError("KEY_INSERTION_EVALUATOR_MISMATCH: explicit interpolation changed the exact expected full projection")
                trial.update(status="observed", evaluated_projection_digest=guards.digest(actual),
                    object_id=fixture["object_id"], layer_id=fixture["layer_id"])
            except Exception as exc:
                primary_error = exc
                trial.update(status="failed", error=str(exc)[:2048])
                raise
            finally:
                # Failure tabs are never removed. Save errors cannot become a
                # success or hide the primary SDK failure; both stay observable.
                run["phase"] = "save_retained_trial_" + str(index)
                try:
                    before_save = read_scene(scene)
                    trial["saved_artifact"] = _save_observed(scene, folder / ("trial-" + str(index) + ".casc"))
                    if trial["saved_artifact"]["length"] > 2 * 1024 * 1024 or read_scene(scene) != before_save:
                        raise ValueError("KEY_INSERTION_FIXTURE_SAVE_UNVERIFIED: small unchanged saved fixture required")
                except Exception as save_error:
                    trial["save_error"] = str(save_error)[:2048]
                    if primary_error is None: raise
                finally:
                    _PROBE_SCENE = None
                    manager.set_current_scene(previous)
        if read_scene(previous) != previous_projection or _CALLBACK_GENERATION != generation:
            raise ValueError("KEY_INSERTION_QUALIFICATION_SOURCE_CHANGED")
        proof = {"schema_version": 1, "contract": CONTRACT, "native_build": SUPPORTED_BUILD,
            "runtime_epoch": guards.RUNTIME_EPOCH, "runtime_fingerprint": guards.LOADED_FINGERPRINT,
            "model_qualification_digest": guards.digest(model), "callback_generation": generation,
            "key_id_kind": "layer_frame_locator", "domain": {"objects": 1, "owning_layers": 1,
                "maximum_preserved_empty_layers": 7, "empty_layer_contract": "entire_projection_unchanged", "parent": None,
                "space": "local", "channel": "position", "models": ["LINEAR", "STEP"],
                "new_key_modes": "same_as_original_segment", "qualification_frames": list(range(9)),
                "original_keys": [0, 4, 8], "inserted_keys": [2, 6], "unkeyed_samples": [1, 3, 5, 7]},
            "run_id": run_id, "trials": copy.deepcopy(run["trials"])}
        _QUALIFICATION_BYTES = _freeze(proof)
        run.update(status="observed", phase="complete", qualification_digest=guards.digest(proof),
            quality="not_evaluated", durable_evaluation_receipt="not_issued_by_disposable_experiment")
        return copy.deepcopy(run)
    except Exception as exc:
        run.update(status="failed", error=str(exc)[:2048])
        exc.insertion_observation = copy.deepcopy(run)
        raise
    finally:
        _PROBE_SCENE = None
        try:
            manager.set_current_scene(previous)
        finally:
            vars(guards._LOCAL).clear()
            vars(guards._LOCAL).update(local_before)
