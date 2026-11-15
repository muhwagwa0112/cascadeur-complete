"""R4 consumer decoding and native completion boundaries; no DCC is launched."""
import copy
import json
import time

import numpy as np
import pytest
from scipy.spatial.transform import Rotation

from cascadeur_complete.capture import canonical_digest
from cascadeur_complete.export_models import ArtifactRef, ExportProfile, PublishPermit, ValidationBundle, ValidationReport
from cascadeur_complete.export_publisher import ExportPublicationError, copy_exclusive, publish_verified, write_immutable_json
from cascadeur_complete.export_workflow import ExportStage, bind_export_stage, create_export_stage, seal_export
from cascadeur_complete.fbx_validation import file_sha256
from cascadeur_complete.motion_context import MotionContext, SampleBatch, RigProfile, IntentConstraints
from cascadeur_complete.motion_quality import QualityPolicy
from cascadeur_complete.target_capture import (TargetCaptureEvidence, decode_target_capture,
    evaluate_target_capture, make_export_expectation, roundtrip_quality_context)


def _inputs(tmp_path):
    context=MotionContext(np.arange(3),np.arange(3)/30,'fps',30,1,1.,np.eye(3),{'observed':'fixture'})
    rest=np.eye(4);rest[:3,:3]=Rotation.from_euler('z',90,degrees=True).as_matrix()
    child=np.eye(4);child[0,3]=1
    rig=RigProfile('rig','character',{'root':'1','tip':'2'},frozenset({'1','2'}),
        parent_ids={'1':None,'2':'1'},rest_local_transforms={'1':rest.tolist(),'2':child.tolist()})
    q=Rotation.from_matrix(rest[:3,:3]).as_quat()[[3,0,1,2]]
    before=SampleBatch(context,('1','2'),'global',{'1':np.zeros((3,3)),'2':np.tile([0,1,0],(3,1))},
        {key:np.tile(q,(3,1)) for key in ('1','2')},{key:np.ones((3,2),bool) for key in ('1','2')},
        {'binding':{'runtime_epoch':'observed-fixture'}})
    intent=IntentConstraints(editable_frames=(0,2),correction_envelope={'position_m':1e-7,'rotation_rad':1e-7})
    metrics=('duration_error_s','position_correction_m','rotation_correction_rad','root_preservation_m',
             'root_preservation_rad','correction_envelope_violation_count','bone_length_error_m',
             'position_readback_m','rotation_readback_rad')
    policy=QualityPolicy(profile_id='p',profile_revision='1',required_metrics=metrics,
        limits_si={name:0 if name=='correction_envelope_violation_count' else 1e-8 for name in metrics})
    profile=ExportProfile(character_ref='character',skeleton_map=[
        {'role':'root','node_path':'Root','source_id':'1'},
        {'role':'tip','node_path':'Root/Tip','parent_path':'Root','source_id':'2'}],take_name='Take',
        first_frame=0,last_frame=2,fps_num=30,axes={'up_axis':1,'up_sign':1,'front_axis':2,'front_sign':-1,'coord_axis':0,'coord_sign':1},
        metres_per_export_unit=1,root_motion={'node_path':'Root'},target_adapter='unavailable',
        target_import_settings={'blender_version':[4,5,0],'blender_to_canonical_basis':np.eye(3).tolist(),
                                'bone_mapping':{'Root':['Armature','Root'],'Root/Tip':['Armature','Root/Tip']}},
        target_adapter_fingerprint='unavailable',target_import_settings_digest='unavailable',destination=str(tmp_path/'out.fbx'))
    expected=make_export_expectation(before,profile,rig,original_reference=before,intent=intent,policy=policy)
    raw={name:expected.model_dump(mode='json')[name] for name in ('time_s','position_m','rotation_delta_wxyz',
        'parent_paths','rest_rotation_wxyz','rest_position_m')}
    raw['mesh']={}
    raw.update(space='global',units='metres',rotation_semantics='global_rest_delta',
               basis_digest=canonical_digest(profile.target_import_settings.blender_to_canonical_basis))
    return before,rig,intent,policy,profile,expected,raw


def test_actual_rest_delta_decode_and_original_intent_provenance(tmp_path):
    before,rig,intent,policy,profile,expected,raw=_inputs(tmp_path)
    decoded=decode_target_capture(raw,expected,profile,before.context,source_binding={'test':'observed'})
    np.testing.assert_allclose(decoded.rotation_wxyz['1'],before.rotation_wxyz['1'],atol=1e-12)
    bad=copy.deepcopy(raw);bad['rest_rotation_wxyz']['Root']=[1,0,0,0]
    with pytest.raises(ValueError,match='BIND_POSE_ROTATION'):
        decode_target_capture(bad,expected,profile,before.context,source_binding={})
    report_path=tmp_path/'capture.json'
    write_immutable_json(report_path,{'capture':raw,'nonce':'observed-process-nonce','artifact_sha256':'a'*64})
    manifest={'nonce':'observed-process-nonce','artifact':{'sha256':'a'*64},'profile':profile.model_dump(mode='json'),
              'expected':expected.model_dump(mode='json'),'report_path':str(report_path)}
    write_immutable_json(tmp_path/'manifest.json',manifest)
    quality=evaluate_target_capture(raw,expected,profile,roundtrip_quality_context(before,before,rig,intent,policy),
        directory=tmp_path,key=b'k'*32,report_path=report_path,manifest=manifest)
    assert quality.status=='pass' and quality.runtime_verified
    resumed=evaluate_target_capture(raw,expected,profile,roundtrip_quality_context(before,before,rig,intent,policy),
        directory=tmp_path,key=b'k'*32,report_path=report_path,manifest=manifest)
    assert resumed.status=='pass' and resumed.capture_digest==quality.capture_digest
    canonical=json.loads((tmp_path/'canonical-capture.json').read_text())
    actual=SampleBatch.from_dict(canonical)
    evidence=TargetCaptureEvidence(tmp_path,b'k'*32)
    assert evidence.verify(actual,canonical_digest(actual.as_dict())).ok
    report_path.write_text('{}')
    assert not evidence.verify(actual,canonical_digest(actual.as_dict())).ok
    assert not TargetCaptureEvidence(tmp_path,b'x'*32).verify(actual,canonical_digest(actual.as_dict())).ok


def test_seal_exact_receipt_and_copy_crash_resume(tmp_path):
    *_,profile,expected,raw=_inputs(tmp_path)
    stage=create_export_stage(profile,'run','step')
    stage=ExportStage.from_dict(stage.as_dict())
    source={'binding':{'runtime_epoch':'same-epoch'}}
    bound=bind_export_stage(stage,request_id='request',attempt_id='attempt',lease_epoch=4,
        operation_name='scene.export',arguments={'path':str(stage.raw_path)},source_binding=source)
    stage.raw_path.write_bytes(b'actual native completed bytes')
    receipt={key:bound[key] for key in ('request_id','run_id','step_id','attempt_id','lease_epoch','operation_digest')}
    receipt.update(phase='terminal',outcome='succeeded',dispatched=True,write_phase='completed',scene_before=source['binding'],
        terminal_result={'ok':True,'result':{'native_completion':'observed','export_profile_digest':stage.profile_digest,
        'raw_path':str(stage.raw_path),'artifact_sha256':file_sha256(stage.raw_path),'artifact_bytes':stage.raw_path.stat().st_size}})
    wrong=copy.deepcopy(receipt);wrong['step_id']=None
    with pytest.raises(ExportPublicationError,match='EXPORT_RECEIPT_MISMATCH'):
        seal_export(stage,wrong,{'output_bytes':1024})
    wrong=copy.deepcopy(receipt);wrong['terminal_result']['result']['export_profile_digest']='b'*64
    with pytest.raises(ExportPublicationError,match='EXPORT_COMPLETION_IDENTITY_MISMATCH'):
        seal_export(stage,wrong,{'output_bytes':1024})
    copy_exclusive(stage.raw_path,stage.sealed_path,max_bytes=1024)
    artifact=seal_export(stage,receipt,{'output_bytes':1024})
    assert artifact==seal_export(stage,receipt,{'output_bytes':1024})
    assert stage.raw_path.stat().st_ino!=stage.sealed_path.stat().st_ino


def test_wire_boolean_or_legacy_callback_cannot_grant_target_provenance(tmp_path):
    from cascadeur_complete.external import validate_target_import
    *_,profile,expected,raw=_inputs(tmp_path)
    artifact=ArtifactRef(path=str(tmp_path/'not-imported.fbx'),sha256='a'*64,bytes=1)
    report=validate_target_import(artifact,profile,expected,quality_context=True,provenance_key=b'k'*32,
                                 roundtrip_validator=lambda *_: {'status':'pass','runtime_verified':True})
    assert report.status=='unverified'
    assert report.reason_codes==('ROUNDTRIP_QUALITY_CONTEXT_UNAVAILABLE',)


def test_publication_reconciles_after_expiry_with_exact_retained_bundle(tmp_path,monkeypatch):
    import cascadeur_complete.export_publisher as publisher
    sealed=tmp_path/'sealed.fbx';sealed.write_bytes(b'bounded publication fixture')
    artifact=ArtifactRef(path=str(sealed),sha256=file_sha256(sealed),bytes=sealed.stat().st_size)
    report=ValidationReport(status='pass',artifact_sha256=artifact.sha256)
    bundle=ValidationBundle(artifact_sha256=artifact.sha256,execution='succeeded',quality='pass',structure=report,
                            target=report,source_capture_digest='a'*64,profile_digest='b'*64)
    permit=PublishPermit(destination=str(tmp_path/'final.fbx'),authorization_digest='c'*64,
                         artifact_sha256=artifact.sha256,profile_digest='b'*64,expires_at=time.time()+60,run_id='run',step_id='publish')
    assert publish_verified(artifact,bundle,permit)['status']=='published'
    monkeypatch.setattr(publisher.time,'time',lambda:permit.expires_at+10)
    assert publish_verified(artifact,bundle,permit)['status']=='published'
    changed=bundle.model_copy(update={'source_capture_digest':'d'*64})
    with pytest.raises(ExportPublicationError,match='PUBLISH_INTENT_CONFLICT'):
        publish_verified(artifact,changed,permit)
