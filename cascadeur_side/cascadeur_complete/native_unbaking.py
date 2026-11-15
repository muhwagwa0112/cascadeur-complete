"""Exact unbaking scope and topology bounds, never native completion proof.

The opaque actions remain unqualified. A projection taken after call_action
returns can reject a visible scope violation, but cannot close an async action.
This module does not register an adapter or turn its observation into success.
"""
from __future__ import annotations

import bisect

from . import guarded_runtime as guards

STEPS = frozenset({"prepare_keys_by_fulcrums", "adjust_keys_and_interpolation", "adjust_autoposing_lock_state"})
POLICY_FIELDS = frozenset({"allow_key_insertion", "allow_interpolation_change", "maximum_added_keys",
                           "maximum_removed_keys", "maximum_written_keys"})
ARGUMENT_FIELDS = frozenset({"step", "object_ids", "layer_ids", "first_frame", "last_frame", "topology_policy"})


def validate_arguments(arguments):
    if (not isinstance(arguments, dict) or set(arguments) != ARGUMENT_FIELDS
            or not isinstance(arguments["step"], str) or arguments["step"] not in STEPS):
        raise ValueError("INVALID_WRITE_SCOPE: exact unbaking target, step and topology policy required")
    for name in ("object_ids", "layer_ids"):
        values = arguments[name]
        if (not isinstance(values, list) or not values
                or any(not isinstance(value, str) or not value for value in values) or len(set(values)) != len(values)):
            raise ValueError("INVALID_WRITE_SCOPE: unique nonempty explicit " + name + " required")
    first, last = arguments["first_frame"], arguments["last_frame"]
    if type(first) is not int or type(last) is not int or not 0 <= first < last:
        raise ValueError("INVALID_WRITE_SCOPE: increasing nonnegative integer unbaking interval required")
    policy = arguments["topology_policy"]
    if (not isinstance(policy, dict) or set(policy) != POLICY_FIELDS
            or any(type(policy[name]) is not bool for name in ("allow_key_insertion", "allow_interpolation_change"))
            or any(type(policy[name]) is not int or policy[name] < 0 for name in POLICY_FIELDS - {
                "allow_key_insertion", "allow_interpolation_change"})
            or policy["maximum_added_keys"] + policy["maximum_removed_keys"] > policy["maximum_written_keys"]
            or (policy["maximum_added_keys"] and not policy["allow_key_insertion"])):
        raise ValueError("INVALID_POLICY: explicit finite unbaking key bounds and strict opt-ins required")
    return policy


def _indexed(rows, name):
    kind = int if name == "frame" else str
    if (not isinstance(rows, list) or any(not isinstance(row, dict) or type(row.get(name)) is not kind for row in rows)):
        raise ValueError("INCOMPLETE_CAPTURE: unbaking projection lacks " + name)
    result = {row[name]: row for row in rows}
    if len(result) != len(rows):
        raise ValueError("INCOMPLETE_CAPTURE: duplicate unbaking projection identity")
    return result


def _topology(projection, arguments):
    if not isinstance(projection, dict) or type(projection.get("frames")) is not int:
        raise ValueError("INCOMPLETE_CAPTURE: full native unbaking projection required")
    if arguments["last_frame"] >= projection["frames"]:
        raise ValueError("INVALID_WRITE_SCOPE: unbaking interval exceeds native scene")
    layers = _indexed(projection["layers"], "id")
    objects = _indexed(projection["objects"], "id")
    selected = set(arguments["layer_ids"])
    if not selected <= set(layers) or not set(arguments["object_ids"]) <= set(objects):
        raise ValueError("INVALID_WRITE_SCOPE: unbaking target is absent from native projection")
    owners = {}
    for identifier in selected:
        layer = layers[identifier]
        if layer.get("locked") is not False or layer.get("visible") is not True:
            raise ValueError("INVALID_WRITE_SCOPE: unbaking layers must be visible and unlocked")
        ids = layer.get("object_ids")
        keys = layer.get("keys")
        if (not isinstance(ids, list) or any(type(item) is not str for item in ids) or len(set(ids)) != len(ids)
                or not isinstance(keys, list) or any(type(frame) is not int or not 0 <= frame < projection["frames"] for frame in keys)
                or keys != sorted(set(keys))):
            raise ValueError("INCOMPLETE_CAPTURE: exact layer ownership and authored keys required")
        for key in ids:
            if key in owners:
                raise ValueError("INVALID_WRITE_SCOPE: shared owning layers are outside unbaking scope")
            owners[key] = identifier
        sections = _indexed(layer["sections"], "frame")
        if (not set(keys) <= set(sections) or any(type(frame) is not int or not 0 <= frame < projection["frames"] for frame in sections)):
            raise ValueError("INCOMPLETE_CAPTURE: complete native key/section map required")
    if set(owners) != set(arguments["object_ids"]):
        raise ValueError("INVALID_WRITE_SCOPE: objects must equal the complete selected layer ownership")
    # The SDK algorithm can expand RigInfo/child-layer selection. It cannot
    # acquire permission for an object already owned by another layer here.
    if any(set(layer.get("object_ids", ())) & set(owners) for identifier, layer in layers.items() if identifier not in selected):
        raise ValueError("INVALID_WRITE_SCOPE: unbaking ownership escapes selected layers")
    return layers, owners


def capture_before(scene, arguments):
    validate_arguments(arguments)
    projection = _read_projection(scene)
    _topology(projection, arguments)
    return projection


def _read_projection(scene):
    import csc.layers.layer
    from .native_scene_reader import native_value, read_scene
    projection = read_scene(scene)
    # The full reader preserves raw label IDs. SDK no_label_id may be an int
    # or Guid rather than None; canonicalize that actual sentinel only here.
    no_label = native_value(csc.layers.layer.Key.no_label_id())
    for layer in projection["layers"]:
        for section in layer["sections"]:
            if section["label"] == no_label:
                section["label"] = None
    return projection


def compare_projections(before, after, arguments):
    """Reject visible out-of-scope effects; do not infer action completion.

    Written keys count the union of added/removed/changed section locators and
    the authored key controlling any changed animation sample. This counts a
    layer/frame once even when several owned channels change at that locator.
    It is a conservative accounting of observed effects, not an SDK call count.
    """
    policy = validate_arguments(arguments)
    before_layers, owners = _topology(before, arguments)
    after_layers, after_owners = _topology(after, arguments)
    mutable = {"layers", "data", "settings"}
    if (set(before) != set(after) or owners != after_owners or set(before_layers) != set(after_layers)
            or any(before[name] != after[name] for name in set(before) - mutable)):
        raise ValueError("UNBAKING_SCOPE_VIOLATION: native scene structure or non-animation content changed")
    first, last = arguments["first_frame"], arguments["last_frame"]
    target_layers = set(arguments["layer_ids"])
    added, removed, written = set(), set(), set()
    for identifier, old_layer in before_layers.items():
        new_layer = after_layers[identifier]
        if identifier not in target_layers:
            if old_layer != new_layer:
                raise ValueError("UNBAKING_SCOPE_VIOLATION: non-target layer changed")
            continue
        if ({key: value for key, value in old_layer.items() if key not in {"keys", "sections"}}
                != {key: value for key, value in new_layer.items() if key not in {"keys", "sections"}}):
            raise ValueError("UNBAKING_SCOPE_VIOLATION: target layer identity or ownership changed")
        old_keys, new_keys = set(old_layer["keys"]), set(new_layer["keys"])
        added.update((identifier, frame) for frame in new_keys - old_keys)
        removed.update((identifier, frame) for frame in old_keys - new_keys)
        old_sections, new_sections = _indexed(old_layer["sections"], "frame"), _indexed(new_layer["sections"], "frame")
        for frame in set(old_sections) | set(new_sections):
            old, new = old_sections.get(frame), new_sections.get(frame)
            if old == new:
                continue
            if not first <= frame <= last:
                raise ValueError("UNBAKING_SCOPE_VIOLATION: section changed outside approved interval")
            if old is not None and old.get("label") is not None:
                raise ValueError("UNBAKING_SCOPE_VIOLATION: labeled original section changed")
            if new is not None and old is None and new.get("label") is not None:
                raise ValueError("UNBAKING_SCOPE_VIOLATION: new labeled section is not authorized")
            if old is None and new is not None and not policy["allow_interpolation_change"]:
                previous = [key for key in old_sections if key <= frame]
                if not previous:
                    raise ValueError("UNBAKING_SCOPE_VIOLATION: new section has no original interpolation")
                original = old_sections[max(previous)]
                if any(original[name] != new[name] for name in (
                        "interpolation", "tangents", "left_weight_velocity", "right_weight_velocity")):
                    raise ValueError("UNBAKING_SCOPE_VIOLATION: new section changes original interpolation")
            if (old is not None and new is None and arguments["step"] != "adjust_autoposing_lock_state"
                    and any(old[name].get("fixation") != "Free" for name in ("key_common", "interval_common"))):
                raise ValueError("UNBAKING_SCOPE_VIOLATION: fixed original section cannot be removed")
            if old is not None and new is not None:
                permitted = {"interpolation", "tangents", "left_weight_velocity", "right_weight_velocity"} if policy["allow_interpolation_change"] else set()
                permitted.add("key_common")
                permitted.add("interval_common")
                if ({key: value for key, value in old.items() if key not in permitted}
                        != {key: value for key, value in new.items() if key not in permitted}):
                    raise ValueError("UNBAKING_SCOPE_VIOLATION: protected section metadata changed")
                for name in ("key_common", "interval_common"):
                    original_common, actual_common = old[name], new[name]
                    allowed = {"ik_fk"} if policy["allow_interpolation_change"] else set()
                    if arguments["step"] == "adjust_autoposing_lock_state":
                        allowed.add("fixation")
                    if ({key: value for key, value in original_common.items() if key not in allowed}
                            != {key: value for key, value in actual_common.items() if key not in allowed}):
                        raise ValueError("UNBAKING_SCOPE_VIOLATION: protected key/interval state changed")
            written.add((identifier, frame))
    written.update(added | removed)
    if any(not first <= frame <= last for _, frame in added | removed):
        raise ValueError("UNBAKING_SCOPE_VIOLATION: authored key changed outside approved interval")
    changed_references = {"data": set(), "settings": set()}
    for field in ("data", "settings"):
        old_rows, new_rows = _indexed(before[field], "id"), _indexed(after[field], "id")
        if set(old_rows) != set(new_rows):
            raise ValueError("UNBAKING_SCOPE_VIOLATION: native data/settings identities changed")
        for identifier, old in old_rows.items():
            new = new_rows[identifier]
            if old == new:
                continue
            if (old.get("owner") not in owners or old.get("mode") != "Animation"
                    or {key: value for key, value in old.items() if key != "values"}
                        != {key: value for key, value in new.items() if key != "values"}
                    or len(old["values"]) != before["frames"] or len(new["values"]) != after["frames"]):
                raise ValueError("UNBAKING_SCOPE_VIOLATION: static or non-target data/settings changed")
            layer_id = owners[old["owner"]]
            keys = sorted(set(before_layers[layer_id]["keys"]) | set(after_layers[layer_id]["keys"]))
            for frame, (old_value, new_value) in enumerate(zip(old["values"], new["values"], strict=True)):
                if old_value == new_value:
                    continue
                if not first <= frame <= last:
                    raise ValueError("UNBAKING_SCOPE_VIOLATION: animation changed outside approved interval")
                left = bisect.bisect_right(keys, frame) - 1
                if left < 0 or not first <= keys[left] <= last:
                    raise ValueError("UNBAKING_SCOPE_VIOLATION: changed sample has no in-scope authored key")
                written.add((layer_id, keys[left]))
            changed_references[field].add(identifier)
    for obj in before["objects"]:
        if obj["id"] in owners:
            continue
        for behaviour in obj["behaviours"]:
            for prop in behaviour["properties"]:
                kind, value = prop["kind"], prop["value"]
                field = "data" if kind in {"DataType", "DataRangeType"} else "settings" if kind in {"SettingType", "SettingRangeType"} else None
                if field is not None and set(value if isinstance(value, list) else [value]) & changed_references[field]:
                    raise ValueError("UNBAKING_SCOPE_VIOLATION: changed animation is referenced by a non-target object")
    for identifier, frame in written:
        original = _indexed(before_layers[identifier]["sections"], "frame").get(frame)
        if original is not None and original.get("label") is not None:
            raise ValueError("UNBAKING_SCOPE_VIOLATION: labeled original key changed")
    if (len(added) > policy["maximum_added_keys"] or len(removed) > policy["maximum_removed_keys"]
            or len(written) > policy["maximum_written_keys"]):
        raise ValueError("UNBAKING_KEY_BUDGET_EXCEEDED: observed topology exceeds approved finite bounds")
    return {"status": "observed_within_bounds", "native_completion": "unverified",
        "maximums": dict(policy), "added_keys": len(added), "removed_keys": len(removed), "written_keys": len(written),
        "before_projection_digest": guards.digest(before), "after_projection_digest": guards.digest(after),
        "policy_digest": guards.digest(policy), "coverage": "sampled_frames"}


def observe_after(scene, before, arguments):
    return compare_projections(before, _read_projection(scene), arguments)
