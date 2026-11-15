"""Observed interpolation and opt-in key-topology plans, without native effects."""
from __future__ import annotations

from bisect import bisect_right
from typing import Literal

from pydantic import Field, StrictInt, model_validator

from .capture import canonical_digest, validate_write_scope
from .motion_context import MotionModel, MotionInputError


class DriverKeyLayout(MotionModel):
    object_id: str
    channel: str
    space: str
    layer_id: str
    key_ids: tuple[str, ...]
    frames: tuple[StrictInt, ...]
    values: tuple[tuple[float, ...], ...] = ()
    segment_modes: tuple[str, ...]
    tangents: tuple[dict, ...] = ()
    boundary_keys: tuple[dict, ...] = ()
    influences: dict
    key_id_kind: Literal["native_id","layer_frame_locator"] = "native_id"
    data_id: str | None = None
    data_mode: str | None = None
    layer_objects: tuple[str,...] = ()
    sections: tuple[dict,...] = ()
    native_model: str | None = None
    reason_codes: tuple[str,...] = ()

    @model_validator(mode="after")
    def valid(self):
        if (self.channel not in ("position","rotation") or self.space not in ("local","global")
                or not self.layer_id or not self.frames or len(self.frames)!=len(self.key_ids)
                or any(frame<0 for frame in self.frames)
                or len(set(self.key_ids))!=len(self.key_ids)
                or any(b<=a for a,b in zip(self.frames,self.frames[1:]))
                or len(self.segment_modes)!=max(len(self.frames)-1,0)):
            raise ValueError("invalid exact per-driver key layout")
        if self.values and (len(self.values)!=len(self.frames) or any(len(x)!=(3 if self.channel=="position" else 4) for x in self.values)):
            raise ValueError("key value coverage/dimension is incomplete")
        return self


class KeyLayoutObservation(MotionModel):
    build_fingerprint: str
    evaluator_fingerprint: str
    source_fingerprint: str
    capture_digest: str
    drivers: tuple[DriverKeyLayout, ...]
    evidence_ref: str
    support_status: Literal["supported","unverified","unsupported"] = "unverified"
    reason_codes: tuple[str,...] = ()
    candidate_models: tuple[str,...] = ()
    qualified_models: tuple[str,...] = ()
    native_source_scope: dict = Field(default_factory=dict)
    raw_sample_projection: dict = Field(default_factory=dict)
    capture_binding: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def valid(self):
        if any(not value for value in (self.build_fingerprint,self.evaluator_fingerprint,
                                      self.source_fingerprint,self.capture_digest,self.evidence_ref)):
            raise ValueError("key observation provenance is incomplete")
        identities=[(x.object_id,x.channel,x.space) for x in self.drivers]
        if len(set(identities))!=len(identities):
            raise ValueError("ambiguous driver/channel/layer resolution")
        return self


def verify_key_layout(observation, capture, verifier):
    observed=KeyLayoutObservation.model_validate(observation)
    digest=canonical_digest(observed.model_dump(mode="json"))
    if observed.capture_digest!=canonical_digest(capture.as_dict()) or not callable(verifier):
        raise MotionInputError("INTERPOLATION_MODEL_UNVERIFIED","descriptor is not bound to this evaluated capture")
    receipt=verifier(observed.model_dump(mode="json"),digest)
    result=getattr(receipt,"result",None)
    if not (getattr(receipt,"ok",False) and isinstance(result,dict)
            and result.get("key_layout_digest")==digest):
        raise MotionInputError("INTERPOLATION_MODEL_UNVERIFIED","native key-layout evidence could not be authenticated")
    if observed.support_status!="supported" or observed.reason_codes:
        raise MotionInputError("INTERPOLATION_MODEL_UNVERIFIED",", ".join(observed.reason_codes) or "native model is not qualified")
    return observed,digest


class KeyAddition(MotionModel):
    object_id: str
    channel: str
    layer_id: str
    frame: StrictInt
    value: tuple[float, ...]
    mode: str
    tangent: dict


class LocatorInsertionEvidence(MotionModel):
    """Native-private insertion prediction, never authority merely by parsing.

    Values use the observed driver's raw local scene units. This contract does
    not convert canonical solver positions or invent persistent key identities.
    Only the insertion verifier may authenticate these exact bytes.
    """
    contract: Literal["independent_absent_layer_frame_position_v1"]
    key_id_kind: Literal["layer_frame_locator"]
    value_space: Literal["native_scene_units"]
    request_digest: str
    key_layout_digest: str
    original_topology_digest: str
    capture_digest: str
    context_digest: str
    source_binding_digest: str
    runtime_epoch: str
    runtime_fingerprint: str
    scene_instance_id: str
    document_lineage_id: str
    before_projection_digest: str
    model_qualification_digest: str
    insertion_qualification_digest: str
    expected_driver: DriverKeyLayout

    @model_validator(mode="after")
    def complete(self):
        hashes=(self.request_digest,self.key_layout_digest,self.original_topology_digest,
                self.capture_digest,self.context_digest,self.source_binding_digest,
                self.runtime_fingerprint,self.before_projection_digest,
                self.model_qualification_digest,self.insertion_qualification_digest)
        if (any(len(value)!=64 or any(c not in "0123456789abcdef" for c in value) for value in hashes)
                or not all((self.runtime_epoch,self.scene_instance_id,self.document_lineage_id))):
            raise ValueError("incomplete native locator insertion provenance")
        return self


class KeyTopologyDelta(MotionModel):
    original_topology_digest: str
    key_layout_digest: str
    additions: tuple[KeyAddition, ...]
    impact_frames: tuple[StrictInt, ...]
    non_target_effects: tuple[str, ...]
    adapter_evidence_ref: str
    original_layout: tuple[DriverKeyLayout,...]
    locator_insertion: LocatorInsertionEvidence | None = None

    @model_validator(mode="after")
    def matches_original(self):
        if self.original_topology_digest!=canonical_digest([x.model_dump(mode="json") for x in self.original_layout]):
            raise ValueError("original topology digest does not match retained observations")
        locator=any(x.key_id_kind=="layer_frame_locator" for x in self.original_layout)
        if locator and self.locator_insertion is None:
            raise ValueError("locator insertion requires retained authenticated prediction")
        if self.locator_insertion is not None:
            proof=self.locator_insertion
            request={"key_layout_digest":self.key_layout_digest,
                     "additions":[x.model_dump(mode="json") for x in self.additions]}
            if (proof.original_topology_digest!=self.original_topology_digest
                    or proof.key_layout_digest!=self.key_layout_digest
                    or proof.request_digest!=canonical_digest(request)):
                raise ValueError("locator prediction differs from retained plan")
            _validate_locator_prediction(self.original_layout,self.additions,proof.expected_driver)
        return self


def _frame_rows(rows):
    result={}
    for row in rows:
        frame=row.get("frame")
        if type(frame) is not int or frame<0 or frame in result:
            raise MotionInputError("KEY_LAYOUT_INSUFFICIENT","ambiguous native section or boundary frame")
        result[frame]=row
    return result


def _validate_locator_prediction(original, additions, after):
    """Preserve every old observable field; admit only exact absent-frame rows."""
    if len(original)!=1 or not 1<=len(additions)<=8:
        raise MotionInputError("KEY_INSERTION_ADAPTER_UNVERIFIED","locator contract requires one driver and one to eight additions")
    before=original[0]
    identity=(before.object_id,before.channel,before.layer_id)
    if (before.key_id_kind!="layer_frame_locator" or before.channel!="position" or before.space!="local"
            or before.layer_objects!=(before.object_id,) or not before.data_id or before.data_mode!="Animation"
            or len(before.frames)+len(additions)>16 or before.reason_codes
            or any((x.object_id,x.channel,x.layer_id)!=identity for x in additions)):
        raise MotionInputError("KEY_INSERTION_ADAPTER_UNVERIFIED","native locator contract does not cover this driver")
    mutable={"frames","key_ids","values","tangents","segment_modes","boundary_keys","sections"}
    if before.model_dump(exclude=mutable)!=after.model_dump(exclude=mutable):
        raise MotionInputError("KEY_TOPOLOGY_MISMATCH","predicted driver ownership or metadata changed")
    old_sections=_frame_rows(before.sections);new_sections=_frame_rows(after.sections)
    old_boundaries=_frame_rows(before.boundary_keys);new_boundaries=_frame_rows(after.boundary_keys)
    new_frames={x.frame for x in additions}
    if (len(new_frames)!=len(additions) or new_frames&set(before.frames) or new_frames&set(old_sections)
            or after.frames!=tuple(sorted(set(before.frames)|new_frames))
            or set(old_boundaries)!=set(before.frames)
            or set(new_boundaries)!=set(old_boundaries)|new_frames
            or set(new_sections)!=set(old_sections)|new_frames
            or any(new_sections[frame]!=row for frame,row in old_sections.items())
            or any(new_boundaries[frame]!=row for frame,row in old_boundaries.items())
            or len(before.values)!=len(before.frames) or len(before.tangents)!=len(before.frames)
            or len(after.values)!=len(after.frames) or len(after.tangents)!=len(after.frames)):
        raise MotionInputError("KEY_TOPOLOGY_MISMATCH","native prediction rewrites original topology or omits exact new rows")
    for driver in (before,after):
        if driver.key_ids!=tuple(driver.layer_id+":"+str(frame) for frame in driver.frames):
            raise MotionInputError("KEY_TOPOLOGY_MISMATCH","layer/frame identity cannot impersonate a persistent native ID")
    additions_by_frame={x.frame:x for x in additions}
    if any(right-left<2 for left,right in zip(after.frames,after.frames[1:])):
        raise MotionInputError("KEY_INSERTION_ADAPTER_UNVERIFIED","SDK adjacent-frame section rewriting is outside the qualified locator contract")
    for index,frame in enumerate(after.frames):
        addition=additions_by_frame.get(frame)
        if addition is None:
            old_index=before.frames.index(frame)
            if (after.values[index],after.tangents[index])!=(before.values[old_index],before.tangents[old_index]):
                raise MotionInputError("KEY_TOPOLOGY_MISMATCH","predicted existing value or tangent changed")
            expected_mode=before.segment_modes[old_index] if old_index<len(before.segment_modes) else None
        else:
            if not before.frames[0]<frame<before.frames[-1]:
                raise MotionInputError("KEY_LAYOUT_INSUFFICIENT","locator insertion must split an existing interval")
            expected_mode=before.segment_modes[bisect_right(before.frames,frame)-1]
            if (addition.mode not in ("LINEAR","STEP") or addition.mode!=expected_mode
                    or after.values[index]!=addition.value or after.tangents[index]!=addition.tangent):
                raise MotionInputError("KEY_TOPOLOGY_MISMATCH","locator prediction exceeds the qualified value/tangent/mode request")
            expected_boundary={"frame":frame,"key_id":before.layer_id+":"+str(frame),
                "key_id_kind":"layer_frame_locator","locked":False,"event":False,"label":None}
            section=new_sections[frame]
            expected_tangent={**section.get("tangent",{}),"key_common":section.get("key_common"),"label":section.get("label")}
            if (new_boundaries[frame]!=expected_boundary or section.get("is_key") is not True
                    or section.get("interval_mode")!=addition.mode
                    or section.get("interval_common")!={"ik_fk":"FK","fixation":"Free"}
                    or section.get("key_common")!={"ik_fk":"FK","fixation":"Free"}
                    or section.get("label") is not None or section.get("tangent",{}).get("mode")!="Continuous"
                    or expected_tangent!=addition.tangent):
                raise MotionInputError("KEY_TOPOLOGY_MISMATCH","unqualified new section, event or boundary metadata")
        if index<len(after.segment_modes) and after.segment_modes[index]!=expected_mode:
            raise MotionInputError("KEY_TOPOLOGY_MISMATCH","predicted outgoing interpolation changed")


def _locator_evidence(result,observed,capture,values,request_digest):
    try:
        proof=LocatorInsertionEvidence.model_validate(result.get("locator_insertion"))
    except ValueError as exc:
        raise MotionInputError("KEY_INSERTION_ADAPTER_UNVERIFIED","private locator prediction is incomplete") from exc
    source=capture.as_dict()["source_binding"]
    binding=source.get("binding") if isinstance(source,dict) else None
    binding=binding if isinstance(binding,dict) else {}
    if (source is None or proof.request_digest!=request_digest
            or proof.key_layout_digest!=canonical_digest(observed.model_dump(mode="json"))
            or proof.original_topology_digest!=canonical_digest([x.model_dump(mode="json") for x in observed.drivers])
            or proof.capture_digest!=canonical_digest(capture.as_dict())
            or proof.context_digest!=canonical_digest(capture.context.as_dict())
            or proof.source_binding_digest!=canonical_digest(source)
            or any(getattr(proof,key)!=binding.get(key)
                   for key in ("runtime_epoch","scene_instance_id","document_lineage_id"))):
        raise MotionInputError("KEY_INSERTION_ADAPTER_UNVERIFIED","locator evidence is not bound to the original source and capture")
    _validate_locator_prediction(observed.drivers,values,proof.expected_driver)
    return proof


def plan_key_insertion(observation, capture, rig, intent, additions, *, verifier,
                       insertion_verifier, generated_keys_budget):
    """Create an exact topology delta only for an authenticated insertion adapter.

    Planning neither performs insertion nor turns an unsupported adapter on.
    Existing-key outgoing modes stay unchanged. A new key's outgoing mode
    requires interpolation-change authority only if it differs from the
    original segment being split. Deletions and retimes are absent.
    The separately qualified locator contract accepts raw local scene-unit
    positions and preserves each split segment's original LINEAR/STEP mode.
    """
    observed,digest=verify_key_layout(observation,capture,verifier)
    if not intent.allow_key_insertion:
        raise MotionInputError("KEY_INSERTION_NOT_AUTHORIZED","intent does not allow new keys")
    values=tuple(KeyAddition.model_validate(x) for x in additions)
    if type(generated_keys_budget) is not int or generated_keys_budget<0:
        raise MotionInputError("INVALID_POLICY","generated key budget must be a nonnegative integer")
    budget=min(generated_keys_budget,int(intent.correction_envelope.get("added_keys",0)))
    if len(values)>budget:
        raise MotionInputError("RESOURCE_BUDGET_EXCEEDED","generated key count exceeds the original grant")
    layouts={(x.object_id,x.channel,x.layer_id):x for x in observed.drivers}
    identities=set()
    for value in values:
        layout=layouts.get((value.object_id,value.channel,value.layer_id))
        identity=(value.object_id,value.channel,value.layer_id,value.frame)
        if identity in identities or layout is None or value.frame in layout.frames:
            raise MotionInputError("KEY_LAYOUT_INSUFFICIENT","addition duplicates or escapes the observed topology")
        identities.add(identity)
        if value.frame not in set(map(int,capture.context.frames)) or not layout.frames[0]<value.frame<layout.frames[-1]:
            raise MotionInputError("KEY_LAYOUT_INSUFFICIENT","insertion must stay within captured existing-key influence boundaries")
        if len(layout.values)!=len(layout.frames) or len(layout.tangents)!=len(layout.frames):
            raise MotionInputError("KEY_LAYOUT_INSUFFICIENT","insertion requires complete original values and tangents")
        if any(row.get("event") or row.get("locked") for row in layout.boundary_keys
               if row.get("frame")==value.frame):
            raise MotionInputError("INTENT_LOCK_VIOLATION","event or boundary key is protected")
        # The old left key retains its outgoing mode up to the first addition.
        # Each added key owns the following subsegment, so compare its mode to
        # that original segment, including multiple additions in one segment.
        segment_index=bisect_right(layout.frames,value.frame)-1
        original_mode=layout.segment_modes[segment_index]
        if value.mode not in ("LINEAR","STEP") or value.mode!=original_mode:
            if not intent.allow_interpolation_change:
                raise MotionInputError("INTERPOLATION_CHANGE_NOT_AUTHORIZED","new segment changes interpolation semantics")
        if len(value.value)!=(3 if value.channel=="position" else 4):
            raise MotionInputError("INVALID_POLICY","key value dimension does not match its channel")
        validate_write_scope([{"id":value.object_id,"frame":value.frame}],rig,intent)
        for role,locks in intent.key_pose_locks.items():
            if rig.role_ids.get(role)==value.object_id and value.frame in locks:
                raise MotionInputError("INTENT_LOCK_VIOLATION","protected pose key cannot be inserted")
        if any(c.role in rig.role_ids and rig.role_ids[c.role]==value.object_id
               and value.frame in (c.first_frame,c.last_frame) for c in intent.contacts):
            raise MotionInputError("INTENT_LOCK_VIOLATION","contact boundary topology is protected")
    request={"key_layout_digest":digest,"additions":[x.model_dump(mode="json") for x in values]}
    receipt=insertion_verifier(request,canonical_digest(request)) if callable(insertion_verifier) else None
    result=getattr(receipt,"result",None)
    if not (getattr(receipt,"ok",False) and isinstance(result,dict)
            and result.get("request_digest")==canonical_digest(request)
            and result.get("shared_layer_effects_observed") is True
            and result.get("adapter_evidence_ref")):
        raise MotionInputError("KEY_INSERTION_ADAPTER_UNVERIFIED","exact insertion and shared-layer effects are not observed")
    locator=None
    if any(driver.key_id_kind=="layer_frame_locator" for driver in observed.drivers):
        locator=_locator_evidence(result,observed,capture,values,canonical_digest(request))
    return KeyTopologyDelta(original_topology_digest=canonical_digest([x.model_dump(mode="json") for x in observed.drivers]),
        key_layout_digest=digest,additions=values,impact_frames=tuple(int(x) for x in capture.context.frames),
        non_target_effects=tuple(result.get("non_target_effects",())),adapter_evidence_ref=result["adapter_evidence_ref"],
        original_layout=observed.drivers,locator_insertion=locator)


class LocatorInsertionCompletion(MotionModel):
    """Private actual full-closure readback bound to the original plan."""
    contract: Literal["independent_absent_layer_frame_position_v1"]
    request_digest: str
    key_layout_digest: str
    adapter_evidence_ref: str
    source_binding_digest: str
    runtime_epoch: str
    runtime_fingerprint: str
    scene_instance_id: str
    document_lineage_id: str
    before_projection_digest: str
    after_projection_digest: str
    completion_receipt_digest: str

    @model_validator(mode="after")
    def complete(self):
        hashes=(self.request_digest,self.key_layout_digest,self.source_binding_digest,
                self.runtime_fingerprint,self.before_projection_digest,self.after_projection_digest,
                self.completion_receipt_digest)
        if (any(len(value)!=64 or any(c not in "0123456789abcdef" for c in value) for value in hashes)
                or not all((self.runtime_epoch,self.scene_instance_id,self.document_lineage_id,self.adapter_evidence_ref))):
            raise ValueError("incomplete native locator completion provenance")
        return self


def _validate_locator_readback(delta,observed,digest,result):
    try:
        completed=LocatorInsertionCompletion.model_validate(result.get("locator_insertion_completion"))
    except ValueError as exc:
        raise MotionInputError("KEY_TOPOLOGY_READBACK_UNVERIFIED","private locator completion evidence is incomplete") from exc
    proof=delta.locator_insertion
    if (any(getattr(completed,key)!=getattr(proof,key) for key in (
            "contract","request_digest","source_binding_digest","runtime_epoch","runtime_fingerprint",
            "scene_instance_id","document_lineage_id","before_projection_digest"))
            or completed.adapter_evidence_ref!=delta.adapter_evidence_ref
            or completed.key_layout_digest!=digest
            or completed.completion_receipt_digest!=result["completion_receipt_digest"]):
        raise MotionInputError("KEY_TOPOLOGY_READBACK_UNVERIFIED","completion belongs to a different insertion or original source")
    if (observed.support_status!="supported" or observed.reason_codes
            or len(observed.drivers)!=1 or observed.drivers[0]!=proof.expected_driver):
        raise MotionInputError("KEY_TOPOLOGY_MISMATCH","actual locator topology differs from the exact authenticated prediction")


def validate_key_topology_readback(delta,observation,*,verifier):
    """Compare authored topology after terminal completion, including old keys."""
    delta=KeyTopologyDelta.model_validate(delta)
    observed=KeyLayoutObservation.model_validate(observation)
    digest=canonical_digest(observed.model_dump(mode="json"))
    receipt=verifier(observed.model_dump(mode="json"),digest) if callable(verifier) else None
    result=getattr(receipt,"result",None)
    if not (getattr(receipt,"ok",False) and isinstance(result,dict)
            and result.get("key_layout_digest")==digest and result.get("completion_receipt_digest")):
        raise MotionInputError("KEY_TOPOLOGY_READBACK_UNVERIFIED","authored topology is not bound to terminal completion")
    if delta.locator_insertion is not None:
        _validate_locator_readback(delta,observed,digest,result)
        return {"status":"matched","key_layout_digest":digest,
            "completion_receipt_digest":result["completion_receipt_digest"],"added_keys":len(delta.additions),
            "key_id_kind":"layer_frame_locator","value_space":"native_scene_units"}
    actual={(x.object_id,x.channel,x.layer_id):x for x in observed.drivers}
    original={(x.object_id,x.channel,x.layer_id):x for x in delta.original_layout}
    if set(actual)!=set(original):
        raise MotionInputError("KEY_TOPOLOGY_MISMATCH","driver/layer closure changed")
    for identity,before in original.items():
        after=actual[identity]
        additions=[x for x in delta.additions if (x.object_id,x.channel,x.layer_id)==identity]
        expected={frame:(key,value,tangent) for frame,key,value,tangent
                  in zip(before.frames,before.key_ids,before.values,before.tangents,strict=True)}
        if (len(after.values)!=len(after.frames) or len(after.tangents)!=len(after.frames)
                or set(after.frames)!=set(before.frames)|{x.frame for x in additions}
                or after.boundary_keys!=before.boundary_keys or after.influences!=before.influences):
            raise MotionInputError("KEY_TOPOLOGY_MISMATCH","unexpected topology, boundary or influence changes")
        for frame,key,value,tangent in zip(after.frames,after.key_ids,after.values,after.tangents,strict=True):
            if frame in expected:
                if (key,value,tangent)!=expected[frame]:
                    raise MotionInputError("KEY_TOPOLOGY_MISMATCH","an existing authored key changed")
            else:
                addition=next(x for x in additions if x.frame==frame)
                if value!=addition.value or tangent!=addition.tangent or key in before.key_ids:
                    raise MotionInputError("KEY_TOPOLOGY_MISMATCH","new key value/tangent/identity differs")
        for frame,mode in zip(after.frames[:-1],after.segment_modes,strict=True):
            addition=next((x for x in additions if x.frame==frame),None)
            if addition is not None:
                expected_mode=addition.mode
            else:
                index=before.frames.index(frame)
                expected_mode=before.segment_modes[index] if index<len(before.segment_modes) else additions[-1].mode
            if mode!=expected_mode:
                raise MotionInputError("KEY_TOPOLOGY_MISMATCH","interpolation mode changed outside the exact delta")
    return {"status":"matched","key_layout_digest":digest,
            "completion_receipt_digest":result["completion_receipt_digest"],"added_keys":len(delta.additions)}
