"""One SDK-shaped check for the new finite retention/admission boundary."""
import hashlib
import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest


def test_retention_requires_admission_and_never_closes_or_replays(tmp_path, monkeypatch):
    native = Path(__file__).resolve().parents[1] / "cascadeur_side" / "cascadeur_complete"
    package = types.ModuleType("retention_boundary")
    package.__path__ = [str(native)]
    monkeypatch.setitem(sys.modules, package.__name__, package)
    state = {"admitted": False, "workspace": tmp_path / "snapshots" / "denied", "calls": 0}
    (tmp_path / "snapshots").mkdir()

    class Scene:
        def __init__(self, identity):
            self.identity, self.projection = identity, {"objects": []}

        def get_path_name(self):
            return ""

        def domain_scene(self):
            return self

        def model_viewer(self):
            return self

        def get_objects(self):
            return []

    original = Scene("original")

    class Manager:
        def __init__(self):
            self.tabs, self.active = [original], original

        def scenes(self):
            return list(self.tabs)

        def current_scene(self):
            return self.active

        def set_current_scene(self, scene):
            assert scene in self.tabs
            self.active = scene

        def create_application_scene(self):
            child = Scene("fixture-" + str(len(self.tabs)))
            self.tabs.append(child)
            self.active = child
            return child

        def remove_application_scene(self, scene):
            pytest.fail("retention must not remove native tabs")

        def close_scene(self, scene):
            pytest.fail("retention must not close native tabs")

    manager = Manager()

    def application():
        state["calls"] += 1
        return types.SimpleNamespace(get_scene_manager=lambda: manager)

    def admit(*_args):
        if not state["admitted"]:
            raise ValueError("SETUP_CONTEXT_UNAVAILABLE")
        if state.get("source_guard") is not None:
            state["source_guard"]()
        return types.SimpleNamespace(workspace_path=str(state["workspace"]), maximum_new_tabs=2, maximum_casc_files=5)

    def bind_source(_setup_id, guard):
        admit()
        assert state.get("source_guard") is None
        guard()
        state["source_guard"] = guard

    def save(scene, path):
        path.write_bytes(b"fixture")
        return {"path": str(path), "sha256": hashlib.sha256(b"fixture").hexdigest(), "length": 7}

    def module(name, **values):
        value = types.ModuleType(name)
        vars(value).update(values)
        monkeypatch.setitem(sys.modules, name, value)
        return value

    module("csc", app=types.SimpleNamespace(get_application=application))
    guards = module("retention_boundary.guarded_runtime", RUNTIME_EPOCH="epoch", LOADED_FINGERPRINT="bytes",
        assert_loaded_package=lambda: None, scene_instance=lambda scene: {"scene_instance_id": scene.identity})
    module("retention_boundary.runtime", runtime_root=lambda: tmp_path, _domain_scene=lambda scene: scene)
    module("retention_boundary.incident_admission", assert_setup_admission=admit, assert_current_setup_admission=admit,
        _bind_setup_source_guard=bind_source)
    module("retention_boundary.native_adapters", installed_build=lambda: "exact-build", _save_observed=save)
    module("retention_boundary.native_scene_reader", read_scene=lambda scene: dict(scene.projection))

    def load(name):
        spec = importlib.util.spec_from_file_location("retention_boundary." + name, native / (name + ".py"))
        value = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, spec.name, value)
        spec.loader.exec_module(value)
        return value

    fixture = load("native_fixture")
    retained = load("native_probe_retention")
    with pytest.raises(ValueError, match="SETUP_CONTEXT_UNAVAILABLE"):
        retained.RetainedProbe("finite_models")
    with pytest.raises(ValueError, match="SETUP_CONTEXT_UNAVAILABLE"):
        fixture.create_disposable_scene(retain_on_failure=True)
    assert state["calls"] == 0 and not state["workspace"].exists()

    state["admitted"] = True

    def start(kind):
        state["source_guard"] = None
        plan_workspace = tmp_path / "snapshots" / kind
        plan_workspace.mkdir()
        state["workspace"] = plan_workspace / "0"
        probe = retained.RetainedProbe(kind)
        probe.before_new_tab()
        child = manager.create_application_scene()
        probe.track(child, "fixture")
        fixture._OWNED[id(child)] = {"scene": child}
        return probe, child

    probe, child = start("finite_models")
    probe.save_fixture(child, "fixture-before.casc", lambda scene: dict(scene.projection))
    with pytest.raises(ValueError, match="TAB_LIMIT"):
        probe.before_new_tab()
    primary = ValueError("actual probe failed")
    observation = probe.finish(primary)
    assert observation["retention_status"] == "observed"
    assert manager.active is original and child in manager.tabs and id(child) not in fixture._OWNED
    assert (probe.directory / "fixture-before.casc").read_bytes() == b"fixture"
    assert json.loads((probe.directory / "retention.json").read_text())["qualification_error"] == str(primary)
    with pytest.raises(ValueError, match="RETENTION_UNVERIFIED"):
        probe.complete({"status": "pass"})
    with pytest.raises(ValueError, match="ATTEMPT_RETAINED"):
        retained.retained_probe_result("finite_models")

    good, good_child = start("position_writer")
    good.finish()
    good.complete({"observation": "successful helper boundary"})
    count = len(manager.tabs)
    assert retained.retained_probe_result("position_writer")["reused"] is True
    assert manager.active is original and good_child in manager.tabs and len(manager.tabs) == count

    changed, _ = start("native_adapter")
    original.projection["changed"] = True
    # Original source validation must happen inside fixture callbacks too,
    # before the caller's setter and before retention diagnostic file writes.
    invoked = []
    with pytest.raises(ValueError, match="QUALIFICATION_ORIGINAL_SCENE_CHANGED"):
        fixture._modify(lambda _label, callback: callback(), "bounded callback", lambda: invoked.append(True))
    assert not invoked
    with pytest.raises(ValueError, match="RETENTION_UNVERIFIED"):
        changed.finish()
    with pytest.raises(ValueError, match="RETENTION_UNVERIFIED"):
        changed.complete({"status": "pass"})
    guards.RUNTIME_EPOCH = "another-epoch"
    with pytest.raises(ValueError, match="CONTEXT_CHANGED"):
        retained.retained_probe_result("position_writer")
