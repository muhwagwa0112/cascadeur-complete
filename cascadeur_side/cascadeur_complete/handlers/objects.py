from __future__ import annotations

from contextlib import suppress

from ..handler_registry import handler


def _parent_id(behaviour_viewer, object_id, context):
    basic = behaviour_viewer.get_behaviour_by_name(object_id, "Basic")
    if basic.is_null():
        return None
    parent = behaviour_viewer.get_behaviour_object(basic, "parent")
    return None if parent.is_null() else context["id_string"](parent)


def _hierarchy(domain, context):
    viewer = domain.model_viewer()
    behaviour_viewer = viewer.behaviour_viewer()
    rows = []
    children = {}
    for object_id in viewer.get_objects():
        object_id_text = context["id_string"](object_id)
        parent = _parent_id(behaviour_viewer, object_id, context)
        row = {
            "id": object_id_text,
            "name": str(viewer.get_object_name(object_id)),
            "type": str(viewer.get_object_type_name(object_id)),
            "parent_id": parent,
        }
        rows.append(row)
        children.setdefault(parent, []).append(object_id_text)
    for row in rows:
        row["children"] = sorted(children.get(row["id"], []))
    return sorted(rows, key=lambda item: item["id"])


def _property_value(behaviour_viewer, behaviour_id, property_name, property_type, context):
    suffixes = {
        "DataType": "data",
        "DataRangeType": "data_range",
        "SettingType": "setting",
        "SettingRangeType": "settings_range",
        "ObjectType": "object",
        "ObjectRangeType": "objects_range",
        "BehaviourType": "reference",
        "BehaviourRangeType": "reference_range",
        "AssetType": "asset",
        "AssetRangeType": "asset_range",
        "StringType": "string",
    }
    suffix = suffixes.get(property_type)
    if suffix is None:
        return None
    getter = getattr(behaviour_viewer, "get_behaviour_" + suffix, None)
    if not callable(getter):
        return None
    try:
        return context["json_safe"](getter(behaviour_id, property_name))
    except Exception as exc:
        return {"unreadable": True, "error": str(exc)}


@handler("object.hierarchy")
def hierarchy(scene, _arguments, _request, context):
    domain = context["domain_scene"](scene)
    rows = _hierarchy(domain, context)
    roots = [item["id"] for item in rows if item["parent_id"] is None]
    return {"roots": roots, "items": rows}, []


@handler("object.properties", "object.behaviors")
def object_details(scene, arguments, request, context):
    domain = context["domain_scene"](scene)
    viewer = domain.model_viewer()
    behaviour_viewer = viewer.behaviour_viewer()
    state = context["scene_state"](scene)
    known_ids = {item["id"] for item in state["objects"]}
    requested = [str(item) for item in arguments.get("ids", [])] or sorted(known_ids)
    unknown = sorted(set(requested) - known_ids)
    if unknown:
        raise KeyError("Unknown object IDs: " + ", ".join(unknown))
    layer_by_object = {}
    with suppress(Exception):
        layers_viewer = domain.layers_viewer()
        for raw_id in requested:
            layer_id = layers_viewer.layer_id_by_obj_id_or_null(context["object_id"](raw_id))
            layer_by_object[raw_id] = None if layer_id.is_null() else context["id_string"](layer_id)
    include_values = bool(arguments.get("include_values", False))
    rows = []
    hierarchy_by_id = {item["id"]: item for item in _hierarchy(domain, context)}
    for raw_id in requested:
        object_id = context["object_id"](raw_id)
        item = dict(hierarchy_by_id[raw_id])
        item["layer_id"] = layer_by_object.get(raw_id)
        behaviours = []
        for behaviour_id in behaviour_viewer.get_behaviours(object_id):
            behaviour = {
                "id": context["id_string"](behaviour_id),
                "name": str(behaviour_viewer.get_behaviour_name(behaviour_id)),
                "hidden": bool(behaviour_viewer.is_hidden(behaviour_id)),
            }
            properties = []
            for property_name in behaviour_viewer.get_behaviour_property_names(behaviour_id):
                property_type = behaviour_viewer.get_property_type(behaviour_id, property_name)
                property_type_name = str(context["read_member"](property_type, "name"))
                property_row = {"name": str(property_name), "type": property_type_name}
                if include_values:
                    property_row["value"] = _property_value(
                        behaviour_viewer,
                        behaviour_id,
                        property_name,
                        property_type_name,
                        context,
                    )
                properties.append(property_row)
            behaviour["properties"] = properties
            behaviours.append(behaviour)
        item["behaviors"] = behaviours
        rows.append(item)
    return {"items": rows, "include_values": include_values, "operation": request.get("feature_id")}, []


@handler("object.rename")
def rename_object(scene, arguments, _request, context):
    domain = context["domain_scene"](scene)
    object_id = context["object_id"](arguments["id"])
    requested_name = str(arguments["name"])

    def rename(model, _update, _scene_updater):
        model.set_object_name(object_id, requested_name)

    domain.modify("Cascadeur Complete: rename object", rename)
    observed = str(domain.model_viewer().get_object_name(object_id))
    if observed != requested_name:
        raise AssertionError("POSTCONDITION_FAILED: object name differs")
    return {"id": str(arguments["id"]), "name": observed}, []


@handler("object.parent", "object.unparent")
def reparent_objects(scene, arguments, _request, context):
    import common.hierarchy as hierarchy

    domain = context["domain_scene"](scene)
    children = [context["object_id"](item) for item in arguments.get("ids", [])]
    if not children:
        raise ValueError("At least one child object ID is required")
    parent = (
        context["object_id"](arguments["parent_id"])
        if arguments.get("parent_id")
        else context["csc"].model.ObjectId.null()
    )
    hierarchy.set_parent_mod(domain, children, parent)
    behaviour_viewer = domain.behaviour_viewer()
    expected = None if parent.is_null() else context["id_string"](parent)
    observed = {context["id_string"](item): _parent_id(behaviour_viewer, item, context) for item in children}
    if any(value != expected for value in observed.values()):
        raise AssertionError("POSTCONDITION_FAILED: object parent differs")
    return {"parent_id": expected, "objects": observed}, []


@handler("object.create")
def create_object(scene, arguments, _request, context):
    import samples.model_cube as model_cube

    domain = context["domain_scene"](scene)
    before = {context["id_string"](item) for item in domain.model_viewer().get_objects()}
    parent = (
        context["object_id"](arguments["parent_id"])
        if arguments.get("parent_id")
        else context["csc"].model.ObjectId.null()
    )
    position = tuple(float(item) for item in arguments.get("position", (0.0, 0.0, 0.0)))
    if len(position) != 3:
        raise ValueError("position must contain exactly three numbers")
    object_id = model_cube.create_and_add_cube(
        domain,
        parent,
        position,
        context["csc"].math.Rotation(),
        str(arguments.get("name", "Cube")),
        float(arguments.get("size", 3.0)),
    )
    observed_id = context["id_string"](object_id)
    after = {context["id_string"](item) for item in domain.model_viewer().get_objects()}
    if observed_id not in after or after == before:
        raise AssertionError("POSTCONDITION_FAILED: object was not created")
    return {"id": observed_id, "name": str(domain.model_viewer().get_object_name(object_id))}, []
