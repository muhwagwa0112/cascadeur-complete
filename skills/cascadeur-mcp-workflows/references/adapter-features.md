# Adapter-bound features

Generated from `cascadeur_complete.adapter_bindings` by `scripts/render_feature_reference.py`; do not edit by hand.

Every row is a dedicated adapter with exact postconditions. Mutating rows run through
`feature_prepare(feature_id, arguments)` and `change_commit(token)`; dialog rows can also use
`file_dialog_prepare`. `fixed` arguments are pinned by the feature and must not be overridden.
Check `feature_describe` for the live state: only `available` rows have live evidence on this build.


## Objects

| Feature | Name | Operation | Arguments | Fixed | Postconditions |
|---|---|---|---|---|---|
| `object_delete` | Delete | `objects.delete` | `ids`: object IDs | — | `objects_absent` |
| `object_duplicate` | Duplicate | `objects.duplicate` | `id`: object ID | — | `one_duplicate_created` |

## Editing

| Feature | Name | Operation | Arguments | Fixed | Postconditions |
|---|---|---|---|---|---|
| `copy_animation` | Copy | `timeline.copy_interval` | `layer_ids`: layer GUIDs (default: all), `first_frame`: int, `last_frame`: int, `target_frame`: int | — | `destination_keys_match_source` |
| `fixing` | Fixing | `editing.fix_foot` | `ids`: IDs, `layer_ids`: layer GUIDs (default: all), `first_frame`: int, `last_frame`: int | — | `scene_revision_changed` |
| `ghost` | Ghost | `view.ghost` | `ids`: optional objects to select first, `mode`: keyframe\|neighbor\|next\|previous\|selected\|disable | — | `viewport_render_changed` |
| `hiding` | Hiding | `objects.visibility` | `ids`: object IDs, `values`: {"visibility": ObjectVisibility enum int} | — | `behaviour_values_equal_request` |
| `interval_edit` | Interval edit | `timeline.interval_edit` | `layer_ids`: layer GUIDs (default: all), `first_frame`: int, `last_frame`: int, `action`: add\|remove | — | `frame_count_changed_by_request` |
| `trajectory` | Trajectory | `view.trajectory` | `ids`: optional objects to select first | — | `viewport_render_changed` |
| `tween` | Tween | `editing.tween` | `ids`: point/controller IDs, `mode`: Previous\|Next\|Inertial\|InverseInertial\|Average, `frame`: int | — | `target_transform_fingerprint_changed` |

## Animation

| Feature | Name | Operation | Arguments | Fixed | Postconditions |
|---|---|---|---|---|---|
| `bake` | Bake | `timeline.bake` | `layer_ids`: layer GUIDs (default: all), `first_frame`: int, `last_frame`: int | — | `every_frame_is_key` |
| `ballistic_ghosts` | Ballistic Ghosts | `view.ballistic_ghosts` | `ids`: optional objects to select first | — | `viewport_render_changed` |
| `cycle` | Cycle | `timeline.cycle` | `layer_ids`: layer GUIDs (default: all), `first_frame`: int, `last_frame`: int | `action=create` | `cycle_present` |
| `graph_edit` | Graph edit | `animation.section_edit` | `layer_id`: layer GUID, `frame`: key frame, `interpolation`: optional Interpolation name, `tangents`: optional Tangents name, `ik_fk`: optional IK\|FK, `fixation`: optional Free\|Fulcrum | — | `section_equals_request` |
| `interpolation_range` | Interpolation range | `timeline.interpolation_range` | `layer_ids`: layer GUIDs (default: all), `first_frame`: int, `last_frame`: int, `interpolation`: Interpolation name (e.g. CLAMPED_BEZIER, LINEAR) | — | `interval_interpolation_equals_request` |
| `layer_activate` | Activate layer | `layer.activate` | `layer_id`: layer GUID | — | `active_layer_equals_request` |
| `node_editor` | Node Editor | `view.node_editor` | `state`: on\|off | — | `viewport_render_changed` |
| `silhouette` | Silhouette mode | `view.silhouette` | `ids`: optional objects to select first | — | `viewport_render_changed` |
| `stretch` | Stretch | `timeline.stretch` | `layer_ids`: layer GUIDs (default: all), `first_frame`: int, `last_frame`: int, `new_last_frame`: int | — | `keys_retimed_to_request` |
| `timeline_play` | Play | `timeline.playback` | — | `state=play` | `playback_frames_advance` |
| `timeline_stop` | Stop | `timeline.playback` | — | `state=stop` | `playback_frame_stable` |
| `trajectory_direction` | Direction trajectory | `view.trajectory_direction` | `ids`: optional objects to select first | — | `viewport_render_changed` |
| `trajectory_rotation` | Rotation trajectory | `view.trajectory_rotate` | `ids`: optional objects to select first | — | `viewport_render_changed` |
| `trajectory_tangents` | Trajectory tangents | `view.trajectory_edit` | `ids`: optional objects to select first | — | `viewport_render_changed` |
| `trajectory_translation` | Translation trajectory | `view.trajectory_translate` | `ids`: optional objects to select first | — | `viewport_render_changed` |

## Generation

| Feature | Name | Operation | Arguments | Fixed | Postconditions |
|---|---|---|---|---|---|
| `autoposing_props` | AutoPosing props | `rig.autoposing_props` | `rig_element_ids`: IDs, `enabled`: bool | — | `autoposing_names_equal_request` |
| `finger_auto_posing` | Finger AutoPosing | `view.fingers_drawing` | `ids`: optional objects to select first | — | `viewport_render_changed` |
| `fulcrum_cleaning` | Fulcrum cleaning | `timeline.fulcrum` | `layer_ids`: layer GUIDs (default: all), `first_frame`: int, `last_frame`: int | `state=Free` | `key_fixation_equals_request` |
| `retargeting` | Retargeting | `generation.retargeting` | `source_point_id`: point controller of the animated source character, `target_point_id`: point controller of the target character (another layer), `first_frame`: first frame to copy, `last_frame`: last frame to copy | — | `target_animation_changed` |
| `root_constraint` | Root Constraint | `rig.root_constraint` | `root_id`: root joint, `rig_element_id`: pelvis rig element | `action=add` | `root_constraint_present` |

## Physics

| Feature | Name | Operation | Arguments | Fixed | Postconditions |
|---|---|---|---|---|---|
| `autophysics_compensation_motion` | AutoPhysics Compensation Motion | `physics.compensation_motion` | `ids`: object IDs (defaults to every owner of the behaviour), `values`: {property: value}, `add_missing`: bool | — | `behaviour_values_equal_request` |
| `autophysics_corrector` | AutoPhysics Physics Corrector | `physics.autophysics_corrector` | `ids`: IDs, `enabled`: bool | — | `behaviour_presence_equals_request` |
| `autophysics_freeze` | AutoPhysics Freeze Physics | `physics.autophysics_freeze` | — | — | `viewport_render_changed` |
| `autophysics_point_settings` | AutoPhysics per-point settings | `physics.autophysics_point_settings` | `ids`: object IDs (defaults to every owner of the behaviour), `values`: {property: value} | — | `behaviour_values_equal_request` |
| `autophysics_priority_frames` | AutoPhysics Priority Frames | `physics.autophysics_priority_frames` | `ids`: object IDs (defaults to every owner of the behaviour), `values`: {property: value} | — | `behaviour_values_equal_request` |
| `autophysics_restore_unbound` | AutoPhysics Restore Unbound | `physics.autophysics_restore` | `center_of_mass_id`: CoM ID, `point_ids`: point IDs | — | `autophysics_values_restored` |
| `autophysics_secondary_motion` | AutoPhysics Secondary Motion | `physics.secondary_motion` | `ids`: object IDs (defaults to every owner of the behaviour), `values`: {property: value}, `add_missing`: bool | — | `behaviour_values_equal_request` |
| `autophysics_separation_motion` | AutoPhysics Separation of Motion | `physics.separation_motion` | `ids`: object IDs (defaults to every owner of the behaviour), `values`: {property: value}, `add_missing`: bool | — | `behaviour_values_equal_request` |
| `autophysics_smooth_rotation` | AutoPhysics Smooth Rotation | `physics.autophysics_smooth_rotation` | `ids`: object IDs (defaults to every owner of the behaviour), `values`: {property: value} | — | `behaviour_values_equal_request` |
| `autophysics_smooth_trajectory` | AutoPhysics Smooth Trajectory | `physics.autophysics_smooth_trajectory` | `ids`: object IDs (defaults to every owner of the behaviour), `values`: {property: value} | — | `behaviour_values_equal_request` |
| `collision_clean` | Collision clean | `physics.fix_collisions` | `ids`: IDs, `layer_ids`: layer GUIDs (default: all), `first_frame`: int, `last_frame`: int | — | `scene_revision_changed` |
| `fulcrum` | Fulcrum | `timeline.fulcrum` | `layer_ids`: layer GUIDs (default: all), `first_frame`: int, `last_frame`: int | `state=Fulcrum` | `key_fixation_equals_request` |
| `penetration_clean` | Penetration cleaning | `physics.penetration_cleaning` | `ids`: IDs, `enabled`: bool | — | `behaviour_presence_equals_request` |
| `ragdoll` | Ragdoll | `physics.ragdoll` | `ids`: object IDs (defaults to every owner of the behaviour), `values`: {property: value}, `add_missing`: bool | — | `behaviour_values_equal_request` |

## Rigging

| Feature | Name | Operation | Arguments | Fixed | Postconditions |
|---|---|---|---|---|---|
| `additional_controller_remove` | Remove additional controller | `rig.additional_controller_remove` | `kind`: point\|box, `controller_id`: ID | — | `additional_controller_absent` |
| `additional_joint_attach` | Attach additional joint | `rig.technical_link` | `rig_element_id`: ID, `target_id`: joint | `kind=additional_joint`, `action=set` | `technical_link_equals_request` |
| `additional_joint_detach` | Detach additional joint | `rig.technical_link` | `rig_element_id`: ID | `kind=additional_joint`, `action=remove` | `technical_link_equals_request` |
| `additional_parent` | Set additional parent | `rig.technical_link` | `rig_element_id`: ID, `target_id`: rig element, `action`: set\|remove | `kind=additional_parent` | `technical_link_equals_request` |
| `blend_shape` | Blend Shape | `mesh.blend_shape_weight` | `object_id`: mesh object imported with Blendshapes, `blend_shape`: optional blend shape name (required when the mesh has several), `weights`: {channel: weight in [-100, 100]}, `frame`: optional frame (default: current) | — | `blend_shape_weights_equal_request` |
| `character_mirror_plane` | Character mirror plane | `rig.character_mirror_plane` | `plane`: 0 YZ\|1 XZ\|2 XY\|3 undefined | — | `mirror_plane_equals_request` |
| `clear_animation_data` | Clear animation data | `rig.clear_animation_data` | — | — | `preserved_data_empty` |
| `custom_additional_point_remove` | Remove custom additional point | `rig.technical_link` | `rig_element_id`: ID | `kind=user_additional_point`, `action=remove` | `technical_link_equals_request` |
| `custom_additional_point_set` | Set custom additional point | `rig.technical_link` | `rig_element_id`: ID, `target_id`: manual point | `kind=user_additional_point`, `action=set` | `technical_link_equals_request` |
| `custom_rotation` | Custom rotation | `rig.technical_link` | `rig_element_id`: ID, `target_id`: rig element, `action`: set\|remove | `kind=custom_rotation` | `technical_link_equals_request` |
| `generate_rig` | Generate rig | `rig.mode` | — | `action=off` | `rig_generated_from_prototypes` |
| `hinge_orthogonalize` | Orthogonalize hinges | `rig.hinge` | `rig_element_ids`: two IDs | `action=orthogonalize` | `hinge_additional_points_coincide` |
| `hinge_straighten` | Straighten hinges | `rig.hinge` | `rig_element_ids`: two IDs | `action=straighten` | `hinge_additional_points_coincide` |
| `hinge_union` | Union hinges | `rig.hinge` | `rig_element_ids`: two IDs | `action=union` | `hinge_additional_points_coincide` |
| `joint_delete` | Delete standard joint | `rig.joint_delete` | `joint_id`: standard rig joint | — | `joint_branch_absent` |
| `prototype_com_remove` | Remove prototype CoM | `rig.proto_center_of_mass_remove` | `center_of_mass_ids`: IDs | — | `proto_center_of_mass_absent` |
| `prototype_fulcrum_groups` | Prototype fulcrum groups | `rig.fulcrum_group` | `rig_element_ids`: IDs | `action=create` | `fulcrum_group_present` |
| `prototype_mirror` | Mirror prototype | `rig.prototype_mirror` | `rig_element_ids`: IDs, `original_suffix`: _l, `mirror_suffix`: _r, `mirror_plane`: 0-3 | — | `mirrored_rig_elements_created` |
| `quick_rig` | Quick Rig | `rig.quick_rig` | `template_path`: .qrigcasc template (resources/autorig_templates) | — | `rig_prototypes_created_from_template` |
| `rig_element_delete` | Delete rig element | `rig.element_delete` | `rig_element_ids`: IDs | — | `rig_elements_absent` |
| `rig_json_export` | Export rig JSON | `rig.json_export` | `path`: destination .json | — | `output_file`, `nonzero_bytes` |
| `rig_json_import` | Import rig JSON | `rig.json_import` | `path`: rig .json, `set_t_pose`: bool | — | `rig_prototypes_created_from_json` |
| `rig_mode_on` | Enter Rig Mode | `rig.mode` | — | `action=on` | `rig_mode_active` |
| `rig_regenerate` | Rig regenerate | `rig.mode` | — | `action=regenerate` | `rig_generated_from_prototypes` |
| `root_constraint_add` | Add Root Constraint | `rig.root_constraint` | `root_id`: ID, `rig_element_id`: ID | `action=add` | `root_constraint_present` |
| `root_constraint_remove` | Remove Root Constraint | `rig.root_constraint` | `constraint_id`: ID | `action=remove` | `root_constraint_absent` |
| `snap_joint` | Snap Joint | `rig.snap` | `id`: virtual joint | `mode=joint_to_rig` | `snap_positions_equal` |
| `snap_rig` | Snap Rig | `rig.snap` | `id`: rig element | `mode=rig_to_joint` | `snap_positions_equal` |
| `untwist` | Untwist | `rig.untwist` | `parent_element_id`: ID, `target_element_id`: ID, `child_element_id`: ID, `axis`: 0\|1\|2 | — | `untwist_dependencies_created` |
| `virtual_joint_create` | Create virtual joint | `rig.virtual_joint` | `joint_id`: parent joint | `action=create` | `virtual_joint_created` |
| `virtual_joint_delete` | Delete virtual joint | `rig.virtual_joint` | `joint_id`: virtual joint | `action=delete` | `virtual_joint_absent` |

## Render

| Feature | Name | Operation | Arguments | Fixed | Postconditions |
|---|---|---|---|---|---|
| `camera_settings` | Camera settings | `render.camera_settings` | `ids`: object IDs (defaults to every owner of the behaviour), `values`: {property: value} | — | `behaviour_values_equal_request` |
| `camera_textures` | Camera textures | `render.camera_texture` | `camera_id`: camera object, `paths`: image files (one per frame), `start_frame`: int | — | `camera_texture_paths_equal_request` |
| `composition` | Composition | `view.composition` | — | — | `viewport_render_changed` |
| `grid` | Grid | `view.isometric_grid` | — | — | `viewport_render_changed` |
| `material` | Filament Material | `render.material` | `ids`: object IDs (defaults to every owner of the behaviour), `values`: {property: value} | — | `behaviour_values_equal_request` |
| `material_textures` | Material textures | `render.material_textures` | `ids`: object IDs (defaults to every owner of the behaviour), `values`: {property: value} | — | `behaviour_values_equal_request` |
| `point_light_properties` | Point light properties | `render.point_light_properties` | `ids`: object IDs (defaults to every owner of the behaviour), `values`: {property: value} | — | `behaviour_values_equal_request` |
| `render_video` | Render video | `system.ui_file_flow` | `path`: output folder + file name without extension (format set by the Export video window), `width`: int (default 320), `height`: int (default 180), `quality`: LOW\|MEDIUM\|HIGH (default LOW) | — | `exact_file_dialog`, `output_file`, `nonzero_bytes` |
| `spot_light_properties` | Spot light properties | `render.spot_light_properties` | `ids`: object IDs (defaults to every owner of the behaviour), `values`: {property: value} | — | `behaviour_values_equal_request` |
| `viewport` | Viewport | `render.viewport_layout` | `count`: 1\|2\|4 | — | `viewport_count_equals_request` |
| `viewport_layout` | Viewport layout and visibility | `render.viewport_layout` | `count`: 1\|2\|4 | — | `viewport_count_equals_request` |

## Io

| Feature | Name | Operation | Arguments | Fixed | Postconditions |
|---|---|---|---|---|---|
| `export_video` | Export video | `system.ui_file_flow` | `path`: output folder + file name without extension (format set by the Export video window), `width`: int (default 320), `height`: int (default 180), `quality`: LOW\|MEDIUM\|HIGH (default LOW) | — | `exact_file_dialog`, `output_file`, `nonzero_bytes` |
| `fix_scene` | Fix Scene | `scene.fix` | — | — | `scene_valid_after_fix` |
| `import_image` | Import image | `system.ui_file_flow` | `path`: image | — | `exact_file_dialog`, `scene_revision_changed` |
| `import_scene_to_current` | Import Scene To Current | `system.ui_file_flow` | `path`: .casc | — | `exact_file_dialog`, `scene_revision_changed` |
| `import_video` | Import video | `system.ui_file_flow` | `path`: video | — | `exact_file_dialog`, `scene_revision_changed` |
| `open_autosave` | Open Autosave | `scene.open_autosave` | `path`: optional autosave .casc (default: newest) | — | `autosave_scene_loaded`, `stable_scene_path` |
| `save_as_new_version` | Save As New Version | `scene.save_new_version` | — | — | `new_version_file_saved` |
| `save_as_without_assets` | Save As without assets | `system.ui_file_flow` | `path`: .casc | — | `exact_file_dialog`, `output_file`, `nonzero_bytes` |
| `scene_parts_export` | Export Scene Parts | `system.ui_file_flow` | `path`: .partscasc | — | `exact_file_dialog`, `output_file`, `nonzero_bytes` |
| `scene_parts_import` | Import Scene Parts | `system.ui_file_flow` | `path`: .partscasc | — | `exact_file_dialog`, `scene_revision_changed` |
| `selection_groups_export` | Export Selection Groups | `system.ui_file_flow` | `path`: file | — | `exact_file_dialog`, `output_file`, `nonzero_bytes` |
| `selection_groups_import` | Import Selection Groups | `io.selection_groups_import` | `path`: selection groups file | — | `selection_groups_loaded` |

## External

| Feature | Name | Operation | Arguments | Fixed | Postconditions |
|---|---|---|---|---|---|
| `blender_export` | Blender export | `io.export_fbx` | `path`: absolute .fbx path | `target=blender` | `output_file`, `nonzero_bytes`, `target_import_verified` |
| `control_picker` | Control Picker | `view.control_picker` | `state`: on\|off | — | `viewport_render_changed` |
