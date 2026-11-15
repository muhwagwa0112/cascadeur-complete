# Public MCP Tool Routing

This catalog mirrors the 82 production tools in the `cascadeur-complete` MCP contract. Prefer the most specific tool in the relevant row. Capability and scene state still determine whether a listed tool can execute. Generic csc/tool/Python execution, runtime tool introspection, and arbitrary settings reads are compiled out of release builds.

<!-- MCP-TOOLS-START -->

| Group | Purpose | Tools |
|---|---|---|
| Health and discovery | Connection/version/license, level-only logs, view modes, feature registry, inventory | `cascadeur_status`, `cascadeur_logs`, `viewport_mode`, `viewport_mode_prepare`, `feature_search`, `feature_describe`, `inventory_refresh` |
| Persistent jobs | Submit, inspect, cancel, or retry retained non-destructive work | `job_submit`, `job_status`, `job_cancel`, `job_retry` |
| Scene and object context | Scene summary, paginated objects, selection, object reads/writes, one-entry batching | `scene_summary`, `scene_objects`, `selection_edit`, `selection_edit_prepare`, `object_delete_prepare`, `object_read`, `object_write_prepare`, `operation_batch` |
| Protection and recovery | Snapshot/dry-run, commit/cancel/two-step rollback, exact UI file-flow preparation | `change_prepare`, `change_commit`, `change_cancel`, `change_rollback_prepare`, `change_rollback`, `scene_exchange_prepare`, `ui_flow_prepare` |
| Adapter-bound features | Prepare or read any feature that has a dedicated adapter, using the argument contract from `feature_describe`; registered Cascadeur file dialogs | `feature_prepare`, `feature_read`, `file_dialog_prepare` |
| Scene files and interchange | CASC lifecycle and native import/export routes | `scene_file`, `scene_file_prepare`, `io_transfer_prepare` |
| Timeline and animation | Playhead, transforms, layers, keys, curves, and interval selection | `timeline_set_frame_prepare`, `timeline_get`, `transform_edit`, `transform_edit_prepare`, `layer_list`, `layer_write_prepare`, `key_edit`, `key_edit_prepare`, `animation_curve`, `animation_curve_prepare`, `timeline_select_interval` |
| Camera and render | Camera/view state, protected camera/light creation, file output | `viewport_camera`, `viewport_camera_prepare`, `render_object_create_prepare`, `render_output_prepare` |
| Generation and editing | AutoPosing, prerequisites, Root Motion, Inbetweening, Unbaking, key reduction, mirror, cycles | `auto_posing_prepare`, `generation_state`, `root_motion_prepare`, `inbetweening_prepare`, `animation_unbaking_prepare`, `key_reduction_prepare`, `mirror_prepare`, `cycle_list` |
| Mocap cleanup | Whole-clip foot-skate/finger measurement and one-shot contact or finger correction (protected key write) | `motion_cleanup_analyze`, `motion_cleanup_prepare` |
| Physics and rig inspection | AutoPhysics readiness, physics/rig inventory, valid constraint drivers | `auto_physics_state`, `physics_state`, `rig_state`, `constraint_driver_catalog` |
| Rig construction | Mass, Joint/RigInfo, IK, manual rig elements, extra controllers, Spline IK, twist | `rigid_body_mass_prepare`, `joint_create_prepare`, `rig_info_create_prepare`, `ik_chain_create_prepare`, `rig_elements_create_prepare`, `additional_point_controller_prepare`, `additional_box_controller_prepare`, `spline_ik_create_prepare`, `twist_prepare` |
| Physics construction | CoM, collisions, constraints, ballistics, AutoPhysics enable/snap | `center_of_mass_prepare`, `collision_create_prepare`, `collision_delete_prepare`, `transform_constraint_prepare`, `point_constraint_prepare`, `ballistic_create_prepare`, `auto_physics_enable_prepare`, `auto_physics_snap_prepare` |
| Low-level and external | Exact registered actions, gated DCC workflow, and history | `action_invoke_prepare`, `external_workflow`, `undo_prepare`, `redo_prepare` |

<!-- MCP-TOOLS-END -->

## Tool-family decisions

### Diagnose or discover

Start with `cascadeur_status`, then `feature_search` and `feature_describe`. Release builds do not expose runtime tool introspection, arbitrary setting reads, or generic call chains.

### Read a scene

Use `scene_summary`, `scene_objects`, `object_read`, `timeline_get`, `layer_list`, `generation_state`, `rig_state`, `physics_state`, and camera-state actions. Read only the domains relevant to the request.

### Make an edit

Every scene or file change is two calls: a `*_prepare` tool returns a confirmation token bound to the current scene, revision and selection, and `change_commit(token)` runs exactly that operation. Read tools (`selection_edit`, `transform_edit`, `key_edit`, `animation_curve`, `viewport_camera`, `viewport_mode`, `scene_file`) only read; their writes live in the tool of the same name with a `_prepare` suffix. Re-read after a successful commit.

### Use an adapter-bound feature

`feature_describe(feature_id)` returns `arguments` (what to pass) and `fixed_arguments` (what the feature pins, e.g. `hinge_union` fixes `action="union"`). Mutating features go through `feature_prepare(feature_id, arguments)` followed by `change_commit(token)`; read-only features use `feature_read`. Passing a conflicting value for a fixed argument is rejected.

### Make a protected change

Use a dedicated `*_prepare` tool when available. Otherwise prepare the exact operation with `change_prepare` or `feature_prepare` and execute only via `change_commit`. A `CONFIRMATION_REQUIRED` from a read tool or `feature_read` means the operation mutates: prepare it instead.

### Use an exact UI file flow

Use `scene_exchange_prepare` for USD/GLB/GLTF/VRM. Use `ui_flow_prepare` only for a `flow_id` returned by the registry. Commit once; if the dialog is locked or times out, inspect outcome before retrying.

### Handle long work

Use `job_submit` only for non-destructive operations. Poll `job_status`; cancel or retry from persisted state. Protected changes remain synchronous token-bound operations.

### Escalate below the task API

Use `action_invoke_prepare` only when an exact registered feature requires it. Generic tool/csc/Python execution is absent from production builds and belongs in a separately compiled developer build.

## Common feature/operation pairs

These pairs are useful with `change_prepare` when no dedicated `*_prepare` tool covers the change:

| Intent | Feature ID | Operation name |
|---|---|---|
| New/open/close/save-as scene | `scene_new`, `scene_open`, `scene_close`, `scene_save_as` | `scene.new`, `scene.open`, `scene.close`, `scene.save_as` |
| FBX/DAE import or export | `import_fbx`, `import_dae`, `export_fbx`, `export_dae` | `io.import_fbx`, `io.import_dae`, `io.export_fbx`, `io.export_dae` |
| Create/parent/unparent/delete object | `object_create`, `object_parent`, `object_unparent`, `object_delete` | `object.create`, `object.parent`, `object.unparent`, `objects.delete` |
| Delete key/layer | `key_delete`, `layer_delete` | `animation.key_delete`, `layer.delete` |
| AutoPosing | `auto_posing` | `generation.auto_posing` |
| Viewport capture/still render | `viewport_capture`, `render_image` | `render.viewport_capture`, `render.image` |
| AutoPhysics snap | `auto_physics` | `physics.auto_snap` |

Confirm exact arguments with the tool schema and `feature_describe`; this table is routing guidance, not permission or a substitute for live capability state.

When the MCP contract changes, run `scripts/validate_tool_coverage.py` from the skill directory (or pass `--server`) and update this catalog before publishing the skill.
