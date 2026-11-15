"""Native bind evidence, without frame evaluation or physical-unit inference.

The installed official commands/go_to_bind_pose.py:39-57 pairs ordered
MeshObject.linked_objects with MeshDependency.inverse_bind_matrices and inverts
each matrix as a Cascadeur global bind transform. pycsc's mesh_object.py:145-158
also calls these Cascadeur coordinates; bindShapeMatrix is its conversion to
FBX coordinates, not a current pose. We keep native coordinates and retain
bindShapeMatrix as raw metadata without applying an FBX conversion.

Neither entry point raises for unavailable/malformed evidence. Callers must
inspect errors, unobserved and the explicit maps; status is not quality proof.
"""
from __future__ import annotations

import hashlib
import json
import math

import numpy as np


MAX_OBJECTS = 10000
MAX_BIND_LINKS = 100000
MAX_PARENT_DEPTH = 256
MATRIX_ATOL = 1e-5


class _Invalid(ValueError):
    def __init__(self, code, detail):
        self.code, self.detail = code, detail
        super().__init__(code + ': ' + detail)


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     allow_nan=False).encode('utf-8')).hexdigest()


def _identity(value, label):
    if not isinstance(value, str) or not value or len(value) > 512:
        raise _Invalid('BIND_REFERENCE_INVALID', label)
    return value


def _rows(value, label, maximum=MAX_OBJECTS):
    if not isinstance(value, (list, tuple)) or len(value) > maximum:
        raise _Invalid('BIND_RESOURCE_OR_SHAPE_INVALID', label)
    if any(not isinstance(row, dict) for row in value):
        raise _Invalid('BIND_PROJECTION_INVALID', label)
    return value


def _index(rows, label):
    result = {}
    for row in rows:
        key = _identity(row.get('id'), label)
        if key in result:
            raise _Invalid('BIND_DUPLICATE_ID', label + ':' + key)
        result[key] = row
    return result


def _properties(behaviour):
    result = {}
    for row in _rows(behaviour.get('properties'), 'behaviour properties', 10000):
        name = row.get('name')
        if not isinstance(name, str) or not name or name in result:
            raise _Invalid('BIND_PROPERTY_AMBIGUOUS', str(name))
        result[name] = row
    return result


def _property(properties, name, kind):
    row = properties.get(name)
    if row is None or row.get('kind') != kind or 'value' not in row:
        raise _Invalid('BIND_PROPERTY_UNOBSERVED', name + ':' + kind)
    return row['value']


def _matrix(value, label, *, rigid=True):
    # Validate shape before ndarray allocation; reject booleans/string coercion.
    if (not isinstance(value, (list, tuple)) or len(value) != 4
            or any(not isinstance(row, (list, tuple)) or len(row) != 4 for row in value)
            or any(type(x) not in (int, float) or not math.isfinite(x) for row in value for x in row)):
        raise _Invalid('BIND_MATRIX_INVALID', label)
    matrix = np.asarray(value, dtype=float)
    rotation = matrix[:3, :3]
    if not np.allclose(matrix[3], (0, 0, 0, 1), rtol=0, atol=MATRIX_ATOL):
        raise _Invalid('BIND_MATRIX_NONAFFINE', label)
    if rigid and (not np.allclose(rotation.T @ rotation, np.eye(3), rtol=0, atol=MATRIX_ATOL)
                  or not math.isclose(float(np.linalg.det(rotation)), 1.0, rel_tol=0, abs_tol=MATRIX_ATOL)):
        raise _Invalid('BIND_MATRIX_NONRIGID', label)
    try:
        inverse = np.linalg.inv(matrix)
    except np.linalg.LinAlgError as exc:
        raise _Invalid('BIND_MATRIX_SINGULAR', label) from exc
    if not np.isfinite(inverse).all():
        raise _Invalid('BIND_MATRIX_INVALID', label + ': inverse')
    return matrix, inverse


def _retained(value, depth=0):
    """Keep rejected raw observations serializable, including invalid floats."""
    if depth > 20:
        return {'invalid_evidence': 'nesting_limit'}
    if value is None or type(value) in (str, bool, int):
        return value
    if type(value) is float:
        return value if math.isfinite(value) else {'invalid_float': repr(value)}
    if isinstance(value, (list, tuple)):
        return [_retained(item, depth + 1) for item in value]
    if isinstance(value, dict):
        return {str(key): _retained(item, depth + 1) for key, item in value.items()}
    return {'invalid_evidence_type': type(value).__name__}


def _empty():
    return {'schema_version': 1, 'status': 'unobserved',
            'coordinate_space': 'cascadeur_scene', 'units': 'native_scene_units',
            'rest_global_transforms': {}, 'rest_local_transforms': {}, 'parent_ids': {},
            'provenance': {}, 'raw_evidence': {'meshes': []}, 'unobserved': [], 'errors': []}


def _shape_metadata(properties, data, object_id):
    """Optional FBX conversion metadata; never a native-rest prerequisite."""
    found = [row for row in properties if row.get('name') == 'bindShapeMatrix']
    result = {'properties': _retained(found), 'native_to_fbx_conversion': 'unobserved',
              'used_for_native_rest': False}
    try:
        if len(found) != 1 or found[0].get('kind') != 'DataType':
            raise _Invalid('BIND_SHAPE_UNOBSERVED', 'Unique bindShapeMatrix DataType required')
        shape_id = _identity(found[0].get('value'), 'bind shape data')
        result['data_id'] = shape_id
        matches = data.get(shape_id, [])
        if len(matches) != 1:
            raise _Invalid('BIND_SHAPE_UNOBSERVED', 'Missing/ambiguous bind shape data')
        shape = matches[0]
        result.update({'mode': shape.get('mode'), 'owner': shape.get('owner')})
        if shape.get('observation_error'):
            result['observation_error'] = shape['observation_error']
        if shape.get('owner') != object_id:
            raise _Invalid('BIND_SHAPE_UNOBSERVED', 'Bind shape owner differs')
        if shape.get('mode') == 'Static':
            values = shape.get('values')
            if not isinstance(values, (list, tuple)) or len(values) != 1:
                raise _Invalid('BIND_SHAPE_UNOBSERVED', 'One static value required')
            result['values'] = _retained(values)
            matrix = values[0]
        elif shape.get('mode') == 'Animation':
            samples = shape.get('sampled_values')
            if (not isinstance(samples, (list, tuple)) or len(samples) != 1
                    or not isinstance(samples[0], dict) or type(samples[0].get('frame')) is not int
                    or 'value' not in samples[0]):
                raise _Invalid('BIND_SHAPE_UNOBSERVED', 'One explicitly framed diagnostic sample required')
            result['sampled_values'] = _retained(samples)
            matrix = samples[0]['value']
        else:
            raise _Invalid('BIND_SHAPE_UNOBSERVED', 'Unsupported bind shape mode')
        _matrix(matrix, object_id + ': optional bind shape', rigid=False)
        result['matrix_observation'] = 'finite_affine_invertible'
    except (_Invalid, ValueError, TypeError, KeyError, OverflowError, np.linalg.LinAlgError) as exc:
        result['observation_error'] = {'code': getattr(exc, 'code', 'BIND_SHAPE_UNOBSERVED'),
                                       'detail': str(exc)[:1000]}
    return result


def read_bind_rest(projection, required_object_ids=None):
    """Derive global/local native rest from a native_scene_reader projection.

    Input uses objects[].behaviours[].properties(name,kind,value), assets[] and
    data[] for optional bindShapeMatrix metadata. IDs are exact native IDs.
    Output matrices are row-major 4x4 nested lists in native scene units. Only
    explicit Basic.parent=null proves a root. A local rest is emitted only when
    its complete ancestor chain has consistent bind evidence. Any malformed
    mesh prevents all rest issuance; missing bind coverage remains explicit.
    """
    result = _empty()
    required = []
    try:
        if not isinstance(projection, dict):
            raise _Invalid('BIND_PROJECTION_INVALID', 'Expected native projection')
        objects = _index(_rows(projection.get('objects'), 'objects'), 'object')
        assets = _index(_rows(projection.get('assets'), 'assets'), 'asset')
        data = {}
        for row in _rows(projection.get('data', []), 'data', 100000):
            if isinstance(row.get('id'), str):
                data.setdefault(row['id'], []).append(row)
        if required_object_ids is not None:
            if not isinstance(required_object_ids, (list, tuple, set, frozenset)) or len(required_object_ids) > MAX_OBJECTS:
                raise _Invalid('BIND_RESOURCE_OR_SHAPE_INVALID', 'required object IDs')
            required = [_identity(x, 'required object') for x in required_object_ids]
            if len(set(required)) != len(required):
                raise _Invalid('BIND_DUPLICATE_REFERENCE', 'required object IDs')
        behaviours_seen, parents, global_bind, witnesses = set(), {}, {}, {}
        result['raw_evidence']['basic_parents'] = parents
        link_count = 0
        for object_id, obj in objects.items():
            named = {}
            for behaviour in _rows(obj.get('behaviours'), 'object behaviours', 10000):
                behaviour_id = _identity(behaviour.get('id'), 'behaviour')
                if behaviour_id in behaviours_seen:
                    raise _Invalid('BIND_DUPLICATE_ID', 'behaviour:' + behaviour_id)
                behaviours_seen.add(behaviour_id)
                name = behaviour.get('name')
                if name in ('Basic', 'MeshObject'):
                    if name in named:
                        raise _Invalid('BIND_BEHAVIOUR_AMBIGUOUS', object_id + ':' + name)
                    named[name] = behaviour
            if 'Basic' in named:
                props = _properties(named['Basic'])
                parent = _property(props, 'parent', 'ObjectType')
                if parent is not None:
                    _identity(parent, 'parent of ' + object_id)
                    if parent not in objects:
                        raise _Invalid('BIND_DANGLING_PARENT', object_id + ':' + parent)
                parents[object_id] = parent
            if 'MeshObject' not in named:
                continue
            behaviour = named['MeshObject']
            mesh_properties = _rows(behaviour.get('properties'), 'mesh properties', 10000)
            # Shape metadata errors are independent of native inverse-bind
            # evidence, including duplicate/missing/wrong-kind shape fields.
            props = _properties({'properties': [row for row in mesh_properties
                                                 if row.get('name') != 'bindShapeMatrix']})
            links = _property(props, 'linked_objects', 'ObjectRangeType')
            dependency = _property(props, 'mesh_dependency', 'AssetType')
            shape_metadata = _shape_metadata(mesh_properties, data, object_id)
            raw = {'mesh_object_id': object_id, 'behaviour_id': behaviour['id'],
                   'linked_object_ids': links, 'mesh_dependency_id': dependency,
                   'bind_shape_data_id': shape_metadata.get('data_id'),
                   'bind_shape_metadata': shape_metadata}
            result['raw_evidence']['meshes'].append(raw)
            if not isinstance(links, (list, tuple)) or not links:
                raise _Invalid('BIND_LINK_MAPPING_INVALID', object_id)
            link_count += len(links)
            if link_count > MAX_BIND_LINKS:
                raise _Invalid('BIND_RESOURCE_OR_SHAPE_INVALID', 'bind links')
            links = [_identity(x, 'linked object') for x in links]
            if len(set(links)) != len(links) or any(x not in objects for x in links):
                raise _Invalid('BIND_LINK_MAPPING_INVALID', object_id + ': duplicate/dangling link')
            _identity(dependency, 'mesh dependency')
            asset = assets.get(dependency)
            if asset is None or asset.get('kind') != 'MeshDependency':
                raise _Invalid('BIND_DEPENDENCY_UNOBSERVED', object_id)
            inverse_matrices = asset.get('inverse_bind_matrices')
            raw['inverse_bind_matrices'] = inverse_matrices
            if not isinstance(inverse_matrices, (list, tuple)) or len(inverse_matrices) != len(links):
                raise _Invalid('BIND_MAPPING_CARDINALITY', object_id)
            for index, joint in enumerate(links):
                _, bind = _matrix(inverse_matrices[index], dependency + ':' + str(index))
                witness = {'mesh_object_id': object_id, 'mesh_dependency_id': dependency,
                           'linked_index': index, 'behaviour_id': behaviour['id']}
                if joint in global_bind and not np.allclose(global_bind[joint], bind, rtol=0, atol=MATRIX_ATOL):
                    raise _Invalid('BIND_SHARED_JOINT_DISAGREEMENT', joint)
                global_bind.setdefault(joint, bind)
                witnesses.setdefault(joint, []).append(witness)
        if required_object_ids is None:
            required = sorted(global_bind)
        required = sorted(required)
        result['parent_ids'] = {key: parents[key] for key in sorted(parents)}
        result['raw_evidence']['basic_parents'] = result['parent_ids'].copy()
        result['raw_evidence']['matrix_absolute_tolerance_native_units'] = MATRIX_ATOL
        result['raw_evidence']['coordinate_rule'] = 'inverse_native_inverse_bind;bind_shape_retained_not_applied'
        # Bind matrices for ancestors are retained even if only descendants were
        # requested. No current/default values enter this calculation.
        local = {}
        for object_id in required:
            if object_id not in objects:
                result['unobserved'].append({'object_id': object_id, 'reason': 'OBJECT_NOT_OBSERVED'})
                continue
            if object_id not in global_bind:
                result['unobserved'].append({'object_id': object_id, 'reason': 'BIND_POSE_NOT_OBSERVED'})
                continue
            chain, seen, current, reason = [], set(), object_id, None
            while current is not None:
                if current in seen:
                    raise _Invalid('BIND_PARENT_CYCLE', object_id)
                if len(chain) >= MAX_PARENT_DEPTH:
                    raise _Invalid('BIND_RESOURCE_OR_SHAPE_INVALID', 'parent closure exceeds 256 objects')
                chain.append(current)
                seen.add(current)
                if current not in global_bind:
                    reason = 'ANCESTOR_BIND_NOT_OBSERVED'
                    break
                if current not in parents:
                    reason = 'PARENT_REFERENCE_NOT_OBSERVED'
                    break
                current = parents[current]
            if reason is not None:
                result['unobserved'].append({'object_id': object_id, 'reason': reason,
                                            'missing_object_id': current, 'ancestor_chain': chain})
                continue
            parent = parents[object_id]
            local_matrix = (np.linalg.inv(global_bind[parent]) @ global_bind[object_id]
                            if parent is not None else global_bind[object_id])
            _matrix(local_matrix.tolist(), object_id + ': derived local')
            local[object_id] = local_matrix.tolist()
        result['raw_evidence'] = _retained(result['raw_evidence'])
        raw_digest = _digest(result['raw_evidence'])
        result['rest_global_transforms'] = {key: value.tolist() for key, value in sorted(global_bind.items())}
        result['rest_local_transforms'] = local
        result['provenance'] = {'source': 'native_mesh_dependency_inverse_bind', 'raw_evidence_digest': raw_digest,
                                'joint_witnesses': witnesses, 'required_object_ids': required,
                                'native_to_fbx_conversion': 'unobserved',
                                'bind_shape_used_for_native_rest': False,
                                'local_rule': 'inverse_parent_global_bind_times_child_global_bind'}
        result['status'] = 'observed' if required and len(local) == len(required) else 'partial'
    except (_Invalid, ValueError, TypeError, KeyError, OverflowError, np.linalg.LinAlgError) as exc:
        result['rest_global_transforms'] = {}
        result['rest_local_transforms'] = {}
        result['provenance'] = {}
        result['status'] = 'unobserved'
        result['errors'].append({'code': getattr(exc, 'code', 'BIND_PROJECTION_INVALID'),
                                 'detail': str(exc)[:1000]})
        result['unobserved'] = [{'object_id': key, 'reason': 'BIND_EVIDENCE_REJECTED'} for key in sorted(required)]
        result['raw_evidence'] = _retained(result['raw_evidence'])
    return result


def read_native_bind_rest(scene, required_object_ids):
    """Read a compact native projection, then call read_bind_rest.

    Only Basic parents, MeshObject links/assets/diagnostic bindShapeMatrix and raw
    inverse bind matrices are read. No frame is changed, no update is run, and
    no mesh vertices, weights or animation frames are enumerated.
    """
    result = _empty()
    projection = {'objects': [], 'assets': [], 'data': []}
    requested = []
    try:
        if not isinstance(required_object_ids, (list, tuple, set, frozenset)) or len(required_object_ids) > MAX_OBJECTS:
            raise _Invalid('BIND_RESOURCE_OR_SHAPE_INVALID', 'required object IDs')
        requested = [_identity(value, 'required object') for value in required_object_ids]
        if len(set(requested)) != len(requested):
            raise _Invalid('BIND_DUPLICATE_REFERENCE', 'required object IDs')
        from . import runtime as rt
        domain = rt._domain_scene(scene)
        if domain is None:
            raise _Invalid('BIND_NATIVE_SCENE_UNAVAILABLE', 'No native domain scene')
        mv, bv, dv = domain.model_viewer(), domain.behaviour_viewer(), domain.data_viewer()
        am = domain.assets_manager()
        objects = list(mv.get_objects())
        if len(objects) > MAX_OBJECTS:
            raise _Invalid('BIND_RESOURCE_OR_SHAPE_INVALID', 'native objects')
        assets, datas = {}, {}
        total_links = total_matrices = 0

        def reference(identifier):
            return None if identifier.is_null() else str(identifier)

        for obj in objects:
            object_id = str(obj)
            row = {'id': object_id, 'behaviours': []}
            projection['objects'].append(row)
            for behaviour in bv.get_behaviours(obj):
                name = bv.get_behaviour_name(behaviour)
                if name not in ('Basic', 'MeshObject'):
                    continue
                entry = {'id': str(behaviour), 'name': name, 'properties': []}
                row['behaviours'].append(entry)
                fields = set(bv.get_behaviour_property_names(behaviour))
                for field, kind, getter in ([('parent', 'ObjectType', 'get_behaviour_object')] if name == 'Basic' else [
                        ('linked_objects', 'ObjectRangeType', 'get_behaviour_objects_range'),
                        ('mesh_dependency', 'AssetType', 'get_behaviour_asset')]):
                    if field not in fields:
                        raise _Invalid('BIND_PROPERTY_UNOBSERVED', object_id + ':' + field)
                    actual_kind = bv.get_property_type(behaviour, field).name
                    if actual_kind != kind:
                        raise _Invalid('BIND_PROPERTY_UNOBSERVED', object_id + ':' + field + ':' + actual_kind)
                    value = getattr(bv, getter)(behaviour, field)
                    if kind == 'ObjectRangeType':
                        values = list(value)
                        total_links += len(values)
                        if total_links > MAX_BIND_LINKS:
                            raise _Invalid('BIND_RESOURCE_OR_SHAPE_INVALID', 'linked objects')
                        encoded = [reference(item) for item in values]
                    else:
                        encoded = reference(value)
                    entry['properties'].append({'name': field, 'kind': kind, 'value': encoded})
                    if encoded is None:
                        continue  # Pure validation rejects null mesh/data refs; null parent is explicit root.
                    if kind == 'AssetType' and encoded not in assets:
                        asset = am.at(value)
                        if type(asset).__name__ != 'MeshDependency':
                            raise _Invalid('BIND_DEPENDENCY_UNOBSERVED', encoded)
                        matrices = asset.inverse_bind_matrices()
                        total_matrices += len(matrices)
                        if total_matrices > MAX_BIND_LINKS:
                            raise _Invalid('BIND_RESOURCE_OR_SHAPE_INVALID', 'inverse bind matrices')
                        assets[encoded] = {'id': encoded, 'kind': 'MeshDependency',
                                           'inverse_bind_matrices': [np.asarray(matrix).tolist() for matrix in matrices]}
                        projection['assets'].append(assets[encoded])
                if name == 'MeshObject' and 'bindShapeMatrix' in fields:
                    # Failure to observe an unrelated FBX conversion matrix
                    # must not invalidate native joint inverse-bind evidence.
                    shape_row = {'name': 'bindShapeMatrix', 'kind': None, 'value': None}
                    entry['properties'].append(shape_row)
                    try:
                        shape_row['kind'] = bv.get_property_type(behaviour, 'bindShapeMatrix').name
                        if shape_row['kind'] != 'DataType':
                            continue
                        shape_id = bv.get_behaviour_data(behaviour, 'bindShapeMatrix')
                        encoded = reference(shape_id)
                        shape_row['value'] = encoded
                        if encoded is None or encoded in datas:
                            continue
                        record = {'id': encoded}
                        datas[encoded] = record
                        projection['data'].append(record)
                        if not dv.has_data(shape_id):
                            raise _Invalid('BIND_SHAPE_UNOBSERVED', 'Missing shape data')
                        shape_data = dv.get_data(shape_id)
                        mode = shape_data.mode.name
                        record.update({'owner': str(shape_data.object_id), 'mode': mode})
                        if mode == 'Static':
                            record['values'] = [np.asarray(dv.get_data_value(shape_id)).tolist()]
                        elif mode == 'Animation':
                            frame = int(domain.get_current_frame(False))
                            record['sampled_values'] = [{'frame': frame,
                                'value': np.asarray(dv.get_data_value(shape_id, frame)).tolist()}]
                        else:
                            raise _Invalid('BIND_SHAPE_UNOBSERVED', 'Unsupported shape data mode:' + mode)
                    except Exception as exc:
                        shape_row['observation_error'] = {'code': getattr(exc, 'code', 'BIND_SHAPE_UNOBSERVED'),
                                                          'detail': str(exc)[:1000]}
        return read_bind_rest(projection, requested)
    except Exception as exc:
        # Native bindings can raise SDK-specific exception types. Never convert
        # a failed compact read into a successful partial mesh capture.
        result['errors'].append({'code': getattr(exc, 'code', 'BIND_NATIVE_READ_UNAVAILABLE'),
                                 'detail': str(exc)[:1000]})
        result['raw_evidence']['compact_projection'] = _retained(projection)
        result['unobserved'] = [{'object_id': str(key), 'reason': 'BIND_NATIVE_READ_UNAVAILABLE'}
                                for key in requested]
        return result
