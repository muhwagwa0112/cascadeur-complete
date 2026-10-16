"""Inventory of MCP tools that send scene mutations through ``service.execute``.

``CascadeurService.execute`` refuses every mutating operation with
CONFIRMATION_REQUIRED (only change_prepare/change_commit may mutate), so these
tool paths can never succeed. Every tool is called with a recording stand-in
for the service, once per value of each enum argument, and the operations it
hands to ``execute`` are classified with the host's own mutation rule.

The known list is the migration backlog for converting these paths to
``*_prepare`` (docs/REFACTOR_PREP.md §5-1). Converting a tool removes its entry.
"""

from __future__ import annotations

from typing import Any

import pytest
from mcp import Client

from cascadeur_complete import server
from cascadeur_complete.models import ExecutionMode, ResultEnvelope
from cascadeur_complete.product_catalog import PRODUCT_CATALOG
from tests.test_operation_contract import OPERATION, _host_is_mutating

KNOWN_DIRECT_MUTATION_TOOLS = {
    "action_invoke": {"system.action_invoke"},
    "animation_curve": {"animation.interpolation_set", "animation.tangent_set"},
    "auto_physics_enable": {"physics.auto_enable"},
    "auto_physics_snap": {"physics.auto_snap"},
    "auto_posing": {"generation.auto_posing"},
    "io_transfer": {
        "io.export_dae",
        "io.export_fbx",
        "io.export_glb",
        "io.export_gltf",
        "io.export_image",
        "io.export_usd",
        "io.export_video",
        "io.export_vrm",
        "io.import_audio",
        "io.import_dae",
        "io.import_fbx",
        "io.import_glb",
        "io.import_gltf",
        "io.import_image",
        "io.import_scene_to_current",
        "io.import_usd",
        "io.import_video",
        "io.import_vrm",
    },
    "key_edit": {"animation.key_add", "animation.key_delete"},
    "layer_write": {"layer.activate", "layer.create", "layer.delete", "layer.folder", "layer.lock", "layer.visibility"},
    "object_write": {
        "object.create",
        "object.parent",
        "object.rename",
        "object.unparent",
        "objects.delete",
        "objects.duplicate",
    },
    "redo": {"system.redo"},
    "render_output": {"render.image", "render.video", "render.viewport_capture"},
    "scene_file": {"scene.activate", "scene.close", "scene.new", "scene.open", "scene.save", "scene.save_as"},
    "selection_edit": {"selection.add", "selection.remove", "selection.set"},
    "timeline_set_frame": {"timeline.set_frame"},
    "transform_edit": {"animation.transform_set"},
    "undo": {"system.undo"},
    "viewport_camera": {"render.camera_activate", "render.camera_view"},
    "viewport_mode": {"system.view_mode_set"},
}


class RecordingService:
    """Answers every service call with a successful empty envelope and records ``execute``."""

    def __init__(self) -> None:
        self.executed: list[tuple[str, str]] = []

    @staticmethod
    def _envelope(feature_id: str = "probe") -> ResultEnvelope:
        return ResultEnvelope(ok=True, feature_id=feature_id, execution_mode=ExecutionMode.NATIVE, result={})

    def execute(self, feature_id: str, operation: str | None = None, *args: Any, **kwargs: Any) -> ResultEnvelope:
        operation = operation or kwargs.get("operation_name") or kwargs.get("operation")
        self.executed.append((feature_id, str(operation)))
        return self._envelope(feature_id)

    def __getattr__(self, name: str):
        def answer(*args: Any, **kwargs: Any) -> ResultEnvelope:
            return self._envelope()

        return answer


# Free-form feature ids: probe every catalog import/export feature.
FEATURE_ID_SAMPLES = sorted(item.id for item in PRODUCT_CATALOG.features if item.family == "io")


def _dummy(schema: dict[str, Any]) -> Any:
    if "enum" in schema:
        return schema["enum"][0]
    for option in schema.get("anyOf", ()):
        if option.get("type") != "null":
            return _dummy(option)
    if schema.get("type") == "array":
        item = schema.get("items", {})
        return [0.0, 0.0, 0.0] if item.get("type") in ("number", "integer") else ["probe"]
    return {"integer": 1, "number": 1.0, "boolean": False, "object": {}}.get(schema.get("type"), "probe")


def _enum_values(schema: dict[str, Any]) -> list[Any]:
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
            values = FEATURE_ID_SAMPLES if name == "feature_id" else _enum_values(schema)
            variants.extend({**base, name: value} for value in values)
    return variants


@pytest.fixture
def recorder(monkeypatch):
    recording = RecordingService()
    monkeypatch.setattr(server, "service", lambda: recording)
    return recording


@pytest.mark.asyncio
async def test_direct_mutation_tools_match_the_migration_backlog(recorder):
    found: dict[str, set[str]] = {}
    async with Client(server.mcp) as client:
        for tool in (await client.list_tools()).tools:
            for arguments in _argument_sets(tool.input_schema):
                recorder.executed.clear()
                await client.call_tool(tool.name, arguments)
                mutating = {
                    operation
                    for _feature, operation in recorder.executed
                    if OPERATION.match(operation) and _host_is_mutating(operation)
                }
                if mutating:
                    found.setdefault(tool.name, set()).update(mutating)
    assert found == KNOWN_DIRECT_MUTATION_TOOLS
