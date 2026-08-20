from __future__ import annotations

from ..handler_registry import handler

PHYSICS_BEHAVIOURS = (
    "PhysicsSettings",
    "RigidBody",
    "CenterOfMass",
    "AutoPhysics",
    "AutoPhysicsApply",
    "BallisticTrajectory",
    "Fulcrum",
    "Constraint",
    "TransformConstraint",
    "ConnectionPointTwoBody",
    "BoxCollision",
    "CapsuleCollision",
    "KinematicMeshCollision",
    "ConvexMeshCollision",
    "CollisionMaterial",
)


def _behaviour_ids(behaviours, behaviour_name):
    try:
        return list(behaviours.get_behaviours(behaviour_name)), True
    except RuntimeError:
        return [], False


def _behaviour_owners(behaviours, behaviour_ids, context):
    return sorted({context["id_string"](behaviours.get_behaviour_owner(item)) for item in behaviour_ids})


def _data_value(data_viewer, data_id):
    try:
        return data_viewer.get_data_value(data_id)
    except (RuntimeError, TypeError):
        return data_viewer.get_data_value(data_id, 0)


def _physics_state(scene, context):
    domain = context["domain_scene"](scene)
    model_viewer = domain.model_viewer()
    behaviours = model_viewer.behaviour_viewer()
    data_viewer = model_viewer.data_viewer()
    inventory = {}
    masses = []
    for behaviour_name in PHYSICS_BEHAVIOURS:
        ids, registered = _behaviour_ids(behaviours, behaviour_name)
        inventory[behaviour_name] = {
            "count": len(ids),
            "owner_ids": _behaviour_owners(behaviours, ids, context),
            "registered": registered,
        }
    seen_mass_owners = set()
    for behaviour_name in ("PhysicsSettings", "RigidBody"):
        behaviour_ids, _registered = _behaviour_ids(behaviours, behaviour_name)
        for behaviour_id in behaviour_ids:
            owner = behaviours.get_behaviour_owner(behaviour_id)
            owner_text = context["id_string"](owner)
            if owner_text in seen_mass_owners:
                continue
            mass_id = behaviours.get_behaviour_data(behaviour_id, "mass")
            if mass_id.is_null():
                continue
            value = float(_data_value(data_viewer, mass_id))
            masses.append(
                {
                    "owner_id": owner_text,
                    "data_id": context["id_string"](mass_id),
                    "mass": value,
                    "source_behaviour": behaviour_name,
                }
            )
            seen_mass_owners.add(owner_text)
    selected = list(context["scene_state"](context["scene_view"]() or scene)["selection"])
    return {
        "behaviours": inventory,
        "rigid_body_masses": masses,
        "rigid_body_count": len(masses),
        "total_mass": sum(item["mass"] for item in masses),
        "selected_ids": selected,
        "selected_rigid_body_ids": sorted(
            set(selected) & (set(inventory["PhysicsSettings"]["owner_ids"]) | set(inventory["RigidBody"]["owner_ids"]))
        ),
        "center_of_mass_ids": sorted(
            set(inventory["CenterOfMass"]["owner_ids"]) | set(inventory["AutoPhysics"]["owner_ids"])
        ),
    }


def _select_objects(domain, object_ids, context, label):
    if not object_ids:
        raise ValueError(label + " requires at least one object ID")
    converted = [context["object_id"](item) for item in object_ids]

    def select(_model, _update, _scene, session):
        session.take_selector().select(set(converted), converted[0])

    domain.modify_with_session("Cascadeur Complete: select " + label, select)
    return converted


@handler("physics.state")
def physics_state(scene, _arguments, _request, context):
    return _physics_state(scene, context), []


@handler("rig.mass_set", "physics.mass_set")
def physics_mass_set(scene, arguments, _request, context):
    requested_total = float(arguments["total_mass"])
    if requested_total <= 0:
        raise ValueError("total_mass must be positive")
    domain = context["domain_scene"](scene)
    model_viewer = domain.model_viewer()
    behaviours = model_viewer.behaviour_viewer()
    data_viewer = model_viewer.data_viewer()
    requested_ids = {str(item) for item in arguments.get("ids", [])}
    selected = set(_physics_state(scene, context)["selected_ids"])
    target_ids = requested_ids or selected
    rows = []
    seen_mass_owners = set()
    for behaviour_name in ("PhysicsSettings", "RigidBody"):
        behaviour_ids, _registered = _behaviour_ids(behaviours, behaviour_name)
        for behaviour_id in behaviour_ids:
            owner = behaviours.get_behaviour_owner(behaviour_id)
            owner_text = context["id_string"](owner)
            if owner_text in seen_mass_owners or (target_ids and owner_text not in target_ids):
                continue
            mass_id = behaviours.get_behaviour_data(behaviour_id, "mass")
            if mass_id.is_null():
                continue
            rows.append((owner_text, mass_id, float(_data_value(data_viewer, mass_id))))
            seen_mass_owners.add(owner_text)
    if not rows:
        raise ValueError("No rigid bodies with PhysicsSettings mass were found in the requested scope")
    before_total = sum(item[2] for item in rows)
    if before_total <= 0:
        raise ValueError("Current total rigid body mass must be positive")
    coefficient = requested_total / before_total

    def set_mass(model, _update, _scene):
        editor = model.data_editor()
        for _owner, data_id, value in rows:
            editor.set_data_value(data_id, value * coefficient)

    domain.modify("Cascadeur Complete: set total rigid body mass", set_mass)
    observed = []
    for owner, data_id, _value in rows:
        observed.append({"owner_id": owner, "mass": float(_data_value(data_viewer, data_id))})
    observed_total = sum(item["mass"] for item in observed)
    tolerance = max(1e-5, abs(requested_total) * 1e-6)
    if abs(observed_total - requested_total) > tolerance:
        raise AssertionError("POSTCONDITION_FAILED: total rigid body mass differs from requested value")
    return {
        "before_total_mass": before_total,
        "requested_total_mass": requested_total,
        "observed_total_mass": observed_total,
        "coefficient": coefficient,
        "rigid_bodies": observed,
    }, []


@handler("physics.ballistic")
def ballistic(scene, arguments, _request, context):
    view_scene = context["scene_view"]()
    if view_scene is None:
        raise RuntimeError("No application scene is available")
    state = _physics_state(scene, context)
    if not state["center_of_mass_ids"]:
        raise ValueError("Ballistic trajectory requires a Center of Mass")
    domain = context["domain_scene"](scene)
    center_id = str(arguments.get("center_of_mass_id") or state["center_of_mass_ids"][0])
    if center_id not in state["center_of_mass_ids"]:
        raise ValueError("center_of_mass_id is not a Center of Mass in the current scene")

    viewer = domain.layers_viewer()
    first = int(arguments["first_frame"])
    last = int(arguments["last_frame"])
    if first < 0 or last < first or last >= int(viewer.frames_count()):
        raise ValueError(f"Invalid ballistic interval: {first}..{last}")
    requested_layers = [str(item) for item in arguments.get("layer_ids", [])]
    layer_ids = (
        [context["guid"](item) for item in requested_layers]
        if requested_layers
        else list(viewer.all_layer_ids())
    )
    if not layer_ids:
        raise ValueError("Ballistic trajectory requires at least one animation layer")

    converted_center = context["object_id"](center_id)

    def select_inputs(_model, _update, _scene, session):
        session.take_selector().select({converted_center}, converted_center)
        session.take_layers_selector().set_full_selection_by_parts(layer_ids, first, last)

    domain.modify_with_session("Cascadeur Complete: select ballistic inputs", select_inputs)
    before = context["casc_tool_state"](view_scene)
    action_id = "BallisticTrajectoryTool.Add ballistic trajectory"
    result = context["csc"].app.get_application().get_action_manager().call_action(action_id)
    saved_path = context["save_current_scene"](view_scene)
    after = context["casc_tool_state"](view_scene)
    if after["ballistic_count"] != before["ballistic_count"] + 1:
        raise AssertionError("POSTCONDITION_FAILED: persisted ballistic trajectory count did not increase")
    return {
        "action_id": action_id,
        "return_value": context["json_safe"](result),
        "center_of_mass_id": center_id,
        "first_frame": first,
        "last_frame": last,
        "layer_ids": sorted(context["id_string"](item) for item in layer_ids),
        "before_ballistic_count": before["ballistic_count"],
        "after_ballistic_count": after["ballistic_count"],
        "saved_path": saved_path,
        "tool_state_fingerprint": after["fingerprint"],
    }, []


@handler("physics.center_of_mass")
def center_of_mass(scene, arguments, _request, context):
    from commands.center_of_mass import (
        connect_with_controllers,
        create_by_rigids,
        create_composite,
        snap_mesh_to_cm,
    )

    mode = str(arguments.get("mode", "from_rigids"))
    commands = {
        "from_rigids": create_by_rigids,
        "composite": create_composite,
        "connect_direction_controllers": connect_with_controllers,
        "snap_mesh": snap_mesh_to_cm,
    }
    if mode not in commands:
        raise ValueError("Unknown Center of Mass mode: " + mode)
    domain = context["domain_scene"](scene)
    ids = [str(item) for item in arguments.get("ids", [])]
    if ids:
        _select_objects(domain, ids, context, "Center of Mass targets")
    before = _physics_state(scene, context)
    before_revision = context["scene_state"](context["scene_view"]() or scene)["revision"]
    commands[mode].run(domain)
    after = _physics_state(scene, context)
    after_revision = context["scene_state"](context["scene_view"]() or scene)["revision"]
    if mode in ("from_rigids", "composite"):
        if len(after["center_of_mass_ids"]) <= len(before["center_of_mass_ids"]):
            raise AssertionError("POSTCONDITION_FAILED: Center of Mass count did not increase")
    elif before_revision == after_revision:
        raise AssertionError("POSTCONDITION_FAILED: Center of Mass operation made no scene change")
    return {
        "mode": mode,
        "execution": "commands.center_of_mass." + commands[mode].__name__.rsplit(".", 1)[-1] + ".run",
        "before_center_of_mass_ids": before["center_of_mass_ids"],
        "after_center_of_mass_ids": after["center_of_mass_ids"],
        "before_revision": before_revision,
        "after_revision": after_revision,
    }, []


@handler("physics.collision_create")
def collision_create(scene, arguments, _request, context):
    shape = str(arguments.get("shape", "box"))
    behaviour_by_shape = {
        "box": "BoxCollision",
        "capsule": "CapsuleCollision",
        "kinematic_mesh": "KinematicMeshCollision",
        "convex_decomposition": "ConvexMeshCollision",
        "convex_by_skinning": "ConvexMeshCollision",
    }
    if shape not in behaviour_by_shape:
        raise ValueError("Unknown collision shape: " + shape)
    domain = context["domain_scene"](scene)
    ids = [str(item) for item in arguments.get("ids", [])]
    if not ids:
        ids = list(_physics_state(scene, context)["selected_ids"])
    converted = _select_objects(domain, ids, context, "collision targets")
    behaviour_name = behaviour_by_shape[shape]
    behaviours = domain.model_viewer().behaviour_viewer()
    before_count = len(list(behaviours.get_behaviours(behaviour_name)))
    result = None
    if shape in ("box", "capsule", "kinematic_mesh"):
        from commands.collision import add_box, add_capsule, add_kinematic_mesh_collision

        commands = {
            "box": add_box,
            "capsule": add_capsule,
            "kinematic_mesh": add_kinematic_mesh_collision,
        }
        commands[shape].run(domain)
        execution = "commands.collision." + commands[shape].__name__.rsplit(".", 1)[-1] + ".run"
    elif shape == "convex_decomposition":
        from commands.collision import generate_convex_mesh

        values = [
            int(arguments.get("max_hulls", 3)),
            int(arguments.get("resolution", 4000000)),
            float(arguments.get("volume_error_percent", 5.0)),
            int(arguments.get("max_recursion_depth", 10)),
            int(arguments.get("fill_mode", 0)),
        ]
        domain.modify(
            "Cascadeur Complete: generate convex collision",
            generate_convex_mesh.get_mod(converted, values),
        )
        execution = "commands.collision.generate_convex_mesh.get_mod"
    else:
        from commands.collision import generate_by_skinning

        values = [
            float(arguments.get("weight_threshold", 0.5)),
            float(arguments.get("hull_tolerance", 1.0)),
        ]
        domain.modify(
            "Cascadeur Complete: generate collision by skinning",
            generate_by_skinning.get_mod(converted, values),
        )
        execution = "commands.collision.generate_by_skinning.get_mod"
    after_count = len(list(behaviours.get_behaviours(behaviour_name)))
    if after_count <= before_count:
        raise AssertionError("POSTCONDITION_FAILED: collision behaviour count did not increase")
    return {
        "shape": shape,
        "target_ids": ids,
        "behaviour": behaviour_name,
        "before_count": before_count,
        "after_count": after_count,
        "execution": execution,
        "return_value": context["json_safe"](result),
    }, []


@handler("physics.collision_delete")
def collision_delete(scene, arguments, _request, context):
    from commands.collision import delete_selected

    ids = [str(item) for item in arguments.get("ids", [])]
    domain = context["domain_scene"](scene)
    converted = _select_objects(domain, ids, context, "collision deletion targets")
    collision_behaviours = (
        "BoxCollision",
        "CapsuleCollision",
        "ConvexMeshCollision",
        "KinematicMeshCollision",
        "CollisionMaterial",
    )
    behaviours = domain.model_viewer().behaviour_viewer()
    before = {}
    for object_id in converted:
        object_text = context["id_string"](object_id)
        before[object_text] = {
            name: not behaviours.get_behaviour_by_name(object_id, name).is_null()
            for name in collision_behaviours
        }
    if not any(any(row.values()) for row in before.values()):
        raise ValueError("No requested object owns a collision behaviour")
    delete_selected.run(domain)
    behaviours = domain.model_viewer().behaviour_viewer()
    remaining = {}
    for object_id in converted:
        names = [
            name
            for name in collision_behaviours
            if not behaviours.get_behaviour_by_name(object_id, name).is_null()
        ]
        if names:
            remaining[context["id_string"](object_id)] = names
    if remaining:
        raise AssertionError("POSTCONDITION_FAILED: collision behaviours remain: " + str(remaining))
    removed = {
        object_id: sorted(name for name, present in row.items() if present)
        for object_id, row in before.items()
    }
    return {
        "target_ids": ids,
        "removed_behaviours": removed,
        "removed_count": sum(len(items) for items in removed.values()),
        "execution": "commands.collision.delete_selected.run",
    }, []


@handler("physics.constraint_transform")
def constraint_transform(scene, arguments, _request, context):
    from common.constraints.transform_constraints import constrain_ortho_transform

    driver_id = context["object_id"](arguments["driver_id"])
    constrained_id = context["object_id"](arguments["constrained_id"])
    if driver_id == constrained_id:
        raise ValueError("driver_id and constrained_id must differ")
    domain = context["domain_scene"](scene)
    behaviours = domain.model_viewer().behaviour_viewer()
    before_count = len(_behaviour_ids(behaviours, "TransformConstraint")[0])
    created = []

    def add_constraint(model, update, _scene, session):
        driver = update.get_object_by_id(driver_id)
        constrained = update.get_object_by_id(constrained_id)
        if not constrained.has_input("Position"):
            raise ValueError("The constrained object does not support transform constraints")
        result = constrain_ortho_transform(domain, model, update, driver, constrained)
        created.append(context["id_string"](result.object_id()))
        session.take_selector().select({result.object_id()}, result.object_id())

    domain.modify_with_session("Cascadeur Complete: transform constraint", add_constraint)
    after_count = len(_behaviour_ids(behaviours, "TransformConstraint")[0])
    if after_count <= before_count and not created:
        raise AssertionError("POSTCONDITION_FAILED: transform constraint was not created")
    return {
        "driver_id": str(arguments["driver_id"]),
        "constrained_id": str(arguments["constrained_id"]),
        "created_ids": created,
        "before_count": before_count,
        "after_count": after_count,
    }, []


@handler("physics.constraint_point")
def constraint_point(scene, arguments, _request, context):
    from commands.constrain.add_constraint import (
        constrain_single_point,
        prepare_selected_points,
    )

    driver_id = str(arguments["driver_id"])
    point_ids = [str(item) for item in arguments.get("point_ids", [])]
    if not point_ids:
        raise ValueError("point_ids must contain at least one point controller")
    domain = context["domain_scene"](scene)
    behaviours = domain.model_viewer().behaviour_viewer()
    converted_points = [context["object_id"](item) for item in point_ids]
    for point_id in converted_points:
        if behaviours.get_behaviour_by_name(point_id, "Point").is_null():
            raise ValueError("Point constraint target lacks Point behaviour: " + context["id_string"](point_id))
    before_count = len(list(behaviours.get_behaviours("Constraint")))
    requested_driver = context["object_id"](driver_id)
    created = []
    resolved_driver_ids = []
    failures = []

    def resolve_triangle(update, point_id):
        point = update.get_object_by_id(point_id).root_group()
        if point.has_output("Position"):
            for attribute in point.output("Position").connected_attributes():
                node = attribute.node()
                point_inputs = ("Main Position", "Direction Position", "Additional Position")
                if attribute.name() in point_inputs and node.has_input("Main Position"):
                    return node.parent_object().id()
        if point.has_input("Base Position"):
            connected = point.input("Base Position").connected_attributes()
            if connected:
                return connected[0].node().parent_object().id()
        return None

    def add_constraints(model, update, current_scene):
        try:
            resolved_driver = requested_driver
            driver_object = update.get_object_by_id(resolved_driver)
            if not driver_object.has_input("Main Position"):
                resolved_driver = resolve_triangle(update, requested_driver)
                if resolved_driver is None:
                    raise ValueError("driver_id must be a constraint Triangle or a Point connected to one")
                driver_object = update.get_object_by_id(resolved_driver)
            resolved_driver_ids.append(context["id_string"](resolved_driver))
            prepared_points = prepare_selected_points(model, update, current_scene, list(converted_points))
            if not prepared_points:
                raise ValueError("No requested Point is eligible for a constraint in the current rig topology")
            for point_id in prepared_points:
                own_triangle = resolve_triangle(update, point_id)
                if own_triangle is not None and own_triangle == resolved_driver:
                    raise ValueError("A Point cannot be constrained to its own Triangle")
                constrain_single_point(
                    model,
                    update,
                    current_scene,
                    driver_object,
                    point_id,
                    bool(arguments.get("spherical_position", False)),
                )
                created.append(context["id_string"](point_id))
        except Exception as exc:
            failures.append(str(exc))

    domain.modify("Cascadeur Complete: point constraints", add_constraints)
    if failures:
        raise RuntimeError("Point constraint failed: " + " | ".join(failures))
    after_count = len(list(behaviours.get_behaviours("Constraint")))
    if after_count <= before_count or not created:
        raise AssertionError("POSTCONDITION_FAILED: point constraint count did not increase")
    return {
        "driver_id": driver_id,
        "resolved_driver_ids": resolved_driver_ids,
        "point_ids": point_ids,
        "created_point_ids": created,
        "spherical_position": bool(arguments.get("spherical_position", False)),
        "before_count": before_count,
        "after_count": after_count,
    }, []


def _auto_physics_state(scene, context):
    domain = context["domain_scene"](scene)
    viewer = domain.model_viewer()
    behaviours = viewer.behaviour_viewer()
    center_ids = []
    for behaviour_id in behaviours.get_behaviours("AutoPhysics"):
        owner = behaviours.get_behaviour_owner(behaviour_id)
        center_ids.append(context["id_string"](owner))
    center_ids = sorted(set(center_ids))
    apply_count = len(list(behaviours.get_behaviours("AutoPhysicsApply")))
    selected = list(context["scene_state"](context["scene_view"]() or scene)["selection"])
    frames_count = int(domain.layers_viewer().frames_count())
    selected_centers = sorted(set(selected) & set(center_ids))
    main_center = selected_centers[0] if selected_centers else (center_ids[0] if len(center_ids) == 1 else None)
    missing = []
    if not center_ids:
        missing.append("center_of_mass")
    if frames_count < 3:
        missing.append("animation_at_least_three_frames")
    if len(center_ids) > 1 and not selected_centers:
        missing.append("select_main_center_of_mass")
    return {
        "center_of_mass_ids": center_ids,
        "center_of_mass_count": len(center_ids),
        "auto_physics_apply_count": apply_count,
        "frames_count": frames_count,
        "selected_ids": selected,
        "selected_center_of_mass_ids": selected_centers,
        "main_center_of_mass_id": main_center,
        "ready_to_enable": not missing,
        "missing_preconditions": missing,
        "working_state_observable": False,
        "next_action": (
            "Enable Physics Assistant and allow recalculation before snapping"
            if not missing
            else "Resolve missing_preconditions before enabling AutoPhysics"
        ),
    }


@handler("physics.auto_state")
def auto_physics_state(scene, _arguments, _request, context):
    return _auto_physics_state(scene, context), []


@handler("physics.auto_enable")
def auto_physics_enable(scene, _arguments, _request, context):
    state = _auto_physics_state(scene, context)
    if not state["ready_to_enable"]:
        raise ValueError("AutoPhysics prerequisites are missing: " + ", ".join(state["missing_preconditions"]))
    main_center = state["main_center_of_mass_id"]
    if main_center and main_center not in state["selected_ids"]:
        domain = context["domain_scene"](scene)
        object_id = context["object_id"](main_center)

        def select_center(_model, _update, _scene, session):
            session.take_selector().select({object_id}, object_id)

        domain.modify_with_session("Cascadeur Complete: select AutoPhysics center of mass", select_center)
    action_id = "AutoPhysicsTool.Switch Auto Physics"
    result = context["csc"].app.get_application().get_action_manager().call_action(action_id)
    after = _auto_physics_state(context["scene_view"]() or scene, context)
    return {
        "action_id": action_id,
        "return_value": context["json_safe"](result),
        "state": after,
        "recalculation_required": True,
    }, ["Cascadeur does not expose the internal working AutoPhysics flag; wait for the assistant to recalculate"]


@handler("physics.auto_snap")
def auto_physics_snap(scene, _arguments, _request, context):
    prerequisite = _auto_physics_state(scene, context)
    if not prerequisite["ready_to_enable"]:
        raise ValueError("AutoPhysics prerequisites are missing: " + ", ".join(prerequisite["missing_preconditions"]))
    if not prerequisite["selected_center_of_mass_ids"]:
        raise ValueError("AutoPhysics snap requires the main Center of Mass selected; call auto_physics_enable first")
    before = context["scene_state"](context["scene_view"]() or scene)
    result = (
        context["csc"].app.get_application().get_action_manager().call_action("AutoPhysicsTool.Snap to Auto Physics")
    )
    after = context["scene_state"](context["scene_view"]() or scene)
    completed_synchronously = before["revision"] != after["revision"]
    return {
        "action_id": "AutoPhysicsTool.Snap to Auto Physics",
        "return_value": context["json_safe"](result),
        "prerequisite": prerequisite,
        "before_revision": before["revision"],
        "after_revision": after["revision"],
        "completed_synchronously": completed_synchronously,
        "confirmation_may_be_pending": not completed_synchronously,
    }, (
        []
        if completed_synchronously
        else ["Cascadeur may be waiting for the known AutoPhysics single-use-feature confirmation"]
    )
