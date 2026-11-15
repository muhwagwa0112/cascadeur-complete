"""Couple real export qualification to the guarded recipe export entry point."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from . import guarded_runtime as guards
from .native_scene_adapter import NativeSceneAdapter


class NativeExportAdapter(NativeSceneAdapter):
    def __init__(self, evidence_bytes, evidence_path):
        super().__init__(evidence_bytes, evidence_path)
        material = json.loads(evidence_bytes)
        self.export_settings_readback = material['export_settings_readback']
        self.export_observation = material['native_export_observation']
        self.verification.update(
            export_completion_observation_digest=guards.digest(self.export_observation),
            export_settings_readback_digest=guards.digest(self.export_settings_readback))

    def _scope(self, scene, scope):
        from . import runtime as rt
        from .native_export import profile_contract, empty_selection_observation
        from .native_interpolation_qualification import independent_projection_identity
        if Path(self.verification['evidence_path']).read_bytes() != self.evidence_bytes:
            raise ValueError('NATIVE_EXPORT_ADAPTER_UNVERIFIED: qualification bytes changed')
        arguments = scope.get('operation_arguments')
        if scope.get('operation_name') != 'io.export_fbx' or not isinstance(arguments, dict):
            raise ValueError('BINDING_UNAVAILABLE: export operation required')
        profile = arguments.get('export_profile')
        if (not isinstance(profile, dict) or arguments.get('export_profile_digest') != guards.digest(profile)
                or guards.digest(profile_contract(profile)) != self.export_observation['profile_contract_digest']):
            raise ValueError('NATIVE_EXPORT_PROFILE_UNQUALIFIED: exact observed settings contract required')
        projection = self.read_scene(scene)
        selection_before = empty_selection_observation(scene)
        requested = sorted(row['source_id'] for row in profile['skeleton_map'])
        if (len(requested) != 1
                or not independent_projection_identity(projection, requested[0])
                or projection['frames'] != profile['last_frame'] + 1):
            raise ValueError('NATIVE_EXPORT_SCOPE_UNQUALIFIED: independent profile object and interval required')
        # The qualification fixture proves independent transforms, not unknown
        # controller graphs, parenting, rotational interpolation or skinning.
        data = {row['id']: row for row in projection['data']}
        for row in projection['objects']:
            names = {item['name'] for item in row['behaviours']}
            if names != {'Basic', 'Node3d', 'Transform', 'FbxExport'}:
                raise ValueError('NATIVE_EXPORT_SCOPE_UNQUALIFIED: independent native Transform closure required')
            behaviours = {item['name']: item for item in row['behaviours']}
            basic = {item['name']: item for item in behaviours['Basic']['properties']}
            if basic.get('parent', {}).get('value') is not None:
                raise ValueError('NATIVE_EXPORT_SCOPE_UNQUALIFIED: parented model not qualified')
            transform = {item['name']: item for item in behaviours['Transform']['properties']}
            for name in ('local_rotation', 'global_rotation', 'local_scale'):
                link = transform.get(name, {}).get('value')
                channel = data.get(link)
                if channel is None or not channel['values'] or any(value != channel['values'][0] for value in channel['values']):
                    raise ValueError('NATIVE_EXPORT_SCOPE_UNQUALIFIED: rotation/scale animation not qualified')
                import numpy as np
                actual = np.asarray(channel['values'][0], dtype=float).reshape(-1)
                expected = np.asarray([1., 1., 1.] if name == 'local_scale' else [1., 0., 0., 0.])
                if actual.shape != expected.shape or not np.allclose(actual, expected, rtol=0, atol=1e-7):
                    raise ValueError('NATIVE_EXPORT_SCOPE_UNQUALIFIED: identity rotation and unit scale required')
        if projection['assets'] or projection['cycles']:
            raise ValueError('NATIVE_EXPORT_SCOPE_UNQUALIFIED: assets/cycles outside fixture domain')
        return arguments, profile, projection, requested, selection_before

    def required_scope(self, scene, scope):
        from .native_adapters import _WORKSPACES
        from .native_export import SELECTION_POLICY
        arguments, profile, projection, selected, selection_before = self._scope(scene, scope)
        result = {'operation_name': 'io.export_fbx', 'operation_arguments': arguments,
                'operation_arguments_digest': guards.digest(arguments), 'adapter_id': 'native-selected-export-v1',
                'object_ids': [row['id'] for row in projection['objects']],
                'layer_ids': [row['id'] for row in projection['layers']],
                'frames': [0, projection['frames'] - 1], 'export_selected_ids': selected,
                'export_selection_before': selection_before, 'export_selection_policy': SELECTION_POLICY,
                'profile': profile, 'input_files': []}
        manifest = _WORKSPACES.get(guards.scene_instance(scene)['scene_instance_id'])
        if manifest is not None:
            result['snapshot_manifest'] = manifest
        return result

    def capture(self, scene, scope):
        _, _, projection, _, selection_before = self._scope(scene, scope)
        return {'coverage_complete': True,
                'authored_projection': {'native': projection, 'export_selection_before': selection_before},
                'sample_projection': projection}

    def execute(self, scene, arguments, request):
        from .native_export import execute_export
        from .native_motion_capture import _evaluation
        # A terminal evaluation receipt is required in production; diagnostic
        # fixture completion alone does not issue an evaluated motion capture.
        _evaluation(scene, self.read_scene(scene))
        return execute_export(scene, arguments, request, arguments['export_profile'], adapter=self)


def qualify_and_register_export():
    """Explicit setup: real base reader qualification and two actual exports."""
    from .native_export import qualify_export_disposable
    guards.assert_loaded_package()
    base = guards._ADAPTERS.get('safety.checkpoint')
    if not isinstance(base, NativeSceneAdapter) or isinstance(base, NativeExportAdapter):
        raise ValueError('SOURCE_READER_UNVERIFIED: qualify the complete scene checkpoint reader first')
    base_path = base.verification.get('evidence_path')
    if not base_path or Path(base_path).read_bytes() != base.evidence_bytes:
        raise ValueError('SOURCE_READER_UNVERIFIED: immutable base evidence required')
    observed = qualify_export_disposable(base, animated=True)
    if observed['reason_codes'] != ['TARGET_ROUNDTRIP_UNVERIFIED']:
        raise ValueError('NATIVE_EXPORT_ADAPTER_UNVERIFIED: animated conformance missing')
    from .native_export import SELECTION_POLICY
    transition = observed['native_export_observation'].get('selection_transition', {})
    if (transition.get('policy') != SELECTION_POLICY or transition.get('status') != 'observed_restored'
            or transition.get('before', {}).get('ids') != []
            or transition.get('before') != transition.get('after')
            or transition.get('during', {}).get('ids') != transition.get('export_selected_ids')
            or transition.get('authored_projection_before_digest') != transition.get('authored_projection_after_digest')):
        raise ValueError('NATIVE_EXPORT_ADAPTER_UNVERIFIED: empty selection transition/restoration unobserved')
    material = {**observed, 'operations': ['io.export_fbx'],
                'base_reader_evidence_sha256': hashlib.sha256(base.evidence_bytes).hexdigest()}
    path = Path(observed['retained_directory']) / 'qualification.json'
    encoded = json.dumps(material, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    with path.open('xb') as stream:
        stream.write(encoded)
    adapter = NativeExportAdapter(encoded, path)
    guards.register_adapter('io.export_fbx', adapter)
    return {'adapter_id': 'native-selected-export-v1', 'qualified_operations': ['io.export_fbx'],
            'evidence_path': str(path), 'evidence_sha256': hashlib.sha256(encoded).hexdigest(),
            'quality': 'not_evaluated', 'target_roundtrip': 'unverified'}
