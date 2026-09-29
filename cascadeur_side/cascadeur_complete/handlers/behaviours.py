"""Feature-bound behaviour property adapters.

Each operation is bound to one Cascadeur behaviour and an explicit property
whitelist taken from the 2026.1.2 behaviour schema. Values are written through
the data editor and read back; the operation fails unless every requested value
is observed afterwards. Generic behaviour access is intentionally not exposed.
"""

from __future__ import annotations

from ..handler_registry import handler

# operation -> (behaviour, allowed data properties, may add the behaviour)
BEHAVIOUR_FEATURES = {
    "physics.autophysics_smooth_trajectory": ("AutoPhysics", ("vertical_jerk", "horizontal_jerk"), False),
    "physics.autophysics_smooth_rotation": ("AutoPhysics", ("rotation_blending",), False),
    "physics.autophysics_priority_frames": ("AutoPhysics", ("priority_frame", "frame_weight"), False),
    "physics.autophysics_point_settings": (
        "AutoPhysicsApply",
        ("keep_global_rotation", "keep_global_translation"),
        False,
    ),
    "physics.compensation_motion": ("CompensationMotion", ("muscle_stiffness",), True),
    "physics.separation_motion": ("SeparationMotion", ("muscle_stiffness",), True),
    "physics.secondary_motion": (
        "SecondaryMotion",
        ("local_blending", "global_blending", "damping", "air_friction"),
        True,
    ),
    "physics.ragdoll": (
        "Ragdoll",
        (
            "local_stiffness",
            "global_stiffness",
            "local_damping",
            "global_damping",
            "muscle_friction",
            "air_friction",
            "global_pin",
        ),
        True,
    ),
    "physics.fulcrum_point": ("FulcrumPoint", ("fulcrum_state", "collision_radius", "max_speed"), True),
    "physics.collision_material": ("CollisionMaterial", ("collision_type", "friction", "bounciness"), False),
    "render.point_light_properties": ("PointLight", ("color", "intensity", "falloff_radius"), False),
    "render.spot_light_properties": ("SpotLight", None, False),
    "render.camera_settings": (
        "Camera",
        (
            "field_of_view",
            "focal_length",
            "sensor_width",
            "near_clipping",
            "far_clipping",
            "aspect_ratio_width",
            "aspect_ratio_height",
            "horizontal_aov",
        ),
        False,
    ),
    "render.mesh_material": (
        "MeshObject",
        ("color", "use_color", "is_transparent", "is_both_side", "always_show_textures", "render_layer"),
        False,
    ),
    # Filament material (Material behaviour); texture slots take image file paths.
    "render.material": ("Material", None, False),
    "render.material_textures": (
        "Material",
        (
            "base_color_map",
            "normal_map",
            "emissive_color_map",
            "roughness_map",
            "metallic_map",
            "reflectance_map",
            "ambient_occlusion_map",
        ),
        False,
    ),
    "objects.visibility": ("Basic", ("visibility",), False),
}
# Structural data that would corrupt a rig or camera if written directly.
DENIED_PROPERTIES = frozenset({"global_matrix", "projection_matrix", "bindShapeMatrix", "parent"})
MARKER_FEATURES = {
    "physics.autophysics_corrector": "PhysicsCorrector",
    "physics.penetration_cleaning": "CollisionPenetrationCleaning",
}


def _plain(value):
    converter = getattr(value, "tolist", None)
    if callable(converter):
        value = converter()
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return float(value) if isinstance(value, float) else value
    name = getattr(value, "name", None)
    if isinstance(name, str):
        return name
    return value


def _equal(observed, expected):
    observed = _plain(observed)
    if isinstance(expected, (list, tuple)):
        if not isinstance(observed, list) or len(observed) != len(expected):
            return False
        return all(_equal(left, right) for left, right in zip(observed, expected, strict=True))
    if isinstance(expected, bool) or isinstance(observed, bool):
        return bool(observed) == bool(expected)
    if isinstance(expected, (int, float)) and isinstance(observed, (int, float)):
        return abs(float(observed) - float(expected)) <= 1e-4 * max(1.0, abs(float(expected)))
    return observed == expected


def _coerce(value):
    if isinstance(value, list):
        return tuple(float(item) for item in value)
    return value


def _is_static(data_viewer, data_id, csc):
    with_mode = data_viewer.get_data(data_id)
    return str(getattr(with_mode.mode, "name", with_mode.mode)) == str(csc.model.DataMode.Static.name)


def _read(data_viewer, data_id, frame, csc):
    if _is_static(data_viewer, data_id, csc):
        return data_viewer.get_data_value(data_id)
    return data_viewer.get_data_value(data_id, frame)


def _targets(domain, arguments, behaviour, context):
    ids = [str(item) for item in arguments.get("ids", [])]
    viewer = domain.model_viewer().behaviour_viewer()
    if not ids:
        ids = sorted(
            {context["id_string"](viewer.get_behaviour_owner(item)) for item in viewer.get_behaviours(behaviour)}
        )
        if not ids:
            raise ValueError("No object in the scene owns " + behaviour + "; pass explicit ids")
    existing = {context["id_string"](item) for item in domain.model_viewer().get_objects()}
    unknown = sorted(set(ids) - existing)
    if unknown:
        raise KeyError("Unknown object IDs: " + ", ".join(unknown))
    return ids


def _allowed(viewer, behaviour_id, behaviour, declared, context):
    names = set()
    for name in viewer.get_behaviour_property_names(behaviour_id):
        kind = str(context["read_member"](viewer.get_property_type(behaviour_id, name), "name"))
        if kind == "DataType" and name not in DENIED_PROPERTIES:
            names.add(str(name))
    return names if declared is None else names & set(declared)


@handler(*BEHAVIOUR_FEATURES, postconditions=("behaviour_values_equal_request",))
def configure_behaviour(scene, arguments, request, context):
    operation = str((request.get("operations") or [{}])[0].get("name", ""))
    behaviour, declared, may_add = BEHAVIOUR_FEATURES[operation]
    values = dict(arguments.get("values") or {})
    if not values:
        raise ValueError("values must name at least one property")
    csc = context["csc"]
    domain = context["domain_scene"](scene)
    frame = int(arguments.get("frame", domain.get_current_frame(False)))
    ids = _targets(domain, arguments, behaviour, context)
    add_missing = bool(arguments.get("add_missing", False))
    if add_missing and not may_add:
        raise ValueError(behaviour + " cannot be added by this feature")
    model_viewer = domain.model_viewer()
    viewer = model_viewer.behaviour_viewer()
    data_viewer = model_viewer.data_viewer()

    missing_owner = [
        item for item in ids if viewer.get_behaviour_by_name(context["object_id"](item), behaviour).is_null()
    ]
    if missing_owner and not add_missing:
        raise ValueError(behaviour + " is missing on: " + ", ".join(missing_owner))

    def edit(model, update, _scene_updater):
        behaviour_editor = model.behaviour_editor()
        data_editor = model.data_editor()
        for raw_id in ids:
            object_id = context["object_id"](raw_id)
            behaviour_id = viewer.get_behaviour_by_name(object_id, behaviour)
            if behaviour_id.is_null():
                behaviour_id = behaviour_editor.add_behaviour(object_id, behaviour)
            allowed = _allowed(viewer, behaviour_id, behaviour, declared, context)
            unknown = sorted(set(values) - allowed)
            if unknown:
                raise ValueError(behaviour + " does not allow: " + ", ".join(unknown))
            group = update.get_object_by_id(object_id).root_group()
            for name, value in values.items():
                data_id = viewer.get_behaviour_data(behaviour_id, name)
                coerced = _coerce(value)
                if data_id.is_null():
                    default = viewer.get_behaviour_default_data_value(behaviour_id, name)
                    created = group.create_regular_data(name, default, csc.model.DataMode.Static).data_id()
                    behaviour_editor.set_behaviour_data(behaviour_id, name, created)
                    data_id = created
                if _is_static(data_viewer, data_id, csc):
                    data_editor.set_data_value(data_id, coerced)
                else:
                    data_editor.set_data_value(data_id, frame, coerced)

    errors = []

    def guarded(model, update, scene_updater):
        try:
            edit(model, update, scene_updater)
        except Exception as exc:  # surfaced after the edit transaction closes
            errors.append(exc)

    domain.modify("Cascadeur Complete: " + operation, guarded)
    if errors:
        raise errors[0]
    viewer = domain.model_viewer().behaviour_viewer()
    observed = {}
    for raw_id in ids:
        behaviour_id = viewer.get_behaviour_by_name(context["object_id"](raw_id), behaviour)
        if behaviour_id.is_null():
            raise AssertionError("POSTCONDITION_FAILED: " + behaviour + " missing after edit on " + raw_id)
        row = {}
        for name, expected in values.items():
            data_id = viewer.get_behaviour_data(behaviour_id, name)
            if data_id.is_null():
                raise AssertionError("POSTCONDITION_FAILED: " + name + " has no data on " + raw_id)
            value = _read(data_viewer, data_id, frame, csc)
            if not _equal(value, expected):
                raise AssertionError("POSTCONDITION_FAILED: " + behaviour + "." + name + " differs on " + raw_id)
            row[name] = _plain(value)
        observed[raw_id] = row
    return {"behaviour": behaviour, "frame": frame, "ids": ids, "values": observed, "added_to": missing_owner}, []


@handler(*MARKER_FEATURES, postconditions=("behaviour_presence_equals_request",))
def marker_behaviour(scene, arguments, request, context):
    operation = str((request.get("operations") or [{}])[0].get("name", ""))
    behaviour = MARKER_FEATURES[operation]
    enabled = bool(arguments.get("enabled", True))
    ids = [str(item) for item in arguments.get("ids", [])]
    if not ids:
        raise ValueError("ids must contain at least one object")
    domain = context["domain_scene"](scene)
    existing = {context["id_string"](item) for item in domain.model_viewer().get_objects()}
    unknown = sorted(set(ids) - existing)
    if unknown:
        raise KeyError("Unknown object IDs: " + ", ".join(unknown))
    viewer = domain.model_viewer().behaviour_viewer()

    def edit(model, _update, _scene_updater):
        editor = model.behaviour_editor()
        for raw_id in ids:
            object_id = context["object_id"](raw_id)
            current = viewer.get_behaviour_by_name(object_id, behaviour)
            if enabled and current.is_null():
                editor.add_behaviour(object_id, behaviour)
            elif not enabled and not current.is_null():
                editor.delete_behaviour(current)

    domain.modify("Cascadeur Complete: " + operation, edit)
    viewer = domain.model_viewer().behaviour_viewer()
    observed = {
        raw_id: not viewer.get_behaviour_by_name(context["object_id"](raw_id), behaviour).is_null() for raw_id in ids
    }
    if any(value != enabled for value in observed.values()):
        raise AssertionError("POSTCONDITION_FAILED: " + behaviour + " presence differs from request")
    return {"behaviour": behaviour, "enabled": enabled, "observed": observed}, []


@handler("physics.autophysics_restore", postconditions=("autophysics_values_restored",))
def autophysics_restore(scene, arguments, _request, context):
    """Restore unbound AutoPhysics values with Cascadeur's bundled restore command."""
    from commands.restore_values import restore_auto_physics_values

    csc = context["csc"]
    domain = context["domain_scene"](scene)
    viewer = domain.model_viewer().behaviour_viewer()
    center = context["object_id"](arguments["center_of_mass_id"])
    auto_physics = viewer.get_behaviour_by_name(center, "AutoPhysics")
    if auto_physics.is_null():
        raise ValueError("center_of_mass_id does not own AutoPhysics")
    points = [context["object_id"](item) for item in arguments.get("point_ids", [])]
    if not points:
        raise ValueError("point_ids must list the AutoPhysics points to restore")
    restore_auto_physics_values(domain, center, set(points))
    data = domain.model_viewer().data_viewer()
    viewer = domain.model_viewer().behaviour_viewer()
    blending = _read(data, viewer.get_behaviour_data(auto_physics, "rotation_blending"), 0, csc)
    if not _equal(blending, 100.0):
        raise AssertionError("POSTCONDITION_FAILED: AutoPhysics rotation blending was not restored")
    restored = {}
    for name in ("CompensationMotion", "SecondaryMotion"):
        rows = set()
        for point in points:
            behaviour_id = viewer.get_behaviour_by_name(point, name)
            if behaviour_id.is_null():
                continue
            rows.add(
                tuple(
                    repr(_plain(_read(data, viewer.get_behaviour_data(behaviour_id, prop), 0, csc)))
                    for prop in sorted(viewer.get_behaviour_property_names(behaviour_id))
                    if not viewer.get_behaviour_data(behaviour_id, prop).is_null()
                )
            )
        if len(rows) > 1:
            raise AssertionError("POSTCONDITION_FAILED: " + name + " values differ between restored points")
        restored[name] = len(rows)
    return {"rotation_blending": _plain(blending), "restored_behaviours": restored}, []
