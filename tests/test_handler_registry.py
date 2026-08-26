import importlib.util
from pathlib import Path


def test_bridge_handler_registry_has_scene_and_layer_routes():
    path = Path(__file__).parents[1] / "cascadeur_side" / "cascadeur_complete" / "handler_registry.py"
    spec = importlib.util.spec_from_file_location("cascadeur_complete_bridge_registry", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)

    @module.handler("example.read")
    def example(_scene, _arguments, _request, _context):
        return {"ok": True}, []

    handled, result = module.dispatch("example.read", None, {}, {}, {})
    assert handled is True
    assert result == ({"ok": True}, [])
    assert module.registered_operations() == ("example.read",)


def test_bridge_handler_modules_register_structured_routes():
    root = Path(__file__).parents[1] / "cascadeur_side" / "cascadeur_complete" / "handlers"
    sources = "\n".join(path.read_text(encoding="utf-8") for path in root.glob("*.py"))
    for route in (
        "scene.list",
        "io.import_dae",
        "io.export_dae",
        "io.import_audio",
        "scene.validate",
        "layer.folder",
        "object.hierarchy",
        "object.properties",
        "object.behaviors",
        "object.create",
        "object.parent",
        "object.unparent",
        "render.viewport_capture",
        "render.camera_create",
        "render.camera_aim",
        "render.light_point",
        "render.light_spot",
        "render.image",
        "physics.auto_state",
        "physics.auto_enable",
        "physics.auto_snap",
        "physics.state",
        "physics.center_of_mass",
        "physics.ballistic",
        "physics.collision_create",
        "physics.collision_delete",
        "physics.constraint_point",
        "physics.constraint_transform",
        "rig.state",
        "rig.constraint_drivers",
        "rig.mass_set",
        "rig.joint_create",
        "rig.rig_info_create",
        "rig.ik_chain_create",
        "rig.rig_elements_create",
        "rig.additional_point_create",
        "rig.additional_box_create",
        "rig.spline_ik_create",
        "rig.twist",
        "generation.state",
        "generation.inbetweening",
        "generation.root_motion",
        "generation.unbaking",
        "animation.key_reduce",
        "animation.cycle_query",
        "editing.mirror",
        "timeline.range",
        "generation.auto_posing",
        "system.logs",
        "system.view_mode",
    ):
        assert f'"{route}"' in sources


def test_focus_and_open_events_drain_complete_queue():
    root = Path(__file__).parents[1] / "cascadeur_side" / "cascadeur_complete_events"
    for relative in ("scene_activated/drain.py", "scene_opened/drain.py"):
        source = (root / relative).read_text(encoding="utf-8")
        assert "cascadeur_complete.runtime import process_pending" in source
        assert "process_pending(scene, matching_scene_only=True)" in source
