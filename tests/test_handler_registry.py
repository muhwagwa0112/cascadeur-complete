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


def test_entry_points_install_the_ui_thread_pump():
    bridge = Path(__file__).parents[1] / "cascadeur_side"
    sources = [
        bridge / "cascadeur_complete" / "__init__.py",
        bridge / "cascadeur_complete" / "process_pending.py",
        bridge / "cascadeur_complete_events" / "scene_activated" / "drain.py",
        bridge / "cascadeur_complete_events" / "scene_opened" / "drain.py",
    ]
    for path in sources:
        assert "ensure_installed()" in path.read_text(encoding="utf-8"), path


def test_pump_never_installs_outside_cascadeur():
    import importlib.util
    import sys
    import types

    path = Path(__file__).parents[1] / "cascadeur_side" / "cascadeur_complete" / "pump.py"
    spec = importlib.util.spec_from_file_location("cascadeur_complete_pump_probe", path)
    module = importlib.util.module_from_spec(spec)
    previous = sys.modules.get("csc")
    sys.modules.setdefault("csc", types.ModuleType("csc"))
    try:
        spec.loader.exec_module(module)
        assert module.ensure_installed() is False
        assert module.status()["hwnd"] is None
    finally:
        if previous is None:
            sys.modules.pop("csc", None)


def test_pump_hot_reloads_changed_handler_modules(tmp_path):
    import importlib
    import importlib.util
    import shutil
    import sys
    import time
    import types

    source = Path(__file__).parents[1] / "cascadeur_side" / "cascadeur_complete"
    package_root = tmp_path / "hotreload_bridge"
    shutil.copytree(source, package_root, ignore=shutil.ignore_patterns("__pycache__"))
    name = "hotreload_bridge"
    previous_csc = sys.modules.get("csc")
    sys.modules["csc"] = types.ModuleType("csc")
    spec = importlib.util.spec_from_file_location(
        name, package_root / "__init__.py", submodule_search_locations=[str(package_root)]
    )
    package = importlib.util.module_from_spec(spec)
    sys.modules[name] = package
    try:
        spec.loader.exec_module(package)
        importlib.import_module(name + ".runtime")
        pump = importlib.import_module(name + ".pump")
        registry = importlib.import_module(name + ".handler_registry")
        before = set(registry.registered_operations())
        assert "test.hot_reloaded" not in before
        pump._reload_handlers_if_changed()  # records the baseline stamp

        system = package_root / "handlers" / "system.py"
        system.write_text(
            system.read_text(encoding="utf-8")
            + '\n\n@handler("test.hot_reloaded")\ndef _hot_reloaded(scene, arguments, request, context):\n'
            + "    return {}, []\n",
            encoding="utf-8",
        )
        time.sleep(0.01)
        pump._reload_handlers_if_changed()

        assert "test.hot_reloaded" in registry.registered_operations()
        assert before < set(registry.registered_operations())
        assert pump.status()["processed"] == 0
        assert pump._state["handlers_reloaded"] == 1
    finally:
        for module in [item for item in sys.modules if item == name or item.startswith(name + ".")]:
            del sys.modules[module]
        if previous_csc is None:
            sys.modules.pop("csc", None)
        else:
            sys.modules["csc"] = previous_csc
