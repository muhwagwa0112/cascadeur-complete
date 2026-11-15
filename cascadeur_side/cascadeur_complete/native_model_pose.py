"""Observed model pose for the privately qualified independent Transform only.

Official Transform.Set/Go To Model Pose commands store/restore the three
Node3d.model_local_* properties. These are source model-pose observations, not
mesh inverse-bind evidence, FBX defaults or evaluated animation samples.
No coordinate or physical-unit conversion is performed here.
"""
from __future__ import annotations

import copy


def read_independent_model_pose_rest(projection, required_object_ids):
    """Read an exact complete native projection; never qualifies a scene/adapter.

    Returns native scene-local/global rigid 4x4 matrices, parent IDs, raw evidence
    and distinct ``native_node3d_model_pose`` provenance. The caller must bind
    the projection to its current source before issuing any observation. Missing
    qualification, scope or properties raise ValueError, with no default rest.
    """
    import numpy as np
    from . import guarded_runtime as guards
    from .native_interpolation_qualification import independent_projection_identity, qualification

    if (not isinstance(required_object_ids, (tuple, list)) or len(required_object_ids) != 1
            or not isinstance(required_object_ids[0], str) or not required_object_ids[0]):
        raise ValueError('MODEL_POSE_SCOPE_UNSUPPORTED: exact one-object scope required')
    identifier = required_object_ids[0]
    if (not isinstance(projection, dict)
            or not independent_projection_identity(projection, identifier)):
        raise ValueError('MODEL_POSE_SCOPE_UNQUALIFIED: privately qualified independent Transform required')
    model_qualification = qualification()
    if model_qualification is None:
        raise ValueError('MODEL_POSE_SCOPE_UNQUALIFIED: independent qualification is stale')
    objects = projection['objects']
    if len(objects) != 1 or objects[0]['id'] != identifier:
        raise ValueError('MODEL_POSE_SCOPE_UNSUPPORTED: complete parentless one-object projection required')
    behaviours = objects[0]['behaviours']
    nodes = [row for row in behaviours if row['name'] == 'Node3d']
    parents = [prop for row in behaviours if row['name'] == 'Basic'
               for prop in row['properties'] if prop['name'] == 'parent']
    if (len(nodes) != 1 or len(parents) != 1 or parents[0]['kind'] != 'ObjectType'
            or parents[0]['value'] is not None):
        raise ValueError('MODEL_POSE_PARENT_UNVERIFIED: unique observed Basic root and Node3d required')
    data = {row['id']: row for row in projection['data']}
    if len(data) != len(projection['data']):
        raise ValueError('MODEL_POSE_DATA_AMBIGUOUS: duplicate native data IDs')
    properties = nodes[0]['properties']
    evidence, values, linked = {}, {}, set()
    for name, size in (('model_local_position', 3), ('model_local_rotation', 4), ('model_local_scale', 3)):
        found = [prop for prop in properties if prop['name'] == name]
        if (len(found) != 1 or found[0]['kind'] != 'DataType'
                or not isinstance(found[0]['value'], str) or not found[0]['value']):
            raise ValueError('MODEL_POSE_PROPERTY_UNOBSERVED: '+name)
        data_id = found[0]['value']
        row = data.get(data_id)
        if (data_id in linked or row is None or row.get('owner') != identifier
                or row.get('mode') != 'Static' or not isinstance(row.get('values'), list)
                or len(row['values']) != 1):
            raise ValueError('MODEL_POSE_DATA_UNOBSERVED: distinct owned Static value required for '+name)
        linked.add(data_id)
        raw = np.asarray(row['values'][0])
        allowed_shapes = ((3,), (3, 1)) if size == 3 else ((4,),)
        if (raw.shape not in allowed_shapes or raw.dtype.kind not in 'iuf'
                or not np.isfinite(raw).all()):
            raise ValueError('MODEL_POSE_VALUE_INVALID: '+name)
        values[name] = raw.astype(float).reshape(size)
        evidence[name] = {'behaviour_id': nodes[0]['id'], 'property': copy.deepcopy(found[0]),
                          'data': copy.deepcopy(row)}
    if not np.array_equal(values['model_local_scale'], np.ones(3)):
        raise ValueError('MODEL_POSE_SCALE_UNSUPPORTED: exact observed unit scale required')
    quaternion = values['model_local_rotation']
    norm = float(np.linalg.norm(quaternion))
    if abs(norm - 1.) > 1e-6:
        raise ValueError('MODEL_POSE_ROTATION_INVALID: normalized native wxyz required')
    w, x, y, z = quaternion / norm
    matrix = np.eye(4)
    matrix[:3, :3] = [[1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)],
                      [2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w)],
                      [2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y)]]
    matrix[:3, 3] = values['model_local_position']
    raw_evidence = {'object_id': identifier, 'parent_property': copy.deepcopy(parents[0]),
                    'model_pose_properties': evidence, 'projection_digest': guards.digest(projection)}
    return {'status': 'observed', 'coordinate_space': 'cascadeur_scene', 'units': 'native_scene_units',
            'rest_local_transforms': {identifier: matrix.tolist()},
            'rest_global_transforms': {identifier: matrix.tolist()}, 'parent_ids': {identifier: None},
            'raw_evidence': raw_evidence, 'errors': [], 'unobserved': [],
            'provenance': {'source': 'native_node3d_model_pose',
                'scope': 'privately_qualified_independent_parentless_transform',
                'independent_qualification_digest': guards.digest(model_qualification),
                'raw_evidence_digest': guards.digest(raw_evidence),
                'coordinate_space': 'cascadeur_scene', 'units': 'native_scene_units',
                'rotation_order': 'wxyz', 'quaternion_normalized_for_matrix': bool(norm != 1.),
                'mesh_inverse_bind_observed': False, 'fbx_static_default_equality': 'unobserved',
                'physical_metadata_verified': False}}
