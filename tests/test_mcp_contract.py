import pytest
from mcp import Client

from cascadeur_complete.server import mcp


@pytest.mark.asyncio
async def test_mcp_lists_expected_tools_and_resources():
    async with Client(mcp) as client:
        tools = await client.list_tools()
        names = {item.name for item in tools.tools}
        assert {
            "cascadeur_status",
            "cascadeur_logs",
            "cascadeur_tool_inspect",
            "setting_get",
            "viewport_mode",
            "feature_search",
            "scene_summary",
            "operation_batch",
            "change_prepare",
            "change_commit",
            "change_rollback",
            "csc_query",
            "csc_mutate",
            "action_invoke",
            "ui_flow_prepare",
            "tool_call",
            "external_workflow",
            "job_submit",
            "job_status",
            "job_cancel",
            "job_retry",
            "timeline_get",
            "transform_edit",
            "layer_list",
            "layer_write",
            "key_edit",
            "render_output",
            "render_object_create_prepare",
            "auto_posing",
            "auto_physics_snap",
            "key_reduction_prepare",
            "mirror_prepare",
            "cycle_list",
            "physics_state",
            "rig_state",
            "constraint_driver_catalog",
            "rigid_body_mass_prepare",
            "joint_create_prepare",
            "rig_info_create_prepare",
            "ik_chain_create_prepare",
            "rig_elements_create_prepare",
            "additional_point_controller_prepare",
            "additional_box_controller_prepare",
            "spline_ik_create_prepare",
            "twist_prepare",
            "center_of_mass_prepare",
            "collision_create_prepare",
            "collision_delete_prepare",
            "transform_constraint_prepare",
            "point_constraint_prepare",
            "ballistic_create_prepare",
            "selection_edit",
            "object_delete_prepare",
        } <= names
        resources = await client.list_resources()
        uris = {str(item.uri) for item in resources.resources}
        assert {
            "cascadeur://capabilities",
            "cascadeur://features",
            "cascadeur://csc/schema",
            "cascadeur://actions",
            "cascadeur://scene/summary",
            "cascadeur://scene/objects",
        } <= uris
        templates = await client.list_resource_templates()
        template_uris = {item.uri_template for item in templates.resource_templates}
        assert "cascadeur://jobs/{job_id}" in template_uris
        assert "cascadeur://snapshots/{snapshot_id}" in template_uris
