"""Input discovery for the privately qualified parentless Transform domain.

This is structural ownership of one independent object, not anatomical rig
inference. Conversion parameters and physical metadata remain declarations.
"""
from __future__ import annotations

import json
import math


def read_independent_inputs(scene, arguments, object_id):
    from . import guarded_runtime as guards
    from .native_adapters import installed_build
    from .native_scene_reader import read_scene
    from .native_interpolation_qualification import qualification, independent_projection_identity
    from .native_model_pose import read_independent_model_pose_rest
    from .native_independent_position import NativeIndependentPositionAdapter

    proof = qualification()
    if proof is None:
        return None
    projection = read_scene(scene)
    if not independent_projection_identity(projection, object_id):
        return None
    first, last = arguments['frame_range']
    if last >= projection['frames']:
        raise ValueError('INVALID_POLICY: requested input interval exceeds native scene frames')
    rest = read_independent_model_pose_rest(projection, [object_id])
    obj = projection['objects'][0]
    nodes = {row['name']: row for row in obj['behaviours']}
    data = {row['id']: row for row in projection['data']}
    transform = {row['name']: row for row in nodes['Transform']['properties']}
    rotation_ids = {}
    for name in ('local_rotation', 'global_rotation'):
        prop = transform.get(name, {})
        row = data.get(prop.get('value'), {})
        if prop.get('kind') != 'DataType' or row.get('owner') != object_id or not row.get('values'):
            return None
        values = row['values']
        if any(not isinstance(q, list) or len(q) != 4
               or any(type(v) not in (int, float) or not math.isfinite(v) for v in q)
               or abs(sum(v*v for v in q)-1.) > 1e-5 for q in values):
            return None
        rotation_ids[name] = row['id']
    layers = [row for row in projection['layers'] if object_id in row['object_ids']]
    if len(layers) != 1:
        return None
    layer = layers[0]
    writable, writer_digest, writer_reason = False, None, 'POSITION_WRITER_UNQUALIFIED'
    adapter = guards._ADAPTERS.get('animation.position_keys_set')
    if type(adapter) is NativeIndependentPositionAdapter:
        try:
            # Re-derive the writer's real closure without dispatching a write.
            # A model proof alone does not establish a writable graph/key grid.
            position = data[transform['local_position']['value']]['values'][0]
            import numpy as np
            position = np.asarray(position, dtype=float).reshape(3).tolist()
            arguments_probe = {'space': 'local', 'writes': [
                {'id': object_id, 'frame': 0, 'position': position}]}
            adapter._inspect(scene, 'animation.position_keys_set', arguments_probe)
            writable, writer_digest, writer_reason = True, guards.digest(json.loads(adapter.evidence_bytes)), None
        except (ValueError, RuntimeError, TypeError, KeyError) as exc:
            writer_reason = str(exc)[:300]
    model_digest = guards.digest(proof)
    contract = {'kind': 'independent_parentless_transform_v1', 'object_id': object_id,
                'model_qualification_digest': model_digest,
                'joint_metadata_applicability': 'not_a_joint',
                'writer_qualification_digest': writer_digest}
    row = {'id': object_id, 'name': obj['name'], 'character_id': object_id,
           'ownership_candidates': [object_id], 'parent_id': None,
           'rest_local_transform': rest['rest_local_transforms'][object_id],
           'rest_local_transform_provenance': rest['provenance'],
           'rotation_channel_observed': True, 'rotation_data_ids': rotation_ids,
           'layer_id': layer['id'], 'writable': writable, 'derived': False}
    orientation = {'reader': 'private_independent_transform_channels_v1', 'status': 'observed',
                   'root_object_id': object_id, 'rotation_data_ids': rotation_ids,
                   'model_qualification_digest': model_digest}
    values = {'context': {'frames': list(range(first, last+1))}, 'objects': [row],
              'role_candidates': {'root': [object_id]}, 'root_rotation_id': object_id,
              'root_orientation_observation': orientation, 'layers': layers,
              'native_model_pose_rest': rest, 'profile_contract': contract,
              'controller_adapter_id': 'independent-parentless-position-v1' if writable else '',
              'mesh_ids': [], 'supports': {},
              'source_coverage': 'complete_native_projection_no_evaluation_refresh',
              'unobserved_fields': ['physical_fps', 'metres_per_scene_unit', 'scene_to_solver_basis',
                                    'support_evaluated_tracks'],
              'observation_warnings': ([] if writer_reason is None else [writer_reason])}
    provenance = {'objects': {'reader': 'complete_native_projection', 'build': installed_build(),
                             'ownership': 'privately_qualified_independent_parentless_transform'},
                  'role_candidates': {'authority': 'observed_parentless_independent_object',
                                      'anatomical_roles_inferred': False},
                  'root_rotation_id': orientation,
                  'rest_local_transforms': rest['provenance'],
                  'profile_contract': contract,
                  'context': {'frames': 'requested integer interval; physical metadata unobserved'}}
    # Reusable structure excludes animation samples, runtime proof UUIDs and
    # the full source projection digest. Stored model-pose bytes remain bound.
    rest_structure = {key: value for key, value in rest['raw_evidence'].items() if key != 'projection_digest'}
    structure = {'objects': [{'id': object_id, 'parent_id': None,
                              'behaviours': obj['behaviours']}],
                 'rest': rest_structure, 'domain': contract['kind']}
    source = {'projection': projection, 'frame_range': [first, last],
              'support_refs': arguments.get('support_refs', []),
              'runtime_epoch': guards.RUNTIME_EPOCH, 'model_qualification_digest': model_digest}
    return {'values': values, 'provenance': provenance,
            'source_fingerprint': guards.digest(source), 'rig_structure_fingerprint': guards.digest(structure),
            'evidence_ref': 'pending-native-registry:'+guards.digest(source)}
