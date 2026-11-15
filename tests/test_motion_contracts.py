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
