"""Turn authenticated native observations into reviewable motion input drafts.

Draft references are local lookup handles, never mutation capabilities. Missing
SDK metadata remains missing; names are not interpreted as rig authority.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
import secrets

from .capture import canonical_data,canonical_digest
from .motion_context import MotionModel,MotionInputError,MotionContext,RigProfile,IntentConstraints,SupportTrack


class MotionInputDraft(MotionModel):
    draft_ref: str
    selection: dict
    values: dict
    provenance: dict
    missing_fields: tuple[str,...]
    ambiguous_fields: dict[str,tuple[str,...]]
    source_fingerprint: str
    rig_structure_fingerprint: str
    observation_digest: str


class ResolvedMotionInputs(MotionModel):
    draft_ref: str
    profile: dict
    context: dict
    intent: dict
    supports: dict
    provenance: dict
    source_fingerprint: str
    rig_structure_fingerprint: str
    observation_digest: str


class MotionInputResolver:
    def __init__(self,reader,verifier):
        self._reader=reader
        self._verifier=verifier
        self._drafts={}

    def _observe(self,selection):
        if not callable(self._reader) or not callable(self._verifier):
            raise MotionInputError("MOTION_INPUT_ADAPTER_UNAVAILABLE","authenticated native input reader is unavailable")
        value=self._reader(deepcopy(selection))
        if getattr(value,"ok",None) is False:
            raise MotionInputError(getattr(value,"error_code",None) or "MOTION_INPUT_ADAPTER_UNAVAILABLE",
                                   getattr(value,"error_message",None) or "native input observation failed")
        observation=deepcopy(getattr(value,"result",value))
        if not isinstance(observation,dict):
            raise MotionInputError("INCOMPLETE_CAPTURE","native observation must be an object")
        digest=canonical_digest(observation)
        receipt=self._verifier(observation,digest)
        result=getattr(receipt,"result",None)
        if not (getattr(receipt,"ok",False) and isinstance(result,dict)
                and result.get("observation_digest")==digest):
            raise MotionInputError("MOTION_INPUT_PROVENANCE_UNVERIFIED","native observation evidence is not authenticated")
        for key in ("values","provenance","source_fingerprint","rig_structure_fingerprint","evidence_ref"):
            if not observation.get(key):
                raise MotionInputError("INCOMPLETE_CAPTURE",f"native observation lacks {key}")
        return observation,digest

    def inspect_motion_inputs(self,character_ref,frame_range,support_refs=(),purpose="repair"):
        if purpose not in ("repair","styling","retarget"):
            raise MotionInputError("INVALID_POLICY","unknown motion purpose")
        if (len(frame_range)!=2 or any(type(f) is not int or f<0 for f in frame_range)
                or frame_range[1]<frame_range[0]):
            raise MotionInputError("INVALID_POLICY","exact integer frame range required")
        selection={"character_ref":character_ref,"frame_range":list(frame_range),
                   "support_refs":list(support_refs),"purpose":purpose}
        observation,digest=self._observe(selection)
        values=observation["values"]
        missing=[]
        for field in ("context","objects","role_candidates","root_rotation_id"):
            if not values.get(field) or not observation["provenance"].get(field):
                missing.append(field)
        context_values=values.get("context",{})
        for field in ("time_s","time_source","fps_num","fps_den","metres_per_scene_unit",
                      "scene_to_solver_basis","metadata_provenance"):
            if field not in context_values:
                missing.append("context."+field)
        for row in values.get("objects",()):
            if row.get("character_id") is None:
                missing.append("character_ownership:"+str(row.get("id")))
        ids=[row.get("id") for row in values.get("objects",())]
        if any(not isinstance(key,str) or not key for key in ids) or len(set(ids))!=len(ids):
            raise MotionInputError("RIG_MAPPING_AMBIGUOUS","duplicate or missing native object IDs")
        candidates=values.get("role_candidates",{})
        ambiguous={role:tuple(matches) for role,matches in candidates.items() if len(matches)!=1}
        singleton_roles={}
        for role,matches in candidates.items():
            if len(matches)==1:singleton_roles.setdefault(matches[0],[]).append(role)
        for object_id,roles in singleton_roles.items():
            if len(roles)>1:ambiguous["shared_object:"+object_id]=tuple(roles)
        for role,matches in candidates.items():
            if not matches:
                missing.append("role:"+role)
            if any(key not in ids for key in matches):
                raise MotionInputError("RIG_MAPPING_AMBIGUOUS","role candidate references an unobserved ID")
        draft=MotionInputDraft(draft_ref=secrets.token_hex(20),selection=selection,values=values,
            provenance=observation["provenance"],missing_fields=tuple(missing),ambiguous_fields=ambiguous,
            source_fingerprint=observation["source_fingerprint"],rig_structure_fingerprint=observation["rig_structure_fingerprint"],
            observation_digest=digest)
        self._drafts[draft.draft_ref]=draft.model_copy(deep=True)
        return draft

    def resolve_motion_inputs(self,draft_ref,overrides,intent_policy):
        draft=self._drafts.get(draft_ref)
        if draft is None:
            raise MotionInputError("STALE_MOTION_INPUT_DRAFT","unknown or expired draft")
        observation,digest=self._observe(draft.selection)
        if (observation["source_fingerprint"]!=draft.source_fingerprint
                or observation["rig_structure_fingerprint"]!=draft.rig_structure_fingerprint
                or canonical_digest(observation["values"])!=canonical_digest(draft.values)):
            raise MotionInputError("STALE_MOTION_INPUT_DRAFT","source or input metadata changed after inspection")
        if set(overrides)-{"roles","reusable_rig_structure_fingerprint"}:
            raise MotionInputError("INVALID_POLICY","only semantic role choices may override native inputs")
        if overrides.get("reusable_rig_structure_fingerprint",draft.rig_structure_fingerprint)!=draft.rig_structure_fingerprint:
            raise MotionInputError("STALE_RIG_PROFILE","reusable profile does not match observed rig structure")
        if draft.missing_fields:
            raise MotionInputError("MISSING_MOTION_INPUTS",", ".join(draft.missing_fields))
        values=draft.values
        roles={}
        supplied=overrides.get("roles",{})
        if set(supplied)-set(values["role_candidates"]):
            raise MotionInputError("RIG_MAPPING_AMBIGUOUS","override introduces an unobserved semantic role")
        for role,candidates in values["role_candidates"].items():
            selected=supplied.get(role,candidates[0] if len(candidates)==1 else None)
            if selected is None or selected not in candidates:
                raise MotionInputError("RIG_MAPPING_AMBIGUOUS",f"select one observed stable ID for {role}")
            roles[role]=selected
        by_id={row["id"]:row for row in values["objects"]}
        if any(row.get("character_id")!=draft.selection["character_ref"] for row in by_id.values()):
            raise MotionInputError("INVALID_WRITE_SCOPE","native observation contains another character's objects")
        rotation_id=values["root_rotation_id"]
        if rotation_id not in by_id or not by_id[rotation_id].get("rotation_channel_observed"):
            raise MotionInputError("ROOT_ROTATION_UNAVAILABLE","root orientation must be observed independently of root Point position")
        if rotation_id not in roles.values():
            roles["root_orientation"]=rotation_id
        selected=set(roles.values())
        required=("parent_id","rest_local_transform","joint_axes","joint_limits_rad")
        for object_id in selected:
            if any(key not in by_id[object_id] for key in required):
                raise MotionInputError("MISSING_MOTION_INPUTS",f"unobserved rest/hierarchy/joint metadata: {object_id}")
        context=MotionContext.from_dict(values["context"])
        if (int(context.frames[0]),int(context.frames[-1]))!=tuple(draft.selection["frame_range"]):
            raise MotionInputError("INCOMPLETE_CAPTURE","native context does not cover requested interval")
        profile=RigProfile(profile_id="observed:"+draft.rig_structure_fingerprint,
            character_id=draft.selection["character_ref"],role_ids=roles,
            writable_ids=frozenset(key for key in selected if by_id[key].get("writable") is True),
            derived_ids=frozenset(key for key,row in by_id.items() if row.get("derived") is True),
            dependency_ids=frozenset(by_id)-selected,
            parent_ids={key:row["parent_id"] for key,row in by_id.items() if "parent_id" in row},
            rest_local_transforms={key:by_id[key]["rest_local_transform"] for key in selected},
            joint_axes={role:by_id[key]["joint_axes"] for role,key in roles.items()},
            joint_limits_rad={role:by_id[key]["joint_limits_rad"] for role,key in roles.items()},
            bone_lengths_m=values.get("bone_lengths_m",{}),mesh_ids=tuple(values.get("mesh_ids",())),
            controller_adapter_id=values.get("controller_adapter_id",""))
        intent=IntentConstraints.model_validate(intent_policy)
        if intent.action!=draft.selection["purpose"]:
            raise MotionInputError("INVALID_POLICY","intent action differs from inspected purpose")
        if (intent.editable_frames[0]<context.frames[0] or intent.editable_frames[1]>context.frames[-1]
                or (set(intent.locked_roles_frames)|set(intent.key_pose_locks))-set(roles)):
            raise MotionInputError("INVALID_POLICY","intent interval or role locks escape observed input scope")
        supports={key:SupportTrack(**track) for key,track in values.get("supports",{}).items()}
        if set(draft.selection["support_refs"])-set(supports):
            raise MotionInputError("MISSING_MOTION_INPUTS","requested support transforms were not observed")
        if any(len(track.origin_m)!=len(context.frames) for track in supports.values()):
            raise MotionInputError("INCOMPLETE_CAPTURE","support traces do not cover the physical grid")
        return ResolvedMotionInputs(draft_ref=draft_ref,profile=canonical_data(asdict(profile)),
            context=context.as_dict(),intent=intent.model_dump(mode="json"),
            supports=canonical_data({key:asdict(track) for key,track in supports.items()}),
            provenance=draft.provenance,source_fingerprint=draft.source_fingerprint,
            rig_structure_fingerprint=draft.rig_structure_fingerprint,observation_digest=digest)
