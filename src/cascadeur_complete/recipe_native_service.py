"""Finite recipe lowering and authenticated native observations.

Declarations are compiled here, never forwarded as arbitrary operation payloads.
Native capability claims come only from the live bridge and its observation ledger.
"""
from __future__ import annotations

import time
from pathlib import Path

from .models import Operation, SourceBinding
from .recipe_models import digest
from .recipe_store import RecipeConflict, file_sha256
from .stage_contracts import BootstrapGrant, CheckpointObservation, DerivedTargetMapping, FileManifest, StageEffect


class RecipeNativeServiceMixin:
    def recipe_preflight(self, spec, steps, *, mode="initial", current_binding=None, predecessor_receipt=None):
        status = self._checked_status(self.refresh_live())
        if not status.ok:
            return [{"code": "RUNTIME_UNAVAILABLE", "detail": status.error_message}]
        live, reasons = status.result, []
        capabilities = live.get("guarded_capabilities", {})
        if live.get("protocol_version") != "3.0":
            reasons.append({"code": "PROTOCOL_MISMATCH"})
        if not capabilities.get("source_binding") or not capabilities.get("identity_verified"):
            reasons.append({"code": "BINDING_UNAVAILABLE"})
        source = current_binding if mode == "continuation" else spec.input.source_binding
        if mode == "continuation" and (source is None or predecessor_receipt is None):
            reasons.append({"code": "CONTINUATION_EVIDENCE_MISSING"})
        if source is not None:
            source = SourceBinding.model_validate(source)
            checked = self.validate_source(source)
            if (not checked.ok or not source.complete or source.binding.scene_instance_id != live.get("scene_id")
                    or source.binding.runtime_epoch != live.get("runtime_epoch")):
                reasons.append({"code": "SCENE_CHANGED", "detail": checked.error_message})
            if mode == "initial" and spec.input.kind == "active_scene" and source.binding != spec.input.binding:
                reasons.append({"code": "INITIAL_SOURCE_MISMATCH"})
            if spec.character.derived_target is None:
                profile, ownership = source.scope.get("profile", {}), source.scope.get("ownership", {})
                if (digest(profile) != spec.character.rig_profile_digest
                        or profile.get("character_id") != spec.character.character_id
                        or profile.get("role_ids") != spec.character.role_ids
                        or any(ownership.get(key) != spec.character.character_id for key in spec.character.object_ids)
                        or not set(spec.character.layer_ids) <= set(source.scope.get("layer_ids", []))):
                    reasons.append({"code": "RIG_MAPPING_AMBIGUOUS"})
        elif spec.input.kind == "active_scene":
            reasons.append({"code": "SOURCE_BINDING_REQUIRED"})
        verified = set(capabilities.get("operations", []))
        for step in steps:
            if (step.effect in {"evaluation", "scene_mutation", "file_stage"} and not step.not_required_reason
                    and step.operation_name not in verified):
                reasons.append({"code": "NATIVE_ADAPTER_UNVERIFIED", "step_id": step.step_id, "operation": step.operation_name})
        if spec.character.derived_target is not None and not capabilities.get("derived_target_observation"):
            reasons.append({"code": "DERIVED_TARGET_ADAPTER_UNVERIFIED"})
        if spec.input.kind != "active_scene" and not capabilities.get("file_bootstrap"):
            reasons.append({"code": "FILE_BOOTSTRAP_READER_UNVERIFIED"})
        if spec.rig.mode == "explicit_mapping":
            reasons.append({"code": "EXPLICIT_RIG_CREATION_ADAPTER_UNVERIFIED"})
        if spec.motion.mode == "keyposes" and any(item.rotation_euler_xyz_radians is not None for item in spec.motion.keyposes):
            reasons.append({"code": "ROTATION_CONVENTION_UNVERIFIED", "detail": "Keyposes require observed native Euler encoding"})
        if spec.motion.mode == "retarget" and spec.motion.route == "host" and not capabilities.get("retarget_inputs"):
            reasons.append({"code": "RETARGET_TARGET_OBSERVATION_UNAVAILABLE"})
        if any(item.kind == "foot_contacts" for item in spec.cleanup) and not capabilities.get("key_layout_observation"):
            reasons.append({"code": "INTERPOLATION_MODEL_UNVERIFIED"})
        if spec.intent.allow_key_insertion and not capabilities.get("key_topology_write"):
            reasons.append({"code": "KEY_TOPOLOGY_ADAPTER_UNAVAILABLE"})
        return reasons

    def recipe_rebind_source(self, source, operation_name, arguments, **_context):
        result = self.client.execute("capture_source", [Operation(name="system.rebind_source", arguments={
            "source_binding": source.model_dump(mode="json"), "operation_name": operation_name,
            "operation_arguments": arguments})])
        if not result.ok:
            raise RecipeConflict("SOURCE_REATTESTATION_FAILED: " + str(result.error_message))
        binding = SourceBinding.model_validate(result.result)
        checked = self.validate_source(binding, operation_name=operation_name, arguments=arguments)
        if not binding.complete or not checked.ok or binding.scope.get("operation_arguments_digest") != digest(arguments):
            raise RecipeConflict("SOURCE_REATTESTATION_FAILED")
        return binding

    def observe_key_layout(self, request):
        from .motion_key_layout import KeyLayoutObservation
        result = self.client.execute("transform_get", [Operation(name="system.observe_key_layout", arguments=request)])
        if not result.ok:
            raise RecipeConflict("KEY_LAYOUT_UNVERIFIED: " + str(result.error_message))
        KeyLayoutObservation.model_validate(result.result)
        return result

    def verify_key_layout(self, observation, observation_digest):
        value = observation.as_dict() if hasattr(observation, "as_dict") else observation.model_dump(mode="json") if hasattr(observation, "model_dump") else observation
        return self.client.execute("transform_get", [Operation(name="system.verify_observation", arguments={
            "observation": value, "digest": observation_digest, "kind": "key_layout"})])

    def recipe_verify_capture(self, capture, capture_digest):
        return self.client.execute("transform_get", [Operation(name="system.verify_observation", arguments={
            "observation": capture.as_dict(), "digest": capture_digest, "kind": "motion_capture"})])

    def observe_retarget_inputs(self, request):
        return self.client.execute("transform_get", [Operation(name="system.observe_retarget_inputs", arguments=request)])

    def verify_retarget_inputs(self, observation, observation_digest):
        return self.client.execute("transform_get", [Operation(name="system.verify_observation", arguments={
            "observation": observation, "digest": observation_digest, "kind": "retarget_inputs"})])

    def verify_controller_targets(self, request, request_digest):
        return self.client.execute("transform_get", [Operation(name="system.verify_observation", arguments={
            "observation": request, "digest": request_digest, "kind": "controller_targets"})])

    def recipe_resolve_stage_effect(self, plan, run, step, context):
        spec, stage = plan.spec, step.stage
        mapping = next((item for item in run.derived_targets if step.target.derived_ref is not None
                        and item.reference_digest == digest(step.target.derived_ref)), None)
        if mapping is not None:
            spec = self.recipes.effective_spec(spec, run)
        source = context.get("source_binding", run.current_binding)
        source = None if source is None else SourceBinding.model_validate(source)
        inputs, outputs, successor = [], [], "same_instance"
        if stage == "initial_checkpoint":
            directory = self.recipes.store.run_dir(run.run_id) / "workspace"
            directory.mkdir(parents=True, exist_ok=True)
            backup, working = directory / "initial.casc", directory / "working.casc"
            args = {"checkpoint_path": str(backup), "working_path": str(working), "input_kind": spec.input.kind,
                    "input_mode": spec.input.mode}
            if spec.input.path is not None:
                sha, length = file_sha256(Path(spec.input.path))
                if sha != spec.input.sha256:
                    raise RecipeConflict("INPUT_DIGEST_MISMATCH")
                inputs.append(FileManifest(path=spec.input.path, sha256=sha, length=length))
                args["input_path"] = spec.input.path
                args["input_sha256"] = sha
            source = spec.input.source_binding
            outputs, successor = [str(backup), str(working)], "working_clone"
        elif stage == "checkpoint":
            manifest = {} if source is None else source.scope.get("snapshot_manifest", {})
            if not manifest.get("working_path"):
                raise RecipeConflict("CHECKPOINT_UNAVAILABLE")
            directory = self.recipes.store.run_dir(run.run_id) / "checkpoints"
            directory.mkdir(parents=True, exist_ok=True)
            path, working = str(directory / f"{step.step_id}-backup.casc"), str(directory / f"{step.step_id}-working.casc")
            args = {"checkpoint_path": path, "working_path": working}
            outputs, successor = [path, working], "working_clone"
        elif stage == "evaluation":
            args = dict(step.fixed_parameters)
        elif stage == "rig":
            if spec.rig.mode == "template":
                args = {"path": spec.rig.template.path}
                inputs.append(FileManifest(path=spec.rig.template.path, sha256=spec.rig.template.sha256, length=spec.rig.template.length))
            elif spec.rig.mode == "explicit_mapping":
                # quick_rig consumes a template file, not a caller-created role map.
                raise RecipeConflict("EXPLICIT_RIG_CREATION_ADAPTER_UNVERIFIED")
            else:
                raise RecipeConflict("EXISTING_RIG_IS_READ_ONLY")
        elif stage == "motion":
            motion = spec.motion
            if motion.mode == "native_unbaking":
                args = {"step": motion.unbaking_step}
            elif motion.mode in {"native_root_motion", "native_inbetweening"}:
                if motion.settings:
                    raise RecipeConflict("NATIVE_GENERATION_SETTINGS_UNSUPPORTED")
                args = {}
            elif motion.mode == "retarget" and motion.route == "native":
                required = {"source_point_id", "target_point_id"}
                if set(motion.mapping) != required:
                    raise RecipeConflict("RETARGET_REQUIRES_EXACT_POINT_MAPPING")
                args = {**motion.mapping, "first_frame": spec.clip.first_frame, "last_frame": spec.clip.last_frame}
            elif motion.mode == "external_motion_asset":
                args = {"path": motion.source.path, "mode": "merge"}
                inputs.append(FileManifest(path=motion.source.path, sha256=motion.source.sha256, length=motion.source.length))
            elif motion.mode == "keyposes":
                if any(item.rotation_euler_xyz_radians is not None for item in motion.keyposes):
                    raise RecipeConflict("ROTATION_CONVENTION_UNVERIFIED")
                args = {"writes": [item.model_dump(mode="json", exclude_none=True) for item in motion.keyposes], "space": "global"}
            elif motion.mode == "retarget" and motion.route == "host":
                args = context["candidate"]["arguments"]
            else:
                raise RecipeConflict("MOTION_STAGE_UNSUPPORTED")
        elif stage == "correction":
            args = context["candidate"]["arguments"]
        elif stage == "export_stage":
            export = context["export_stage"]
            # This strict profile is consumed only by a registered export adapter;
            # it must observe actual native settings/closure before dispatch.
            args = {"path": export["raw_path"], "export_profile": spec.export.model_dump(mode="json"),
                    "export_profile_digest": digest(spec.export)}
            outputs = [export["raw_path"], export["sealed_path"]]
        else:
            raise RecipeConflict("STAGE_LOWERING_UNSUPPORTED")
        args = self._bound_arguments(step.feature_id, args)
        if stage != "initial_checkpoint" or source is not None:
            if source is None:
                raise RecipeConflict("BINDING_UNAVAILABLE")
            source = self.recipe_rebind_source(source, step.operation_name, args, plan=plan, run=run, step=step)
        ids = step.target.object_ids if mapping is None else tuple(mapping.role_ids[key] for key in step.target.object_ids) if step.target.object_ids else mapping.object_ids
        layers = step.target.layer_ids if mapping is None else mapping.layer_ids
        return StageEffect(step_id=step.step_id, declaration_digest=step.fixed_parameters_digest,
            lowering_rule_id=step.lowering_rule_id, lowering_rule_digest=step.lowering_rule_digest,
            feature_id=step.feature_id, operation_name=step.operation_name,
            effect_class="mixed" if stage in {"checkpoint", "initial_checkpoint"} else "file" if stage == "export_stage" else "evaluation" if stage == "evaluation" else "scene",
            arguments=args, arguments_digest=digest(args), operation_digest=digest([{"name": step.operation_name, "arguments": args}]),
            effect_bounds_digest=digest(step.max_effect_from_baseline),
            source_binding=source, input_files=tuple(inputs), output_paths=tuple(outputs), target_object_ids=ids,
            target_layer_ids=layers, derived_mapping_digest=None if mapping is None else digest(mapping), expected_successor=successor)

    def prepare_initial_checkpoint(self, grant, execution_context):
        grant = self.recipes.store.verify_bootstrap(grant)
        run = self.recipes.store.read(grant.run_id)
        step = next(item for item in run.steps if item.step_id == grant.step_id)
        effect = step.stage_effect
        expected = {"run_id": grant.run_id, "step_id": grant.step_id, "attempt_id": grant.attempt_id,
                    "lease_epoch": grant.lease_epoch, "request_id": grant.request_id}
        if execution_context != expected or effect is None or effect.operation_name != "safety.bootstrap":
            raise RecipeConflict("BOOTSTRAP_EXECUTION_CONTEXT_MISMATCH")
        if grant.source_binding is None:
            # File bootstrap needs a runtime-issued file reader identity. It may
            # not invent a SceneBinding from a pathname.
            raise RecipeConflict("FILE_BOOTSTRAP_READER_UNVERIFIED")
        checked = self.validate_source(grant.source_binding, operation_name=effect.operation_name, arguments=effect.arguments)
        if not checked.ok:
            raise RecipeConflict("BOOTSTRAP_SOURCE_CHANGED")
        source = grant.source_binding
        record = self.changes.prepare(feature_id=effect.feature_id, scene_id=source.binding.scene_instance_id,
            scene_revision=None, selection_fingerprint=source.binding.selection_digest,
            operation=Operation(name=effect.operation_name, arguments=effect.arguments),
            impact={"bootstrap_grant_id": grant.grant_id, "bootstrap_grant": grant.model_dump(mode="json")},
            backup_path=None, ttl=min(300, grant.expires_at - time.time()), source_binding=source,
            execution_context=execution_context, mutation_request_id=grant.request_id)
        return {"ok": True, "confirmation_token": record.token, "operation": record.operation.model_dump(mode="json")}

    def recipe_successor_source(self, effect, receipt):
        native = (receipt.get("terminal_result") or {}).get("result") or {}
        source = SourceBinding.model_validate(native.get("source_binding"))
        if not source.complete or source.binding.model_dump(mode="json") != receipt.get("scene_after"):
            raise RecipeConflict("SUCCESSOR_BINDING_UNVERIFIED")
        if effect.source_binding is not None and effect.expected_successor == "same_instance":
            before = effect.source_binding.binding
            if (before.scene_instance_id != source.binding.scene_instance_id
                    or before.document_lineage_id != source.binding.document_lineage_id):
                raise RecipeConflict("SUCCESSOR_LINEAGE_MISMATCH")
        if not self.validate_source(source).ok:
            raise RecipeConflict("SUCCESSOR_BINDING_UNVERIFIED")
        return source

    def recipe_checkpoint_observation(self, receipt, effect):
        native = (receipt.get("terminal_result") or {}).get("result") or {}
        value = dict(native.get("checkpoint_observation") or {})
        value.update({key: receipt.get(key) for key in ("request_id", "run_id", "step_id", "attempt_id", "lease_epoch", "operation_digest")})
        value["receipt_digest"] = digest(receipt)
        observation = CheckpointObservation.model_validate(value)
        if (receipt.get("phase") != "terminal" or receipt.get("outcome") != "succeeded"
                or observation.operation_digest != effect.operation_digest or observation.source_before != effect.source_binding
                or observation.source_after.binding.model_dump(mode="json") != receipt.get("scene_after")):
            raise RecipeConflict("CHECKPOINT_RECEIPT_MISMATCH")
        for manifest in (observation.checkpoint, observation.working_file):
            sha, length = file_sha256(Path(manifest.path))
            if sha != manifest.sha256 or length != manifest.length:
                raise RecipeConflict("CHECKPOINT_BYTES_CHANGED")
        if observation.checkpoint.path not in effect.output_paths:
            raise RecipeConflict("CHECKPOINT_PATH_MISMATCH")
        if not self.validate_source(observation.source_after).ok:
            raise RecipeConflict("SUCCESSOR_BINDING_UNVERIFIED")
        return observation

    def recipe_resolve_derived_target(self, reference, receipt):
        result = self.client.execute("capture_source", [Operation(name="system.resolve_derived_target", arguments={
            "reference": reference.model_dump(mode="json"), "producer_request_id": receipt["request_id"],
            "producer_receipt_digest": digest(receipt)})])
        if not result.ok:
            raise RecipeConflict("DERIVED_TARGET_UNVERIFIED: " + str(result.error_message))
        mapping = DerivedTargetMapping.model_validate(result.result)
        if (mapping.reference_digest != digest(reference) or mapping.producer_request_id != receipt["request_id"]
                or mapping.producer_receipt_digest != digest(receipt) or set(mapping.role_ids) != set(reference.role_paths)
                or not self.validate_source(mapping.source_binding).ok):
            raise RecipeConflict("DERIVED_TARGET_EVIDENCE_MISMATCH")
        return mapping
