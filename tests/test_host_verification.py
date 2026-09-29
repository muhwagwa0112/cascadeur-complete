"""Host-side postconditions for view toggles, playback, dependencies and Blender export."""

from __future__ import annotations

from pathlib import Path

import pytest

import cascadeur_complete.service as service_module
from cascadeur_complete.discovery import BASELINE_TOOLS, load_csc_schema
from cascadeur_complete.feature_registry import build_registry
from cascadeur_complete.models import ExecutionMode, ResultEnvelope
from cascadeur_complete.paths import RuntimePaths
from cascadeur_complete.service import CascadeurService
from cascadeur_complete.uia import sample_difference
from tests.test_service import FakeBridge


def test_sample_difference_ignores_noise_and_detects_change():
    base = [100] * 1000
    assert sample_difference(base, [110] * 1000) == 0.0
    changed = list(base)
    changed[:50] = [200] * 50
    assert sample_difference(base, changed) == 0.05
    assert sample_difference(None, base) == 0.0


def _view_service(tmp_path, monkeypatch, samples):
    paths = RuntimePaths.discover(tmp_path / "runtime")
    svc = CascadeurService(paths, client=FakeBridge(paths.snapshots))
    feed = iter(samples)
    monkeypatch.setattr(service_module, "capture_window_sample", lambda: next(feed))
    monkeypatch.setattr(service_module.time, "sleep", lambda _seconds: None)
    return svc


def test_view_toggle_requires_a_rendered_change(tmp_path, monkeypatch):
    svc = _view_service(tmp_path, monkeypatch, [[0] * 100, [0] * 100])
    prepared = svc.prepare_change("silhouette", "view.silhouette", {})
    result = svc.commit_change(prepared["confirmation_token"], timeout=2)
    assert not result.ok
    assert "did not change" in result.error_message


def test_view_toggle_reports_viewport_render_changed(tmp_path, monkeypatch):
    svc = _view_service(tmp_path, monkeypatch, [[0] * 100, [255] * 100])
    prepared = svc.prepare_change("silhouette", "view.silhouette", {})
    result = svc.commit_change(prepared["confirmation_token"], timeout=2)
    assert result.ok
    assert "viewport_render_changed" in {item["id"] for item in result.postconditions}


def test_playback_prepare_refuses_when_state_already_matches(tmp_path, monkeypatch):
    paths = RuntimePaths.discover(tmp_path / "runtime")
    svc = CascadeurService(paths, client=FakeBridge(paths.snapshots))
    monkeypatch.setattr(svc, "_playback_moving", lambda: False)
    refused = svc.prepare_change("timeline_stop", "timeline.playback", {})
    assert refused["ok"] is False and "already stopped" in refused["error_message"]


def test_detected_dependency_ungates_adapter_but_keeps_its_name():
    records = {
        item.id: item
        for item in build_registry(
            load_csc_schema(), [], BASELINE_TOOLS, available_dependencies={"Blender integration"}
        )
    }
    assert records["blender_export"].state.value != "missing_dependency"
    assert records["blender_export"].dependency == "Blender integration"
    gated = {item.id: item for item in build_registry(load_csc_schema(), [], BASELINE_TOOLS)}
    assert gated["blender_export"].state.value == "missing_dependency"


def test_blender_export_requires_target_side_import(tmp_path, monkeypatch):
    paths = RuntimePaths.discover(tmp_path / "runtime")
    bridge = FakeBridge(paths.snapshots)
    destination = tmp_path / "out.fbx"
    original = bridge.execute

    def execute(feature_id, operations, **kwargs):
        if operations[0].name == "io.export_fbx":
            destination.write_bytes(b"FBX")
            return ResultEnvelope(ok=True, feature_id=feature_id, execution_mode=ExecutionMode.NATIVE, result={})
        return original(feature_id, operations, **kwargs)

    bridge.execute = execute
    monkeypatch.setattr(service_module, "available_dependencies", lambda: {"Blender integration"})
    svc = CascadeurService(paths, client=bridge)
    monkeypatch.setattr(
        service_module,
        "verify_blender_fbx",
        lambda path: {"armatures": 1, "bones": 2, "actions": [{"name": "a"}], "blender": "5.1", "path": path},
    )
    prepared = svc.prepare_change("blender_export", "io.export_fbx", {"path": str(destination)})
    assert prepared["operation"]["arguments"]["target"] == "blender"
    result = svc.commit_change(prepared["confirmation_token"], timeout=2)
    assert result.ok, result.error_message
    assert {"output_file", "nonzero_bytes", "target_import_verified"} <= {item["id"] for item in result.postconditions}


@pytest.mark.parametrize("report", [{"armatures": 0, "bones": 0, "actions": [], "blender": "5.1"}])
def test_blender_export_fails_when_blender_sees_no_rig(tmp_path, monkeypatch, report):
    paths = RuntimePaths.discover(tmp_path / "runtime")
    bridge = FakeBridge(paths.snapshots)
    destination = tmp_path / "out.fbx"
    original = bridge.execute

    def execute(feature_id, operations, **kwargs):
        if operations[0].name == "io.export_fbx":
            Path(destination).write_bytes(b"FBX")
            return ResultEnvelope(ok=True, feature_id=feature_id, execution_mode=ExecutionMode.NATIVE, result={})
        return original(feature_id, operations, **kwargs)

    bridge.execute = execute
    monkeypatch.setattr(service_module, "available_dependencies", lambda: {"Blender integration"})
    svc = CascadeurService(paths, client=bridge)
    monkeypatch.setattr(service_module, "verify_blender_fbx", lambda _path: report)
    prepared = svc.prepare_change("blender_export", "io.export_fbx", {"path": str(destination)})
    result = svc.commit_change(prepared["confirmation_token"], timeout=2)
    assert not result.ok
