import time
from pathlib import Path
from threading import Thread
from types import SimpleNamespace

import pytest

import cascadeur_complete.service as service_module
from cascadeur_complete.models import ErrorCode, ExecutionMode, ResultEnvelope
from cascadeur_complete.paths import RuntimePaths
from cascadeur_complete.service import CascadeurService


class FakeBridge:
    def __init__(self, snapshot_dir: Path):
        self.snapshot_dir = snapshot_dir
        self.calls = []
        self.state = {
            "scene_id": "scene-1",
            "revision": "rev-1",
            "selection_fingerprint": "sel-1",
            "selection": ["obj-1"],
            "objects": [{"id": "obj-1"}],
            "tools": ["AutoPosingTool", "Timeline"],
            "license": "Basic",
        }

    def execute(self, feature_id, operations, **kwargs):
        self.calls.append((feature_id, operations, kwargs))
        name = operations[0].name
        if name == "system.status":
            return ResultEnvelope(
                ok=True,
                feature_id=feature_id,
                execution_mode=ExecutionMode.NATIVE,
                scene_id=self.state["scene_id"],
                scene_revision=self.state["revision"],
                result=dict(self.state),
            )
        if name == "safety.snapshot":
            snapshot_id = operations[0].arguments["snapshot_id"]
            working_id = operations[0].arguments["working_id"]
            path = self.snapshot_dir / f"{snapshot_id}.casc"
            working_path = self.snapshot_dir / f"{working_id}.working.casc"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"CASC")
            working_path.write_bytes(b"CASC")
            return ResultEnvelope(
                ok=True,
                feature_id=feature_id,
                execution_mode=ExecutionMode.NATIVE,
                scene_id="scene-1",
                scene_revision="rev-1",
                result={
                    "snapshot_id": snapshot_id,
                    "path": str(path),
                    "working_path": str(working_path),
                },
            )
        if name in {"safety.rollback", "safety.rollback_internal"}:
            working_id = operations[0].arguments["working_id"]
            working_path = self.snapshot_dir / f"{working_id}.working.casc"
            working_path.write_bytes(Path(operations[0].arguments["path"]).read_bytes())
            self.state.update(
                {
                    "path": str(working_path),
                    "revision": "restored-rev",
                }
            )
            return ResultEnvelope(
                ok=True,
                feature_id=feature_id,
                execution_mode=ExecutionMode.NATIVE,
                scene_id=self.state["scene_id"],
                scene_revision=self.state["revision"],
                result={"path": str(working_path), "loaded": True},
            )
        return ResultEnvelope(
            ok=True,
            feature_id=feature_id,
            execution_mode=ExecutionMode.NATIVE,
            scene_id="scene-1",
            scene_revision="rev-2",
            result={"done": True},
        )


def test_destructive_feature_requires_prepare_and_commit(tmp_path):
    paths = RuntimePaths.discover(tmp_path / "runtime")
    bridge = FakeBridge(paths.snapshots)
    svc = CascadeurService(paths, client=bridge)
    refused = svc.execute("scene_new", "scene.new", {})
    assert refused.error_code.value == "CONFIRMATION_REQUIRED"
    prepared = svc.prepare_change("scene_new", "scene.new", {})
    assert prepared["ok"] and Path(prepared["backup_path"]).is_file()
    assert Path(prepared["working_path"]).is_file()
    assert prepared["backup_path"] != prepared["working_path"]
    committed = svc.commit_change(prepared["confirmation_token"])
    assert committed.ok and committed.snapshot_id
    assert svc._live_scene_id == committed.scene_id
    assert svc._live_scene_revision == committed.scene_revision
    assert "scene_new" not in svc.evidence_store.verified_features(svc._version_name)


def test_refresh_live_binds_status_to_cached_scene_identity(tmp_path):
    paths = RuntimePaths.discover(tmp_path / "runtime")
    bridge = FakeBridge(paths.snapshots)
    svc = CascadeurService(paths, client=bridge)
    svc._live_scene_id = "scene-cached"
    svc._live_scene_revision = "rev-cached"

    result = svc.refresh_live()

    assert result.ok
    _, operations, kwargs = bridge.calls[-1]
    assert operations[0].name == "system.status"
    assert kwargs["scene_id"] == "scene-cached"
    assert kwargs["expected_revision"] == "rev-cached"
    assert svc._live_scene_id == "scene-1"
    assert svc._live_scene_revision == "rev-1"


def test_product_coverage_does_not_count_discovery_or_contract_only_rows(tmp_path):
    paths = RuntimePaths.discover(tmp_path / "runtime")
    svc = CascadeurService(paths, client=FakeBridge(paths.snapshots))

    status = svc.capabilities(live=False)
    searched = svc.feature_search("", limit=500)

    assert status["product_coverage"]["catalog_count"] == 223
    assert status["product_coverage"]["supported"] == 0
    assert status["product_coverage"]["support_percent"] == 0
    assert searched and all(item["truth_layer"] == "product" for item in searched)


def test_ui_only_feature_returns_exact_gate_without_bridge_dispatch(tmp_path):
    paths = RuntimePaths.discover(tmp_path / "runtime")
    bridge = FakeBridge(paths.snapshots)
    svc = CascadeurService(paths, client=bridge)

    result = svc.prepare_change("object_delete", "object.delete", {"ids": ["obj-1"]})

    assert result["ok"] is False
    assert result["error_code"] == "UI_LOCKED"
    assert "action.Delete_objects" in result["error_message"]
    assert bridge.calls == []


def test_viewport_capture_waits_for_nonempty_stable_output(tmp_path):
    paths = RuntimePaths.discover(tmp_path / "runtime")
    bridge = FakeBridge(paths.snapshots)
    destination = tmp_path / "viewport.png"
    original_execute = bridge.execute

    def execute(feature_id, operations, **kwargs):
        if operations[0].name == "render.viewport_capture":
            destination.write_bytes(b"PNG")
        return original_execute(feature_id, operations, **kwargs)

    bridge.execute = execute
    svc = CascadeurService(paths, client=bridge)

    prepared = svc.prepare_change(
        "viewport_capture",
        "render.viewport_capture",
        {"path": str(destination), "width": 64, "height": 64, "samples": 1},
    )
    result = svc.commit_change(prepared["confirmation_token"], timeout=2)

    assert result.ok
    assert result.result["path"] == str(destination)
    assert result.result["bytes"] == 3
    assert any(item.kind == "host_file_postcondition" for item in result.evidence)


def test_prepare_rebinds_post_snapshot_status_to_working_scene(tmp_path):
    paths = RuntimePaths.discover(tmp_path / "runtime")
    bridge = FakeBridge(paths.snapshots)
    original_execute = bridge.execute

    def execute(feature_id, operations, **kwargs):
        result = original_execute(feature_id, operations, **kwargs)
        if operations[0].name == "safety.snapshot":
            bridge.state.update(scene_id="scene-working", revision="rev-working")
            result.scene_id = "scene-working"
            result.scene_revision = "rev-working"
        return result

    bridge.execute = execute
    svc = CascadeurService(paths, client=bridge)

    prepared = svc.prepare_change("scene_new", "scene.new", {})

    assert prepared["ok"]
    status_calls = [call for call in bridge.calls if call[1][0].name == "system.status"]
    assert status_calls[-1][2]["scene_id"] == "scene-working"
    assert status_calls[-1][2]["expected_revision"] == "rev-working"
    assert prepared["scene_id"] == "scene-working"


def test_failed_destructive_commit_automatically_restores_snapshot(tmp_path, monkeypatch):
    paths = RuntimePaths.discover(tmp_path / "runtime")
    bridge = FakeBridge(paths.snapshots)
    svc = CascadeurService(paths, client=bridge)
    prepared = svc.prepare_change("scene_new", "scene.new", {})
    snapshot_id = Path(prepared["backup_path"]).stem

    original_execute = bridge.execute

    def fail_commit(feature_id, operations, **kwargs):
        if operations[0].name == "scene.new":
            return ResultEnvelope(
                ok=False,
                feature_id=feature_id,
                execution_mode=ExecutionMode.NATIVE,
                error_code="POSTCONDITION_FAILED",
                error_message="partial mutation",
            )
        return original_execute(feature_id, operations, **kwargs)

    bridge.execute = fail_commit
    restored = ResultEnvelope(
        ok=True,
        feature_id="change_rollback",
        execution_mode=ExecutionMode.NATIVE,
        scene_id="restored-scene",
        scene_revision="restored-revision",
    )
    rollback_calls = []
    monkeypatch.setattr(svc, "_rollback_internal", lambda value: rollback_calls.append(value) or restored)

    result = svc.commit_change(prepared["confirmation_token"])

    assert not result.ok
    assert rollback_calls == [snapshot_id]
    assert result.scene_id == "restored-scene"
    assert result.scene_revision == "restored-revision"
    assert any(item.kind == "automatic_rollback" for item in result.evidence)
    assert any("automatically restored" in warning for warning in result.warnings)


def test_host_postcondition_exception_also_restores_snapshot(tmp_path, monkeypatch):
    paths = RuntimePaths.discover(tmp_path / "runtime")
    bridge = FakeBridge(paths.snapshots)
    svc = CascadeurService(paths, client=bridge)
    destination = tmp_path / "frame.png"
    prepared = svc.prepare_change("render_image", "render.image", {"path": str(destination)})
    snapshot_id = Path(prepared["backup_path"]).stem
    monkeypatch.setattr(svc, "_wait_for_output_file", lambda *_args: (_ for _ in ()).throw(RuntimeError("boom")))
    restored = ResultEnvelope(
        ok=True,
        feature_id="change_rollback",
        execution_mode=ExecutionMode.NATIVE,
        scene_id="restored-scene",
        scene_revision="restored-revision",
    )
    rollback_calls = []
    monkeypatch.setattr(svc, "_rollback_internal", lambda value: rollback_calls.append(value) or restored)

    result = svc.commit_change(prepared["confirmation_token"])

    assert not result.ok
    assert result.error_code.value == "POSTCONDITION_FAILED"
    assert "Host postcondition failed: boom" in result.error_message
    assert rollback_calls == [snapshot_id]
    assert any(item.kind == "automatic_rollback" for item in result.evidence)


def test_prepare_change_cannot_bypass_license_gate(tmp_path):
    paths = RuntimePaths.discover(tmp_path / "runtime")
    bridge = FakeBridge(paths.snapshots)
    svc = CascadeurService(paths, client=bridge)
    svc._license_name = "Basic"
    svc._scene_available = True
    svc._rebuild_features()

    result = svc.prepare_change("inbetweening", "generation.inbetweening", {})

    assert result["ok"] is False
    assert result["error_code"] == "LICENSE_GATED"
    assert not bridge.calls


def test_action_manager_calls_are_bound_to_exact_installed_command(tmp_path):
    paths = RuntimePaths.discover(tmp_path / "runtime")
    svc = CascadeurService(paths, client=FakeBridge(paths.snapshots))

    assert svc.action_allowed("command.add.joint", "Add.Joint") is True
    assert svc.action_allowed("command.add.joint", "Scene.Undo") is False
    assert svc.action_allowed("daz_export", "Export to DAZ") is True
    assert svc.action_allowed("ragdoll", "Physics.Ragdoll") is False


def test_prepare_change_rejects_scene_feature_when_no_scene_is_active(tmp_path):
    paths = RuntimePaths.discover(tmp_path / "runtime")
    bridge = FakeBridge(paths.snapshots)
    bridge.state.update({"scene_id": None, "revision": None})
    svc = CascadeurService(paths, client=bridge)

    result = svc.prepare_change("constraint_point", "physics.constraint_point", {"point_ids": ["point"]})

    assert result["ok"] is False
    assert result["error_code"] == "POSTCONDITION_FAILED"
    assert "active Cascadeur scene" in result["error_message"]
    assert not any(call[1][0].name == "safety.snapshot" for call in bridge.calls)


def test_render_output_requires_prepared_change(tmp_path):
    paths = RuntimePaths.discover(tmp_path / "runtime")
    bridge = FakeBridge(paths.snapshots)
    svc = CascadeurService(paths, client=bridge)
    destination = tmp_path / "frame.png"
    refused = svc.execute("render_image", "render.image", {"path": str(destination)})
    assert refused.error_code.value == "CONFIRMATION_REQUIRED"
    prepared = svc.prepare_change("render_image", "render.image", {"path": str(destination)})
    assert prepared["ok"]
    assert prepared["operation"]["arguments"]["path"] == str(destination.resolve())


def test_async_render_output_waits_for_stable_nonzero_file(tmp_path):
    paths = RuntimePaths.discover(tmp_path / "runtime")
    svc = CascadeurService(paths, client=FakeBridge(paths.snapshots))
    destination = tmp_path / "frame.png"
    initial = ResultEnvelope(
        ok=True,
        feature_id="render_image",
        execution_mode=ExecutionMode.NATIVE,
        result={"scheduled": True},
    )

    def create_output():
        time.sleep(0.05)
        destination.write_bytes(b"PNG")

    writer = Thread(target=create_output)
    writer.start()
    result = svc._wait_for_output_file(initial, str(destination), 2, None)
    writer.join()
    assert result.ok
    assert result.result["bytes"] == 3
    assert result.result["scheduled"] is False
    assert any(item.kind == "host_file_postcondition" for item in result.evidence)


def test_ui_export_flow_verifies_exact_dialog_and_stable_file(tmp_path, monkeypatch):
    paths = RuntimePaths.discover(tmp_path / "runtime")
    bridge = FakeBridge(paths.snapshots)
    svc = CascadeurService(paths, client=bridge)
    destination = tmp_path / "model.usd"

    def complete(**arguments):
        destination.write_bytes(b"USD")
        return SimpleNamespace(
            action_id=arguments["action_id"],
            dialog_title=arguments["expected_dialog_title"],
            file_name_automation_id="1148",
            accept_automation_id="1",
            file_type="USD(*.usd)",
            completed_at=time.time(),
        )

    monkeypatch.setattr(service_module, "complete_file_dialog", complete)
    prepared = svc.prepare_change(
        "export_usd",
        "system.ui_file_flow",
        {
            "action_id": "File.Export.Scene.Usd...",
            "path": str(destination),
            "dialog_title": "Export. preset: scene",
            "file_type_extension": ".usd",
            "output": True,
        },
    )

    result = svc.commit_change(prepared["confirmation_token"], timeout=2)

    assert result.ok
    assert result.execution_mode == ExecutionMode.UIA
    assert result.result["path"] == str(destination)
    assert any(item.kind == "host_ui_file_dialog" for item in result.evidence)
    assert any(item.kind == "host_file_postcondition" for item in result.evidence)


def test_ui_import_flow_requires_changed_scene_revision(tmp_path, monkeypatch):
    paths = RuntimePaths.discover(tmp_path / "runtime")
    bridge = FakeBridge(paths.snapshots)
    svc = CascadeurService(paths, client=bridge)
    source = tmp_path / "model.usd"
    source.write_bytes(b"USD")

    original_execute = bridge.execute

    def execute(feature_id, operations, **kwargs):
        result = original_execute(feature_id, operations, **kwargs)
        if operations[0].name == "system.action_dispatch":
            bridge.state["revision"] = "rev-2"
        return result

    bridge.execute = execute
    monkeypatch.setattr(
        service_module,
        "complete_file_dialog",
        lambda **arguments: SimpleNamespace(
            action_id=arguments["action_id"],
            dialog_title=arguments["expected_dialog_title"],
            file_name_automation_id="1148",
            accept_automation_id="1",
            file_type="USD(*.usd)",
            completed_at=time.time(),
        ),
    )
    monkeypatch.setattr(service_module, "resolve_optional_rig_mode_helper", lambda **_arguments: None)
    prepared = svc.prepare_change(
        "import_usd",
        "system.ui_file_flow",
        {
            "action_id": "File.Import.Scene.Usd...",
            "path": str(source),
            "dialog_title": "Import. preset: scene",
            "file_type_extension": ".usd",
            "input": True,
        },
    )

    result = svc.commit_change(prepared["confirmation_token"], timeout=2)

    assert result.ok
    assert result.scene_revision == "rev-2"
    assert any(item.kind == "host_scene_postcondition" for item in result.evidence)


def test_open_scene_uses_bridge_path_and_native_window_postconditions(tmp_path, monkeypatch):
    paths = RuntimePaths.discover(tmp_path / "runtime")
    bridge = FakeBridge(paths.snapshots)
    svc = CascadeurService(paths, client=bridge)
    destination = tmp_path / "walk.casc"
    initial = ResultEnvelope(
        ok=True,
        feature_id="scene_open",
        execution_mode=ExecutionMode.NATIVE,
        scene_id="scene-2",
        scene_revision="rev-2",
        result={"path": str(destination), "loaded": True},
    )
    calls_before = len(bridge.calls)
    monkeypatch.setattr(service_module, "cascadeur_window_titles", lambda: [f"{destination} - Cascadeur"])

    result = svc._wait_for_open_scene(initial, str(destination), 2)

    assert result.ok
    assert result.result["stable_observations"] == 2
    assert result.result["window_title"].endswith(" - Cascadeur")
    assert len(bridge.calls) == calls_before
    assert any(item.kind == "host_window_postcondition" for item in result.evidence)


def test_auto_physics_snap_completes_known_modal_and_verifies_revision(tmp_path, monkeypatch):
    paths = RuntimePaths.discover(tmp_path / "runtime")
    bridge = FakeBridge(paths.snapshots)
    original_execute = bridge.execute

    def execute(feature_id, operations, **kwargs):
        if operations[0].name == "system.status":
            return ResultEnvelope(
                ok=True,
                feature_id=feature_id,
                execution_mode=ExecutionMode.NATIVE,
                scene_id="scene-1",
                scene_revision="rev-after",
                result={**bridge.state, "revision": "rev-after"},
            )
        return original_execute(feature_id, operations, **kwargs)

    bridge.execute = execute
    svc = CascadeurService(paths, client=bridge)
    initial = ResultEnvelope(
        ok=True,
        feature_id="auto_physics",
        execution_mode=ExecutionMode.NATIVE,
        scene_id="scene-1",
        scene_revision="rev-before",
        result={
            "before_revision": "rev-before",
            "after_revision": "rev-before",
            "completed_synchronously": False,
            "confirmation_may_be_pending": True,
        },
    )
    monkeypatch.setattr(
        service_module,
        "resolve_autophysics_snap_warning",
        lambda **_kwargs: SimpleNamespace(window_title="Warning", button="Yes", dismissed_at=time.time()),
    )

    result = svc._complete_auto_physics_snap(initial, 2)

    assert result.ok
    assert result.scene_revision == "rev-after"
    assert result.result["confirmation_button"] == "Yes"
    assert "scene.animation" in result.changed_entities
    assert any(item.kind == "host_ui_postcondition" for item in result.evidence)


def test_arbitrary_action_cannot_hide_behind_unrelated_feature(tmp_path):
    paths = RuntimePaths.discover(tmp_path / "runtime")
    svc = CascadeurService(paths, client=FakeBridge(paths.snapshots))
    result = svc.execute("status", "system.action_invoke", {"action_id": "Delete"})
    assert result.error_code.value == "INVALID_REQUEST"


@pytest.mark.parametrize(
    "operation_name",
    [
        "animation.key_reduce",
        "editing.mirror",
        "physics.collision_delete",
        "physics.auto_enable",
        "rig.joint_create",
        "rig.rig_info_create",
        "rig.ik_chain_create",
        "rig.rig_elements_create",
        "rig.additional_point_create",
        "rig.additional_box_create",
        "rig.spline_ik_create",
        "rig.twist",
        "layer.folder",
    ],
)
def test_every_known_mutation_requires_a_prepared_change(tmp_path, operation_name):
    paths = RuntimePaths.discover(tmp_path / "runtime")
    svc = CascadeurService(paths, client=FakeBridge(paths.snapshots))
    assert svc._operation_is_mutating(operation_name)


def test_prepare_rejects_feature_operation_privilege_substitution(tmp_path):
    paths = RuntimePaths.discover(tmp_path / "runtime")
    bridge = FakeBridge(paths.snapshots)
    svc = CascadeurService(paths, client=bridge)

    result = svc.prepare_change("status", "object.delete", {"ids": ["obj-1"]})

    assert result["ok"] is False
    assert result["error_code"] == "INVALID_REQUEST"
    assert bridge.calls == []


def test_action_cannot_disable_verification_without_postcondition(tmp_path):
    paths = RuntimePaths.discover(tmp_path / "runtime")
    svc = CascadeurService(paths, client=FakeBridge(paths.snapshots))
    result = svc.execute(
        "auto_posing",
        "system.action_invoke",
        {"action_id": "AutoPosing", "expect_change": False},
    )
    assert result.error_code.value == "INVALID_REQUEST"


def test_scene_mutation_requires_expected_revision(tmp_path):
    paths = RuntimePaths.discover(tmp_path / "runtime")
    svc = CascadeurService(paths, client=FakeBridge(paths.snapshots))
    result = svc.execute("timeline_set_frame", "timeline.set_frame", {"frame": 10})
    assert result.error_code.value == "CONFIRMATION_REQUIRED"


def test_transform_read_caches_identity_for_followup_write(tmp_path):
    paths = RuntimePaths.discover(tmp_path / "runtime")
    bridge = FakeBridge(paths.snapshots)
    svc = CascadeurService(paths, client=bridge)
    read = svc.execute("transform_get", "animation.transform_get", {"ids": ["obj-1"]})
    assert read.ok
    written = svc.execute(
        "transform_set",
        "animation.transform_set",
        {"ids": ["obj-1"], "position": [1, 2, 3]},
    )
    assert written.error_code == ErrorCode.CONFIRMATION_REQUIRED
    prepared = svc.prepare_change(
        "transform_set",
        "animation.transform_set",
        {"ids": ["obj-1"], "position": [1, 2, 3]},
    )
    written = svc.commit_change(prepared["confirmation_token"])
    assert written.ok
    _, _, kwargs = bridge.calls[-1]
    assert kwargs["scene_id"] == "scene-1"
    assert kwargs["expected_revision"] == prepared["scene_revision"]


def test_selection_remove_is_a_protected_mutation(tmp_path):
    paths = RuntimePaths.discover(tmp_path / "runtime")
    svc = CascadeurService(paths, client=FakeBridge(paths.snapshots))
    result = svc.batch(
        "selection_remove",
        [{"name": "selection.remove", "arguments": {"ids": ["obj-1"]}}],
        scene_id="scene-1",
        expected_revision="rev-1",
    )
    assert result.error_code == ErrorCode.CONFIRMATION_REQUIRED


def test_mutation_allowlist_comes_from_installed_schema(tmp_path):
    paths = RuntimePaths.discover(tmp_path / "runtime")
    svc = CascadeurService(paths, client=FakeBridge(paths.snapshots))
    assert svc.csc_mutate_allowed([{"attr": "set_current_frame", "call": True}])
    assert not svc.csc_mutate_allowed([{"attr": "__subclasses__", "call": True}])


@pytest.mark.parametrize(
    ("feature_id", "operation_name"),
    [
        ("csc_query", "system.csc_query"),
        ("csc_mutate", "system.csc_mutate"),
        ("developer_execute_python", "system.developer_execute_python"),
    ],
)
def test_production_policy_rejects_generic_runtime_apis(tmp_path, feature_id, operation_name):
    paths = RuntimePaths.discover(tmp_path / "runtime")
    svc = CascadeurService(paths, client=FakeBridge(paths.snapshots))

    result = svc.execute(feature_id, operation_name, {})

    assert result.error_code == ErrorCode.INVALID_REQUEST
    assert "disabled in production" in result.error_message


def test_unknown_snapshot_is_rejected_before_bridge_call(tmp_path):
    paths = RuntimePaths.discover(tmp_path / "runtime")
    bridge = FakeBridge(paths.snapshots)
    result = CascadeurService(paths, client=bridge).prepare_rollback("missing")
    assert result["error_code"] == "INVALID_REQUEST"
    assert not bridge.calls


def test_rollback_opens_a_working_clone_and_preserves_immutable_snapshot(tmp_path):
    paths = RuntimePaths.discover(tmp_path / "runtime")
    bridge = FakeBridge(paths.snapshots)
    svc = CascadeurService(paths, client=bridge)
    prepared = svc.prepare_change("scene_new", "scene.new", {})
    snapshot = Path(prepared["backup_path"])
    before = snapshot.read_bytes()

    rollback_prepared = svc.prepare_rollback(prepared["snapshot_id"])
    assert rollback_prepared["ok"]
    result = svc.rollback(rollback_prepared["confirmation_token"], timeout=2)

    assert result.ok
    assert Path(result.result["path"]).name.endswith(".working.casc")
    assert Path(result.result["path"]) != snapshot
    assert snapshot.read_bytes() == before


def test_background_job_persists_result(tmp_path):
    paths = RuntimePaths.discover(tmp_path / "runtime")
    bridge = FakeBridge(paths.snapshots)
    svc = CascadeurService(paths, client=bridge)
    submitted = svc.submit_job("status", "system.status")
    deadline = time.monotonic() + 2
    record = None
    while time.monotonic() < deadline:
        record = svc.jobs.get(submitted["job_id"])
        if record and record.status in ("succeeded", "failed"):
            break
        time.sleep(0.01)
    assert record is not None and record.status == "succeeded"
    assert record.result is not None and record.result.ok


def test_job_id_cannot_escape_job_store_or_echo_external_json(tmp_path):
    paths = RuntimePaths.discover(tmp_path / "runtime")
    external = tmp_path / "sensitive.json"
    external.write_text('{"token":"must-not-be-read"}', encoding="utf-8")
    svc = CascadeurService(paths, client=FakeBridge(paths.snapshots))

    with pytest.raises(ValueError, match="Invalid job id"):
        svc.jobs.get(str(external.with_suffix("")))


def test_wrong_build_gates_every_discovered_route(tmp_path):
    paths = RuntimePaths.discover(tmp_path / "runtime")
    bridge = FakeBridge(paths.snapshots)
    svc = CascadeurService(paths, client=bridge)
    svc.installation["version"] = "2026.1.3.0.99999"
    svc.installation["compatible"] = False
    svc._rebuild_features()

    assert all(item.state.value == "unsupported_version" for item in svc.features)
    result = svc.execute("scene_summary", "scene.summary")
    assert result.error_code == ErrorCode.UNSUPPORTED_VERSION
    assert bridge.calls == []


def test_failed_job_can_retry_from_persisted_contract(tmp_path):
    paths = RuntimePaths.discover(tmp_path / "runtime")
    svc = CascadeurService(paths, client=FakeBridge(paths.snapshots))
    original = svc.jobs.create(
        "status",
        operation_name="system.status",
        arguments={},
        timeout=12,
    )
    svc.jobs.update(original.job_id, status="failed", progress=1, log="test failure")
    retried = svc.retry_job(original.job_id)
    assert retried["retry_of"] == original.job_id
    assert retried["attempt"] == 2
    deadline = time.monotonic() + 2
    record = None
    while time.monotonic() < deadline:
        record = svc.jobs.get(retried["job_id"])
        if record and record.status == "succeeded":
            break
        time.sleep(0.01)
    assert record is not None and record.status == "succeeded"
