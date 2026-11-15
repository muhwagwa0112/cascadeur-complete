import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from cascadeur_complete.paths import RuntimePaths
from cascadeur_complete.recipe_models import RecipeSpec, digest
from cascadeur_complete.recipe_planning import build_plan
from cascadeur_complete.recipe_runner import RecipeRunner
from cascadeur_complete.recipe_store import RecipeConflict, RecipeRunStore


def spec_dict():
    profile = {"profile_id": "test", "character_id": "hero", "role_ids": {"root": "root"},
               "writable_ids": ["root"]}
    return {"input": {"kind": "active_scene", "binding": {
        "runtime_epoch": "epoch", "scene_instance_id": "scene", "document_lineage_id": "lineage",
        "scope_digest": "scope", "content_revision": "revision"}},
        "character": {"character_id": "hero", "root_id": "root", "object_ids": ["root"],
                      "role_ids": {"root": "root"}, "rig_profile_digest": digest(profile), "rig_profile": profile},
        "clip": {"first_frame": 5, "last_frame": 7, "fps_num": 24, "fps_den": 1,
                 "metres_per_scene_unit": .01, "scene_to_solver_basis": [[1, 0, 0], [0, 1, 0], [0, 0, 1]]},
        "rig": {"controller_adapter_id": "explicit-test-profile"},
        "intent": {"editable_frames": [5, 7]},
        "quality": {"profile_id": "test", "profile_revision": "1", "required_metrics": ["duration_error_s"],
                    "limits_si": {"duration_error_s": 0}}}


def allocated(tmp_path):
    paths = RuntimePaths.discover(tmp_path)
    paths.ensure()
    store = RecipeRunStore(paths)
    plan = store.save_plan(build_plan(RecipeSpec.model_validate(spec_dict()), []))
    grant = store.authorize(plan, time.time() + 300)
    run = store.create(plan, grant, "same-start")
    return paths, store, plan, grant, run


def allocated_readback(tmp_path, *, export=False, skip_before_readback=True):
    """Persist host-state fixtures; no native failure or quality evidence."""
    from cascadeur_complete.motion_context import IntentConstraints, RigProfile
    from cascadeur_complete.motion_quality import required_motion_metrics
    value = spec_dict()
    value["cleanup"] = [{"kind": "foot_contacts", "object_ids": ["root"]}]
    required = required_motion_metrics(RigProfile(**value["character"]["rig_profile"]),
                                       IntentConstraints.model_validate(value["intent"]))
    value["quality"].update(required_metrics=sorted(required), limits_si={name: 0 for name in required})
    if export:
        value["export"] = {"character_ref": "hero", "skeleton_map": [
            {"role": "root", "node_path": "Root", "source_id": "root"}], "take_name": "Take",
            "first_frame": 5, "last_frame": 7, "fps_num": 24,
            "axes": {"up_axis": 1, "up_sign": 1, "front_axis": 2, "front_sign": 1,
                     "coord_axis": 0, "coord_sign": 1}, "metres_per_export_unit": .01,
            "root_motion": {"node_path": "Root"}, "target_adapter": "host-test-only",
            "target_adapter_fingerprint": "unqualified", "target_import_settings_digest": "unqualified",
            "destination": str(tmp_path / "unused.fbx")}
    paths = RuntimePaths.discover(tmp_path)
    paths.ensure()
    store = RecipeRunStore(paths)
    plan = store.save_plan(build_plan(RecipeSpec.model_validate(value), []))
    grant = store.authorize(plan, time.time() + 300)
    run = store.create(plan, grant, "readback-boundary")
    record = next(item for item in run.steps if item.step_id.endswith("-actual_readback"))
    steps = [item.model_copy(update={"state": "skipped"}) if skip_before_readback and item.step_id < record.step_id else item
             for item in run.steps]
    run = store.compare_and_update(run.run_id, expected_seq=run.seq, lease_epoch=run.lease_epoch,
        transition={"state": "running", "steps": [item.model_dump(mode="json") for item in steps]})
    return paths, store, plan, run, next(item for item in run.steps if item.step_id == record.step_id)


def test_failed_actual_readback_persists_failed_step_and_run(tmp_path):
    """A capture/verification double exercises persistence, not native execution."""
    from cascadeur_complete.models import SourceBinding
    paths, store, plan, run, record = allocated_readback(tmp_path)
    source = SourceBinding(binding=plan.spec.input.binding, scope={}, sample_digest="sample",
                           inputs_digest="inputs", adapter_fingerprint="fingerprint", complete=True)
    runner = RecipeRunner(SimpleNamespace(paths=paths))
    runner._capture = lambda *args, **kwargs: {"global": {"source_binding": source.model_dump(mode="json")}}
    runner._verify_actual = lambda *args: {"status": "fail", "reason_codes": ["DRIVER_READBACK_MISMATCH:position_readback_m"]}
    step = next(item for item in plan.steps if item.step_id == record.step_id)
    runner._host_step(run, record, step, plan)
    failed = store.read(run.run_id)
    saved = next(item for item in failed.steps if item.step_id == record.step_id)
    assert failed.state == saved.state == "failed" and saved.verification_status == "fail"
    assert failed.blocked_reason == "ACTUAL_READBACK_FAILED"
    observation = store.read_artifact(run.run_id, saved.artifact_refs[-1])
    assert observation["verification"]["status"] == "fail"
    runner._schedule = lambda *_: pytest.fail("Failed readback cannot schedule another worker")
    runner.resume(run.run_id)
    assert store.read(run.run_id) == failed


@pytest.mark.parametrize("entry", ["resume", "advance", "resume_publish"])
def test_legacy_success_marked_failed_readback_cannot_resume_past_its_artifact(tmp_path, entry):
    paths, store, _, run, record = allocated_readback(tmp_path, export=entry == "resume_publish")
    observation = {"verification": {"status": "fail", "reason_codes": ["DRIVER_READBACK_MISMATCH:position_readback_m"]}}
    ref = store.artifact(run.run_id, record.step_id, observation)
    legacy = record.model_copy(update={"state": "succeeded", "result": observation, "artifact_refs": (ref,)})
    steps = [legacy if item.step_id == record.step_id else item for item in run.steps]
    if entry == "resume_publish":
        intent = tmp_path / "already-journaled-publish.intent.json"
        intent.write_text("{}", encoding="utf-8")
        steps = [item.model_copy(update={"state": "awaiting_result", "stage_data": {"intent_path": str(intent)}})
                 if item.step_id.endswith("-publish") else item for item in steps]
    run = store.compare_and_update(run.run_id, expected_seq=run.seq, lease_epoch=run.lease_epoch,
        transition={"state": "running" if entry == "advance" else "blocked",
            "blocked_reason": "ACTUAL_READBACK_FAILED", "steps": [item.model_dump(mode="json") for item in steps],
            "artifacts": [ref.model_dump(mode="json")]})
    runner = RecipeRunner(SimpleNamespace(paths=paths))
    def forbidden(*args, **kwargs):
        pytest.fail("Failed readback must precede preflight, dispatch and early publish")
    runner._check_plan = runner._schedule = runner._prepare = runner._export_host_step = forbidden
    if entry == "advance":
        runner.advance_once(run.run_id)
    else:
        runner.resume(run.run_id)
    stopped = store.read(run.run_id)
    assert stopped.state == "failed" and stopped.blocked_reason == "ACTUAL_READBACK_FAILED"
    assert stopped.steps == run.steps and stopped.artifacts == run.artifacts
    assert store.read_artifact(run.run_id, ref) == observation


def export_validation_fixture(tmp_path, monkeypatch, validation_result):
    """Real host persistence with consumer doubles; no native/FBX quality proof."""
    import hashlib
    import cascadeur_complete.recipe_runner as runner_module
    import cascadeur_complete.export_workflow as workflow
    import cascadeur_complete.target_capture as capture
    paths, store, plan, run, _ = allocated_readback(tmp_path, export=True, skip_before_readback=False)
    sealed = tmp_path / "sealed.fbx"
    sealed.write_bytes(b"host continuity fixture only")
    exported = {"artifact": {"path": str(sealed), "sha256": hashlib.sha256(sealed.read_bytes()).hexdigest(),
        "bytes": sealed.stat().st_size}, "export_stage": {"directory": str(tmp_path)},
        "before_export": {"global": {"fixture": "before-export"}}}
    baseline = {"global": {"fixture": "original"}}
    refs, steps = [], []
    for item in run.steps:
        stage = item.step_id.split("-", 1)[1]
        if stage in {"baseline_capture", "export_stage"}:
            value = exported if stage == "export_stage" else baseline
            ref = store.artifact(run.run_id, item.step_id, value)
            refs.append(ref)
            item = item.model_copy(update={"state": "succeeded", "result": value, "artifact_refs": (ref,),
                **({"request_id": "original-export", "attempt_id": "export-attempt", "calls_used": 1}
                   if stage == "export_stage" else {})})
        elif stage not in {"export_validate", "publish"} and item.state not in {"skipped", "succeeded"}:
            item = item.model_copy(update={"state": "skipped"})
        steps.append(item)
    run = store.compare_and_update(run.run_id, expected_seq=run.seq, lease_epoch=run.lease_epoch,
        transition={"steps": [item.model_dump(mode="json") for item in steps], "quality": "pass", "export": "staged",
                    "artifacts": [item.model_dump(mode="json") for item in refs]})
    calls = []
    def validate(artifact, profile, expected, **kwargs):
        calls.append((artifact.model_dump(mode="json"), profile, expected, kwargs["quality_context"]))
        return validation_result
    monkeypatch.setattr(runner_module, "_batch", lambda value: value)
    monkeypatch.setattr(capture, "make_export_expectation", lambda *args, **kwargs: "same-expectation")
    monkeypatch.setattr(capture, "roundtrip_quality_context", lambda *args, **kwargs: "same-original-context")
    monkeypatch.setattr(workflow, "validate_export", validate)
    runner = RecipeRunner(SimpleNamespace(paths=paths))
    runner._check_plan = lambda *args: None  # These doubles do not claim a qualified live runtime.
    runner._schedule = lambda *args: None
    return runner, store, plan, run, calls


@pytest.mark.parametrize("quality", ["fail", "unverified"])
def test_export_validation_nonpass_is_never_succeeded_or_published(tmp_path, monkeypatch, quality):
    runner, store, _, run, calls = export_validation_fixture(tmp_path, monkeypatch,
        {"export": "staged", "quality": quality, "target": {"status": quality}})
    runner.advance_once(run.run_id)
    observed = store.read(run.run_id)
    validation = next(item for item in observed.steps if item.step_id.endswith("-export_validate"))
    assert observed.state == ("failed" if quality == "fail" else "blocked")
    assert validation.state == ("failed" if quality == "fail" else "ready")
    assert validation.verification_status == quality and validation.calls_used == 1
    assert observed.export == "staged" and len(calls) == 1
    assert store.read_artifact(run.run_id, validation.artifact_refs[-1])["quality"] == quality
    if quality == "fail":
        runner.resume(run.run_id)
        assert store.read(run.run_id) == observed and len(calls) == 1
    else:
        # Explicit resumes consume only the existing read-retry budget, never a
        # fresh export request/profile/context or another native export attempt.
        for _ in range(2):
            runner.resume(run.run_id)
            runner.advance_once(run.run_id)
        retried = store.read(run.run_id)
        assert retried.budgets_used.read_retries == 2 and len(calls) == 3
        assert all(call == calls[0] for call in calls)
        export_step = next(item for item in retried.steps if item.step_id.endswith("-export_stage"))
        assert export_step.request_id == "original-export" and export_step.calls_used == 1
        runner.resume(run.run_id)
        with pytest.raises(RecipeConflict, match="read_retries"):
            runner.advance_once(run.run_id)
        assert len(calls) == 3


def test_unverified_export_validation_cancel_does_not_retry_consumer(tmp_path, monkeypatch):
    runner, store, _, run, calls = export_validation_fixture(tmp_path, monkeypatch,
        {"export": "staged", "quality": "unverified"})
    runner.advance_once(run.run_id)
    runner.cancel(run.run_id)
    canceled = store.read(run.run_id)
    assert canceled.state == "canceled" and canceled.export == "staged" and len(calls) == 1
    assert next(item for item in canceled.steps if item.step_id.endswith("-export_validate")).state == "canceled"


def test_legacy_nonpass_validation_cannot_enter_early_publish_resume(tmp_path, monkeypatch):
    result = {"export": "staged", "quality": "unverified"}
    runner, store, _, run, calls = export_validation_fixture(tmp_path, monkeypatch, result)
    record = next(item for item in run.steps if item.step_id.endswith("-export_validate"))
    ref = store.artifact(run.run_id, record.step_id, result)
    intent = tmp_path / "legacy-publish.intent.json"
    intent.write_text("{}", encoding="utf-8")
    steps = [item.model_copy(update={"state": "succeeded", "result": result, "artifact_refs": (ref,)})
        if item.step_id == record.step_id else item.model_copy(update={"state": "blocked", "stage_data": {"intent_path": str(intent)}})
        if item.step_id.endswith("-publish") else item for item in run.steps]
    run = store.compare_and_update(run.run_id, expected_seq=run.seq, lease_epoch=run.lease_epoch,
        transition={"state": "blocked", "blocked_reason": "EXPORT_VALIDATION_FAILED",
            "steps": [item.model_dump(mode="json") for item in steps],
            "artifacts": [item.model_dump(mode="json") for item in (*run.artifacts, ref)]})
    runner._export_host_step = lambda *args: pytest.fail("Nonpassing immutable validation cannot publish")
    runner.resume(run.run_id)
    stopped = store.read(run.run_id)
    assert stopped.state == "failed" and stopped.blocked_reason == "EXPORT_VALIDATION_FAILED"
    assert stopped.steps == run.steps and stopped.artifacts == run.artifacts and calls == []


def test_r4_checkpoint_steps_and_derived_identity_are_explicit():
    from cascadeur_complete.recipe_planning import compile_steps
    value = spec_dict()
    steps = compile_steps(RecipeSpec.model_validate(value))
    bootstrap = steps[1]
    assert bootstrap.stage == "initial_checkpoint" and bootstrap.operation_name == "safety.bootstrap"
    assert bootstrap.lowering_rule_id == "bootstrap-v1"
    checkpoints = [step for step in steps if step.stage == "checkpoint"]
    assert checkpoints and all(step.operation_name == "safety.checkpoint" and step.max_calls == 1 for step in checkpoints)
    value["character"] = {"derived_target": {"producer_step_id": bootstrap.step_id,
        "role_paths": {"root": "Character/Root"}, "topology_policy_digest": "a" * 64}}
    derived = RecipeSpec.model_validate(value)
    assert derived.character.character_id is None and derived.character.object_ids == ()
    value["character"]["character_id"] = "invented-before-import"
    with pytest.raises(ValidationError, match="invented"):
        RecipeSpec.model_validate(value)


def test_r4_late_terminal_receipt_resume_schedules_original_step(tmp_path):
    paths, store, _, _, run = allocated(tmp_path)
    record = run.steps[1].model_copy(update={"state": "blocked", "request_id": "original",
        "attempt_id": "attempt", "dispatch_lease_epoch": run.lease_epoch,
        "execution_outcome": "outcome_unknown", "result": {"host_commit_result": {"ok": True}}})
    run = store.compare_and_update(run.run_id, expected_seq=run.seq, lease_epoch=run.lease_epoch,
        transition={"state": "blocked", "blocked_reason": "outcome_unknown", "steps": [
            record.model_dump(mode="json") if item.step_id == record.step_id else item.model_dump(mode="json") for item in run.steps]})
    queried, scheduled = [], []
    receipt = {"phase": "terminal", "outcome": "succeeded", "request_id": "original", "run_id": run.run_id,
               "step_id": record.step_id, "attempt_id": "attempt", "lease_epoch": run.lease_epoch}
    runner = RecipeRunner(SimpleNamespace(paths=paths, client=SimpleNamespace(
        request_status=lambda request_id: queried.append(request_id) or receipt)))
    runner._schedule = scheduled.append
    runner.resume(run.run_id)
    resumed = store.read(run.run_id)
    restored = next(item for item in resumed.steps if item.step_id == record.step_id)
    assert queried == ["original"] and scheduled == [run.run_id]
    assert restored.state == "verifying" and restored.request_id == "original" and restored.calls_used == record.calls_used


def test_late_failed_receipt_continues_same_consumed_recovery_without_changing_original_outcome(tmp_path):
    """Host continuation routing only, not native failure/completion evidence."""
    paths, store, _, _, run = allocated(tmp_path)
    record = run.steps[1].model_copy(update={"state": "blocked", "request_id": "original",
        "attempt_id": "attempt", "dispatch_lease_epoch": run.lease_epoch, "token_ref": "consumed-token",
        "execution_outcome": "outcome_unknown"})
    run = store.compare_and_update(run.run_id, expected_seq=run.seq, lease_epoch=run.lease_epoch,
        transition={"state": "blocked", "blocked_reason": "outcome_unknown", "steps": [
            record.model_dump(mode="json") if item.step_id == record.step_id else item.model_dump(mode="json") for item in run.steps]})
    receipt = {"phase": "terminal", "outcome": "failed_after_dispatch", "request_id": "original",
        "run_id": run.run_id, "step_id": record.step_id, "attempt_id": "attempt", "lease_epoch": run.lease_epoch,
        "terminal_result": {"recovery_eligible": True, "outcome": "failed_after_dispatch"}}
    calls, scheduled = [], []
    recovery_state = "blocked_recovery_outcome_unknown"
    def continue_consumed(token, **expected):
        calls.append((token, expected))
        return {"ok": False, "request_id": "original", "phase": "terminal",
                "outcome": "failed_after_dispatch", "recovery_state": recovery_state}
    runner = RecipeRunner(SimpleNamespace(paths=paths, client=SimpleNamespace(request_status=lambda _: receipt),
        reconcile_consumed_change=continue_consumed))
    runner._schedule = scheduled.append
    runner.resume(run.run_id)
    waiting = store.read(run.run_id)
    assert waiting.state == "blocked" and waiting.blocked_reason == recovery_state
    failed_step = next(item for item in waiting.steps if item.step_id == record.step_id)
    assert failed_step.execution_outcome == "failed_after_dispatch" and failed_step.state == "blocked"
    assert failed_step.result["host_commit_result"]["recovery_state"] == recovery_state
    runner.status(run.run_id)
    assert len(calls) == 1  # Status is observation, not recovery execution.
    recovery_state = "recovered"
    runner.resume(run.run_id)
    finished = store.read(run.run_id)
    failed_step = next(item for item in finished.steps if item.step_id == record.step_id)
    assert finished.state == failed_step.state == "failed"
    assert failed_step.execution_outcome == receipt["outcome"] == "failed_after_dispatch"
    assert failed_step.result["host_commit_result"]["recovery_state"] == "recovered"
    assert failed_step.request_id == record.request_id and failed_step.calls_used == record.calls_used
    assert calls == [("consumed-token", {"expected_request_id": "original", "expected_execution_context": {
        "run_id": run.run_id, "step_id": record.step_id, "attempt_id": "attempt",
        "lease_epoch": run.lease_epoch, "request_id": "original"}})] * 2


def test_r4_worker_exit_preserves_pending_wakeup(tmp_path):
    import threading
    paths, _, _, _, run = allocated(tmp_path)
    runner = RecipeRunner(SimpleNamespace(paths=paths))
    entered, release, resumed = threading.Event(), threading.Event(), threading.Event()
    calls = []
    def work(run_id):
        calls.append(run_id)
        if len(calls) == 1:
            entered.set()
            assert release.wait(5)
        else:
            resumed.set()
    runner._work = work
    runner._schedule(run.run_id)
    assert entered.wait(5)
    runner._schedule(run.run_id)
    release.set()
    assert resumed.wait(5)
    assert calls == [run.run_id, run.run_id]


def test_strict_recipe_rejects_unknown_boolean_frames_and_nonfinite():
    for update in ({"arbitrary_operation": "scene.delete"},):
        with pytest.raises(ValidationError):
            RecipeSpec.model_validate({**spec_dict(), **update})
    value = spec_dict()
    value["clip"]["first_frame"] = True
    with pytest.raises(ValidationError):
        RecipeSpec.model_validate(value)
    value = spec_dict()
    value["intent"]["correction_envelope"] = {"position_m": float("nan")}
    with pytest.raises(ValidationError):
        RecipeSpec.model_validate(value)


def test_start_allocation_is_single_use_and_idempotent_across_stores(tmp_path):
    paths, store, plan, grant, run = allocated(tmp_path)
    other = RecipeRunStore(paths)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda item: item.create(plan, grant, "same-start").run_id, [store, other]))
    assert results == [run.run_id, run.run_id]
    with pytest.raises(RecipeConflict, match="already assigned"):
        other.create(plan, grant, "different-start")


def test_cas_retains_cancel_and_never_accepts_stale_writer(tmp_path):
    _, store, _, _, run = allocated(tmp_path)
    canceled = store.record_cancel_intent(run.run_id)
    with pytest.raises(RecipeConflict, match="conflict"):
        store.compare_and_update(run.run_id, expected_seq=run.seq, lease_epoch=run.lease_epoch,
                                 transition={"state": "running"})
    updated = store.compare_and_update(run.run_id, expected_seq=canceled.seq, lease_epoch=canceled.lease_epoch,
                                      transition={"cancel_requested": False})
    assert updated.cancel_requested


def test_signed_plan_and_artifact_tampering_is_rejected(tmp_path):
    _, store, plan, _, run = allocated(tmp_path)
    artifact = store.artifact(run.run_id, "quality", {"metric": 1})
    from pathlib import Path
    Path(artifact.path).write_text('{"metric":0}', encoding="utf-8")
    with pytest.raises(RecipeConflict, match="integrity"):
        store.read_artifact(run.run_id, artifact)
    path = store.root / "plans" / f"{plan.plan_id}.json"
    path.write_text(path.read_text().replace('"fps_num":24', '"fps_num":48'), encoding="utf-8")
    with pytest.raises(RecipeConflict, match="authentication"):
        store.read_plan(plan.plan_id)


def test_fresh_grant_continues_same_run_without_extending_wall_budget(tmp_path):
    _, store, plan, _, run = allocated(tmp_path)
    fresh = store.authorize(plan, time.time() + 600)
    renewed = store.renew_authorization(run.run_id, fresh)
    assert renewed.run_id == run.run_id and renewed.deadline == run.deadline
    assert renewed.authorization_id == fresh.authorization_id
    assert store.create(plan, fresh, run.idempotency_key).run_id == run.run_id
    with pytest.raises(RecipeConflict, match="already assigned"):
        store.create(plan, fresh, "another-run")


def test_effect_measurement_uses_explicit_quaternion_not_euler_guess(tmp_path):
    import math
    paths, store, plan, _, run = allocated(tmp_path)
    binding = {"binding": plan.spec.input.binding.model_dump(mode="json"), "scope": {},
               "sample_digest": "sample", "inputs_digest": "inputs", "adapter_fingerprint": "adapter", "complete": True}
    batch = {"context": {"frames": [5, 6, 7], "time_s": [0, 1 / 24, 2 / 24], "time_source": "fps",
                         "fps_num": 24, "fps_den": 1, "metres_per_scene_unit": .01,
                         "scene_to_solver_basis": [[1, 0, 0], [0, 1, 0], [0, 0, 1]], "metadata_provenance": {"test": "explicit"}},
             "object_ids": ["root"], "space": "local", "position_m": {"root": [[0, 0, 0]] * 3},
             "rotation_wxyz": {"root": [[1, 0, 0, 0]] * 3}, "channel_valid": {"root": [[True, True]] * 3},
             "source_binding": binding}
    capture = {"local": batch, "global": {**batch, "space": "global"}}
    ref = store.artifact(run.run_id, "baseline", capture)
    record = next(item for item in run.steps if item.step_id.endswith("-baseline_capture"))
    record = record.model_copy(update={"state": "succeeded", "result": capture, "artifact_refs": (ref,)})
    run = store.compare_and_update(run.run_id, expected_seq=run.seq, lease_epoch=run.lease_epoch,
                                   transition={"state": "running", "steps": [record.model_dump(mode="json") if item.step_id == record.step_id
                                                         else item.model_dump(mode="json") for item in run.steps]})
    runner = RecipeRunner(SimpleNamespace(paths=paths))
    effect = runner._measured_effect(run, plan, {"space": "local", "writes": [{"id": "root", "frame": 6,
        "rotation_euler_xyz_radians": [123, 456, 789],
        "expected_quaternion_wxyz": [math.sqrt(.5), math.sqrt(.5), 0, 0]}]})
    assert effect["rotation_rad"] == pytest.approx(math.pi / 2)


def test_unknown_receipt_never_replays_or_reads_scene(tmp_path):
    paths, store, plan, _, run = allocated(tmp_path)
    record = run.steps[0].model_copy(update={"state": "dispatching", "request_id": "original",
                                           "attempt_id": "attempt", "execution_outcome": "outcome_unknown"})
    run = store.compare_and_update(run.run_id, expected_seq=run.seq, lease_epoch=run.lease_epoch,
                                  transition={"state": "running", "steps": [record.model_dump(mode="json"),
                                               *[item.model_dump(mode="json") for item in run.steps[1:]]]})
    calls = []
    service = SimpleNamespace(paths=paths, client=SimpleNamespace(request_status=lambda request_id: (
        calls.append(request_id) or {"phase": "dispatch_started", "outcome": "outcome_unknown"})))
    runner = RecipeRunner(service)
    first = runner.reconcile(run.run_id)
    second = runner.reconcile(run.run_id)
    assert first.state == second.state == "blocked"
    assert first.blocked_reason == second.blocked_reason == "outcome_unknown"
    assert calls == ["original", "original"]
    assert runner.status(run.run_id)["workflow"] == "outcome_unknown"
    assert runner.status(run.run_id)["ok"] is False


@pytest.mark.parametrize("host_result, reason", [({"ok": False, "status": "failed"}, "HOST_POSTCONDITION_FAILED"),
                                                (None, "HOST_POSTCONDITION_RESULT_MISSING")])
def test_native_success_preserves_host_failure_or_missing_result(tmp_path, host_result, reason):
    paths, store, _, _, run = allocated(tmp_path)
    record = run.steps[0].model_copy(update={"state": "dispatching", "request_id": "original",
                                            "attempt_id": "attempt", "execution_outcome": "outcome_unknown",
                                            "result": None if host_result is None else {"host_commit_result": host_result}})
    run = store.compare_and_update(run.run_id, expected_seq=run.seq, lease_epoch=run.lease_epoch,
                                   transition={"state": "running", "steps": [record.model_dump(mode="json"),
                                                *[item.model_dump(mode="json") for item in run.steps[1:]]]})
    receipt = {"phase": "terminal", "outcome": "succeeded", "request_id": "original", "run_id": run.run_id,
               "step_id": record.step_id, "attempt_id": "attempt", "lease_epoch": run.lease_epoch}
    runner = RecipeRunner(SimpleNamespace(paths=paths, client=SimpleNamespace(request_status=lambda _: receipt)))
    updated = runner.reconcile(run.run_id)
    assert updated.state == "blocked" and updated.blocked_reason == reason
    assert updated.steps[0].execution_outcome == "succeeded"
    assert runner.status(run.run_id)["ok"] is False


def test_interrupted_checkpoint_is_not_dispatched_again(tmp_path):
    paths, store, _, _, run = allocated(tmp_path)
    steps = [item.model_copy(update={"state": "checkpointing" if item.step_id.endswith("-checkpoint") else "skipped"})
             for item in run.steps]
    run = store.compare_and_update(run.run_id, expected_seq=run.seq, lease_epoch=run.lease_epoch,
                                   transition={"state": "running", "steps": [item.model_dump(mode="json") for item in steps]})
    calls = []
    runner = RecipeRunner(SimpleNamespace(paths=paths, recipe_checkpoint=lambda *args: calls.append(args)))
    result = runner.advance_once(run.run_id)
    assert result.state == "blocked" and result.blocked_reason == "CHECKPOINT_MISSING"
    assert calls == []


def test_mandatory_quality_closure_blocks_duration_only_recipe(tmp_path):
    spec = RecipeSpec.model_validate(spec_dict())
    runner = RecipeRunner(SimpleNamespace(paths=RuntimePaths.discover(tmp_path),
                                         recipe_preflight=lambda *args: [], recipe_checkpoint=lambda *args: None))
    reasons = runner._preflight(spec, ())
    policy_reason = next(item for item in reasons if item["code"] == "QUALITY_POLICY_INCOMPLETE")
    assert {"root_preservation_m", "root_preservation_rad", "position_correction_m"} <= set(policy_reason["required_metrics"])
    assert runner.plan(spec)["accepted"] is False


def test_mandatory_quality_closure_requires_mesh_observations_and_rechecks_evaluation(tmp_path):
    from cascadeur_complete.motion_quality import evaluate_metrics, measured_metric
    value = spec_dict()
    value["character"]["required_mesh_ids"] = ["body-mesh"]
    spec = RecipeSpec.model_validate(value)
    runner = RecipeRunner(SimpleNamespace(paths=RuntimePaths.discover(tmp_path),
                                         recipe_preflight=lambda *args: [], recipe_checkpoint=lambda *args: None))
    reasons = runner._preflight(spec, ())
    policy_reason = next(item for item in reasons if item["code"] == "QUALITY_POLICY_INCOMPLETE")
    assert {"mesh_penetration_m", "mesh_surface_intersection_count"} <= set(policy_reason["required_metrics"])
    report = evaluate_metrics({"duration_error_s": measured_metric([0], units="s")}, spec.quality,
                              rig=runner._profile(spec), intent=spec.intent, include_mesh=True,
                              runtime_verified=True, capture_digest="a" * 64)
    assert report.status == "unverified" and not report.passed


def test_implementation_digest_tracks_real_bridge_copy_and_frozen_executable(tmp_path, monkeypatch):
    import shutil
    import sys
    from pathlib import Path
    from cascadeur_complete import package_fingerprint, recipe_planning

    source_package = Path(recipe_planning.__file__).parent
    source_bridge = source_package.parents[1] / "cascadeur_side" / "cascadeur_complete"
    copied_package = tmp_path / "src" / "cascadeur_complete"
    copied_bridge = tmp_path / "cascadeur_side" / "cascadeur_complete"
    copied_package.mkdir(parents=True)
    copied_bridge.mkdir(parents=True)
    for name in ("recipe_planning.py", "package_fingerprint.py"):
        shutil.copy2(source_package / name, copied_package / name)
    for name in ("runtime.py", "guarded_runtime.py"):
        shutil.copy2(source_bridge / name, copied_bridge / name)
    monkeypatch.setattr(recipe_planning, "__file__", str(copied_package / "recipe_planning.py"))
    monkeypatch.setattr(package_fingerprint, "__file__", str(copied_package / "package_fingerprint.py"))
    before = recipe_planning.implementation_digest()
    guard = copied_bridge / "guarded_runtime.py"
    guard.write_bytes(guard.read_bytes() + b"\n# changed copied bridge bytes\n")
    assert recipe_planning.implementation_digest() != before

    executable_copy = tmp_path / "copied-host.exe"
    shutil.copy2(sys.executable, executable_copy)
    monkeypatch.setattr(recipe_planning, "sys", SimpleNamespace(frozen=True, executable=str(executable_copy)))
    monkeypatch.setattr(recipe_planning, "__file__", str(tmp_path / "no-source" / "recipe_planning.py"))
    frozen_before = recipe_planning.implementation_digest()
    executable_copy.write_bytes(executable_copy.read_bytes() + b"\0")
    assert recipe_planning.implementation_digest() != frozen_before
