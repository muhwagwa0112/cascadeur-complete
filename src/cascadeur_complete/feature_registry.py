from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from dataclasses import dataclass

from .models import CapabilityState, ExecutionMode, FeatureRecord, VerificationState


@dataclass(frozen=True)
class CoreSpec:
    family: str
    feature_id: str
    name: str
    route: str
    mode: ExecutionMode = ExecutionMode.NATIVE
    requires_scene: bool = True
    destructive: bool = False
    license: str = "any"
    dependency: str | None = None


def _specs(
    family: str,
    names: str,
    *,
    mode: ExecutionMode = ExecutionMode.NATIVE,
    destructive: Iterable[str] = (),
    no_scene: Iterable[str] = (),
    pro: Iterable[str] = (),
    dependencies: dict[str, str] | None = None,
) -> list[CoreSpec]:
    destructive_set, no_scene_set, pro_set = set(destructive), set(no_scene), set(pro)
    deps = dependencies or {}
    result: list[CoreSpec] = []
    for item in names.split():
        feature_id, label, route = item.split("|")
        result.append(
            CoreSpec(
                family=family,
                feature_id=feature_id,
                name=label.replace("_", " "),
                route=route,
                mode=ExecutionMode.EXTERNAL if feature_id in deps else mode,
                requires_scene=feature_id not in no_scene_set,
                destructive=feature_id in destructive_set,
                license="pro" if feature_id in pro_set else "any",
                dependency=deps.get(feature_id),
            )
        )
    return result


CORE_FEATURES: tuple[CoreSpec, ...] = tuple(
    _specs(
        "diagnostics",
        """
status|Status|system.status feature_search|Feature_search|host.feature_search
feature_describe|Feature_describe|host.feature_describe logs|Logs|system.logs
scene_validate|Scene_validation|scene.validate inventory_refresh|Inventory_refresh|host.inventory_refresh
tool_inspect|Tool_inspect|system.tool_inspect
""",
        no_scene={"status", "feature_search", "feature_describe", "logs", "inventory_refresh"},
    )
    + _specs(
        "scene",
        """
scene_new|New_scene|scene.new scene_open|Open_CASC|scene.open scene_save|Save|scene.save
scene_save_as|Save_as|scene.save_as scene_close|Close|scene.close scene_list|List_tabs|scene.list
scene_activate|Activate_tab|scene.activate scene_summary|Scene_summary|scene.summary
""",
        destructive={"scene_new", "scene_open", "scene_save_as", "scene_close"},
        no_scene={"scene_new", "scene_open", "scene_list"},
    )
    + _specs(
        "io",
        """
import_fbx|Import_FBX|io.import_fbx export_fbx|Export_FBX|io.export_fbx
import_dae|Import_DAE|io.import_dae export_dae|Export_DAE|io.export_dae
import_usd|Import_USD|io.import_usd export_usd|Export_USD|io.export_usd
import_gltf|Import_GLTF|io.import_gltf export_gltf|Export_GLTF|io.export_gltf
import_glb|Import_GLB|io.import_glb export_glb|Export_GLB|io.export_glb
import_vrm|Import_VRM|io.import_vrm export_vrm|Export_VRM|io.export_vrm
import_image|Import_image|action.File.Import.Image import_video|Import_video|action.File.Import.Video
import_audio|Import_audio|io.import_audio export_image|Export_image|io.export_image
export_video|Export_video|tool.RenderToFile
""",
        destructive={
            "import_fbx",
            "import_dae",
            "import_usd",
            "import_gltf",
            "import_glb",
            "import_vrm",
            "import_image",
            "import_video",
            "import_audio",
            "export_fbx",
            "export_dae",
            "export_usd",
            "export_gltf",
            "export_glb",
            "export_vrm",
            "export_image",
            "export_video",
        },
    )
    + _specs(
        "objects",
        """
object_search|Search_objects|scene.objects selection_get|Get_selection|selection.get
selection_set|Set_selection|selection.set selection_add|Add_selection|selection.add
selection_remove|Remove_selection|selection.remove selection_filter|Filter_selection|selection.filter
object_create|Create_object|object.create object_duplicate|Duplicate|tool.CopierTool
object_delete|Delete|action.Delete_objects object_rename|Rename|object.rename object_parent|Set_parent|object.parent
object_unparent|Remove_parent|object.unparent object_hierarchy|Hierarchy|object.hierarchy
object_properties|Properties|object.properties object_behaviors|Behaviors|object.behaviors
""",
        destructive={"object_create", "object_duplicate", "object_delete", "object_parent", "object_unparent"},
    )
    + _specs(
        "animation",
        """
transform_get|Get_transform|animation.transform_get transform_set|Set_transform|animation.transform_set
key_list|List_keys|animation.key_list key_add|Add_key|animation.key_add key_delete|Delete_key|animation.key_delete
interpolation_set|Set_interpolation|animation.interpolation_set tangent_set|Set_tangent|animation.tangent_set
graph_query|Graph_query|animation.graph_query graph_edit|Graph_edit|tool.Timeline
timeline_get|Timeline_state|timeline.get timeline_set_frame|Set_frame|timeline.set_frame
timeline_range|Timeline_range|timeline.range timeline_play|Play|tool.Timeline timeline_stop|Stop|tool.Timeline
layer_list|List_layers|layer.list layer_create|Create_layer|layer.create layer_delete|Delete_layer|layer.delete
layer_activate|Activate_layer|tool.Timeline layer_visibility|Layer_visibility|layer.visibility
layer_lock|Layer_lock|layer.lock layer_folder|Layer_folder|layer.folder
cycle_query|Cycle_query|animation.cycle_query cycle|Cycle|tool.Timeline
stretch|Stretch|tool.Timeline bake|Bake|tool.Timeline
""",
        destructive={"key_delete", "graph_edit", "layer_delete", "cycle", "bake"},
    )
    + _specs(
        "editing",
        """
tween|Tween|tool.Tween mirror|Mirror|editing.mirror copy_animation|Copy|tool.Copier
interval_edit|Interval_edit|tool.Timeline trajectory|Trajectory|tool.TrajectoryTool
ghost|Ghost|tool.GhostTool fixing|Fixing|tool.FixFootTool hiding|Hiding|action.hiding
""",
        mode=ExecutionMode.ACTION,
        destructive={"mirror"},
    )
    + _specs(
        "generation",
        """
generation_state|Generation_state|generation.state
auto_posing|AutoPosing|tool.AutoPosingTool finger_auto_posing|Finger_AutoPosing|action.finger_auto_posing
inbetweening|Inbetweening|generation.inbetweening root_motion|Root_Motion|generation.root_motion
mocap|Mocap|tool.MocapTool retargeting|Retargeting|tool.Retargeting
unbaking|Animation_Unbaking|generation.unbaking fulcrum_cleaning|Fulcrum_cleaning|action.fulcrum_cleaning
key_reduction|Key_reduction|animation.key_reduce
""",
        mode=ExecutionMode.ACTION,
        destructive={"inbetweening", "root_motion", "mocap", "retargeting", "unbaking", "key_reduction"},
        pro={"inbetweening", "mocap", "retargeting"},
    )
    + _specs(
        "physics",
        """
physics_state|Physics_state|physics.state
center_of_mass|Center_of_Mass|physics.center_of_mass ballistic|Ballistic|physics.ballistic
fulcrum|Fulcrum|action.fulcrum auto_physics_state|AutoPhysics_state|physics.auto_state
auto_physics_enable|Enable_AutoPhysics|physics.auto_enable auto_physics|AutoPhysics|tool.AutoPhysicsTool
ragdoll|Ragdoll|action.ragdoll constraint_point|Point_constraint|physics.constraint_point
constraint_transform|Transform_constraint|physics.constraint_transform
collision_create|Collision_create|physics.collision_create collision_delete|Collision_delete|physics.collision_delete
collision_clean|Collision_clean|tool.FixCollisionsTool
penetration_clean|Penetration_cleaning|action.penetration_clean
""",
        mode=ExecutionMode.ACTION,
        destructive={
            "ballistic",
            "ragdoll",
            "constraint_point",
            "constraint_transform",
            "collision_create",
            "collision_delete",
            "penetration_clean",
        },
    )
    + _specs(
        "rigging",
        """
rig_state|Rig_state|rig.state
constraint_drivers|Constraint_drivers|rig.constraint_drivers
quick_rig|Quick_Rig|action.quick_rig manual_rig|Manual_Rig|rig.rig_elements_create
rig_create|Rig_create|rig.rig_elements_create rig_regenerate|Rig_regenerate|action.rig_regenerate
controller_point|Point_controller|rig.additional_point_create controller_box|Box_controller|rig.additional_box_create
joint|Joint|rig.joint_create rigid_body|Rigid_body|rig.rig_elements_create
ik|IK|rig.ik_chain_create spline_ik|Spline_IK|rig.spline_ik_create twist|Twist|rig.twist
mass|Mass|rig.mass_set rig_info|Rig_Info|rig.rig_info_create blend_shape|Blend_Shape|action.blend_shape
""",
        mode=ExecutionMode.ACTION,
        destructive={
            "quick_rig",
            "manual_rig",
            "rig_create",
            "rig_regenerate",
            "controller_point",
            "controller_box",
            "joint",
            "rigid_body",
            "ik",
            "spline_ik",
            "twist",
            "mass",
            "rig_info",
        },
    )
    + _specs(
        "render",
        """
camera_create|Camera|render.camera_create camera_aim|Camera_with_aim|render.camera_aim
viewport|Viewport|tool.ViewportsTool material|Filament_Material|action.material
viewport_state|Viewport_state|render.viewport_state camera_catalog|Camera_catalog|render.camera_catalog
camera_view|Camera_view|render.camera_view camera_activate|Camera_activate|render.camera_activate
light_point|Point_Light|render.light_point light_spot|Spot_Light|render.light_spot
grid|Grid|tool.ViewGridTool composition|Composition|tool.CompositionTool
viewport_capture|Viewport_capture|render.viewport_capture render_image|Render_image|render.image
render_video|Render_video|tool.RenderToFile
""",
        mode=ExecutionMode.ACTION,
        destructive={"camera_create", "camera_aim", "light_point", "light_spot", "render_image", "render_video"},
    )
    + _specs(
        "external",
        """
unreal_livelink|Unreal_LiveLink|tool.LiveLinkTool unreal_export|Unreal_export|external.unreal
unity_export|Unity_export|external.unity daz_export|Daz_export|command.Export_to_Daz
roblox_export|Roblox_export|command.Export_to_Roblox blender_export|Blender_export|external.blender
control_picker|Control_Picker|tool.ControlPicker scene_linking|Scene_Linking|tool.LinkedScenes
""",
        dependencies={
            "unreal_livelink": "Unreal Engine LiveLink plugin and running Unreal Editor",
            "unreal_export": "Unreal Engine integration",
            "unity_export": "Unity integration",
            "daz_export": "Daz Studio integration",
            "roblox_export": "Roblox export target",
            "blender_export": "Blender integration",
        },
    )
    + _specs(
        "system",
        """
settings_get|Settings_get|system.settings_get settings_set|Settings_set|action.Settings
view_mode|View_mode|system.view_mode undo|Undo|system.undo redo|Redo|system.redo
action_invoke|Action_invoke|host.action_dispatcher ui_flow_run|UI_flow|host.ui_flow_prepare
csc_query|CSC_query|system.csc_query csc_mutate|CSC_mutate|system.csc_mutate
developer_execute_python|Developer_Python|system.developer_execute_python
""",
        destructive={"action_invoke", "csc_mutate"},
        no_scene={
            "settings_get",
            "settings_set",
            "action_invoke",
            "ui_flow_run",
            "csc_query",
            "developer_execute_python",
        },
    )
)


@dataclass(frozen=True)
class AdapterSpec:
    adapter_id: str
    preconditions: tuple[str, ...]
    postconditions: tuple[str, ...]
    test_ids: tuple[str, ...]
    requires_live: bool = True
    mode: ExecutionMode | None = None


def _adapter(
    route: str,
    *,
    preconditions: tuple[str, ...] = ("compatible_version",),
    postconditions: tuple[str, ...] = ("bridge_response",),
    requires_live: bool = True,
    mode: ExecutionMode | None = None,
) -> tuple[str, AdapterSpec]:
    slug = route.replace(".", "_")
    return (
        route,
        AdapterSpec(
            adapter_id=f"cascadeur_2026_1.{route}",
            preconditions=preconditions,
            postconditions=postconditions,
            test_ids=(f"contract::{slug}", f"live::{slug}"),
            requires_live=requires_live,
            mode=mode,
        ),
    )


ADAPTER_SPECS = dict(
    [
        _adapter("host.feature_search", requires_live=False),
        _adapter("host.feature_describe", requires_live=False),
        _adapter("host.action_dispatcher", postconditions=("registered_action_binding",), requires_live=False),
        _adapter("host.ui_flow_prepare", postconditions=("registered_uia_flow_token",), requires_live=False),
        _adapter("host.inventory_refresh", postconditions=("schema_counts", "feature_registry")),
        _adapter("system.status", postconditions=("scene_identity", "runtime_tools")),
        _adapter("system.logs", postconditions=("bounded_tail",), mode=ExecutionMode.NATIVE),
        _adapter("system.tool_inspect", postconditions=("tool_method_catalog",), mode=ExecutionMode.NATIVE),
        _adapter("system.settings_get", postconditions=("typed_setting_value",), mode=ExecutionMode.NATIVE),
        _adapter(
            "system.view_mode",
            preconditions=("active_viewport", "known_viewport_mode"),
            postconditions=("viewport_mode_equals_request",),
            mode=ExecutionMode.NATIVE,
        ),
        _adapter("scene.summary", postconditions=("scene_revision",)),
        _adapter("scene.objects", postconditions=("pagination_contract",)),
        _adapter("scene.new", postconditions=("new_scene_identity",)),
        _adapter("scene.open", postconditions=("stable_scene_path",)),
        _adapter("scene.save", postconditions=("save_completed",)),
        _adapter("scene.save_as", postconditions=("output_file", "nonzero_bytes")),
        _adapter("scene.close", postconditions=("tab_absent",)),
        _adapter("scene.list", postconditions=("tab_catalog",)),
        _adapter("scene.activate", postconditions=("tab_active",)),
        _adapter("scene.validate", postconditions=("validation_report",)),
        _adapter("io.import_fbx", postconditions=("scene_changed",)),
        _adapter("io.export_fbx", postconditions=("output_file", "nonzero_bytes")),
        _adapter("io.import_dae", postconditions=("scene_changed", "new_objects"), mode=ExecutionMode.NATIVE),
        _adapter("io.export_dae", postconditions=("output_file", "nonzero_bytes"), mode=ExecutionMode.NATIVE),
        _adapter("io.import_audio", postconditions=("audio_behaviour_count_increased",), mode=ExecutionMode.NATIVE),
        _adapter(
            "io.import_usd", postconditions=("exact_file_dialog", "scene_revision_changed"), mode=ExecutionMode.UIA
        ),
        _adapter(
            "io.export_usd",
            postconditions=("exact_file_dialog", "output_file", "nonzero_bytes"),
            mode=ExecutionMode.UIA,
        ),
        _adapter(
            "io.import_glb",
            postconditions=("exact_options_window", "exact_file_dialog", "scene_revision_changed"),
            mode=ExecutionMode.UIA,
        ),
        _adapter(
            "io.import_gltf",
            postconditions=("exact_options_window", "exact_file_dialog", "scene_revision_changed"),
            mode=ExecutionMode.UIA,
        ),
        _adapter(
            "io.import_vrm",
            postconditions=("exact_options_window", "exact_file_dialog", "scene_revision_changed"),
            mode=ExecutionMode.UIA,
        ),
        _adapter(
            "io.export_glb",
            postconditions=("exact_options_window", "exact_file_dialog", "output_file", "nonzero_bytes"),
            mode=ExecutionMode.UIA,
        ),
        _adapter(
            "io.export_gltf",
            postconditions=("exact_options_window", "exact_file_dialog", "output_file", "nonzero_bytes"),
            mode=ExecutionMode.UIA,
        ),
        _adapter("timeline.set_frame", postconditions=("frame_equals_requested",)),
        _adapter("timeline.get", postconditions=("unclamped_frame",)),
        _adapter("animation.transform_get", postconditions=("transform_payload",)),
        _adapter("animation.transform_set", postconditions=("transform_equals_requested",)),
        _adapter("selection.get", postconditions=("selection_payload",)),
        _adapter("selection.set", postconditions=("selection_equals_requested",)),
        _adapter("selection.add", postconditions=("selection_contains_requested",)),
        _adapter("selection.remove", postconditions=("selection_excludes_requested",)),
        _adapter("selection.filter", postconditions=("filter_matches",)),
        _adapter("object.create", postconditions=("object_present",)),
        _adapter("object.parent", postconditions=("parent_equals_requested",)),
        _adapter("object.unparent", postconditions=("parent_is_null",)),
        _adapter("object.hierarchy", postconditions=("acyclic_parent_graph",)),
        _adapter("object.properties", postconditions=("object_metadata",)),
        _adapter("object.behaviors", postconditions=("behavior_schema",)),
        _adapter("object.rename", postconditions=("name_equals_requested",)),
        _adapter("layer.list", postconditions=("layer_payload",)),
        _adapter("layer.create", postconditions=("layer_present",)),
        _adapter("layer.delete", postconditions=("layer_absent",)),
        _adapter("layer.visibility", postconditions=("visibility_equals_requested",)),
        _adapter("layer.lock", postconditions=("lock_equals_requested",)),
        _adapter("layer.folder", postconditions=("folder_structure_equals_requested",)),
        _adapter(
            "timeline.range",
            preconditions=("valid_frame_interval", "existing_layers"),
            postconditions=("selected_interval_equals_requested",),
        ),
        _adapter("animation.key_list", postconditions=("key_payload",)),
        _adapter("animation.key_add", postconditions=("key_present",)),
        _adapter("animation.key_delete", postconditions=("key_absent",)),
        _adapter("animation.interpolation_set", postconditions=("interpolation_equals_requested",)),
        _adapter("animation.tangent_set", postconditions=("tangent_mode_equals_requested",)),
        _adapter("animation.graph_query", postconditions=("section_payload",)),
        _adapter(
            "animation.cycle_query",
            preconditions=("existing_layers", "valid_frame_interval"),
            postconditions=("normalized_cycle_catalog",),
            mode=ExecutionMode.NATIVE,
        ),
        _adapter(
            "editing.mirror",
            preconditions=("box_controller_ids", "valid_mirror_plane", "valid_frame_or_interval"),
            postconditions=("target_transform_fingerprint_changed",),
            mode=ExecutionMode.NATIVE,
        ),
        _adapter("render.viewport_state", postconditions=("viewport_payload",), mode=ExecutionMode.NATIVE),
        _adapter("render.camera_catalog", postconditions=("camera_payload",), mode=ExecutionMode.NATIVE),
        _adapter("render.camera_view", postconditions=("camera_equals_requested",), mode=ExecutionMode.NATIVE),
        _adapter("render.camera_activate", postconditions=("camera_active",), mode=ExecutionMode.NATIVE),
        _adapter("render.camera_create", postconditions=("new_camera_objects",), mode=ExecutionMode.NATIVE),
        _adapter("render.camera_aim", postconditions=("new_camera_rig_objects",), mode=ExecutionMode.NATIVE),
        _adapter("render.light_point", postconditions=("point_light_count_increased",), mode=ExecutionMode.NATIVE),
        _adapter("render.light_spot", postconditions=("spot_light_count_increased",), mode=ExecutionMode.NATIVE),
        _adapter("render.viewport_capture", postconditions=("output_file", "nonzero_bytes"), mode=ExecutionMode.NATIVE),
        _adapter("render.image", postconditions=("output_file", "nonzero_bytes"), mode=ExecutionMode.NATIVE),
        _adapter("io.export_image", postconditions=("output_file", "nonzero_bytes"), mode=ExecutionMode.NATIVE),
        _adapter(
            "tool.AutoPosingTool",
            preconditions=("selected_character_controllers",),
            postconditions=("scene_revision_changed",),
            mode=ExecutionMode.NATIVE,
        ),
        _adapter("generation.state", postconditions=("generation_precondition_report",), mode=ExecutionMode.NATIVE),
        _adapter(
            "generation.inbetweening",
            preconditions=("pro_license", "selected_timeline_interval", "two_keyframes", "standard_humanoid_rig"),
            postconditions=("scene_revision_changed",),
            mode=ExecutionMode.ACTION,
        ),
        _adapter(
            "generation.root_motion",
            preconditions=("selected_timeline_interval", "two_keyframes", "standard_humanoid_rig"),
            postconditions=("scene_revision_changed",),
            mode=ExecutionMode.ACTION,
        ),
        _adapter(
            "generation.unbaking",
            preconditions=("selected_character_layers", "selected_timeline_interval"),
            postconditions=("scene_revision_changed",),
            mode=ExecutionMode.ACTION,
        ),
        _adapter(
            "physics.auto_state",
            preconditions=("scene",),
            postconditions=("autophysics_prerequisite_report",),
            mode=ExecutionMode.NATIVE,
        ),
        _adapter(
            "physics.auto_enable",
            preconditions=("center_of_mass", "animation_at_least_three_frames"),
            postconditions=("physics_assistant_action_dispatched",),
            mode=ExecutionMode.NATIVE,
        ),
        _adapter(
            "tool.AutoPhysicsTool",
            preconditions=("working_auto_physics", "selected_center_of_mass"),
            postconditions=("scene_revision_changed",),
            mode=ExecutionMode.NATIVE,
        ),
        _adapter("physics.state", postconditions=("physics_inventory",), mode=ExecutionMode.NATIVE),
        _adapter(
            "physics.center_of_mass",
            preconditions=("selected_rigid_bodies",),
            postconditions=("center_of_mass_count_increased",),
            mode=ExecutionMode.ACTION,
        ),
        _adapter(
            "physics.ballistic",
            preconditions=("center_of_mass", "selected_timeline_interval"),
            postconditions=("persisted_ballistic_count_increased",),
            mode=ExecutionMode.ACTION,
        ),
        _adapter(
            "physics.constraint_transform",
            preconditions=("driver_and_constrained_transform",),
            postconditions=("constraint_count_increased",),
            mode=ExecutionMode.NATIVE,
        ),
        _adapter(
            "physics.constraint_point",
            preconditions=("driver_transform", "point_controllers"),
            postconditions=("constraint_count_increased",),
            mode=ExecutionMode.NATIVE,
        ),
        _adapter(
            "physics.collision_create",
            preconditions=("target_objects",),
            postconditions=("collision_count_increased",),
            mode=ExecutionMode.NATIVE,
        ),
        _adapter(
            "physics.collision_delete",
            preconditions=("target_objects_with_collision_behaviours",),
            postconditions=("target_collision_behaviours_absent",),
            mode=ExecutionMode.NATIVE,
        ),
        _adapter("rig.state", postconditions=("rig_inventory",), mode=ExecutionMode.NATIVE),
        _adapter(
            "rig.constraint_drivers",
            postconditions=("constraint_driver_catalog", "scene_unchanged"),
            mode=ExecutionMode.NATIVE,
        ),
        _adapter(
            "rig.mass_set",
            preconditions=("rigid_bodies", "positive_total_mass"),
            postconditions=("total_mass_equals_requested",),
            mode=ExecutionMode.NATIVE,
        ),
        _adapter(
            "rig.joint_create",
            postconditions=("joint_count_increased_by_one", "created_joint_selected"),
            mode=ExecutionMode.NATIVE,
        ),
        _adapter(
            "rig.rig_info_create",
            preconditions=("unlinked_joint_ids",),
            postconditions=("rig_info_count_increased_by_one", "related_joints_equal_request"),
            mode=ExecutionMode.NATIVE,
        ),
        _adapter(
            "rig.ik_chain_create",
            preconditions=("ordered_ends_with_attraction_points", "middle_connection_points"),
            postconditions=("chain_ik_created_on_main_end",),
            mode=ExecutionMode.NATIVE,
        ),
        _adapter(
            "rig.rig_elements_create",
            preconditions=("explicit_joint_pairs", "joint_behaviours", "valid_rig_options"),
            postconditions=("one_technical_links_owner_per_pair", "linked_joints_equal_request"),
            mode=ExecutionMode.NATIVE,
        ),
        _adapter(
            "rig.additional_point_create",
            preconditions=("rig_element_with_technical_links",),
            postconditions=("one_manual_point_link_added",),
            mode=ExecutionMode.NATIVE,
        ),
        _adapter(
            "rig.additional_box_create",
            preconditions=("rig_element_with_technical_links",),
            postconditions=("one_additional_box_link_added",),
            mode=ExecutionMode.NATIVE,
        ),
        _adapter(
            "rig.spline_ik_create",
            preconditions=("two_joint_endpoints", "same_hierarchy_branch", "full_rig_elements"),
            postconditions=("one_proto_spline_ik_created", "resolved_hierarchy_references_equal"),
            mode=ExecutionMode.NATIVE,
        ),
        _adapter(
            "rig.twist",
            preconditions=("proto_box", "related_twist_joint", "no_rigid_body_on_rig_element"),
            postconditions=("proto_box_twist_reference_equals_request",),
            mode=ExecutionMode.NATIVE,
        ),
        _adapter(
            "animation.key_reduce",
            preconditions=("layer_ids", "valid_frame_interval", "positive_every_n"),
            postconditions=("observed_keys_equal_reduction_plan",),
            mode=ExecutionMode.NATIVE,
        ),
        _adapter("system.undo", postconditions=("scene_revision_changed",)),
        _adapter("system.redo", postconditions=("scene_revision_changed",)),
        _adapter("system.action_invoke", postconditions=("declared_postcondition",)),
        _adapter("system.csc_query", postconditions=("json_safe_result",)),
        _adapter("system.csc_mutate", postconditions=("registered_mutation", "scene_revision_changed")),
        _adapter("system.developer_execute_python", postconditions=("policy_enabled",)),
    ]
)


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", ".", value.lower()).strip(".")


def _record(
    spec: CoreSpec,
    license_name: str,
    scene_available: bool,
    available_tools: set[str],
    available_commands: set[str],
    version_name: str,
    verified_features: set[str],
    developer_enabled: bool,
) -> FeatureRecord:
    adapter = ADAPTER_SPECS.get(spec.route)
    tool_missing = spec.route.startswith("tool.") and spec.route.removeprefix("tool.") not in available_tools
    command_missing = (
        spec.route.startswith("command.") and spec.route.removeprefix("command.") not in available_commands
    )
    dependency = spec.dependency
    if spec.feature_id == "developer_execute_python" and not developer_enabled:
        dependency = "Local policy developer_execute_python=true"
    if not version_name.startswith("2026.1.") or spec.feature_id == "export_vrm":
        state = CapabilityState.UNSUPPORTED_VERSION
        mode = ExecutionMode.GATED
    elif spec.license == "pro" and license_name.lower() != "pro":
        state = CapabilityState.LICENSE_GATED
        mode = ExecutionMode.GATED
    elif dependency:
        state = CapabilityState.MISSING_DEPENDENCY
        mode = ExecutionMode.GATED if spec.feature_id == "developer_execute_python" else ExecutionMode.EXTERNAL
    elif adapter and (not adapter.requires_live or spec.feature_id in verified_features):
        state = (
            CapabilityState.NEEDS_SCENE if spec.requires_scene and not scene_available else CapabilityState.AVAILABLE
        )
        mode = adapter.mode or spec.mode
    elif adapter:
        state = CapabilityState.UNHEALTHY
        mode = adapter.mode or spec.mode
    elif tool_missing or command_missing or spec.route.startswith(("action.", "tool.", "command.")):
        state = CapabilityState.UI_ONLY
        mode = ExecutionMode.UIA
    elif spec.mode == ExecutionMode.NATIVE:
        state = CapabilityState.UNHEALTHY
        mode = spec.mode
    else:
        state = CapabilityState.UI_ONLY
        mode = ExecutionMode.UIA
    verification = VerificationState.DISCOVERED
    evidence_kind = "none"
    last_verified_version = None
    if dependency:
        verification = VerificationState.GATED
        evidence_kind = "gate"
    elif adapter:
        verification = VerificationState.IMPLEMENTED
        evidence_kind = "handler"
        if not adapter.requires_live:
            verification = VerificationState.CONTRACT
            evidence_kind = "contract"
        elif spec.feature_id in verified_features:
            verification = VerificationState.VERIFIED_LIVE
            evidence_kind = "live"
            last_verified_version = version_name
    return FeatureRecord(
        id=spec.feature_id,
        family=spec.family,
        name=spec.name,
        description=f"Cascadeur {spec.name} capability",
        execution_mode=mode,
        state=state,
        route=spec.route,
        test_id=f"feature::{spec.feature_id}",
        test_ids=list(adapter.test_ids) if adapter else [f"feature::{spec.feature_id}"],
        adapter_id=adapter.adapter_id if adapter else None,
        preconditions=list(adapter.preconditions) if adapter else [],
        postconditions=list(adapter.postconditions) if adapter else [],
        verification=verification,
        evidence_kind=evidence_kind,
        last_verified_version=last_verified_version,
        requires_scene=spec.requires_scene,
        destructive=spec.destructive,
        license=spec.license,  # type: ignore[arg-type]
        dependency=dependency,
        source="Cascadeur 2026.1 tools and release inventory",
    )


def _walk_schema(node: dict, prefix: tuple[str, ...] = ()):
    for name, value in node.items():
        if isinstance(value, dict) and "type" in value:
            yield prefix + (name,), value
            for method in value.get("methods", []):
                yield prefix + (name, method), {"type": "method", "doc": ""}
            for member in value.get("values", []):
                yield prefix + (name, member), {"type": "value", "doc": ""}
        elif isinstance(value, dict):
            yield from _walk_schema(value, prefix + (name,))


def schema_records(schema: dict) -> list[FeatureRecord]:
    records: list[FeatureRecord] = []
    for path, meta in _walk_schema(schema):
        dotted = ".".join(path)
        identity = "api." + _slug(dotted)
        kind = meta.get("type", "symbol")
        records.append(
            FeatureRecord(
                id=identity,
                family="csc_api",
                name=dotted,
                description=(meta.get("doc") or f"Installed csc {kind}")[:500],
                execution_mode=ExecutionMode.NATIVE,
                state=CapabilityState.AVAILABLE if len(path) < 3 else CapabilityState.NEEDS_SCENE,
                route=f"csc_query:{dotted}",
                test_id=f"schema::{hashlib.sha1(dotted.encode()).hexdigest()[:12]}",
                test_ids=[f"schema::{hashlib.sha1(dotted.encode()).hexdigest()[:12]}"],
                adapter_id="cascadeur_2026_1.system.csc_query",
                preconditions=["installed_symbol"],
                postconditions=["schema_presence"],
                verification=VerificationState.CONTRACT,
                evidence_kind="schema",
                requires_scene=len(path) >= 3,
                source="installed csc schema",
            )
        )
    return records


def command_records(commands: Iterable[dict[str, str]]) -> list[FeatureRecord]:
    result = []
    for command in commands:
        name = command["name"]
        result.append(
            FeatureRecord(
                id="command." + _slug(name),
                family="python_command",
                name=name,
                description=command.get("description", "Installed Cascadeur Python command"),
                execution_mode=ExecutionMode.ACTION,
                state=CapabilityState.NEEDS_SCENE,
                route=f"action_invoke:{name}",
                test_id=f"command::{hashlib.sha1(name.encode()).hexdigest()[:12]}",
                test_ids=[f"command::{hashlib.sha1(name.encode()).hexdigest()[:12]}"],
                verification=VerificationState.DISCOVERED,
                evidence_kind="none",
                source=command.get("path", "installed Python command"),
                destructive=True,
            )
        )
    return result


def tool_records(tools: Iterable[str]) -> list[FeatureRecord]:
    return [
        FeatureRecord(
            id="gui_tool." + _slug(name),
            family="gui_tool",
            name=name,
            description=f"Runtime-registered Cascadeur GUI tool {name}",
            execution_mode=ExecutionMode.ACTION,
            state=CapabilityState.UI_ONLY,
            route=f"tool:{name}",
            test_id=f"tool::{hashlib.sha1(name.encode()).hexdigest()[:12]}",
            test_ids=[f"tool::{hashlib.sha1(name.encode()).hexdigest()[:12]}"],
            verification=VerificationState.DISCOVERED,
            evidence_kind="none",
            source="runtime ToolsManager",
        )
        for name in sorted(set(tools))
    ]


def build_registry(
    schema: dict,
    commands: Iterable[dict[str, str]],
    tools: Iterable[str],
    *,
    license_name: str = "Basic",
    scene_available: bool = False,
    version_name: str = "2026.1.2.0.15343",
    verified_features: Iterable[str] = (),
    developer_enabled: bool = False,
) -> list[FeatureRecord]:
    tool_set = set(tools)
    command_list = list(commands)
    command_set = {item["name"] for item in command_list}
    verified_set = set(verified_features)
    records = [
        _record(
            spec,
            license_name,
            scene_available,
            tool_set,
            command_set,
            version_name,
            verified_set,
            developer_enabled,
        )
        for spec in CORE_FEATURES
    ]
    records.extend(schema_records(schema))
    records.extend(command_records(command_list))
    records.extend(tool_records(tool_set))
    unique: dict[str, FeatureRecord] = {}
    for record in records:
        unique[record.id] = record
    return sorted(unique.values(), key=lambda item: item.id)


def registry_json(records: list[FeatureRecord]) -> str:
    payload = {
        "schema_version": 2,
        "feature_count": len(records),
        "unclassified_count": sum(
            not item.execution_mode or not item.test_ids or not item.evidence_kind for item in records
        ),
        "features": [item.model_dump(mode="json") for item in records],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)
