"""Single source of truth for product features bound to dedicated bridge adapters.

Each binding names the bridge operation, the exact postconditions the adapter
proves, and any arguments fixed by the feature (several features can share one
operation, e.g. the three hinge actions). ``scripts/sync_adapter_catalog.py``
writes these bindings into the product catalog; the feature registry and the
service read them at runtime, so the catalog, registry and binding checks
cannot drift apart.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from .models import ExecutionMode


@dataclass(frozen=True)
class AdapterBinding:
    feature_id: str
    operation: str
    postconditions: tuple[str, ...]
    preconditions: tuple[str, ...] = ("compatible_version",)
    fixed_arguments: MappingProxyType = field(default_factory=lambda: MappingProxyType({}))
    arguments: MappingProxyType = field(default_factory=lambda: MappingProxyType({}))
    replaces: str | None = None  # official_gap.* catalog id promoted by this binding
    mode: ExecutionMode = ExecutionMode.NATIVE
    mutation: bool = True
    requires_scene: bool = True


def _b(
    feature_id: str,
    operation: str,
    postconditions: tuple[str, ...],
    *,
    fixed: dict[str, Any] | None = None,
    arguments: dict[str, str] | None = None,
    preconditions: tuple[str, ...] = ("compatible_version",),
    gap: bool = False,
    mode: ExecutionMode = ExecutionMode.NATIVE,
    mutation: bool = True,
) -> AdapterBinding:
    return AdapterBinding(
        feature_id=feature_id,
        operation=operation,
        postconditions=postconditions,
        preconditions=preconditions,
        fixed_arguments=MappingProxyType(dict(fixed or {})),
        arguments=MappingProxyType(dict(arguments or {})),
        replaces=f"official_gap.{feature_id}" if gap else None,
        mode=mode,
        mutation=mutation,
    )


VALUES = {"ids": "object IDs (defaults to every owner of the behaviour)", "values": "{property: value}"}
LAYER_INTERVAL = {"layer_ids": "layer GUIDs (default: all)", "first_frame": "int", "last_frame": "int"}

BINDINGS: tuple[AdapterBinding, ...] = (
    # -- objects / editing ---------------------------------------------------------
    _b("object_delete", "objects.delete", ("objects_absent",), arguments={"ids": "object IDs"}),
    _b("object_duplicate", "objects.duplicate", ("one_duplicate_created",), arguments={"id": "object ID"}),
    _b(
        "hiding",
        "objects.visibility",
        ("behaviour_values_equal_request",),
        arguments={"ids": "object IDs", "values": '{"visibility": bool}'},
    ),
    _b(
        "tween",
        "editing.tween",
        ("target_transform_fingerprint_changed",),
        arguments={
            "ids": "point/controller IDs",
            "mode": "Previous|Next|Inertial|InverseInertial|Average",
            "frame": "int",
        },
    ),
    _b("fixing", "editing.fix_foot", ("scene_revision_changed",), arguments={"ids": "IDs", **LAYER_INTERVAL}),
    _b(
        "collision_clean",
        "physics.fix_collisions",
        ("scene_revision_changed",),
        arguments={"ids": "IDs", **LAYER_INTERVAL},
    ),
    # -- timeline -----------------------------------------------------------------
    _b("cycle", "timeline.cycle", ("cycle_present",), fixed={"action": "create"}, arguments=LAYER_INTERVAL),
    _b("bake", "timeline.bake", ("every_frame_is_key",), arguments=LAYER_INTERVAL),
    _b(
        "stretch",
        "timeline.stretch",
        ("keys_retimed_to_request",),
        arguments={**LAYER_INTERVAL, "new_last_frame": "int"},
    ),
    _b(
        "interval_edit",
        "timeline.interval_edit",
        ("frame_count_changed_by_request",),
        arguments={**LAYER_INTERVAL, "action": "add|remove"},
    ),
    _b(
        "copy_animation",
        "timeline.copy_interval",
        ("destination_keys_match_source",),
        arguments={**LAYER_INTERVAL, "target_frame": "int"},
    ),
    _b(
        "fulcrum",
        "timeline.fulcrum",
        ("key_fixation_equals_request",),
        fixed={"state": "Fulcrum"},
        arguments=LAYER_INTERVAL,
    ),
    _b(
        "fulcrum_cleaning",
        "timeline.fulcrum",
        ("key_fixation_equals_request",),
        fixed={"state": "Free"},
        arguments=LAYER_INTERVAL,
    ),
    _b("timeline_play", "timeline.playback", ("playback_frames_advance",), fixed={"state": "play"}),
    _b("timeline_stop", "timeline.playback", ("playback_frame_stable",), fixed={"state": "stop"}),
    _b("layer_activate", "layer.activate", ("active_layer_equals_request",), arguments={"layer_id": "layer GUID"}),
    _b(
        "graph_edit",
        "animation.section_edit",
        ("section_equals_request",),
        arguments={
            "layer_id": "layer GUID",
            "frame": "key frame",
            "interpolation": "optional Interpolation name",
            "tangents": "optional Tangents name",
            "ik_fk": "optional IK|FK",
            "fixation": "optional Free|Fulcrum",
        },
    ),
    # -- physics / AutoPhysics ----------------------------------------------------
    _b("ragdoll", "physics.ragdoll", ("behaviour_values_equal_request",), arguments={**VALUES, "add_missing": "bool"}),
    _b(
        "penetration_clean",
        "physics.penetration_cleaning",
        ("behaviour_presence_equals_request",),
        arguments={"ids": "IDs", "enabled": "bool"},
    ),
    _b(
        "autophysics_priority_frames",
        "physics.autophysics_priority_frames",
        ("behaviour_values_equal_request",),
        arguments=VALUES,
        gap=True,
    ),
    _b(
        "autophysics_corrector",
        "physics.autophysics_corrector",
        ("behaviour_presence_equals_request",),
        arguments={"ids": "IDs", "enabled": "bool"},
        gap=True,
    ),
    _b(
        "autophysics_smooth_trajectory",
        "physics.autophysics_smooth_trajectory",
        ("behaviour_values_equal_request",),
        arguments=VALUES,
        gap=True,
    ),
    _b(
        "autophysics_smooth_rotation",
        "physics.autophysics_smooth_rotation",
        ("behaviour_values_equal_request",),
        arguments=VALUES,
        gap=True,
    ),
    _b(
        "autophysics_compensation_motion",
        "physics.compensation_motion",
        ("behaviour_values_equal_request",),
        arguments={**VALUES, "add_missing": "bool"},
        gap=True,
    ),
    _b(
        "autophysics_separation_motion",
        "physics.separation_motion",
        ("behaviour_values_equal_request",),
        arguments={**VALUES, "add_missing": "bool"},
        gap=True,
    ),
    _b(
        "autophysics_secondary_motion",
        "physics.secondary_motion",
        ("behaviour_values_equal_request",),
        arguments={**VALUES, "add_missing": "bool"},
        gap=True,
    ),
    _b(
        "autophysics_point_settings",
        "physics.autophysics_point_settings",
        ("behaviour_values_equal_request",),
        arguments=VALUES,
        gap=True,
    ),
    _b(
        "autophysics_restore_unbound",
        "physics.autophysics_restore",
        ("autophysics_values_restored",),
        arguments={"center_of_mass_id": "CoM ID", "point_ids": "point IDs"},
        gap=True,
    ),
    # -- rigging (Rig Mode prototypes) ---------------------------------------------
    _b("generate_rig", "rig.mode", ("rig_generated_from_prototypes",), fixed={"action": "off"}, gap=True),
    _b("rig_regenerate", "rig.mode", ("rig_generated_from_prototypes",), fixed={"action": "regenerate"}),
    _b(
        "rig_element_delete",
        "rig.element_delete",
        ("rig_elements_absent",),
        arguments={"rig_element_ids": "IDs"},
        gap=True,
    ),
    _b(
        "joint_delete",
        "rig.joint_delete",
        ("joint_branch_absent",),
        arguments={"joint_id": "standard rig joint"},
        gap=True,
    ),
    _b(
        "virtual_joint_create",
        "rig.virtual_joint",
        ("virtual_joint_created",),
        fixed={"action": "create"},
        arguments={"joint_id": "parent joint"},
        gap=True,
    ),
    _b(
        "virtual_joint_delete",
        "rig.virtual_joint",
        ("virtual_joint_absent",),
        fixed={"action": "delete"},
        arguments={"joint_id": "virtual joint"},
        gap=True,
    ),
    _b(
        "snap_rig",
        "rig.snap",
        ("snap_positions_equal",),
        fixed={"mode": "rig_to_joint"},
        arguments={"id": "rig element"},
        gap=True,
    ),
    _b(
        "snap_joint",
        "rig.snap",
        ("snap_positions_equal",),
        fixed={"mode": "joint_to_rig"},
        arguments={"id": "virtual joint"},
        gap=True,
    ),
    _b(
        "prototype_mirror",
        "rig.prototype_mirror",
        ("mirrored_rig_elements_created",),
        arguments={"rig_element_ids": "IDs", "original_suffix": "_l", "mirror_suffix": "_r", "mirror_plane": "0-3"},
        gap=True,
    ),
    _b(
        "hinge_union",
        "rig.hinge",
        ("hinge_additional_points_coincide",),
        fixed={"action": "union"},
        arguments={"rig_element_ids": "two IDs"},
        gap=True,
    ),
    _b(
        "hinge_orthogonalize",
        "rig.hinge",
        ("hinge_additional_points_coincide",),
        fixed={"action": "orthogonalize"},
        arguments={"rig_element_ids": "two IDs"},
        gap=True,
    ),
    _b(
        "hinge_straighten",
        "rig.hinge",
        ("hinge_additional_points_coincide",),
        fixed={"action": "straighten"},
        arguments={"rig_element_ids": "two IDs"},
        gap=True,
    ),
    _b("clear_animation_data", "rig.clear_animation_data", ("preserved_data_empty",), gap=True),
    _b(
        "prototype_com_remove",
        "rig.proto_center_of_mass_remove",
        ("proto_center_of_mass_absent",),
        arguments={"center_of_mass_ids": "IDs"},
        gap=True,
    ),
    _b(
        "prototype_fulcrum_groups",
        "rig.fulcrum_group",
        ("fulcrum_group_present",),
        fixed={"action": "create"},
        arguments={"rig_element_ids": "IDs"},
        gap=True,
    ),
    _b(
        "root_constraint_add",
        "rig.root_constraint",
        ("root_constraint_present",),
        fixed={"action": "add"},
        arguments={"root_id": "ID", "rig_element_id": "ID"},
        gap=True,
    ),
    _b(
        "root_constraint_remove",
        "rig.root_constraint",
        ("root_constraint_absent",),
        fixed={"action": "remove"},
        arguments={"constraint_id": "ID"},
        gap=True,
    ),
    _b(
        "additional_controller_remove",
        "rig.additional_controller_remove",
        ("additional_controller_absent",),
        arguments={"kind": "point|box", "controller_id": "ID"},
        gap=True,
    ),
    _b(
        "custom_additional_point_set",
        "rig.technical_link",
        ("technical_link_equals_request",),
        fixed={"kind": "user_additional_point", "action": "set"},
        arguments={"rig_element_id": "ID", "target_id": "manual point"},
        gap=True,
    ),
    _b(
        "custom_additional_point_remove",
        "rig.technical_link",
        ("technical_link_equals_request",),
        fixed={"kind": "user_additional_point", "action": "remove"},
        arguments={"rig_element_id": "ID"},
        gap=True,
    ),
    _b(
        "additional_joint_attach",
        "rig.technical_link",
        ("technical_link_equals_request",),
        fixed={"kind": "additional_joint", "action": "set"},
        arguments={"rig_element_id": "ID", "target_id": "joint"},
        gap=True,
    ),
    _b(
        "additional_joint_detach",
        "rig.technical_link",
        ("technical_link_equals_request",),
        fixed={"kind": "additional_joint", "action": "remove"},
        arguments={"rig_element_id": "ID"},
        gap=True,
    ),
    _b(
        "additional_parent",
        "rig.technical_link",
        ("technical_link_equals_request",),
        fixed={"kind": "additional_parent"},
        arguments={"rig_element_id": "ID", "target_id": "rig element", "action": "set|remove"},
        gap=True,
    ),
    _b(
        "custom_rotation",
        "rig.technical_link",
        ("technical_link_equals_request",),
        fixed={"kind": "custom_rotation"},
        arguments={"rig_element_id": "ID", "target_id": "rig element", "action": "set|remove"},
        gap=True,
    ),
    _b(
        "autoposing_props",
        "rig.autoposing_props",
        ("autoposing_names_equal_request",),
        arguments={"rig_element_ids": "IDs", "enabled": "bool"},
        gap=True,
    ),
    _b(
        "character_mirror_plane",
        "rig.character_mirror_plane",
        ("mirror_plane_equals_request",),
        arguments={"plane": "0 YZ|1 XZ|2 XY|3 undefined"},
        gap=True,
    ),
    _b(
        "rig_json_export",
        "rig.json_export",
        ("output_file", "nonzero_bytes"),
        arguments={"path": "destination .json"},
        gap=True,
    ),
    _b(
        "rig_json_import",
        "rig.json_import",
        ("rig_prototypes_created_from_json",),
        arguments={"path": "rig .json", "set_t_pose": "bool"},
        gap=True,
    ),
    # -- render ------------------------------------------------------------------
    _b(
        "point_light_properties",
        "render.point_light_properties",
        ("behaviour_values_equal_request",),
        arguments=VALUES,
        gap=True,
    ),
    _b(
        "spot_light_properties",
        "render.spot_light_properties",
        ("behaviour_values_equal_request",),
        arguments=VALUES,
        gap=True,
    ),
    _b("camera_settings", "render.camera_settings", ("behaviour_values_equal_request",), arguments=VALUES, gap=True),
    _b("material", "render.mesh_material", ("behaviour_values_equal_request",), arguments=VALUES),
    _b(
        "viewport_layout",
        "render.viewport_layout",
        ("viewport_count_equals_request",),
        arguments={"count": "1|2|4"},
        gap=True,
    ),
    _b("viewport", "render.viewport_layout", ("viewport_count_equals_request",), arguments={"count": "1|2|4"}),
    # -- scene maintenance ---------------------------------------------------------
    _b("fix_scene", "scene.fix", ("scene_valid_after_fix",), gap=True),
)

BY_FEATURE = MappingProxyType({item.feature_id: item for item in BINDINGS})
BY_OPERATION: MappingProxyType = MappingProxyType(
    {
        operation: tuple(item for item in BINDINGS if item.operation == operation)
        for operation in {b.operation for b in BINDINGS}
    }
)
