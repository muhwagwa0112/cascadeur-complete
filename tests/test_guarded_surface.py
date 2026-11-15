"""The real in-process MCP surface exposes guarded contracts, without apps."""
import pytest
from mcp import Client

from cascadeur_complete import server


@pytest.mark.asyncio
async def test_recipe_and_source_contracts_are_reachable_over_mcp():
    async with Client(server.mcp) as client:
        tools = {item.name: item for item in (await client.list_tools()).tools}
        assert {f"recipe_{name}" for name in ("plan", "authorize", "start", "status", "cancel", "resume", "artifacts")} <= tools.keys()
        assert {"source_capture", "source_validate", "request_status", "request_reconcile", "interpolation_refresh_prepare"} <= tools.keys()
        schema = tools["recipe_plan"].input_schema
        assert "RecipeSpec" in schema["$defs"]
        assert schema["$defs"]["RecipeSpec"]["additionalProperties"] is False
        assert "source_binding" in tools["change_prepare"].input_schema["properties"]
        assert tools["motion_cleanup_prepare"].input_schema["properties"]["steps"]["default"] is False


@pytest.mark.asyncio
async def test_old_mutation_calls_keep_signatures_and_never_dispatch(monkeypatch):
    def no_service():
        raise AssertionError("Deprecated mutation must not instantiate or dispatch a service")
    monkeypatch.setattr(server, "service", no_service)
    async with Client(server.mcp) as client:
        for name, arguments in (
            ("timeline_set_frame", {"frame": 12, "scene_id": "old", "expected_revision": "r"}),
            ("transform_edit", {"action": "set", "ids": ["a"], "position": [1,2,3]}),
            ("scene_file", {"action": "open", "path": "C:/clip.casc", "confirmation_token": "old"}),
            ("transform_edit", {"action": "get", "refresh": True}),
        ):
            result = await client.call_tool(name, arguments)
            assert not result.is_error
            assert result.structured_content["error_code"] == "CONFIRMATION_REQUIRED"
            assert result.structured_content["dispatched"] is False
