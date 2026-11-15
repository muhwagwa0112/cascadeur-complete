"""Finite recipe lowering and authenticated native observations.

Declarations are compiled here, never forwarded as arbitrary operation payloads.
Native capability claims come only from the live bridge and its observation ledger.
"""
from __future__ import annotations

import math
import time
from pathlib import Path

from .models import Operation, SourceBinding
from .recipe_models import digest
from .recipe_store import RecipeConflict, file_sha256
from .stage_contracts import BootstrapGrant, CheckpointObservation, DerivedTargetMapping, FileManifest, RecipeTargetObservation, StageEffect


def _file_bootstrap_supported(capabilities, kind, mode):
    """A live typed capability names the exact observed loader and scene policy."""
    capability = capabilities.get("file_bootstrap")
    return (kind == "casc_file" and mode == "new_working_scene" and isinstance(capability, dict)
            and isinstance(capability.get("kinds"), list) and kind in capability["kinds"]
            and isinstance(capability.get("modes"), list) and mode in capability["modes"])


def _bootstrap_file_arguments(input_spec, manifest):
    return {"input_kind": input_spec.kind, "input_mode": input_spec.mode,
            "input_path": manifest.path, "input_sha256": manifest.sha256, "input_length": manifest.length}


def _assert_file_source(source, manifest, arguments):
    if (source is None or not source.complete or source.scope.get("operation_name") != "safety.bootstrap"
            or source.scope.get("operation_arguments_digest") != digest(arguments)
            or source.scope.get("input_files") != [manifest.model_dump(mode="json")]):
        raise RecipeConflict("FILE_BOOTSTRAP_SOURCE_UNVERIFIED: exact current scene and input manifest are required")


def _assert_export_source(source, spec):
    """Distinguish the authenticated export scope's profile from a rig profile."""
    from .export_models import ExportProfile
    scope = source.scope
    if (scope.get('adapter_id') != 'native-selected-export-v1'
            or scope.get('operation_name') != 'io.export_fbx' or spec.export is None):
        raise RecipeConflict('EXPORT_SOURCE_UNVERIFIED: exact native export adapter and recipe export required')
    profile = ExportProfile.model_validate(scope.get('profile'))
    arguments = scope.get('operation_arguments')
    if (not isinstance(arguments, dict)
            or set(arguments) != {'path','export_profile','export_profile_digest','max_output_bytes'}
            or scope.get('operation_arguments_digest') != digest(arguments)
            or digest(scope['profile']) != digest(profile) or digest(profile) != digest(spec.export)
            or arguments['export_profile_digest'] != digest(profile)
            or digest(arguments['export_profile']) != digest(profile)):
        raise RecipeConflict('EXPORT_SOURCE_UNVERIFIED: exact export profile and arguments differ from recipe')
    mapped = sorted(item.source_id for item in profile.skeleton_map)
    selection = scope.get('export_selection_before')
    if (scope.get('export_selection_policy') != 'temporary_empty_selection_observed_restore'
            or not isinstance(selection, dict)
            or set(selection) != {'ids', 'ordered_ids', 'pivot_position_native', 'pivot_rotation_wxyz', 'pivot_identity_status'}
            or selection['ids'] != [] or selection['ordered_ids'] != []
            or selection['pivot_identity_status'] != 'unobserved'):
        raise RecipeConflict('EXPORT_SOURCE_UNVERIFIED: observed empty-selection restore contract required')
    for key, size in (('pivot_position_native', 3), ('pivot_rotation_wxyz', 4)):
        values = selection[key]
        if (not isinstance(values, list) or len(values) != size
                or any(type(value) not in (int, float) or not math.isfinite(value) for value in values)):
            raise RecipeConflict('EXPORT_SOURCE_UNVERIFIED: finite observed selection pivot required')
    path = Path(arguments['path'])
    if (len(mapped) != 1 or mapped != sorted(spec.character.object_ids)
            or scope.get('object_ids') != mapped or scope.get('export_selected_ids') != mapped
            or not set(spec.character.layer_ids) <= set(scope.get('layer_ids', []))
            or profile.first_frame != 0 or scope.get('frames') != [0, profile.last_frame]
            or not path.is_absolute() or path.name != 'raw.fbx'
            or type(arguments['max_output_bytes']) is not int
            or not 0 < arguments['max_output_bytes'] <= 2 * 1024**3
            or arguments['max_output_bytes'] != min(spec.budgets.output_bytes, spec.budgets.disk_bytes, 2 * 1024**3)):
        raise RecipeConflict('EXPORT_SOURCE_UNVERIFIED: selected export closure, range or output differs')


class RecipeNativeServiceMixin:
    def recipe_observe_target(self, spec, source):
        """Authenticate exact target ownership without rewriting source scope.

        Role choices, constraints and physical context remain declarations. The
        private native observer verifies supported structural facts and refuses
        unsupported supplied metadata; a caller's observation or flag cannot
        replace its process-local verification record.
        """
        import numpy as np
        from .capture import enforce_motion_budget, estimate_motion_resources
        from .motion_context import MotionContext

        source = SourceBinding.model_validate(source)
        count = spec.clip.last_frame - spec.clip.first_frame + 1
        estimate = estimate_motion_resources(count, {key: count for key in spec.character.object_ids},
            retained_capture_bytes=count * len(spec.character.object_ids) * 2048)
        enforce_motion_budget(estimate, {"max_memory_bytes": spec.budgets.memory_bytes})
        frames = np.arange(spec.clip.first_frame, spec.clip.last_frame + 1, dtype=np.int64)
        context = MotionContext(frames, spec.clip.time_origin_s + (frames - frames[0]) * spec.clip.fps_den / spec.clip.fps_num,
            "explicit" if spec.clip.time_origin_s != 0 else "fps", spec.clip.fps_num, spec.clip.fps_den,
            spec.clip.metres_per_scene_unit, np.asarray(spec.clip.scene_to_solver_basis),
            {"recipe_clip_digest": digest(spec.clip)}).as_dict()
        character = spec.character.model_dump(mode="json", include={
            "character_id", "root_id", "object_ids", "layer_ids", "role_ids", "rig_profile", "rig_profile_digest",
            "required_mesh_ids", "optional_mesh_ids"})
        request = {"source_binding": source.model_dump(mode="json"), "character": character, "context": context}
        result = self.client.execute("motion_inputs", [Operation(name="system.observe_recipe_target", arguments=request)])
        if not result.ok:
            raise RecipeConflict("RECIPE_TARGET_OBSERVATION_UNAVAILABLE: " + str(result.error_message))
        observation = RecipeTargetObservation.model_validate(result.result)
        expected = {"request_digest": digest(request), "source_binding_digest": digest(request["source_binding"]),
            "profile_digest": character["rig_profile_digest"], "target_digest": digest(character),
            "context_digest": digest(context), "runtime_epoch": source.binding.runtime_epoch,
            "adapter_fingerprint": source.adapter_fingerprint}
        if (any(getattr(observation, key) != value for key, value in expected.items())
                or digest(character["rig_profile"]) != observation.profile_digest
                or set(observation.object_ids) != set(character["object_ids"])
                or set(observation.layer_ids) != set(character["layer_ids"])
                or not set(observation.object_ids) <= set(source.scope.get("object_ids", []))
                or any(owner != character["character_id"] for owner in observation.ownership.values())):
            raise RecipeConflict("RECIPE_TARGET_OBSERVATION_MISMATCH")
        value = observation.model_dump(mode="json")
        observation_digest = digest(value)
        verified = self.client.execute("motion_inputs", [Operation(name="system.verify_observation", arguments={
            "kind": "recipe_target", "observation": value, "digest": observation_digest})])
        if (not verified.ok or not isinstance(verified.result, dict)
                or verified.result.get("observation_digest") != observation_digest
                or verified.result.get("request_digest") != expected["request_digest"]):
            raise RecipeConflict("RECIPE_TARGET_PROVENANCE_UNVERIFIED")
        return observation

    def recipe_bind_input(self, spec):
        """Bind a file plan to a real current scene and runtime-read file bytes.

        Capability absence remains an ordinary displayed preflight blocker. A
        claimed capability cannot replace a successful capture/validation call.
        """
        if spec.input.kind == "active_scene":
            return spec
        status = self._checked_status(self.refresh_live())
        if not status.ok or not _file_bootstrap_supported(status.result.get("guarded_capabilities", {}), spec.input.kind, spec.input.mode):
            return spec
        path = Path(spec.input.path).resolve()
        if path.suffix.lower() != ".casc":
            return spec
        if path.stat().st_size > spec.budgets.disk_bytes:
            raise RecipeConflict("RESOURCE_BUDGET_EXCEEDED: bootstrap input bytes")
        sha, length = file_sha256(path)
        if sha != spec.input.sha256 or length > spec.budgets.disk_bytes:
            raise RecipeConflict("INPUT_DIGEST_MISMATCH_OR_BUDGET_EXCEEDED")
        manifest = FileManifest(path=str(path), sha256=sha, length=length)
        if spec.input.source_binding is not None and not self.validate_source(spec.input.source_binding).ok:
            raise RecipeConflict("INITIAL_SOURCE_CHANGED")
        arguments = _bootstrap_file_arguments(spec.input, manifest)
        source = self.capture_source({"operation_name": "safety.bootstrap", "operation_arguments": arguments},
            digest({"input": manifest.model_dump(mode="json"), "input_mode": spec.input.mode}), None)
        source = SourceBinding.model_validate(source)
        _assert_file_source(source, manifest, arguments)
        checked = self.validate_source(source, operation_name="safety.bootstrap", arguments=arguments)
        if not checked.ok:
            raise RecipeConflict("FILE_BOOTSTRAP_SOURCE_UNVERIFIED: " + str(checked.error_message))
        prior = spec.input.binding
        if prior is not None and (prior.scene_instance_id != source.binding.scene_instance_id
                or prior.runtime_epoch != source.binding.runtime_epoch or prior.document_lineage_id != source.binding.document_lineage_id):
            raise RecipeConflict("INITIAL_SOURCE_CHANGED")
        value = spec.model_dump(mode="json")
        value["input"].update(path=manifest.path, binding=source.binding.model_dump(mode="json"),
                              source_binding=source.model_dump(mode="json"))
        return type(spec).model_validate(value)

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
            source_valid = (checked.ok and source.complete and source.binding.scene_instance_id == live.get("scene_id")
                            and source.binding.runtime_epoch == live.get("runtime_epoch"))
            if not source_valid:
                reasons.append({"code": "SCENE_CHANGED", "detail": checked.error_message})
            if mode == "initial" and source.binding != spec.input.binding:
                reasons.append({"code": "INITIAL_SOURCE_MISMATCH"})
            if spec.character.derived_target is None and (mode == "continuation" or spec.input.kind == "active_scene"):
                profile, ownership = source.scope.get("profile", {}), source.scope.get("ownership", {})
                export_scope = (source.scope.get('adapter_id') == 'native-selected-export-v1'
                                or source.scope.get('operation_name') == 'io.export_fbx')
                if export_scope:
                    if source_valid:
                        try:
                            _assert_export_source(source, spec)
                            # ExportProfile proves the requested artifact contract,
                            # not RigProfile rest/ownership. Reauthenticate those
                            # through the existing native target observer as well.
                            self.recipe_observe_target(spec, source)
                        except (ValueError, TypeError, KeyError, OSError) as exc:
                            reasons.append({'code':'EXPORT_SOURCE_UNVERIFIED', 'detail':str(exc)})
                elif profile or ownership:
                    if (digest(profile) != spec.character.rig_profile_digest
                        or profile.get("character_id") != spec.character.character_id
                        or profile.get("role_ids") != spec.character.role_ids
                        or any(ownership.get(key) != spec.character.character_id for key in spec.character.object_ids)
                        or not set(spec.character.layer_ids) <= set(source.scope.get("layer_ids", []))):
                        reasons.append({"code": "RIG_MAPPING_AMBIGUOUS",
                            "detail": "The authenticated source profile or ownership contradicts the declared exact target"})
                elif source_valid:
                    try:
                        self.recipe_observe_target(spec, source)
                    except (ValueError, TypeError, KeyError, OSError) as exc:
                        reasons.append({"code": "RIG_MAPPING_AMBIGUOUS", "detail": str(exc)})
        elif spec.input.kind == "active_scene":
            reasons.append({"code": "SOURCE_BINDING_REQUIRED"})
        verified = set(capabilities.get("operations", []))
        for step in steps:
            if (step.effect in {"evaluation", "scene_mutation", "file_stage"} and not step.not_required_reason
                    and step.operation_name not in verified):
                reasons.append({"code": "NATIVE_ADAPTER_UNVERIFIED", "step_id": step.step_id, "operation": step.operation_name})
        if spec.character.derived_target is not None and not capabilities.get("derived_target_observation"):
            reasons.append({"code": "DERIVED_TARGET_ADAPTER_UNVERIFIED"})
        if spec.input.kind != "active_scene":
            if not _file_bootstrap_supported(capabilities, spec.input.kind, spec.input.mode):
                reasons.append({"code": "FILE_BOOTSTRAP_READER_UNVERIFIED", "kind": spec.input.kind, "mode": spec.input.mode})
            elif mode == "initial":
                try:
                    path = Path(spec.input.path)
                    sha, length = file_sha256(path)
                    manifest = FileManifest(path=str(path), sha256=sha, length=length)
                    if path.suffix.lower() != ".casc" or sha != spec.input.sha256:
                        raise RecipeConflict("INPUT_DIGEST_MISMATCH_OR_FORMAT_UNSUPPORTED")
                    _assert_file_source(source, manifest, _bootstrap_file_arguments(spec.input, manifest))
                except (ValueError, OSError) as exc:
                    reasons.append({"code": "FILE_BOOTSTRAP_SOURCE_UNVERIFIED", "detail": str(exc)})
        if spec.rig.mode == "explicit_mapping":
            reasons.append({"code": "EXPLICIT_RIG_CREATION_ADAPTER_UNVERIFIED"})
        if spec.motion.mode == "keyposes" and any(item.rotation_euler_xyz_radians is not None for item in spec.motion.keyposes):
            reasons.append({"code": "ROTATION_CONVENTION_UNVERIFIED", "detail": "Keyposes require observed native Euler encoding"})
        if spec.motion.mode == "retarget" and spec.motion.route == "host":
            from .retarget_controller import ADAPTER_ID
            capability = capabilities.get("retarget_inputs")
            file_bootstrap = (spec.input.kind == "casc_file" and spec.input.mode == "new_working_scene")
            if (not isinstance(capability, dict) or capability.get("adapter_id") != ADAPTER_ID
                    or capability.get("channels") != ["position"] or capability.get("space") != "global"
                    or capability.get("existing_keys_only") is not True
                    or capability.get("private_target_observation_required") is not True
                    or (not file_bootstrap and (capability.get("target_scope") != "observed"
                        or capability.get("object_ids") != list(spec.character.object_ids)))):
                reasons.append({"code": "RETARGET_TARGET_OBSERVATION_UNAVAILABLE",
                    "detail": "Current target requires its privately qualified independent existing-position writer"})
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

    def observe_motion_capture(self, request):
        return self.client.execute("transform_get", [Operation(name="system.observe_motion_capture", arguments=request)])

    def verify_key_layout(self, observation, observation_digest):
        value = observation.as_dict() if hasattr(observation, "as_dict") else observation.model_dump(mode="json") if hasattr(observation, "model_dump") else observation
        return self.client.execute("transform_get", [Operation(name="system.verify_observation", arguments={
            "observation": value, "digest": observation_digest, "kind": "key_layout"})])

    def verify_key_insertion(self, request, request_digest):
        """Observe an exact native insertion prediction without authorizing a write."""
        from .capture import canonical_digest
        from .motion_key_layout import KeyAddition, LocatorInsertionEvidence
        if (not isinstance(request, dict) or set(request) != {"key_layout_digest", "additions"}
                or not isinstance(request["key_layout_digest"], str)
                or len(request["key_layout_digest"]) != 64
                or any(c not in "0123456789abcdef" for c in request["key_layout_digest"])
                or not isinstance(request["additions"], list) or not 1 <= len(request["additions"]) <= 8):
            raise RecipeConflict("INVALID_POLICY: exact observed key layout and one-to-eight additions required")
        additions = tuple(KeyAddition.model_validate(row) for row in request["additions"])
        identities = {(row.object_id, row.channel, row.layer_id) for row in additions}
        if (len(identities) != 1 or len({row.frame for row in additions}) != len(additions)
                or any(not row.object_id or not row.layer_id or row.channel != "position"
                       or row.mode not in {"LINEAR", "STEP"} or row.frame < 0 or len(row.value) != 3
                       for row in additions)):
            raise RecipeConflict("INVALID_POLICY: one exact position driver with unique finite LINEAR/STEP additions required")
        value = {"key_layout_digest": request["key_layout_digest"],
                 "additions": [row.model_dump(mode="json") for row in additions]}
        if canonical_digest(value) != request_digest or canonical_digest(request) != request_digest:
            raise RecipeConflict("KEY_INSERTION_ADAPTER_UNVERIFIED: request digest differs from exact typed additions")
        result = self.client.execute("transform_get", [Operation(name="system.verify_key_insertion", arguments={
            "request": value, "digest": request_digest})])
        if not result.ok:
            return result
        observed = result.result
        if not isinstance(observed, dict):
            raise RecipeConflict("KEY_INSERTION_ADAPTER_UNVERIFIED: missing native observation")
        proof = LocatorInsertionEvidence.model_validate(observed.get("locator_insertion"))
        if (observed.get("request_digest") != request_digest or proof.request_digest != request_digest
                or proof.key_layout_digest != value["key_layout_digest"]
                or observed.get("shared_layer_effects_observed") is not True
                or not isinstance(observed.get("adapter_evidence_ref"), str)
                or not observed["adapter_evidence_ref"]):
            raise RecipeConflict("KEY_INSERTION_ADAPTER_UNVERIFIED: native evidence belongs to a different request")
        return result

    def verify_key_topology(self, observation, observation_digest, adapter_evidence_ref):
        """Read actual completed topology evidence; parsing never grants mutation authority."""
        from .capture import canonical_digest
        from .motion_key_layout import KeyLayoutObservation, LocatorInsertionCompletion
        typed = KeyLayoutObservation.model_validate(observation)
        value = typed.model_dump(mode="json")
        if (not isinstance(adapter_evidence_ref, str) or not adapter_evidence_ref
                or canonical_digest(value) != observation_digest
                or canonical_digest(observation) != observation_digest):
            raise RecipeConflict("KEY_TOPOLOGY_READBACK_UNVERIFIED: exact observed topology digest and evidence reference required")
        result = self.client.execute("transform_get", [Operation(name="system.verify_key_topology", arguments={
            "observation": value, "digest": observation_digest, "adapter_evidence_ref": adapter_evidence_ref})])
        if not result.ok:
            return result
        observed = result.result
        if not isinstance(observed, dict):
            raise RecipeConflict("KEY_TOPOLOGY_READBACK_UNVERIFIED: missing native completion observation")
        completed = LocatorInsertionCompletion.model_validate(observed.get("locator_insertion_completion"))
        if (observed.get("key_layout_digest") != observation_digest
                or completed.key_layout_digest != observation_digest
                or completed.adapter_evidence_ref != adapter_evidence_ref
                or completed.completion_receipt_digest != observed.get("completion_receipt_digest")
                or typed.support_status != "supported" or typed.reason_codes):
            raise RecipeConflict("KEY_TOPOLOGY_READBACK_UNVERIFIED: native completion differs from the exact observed topology")
        return result

    def recipe_verify_capture(self, capture, capture_digest):
        return self.client.execute("transform_get", [Operation(name="system.verify_observation", arguments={
            "observation": capture.as_dict(), "digest": capture_digest, "kind": "motion_capture"})])

    def _retarget_context(self):
        import threading
        return self.__dict__.setdefault("_retarget_execution_local", threading.local())

    def observe_retarget_inputs(self, request):
        self._retarget_context().observation_digest = None
        result = self.client.execute("transform_get", [Operation(name="system.observe_retarget_inputs", arguments=request)])
        if result.ok:
            value = result.result
            expected = {"request_digest": digest(request), "source_binding_digest": digest(request["source_binding"]),
                "profile_digest": digest(request["profile"]), "context_digest": digest(request["context"]),
                "source_artifact_digest": request["source_artifact_digest"],
                "declaration_digest": digest(request["declaration"]), "intent_digest": digest(request["intent"]),
                "runtime_epoch": request["source_binding"]["binding"]["runtime_epoch"],
                "adapter_fingerprint": request["source_binding"]["adapter_fingerprint"]}
            if (not isinstance(value, dict) or value.get("schema_version") != 1 or value.get("kind") != "retarget_inputs"
                    or any(value.get(key) != expected_value for key, expected_value in expected.items())):
                raise RecipeConflict("RETARGET_TARGET_OBSERVATION_MISMATCH")
            import copy
            requests = getattr(self, "_retarget_requests", {})
            requests[digest(value)] = copy.deepcopy(request)
            while len(requests) > 16:
                requests.pop(next(iter(requests)))
            self._retarget_requests = requests
        return result

    def verify_retarget_inputs(self, observation, observation_digest):
        result = self.client.execute("transform_get", [Operation(name="system.verify_observation", arguments={
            "observation": observation, "digest": observation_digest, "kind": "retarget_inputs"})])
        request = getattr(self, "_retarget_requests", {}).get(observation_digest)
        if result.ok:
            if (request is None or digest(observation) != observation_digest
                    or not isinstance(result.result, dict)
                    or result.result.get("retarget_inputs_digest") != observation_digest
                    or result.result.get("request_digest") != digest(request)):
                raise RecipeConflict("RETARGET_TARGET_PROVENANCE_UNVERIFIED")
            import copy
            records = getattr(self, "_retarget_observations", {})
            records[observation_digest] = copy.deepcopy(observation)
            while len(records) > 16:
                records.pop(next(iter(records)))
            self._retarget_observations = records
            self._retarget_context().observation_digest = observation_digest
        return result

    @property
    def motion_controller_adapter(self):
        from .retarget_controller import IndependentPositionController
        return IndependentPositionController(self._verified_position_targets)

    def verify_controller_targets(self, request, request_digest):
        from .retarget_controller import lower_position_request
        if digest(request) != request_digest:
            raise RecipeConflict("RETARGET_CONTROLLER_REQUEST_MISMATCH")
        lowered = lower_position_request(request)
        observations = getattr(self, "_retarget_observations", {})
        observation = observations.get(getattr(self._retarget_context(), "observation_digest", None))
        if observation is None or observation["profile_digest"] != digest(request["profile"]):
            raise RecipeConflict("RETARGET_TARGET_PROVENANCE_UNVERIFIED")
        result = self.client.execute("transform_get", [Operation(name="system.observe_controller_targets", arguments={
            "retarget_observation": observation, "controller_request": request,
            "controller_request_digest": request_digest, "controller_targets": lowered})])
        if not result.ok:
            return result
        value = result.result
        if (not isinstance(value, dict) or value.get("schema_version") != 1 or value.get("kind") != "controller_targets"
                or value.get("controller_request_digest") != request_digest
                or value.get("controller_targets_digest") != digest(lowered) or value.get("controller_targets") != lowered
                or value.get("retarget_inputs_digest") != digest(observation)
                or any(value.get(key) != observation[key] for key in (
                    "adapter_id", "source_binding_digest", "profile_digest", "context_digest", "native_projection_digest",
                    "runtime_epoch", "adapter_fingerprint", "qualification_digest"))):
            raise RecipeConflict("RETARGET_CONTROLLER_OBSERVATION_MISMATCH")
        verified = self.client.execute("transform_get", [Operation(name="system.verify_observation", arguments={
            "observation": value, "digest": digest(value), "kind": "controller_targets"})])
        if verified.ok:
            self._check_controller_proof(verified, value)
            import copy
            records = getattr(self, "_retarget_controller_proofs", {})
            records[(digest(observation), request_digest)] = copy.deepcopy(value)
            while len(records) > 16:
                records.pop(next(iter(records)))
            self._retarget_controller_proofs = records
        return verified

    @staticmethod
    def _check_controller_proof(verified, value):
        expected = {"observation_digest": digest(value), "controller_request_digest": value["controller_request_digest"],
                    "controller_targets_digest": value["controller_targets_digest"],
                    "retarget_inputs_digest": value["retarget_inputs_digest"]}
        if not isinstance(verified.result, dict) or any(verified.result.get(key) != item for key, item in expected.items()):
            raise RecipeConflict("RETARGET_CONTROLLER_PROVENANCE_UNVERIFIED")

    def _verified_position_targets(self, request, request_digest):
        import copy
        observation_digest = getattr(self._retarget_context(), "observation_digest", None)
        value = getattr(self, "_retarget_controller_proofs", {}).get((observation_digest, request_digest))
        if value is None or digest(request) != request_digest:
            raise RecipeConflict("RETARGET_CONTROLLER_PROVENANCE_UNVERIFIED")
        verified = self.client.execute("transform_get", [Operation(name="system.verify_observation", arguments={
            "observation": value, "digest": digest(value), "kind": "controller_targets"})])
        if not verified.ok:
            raise RecipeConflict("RETARGET_CONTROLLER_PROVENANCE_UNVERIFIED: " + str(verified.error_message))
        self._check_controller_proof(verified, value)
        return {**copy.deepcopy(value), "observation_digest": digest(value)}

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
                args["input_length"] = length
            source = spec.input.source_binding
            outputs = [str(backup), str(working)]
            successor = "working_clone" if spec.input.kind == "active_scene" else "new_instance"
        elif stage == "checkpoint":
            manifest = {} if source is None else source.scope.get("snapshot_manifest", {})
            if not manifest.get("working_path"):
                raise RecipeConflict("CHECKPOINT_UNAVAILABLE")
            directory = self.recipes.store.run_dir(run.run_id) / "checkpoints"
            directory.mkdir(parents=True, exist_ok=True)
            path, working = str(directory / f"{step.step_id}-backup.casc"), str(directory / f"{step.step_id}-working.casc")
            args = {"checkpoint_path": path, "working_path": working}
            outputs = [path, working]
        elif stage in {"evaluation", "insertion_evaluation"}:
            args = {} if stage == "insertion_evaluation" else dict(step.fixed_parameters)
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
                from .unbaking_contract import unbaking_topology_policy
                if len(step.frame_ranges) != 1:
                    raise RecipeConflict("UNBAKING_REQUIRES_ONE_EXACT_FRAME_RANGE")
                first, last = step.frame_ranges[0]
                target_ids = step.target.object_ids if mapping is None else tuple(
                    mapping.role_ids[key] for key in step.target.object_ids
                ) if step.target.object_ids else mapping.object_ids
                target_layers = step.target.layer_ids if mapping is None else mapping.layer_ids
                if not target_ids or not target_layers or first >= last:
                    raise RecipeConflict("UNBAKING_REQUIRES_EXACT_OBJECTS_LAYERS_AND_INTERVAL")
                args = {"step": motion.unbaking_step, "object_ids": list(target_ids),
                        "layer_ids": list(target_layers), "first_frame": first, "last_frame": last,
                        "topology_policy": unbaking_topology_policy(motion.unbaking_limits,
                            allow_key_insertion=spec.intent.allow_key_insertion,
                            allow_interpolation_change=spec.intent.allow_interpolation_change).model_dump(mode="json")}
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
        elif stage in {"correction", "key_insert"}:
            args = context["candidate"]["arguments"]
        elif stage == "export_stage":
            export = context["export_stage"]
            # This strict profile is consumed only by a registered export adapter;
            # it must observe actual native settings/closure before dispatch.
            args = {"path": export["raw_path"], "export_profile": spec.export.model_dump(mode="json"),
                    "export_profile_digest": digest(spec.export), "max_output_bytes": min(spec.budgets.output_bytes, spec.budgets.disk_bytes, 2 * 1024**3)}
            outputs = [export["raw_path"], export["sealed_path"]]
        else:
            raise RecipeConflict("STAGE_LOWERING_UNSUPPORTED")
        args = self._bound_arguments(step.feature_id, args)
        if stage != "initial_checkpoint" or source is not None:
            if source is None:
                raise RecipeConflict("BINDING_UNAVAILABLE")
            source = self.recipe_rebind_source(source, step.operation_name, args, plan=plan, run=run, step=step)
        if stage == "initial_checkpoint" and inputs:
            _assert_file_source(source, inputs[0], args)
        ids = step.target.object_ids if mapping is None else tuple(mapping.role_ids[key] for key in step.target.object_ids) if step.target.object_ids else mapping.object_ids
        layers = step.target.layer_ids if mapping is None else mapping.layer_ids
        return StageEffect(step_id=step.step_id, declaration_digest=step.fixed_parameters_digest,
            lowering_rule_id=step.lowering_rule_id, lowering_rule_digest=step.lowering_rule_digest,
            feature_id=step.feature_id, operation_name=step.operation_name,
            effect_class="mixed" if stage in {"checkpoint", "initial_checkpoint"} else "file" if stage == "export_stage" else "evaluation" if stage in {"evaluation", "insertion_evaluation"} else "scene",
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
        if grant.input_file is not None:
            capability = self.client.runtime_status.get("guarded_capabilities", {})
            if not _file_bootstrap_supported(capability, effect.arguments.get("input_kind"), effect.arguments.get("input_mode")):
                raise RecipeConflict("FILE_BOOTSTRAP_READER_UNVERIFIED")
            sha, length = file_sha256(Path(grant.input_file.path))
            if sha != grant.input_file.sha256 or length != grant.input_file.length:
                raise RecipeConflict("INPUT_DIGEST_MISMATCH")
            _assert_file_source(grant.source_binding, grant.input_file, effect.arguments)
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
                or receipt.get("dispatched") is not True or receipt.get("write_phase") != "completed"
                or observation.operation_digest != effect.operation_digest or observation.source_before != effect.source_binding
                or effect.source_binding is None or effect.source_binding.binding.model_dump(mode="json") != receipt.get("scene_before")
                or observation.source_after.binding.model_dump(mode="json") != receipt.get("scene_after")):
            raise RecipeConflict("CHECKPOINT_RECEIPT_MISMATCH")
        for manifest in (observation.checkpoint, observation.working_file):
            sha, length = file_sha256(Path(manifest.path))
            if sha != manifest.sha256 or length != manifest.length:
                raise RecipeConflict("CHECKPOINT_BYTES_CHANGED")
        if (observation.checkpoint.path != effect.arguments.get("checkpoint_path")
                or observation.working_file.path != effect.arguments.get("working_path")
                or set(effect.output_paths) != {observation.checkpoint.path, observation.working_file.path}):
            raise RecipeConflict("CHECKPOINT_PATH_MISMATCH")
        before, after = effect.source_binding.binding, observation.source_after.binding
        if (observation.parent_scene_instance_id != before.scene_instance_id
                or after.runtime_epoch != before.runtime_epoch or receipt.get("runtime_epoch") != after.runtime_epoch
                or observation.source_after.adapter_fingerprint != effect.source_binding.adapter_fingerprint
                or observation.authored_digest != after.content_revision
                or observation.sample_digest != observation.source_after.sample_digest
                or (effect.expected_successor == "same_instance" and (after.scene_instance_id != before.scene_instance_id
                    or after.document_lineage_id != before.document_lineage_id))
                or (effect.expected_successor != "same_instance" and after.scene_instance_id == before.scene_instance_id)
                or (effect.expected_successor == "working_clone" and after.document_lineage_id != before.document_lineage_id)):
            raise RecipeConflict("CHECKPOINT_SUCCESSOR_MISMATCH")
        manifest = observation.source_after.scope.get("snapshot_manifest") or {}
        expected_manifest = {"path": observation.checkpoint.path, "sha256": observation.checkpoint.sha256,
            "bytes": observation.checkpoint.length, "working_path": observation.working_file.path,
            "working_scene_instance_id": after.scene_instance_id, "document_lineage_id": after.document_lineage_id,
            "runtime_epoch": after.runtime_epoch, "adapter_fingerprint": observation.source_after.adapter_fingerprint,
            "native_completion": "observed", "authored_projection_digest": observation.sample_digest}
        if any(manifest.get(key) != expected for key, expected in expected_manifest.items()):
            raise RecipeConflict("CHECKPOINT_MANIFEST_MISMATCH")
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
