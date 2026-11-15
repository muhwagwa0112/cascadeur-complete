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
from .motion_quality import contact_metrics, evaluate_actual_quality, original_intent_metrics, required_motion_metrics, validate_quality_policy
from .recipe_authorization import validate_step_authorization, validate_usage
from .recipe_models import BudgetUsage, RecipeSpec, StepRecord, canonical_bytes, digest, run_view
from .recipe_planning import build_plan, compile_steps, implementation_digest, input_preflight
from .recipe_store import HOST_INSTANCE_ID, RecipeConflict, RecipeRunStore, TERMINAL_RUNS, TERMINAL_STEPS
from .store_lock import store_lock
from .stage_contracts import StageEffect
from .capture import estimate_motion_resources, enforce_motion_budget


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
        if name not in {"execute_readonly", "capture_source", "validate_source", "recipe_rebind_source", "batch", "observe_key_layout", "verify_key_layout", "observe_motion_capture", "recipe_verify_capture",
                        "observe_retarget_inputs", "verify_retarget_inputs", "motion_controller_adapter", "verify_controller_targets",
                        "motion_rotation_adapter"}:
            raise RecipeConflict("Solver attempted an effect outside read-only planning")
        return getattr(self._service, name)


class RecipeRunner:
    def __init__(self, service):
        self.service = service
        self.store = RecipeRunStore(service.paths)
        self._threads: dict[str, threading.Thread] = {}
        self._threads_lock = threading.Lock()
        self._wakeups: set[str] = set()

    def _preflight(self, spec, steps, **context):
        reasons = input_preflight(spec)
        hook = getattr(self.service, "recipe_preflight", None)
        if not callable(hook):
            reasons.append({"code": "RUNTIME_PREFLIGHT_UNAVAILABLE"})
        else:
            reasons.extend(hook(spec, steps, **context))
        if spec.motion.mode == "retarget" and spec.motion.route == "host" and not callable(getattr(CleanupWorkflow, "plan_retarget", None)):
            reasons.append({"code": "HOST_RETARGET_CONTROLLER_ADAPTER_UNAVAILABLE"})
        if spec.character.derived_target is not None:
            producer = next((item for item in steps if item.step_id == spec.character.derived_target.producer_step_id), None)
            if producer is None or producer.stage not in {"initial_checkpoint", "rig"}:
                reasons.append({"code": "DERIVED_TARGET_PRODUCER_INVALID"})
            return reasons
        try:
            rig = self._profile(spec)
        except (ValueError, TypeError, KeyError) as exc:
            reasons.append({"code": "RIG_MAPPING_AMBIGUOUS", "detail": str(exc)})
        else:
            required = set(required_motion_metrics(rig, spec.intent, self._include_mesh(spec, rig)))
            if self._required_rotation_ids(spec, rig):
                required.add("rotation_correction_rad")
            try:
                validate_quality_policy(spec.quality, rig, spec.intent, self._include_mesh(spec, rig))
                missing = required - set(spec.quality.required_metrics)
                if missing:
                    raise MotionInputError("QUALITY_POLICY_INCOMPLETE",
                        "required recipe capture metrics omitted: " + ", ".join(sorted(missing)))
                if spec.export is not None:
                    roundtrip = {"position_readback_m", "rotation_readback_rad", "duration_error_s"}
                    missing = roundtrip - set(spec.quality.required_metrics)
                    if missing:
                        reasons.append({"code": "EXPORT_ROUNDTRIP_METRICS_REQUIRED", "metrics": sorted(missing)})
            except MotionInputError as exc:
                reasons.append({"code": exc.code, "detail": str(exc),
                                "required_metrics": sorted(required)})
        return reasons

    @staticmethod
    def _include_mesh(spec, rig):
        return bool(spec.character.required_mesh_ids or rig.mesh_ids or spec.references.geometry
                    or spec.export is not None and spec.export.include_mesh)

    def plan(self, spec):
        spec = RecipeSpec.model_validate(spec)
        binding_reasons = []
        if spec.input.kind != "active_scene":
            try:
                spec = self.service.recipe_bind_input(spec)
            except (ValueError, OSError) as exc:
                binding_reasons.append({"code": "FILE_BOOTSTRAP_SOURCE_UNVERIFIED", "detail": str(exc)})
        reasons = binding_reasons + self._preflight(spec, compile_steps(spec))
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

    def _check_plan(self, plan, run=None):
        if plan.implementation_digest != implementation_digest():
            raise RecipeConflict("IMPLEMENTATION_CHANGED: plan again before authorization or dispatch")
        context = {}
        if run is not None and any(item.execution_outcome == "succeeded" for item in run.steps):
            receipts = [ref for item in run.steps for ref in item.artifact_refs if ref.kind == "runtime_receipt"]
            if not receipts:
                raise RecipeConflict("CONTINUATION_EVIDENCE_MISSING")
            context = {"mode": "continuation", "current_binding": run.current_binding,
                       "predecessor_receipt": self.store.read_artifact(run.run_id, receipts[-1])}
        spec = plan.spec if run is None or not run.derived_targets else self.effective_spec(plan.spec, run)
        reasons = self._preflight(spec, plan.steps, **context)
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
        if run.state in TERMINAL_RUNS:
            return run_view(run)
        # Adoption proves that a previous process has exited; recording intent
        # alone cannot give this host permission to advance its lease.
        self.store.adopt(run_id)
        return self._continue_cancellation(run_id)

    def _continue_cancellation(self, run_id):
        with store_lock(self.store.run_dir(run_id) / ".execution.lock"):
            run = self.store.read(run_id)
            if run.state in TERMINAL_RUNS:
                return run_view(run)
            if run.owner_host_instance_id != HOST_INSTANCE_ID:
                raise RecipeConflict("Only the active host lease can advance this run")
            if not run.cancel_requested:
                raise RecipeConflict("Cancellation intent is required")
            record = next((item for item in run.steps if item.state not in TERMINAL_STEPS), None)
            if record is None:
                return run_view(self._update(run, state="canceled", blocked_reason=None))
            published_intent = (record.step_id.endswith("-publish") and record.stage_data
                                and Path(record.stage_data["intent_path"]).exists())
            # A completed preparation has not dispatched its mutation. Preserve
            # the original token, request, grant and usage; no live scene or
            # still-current implementation/authorization is needed to stop it.
            if (not published_intent and record.execution_outcome == "not_dispatched"
                    and record.receipt_ref is None
                    and (record.state in {"pending", "ready", "prepared"}
                         or record.state == "blocked" and record.request_id is None)):
                canceled = record.model_copy(update={"state": "canceled", "execution_outcome": "canceled_pre_dispatch"})
                return run_view(self._step_update(run, canceled, state="canceled", blocked_reason=None))
            if run.state == "blocked":
                run = self._update(run, state="cancel_requested", blocked_reason=None)
            # Already issued native work and journaled publication must finish
            # their original observation path. A queue cancellation is only a
            # hint; it never establishes that an unknown effect did not occur.
            if not published_intent and record.state not in {"verifying", "checkpointing"}:
                if record.request_id:
                    try:
                        self.service.client.cancel_request(record.request_id)
                    except (ValueError, FileNotFoundError):
                        pass  # Reconciliation retains an unavailable receipt as unknown.
                if record.state not in {"preparing", "dispatching", "awaiting_result", "blocked"}:
                    run = self._step_update(run, record.model_copy(update={"state": "blocked"}))
                run = self.reconcile(run_id)
            if run.state not in TERMINAL_RUNS and run.state != "blocked":
                self._schedule(run_id)
            return run_view(run)

    def resume(self, run_id, authorization_id=None):
        run = self.store.adopt(run_id)
        if run.state in TERMINAL_RUNS:
            return run_view(run)
        if run.cancel_requested:
            return self._continue_cancellation(run_id)
        if authorization_id is not None and authorization_id != run.authorization_id:
            run = self.store.renew_authorization(run_id, self.store.read_grant(authorization_id))
        publish = next((item for item in run.steps if item.step_id.endswith("-publish")
                        and item.stage_data and Path(item.stage_data["intent_path"]).exists()), None)
        if publish is not None and publish.state not in TERMINAL_STEPS:
            plan = self.store.read_plan(run.plan_id)
            step = next(item for item in plan.steps if item.step_id == publish.step_id)
            if run.state == "blocked":
                run = self._update(run, state="cancel_requested" if run.cancel_requested else "running", blocked_reason=None)
            run = self._export_host_step(run, publish, step, plan)
            self._schedule(run_id)
            return run_view(run)
        if any(item.state in {"preparing", "dispatching", "awaiting_result", "blocked"} for item in run.steps):
            run = self.reconcile(run_id)
            if run.state != "blocked":
                self._schedule(run_id)
            return run_view(run)
        if any(item.state in {"verifying", "checkpointing"} for item in run.steps):
            # A failed observation leaves the native step in this state. Resume
            # the existing receipt, even after expiry, rather than dispatching it
            # again or scheduling a worker that immediately exits as blocked.
            if run.state == "blocked":
                run = self._update(run, state="cancel_requested" if run.cancel_requested else "running", blocked_reason=None)
            self._schedule(run_id)
            return run_view(run)
        # A process interruption after an applied effect requires the persisted
        # successor checkpoint, never a new solve or mutation replay.
        self._check_plan(self.store.read_plan(run.plan_id), run)
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
                self._wakeups.add(run_id)
                return
            worker = threading.Thread(target=self._supervise, args=(run_id,), daemon=True,
                                      name=f"cascadeur-recipe-{run_id}")
            self._threads[run_id] = worker
            worker.start()

    def _supervise(self, run_id):
        try:
            self._work(run_id)
        finally:
            with self._threads_lock:
                self._threads.pop(run_id, None)
                wake = run_id in self._wakeups
                self._wakeups.discard(run_id)
            if wake:
                run = self.store.read(run_id)
                if run.state not in TERMINAL_RUNS and run.state != "blocked":
                    self._schedule(run_id)

    def _work(self, run_id):
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
                    self._update(current, state="blocked", blocked_reason=str(getattr(exc, "code", f"WORKER_EXCEPTION:{type(exc).__name__}"))[:256])
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
            # An already journaled atomic publication is observed even when its
            # authorization has since expired or cancellation was requested.
            if step.stage == "publish" and pending.stage_data and Path(pending.stage_data["intent_path"]).exists():
                return self._export_host_step(run, pending, step, plan)
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
                self._check_plan(plan, run)
                return self._persist_result(run, pending, {"reason": step.not_required_reason,
                                                           "verified_by": "live_preflight"}, step_state="skipped")
            if step.stage == "preflight":
                self._check_plan(plan, run)
                return self._persist_result(run, pending, {"supported": True})
            if step.stage in {"source_capture", "baseline_capture", "retarget_capture", "actual_readback", "analyze", "solve", "quality", "host_retarget"}:
                return self._host_step(run, pending, step, plan)
            if step.stage in {"export_validate", "publish"}:
                return self._export_host_step(run, pending, step, plan)
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

    @staticmethod
    def effective_spec(spec, run):
        reference = spec.character.derived_target
        if reference is None:
            return spec
        mapping = next((item for item in run.derived_targets if item.reference_digest == digest(reference)), None)
        if mapping is None:
            raise RecipeConflict("DERIVED_TARGET_UNRESOLVED")
        value = spec.model_dump(mode="json")
        value["character"].update(character_id=mapping.character_id, root_id=mapping.root_id,
            object_ids=list(mapping.object_ids), layer_ids=list(mapping.layer_ids), role_ids=mapping.role_ids,
            rig_profile=mapping.rig_profile, rig_profile_digest=mapping.rig_profile_digest, derived_target=None)
        for cleanup in value["cleanup"]:
            cleanup["object_ids"] = [mapping.role_ids[key] for key in cleanup["object_ids"]]
            for parameters in (cleanup["parameters"], *(variant["parameters"] for variant in cleanup["variants"])):
                if "joint_ids" in parameters:
                    parameters["joint_ids"] = [mapping.role_ids[key] for key in parameters["joint_ids"]]
        for write in value["motion"]["keyposes"]:
            write["id"] = mapping.role_ids[write["id"]]
        return RecipeSpec.model_validate(value)

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

    @staticmethod
    def _required_rotation_ids(spec, rig):
        ids = spec.character.object_ids
        roles = {"root", *spec.intent.key_pose_locks, *spec.intent.locked_roles_frames}
        return tuple(sorted(set(ids) if spec.export is not None or (spec.motion.mode == "retarget" and spec.motion.host_channel == "rotation") else
            {rig.role_ids[role] for role in roles if role in rig.role_ids}
            | {obj for cleanup in spec.cleanup if cleanup.kind in {"fingers", "finger_fan", "wrist_soften", "hand_pose"}
               for obj in cleanup.object_ids}))

    def _capture(self, spec, source=None):
        workflow = self._workflow(spec, source)
        ids = spec.character.object_ids
        rotation_ids = self._required_rotation_ids(spec, self._profile(spec))
        global_batch = workflow.capture_batch(ids, space="global", required_rotation_ids=rotation_ids)
        local_batch = workflow.capture_batch(ids, space="local", required_rotation_ids=rotation_ids)
        # The native observation registry authenticates these exact canonical
        # bytes, including their source binding. A newly bound write scope must
        # never replace that binding on an already issued sample batch.
        return {"global": _batch_json(global_batch), "local": _batch_json(local_batch)}

    def _latest(self, run, prefix):
        records = [item for item in run.steps if item.step_id.split("-", 1)[-1] == prefix and item.result is not None]
        if not records:
            raise RecipeConflict(f"Missing persisted {prefix} artifact")
        # Integrity-check persisted bytes rather than trusting an in-memory copy.
        ref = records[-1].artifact_refs[-1]
        return self.store.read_artifact(run.run_id, ref)

    def _host_step(self, run, record, step, plan):
        # Resolve symbolic selectors only from immutable producer evidence.
        plan = plan.model_copy(update={"spec": self.effective_spec(plan.spec, run)})
        validate_quality_policy(plan.spec.quality, self._profile(plan.spec), plan.spec.intent,
                                self._include_mesh(plan.spec, self._profile(plan.spec)))
        if step.stage == "host_retarget":
            from .recipe_store import file_sha256
            source = plan.spec.motion.source
            sha, size = file_sha256(Path(source.path))
            if sha != source.sha256 or size != source.length:
                raise RecipeConflict("RETARGET_SOURCE_DIGEST_MISMATCH")
            value = read_json(Path(source.path))
            workflow = self._workflow(plan.spec, run.current_binding, planning=True)
            planner = getattr(workflow, "plan_retarget", None)
            if not callable(planner):
                raise RecipeConflict("HOST_RETARGET_CONTROLLER_ADAPTER_UNAVAILABLE")
            settings = dict(plan.spec.motion.settings)
            if settings.get("target_channels", [plan.spec.motion.host_channel]) != [plan.spec.motion.host_channel]:
                raise RecipeConflict("RETARGET_CHANNEL_DECLARATION_MISMATCH")
            settings["target_channels"] = [plan.spec.motion.host_channel]
            result = _json(planner(value, dict(plan.spec.motion.mapping), settings))
            if result.get("status") not in {"candidate", "no_change"}:
                return self._persist_result(run, record, result, state="blocked", blocked_reason="HOST_RETARGET_UNVERIFIED")
            return self._persist_result(run, record, result)
        used = run.budgets_used.model_dump()
        if step.stage in {"source_capture", "baseline_capture", "retarget_capture", "actual_readback"}:
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
                estimate = estimate_motion_resources(n, {key: n for key in plan.spec.cleanup[step.fixed_parameters["cleanup_index"]].object_ids},
                    retained_capture_bytes=n * len(plan.spec.character.object_ids) * 2048)
                enforce_motion_budget(estimate, {"max_memory_bytes": plan.spec.budgets.memory_bytes})
                used["memory_bytes"] = max(used["memory_bytes"], estimate["estimated_peak_bytes"])
        usage = BudgetUsage.model_validate(used)
        validate_usage(plan, usage, run.deadline)
        # Reserve all bounded resource costs before calling a native read helper
        # or host solver. Pure compute may be repeated after a crash, never writes.
        record = record.model_copy(update={"state": "ready"})
        run = self._step_update(run, record, budgets_used=usage.model_dump(mode="json"))
        if step.stage in {"source_capture", "baseline_capture", "retarget_capture", "actual_readback"}:
            value = self._capture(plan.spec, source=run.current_binding)
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
        report = evaluate_actual_quality(original, batch, rig, plan.spec.intent, plan.spec.quality,
            supports=self._supports(plan.spec), capture_verifier=getattr(self.service, "recipe_verify_capture", None)).as_dict()
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
        context = {}
        if step.stage == "correction":
            candidate = self._latest(run, "solve")
            if candidate.get("status") == "no_change":
                return self._persist_result(run, record, candidate, step_state="no_change")
            if candidate.get("operation_name") != step.operation_name or candidate.get("feature_id") != step.feature_id:
                raise RecipeConflict("Solver candidate operation differs from the exact permit")
            context["candidate"] = candidate
            context["source_binding"] = candidate["source_binding"]
            measured = self._measured_effect(run, plan, candidate["arguments"])
        else:
            measured = None
        if step.stage == "motion" and plan.spec.motion.mode == "retarget" and plan.spec.motion.route == "host":
            candidate = self._latest(run, "host_retarget")
            if candidate.get("status") == "no_change":
                return self._persist_result(run, record, candidate, step_state="no_change")
            if candidate.get("operation_name") != step.operation_name or candidate.get("feature_id") != step.feature_id:
                raise RecipeConflict("RETARGET_CANDIDATE_OPERATION_MISMATCH")
            context["candidate"] = candidate
            context["source_binding"] = candidate["source_binding"]
            measured = self._measured_effect(run, plan, candidate["arguments"], baseline_prefix="retarget_capture")
        if step.stage == "export_stage":
            from .export_workflow import create_export_stage
            if record.stage_data is None:
                spec = self.effective_spec(plan.spec, run)
                n = spec.clip.last_frame - spec.clip.first_frame + 1
                used = run.budgets_used.model_dump()
                used["bridge_requests"] += 4 * ((n * len(spec.character.object_ids) + 24) // 25) + 8
                used["memory_bytes"] = max(used["memory_bytes"], n * len(spec.character.object_ids) * 2048)
                usage = BudgetUsage.model_validate(used)
                validate_usage(plan, usage, run.deadline)
                run = self._step_update(run, record, budgets_used=usage.model_dump(mode="json"))
                stage = create_export_stage(plan.spec.export, run.run_id, step.step_id)
                before = self._capture(spec, source=run.current_binding)
                record = record.model_copy(update={"stage_data": {"export_stage": stage.as_dict(), "before_export": before}})
                run = self._step_update(run, record)
            context["export_stage"] = record.stage_data["export_stage"]
        effect = self.service.recipe_resolve_stage_effect(plan, run, step, context)
        effect = StageEffect.model_validate(effect)
        arguments, source = effect.arguments, effect.source_binding
        grant = self.store.read_grant(run.authorization_id)
        validate_step_authorization(self.store, grant, plan, run, step, source=source, arguments=arguments,
                                    measured_effect=measured, stage_effect=effect)
        attempt_id, request_id = str(uuid.uuid4()), str(uuid.uuid4())
        usage = run.budgets_used.model_dump()
        usage["bridge_requests"] += 8
        usage["written_keys"] += len(arguments.get("writes", []))
        usage["generated_keys"] += int((measured or {}).get("added_keys", 0))
        usage["correction_passes"] += int(step.stage == "correction")
        usage = BudgetUsage.model_validate(usage)
        validate_usage(plan, usage, run.deadline)
        record = record.model_copy(update={"state": "preparing", "attempt_id": attempt_id, "request_id": request_id,
                                           "source_binding": source, "calls_used": record.calls_used + 1,
                                           "dispatch_lease_epoch": run.lease_epoch,
                                           "request_digest": digest(arguments), "stage_effect": effect})
        run = self._step_update(run, record, budgets_used=usage.model_dump(mode="json"),
                                current_binding=None if source is None else source.model_dump(mode="json"))
        execution = {"run_id": run.run_id, "step_id": step.step_id, "attempt_id": attempt_id,
                     "lease_epoch": run.lease_epoch, "request_id": request_id}
        if step.stage == "export_stage":
            from .export_workflow import ExportStage, bind_export_stage
            bind_export_stage(ExportStage.from_dict(record.stage_data["export_stage"]), request_id=request_id,
                attempt_id=attempt_id, lease_epoch=run.lease_epoch, operation_name=step.operation_name,
                arguments=arguments, source_binding=source)
        # Durable intent precedes snapshot/evaluation effects in prepare_change.
        if step.stage == "initial_checkpoint":
            bootstrap = self.store.issue_bootstrap(plan, run, step, effect, attempt_id=attempt_id, request_id=request_id)
            record = record.model_copy(update={"bootstrap_grant": bootstrap})
            run = self._step_update(run, record)
            prepared = self.service.prepare_initial_checkpoint(bootstrap, execution)
        else:
            prepared = self.service.prepare_change(step.feature_id, step.operation_name, arguments,
                                              min(plan.spec.budgets.per_step_seconds, grant.expires_at - time.time()),
                                              source_binding=source, execution_context=execution)
        if not prepared.get("confirmation_token"):
            return self._persist_result(self.store.read(run.run_id), record, prepared, step_state="blocked",
                                        state="blocked", blocked_reason="PREPARATION_BLOCKED")
        record = record.model_copy(update={"state": "prepared", "token_ref": prepared["confirmation_token"]})
        return self._step_update(self.store.read(run.run_id), record)

    def _measured_effect(self, run, plan, arguments, baseline_prefix="baseline_capture"):
        baseline = self._latest(run, baseline_prefix)
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
        host_result = _json(self.service.commit_initial_checkpoint(record.bootstrap_grant, record.token_ref,
                           timeout=plan.spec.budgets.per_step_seconds) if record.bootstrap_grant is not None
                           else self.service.commit_change(record.token_ref, timeout=plan.spec.budgets.per_step_seconds))
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
                repeatable_evidence = (record.stage_effect is not None and record.stage_effect.operation_name
                                       in {"safety.bootstrap", "safety.checkpoint", "io.export_fbx"})
                recoverable_observation = repeatable_evidence and (host_result is None or (
                    host_result.get("outcome") == "outcome_unknown" and host_result.get("error_code") != "POSTCONDITION_FAILED"))
                if not recoverable_observation and (host_result is None or not host_result.get("ok")):
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
        receipt_ref = next((item for item in record.artifact_refs if item.path == record.receipt_ref), None)
        if receipt_ref is None or record.stage_effect is None:
            raise RecipeConflict("NATIVE_EVIDENCE_MISSING")
        receipt = self.store.read_artifact(run.run_id, receipt_ref)
        effect = record.stage_effect
        transition = {}
        if step.stage in {"initial_checkpoint", "checkpoint"}:
            observation = self.service.recipe_checkpoint_observation(receipt, effect)
            binding = observation.source_after
            value = observation.model_dump(mode="json")
            ref = self.store.artifact(run.run_id, "successor_checkpoint", value)
            run = self._step_update(run, record, artifacts=[item.model_dump(mode="json") for item in (*run.artifacts, ref)])
            record = record.model_copy(update={"checkpoint_ref": ref.path, "checkpoint_observation": observation})
        elif step.stage == "export_stage":
            from .export_workflow import ExportStage, seal_export
            stage = ExportStage.from_dict(record.stage_data["export_stage"])
            artifact = seal_export(stage, receipt, plan.spec.budgets)
            value = {"artifact": artifact.model_dump(mode="json"), "export_stage": stage.as_dict(),
                     "before_export": record.stage_data["before_export"]}
            binding = effect.source_binding
            transition["export"] = "staged"
        else:
            binding = self.service.recipe_successor_source(effect, receipt)
            value = {"source_binding": binding.model_dump(mode="json"), "receipt_digest": digest(receipt)}
        if plan.spec.character.derived_target is not None and plan.spec.character.derived_target.producer_step_id == step.step_id:
            mapping = self.service.recipe_resolve_derived_target(plan.spec.character.derived_target, receipt)
            transition["derived_targets"] = [item.model_dump(mode="json") for item in (*run.derived_targets, mapping)]
            binding = mapping.source_binding
        used = run.budgets_used.model_dump()
        native_files = set()
        for prior in (*run.steps, record):
            if prior.stage_effect is not None:
                native_files.update(prior.stage_effect.output_paths)
        retained = sum(Path(path).stat().st_size for path in native_files if Path(path).is_file())
        retained += sum(path.stat().st_size for path in (self.store.run_dir(run.run_id) / "artifacts").glob("*.json"))
        used["disk_bytes"] = max(used["disk_bytes"], retained)
        if step.stage == "export_stage":
            used["output_bytes"] = max(used["output_bytes"], artifact.bytes)
        usage = BudgetUsage.model_validate(used)
        # Receipt/copy recovery is observation and remains possible after expiry;
        # resource caps still apply before a later effect can be dispatched.
        for name in ("disk_bytes", "output_bytes"):
            if getattr(usage, name) > getattr(plan.spec.budgets, name):
                raise RecipeConflict(f"RESOURCE_BUDGET_EXCEEDED: {name}")
        transition["budgets_used"] = usage.model_dump(mode="json")
        record = record.model_copy(update={"expected_successor": binding, "verification_status": "pass"})
        return self._persist_result(run, record, value, current_binding=binding.model_dump(mode="json"), **transition)

    def _export_host_step(self, run, record, step, plan):
        plan = plan.model_copy(update={"spec": self.effective_spec(plan.spec, run)})
        from .export_models import ArtifactRef as ExportArtifact, PublishPermit, ValidationBundle
        from .export_publisher import publish_verified, reconcile_publish
        from .export_workflow import validate_export
        from .target_capture import make_export_expectation, roundtrip_quality_context
        exported = self._latest(run, "export_stage")
        artifact = ExportArtifact.model_validate(exported["artifact"])
        if step.stage == "export_validate":
            # Persisted captures preserve both original intent and the actual
            # pre-export state. Reconstructing this host context is safe to repeat.
            before = _batch(exported["before_export"]["global"])
            original = _batch(self._latest(run, "baseline_capture")["global"])
            rig = self._profile(plan.spec)
            expected = make_export_expectation(before, plan.spec.export, rig,
                original_reference=original, intent=plan.spec.intent, policy=plan.spec.quality,
                reference_digests={"supports": digest(plan.spec.references.support_tracks),
                                   "geometry": digest(plan.spec.references.geometry), "props": digest(plan.spec.references.prop_tracks)})
            context = roundtrip_quality_context(before, original, rig, plan.spec.intent, plan.spec.quality,
                                               supports=self._supports(plan.spec))
            result = validate_export(artifact, plan.spec.export, expected, quality_context=context,
                                     provenance_key=self.store._secret, timeout=plan.spec.budgets.per_step_seconds,
                                     cancel=lambda: self.store.read(run.run_id).cancel_requested)
            if result.get("export") != "validated" or result.get("quality") != "pass":
                return self._persist_result(run, record, result, state="blocked", blocked_reason="EXPORT_VALIDATION_FAILED")
            return self._persist_result(run, record, result, export="validated")
        if record.stage_data is None:
            grant = self.store.read_grant(run.authorization_id)
            permit = PublishPermit(destination=plan.spec.export.destination, authorization_digest=digest(grant),
                artifact_sha256=artifact.sha256, profile_digest=digest(plan.spec.export),
                expires_at=min(grant.expires_at, run.deadline), run_id=run.run_id, step_id=step.step_id,
                overwrite_mode=plan.spec.export.overwrite_mode, overwrite_semantics=plan.spec.export.overwrite_semantics)
            journal = Path(exported["export_stage"]["directory"])
            key = digest({"run_id": run.run_id, "step_id": step.step_id, "authorization_digest": digest(grant)})[:32]
            record = record.model_copy(update={"stage_data": {"permit": permit.model_dump(mode="json"),
                "intent_path": str(journal / f"publish-{key}.intent.json"), "journal": str(journal)}})
            run = self._step_update(run, record)
        data = record.stage_data
        permit = PublishPermit.model_validate(data["permit"])
        if Path(data["intent_path"]).exists():
            result = reconcile_publish(data["intent_path"], expected_permit=permit)
        else:
            validate_usage(plan, run.budgets_used, run.deadline)
            self.store.verify_grant(self.store.read_grant(run.authorization_id), plan)
            if run.cancel_requested:
                return self._step_update(run, record.model_copy(update={"state": "canceled"}), state="canceled")
            validation = self._latest(run, "export_validate")
            result = publish_verified(artifact, ValidationBundle.model_validate(validation["validation_bundle"]), permit,
                                      journal_directory=data["journal"])
        if result.get("status") != "published":
            return self._persist_result(run, record, result, step_state="blocked", state="blocked", blocked_reason="PUBLISH_OUTCOME_UNKNOWN")
        return self._persist_result(run, record, result, export="published")
