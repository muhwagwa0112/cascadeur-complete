# Support status

Generated 2026-09-29 by `scripts/support_report.py` for Cascadeur `2026.1.2.0.15343` (license: Basic).

**118 of 224 product features are supported** (dedicated adapter + exact postconditions + live evidence on this build; host-only features by contract).

| State | Count |
|---|---|
| supported | 118 |
| unhealthy | 79 |
| not_implemented | 9 |
| missing_dependency | 8 |
| ui_only | 4 |
| license_gated | 3 |
| unsupported | 2 |
| unsupported_version | 1 |

## Not supported on this machine

| Feature | Family | State | Reason |
|---|---|---|---|
| `inbetweening` | generation | license_gated | requires a Cascadeur Pro license (this machine: Basic) |
| `mocap` | generation | license_gated | requires a Cascadeur Pro license (this machine: Basic) |
| `retargeting` | generation | license_gated | requires a Cascadeur Pro license (this machine: Basic) |
| `csc_mutate` | system | missing_dependency | requires Developer build with local developer_mode and generic_api policy |
| `csc_query` | system | missing_dependency | requires Developer build with local developer_mode and generic_api policy |
| `daz_export` | external | missing_dependency | requires Daz Studio integration |
| `developer_execute_python` | system | missing_dependency | requires Developer build with local developer_mode and generic_api policy |
| `roblox_export` | external | missing_dependency | requires Roblox export target |
| `unity_export` | external | missing_dependency | requires Unity integration |
| `unreal_export` | external | missing_dependency | requires Unreal Engine integration |
| `unreal_livelink` | external | missing_dependency | requires Unreal Engine LiveLink plugin and running Unreal Editor |
| `official_gap.filament_ambient_occlusion` | render | not_implemented | no adapter yet |
| `official_gap.filament_bloom` | render | not_implemented | no adapter yet |
| `official_gap.filament_dynamic_lights` | render | not_implemented | no adapter yet |
| `official_gap.filament_environment_color` | render | not_implemented | no adapter yet |
| `official_gap.filament_environment_direction` | render | not_implemented | no adapter yet |
| `official_gap.filament_environment_intensity` | render | not_implemented | no adapter yet |
| `official_gap.filament_environment_map` | render | not_implemented | no adapter yet |
| `official_gap.filament_environment_rotation` | render | not_implemented | no adapter yet |
| `official_gap.filament_shadows` | render | not_implemented | no adapter yet |
| `export_video` | io | ui_only | only reachable through Cascadeur's QML UI; no action id or Python API exists in 2026.1.2 |
| `render_video` | render | ui_only | only reachable through Cascadeur's QML UI; no action id or Python API exists in 2026.1.2 |
| `scene_linking` | external | ui_only | only reachable through Cascadeur's QML UI; no action id or Python API exists in 2026.1.2 |
| `settings_set` | system | ui_only | only reachable through Cascadeur's QML UI; no action id or Python API exists in 2026.1.2 |
| `additional_controller_remove` | rigging | unhealthy | adapter present, no current live evidence on this machine |
| `additional_joint_attach` | rigging | unhealthy | adapter present, no current live evidence on this machine |
| `additional_joint_detach` | rigging | unhealthy | adapter present, no current live evidence on this machine |
| `additional_parent` | rigging | unhealthy | adapter present, no current live evidence on this machine |
| `auto_physics` | physics | unhealthy | adapter present, no current live evidence on this machine |
| `auto_physics_enable` | physics | unhealthy | adapter present, no current live evidence on this machine |
| `auto_posing` | generation | unhealthy | adapter present, no current live evidence on this machine |
| `autophysics_freeze` | physics | unhealthy | adapter present, no current live evidence on this machine |
| `autoposing_props` | generation | unhealthy | adapter present, no current live evidence on this machine |
| `ballistic` | physics | unhealthy | adapter present, no current live evidence on this machine |
| `ballistic_ghosts` | animation | unhealthy | adapter present, no current live evidence on this machine |
| `blend_shape` | rigging | unhealthy | adapter present, no current live evidence on this machine |
| `blender_export` | external | unhealthy | adapter present, no current live evidence on this machine |
| `character_mirror_plane` | rigging | unhealthy | adapter present, no current live evidence on this machine |
| `clear_animation_data` | rigging | unhealthy | adapter present, no current live evidence on this machine |
| `collision_clean` | physics | unhealthy | adapter present, no current live evidence on this machine |
| `composition` | render | unhealthy | adapter present, no current live evidence on this machine |
| `constraint_transform` | physics | unhealthy | adapter present, no current live evidence on this machine |
| `control_picker` | external | unhealthy | adapter present, no current live evidence on this machine |
| `controller_box` | rigging | unhealthy | adapter present, no current live evidence on this machine |
| `controller_point` | rigging | unhealthy | adapter present, no current live evidence on this machine |
| `custom_additional_point_remove` | rigging | unhealthy | adapter present, no current live evidence on this machine |
| `custom_additional_point_set` | rigging | unhealthy | adapter present, no current live evidence on this machine |
| `custom_rotation` | rigging | unhealthy | adapter present, no current live evidence on this machine |
| `finger_auto_posing` | generation | unhealthy | adapter present, no current live evidence on this machine |
| `fixing` | editing | unhealthy | adapter present, no current live evidence on this machine |
| `fulcrum` | physics | unhealthy | adapter present, no current live evidence on this machine |
| `fulcrum_cleaning` | generation | unhealthy | adapter present, no current live evidence on this machine |
| `generate_rig` | rigging | unhealthy | adapter present, no current live evidence on this machine |
| `ghost` | editing | unhealthy | adapter present, no current live evidence on this machine |
| `grid` | render | unhealthy | adapter present, no current live evidence on this machine |
| `hinge_orthogonalize` | rigging | unhealthy | adapter present, no current live evidence on this machine |
| `hinge_straighten` | rigging | unhealthy | adapter present, no current live evidence on this machine |
| `hinge_union` | rigging | unhealthy | adapter present, no current live evidence on this machine |
| `import_scene_to_current` | io | unhealthy | adapter present, no current live evidence on this machine |
| `import_video` | io | unhealthy | adapter present, no current live evidence on this machine |
| `joint` | rigging | unhealthy | adapter present, no current live evidence on this machine |
| `joint_delete` | rigging | unhealthy | adapter present, no current live evidence on this machine |
| `key_reduction` | generation | unhealthy | adapter present, no current live evidence on this machine |
| `layer_activate` | animation | unhealthy | adapter present, no current live evidence on this machine |
| `manual_rig` | rigging | unhealthy | adapter present, no current live evidence on this machine |
| `mirror` | editing | unhealthy | adapter present, no current live evidence on this machine |
| `node_editor` | animation | unhealthy | adapter present, no current live evidence on this machine |
| `prototype_com_remove` | rigging | unhealthy | adapter present, no current live evidence on this machine |
| `prototype_fulcrum_groups` | rigging | unhealthy | adapter present, no current live evidence on this machine |
| `prototype_mirror` | rigging | unhealthy | adapter present, no current live evidence on this machine |
| `quick_rig` | rigging | unhealthy | adapter present, no current live evidence on this machine |
| `rig_create` | rigging | unhealthy | adapter present, no current live evidence on this machine |
| `rig_element_delete` | rigging | unhealthy | adapter present, no current live evidence on this machine |
| `rig_info` | rigging | unhealthy | adapter present, no current live evidence on this machine |
| `rig_json_export` | rigging | unhealthy | adapter present, no current live evidence on this machine |
| `rig_json_import` | rigging | unhealthy | adapter present, no current live evidence on this machine |
| `rig_mode_on` | rigging | unhealthy | adapter present, no current live evidence on this machine |
| `rig_regenerate` | rigging | unhealthy | adapter present, no current live evidence on this machine |
| `rigid_body` | rigging | unhealthy | adapter present, no current live evidence on this machine |
| `root_constraint` | generation | unhealthy | adapter present, no current live evidence on this machine |
| `root_constraint_add` | rigging | unhealthy | adapter present, no current live evidence on this machine |
| `root_constraint_remove` | rigging | unhealthy | adapter present, no current live evidence on this machine |
| `root_motion` | generation | unhealthy | adapter present, no current live evidence on this machine |
| `scene_parts_import` | io | unhealthy | adapter present, no current live evidence on this machine |
| `selection_groups_import` | io | unhealthy | adapter present, no current live evidence on this machine |
| `silhouette` | animation | unhealthy | adapter present, no current live evidence on this machine |
| `snap_joint` | rigging | unhealthy | adapter present, no current live evidence on this machine |
| `snap_rig` | rigging | unhealthy | adapter present, no current live evidence on this machine |
| `spline_ik` | rigging | unhealthy | adapter present, no current live evidence on this machine |
| `stretch` | animation | unhealthy | adapter present, no current live evidence on this machine |
| `timeline_play` | animation | unhealthy | adapter present, no current live evidence on this machine |
| `timeline_stop` | animation | unhealthy | adapter present, no current live evidence on this machine |
| `trajectory` | editing | unhealthy | adapter present, no current live evidence on this machine |
| `trajectory_direction` | animation | unhealthy | adapter present, no current live evidence on this machine |
| `trajectory_rotation` | animation | unhealthy | adapter present, no current live evidence on this machine |
| `trajectory_tangents` | animation | unhealthy | adapter present, no current live evidence on this machine |
| `trajectory_translation` | animation | unhealthy | adapter present, no current live evidence on this machine |
| `tween` | editing | unhealthy | adapter present, no current live evidence on this machine |
| `twist` | rigging | unhealthy | adapter present, no current live evidence on this machine |
| `unbaking` | generation | unhealthy | adapter present, no current live evidence on this machine |
| `untwist` | rigging | unhealthy | adapter present, no current live evidence on this machine |
| `virtual_joint_create` | rigging | unhealthy | adapter present, no current live evidence on this machine |
| `virtual_joint_delete` | rigging | unhealthy | adapter present, no current live evidence on this machine |
| `settings_get` | system | unsupported | the 2026.1.2 build exposes no such capability |
| `tool_inspect` | diagnostics | unsupported | the 2026.1.2 build exposes no such capability |
| `export_vrm` | io | unsupported_version | installed build differs from the pinned build |

## Supported

| Feature | Family | Mode | Evidence |
|---|---|---|---|
| `bake` | animation | Native | live |
| `cycle` | animation | Native | live |
| `cycle_query` | animation | Native | live |
| `graph_edit` | animation | Native | live |
| `graph_query` | animation | Native | live |
| `interpolation_set` | animation | Native | live |
| `key_add` | animation | Native | live |
| `key_delete` | animation | Native | live |
| `key_list` | animation | Native | live |
| `layer_create` | animation | Native | live |
| `layer_delete` | animation | Native | live |
| `layer_folder` | animation | Native | live |
| `layer_list` | animation | Native | live |
| `layer_lock` | animation | Native | live |
| `layer_visibility` | animation | Native | live |
| `tangent_set` | animation | Native | live |
| `timeline_get` | animation | Native | live |
| `timeline_range` | animation | Native | live |
| `timeline_set_frame` | animation | Native | live |
| `transform_get` | animation | Native | live |
| `transform_set` | animation | Native | live |
| `feature_describe` | diagnostics | Native | host contract |
| `feature_search` | diagnostics | Native | host contract |
| `inventory_refresh` | diagnostics | Native | live |
| `logs` | diagnostics | Native | live |
| `scene_validate` | diagnostics | Native | live |
| `status` | diagnostics | Native | live |
| `copy_animation` | editing | Native | live |
| `hiding` | editing | Native | live |
| `interval_edit` | editing | Native | live |
| `generation_state` | generation | Native | live |
| `export_dae` | io | Native | live |
| `export_fbx` | io | External | live |
| `export_glb` | io | UIA | live |
| `export_gltf` | io | UIA | live |
| `export_image` | io | Native | live |
| `export_usd` | io | UIA | live |
| `fix_scene` | io | Native | live |
| `import_audio` | io | Native | live |
| `import_dae` | io | Native | live |
| `import_fbx` | io | Native | live |
| `import_glb` | io | UIA | live |
| `import_gltf` | io | UIA | live |
| `import_image` | io | UIA | live |
| `import_usd` | io | UIA | live |
| `import_vrm` | io | UIA | live |
| `open_autosave` | io | Native | live |
| `save_as_new_version` | io | Native | live |
| `save_as_without_assets` | io | UIA | live |
| `scene_parts_export` | io | UIA | live |
| `selection_groups_export` | io | UIA | live |
| `object_behaviors` | objects | Native | live |
| `object_create` | objects | Native | live |
| `object_delete` | objects | Native | live |
| `object_duplicate` | objects | Native | live |
| `object_hierarchy` | objects | Native | live |
| `object_parent` | objects | Native | live |
| `object_properties` | objects | Native | live |
| `object_rename` | objects | Native | live |
| `object_search` | objects | Native | live |
| `object_unparent` | objects | Native | live |
| `selection_add` | objects | Native | live |
| `selection_filter` | objects | Native | live |
| `selection_get` | objects | Native | live |
| `selection_remove` | objects | Native | live |
| `selection_set` | objects | Native | live |
| `auto_physics_state` | physics | Native | live |
| `autophysics_compensation_motion` | physics | Native | live |
| `autophysics_corrector` | physics | Native | live |
| `autophysics_point_settings` | physics | Native | live |
| `autophysics_priority_frames` | physics | Native | live |
| `autophysics_restore_unbound` | physics | Native | live |
| `autophysics_secondary_motion` | physics | Native | live |
| `autophysics_separation_motion` | physics | Native | live |
| `autophysics_smooth_rotation` | physics | Native | live |
| `autophysics_smooth_trajectory` | physics | Native | live |
| `center_of_mass` | physics | Action | live |
| `collision_create` | physics | Native | live |
| `collision_delete` | physics | Native | live |
| `constraint_point` | physics | Native | live |
| `penetration_clean` | physics | Native | live |
| `physics_state` | physics | Native | live |
| `ragdoll` | physics | Native | live |
| `camera_activate` | render | Native | live |
| `camera_aim` | render | Native | live |
| `camera_catalog` | render | Native | live |
| `camera_create` | render | Native | live |
| `camera_settings` | render | Native | live |
| `camera_textures` | render | Native | live |
| `camera_view` | render | Native | live |
| `light_point` | render | Native | live |
| `light_spot` | render | Native | live |
| `material` | render | Native | live |
| `material_textures` | render | Native | live |
| `point_light_properties` | render | Native | live |
| `render_image` | render | Native | live |
| `spot_light_properties` | render | Native | live |
| `viewport` | render | Native | live |
| `viewport_capture` | render | Native | live |
| `viewport_layout` | render | Native | live |
| `viewport_state` | render | Native | live |
| `constraint_drivers` | rigging | Native | live |
| `ik` | rigging | Native | live |
| `mass` | rigging | Native | live |
| `rig_state` | rigging | Native | live |
| `scene_activate` | scene | Native | live |
| `scene_close` | scene | Native | live |
| `scene_list` | scene | Native | live |
| `scene_new` | scene | Native | live |
| `scene_open` | scene | Native | live |
| `scene_save` | scene | Native | live |
| `scene_save_as` | scene | Native | live |
| `scene_summary` | scene | Native | live |
| `action_invoke` | system | Native | live |
| `redo` | system | Native | live |
| `ui_flow_run` | system | Native | live |
| `undo` | system | Native | live |
| `view_mode` | system | Native | live |
