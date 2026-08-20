from __future__ import annotations

from contextlib import suppress

from ..handler_registry import handler

RIG_BEHAVIOURS = (
    "RigInfo",
    "RigAdditionalInfo",
    "Joint",
    "RigidBody",
    "RigidBodyView",
    "PhysicsSettings",
    "Point",
    "Ortho",
    "BoxView",
    "ProtoBox",
    "TechnicalLinks",
    "LimbDirection",
    "ConnectionPointTwoBody",
    "AttractionPoint",
    "ChainIK",
    "SplineIk",
    "ProtoSplineIk",
    "Twist",
    "Untwist",
    "BlendShape",
)


def _behaviour_ids(viewer, name):
    try:
        return list(viewer.get_behaviours(name)), True
    except RuntimeError:
        return [], False


def _owners(viewer, ids, context):
    return sorted({context["id_string"](viewer.get_behaviour_owner(item)) for item in ids})


def _behaviour_owner_set(viewer, behaviour_name, context):
    ids, _registered = _behaviour_ids(viewer, behaviour_name)
    return {context["id_string"](viewer.get_behaviour_owner(item)) for item in ids}


def _require_existing_objects(domain, object_ids, context, label):
    existing = {context["id_string"](item) for item in domain.model_viewer().get_objects()}
    missing = [str(item) for item in object_ids if str(item) not in existing]
    if missing:
        raise ValueError(label + " contains unknown object IDs: " + ", ".join(missing))
    return [context["object_id"](item) for item in object_ids]


def _select_exact(domain, object_ids):
    if not object_ids:
        raise ValueError("At least one object must be selected")

    def select(_model, _update, _scene, session):
        session.take_selector().select(set(object_ids), object_ids[0])

    domain.modify_with_session("Cascadeur Complete: select rig objects", select)


def _reference_owner_ids(viewer, behaviour_id, property_name, context):
    owners = []
    for reference in viewer.get_behaviour_reference_range(behaviour_id, property_name):
        if not reference.is_null():
            owners.append(context["id_string"](viewer.get_behaviour_owner(reference)))
    return sorted(set(owners))


def _reference_owner(viewer, behaviour_id, property_name, context):
    reference = viewer.get_behaviour_reference(behaviour_id, property_name)
    if reference.is_null():
        return None
    return context["id_string"](viewer.get_behaviour_owner(reference))


@handler("rig.state")
def rig_state(scene, _arguments, _request, context):
    domain = context["domain_scene"](scene)
    model_viewer = domain.model_viewer()
    viewer = model_viewer.behaviour_viewer()
    inventory = {}
    for name in RIG_BEHAVIOURS:
        ids, registered = _behaviour_ids(viewer, name)
        inventory[name] = {
            "count": len(ids),
            "owner_ids": _owners(viewer, ids, context),
            "registered": registered,
        }
    rig_infos = []
    for behaviour_id in viewer.get_behaviours("RigInfo"):
        owner = viewer.get_behaviour_owner(behaviour_id)
        related_joints = []
        with suppress(Exception):
            related_joints = [
                context["id_string"](item)
                for item in viewer.get_behaviour_objects_range(behaviour_id, "related_joints")
            ]
        rig_infos.append(
            {
                "behaviour_id": context["id_string"](behaviour_id),
                "owner_id": context["id_string"](owner),
                "related_joint_ids": sorted(set(related_joints)),
                "related_joint_count": len(set(related_joints)),
            }
        )
    selected = list(context["scene_state"](context["scene_view"]() or scene)["selection"])
    quick_rig = {"available": False}
    view_scene = context["scene_view"]()
    if view_scene is not None:
        with suppress(Exception):
            editor = (
                context["csc"]
                .app.get_application()
                .get_tools_manager()
                .get_tool("RiggingToolWindowTool")
                .editor(view_scene)
            )
            quick_rig = {
                "available": editor is not None,
                "create_autoposing": bool(editor.get_is_create_autoposing()),
                "mirror_plane": context["json_safe"](editor.get_character_mirror_plane()),
            }
    return {
        "behaviours": inventory,
        "rig_infos": rig_infos,
        "rig_info_count": len(rig_infos),
        "selected_ids": selected,
        "selected_joint_ids": sorted(set(selected) & set(inventory["Joint"]["owner_ids"])),
        "selected_point_ids": sorted(set(selected) & set(inventory["Point"]["owner_ids"])),
        "quick_rig": quick_rig,
        "ready_for_animation": bool(rig_infos and inventory["Point"]["count"]),
        "ready_for_physics": bool(inventory["PhysicsSettings"]["count"] or inventory["RigidBody"]["count"]),
    }, []


@handler("rig.constraint_drivers")
def constraint_drivers(scene, _arguments, _request, context):
    domain = context["domain_scene"](scene)
    viewer = domain.model_viewer()
    candidates = []
    failures = []

    def inspect_update(_model, update, _scene):
        try:
            required = ("Main Position", "Direction Position", "Additional Position")
            for object_id in viewer.get_objects():
                obj = update.get_object_by_id(object_id)
                if all(obj.has_input(name) for name in required):
                    candidates.append(
                        {
                            "id": context["id_string"](object_id),
                            "name": str(viewer.get_object_name(object_id)),
                            "type": str(viewer.get_object_type_name(object_id)),
                        }
                    )
        except Exception as exc:
            failures.append(str(exc))

    before = context["scene_state"](context["scene_view"]() or scene)["revision"]
    domain.modify("Cascadeur Complete: inspect constraint drivers", inspect_update)
    after = context["scene_state"](context["scene_view"]() or scene)["revision"]
    if failures:
        raise RuntimeError("Constraint driver inspection failed: " + " | ".join(failures))
    if before != after:
        raise AssertionError("POSTCONDITION_FAILED: constraint driver inspection changed the scene")
    candidates.sort(key=lambda item: (item["name"], item["id"]))
    return {"items": candidates, "count": len(candidates)}, []


@handler("rig.joint_create")
def joint_create(scene, _arguments, _request, context):
    from commands.add import add_joint

    domain = context["domain_scene"](scene)
    behaviours = domain.model_viewer().behaviour_viewer()
    before_owners = _behaviour_owner_set(behaviours, "Joint", context)
    add_joint.run(domain)
    after_owners = _behaviour_owner_set(behaviours, "Joint", context)
    created = sorted(after_owners - before_owners)
    if len(created) != 1:
        raise AssertionError(
            "POSTCONDITION_FAILED: Add.Joint did not create exactly one Joint owner"
        )
    created_id = context["object_id"](created[0])
    selected = {
        context["id_string"](item)
        for item in domain.selector().selected().ids
        if isinstance(item, context["csc"].model.ObjectId)
    }
    if created[0] not in selected:
        raise AssertionError("POSTCONDITION_FAILED: created Joint was not selected")
    return {
        "created_id": created[0],
        "name": str(domain.model_viewer().get_object_name(created_id)),
        "before_joint_count": len(before_owners),
        "after_joint_count": len(after_owners),
        "execution": "commands.add.add_joint.run",
    }, []


@handler("rig.rig_info_create")
def rig_info_create(scene, arguments, _request, context):
    import rig_gen.add_support_info as support_info

    joint_ids = [str(item) for item in arguments.get("joint_ids", [])]
    if not joint_ids:
        raise ValueError("joint_ids must contain at least one Joint owner")
    if len(set(joint_ids)) != len(joint_ids):
        raise ValueError("joint_ids must not contain duplicates")
    domain = context["domain_scene"](scene)
    converted = _require_existing_objects(domain, joint_ids, context, "joint_ids")
    behaviours = domain.model_viewer().behaviour_viewer()
    joint_owners = _behaviour_owner_set(behaviours, "Joint", context)
    invalid = [item for item in joint_ids if item not in joint_owners]
    if invalid:
        raise ValueError("Objects do not own Joint behaviours: " + ", ".join(invalid))

    linked = set()
    for rig_info_id in behaviours.get_behaviours("RigInfo"):
        related = {
            context["id_string"](item)
            for item in behaviours.get_behaviour_objects_range(rig_info_id, "related_joints")
        }
        linked.update(set(joint_ids) & related)
    if linked:
        raise ValueError("Joints are already linked to RigInfo: " + ", ".join(sorted(linked)))

    before_owners = _behaviour_owner_set(behaviours, "RigInfo", context)
    created_behaviours = []
    requested_name = str(arguments.get("name", ""))

    def create(model, update, _scene):
        _object, rig_info_id = support_info.create_support_info(model, update, requested_name)
        model.behaviour_editor().set_behaviour_model_objects_to_range(
            rig_info_id,
            "related_joints",
            converted,
        )
        created_behaviours.append(rig_info_id)

    domain.modify("Cascadeur Complete: create RigInfo", create)
    behaviours = domain.model_viewer().behaviour_viewer()
    after_owners = _behaviour_owner_set(behaviours, "RigInfo", context)
    created_owners = sorted(after_owners - before_owners)
    if len(created_owners) != 1 or len(created_behaviours) != 1:
        raise AssertionError("POSTCONDITION_FAILED: exactly one RigInfo was not created")
    created_behaviour = created_behaviours[0]
    observed_related = sorted(
        {
            context["id_string"](item)
            for item in behaviours.get_behaviour_objects_range(created_behaviour, "related_joints")
        }
    )
    if observed_related != sorted(joint_ids):
        raise AssertionError("POSTCONDITION_FAILED: RigInfo related_joints differ from request")
    created_owner = context["object_id"](created_owners[0])
    return {
        "created_id": created_owners[0],
        "name": str(domain.model_viewer().get_object_name(created_owner)),
        "related_joint_ids": observed_related,
        "before_rig_info_count": len(before_owners),
        "after_rig_info_count": len(after_owners),
        "execution": "rig_gen.add_support_info.create_support_info",
    }, []


@handler("rig.ik_chain_create")
def ik_chain_create(scene, arguments, _request, context):
    import pycsc
    from commands.ik.add_ik import calculate_chain_length, resolve_attraction_point

    ordered_ids = [str(item) for item in arguments.get("ordered_ids", [])]
    if len(ordered_ids) < 2:
        raise ValueError("ordered_ids requires at least main and secondary end objects")
    if len(set(ordered_ids)) != len(ordered_ids):
        raise ValueError("ordered_ids must not contain duplicates")
    domain = context["domain_scene"](scene)
    converted = _require_existing_objects(domain, ordered_ids, context, "ordered_ids")
    behaviours = domain.model_viewer().behaviour_viewer()
    attraction_owners = _behaviour_owner_set(behaviours, "AttractionPoint", context)
    for end_id in (ordered_ids[0], ordered_ids[-1]):
        if end_id not in attraction_owners:
            raise ValueError("IK end lacks AttractionPoint behaviour: " + end_id)
    connection_owners = _behaviour_owner_set(behaviours, "ConnectionPointTwoBody", context)
    missing_links = [item for item in ordered_ids[1:-1] if item not in connection_owners]
    if missing_links:
        raise ValueError(
            "IK middle links lack ConnectionPointTwoBody behaviour: " + ", ".join(missing_links)
        )

    before_owners = _behaviour_owner_set(behaviours, "ChainIK", context)
    py_scene = pycsc.wrap(domain)
    point_objects = [pycsc.wrap(item, py_scene) for item in converted]
    first_end = point_objects[0]
    second_end = point_objects[-1]
    chain_links = point_objects[1:-1]
    initial_length = calculate_chain_length(py_scene, point_objects)
    created = []

    def create(_py_scene):
        first_attractions = first_end.get_behaviours_by_name("AttractionPoint")
        second_attractions = second_end.get_behaviours_by_name("AttractionPoint")
        link_points = [item.get_behaviour("ConnectionPointTwoBody") for item in chain_links]
        first_attraction, second_attraction = resolve_attraction_point(
            py_scene,
            link_points,
            first_attractions,
            second_attractions,
        )
        ik_behaviour = first_end.add_behaviour("ChainIK")
        ik_behaviour.first_end.set(first_attraction)
        ik_behaviour.second_end.set(second_attraction)
        ik_behaviour.connections.set(link_points)
        ik_behaviour.length.create("Chain Length", context["csc"].model.DataMode.Static, initial_length)
        ik_behaviour.length_fixed.create("Chain Length Fixed", context["csc"].model.DataMode.Static, False)
        ik_behaviour.inv_mass_1.create("Inverse Mass 1", context["csc"].model.DataMode.Static, 1.0)
        ik_behaviour.inv_mass_2.create("Inverse Mass 2", context["csc"].model.DataMode.Static, 1.0)
        created.append(context["id_string"](ik_behaviour.handle))

    edited = py_scene.edit("Cascadeur Complete: add IK chain", create)
    if edited is False:
        raise RuntimeError("IK chain edit was rejected by Cascadeur")
    after_owners = _behaviour_owner_set(behaviours, "ChainIK", context)
    if ordered_ids[0] not in after_owners - before_owners:
        raise AssertionError("POSTCONDITION_FAILED: ChainIK was not created on the main end")
    return {
        "main_end_id": ordered_ids[0],
        "secondary_end_id": ordered_ids[-1],
        "connection_ids": ordered_ids[1:-1],
        "initial_length": float(initial_length),
        "created_behaviour_ids": created,
        "before_chain_ik_count": len(before_owners),
        "after_chain_ik_count": len(after_owners),
        "execution": "commands.ik.add_ik verified direct implementation",
    }, []


@handler("rig.rig_elements_create")
def rig_elements_create(scene, arguments, request, context):
    """Create deterministic manual-rig elements from explicit joint pairs.

    This uses the same bundled rig process as Cascadeur's Rigging mode, but
    does not depend on the GUI selection order or on a modal window.
    """

    import pycsc
    from prototypes.add_rig_elements_actions import actions as rig_actions

    pair_rows = list(arguments.get("pairs", []))
    if not pair_rows:
        raise ValueError("pairs must contain at least one joint pair")
    domain = context["domain_scene"](scene)
    viewer = domain.model_viewer().behaviour_viewer()
    joint_owners = _behaviour_owner_set(viewer, "Joint", context)
    parsed_pairs = []
    requested_starts = []
    for index, row in enumerate(pair_rows):
        if not isinstance(row, dict):
            raise ValueError(f"pairs[{index}] must be an object")
        start = str(row.get("joint_id", ""))
        direction = row.get("direction_joint_id")
        direction = str(direction) if direction else None
        if not start:
            raise ValueError(f"pairs[{index}].joint_id is required")
        if start not in joint_owners:
            raise ValueError(f"pairs[{index}].joint_id does not own Joint: {start}")
        if direction is not None and direction not in joint_owners:
            raise ValueError(
                f"pairs[{index}].direction_joint_id does not own Joint: {direction}"
            )
        if direction == start:
            raise ValueError(f"pairs[{index}] cannot point a Joint at itself")
        requested_starts.append(start)
        parsed_pairs.append(
            (
                context["object_id"](start),
                context["csc"].model.ObjectId.null()
                if direction is None
                else context["object_id"](direction),
            )
        )
    if len(set(requested_starts)) != len(requested_starts):
        raise ValueError("pairs must not contain duplicate joint_id values")

    options = dict(arguments.get("options", {}))
    data = context["csc"].rig.AddElementData()
    option_types = {
        "only_box_controller": bool,
        "box_multiplier": int,
        "axis_point_controller": int,
        "use_global_axis": bool,
        "orthogonal_with_parent": bool,
        "offset_point_controller": int,
        "joint_size_without_child": float,
    }
    unknown_options = sorted(set(options) - set(option_types))
    if unknown_options:
        raise ValueError("Unknown rig element options: " + ", ".join(unknown_options))
    normalized_options = {}
    for name, converter in option_types.items():
        if name in options:
            value = converter(options[name])
            if name in {"box_multiplier", "joint_size_without_child"} and value <= 0:
                raise ValueError(name + " must be positive")
            setattr(data, name, value)
            normalized_options[name] = value

    before = {
        name: _behaviour_owner_set(viewer, name, context)
        for name in (
            "TechnicalLinks",
            "RigidBody",
            "RigidBodyView",
            "Point",
            "BoxView",
            "PhysicsSettings",
        )
    }
    py_scene = pycsc.wrap(domain)
    created_objects = rig_actions._add_rig_elements(py_scene, data, parsed_pairs)
    viewer = domain.model_viewer().behaviour_viewer()
    after = {
        name: _behaviour_owner_set(viewer, name, context)
        for name in before
    }
    created_rig_elements = sorted(after["TechnicalLinks"] - before["TechnicalLinks"])
    if len(created_rig_elements) != len(parsed_pairs):
        raise AssertionError(
            "POSTCONDITION_FAILED: manual rig did not create exactly one TechnicalLinks owner per pair"
        )
    observed_joint_by_element = {}
    for owner_id in created_rig_elements:
        technical_links = viewer.get_behaviour_by_name(
            context["object_id"](owner_id), "TechnicalLinks"
        )
        joint_reference = viewer.get_behaviour_reference(technical_links, "joint")
        if joint_reference.is_null():
            raise AssertionError("POSTCONDITION_FAILED: new rig element has no linked Joint")
        observed_joint_by_element[owner_id] = context["id_string"](
            viewer.get_behaviour_owner(joint_reference)
        )
    if sorted(observed_joint_by_element.values()) != sorted(requested_starts):
        raise AssertionError("POSTCONDITION_FAILED: new rig elements link different Joints")
    box_only = bool(normalized_options.get("only_box_controller", False))
    if not box_only and len(after["RigidBodyView"] - before["RigidBodyView"]) != len(parsed_pairs):
        raise AssertionError(
            "POSTCONDITION_FAILED: full rig elements did not create one RigidBodyView per pair"
        )
    if request.get("feature_id") == "rigid_body" and box_only:
        raise AssertionError("POSTCONDITION_FAILED: rigid_body cannot create box-only rig elements")
    returned_ids = []
    for item in created_objects or []:
        raw = getattr(item, "handle", item)
        returned_ids.append(context["id_string"](raw))
    return {
        "pairs": [
            {
                "joint_id": requested_starts[index],
                "direction_joint_id": pair_rows[index].get("direction_joint_id"),
            }
            for index in range(len(pair_rows))
        ],
        "options": normalized_options,
        "created_rig_element_ids": created_rig_elements,
        "returned_ids": sorted(set(returned_ids)),
        "linked_joint_by_element": observed_joint_by_element,
        "created_behaviour_owner_ids": {
            name: sorted(after[name] - before[name])
            for name in after
        },
        "execution": "prototypes.add_rig_elements_actions.actions._add_rig_elements",
    }, []


@handler("rig.additional_point_create")
def additional_point_create(scene, arguments, _request, context):
    from prototypes.additional_actions import actions as additional_actions

    domain = context["domain_scene"](scene)
    owner_id = str(arguments.get("rig_element_id", ""))
    _require_existing_objects(domain, [owner_id], context, "rig_element_id")
    viewer = domain.model_viewer().behaviour_viewer()
    technical_links = viewer.get_behaviour_by_name(context["object_id"](owner_id), "TechnicalLinks")
    if technical_links.is_null():
        raise ValueError("rig_element_id does not own TechnicalLinks: " + owner_id)
    before = _reference_owner_ids(viewer, technical_links, "manual_points", context)
    _select_exact(domain, [context["object_id"](owner_id)])
    color = context["csc"].rig.AddElementData().point_color
    additional_actions.add_additional_point_controller(domain, color)
    viewer = domain.model_viewer().behaviour_viewer()
    technical_links = viewer.get_behaviour_by_name(context["object_id"](owner_id), "TechnicalLinks")
    after = _reference_owner_ids(viewer, technical_links, "manual_points", context)
    created = sorted(set(after) - set(before))
    if len(created) != 1:
        raise AssertionError(
            "POSTCONDITION_FAILED: exactly one additional Point controller was not linked"
        )
    return {
        "rig_element_id": owner_id,
        "created_point_id": created[0],
        "manual_point_ids": after,
        "execution": "prototypes.additional_actions.actions.add_additional_point_controller",
    }, []


@handler("rig.additional_box_create")
def additional_box_create(scene, arguments, _request, context):
    from prototypes.additional_actions import actions as additional_actions

    domain = context["domain_scene"](scene)
    owner_id = str(arguments.get("rig_element_id", ""))
    _require_existing_objects(domain, [owner_id], context, "rig_element_id")
    viewer = domain.model_viewer().behaviour_viewer()
    technical_links = viewer.get_behaviour_by_name(context["object_id"](owner_id), "TechnicalLinks")
    if technical_links.is_null():
        raise ValueError("rig_element_id does not own TechnicalLinks: " + owner_id)
    before = _reference_owner_ids(viewer, technical_links, "additional_boxes", context)
    _select_exact(domain, [context["object_id"](owner_id)])
    result = additional_actions.add_additional_box(domain)
    if result is False:
        raise RuntimeError("Cascadeur rejected additional Box controller creation")
    viewer = domain.model_viewer().behaviour_viewer()
    technical_links = viewer.get_behaviour_by_name(context["object_id"](owner_id), "TechnicalLinks")
    after = _reference_owner_ids(viewer, technical_links, "additional_boxes", context)
    created = sorted(set(after) - set(before))
    if len(created) != 1:
        raise AssertionError(
            "POSTCONDITION_FAILED: exactly one additional Box controller was not linked"
        )
    return {
        "rig_element_id": owner_id,
        "created_box_id": created[0],
        "additional_box_ids": after,
        "execution": "prototypes.additional_actions.actions.add_additional_box",
    }, []


@handler("rig.spline_ik_create")
def spline_ik_create(scene, arguments, _request, context):
    from prototypes.main_actions import actions as main_actions

    start_id = str(arguments.get("start_joint_id", ""))
    end_id = str(arguments.get("end_joint_id", ""))
    if not start_id or not end_id or start_id == end_id:
        raise ValueError("start_joint_id and a different end_joint_id are required")
    domain = context["domain_scene"](scene)
    _require_existing_objects(domain, [start_id, end_id], context, "Spline IK endpoints")
    viewer = domain.model_viewer().behaviour_viewer()
    joint_owners = _behaviour_owner_set(viewer, "Joint", context)
    invalid = [item for item in (start_id, end_id) if item not in joint_owners]
    if invalid:
        raise ValueError("Spline IK endpoints do not own Joint: " + ", ".join(invalid))
    start = context["object_id"](start_id)
    end = context["object_id"](end_id)

    endpoint_behaviours = {
        viewer.get_behaviour_by_name(start, "Joint"),
        viewer.get_behaviour_by_name(end, "Joint"),
    }
    already_linked = set()
    for spline_id in viewer.get_behaviours("ProtoSplineIk"):
        already_linked.update(viewer.get_behaviour_reference_range(spline_id, "joints"))
    if endpoint_behaviours & already_linked:
        raise ValueError("A Spline IK endpoint already belongs to ProtoSplineIk")

    try:
        technical_links, joints = main_actions.get_splineIk_elements(domain, viewer, start, end)
    except Exception as exc:
        raise ValueError("Spline IK endpoints are not a supported rigged hierarchy: " + str(exc)) from exc
    if not technical_links:
        raise ValueError("No full rig elements were found along the Spline IK hierarchy")
    if len(technical_links) == len(joints):
        raise ValueError("Spline IK requires fewer rig elements than joints along the hierarchy")

    before = _behaviour_owner_set(viewer, "ProtoSplineIk", context)
    created = []
    requested_name = str(arguments.get("name", "")) or None

    def create(model, update, _scene):
        obj = main_actions.add_proto_spline_ik_beh(
            model,
            update,
            domain,
            technical_links,
            joints,
            requested_name,
        )
        created.append(context["id_string"](obj.object_id()))

    domain.modify("Cascadeur Complete: create Spline IK", create)
    viewer = domain.model_viewer().behaviour_viewer()
    after = _behaviour_owner_set(viewer, "ProtoSplineIk", context)
    created_owners = sorted(after - before)
    if len(created_owners) != 1 or created_owners != created:
        raise AssertionError("POSTCONDITION_FAILED: exactly one ProtoSplineIk was not created")
    behaviour = viewer.get_behaviour_by_name(
        context["object_id"](created_owners[0]), "ProtoSplineIk"
    )
    observed_joints = {
        context["id_string"](viewer.get_behaviour_owner(item))
        for item in viewer.get_behaviour_reference_range(behaviour, "joints")
    }
    expected_joints = {
        context["id_string"](viewer.get_behaviour_owner(item)) for item in joints
    }
    observed_links = {
        context["id_string"](viewer.get_behaviour_owner(item))
        for item in viewer.get_behaviour_reference_range(behaviour, "tech_links")
    }
    expected_links = {
        context["id_string"](viewer.get_behaviour_owner(item)) for item in technical_links
    }
    if observed_joints != expected_joints or observed_links != expected_links:
        raise AssertionError("POSTCONDITION_FAILED: ProtoSplineIk references differ from resolved hierarchy")
    return {
        "created_id": created_owners[0],
        "start_joint_id": start_id,
        "end_joint_id": end_id,
        "joint_ids": sorted(observed_joints),
        "rig_element_ids": sorted(observed_links),
        "execution": "prototypes.main_actions.actions.add_proto_spline_ik_beh",
    }, []


@handler("rig.twist")
def twist(scene, arguments, _request, context):
    from prototypes.main_actions import actions as main_actions

    domain = context["domain_scene"](scene)
    action = str(arguments.get("action", "set"))
    if action not in ("set", "remove"):
        raise ValueError("Twist action must be set or remove")
    box_id = str(arguments.get("box_id", ""))
    if not box_id:
        raise ValueError("box_id is required")
    ids = [box_id]
    joint_id = str(arguments.get("joint_id", ""))
    if action == "set":
        if not joint_id:
            raise ValueError("joint_id is required for Twist set")
        ids.append(joint_id)
    _require_existing_objects(domain, ids, context, "Twist objects")
    viewer = domain.model_viewer().behaviour_viewer()
    box = context["object_id"](box_id)
    proto_box = viewer.get_behaviour_by_name(box, "ProtoBox")
    if proto_box.is_null():
        raise ValueError("box_id does not own ProtoBox: " + box_id)
    before_joint = _reference_owner(viewer, proto_box, "twist_id", context)

    if action == "set":
        joint = context["object_id"](joint_id)
        if viewer.get_behaviour_by_name(joint, "Joint").is_null():
            raise ValueError("joint_id does not own Joint: " + joint_id)
        _select_exact(domain, [joint, box])
        main_actions.set_twist(domain)
    else:
        _select_exact(domain, [box])
        main_actions.remove_twist(domain)

    viewer = domain.model_viewer().behaviour_viewer()
    proto_box = viewer.get_behaviour_by_name(box, "ProtoBox")
    after_joint = _reference_owner(viewer, proto_box, "twist_id", context)
    if action == "set" and (after_joint != joint_id or after_joint == before_joint):
        raise AssertionError("POSTCONDITION_FAILED: ProtoBox twist_id does not reference requested Joint")
    if action == "remove" and after_joint is not None:
        raise AssertionError("POSTCONDITION_FAILED: ProtoBox twist_id remains after remove")
    return {
        "action": action,
        "box_id": box_id,
        "joint_id": joint_id or None,
        "before_twist_joint_id": before_joint,
        "after_twist_joint_id": after_joint,
        "execution": (
            "prototypes.main_actions.actions.set_twist"
            if action == "set"
            else "prototypes.main_actions.actions.remove_twist"
        ),
    }, []
