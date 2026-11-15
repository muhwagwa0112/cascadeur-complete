"""Focused reproductions for the r3 domain defects; no native scene mutations."""
import numpy as np
import pytest
from scipy.spatial.transform import Rotation

from cascadeur_complete.capture import partition_writes
from cascadeur_complete.motion_cleanup import linear_interpolation
from cascadeur_complete.motion_context import (ContactSegment, IntentConstraints, MotionContext, RigProfile,
                                                SampleBatch, SupportTrack, MotionInputError)
from cascadeur_complete.motion_geometry import TriangleSurface, closest_triangle, triangle_pair_distance, segment_distance
from cascadeur_complete.motion_math import align_vectors, hemisphere_continuous, solve_two_bone
from cascadeur_complete.motion_solvers import build_key_model, fit_keys, repair_rotation_spikes, solve_contacts_v2
from cascadeur_complete.retargeting import retarget_pose, world_to_local


def context(n):
    return MotionContext(np.arange(n),np.arange(n)/60,"fps",60,1,.01,np.eye(3),{"source":"explicit_test_profile"})


def batch(positions,n):
    return SampleBatch(context(n),tuple(positions),"global",positions,{},
                       {key:np.tile([True,False],(n,1)) for key in positions},None)


@pytest.mark.parametrize("protected_role", [True,False])
def test_original_quality_measures_protected_rotation_for_roles_and_dependencies(protected_role):
    from cascadeur_complete.motion_quality import (QualityPolicy,evaluate_metrics,original_intent_metrics,
                                                   required_motion_metrics)
    n=3
    ids=("root","protected")
    positions={key:np.zeros((n,3)) for key in ids}
    rotation={key:np.tile([1.,0.,0.,0.],(n,1)) for key in ids}
    if not protected_role:
        del rotation["root"]
    validity={key:np.ones((n,2),dtype=bool) for key in ids}
    before=SampleBatch(context(n),ids,"global",positions,rotation,validity,None)
    changed={**rotation,"protected":Rotation.from_euler("z",np.array([0,.25,0])[:,None]).as_quat()[:,[3,0,1,2]]}
    after=SampleBatch(context(n),ids,"global",positions,changed,validity,None)
    roles={"root":"root",**({"fixed":"protected"} if protected_role else {})}
    rig=RigProfile("p","c",roles,frozenset(("root",)),
                   dependency_ids=frozenset() if protected_role else frozenset(("protected",)))
    intent=IntentConstraints(editable_frames=(0,2),root_policy="explicit_mapped_trajectory",
                             correction_envelope={"position_m":0.,"rotation_rad":1.})
    required=required_motion_metrics(rig,intent,capture=before)
    assert "non_target_scope_rad" in required
    policy=QualityPolicy(profile_id="p",profile_revision="r",required_metrics=tuple(sorted(required)),
                         limits_si={name:1. if name=="rotation_correction_rad" else 0. for name in required})
    metrics=original_intent_metrics(before,after,rig,intent)
    assert metrics["non_target_scope_m"]["max"]==0
    assert metrics["non_target_scope_rad"]["max"]==pytest.approx(.25)
    report=evaluate_metrics(metrics,policy,rig=rig,intent=intent,capture=before)
    assert report.status=="fail" and report.reason_codes==["METRIC_FAILED:non_target_scope_rad"]
    # A missing observed rotation cannot be converted to a zero preservation error.
    incomplete=SampleBatch(context(n),ids,"global",positions,
                           {key:value for key,value in rotation.items() if key!="protected"},validity,None)
    with pytest.raises(MotionInputError,match="INCOMPLETE_CAPTURE"):
        original_intent_metrics(before,incomplete,rig,intent)


def test_original_quality_rejects_missing_role_and_frame_relabeling():
    from cascadeur_complete.motion_quality import original_intent_metrics
    capture=batch({"root":np.zeros((3,3))},3)
    intent=IntentConstraints(editable_frames=(0,2))
    missing=RigProfile("p","c",{"root":"root","missing":"missing"},frozenset(("root",)))
    with pytest.raises(MotionInputError,match="INCOMPLETE_CAPTURE"):
        original_intent_metrics(capture,capture,missing,intent)
    shifted=MotionContext(np.arange(3)+1,np.arange(3)/60,"explicit",60,1,.01,np.eye(3),
                          {"source":"explicit_test_profile"})
    after=SampleBatch(shifted,capture.object_ids,capture.space,capture.position_m,{},capture.channel_valid,None)
    with pytest.raises(MotionInputError,match="complete original time grid"):
        original_intent_metrics(capture,after,RigProfile("p","c",{"root":"root"},frozenset(("root",))),intent)


@pytest.mark.parametrize("locked", [True,False])
def test_quality_requires_observed_rotation_locks(locked):
    from cascadeur_complete.motion_quality import required_motion_metrics
    capture=SampleBatch(context(3),("root",),"global",{"root":np.zeros((3,3))},
        {"root":np.tile([1.,0.,0.,0.],(3,1))},{"root":np.ones((3,2),dtype=bool)},None)
    rig=RigProfile("p","c",{"root":"root"},frozenset(("root",)))
    intent=IntentConstraints(editable_frames=(0,2) if locked else (1,2),
                             locked_roles_frames={"root":(1,)} if locked else {})
    assert "key_pose_rotation_rad" in required_motion_metrics(rig,intent,capture=capture)


def test_half_turn_sign_and_intentional_chart_crossing_are_not_spikes():
    q=Rotation.from_euler("z",np.array([179,180,181])[:,None],degrees=True).as_quat()[:,[3,0,1,2]]
    q[1]*=-1
    corrected=repair_rotation_spikes(q,[0,.02,.04],spike_angle_rad=.1)
    assert corrected["corrected_rows"]==[]
    assert np.all(np.sum(hemisphere_continuous(q)[:-1]*hemisphere_continuous(q)[1:],axis=1)>0)


def test_two_bone_projects_the_actual_wrist_and_handles_zero_and_antiparallel():
    args=([0,0,0],[0,1,0],[3,0,0],1.,1.)
    assert solve_two_bone(*args).status=="failed"
    result=solve_two_bone(*args,reach_policy="project")
    assert result.status=="candidate" and not result.reached_target
    assert np.linalg.norm(result.wrist_m-result.elbow_m)==pytest.approx(1)
    assert np.linalg.norm(result.elbow_m)==pytest.approx(1)
    assert solve_two_bone([0,0,0],[0,0,0],[0,0,0],1,1).status=="candidate"
    assert align_vectors([1,0,0],[-1,0,0]).apply([1,0,0])==pytest.approx([-1,0,0])


def test_triangle_interior_and_crossing_edges_use_surface_geometry():
    triangle=np.array([[-10,-10,0],[10,-10,0],[0,10,0.]])
    closest,_=closest_triangle([0,0,1],triangle)
    assert closest==pytest.approx([0,0,0])
    crossing=np.array([[0,-1,-1],[0,1,-1],[0,0,1.]])
    assert triangle_pair_distance(triangle,crossing)==pytest.approx(0)
    distance,left,right=segment_distance([-1,0,0],[1,0,0],[0,-1,0],[0,1,0],return_points=True)
    assert distance==pytest.approx(0) and np.linalg.norm(left-right)<1e-12


def test_reversed_closed_component_sign_and_open_ambiguity():
    vertices=np.array([[0,0,0],[1,0,0],[0,1,0],[0,0,1.]])
    triangles=np.array([[0,2,1],[0,1,3],[0,3,2],[1,2,3]])
    for faces in (triangles,triangles[:,::-1]):
        assert TriangleSurface(vertices,faces).closest([.1,.1,.1]).signed_distance_m<0
    assert TriangleSurface(vertices,triangles[:3]).closest([.1,.1,.1]).signed_distance_m is None


def test_short_interpolation_and_different_driver_key_grids_fit_independently():
    assert linear_interpolation([0,1,2],[1]).toarray()==pytest.approx(np.ones((3,1)))
    with pytest.raises(MotionInputError):
        linear_interpolation([0,1],[])
    positions={"a":np.zeros((3,3)),"b":np.zeros((3,3))}
    capture=batch(positions,3)
    rig=RigProfile("p","c",{"a":"a","b":"b"},frozenset(positions))
    model=build_key_model(capture,rig,interpolation_capabilities={"a":{"frames":[0,2],"mode":"LINEAR"},"b":{"frames":[0,1,2],"mode":"LINEAR"}})
    goal={"a":np.array([[0,0,0],[.01,0,0],[.02,0,0]]),"b":np.array([[0,0,0],[.02,0,0],[0,0,0]])}
    result=fit_keys(goal,capture,model,{}, {"velocity_weight":0,"acceleration_weight":0,"position_correction_m":.03})
    assert result.status=="candidate"
    assert result.values["a"]["frames"]==[0,2] and result.values["b"]["frames"]==[0,1,2]


def test_global_contact_tracks_a_moving_support_and_keeps_exact_lengths():
    n=4
    origin=np.column_stack((np.arange(n)*.005,np.zeros((n,2))))
    positions={"h":np.tile([0,.9,0],(n,1)),"k":np.tile([0,.45,.2],(n,1)),
               "a":origin+np.column_stack((np.arange(n)*.005,np.full(n,.01),np.zeros(n)))}
    capture=batch(positions,n)
    lengths={"Left.upper_leg":np.linalg.norm(positions["k"][0]-positions["h"][0]),"Left.lower_leg":np.linalg.norm(positions["a"][0]-positions["k"][0])}
    rig=RigProfile("p","c",{"Left.hip":"h","Left.knee":"k","Left.ankle":"a"},frozenset(("k","a")),bone_lengths_m=lengths)
    contact=ContactSegment(role="Left.ankle",support_id="floor",first_frame=0,last_frame=3,mode="planted",provenance="explicit")
    intent=IntentConstraints(editable_frames=(0,3),contacts=(contact,))
    support=SupportTrack("floor",origin,np.tile([1,0,0,0],(n,1)),{"kind":"plane","normal_local":[0,1,0]})
    blocked=solve_contacts_v2(capture,rig,{"floor":support},intent.contacts,intent,
                              {"position_correction_m":.05,"max_variables":1})
    assert blocked.reason_codes==["RESOURCE_BUDGET_EXCEEDED"]
    result=solve_contacts_v2(capture,rig,{"floor":support},intent.contacts,intent,{"position_correction_m":.05})
    assert result.status=="candidate",result.as_dict()
    goal=result.values["position_m"]
    assert goal["a"]==pytest.approx(origin,abs=2e-6)
    assert np.linalg.norm(goal["k"]-positions["h"],axis=1)==pytest.approx(lengths["Left.upper_leg"],abs=1e-8)
    assert np.linalg.norm(goal["a"]-goal["k"],axis=1)==pytest.approx(lengths["Left.lower_leg"],abs=1e-8)


def test_short_contacts_budget_their_retained_full_clip_arrays_before_sparse_allocation(monkeypatch):
    from cascadeur_complete import motion_quality,motion_solvers
    n=100
    capture=batch({key:np.tile(position,(n,1)) for key,position in
                   (("h",[0,.9,0]),("k",[0,.45,.2]),("a",[0,.01,0]))},n)
    rig=RigProfile("p","c",{"Left.hip":"h","Left.knee":"k","Left.ankle":"a"},frozenset(("k","a")))
    contact=ContactSegment(role="Left.ankle",support_id="floor",first_frame=0,last_frame=0,
                           mode="planted",provenance="explicit")
    contacts=(contact,)*1000
    intent=IntentConstraints(editable_frames=(0,n-1),contacts=contacts)
    # Isolate resource ordering from baseline measurement. These full-clip
    # preparations alone require 1000 * 100 * 4 * 3 * 8 = 9,600,000 bytes.
    monkeypatch.setattr(motion_quality,"contact_metrics",lambda *_,**__: {"contact_gap_m":{"max":.01}})
    monkeypatch.setattr(motion_solvers,"temporal_operators",lambda _:pytest.fail("sparse allocation preceded preparation budget"))
    result=solve_contacts_v2(capture,rig,{"floor":object()},contacts,intent,{"max_memory_bytes":8*1024*1024})
    assert result.reason_codes==["RESOURCE_BUDGET_EXCEEDED"]
    assert "max_memory_bytes" in result.report["detail"]


def test_rest_relative_retarget_and_planned_parent_inverse():
    rest=Rotation.from_euler("z",np.pi/2).as_matrix()
    delta=Rotation.from_euler("x",.2).as_matrix()
    source={"root":{"position_m":[0,0,0],"rotation_matrix":np.array([rest@delta,rest@delta])}}
    result=retarget_pose(source,{"root":{"rotation_matrix":rest}},
       {"root":{"position_m":[0,0,0],"rotation_matrix":np.eye(3)}},{"root":"root"},{"root":np.eye(3)},
       {"root":None},root_role="root",source_root_position_m=[[0,0,0],[1,0,0]],target_root_anchor_m=[3,0,0],root_basis=rest,scale=2)
    assert result.status=="candidate"
    assert result.values["local"]["root"]["rotation_matrix"][0]==pytest.approx(delta)
    assert result.values["world"]["root"]["position_m"][1]==pytest.approx([3,2,0])
    local=world_to_local([3,2,0],rest,[3,0,0],rest,2)
    assert local["position_m"]==pytest.approx([1,0,0])


def test_transport_split_keeps_one_owner_and_preserves_the_global_digest():
    writes=[{"id":"a","frame":f,"position":[0.,0.,0.]} for f in range(8)]
    chunks=partition_writes(writes,max_writes=3,payload_budget_bytes=500)
    assert [w for chunk in chunks for w in chunk["writes"]]==writes
    assert len({chunk["candidate_digest"] for chunk in chunks})==1
    assert [chunk["chunk_index"] for chunk in chunks]==list(range(len(chunks)))


def test_declared_interpolation_is_not_native_evidence_and_budget_precedes_allocation(monkeypatch):
    from cascadeur_complete.capture import estimate_motion_resources,enforce_motion_budget
    from cascadeur_complete import motion_solvers
    capture=batch({"a":np.zeros((3,3))},3)
    rig=RigProfile("p","c",{"a":"a"},frozenset(("a",)))
    model=build_key_model(capture,rig,interpolation_capabilities={"a":{"frames":[0,2],"mode":"LINEAR"}})
    assert model.capability=="declared_only"
    with pytest.raises(MotionInputError,match="INTERPOLATION_MODEL_UNVERIFIED"):
        build_key_model(capture,rig,key_layout={"build_fingerprint":"b","evaluator_fingerprint":"e",
            "source_fingerprint":"s","capture_digest":"wrong","evidence_ref":"ref","drivers":[]})
    monkeypatch.setattr(motion_solvers,"temporal_operators",lambda _:pytest.fail("allocation occurred before the budget guard"))
    result=fit_keys({"a":np.zeros((3,3))},capture,model,{}, {"max_variables":1})
    assert result.reason_codes==["RESOURCE_BUDGET_EXCEEDED"]
    estimate=estimate_motion_resources(100000,{"a":20})
    assert estimate["estimated_peak_bytes"]<256*1024*1024
    with pytest.raises(MotionInputError,match="RESOURCE_BUDGET_UNVERIFIED"):
        enforce_motion_budget(estimate,{"require_factorization_bound":True})


def test_motion_draft_reports_missing_orientation_and_rejects_stale_native_inputs():
    from copy import deepcopy
    from types import SimpleNamespace
    from cascadeur_complete.motion_profile_builder import MotionInputResolver
    observed={"values":{"context":context(3).as_dict(),"objects":[{"id":"p","character_id":"c"}],
                        "role_candidates":{"root":["p"]},"root_rotation_id":None},
              "provenance":{key:"native" for key in ("context","objects","role_candidates","root_rotation_id")},
              "source_fingerprint":"s","rig_structure_fingerprint":"r","evidence_ref":"immutable-record"}
    resolver=MotionInputResolver(lambda _:deepcopy(observed),
        lambda _,digest:SimpleNamespace(ok=True,result={"observation_digest":digest}))
    draft=resolver.inspect_motion_inputs("c",(0,2))
    assert "root_rotation_id" in draft.missing_fields
    draft.values["root_rotation_id"]="injected"
    with pytest.raises(MotionInputError,match="MISSING_MOTION_INPUTS"):
        resolver.resolve_motion_inputs(draft.draft_ref,{}, {"editable_frames":[0,2]})
    observed["source_fingerprint"]="successor"
    with pytest.raises(MotionInputError,match="STALE_MOTION_INPUT_DRAFT"):
        resolver.resolve_motion_inputs(draft.draft_ref,{}, {"editable_frames":[0,2]})
    observed["values"]["objects"].append({"id":"p","character_id":"c"})
    with pytest.raises(MotionInputError,match="duplicate"):
        resolver.inspect_motion_inputs("c",(0,2))


def test_actual_mesh_metric_requires_authenticated_evaluated_geometry():
    from types import SimpleNamespace
    from cascadeur_complete.capture import canonical_digest
    from cascadeur_complete.motion_geometry import ObservedSurfaceTrack
    from cascadeur_complete.motion_quality import QualityPolicy,actual_mesh_metrics
    vertices=np.array([[0,0,0],[1,0,0],[0,1,0],[0,0,1.]])
    faces=np.array([[0,2,1],[0,1,3],[0,3,2],[1,2,3]])
    ctx=context(1)
    tracks={"a":ObservedSurfaceTrack(vertices[None],faces,context=ctx),
            "b":ObservedSurfaceTrack((vertices+3)[None],faces,context=ctx)}
    manifest={"capture_kind":"target_actual","source_digest":"s","successor_digest":"t",
              "completion_receipt_digest":"done","topology_digest":"topology","skin_digest":"skin",
              "context_digest":canonical_digest(ctx.as_dict()),"frames":[0],"time_s":[0.],
              "windows":{key:track.windows for key,track in tracks.items()},
              "pairs":[["a","b"]],"space":"global","units":"metres"}
    geometry={"manifest":manifest,"tracks":tracks}
    policy=QualityPolicy(profile_id="p",profile_revision="r",required_metrics=("mesh_penetration_m","mesh_surface_intersection_count"),
                         limits_si={"mesh_penetration_m":0,"mesh_surface_intersection_count":0})
    with pytest.raises(MotionInputError,match="PROVENANCE_UNVERIFIED"):
        actual_mesh_metrics(geometry,policy,verifier=None)
    metrics=actual_mesh_metrics(geometry,policy,
        verifier=lambda _,digest:SimpleNamespace(ok=True,result={"geometry_digest":digest}),required_mesh_ids=("a","b"))
    assert metrics["mesh_penetration_m"]["max"]==0
    assert metrics["mesh_surface_intersection_count"]["sample_count"]==1


def test_host_retarget_observes_target_and_blocks_an_absent_controller_adapter():
    from types import SimpleNamespace
    from cascadeur_complete.cleanup_workflow import CleanupWorkflow
    ctx=context(2)
    observation={"target_rest":{"root":{"position_m":[0,0,0],"rotation_matrix":np.eye(3).tolist()}},
        "target_parents":{"root":None},"axis_alignment":{"root":np.eye(3).tolist()},
        "root_basis":np.eye(3).tolist(),"target_root_anchor_m":[0,0,0]}
    requests=[]
    service=SimpleNamespace(observe_retarget_inputs=lambda request:(requests.append(request) or SimpleNamespace(ok=True,result=observation)),
        verify_retarget_inputs=lambda _,digest:SimpleNamespace(ok=True,result={"retarget_inputs_digest":digest}))
    rig=RigProfile("p","c",{"root":"r"},frozenset(("r",)))
    workflow=CleanupWorkflow(service,profile=rig,context=ctx,
        intent=IntentConstraints(action="retarget",editable_frames=(0,1),root_policy="explicit_mapped_trajectory"))
    source={"schema_version":1,"context":ctx.as_dict(),"provenance":{"source":"canonical imported observations"},
        "source_local":{"root":{"position_m":np.zeros((2,3)).tolist(),"rotation_matrix":np.tile(np.eye(3),(2,1,1)).tolist()}},
        "source_rest":{"root":{"position_m":[0,0,0],"rotation_matrix":np.eye(3).tolist()}},
        "source_root_position_m":np.zeros((2,3)).tolist()}
    result=workflow.plan_retarget(source,{"root":"root"},{"root_role":"root","scale":1,"target_channels":["position"]})
    assert requests[0]["role_ids"]=={"root":"r"}
    assert result["reason_codes"]==["RIG_ADAPTER_UNVERIFIED"]


def test_observed_piecewise_keys_fit_the_native_segment_schedule_without_invented_ids():
    from types import SimpleNamespace
    from cascadeur_complete.capture import canonical_digest
    from cascadeur_complete.motion_key_layout import KeyLayoutObservation
    capture=batch({"a":np.zeros((5,3))},5)
    rig=RigProfile("p","c",{"a":"a"},frozenset(("a",)))
    model_id="piecewise_linear_step_position_independent_v1"
    observed={"build_fingerprint":"actual-test-build","evaluator_fingerprint":"test-evaluator",
        "source_fingerprint":"test-source","capture_digest":canonical_digest(capture.as_dict()),"evidence_ref":"test-runtime-record",
        "support_status":"supported","qualified_models":[model_id],"drivers":[{"object_id":"a","channel":"position",
        "space":"global","layer_id":"layer","key_ids":["layer:0","layer:2","layer:4"],
        "key_id_kind":"layer_frame_locator","frames":[0,2,4],"segment_modes":["STEP","LINEAR"],
        "influences":{"controllers":[],"blend":[],"cycle":[]},"native_model":model_id}]}
    verifier=lambda _,digest:SimpleNamespace(ok=True,result={"key_layout_digest":digest})
    model=build_key_model(capture,rig,key_layout=observed,verifier=verifier)
    goal=np.zeros((5,3));goal[:,0]=[0,0,.01,.015,.02]
    result=fit_keys({"a":goal},capture,model,{}, {"velocity_weight":0,"acceleration_weight":0,"position_correction_m":.03})
    assert result.status=="candidate"
    assert result.values["a"]["position_m"][:,0]==pytest.approx([0,.01,.02],abs=1e-7)
    assert result.report["key_layout_digest"]==canonical_digest(KeyLayoutObservation.model_validate(observed).model_dump(mode="json"))
    observed["support_status"]="unverified"
    with pytest.raises(MotionInputError,match="INTERPOLATION_MODEL_UNVERIFIED"):
        build_key_model(capture,rig,key_layout=observed,verifier=verifier)


def _plan_domain_key_insertions(additions, *, allow_interpolation_change=False):
    from types import SimpleNamespace
    from cascadeur_complete.capture import canonical_digest
    from cascadeur_complete.motion_key_layout import plan_key_insertion
    capture=batch({"a":np.column_stack(([0,.01,.02,.03,.04,.04,.04,.04,.08],np.zeros((9,2))))},9)
    rig=RigProfile("p","c",{"a":"a"},frozenset(("a",)))
    intent=IntentConstraints(editable_frames=(0,8),allow_key_insertion=True,
        allow_interpolation_change=allow_interpolation_change,correction_envelope={"added_keys":2})
    observed={"build_fingerprint":"domain-test-build","evaluator_fingerprint":"domain-test-evaluator",
        "source_fingerprint":"domain-test-source","capture_digest":canonical_digest(capture.as_dict()),
        "evidence_ref":"domain-test-record","support_status":"supported","drivers":[{
            "object_id":"a","channel":"position","space":"global","layer_id":"layer",
            "key_ids":["k0","k4","k8"],"frames":[0,4,8],
            "values":[[0,0,0],[.04,0,0],[.08,0,0]],"tangents":[{},{},{}],
            "segment_modes":["LINEAR","STEP"],"influences":{"controllers":[],"blend":[],"cycle":[]}}]}
    # These receipts exercise the pure planner contract, not native qualification.
    verifier=lambda _,digest:SimpleNamespace(ok=True,result={"key_layout_digest":digest,
                                                           "completion_receipt_digest":"domain-test-completion"})
    insertion_verifier=lambda _,digest:SimpleNamespace(ok=True,result={"request_digest":digest,
        "shared_layer_effects_observed":True,"adapter_evidence_ref":"domain-test-insertion"})
    delta=plan_key_insertion(observed,capture,rig,intent,additions,verifier=verifier,
        insertion_verifier=insertion_verifier,generated_keys_budget=2)
    return delta,observed,verifier


def _domain_key_addition(frame,mode):
    return {"object_id":"a","channel":"position","layer_id":"layer","frame":frame,
            "value":[min(frame,4)*.01,0,0],"mode":mode,"tangent":{}}


def test_key_insertion_preserves_mixed_original_segments_and_old_outgoing_modes():
    from copy import deepcopy
    from cascadeur_complete.motion_key_layout import validate_key_topology_readback
    # Reverse request order also checks that each addition uses its own interval.
    delta,observed,verifier=_plan_domain_key_insertions([
        _domain_key_addition(6,"STEP"),_domain_key_addition(2,"LINEAR")])
    after=deepcopy(observed)
    after["drivers"][0].update(frames=[0,2,4,6,8],key_ids=["k0","new2","k4","new6","k8"],
        values=[[0,0,0],[.02,0,0],[.04,0,0],[.04,0,0],[.08,0,0]],tangents=[{}]*5,
        segment_modes=["LINEAR","LINEAR","STEP","STEP"])
    assert validate_key_topology_readback(delta,after,verifier=verifier)["added_keys"]==2
    after["drivers"][0]["segment_modes"][0]="STEP"
    with pytest.raises(MotionInputError,match="KEY_TOPOLOGY_MISMATCH"):
        validate_key_topology_readback(delta,after,verifier=verifier)


def test_key_insertion_requires_authority_for_its_new_outgoing_mode_only():
    from copy import deepcopy
    from cascadeur_complete.motion_key_layout import validate_key_topology_readback
    addition=_domain_key_addition(2,"STEP")
    with pytest.raises(MotionInputError,match="INTERPOLATION_CHANGE_NOT_AUTHORIZED"):
        _plan_domain_key_insertions([addition])
    delta,observed,verifier=_plan_domain_key_insertions([addition],allow_interpolation_change=True)
    after=deepcopy(observed)
    after["drivers"][0].update(frames=[0,2,4,8],key_ids=["k0","new2","k4","k8"],
        values=[[0,0,0],[.02,0,0],[.04,0,0],[.08,0,0]],tangents=[{}]*4,
        segment_modes=["LINEAR","STEP","STEP"])
    assert validate_key_topology_readback(delta,after,verifier=verifier)["status"]=="matched"
    # Even authorized new-key mode changes do not authorize rewriting old modes.
    after["drivers"][0]["segment_modes"][0]="STEP"
    with pytest.raises(MotionInputError,match="KEY_TOPOLOGY_MISMATCH"):
        validate_key_topology_readback(delta,after,verifier=verifier)


@pytest.mark.parametrize("frames",[(0,),(4,),(8,),(-1,),(9,),(2,2)])
def test_key_insertion_still_rejects_endpoints_existing_keys_and_duplicates(frames):
    with pytest.raises(MotionInputError,match="KEY_LAYOUT_INSUFFICIENT"):
        _plan_domain_key_insertions([_domain_key_addition(frame,"LINEAR") for frame in frames])


def _locator_insertion_domain_case():
    """Synthetic wire-contract data only; no native qualification is implied."""
    from copy import deepcopy
    from dataclasses import replace
    from types import SimpleNamespace
    from cascadeur_complete.capture import canonical_digest
    from cascadeur_complete.motion_key_layout import KeyLayoutObservation
    digest=canonical_digest({"domain_only":True})
    source={"schema_version":1,"binding":{"schema_version":1,"runtime_epoch":"domain-epoch",
        "scene_instance_id":"domain-scene","document_lineage_id":"domain-document",
        "revision_kind":"scope_digest","scope_digest":digest,"content_revision":digest,
        "selection_digest":None},"scope":{"object_ids":["a"]},"sample_digest":digest,
        "inputs_digest":digest,"adapter_fingerprint":digest,"complete":False}
    capture=replace(batch({"a":np.zeros((9,3))},9),space="local",source_binding=source)
    rig=RigProfile("p","c",{"a":"a"},frozenset(("a",)))
    intent=IntentConstraints(editable_frames=(0,8),allow_key_insertion=True,correction_envelope={"added_keys":2})
    common={"ik_fk":"FK","fixation":"Free"}
    def section(frame,mode):
        return {"frame":frame,"is_key":True,"interval_mode":mode,"interval_common":dict(common),
            "tangent":{"mode":"Continuous","left_weight_velocity":1.,"right_weight_velocity":1.},
            "key_common":dict(common),"label":None}
    def boundary(frame):
        return {"frame":frame,"key_id":"layer:"+str(frame),"key_id_kind":"layer_frame_locator",
                "locked":False,"event":False,"label":None}
    def tangent(row):
        return {**row["tangent"],"key_common":row["key_common"],"label":row["label"]}
    sections=[section(0,"LINEAR"),section(4,"STEP"),section(8,"STEP")]
    driver={"object_id":"a","channel":"position","space":"local","layer_id":"layer",
        "key_id_kind":"layer_frame_locator","key_ids":["layer:0","layer:4","layer:8"],
        "frames":[0,4,8],"values":[[0.,0.,0.],[4.,0.,0.],[8.,0.,0.]],
        "segment_modes":["LINEAR","STEP"],"tangents":[tangent(row) for row in sections],
        "boundary_keys":[boundary(frame) for frame in (0,4,8)],"sections":sections,
        "influences":{"controllers":[],"blend":[],"cycle":[]},"data_id":"data",
        "data_mode":"Animation","layer_objects":["a"],"native_model":"domain-piecewise"}
    observed=KeyLayoutObservation(build_fingerprint=digest,evaluator_fingerprint=digest,
        source_fingerprint=digest,capture_digest=canonical_digest(capture.as_dict()),
        evidence_ref="domain-key-layout",support_status="supported",drivers=[driver]).model_dump(mode="json")
    new_section=section(2,"LINEAR")
    addition={"object_id":"a","channel":"position","layer_id":"layer","frame":2,
              "value":[2.,0.,0.],"mode":"LINEAR","tangent":tangent(new_section)}
    expected=deepcopy(observed["drivers"][0])
    expected.update(frames=[0,2,4,8],key_ids=["layer:0","layer:2","layer:4","layer:8"],
        values=[[0.,0.,0.],[2.,0.,0.],[4.,0.,0.],[8.,0.,0.]],
        segment_modes=["LINEAR","LINEAR","STEP"],sections=[sections[0],new_section,*sections[1:]],
        tangents=[tangent(row) for row in [sections[0],new_section,*sections[1:]]],
        boundary_keys=[boundary(frame) for frame in (0,2,4,8)])
    request={"key_layout_digest":canonical_digest(observed),"additions":[addition]}
    proof={"contract":"independent_absent_layer_frame_position_v1","key_id_kind":"layer_frame_locator",
        "value_space":"native_scene_units","request_digest":canonical_digest(request),
        "key_layout_digest":canonical_digest(observed),"original_topology_digest":canonical_digest(observed["drivers"]),
        "capture_digest":canonical_digest(capture.as_dict()),"context_digest":canonical_digest(capture.context.as_dict()),
        "source_binding_digest":canonical_digest(source),"runtime_epoch":"domain-epoch",
        "runtime_fingerprint":digest,"scene_instance_id":"domain-scene","document_lineage_id":"domain-document",
        "before_projection_digest":digest,"model_qualification_digest":digest,
        "insertion_qualification_digest":digest,"expected_driver":expected}
    insertion_result={"request_digest":canonical_digest(request),"shared_layer_effects_observed":True,
        "adapter_evidence_ref":"domain-insertion","locator_insertion":proof}
    verifier=lambda _,key:SimpleNamespace(ok=True,result={"key_layout_digest":key})
    insertion_verifier=lambda *_:SimpleNamespace(ok=True,result=insertion_result)
    return capture,rig,intent,observed,addition,proof,insertion_result,verifier,insertion_verifier


def test_locator_insertion_requires_exact_private_prediction_and_completed_readback():
    from copy import deepcopy
    from types import SimpleNamespace
    from cascadeur_complete.capture import canonical_digest
    from cascadeur_complete.motion_key_layout import plan_key_insertion,validate_key_topology_readback
    capture,rig,intent,observed,addition,proof,_,verifier,insertion_verifier=_locator_insertion_domain_case()
    delta=plan_key_insertion(observed,capture,rig,intent,[addition],verifier=verifier,
        insertion_verifier=insertion_verifier,generated_keys_budget=2)
    assert delta.locator_insertion.value_space=="native_scene_units"
    after=deepcopy(observed)
    after["drivers"]=[deepcopy(proof["expected_driver"])]
    completion={key:proof[key] for key in ("contract","request_digest","source_binding_digest",
        "runtime_epoch","runtime_fingerprint","scene_instance_id","document_lineage_id","before_projection_digest")}
    completion.update(key_layout_digest=canonical_digest(after),adapter_evidence_ref="domain-insertion",
        after_projection_digest=canonical_digest({"domain_after":True}),
        completion_receipt_digest=canonical_digest({"domain_completion":True}))
    result={"key_layout_digest":canonical_digest(after),"completion_receipt_digest":completion["completion_receipt_digest"],
            "locator_insertion_completion":completion}
    readback=lambda *_:SimpleNamespace(ok=True,result=result)
    assert validate_key_topology_readback(delta,after,verifier=readback)["added_keys"]==1
    # A valid post observation digest does not authorize a different original source.
    completion["scene_instance_id"]="another-scene"
    with pytest.raises(MotionInputError,match="KEY_TOPOLOGY_READBACK_UNVERIFIED"):
        validate_key_topology_readback(delta,after,verifier=readback)
    completion["scene_instance_id"]=proof["scene_instance_id"]
    after["drivers"][0]["sections"][0]["interval_mode"]="STEP"
    result["key_layout_digest"]=completion["key_layout_digest"]=canonical_digest(after)
    with pytest.raises(MotionInputError,match="KEY_TOPOLOGY_MISMATCH"):
        validate_key_topology_readback(delta,after,verifier=readback)


@pytest.mark.parametrize("change",["missing_proof","source","old_section","new_event","persistent_id"])
def test_locator_insertion_rejects_unbound_or_rewritten_predictions(change):
    from cascadeur_complete.motion_key_layout import plan_key_insertion
    capture,rig,intent,observed,addition,proof,result,verifier,insertion_verifier=_locator_insertion_domain_case()
    if change=="missing_proof":
        result.pop("locator_insertion")
    elif change=="source":
        proof["document_lineage_id"]="another-document"
    elif change=="old_section":
        proof["expected_driver"]["sections"][0]["interval_mode"]="STEP"
    elif change=="new_event":
        proof["expected_driver"]["boundary_keys"][1]["event"]=True
    else:
        proof["expected_driver"]["key_ids"][1]="invented-guid"
    with pytest.raises(MotionInputError,match="KEY_(INSERTION_ADAPTER_UNVERIFIED|TOPOLOGY_MISMATCH)"):
        plan_key_insertion(observed,capture,rig,intent,[addition],verifier=verifier,
            insertion_verifier=insertion_verifier,generated_keys_budget=2)


def _sparse_refinement_case():
    from copy import deepcopy
    from cascadeur_complete.motion_context import IntentConstraints
    capture,rig,_,observed,_,_,_,verifier,_=_locator_insertion_domain_case()
    observed=deepcopy(observed)
    driver=observed["drivers"][0]
    driver["values"]=[[0.,0.,0.]]*3
    driver["segment_modes"]=["LINEAR","LINEAR"]
    driver["native_model"]="linear_position_independent_v1"
    for section in driver["sections"]:
        section["interval_mode"]="LINEAR"
    observed["qualified_models"]=[driver["native_model"]]
    observed["raw_sample_projection"]={"space":"local","frames":list(range(9)),
        "samples":[{"frame":frame,"id":"a","position":[0.,0.,0.]} for frame in range(9)]}
    intent=IntentConstraints(editable_frames=(0,8),allow_key_insertion=True,
        correction_envelope={"added_keys":1,"position_m":.03})
    wanted=np.zeros((9,3));wanted[:,0]=[0,.005,.01,.005,0,0,0,0,0]
    return capture,rig,intent,observed,verifier,{"a":wanted}


def test_sparse_refinement_fits_interior_motion_without_moving_original_keys():
    from cascadeur_complete.motion_solvers import refine_sparse_keys
    capture,rig,intent,observed,verifier,goal=_sparse_refinement_case()
    result=refine_sparse_keys(goal,capture,rig,intent,{},
        {"velocity_weight":0,"acceleration_weight":0,"fit_error_m":1e-7},
        key_layout=observed,verifier=verifier,allow_key_insertion=True,max_added_keys=1)
    assert result.status=="candidate",result.as_dict()
    assert result.values["existing_writes"]==[]
    assert [row["frame"] for row in result.values["additions"]]==[2]
    predicted=np.asarray(result.values["predicted_position_m"]["a"])
    assert predicted==pytest.approx(goal["a"],abs=1e-7)
    assert np.array_equal(predicted[[0,4,8]],capture.position_m["a"][[0,4,8]])


def test_sparse_refinement_requires_optin_and_reserves_budget_before_matrices(monkeypatch):
    import cascadeur_complete.motion_solvers as solvers
    capture,rig,intent,observed,verifier,goal=_sparse_refinement_case()
    assert solvers.refine_sparse_keys(goal,capture,rig,intent,{}, {},key_layout=observed,
        verifier=verifier,max_added_keys=1).reason_codes==["KEY_INSERTION_NOT_AUTHORIZED"]
    def forbidden(*args,**kwargs):
        raise AssertionError("interpolation allocation preceded resource reservation")
    monkeypatch.setattr(solvers,"_refinement_interpolant",forbidden)
    result=solvers.refine_sparse_keys(goal,capture,rig,intent,{}, {"max_variables":0},
        key_layout=observed,verifier=verifier,allow_key_insertion=True,max_added_keys=1)
    assert result.reason_codes==["RESOURCE_BUDGET_EXCEEDED"]


def test_sparse_refinement_cannot_spend_a_contact_boundary_or_locked_frame():
    from cascadeur_complete.motion_context import ContactSegment
    from cascadeur_complete.motion_solvers import refine_sparse_keys
    capture,rig,intent,observed,verifier,goal=_sparse_refinement_case()
    for protection in ({"locked_roles_frames":{"a":(2,)}},
                       {"contacts":(ContactSegment(role="a",support_id="floor",first_frame=2,last_frame=4,
                            mode="planted",provenance="explicit"),)}):
        protected=intent.model_copy(update=protection)
        result=refine_sparse_keys(goal,capture,rig,protected,{},
            {"velocity_weight":0,"acceleration_weight":0,"fit_error_m":1e-7},
            key_layout=observed,verifier=verifier,allow_key_insertion=True,max_added_keys=1)
        assert result.status=="failed"
        assert result.reason_codes==["KEY_LAYOUT_INSUFFICIENT"]


def _sparse_workflow_domain_case(monkeypatch, *, joint=False, with_rotation=False):
    """Host-contract doubles only; these do not qualify a native operation."""
    from copy import deepcopy
    from dataclasses import replace
    from types import SimpleNamespace
    from cascadeur_complete.capture import canonical_digest
    from cascadeur_complete.cleanup_workflow import CleanupWorkflow
    capture,rig,intent,observed,verifier,goal=_sparse_refinement_case()
    capture=replace(capture,source_binding={**capture.source_binding,"complete":True})
    if with_rotation:
        capture=replace(capture,rotation_wxyz={"a":np.tile([1.,0.,0.,0.],(9,1))},
                        channel_valid={"a":np.ones((9,2),dtype=bool)})
    if joint:
        goal={"a":np.column_stack(([0.,.005,.01,.01,.01,.0075,.005,.0025,0.],np.zeros((9,2))))}
        intent=intent.model_copy(update={"root_policy":"explicit_mapped_trajectory"})
    observed["capture_digest"]=canonical_digest(capture.as_dict())
    observed["native_source_scope"]={"objects":[{"id":"a","parent_id":None}]}
    _,_,_,_,_,proof,_,_,_=_locator_insertion_domain_case()
    before_digest=canonical_digest(capture.as_dict())
    requests=[]
    def insertion_verifier(request,sha):
        requests.append(deepcopy(request))
        row=request["additions"][0]
        expected=deepcopy(observed["drivers"][0])
        new_section={"frame":row["frame"],"is_key":True,"interval_mode":row["mode"],
            "interval_common":{"ik_fk":"FK","fixation":"Free"},
            "tangent":{key:value for key,value in row["tangent"].items() if key not in {"key_common","label"}},
            "key_common":row["tangent"]["key_common"],"label":None}
        expected.update(frames=[0,2,4,8],key_ids=["layer:0","layer:2","layer:4","layer:8"],
            values=[[0.,0.,0.],row["value"],[0.,0.,0.],[0.,0.,0.]],segment_modes=["LINEAR"]*3,
            sections=[expected["sections"][0],new_section,*expected["sections"][1:]],
            tangents=[expected["tangents"][0],row["tangent"],*expected["tangents"][1:]],
            boundary_keys=[expected["boundary_keys"][0],{"frame":2,"key_id":"layer:2",
                "key_id_kind":"layer_frame_locator","locked":False,"event":False,"label":None},
                *expected["boundary_keys"][1:]])
        issued={**proof,"request_digest":sha,"key_layout_digest":canonical_digest(observed),
            "original_topology_digest":canonical_digest(observed["drivers"]),"capture_digest":before_digest,
            "source_binding_digest":canonical_digest(capture.source_binding),"expected_driver":expected}
        return SimpleNamespace(ok=True,result={"request_digest":sha,"shared_layer_effects_observed":True,
            "non_target_effects":[],"adapter_evidence_ref":"domain-only-private-proof","locator_insertion":issued})
    service=SimpleNamespace(observe_key_layout=lambda request:SimpleNamespace(ok=True,result=observed),
        verify_key_layout=verifier,verify_key_insertion=insertion_verifier)
    workflow=CleanupWorkflow(service,profile=rig,context=capture.context,intent=intent,source_binding=capture.source_binding)
    monkeypatch.setattr(workflow,"capture_batch",lambda *args,**kwargs:capture)
    bound=[]
    monkeypatch.setattr(workflow,"_bind_source",lambda op,args:(bound.append((op,args)) or capture.source_binding))
    result=workflow._plan_sparse_insertion(replace(capture,space="global"),goal,{},
        {"velocity_weight":0,"acceleration_weight":0,"fit_error_m":1e-7},1,{},frozenset(("a",)))
    return SimpleNamespace(capture=capture,rig=rig,intent=intent,observed=observed,goal=goal,
        workflow=workflow,result=result,requests=requests,bound=bound,before_digest=before_digest)


def test_sparse_workflow_authenticates_native_units_and_keeps_original_capture(monkeypatch):
    from copy import deepcopy
    from types import SimpleNamespace
    from cascadeur_complete.capture import canonical_digest
    case=_sparse_workflow_domain_case(monkeypatch)
    result,capture,goal=case.result,case.capture,case.goal
    requests,bound,before_digest=case.requests,case.bound,case.before_digest
    assert result["operation_name"]=="motion.key_topology_insert"
    assert result["existing_writes"]==[]
    assert requests[0]["additions"][0]["value"]==pytest.approx([1.,0.,0.],abs=1e-6)
    assert result["arguments"]["additions"][0]["position"]==requests[0]["additions"][0]["value"]
    assert canonical_digest(result["original_capture"])==before_digest
    assert canonical_digest(capture.as_dict())==before_digest
    assert np.asarray(result["predicted_target"]["position_m"]["a"])==pytest.approx(goal["a"],abs=1e-7)
    assert bound[0][0]==result["operation_name"]
    from cascadeur_complete.recipe_runner import RecipeRunner
    from cascadeur_complete.recipe_store import RecipeConflict
    plan=SimpleNamespace(spec=SimpleNamespace(character=SimpleNamespace(object_ids=("a",))))
    runner=RecipeRunner.__new__(RecipeRunner)
    prediction=runner._insertion_prediction(result,plan)
    assert prediction.space=="global"
    tampered=deepcopy(result)
    tampered["predicted_target"]["position_m"]["a"][2][0]+=.001
    with pytest.raises(RecipeConflict,match="KEY_INSERTION_.*PREDICTION|KEY_INSERTION_.*TARGET"):
        runner._insertion_prediction(tampered,plan)


def test_joint_sparse_fit_moves_existing_keys_only_with_explicit_optin():
    from cascadeur_complete.motion_solvers import refine_sparse_keys
    capture,rig,intent,observed,verifier,_=_sparse_refinement_case()
    goal={"a":np.column_stack(([0.,.005,.01,.01,.01,.0075,.005,.0025,0.],np.zeros((9,2))))}
    settings={"velocity_weight":0,"acceleration_weight":0,"fit_error_m":1e-7}
    fixed=refine_sparse_keys(goal,capture,rig,intent,{},settings,key_layout=observed,
        verifier=verifier,allow_key_insertion=True,max_added_keys=1)
    assert fixed.status=="failed" and fixed.reason_codes==["KEY_LAYOUT_INSUFFICIENT"]
    result=refine_sparse_keys(goal,capture,rig,intent,{},settings,key_layout=observed,
        verifier=verifier,allow_key_insertion=True,max_added_keys=1,allow_existing_key_updates=True)
    assert result.status=="candidate",result.as_dict()
    assert [row["frame"] for row in result.values["additions"]]==[2]
    assert [row["frame"] for row in result.values["existing_writes"]]==[4]
    assert np.asarray(result.values["predicted_position_m"]["a"])==pytest.approx(goal["a"],abs=1e-7)
    assert result.report["resources"]["maximum_qp_solves"]==12
    assert result.report["qp_solves"]<=12
    protected=intent.model_copy(update={"locked_roles_frames":{"a":(4,)}})
    locked=refine_sparse_keys(goal,capture,rig,protected,{},settings,key_layout=observed,
        verifier=verifier,allow_key_insertion=True,max_added_keys=1,allow_existing_key_updates=True)
    assert locked.status=="failed" and locked.reason_codes==["KEY_LAYOUT_INSUFFICIENT"]


def test_joint_sparse_workflow_binds_existing_values_only_after_private_completion(monkeypatch):
    from copy import deepcopy
    from dataclasses import replace
    from types import SimpleNamespace
    from cascadeur_complete.capture import canonical_digest
    from cascadeur_complete.motion_key_layout import KeyTopologyDelta
    from cascadeur_complete.recipe_runner import RecipeRunner
    from cascadeur_complete.recipe_store import RecipeConflict
    case=_sparse_workflow_domain_case(monkeypatch,joint=True,with_rotation=True)
    parent,workflow,capture=case.result,case.workflow,case.capture
    assert parent["status"]=="candidate",parent
    assert parent["arguments"]["additions"]==[{"frame":2,"position":[0.,0.,0.],"mode":"LINEAR"}]
    assert parent["existing_writes"]==[] and parent["chunks"]==[]
    assert np.array_equal(parent["predicted_target"]["position_m"]["a"],capture.position_m["a"])
    assert np.asarray(parent["refinement"]["final_target"]["position_m"]["a"])==pytest.approx(case.goal["a"],abs=1e-7)
    proof=KeyTopologyDelta.model_validate(parent["key_topology_delta"]).locator_insertion
    successor={**capture.source_binding,"sample_digest":canonical_digest({"domain_successor":True})}
    workflow.source_binding=successor
    fresh=replace(capture,source_binding=successor)
    after={**deepcopy(case.observed),"capture_digest":canonical_digest(fresh.as_dict()),
           "drivers":[proof.expected_driver.model_dump(mode="json")]}
    workflow.service.observe_key_layout=lambda request:SimpleNamespace(ok=True,result=after)
    captures=[]
    def actual_capture(ids,*,space,required_rotation_ids=()):
        captures.append((space,required_rotation_ids))
        return replace(fresh,space=space)
    monkeypatch.setattr(workflow,"capture_batch",actual_capture)
    completion={name:getattr(proof,name) for name in ("contract","request_digest","source_binding_digest",
        "runtime_epoch","runtime_fingerprint","scene_instance_id","document_lineage_id","before_projection_digest")}
    completion.update(key_layout_digest=canonical_digest(after),adapter_evidence_ref=parent["key_topology_delta"]["adapter_evidence_ref"],
        after_projection_digest=canonical_digest({"domain_after":True}),
        completion_receipt_digest=canonical_digest({"domain_completion":True}))
    rejected=SimpleNamespace(ok=False,result={})
    workflow.service.verify_key_topology=lambda *args:rejected
    binds=len(case.bound)
    with pytest.raises(MotionInputError,match="KEY_TOPOLOGY_READBACK_UNVERIFIED"):
        workflow.plan_refined_correction(parent)
    assert len(case.bound)==binds
    workflow.service.verify_key_topology=lambda *args:SimpleNamespace(ok=True,result={
        "key_layout_digest":canonical_digest(after),"completion_receipt_digest":completion["completion_receipt_digest"],
        "locator_insertion_completion":completion})
    result=workflow.plan_refined_correction(parent)
    assert result["status"]=="candidate"
    assert result["operation_name"]=="animation.position_keys_set" and result["arguments"]["space"]=="global"
    assert [row["frame"] for row in result["arguments"]["writes"]]==[2,4]
    assert np.asarray([row["position"] for row in result["arguments"]["writes"]])==pytest.approx(np.asarray([[1.,0.,0.],[1.,0.,0.]]),abs=1e-6)
    assert result["refinement_parent_digest"]==canonical_digest(parent)
    assert result["report"]["completion_receipt_digest"]==completion["completion_receipt_digest"]
    assert all(rotations==("a",) for _,rotations in captures)
    assert canonical_digest(capture.as_dict())==case.before_digest
    plan=SimpleNamespace(spec=SimpleNamespace(character=SimpleNamespace(object_ids=("a",))))
    runner=RecipeRunner.__new__(RecipeRunner)
    prediction=runner._refinement_prediction(result,parent,plan)
    assert prediction.source_binding.model_dump(mode="json")==successor
    assert prediction.position_m["a"]==pytest.approx(case.goal["a"],abs=1e-7)
    tampered=deepcopy(result)
    tampered["refinement_prediction"]["position_m"]["a"][3][0]+=.001
    with pytest.raises(RecipeConflict,match="REFINEMENT_TARGET_DIFFERS_FROM_RETAINED_DRIVER"):
        runner._refinement_prediction(tampered,parent,plan)
    tampered=deepcopy(parent)
    tampered["refinement"]["final_driver"]["segment_modes"][0]="STEP"
    binds=len(case.bound)
    with pytest.raises(MotionInputError,match="KEY_REFINEMENT_TOPOLOGY_CHANGED"):
        workflow.plan_refined_correction(tampered)
    assert len(case.bound)==binds
    # Exercise the real phase-specific quality logic using host capture
    # doubles. A neutral insertion cannot satisfy the deferred final target.
    from cascadeur_complete.motion_quality import QualityPolicy,required_motion_metrics
    baseline=replace(capture,space="global")
    required=required_motion_metrics(case.rig,case.intent,capture=baseline)|{"acceleration_m_s2"}
    quality=QualityPolicy(profile_id="domain",profile_revision="1",required_metrics=tuple(sorted(required)),
        limits_si={**{name:0. for name in required},"position_correction_m":.03,"acceleration_m_s2":100.})
    plan.spec.intent,plan.spec.quality,plan.spec.export=case.intent,quality,None
    runner._profile=lambda spec:case.rig
    runner._supports=lambda spec:{}
    runner._latest=lambda run,stage:{"global":baseline.as_dict()} if stage=="baseline_capture" else parent
    runner._cleanup_result=lambda run,plan,stage,index:parent
    runner._correction_candidate=lambda *args:result
    runner.service=SimpleNamespace(recipe_verify_capture=lambda actual,sha:SimpleNamespace(ok=True,result={"capture_digest":sha}))
    insertion_step=SimpleNamespace(stage="insertion_readback",fixed_parameters={"cleanup_index":0})
    actual_step=SimpleNamespace(stage="actual_readback",fixed_parameters={"cleanup_index":0})
    neutral={"local":fresh.as_dict(),"global":replace(fresh,space="global").as_dict()}
    report=runner._verify_actual(None,plan,neutral,insertion_step)
    assert report["status"]=="pass",report
    assert report["quality_scope"]=="insertion_interim_integrity"
    assert "acceleration_m_s2" in report["deferred_required_metrics"]
    report=runner._verify_actual(None,plan,neutral,actual_step)
    assert report["status"]=="fail"
    assert "REFINEMENT_PREDICTION_READBACK_MISMATCH:position_readback_m" in report["reason_codes"]
    final_actual={"global":prediction.as_dict(),"local":replace(prediction,space="local").as_dict()}
    report=runner._verify_actual(None,plan,final_actual,actual_step)
    assert report["status"]=="pass",report
    assert report["quality_scope"]=="refinement_final_native"
    assert "acceleration_m_s2" in report["evaluated_required_metrics"]


def test_sparse_insertion_requests_protected_rotations_in_both_actual_spaces(monkeypatch):
    from dataclasses import replace
    from types import SimpleNamespace
    from cascadeur_complete.cleanup_workflow import CleanupWorkflow
    capture,rig,intent,_,_,goal=_sparse_refinement_case()
    rig=replace(rig,role_ids={"root":"a"})
    intent=intent.model_copy(update={"root_policy":"explicit_mapped_trajectory"})
    service=SimpleNamespace(observe_key_layout=lambda request:SimpleNamespace(ok=False))
    workflow=CleanupWorkflow(service,profile=rig,context=capture.context,intent=intent,source_binding=capture.source_binding)
    calls=[]
    def actual_capture(ids,*,space,required_rotation_ids):
        calls.append((space,required_rotation_ids))
        return replace(capture,space=space,rotation_wxyz={"a":np.tile([1.,0.,0.,0.],(9,1))},
                       channel_valid={"a":np.ones((9,2),dtype=bool)})
    monkeypatch.setattr(workflow,"capture_batch",actual_capture)
    with pytest.raises(MotionInputError,match="INTERPOLATION_MODEL_UNVERIFIED"):
        workflow._plan_sparse_insertion(replace(capture,space="global"),goal,{}, {},1,{},frozenset(("a",)))
    assert calls==[("global",("a",)),("local",("a",))]
