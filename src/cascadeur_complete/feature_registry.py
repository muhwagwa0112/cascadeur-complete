from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass

from .adapter_bindings import BINDINGS, BY_OPERATION
from .build_profile import DEVELOPER_BUILD
from .models import CapabilityState, ExecutionMode, FeatureRecord, VerificationState
from .product_catalog import PRODUCT_CATALOG, PRODUCT_VERSION, SUPPORTED_BUILD, ProductFeature

# Generic csc/Python execution is compiled out of release builds; these rows are
# gated by the developer build policy rather than implemented for production.
DEVELOPER_POLICY = "Developer build with local developer_mode and generic_api policy"


@dataclass(frozen=True)
class CoreSpec:
    family: str
    feature_id: str
    name: str
    route: str
    mode: ExecutionMode = ExecutionMode.NATIVE
    requires_scene: bool = True
    license: str = "any"
    dependency: str | None = None


def _specs(
    family: str,
    names: str,
    *,
    mode: ExecutionMode = ExecutionMode.NATIVE,
    no_scene: Iterable[str] = (),
    pro: Iterable[str] = (),
    dependencies: dict[str, str] | None = None,
) -> list[CoreSpec]:
    no_scene_set, pro_set = set(no_scene), set(pro)
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
    )
    + _specs(
        "editing",
        """
tween|Tween|tool.Tween mirror|Mirror|editing.mirror copy_animation|Copy|tool.Copier
interval_edit|Interval_edit|tool.Timeline trajectory|Trajectory|tool.TrajectoryTool
ghost|Ghost|tool.GhostTool fixing|Fixing|tool.FixFootTool hiding|Hiding|action.hiding
""",
        mode=ExecutionMode.ACTION,
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
        dependencies={
            "csc_query": DEVELOPER_POLICY,
            "csc_mutate": DEVELOPER_POLICY,
            "developer_execute_python": DEVELOPER_POLICY,
        },
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


def _binding_specs(specs: list[CoreSpec]) -> tuple[CoreSpec, ...]:
    """Apply dedicated adapter bindings on top of the legacy core table."""
    by_id = {spec.feature_id: spec for spec in specs}
    for binding in BINDINGS:
        product = PRODUCT_CATALOG.by_id.get(binding.feature_id)
        legacy = by_id.get(binding.feature_id)
        if legacy is None and product is None:
            continue
        by_id[binding.feature_id] = CoreSpec(
            family=legacy.family if legacy else product.family,
            feature_id=binding.feature_id,
            name=legacy.name if legacy else product.name,
            route=binding.operation,
            mode=binding.mode,
            requires_scene=binding.requires_scene,
            license=legacy.license if legacy else product.license,
            dependency=legacy.dependency if legacy else product.dependency,
        )
    return tuple(by_id.values())


CORE_FEATURES = _binding_specs(list(CORE_FEATURES))


@dataclass(frozen=True)
class AdapterSpec:
    """A route with a dedicated adapter. Its contract (pre/postconditions, tests,
    mutation) lives in the product catalog JSON, which is the single source of truth."""

    adapter_id: str
    requires_live: bool = True
    mode: ExecutionMode | None = None


def _adapter(
    route: str, *, requires_live: bool = True, mode: ExecutionMode | None = None
) -> tuple[str, AdapterSpec]:
    return route, AdapterSpec(adapter_id=f"cascadeur_2026_1.{route}", requires_live=requires_live, mode=mode)


ADAPTER_SPECS = dict(
    [
        _adapter("host.feature_search", requires_live=False),
        _adapter("host.feature_describe", requires_live=False),
        # Dispatchers reach Cascadeur: they need live evidence from a concrete
        # bound command or UI file flow, not just the host binding contract.
        _adapter("host.action_dispatcher"),
        _adapter("host.ui_flow_prepare"),
        _adapter("host.inventory_refresh"),
        _adapter("system.status"),
        _adapter("system.logs", mode=ExecutionMode.NATIVE),
        _adapter("system.view_mode", mode=ExecutionMode.NATIVE),
        _adapter("scene.summary"),
        _adapter("scene.objects"),
        _adapter("scene.new"),
        _adapter("scene.open"),
        _adapter("scene.save"),
        _adapter("scene.save_as"),
        _adapter("scene.close"),
        _adapter("scene.list"),
        _adapter("scene.activate"),
        _adapter("scene.validate"),
        _adapter("io.import_fbx"),
        _adapter("io.export_fbx"),
        _adapter("io.import_dae", mode=ExecutionMode.NATIVE),
        _adapter("io.export_dae", mode=ExecutionMode.NATIVE),
        _adapter("io.import_audio", mode=ExecutionMode.NATIVE),
        _adapter("io.import_usd", mode=ExecutionMode.UIA),
        _adapter("io.export_usd", mode=ExecutionMode.UIA),
        _adapter("io.import_glb", mode=ExecutionMode.UIA),
        _adapter("io.import_gltf", mode=ExecutionMode.UIA),
        _adapter("io.import_vrm", mode=ExecutionMode.UIA),
        _adapter("io.export_glb", mode=ExecutionMode.UIA),
        _adapter("io.export_gltf", mode=ExecutionMode.UIA),
        _adapter("timeline.set_frame"),
        _adapter("timeline.get"),
        _adapter("animation.transform_get"),
        _adapter("animation.transform_set"),
        _adapter("selection.get"),
        _adapter("selection.set"),
        _adapter("selection.add"),
        _adapter("selection.remove"),
        _adapter("selection.filter"),
        _adapter("object.create"),
        _adapter("object.parent"),
        _adapter("object.unparent"),
        _adapter("object.hierarchy"),
        _adapter("object.properties"),
        _adapter("object.behaviors"),
        _adapter("object.rename"),
        _adapter("layer.list"),
        _adapter("layer.create"),
        _adapter("layer.delete"),
        _adapter("layer.visibility"),
        _adapter("layer.lock"),
        _adapter("layer.folder"),
        _adapter("timeline.range"),
        _adapter("animation.key_list"),
        _adapter("animation.key_add"),
        _adapter("animation.key_delete"),
        _adapter("animation.interpolation_set"),
        _adapter("animation.tangent_set"),
        _adapter("animation.graph_query"),
        _adapter("animation.cycle_query", mode=ExecutionMode.NATIVE),
        _adapter("editing.mirror", mode=ExecutionMode.NATIVE),
        _adapter("render.viewport_state", mode=ExecutionMode.NATIVE),
        _adapter("render.camera_catalog", mode=ExecutionMode.NATIVE),
        _adapter("render.camera_view", mode=ExecutionMode.NATIVE),
        _adapter("render.camera_activate", mode=ExecutionMode.NATIVE),
        _adapter("render.camera_create", mode=ExecutionMode.NATIVE),
        _adapter("render.camera_aim", mode=ExecutionMode.NATIVE),
        _adapter("render.light_point", mode=ExecutionMode.NATIVE),
        _adapter("render.light_spot", mode=ExecutionMode.NATIVE),
        _adapter("render.viewport_capture", mode=ExecutionMode.NATIVE),
        _adapter("render.image", mode=ExecutionMode.NATIVE),
        _adapter("io.export_image", mode=ExecutionMode.NATIVE),
        _adapter("tool.AutoPosingTool", mode=ExecutionMode.NATIVE),
        _adapter("generation.state", mode=ExecutionMode.NATIVE),
        _adapter("generation.inbetweening", mode=ExecutionMode.ACTION),
        _adapter("generation.root_motion", mode=ExecutionMode.ACTION),
        _adapter("generation.unbaking", mode=ExecutionMode.ACTION),
        _adapter("physics.auto_state", mode=ExecutionMode.NATIVE),
        _adapter("physics.auto_enable", mode=ExecutionMode.NATIVE),
        _adapter("tool.AutoPhysicsTool", mode=ExecutionMode.NATIVE),
        _adapter("physics.state", mode=ExecutionMode.NATIVE),
        _adapter("physics.center_of_mass", mode=ExecutionMode.ACTION),
        _adapter("physics.ballistic", mode=ExecutionMode.ACTION),
        _adapter("physics.constraint_transform", mode=ExecutionMode.NATIVE),
        _adapter("physics.constraint_point", mode=ExecutionMode.NATIVE),
        _adapter("physics.collision_create", mode=ExecutionMode.NATIVE),
        _adapter("physics.collision_delete", mode=ExecutionMode.NATIVE),
        _adapter("rig.state", mode=ExecutionMode.NATIVE),
        _adapter("rig.constraint_drivers", mode=ExecutionMode.NATIVE),
        _adapter("rig.mass_set", mode=ExecutionMode.NATIVE),
        _adapter("rig.joint_create", mode=ExecutionMode.NATIVE),
        _adapter("rig.rig_info_create", mode=ExecutionMode.NATIVE),
        _adapter("rig.ik_chain_create", mode=ExecutionMode.NATIVE),
        _adapter("rig.rig_elements_create", mode=ExecutionMode.NATIVE),
        _adapter("rig.additional_point_create", mode=ExecutionMode.NATIVE),
        _adapter("rig.additional_box_create", mode=ExecutionMode.NATIVE),
        _adapter("rig.spline_ik_create", mode=ExecutionMode.NATIVE),
        _adapter("rig.twist", mode=ExecutionMode.NATIVE),
        _adapter("animation.key_reduce", mode=ExecutionMode.NATIVE),
        _adapter("system.undo"),
        _adapter("system.redo"),
        _adapter("system.action_invoke"),
        _adapter("system.csc_query"),
        _adapter("system.csc_mutate"),
        _adapter("system.developer_execute_python"),
    ]
    + [
        _adapter(operation, mode=bindings[0].mode)
        for operation, bindings in sorted(BY_OPERATION.items())
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
    available_dependencies: set[str] = frozenset(),
) -> FeatureRecord:
    adapter = ADAPTER_SPECS.get(spec.route)
    # Every core spec has a catalog entry (tests/test_inventory.py pins this).
    product = PRODUCT_CATALOG.by_id[spec.feature_id]
    tool_missing = spec.route.startswith("tool.") and spec.route.removeprefix("tool.") not in available_tools
    command_missing = (
        spec.route.startswith("command.") and spec.route.removeprefix("command.") not in available_commands
    )
    required_dependency = spec.dependency
    # A dependency detected on this machine no longer gates the adapter; the
    # record still names it so callers know what the route relies on.
    dependency = None if required_dependency in available_dependencies else required_dependency
    if spec.feature_id == "developer_execute_python" and developer_enabled and DEVELOPER_BUILD:
        dependency = None
    if version_name != PRODUCT_CATALOG.supported_build:
        state = CapabilityState.UNSUPPORTED_VERSION
        mode = ExecutionMode.GATED
    elif product.implementation_status == "unsupported":
        state = CapabilityState.UNSUPPORTED
        mode = ExecutionMode.GATED
    elif spec.license == "pro" and license_name.lower() != "pro":
        state = CapabilityState.LICENSE_GATED
        mode = ExecutionMode.GATED
    elif dependency:
        state = CapabilityState.MISSING_DEPENDENCY
        mode = ExecutionMode.GATED if dependency == DEVELOPER_POLICY else ExecutionMode.EXTERNAL
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
    if product.implementation_status == "unsupported" or dependency:
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
        test_id=(
            product.contract_test_ids[0]
            if product.contract_test_ids
            else "tests/test_inventory.py::test_product_catalog_core_matches_registry_contract"
        ),
        test_ids=(
            list(product.contract_test_ids)
            if product.contract_test_ids
            else ["tests/test_inventory.py::test_product_catalog_core_matches_registry_contract"]
        ),
        adapter_id=adapter.adapter_id if adapter else None,
        preconditions=list(product.preconditions),
        postconditions=list(product.postconditions),
        verification=verification,
        evidence_kind=evidence_kind,
        last_verified_version=last_verified_version,
        requires_scene=spec.requires_scene,
        destructive=product.mutation,
        license=spec.license,  # type: ignore[arg-type]
        dependency=required_dependency if dependency is None and required_dependency else dependency,
        source=product.source_url,
        source_url=product.source_url,
        public_action=product.action,
        operation_id=product.operation,
        fixture_id=product.fixture_id,
        arguments=dict(product.arguments),
        fixed_arguments=dict(product.fixed_arguments),
        mutation=product.mutation,
        contract_status=(
            "bound"
            if adapter
            else (
                "gate"
                if dependency or product.implementation_status == "unsupported"
                else "not_implemented"
            )
        ),
        truth_layer="product",
    )


def _official_gap_record(feature: ProductFeature) -> FeatureRecord:
    test_ids = list(feature.contract_test_ids)
    return FeatureRecord(
        id=feature.id,
        family=feature.family,
        name=feature.name,
        description=(
            f"Official Cascadeur {PRODUCT_VERSION} feature without a postcondition-safe MCP adapter: {feature.name}"
        ),
        execution_mode=ExecutionMode.GATED,
        state=CapabilityState.NOT_IMPLEMENTED,
        route=f"not_implemented:{feature.id}",
        test_id=test_ids[0],
        test_ids=test_ids,
        adapter_id=None,
        preconditions=list(feature.preconditions),
        postconditions=list(feature.postconditions),
        verification=VerificationState.DISCOVERED,
        evidence_kind="none",
        requires_scene=feature.requires_scene,
        destructive=feature.mutation,
        license=feature.license,  # type: ignore[arg-type]
        dependency=feature.dependency,
        source=feature.source_url,
        since=feature.since,
        source_url=feature.source_url,
        public_action=feature.action,
        operation_id=feature.operation,
        fixture_id=feature.fixture_id,
        mutation=feature.mutation,
        contract_status="not_implemented",
        truth_layer="product",
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
                test_id="tests/test_inventory.py::test_discovered_inventory_is_separate_from_product_catalog",
                test_ids=["tests/test_inventory.py::test_discovered_inventory_is_separate_from_product_catalog"],
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
                test_id="tests/test_inventory.py::test_discovered_inventory_is_separate_from_product_catalog",
                test_ids=["tests/test_inventory.py::test_discovered_inventory_is_separate_from_product_catalog"],
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
            test_id="tests/test_inventory.py::test_discovered_inventory_is_separate_from_product_catalog",
            test_ids=["tests/test_inventory.py::test_discovered_inventory_is_separate_from_product_catalog"],
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
    version_name: str = SUPPORTED_BUILD,
    verified_features: Iterable[str] = (),
    developer_enabled: bool = False,
    available_dependencies: Iterable[str] = (),
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
            set(available_dependencies),
        )
        for spec in CORE_FEATURES
    ]
    records.extend(_official_gap_record(feature) for feature in PRODUCT_CATALOG.official_gaps)
    records.extend(schema_records(schema))
    records.extend(command_records(command_list))
    records.extend(tool_records(tool_set))
    if version_name != PRODUCT_CATALOG.supported_build:
        # Discovered API/command/tool rows are inventory, not an alternate way
        # around the build pin. Fail closed across every truth layer.
        for record in records:
            record.state = CapabilityState.UNSUPPORTED_VERSION
            record.execution_mode = ExecutionMode.GATED
            record.verification = VerificationState.GATED
            record.evidence_kind = "gate"
    unique: dict[str, FeatureRecord] = {}
    for record in records:
        unique[record.id] = record
    return sorted(unique.values(), key=lambda item: item.id)


def registry_json(records: list[FeatureRecord]) -> str:
    product_ids = set(PRODUCT_CATALOG.by_id)
    payload = {
        "schema_version": 3,
        "product_catalog": {
            "product_version": PRODUCT_CATALOG.product_version,
            "supported_build": PRODUCT_CATALOG.supported_build,
            "feature_count": len(PRODUCT_CATALOG.features),
            "core_feature_count": len(PRODUCT_CATALOG.core_features),
            "official_gap_count": len(PRODUCT_CATALOG.official_gaps),
        },
        "feature_count": len(records),
        "unclassified_count": sum(
            item.id in product_ids
            and (not item.execution_mode or not item.test_ids or item.evidence_kind == "none")
            for item in records
        ),
        "features": [item.model_dump(mode="json") for item in records],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)
