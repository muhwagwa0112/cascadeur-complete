"""Explicit hand styling in seconds, metres and declared anatomical frames."""
from __future__ import annotations

import numpy as np
from scipy.spatial.transform import Rotation

from .motion_context import MotionInputError, SolverResult, validate_samples
from .motion_math import hemisphere_continuous, smooth_rotations, solve_two_bone


def pulse_envelope_seconds(time_s, pulses_s, *, attack_s=.04, release_s=.08):
    t=np.asarray(time_s,dtype=float)
    if t.ndim!=1 or not len(t) or not np.isfinite(t).all() or np.any(np.diff(t)<=0):
        raise MotionInputError("INVALID_POLICY","finite increasing physical time grid required")
    if not pulses_s or not np.isfinite([attack_s,release_s]).all() or min(attack_s,release_s)<=0:
        raise MotionInputError("INVALID_POLICY","nonempty pulses and positive attack/release seconds required")
    out=np.zeros(len(t)); previous=-np.inf
    for pulse in pulses_s:
        if len(pulse)!=2:
            raise MotionInputError("INVALID_POLICY","pulse must be a first/last time pair")
        first,last=map(float,pulse)
        if not np.isfinite([first,last]).all() or first< t[0] or last>t[-1] or last<=first or first<=previous:
            raise MotionInputError("INVALID_POLICY","pulses must be ordered, disjoint and within physical time coverage")
        previous=last
        duration=last-first
        attack=min(attack_s,duration/2); release=min(release_s,duration/2)
        x=np.clip((t-first)/attack,0,1); y=np.clip((last-t)/release,0,1)
        out=np.maximum(out,(x*x*(3-2*x))*(y*y*(3-2*y)))
    if not np.any(out>0):
        raise MotionInputError("KEY_LAYOUT_INSUFFICIENT","no sample lies within the requested pulse")
    return out


def style_rotation_targets(batch,rig,intent,kind,parameters):
    if intent.action!="styling":
        return SolverResult("failed",["INTENT_LOCK_VIOLATION"])
    selected=parameters.get("joint_ids") or [key for role,key in rig.role_ids.items()
                if ("finger" in role.lower() if kind in ("hand_pose","finger_fan") else role.lower().endswith("wrist"))]
    if not selected:
        return SolverResult("unsupported",["RIG_MAPPING_AMBIGUOUS"])
    validate_samples(batch,{key:("rotation",) for key in selected})
    inverse={key:role for role,key in rig.role_ids.items()}
    result,report={},{}
    for key in selected:
        role=inverse[key]
        q=hemisphere_continuous(batch.rotation_wxyz[key]); original=Rotation.from_quat(q[:,[1,2,3,0]])
        rest=rig.rest_local_transforms.get(key,rig.rest_local_transforms.get(role,{}))
        rest_q=rest.get("rotation_wxyz") if isinstance(rest,dict) else None
        if rest_q is None:
            return SolverResult("unsupported",["RIG_ADAPTER_UNVERIFIED"],report={"missing_rest_rotation":role})
        reference=Rotation.from_quat(np.asarray(rest_q)[[1,2,3,0]])
        delta=(reference.inv()*original).as_rotvec()
        axis=rig.joint_axes.get(role)
        if isinstance(axis,dict):
            axis=axis.get("splay" if kind=="finger_fan" else "flexion")
        axis=np.asarray(axis,dtype=float)
        if axis.shape!=(3,) or not np.isfinite(axis).all() or np.linalg.norm(axis)<1e-12:
            return SolverResult("unsupported",["RIG_ADAPTER_UNVERIFIED"],report={"missing_axis":role})
        axis=axis/np.linalg.norm(axis)
        twist=delta@axis
        if kind=="wrist_soften":
            bounds=rig.joint_limits_rad.get(role)
            if not isinstance(bounds,(list,tuple)) or len(bounds)!=2:
                return SolverResult("unsupported",["JOINT_LIMITS_UNAVAILABLE"],report={"role":role})
            low,high=map(float,bounds)
            if not np.isfinite([low,high]).all() or low>=high:
                return SolverResult("failed",["INVALID_POLICY"])
            desired=np.clip(twist,low,high)
        elif kind=="finger_fan":
            if ".index." not in role.lower() and not role.lower().endswith("index"):
                continue
            desired=np.full(len(q),float(parameters.get("target_angle_rad",np.radians(parameters.get("target_deg",3.)))))
        else:
            authored=parameters.get("pose_angles_rad",{})
            if role not in authored:
                continue  # An explicit pose never silently rewrites unrelated fingers.
            desired=np.asarray(authored[role],dtype=float)
            if desired.ndim==0:
                desired=np.full(len(q),float(desired))
            if desired.shape!=(len(q),) or not np.isfinite(desired).all():
                return SolverResult("failed",["INVALID_POLICY"])
        target=reference*Rotation.from_rotvec(delta+(desired-twist)[:,None]*axis)
        lock=np.isin(batch.context.frames,list(set(intent.locked_roles_frames.get(role,()))|set(intent.key_pose_locks.get(role,{}))))
        editable=(batch.context.frames>=intent.editable_frames[0])&(batch.context.frames<=intent.editable_frames[1])
        target_q=smooth_rotations(target.as_quat()[:,[3,0,1,2]],batch.context.time_s,
            sigma_s=float(parameters.get("sigma_s",.05)),editable_mask=editable,locks=lock)
        target_q[~editable|lock]=q[~editable|lock]
        change=(original.inv()*Rotation.from_quat(target_q[:,[1,2,3,0]])).magnitude()
        cap=float(intent.correction_envelope.get("rotation_rad",0.))
        if change.max(initial=0)>cap+1e-8:
            return SolverResult("failed",["CORRECTION_ENVELOPE_EXCEEDED"],report={"role":role,"max_rad":float(change.max())})
        result[key]=target_q
        report[role]={"max_correction_rad":float(change.max(initial=0))}
    if not result:
        return SolverResult("no_change",report={"constraints_checked":True})
    changed=any(np.max(np.abs(value-batch.rotation_wxyz[key]))>1e-10 for key,value in result.items())
    return SolverResult("candidate" if changed else "no_change",values={"rotation_wxyz":result},
                        report={"roles":report,"runtime_quality":"unverified"})


def wrist_accent_targets(batch,rig,intent,parameters):
    if intent.action!="styling":
        return SolverResult("failed",["INTENT_LOCK_VIOLATION"])
    side=parameters.get("side")
    roles=[f"{side}.{suffix}" for suffix in ("wrist","hand_direction","hand_additional","hand_frame")]
    if any(role not in rig.role_ids for role in roles):
        return SolverResult("unsupported",["RIG_MAPPING_AMBIGUOUS"])
    wrist,direction,additional,frame=[rig.role_ids[role] for role in roles]
    validate_samples(batch,{wrist:("position",),direction:("position",),additional:("position",),frame:("rotation",)})
    axis=np.asarray(rig.joint_axes.get(f"{side}.wrist_flexion_local"),dtype=float)
    if axis.shape!=(3,) or not np.isfinite(axis).all() or np.linalg.norm(axis)<1e-12:
        return SolverResult("unsupported",["RIG_ADAPTER_UNVERIFIED"])
    pulse=parameters.get("pulses_s")
    if pulse is None and "pulses" in parameters:
        lookup=dict(zip(map(int,batch.context.frames),batch.context.time_s,strict=True))
        pulse=[]
        for pair in parameters["pulses"]:
            if len(pair)!=2 or any(isinstance(f,bool) or not isinstance(f,int) or f not in lookup for f in pair):
                raise MotionInputError("INVALID_POLICY","pulse frame ids must be exact captured integers")
            pulse.append([lookup[pair[0]],lookup[pair[1]]])
    envelope=pulse_envelope_seconds(batch.context.time_s,pulse,attack_s=parameters.get("attack_s",.04),release_s=parameters.get("release_s",.08))
    amplitude=float(parameters.get("amplitude_rad",np.radians(parameters.get("amplitude_deg",15.))))
    cap=float(intent.correction_envelope.get("rotation_rad",0.))
    if not np.isfinite(amplitude) or abs(amplitude)>cap:
        return SolverResult("failed",["CORRECTION_ENVELOPE_EXCEEDED"])
    local_axis=axis/np.linalg.norm(axis)
    global_axis=Rotation.from_quat(batch.rotation_wxyz[frame][:,[1,2,3,0]]).apply(local_axis)
    rotation=Rotation.from_rotvec(global_axis*(envelope*amplitude)[:,None])
    targets={key:batch.position_m[wrist]+rotation.apply(batch.position_m[key]-batch.position_m[wrist]) for key in (direction,additional)}
    return SolverResult("candidate",values={"position_m":targets},report={"runtime_quality":"unverified","pulses_s":pulse})


def hand_rest_targets(batch,rig,supports,intent,parameters):
    """Only approved hand contacts generate goals; proximity never creates intent."""
    contacts=[c for c in intent.contacts if "hand" in c.role.lower() or c.role.lower().endswith("wrist")]
    if not contacts:
        return SolverResult("unsupported",["CONTACT_INTENT_AMBIGUOUS"])
    targets={}
    for contact in contacts:
        if contact.mode=="free":
            continue
        side=contact.role.split('.')[0]
        roles=[f"{side}.{name}" for name in ("shoulder","elbow","wrist")]
        if any(role not in rig.role_ids for role in roles) or contact.support_id not in supports:
            return SolverResult("unsupported",["RIG_MAPPING_AMBIGUOUS"])
        shoulder,elbow,wrist=[rig.role_ids[role] for role in roles]
        validate_samples(batch,{key:("position",) for key in (shoulder,elbow,wrist)})
        if contact.anchor_local_m is None:
            return SolverResult("unsupported",["CONTACT_INTENT_AMBIGUOUS"],report={"detail":"hand rest requires an approved support-local anchor"})
        support=supports[contact.support_id]
        anchors=support.anchors_world(contact.anchor_local_m)
        w=batch.position_m[wrist].copy(); e=batch.position_m[elbow].copy()
        for row,frame in enumerate(batch.context.frames):
            if not contact.first_frame<=frame<=contact.last_frame:
                continue
            if frame in intent.locked_roles_frames.get(f"{side}.wrist",()):
                if np.linalg.norm(anchors[row]-w[row])>1e-9:
                    return SolverResult("failed",["INTENT_LOCK_VIOLATION"])
            result=solve_two_bone(batch.position_m[shoulder][row],e[row],anchors[row],
                rig.bone_lengths_m.get(f"{side}.upper_arm",np.nan),rig.bone_lengths_m.get(f"{side}.forearm",np.nan),
                pole_axis=rig.joint_axes.get(f"{side}.elbow_pole"))
            if result.status!="candidate":
                return SolverResult("failed",["CONTACT_REACH_CONFLICT"])
            e[row],w[row]=result.elbow_m,result.wrist_m
        targets[elbow],targets[wrist]=e,w
    return SolverResult("candidate" if targets else "no_change",values={"position_m":targets},
                        report={"runtime_quality":"unverified","contact_provenance":"approved_schedule"})
