"""Measured quality is independent of native execution and solver prediction."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import numpy as np
from pydantic import Field, model_validator
from scipy.spatial.transform import Rotation

from .motion_context import MotionInputError, MotionModel, SampleBatch, validate_samples


class QualityPolicy(MotionModel):
    profile_id: str
    profile_revision: str
    calibration_status: Literal["proposed", "host_checked", "runtime_calibrated"] = "proposed"
    required_metrics: tuple[str, ...]
    limits_si: dict[str, float]
    coverage: Literal["sampled_frames", "verified_continuous"] = "sampled_frames"
    collision_semantics: Literal["volume", "oriented_patch", "unsigned_surface"] = "volume"
    permitted_contact_allowances: dict[str, float] = Field(default_factory=dict)
    required_export_roundtrip: bool = False

    @model_validator(mode="after")
    def valid_policy(self):
        if (not self.profile_id or not self.profile_revision or not self.required_metrics
                or len(set(self.required_metrics)) != len(self.required_metrics)):
            raise ValueError("unique required metrics and profile identity required")
        if any(v < 0 for v in (*self.limits_si.values(), *self.permitted_contact_allowances.values())):
            raise ValueError("quality thresholds must be nonnegative")
        if any(name not in self.limits_si for name in self.required_metrics):
            raise ValueError("each required metric needs its own SI threshold")
        return self


@dataclass
class QualityReport:
    status: Literal["pass", "fail", "unverified", "not_applicable"]
    metrics: dict = field(default_factory=dict)
    reason_codes: list[str] = field(default_factory=list)
    coverage: str = "sampled_frames"
    runtime_verified: bool = False
    capture_digest: str | None = None

    @property
    def passed(self):
        return self.status == "pass"

    def as_dict(self):
        return {"status": self.status, "metrics": self.metrics, "reason_codes": self.reason_codes,
                "coverage": self.coverage, "runtime_verified": self.runtime_verified,
                "capture_digest": self.capture_digest}


def required_motion_metrics(rig,intent,include_mesh=False,*,capture=None):
    """The minimum scenario closure is independent of the caller's policy list."""
    required={"duration_error_s","position_correction_m","correction_envelope_violation_count"}
    if intent.root_policy=="preserve":
        required.update(("root_preservation_m","root_preservation_rad"))
    if rig.parent_ids or rig.bone_lengths_m:
        required.add("bone_length_error_m")
    if rig.dependency_ids or rig.derived_ids or set(rig.role_ids.values())-rig.writable_ids:
        required.add("non_target_scope_m")
    if intent.locked_roles_frames or any(len(value)==3 for locks in intent.key_pose_locks.values() for value in locks.values()):
        required.add("key_pose_position_m")
    if any(len(value)==4 for locks in intent.key_pose_locks.values() for value in locks.values()):
        required.add("key_pose_rotation_rad")
    if capture is not None:
        if any(np.asarray(value).shape==(len(capture.context.frames),4) for value in capture.rotation_wxyz.values()):
            required.add("rotation_correction_rad")
        if np.any((capture.context.frames<intent.editable_frames[0])|(capture.context.frames>intent.editable_frames[1])):
            required.add("key_pose_position_m")
    elif any("finger" in role.lower() or role.lower().endswith("hand_frame") for role in rig.role_ids):
        required.add("rotation_correction_rad")
    contacts=[contact for contact in intent.contacts if contact.mode!="free"]
    if contacts:
        required.add("contact_gap_m")
    if any(contact.mode in ("planted","rolling") for contact in contacts):
        required.add("contact_drift_m")
    if include_mesh:
        required.update(("mesh_penetration_m","mesh_surface_intersection_count"))
    return frozenset(required)


def validate_quality_policy(policy,rig,intent,include_mesh=False,*,capture=None):
    if not isinstance(policy,QualityPolicy):
        policy=QualityPolicy.model_validate(policy)
    required=required_motion_metrics(rig,intent,include_mesh,capture=capture)
    missing=required-set(policy.required_metrics)
    if missing:
        raise MotionInputError("QUALITY_POLICY_INCOMPLETE","required scenario metrics omitted: "+", ".join(sorted(missing)))
    for metric,channel in (("position_correction_m","position_m"),("rotation_correction_rad","rotation_rad")):
        cap=intent.correction_envelope.get(channel,0.)
        if metric in policy.limits_si and policy.limits_si[metric]>cap+1e-12:
            raise MotionInputError("QUALITY_POLICY_INCOMPLETE",f"{metric} threshold exceeds original intent envelope")
    if policy.limits_si["correction_envelope_violation_count"]!=0:
        raise MotionInputError("QUALITY_POLICY_INCOMPLETE","original role/channel envelope violations must have a zero threshold")
    return required


def measured_metric(values, *, units: str, frame_ids=None):
    values = np.asarray(values, dtype=float)
    if not values.size or not np.isfinite(values).all():
        return {"status": "unverified", "reason": "INCOMPLETE_METRIC", "units": units}
    worst = int(np.argmax(values))
    return {"status": "measured", "units": units, "max": float(values.max()),
            "p50": float(np.percentile(values, 50)), "p95": float(np.percentile(values, 95)),
            "sample_count": int(values.size),
            "worst_frame": None if frame_ids is None else int(np.asarray(frame_ids)[worst % len(frame_ids)])}


def evaluate_metrics(metrics: dict, policy: QualityPolicy, *, coverage="sampled_frames",
                     runtime_verified=False, capture_digest=None,rig=None,intent=None,include_mesh=False,capture=None):
    reports, missing, failed = dict(metrics), [], []
    if rig is not None and intent is not None:
        try:
            validate_quality_policy(policy,rig,intent,include_mesh,capture=capture)
        except MotionInputError as exc:
            return QualityReport("unverified",reports,[str(exc)],coverage,runtime_verified,capture_digest)
    for name in policy.required_metrics:
        metric = reports.get(name)
        if (not isinstance(metric, dict) or metric.get("status") != "measured"
                or not isinstance(metric.get("max"), (int, float)) or not np.isfinite(metric["max"])
                or metric.get("sample_count", 0) <= 0):
            missing.append(name)
            continue
        reports[name] = {**metric, "limit": policy.limits_si[name],
                         "pass": metric["max"] <= policy.limits_si[name]}
        if not reports[name]["pass"]:
            failed.append(name)
    if policy.coverage == "verified_continuous" and coverage != "verified_continuous":
        missing.append("CONTINUOUS_COVERAGE_UNVERIFIED")
    status = "fail" if failed else "unverified" if missing else "pass"
    reasons = [f"METRIC_FAILED:{name}" for name in failed] + [f"METRIC_UNVERIFIED:{name}" for name in missing]
    return QualityReport(status, reports, reasons, coverage, runtime_verified, capture_digest)


def contact_metrics(batch, rig, supports, contacts, *, reference_batch=None):
    """Measure the original schedule in support-local coordinates, including rotating supports."""
    from .motion_math import normalise_quaternions
    gaps, drifts, frames = [], [], []
    for contact in contacts:
        if contact.mode == "free":
            continue
        if contact.role not in rig.role_ids or contact.support_id not in supports:
            raise MotionInputError("CONTACT_INTENT_AMBIGUOUS", "missing declared contact role/support")
        support = supports[contact.support_id]
        ids = np.where((batch.context.frames >= contact.first_frame) & (batch.context.frames <= contact.last_frame))[0]
        if not len(ids) or contact.first_frame not in batch.context.frames or contact.last_frame not in batch.context.frames:
            raise MotionInputError("INCOMPLETE_CAPTURE", "contact interval not captured")
        point = batch.position_m[rig.role_ids[contact.role]]
        rotation = Rotation.from_quat(normalise_quaternions(support.rotation_wxyz)[:, [1, 2, 3, 0]])
        local = rotation.inv().apply(point - np.asarray(support.origin_m))
        effective=contact
        if contact.anchor_local_m is None and isinstance(support.geometry,dict) and support.geometry.get("kind")=="plane":
            original=batch if reference_batch is None else reference_batch
            validate_samples(original,{rig.role_ids[contact.role]:("position",)})
            original_local=rotation.inv().apply(original.position_m[rig.role_ids[contact.role]]-support.origin_m)
            normal=np.asarray(support.geometry["normal_local"],dtype=float)
            normal=normal/np.linalg.norm(normal)
            anchor=original_local[ids[0]].copy()
            anchor-=(anchor@normal-float(support.geometry.get("offset_m",0)))*normal
            effective=contact.model_copy(update={"anchor_local_m":tuple(anchor)})
        anchors,normal,gap=support.contact_reference(effective,local)
        delta=local[ids]-anchors[ids]
        tangent=delta-np.einsum("ij,ij->i",delta,normal[ids])[:,None]*normal[ids]
        gaps.extend(np.abs(gap[ids]))
        if contact.mode in ("planted", "rolling"):
            drifts.extend(np.linalg.norm(tangent, axis=1))
        frames.extend(batch.context.frames[ids])
    out = {}
    if gaps:
        out["contact_gap_m"] = measured_metric(gaps, units="m", frame_ids=frames)
    if drifts:
        out["contact_drift_m"] = measured_metric(drifts, units="m")
    return out


def compare_captures(before: SampleBatch, after: SampleBatch, mapping=None):
    if (not np.array_equal(before.context.time_s, after.context.time_s)
            or before.space != after.space):
        raise MotionInputError("EXPORT_TIME_GRID_MISMATCH", "captures must share physical time grid and space")
    mapping = mapping or {key: key for key in before.object_ids}
    positions, rotations = [], []
    for source, target in mapping.items():
        channels = []
        if source in before.position_m:
            channels.append("position")
        if source in before.rotation_wxyz and np.asarray(before.channel_valid[source])[:, 1].all():
            channels.append("rotation")
        validate_samples(before, {source: tuple(channels)})
        validate_samples(after, {target: tuple(channels)})
        if "position" in channels:
            positions.extend(np.linalg.norm(after.position_m[target] - before.position_m[source], axis=1))
        if "rotation" in channels:
            a = Rotation.from_quat(before.rotation_wxyz[source][:, [1, 2, 3, 0]])
            b = Rotation.from_quat(after.rotation_wxyz[target][:, [1, 2, 3, 0]])
            rotations.extend((a.inv() * b).magnitude())
    result = {}
    if positions:
        result["position_readback_m"] = measured_metric(positions, units="m")
    if rotations:
        result["rotation_readback_rad"] = measured_metric(rotations, units="rad")
    result["duration_error_s"] = measured_metric(
        [abs((after.context.time_s[-1] - after.context.time_s[0]) -
             (before.context.time_s[-1] - before.context.time_s[0]))], units="s")
    return result


def original_intent_metrics(before: SampleBatch, after: SampleBatch, rig, intent):
    """Measure invariants against the original capture, never an accepted prefix."""
    from .motion_math import angular_velocity, temporal_operators
    if before.space != after.space or not np.array_equal(before.context.time_s, after.context.time_s):
        raise MotionInputError("INCOMPLETE_CAPTURE", "intent comparison requires the complete original time grid")
    frames, n = before.context.frames, len(before.context.frames)
    outside = (frames < intent.editable_frames[0]) | (frames > intent.editable_frames[1])
    root_position, root_rotation, lock_position, lock_rotation, non_target, lengths = [], [], [], [], [], []
    corrections, angle_corrections, acceleration, jerk, angular_acceleration = [], [], [], [], []
    envelope_violations=[]
    d1, d2 = temporal_operators(before.context.time_s)
    for role,key in rig.role_ids.items():
        if key not in before.position_m or key not in after.position_m:
            continue
        channels=("position","rotation") if key in before.rotation_wxyz else ("position",)
        validate_samples(before,{key:channels}); validate_samples(after,{key:channels})
        error=np.linalg.norm(after.position_m[key]-before.position_m[key],axis=1)
        corrections.extend(error)
        cap=min(intent.correction_envelope.get("position_m",0.),intent.correction_envelope.get(f"{role}.position_m",np.inf))
        envelope_violations.extend((error>cap+1e-9).astype(float))
        root=role.lower() in ("root","pelvis.root","character.root","root_orientation")
        if root and intent.root_policy=="preserve":
            root_position.extend(error)
        mask=outside | np.isin(frames,list(intent.locked_roles_frames.get(role,())))
        lock_position.extend(error[mask])
        if key not in rig.writable_ids:
            non_target.extend(error)
        for frame,expected in intent.key_pose_locks.get(role,{}).items():
            rows=np.where(frames==int(frame))[0]
            if not len(rows):
                raise MotionInputError("INCOMPLETE_CAPTURE","key pose lock frame missing")
            expected=np.asarray(expected,dtype=float)
            if expected.shape==(3,):
                lock_position.append(float(np.linalg.norm(after.position_m[key][rows[0]]-expected)))
            elif expected.shape==(4,) and key in after.rotation_wxyz:
                expected_r=Rotation.from_quat(expected[[1,2,3,0]])
                actual_r=Rotation.from_quat(after.rotation_wxyz[key][rows[0],[1,2,3,0]])
                lock_rotation.append(float((expected_r.inv()*actual_r).magnitude()))
            else:
                raise MotionInputError("INVALID_POLICY","key pose lock must declare a position3 or quaternion4")
        parent=rig.parent_ids.get(key)
        if parent is not None:
            if parent not in after.position_m or parent not in before.position_m:
                raise MotionInputError("INCOMPLETE_CAPTURE","missing bone parent dependency")
            actual=np.linalg.norm(after.position_m[key]-after.position_m[parent],axis=1)
            expected=rig.bone_lengths_m.get(role)
            if expected is None:
                expected=np.linalg.norm(before.position_m[key]-before.position_m[parent],axis=1)
            lengths.extend(np.abs(actual-expected))
        if n>=3:
            dt=np.diff(before.context.time_s)
            velocity=np.diff(after.position_m[key],axis=0)/dt[:,None]
            dense=2*np.diff(velocity,axis=0)/(dt[:-1]+dt[1:])[:,None]
            acceleration.extend(np.linalg.norm(dense,axis=1))
            if n>=4:
                dt=np.diff(before.context.time_s[1:-1])
                jerk.extend(np.linalg.norm(np.diff(dense,axis=0)/dt[:,None],axis=1))
        if key in before.rotation_wxyz:
            a=Rotation.from_quat(before.rotation_wxyz[key][:,[1,2,3,0]])
            b=Rotation.from_quat(after.rotation_wxyz[key][:,[1,2,3,0]])
            angle=(a.inv()*b).magnitude()
            angle_corrections.extend(angle)
            cap=min(intent.correction_envelope.get("rotation_rad",0.),intent.correction_envelope.get(f"{role}.rotation_rad",np.inf))
            envelope_violations.extend((angle>cap+1e-9).astype(float))
            lock_rotation.extend(angle[mask])
            if root and intent.root_policy=="preserve":
                root_rotation.extend(angle)
            if n>=3:
                omega=angular_velocity(after.rotation_wxyz[key],after.context.time_s)
                midpoint=(after.context.time_s[1:]+after.context.time_s[:-1])/2
                angular_acceleration.extend(np.linalg.norm(np.diff(omega,axis=0)/np.diff(midpoint)[:,None],axis=1))
    for key in set(before.object_ids)-set(rig.role_ids.values()):
        if key not in rig.writable_ids:
            validate_samples(before,{key:("position",)});validate_samples(after,{key:("position",)})
            non_target.extend(np.linalg.norm(after.position_m[key]-before.position_m[key],axis=1))
    for side in ("Left","Right"):
        for bone,first,last in (("upper_leg","hip","knee"),("lower_leg","knee","ankle"),
                               ("upper_arm","shoulder","elbow"),("forearm","elbow","wrist")):
            declared=rig.bone_lengths_m.get(f"{side}.{bone}")
            if declared is None:
                continue
            first_id,last_id=rig.role_ids.get(f"{side}.{first}"),rig.role_ids.get(f"{side}.{last}")
            if first_id is None or last_id is None:
                raise MotionInputError("RIG_MAPPING_AMBIGUOUS","declared bone length is missing endpoint roles")
            validate_samples(after,{first_id:("position",),last_id:("position",)})
            lengths.extend(np.abs(np.linalg.norm(after.position_m[last_id]-after.position_m[first_id],axis=1)-declared))
    result={"duration_error_s":measured_metric([abs((after.context.time_s[-1]-after.context.time_s[0])-(before.context.time_s[-1]-before.context.time_s[0]))],units="s")}
    for name,values,units in (("root_preservation_m",root_position,"m"),("root_preservation_rad",root_rotation,"rad"),
          ("key_pose_position_m",lock_position,"m"),("key_pose_rotation_rad",lock_rotation,"rad"),
          ("non_target_scope_m",non_target,"m"),("bone_length_error_m",lengths,"m"),
          ("position_correction_m",corrections,"m"),("rotation_correction_rad",angle_corrections,"rad"),
          ("acceleration_m_s2",acceleration,"m/s2"),("jerk_m_s3",jerk,"m/s3"),
          ("angular_acceleration_rad_s2",angular_acceleration,"rad/s2"),
          ("correction_envelope_violation_count",envelope_violations,"count")):
        if values:
            result[name]=measured_metric(values,units=units)
    return result


def evaluate_candidate(plan, evaluator, *, capture_scope, provenance_verifier=None):
    """Actual evaluation is supplied by a verified readback adapter, not a solver flag."""
    if evaluator is None or not callable(getattr(evaluator,"evaluate_candidate",None)):
        return QualityReport("unverified",reason_codes=["ACTUAL_READBACK_ADAPTER_UNAVAILABLE"])
    report=evaluator.evaluate_candidate(plan,capture_scope=capture_scope)
    if not isinstance(report,QualityReport) or not report.capture_digest:
        return QualityReport("unverified",reason_codes=["ACTUAL_CAPTURE_DIGEST_MISSING"])
    from .capture import canonical_digest
    evidence={"plan":plan,"scope":capture_scope,"report":report.as_dict()}
    digest=canonical_digest(evidence)
    receipt=provenance_verifier(evidence,digest) if callable(provenance_verifier) else None
    result=getattr(receipt,"result",None)
    if not (getattr(receipt,"ok",False) and isinstance(result,dict) and result.get("evaluation_digest")==digest):
        report.runtime_verified=False
        if report.status!="fail":report.status="unverified"
        report.reason_codes.append("ACTUAL_CAPTURE_PROVENANCE_UNVERIFIED")
    return report


def actual_mesh_metrics(geometry,policy,*,verifier,required_mesh_ids=()):
    """Measure actual evaluated triangle pairs on the exact physical grid.

    ``geometry`` contains immutable window manifests and tracks, not a solver's
    predicted capsules or baseline vertices. Its authenticated manifest binds
    terminal completion, successor/source, topology, skin and canonical units.
    """
    from .capture import canonical_digest
    from .motion_geometry import triangle_pair_distance
    manifest=geometry.get("manifest",{})
    required=("capture_kind","source_digest","successor_digest","completion_receipt_digest",
              "topology_digest","skin_digest","context_digest","frames","time_s","windows")
    if any(not manifest.get(key) for key in required) or manifest.get("capture_kind") not in ("native_actual","target_actual"):
        raise MotionInputError("ACTUAL_MESH_PROVENANCE_UNVERIFIED","evaluated geometry provenance is incomplete")
    if manifest.get("space")!="global" or manifest.get("units")!="metres":
        raise MotionInputError("ACTUAL_MESH_PROVENANCE_UNVERIFIED","actual meshes must be global canonical metres")
    frames=manifest["frames"];times=np.asarray(manifest["time_s"],dtype=float)
    if (not frames or any(type(x) is not int for x in frames) or any(b<=a for a,b in zip(frames,frames[1:]))
            or times.shape!=(len(frames),) or not np.isfinite(times).all() or np.any(np.diff(times)<=0)):
        raise MotionInputError("INCOMPLETE_CAPTURE","actual geometry physical grid is invalid")
    digest=canonical_digest(manifest)
    receipt=verifier(manifest,digest) if callable(verifier) else None
    result=getattr(receipt,"result",None)
    if not (getattr(receipt,"ok",False) and isinstance(result,dict) and result.get("geometry_digest")==digest):
        raise MotionInputError("ACTUAL_MESH_PROVENANCE_UNVERIFIED","geometry window hashes and completion were not authenticated")
    tracks=geometry.get("tracks",{})
    pairs=manifest.get("pairs",())
    if not pairs or any(a not in tracks or b not in tracks or a==b for a,b in pairs):
        raise MotionInputError("INCOMPLETE_CAPTURE","actual collision pair closure is missing")
    if set(required_mesh_ids)-{key for pair in pairs for key in pair}:
        raise MotionInputError("INCOMPLETE_CAPTURE","required mesh is absent from actual collision pairs")
    from .motion_geometry import ObservedSurfaceTrack,WindowedSurfaceTrack
    for object_id,track in tracks.items():
        windows=manifest["windows"].get(object_id)
        if (not isinstance(track,(ObservedSurfaceTrack,WindowedSurfaceTrack))
                or not windows or getattr(track,"windows",None)!=windows
                or not np.array_equal(getattr(track,"frames",()),frames)
                or canonical_digest(track.context.as_dict())!=manifest["context_digest"]):
            raise MotionInputError("ACTUAL_MESH_PROVENANCE_UNVERIFIED","track does not match authenticated evaluated windows")
        if track.semantics!=policy.collision_semantics:
            raise MotionInputError("MESH_SIGN_UNVERIFIED","surface query semantics differ from the policy")
        if policy.collision_semantics=="oriented_patch" and not (
                track.orientation_observed and manifest.get("orientation_evidence",{}).get(object_id)):
            raise MotionInputError("MESH_SIGN_UNVERIFIED","patch orientation has no authenticated observation")
    if manifest.get("contact_allowances"):
        # Unsupported exemptions cannot silently erase measured intersections.
        raise MotionInputError("CONTACT_REGION_UNVERIFIED","triangle-region contact exemptions require an observed region adapter")
    budget=geometry.get("max_pair_checks",1_000_000)
    query_budget=geometry.get("max_surface_queries",1_000_000)
    if type(budget) is not int or budget<1 or type(query_budget) is not int or query_budget<1:
        raise MotionInputError("INVALID_POLICY","positive exact triangle pair budget required")
    checks=queries=0;penetration=[];intersections=[];penetration_frames=[];intersection_frames=[]
    for row,_ in enumerate(frames):
        for a,b in pairs:
            left,right=tracks[a][row],tracks[b][row]
            queries+=len(left.vertices)+len(right.vertices)
            if queries>query_budget:
                raise MotionInputError("RESOURCE_BUDGET_EXCEEDED","exact surface query budget exhausted")
            distances=[]
            for source,target in ((left,right),(right,left)):
                for vertex in source.vertices:
                    query=target.closest(vertex)
                    if policy.collision_semantics=="volume":
                        if query.signed_distance_m is None:
                            raise MotionInputError("MESH_SIGN_UNVERIFIED","open or ambiguous mesh has no volume penetration sign")
                        distances.append(max(0.,-query.signed_distance_m))
                    elif policy.collision_semantics=="oriented_patch":
                        if query.signed_distance_m is None:
                            raise MotionInputError("MESH_SIGN_UNVERIFIED","oriented patch band is not observed")
                        distances.append(max(0.,-query.signed_distance_m))
                    else:
                        raise MotionInputError("MESH_SIGN_UNVERIFIED","unsigned distance cannot measure penetration")
            penetration.extend(distances)
            penetration_frames.extend([frames[row]]*len(distances))
            count=0
            right_triangles=right.vertices[right.triangles]
            lower=right_triangles.min(axis=1);upper=right_triangles.max(axis=1)
            for triangle in left.vertices[left.triangles]:
                candidates=np.flatnonzero(np.all(upper>=triangle.min(axis=0)-1e-10,axis=1)
                                          &np.all(lower<=triangle.max(axis=0)+1e-10,axis=1))
                checks+=len(candidates)
                if checks>budget:
                    raise MotionInputError("RESOURCE_BUDGET_EXCEEDED","exact mesh intersection query budget exhausted")
                count+=sum(triangle_pair_distance(triangle,right_triangles[index])<=1e-10 for index in candidates)
            intersections.append(float(count))
            intersection_frames.append(frames[row])
    return {"mesh_penetration_m":measured_metric(penetration,units="m",frame_ids=penetration_frames),
            "mesh_surface_intersection_count":measured_metric(intersections,units="count",frame_ids=intersection_frames)}


def evaluate_actual_quality(original,actual,rig,intent,policy,*,supports=None,prediction=None,
                            geometry=None,capture_verifier=None,geometry_verifier=None):
    """Canonical original→actual and prediction→actual closure after completion."""
    from .capture import canonical_digest
    digest=canonical_digest(actual.as_dict())
    try:
        include_mesh=bool(rig.mesh_ids)
        validate_quality_policy(policy,rig,intent,include_mesh,capture=original)
        metrics=original_intent_metrics(original,actual,rig,intent)
        if intent.contacts:
            metrics.update(contact_metrics(actual,rig,supports or {},intent.contacts,reference_batch=original))
        if prediction is not None:
            metrics.update(compare_captures(prediction,actual))
        if include_mesh and geometry is not None:
            if (geometry.get("manifest",{}).get("context_digest")!=canonical_digest(actual.context.as_dict())
                    or geometry.get("manifest",{}).get("motion_capture_digest")!=digest):
                raise MotionInputError("INCOMPLETE_CAPTURE","actual mesh and motion schedules differ")
            metrics.update(actual_mesh_metrics(geometry,policy,verifier=geometry_verifier,required_mesh_ids=rig.mesh_ids))
        receipt=capture_verifier(actual,digest) if callable(capture_verifier) else None
        result=getattr(receipt,"result",None)
        observed=bool(getattr(receipt,"ok",False) and isinstance(result,dict) and result.get("capture_digest")==digest)
        report=evaluate_metrics(metrics,policy,runtime_verified=observed,capture_digest=digest,
                                rig=rig,intent=intent,include_mesh=include_mesh,capture=actual)
        if not observed:
            if report.status!="fail": report.status="unverified"
            report.reason_codes.append("ACTUAL_CAPTURE_PROVENANCE_UNVERIFIED")
        return report
    except (MotionInputError,KeyError,ValueError) as exc:
        return QualityReport("unverified",reason_codes=[str(exc)],capture_digest=digest)


def validate_export_roundtrip(before_export: SampleBatch, exported_capture: SampleBatch,
                              export_profile, rig_mapping, intent, policy: QualityPolicy, *,
                              rig=None, original_reference=None, supports=None,
                              capture_verifier=None, mesh_evaluator=None):
    """Compare a measured target capture and the original, immutable intent.

    The importer supplies a trusted verification callback binding its actual
    observations to this capture digest. A pose-only comparison cannot attest
    target execution or the original cleanup constraints.
    """
    try:
        from .capture import canonical_digest
        from .motion_context import RigProfile, IntentConstraints
        policy=QualityPolicy.model_validate(policy) if isinstance(policy,dict) else policy
        intent=IntentConstraints.model_validate(intent) if isinstance(intent,dict) else intent
        digest=canonical_digest(exported_capture.as_dict())
        metrics = compare_captures(before_export, exported_capture, rig_mapping)
        if not isinstance(rig,RigProfile):
            return QualityReport("unverified",metrics,["EXPORT_RIG_MAPPING_AMBIGUOUS: complete RigProfile required for mandatory metric closure"],capture_digest=digest)
        include_mesh=bool(export_profile.get("include_mesh",False) if isinstance(export_profile,dict) else getattr(export_profile,"include_mesh",False))
        validate_quality_policy(policy,rig,intent,include_mesh,capture=before_export)
        if original_reference is None:
            return QualityReport("unverified",metrics,["ORIGINAL_INTENT_REFERENCE_UNAVAILABLE"],capture_digest=digest)
        mapping=rig_mapping or {key:key for key in before_export.object_ids}
        aligned=SampleBatch(exported_capture.context,tuple(mapping),exported_capture.space,
            {source:exported_capture.position_m[target] for source,target in mapping.items() if target in exported_capture.position_m},
            {source:exported_capture.rotation_wxyz[target] for source,target in mapping.items() if target in exported_capture.rotation_wxyz},
            {source:exported_capture.channel_valid[target] for source,target in mapping.items()},exported_capture.source_binding)
        metrics.update(original_intent_metrics(original_reference,aligned,rig,intent))
        if any(contact.mode!="free" for contact in intent.contacts):
            if supports is None:
                return QualityReport("unverified",metrics,["ORIGINAL_SUPPORT_REFERENCE_UNAVAILABLE"],capture_digest=digest)
            metrics.update(contact_metrics(aligned,rig,supports,intent.contacts,reference_batch=original_reference))
        if include_mesh and mesh_evaluator is not None:
            metrics.update(mesh_evaluator(exported_capture,rig,intent))
        observed=False
        if capture_verifier is not None:
            receipt=capture_verifier(exported_capture,digest)
            result=getattr(receipt,"result",None)
            observed=bool(getattr(receipt,"ok",False) and isinstance(result,dict) and result.get("capture_digest")==digest)
        report=evaluate_metrics(metrics,policy,runtime_verified=observed,capture_digest=digest,
                                rig=rig,intent=intent,include_mesh=include_mesh,capture=aligned)
        if not observed:
            report.runtime_verified=False
            if report.status!="fail":
                report.status="unverified"
            report.reason_codes.append("ACTUAL_CAPTURE_PROVENANCE_UNVERIFIED")
        return report
    except (MotionInputError, ValueError, KeyError) as exc:
        return QualityReport("unverified", reason_codes=[str(exc)])
