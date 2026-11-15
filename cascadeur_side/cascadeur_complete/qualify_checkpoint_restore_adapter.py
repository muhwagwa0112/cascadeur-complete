"""Explicit exact-readback restore qualification on an owned checkpoint."""
import json
import uuid
from pathlib import Path


def command_name():
    return "Cascadeur Complete.Qualify checkpoint restore adapter"


def command_description():
    return "Observe exact new-tab native restore of the active owned checkpoint; leaves failed observations for reconciliation"


def run(scene):
    import csc
    from . import guarded_runtime as guards
    from .native_adapters import _WORKSPACES
    from .native_scene_reader import read_scene
    from .native_checkpoint_restore import qualify_restore, NativeCheckpointRestoreAdapter, _CHECKPOINTS
    guards.assert_loaded_package()
    manager = csc.app.get_application().get_scene_manager()
    active = manager.current_scene()
    manifest = _WORKSPACES.get(guards.scene_instance(active)["scene_instance_id"])
    anchor = _CHECKPOINTS.get(guards.digest(manifest)) if manifest else None
    if anchor is None:
        raise ValueError("RECOVERY_CHECKPOINT_ANCHOR_UNAVAILABLE: active owned checkpoint required")
    saved_local = dict(vars(guards._LOCAL))
    before = read_scene(active)
    try:
        guards.begin_request({"operations": []})
        guards.set_write_guard(lambda: read_scene(active) == before or
                               (_ for _ in ()).throw(ValueError("SCENE_CHANGED")))
        evidence = qualify_restore(active, manifest, run_id=anchor["run_id"])
        observation = json.loads(evidence)
        target_id = observation["scene_after"]["scene_instance_id"]
        target = next((item for item in manager.scenes()
                       if guards.scene_instance(item)["scene_instance_id"] == target_id), None)
        if target is None or manager.current_scene() is not active or read_scene(active) != before:
            raise ValueError("RECOVERY_QUALIFICATION_SOURCE_CHANGED")
        path = Path(manifest["path"]).parent / ("restore-qualification-" + str(uuid.uuid4()) + ".json")
        with path.open("xb") as stream:
            stream.write(evidence)
        manager.remove_application_scene(target)
        adapter = NativeCheckpointRestoreAdapter(evidence, path)
        guards.register_adapter("safety.rollback", adapter)
        scene.success("Qualified exact native restore primitive; failed-request recovery requires separate attestation and permit")
        return {"operation": "safety.rollback", "evidence_path": str(path),
                "evidence_sha256": adapter.verification["evidence_sha256"],
                "conditional_failed_request_recovery": "requires_partial_write_attestation_and_signed_permit"}
    finally:
        vars(guards._LOCAL).clear()
        vars(guards._LOCAL).update(saved_local)
