"""Bounded, read-only native scene projection for checkpoint and evaluation.

Read every model property (including ordered ranges), owned/referenced data and
settings, cluster links, animation sections and supported embedded assets. An
unreadable property/asset is a blocker, never silently omitted from a digest.
This does not infer physical units, semantic rig roles or evaluated motion.
"""
from __future__ import annotations

import hashlib
import json
import math


MAX_OBJECTS = 5000
MAX_FRAMES = 20001
MAX_VALUES = 2_000_000
MAX_ASSET_ELEMENTS = 2_000_000
MAX_PROJECTION_BYTES = 128 * 1024 * 1024


def member(value, name):
    found = getattr(value, name)
    return found() if callable(found) else found


def native_value(value):
    if type(value).__name__ == "Guid":
        return str(value)
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("INCOMPLETE_CAPTURE: nonfinite native data")
        return value
    if hasattr(value, "to_quaternion"):
        value = value.to_quaternion()
    if all(hasattr(value, name) for name in ("w", "x", "y", "z")):
        return [float(member(value, key)) for key in ("w", "x", "y", "z")]
    if hasattr(value, "tolist"):
        return native_value(value.tolist())
    if isinstance(value, (list, tuple)):
        return [native_value(item) for item in value]
    raise ValueError("INCOMPLETE_CAPTURE: unsupported value " + type(value).__name__)


def _asset(asset):
    kind = type(asset).__name__
    def array(name):
        values = member(asset, name)
        if len(values) > MAX_ASSET_ELEMENTS:
            raise ValueError("RESOURCE_BUDGET_EXCEEDED: native asset " + name)
        return native_value(values)
    if kind == "Mesh":
        vertices = member(asset, "vertices")
        if len(vertices) > MAX_ASSET_ELEMENTS:
            raise ValueError("RESOURCE_BUDGET_EXCEEDED: mesh vertices")
        return {"kind": kind, "positions": array("positions"), "normals": array("normals"), "uvs": array("uvs"),
                "vertices_in_polygon": int(member(asset, "vertices_in_polygon")),
                "vertices": [[int(member(v, key)) for key in ("position_index", "normal_index", "uv_index")] for v in vertices]}
    if kind == "MeshDependency":
        weights = member(asset, "vertices_weights")
        if len(weights) > MAX_ASSET_ELEMENTS or sum(len(row) for row in weights) > MAX_ASSET_ELEMENTS:
            raise ValueError("RESOURCE_BUDGET_EXCEEDED: skin weights")
        return {"kind": kind, "inverse_bind_matrices": array("inverse_bind_matrices"),
                "vertices_weights": [[[int(member(w, "index")), float(member(w, "weight"))] for w in row] for row in weights]}
    raise ValueError("INCOMPLETE_CAPTURE: native asset content unavailable for " + kind)


def _sections(layer):
    result = []
    for frame, section in sorted(member(layer, "sections").items()):
        key, interval = member(section, "key"), member(section, "interval")
        row = {"frame": int(frame), "interpolation": member(member(interval, "interpolation"), "name"),
               "description_for_ai_interpolation": str(member(interval, "description_for_ai_interpolation")),
               "tangents": member(member(key, "tangents"), "name"), "label": native_value(member(key, "label")),
               "left_weight_velocity": float(member(key, "left_weight_velocity")),
               "right_weight_velocity": float(member(key, "right_weight_velocity"))}
        for name, value in (("key_common", member(key, "common")), ("interval_common", member(interval, "common"))):
            row[name] = {field: member(member(value, field), "name") for field in ("ik_fk", "fixation")}
        result.append(row)
    return result


def read_scene(scene):
    from . import runtime as rt
    from .handlers.animation import _cycles
    domain = rt._domain_scene(scene)
    mv, bv, dv, lv = domain.model_viewer(), domain.behaviour_viewer(), domain.data_viewer(), domain.layers_viewer()
    objects = sorted(mv.get_objects(), key=str)
    frames = int(lv.frames_count())
    if len(objects) > MAX_OBJECTS or frames < 1 or frames > MAX_FRAMES:
        raise ValueError("RESOURCE_BUDGET_EXCEEDED: native scene object/frame scope")
    import csc.additive_layers
    additive = csc.additive_layers.get_manager(domain)
    if additive.get_stacked_layers_count() != 0:
        raise ValueError("INCOMPLETE_CAPTURE: stacked additive animation content unavailable")
    rows, data_ids, setting_ids, asset_ids, known_behaviours = [], {}, {}, set(), set()
    routes = {
        "ObjectType": ("get_behaviour_object", None), "ObjectRangeType": ("get_behaviour_objects_range", None),
        "BehaviourType": ("get_behaviour_reference", "behaviour"), "BehaviourRangeType": ("get_behaviour_reference_range", "behaviour"),
        "DataType": ("get_behaviour_data", "data"), "DataRangeType": ("get_behaviour_data_range", "data"),
        "SettingType": ("get_behaviour_setting", "setting"), "SettingRangeType": ("get_behaviour_settings_range", "setting"),
        "AssetType": ("get_behaviour_asset", "asset"), "AssetRangeType": ("get_behaviour_asset_range", "asset"),
        "StringType": ("get_behaviour_string", "string"),
    }
    behaviour_refs = set()
    for obj in objects:
        object_row = {"id": str(obj), "name": mv.get_object_name(obj), "type": mv.get_object_type_name(obj), "behaviours": []}
        for data_id in dv.get_all_data_id(obj):
            data_ids[str(data_id)] = data_id
        for setting_id in dv.get_all_settings_id(obj):
            setting_ids[str(setting_id)] = setting_id
        for behaviour in sorted(bv.get_behaviours(obj), key=str):
            known_behaviours.add(str(behaviour))
            row = {"id": str(behaviour), "name": bv.get_behaviour_name(behaviour),
                   "hidden": bool(bv.is_hidden(behaviour)), "properties": []}
            for name in sorted(bv.get_behaviour_property_names(behaviour)):
                kind = bv.get_property_type(behaviour, name).name
                if kind not in routes:
                    raise ValueError("INCOMPLETE_CAPTURE: unsupported property kind " + kind)
                method, target = routes[kind]
                value = getattr(bv, method)(behaviour, name)
                if target == "string":
                    encoded = value
                else:
                    ids = list(value) if "Range" in kind else [value]
                    encoded_ids = []
                    for identifier in ids:
                        text = None if identifier.is_null() else str(identifier)
                        encoded_ids.append(text)
                        if text is not None:
                            if target == "data": data_ids[text] = identifier
                            elif target == "setting": setting_ids[text] = identifier
                            elif target == "asset": asset_ids.add(text)
                            elif target == "behaviour": behaviour_refs.add(text)
                    encoded = encoded_ids if "Range" in kind else encoded_ids[0]
                row["properties"].append({"name": name, "kind": kind, "value": encoded})
            object_row["behaviours"].append(row)
        rows.append(object_row)
    if behaviour_refs - known_behaviours:
        raise ValueError("INCOMPLETE_CAPTURE: behaviour reference escapes enumerated scene")
    # Native Dynamic ranges may retain dangling IDs. Capture their observed
    # absence as well as the ordered links, so creating/deleting that data later
    # changes the projection. Do not call an absent reference a zero value.
    missing_data = sorted(text for text, identifier in data_ids.items() if not dv.has_data(identifier))
    missing_settings = sorted(text for text, identifier in setting_ids.items() if not dv.has_setting(identifier))
    data_ids = {text: identifier for text, identifier in data_ids.items() if text not in missing_data}
    setting_ids = {text: identifier for text, identifier in setting_ids.items() if text not in missing_settings}
    estimated = 0
    for identifier in data_ids.values():
        estimated += frames if dv.get_data(identifier).mode.name == "Animation" else 1
    for identifier in setting_ids.values():
        estimated += frames if dv.get_setting(identifier).mode.name == "Animation" else 1
    if estimated > MAX_VALUES:
        raise ValueError("RESOURCE_BUDGET_EXCEEDED: native data/settings projection")
    data, settings = [], []
    def description(identifier):
        link = dv.get_description_id_by_linked_id(identifier)
        return None if link.is_null() else {"id": str(link), "name": dv.get_description_name(link), "value": dv.get_description_value(link)}
    for text, identifier in sorted(data_ids.items()):
        item = dv.get_data(identifier)
        values = [native_value(dv.get_data_value(identifier, f)) for f in range(frames)] if item.mode.name == "Animation" else [native_value(dv.get_data_value(identifier))]
        data.append({"id": text, "owner": str(item.object_id), "name": item.name, "mode": item.mode.name,
                     "values": values, "description": description(identifier)})
    for text, identifier in sorted(setting_ids.items()):
        item = dv.get_setting(identifier)
        values = [native_value(dv.get_setting_value(identifier, f)) for f in range(frames)] if item.mode.name == "Animation" else [native_value(dv.get_setting_value(identifier))]
        settings.append({"id": text, "owner": str(item.object_id), "name": item.name, "mode": item.mode.name,
                         "values": values, "description": description(identifier)})
    layers, folders = [], []
    for layer_id in sorted(lv.all_layer_ids(), key=str):
        layer, header = lv.layer(layer_id), lv.header(layer_id)
        layers.append({"id": str(layer_id), "name": member(header, "name"), "locked": bool(member(layer, "is_locked")),
                       "visible": bool(member(layer, "is_visible")), "parents": [str(x) for x in lv.all_parent_ids(layer_id)],
                       "position_in_parent": int(lv.pos_in_parent(layer_id)),
                       "object_ids": sorted(str(x) for x in member(layer, "obj_ids")),
                       "keys": list(map(int, layer.key_frame_indices())), "sections": _sections(layer)})
    for folder_id, folder in sorted(lv.folders_map().items(), key=lambda row: str(row[0])):
        folders.append({"id": str(folder_id), "name": member(lv.header(folder_id), "name"),
                        "children_ordered": [str(x) for x in folder.children_ordered()],
                        "parents": [str(x) for x in lv.all_parent_ids(folder_id)]})
    context = {"read_member": rt._read_member, "id_string": rt._id_string, "json_safe": rt.json_safe, "csc": rt.csc, "guid": rt._guid}
    assets_manager = domain.assets_manager()
    actual_assets = {str(i): i for i in assets_manager.all_ids()}
    if asset_ids - set(actual_assets):
        raise ValueError("INCOMPLETE_CAPTURE: external or missing asset content")
    if assets_manager.link_ids():
        raise ValueError("INCOMPLETE_CAPTURE: external linked asset content is outside native snapshot reader")
    assets = [{"id": text, **_asset(assets_manager.at(identifier))} for text, identifier in sorted(actual_assets.items())]
    clusters = dv.cluster_viewer()
    cluster_rows = [{"id": int(i), "name": clusters.cluster_name(i), "data": sorted(str(x) for x in clusters.cluster_datas(i))} for i in sorted(clusters.clusters())]
    edges = sorted([int(member(e, "a")), int(member(e, "b"))] for e in clusters.clusters_bindings())
    result = {"schema_version": 1, "reader": "native-model-assets-v1", "frames": frames,
              "objects": rows, "data": data, "settings": settings, "layers": layers, "folders": folders,
              "cycles": _cycles(domain, list(lv.all_layer_ids()), 0, frames - 1, context),
              "assets": assets, "clusters": cluster_rows, "cluster_edges": edges,
              "missing_data_references": missing_data, "missing_setting_references": missing_settings,
              "additive": {"stacked_layers_count": 0, "current_layer_index": additive.get_current_layer_index()},
              "descriptions": [[str(n), dv.get_any_description_value_by_name(n)] for n in sorted(dv.get_description_names())]}
    encoded = json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    if len(encoded) > MAX_PROJECTION_BYTES:
        raise ValueError("RESOURCE_BUDGET_EXCEEDED: native projection bytes")
    return result


def projection_digest(scene):
    value = read_scene(scene)
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
