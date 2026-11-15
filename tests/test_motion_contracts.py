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
