from __future__ import annotations

from ..handler_registry import handler, transact


def _enum_name(value, context):
    return str(context["read_member"](value, "name"))


def _section_row(layer_id, frame, section, context):
    interval = context["read_member"](section, "interval")
    key = context["read_member"](section, "key")
    interval_common = context["read_member"](interval, "common")
    key_common = context["read_member"](key, "common")
    return {
        "layer_id": context["id_string"](layer_id),
        "frame": int(frame),
        "interpolation": _enum_name(context["read_member"](interval, "interpolation"), context),
        "tangents": _enum_name(context["read_member"](key, "tangents"), context),
        "interval": {
            "ik_fk": _enum_name(context["read_member"](interval_common, "ik_fk"), context),
            "fixation": _enum_name(context["read_member"](interval_common, "fixation"), context),
        },
        "key": {
            "ik_fk": _enum_name(context["read_member"](key_common, "ik_fk"), context),
            "fixation": _enum_name(context["read_member"](key_common, "fixation"), context),
            "label": context["json_safe"](context["read_member"](key, "label")),
        },
    }


def _sections(domain, arguments, context):
    viewer = domain.layers_viewer()
    requested = [str(item) for item in arguments.get("layer_ids", [])]
    layer_ids = [context["guid"](item) for item in requested] if requested else list(viewer.all_layer_ids())
    first = arguments.get("first_frame")
    last = arguments.get("last_frame")
    rows = []
    for layer_id in layer_ids:
        if not viewer.has_item(layer_id):
            raise KeyError("Unknown layer ID: " + context["id_string"](layer_id))
        layer = viewer.layer(layer_id)
        sections = context["read_member"](layer, "sections")
        for frame, section in sections.items():
            if first is not None and int(frame) < int(first):
                continue
            if last is not None and int(frame) > int(last):
                continue
            rows.append(_section_row(layer_id, frame, section, context))
    return sorted(rows, key=lambda item: (item["layer_id"], item["frame"]))


def _cycle_row(cycle):
    return {
        "first_active_frame": int(cycle.first_active_frame_index),
        "last_active_frame": int(cycle.last_active_frame_index),
        "left_inactive_frame": int(cycle.left_inactive_frame_index),
        "right_inactive_frame": int(cycle.right_inactive_frame_index),
        "following_interval": int(cycle.following_interval),
        "left_frame": int(cycle.left_frame_index()),
        "right_frame": int(cycle.right_frame_index()),
    }


def _cycles(domain, layer_ids, first, last, context):
    viewer = domain.layers_viewer()
    rows = []
    for layer_id in layer_ids:
        cycles_viewer = context["csc"].layers.CyclesViewer(viewer.layer(layer_id))
        seen = set()
        for cycle in cycles_viewer.get_cycles_in_frames(first, last):
            row = _cycle_row(cycle)
            identity = tuple(row.values())
            if identity in seen:
                continue
            seen.add(identity)
            rows.append({"layer_id": context["id_string"](layer_id), **row})
    return sorted(rows, key=lambda item: (item["layer_id"], item["left_frame"], item["right_frame"]))


def _cycle_layers(domain, requested, context):
    viewer = domain.layers_viewer()
    layer_ids = [context["guid"](item) for item in requested] if requested else list(viewer.all_layer_ids())
    if not layer_ids:
        raise ValueError("Cycle operation requires at least one animation layer")
    unknown = [context["id_string"](item) for item in layer_ids if not viewer.has_item(item)]
    if unknown:
        raise KeyError("Unknown layer IDs: " + ", ".join(unknown))
    return layer_ids


@handler("animation.cycle_query", postconditions=("normalized_cycle_catalog",))
def cycle_query(scene, arguments, _request, context):
    domain = context["domain_scene"](scene)
    viewer = domain.layers_viewer()
    frames_count = int(viewer.frames_count())
    action = str(arguments.get("action", "list"))
    if action != "list":
        raise ValueError("animation.cycle_query only supports list")
    layer_ids = _cycle_layers(domain, arguments.get("layer_ids", []), context)
    first = int(arguments.get("first_frame", 0))
    last = int(arguments.get("last_frame", frames_count - 1))
    if first < 0 or last < first or last >= frames_count:
        raise ValueError(f"Invalid cycle query interval: {first}..{last}")
    rows = _cycles(domain, layer_ids, first, last, context)
    return {"cycles": rows, "count": len(rows), "first_frame": first, "last_frame": last}, []


@handler("animation.graph_query", postconditions=("section_payload",))
def graph_query(scene, arguments, _request, context):
    domain = context["domain_scene"](scene)
    rows = _sections(domain, arguments, context)
    return {"sections": rows, "count": len(rows)}, []


@handler(
    "animation.interpolation_set",
    "animation.tangent_set",
    postconditions={
        "animation.interpolation_set": ("interpolation_equals_requested",),
        "animation.tangent_set": ("tangent_mode_equals_requested",),
    },
)
def edit_section(scene, arguments, request, context):
    domain = context["domain_scene"](scene)
    layer_id = context["guid"](arguments["layer_id"])
    frame = int(arguments["frame"])
    operation = str(arguments["operation"])
    bound = {"animation.interpolation_set": "interpolation", "animation.tangent_set": "tangent"}.get(
        str((request.get("operations") or [{}])[0].get("name", ""))
    )
    if bound is not None and operation != bound:
        raise ValueError("operation argument " + operation + " does not match the requested bridge operation")
    requested = str(arguments["value"])
    if operation == "interpolation":
        enum_class = context["csc"].layers.layer.Interpolation
        attribute = "interpolation"
    elif operation == "tangent":
        enum_class = context["csc"].layers.layer.Tangents
        attribute = "tangents"
    else:
        raise ValueError("Unsupported section operation: " + operation)
    try:
        enum_name = next(name for name in dir(enum_class) if name.casefold() == requested.casefold())
        enum_value = getattr(enum_class, enum_name)
    except (AttributeError, StopIteration) as exc:
        allowed = [name for name in dir(enum_class) if not name.startswith("_") and name[:1].isupper()]
        raise ValueError("Unsupported value. Expected one of: " + ", ".join(allowed)) from exc

    def edit(model, _update, _scene_updater):
        def modify(section):
            target = section.interval if operation == "interpolation" else section.key
            setattr(target, attribute, enum_value)

        model.layers_editor().change_section(frame, layer_id, modify)

    transact(domain.modify, "Cascadeur Complete: set " + operation, edit)
    rows = _sections(domain, {"layer_ids": [str(arguments["layer_id"])]}, context)
    observed = next((item for item in rows if item["frame"] == frame), None)
    expected = _enum_name(enum_value, context)
    actual = observed["interpolation" if operation == "interpolation" else "tangents"] if observed else None
    if actual != expected:
        raise AssertionError("POSTCONDITION_FAILED: section value differs")
    return observed, []


@handler("animation.key_reduce", postconditions=("observed_keys_equal_reduction_plan",))
def key_reduce(scene, arguments, _request, context):
    domain = context["domain_scene"](scene)
    viewer = domain.layers_viewer()
    every_n = int(arguments.get("every_n", 2))
    if every_n <= 0:
        raise ValueError("every_n must be a positive integer")
    first = int(arguments["first_frame"])
    last = int(arguments["last_frame"])
    if first < 0 or last < first or last >= int(viewer.frames_count()):
        raise ValueError(f"Invalid key reduction interval: {first}..{last}")
    requested = [str(item) for item in arguments.get("layer_ids", [])]
    layer_ids = [context["guid"](item) for item in requested] if requested else list(viewer.all_layer_ids())
    if not layer_ids:
        raise ValueError("Key reduction requires at least one animation layer")
    unknown = [context["id_string"](item) for item in layer_ids if not viewer.has_item(item)]
    if unknown:
        raise KeyError("Unknown layer IDs: " + ", ".join(unknown))
    preserve_endpoints = bool(arguments.get("preserve_endpoints", True))
    fixed_interpolation = bool(arguments.get("fixed_interpolation", False))
    before = {}
    expected = {}
    for layer_id in layer_ids:
        key_frames = [int(frame) for frame in viewer.layer(layer_id).key_frame_indices() if first <= int(frame) <= last]
        layer_text = context["id_string"](layer_id)
        before[layer_text] = key_frames
        preserved = set(key_frames[::every_n])
        if preserve_endpoints and key_frames:
            preserved.update((key_frames[0], key_frames[-1]))
        expected[layer_text] = sorted(preserved)

    def reduce(model, _update, _scene_updater):
        editor = model.layers_editor()

        def set_fixed(section):
            section.interval.interpolation = context["csc"].layers.layer.Interpolation.FIXED

        for layer_id in layer_ids:
            layer_text = context["id_string"](layer_id)
            preserved = set(expected[layer_text])
            layer_keys = before[layer_text]
            for frame in layer_keys:
                if frame not in preserved:
                    editor.unset_section(frame, layer_id)
                elif fixed_interpolation and frame != layer_keys[-1]:
                    editor.change_section(frame, layer_id, set_fixed)

    transact(domain.modify, "Cascadeur Complete: reduce keyframes", reduce)
    observed = {}
    for layer_id in layer_ids:
        layer_text = context["id_string"](layer_id)
        observed[layer_text] = sorted(
            int(frame)
            for frame in domain.layers_viewer().layer(layer_id).key_frame_indices()
            if first <= int(frame) <= last
        )
        if observed[layer_text] != expected[layer_text]:
            raise AssertionError("POSTCONDITION_FAILED: reduced key set differs for layer " + layer_text)
    removed = {layer_id: sorted(set(before[layer_id]) - set(observed[layer_id])) for layer_id in observed}
    return {
        "first_frame": first,
        "last_frame": last,
        "every_n": every_n,
        "preserve_endpoints": preserve_endpoints,
        "fixed_interpolation": fixed_interpolation,
        "before_keys": before,
        "after_keys": observed,
        "removed_keys": removed,
        "removed_count": sum(len(items) for items in removed.values()),
        "execution": "commands.animation_scripts.keyframe_reduction verified direct implementation",
    }, []


def rotation_from_euler_xyz(csc, euler):
    """Build a Rotation from the euler_xyz_radians that transform reads return.

    Reads use Rotation.to_euler_angles_x_y_z; its inverse is
    euler_angles_to_quaternion_x_y_z. Rotation.from_euler uses a different
    convention, so feeding a read value back through it produced a different
    rotation (tens of degrees off on finger controllers).
    """
    import numpy

    converter = getattr(csc.math, "euler_angles_to_quaternion_x_y_z", None)
    if converter is None:
        return csc.math.Rotation.from_euler(*euler)
    quaternion = converter(numpy.array([float(value) for value in euler], dtype=numpy.float32))
    return csc.math.Rotation.from_quaternion(quaternion)


MAX_ROTATION_KEY_WRITES = 20000


@handler("animation.rotation_keys_set", postconditions=("rotation_keys_equal_request",))
def rotation_keys_set(scene, arguments, _request, context):
    """Rewrite rotations (local or global) at existing keys for many objects in one transaction.

    Pose polish (e.g. limiting mocap finger spread) touches thousands of
    (controller, key) pairs; one protected transform_set per pair is
    impractical. Only existing keys on each object's own layer are rewritten,
    so the key structure and interpolation are unchanged. Every write is read
    back and must match the requested rotation.
    """
    from ..runtime import _quaternion_list, _read_transforms, _transform_data_ids

    csc = context["csc"]
    domain = context["domain_scene"](scene)
    writes = list(arguments.get("writes") or [])
    space = str(arguments.get("space", "local"))
    if space not in ("local", "global"):
        raise ValueError("space must be local or global")
    if not writes:
        raise ValueError("writes must be a non-empty list of {id, frame, rotation_euler_xyz_radians}")
    if len(writes) > MAX_ROTATION_KEY_WRITES:
        raise ValueError(f"At most {MAX_ROTATION_KEY_WRITES} writes per call")
    layers_viewer = domain.layers_viewer()
    targets = {}
    by_frame = {}
    for item in writes:
        raw_id = str(item["id"])
        frame = int(item["frame"])
        euler = [float(value) for value in item["rotation_euler_xyz_radians"]]
        if len(euler) != 3:
            raise ValueError("rotation_euler_xyz_radians must contain exactly three numbers")
        if raw_id not in targets:
            object_id = context["object_id"](raw_id)
            data_ids = _transform_data_ids(domain, object_id, space)
            if data_ids is None or data_ids["rotation"].is_null():
                raise ValueError(f"Object has no {space} rotation data: " + raw_id)
            layer = layers_viewer.layer(layers_viewer.layer_id_by_obj_id(object_id))
            targets[raw_id] = (data_ids["rotation"], {int(key) for key in layer.key_frame_indices()})
        if frame not in targets[raw_id][1]:
            raise ValueError(f"{raw_id} has no key at frame {frame}; only existing keys are rewritten")
        by_frame.setdefault(frame, []).append((raw_id, euler))

    node_name = "Local Rotation" if space == "local" else "Global Rotation"

    def edit(model, update, scene_updater):
        # Write through the object's update-graph node, as Cascadeur's own
        # animation tools (ml/editable_animation.py) do; fall back to the
        # Transform data. Whether a rig re-solves the value afterwards is
        # checked by the host's settled read-back, not here.
        editor = model.data_editor()
        nodes = {}
        for raw_id in targets:
            node = None
            try:
                node = update.get_object_by_id(context["object_id"](raw_id)).root_group().node_deep(node_name)
            except Exception:
                node = None
            nodes[raw_id] = node
        for frame in sorted(by_frame):
            changed = set()
            for raw_id, euler in by_frame[frame]:
                rotation = rotation_from_euler_xyz(csc, euler)
                node = nodes[raw_id]
                if node is not None:
                    node.set_value(rotation, frame)
                    changed.add(node.data_id())
                else:
                    data_id = targets[raw_id][0]
                    editor.set_data_value(data_id, frame, rotation)
                    changed.add(data_id)
            scene_updater.run_update(changed, frame)

    transact(domain.modify_update, "Cascadeur Complete: set rotation keys", edit)
    refresh_interpolation(domain)
    worst = 0.0
    for frame, items in by_frame.items():
        observed = {row["id"]: row for row in _read_transforms(domain, [raw for raw, _ in items], frame, space)}
        for raw_id, euler in items:
            expected = _quaternion_list(rotation_from_euler_xyz(csc, euler))
            actual = observed[str(raw_id)]["rotation"]["quaternion_wxyz"]
            error = abs(1.0 - abs(sum(a * b for a, b in zip(expected, actual, strict=True))))
            worst = max(worst, error)
            if error > 1e-4:
                raise AssertionError(f"POSTCONDITION_FAILED: rotation differs for {raw_id} at frame {frame}")
    return {
        "space": space,
        "write_count": len(writes),
        "object_count": len(targets),
        "frame_count": len(by_frame),
        "max_quaternion_error": worst,
    }, []


def refresh_interpolation(domain):
    """Recompute interpolated frames for the whole timeline.

    Cascadeur only re-interpolates from frame 0 up to the playhead after an
    edit, so frames past it keep stale values until the playhead reaches them.
    """

    def refresh(_model, _update, scene_updater):
        interpolator = scene_updater.get_interpolator()
        interpolator.reload()
        interpolator.interpolate()

    transact(domain.modify_update, "Cascadeur Complete: refresh interpolation", refresh)


@handler("animation.interpolation_refresh", postconditions=("interpolation_refreshed",))
def interpolation_refresh(scene, _arguments, _request, context):
    import time

    started = time.monotonic()
    refresh_interpolation(context["domain_scene"](scene))
    return {"duration_ms": int((time.monotonic() - started) * 1000)}, []


@handler("animation.position_keys_set", postconditions=("position_keys_equal_request",))
def position_keys_set(scene, arguments, _request, context):
    """Rewrite positions at existing keys for many objects in one transaction.

    Used for contact cleanup (pinning a sliding foot's points in place): only
    existing keys on each object's own layer are rewritten, through the
    update-graph position node when the object has one. Every write is read
    back; the host re-reads a sample in a separate request as well.
    """
    from ..runtime import _read_transforms, _transform_data_ids

    domain = context["domain_scene"](scene)
    writes = list(arguments.get("writes") or [])
    space = str(arguments.get("space", "global"))
    if space not in ("local", "global"):
        raise ValueError("space must be local or global")
    # Rig constraints (IK limb lengths) may trim a requested position slightly;
    # callers that move whole limbs pass an explicit, bounded tolerance.
    tolerance = float(arguments.get("tolerance_cm", 0.05))
    if not 0.0 < tolerance <= 5.0:
        raise ValueError("tolerance_cm must be in (0, 5]")
    if not writes:
        raise ValueError("writes must be a non-empty list of {id, frame, position}")
    if len(writes) > MAX_ROTATION_KEY_WRITES:
        raise ValueError(f"At most {MAX_ROTATION_KEY_WRITES} writes per call")
    layers_viewer = domain.layers_viewer()
    targets = {}
    by_frame = {}
    for item in writes:
        raw_id = str(item["id"])
        frame = int(item["frame"])
        position = [float(value) for value in item["position"]]
        if len(position) != 3:
            raise ValueError("position must contain exactly three numbers")
        if raw_id not in targets:
            object_id = context["object_id"](raw_id)
            data_ids = _transform_data_ids(domain, object_id, space)
            if data_ids is None or data_ids["position"].is_null():
                raise ValueError(f"Object has no {space} position data: " + raw_id)
            layer = layers_viewer.layer(layers_viewer.layer_id_by_obj_id(object_id))
            targets[raw_id] = (data_ids["position"], {int(key) for key in layer.key_frame_indices()})
        if frame not in targets[raw_id][1]:
            raise ValueError(f"{raw_id} has no key at frame {frame}; only existing keys are rewritten")
        by_frame.setdefault(frame, []).append((raw_id, position))
    node_names = ("Global Position", "Position") if space == "global" else ("Local Position", "Position")

    def edit(model, update, scene_updater):
        import numpy

        editor = model.data_editor()
        nodes = {}
        for raw_id in targets:
            nodes[raw_id] = None
            for node_name in node_names:
                try:
                    node = update.get_object_by_id(context["object_id"](raw_id)).root_group().node_deep(node_name)
                except Exception:
                    node = None
                if node is not None:
                    nodes[raw_id] = node
                    break
        for frame in sorted(by_frame):
            changed = set()
            for raw_id, position in by_frame[frame]:
                value = numpy.array(position, dtype=numpy.float32)
                node = nodes[raw_id]
                if node is not None:
                    node.set_value(value, frame)
                    changed.add(node.data_id())
                else:
                    data_id = targets[raw_id][0]
                    editor.set_data_value(data_id, frame, value)
                    changed.add(data_id)
            scene_updater.run_update(changed, frame)

    transact(domain.modify_update, "Cascadeur Complete: set position keys", edit)
    refresh_interpolation(domain)
    worst = 0.0
    mismatched = {}
    adjusted = {}
    for frame, items in by_frame.items():
        observed = {row["id"]: row for row in _read_transforms(domain, [raw for raw, _ in items], frame, space)}
        for raw_id, position in items:
            actual = observed[str(raw_id)]["position"]
            error = max(abs(a - b) for a, b in zip(actual, position, strict=True))
            worst = max(worst, error)
            if error > 0.01:
                adjusted[raw_id] = max(adjusted.get(raw_id, 0.0), error)
            if error > tolerance:
                mismatched[raw_id] = max(mismatched.get(raw_id, 0.0), error)
    if mismatched:
        # Rig-derived points (e.g. direction points) are recomputed from their
        # drivers; report every one so the caller can drop them from the plan.
        detail = ", ".join(f"{key} ({value:.2f})" for key, value in sorted(mismatched.items()))
        raise AssertionError(f"POSTCONDITION_FAILED: position differs for {len(mismatched)} object(s): {detail}")
    return {
        "space": space,
        "write_count": len(writes),
        "object_count": len(targets),
        "frame_count": len(by_frame),
        "max_position_error": worst,
        "tolerance_cm": tolerance,
        "adjusted_by_rig": {key: round(value, 3) for key, value in sorted(adjusted.items())},
    }, []
