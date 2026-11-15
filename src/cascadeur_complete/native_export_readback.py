"""Host-side actual FBX conformance for a native qualification observation.

This validates artifact bytes, not the provenance of a supplied observation.
The runtime separately accepts only its own in-memory completion observation.
No result from this module registers or enables a native adapter.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from types import SimpleNamespace

from .export_models import ArtifactRef, ExportExpectation, ExportProfile
from .export_publisher import canonical_digest
from .fbx_validation import FbxError, ParseLimits, properties, read_fbx_structure, timebase, validate_fbx_structure


def readback_native_export(artifact: ArtifactRef, profile: ExportProfile, expected: ExportExpectation,
                           completion_observation: dict, *, parse_limits: ParseLimits | None = None):
    artifact = ArtifactRef.model_validate(artifact)
    profile = ExportProfile.model_validate(profile)
    expected = ExportExpectation.model_validate(expected)
    return _readback(artifact, profile, expected, completion_observation, parse_limits=parse_limits)


def _readback(artifact, profile, expected, completion_observation, *, parse_limits=None):
    observed = completion_observation
    actual_artifact = observed.get('artifact', {})
    if (observed.get('native_completion') != 'observed' or observed.get('profile_digest') != canonical_digest(profile)
            or actual_artifact.get('sha256') != artifact.sha256 or actual_artifact.get('bytes') != artifact.bytes
            or actual_artifact.get('path') != artifact.path or expected.settings_digest != canonical_digest(profile)):
        raise ValueError('NATIVE_EXPORT_OBSERVATION_MISMATCH')
    document = read_fbx_structure(artifact.path, parse_limits)
    if document.sha256 != artifact.sha256 or document.byte_length != artifact.bytes:
        raise ValueError('NATIVE_EXPORT_ARTIFACT_CHANGED')
    validation = validate_fbx_structure(document, profile, expected)
    if not validation.ok:
        return {'status': validation.status, 'artifact_sha256': artifact.sha256,
                'reason_codes': list(validation.reason_codes), 'structure': validation.model_dump(mode='json')}
    globals_ = [node for node in document.nodes if node.name == 'GlobalSettings']
    objects = [node for node in document.nodes if node.name == 'Objects']
    if len(globals_) != 1 or len(objects) != 1:
        raise FbxError('FBX_NODE_MISSING', 'Unique native export metadata required')
    settings = properties(globals_[0])
    takes = []
    for node in objects[0].children:
        if node.name == 'AnimationStack':
            takes.append({'name': str(node.properties[1]).split('\x00', 1)[0].removeprefix('AnimationStack::'),
                          'properties': properties(node)})
    return {'schema_version': 1, 'status': 'pass', 'artifact_sha256': artifact.sha256,
            'artifact_bytes': artifact.bytes, 'profile_digest': canonical_digest(profile),
            'profile_contract_digest': observed['profile_contract_digest'],
            'completion_observation_digest': canonical_digest(observed),
            'fbx_version': document.version, 'timebase': timebase(document),
            'actual_global_settings': settings, 'actual_takes': takes,
            'structure': validation.model_dump(mode='json'), 'quality': 'not_evaluated'}


def qualification_readback(payload: dict):
    """Structural setup only: never invents a motion capture or runtime quality.

    Discovery learns the SDK's unsupported getters from actual artifact bytes.
    The second export must then match that explicit contract independently.
    """
    artifact = ArtifactRef.model_validate(payload['artifact'])
    if payload['mode'] == 'discover':
        document = read_fbx_structure(artifact.path, ParseLimits(max_file_bytes=64 * 1024**2))
        if document.sha256 != artifact.sha256 or document.byte_length != artifact.bytes:
            raise ValueError('NATIVE_EXPORT_ARTIFACT_CHANGED')
        globals_ = [n for n in document.nodes if n.name == 'GlobalSettings']
        objects = [n for n in document.nodes if n.name == 'Objects']
        if len(globals_) != 1 or len(objects) != 1:
            raise ValueError('NATIVE_EXPORT_METADATA_UNAVAILABLE')
        settings = properties(globals_[0])
        stacks = [n for n in objects[0].children if n.name == 'AnimationStack']
        if len(stacks) != 1 or len(stacks[0].properties) < 2:
            raise ValueError('NATIVE_EXPORT_SINGLE_TAKE_UNVERIFIED')
        take = str(stacks[0].properties[1]).split('\x00', 1)[0].removeprefix('AnimationStack::')
        if payload['take_readback'] != [take]:
            raise ValueError('NATIVE_EXPORT_TAKE_READERS_DISAGREE')
        axes = {key: settings[field] for key, field in (
            ('up_axis', 'UpAxis'), ('up_sign', 'UpAxisSign'), ('front_axis', 'FrontAxis'),
            ('front_sign', 'FrontAxisSign'), ('coord_axis', 'CoordAxis'), ('coord_sign', 'CoordAxisSign'))}
        if axes['up_axis'] != 1 or axes['up_sign'] != 1:
            raise ValueError('NATIVE_EXPORT_APPLIED_UP_AXIS_MISMATCH')
        scale = settings['UnitScaleFactor']
        if type(scale) not in (int, float) or not math.isfinite(scale) or scale <= 0:
            raise ValueError('NATIVE_EXPORT_UNITS_UNAVAILABLE')
        count = payload['frame_count']
        if type(count) is not int or not 1 <= count <= 2001:
            raise ValueError('NATIVE_EXPORT_RANGE_UNSUPPORTED')
        profile = ExportProfile(character_ref='disposable-independent-transform',
            skeleton_map=[{'role': 'qualification_transform', 'source_id': payload['source_id'],
                           'node_path': payload['node_path'], 'parent_path': None}],
            take_name=take, first_frame=0, last_frame=count - 1, fps_num=30, fps_den=1,
            time_origin='zero', axes=axes, metres_per_export_unit=scale / 100,
            bake='dense', include_mesh=False, required_channels=[],
            root_motion={'node_path': payload['node_path'], 'mode': 'preserve_world'},
            target_adapter='native_qualification_only', target_adapter_fingerprint='unavailable',
            target_import_settings_digest='unavailable', destination=str(Path(artifact.path).parent / 'never-published.fbx'))
        return {'status': 'discovered', 'profile': profile.model_dump(mode='json'),
                'actual_global_settings': settings, 'quality': 'not_evaluated'}
    if payload['mode'] != 'validate':
        raise ValueError('NATIVE_EXPORT_READBACK_MODE_UNSUPPORTED')
    profile = ExportProfile.model_validate(payload['profile'])
    # Only the structural validator consumes this object. It cannot satisfy the
    # typed ExportExpectation needed by target roundtrip or publication.
    expected = SimpleNamespace(settings_digest=canonical_digest(profile),
        time_s=tuple(frame * profile.fps_den / profile.fps_num
                     for frame in range(profile.first_frame, profile.last_frame + 1)),
        parent_paths={bone.node_path: bone.parent_path for bone in profile.skeleton_map})
    return _readback(artifact, profile, expected, payload['completion_observation'],
                     parse_limits=ParseLimits(max_file_bytes=64 * 1024**2))


def _main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', required=True)
    parser.add_argument('--output', required=True)
    options = parser.parse_args()
    source, target = Path(options.manifest), Path(options.output)
    if (not source.is_absolute() or not target.is_absolute() or source.parent != target.parent
            or source.is_symlink() or source.stat().st_size > 4 * 1024**2 or target.exists()):
        raise ValueError('NATIVE_EXPORT_READBACK_PATH_UNAVAILABLE')
    try:
        result = qualification_readback(json.loads(source.read_text(encoding='utf-8')))
    except Exception as exc:
        result = {'status': 'unsupported', 'reason_codes': [getattr(exc, 'code', type(exc).__name__)],
                  'detail': str(exc)[:2000], 'quality': 'not_evaluated'}
    encoded = json.dumps(result, allow_nan=False).encode('utf-8')
    if len(encoded) > 4 * 1024**2:
        raise ValueError('NATIVE_EXPORT_READBACK_BUDGET_EXCEEDED')
    with target.open('xb') as stream:
        stream.write(encoded)


if __name__ == '__main__':
    _main()
