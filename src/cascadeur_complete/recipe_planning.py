"""Compile declarative recipes into a finite, concrete sequence of permits."""

from __future__ import annotations

import hashlib
import sys
import time
import uuid
from pathlib import Path

from .recipe_models import EffectBounds, ExactTarget, RecipeSpec, StepPermit, VariantEnvelope, WorkflowPlan, digest
from .recipe_store import file_sha256
from .package_fingerprint import expected_bridge_fingerprint
from .capture import estimate_motion_resources


def implementation_digest() -> str:
    directory = Path(__file__).parent
    names = (
        "recipe_models.py", "recipe_planning.py", "recipe_store.py", "recipe_authorization.py", "recipe_runner.py",
        "motion_context.py", "motion_quality.py", "motion_math.py", "motion_cleanup.py", "cleanup_workflow.py",
        "change_flow.py", "safety.py", "models.py", "export_models.py", "export_workflow.py", "export_publisher.py",
        "bridge_client.py", "atomic_queue.py", "request_ledger.py", "effects.py", "capture.py",
        "motion_geometry.py", "motion_solvers.py", "retargeting.py", "fbx_validation.py", "store_lock.py",
        "state_lock.py", "service.py", "server.py", "handler_registry.py", "external.py", "jobs.py",
        "motion_styling.py", "recovery.py", "host_postconditions.py", "package_fingerprint.py",
        "blender_export_adapter.py",
    )
    # A missing dependency is fingerprinted as missing, never treated as an
    # installed native adapter. Preflight separately decides availability.
    host = {name: hashlib.sha256((directory / name).read_bytes()).hexdigest()
            if (directory / name).is_file() else None for name in names}
    # Include indirect route dependencies and newly added modules as well as
    # explicit missing-file markers. The native bridge lives outside src/ in
    # checkout builds; installed builds bind the shipped bridge-package.json.
    host.update({path.relative_to(directory).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                 for path in sorted(directory.rglob("*.py"))})
    executable = None
    if getattr(sys, "frozen", False):
        executable_sha, executable_length = file_sha256(Path(sys.executable))
        executable = {"sha256": executable_sha, "length": executable_length}
    elif not any(value is not None for value in host.values()):
        raise ValueError("Host implementation source is unavailable")
    return digest({"host_source": host, "host_executable": executable,
                   "expected_bridge_package": expected_bridge_fingerprint()})


def compile_steps(spec: RecipeSpec) -> tuple[StepPermit, ...]:
    target = ExactTarget(
        character_id=spec.character.character_id, object_ids=spec.character.object_ids,
        layer_ids=spec.character.layer_ids,
        lineage_id=spec.input.binding.document_lineage_id if spec.input.kind == "active_scene" and spec.input.binding is not None else None,
        derived_ref=spec.character.derived_target,
    )
    envelope = spec.intent.correction_envelope
    bounds = EffectBounds(
        maximum_position_m=envelope.get("position_m", 0), maximum_rotation_rad=envelope.get("rotation_rad", 0),
        maximum_added_keys=spec.budgets.generated_keys if spec.intent.allow_key_insertion else 0,
        maximum_written_keys=spec.budgets.written_keys,
        output_paths=() if spec.export is None else (spec.export.destination,),
    )
    steps: list[StepPermit] = []

    def add(stage, feature, operation, effect, parameters=None, channels=(), reason=None, variants=(), postconditions=(), objects=None, lowering="literal-v1", owned="none"):
        parameters = parameters or {}
        step = StepPermit(
            step_id=f"{len(steps):03d}-{stage}", stage=stage, feature_id=feature, operation_name=operation,
            effect=effect, intent=spec.intent.action,
            target=target if objects is None else target.model_copy(update={"object_ids": tuple(objects)}),
            frame_ranges=((spec.clip.first_frame, spec.clip.last_frame),), allowed_channels=channels,
            fixed_parameters=parameters, fixed_parameters_digest=digest(parameters),
            candidate_variants=variants, max_effect_from_baseline=bounds.model_copy(update={"owned_output_policy": owned}),
            prerequisite_step_ids=() if not steps else (steps[-1].step_id,),
            required_postconditions=postconditions, not_required_reason=reason,
            lowering_rule_id=lowering,
        )
        steps.append(step)

    add("preflight", "status", "system.status", "read", postconditions=("supported_capabilities",))
    add("initial_checkpoint", "snapshot", "safety.bootstrap", "scene_mutation",
        {"input": spec.input.model_dump(mode="json")}, ("scene", "file"),
        postconditions=("isolated_working_clone", "native_checkpoint_complete"), lowering="bootstrap-v1", owned="run_workspace")
    input_parameters = {} if spec.input.path is None else {"path": spec.input.path}
    add("input", "scene_open" if spec.input.kind == "casc_file" else "import_fbx", 
        "scene.open" if spec.input.kind == "casc_file" else "io.import_fbx", "scene_mutation",
        input_parameters, ("scene",), "bootstrap_loaded_exact_input",
        postconditions=("source_lineage", "source_integrity"))
    add("rig", "quick_rig", "rig.quick_rig", "scene_mutation", spec.rig.model_dump(mode="json"), ("scene",),
        "existing_explicit_rig_profile" if spec.rig.mode == "existing" else None, postconditions=("target_rig_ownership",), lowering="rig-v1")
    mode = spec.motion.mode
    motion_feature, motion_operation = {
        "existing": ("status", "system.status"),
        "retarget": (("retargeting", "generation.retargeting") if spec.motion.route == "native" else
                     ("rotation_keys", "animation.rotation_keys_set") if spec.motion.host_channel == "rotation" else
                     ("position_keys", "animation.position_keys_set")),
        "keyposes": ("position_keys", "animation.position_keys_set"),
        "native_root_motion": ("root_motion", "generation.root_motion"),
        "native_inbetweening": ("inbetweening", "generation.inbetweening"),
        "external_motion_asset": ("import_fbx", "io.import_fbx"),
        "native_unbaking": ("unbaking", "generation.unbaking"),
    }[mode]
    if mode == "retarget" and spec.motion.route == "host":
        add("evaluation", "interpolation_refresh", "animation.interpolation_refresh", "evaluation", channels=("evaluation",),
            postconditions=("evaluation_settled",))
        add("retarget_capture", "transform_get", "motion.capture", "read", postconditions=("complete_retarget_target_capture",))
        add("host_retarget", "motion_retarget", "motion.retarget.solve", "host_compute",
            spec.motion.model_dump(mode="json"), postconditions=("verified_controller_candidate",), lowering="host-retarget-v1")
    channels = (spec.motion.host_channel,) if mode == "retarget" and spec.motion.route == "host" else ("position",) if mode == "keyposes" else ("position", "rotation")
    add("motion", motion_feature, motion_operation, "scene_mutation", spec.motion.model_dump(mode="json"),
        channels, "existing_motion_preserved" if mode == "existing" else None,
        postconditions=("target_motion_readback", "non_target_unchanged"), lowering="motion-v1")
    add("evaluation", "interpolation_refresh", "animation.interpolation_refresh", "evaluation", channels=("evaluation",),
        postconditions=("evaluation_settled",))
    add("source_capture", "transform_get", "motion.capture", "read", postconditions=("complete_source_capture",))
    add("baseline_capture", "transform_get", "motion.capture", "read", postconditions=("complete_source_capture",))
    add("analyze", "motion_analysis", "motion.analyze", "host_compute", postconditions=("required_metric_eligibility",))
    insertion_budget = min(spec.budgets.generated_keys, int(envelope.get("added_keys", 0)), 8 * len(spec.cleanup))
    for index, cleanup in enumerate(spec.cleanup):
        variants = cleanup.variants or (VariantEnvelope(variant_id="requested", parameters=cleanup.parameters),)
        add("solve", "motion_cleanup", "motion.solve", "host_compute", {"cleanup_index": index}, variants=variants,
            postconditions=("finite_feasible_candidate", "original_intent_preserved"))
        if spec.intent.allow_key_insertion:
            cap = insertion_budget // len(spec.cleanup) + int(index < insertion_budget % len(spec.cleanup))
            add("key_insert", "key_insert", "motion.key_topology_insert", "scene_mutation",
                {"cleanup_index": index, "max_added_keys": cap}, ("position", "scene"),
                postconditions=("key_topology_inserted", "successor_binding"), objects=cleanup.object_ids,
                lowering="cleanup-key-insertion-v1")
            steps[-1] = steps[-1].model_copy(update={"max_effect_from_baseline": bounds.model_copy(
                update={"maximum_added_keys": cap})})
            add("insertion_evaluation", "interpolation_refresh", "animation.interpolation_refresh", "evaluation",
                {"cleanup_index": index}, ("evaluation",), postconditions=("evaluation_settled",))
            add("insertion_readback", "transform_get", "motion.capture", "read", {"cleanup_index": index},
                postconditions=("completed_exact_topology", "original_intent_preserved", "predicted_target_readback"))
        rotations = cleanup.kind in {"fingers", "finger_fan", "hand_pose", "wrist_soften"}
        add("correction", "rotation_keys" if rotations else "position_keys",
            "animation.rotation_keys_set" if rotations else "animation.position_keys_set", "scene_mutation",
            {"cleanup_index": index, "space": "local" if rotations else "global"}, ("rotation",) if rotations else ("position",),
            postconditions=("exact_driver_readback", "successor_binding"), objects=cleanup.object_ids, lowering="solver-candidate-v1")
        add("actual_readback", "transform_get", "motion.capture", "read", {"cleanup_index": index},
            postconditions=("complete_actual_capture",))
        add("checkpoint", "snapshot", "safety.checkpoint", "scene_mutation", {"after_cleanup_index": index}, ("scene", "file"),
            postconditions=("durable_successor_checkpoint",), lowering="checkpoint-v1", owned="run_workspace")
    add("quality", "motion_quality", "motion.quality", "host_compute", postconditions=("actual_required_metrics_pass",))
    add("checkpoint", "snapshot", "safety.checkpoint", "scene_mutation", channels=("scene", "file"),
        postconditions=("durable_successor_checkpoint",), lowering="checkpoint-v1", owned="run_workspace")
    if spec.export is not None:
        add("export_stage", "export_fbx", "io.export_fbx", "file_stage", spec.export.model_dump(mode="json"),
            ("file",), postconditions=("target_export_scope", "native_export_terminal"), lowering="export-v1", owned="export_stage")
        add("export_validate", "export_validation", "export.validate", "host_compute",
            postconditions=("sealed_structure_pass", "target_roundtrip_pass"))
        add("publish", "publish", "export.publish", "publish", {"destination": spec.export.destination},
            ("file",), postconditions=("validated_hash_published",))
    return tuple(steps)


def input_preflight(spec: RecipeSpec) -> list[dict]:
    reasons = []
    references = (*spec.references.support_tracks, *spec.references.geometry, *spec.references.prop_tracks)
    files = [(ref.path, ref.sha256, ref.length) for ref in references]
    if spec.input.path is not None:
        files.append((spec.input.path, spec.input.sha256, None))
    if spec.motion.source is not None:
        files.append((spec.motion.source.path, spec.motion.source.sha256, spec.motion.source.length))
    if spec.rig.template is not None:
        files.append((spec.rig.template.path, spec.rig.template.sha256, spec.rig.template.length))
    for path_string, expected_sha, expected_length in files:
        path = Path(path_string)
        try:
            if not path.is_absolute() or not path.is_file() or path.stat().st_size > spec.budgets.disk_bytes:
                raise ValueError("Input path is missing, nonlocal or exceeds the disk budget")
            actual_sha, length = file_sha256(path)
            if actual_sha != expected_sha or expected_length is not None and length != expected_length:
                reasons.append({"code": "INPUT_DIGEST_MISMATCH", "path": path_string})
        except (OSError, ValueError):
            reasons.append({"code": "INPUT_UNAVAILABLE", "path": path_string})
    # The entire requested interval must fit capture accounting. No shortened
    # clip or missing mandatory channel is silently substituted.
    n = spec.clip.last_frame - spec.clip.first_frame + 1
    retained = n * len(spec.character.object_ids) * 2048
    # Before authenticated key-layout capture, use the conservative own-grid
    # maximum key count. The sparse estimate never allocates a dense n*n matrix.
    estimate = estimate_motion_resources(n, {key: n for key in spec.character.object_ids}, retained_capture_bytes=retained)
    estimated = estimate["estimated_peak_bytes"]
    if estimated > spec.budgets.memory_bytes:
        reasons.append({"code": "RESOURCE_BUDGET_EXCEEDED", "resource": "capture_memory_bytes", "required": estimated})
    return reasons


def build_plan(spec: RecipeSpec, blocked_reasons: list[dict], runtime_fingerprints=None) -> WorkflowPlan:
    steps = compile_steps(spec)
    scope = {
        "input": spec.input.model_dump(mode="json"), "character": spec.character.model_dump(mode="json"),
        "clip": spec.clip.model_dump(mode="json"), "intent": spec.intent.model_dump(mode="json"),
        "quality": spec.quality.model_dump(mode="json"), "references": spec.references.model_dump(mode="json"),
        "export": None if spec.export is None else spec.export.model_dump(mode="json"),
        "steps": [step.model_dump(mode="json") for step in steps], "budgets": spec.budgets.model_dump(mode="json"),
    }
    payload = dict(schema_version=1, plan_id=str(uuid.uuid4()), created_at=time.time(), spec=spec.model_dump(mode="json"),
                   steps=[step.model_dump(mode="json") for step in steps], scope_digest=digest(scope),
                   implementation_digest=implementation_digest(), runtime_fingerprints=runtime_fingerprints or {},
                   blocked_reasons=blocked_reasons)
    return WorkflowPlan.model_validate({**payload, "plan_digest": digest(payload)})
