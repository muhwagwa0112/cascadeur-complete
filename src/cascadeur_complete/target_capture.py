"""Decode observed target motion and bind canonical arrays to immutable evidence."""
from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
from scipy.spatial.transform import Rotation

from .capture import canonical_digest as capture_digest
from .export_models import ExportExpectation
from .export_publisher import canonical_digest, write_immutable_json
from .fbx_validation import file_sha256
from .motion_context import MotionContext, SampleBatch, validate_samples
from .motion_quality import validate_quality_policy, validate_export_roundtrip
from .models import ResultEnvelope, ExecutionMode


def _retain_json(path, payload):
    if path.exists():
        if path.is_symlink() or json.loads(path.read_text(encoding='utf-8')) != payload:
            raise ValueError('TARGET_PROVENANCE_RECORD_CONFLICT')
    else:
        write_immutable_json(path,payload)


def _rotation(q):
    q = np.asarray(q, dtype=float)
    if q.shape[-1] != 4 or not np.isfinite(q).all() or np.any(np.abs(np.linalg.norm(q, axis=-1)-1)>1e-5):
        raise ValueError("EXPORT_REST_OR_ROTATION_INVALID")
    return Rotation.from_quat(q[..., [1,2,3,0]])


def _wxyz(rotation):
    return rotation.as_quat()[..., [3,0,1,2]]


def _require_roundtrip_coverage(before, original, rig, profile):
    """Require target observations for every channel used by original intent.

    A source dependency is not a target observation. In particular, do not fill
    an omitted target role from the immutable source just to complete a metric.
    """
    mapped = {item.source_id for item in profile.skeleton_map}
    required = (set(rig.role_ids.values())
                | (set(original.object_ids) - set(rig.writable_ids)))
    missing = required - mapped
    if missing:
        raise ValueError('EXPORT_INTENT_TARGET_COVERAGE_UNAVAILABLE: '+', '.join(sorted(missing)))
    if (before.space != 'global' or original.space != 'global'
            or not np.array_equal(before.context.frames, original.context.frames)
            or not np.array_equal(before.context.time_s, original.context.time_s)):
        raise ValueError('EXPORT_ORIGINAL_REFERENCE_GRID_MISMATCH')
    for batch in (before, original):
        validate_samples(batch, {key: ('position', 'rotation') for key in required})


def _rest_globals(rig, before, supplied=None):
    if supplied is not None:
        matrices = {key: np.asarray(value, dtype=float) for key,value in supplied.items()}
    else:
        matrices, visiting = {}, set()
        def resolve(key):
            if key in matrices:
                return matrices[key]
            if key in visiting or key not in rig.parent_ids:
                raise ValueError("EXPORT_REST_PARENT_CLOSURE_UNAVAILABLE")
            visiting.add(key)
            role = next((role for role, value in rig.role_ids.items() if value==key), None)
            value = rig.rest_local_transforms.get(key, rig.rest_local_transforms.get(role))
            local = np.asarray(value, dtype=float)
            if local.shape != (4,4):
                raise ValueError("EXPORT_OBSERVED_REST_MATRIX_UNAVAILABLE")
            parent = rig.parent_ids[key]
            result = (resolve(parent) @ local) if parent is not None else local
            matrices[key] = result
            visiting.remove(key)
            return result
        for key in rig.role_ids.values():
            resolve(key)
        basis = before.context.scene_to_solver_basis
        for key, value in tuple(matrices.items()):
            result = value.copy()
            result[:3,:3] = basis @ value[:3,:3] @ basis.T
            result[:3,3] = basis @ value[:3,3] * before.context.metres_per_scene_unit
            matrices[key] = result
    for value in matrices.values():
        if (value.shape!=(4,4) or not np.isfinite(value).all() or not np.allclose(value[3], [0,0,0,1],atol=1e-9)
                or not np.allclose(value[:3,:3].T@value[:3,:3],np.eye(3),atol=1e-7)
                or not np.isclose(np.linalg.det(value[:3,:3]),1,atol=1e-7)):
            raise ValueError("EXPORT_NONRIGID_REST_UNSUPPORTED")
    return matrices


def make_export_expectation(before_export, profile, rig, *, original_reference, intent, policy,
                            reference_digests=None, rest_global_matrices=None):
    validate_samples(before_export,{key:('position','rotation') for key in before_export.object_ids})
    if before_export.space!="global" or original_reference is None or not before_export.source_binding:
        raise ValueError("EXPORT_ACTUAL_GLOBAL_REFERENCE_UNAVAILABLE")
    _require_roundtrip_coverage(before_export, original_reference, rig, profile)
    validate_quality_policy(policy,rig,intent,profile.include_mesh,capture=before_export)
    frames=before_export.context.frames
    if (frames[0]!=profile.first_frame or frames[-1]!=profile.last_frame
            or len(frames)!=profile.last_frame-profile.first_frame+1 or np.any(np.diff(frames)!=1)
            or before_export.context.fps_num*profile.fps_den!=profile.fps_num*before_export.context.fps_den):
        raise ValueError("EXPORT_CAPTURE_INTERVAL_MISMATCH")
    rest=_rest_globals(rig,before_export,rest_global_matrices)
    positions, rotations, rest_q, rest_p, parents = {},{},{},{},{}
    by_id={item.source_id:item.node_path for item in profile.skeleton_map}
    for item in profile.skeleton_map:
        key,path=item.source_id,item.node_path
        if rig.role_ids.get(item.role)!=key or key not in before_export.object_ids or key not in rig.parent_ids:
            raise ValueError("EXPORT_RIG_MAPPING_AMBIGUOUS")
        parent=rig.parent_ids[key]
        if parent is not None and parent not in by_id:
            raise ValueError("EXPORT_PARENT_CLOSURE_UNAVAILABLE")
        if by_id.get(parent)!=item.parent_path:
            raise ValueError("EXPORT_PARENT_MAPPING_MISMATCH")
        if not np.asarray(before_export.channel_valid[key]).all():
            raise ValueError("EXPORT_CAPTURE_CHANNEL_UNOBSERVED")
        rest_rotation=Rotation.from_matrix(rest[key][:3,:3])
        rest_q[path]=_wxyz(rest_rotation).tolist()
        rest_p[path]=rest[key][:3,3].tolist()
        positions[path]=before_export.position_m[key].tolist()
        rotations[path]=_wxyz(_rotation(before_export.rotation_wxyz[key])*rest_rotation.inv()).tolist()
        parents[path]=item.parent_path
    refs=dict(reference_digests or {})
    refs['original_reference']=capture_digest(original_reference.as_dict())
    refs['rig_profile']=capture_digest(asdict(rig))
    roundtrip={'position_readback_m','rotation_readback_rad','duration_error_s'}
    if not roundtrip <= set(policy.required_metrics):
        raise ValueError('EXPORT_ROUNDTRIP_METRICS_REQUIRED: '+', '.join(sorted(roundtrip)))
    return ExportExpectation(source_capture_digest=capture_digest(before_export.as_dict()),
        intent_digest=canonical_digest(intent),quality_policy_digest=canonical_digest(policy),
        source_binding_digest=canonical_digest(before_export.as_dict()['source_binding']),settings_digest=canonical_digest(profile),
        reference_digests=refs,time_s=before_export.context.time_s.tolist(),position_m=positions,
        rotation_delta_wxyz=rotations,rest_rotation_wxyz=rest_q,rest_position_m=rest_p,
        parent_paths=parents,required_metrics=policy.required_metrics,runtime_quality='pass')


@dataclass(frozen=True)
class RoundtripQualityContext:
    before_export: SampleBatch
    original_reference: SampleBatch
    rig: object
    intent: object
    policy: object
    supports: object = None
    mesh_evaluator: object = None


def roundtrip_quality_context(before_export, original_reference, rig, intent, policy, supports=None, mesh_evaluator=None):
    return RoundtripQualityContext(before_export,original_reference,rig,intent,policy,supports,mesh_evaluator)


def decode_target_capture(raw, expected, profile, context, *, source_binding):
    settings=profile.target_import_settings
    if (settings is None or raw.get('space')!='global' or raw.get('units')!='metres'
            or raw.get('rotation_semantics')!='global_rest_delta'
            or raw.get('basis_digest')!=canonical_digest(settings.blender_to_canonical_basis)):
        raise ValueError('TARGET_CANONICAL_CONVENTION_UNVERIFIED')
    paths=set(expected.position_m)
    if (not np.array_equal(np.asarray(raw['time_s']),np.asarray(expected.time_s))
            or raw['parent_paths']!=expected.parent_paths):
        raise ValueError('TARGET_TIME_OR_PARENT_MISMATCH')
    for field in ('position_m','rotation_delta_wxyz','rest_rotation_wxyz','rest_position_m'):
        if set(raw.get(field,{}))!=paths or set(getattr(expected,field))!=paths:
            raise ValueError('TARGET_CAPTURE_REST_COVERAGE_UNVERIFIED')
    positions,rotations,valid={},{},{}
    for item in profile.skeleton_map:
        path,key=item.node_path,item.source_id
        target_rest=_rotation(raw['rest_rotation_wxyz'][path])
        source_rest=_rotation(expected.rest_rotation_wxyz[path])
        if (target_rest.inv()*source_rest).magnitude()>profile.tolerances.rotation_rad:
            raise ValueError('EXPORT_BIND_POSE_ROTATION_MISMATCH')
        target_position=np.asarray(raw['rest_position_m'][path],dtype=float)
        if (target_position.shape!=(3,) or not np.isfinite(target_position).all()
                or np.linalg.norm(target_position-np.asarray(expected.rest_position_m[path]))>profile.tolerances.position_m):
            raise ValueError('EXPORT_BIND_POSE_POSITION_MISMATCH')
        position=np.asarray(raw['position_m'][path],dtype=float)
        delta=_rotation(raw['rotation_delta_wxyz'][path])
        if position.shape!=(len(expected.time_s),3) or not np.isfinite(position).all() or delta.as_quat().shape!=(len(expected.time_s),4):
            raise ValueError('TARGET_CAPTURE_CHANNEL_COVERAGE')
        positions[key]=position
        rotations[key]=_wxyz(delta*target_rest)
        valid[key]=np.ones((len(expected.time_s),2),dtype=bool)
    target_context=MotionContext(context.frames,context.time_s,context.time_source,context.fps_num,context.fps_den,
        1.,np.asarray(settings.blender_to_canonical_basis),{'capture_kind':'target_actual',
        'source_grid_context_digest':capture_digest(context.as_dict()),'decoder':'blender_fbx_classic_v1',
        'basis_digest':raw['basis_digest'],'source_binding':source_binding})
    result=SampleBatch(target_context,tuple(positions),'global',positions,rotations,valid,source_binding)
    validate_samples(result,{key:('position','rotation') for key in result.object_ids})
    return result


class TargetCaptureEvidence:
    """Internal subprocess completion evidence; a wire boolean is never consulted."""
    def __init__(self, directory, key):
        if not isinstance(key,bytes) or len(key)<32:
            raise ValueError('TARGET_PROVENANCE_KEY_UNAVAILABLE')
        self.directory,self.key=Path(directory),key

    @classmethod
    def record(cls,directory,key,*,report_path,manifest,canonical):
        evidence=cls(directory,key)
        canonical_path=Path(directory)/'canonical-capture.json'
        _retain_json(canonical_path,canonical.as_dict())
        payload={'schema_version':1,'manifest_digest':canonical_digest(manifest),
                 'raw_report_sha256':file_sha256(report_path),'raw_report_path':str(report_path),
                 'canonical_file_sha256':file_sha256(canonical_path),'canonical_path':str(canonical_path),
                 'capture_digest':capture_digest(canonical.as_dict()),'artifact_sha256':manifest['artifact']['sha256'],
                 'profile_digest':canonical_digest(manifest['profile']),'nonce':manifest['nonce']}
        payload['mac']=hmac.new(key,canonical_digest(payload).encode(),hashlib.sha256).hexdigest()
        _retain_json(Path(directory)/'capture-provenance.json',payload)
        return evidence

    def verify(self,batch,digest):
        try:
            payload=json.loads((self.directory/'capture-provenance.json').read_text(encoding='utf-8'))
            mac=payload.pop('mac')
            valid=hmac.compare_digest(mac,hmac.new(self.key,canonical_digest(payload).encode(),hashlib.sha256).hexdigest())
            valid=valid and payload['capture_digest']==digest==capture_digest(batch.as_dict())
            valid=valid and Path(payload['raw_report_path']).parent==self.directory and Path(payload['canonical_path']).parent==self.directory
            valid=valid and not Path(payload['raw_report_path']).is_symlink() and not Path(payload['canonical_path']).is_symlink()
            valid=valid and file_sha256(payload['raw_report_path'])==payload['raw_report_sha256']
            valid=valid and file_sha256(payload['canonical_path'])==payload['canonical_file_sha256']
            valid=valid and capture_digest(json.loads(Path(payload['canonical_path']).read_text(encoding='utf-8')))==digest
            valid=valid and canonical_digest(json.loads((self.directory/'manifest.json').read_text(encoding='utf-8')))==payload['manifest_digest']
        except (OSError,ValueError,KeyError,TypeError):
            valid=False
        return ResultEnvelope(ok=bool(valid),feature_id='export.target_capture',execution_mode=ExecutionMode.EXTERNAL,
                              result={'capture_digest':digest} if valid else {})

    def bind_geometry(self,manifest,batch):
        if not self.verify(batch,capture_digest(batch.as_dict())).ok:
            raise ValueError('TARGET_CAPTURE_PROVENANCE_CHANGED')
        payload={'manifest':manifest,'capture_digest':capture_digest(batch.as_dict()),
                 'raw_report_sha256':file_sha256(self.directory/'capture.json')}
        payload['mac']=hmac.new(self.key,canonical_digest(payload).encode(),hashlib.sha256).hexdigest()
        _retain_json(self.directory/'geometry-provenance.json',payload)

    def verify_geometry(self,manifest,digest):
        try:
            payload=json.loads((self.directory/'geometry-provenance.json').read_text(encoding='utf-8'))
            mac=payload.pop('mac')
            valid=hmac.compare_digest(mac,hmac.new(self.key,canonical_digest(payload).encode(),hashlib.sha256).hexdigest())
            valid=valid and canonical_digest(payload['manifest'])==digest==canonical_digest(manifest)
            valid=valid and payload['raw_report_sha256']==file_sha256(self.directory/'capture.json')
            valid=valid and payload['capture_digest']==manifest['motion_capture_digest']
        except (OSError,ValueError,KeyError,TypeError):
            valid=False
        return ResultEnvelope(ok=bool(valid),feature_id='export.target_geometry',execution_mode=ExecutionMode.EXTERNAL,
                              result={'geometry_digest':digest} if valid else {})


def evaluate_target_capture(raw,expected,profile,quality_context,*,directory,key,report_path,manifest):
    if not isinstance(quality_context,RoundtripQualityContext):
        raise ValueError('ROUNDTRIP_QUALITY_CONTEXT_UNAVAILABLE')
    ctx=quality_context
    _require_roundtrip_coverage(ctx.before_export, ctx.original_reference, ctx.rig, profile)
    if (expected.source_capture_digest!=capture_digest(ctx.before_export.as_dict())
            or expected.reference_digests.get('original_reference')!=capture_digest(ctx.original_reference.as_dict())
            or expected.reference_digests.get('rig_profile')!=capture_digest(asdict(ctx.rig))
            or expected.intent_digest!=canonical_digest(ctx.intent) or expected.quality_policy_digest!=canonical_digest(ctx.policy)):
        raise ValueError('ROUNDTRIP_QUALITY_CONTEXT_STALE')
    if (canonical_digest(manifest['profile'])!=canonical_digest(profile)
            or canonical_digest(manifest.get('expected'))!=canonical_digest(expected)
            or manifest['report_path']!=str(report_path)):
        raise ValueError('TARGET_MANIFEST_CONTEXT_STALE')
    observed=json.loads(Path(report_path).read_text(encoding='utf-8'))
    if (canonical_digest(observed['capture'])!=canonical_digest(raw) or observed['nonce']!=manifest['nonce']
            or observed['artifact_sha256']!=manifest['artifact']['sha256']):
        raise ValueError('TARGET_REPORT_CHANGED')
    batch=decode_target_capture(raw,expected,profile,ctx.before_export.context,source_binding={
        'kind':'target_subprocess','nonce':manifest['nonce'],'artifact_sha256':manifest['artifact']['sha256'],
        'raw_report_sha256':file_sha256(report_path)})
    evidence=TargetCaptureEvidence.record(directory,key,report_path=report_path,manifest=manifest,canonical=batch)
    mesh_evaluator=None
    if profile.include_mesh:
        from itertools import combinations
        from .motion_geometry import ObservedSurfaceTrack
        from .motion_quality import actual_mesh_metrics
        if set(raw.get('mesh',{}))!=set(profile.mesh_refs) or not raw.get('mesh_skin_digest'):
            raise ValueError('TARGET_MESH_PROVENANCE_INCOMPLETE')
        tracks={name:ObservedSurfaceTrack(value['positions_m'],value['triangles'],context=batch.context,
                                          semantics=ctx.policy.collision_semantics)
                for name,value in raw['mesh'].items()}
        windows={name:track.windows for name,track in tracks.items()}
        geometry_manifest={'capture_kind':'target_actual','source_digest':expected.source_capture_digest,
            'successor_digest':capture_digest(batch.as_dict()),'completion_receipt_digest':file_sha256(report_path),
            'topology_digest':canonical_digest({name:value[0]['triangles_sha256'] for name,value in windows.items()}),
            'skin_digest':raw['mesh_skin_digest'],'context_digest':capture_digest(batch.context.as_dict()),
            'motion_capture_digest':capture_digest(batch.as_dict()),'frames':batch.context.frames.tolist(),
            'time_s':batch.context.time_s.tolist(),'windows':windows,'pairs':[list(pair) for pair in combinations(sorted(tracks),2)],
            'space':'global','units':'metres'}
        evidence.bind_geometry(geometry_manifest,batch)
        geometry={'manifest':geometry_manifest,'tracks':tracks}
        mesh_evaluator=lambda measured,rig,intent:actual_mesh_metrics(geometry,ctx.policy,verifier=evidence.verify_geometry)
    return validate_export_roundtrip(ctx.before_export,batch,profile,{key:key for key in batch.object_ids},ctx.intent,ctx.policy,
        rig=ctx.rig,original_reference=ctx.original_reference,supports=ctx.supports,capture_verifier=evidence.verify,
        mesh_evaluator=mesh_evaluator)
