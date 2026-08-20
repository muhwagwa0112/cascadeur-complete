from __future__ import annotations

from ..handler_registry import handler


@handler("timeline.range")
def select_interval(scene, arguments, _request, context):
    domain = context["domain_scene"](scene)
    viewer = domain.layers_viewer()
    first = int(arguments["first_frame"])
    last = int(arguments["last_frame"])
    if first < 0 or last < first or last >= int(viewer.frames_count()):
        raise ValueError(f"Invalid timeline interval: {first}..{last}")
    requested = [str(item) for item in arguments.get("layer_ids", [])]
    layer_ids = [context["guid"](item) for item in requested] if requested else list(viewer.all_layer_ids())
    if not layer_ids:
        raise ValueError("Timeline interval selection requires at least one animation layer")
    unknown = [context["id_string"](item) for item in layer_ids if not viewer.has_item(item)]
    if unknown:
        raise KeyError("Unknown layer IDs: " + ", ".join(unknown))

    def apply(_model, _update, _scene, session):
        session.take_layers_selector().set_full_selection_by_parts(layer_ids, first, last)

    domain.modify_with_session("Cascadeur Complete: select timeline interval", apply)
    selector = domain.get_layers_selector()
    observed_ids = {context["id_string"](item) for item in selector.all_included_layer_ids()}
    interval = selector.selection().frames_interval()
    observed_first = int(context["read_member"](interval, "first"))
    observed_last = int(context["read_member"](interval, "last"))
    expected_ids = {context["id_string"](item) for item in layer_ids}
    if observed_ids != expected_ids or observed_first != first or observed_last != last:
        raise AssertionError("POSTCONDITION_FAILED: selected timeline interval differs")
    return {
        "layer_ids": sorted(observed_ids),
        "first_frame": observed_first,
        "last_frame": observed_last,
    }, []
