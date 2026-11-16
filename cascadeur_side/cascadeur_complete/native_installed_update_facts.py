"""Read the installed 2026.2 Update graph inside an admitted callback only.

No SDK import or scene access occurs at import. These observations are not an
interpolation/completion qualification or a derived-storage classifier. In
particular an Animation data with an incoming function remains authored-unknown.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

_MAX_NODES = 8192
_MAX_PORTS = 65536
_MAX_EDGES = 131072
_IMAGE = None


def _json_addresses(value):
    """Keep hashable internal addresses while encoding JSON-only observations."""
    if isinstance(value, (tuple, list)):
        return [_json_addresses(item) for item in value]
    if isinstance(value, dict):
        return {key: _json_addresses(item) for key, item in value.items()}
    return value


def _value_type(value):
    import numpy as np
    from .native_scene_reader import native_value
    if isinstance(value, np.ndarray) and (value.ndim > 3 or any(not 1 <= n <= 16 for n in value.shape)):
        raise ValueError("UPDATE_NATIVE_VALUE_SHAPE_BUDGET")
    if isinstance(value, str) and len(value) > 4096:
        raise ValueError("UPDATE_NATIVE_STRING_BUDGET")
    encoded = native_value(value)
    shape = tuple(np.asarray(encoded).shape)
    if isinstance(value, np.ndarray):
        dtype = value.dtype.name if value.dtype.isnative else value.dtype.str
    else:
        # A Python float/Rotation/Quaternion is not native-storage f32 evidence.
        dtype = "native:" + type(value).__name__
    return encoded, dtype, shape


def _guid(value):
    import uuid
    text = str(value)
    try:
        if str(uuid.UUID(text)) != text.lower():
            raise ValueError()
    except (ValueError, AttributeError) as error:
        raise ValueError("UPDATE_NATIVE_GUID_ENCODING_UNAVAILABLE") from error
    return text.lower()


def _direction(value):
    # Direction wraps DirectionValue; this is the installed documented getter.
    return int(value.value())


def _node_key(node):
    identifier = node.id()
    kind = type(identifier).__name__
    if kind == "InterfaceId":
        return (kind, _guid(identifier.group_id), _direction(identifier.direction))
    if kind in ("ConstantDatasId", "ConstantSettingsId", "ExternalPropertiesId"):
        # These SDK wrappers have no string getter. Their documented identity
        # is the containing group's ID, with the node kind as discriminator.
        return (kind, _guid(node.parent_group().id()))
    return (kind, _guid(identifier))


def _port_key(attribute):
    identifier = attribute.id()
    kind = type(identifier).__name__
    if kind == "GroupAttributeId":
        details = (_guid(identifier.group_id), _guid(identifier.attribute_id))
    elif kind in ("ConstantDataAttributeId", "ConstantSettingAttributeId"):
        details = (_guid(attribute.node().parent_group().id()), _guid(identifier.attribute_id))
    elif kind == "RegularFunctionAttributeId":
        details = (_guid(identifier.function_id), str(identifier.attribute_id))
    elif kind == "SettingFunctionAttributeId":
        details = (_guid(identifier.function_id), int(identifier.attribute_index), int(identifier.attribute_sub_index))
    elif kind == "ExternalPropertyAttributeId":
        details = (_guid(attribute.node().parent_group().id()), int(identifier.property))
    elif kind in ("RegularDataAttributeId", "ActualityAttributeId", "DataId", "SettingId", "HyperedgeId"):
        # The first two IDs intentionally expose no string/getter. Their one
        # input/output/actuality ports are identified by the owning typed node,
        # direction and exact name, not repr(pointer) or a fabricated GUID.
        details = ()
    else:
        raise ValueError("UPDATE_ATTRIBUTE_ID_TYPE_UNSUPPORTED:" + kind)
    name = str(attribute.name())
    if len(name) > 1024:
        raise ValueError("UPDATE_PORT_NAME_BUDGET")
    return (_node_key(attribute.node()), _direction(attribute.direction()), kind, details, name)


def _implementation_identity():
    """Pin the running host image; function type names alone are not versions."""
    import ctypes
    global _IMAGE
    path = ctypes.create_unicode_buffer(32768)
    if not ctypes.windll.kernel32.GetModuleFileNameW(None, path, len(path)):
        raise ValueError("UPDATE_NATIVE_IMPLEMENTATION_IMAGE_UNAVAILABLE")
    image = Path(path.value)
    stat = image.stat()
    def identity_of(value):
        # Reading the image may update atime. Pin its file identity and content
        # metadata instead of comparing the entire stat_result (incl. atime).
        return (str(image.resolve()), value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns)
    identity = identity_of(stat)
    if _IMAGE is not None:
        if _IMAGE[0] != identity:
            raise ValueError("UPDATE_NATIVE_IMPLEMENTATION_IMAGE_CHANGED")
        return _IMAGE[1]
    if not 0 < stat.st_size <= 2 * 1024**3:
        raise ValueError("UPDATE_NATIVE_IMAGE_BUDGET")
    with image.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    if identity_of(image.stat()) != identity:
        raise ValueError("UPDATE_NATIVE_IMPLEMENTATION_IMAGE_CHANGED")
    _IMAGE = (identity, {"image_sha256": digest, "image_bytes": stat.st_size})
    return _IMAGE[1]


def extract_installed_update_facts(model, update, updater):
    """Observe typed nodes/ports, all immediate edges and native value shapes.

    Call only through bind_native_update_runner. Every endpoint must be in the
    enumerated root closure, and model data/settings must have an observed node
    or an explicit constant port. No missing edge/type is silently discarded.
    """
    import csc
    import numpy as np
    from .native_scene_reader import native_value, MAX_OBJECTS, MAX_VALUES
    from .native_update_capture import NativeDataFact, UpdateFacts, frozen_json

    if not isinstance(update, csc.update.Update):
        raise ValueError("INSTALLED_UPDATE_OBJECT_REQUIRED")
    viewer = model.get_viewer()
    dv = viewer.data_viewer()
    objects = list(viewer.get_objects())
    if len(objects) > MAX_OBJECTS:
        raise ValueError("UPDATE_OBJECT_BUDGET")
    implementation = _implementation_identity()
    graph_bytes_reserved = 0
    def reserve(value):
        nonlocal graph_bytes_reserved
        graph_bytes_reserved += len(frozen_json(_json_addresses(value))) + 8
        if graph_bytes_reserved > 2 * 1024**2:
            raise ValueError("UPDATE_GRAPH_ENCODING_BUDGET")
    nodes, ports, native_ports, native_nodes = {}, {}, {}, {}
    regular, constants, setting_nodes, constant_settings = {}, {}, {}, {}
    pending = [update.root()]
    while pending:
        node = pending.pop()
        key = _node_key(node)
        if key in nodes:
            if not native_nodes[key].equal_to(node):
                raise ValueError("UPDATE_NODE_ID_COLLISION")
            continue
        if len(nodes) >= _MAX_NODES:
            raise ValueError("UPDATE_NODE_BUDGET")
        kind = type(node).__name__
        parent = node.parent_object()
        owner = None if parent is None or parent.object_id().is_null() else _guid(parent.object_id())
        name = str(node.name())
        if len(name) > 1024:
            raise ValueError("UPDATE_NODE_NAME_BUDGET")
        row = {"id": key, "kind": kind, "name": name,
               "owner": owner, "fictive": bool(node.is_fictive()), "active": bool(node.is_active())}
        nodes[key], native_nodes[key] = row, node
        if isinstance(node, (csc.update.RegularFunction, csc.update.SettingFunction)):
            row.update(producer_type=str(node.type_name()), implementation=implementation,
                       convertible=bool(node.is_convertible()))
        if isinstance(node, csc.update.RegularData):
            identifier = _guid(node.data_id())
            if identifier in regular:
                raise ValueError("UPDATE_DATA_NODE_DUPLICATE")
            regular[identifier] = node
            row.update(data_id=identifier, native_type=str(node.data_type_name()), mode=str(node.mode().name),
                       apply_euler_filter=bool(node.get_apply_euler_filter()),
                       explicit_linear=bool(node.get_explicit_linear()), lerp_mode=str(node.get_lerp_mode().name),
                       period=node.get_period(), actual=bool(node.is_actual()))
        elif isinstance(node, csc.update.SettingData):
            setting_nodes[_guid(node.data_id())] = node
        if isinstance(node, csc.update.Group):
            pending.extend(node.nodes())
            pending.extend((node.constant_datas(), node.constant_settings(),
                            node.input_interface_node(), node.output_interface_node()))
        if isinstance(node, csc.update.ObjectGroup):
            pending.extend(node.objects()); pending.extend(node.object_groups())
        if isinstance(node, csc.update.Object):
            pending.append(node.root_group())
        if isinstance(node, csc.update.UpdateGroup):
            pending.extend(node.groups()); pending.extend(node.regular_datas())
            pending.extend(node.regular_functions()); pending.extend(node.settings_datas())
            pending.extend(node.setting_functions()); pending.append(node.external_properties())
        # Static RegularData exposes outputs only; inputs() itself throws.
        inputs = [] if isinstance(node, csc.update.RegularData) and node.mode().name == "Static" else list(node.inputs())
        outputs = list(node.outputs())
        if len(inputs) + len(outputs) > _MAX_PORTS:
            raise ValueError("UPDATE_PORT_BUDGET")
        row.update(inputs=[_port_key(a) for a in inputs], outputs=[_port_key(a) for a in outputs])
        reserve(row)
        for attribute in inputs + outputs:
            pk = _port_key(attribute)
            if not attribute.node().equal_to(node):
                # Object forwards its root UpdateGroup's interface attributes.
                # Keep those references on the Object row, but collect each
                # physical port only when visiting its actual owning node.
                if not isinstance(node, csc.update.Object) or not attribute.node().equal_to(node.root_group()):
                    raise ValueError("UPDATE_PORT_OWNER_DIFFERS")
                continue
            if pk in ports or len(ports) >= _MAX_PORTS:
                raise ValueError("UPDATE_PORT_COLLISION_OR_BUDGET")
            ports[pk] = {"id": pk, "kind": type(attribute).__name__, "active": bool(attribute.is_active())}
            reserve(ports[pk])
            native_ports[pk] = attribute
            aid = attribute.id()
            if isinstance(attribute, csc.update.ConstantDataAttribute):
                constants[_guid(aid.attribute_id)] = attribute
            if isinstance(attribute, csc.update.ConstantSettingAttribute):
                constant_settings[_guid(aid.attribute_id)] = attribute
            if (isinstance(attribute, csc.update.SettingFunctionAttribute)
                    and attribute.direction().value() == csc.DirectionValue.Out):
                ports[pk].update(output_id=_guid(attribute.output_id()), out_true=bool(attribute.is_out_true()))

    if any(pk not in ports for row in nodes.values() for pk in row["inputs"] + row["outputs"]):
        raise ValueError("UPDATE_NODE_PORT_UNOBSERVED")
    edges, external = set(), set()
    for pk, attribute in native_ports.items():
        connections = attribute.connected_attributes()
        if len(connections) > _MAX_EDGES - len(edges):
            raise ValueError("UPDATE_EDGE_BUDGET")
        for other in connections:
            target = _port_key(other)
            if target not in ports:
                external.add((pk, target))
            else:
                # Port direction is preserved; traversing from both endpoints
                # produces one undirected physical connection, not two edges.
                edge = tuple(sorted((pk, target)))
                if edge not in edges:
                    reserve(edge)
                edges.add(edge)
            if len(edges) + len(external) > _MAX_EDGES:
                raise ValueError("UPDATE_EDGE_BUDGET")
        if isinstance(attribute, csc.update.InterfaceAttribute):
            target = _port_key(attribute.other_side())
            if target not in ports:
                external.add((pk, target))
            else:
                edge = tuple(sorted((pk, target)))
                if edge not in edges:
                    reserve(edge)
                edges.add(edge)
        native_leaves = attribute.connected_leaves(False)
        if len(native_leaves) > _MAX_PORTS:
            raise ValueError("UPDATE_CONNECTED_LEAF_BUDGET")
        leaves = [_port_key(a) for a in native_leaves]
        if any(leaf not in ports for leaf in leaves):
            raise ValueError("UPDATE_GRAPH_EXTERNAL_LEAF_UNOBSERVED")
        ports[pk]["connected_leaves"] = sorted(leaves)
        reserve(leaves)
    if external:
        raise ValueError("UPDATE_GRAPH_EXTERNAL_ENDPOINT_UNOBSERVED")

    model_data = {str(identifier): identifier for obj in objects for identifier in dv.get_all_data_id(obj)}
    model_settings = {str(identifier): identifier for obj in objects for identifier in dv.get_all_settings_id(obj)}
    # Match native_scene_reader's actual referenced data closure, including
    # ordered dynamic ranges and their observed dangling references.
    bv = viewer.behaviour_viewer()
    routes = {"DataType": (model_data, "get_behaviour_data"),
              "DataRangeType": (model_data, "get_behaviour_data_range"),
              "SettingType": (model_settings, "get_behaviour_setting"),
              "SettingRangeType": (model_settings, "get_behaviour_settings_range")}
    for obj in objects:
        for behaviour in bv.get_behaviours(obj):
            for name in bv.get_behaviour_property_names(behaviour):
                kind = bv.get_property_type(behaviour, name).name
                if kind in routes:
                    target, method = routes[kind]
                    value = getattr(bv, method)(behaviour, name)
                    for identifier in list(value) if "Range" in kind else [value]:
                        if not identifier.is_null():
                            target[str(identifier)] = identifier
    model_data = {key: value for key, value in model_data.items() if dv.has_data(value)}
    model_settings = {key: value for key, value in model_settings.items() if dv.has_setting(value)}
    if not set(model_data) <= set(regular) | set(constants):
        raise ValueError("UPDATE_MODEL_DATA_CLOSURE_DIFFERS")
    if not set(model_settings) <= set(setting_nodes) | set(constant_settings):
        raise ValueError("UPDATE_MODEL_SETTING_CLOSURE_DIFFERS")
    all_graph_settings = {**{key: node.data_id() for key, node in setting_nodes.items()},
                          **{key: port.id().attribute_id for key, port in constant_settings.items()}, **model_settings}
    frames = int(dv.get_animation_size())
    if frames < 1:
        raise ValueError("UPDATE_EMPTY_TIMELINE_UNSUPPORTED")
    reservation = sum(frames if dv.get_data(key).mode.name == "Animation" else 1 for key in model_data.values())
    reservation += sum(frames if dv.get_setting(key).mode.name == "Animation" else 1 for key in all_graph_settings.values())
    if reservation > MAX_VALUES:
        raise ValueError("UPDATE_TYPED_VALUE_BUDGET")
    facts = []
    for text, identifier in sorted(model_data.items()):
        item = dv.get_data(identifier)
        samples = range(frames) if item.mode.name == "Animation" else (None,)
        observed_type = None
        for frame in samples:
            value = dv.get_data_value(identifier) if frame is None else dv.get_data_value(identifier, frame)
            encoded, dtype, shape = _value_type(value)
            if observed_type is not None and observed_type != (dtype, shape):
                raise ValueError("UPDATE_NATIVE_TYPE_VARIES_BY_FRAME")
            observed_type = (dtype, shape)
        node = regular.get(text)
        if node is None:
            producer, consumers, upstream = None, (), ()
            # Constant payload participates in graph identity; ordinary authored
            # animation values deliberately remain in the raw projection only.
            ports[_port_key(constants[text])].update(value=encoded, native_dtype=dtype, sample_shape=shape)
        else:
            producers = [] if node.mode().name == "Static" else [a.node() for a in node.input().connected_leaves(False)]
            producers = {_node_key(n): n for n in producers if isinstance(n, csc.update.RegularFunction)}
            producer = next(iter(producers.values())) if len(producers) == 1 else None
            consumers = tuple(sorted({_guid(n.func_id()) for a in node.output().connected_leaves(False)
                                      if isinstance((n := a.node()), csc.update.RegularFunction)}))
            inputs = [a.node() for candidate in producers.values() for port in candidate.arguments()
                      for a in port.connected_leaves(False)]
            upstream = tuple(sorted({_guid(n.data_id()) for n in inputs if isinstance(n, csc.update.RegularData)
                                     and _guid(n.data_id()) in model_data}))
        kind = None if producer is None else str(producer.type_name()) + ":" + implementation["image_sha256"]
        facts.append(NativeDataFact(text, _guid(item.object_id), observed_type[0], observed_type[1],
            None if producer is None else _guid(producer.func_id()), kind, None, upstream, consumers))
    # A graph input not owned/referenced by a scene object must not disappear
    # merely because the raw model projection does not list its data row.
    for text, node in regular.items():
        if text not in model_data:
            if node.mode().name != "Static":
                raise ValueError("UPDATE_UNPROJECTED_ANIMATION_DATA")
            value, dtype, shape = _value_type(node.value())
            payload = {"value": value, "native_dtype": dtype, "sample_shape": shape}
            reserve(payload)
            nodes[_node_key(node)].update(payload)
    settings = []
    for text, identifier in sorted(all_graph_settings.items()):
        item = dv.get_setting(identifier)
        samples = range(frames) if item.mode.name == "Animation" else (None,)
        values = [native_value(dv.get_setting_value(identifier) if f is None else dv.get_setting_value(identifier, f)) for f in samples]
        row = {"id": text, "owner": _guid(item.object_id), "mode": item.mode.name, "values": values}
        reserve(row)
        settings.append(row)
    # Unreferenced defaults are still real graph constants; retain their exact
    # payloads, instead of dropping nodes to make two graph digests agree.
    for text, port in constants.items():
        if text not in model_data:
            item = dv.get_data(port.id().attribute_id)
            if item.mode.name != "Static":
                raise ValueError("UPDATE_NONSTATIC_UNREFERENCED_CONSTANT")
            value, dtype, shape = _value_type(dv.get_data_value(item.id))
            ports[_port_key(port)].update(value=value, native_dtype=dtype, sample_shape=shape)
    for text, port in constant_settings.items():
        if text not in model_settings:
            item = dv.get_setting(port.id().attribute_id)
            if item.mode.name != "Static":
                raise ValueError("UPDATE_NONSTATIC_UNREFERENCED_SETTING")
            ports[_port_key(port)]["value"] = native_value(dv.get_setting_value(item.id))
    graph = {"schema_version": 1, "reader": "installed-update-2026.2-v1", "implementation": implementation,
             "nodes": [nodes[k] for k in sorted(nodes)], "ports": [ports[k] for k in sorted(ports)],
             "edges": sorted(edges), "external_links": [], "settings": settings}
    raw = frozen_json(_json_addresses(graph))
    if len(raw) > 2 * 1024**2:
        raise ValueError("UPDATE_GRAPH_ENCODING_BUDGET")
    return UpdateFacts(raw, tuple(facts))


def serialization_role_specs(scene):
    """No installed API proves authored-vs-derived storage for generic data.

    Exact-only is executable and deliberately needs no invented tolerance.
    A later reviewed typed producer rule must establish storage semantics first.
    """
    return ()
