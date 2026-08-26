# Public MCP Tool Routing

This catalog mirrors the 70 production tools in the `cascadeur-complete` MCP contract. Prefer the most specific tool in the relevant row. Capability and scene state still determine whether a listed tool can execute. Generic csc/tool/Python execution, runtime tool introspection, and arbitrary settings reads are compiled out of release builds.

<!-- MCP-TOOLS-START -->

| Group | Purpose | Tools |
|---|---|---|
| Health and discovery | Connection/version/license, level-only logs, view modes, feature registry, inventory | `cascadeur_status`, `cascadeur_logs`, `viewport_mode`, `feature_search`, `feature_describe`, `inventory_refresh` |
| Persistent jobs | Submit, inspect, cancel, or retry retained non-destructive work | `job_submit`, `job_status`, `job_cancel`, `job_retry` |
| Scene and object context | Scene summary, paginated objects, selection, object reads/writes, one-entry batching | `scene_summary`, `scene_objects`, `selection_edit`, `object_delete_prepare`, `object_read`, `object_write`, `operation_batch` |
| Protection and recovery | Snapshot/dry-run, commit/cancel/two-step rollback, exact UI file-flow preparation | `change_prepare`, `change_commit`, `change_cancel`, `change_rollback_prepare`, `change_rollback`, `scene_exchange_prepare`, `ui_flow_prepare` |
| Scene files and interchange | CASC lifecycle and registered import/export routes | `scene_file`, `io_transfer` |
| Timeline and animation | Playhead, transforms, layers, keys, curves, and interval selection | `timeline_set_frame`, `timeline_get`, `transform_edit`, `layer_list`, `layer_write`, `key_edit`, `animation_curve`, `timeline_select_interval` |
| Camera and render | Camera/view state, protected camera/light creation, file output | `viewport_camera`, `render_object_create_prepare`, `render_output` |
| Generation and editing | AutoPosing, prerequisites, Root Motion, Inbetweening, Unbaking, key reduction, mirror, cycles | `auto_posing`, `generation_state`, `root_motion_prepare`, `inbetweening_prepare`, `animation_unbaking_prepare`, `key_reduction_prepare`, `mirror_prepare`, `cycle_list` |
| Physics and rig inspection | AutoPhysics readiness, physics/rig inventory, valid constraint drivers | `auto_physics_state`, `physics_state`, `rig_state`, `constraint_driver_catalog` |
| Rig construction | Mass, Joint/RigInfo, IK, manual rig elements, extra controllers, Spline IK, twist | `rigid_body_mass_prepare`, `joint_create_prepare`, `rig_info_create_prepare`, `ik_chain_create_prepare`, `rig_elements_create_prepare`, `additional_point_controller_prepare`, `additional_box_controller_prepare`, `spline_ik_create_prepare`, `twist_prepare` |
| Physics construction | CoM, collisions, constraints, ballistics, AutoPhysics enable/snap | `center_of_mass_prepare`, `collision_create_prepare`, `collision_delete_prepare`, `transform_constraint_prepare`, `point_constraint_prepare`, `ballistic_create_prepare`, `auto_physics_enable`, `auto_physics_snap` |
| Low-level and external | Exact registered actions, gated DCC workflow, and history | `action_invoke`, `external_workflow`, `undo`, `redo` |

<!-- MCP-TOOLS-END -->

## Tool-family decisions

### Diagnose or discover

Start with `cascadeur_status`, then `feature_search` and `feature_describe`. Release builds do not expose runtime tool introspection, arbitrary setting reads, or generic call chains.

### Read a scene

Use `scene_summary`, `scene_objects`, `object_read`, `timeline_get`, `layer_list`, `generation_state`, `rig_state`, `physics_state`, and camera-state actions. Read only the domains relevant to the request.

### Make an ordinary revision-checked edit

Use `selection_edit`, `timeline_set_frame`, `transform_edit`, non-destructive `layer_write`/`key_edit`/`animation_curve` actions, camera updates, or `auto_physics_enable`. Pass the latest scene identity/revision and re-read after success.

### Make a protected change

Use a dedicated `*_prepare` tool when available. Otherwise prepare the exact operation with `change_prepare` and execute only via `change_commit`. `render_output`, `auto_posing`, `scene_file`, `io_transfer`, or another direct wrapper may correctly return `CONFIRMATION_REQUIRED`; that response means switch to the generic protected contract, not that the operation failed permanently.

### Use an exact UI file flow

Use `scene_exchange_prepare` for USD/GLB/GLTF/VRM. Use `ui_flow_prepare` only for a `flow_id` returned by the registry. Commit once; if the dialog is locked or times out, inspect outcome before retrying.

### Handle long work

Use `job_submit` only for non-destructive operations. Poll `job_status`; cancel or retry from persisted state. Protected changes remain synchronous token-bound operations.

### Escalate below the task API

Use `action_invoke` only when an exact registered feature requires it. Generic tool/csc/Python execution is absent from production builds and belongs in a separately compiled developer build.

## Common feature/operation pairs

These pairs are useful with `change_prepare` when a direct tool returns `CONFIRMATION_REQUIRED`:

| Intent | Feature ID | Operation name |
|---|---|---|
| New/open/close/save-as scene | `scene_new`, `scene_open`, `scene_close`, `scene_save_as` | `scene.new`, `scene.open`, `scene.close`, `scene.save_as` |
| FBX/DAE import or export | `import_fbx`, `import_dae`, `export_fbx`, `export_dae` | `io.import_fbx`, `io.import_dae`, `io.export_fbx`, `io.export_dae` |
| Create/parent/unparent/delete object | `object_create`, `object_parent`, `object_unparent`, `object_delete` | `object.create`, `object.parent`, `object.unparent`, `object.delete` |
| Delete key/layer | `key_delete`, `layer_delete` | `animation.key_delete`, `layer.delete` |
| AutoPosing | `auto_posing` | `generation.auto_posing` |
| Viewport capture/still render | `viewport_capture`, `render_image` | `render.viewport_capture`, `render.image` |
| AutoPhysics snap | `auto_physics` | `physics.auto_snap` |

Confirm exact arguments with the tool schema and `feature_describe`; this table is routing guidance, not permission or a substitute for live capability state.

When the MCP contract changes, run `scripts/validate_tool_coverage.py` from the skill directory (or pass `--server`) and update this catalog before publishing the skill.
