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
            "viewport_mode",
            "feature_search",
            "scene_summary",
            "operation_batch",
            "change_prepare",
            "change_commit",
            "change_rollback_prepare",
            "change_rollback",
            "action_invoke_prepare",
            "ui_flow_prepare",
            "external_workflow",
            "job_submit",
            "job_status",
            "job_cancel",
            "job_retry",
            "timeline_get",
            "transform_edit",
            "layer_list",
            "layer_write_prepare",
            "key_edit",
            "render_output_prepare",
            "render_object_create_prepare",
            "auto_posing_prepare",
            "auto_physics_snap_prepare",
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
            "motion_cleanup_analyze",
            "motion_cleanup_prepare",
            "viewport_mode_prepare",
            "selection_edit_prepare",
            "object_write_prepare",
            "scene_file_prepare",
            "io_transfer_prepare",
            "timeline_set_frame_prepare",
            "transform_edit_prepare",
            "key_edit_prepare",
            "animation_curve_prepare",
            "viewport_camera_prepare",
            "auto_physics_enable_prepare",
            "undo_prepare",
            "redo_prepare",
        } <= names
        assert {
            "tool_call",
            "csc_query",
            "csc_mutate",
            "developer_execute_python",
            "cascadeur_tool_inspect",
            "setting_get",
            # Direct mutation wrappers replaced by *_prepare tools.
            "object_write",
            "io_transfer",
            "timeline_set_frame",
            "layer_write",
            "render_output",
            "auto_posing",
            "auto_physics_enable",
            "auto_physics_snap",
            "action_invoke",
            "undo",
            "redo",
        }.isdisjoint(names)
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
