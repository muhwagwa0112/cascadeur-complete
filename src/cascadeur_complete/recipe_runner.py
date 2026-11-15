"""Finite recipe orchestration over protected service changes and durable receipts.

Only planning is public and declarative. Native effects use the same preparation
and single-use confirmation path as an individual protected change.
"""
from __future__ import annotations

import threading
import time
import uuid
from pathlib import Path
from typing import Any

import numpy as np
from scipy.spatial.transform import Rotation

from .atomic_queue import read_json
from .cleanup_workflow import CleanupWorkflow
from .models import SourceBinding
from .motion_context import MotionContext, MotionInputError, RigProfile, SampleBatch, SupportTrack, validate_samples
from .motion_quality import contact_metrics, evaluate_metrics, original_intent_metrics, required_motion_metrics, validate_quality_policy
from .recipe_authorization import validate_step_authorization, validate_usage
from .recipe_models import BudgetUsage, RecipeSpec, StepRecord, canonical_bytes, digest, run_view
from .recipe_planning import build_plan, compile_steps, implementation_digest, input_preflight
from .recipe_store import HOST_INSTANCE_ID, RecipeConflict, RecipeRunStore, TERMINAL_RUNS, TERMINAL_STEPS
from .store_lock import store_lock


def _json(value):
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if hasattr(value, "as_dict"):
        return _json(value.as_dict())
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, dict):
        return {key: _json(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, set, frozenset)):
        return [_json(item) for item in value]
    if isinstance(value, np.generic):
        return value.item()
    return value


def _batch_json(batch):
    return {"context": batch.context.as_dict(), "object_ids": list(batch.object_ids), "space": batch.space,
            "position_m": _json(batch.position_m), "rotation_wxyz": _json(batch.rotation_wxyz),
            "channel_valid": _json(batch.channel_valid), "source_binding": _json(batch.source_binding)}


def _batch(value):
    return SampleBatch(MotionContext.from_dict(value["context"]), tuple(value["object_ids"]), value["space"],
                       {key: np.asarray(item) for key, item in value["position_m"].items()},
                       {key: np.asarray(item) for key, item in value["rotation_wxyz"].items()},
                       {key: np.asarray(item, dtype=bool) for key, item in value["channel_valid"].items()},
                       SourceBinding.model_validate(value["source_binding"]))


class _PlanningService:
    """The solver can capture, but can only describe a mutation, never mint a token."""
    def __init__(self, service):
        self._service = service

    def prepare_change(self, feature_id, operation_name, arguments, ttl=300, **kwargs):
        return {"status": "candidate", "feature_id": feature_id, "operation_name": operation_name,
                "arguments": arguments, "source_binding": _json(kwargs.get("source_binding"))}

    def __getattr__(self, name):
        if name not in {"execute_readonly", "capture_source", "validate_source", "batch"}:
            raise RecipeConflict("Solver attempted an effect outside read-only planning")
        return getattr(self._service, name)


class RecipeRunner:
    def __init__(self, service):
        self.service = service
        self.store = RecipeRunStore(service.paths)
        self._threads: dict[str, threading.Thread] = {}
        self._threads_lock = threading.Lock()

    def _preflight(self, spec, steps):
        reasons = input_preflight(spec)
        hook = getattr(self.service, "recipe_preflight", None)
        if not callable(hook):
            reasons.append({"code": "RUNTIME_PREFLIGHT_UNAVAILABLE"})
        else:
            reasons.extend(hook(spec, steps))
        # These are native adapters, not generic user-supplied operation dispatch.
        for stage, required in (("input", spec.input.kind != "active_scene"),
                                ("rig", spec.rig.mode != "existing"),
                                ("motion", spec.motion.mode != "existing"),
                                ("export", spec.export is not None)):
            if required and not callable(getattr(self.service, f"recipe_{stage}_arguments", None)):
                reasons.append({"code": "STAGE_ADAPTER_UNAVAILABLE", "stage": stage})
        if not callable(getattr(self.service, "recipe_checkpoint", None)):
            reasons.append({"code": "CHECKPOINT_ADAPTER_UNAVAILABLE"})
        if spec.export is not None and not callable(getattr(self.service, "recipe_export_stage", None)):
            reasons.append({"code": "VERIFIED_EXPORT_ADAPTER_UNAVAILABLE"})
        if spec.intent.allow_key_insertion:
            reasons.append({"code": "KEY_TOPOLOGY_ADAPTER_UNAVAILABLE"})
        for cleanup in spec.cleanup:
            if cleanup.kind not in {"fingers", "foot_contacts"}:
                reasons.append({"code": "VERIFIED_CONTROLLER_ADAPTER_UNAVAILABLE", "kind": cleanup.kind})
            if cleanup.kind == "foot_contacts":
                verifier = getattr(self.service, "recipe_verify_interpolation", None)
                if not callable(verifier) or not verifier(spec, cleanup):
                    reasons.append({"code": "INTERPOLATION_MODEL_UNVERIFIED", "kind": cleanup.kind})
        try:
            rig = self._profile(spec)
        except (ValueError, TypeError, KeyError) as exc:
            reasons.append({"code": "RIG_MAPPING_AMBIGUOUS", "detail": str(exc)})
        else:
            try:
                validate_quality_policy(spec.quality, rig, spec.intent, self._include_mesh(spec, rig))
            except MotionInputError as exc:
                reasons.append({"code": exc.code, "detail": str(exc),
                                "required_metrics": sorted(required_motion_metrics(rig, spec.intent, self._include_mesh(spec, rig)))})
        return reasons

    @staticmethod
    def _include_mesh(spec, rig):
        return bool(spec.character.required_mesh_ids or rig.mesh_ids or spec.references.geometry
                    or spec.export is not None and spec.export.include_mesh)

    def plan(self, spec):
        spec = RecipeSpec.model_validate(spec)
        reasons = self._preflight(spec, compile_steps(spec))
        plan = build_plan(spec, reasons, self._runtime_fingerprints())
        self.store.save_plan(plan)
        return {"ok": False, "accepted": not plan.blocked_reasons,
                "workflow": "planned" if not plan.blocked_reasons else "waiting",
                "status": "planned" if not plan.blocked_reasons else "blocked", **plan.model_dump(mode="json")}

    def authorize(self, plan_id, plan_digest, scope_digest, expires_at):
        plan = self.store.read_plan(plan_id)
        if plan.plan_digest != plan_digest or plan.scope_digest != scope_digest:
            raise RecipeConflict("Explicit authorization must match the displayed plan and scope")
        self._check_plan(plan)
        grant = self.store.authorize(plan, expires_at)
        return {"ok": False, "accepted": True, "workflow": "authorized", **grant.model_dump(mode="json")}

    def _check_plan(self, plan):
        if plan.implementation_digest != implementation_digest():
            raise RecipeConflict("IMPLEMENTATION_CHANGED: plan again before authorization or dispatch")
        reasons = self._preflight(plan.spec, plan.steps)
        if reasons:
            raise RecipeConflict("PREFLIGHT_BLOCKED: " + canonical_bytes(reasons).decode("utf-8"))
        if self._runtime_fingerprints() != plan.runtime_fingerprints:
            raise RecipeConflict("RUNTIME_CHANGED: loaded bridge fingerprint or runtime epoch differs from the approved plan")

    def _runtime_fingerprints(self):
        status = getattr(getattr(self.service, "client", None), "runtime_status", {}) or {}
        return _json({"runtime_epoch": status.get("runtime_epoch"),
                      "loaded_adapter_fingerprint": status.get("adapter_fingerprint"),
                      "guarded_capabilities": status.get("guarded_capabilities"),
                      "installation_version": getattr(self.service, "_version_name", None)})

    def start(self, plan_id, authorization_id, idempotency_key):
        plan = self.store.read_plan(plan_id)
        grant = self.store.read_grant(authorization_id)
        # Repeating a previously allocated start is read-only, even after expiry.
        allocation = self.store.root / "authorizations" / grant.authorization_id / "allocation.json"
        if not allocation.exists():
            self._check_plan(plan)
        run = self.store.create(plan, grant, idempotency_key)
        if run.owner_host_instance_id == HOST_INSTANCE_ID and run.state not in TERMINAL_RUNS:
            self._schedule(run.run_id)
        return run_view(run)

    def status(self, run_id, after_seq=None):
        if after_seq is not None and (type(after_seq) is not int or after_seq < 0):
            raise RecipeConflict("after_seq must be a nonnegative integer")
        return run_view(self.store.read(run_id), after_seq)

    def artifacts(self, run_id):
        run = self.store.read(run_id)
        return {"run_id": run_id, "seq": run.seq, "artifacts": [item.model_dump(mode="json") for item in run.artifacts]}

    def cancel(self, run_id):
        run = self.store.record_cancel_intent(run_id)
        # No native abort and no implicit rollback. An in-flight request remains
        # unknown until its immutable terminal receipt arrives.
        for record in run.steps:
            if record.request_id and record.state in {"dispatching", "awaiting_result", "blocked"}:
                self.service.client.cancel_request(record.request_id)
        self._schedule(run_id)
        return run_view(self.store.read(run_id))

    def resume(self, run_id, authorization_id=None):
        run = self.store.adopt(run_id)
        if run.state in TERMINAL_RUNS:
            return run_view(run)
        if authorization_id is not None and authorization_id != run.authorization_id:
            run = self.store.renew_authorization(run_id, self.store.read_grant(authorization_id))
        if any(item.state in {"preparing", "dispatching", "awaiting_result", "blocked"} for item in run.steps):
            return run_view(self.reconcile(run_id))
        # A process interruption after an applied effect requires the persisted
        # successor checkpoint, never a new solve or mutation replay.
        if any(item.execution_outcome == "succeeded" and not item.checkpoint_ref
               and item.state not in TERMINAL_STEPS for item in run.steps):
            return run_view(self._update(run, state="blocked", blocked_reason="CHECKPOINT_MISSING"))
        self._check_plan(self.store.read_plan(run.plan_id))
        self.store.verify_grant(self.store.read_grant(run.authorization_id), self.store.read_plan(run.plan_id))
        if run.state == "blocked" and run.blocked_reason in {"QUALITY_UNVERIFIED", "QUALITY_FAILED"}:
            return run_view(run)
        if run.state == "blocked":
            run = self._update(run, state="cancel_requested" if run.cancel_requested else "running", blocked_reason=None)
        self._schedule(run_id)
        return run_view(run)

    def _schedule(self, run_id):
        with self._threads_lock:
            if run_id in self._threads and self._threads[run_id].is_alive():
                return
            worker = threading.Thread(target=self._supervise, args=(run_id,), daemon=True,
                                      name=f"cascadeur-recipe-{run_id}")
            self._threads[run_id] = worker
            worker.start()

    def _supervise(self, run_id):
        while True:
            before = self.store.read(run_id)
            if before.state in TERMINAL_RUNS or before.state == "blocked":
                return
            try:
                after = self.advance_once(run_id)
            except RecipeConflict as exc:
                # A concurrent cancellation may win the CAS. Re-read rather
                # than repeating a dispatch intent from stale memory.
                after = self.store.read(run_id)
                if str(exc) != "Run state or lease epoch conflict":
                    if after.state not in TERMINAL_RUNS:
                        self._update(after, state="blocked", blocked_reason=str(exc).split(":", 1)[0][:256])
                    return
            except Exception as exc:
                current = self.store.read(run_id)
                if current.state not in TERMINAL_RUNS:
                    self._update(current, state="blocked", blocked_reason=f"WORKER_EXCEPTION:{type(exc).__name__}")
                return
            if after.seq == before.seq:
                return

    def _update(self, run, **transition):
        return self.store.compare_and_update(run.run_id, expected_seq=run.seq,
                                             lease_epoch=run.lease_epoch, transition=transition)

    def _step_update(self, run, record, **transition):
        steps = tuple(record if item.step_id == record.step_id else item for item in run.steps)
        return self._update(run, steps=[item.model_dump(mode="json") for item in steps], **transition)

    def _persist_result(self, run, record, value, *, step_state="succeeded", **transition):
        value = _json(value)
        ref = self.store.artifact(run.run_id, record.step_id, value)
        updated = record.model_copy(update={"state": step_state, "result": value,
                                            "artifact_refs": (*record.artifact_refs, ref)})
        return self._step_update(run, updated, artifacts=[item.model_dump(mode="json") for item in (*run.artifacts, ref)],
                                 **transition)

    def advance_once(self, run_id):
        with store_lock(self.store.run_dir(run_id) / ".execution.lock"):
            run = self.store.read(run_id)
            if run.owner_host_instance_id != HOST_INSTANCE_ID:
                raise RecipeConflict("Only the active host lease can advance this run")
            if run.state in TERMINAL_RUNS or run.state == "blocked":
                return run
            plan = self.store.read_plan(run.plan_id)
            pending = next((item for item in run.steps if item.state not in TERMINAL_STEPS), None)
            if pending is None:
                success = (all(item.state in {"succeeded", "no_change", "skipped"} for item in run.steps)
                           and run.quality == "pass" and (plan.spec.export is None or run.export == "published"))
                return self._update(run, state="canceled" if run.cancel_requested else "succeeded" if success else "failed")
            step = next(item for item in plan.steps if item.step_id == pending.step_id)
            if pending.state in {"preparing", "dispatching", "awaiting_result", "blocked"}:
                return self.reconcile(run_id)
            if pending.state in {"verifying", "checkpointing"}:
                return self._finish_native(run, pending, step, plan)
            if run.cancel_requested:
                canceled = pending.model_copy(update={"state": "canceled", "execution_outcome": "canceled_pre_dispatch"})
                return self._step_update(run, canceled, state="canceled")
            validate_usage(plan, run.budgets_used, run.deadline)
            self.store.verify_grant(self.store.read_grant(run.authorization_id), plan)
            if pending.state == "prepared":
                return self._commit(run, pending, step, plan)
            if run.state == "queued":
                return self._update(run, state="running", current_step_id=pending.step_id)
            if step.not_required_reason:
                # Live preflight verifies these assertions; a client label is
                # never enough to skip an input/rig/motion obligation.
                self._check_plan(plan)
                return self._persist_result(run, pending, {"reason": step.not_required_reason,
                                                           "verified_by": "live_preflight"}, step_state="skipped")
            if step.stage == "preflight":
                self._check_plan(plan)
                return self._persist_result(run, pending, {"supported": True})
            if step.stage in {"source_capture", "baseline_capture", "actual_readback", "analyze", "solve", "quality"}:
                return self._host_step(run, pending, step, plan)
            if step.stage == "checkpoint":
                pending = pending.model_copy(update={"state": "checkpointing"})
                run = self._step_update(run, pending)
                result = self.service.recipe_checkpoint(run, plan, step)
                if not result.get("verified") or not result.get("sha256"):
                    raise RecipeConflict("CHECKPOINT_UNVERIFIED")
                ref = self.store.artifact(run_id, "checkpoint", result)
                record = pending.model_copy(update={"checkpoint_ref": ref.path, "verification_status": "pass"})
                return self._persist_result(run, record, result)
            if step.stage in {"export_stage", "export_validate", "publish"}:
                hook = getattr(self.service, f"recipe_{step.stage}", None)
                if not callable(hook):
                    raise RecipeConflict("VERIFIED_EXPORT_ADAPTER_UNAVAILABLE")
                # Export adapters receive only immutable permits; the installed
                # protected native export path must own its request journal.
                raise RecipeConflict("EXPORT_STAGE_REQUIRES_PERSISTED_NATIVE_PREPARATION")
            return self._prepare(run, pending, step, plan)

    @staticmethod
    def _profile(spec):
        value = dict(spec.character.rig_profile)
        for key in ("writable_ids", "derived_ids", "dependency_ids"):
            if key in value:
                value[key] = frozenset(value[key])
        profile = RigProfile(**value)
        if profile.character_id != spec.character.character_id or profile.role_ids != spec.character.role_ids:
            raise RecipeConflict("Rig profile differs from exact character roles")
        if not (set(profile.role_ids.values()) | set(profile.dependency_ids)) <= set(spec.character.object_ids):
            raise RecipeConflict("Rig dependencies escape the exact target object scope")
        return profile

    def _supports(self, spec):
        supports = {}
        for ref in spec.references.support_tracks:
            value = read_json(Path(ref.path))
            if value.get("artifact_id") != ref.artifact_id:
                raise RecipeConflict("Support artifact identity mismatch")
            expected = list(range(spec.clip.first_frame, spec.clip.last_frame + 1))
            if value.get("frames") != expected:
                raise RecipeConflict("INCOMPLETE_CAPTURE: support track frame coverage")
            supports[ref.artifact_id] = SupportTrack(ref.artifact_id, np.asarray(value["origin_m"]),
                                                    np.asarray(value["rotation_wxyz"]), value["geometry"])
        return supports

    def _workflow(self, spec, source=None, *, planning=False):
        frames = np.arange(spec.clip.first_frame, spec.clip.last_frame + 1, dtype=np.int64)
        if spec.clip.time_origin_s != 0:
            time_source = "explicit"
        else:
            time_source = "fps"
        context = MotionContext(frames, spec.clip.time_origin_s + (frames - frames[0]) * spec.clip.fps_den / spec.clip.fps_num,
                                time_source, spec.clip.fps_num, spec.clip.fps_den, spec.clip.metres_per_scene_unit,
                                np.asarray(spec.clip.scene_to_solver_basis), {"recipe_clip_digest": digest(spec.clip)})
        return CleanupWorkflow(_PlanningService(self.service) if planning else self.service,
                               profile=self._profile(spec), context=context, intent=spec.intent,
                               source_binding=source, supports=self._supports(spec))

    def _capture(self, spec, operation="motion.capture", arguments=None, source=None):
        workflow = self._workflow(spec, source)
        ids = spec.character.object_ids
        rotation_ids = tuple(item for item in self._profile(spec).role_ids.values()
                             if item in {obj for cleanup in spec.cleanup if cleanup.kind == "fingers" for obj in cleanup.object_ids})
        global_batch = workflow.capture_batch(ids, space="global", required_rotation_ids=rotation_ids)
        local_batch = workflow.capture_batch(ids, space="local", required_rotation_ids=rotation_ids)
        binding = _json(workflow._bind_source(operation, arguments))
        result = {"global": _batch_json(global_batch), "local": _batch_json(local_batch)}
        for value in result.values():
            value["source_binding"] = binding
        return result

    def _latest(self, run, prefix):
        records = [item for item in run.steps if item.step_id.split("-", 1)[-1] == prefix and item.result is not None]
        if not records:
            raise RecipeConflict(f"Missing persisted {prefix} artifact")
        # Integrity-check persisted bytes rather than trusting an in-memory copy.
        ref = records[-1].artifact_refs[-1]
        return self.store.read_artifact(run.run_id, ref)

    def _host_step(self, run, record, step, plan):
        used = run.budgets_used.model_dump()
        if step.stage in {"source_capture", "baseline_capture", "actual_readback"}:
            # Upper bound covers compact read chunks, rotation/local capture,
            # and source certification before entering the capture helper.
            n = plan.spec.clip.last_frame - plan.spec.clip.first_frame + 1
            used["bridge_requests"] += 4 * ((n * len(plan.spec.character.object_ids) + 24) // 25) + 8
            used["memory_bytes"] = max(used["memory_bytes"], n * len(plan.spec.character.object_ids) * 2048)
        if step.stage == "solve":
            used["solve_iterations"] += sum(int(item.parameters.get("limits", {}).get("iterations", 8))
                                             if plan.spec.cleanup[step.fixed_parameters["cleanup_index"]].kind == "foot_contacts"
                                             else 1 for item in step.candidate_variants)
            n = plan.spec.clip.last_frame - plan.spec.clip.first_frame + 1
            used["bridge_requests"] += len(step.candidate_variants) * (2 * ((n + 24) // 25) + 8)
            if plan.spec.cleanup[step.fixed_parameters["cleanup_index"]].kind == "foot_contacts":
                used["memory_bytes"] = max(used["memory_bytes"], n * n * 128)
        usage = BudgetUsage.model_validate(used)
        validate_usage(plan, usage, run.deadline)
        # Reserve all bounded resource costs before calling a native read helper
        # or host solver. Pure compute may be repeated after a crash, never writes.
        record = record.model_copy(update={"state": "ready"})
        run = self._step_update(run, record, budgets_used=usage.model_dump(mode="json"))
        if step.stage in {"source_capture", "baseline_capture", "actual_readback"}:
            value = (self._capture(plan.spec, "animation.interpolation_refresh", {}, run.current_binding)
                     if step.stage == "source_capture" else self._capture(plan.spec, source=run.current_binding))
            binding = SourceBinding.model_validate(value["global"]["source_binding"])
            if not binding.complete:
                raise RecipeConflict("BINDING_UNAVAILABLE")
            if step.stage == "actual_readback":
                verification = self._verify_actual(run, plan, value)
                value["verification"] = verification
                if verification["status"] != "pass":
                    return self._persist_result(run, record, value, state="blocked",
                                                blocked_reason="ACTUAL_READBACK_FAILED",
                                                current_binding=binding.model_dump(mode="json"))
            return self._persist_result(run, record, value, current_binding=binding.model_dump(mode="json"))
        baseline = self._latest(run, "baseline_capture")
        actual = self._latest(run, "actual_readback") if any(
            item.step_id.endswith("-actual_readback") and item.result for item in run.steps) else baseline
        if step.stage == "analyze":
            batch = _batch(baseline["global"])
            validate_samples(batch, {key: ("position",) for key in batch.object_ids})
            return self._persist_result(run, record, {"status": "complete", "capture_digest": digest(baseline),
                                                      "required_metrics": list(plan.spec.quality.required_metrics)})
        if step.stage == "solve":
            cleanup = plan.spec.cleanup[step.fixed_parameters["cleanup_index"]]
            workflow = self._workflow(plan.spec, run.current_binding, planning=True)
            candidates = []
            for variant in step.candidate_variants:
                result = _json(workflow.plan_pass(cleanup.kind, {**variant.parameters, "object_ids": list(cleanup.object_ids)}))
                if result.get("status") == "no_change":
                    candidates.append({"variant_id": variant.variant_id, **result})
                    break
                if result.get("status") == "candidate" and isinstance(result.get("arguments"), dict):
                    candidates.append({"variant_id": variant.variant_id, **result})
                    break
            if not candidates:
                raise RecipeConflict("NO_FEASIBLE_CANDIDATE: every approved variant failed")
            return self._persist_result(run, record, candidates[0])
        batch, original = _batch(actual["global"]), _batch(baseline["global"])
        rig = self._profile(plan.spec)
        metrics = original_intent_metrics(original, batch, rig, plan.spec.intent)
        metrics.update(contact_metrics(batch, rig, self._supports(plan.spec), plan.spec.intent.contacts,
                                       reference_batch=original))
        binding = SourceBinding.model_validate(actual["global"]["source_binding"])
        if not binding.complete:
            raise RecipeConflict("BINDING_UNAVAILABLE: actual quality source has no runtime certification")
        valid = self.service.validate_source(binding)
        if not valid.ok:
            raise RecipeConflict("SOURCE_CHANGED: actual quality capture is no longer the live source")
        report = evaluate_metrics(metrics, plan.spec.quality, runtime_verified=binding.complete, capture_digest=digest(actual),
                                  rig=rig, intent=plan.spec.intent, include_mesh=self._include_mesh(plan.spec, rig),
                                  capture=batch).as_dict()
        violations = self._original_constraints(plan, metrics)
        if violations:
            report["status"] = "fail"
            report["reason_codes"].extend(violations)
        return self._persist_result(run, record, report, quality=report["status"],
                                    **({} if report["status"] == "pass" else {"state": "blocked", "blocked_reason": "QUALITY_UNVERIFIED" if report["status"] == "unverified" else "QUALITY_FAILED"}))

    @staticmethod
    def _original_constraints(plan, metrics):
        envelope = plan.spec.intent.correction_envelope
        caps = {"position_correction_m": envelope.get("position_m", 0),
                "rotation_correction_rad": envelope.get("rotation_rad", 0)}
        if plan.spec.intent.root_policy == "preserve":
            caps.update(root_preservation_m=plan.spec.quality.limits_si.get("root_preservation_m", 1e-9),
                        root_preservation_rad=plan.spec.quality.limits_si.get("root_preservation_rad", 1e-9))
        if plan.spec.intent.preserve_timing:
            caps["duration_error_s"] = plan.spec.quality.limits_si.get("duration_error_s", 1e-12)
        if plan.spec.intent.locked_roles_frames or plan.spec.intent.key_pose_locks:
            caps.update(key_pose_position_m=plan.spec.quality.limits_si.get("key_pose_position_m", 1e-9),
                        key_pose_rotation_rad=plan.spec.quality.limits_si.get("key_pose_rotation_rad", 1e-9))
        return [f"ORIGINAL_INTENT_VIOLATION:{name}" for name, cap in caps.items()
                if name in metrics and metrics[name].get("status") == "measured" and metrics[name]["max"] > cap]

    def _verify_actual(self, run, plan, actual):
        original = self._latest(run, "baseline_capture")
        metrics = original_intent_metrics(_batch(original["global"]), _batch(actual["global"]),
                                           self._profile(plan.spec), plan.spec.intent)
        reasons = self._original_constraints(plan, metrics)
        candidate = self._latest(run, "solve")
        arguments = candidate.get("arguments", {})
        batch = _batch(actual[arguments.get("space", "global")])
        rows = {int(frame): index for index, frame in enumerate(batch.context.frames)}
        positions, rotations = [], []
        for write in arguments.get("writes", []):
            key, row = write["id"], rows[write["frame"]]
            if "position" in write:
                validate_samples(batch, {key: ("position",)})
                positions.append(float(np.linalg.norm(batch.position_m[key][row] - batch.context.positions_to_solver(write["position"]))))
            if "rotation_euler_xyz_radians" in write:
                validate_samples(batch, {key: ("rotation",)})
                q = write.get("expected_quaternion_wxyz")
                if q is None:
                    reasons.append("ROTATION_CONVENTION_UNVERIFIED")
                    continue
                expected = Rotation.from_matrix(batch.context.rotations_to_solver(Rotation.from_quat(np.asarray(q)[[1, 2, 3, 0]]).as_matrix()))
                observed = Rotation.from_quat(batch.rotation_wxyz[key][row][[1, 2, 3, 0]])
                rotations.append(float((expected.inv() * observed).magnitude()))
        for name, values, default in (("position_readback_m", positions, 1e-8), ("rotation_readback_rad", rotations, 1e-8)):
            if values and max(values) > plan.spec.quality.limits_si.get(name, default):
                reasons.append(f"DRIVER_READBACK_MISMATCH:{name}")
        return {"status": "fail" if reasons else "pass", "reason_codes": reasons,
                "original_metrics": metrics, "position_errors_m": positions, "rotation_errors_rad": rotations,
                "capture_digest": digest(actual), "candidate_digest": digest(candidate)}

    def _prepare(self, run, record, step, plan):
        if step.stage == "correction":
            candidate = self._latest(run, "solve")
            if candidate.get("status") == "no_change":
                return self._persist_result(run, record, candidate, step_state="no_change")
            if candidate.get("operation_name") != step.operation_name or candidate.get("feature_id") != step.feature_id:
                raise RecipeConflict("Solver candidate operation differs from the exact permit")
            arguments = candidate["arguments"]
            source = SourceBinding.model_validate(candidate["source_binding"])
            effect = self._measured_effect(run, plan, arguments)
        else:
            source, effect = run.current_binding, None
            if step.stage == "evaluation":
                if source is None:
                    raise RecipeConflict("BINDING_UNAVAILABLE: pre-evaluation source capture is missing")
                arguments = dict(step.fixed_parameters)
            else:
                adapter = getattr(self.service, f"recipe_{step.stage}_arguments", None)
                if not callable(adapter):
                    raise RecipeConflict("STAGE_ADAPTER_UNAVAILABLE")
                arguments = adapter(plan.spec, step)
        grant = self.store.read_grant(run.authorization_id)
        validate_step_authorization(self.store, grant, plan, run, step, source=source, arguments=arguments, measured_effect=effect)
        attempt_id, request_id = str(uuid.uuid4()), str(uuid.uuid4())
        usage = run.budgets_used.model_dump()
        usage["bridge_requests"] += 8
        usage["written_keys"] += len(arguments.get("writes", []))
        usage["generated_keys"] += int((effect or {}).get("added_keys", 0))
        usage["correction_passes"] += int(step.stage == "correction")
        usage = BudgetUsage.model_validate(usage)
        validate_usage(plan, usage, run.deadline)
        record = record.model_copy(update={"state": "preparing", "attempt_id": attempt_id, "request_id": request_id,
                                           "source_binding": source, "calls_used": record.calls_used + 1,
                                           "dispatch_lease_epoch": run.lease_epoch,
                                           "request_digest": digest(arguments)})
        run = self._step_update(run, record, budgets_used=usage.model_dump(mode="json"),
                                current_binding=source.model_dump(mode="json"))
        # Durable intent precedes snapshot/evaluation effects in prepare_change.
        prepared = self.service.prepare_change(step.feature_id, step.operation_name, arguments,
                                              min(plan.spec.budgets.per_step_seconds, grant.expires_at - time.time()),
                                              source_binding=source, execution_context={"run_id": run.run_id,
                                              "step_id": step.step_id, "attempt_id": attempt_id,
                                              "lease_epoch": run.lease_epoch, "request_id": request_id})
        if not prepared.get("confirmation_token"):
            return self._persist_result(self.store.read(run.run_id), record, prepared, step_state="blocked",
                                        state="blocked", blocked_reason="PREPARATION_BLOCKED")
        record = record.model_copy(update={"state": "prepared", "token_ref": prepared["confirmation_token"]})
        return self._step_update(self.store.read(run.run_id), record)

    def _measured_effect(self, run, plan, arguments):
        baseline = self._latest(run, "baseline_capture")
        space = arguments.get("space", "local" if "rotation" in arguments.get("channel", "") else "global")
        batch = _batch(baseline[space])
        positions, rotations = [0.0], [0.0]
        frames = {int(frame): index for index, frame in enumerate(batch.context.frames)}
        for write in arguments.get("writes", []):
            index, object_id = frames[write["frame"]], write["id"]
            if "position" in write:
                value = batch.context.positions_to_solver(write["position"])
                positions.append(float(np.linalg.norm(value - batch.position_m[object_id][index])))
            if "rotation_euler_xyz_radians" in write:
                quaternion = write.get("expected_quaternion_wxyz")
                if quaternion is None:
                    raise RecipeConflict("ROTATION_CONVENTION_UNVERIFIED: explicit expected quaternion is required")
                matrix = Rotation.from_quat(np.asarray(quaternion)[[1, 2, 3, 0]]).as_matrix()
                new = Rotation.from_matrix(batch.context.rotations_to_solver(matrix))
                old = Rotation.from_quat(batch.rotation_wxyz[object_id][index][[1, 2, 3, 0]])
                rotations.append(float((old.inv() * new).magnitude()))
        # Key insertion must be established against exact captured key topology.
        # Until that adapter exists, only plans forbidding insertion can dispatch.
        if plan.spec.intent.allow_key_insertion:
            raise RecipeConflict("KEY_TOPOLOGY_ADAPTER_UNAVAILABLE")
        return {"position_m": max(positions), "rotation_rad": max(rotations), "added_keys": 0}

    def _commit(self, run, record, step, plan):
        # Cancellation is checked again immediately before durable dispatch.
        current = self.store.read(run.run_id)
        if current.cancel_requested:
            return self._step_update(current, record.model_copy(update={"state": "canceled",
                                     "execution_outcome": "canceled_pre_dispatch"}), state="canceled")
        self.store.verify_grant(self.store.read_grant(run.authorization_id), plan)
        if plan.implementation_digest != implementation_digest() or plan.runtime_fingerprints != self._runtime_fingerprints():
            raise RecipeConflict("IMPLEMENTATION_CHANGED: prepared step cannot dispatch after host or loaded runtime changes")
        record = record.model_copy(update={"state": "dispatching", "execution_outcome": "outcome_unknown"})
        run = self._step_update(current, record)
        host_result = _json(self.service.commit_change(record.token_ref, timeout=plan.spec.budgets.per_step_seconds))
        current = self.store.read(run.run_id)
        record = next(item for item in current.steps if item.step_id == record.step_id)
        ref = self.store.artifact(run.run_id, "host_commit_result", host_result)
        record = record.model_copy(update={"state": "awaiting_result", "result": {"host_commit_result": host_result},
                                           "artifact_refs": (*record.artifact_refs, ref)})
        self._step_update(current, record, artifacts=[item.model_dump(mode="json") for item in (*current.artifacts, ref)])
        # A returned envelope is not authority for mutation outcome. Reconcile
        # the original immutable runtime receipt, preserving request identity.
        return self.reconcile(run.run_id)

    def reconcile(self, run_id):
        with store_lock(self.store.run_dir(run_id) / ".execution.lock"):
            run = self.store.read(run_id)
            record = next((item for item in run.steps if item.state in {"preparing", "dispatching", "awaiting_result", "blocked"}), None)
            if record is None or not record.request_id:
                return run
            try:
                receipt = self.service.client.request_status(record.request_id)
            except (ValueError, FileNotFoundError):
                return self._step_update(run, record.model_copy(update={"state": "blocked"}),
                                         state="blocked", blocked_reason="PREPARATION_OUTCOME_UNKNOWN")
            if receipt.get("phase") != "terminal":
                if receipt.get("outcome") == "canceled_pre_dispatch" and receipt.get("dispatched") is False:
                    return self._step_update(run, record.model_copy(update={"state": "canceled",
                                            "execution_outcome": "canceled_pre_dispatch"}), state="canceled")
                return self._step_update(run, record.model_copy(update={"state": "blocked", "execution_outcome": "outcome_unknown"}),
                                         state="blocked", blocked_reason="outcome_unknown")
            if any(receipt.get(key) != expected for key, expected in {
                "request_id": record.request_id, "run_id": run.run_id, "step_id": record.step_id,
                "attempt_id": record.attempt_id, "lease_epoch": record.dispatch_lease_epoch or run.lease_epoch,
            }.items()):
                return self._update(run, state="blocked", blocked_reason="RECEIPT_BINDING_MISMATCH")
            outcome = receipt.get("outcome")
            if outcome not in {"succeeded", "failed_after_dispatch", "canceled_pre_dispatch", "rejected_pre_dispatch"}:
                return self._update(run, state="blocked", blocked_reason="outcome_unknown")
            if outcome == "succeeded":
                host_result = (record.result or {}).get("host_commit_result")
                if host_result is None or not host_result.get("ok"):
                    reason = "HOST_POSTCONDITION_RESULT_MISSING" if host_result is None else "HOST_POSTCONDITION_FAILED"
                    return self._step_update(run, record.model_copy(update={"state": "blocked",
                                            "execution_outcome": "succeeded", "verification_status": "unverified" if host_result is None else "fail"}),
                                            state="blocked", blocked_reason=reason)
            ref = self.store.artifact(run_id, "runtime_receipt", receipt)
            updated = record.model_copy(update={"state": "verifying" if outcome == "succeeded" else "failed",
                                               "execution_outcome": outcome, "receipt_ref": ref.path,
                                               "artifact_refs": (*record.artifact_refs, ref)})
            return self._step_update(run, updated, state="running" if outcome == "succeeded" and not run.cancel_requested
                                     else "cancel_requested" if outcome == "succeeded" else "canceled" if outcome == "canceled_pre_dispatch" else "failed",
                                     blocked_reason=None, artifacts=[item.model_dump(mode="json") for item in (*run.artifacts, ref)])

    def _finish_native(self, run, record, step, plan):
        # No further evaluation or transform read occurs while outcome is
        # unknown. Reaching this branch requires its terminal success receipt.
        if record.state == "checkpointing":
            return self._update(run, state="blocked", blocked_reason="CHECKPOINT_MISSING")
        record = record.model_copy(update={"state": "checkpointing"})
        run = self._step_update(run, record)
        value = self.service.recipe_checkpoint(run, plan, step)
        if not value.get("verified") or not value.get("sha256") or not value.get("source_binding"):
            return self._update(run, state="blocked", blocked_reason="CHECKPOINT_MISSING")
        binding = SourceBinding.model_validate(value["source_binding"])
        if not binding.complete:
            return self._update(run, state="blocked", blocked_reason="SUCCESSOR_BINDING_UNVERIFIED")
        ref = self.store.artifact(run.run_id, "successor_checkpoint", value)
        record = record.model_copy(update={"checkpoint_ref": ref.path, "expected_successor": binding,
                                           "verification_status": "pass"})
        return self._persist_result(run, record, value, current_binding=binding.model_dump(mode="json"))
