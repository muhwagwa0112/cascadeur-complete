"""Canonical, unit-aware motion inputs shared by cleanup, recipes and export.

These types describe host data. They do not invent an accessor in the native SDK.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator


class MotionInputError(ValueError):
    def __init__(self, code: str, detail: str):
        self.code = code
        super().__init__(f"{code}: {detail}")


class MotionModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class ContactSegment(MotionModel):
    role: str
    support_id: str
    first_frame: StrictInt
    last_frame: StrictInt
    mode: Literal["planted", "rolling", "sliding", "free"]
    anchor_local_m: tuple[float, float, float] | None = None
    triangle_id: StrictInt | None = None
    barycentric: tuple[float, float, float] | None = None
    provenance: Literal["explicit", "imported", "approved_detection"]

    @model_validator(mode="after")
    def valid_interval(self):
        if self.first_frame < 0 or self.last_frame < self.first_frame:
            raise ValueError("invalid contact interval")
        if self.barycentric is not None and (
            min(self.barycentric) < 0 or not np.isclose(sum(self.barycentric), 1.0, atol=1e-9)
        ):
            raise ValueError("invalid barycentric coordinates")
        if (self.triangle_id is None) != (self.barycentric is None):
            raise ValueError("triangle_id and barycentric must be specified together")
        return self


class IntentConstraints(MotionModel):
    action: Literal["repair", "styling", "retarget"] = "repair"
    editable_frames: tuple[StrictInt, StrictInt]
    root_policy: Literal["preserve", "explicit_mapped_trajectory"] = "preserve"
    contacts: tuple[ContactSegment, ...] = ()
    locked_roles_frames: dict[str, tuple[StrictInt, ...]] = Field(default_factory=dict)
    key_pose_locks: dict[str, dict[int, list[float]]] = Field(default_factory=dict)
    preserve_timing: bool = True
    allow_key_insertion: bool = False
    allow_interpolation_change: bool = False
    correction_envelope: dict[str, float] = Field(default_factory=dict)

    @model_validator(mode="after")
    def valid_intent(self):
        first, last = self.editable_frames
        if first < 0 or last < first:
            raise ValueError("invalid editable interval")
        if any(value < 0 for value in self.correction_envelope.values()):
            raise ValueError("correction envelope must be nonnegative")
        if any(key not in ("position_m","rotation_rad","added_keys") and not key.endswith((".position_m",".rotation_rad")) for key in self.correction_envelope):
            raise ValueError("correction envelope supports position_m, rotation_rad, added_keys or semantic-role channel limits")
        keys=self.correction_envelope.get("added_keys",0)
        if keys!=int(keys) or (keys and not self.allow_key_insertion):
            raise ValueError("added_keys must be an integer and needs explicit allow_key_insertion")
        if any(c.first_frame < first or c.last_frame > last for c in self.contacts):
            raise ValueError("contact outside editable interval")
        return self


@dataclass(frozen=True)
class MotionContext:
    frames: np.ndarray
    time_s: np.ndarray
    time_source: str
    fps_num: int
    fps_den: int
    metres_per_scene_unit: float
    scene_to_solver_basis: np.ndarray
    metadata_provenance: dict

    def __post_init__(self):
        frames = np.asarray(self.frames)
        times = np.asarray(self.time_s, dtype=np.float64)
        basis = np.asarray(self.scene_to_solver_basis, dtype=np.float64)
        if frames.ndim != 1 or not len(frames) or frames.dtype.kind not in "iu":
            raise MotionInputError("INVALID_POLICY", "frames must be a nonempty integer array")
        frames = frames.astype(np.int64, copy=True)
        if np.any(frames < 0) or np.any(np.diff(frames) <= 0):
            raise MotionInputError("INVALID_POLICY", "frames must be nonnegative and strictly increasing")
        if times.shape != frames.shape or not np.isfinite(times).all() or np.any(np.diff(times) <= 0):
            raise MotionInputError("INVALID_POLICY", "time coverage must be finite and strictly increasing")
        if (isinstance(self.fps_num, bool) or isinstance(self.fps_den, bool)
                or not isinstance(self.fps_num, int) or not isinstance(self.fps_den, int)
                or self.fps_num <= 0 or self.fps_den <= 0):
            raise MotionInputError("MISSING_CLIP_METADATA", "positive rational FPS is required")
        if self.time_source not in ("fps", "explicit"):
            raise MotionInputError("INVALID_POLICY", "unknown time source")
        if self.time_source == "fps" and not np.allclose(
            times, (frames - frames[0]) * self.fps_den / self.fps_num, rtol=0, atol=1e-12
        ):
            raise MotionInputError("INVALID_POLICY", "times disagree with rational FPS")
        if not np.isfinite(self.metres_per_scene_unit) or self.metres_per_scene_unit <= 0:
            raise MotionInputError("MISSING_CLIP_METADATA", "positive length scale is required")
        if (basis.shape != (3, 3) or not np.isfinite(basis).all()
                or not np.allclose(basis.T @ basis, np.eye(3), atol=1e-10, rtol=0)
                or not np.isclose(np.linalg.det(basis), 1.0, atol=1e-10)):
            raise MotionInputError("UNSUPPORTED_COORDINATE_SYSTEM", "basis must be a proper orthogonal matrix")
        if not self.metadata_provenance:
            raise MotionInputError("MISSING_CLIP_METADATA", "metadata provenance is required")
        times, basis = times.copy(), basis.copy()
        frames.flags.writeable = times.flags.writeable = basis.flags.writeable = False
        object.__setattr__(self, "frames", frames)
        object.__setattr__(self, "time_s", times)
        object.__setattr__(self, "scene_to_solver_basis", basis)

    @classmethod
    def from_dict(cls, value: dict) -> MotionContext:
        return cls(**value)

    def positions_to_solver(self, value):
        return np.asarray(value, dtype=np.float64) @ self.scene_to_solver_basis.T * self.metres_per_scene_unit

    def positions_to_scene(self, value):
        return np.asarray(value, dtype=np.float64) @ self.scene_to_solver_basis / self.metres_per_scene_unit

    def rotations_to_solver(self, matrices):
        c = self.scene_to_solver_basis
        return c @ np.asarray(matrices) @ c.T

    def as_dict(self):
        return {
            "frames": self.frames.tolist(), "time_s": self.time_s.tolist(), "time_source": self.time_source,
            "fps_num": self.fps_num, "fps_den": self.fps_den,
            "metres_per_scene_unit": self.metres_per_scene_unit,
            "scene_to_solver_basis": self.scene_to_solver_basis.tolist(),
            "metadata_provenance": self.metadata_provenance,
        }


@dataclass(frozen=True)
class RigProfile:
    profile_id: str
    character_id: str
    role_ids: dict[str, str]
    writable_ids: frozenset[str]
    derived_ids: frozenset[str] = frozenset()
    dependency_ids: frozenset[str] = frozenset()
    parent_ids: dict[str, str | None] = field(default_factory=dict)
    rest_local_transforms: dict = field(default_factory=dict)
    joint_axes: dict = field(default_factory=dict)
    joint_limits_rad: dict = field(default_factory=dict)
    bone_lengths_m: dict = field(default_factory=dict)
    mesh_ids: tuple[str, ...] = ()
    controller_adapter_id: str = ""

    def __post_init__(self):
        for name in ("writable_ids", "derived_ids", "dependency_ids"):
            object.__setattr__(self, name, frozenset(getattr(self, name)))
        object.__setattr__(self, "mesh_ids", tuple(self.mesh_ids))
        ids = set(self.role_ids.values()) | set(self.dependency_ids)
        if not self.character_id or not self.profile_id or not self.role_ids:
            raise MotionInputError("RIG_MAPPING_AMBIGUOUS", "explicit character and role mapping required")
        if not self.writable_ids <= ids or self.writable_ids & self.derived_ids:
            raise MotionInputError("INVALID_WRITE_SCOPE", "writable and derived scopes must be disjoint declared ids")
        if len(set(self.role_ids.values())) != len(self.role_ids):
            raise MotionInputError("RIG_MAPPING_AMBIGUOUS", "roles must resolve to unique objects")
        if any(not np.isfinite(v) or v <= 0 for v in self.bone_lengths_m.values()):
            raise MotionInputError("INVALID_POLICY", "bone lengths must be finite and positive")
        for start in self.parent_ids:
            seen, current = set(), start
            while current is not None:
                if current in seen:
                    raise MotionInputError("RIG_MAPPING_AMBIGUOUS", "cyclic parent mapping")
                seen.add(current)
                current = self.parent_ids.get(current)


@dataclass(frozen=True)
class SampleBatch:
    context: MotionContext
    object_ids: tuple[str, ...]
    space: str
    position_m: dict[str, np.ndarray]
    rotation_wxyz: dict[str, np.ndarray]
    channel_valid: dict[str, np.ndarray]
    source_binding: Any

    def __post_init__(self):
        object.__setattr__(self, "object_ids", tuple(self.object_ids))
        for name in ("position_m", "rotation_wxyz", "channel_valid"):
            copied = {}
            for key, value in getattr(self, name).items():
                array = np.array(value, copy=True)
                array.flags.writeable = False
                copied[str(key)] = array
            object.__setattr__(self, name, copied)

    def as_dict(self):
        binding = self.source_binding
        if hasattr(binding, "model_dump"):
            binding = binding.model_dump(mode="json")
        return {"context": self.context.as_dict(), "object_ids": list(self.object_ids), "space": self.space,
                "position_m": {k: v.tolist() for k, v in self.position_m.items()},
                "rotation_wxyz": {k: v.tolist() for k, v in self.rotation_wxyz.items()},
                "channel_valid": {k: v.tolist() for k, v in self.channel_valid.items()}, "source_binding": binding}

    @classmethod
    def from_dict(cls, value):
        value = dict(value)
        value["context"] = MotionContext.from_dict(value["context"])
        return cls(**value)


def resolve_rig_profile(objects, requested_ids, profile):
    from dataclasses import replace
    profile=RigProfile(**profile) if isinstance(profile,dict) else profile
    if not isinstance(profile,RigProfile):
        raise MotionInputError("RIG_MAPPING_AMBIGUOUS","explicit stable-id profile required")
    by_id={str(row["id"]):row for row in objects}
    if len(by_id)!=len(objects):
        raise MotionInputError("RIG_MAPPING_AMBIGUOUS","duplicate scene object ids")
    required=set(profile.role_ids.values())|profile.dependency_ids|profile.derived_ids
    if not required<=set(by_id):
        raise MotionInputError("RIG_MAPPING_AMBIGUOUS","profile contains missing scene objects")
    for key in required:
        owner=by_id[key].get("character_id")
        if owner is not None and owner!=profile.character_id:
            raise MotionInputError("INVALID_WRITE_SCOPE","profile crosses observed character ownership")
        if "parent_id" in by_id[key] and key in profile.parent_ids and by_id[key]["parent_id"]!=profile.parent_ids[key]:
            raise MotionInputError("RIG_ADAPTER_UNVERIFIED","declared parent differs from observed parent")
    writable=profile.writable_ids if requested_ids is None else frozenset(requested_ids)
    if not writable<=profile.writable_ids:
        raise MotionInputError("INVALID_WRITE_SCOPE","explicit object subset cannot enlarge writable profile")
    return replace(profile,writable_ids=writable)


def validate_samples(batch: SampleBatch, required_channels: dict[str, tuple[str, ...]]) -> None:
    if batch.space not in ("local", "global") or len(batch.object_ids) != len(set(batch.object_ids)):
        raise MotionInputError("INCOMPLETE_CAPTURE", "invalid space or duplicate ids")
    n = len(batch.context.frames)
    for object_id, channels in required_channels.items():
        if object_id not in batch.object_ids:
            raise MotionInputError("INCOMPLETE_CAPTURE", "missing requested object")
        validity = np.asarray(batch.channel_valid.get(object_id))
        if validity.shape != (n, 2):
            raise MotionInputError("INCOMPLETE_CAPTURE", "missing channel validity")
        for channel in channels:
            if channel not in ("position", "rotation"):
                raise MotionInputError("INVALID_POLICY", "unknown channel")
            rotations = channel == "rotation"
            values = (batch.rotation_wxyz if rotations else batch.position_m).get(object_id)
            values = np.asarray(values)
            if (values.shape != (n, 4 if rotations else 3) or not np.isfinite(values).all()
                    or not validity[:, int(rotations)].all()):
                raise MotionInputError("INCOMPLETE_CAPTURE", f"missing/nonfinite {channel}: {object_id}")
            if rotations:
                from .motion_math import normalise_quaternions
                normalise_quaternions(values)


@dataclass
class SolverResult:
    status: Literal["no_change", "candidate", "failed", "unsupported", "cancelled"]
    reason_codes: list[str] = field(default_factory=list)
    values: dict = field(default_factory=dict)
    report: dict = field(default_factory=dict)

    def as_dict(self):
        from .capture import canonical_data
        return canonical_data({"status": self.status, "reason_codes": self.reason_codes, "values": self.values, "report": self.report})


@dataclass(frozen=True)
class SupportTrack:
    support_id: str
    origin_m: np.ndarray
    rotation_wxyz: np.ndarray
    geometry: Any
    deforming_vertices_m: Any = None

    def __post_init__(self):
        from .motion_math import normalise_quaternions
        origins=np.asarray(self.origin_m,dtype=float)
        q=normalise_quaternions(self.rotation_wxyz)
        if not self.support_id or origins.shape!=(len(q),3) or not np.isfinite(origins).all():
            raise MotionInputError("INCOMPLETE_CAPTURE","support transform coverage must be finite and exact")
        origins,q=origins.copy(),q.copy()
        origins.flags.writeable=q.flags.writeable=False
        object.__setattr__(self,"origin_m",origins)
        object.__setattr__(self,"rotation_wxyz",q)

    def anchors_world(self, local_m):
        from .motion_math import normalise_quaternions
        from scipy.spatial.transform import Rotation
        q = normalise_quaternions(self.rotation_wxyz)
        origins = np.asarray(self.origin_m, dtype=float)
        if origins.shape != (len(q), 3) or not np.isfinite(origins).all():
            raise MotionInputError("INCOMPLETE_CAPTURE", "invalid support transform coverage")
        return origins + Rotation.from_quat(q[:, [1, 2, 3, 0]]).apply(local_m)

    def contact_reference(self, contact, point_local):
        """Return per-frame local anchor, normal and signed gap for approved geometry."""
        point=np.asarray(point_local,dtype=float)
        n=len(self.origin_m)
        if point.shape!=(n,3) or not np.isfinite(point).all() or not isinstance(self.geometry,dict):
            raise MotionInputError("INCOMPLETE_CAPTURE","invalid support-local contact coverage")
        geometry=self.geometry
        if geometry.get("kind")=="plane":
            normal=np.asarray(geometry.get("normal_local"),dtype=float)
            if normal.shape!=(3,) or not np.isfinite(normal).all() or np.linalg.norm(normal)<1e-12:
                raise MotionInputError("INVALID_POLICY","invalid support plane normal")
            normal=normal/np.linalg.norm(normal)
            normal=np.tile(normal,(n,1))
            at=np.where((contact.first_frame<=np.asarray(geometry.get("frames",np.arange(n)))) &
                        (np.asarray(geometry.get("frames",np.arange(n)))<=contact.last_frame))[0]
            first=int(at[0]) if len(at) else 0
            anchor=np.asarray(contact.anchor_local_m) if contact.anchor_local_m is not None else point[first]
            anchor=anchor.copy()
            height=float(anchor@normal[0]-float(geometry.get("offset_m",0)))
            if contact.anchor_local_m is not None and abs(height)>1e-8:
                raise MotionInputError("INVALID_POLICY","declared contact anchor is outside its support plane")
            anchor-=height*normal[0]
            anchors=np.tile(anchor,(n,1))
            gap=np.einsum("ij,ij->i",point,normal)-float(geometry.get("offset_m",0))
            return anchors,normal,gap
        if geometry.get("kind")!="mesh" or contact.triangle_id is None or contact.barycentric is None:
            raise MotionInputError("SUPPORT_GEOMETRY_UNSUPPORTED","mesh contacts require an approved triangle+barycentric anchor")
        vertices=np.asarray(self.deforming_vertices_m if self.deforming_vertices_m is not None else geometry.get("vertices_local_m"),dtype=float)
        triangles=np.asarray(geometry.get("triangles"))
        if vertices.ndim==2:
            vertices=np.broadcast_to(vertices,(n,*vertices.shape))
        if (vertices.ndim!=3 or vertices.shape[0]!=n or vertices.shape[2]!=3 or not np.isfinite(vertices).all()
                or triangles.ndim!=2 or triangles.shape[1]!=3 or triangles.dtype.kind not in "iu"
                or np.any(triangles<0) or np.any(triangles>=vertices.shape[1]) or not 0<=contact.triangle_id<len(triangles)):
            raise MotionInputError("INVALID_MESH","invalid evaluated support mesh coverage/topology")
        face=vertices[:,triangles[contact.triangle_id],:]
        anchors=np.einsum("j,ijk->ik",np.asarray(contact.barycentric),face)
        normal=np.cross(face[:,1]-face[:,0],face[:,2]-face[:,0])
        lengths=np.linalg.norm(normal,axis=1)
        if np.any(lengths<1e-12):
            raise MotionInputError("SUPPORT_GEOMETRY_UNSUPPORTED","degenerate support triangle")
        normal/=lengths[:,None]
        # A local patch's orientation must have an explicit observation.
        if not geometry.get("orientation_observed",False):
            raise MotionInputError("COLLISION_SIGN_UNVERIFIED","mesh support normal orientation is unobserved")
        gap=np.einsum("ij,ij->i",point-anchors,normal)
        return anchors,normal,gap
