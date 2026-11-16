"""Actual immutable-P0 roundtrip inside the admitted owned-pair setup.

No fabricated failed request or recovery permit is needed. The same save/load
primitives as dispatch operate on the fresh owned fixture and a retained clone.
This observation does not qualify arbitrary rigs or retire an open incident.
"""
from __future__ import annotations

from . import guarded_runtime as guards


def observe_pair_checkpoint(scene, retained):
    from .incident_admission import assert_setup_admission, _LOCAL as admission_local
    from .native_owned_pair_geometry import SETUP_OPERATION
    from .native_adapters import _save_checkpoint_files
    from .native_checkpoint_restore import _CHECKPOINTS, _restore_native
    from .native_scene_reader import read_scene
    grant = assert_setup_admission(SETUP_OPERATION)
    request = getattr(guards._LOCAL, "request", None)
    if (request is None or request.get("request_id") != admission_local.setup["invocation_ref"]
            or grant.maximum_new_tabs != 2 or grant.maximum_casc_files != 5
            or grant.maximum_update_graph_captures != 7
            or not any(scene is item[0] for item in retained.identified)
            or retained.manager.current_scene() is not scene):
        raise ValueError("PAIR_CHECKPOINT_SETUP_SCOPE_DIFFERS")
    projection = read_scene(scene)
    checkpoint = retained.plan_file("checkpoint.casc")
    working = retained.plan_file("checkpoint-working.casc")
    restored_path = retained.plan_file("checkpoint-restored.casc")
    retained.before_effect()
    manifest, saved, working_file, checkpoint_phase, working_phase = _save_checkpoint_files(
        scene, checkpoint, working, expected_projection=projection,
        phase_guard=retained.before_effect, run_id=(request.get("execution_context") or {}).get("run_id"),
        reader=read_scene)
    retained.record_file(saved)
    retained.record_file(working_file)
    if manifest["schema_version"] != 2:
        raise ValueError("PAIR_CHECKPOINT_IMMUTABLE_ANCHOR_REQUIRED")
    retained.before_new_tab()
    def source_unchanged():
        retained.before_effect()
        if read_scene(scene) != projection or str(scene.get_path_name()) != str(working):
            raise ValueError("PAIR_CHECKPOINT_SOURCE_CHANGED_BEFORE_LOAD")
    guards.before_write(source_unchanged)
    # Track only the actual loader's returned/partially created native wrapper;
    # an unrelated new tab must remain unidentified and fail retention checks.
    restored = _restore_native(scene, _CHECKPOINTS[guards.digest(manifest)], restored_path,
        on_loaded=lambda target: retained.track(target, "owned-checkpoint-restored"))
    # link_clone completes only after both load/save comparisons. Refresh that
    # same tracked wrapper's final lineage for the retained observation.
    for index, (target, role, _identity, old_path) in enumerate(retained.identified):
        if target is restored.target:
            retained.identified[index] = (target, role, dict(guards.scene_instance(target)), old_path)
    retained.record_file(restored.saved)
    phases = [checkpoint_phase.as_dict(), working_phase.as_dict(),
              restored.project_load_serialization_observation, restored.serialization_observation]
    if (any(not isinstance(row, dict) for row in phases)
            or [row["phase"] for row in phases] != ["checkpoint_save", "working_save", "project_load", "restored_save"]
            or any(row["reference_projection_digest"] != manifest["reference_projection_digest"] for row in phases)
            or read_scene(scene) != projection
            or restored.after["scene_instance_id"] == restored.before["scene_instance_id"]
            or restored.after["document_lineage_id"] != restored.before["document_lineage_id"]):
        raise ValueError("PAIR_CHECKPOINT_ROUNDTRIP_NOT_OBSERVED")
    return {"completion": "native_observed", "reference_projection_digest": manifest["reference_projection_digest"],
        "checkpoint_anchor_digest": manifest["checkpoint_anchor_digest"], "snapshot_manifest": manifest,
        "phase_observations": phases, "project_load": restored.project_load,
        "restored_scene": restored.after, "restored_file": restored.saved,
        "successor_manifest": restored.successor_manifest,
        "general_rig_supported": False, "recovery_permit_issued": False}
