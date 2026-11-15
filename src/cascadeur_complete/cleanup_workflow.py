"""Read a character's motion from the live scene and prepare whole-clip cleanup writes.

The math lives in ``motion_cleanup``; this module samples every frame through
the bridge (pinned to one scene so a tab switch fails the read instead of
mixing scenes), keeps writes on each object's existing keys, and hands the
result to the protected ``position_keys`` / ``rotation_keys`` changes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np

from . import motion_cleanup as mc
from .capture import canonical_data, canonical_digest, partition_writes, sample_projection, validate_write_scope
from .motion_context import IntentConstraints, MotionContext, MotionInputError, RigProfile, SampleBatch, validate_samples
from .motion_quality import QualityPolicy, compare_captures, evaluate_metrics
from .models import Operation

if TYPE_CHECKING:
    from .service import CascadeurService

READ_CHUNK = 25
# An index-middle gap this wide for most of the clip reads as a claw.
FAN_FLAG_DEG = 10.0
# Hand controllers: the wrist point, then the two that orient the hand around it.
HAND_POINTS = ("Hand_MainPoint", "Hand_DirectionPoint", "Hand_AdditionalPoint")
# Arm controllers moved by the arm clearance solve (elbow group, then wrist group).
ARM_POINTS = (
    "ForeArm_MainPoint",
    "ForeArm_AdditionalPoint",
    "Hand_MainPoint",
    "Hand_DirectionPoint",
    "Hand_AdditionalPoint",
)


class CleanupError(RuntimeError):
    pass


class CleanupWorkflow:
    def __init__(self, service: CascadeurService, rig: mc.FootRig | None = None, *,
                 profile=None, context=None, intent=None, source_binding=None, supports=None):
        self.service = service
        self.rig = rig or mc.FootRig()
        self.scene_id: str | None = None
        self.profile = RigProfile(**profile) if isinstance(profile, dict) else profile
        self.context = MotionContext.from_dict(context) if isinstance(context, dict) else context
        self.intent = IntentConstraints.model_validate(intent) if isinstance(intent, dict) else intent
        self.source_binding = source_binding
        from .motion_context import SupportTrack
        self.supports = {key: SupportTrack(**value) if isinstance(value,dict) else value for key,value in (supports or {}).items()}
        self._captures = []
        self._capture_scopes = []
        self._mesh_artifacts = []
        if self.context is not None and any(len(support.origin_m)!=len(self.context.frames) for support in self.supports.values()):
            raise CleanupError("INCOMPLETE_CAPTURE: support traces must cover the exact motion time grid")

    def _require_contract(self, kind, object_ids=None):
        if self.profile is None:
            raise CleanupError("RIG_MAPPING_AMBIGUOUS: explicit stable-id RigProfile is required for preparation")
        if self.context is None:
            raise CleanupError("MISSING_CLIP_METADATA: explicit FPS, length scale, basis and provenance required")
        if self.intent is None:
            raise CleanupError("MISSING_MOTION_INTENT: an explicit repair/styling intent is required")
        if (set(self.intent.locked_roles_frames)|set(self.intent.key_pose_locks))-set(self.profile.role_ids):
            raise CleanupError("RIG_MAPPING_AMBIGUOUS: intent locks reference an undeclared role")
        if object_ids and not set(object_ids) <= set(self.profile.role_ids.values()) | set(self.profile.dependency_ids):
            raise CleanupError("INVALID_WRITE_SCOPE: requested objects are outside the character profile")
        styling = kind in ("finger_fan", "wrist_soften", "hand_pose", "hand_rest", "wrist_accent", "synthesize_steps")
        if styling and self.intent.action != "styling":
            raise CleanupError("INTENT_LOCK_VIOLATION: this pass changes style and needs a declared styling intent")

    def _bind_source(self, kind, arguments=None):
        if not self._captures:
            raise CleanupError("INCOMPLETE_CAPTURE: no complete sampled source")
        from dataclasses import asdict
        scope = {"operation_name": kind, "captures": self._capture_scopes,
                 "requested_ids": sorted(set().union(*(set(c["ids"]) for c in self._capture_scopes))),
                 "profile": asdict(self.profile), "mesh_artifacts": self._mesh_artifacts,
                 "context": self.context.as_dict(),
                 "support_tracks": {key:asdict(value) for key,value in self.supports.items()}}
        if arguments is not None:
            scope["operation_arguments_digest"] = canonical_digest(arguments)
        # Frozen sets are normalized explicitly rather than relying on repr ordering.
        scope["profile"] = {key: sorted(value) if isinstance(value, (set, frozenset)) else value
                            for key, value in scope["profile"].items()}
        scope=canonical_data(scope)
        prior_scope=(self.source_binding.get("scope",{}) if isinstance(self.source_binding,dict)
                     else getattr(self.source_binding,"scope",{}))
        if prior_scope.get("snapshot_manifest") is not None:
            validator=getattr(self.service,"validate_source",None)
            if not callable(validator):
                raise CleanupError("BINDING_UNAVAILABLE: prior checkpoint source cannot be authenticated")
            prior_validation=validator(self.source_binding)
            if not getattr(prior_validation,"ok",False):
                raise CleanupError(f"{getattr(prior_validation,'error_code','STALE_SCENE')}: prior checkpoint binding no longer matches the working scene")
            # Preserve only authenticated checkpoint identity. The runtime's
            # next capture must independently attest it in the new exact scope.
            scope["snapshot_manifest"]=canonical_data(prior_scope["snapshot_manifest"])
        inputs = {"context": self.context.as_dict(), "profile": scope["profile"],
                  "intent": self.intent.model_dump(mode="json"),"support_tracks":scope["support_tracks"]}
        scope["planning_parameters"]=getattr(self,"_planning_parameters",{})
        if getattr(self,"_key_layout_digest",None):
            scope["key_layout_digest"]=self._key_layout_digest
        bound_scope = (self.source_binding.get("scope", {}) if isinstance(self.source_binding, dict)
                       else getattr(self.source_binding, "scope", {}))
        if self.source_binding is None or bound_scope != scope:
            capture_source = getattr(self.service, "capture_source", None)
            if not callable(capture_source):
                raise CleanupError("BINDING_UNAVAILABLE: installed bridge cannot certify source capture")
            self.source_binding = capture_source(scope, canonical_digest(inputs), canonical_digest({"captures": self._captures}))
        binding = self.source_binding
        complete = binding.get("complete", False) if isinstance(binding, dict) else getattr(binding, "complete", False)
        if not complete:
            raise CleanupError("BINDING_UNAVAILABLE: runtime could not verify the complete dependency closure")
        validate = getattr(self.service, "validate_source", None)
        if not callable(validate):
            raise CleanupError("BINDING_UNAVAILABLE: source attestation validator is not installed")
        result = validate(binding, operation_name=kind, arguments=arguments)
        if not getattr(result, "ok", False):
            raise CleanupError(f"{getattr(result, 'error_code', 'BINDING_UNAVAILABLE')}: {getattr(result, 'error_message', 'source validation failed')}")
        return binding

    def _prepare_bound(self, feature_id, operation_name, arguments, ttl):
        self._require_contract(operation_name)
        writes = arguments.get("writes", [])
        validate_write_scope(writes, self.profile, self.intent)
        chunks = partition_writes(writes)
        if len(chunks) != 1:
            raise CleanupError("RESOURCE_BUDGET_EXCEEDED: this candidate needs guarded recipe chunk continuation")
        source_binding = self._bind_source(operation_name, arguments)
        result = self.service.prepare_change(feature_id, operation_name, arguments, ttl,
                                             source_binding=source_binding)
        result.setdefault("quality", "unverified")
        result.setdefault("execution", "not_dispatched")
        return result

    # -- bridge reads -----------------------------------------------------

    def _read(self, feature_id: str, operations: list[Operation], timeout: float = 120.0) -> Any:
        # Not pinned through the request's scene_id: a pinned request for an
        # inactive tab makes the host activate tabs. Every read is compared
        # against the first one instead. service.batch applies the build pin,
        # the feature gate and the read-only check that a bare bridge call skipped.
        result = self.service.batch(
            feature_id,
            [operation.model_dump(mode="json") for operation in operations],
            scene_id=None,
            expected_revision=None,
            timeout=timeout,
        )
        if not result.ok:
            raise CleanupError(f"{operations[0].name} failed: {result.error_code}: {result.error_message}")
        if self.scene_id is None:
            self.scene_id = result.scene_id
        elif result.scene_id != self.scene_id:
            raise CleanupError("The active scene tab changed while the motion was being read; nothing was prepared")
        return result.result

    def frame_count(self) -> int:
        timeline = self._read("timeline_get", [Operation(name="timeline.get")])
        return int(timeline["frames_count"])

    def objects(self, object_ids: list[str] | None = None) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        offset = 0
        while True:
            page = self._read(
                "object_search", [Operation(name="scene.objects", arguments={"offset": offset, "limit": 400})]
            )
            batch = page["items"] if isinstance(page, dict) else page
            items += batch
            if len(batch) < 400:
                break
            offset += 400
        if object_ids:
            wanted = {str(item) for item in object_ids}
            items = [item for item in items if item["id"] in wanted]
        return items

    def by_name(self, objects: list[dict[str, Any]], names: list[str]) -> dict[str, str]:
        found: dict[str, list[str]] = {}
        for item in objects:
            if item["name"] in names:
                found.setdefault(item["name"], []).append(item["id"])
        missing = sorted(set(names) - set(found))
        if missing:
            raise CleanupError("Rig points not found: " + ", ".join(missing))
        ambiguous = sorted(name for name, ids in found.items() if len(ids) > 1)
        if ambiguous:
            raise CleanupError(
                "Several characters share these names; pass object_ids for one character: " + ", ".join(ambiguous)
            )
        return {name: ids[0] for name, ids in found.items()}

    def key_frames(self, ids: list[str]) -> dict[str, list[int]]:
        details = self._read("object_properties", [Operation(name="object.properties", arguments={"ids": ids})])
        layers = self._read("layer_list", [Operation(name="layer.list")])
        if any(isinstance(frame,bool) or not isinstance(frame,int) or frame<0 for layer in layers for frame in layer["keys"]):
            raise CleanupError("INCOMPLETE_CAPTURE: layer keys must be exact nonnegative integers")
        keys_by_layer = {layer["id"]: list(layer["keys"]) for layer in layers}
        if len(keys_by_layer)!=len(layers):
            raise CleanupError("INCOMPLETE_CAPTURE: duplicate animation layer ids")
        rows=details["items"]
        if len(rows)!=len(ids) or {str(row["id"]) for row in rows}!=set(ids):
            raise CleanupError("INCOMPLETE_CAPTURE: key-grid read omitted, duplicated or added an object")
        out = {}
        for row in rows:
            layer_id = row.get("layer_id")
            if layer_id is None or layer_id not in keys_by_layer:
                raise CleanupError(f"{row['id']} is not on an animation layer")
            out[row["id"]] = keys_by_layer[layer_id]
            if any(a>=b for a,b in zip(out[row["id"]],out[row["id"]][1:])):
                raise CleanupError("INCOMPLETE_CAPTURE: animation key grid is not unique and ordered")
        return out

    def sample(
        self, ids: list[str], frames: int, space: str = "global", only: list[int] | None = None
    ) -> dict[str, dict[str, np.ndarray]]:
        """Compact exact requested coverage. Pure reads never trigger interpolation refresh."""
        if isinstance(frames, bool) or not isinstance(frames, int) or frames <= 0:
            raise CleanupError("INVALID_POLICY: positive integer frame count required")
        if not ids or len(set(ids)) != len(ids) or space not in ("local", "global"):
            raise CleanupError("INCOMPLETE_CAPTURE: unique ids and explicit local/global space required")
        wanted = list(range(frames)) if only is None else list(only)
        if (not wanted or any(isinstance(f, bool) or not isinstance(f, (int, np.integer)) for f in wanted)
                or any(f < 0 or f >= frames for f in wanted) or np.any(np.diff(wanted) <= 0)):
            raise CleanupError("INVALID_POLICY: requested frames must be ordered, unique and within the clip")
        positions = {object_id: np.full((len(wanted), 3), np.nan) for object_id in ids}
        quaternions = {object_id: np.full((len(wanted), 4), np.nan) for object_id in ids}
        for start in range(0, len(wanted), READ_CHUNK):
            chunk = wanted[start : start + READ_CHUNK]
            operations = [
                Operation(
                    name="animation.transform_get",
                    arguments={
                        "ids": ids,
                        "frame": frame,
                        "space": space,
                        "refresh": False,
                    },
                )
                for frame in chunk
            ]
            rows = self._read("transform_get", operations, timeout=240)
            rows = rows if len(operations) > 1 else [{"result": rows}]
            for offset, (frame, row) in enumerate(zip(chunk, rows, strict=True), start=start):
                received = [str(item.get("id")) for item in row["result"]]
                if len(received) != len(ids) or set(received) != set(ids):
                    raise CleanupError("INCOMPLETE_CAPTURE: missing, duplicate or unexpected id in transform response")
                for item in row["result"]:
                    position = np.asarray(item.get("position"), dtype=float)
                    if position.shape != (3,) or not np.isfinite(position).all():
                        raise CleanupError("INCOMPLETE_CAPTURE: missing or nonfinite transform position")
                    if "frame" in item and item["frame"] != frame:
                        raise CleanupError("INCOMPLETE_CAPTURE: mismatched response frame")
                    positions[item["id"]][offset] = position
                    # Points carry a position only; rotation is null for them.
                    if item.get("rotation"):
                        quaternion = np.asarray(item["rotation"].get("quaternion_wxyz"), dtype=float)
                        from .motion_math import normalise_quaternions
                        normalise_quaternions(quaternion.reshape(1, 4))
                        # The binding hashes exact bridge observations. Unit
                        # normalization belongs to host math, after projection.
                        quaternions[item["id"]][offset] = quaternion
        projection = sample_projection(space, wanted, ids, positions, quaternions)
        self._captures.append(projection)
        self._capture_scopes.append({"space": space, "frames": list(map(int, wanted)), "ids": sorted(ids),
                                     "channels": {item: ["position"] + (["rotation"] if np.isfinite(quaternions[item]).all() else [])
                                                  for item in sorted(ids)}})
        return {"position": positions, "quaternion": quaternions, "frames": np.asarray(wanted, dtype=np.int64)}

    def capture_batch(self, ids, frames=None, space="global", required_rotation_ids=()):
        self._require_contract("capture", ids)
        grid = self.context.frames if frames is None else np.asarray(frames)
        if not np.array_equal(grid, self.context.frames):
            raise CleanupError("INCOMPLETE_CAPTURE: capture must cover the exact context time grid")
        ids=list(ids)
        required_rotation_ids=list(required_rotation_ids)
        if (not ids or len(set(ids))!=len(ids) or not set(required_rotation_ids)<=set(ids)
                or space not in ("local","global")):
            raise CleanupError("INVALID_POLICY: exact unique capture IDs, rotation subset and space required")
        observer=getattr(self.service,"observe_motion_capture",None)
        if callable(observer):
            if self.source_binding is None:
                raise CleanupError("BINDING_UNAVAILABLE: native evaluated capture requires an issued source binding")
            source=(self.source_binding.model_dump(mode="json") if hasattr(self.source_binding,"model_dump")
                    else canonical_data(self.source_binding))
            receipt=observer({"ids":ids,"space":space,"context":self.context.as_dict(),
                              "required_rotation_ids":required_rotation_ids,"source_binding":source})
            if not getattr(receipt,"ok",False):
                raise CleanupError("CAPTURE_UNVERIFIED: "+str(getattr(receipt,"error_message","native capture failed")))
            issued=receipt.result
            if not isinstance(issued,dict) or not isinstance(issued.get("canonical_batch"),dict):
                raise CleanupError("CAPTURE_UNVERIFIED: canonical native batch was not returned")
            value=issued["canonical_batch"]
            expected_fields={"context","object_ids","space","position_m","rotation_wxyz","channel_valid","source_binding"}
            if (set(value)!=expected_fields or value["context"]!=self.context.as_dict() or value["object_ids"]!=ids
                    or value["space"]!=space or value["source_binding"]!=source
                    or issued.get("capture_digest")!=canonical_digest(value)):
                raise CleanupError("CAPTURE_SCOPE_MISMATCH: issued canonical batch differs from exact requested scope")
            batch=SampleBatch.from_dict(value)
            required={key:("position","rotation") if key in required_rotation_ids else ("position",) for key in ids}
            validate_samples(batch,required)
            if (set(batch.position_m)!=set(ids) or set(batch.channel_valid)!=set(ids)
                    or not set(batch.rotation_wxyz)<=set(ids)):
                raise CleanupError("INCOMPLETE_CAPTURE: canonical channel map escapes exact capture IDs")
            verifier=getattr(self.service,"recipe_verify_capture",None)
            if not callable(verifier):
                raise CleanupError("CAPTURE_UNVERIFIED: runtime-issued capture authenticator unavailable")
            verified=verifier(batch,issued["capture_digest"])
            if (not getattr(verified,"ok",False) or not isinstance(verified.result,dict)
                    or verified.result.get("capture_digest")!=issued["capture_digest"]):
                raise CleanupError("CAPTURE_UNVERIFIED: current native capture provenance could not be authenticated")
            if not issued.get("evaluation_receipt_digest"):
                raise CleanupError("EVALUATION_RECEIPT_UNAVAILABLE: native capture has no durable evaluation receipt")
            observed_scene=issued.get("scene_instance_id")
            if not observed_scene or (self.scene_id is not None and self.scene_id!=observed_scene):
                raise CleanupError("SCENE_CHANGED: native capture scene instance differs")
            self.scene_id=observed_scene
            raw=issued.get("sample_projection")
            if (not isinstance(raw,dict) or raw.get("space")!=space or raw.get("frames")!=grid.tolist()
                    or [(row.get("frame"),row.get("id")) for row in raw.get("samples",[])]
                       !=[(int(frame),key) for frame in grid for key in sorted(ids)]):
                raise CleanupError("INCOMPLETE_CAPTURE: native raw projection coverage differs")
            self._captures.append(canonical_data(raw))
            self._capture_scopes.append({"space":space,"frames":grid.tolist(),"ids":sorted(ids),
                "channels":{key:["position"]+(["rotation"] if key in batch.rotation_wxyz else []) for key in sorted(ids)}})
            return batch
        # Legacy read-only clients without the private native observation hook
        # can still analyze samples; this path issues no evaluated-capture proof.
        from scipy.spatial.transform import Rotation
        raw = self.sample(list(ids), self.frame_count(), space=space, only=grid.tolist())
        positions = {key: self.context.positions_to_solver(value) for key, value in raw["position"].items()}
        rotations, valid = {}, {}
        for key in ids:
            q = raw["quaternion"][key]
            has_rotation = bool(np.isfinite(q).all())
            valid[key] = np.column_stack((np.ones(len(grid), dtype=bool), np.full(len(grid), has_rotation)))
            if has_rotation:
                matrices = Rotation.from_quat(q[:, [1, 2, 3, 0]]).as_matrix()
                rotations[key] = Rotation.from_matrix(self.context.rotations_to_solver(matrices)).as_quat()[:, [3, 0, 1, 2]]
        batch = SampleBatch(self.context, tuple(ids), space, positions, rotations, valid, self.source_binding)
        required = {key: ("position", "rotation") if key in required_rotation_ids else ("position",) for key in ids}
        validate_samples(batch, required)
        return batch

    def _observed_key_model(self,batch,goal,parameters):
        from dataclasses import replace
        from .motion_solvers import build_key_model
        descriptor=parameters.pop("key_layout",None)
        # Legacy declarations may describe a math experiment, but cannot
        # certify native interpolation or enable a production write.
        parameters.pop("interpolation_capabilities",None)
        if descriptor is None:
            reader=getattr(self.service,"observe_key_layout",None)
            if not callable(reader):
                raise MotionInputError("INTERPOLATION_MODEL_UNVERIFIED","native key-layout reader unavailable")
            receipt=reader({"ids":sorted(goal),"space":batch.space,"channel":"position",
                            "frames":batch.context.frames.tolist(),"capture_digest":canonical_digest(batch.as_dict()),
                            "capture_object_ids":list(batch.object_ids),"context":batch.context.as_dict()})
            if not getattr(receipt,"ok",False):
                raise MotionInputError("INTERPOLATION_MODEL_UNVERIFIED","native key-layout observation failed")
            descriptor=receipt.result
        model=build_key_model(batch,replace(self.profile,writable_ids=frozenset(goal)),
            key_layout=descriptor,verifier=getattr(self.service,"verify_key_layout",None))
        self._key_layout_digest=model.descriptor_digest
        return model

    def plan_pass(self, kind, parameters=None):
        """Compute a whole-domain candidate, without preparing a token or changing a scene."""
        from scipy.spatial.transform import Rotation
        from .motion_solvers import solve_contacts_v2, repair_rotation_spikes, build_key_model, fit_keys, solve_arm_clearance_v2
        parameters = dict(parameters or {})
        self._require_contract(kind)
        allowed={
            "feet":{"steps","limits","interpolation_capabilities"},
            "foot_contacts":{"steps","limits","interpolation_capabilities"},
            "arm_clearance":{"surface_tracks","limits","interpolation_capabilities"},
            "hand_rest":{"limits","interpolation_capabilities"},
            "wrist_accent":{"side","pulses","pulses_s","attack_s","release_s","amplitude_deg","amplitude_rad","limits","interpolation_capabilities"},
            "fingers":{"joint_ids","spike_deg","spike_angle_rad","max_duration_s"},
            "finger_repair":{"joint_ids","spike_deg","spike_angle_rad","max_duration_s"},
            "finger_fan":{"joint_ids","target_deg","target_angle_rad","sigma_s"},
            "hand_pose":{"joint_ids","pose_angles_rad","sigma_s"},
            "wrist_soften":{"joint_ids","sigma_s"},
        }
        unknown=set(parameters)-allowed.get(kind,set())-{"object_ids","ttl"}
        unknown.discard("key_layout")
        if unknown:
            raise CleanupError("INVALID_POLICY: unsupported parameters: "+", ".join(sorted(unknown)))
        limit_names={"position_correction_m","rotation_correction_rad","contact_gap_m","contact_drift_m","iterations",
                     "collision_clearance_m","collision_residual_m","arm_radius_m","velocity_weight","acceleration_weight","fit_error_m","max_nonzeros",
                     "max_variables","max_memory_bytes","factorization_workspace_bytes","fit_iterations"}
        limits=parameters.get("limits",{})
        if not isinstance(limits,dict) or set(limits)-limit_names:
            raise CleanupError("INVALID_POLICY: unsupported solver limit names")
        if any(isinstance(value,bool) or not isinstance(value,(int,float)) or not np.isfinite(value) or value<0 for value in limits.values()):
            raise CleanupError("INVALID_POLICY: solver limits must be finite nonnegative numbers")
        self._planning_parameters=canonical_data(parameters)
        self._key_layout_digest=None
        fit_limits={**limits,"position_correction_m":min(limits.get("position_correction_m",float("inf")),
                                                       self.intent.correction_envelope.get("position_m",0.))}
        requested = parameters.pop("object_ids", None)
        requested_writes = set(self.profile.writable_ids) if requested is None else set(requested)
        self._require_contract(kind, requested_writes)
        if not requested_writes <= self.profile.writable_ids:
            raise CleanupError("INVALID_WRITE_SCOPE: requested writes must be declared drivers")
        ids = sorted(set(self.profile.role_ids.values()) | self.profile.dependency_ids)
        ttl = parameters.pop("ttl", 900.0)
        del ttl  # Planning never creates a prepared mutation.
        if kind in ("feet", "foot_contacts"):
            if parameters.pop("steps", False):
                raise CleanupError("INTENT_LOCK_VIOLATION: step synthesis is a separate styling operation")
            batch = self.capture_batch(ids)
            solved = solve_contacts_v2(batch, self.profile, self.supports, self.intent.contacts,
                                       self.intent, parameters.pop("limits", {}))
            if solved.status != "candidate":
                return solved.as_dict()
            goal = solved.values.get("position_m", solved.values)
            model = self._observed_key_model(batch,goal,parameters)
            locks = {self.profile.role_ids[role]: {frame:value for frame,value in values.items() if len(value)==3} for role, values in self.intent.key_pose_locks.items()
                     if role in self.profile.role_ids}
            fitted = fit_keys(goal, batch, model, locks, fit_limits)
            if fitted.status != "candidate":
                return fitted.as_dict()
            writes = []
            for key, value in fitted.values.items():
                for frame, position in zip(value["frames"], self.context.positions_to_scene(value["position_m"]), strict=True):
                    if np.linalg.norm(position - self.context.positions_to_scene(batch.position_m[key])[np.where(self.context.frames == frame)[0][0]]) > 1e-9:
                        writes.append({"id": key, "frame": int(frame), "position": position.tolist()})
            feature, operation, space = "position_keys", "animation.position_keys_set", "global"
            report = {**solved.report, **fitted.report}
        elif kind in ("arm_clearance", "hand_rest", "wrist_accent"):
            from .motion_styling import hand_rest_targets, wrist_accent_targets
            required_rotations = [self.profile.role_ids[role] for role in self.profile.role_ids if role.endswith("hand_frame")] if kind=="wrist_accent" else []
            batch = self.capture_batch(ids, required_rotation_ids=required_rotations)
            if kind=="arm_clearance":
                surfaces=self._surface_tracks(parameters.pop("surface_tracks", {}))
                solved=solve_arm_clearance_v2(batch,self.profile,surfaces,self.intent,parameters.pop("limits",{}))
            elif kind=="hand_rest":
                solved=hand_rest_targets(batch,self.profile,self.supports,self.intent,parameters)
            else:
                solved=wrist_accent_targets(batch,self.profile,self.intent,parameters)
            if solved.status!="candidate":
                return solved.as_dict()
            model=self._observed_key_model(batch,solved.values["position_m"],parameters)
            locks={self.profile.role_ids[role]:{frame:value for frame,value in values.items() if len(value)==3} for role,values in self.intent.key_pose_locks.items() if role in self.profile.role_ids}
            fitted=fit_keys(solved.values["position_m"],batch,model,locks,fit_limits)
            if fitted.status!="candidate":
                return fitted.as_dict()
            writes=[]
            for key,value in fitted.values.items():
                for frame,position in zip(value["frames"],self.context.positions_to_scene(value["position_m"]),strict=True):
                    row=np.where(self.context.frames==frame)[0]
                    if not len(row):
                        raise CleanupError("KEY_LAYOUT_INSUFFICIENT: key falls outside the complete capture")
                    if np.linalg.norm(self.context.positions_to_solver(position)-batch.position_m[key][row[0]])>1e-9:
                        writes.append({"id":key,"frame":int(frame),"position":position.tolist()})
            feature,operation,space="position_keys","animation.position_keys_set","global"
            report={**solved.report,**fitted.report}
        elif kind in ("wrist_soften", "finger_fan", "hand_pose"):
            from .motion_styling import style_rotation_targets
            selected=parameters.get("joint_ids") or [key for role,key in self.profile.role_ids.items()
                if ("finger" in role.lower() if kind in ("hand_pose","finger_fan") else role.lower().endswith("wrist"))]
            selected=[key for key in selected if key in requested_writes]
            parameters["joint_ids"]=selected
            batch=self.capture_batch(selected,space="local",required_rotation_ids=selected)
            solved=style_rotation_targets(batch,self.profile,self.intent,kind,parameters)
            if solved.status!="candidate":
                return solved.as_dict()
            keys=self.key_frames(selected); writes=[]
            for key,q in solved.values["rotation_wxyz"].items():
                source=Rotation.from_quat(batch.rotation_wxyz[key][:,[1,2,3,0]])
                target=Rotation.from_quat(q[:,[1,2,3,0]])
                changed=np.where((source.inv()*target).magnitude()>1e-9)[0]
                c=self.context.scene_to_solver_basis
                euler=self._eulers_from_solver(q)
                for row in changed:
                    frame=int(self.context.frames[row])
                    if frame not in keys[key]:
                        return {"status":"failed","reason_codes":["KEY_LAYOUT_INSUFFICIENT"],"report":solved.report}
                    writes.append({"id":key,"frame":frame,"rotation_euler_xyz_radians":euler[row].tolist(),
                                   "expected_quaternion_wxyz":self._scene_quaternions(q)[row].tolist()})
            feature,operation,space="rotation_keys","animation.rotation_keys_set","local"
            report=solved.report
        elif kind in ("fingers", "finger_repair"):
            selected = parameters.pop("joint_ids", [key for role, key in self.profile.role_ids.items() if "finger" in role.lower()])
            selected = [key for key in selected if key in requested_writes]
            if not selected:
                return {"status": "unsupported", "reason_codes": ["RIG_MAPPING_AMBIGUOUS"], "report": {"detail": "no finger roles"}}
            batch = self.capture_batch(selected, space="local", required_rotation_ids=selected)
            key_grid = self.key_frames(selected)
            writes, report = [], {}
            inverse_roles = {key: role for role, key in self.profile.role_ids.items()}
            for key in selected:
                locked = set(self.intent.locked_roles_frames.get(inverse_roles[key], ()))
                locked.update(self.intent.key_pose_locks.get(inverse_roles[key],{}))
                editable = ((self.context.frames >= self.intent.editable_frames[0]) & (self.context.frames <= self.intent.editable_frames[1]))
                result = repair_rotation_spikes(batch.rotation_wxyz[key], self.context.time_s,
                    spike_angle_rad=float(parameters.get("spike_angle_rad", np.radians(parameters.get("spike_deg", 10.0)))),
                    max_duration_s=float(parameters.get("max_duration_s",.1)),
                    editable_mask=editable, locks=np.isin(self.context.frames, list(locked)))
                report[key] = {k: v for k, v in result.items() if k != "quaternion_wxyz"}
                q = result["quaternion_wxyz"]
                matrices = Rotation.from_quat(q[:, [1, 2, 3, 0]]).as_matrix()
                c = self.context.scene_to_solver_basis
                eulers = self._eulers_from_solver(q) if result["corrected_rows"] else None
                for row in result["corrected_rows"]:
                    frame = int(self.context.frames[row])
                    if frame not in key_grid[key]:
                        return {"status": "failed", "reason_codes": ["KEY_LAYOUT_INSUFFICIENT"], "report": report}
                    writes.append({"id": key, "frame": frame, "rotation_euler_xyz_radians": eulers[row].tolist(),
                                   "expected_quaternion_wxyz":self._scene_quaternions(q)[row].tolist()})
            feature, operation, space = "rotation_keys", "animation.rotation_keys_set", "local"
        else:
            return {"status": "unsupported", "reason_codes": ["VERIFIED_CONTROLLER_ADAPTER_UNAVAILABLE"],
                    "report": {"kind": kind, "detail": "this rig has no installed bounded controller adapter for the requested pass"}}
        if not writes:
            return {"status": "no_change", "reason_codes": [], "report": report}
        validate_write_scope(writes, self.profile, self.intent)
        if any(write["id"] not in requested_writes for write in writes):
            raise CleanupError("INVALID_WRITE_SCOPE: solve requires a driver outside the explicit request")
        self._validate_candidate_effect(writes,batch)
        chunks = partition_writes(writes)
        writes=[write for chunk in chunks for write in chunk["writes"]]
        arguments = {"writes": writes, "space": space}
        return {"status": "candidate", "feature_id": feature, "operation_name": operation,
                "arguments": arguments, "source_binding": self._bind_source(operation, arguments),
                "chunks": chunks, "report": report}

    def plan_retarget(self,source_artifact,mapping,settings):
        """Lower a canonical source artifact through observed target controllers.

        This is host computation followed by the same existing-key writer as
        cleanup. An import file is never dispatched as a native retarget op.
        """
        from .retargeting import retarget_pose,controller_targets
        from .motion_solvers import fit_keys
        self._require_contract("retarget")
        self._key_layout_digest=None
        if self.intent.action!="retarget" or self.intent.root_policy!="explicit_mapped_trajectory":
            raise MotionInputError("MISSING_MOTION_INTENT","retarget requires explicit mapped-root intent")
        fields={"schema_version","context","source_local","source_rest","source_root_position_m",
                "source_leg_length_m","provenance"}
        if (not isinstance(source_artifact,dict) or set(source_artifact)-fields
                or type(source_artifact.get("schema_version")) is not int or source_artifact.get("schema_version")!=1
                or not source_artifact.get("provenance")):
            raise MotionInputError("RETARGET_SOURCE_UNVERIFIED","canonical source artifact/provenance is incomplete")
        source_context=MotionContext.from_dict(source_artifact["context"])
        if (not np.array_equal(source_context.time_s,self.context.time_s)
                or not np.array_equal(source_context.frames,self.context.frames)):
            raise MotionInputError("INCOMPLETE_CAPTURE","retarget source must use the exact target physical sample schedule")
        allowed={"root_role","axis_alignment","root_basis","scale","target_leg_length_m","target_root_anchor_m",
                 "required_roles","end_effector_constraints","fit_limits","target_channels"}
        if set(settings)-allowed or not mapping or set(mapping)-set(self.profile.role_ids):
            raise MotionInputError("RIG_MAPPING_AMBIGUOUS","retarget settings or target semantic mapping are unknown")
        channels=tuple(settings.get("target_channels",("position",)))
        if channels not in (("position",),("rotation",)):
            raise MotionInputError("COUPLED_CHANNEL_WRITER_UNAVAILABLE","retarget must declare one target channel")
        fit_limits=settings.get("fit_limits",{})
        if (not isinstance(fit_limits,dict) or set(fit_limits)-{"position_correction_m","velocity_weight",
                "acceleration_weight","fit_error_m","max_variables","max_nonzeros","max_memory_bytes",
                "factorization_workspace_bytes","fit_iterations"}):
            raise MotionInputError("INVALID_POLICY","unknown retarget key fitting limits")
        n=len(self.context.frames)
        for role,value in source_artifact["source_local"].items():
            if np.asarray(value.get("position_m")).shape!=(n,3) or np.asarray(value.get("rotation_matrix")).shape!=(n,3,3):
                raise MotionInputError("INCOMPLETE_CAPTURE",f"source local time coverage missing: {role}")
        reader=getattr(self.service,"observe_retarget_inputs",None)
        verifier=getattr(self.service,"verify_retarget_inputs",None)
        if not callable(reader) or not callable(verifier):
            return {"status":"unsupported","reason_codes":["RETARGET_TARGET_OBSERVATION_UNAVAILABLE"]}
        receipt=reader({"profile_id":self.profile.profile_id,"role_ids":self.profile.role_ids,
                        "context":self.context.as_dict(),"source_artifact_digest":canonical_digest(source_artifact)})
        if not getattr(receipt,"ok",False) or not isinstance(receipt.result,dict):
            return {"status":"unsupported","reason_codes":["RETARGET_TARGET_OBSERVATION_UNAVAILABLE"]}
        observed=receipt.result;observed_digest=canonical_digest(observed)
        proof=verifier(observed,observed_digest)
        if not (getattr(proof,"ok",False) and isinstance(getattr(proof,"result",None),dict)
                and proof.result.get("retarget_inputs_digest")==observed_digest):
            return {"status":"unsupported","reason_codes":["RETARGET_TARGET_PROVENANCE_UNVERIFIED"]}
        for key in ("target_rest","target_parents","axis_alignment","root_basis","target_root_anchor_m"):
            if key not in observed:
                return {"status":"unsupported","reason_codes":["RETARGET_TARGET_OBSERVATION_INCOMPLETE"],"report":{"missing":key}}
        if ("target_leg_length_m" in settings
                and settings["target_leg_length_m"]!=observed.get("target_leg_length_m")):
            raise MotionInputError("RIG_ADAPTER_UNVERIFIED","declared target leg length differs from native observation")
        solved=retarget_pose(source_artifact["source_local"],source_artifact["source_rest"],observed["target_rest"],
            mapping,settings.get("axis_alignment",observed["axis_alignment"]),observed["target_parents"],
            root_role=settings["root_role"],source_root_position_m=source_artifact["source_root_position_m"],
            target_root_anchor_m=settings.get("target_root_anchor_m",observed["target_root_anchor_m"]),
            root_basis=settings.get("root_basis",observed["root_basis"]),scale=settings.get("scale"),
            source_leg_length_m=source_artifact.get("source_leg_length_m"),
            target_leg_length_m=observed.get("target_leg_length_m"),required_roles=settings.get("required_roles",()),
            end_effector_constraints=settings.get("end_effector_constraints",()))
        if solved.status!="candidate":return solved.as_dict()
        targets=controller_targets(solved,self.profile,getattr(self.service,"motion_controller_adapter",None),
            planned_world=solved.values["world"],adapter_verifier=getattr(self.service,"verify_controller_targets",None))
        if targets.status!="candidate":return targets.as_dict()
        if set(targets.values)-{"position_m","rotation_wxyz","space"}:
            raise MotionInputError("RIG_ADAPTER_UNVERIFIED","controller adapter returned an unsupported candidate schema")
        positions=targets.values.get("position_m",{});rotations=targets.values.get("rotation_wxyz",{})
        if bool(positions)==bool(rotations):
            return {"status":"unsupported","reason_codes":["COUPLED_CHANNEL_WRITER_UNAVAILABLE"]}
        if ("position" if positions else "rotation")!=channels[0]:
            return {"status":"unsupported","reason_codes":["RETARGET_CONTROLLER_CHANNEL_MISMATCH"]}
        space=targets.values.get("space","global")
        ids=sorted(set(self.profile.role_ids.values())|self.profile.dependency_ids)
        batch=self.capture_batch(ids,space=space,required_rotation_ids=tuple(rotations))
        writes=[]
        report={**solved.report,**targets.report,"target_observation_digest":observed_digest,
                "source_artifact_digest":canonical_digest(source_artifact)}
        self._planning_parameters={"retarget":canonical_data(settings),"mapping":dict(mapping),**report}
        if positions:
            model=self._observed_key_model(batch,positions,{})
            limits={**fit_limits,"position_correction_m":min(fit_limits.get("position_correction_m",float("inf")),
                                                            self.intent.correction_envelope.get("position_m",0.))}
            locks={self.profile.role_ids[role]:{frame:value for frame,value in values.items() if len(value)==3}
                   for role,values in self.intent.key_pose_locks.items()}
            fitted=fit_keys(positions,batch,model,locks,limits)
            if fitted.status!="candidate":return fitted.as_dict()
            report.update(fitted.report)
            for object_id,value in fitted.values.items():
                for frame,position in zip(value["frames"],value["position_m"],strict=True):
                    row=int(np.flatnonzero(self.context.frames==frame)[0])
                    if np.linalg.norm(position-batch.position_m[object_id][row])>1e-9:
                        writes.append({"id":object_id,"frame":frame,"position":self.context.positions_to_scene(position).tolist()})
            feature,operation="position_keys","animation.position_keys_set"
        else:
            from scipy.spatial.transform import Rotation
            keys=self.key_frames(rotations)
            for object_id,value in rotations.items():
                values=np.asarray(value,dtype=float)
                if values.shape!=(n,4) or not np.isfinite(values).all():
                    raise MotionInputError("INCOMPLETE_CAPTURE","controller rotation coverage is incomplete")
                before=Rotation.from_quat(batch.rotation_wxyz[object_id][:,[1,2,3,0]])
                after=Rotation.from_quat(values[:,[1,2,3,0]])
                changed=np.flatnonzero((before.inv()*after).magnitude()>1e-9)
                if any(int(self.context.frames[row]) not in keys[object_id] for row in changed):
                    return {"status":"unsupported","reason_codes":["KEY_LAYOUT_INSUFFICIENT"]}
                eulers=self._eulers_from_solver(values);expected=self._scene_quaternions(values)
                for row in changed:
                    writes.append({"id":object_id,"frame":int(self.context.frames[row]),
                        "rotation_euler_xyz_radians":eulers[row].tolist(),"expected_quaternion_wxyz":expected[row].tolist()})
            feature,operation="rotation_keys","animation.rotation_keys_set"
        if not writes:return {"status":"no_change","reason_codes":[],"report":report}
        validate_write_scope(writes,self.profile,self.intent)
        self._validate_candidate_effect(writes,batch)
        chunks=partition_writes(writes)
        arguments={"writes":[write for chunk in chunks for write in chunk["writes"]],"space":space}
        return {"status":"candidate","feature_id":feature,"operation_name":operation,"arguments":arguments,
                "source_binding":self._bind_source(operation,arguments),"chunks":chunks,"report":report}

    def _validate_candidate_effect(self,writes,batch):
        from scipy.spatial.transform import Rotation
        inverse={key:role for role,key in self.profile.role_ids.items()}
        rows={int(frame):row for row,frame in enumerate(self.context.frames)}
        for write in writes:
            key,frame=write["id"],write["frame"]
            role=inverse.get(key,key)
            if frame not in rows:
                raise CleanupError("INVALID_WRITE_SCOPE: candidate frame was not captured")
            row=rows[frame]
            if "position" in write:
                error=float(np.linalg.norm(self.context.positions_to_solver(write["position"])-batch.position_m[key][row]))
                cap=min(self.intent.correction_envelope.get("position_m",0.),
                        self.intent.correction_envelope.get(f"{role}.position_m",np.inf))
            else:
                q=write["expected_quaternion_wxyz"]
                matrix=self.context.rotations_to_solver(Rotation.from_quat(np.asarray(q)[[1,2,3,0]]).as_matrix())
                original=Rotation.from_quat(batch.rotation_wxyz[key][row,[1,2,3,0]])
                error=float((original.inv()*Rotation.from_matrix(matrix)).magnitude())
                cap=min(self.intent.correction_envelope.get("rotation_rad",0.),
                        self.intent.correction_envelope.get(f"{role}.rotation_rad",np.inf))
            if error>cap+1e-8:
                raise CleanupError(f"CORRECTION_ENVELOPE_EXCEEDED: {role} at frame {frame}: {error} > {cap}")
            expected=self.intent.key_pose_locks.get(role,{}).get(frame)
            if expected is not None:
                expected=np.asarray(expected,dtype=float)
                if "position" in write and expected.shape==(3,):
                    lock_error=np.linalg.norm(self.context.positions_to_solver(write["position"])-expected)
                elif "expected_quaternion_wxyz" in write and expected.shape==(4,):
                    lock_error=(Rotation.from_quat(expected[[1,2,3,0]]).inv()*Rotation.from_matrix(matrix)).magnitude()
                else:
                    lock_error=0.
                if lock_error>1e-8:
                    raise CleanupError("INTENT_LOCK_VIOLATION: candidate changes an explicit key pose lock")
            if role.lower() in ("root","pelvis.root","character.root") and self.intent.root_policy=="preserve" and error>1e-9:
                raise CleanupError("INTENT_LOCK_VIOLATION: repair candidate changes the original root trajectory")

    def _eulers_from_solver(self, quaternion_wxyz):
        from scipy.spatial.transform import Rotation
        adapter=getattr(self.service,"motion_rotation_adapter",None)
        q=np.asarray(quaternion_wxyz,dtype=float)
        c=self.context.scene_to_solver_basis
        scene=Rotation.from_matrix(c.T@Rotation.from_quat(q[:,[1,2,3,0]]).as_matrix()@c)
        scene_q=scene.as_quat()[:,[3,0,1,2]]
        if adapter is None or not getattr(adapter,"verified",False):
            # This is only an encoding candidate. Every native write preflights
            # its SDK converter against expected_quaternion_wxyz before mutation.
            return scene.as_euler("xyz")
        eulers=np.asarray(adapter.quaternion_to_euler_xyz(scene_q),dtype=float)
        if eulers.shape!=(len(q),3) or not np.isfinite(eulers).all():
            raise CleanupError("RIG_ADAPTER_UNVERIFIED: invalid native Euler conversion")
        back=np.asarray(adapter.euler_xyz_to_quaternion(eulers),dtype=float)
        if back.shape!=scene_q.shape or not np.isfinite(back).all():
            raise CleanupError("RIG_ADAPTER_UNVERIFIED: invalid native Euler roundtrip")
        error=(scene.inv()*Rotation.from_quat(back[:,[1,2,3,0]])).magnitude()
        if error.max(initial=0)>1e-6:
            raise CleanupError("RIG_ADAPTER_UNVERIFIED: native Euler roundtrip residual exceeds 1e-6 rad")
        return eulers

    def _scene_quaternions(self, quaternion_wxyz):
        from scipy.spatial.transform import Rotation
        q=np.asarray(quaternion_wxyz,dtype=float)
        c=self.context.scene_to_solver_basis
        return Rotation.from_matrix(c.T@Rotation.from_quat(q[:,[1,2,3,0]]).as_matrix()@c).as_quat()[:,[3,0,1,2]]

    def _surface_tracks(self, tracks):
        """Explicit immutable evaluated geometry, in canonical metres, never a guessed mesh API."""
        from .motion_geometry import TriangleSurface, WindowedSurfaceTrack
        result={}
        used_bytes=0
        for side,rows in tracks.items():
            if isinstance(rows,dict) and "windows" in rows:
                result[side]=WindowedSurfaceTrack(rows["windows"],self.context.frames,context=self.context,
                    semantics=rows.get("semantics","volume"),orientation_observed=bool(rows.get("orientation_observed",False)),
                    memory_budget_bytes=rows.get("memory_budget_bytes",256*1024*1024))
                self._mesh_artifacts.extend(rows["windows"])
                continue
            if len(rows)!=len(self.context.frames):
                raise CleanupError("INCOMPLETE_CAPTURE: surface tracks must cover the global time grid")
            result[side]=[]
            for row in rows:
                vertices=np.asarray(row["vertices_m"],dtype=float)
                triangles=np.asarray(row["triangles"])
                used_bytes+=vertices.nbytes+triangles.nbytes
                if used_bytes>256*1024*1024:
                    raise CleanupError("RESOURCE_BUDGET_EXCEEDED: use a verified streaming surface provider for this capture")
                result[side].append(TriangleSurface(vertices,triangles,semantics=row.get("semantics","volume"),
                    orientation_observed=bool(row.get("orientation_observed",False))))
        if tracks:
            self._mesh_artifacts.append({"kind":"evaluated_surface_track","digest":canonical_digest(tracks),"bytes":used_bytes})
        return result

    def _prepare_plan(self, kind, parameters, ttl):
        plan=self.plan_pass(kind,parameters)
        if plan["status"]!="candidate":
            return {"ok":plan["status"]=="no_change","execution":"not_dispatched","quality":"unverified",**plan}
        if len(plan["chunks"])!=1:
            raise CleanupError("RESOURCE_BUDGET_EXCEEDED: use guarded recipe continuation for the complete candidate")
        result=self.service.prepare_change(plan["feature_id"],plan["operation_name"],plan["arguments"],ttl,
                                           source_binding=plan["source_binding"])
        result["cleanup"]={"kind":kind,**plan["report"]}
        result["quality"]="unverified"
        return result

    # -- feet ---------------------------------------------------------------

    def _points(self, object_ids):
        objects = self.objects(object_ids)
        points = [item for item in objects if item["type"] == "Point"]
        if self.profile is not None:
            points = [item for item in points if item["id"] in self.profile.writable_ids | self.profile.dependency_ids]
        elif object_ids is None:
            # Name detection can select diagnostic roles, never every Point in a scene.
            required = set(self.rig.required())
            points = [item for item in points if item["name"] in required]
        self.by_name(points, self.rig.required())
        names = [item["name"] for item in points]
        duplicated = sorted({name for name in names if names.count(name) > 1})
        if duplicated:
            raise CleanupError(
                "Several characters share point names; pass object_ids for one character: " + ", ".join(duplicated[:5])
            )
        return {item["name"]: item["id"] for item in points}

    def _feet_track(self, object_ids):
        points = self._points(object_ids)
        frames = self.frame_count()
        sampled = self.sample(list(points.values()), frames)
        track = {name: sampled["position"][object_id] for name, object_id in points.items()}
        return points, frames, track

    def analyze_feet(self, object_ids=None, segments=None) -> dict[str, Any]:
        _, frames, track = self._feet_track(object_ids)
        skate, _ = mc.skate_per_frame(track, self.rig)
        found = mc.survey(track, self.rig)
        found.pop("_info")
        return {"frames": frames, "skate": mc.skate_summary(skate, segments), "survey": found}

    def prepare_feet(self, object_ids=None, params=None, steps=False, segments=None, ttl=900.0, *, parameters=None):
        settings=dict(parameters or {})
        if object_ids is not None: settings['object_ids']=object_ids
        if params is not None:
            settings.setdefault('limits',{}).update(position_correction_m=float(params.max_foot_offset)/100,iterations=int(params.iterations))
        if segments is not None:
            raise CleanupError('CONTACT_INTENT_AMBIGUOUS: legacy report segments are not an approved contact schedule; supply intent.contacts')
        settings['steps']=steps
        return self._prepare_plan('foot_contacts',settings,ttl)

    # -- fingers -----------------------------------------------------------

    def _finger_boxes(self, object_ids, joints):
        objects = self.objects(object_ids)
        boxes = {item["name"]: item["id"] for item in objects if mc.finger_parts(item["name"])}
        names = [item["name"] for item in objects if mc.finger_parts(item["name"])]
        if len(names) != len(set(names)):
            raise CleanupError("Several characters share finger names; pass object_ids for one character")
        if joints:
            wanted = {joint if joint.endswith("_Box") else joint + "_Box" for joint in joints}
            boxes = {name: object_id for name, object_id in boxes.items() if name in wanted}
        if not boxes:
            raise CleanupError("No finger controllers (e.g. RightHandIndex1_Box) found")
        return boxes

    def _finger_quaternions(self, object_ids, joints):
        boxes = self._finger_boxes(object_ids, joints)
        frames = self.frame_count()
        sampled = self.sample(list(boxes.values()), frames, space="local")
        return boxes, frames, {name: sampled["quaternion"][object_id] for name, object_id in boxes.items()}

    def analyze_fingers(self, object_ids=None, spike_deg: float = 10.0) -> dict[str, Any]:
        _, frames, quaternions = self._finger_quaternions(object_ids, None)
        rows = mc.finger_stats(quaternions, spike_deg)
        # Thumbs swing wide by design; only spikes flag them.
        flagged = [
            row
            for row in rows
            if row["steps_over_spike"] or (row["spread_range_deg"] > 15 and "Thumb" not in row["joint"])
        ]
        result = {"frames": frames, "joints": rows, "flagged": [row["joint"] for row in flagged]}
        try:
            fan = self._fan_track(object_ids)
        except CleanupError as exc:
            result["gaps_unavailable"] = str(exc)
            return result
        result["gaps"] = {side: mc.gap_summary(mc.finger_gaps(fan[2], side)["gaps"]) for side in mc.SIDES}
        for side, pairs in result["gaps"].items():
            if abs(pairs["IndexMiddle"]["median_deg"]) > FAN_FLAG_DEG:
                result["flagged"].append(f"{side}IndexMiddle gap")
        return result

    # -- finger fan --------------------------------------------------------

    def _fan_track(self, object_ids):
        objects = self.objects(object_ids)
        joint_names = [name for side in mc.SIDES for name in mc.fan_joint_names(side)]
        box_names = [f"{side}{suffix}" for side in mc.SIDES for suffix in ("Hand_Box", "HandIndex1_Box")]
        joints = self.by_name([item for item in objects if item["type"] == "Joint"], joint_names)
        boxes = self.by_name([item for item in objects if item["type"] == "Box"], box_names)
        frames = self.frame_count()
        sampled = self.sample(list(joints.values()) + list(boxes.values()), frames, space="global")
        positions = {name: sampled["position"][object_id] for name, object_id in joints.items()}
        rotations = {name: sampled["quaternion"][object_id] for name, object_id in boxes.items()}
        return boxes, frames, positions, rotations

    def prepare_finger_fan(self, object_ids=None, target_deg=3.0, keep=0.2, ttl=900.0, *, parameters=None):
        settings=dict(parameters or {}); settings.setdefault('target_deg',target_deg)
        if object_ids is not None: settings['object_ids']=object_ids
        if keep!=0.2:
            raise CleanupError('INVALID_POLICY: legacy fan keep has no authored anatomical-axis equivalent; use explicit target_angle_rad')
        return self._prepare_plan('finger_fan',settings,ttl)

    def prepare_fingers(self, object_ids=None, joints=None, spike_deg=10.0, ttl=900.0, *, parameters=None):
        settings=dict(parameters or {}); settings.setdefault('spike_deg',spike_deg)
        if object_ids is not None: settings['object_ids']=object_ids
        if joints is not None:
            self._require_contract('fingers')
            resolved=[self.profile.role_ids.get(role,role) for role in joints]
            if not set(resolved)<=set(self.profile.role_ids.values()):
                raise CleanupError('RIG_MAPPING_AMBIGUOUS: joints must be semantic roles or stable ids')
            settings['joint_ids']=resolved
        return self._prepare_plan('fingers',settings,ttl)

    # -- arm clearance -------------------------------------------------------

    def _arm_points(self, object_ids):
        objects = self.objects(object_ids)
        # The shoulder point anchors the solve; only ARM_POINTS are written.
        names = [f"{s}{name}" for s in mc.SIDES for name in ("Arm_MainPoint", *ARM_POINTS)]
        points = self.by_name([item for item in objects if item["type"] == "Point"], names)
        meshes = [item for item in objects if item["type"] == "Mesh Object"]
        if len(meshes) != 1:
            raise CleanupError(f"Expected one character mesh, found {len(meshes)}; pass object_ids including the mesh")
        return points, meshes[0]["id"]

    def _arm_mesh(self, object_ids, name: str, every_frame: bool = False):
        """Arm controller positions and the skinned mesh at the arm controllers' keys (or every frame)."""
        points, mesh_id = self._arm_points(object_ids)
        frames = self.frame_count()
        keys = self.key_frames(list(points.values()))
        written = [points[f"{s}{point}"] for s in mc.SIDES for point in ARM_POINTS]
        common = sorted(set.intersection(*[set(keys[item]) for item in written]))
        common = [frame for frame in common if 0 <= frame < frames]
        if len(common) < 3:
            raise CleanupError("The arm controllers share fewer than three keys; reduce and bake the clip first")
        keys = np.array(common)
        if every_frame:
            common = list(range(frames))
        sampled = self.sample(list(points.values()), frames, only=common)
        track = {name_: sampled["position"][object_id] for name_, object_id in points.items()}
        result = self._read(
            "mesh_sample",
            [Operation(name="animation.mesh_sample", arguments={"id": mesh_id, "frames": common, "name": name})],
            timeout=600,
        )
        mesh = np.load(result["path"])
        return points, np.array(common), track, mesh, keys

    def _arm_surface(self, mesh, track, side, params):
        return mc.MeshSurface(
            mesh["positions"],
            mesh["triangles"],
            mesh["dominant"],
            mesh["joints"],
            side,
            track[f"{side}Arm_MainPoint"],
            track[f"{side}ForeArm_MainPoint"],
            track[f"{side}Hand_MainPoint"],
            params,
        )

    def analyze_arms(
        self, object_ids=None, params: mc.ArmParams | None = None, every_frame: bool = False
    ) -> dict[str, Any]:
        """Where each arm's mesh is inside the rest of the body, measured on the skinned mesh.

        Samples the arm controllers' key frames, or every frame to check the
        interpolated frames between keys as well.
        """
        params = params or mc.ArmParams()
        _, frames, track, mesh, _ = self._arm_mesh(object_ids, "arms_analyze", every_frame)
        zero = np.zeros((2, len(frames), 3))
        return {
            "sampled_frames": len(frames),
            **{
                side: mc.depth_summary(self._arm_surface(mesh, track, side, params).depth(zero), frames, params.allow)
                for side in mc.SIDES
            },
        }

    def prepare_arm_clearance(self, object_ids=None, params=None, ttl=900.0, *, parameters=None):
        settings=dict(parameters or {})
        if object_ids is not None: settings['object_ids']=object_ids
        if params is not None:
            settings.setdefault('limits',{}).update(collision_clearance_m=float(params.margin)/100,collision_residual_m=float(params.allow)/100,arm_radius_m=float(params.hand_radius)/100,iterations=int(params.iterations))
        return self._prepare_plan('arm_clearance',settings,ttl)

    # -- hand styling --------------------------------------------------------

    def _hand_track(self, object_ids):
        """Joint positions, box orientations and hand points for both hands on every frame."""
        objects = self.objects(object_ids)
        fingers = ("Thumb", *mc.FOUR_FINGERS)
        joint_names = [
            name
            for side in mc.SIDES
            for name in (
                f"{side}ForeArm",
                f"{side}Hand",
                *[f"{side}Hand{finger}{index}" for finger in fingers for index in (1, 2, 3, 4)],
            )
        ]
        box_names = [
            name
            for side in mc.SIDES
            for name in (
                f"{side}Hand_Box",
                *[f"{side}Hand{finger}{index}_Box" for finger in fingers for index in (1, 2, 3)],
            )
        ]
        point_names = [f"{side}{name}" for side in mc.SIDES for name in HAND_POINTS]
        joints = self.by_name([item for item in objects if item["type"] == "Joint"], joint_names)
        boxes = self.by_name([item for item in objects if item["type"] == "Box"], box_names)
        points = self.by_name([item for item in objects if item["type"] == "Point"], point_names)
        frames = self.frame_count()
        sampled = self.sample([*joints.values(), *boxes.values(), *points.values()], frames)
        return {
            "frames": frames,
            "joints": {name: sampled["position"][object_id] for name, object_id in joints.items()},
            "boxes": {name: sampled["quaternion"][object_id] for name, object_id in boxes.items()},
            "points": {name: sampled["position"][object_id] for name, object_id in points.items()},
            "box_ids": boxes,
            "point_ids": points,
        }

    def analyze_hands(self, object_ids=None) -> dict[str, Any]:
        """Wrist bend ranges and how the hands split between open, half-closed and fist."""
        track = self._hand_track(object_ids)
        out: dict[str, Any] = {"frames": track["frames"]}
        for side in mc.SIDES:
            hand = mc.HandGeometry(track["joints"], track["boxes"], side)
            closure = hand.closure()
            out[side] = {
                "wrist": mc.wrist_summary(hand),
                "closure_deg": [round(float(item)) for item in np.percentile(closure, [5, 50, 95])],
            }
        return out

    def prepare_wrists(self, object_ids=None, params=None, ttl=900.0, *, parameters=None):
        settings=dict(parameters or {})
        if object_ids is not None: settings['object_ids']=object_ids
        if params is not None:
            raise CleanupError('JOINT_LIMITS_UNAVAILABLE: use declared anatomical rig limits and sigma_s instead of legacy chart limits')
        return self._prepare_plan('wrist_soften',settings,ttl)

    def prepare_hand_pose(self, object_ids=None, params=None, ttl=900.0, *, parameters=None):
        settings=dict(parameters or {})
        if object_ids is not None: settings['object_ids']=object_ids
        if params is not None:
            raise CleanupError('RIG_ADAPTER_UNVERIFIED: legacy universal open/fist charts require authored per-role pose_angles_rad')
        return self._prepare_plan('hand_pose',settings,ttl)

    # -- resting hands -------------------------------------------------------

    def prepare_hand_rest(self, object_ids=None, near_cm=14.0, touch_cm=0.4, ttl=900.0, *, parameters=None):
        settings=dict(parameters or {})
        if object_ids is not None: settings['object_ids']=object_ids
        return self._prepare_plan('hand_rest',settings,ttl)

    # -- wrist accents -------------------------------------------------------

    def prepare_wrist_accent(self, side, pulses, amplitude_deg=15.0, object_ids=None, ttl=900.0, *, parameters=None):
        settings=dict(parameters or {}); settings.update(side=side,pulses=pulses,amplitude_deg=amplitude_deg)
        if object_ids is not None: settings['object_ids']=object_ids
        return self._prepare_plan('wrist_accent',settings,ttl)
