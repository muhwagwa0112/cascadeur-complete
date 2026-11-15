"""Every scene or file change goes through a ``*_prepare`` tool.

``CascadeurService.execute`` refuses every mutating operation with
CONFIRMATION_REQUIRED (only change_prepare/change_commit may mutate), so a tool
that hands a mutation to ``execute`` can never succeed. Every tool is called
with a recording stand-in for the service, once per value of each enum
argument, and the operations it hands to ``execute`` and ``prepare_change`` are
checked: none may reach ``execute`` as a mutation, and each ``*_prepare`` tool
must bind exactly the feature/operation pairs listed here.

Tools that pass caller-chosen operations on (operation_batch, job_submit,
feature_read) hand them to service methods that refuse mutations themselves;
tests/test_service.py covers those refusals.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from mcp import Client

from cascadeur_complete import server
from cascadeur_complete.product_catalog import PRODUCT_CATALOG
from tests.test_operation_contract import OPERATION, _host_is_mutating

# Free-form feature ids: probe every catalog import/export feature.
FEATURE_ID_SAMPLES = sorted(item.id for item in PRODUCT_CATALOG.features if item.family == "io")


IO_OPERATIONS = {
    "blender_export": "io.export_fbx",
    "export_dae": "io.export_dae",
    "export_fbx": "io.export_fbx",
    "export_image": "io.export_image",
    "import_audio": "io.import_audio",
    "import_dae": "io.import_dae",
    "import_fbx": "io.import_fbx",
    "selection_groups_import": "io.selection_groups_import",
}

# The tools that replaced the direct mutation paths, and what each one prepares.
PREPARE_TOOL_OPERATIONS = {
    "action_invoke_prepare": {(feature, "system.action_invoke") for feature in [*FEATURE_ID_SAMPLES, "probe"]},
    "animation_curve_prepare": {
        ("interpolation_set", "animation.interpolation_set"),
        ("tangent_set", "animation.tangent_set"),
    },
    "auto_physics_enable_prepare": {("auto_physics_enable", "physics.auto_enable")},
    "auto_physics_snap_prepare": {("auto_physics", "physics.auto_snap")},
    "auto_posing_prepare": {("auto_posing", "generation.auto_posing")},
    "io_transfer_prepare": set(IO_OPERATIONS.items()),
    "key_edit_prepare": {("key_add", "animation.key_add"), ("key_delete", "animation.key_delete")},
    "layer_write_prepare": {
        ("layer_activate", "layer.activate"),
        ("layer_create", "layer.create"),
        ("layer_delete", "layer.delete"),
        ("layer_folder", "layer.folder"),
        ("layer_lock", "layer.lock"),
        ("layer_visibility", "layer.visibility"),
    },
    "object_write_prepare": {
        ("object_create", "object.create"),
        ("object_delete", "objects.delete"),
        ("object_duplicate", "objects.duplicate"),
        ("object_parent", "object.parent"),
        ("object_rename", "object.rename"),
        ("object_unparent", "object.unparent"),
    },
    "redo_prepare": {("redo", "system.redo")},
    "render_output_prepare": {
        ("render_image", "render.image"),
        ("viewport_capture", "render.viewport_capture"),
    },
    "scene_file_prepare": {
        (f"scene_{action}", f"scene.{action}") for action in ("activate", "close", "new", "open", "save", "save_as")
    },
    "selection_edit_prepare": {
        ("selection_add", "selection.add"),
        ("selection_remove", "selection.remove"),
        ("selection_set", "selection.set"),
    },
    "timeline_set_frame_prepare": {("timeline_set_frame", "timeline.set_frame")},
    "transform_edit_prepare": {("transform_set", "animation.transform_set")},
    "undo_prepare": {("undo", "system.undo")},
    "viewport_camera_prepare": {
        ("camera_activate", "render.camera_activate"),
        ("camera_view", "render.camera_view"),
    },
    "viewport_mode_prepare": {("view_mode", "system.view_mode_set")},
}


class Anything(dict):
    """An empty dict that also answers any attribute or call, so every tool can run to completion."""

    ok = True
    adapter_id = "probe-adapter"
    route = "probe"
    dependency = None
    execution_mode = "Native"

    def __getattr__(self, name: str) -> Anything:
        if name.startswith("__"):  # leave protocol lookups (pickling, pydantic) alone
            raise AttributeError(name)
        return Anything()

    def __call__(self, *args: Any, **kwargs: Any) -> Anything:
        return Anything()

    @property
    def result(self) -> dict[str, Any]:
        return {}

    @property
    def state(self) -> Any:
        return SimpleNamespace(value="available")

    def model_dump(self, **kwargs: Any) -> dict[str, Any]:
        return {"ok": True}


class RecordingService(Anything):
    """Records the operations handed to ``execute`` and ``prepare_change``; answers everything else."""

    def __init__(self) -> None:
        super().__init__()
        self.executed: list[tuple[str, str]] = []
        self.prepared: list[tuple[str, str]] = []

    def execute(self, feature_id: str, operation: str | None = None, *args: Any, **kwargs: Any) -> Anything:
        self.executed.append((feature_id, str(operation or kwargs.get("operation_name"))))
        return Anything()

    def action_allowed(self, feature_id: str, action_id: str) -> bool:
        return True

    def prepare_change(self, feature_id: str, operation_name: str, *args: Any, **kwargs: Any) -> dict[str, Any]:
        self.prepared.append((feature_id, operation_name))
        return {"ok": True, "confirmation_token": "probe"}


def _dummy(schema: dict[str, Any]) -> Any:
    if "const" in schema:
        return schema["const"]
    if "enum" in schema:
        return schema["enum"][0]
    for option in schema.get("anyOf", ()):
        if option.get("type") != "null":
            return _dummy(option)
    if schema.get("type") == "array":
        item = schema.get("items", {})
        if item.get("type") in ("number", "integer"):
            return [0.0, 0.0, 0.0]
        return [{}] if item.get("type") == "object" else ["probe"]
    return {"integer": 1, "number": 1.0, "boolean": False, "object": {}}.get(schema.get("type"), "probe")


def _enum_values(schema: dict[str, Any]) -> list[Any]:
    if "const" in schema:
        return [schema["const"]]
    if "enum" in schema:
        return list(schema["enum"])
    values: list[Any] = []
    for option in schema.get("anyOf", ()):
        values.extend(option.get("enum", ()))
    return values


def _argument_sets(input_schema: dict[str, Any]) -> list[dict[str, Any]]:
    """Required-only and fully-populated calls, each crossed with every enum value."""
    properties = input_schema.get("properties", {})
    required = {name: _dummy(properties[name]) for name in input_schema.get("required", ())}
    populated = {name: _dummy(schema) for name, schema in properties.items()}
    variants = []
    for base in (required, populated):
        variants.append(dict(base))
        for name, schema in properties.items():
            values = _enum_values(schema) or (FEATURE_ID_SAMPLES if name == "feature_id" else [])
            variants.extend({**base, name: value} for value in values)
    return variants


@pytest.fixture
def recorder(monkeypatch):
    recording = RecordingService()
    monkeypatch.setattr(server, "service", lambda: recording)
    return recording


# Tools the stand-in service cannot drive to completion. Every other tool must run
# without an error, so the checks below are not vacuous for it.
KNOWN_STAND_IN_ERRORS = {
    "feature_search": "returns a list; the stand-in answers with a dict",
    "motion_cleanup_analyze": "reads real scene objects through the bridge client",
    "motion_cleanup_prepare": "reads real scene objects through the bridge client",
}


async def _record_every_tool(recorder) -> tuple[dict[str, set[str]], dict[str, set[tuple[str, str]]], set[str]]:
    executed: dict[str, set[str]] = {}
    prepared: dict[str, set[tuple[str, str]]] = {}
    failed: set[str] = set()
    async with Client(server.mcp) as client:
        for tool in (await client.list_tools()).tools:
            for arguments in _argument_sets(tool.input_schema):
                recorder.executed.clear()
                recorder.prepared.clear()
                if (await client.call_tool(tool.name, arguments)).is_error:
                    failed.add(tool.name)
                mutating = {
                    operation
                    for _feature, operation in recorder.executed
                    if OPERATION.match(operation) and _host_is_mutating(operation)
                }
                if mutating:
                    executed.setdefault(tool.name, set()).update(mutating)
                bound = {pair for pair in recorder.prepared if OPERATION.match(pair[1])}
                if bound:
                    prepared.setdefault(tool.name, set()).update(bound)
    return executed, prepared, failed


@pytest.mark.asyncio
async def test_no_tool_sends_a_mutation_through_execute(recorder):
    executed, _prepared, failed = await _record_every_tool(recorder)
    assert failed == set(KNOWN_STAND_IN_ERRORS)
    assert executed == {}


@pytest.mark.asyncio
async def test_prepare_tools_bind_their_mutating_operations(recorder):
    _executed, prepared, _failed = await _record_every_tool(recorder)
    assert {name: prepared.get(name) for name in PREPARE_TOOL_OPERATIONS} == PREPARE_TOOL_OPERATIONS
    for name in PREPARE_TOOL_OPERATIONS:
        assert all(_host_is_mutating(operation) for _feature, operation in prepared[name]), name


def test_prepare_tool_operations_pass_the_service_binding_rules(tmp_path):
    from cascadeur_complete.paths import RuntimePaths
    from cascadeur_complete.service import CascadeurService
    from tests.test_service import FakeBridge

    paths = RuntimePaths.discover(tmp_path / "runtime")
    svc = CascadeurService(paths, client=FakeBridge(paths.snapshots))
    errors = {
        (feature_id, operation): svc._operation_binding_error(svc.feature(feature_id), operation, {})
        for name, pairs in PREPARE_TOOL_OPERATIONS.items()
        if name != "action_invoke_prepare"  # bound per action id, checked by action_allowed
        for feature_id, operation in pairs
    }
    assert {pair: error for pair, error in errors.items() if error} == {}


def test_prepare_tool_operations_reach_a_bridge_handler():
    from tests.bridge_support import inline_operations, loaded_bridge

    with loaded_bridge("cascadeur_complete_bridge_prepare_tools") as (_runtime, registry):
        handled = set(registry.registered_operations()) | inline_operations()
    operations = {operation for pairs in PREPARE_TOOL_OPERATIONS.values() for _feature, operation in pairs}
    assert operations - handled == set()
