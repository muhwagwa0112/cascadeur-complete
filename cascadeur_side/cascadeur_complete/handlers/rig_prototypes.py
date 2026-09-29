"""Rig Mode prototype adapters built on Cascadeur's bundled prototype actions.

Cascadeur's prototype actions read the current selection and report problems
with ``scene.error`` instead of raising. Each adapter therefore validates its
explicit inputs first, selects exactly those objects, calls the bundled action
(or its selection-free core), and verifies the resulting behaviour graph.
"""

from __future__ import annotations

from ..handler_registry import handler

RIG_MODE_COLOR = [0.0, 0.5, 0.0]


def _viewer(domain):
    return domain.model_viewer().behaviour_viewer()


def _existing(domain, context):
    return {context["id_string"](item) for item in domain.model_viewer().get_objects()}


def _require(domain, ids, context, label):
    ids = [str(item) for item in ids]
    if not ids:
        raise ValueError(label + " must not be empty")
    unknown = sorted(set(ids) - _existing(domain, context))
    if unknown:
        raise KeyError(label + " contains unknown object IDs: " + ", ".join(unknown))
    return [context["object_id"](item) for item in ids]


def _owners(domain, behaviour, context):
    try:
        ids = _viewer(domain).get_behaviours(behaviour)
    except RuntimeError:
        return set()
    return {context["id_string"](_viewer(domain).get_behaviour_owner(item)) for item in ids}


def _select(domain, object_ids, context):
    def apply(_model, _update, _scene, session):
        session.take_selector().select(
            set(object_ids), object_ids[0] if object_ids else context["csc"].model.ObjectId.null()
        )

    domain.modify_with_session("Cascadeur Complete: select prototype objects", apply)


def _technical_links(domain, object_id, context):
    links = _viewer(domain).get_behaviour_by_name(object_id, "TechnicalLinks")
    if links.is_null():
        raise ValueError("Object is not a rig element (no TechnicalLinks): " + context["id_string"](object_id))
    return links


def _global_position(domain, object_id):
    viewer = _viewer(domain)
    transform = viewer.get_behaviour_by_name(object_id, "Transform")
    data_id = viewer.get_behaviour_data(transform, "global_position")
    value = domain.data_viewer().get_data_value(data_id, 0)
    converter = getattr(value, "tolist", None)
    return [float(item) for item in (converter() if callable(converter) else value)]


def _close(left, right, tolerance=1e-3):
    return all(abs(a - b) <= tolerance for a, b in zip(left, right, strict=True))


def _reference_owner(domain, behaviour_id, name, context):
    reference = _viewer(domain).get_behaviour_reference(behaviour_id, name)
    return None if reference.is_null() else context["id_string"](_viewer(domain).get_behaviour_owner(reference))


# -- rig mode -------------------------------------------------------------------------


@handler("rig.mode", postconditions=("rig_prototypes_present", "rig_generated_from_prototypes"))
def rig_mode(scene, arguments, _request, context):
    import rig_mode.off as rig_mode_off
    import rig_mode.on as rig_mode_on

    domain = context["domain_scene"](scene)
    action = str(arguments.get("action", "on"))
    if action not in ("on", "off", "regenerate"):
        raise ValueError("rig mode action must be on, off or regenerate")
    before_links = _owners(domain, "TechnicalLinks", context)
    if action in ("on", "regenerate"):
        rig_ids = _owners(domain, "RigInfo", context)
        if len(rig_ids) != 1:
            raise ValueError("Rig Mode needs exactly one RigInfo in the scene; found " + str(len(rig_ids)))
        _select(domain, [context["object_id"](next(iter(rig_ids)))], context)
        rig_mode_on.run_raw(domain, list(RIG_MODE_COLOR))
        if not _owners(domain, "TechnicalLinks", context):
            raise AssertionError("POSTCONDITION_FAILED: Rig Mode produced no rig element prototypes")
    if action in ("off", "regenerate"):
        if not _owners(domain, "TechnicalLinks", context):
            raise ValueError("The scene has no rig element prototypes; enable Rig Mode first")
        rig_mode_off.run(domain, True)
        if _owners(domain, "TechnicalLinks", context):
            raise AssertionError("POSTCONDITION_FAILED: rig prototypes remain after generating the rig")
        if not _owners(domain, "RigInfo", context):
            raise AssertionError("POSTCONDITION_FAILED: generated rig has no RigInfo")
    return {
        "observed_postconditions": ["rig_prototypes_present"] if action == "on" else ["rig_generated_from_prototypes"],
        "action": action,
        "rig_elements_before": len(before_links),
        "rig_elements_after": len(_owners(domain, "TechnicalLinks", context)),
        "rig_infos": sorted(_owners(domain, "RigInfo", context)),
    }, []


# -- rig elements ---------------------------------------------------------------------


@handler("rig.element_delete", postconditions=("rig_elements_absent",))
def element_delete(scene, arguments, _request, context):
    from prototypes.delete_actions import actions as delete_actions

    domain = context["domain_scene"](scene)
    ids = _require(domain, arguments.get("rig_element_ids", []), context, "rig_element_ids")
    for object_id in ids:
        _technical_links(domain, object_id, context)
    _select(domain, ids, context)
    delete_actions.delete_rig_element(domain)
    remaining = sorted({context["id_string"](item) for item in ids} & _owners(domain, "TechnicalLinks", context))
    if remaining:
        raise AssertionError("POSTCONDITION_FAILED: rig elements remain: " + ", ".join(remaining))
    return {"deleted": sorted(context["id_string"](item) for item in ids)}, []


def _hinge_points(domain, object_id, context):
    viewer = _viewer(domain)
    links = _technical_links(domain, object_id, context)
    additional = viewer.get_behaviour_reference(links, "additional_point")
    if additional.is_null() or viewer.get_behaviour_reference(links, "rigid_body").is_null():
        raise ValueError("Hinge elements need a rigid body and an additional point: " + context["id_string"](object_id))
    return viewer.get_behaviour_owner(additional)


@handler("rig.hinge", postconditions=("hinge_additional_points_coincide",))
def hinge(scene, arguments, _request, context):
    from prototypes.hinge_actions import actions as hinge_actions
    from prototypes.hinge_actions import implementation as hinge_impl

    domain = context["domain_scene"](scene)
    action = str(arguments.get("action", "union"))
    if action not in ("union", "orthogonalize", "straighten"):
        raise ValueError("hinge action must be union, orthogonalize or straighten")
    ids = _require(domain, arguments.get("rig_element_ids", []), context, "rig_element_ids")
    if len(ids) != 2:
        raise ValueError("A hinge needs exactly two rig elements")
    points = {context["id_string"](item): _hinge_points(domain, item, context) for item in ids}
    parent, child = hinge_actions.get_parent_child(_viewer(domain), list(ids))
    if action != "union" and not _close(
        _global_position(domain, points[context["id_string"](parent)]),
        _global_position(domain, points[context["id_string"](child)]),
    ):
        raise ValueError("The two rig elements are not a hinge yet; run the union action first")

    def edit(model, _update, scene_updater):
        if action == "union":
            actual = hinge_actions.union_to_hinge_action(domain, model, parent, child)
        elif action == "orthogonalize":
            hinge_impl.change_to_ortho(domain, model, parent, child)
            actual = set()
        else:
            actual = hinge_actions.straighten_to_hinge_action(domain, model, parent, child)
        scene_updater.generate_update()
        scene_updater.run_update(actual, 0)

    domain.modify_update("Cascadeur Complete: hinge " + action, edit)
    left = _global_position(domain, points[context["id_string"](parent)])
    right = _global_position(domain, points[context["id_string"](child)])
    if not _close(left, right):
        raise AssertionError("POSTCONDITION_FAILED: hinge additional points do not coincide")
    return {
        "action": action,
        "parent_id": context["id_string"](parent),
        "child_id": context["id_string"](child),
        "additional_point": left,
    }, []


@handler("rig.prototype_mirror", postconditions=("mirrored_rig_elements_created",))
def prototype_mirror(scene, arguments, _request, context):
    from prototypes.mirror_actions import actions as mirror_actions

    domain = context["domain_scene"](scene)
    ids = _require(domain, arguments.get("rig_element_ids", []), context, "rig_element_ids")
    for object_id in ids:
        _technical_links(domain, object_id, context)
    original = str(arguments.get("original_suffix", "_l"))
    mirrored = str(arguments.get("mirror_suffix", "_r"))
    if not original or not mirrored or original == mirrored:
        raise ValueError("original_suffix and mirror_suffix must be different non-empty suffixes")
    editor = (
        context["csc"]
        .app.get_application()
        .get_tools_manager()
        .get_tool("RiggingToolWindowTool")
        .editor(context["scene_view"]())
    )
    plane = arguments.get("mirror_plane")
    plane = editor.get_character_mirror_plane() if plane is None else int(plane)
    before = _owners(domain, "TechnicalLinks", context)
    _select(domain, ids, context)
    mirror_actions.create_mirror(domain, original, mirrored, plane, context["csc"].rig.AddElementData().point_color)
    created = sorted(_owners(domain, "TechnicalLinks", context) - before)
    if not created:
        raise AssertionError("POSTCONDITION_FAILED: no mirrored rig element was created")
    return {"created_rig_element_ids": created, "mirror_plane": plane, "suffixes": [original, mirrored]}, []


# -- joints ---------------------------------------------------------------------------


def _virtual_owner_ids(domain, context):
    from prototypes.rig_joint_actions import virtual

    return {
        context["id_string"](item)
        for item in domain.model_viewer().get_objects()
        if not virtual.get_virtual_joint_behaviour(domain, item).is_null()
    }


@handler("rig.virtual_joint", postconditions=("virtual_joint_created", "virtual_joint_absent"))
def virtual_joint(scene, arguments, _request, context):
    from prototypes.rig_joint_actions import virtual

    domain = context["domain_scene"](scene)
    action = str(arguments.get("action", "create"))
    joint = _require(domain, [arguments.get("joint_id", "")], context, "joint_id")[0]
    if _viewer(domain).get_behaviour_by_name(joint, "Joint").is_null():
        raise ValueError("joint_id does not own a Joint behaviour")
    before_objects = _existing(domain, context)
    before_virtual = _virtual_owner_ids(domain, context)
    _select(domain, [joint], context)
    if action == "create":
        virtual.add_virtual_joint(domain)
        created = sorted(
            (_virtual_owner_ids(domain, context) - before_virtual) & (_existing(domain, context) - before_objects)
        )
        if len(created) != 1:
            raise AssertionError("POSTCONDITION_FAILED: exactly one virtual joint was not created")
        return {"observed_postconditions": ["virtual_joint_created"], "created_id": created[0]}, []
    if action != "delete":
        raise ValueError("virtual joint action must be create or delete")
    if context["id_string"](joint) not in before_virtual:
        raise ValueError("joint_id is not a virtual joint")
    virtual.delete_virtual_joint(domain)
    if context["id_string"](joint) in _existing(domain, context):
        raise AssertionError("POSTCONDITION_FAILED: virtual joint remains")
    return {"observed_postconditions": ["virtual_joint_absent"], "deleted_id": context["id_string"](joint)}, []


@handler("rig.joint_delete", postconditions=("joint_branch_absent",))
def joint_delete(scene, arguments, _request, context):
    import common.hierarchy as hierarchy
    from prototypes.rig_joint_actions import standard

    domain = context["domain_scene"](scene)
    joint = _require(domain, [arguments.get("joint_id", "")], context, "joint_id")[0]
    if standard.get_rig_joint_behaviour(domain, joint).is_null():
        raise ValueError("joint_id is not a standard rig joint")
    branch = {context["id_string"](item) for item in hierarchy.get_object_branch_inclusive(joint, domain)}
    _select(domain, [joint], context)
    standard.delete_standard_joint(domain)
    remaining = sorted(branch & _existing(domain, context))
    if remaining:
        raise AssertionError("POSTCONDITION_FAILED: joint branch objects remain: " + ", ".join(remaining))
    return {"deleted_ids": sorted(branch)}, []


@handler("rig.snap", postconditions=("snap_positions_equal",))
def snap(scene, arguments, _request, context):
    from prototypes.rig_joint_actions import common as joint_common
    from prototypes.rig_joint_actions import virtual

    domain = context["domain_scene"](scene)
    mode = str(arguments.get("mode", "rig_to_joint"))
    if mode not in ("rig_to_joint", "joint_to_rig"):
        raise ValueError("mode must be rig_to_joint or joint_to_rig")
    target = _require(domain, [arguments.get("id", "")], context, "id")[0]
    if mode == "rig_to_joint":
        _technical_links(domain, target, context)
        element = target
        joint = joint_common.get_rig_joint(domain, element)
        if joint.is_null():
            raise ValueError("The rig element has no joint")
        _select(domain, [element], context)
        virtual.snap_rig_to_joint(domain)
    else:
        joint = target
        if virtual.get_virtual_joint_behaviour(domain, joint).is_null():
            raise ValueError("Only virtual joints can be snapped to their rig element")
        elements = joint_common.get_rig_elements(domain, [joint])
        if not elements:
            raise ValueError("The joint has no rig element")
        element = elements[joint]
        _select(domain, [joint], context)
        virtual.snap_joint_to_rig(domain)
    left = _global_position(domain, element)
    right = _global_position(domain, joint)
    if not _close(left, right):
        raise AssertionError("POSTCONDITION_FAILED: snapped objects do not share a global position")
    return {"mode": mode, "rig_element_id": context["id_string"](element), "joint_id": context["id_string"](joint)}, []


# -- prototype unions -----------------------------------------------------------------


@handler("rig.root_constraint", postconditions=("root_constraint_present", "root_constraint_absent"))
def root_constraint(scene, arguments, _request, context):
    from prototypes.main_actions import actions as main_actions

    domain = context["domain_scene"](scene)
    action = str(arguments.get("action", "add"))
    before = _owners(domain, "ProtoRootConstraint", context)
    if action == "add":
        root = _require(domain, [arguments.get("root_id", "")], context, "root_id")[0]
        element = _require(domain, [arguments.get("rig_element_id", "")], context, "rig_element_id")[0]
        _technical_links(domain, element, context)
        if not _viewer(domain).get_behaviour_by_name(root, "TechnicalLinks").is_null():
            raise ValueError("root_id must not be a rig element")

        def edit(model, update, _scene_updater):
            main_actions.add_proto_root_constraint_beh(model, update, domain, root, element)

        domain.modify("Cascadeur Complete: add root constraint", edit)
        created = sorted(_owners(domain, "ProtoRootConstraint", context) - before)
        if len(created) != 1:
            raise AssertionError("POSTCONDITION_FAILED: exactly one root constraint was not created")
        behaviour = _viewer(domain).get_behaviour_by_name(context["object_id"](created[0]), "ProtoRootConstraint")
        if _reference_owner(domain, behaviour, "rig_element", context) != context["id_string"](element):
            raise AssertionError("POSTCONDITION_FAILED: root constraint targets another rig element")
        return {"observed_postconditions": ["root_constraint_present"], "created_id": created[0]}, []
    if action != "remove":
        raise ValueError("root constraint action must be add or remove")
    target = str(arguments.get("constraint_id", ""))
    if target not in before:
        raise ValueError("constraint_id is not a ProtoRootConstraint owner")
    _select(domain, [context["object_id"](target)], context)
    main_actions.remove_proto_root_constraint(domain)
    if target in _owners(domain, "ProtoRootConstraint", context):
        raise AssertionError("POSTCONDITION_FAILED: root constraint remains")
    return {"observed_postconditions": ["root_constraint_absent"], "removed_id": target}, []


@handler("rig.fulcrum_group", postconditions=("fulcrum_group_present", "fulcrum_group_absent"))
def fulcrum_group(scene, arguments, _request, context):
    from prototypes.main_actions import actions as main_actions

    domain = context["domain_scene"](scene)
    action = str(arguments.get("action", "create"))
    before = _owners(domain, "ProtoFulcrumGroup", context)
    if action == "create":
        ids = _require(domain, arguments.get("rig_element_ids", []), context, "rig_element_ids")
        for object_id in ids:
            _technical_links(domain, object_id, context)

        def edit(model, update, _scene_updater):
            main_actions.create_fulcrum_group_beh(model, update, domain, ids, arguments.get("name") or None)

        domain.modify("Cascadeur Complete: create fulcrum group", edit)
        created = sorted(_owners(domain, "ProtoFulcrumGroup", context) - before)
        if len(created) != 1:
            raise AssertionError("POSTCONDITION_FAILED: exactly one fulcrum group was not created")
        container = _viewer(domain).get_behaviour_by_name(context["object_id"](created[0]), "ObjectsContainer")
        members = {context["id_string"](item) for item in _viewer(domain).get_behaviour_objects_range(container, "ids")}
        if members != {context["id_string"](item) for item in ids}:
            raise AssertionError("POSTCONDITION_FAILED: fulcrum group members differ from request")
        return {
            "observed_postconditions": ["fulcrum_group_present"],
            "created_id": created[0],
            "members": sorted(members),
        }, []
    if action != "remove":
        raise ValueError("fulcrum group action must be create or remove")
    target = str(arguments.get("group_id", ""))
    if target not in before:
        raise ValueError("group_id is not a ProtoFulcrumGroup owner")
    _select(domain, [context["object_id"](target)], context)
    main_actions.remove_fulcrum_group(domain)
    if target in _owners(domain, "ProtoFulcrumGroup", context):
        raise AssertionError("POSTCONDITION_FAILED: fulcrum group remains")
    return {"observed_postconditions": ["fulcrum_group_absent"], "removed_id": target}, []


@handler("rig.proto_center_of_mass_remove", postconditions=("proto_center_of_mass_absent",))
def proto_center_of_mass_remove(scene, arguments, _request, context):
    from prototypes.main_actions import actions as main_actions

    domain = context["domain_scene"](scene)
    ids = _require(domain, arguments.get("center_of_mass_ids", []), context, "center_of_mass_ids")
    owners = _owners(domain, "ProtoCenterOfMass", context)
    invalid = sorted({context["id_string"](item) for item in ids} - owners)
    if invalid:
        raise ValueError("Not ProtoCenterOfMass owners: " + ", ".join(invalid))
    _select(domain, ids, context)
    main_actions.remove_center_of_mass(domain)
    remaining = sorted({context["id_string"](item) for item in ids} & _owners(domain, "ProtoCenterOfMass", context))
    if remaining:
        raise AssertionError("POSTCONDITION_FAILED: prototype centers of mass remain: " + ", ".join(remaining))
    return {"removed_ids": sorted(context["id_string"](item) for item in ids)}, []


@handler("rig.additional_controller_remove", postconditions=("additional_controller_absent",))
def additional_controller_remove(scene, arguments, _request, context):
    from prototypes.additional_actions import actions as additional_actions

    domain = context["domain_scene"](scene)
    kind = str(arguments.get("kind", "point"))
    fields = {"point": ("manual_points", "ProtoPoint"), "box": ("additional_boxes", "ProtoBox")}
    if kind not in fields:
        raise ValueError("kind must be point or box")
    field, behaviour = fields[kind]
    controller = _require(domain, [arguments.get("controller_id", "")], context, "controller_id")[0]
    viewer = _viewer(domain)
    controller_behaviour = viewer.get_behaviour_by_name(controller, behaviour)
    if controller_behaviour.is_null():
        raise ValueError("controller_id does not own " + behaviour)
    linked = [
        item
        for item in viewer.get_behaviours("TechnicalLinks")
        if controller_behaviour in list(viewer.get_behaviour_reference_range(item, field))
    ]
    if not linked:
        raise ValueError("controller_id is not an additional " + kind + " controller")
    _select(domain, [controller], context)
    if kind == "point":
        additional_actions.remove_additional_point_controller(domain)
    else:
        additional_actions.remove_additional_box(domain)
    viewer = _viewer(domain)
    still_linked = [
        item
        for item in viewer.get_behaviours("TechnicalLinks")
        if controller_behaviour in list(viewer.get_behaviour_reference_range(item, field))
    ]
    if still_linked or context["id_string"](controller) in _existing(domain, context):
        raise AssertionError("POSTCONDITION_FAILED: additional controller remains")
    return {"kind": kind, "removed_id": context["id_string"](controller)}, []


LINK_FIELDS = {
    "user_additional_point": ("ProtoPoint", True),
    "additional_joint": ("Joint", True),
    "additional_parent": ("TechnicalLinks", False),
    "custom_rotation": ("TechnicalLinks", False),
}
FIELD_NAMES = {
    "user_additional_point": "user_additional_point",
    "additional_joint": "additional_joint",
    "additional_parent": "additional_parent",
    "custom_rotation": "custom_point_rotation",
}


@handler("rig.technical_link", postconditions=("technical_link_equals_request",))
def technical_link(scene, arguments, _request, context):
    """Set or clear one TechnicalLinks reference (the Rig Mode additional-* actions)."""
    import prototypes.prototypes_common.pub as prototype_pub
    import pycsc

    domain = context["domain_scene"](scene)
    kind = str(arguments.get("kind", ""))
    if kind not in LINK_FIELDS:
        raise ValueError("kind must be one of: " + ", ".join(sorted(LINK_FIELDS)))
    field = FIELD_NAMES[kind]
    source_behaviour, refresh_interpolation = LINK_FIELDS[kind]
    element = _require(domain, [arguments.get("rig_element_id", "")], context, "rig_element_id")[0]
    links = _technical_links(domain, element, context)
    viewer = _viewer(domain)
    action = str(arguments.get("action", "set"))
    if action == "set":
        source = _require(domain, [arguments.get("target_id", "")], context, "target_id")[0]
        if source_behaviour == "TechnicalLinks":
            # additional parent / custom rotation reference the joint link of another rig element
            other = _technical_links(domain, source, context)
            reference = viewer.get_behaviour_reference(other, "joint")
        else:
            reference = viewer.get_behaviour_by_name(source, source_behaviour)
        if reference.is_null():
            raise ValueError("target_id has no " + source_behaviour + " to reference")
        if kind == "user_additional_point":
            manual = list(viewer.get_behaviour_reference_range(links, "manual_points"))
            if reference not in manual:
                raise ValueError("target_id must be one of the rig element's additional point controllers")
    elif action == "remove":
        reference = context["csc"].model.BehaviourId.null()
    else:
        raise ValueError("action must be set or remove")

    def edit(model, update, _scene_updater):
        model.behaviour_editor().set_behaviour_reference(links, field, reference)
        if refresh_interpolation:
            py_scene = pycsc.wrap(domain)
            py_scene.set_modifiers(model, update)
            prototype_pub.update_interpolation_controller(pycsc.wrap(links, py_scene))

    domain.modify("Cascadeur Complete: " + kind + " " + action, edit)
    observed = _viewer(domain).get_behaviour_reference(links, field)
    if (action == "set" and observed != reference) or (action == "remove" and not observed.is_null()):
        raise AssertionError("POSTCONDITION_FAILED: " + field + " differs from request")
    return {"kind": kind, "action": action, "rig_element_id": context["id_string"](element), "field": field}, []


@handler("rig.autoposing_props", postconditions=("autoposing_names_equal_request",))
def autoposing_props(scene, arguments, _request, context):
    domain = context["domain_scene"](scene)
    ids = _require(domain, arguments.get("rig_element_ids", []), context, "rig_element_ids")
    for object_id in ids:
        _technical_links(domain, object_id, context)
    value = "props" if bool(arguments.get("enabled", True)) else ""
    names = ("main_name", "additional_name", "direction_name", "self_name")

    def edit(model, _update, _scene_updater):
        editor = model.data_editor()
        for object_id in ids:
            info = _viewer(domain).get_behaviour_by_name(object_id, "AutoPosingInfo")
            if info.is_null():
                info = model.behaviour_editor().add_behaviour(object_id, "AutoPosingInfo")
            for name in names:
                editor.set_data_value(_viewer(domain).get_behaviour_data(info, name), value)

    domain.modify("Cascadeur Complete: AutoPosing props", edit)
    data = domain.data_viewer()
    for object_id in ids:
        info = _viewer(domain).get_behaviour_by_name(object_id, "AutoPosingInfo")
        if info.is_null() or any(
            str(data.get_data_value(_viewer(domain).get_behaviour_data(info, name))) != value for name in names
        ):
            raise AssertionError("POSTCONDITION_FAILED: AutoPosing props names differ from request")
    return {"rig_element_ids": [context["id_string"](item) for item in ids], "value": value}, []


@handler("rig.clear_animation_data", postconditions=("preserved_data_empty",))
def clear_animation_data(scene, _arguments, _request, context):
    view = context["scene_view"]()
    domain = context["domain_scene"](scene)
    tool = context["csc"].app.get_application().get_tools_manager().get_tool("RiggingModeTool").editor(view)

    def clear(_model, _update, _scene, session):
        tool.erase_preserved_data(session)
        tool.erase_preserved_setting(session)

    domain.modify_with_session("Cascadeur Complete: clear additional animation data", clear)
    remaining = tool.get_preserved_data()
    if remaining:
        raise AssertionError("POSTCONDITION_FAILED: preserved animation data remains")
    return {"cleared": True}, []


@handler("rig.character_mirror_plane", postconditions=("mirror_plane_equals_request",))
def character_mirror_plane(_scene, arguments, _request, context):
    view = context["scene_view"]()
    editor = context["csc"].app.get_application().get_tools_manager().get_tool("RiggingToolWindowTool").editor(view)
    plane = int(arguments["plane"])
    if plane not in (0, 1, 2, 3):
        raise ValueError("plane must be 0 (YZ), 1 (XZ), 2 (XY) or 3 (undefined)")
    before = int(editor.get_character_mirror_plane())
    editor.set_character_mirror_plane(plane)
    observed = int(editor.get_character_mirror_plane())
    if observed != plane:
        raise AssertionError("POSTCONDITION_FAILED: character mirror plane differs from request")
    return {"before": before, "plane": observed}, []


@handler("rig.json_export", postconditions=("output_file", "nonzero_bytes"))
def rig_json_export(scene, arguments, _request, context):
    from pathlib import Path

    import pycsc
    from prototypes.json_actions import json_export

    domain = context["domain_scene"](scene)
    if not _owners(domain, "TechnicalLinks", context):
        raise ValueError("Rig JSON export needs rig element prototypes (enable Rig Mode first)")
    path = Path(str(arguments["path"]))
    view = context["scene_view"]()
    editor = context["csc"].app.get_application().get_tools_manager().get_tool("RiggingToolWindowTool").editor(view)
    json_export.create_json(
        pycsc.wrap(domain), str(path), editor.get_character_mirror_plane(), bool(editor.get_is_create_autoposing())
    )
    if not path.is_file() or path.stat().st_size <= 0:
        raise AssertionError("POSTCONDITION_FAILED: rig JSON was not written")
    return {"path": str(path), "bytes": path.stat().st_size}, []


@handler("rig.json_import", postconditions=("rig_prototypes_created_from_json",))
def rig_json_import(scene, arguments, _request, context):
    from pathlib import Path

    from prototypes.json_actions import json_import

    domain = context["domain_scene"](scene)
    path = Path(str(arguments["path"]))
    if not path.is_file():
        raise FileNotFoundError(path)
    before = _owners(domain, "TechnicalLinks", context)
    json_import.generate_proto_from_json(
        domain,
        str(path),
        str(arguments.get("selected_path", "")),
        context["csc"].rig.AddElementData().point_color,
        bool(arguments.get("set_t_pose", False)),
    )
    created = sorted(_owners(domain, "TechnicalLinks", context) - before)
    if not created:
        raise AssertionError("POSTCONDITION_FAILED: rig JSON created no rig element prototypes")
    return {"path": str(path), "created_rig_element_ids": created}, []
