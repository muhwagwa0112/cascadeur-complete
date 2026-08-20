from __future__ import annotations

import hashlib
import json

from ..handler_registry import handler


def _value_token(value):
    converter = getattr(value, "tolist", None)
    if callable(converter):
        return converter()
    quaternion = getattr(value, "to_quaternion", None)
    if callable(quaternion):
        value = quaternion()
        components = []
        for name in ("w", "x", "y", "z"):
            member = getattr(value, name, None)
            if member is None:
                break
            components.append(float(member() if callable(member) else member))
        if len(components) == 4:
            return components
    return repr(value)[:500]


def _transform_fingerprint(domain, object_ids, first, last, context):
    behaviours = domain.model_viewer().behaviour_viewer()
    data = domain.data_viewer()
    rows = []
    for object_id in object_ids:
        transform = behaviours.get_behaviour_by_name(object_id, "Transform")
        if transform.is_null():
            raise ValueError("Mirror target has no Transform behaviour: " + context["id_string"](object_id))
        properties = []
        for name in ("local_position", "local_rotation", "local_scale"):
            data_id = behaviours.get_behaviour_data(transform, name)
            if data_id.is_null():
                properties.append((name, None))
                continue
            values = []
            for frame in range(first, last + 1):
                values.append(_value_token(data.get_data_value(data_id, frame)))
            properties.append((name, values))
        rows.append((context["id_string"](object_id), properties))
    raw = json.dumps(rows, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _box_owner_ids(domain, context):
    behaviours = domain.model_viewer().behaviour_viewer()
    return {
        context["id_string"](behaviours.get_behaviour_owner(item))
        for item in behaviours.get_behaviours("BoxView")
    }


def _select_interval(domain, layer_ids, first, last, context):
    viewer = domain.layers_viewer()
    if first < 0 or last < first or last >= int(viewer.frames_count()):
        raise ValueError(f"Invalid mirror interval: {first}..{last}")
    requested = [context["guid"](item) for item in layer_ids] if layer_ids else list(viewer.all_layer_ids())
    if not requested:
        raise ValueError("Interval mirror requires at least one animation layer")
    unknown = [context["id_string"](item) for item in requested if not viewer.has_item(item)]
    if unknown:
        raise KeyError("Unknown layer IDs: " + ", ".join(unknown))

    def apply(_model, _update, _scene, session):
        session.take_layers_selector().set_full_selection_by_parts(requested, first, last)

    domain.modify_with_session("Cascadeur Complete: select mirror interval", apply)
    selector = domain.get_layers_selector()
    interval = selector.selection().frames_interval()
    observed = {
        "layer_ids": sorted(context["id_string"](item) for item in selector.all_included_layer_ids()),
        "first_frame": int(context["read_member"](interval, "first")),
        "last_frame": int(context["read_member"](interval, "last")),
    }
    expected = sorted(context["id_string"](item) for item in requested)
    if observed != {"layer_ids": expected, "first_frame": first, "last_frame": last}:
        raise AssertionError("POSTCONDITION_FAILED: mirror interval selection differs")
    return observed


@handler("editing.mirror")
def mirror(scene, arguments, _request, context):
    domain = context["domain_scene"](scene)
    model = domain.model_viewer()
    requested_ids = [str(item) for item in arguments.get("ids", [])]
    if not requested_ids:
        raise ValueError("Mirror requires at least one explicit Box controller ID")
    existing = {context["id_string"](item) for item in model.get_objects()}
    missing = sorted(set(requested_ids) - existing)
    if missing:
        raise KeyError("Unknown mirror target IDs: " + ", ".join(missing))
    non_boxes = sorted(set(requested_ids) - _box_owner_ids(domain, context))
    if non_boxes:
        raise ValueError("Mirror targets must own BoxView behaviours: " + ", ".join(non_boxes))
    object_ids = [context["object_id"](item) for item in requested_ids]

    normal = [float(item) for item in arguments.get("plane_normal", [1.0, 0.0, 0.0])]
    origin = [float(item) for item in arguments.get("plane_origin", [0.0, 0.0, 0.0])]
    if len(normal) != 3 or len(origin) != 3 or sum(item * item for item in normal) <= 1e-12:
        raise ValueError("Mirror plane requires a non-zero 3D normal and a 3D origin")
    mode = str(arguments.get("mode", "frame"))
    if mode not in ("frame", "interval"):
        raise ValueError("Mirror mode must be frame or interval")

    if mode == "frame":
        first = last = int(arguments.get("frame", domain.get_current_frame(False)))
        frames_count = int(domain.layers_viewer().frames_count())
        if first < 0 or first >= frames_count:
            raise ValueError(f"Invalid mirror frame: {first}")

        def set_frame(_model, _update, _scene, session):
            session.set_current_frame(first)

        domain.modify_with_session("Cascadeur Complete: set mirror frame", set_frame)
        interval = None
    else:
        first = int(arguments["first_frame"])
        last = int(arguments["last_frame"])
        interval = _select_interval(domain, arguments.get("layer_ids", []), first, last, context)

    before = _transform_fingerprint(domain, object_ids, first, last, context)
    app = context["csc"].app.get_application()
    core = app.get_tools_manager().get_tool("MirrorTool").editor(context["scene_view"]()).core()
    core.set_plane(context["csc"].math.Plane(normal, origin))
    if mode == "frame":
        core.mirror_frame(set(object_ids))
    else:
        core.mirror_interval(set(object_ids))
    after = _transform_fingerprint(domain, object_ids, first, last, context)
    if after == before:
        raise AssertionError("POSTCONDITION_FAILED: Mirror produced no observable target transform change")

    return {
        "mode": mode,
        "ids": sorted(set(requested_ids)),
        "plane_normal": normal,
        "plane_origin": origin,
        "frame": first if mode == "frame" else None,
        "interval": interval,
        "before_fingerprint": before,
        "after_fingerprint": after,
        "execution": "csc.tools.MirrorTool.editor(scene).core() verified native adapter",
    }, []
