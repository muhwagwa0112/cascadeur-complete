"""Read-only authored-key observations for the installed Cascadeur SDK.

Layer keys expose frame locators, not persistent GUIDs. DataViewer reads do not
refresh interpolation. A production model therefore also needs a private,
runtime-issued evaluated capture and an independently qualified finite model.
"""
from __future__ import annotations

import math


CONSTANT_MODEL="constant_position_independent_v1"
LINEAR_MODEL="linear_position_independent_v1"
STEP_MODEL="step_position_independent_v1"
PIECEWISE_MODEL="piecewise_linear_step_position_independent_v1"
FINITE_MODELS=(CONSTANT_MODEL,LINEAR_MODEL,STEP_MODEL,PIECEWISE_MODEL)


def _name(value):
    member=getattr(value,"name",None)
    return str(member() if callable(member) else member) if member is not None else str(value)


def read_key_layout(scene,arguments,*,capture_lookup=None):
    """Return observations compatible with host ``KeyLayoutObservation``.

    ``capture_lookup`` is injected by the native registry, never deserialized
    from request arguments. Without it the same useful authored observations
    are returned with an explicit unverified capture/model status.
    """
    import csc
    from . import runtime as rt
    from . import guarded_runtime as guards
    from .native_adapters import installed_build
    from .native_scene_reader import MAX_OBJECTS

    allowed={"ids","space","channel","frames","capture_digest","capture_object_ids","context"}
    if not isinstance(arguments,dict) or set(arguments)-allowed:
        raise ValueError("INVALID_POLICY: unknown native key-layout request fields")
    ids=arguments.get("ids",[]);frames=arguments.get("frames",[])
    capture_ids=arguments.get("capture_object_ids",ids)
    if (not isinstance(ids,list) or not ids or len(ids)>64 or any(not isinstance(x,str) or not x for x in ids)
            or len(set(ids))!=len(ids) or not isinstance(capture_ids,list)
            or any(not isinstance(x,str) or not x for x in capture_ids) or len(set(capture_ids))!=len(capture_ids)
            or not set(ids)<=set(capture_ids) or len(capture_ids)>128):
        raise ValueError("INVALID_POLICY: exact unique driver/capture IDs required within native read budget")
    if (not isinstance(frames,list) or not frames or len(frames)>256
            or any(type(x) is not int or x<0 for x in frames)
            or any(b<=a for a,b in zip(frames,frames[1:])) or len(frames)*len(capture_ids)>16384):
        raise ValueError("RESOURCE_BUDGET_EXCEEDED: native key-layout grid exceeds the bounded read domain")
    channel=arguments.get("channel","position");space=arguments.get("space","local")
    if channel not in ("position","rotation") or space not in ("local","global"):
        raise ValueError("INVALID_POLICY: position/rotation and local/global space required")
    capture_digest=arguments.get("capture_digest")
    if (not isinstance(capture_digest,str) or len(capture_digest)!=64
            or any(x not in "0123456789abcdef" for x in capture_digest)):
        raise ValueError("INVALID_POLICY: canonical capture digest reference required")
    domain=rt._domain_scene(scene)
    mv=domain.model_viewer();bv=mv.behaviour_viewer();dv=mv.data_viewer();lv=domain.layers_viewer()
    objects={rt._id_string(x):x for x in mv.get_objects()}
    if len(objects)>MAX_OBJECTS:
        raise ValueError("RESOURCE_BUDGET_EXCEEDED: native influence inspection exceeds full native scene object budget")
    if set(capture_ids)-set(objects):
        raise ValueError("INCOMPLETE_CAPTURE: requested driver/dependency IDs do not exist")
    frame_count=int(lv.frames_count())
    if frames[-1]>=frame_count:
        raise ValueError("INCOMPLETE_CAPTURE: requested frames exceed the actual native timeline")
    build=installed_build();reasons=[];controllers=[];object_scope=[]

    def value(data_id,frame,kind):
        native=dv.get_data(data_id)
        mode=_name(native.mode)
        raw=dv.get_data_value(data_id) if mode=="Static" else dv.get_data_value(data_id,frame)
        if kind=="rotation":
            result=rt._quaternion_list(raw)
            if result is None or len(result)!=4 or not all(math.isfinite(x) for x in result):
                raise ValueError("INCOMPLETE_CAPTURE: native rotation is not a finite observed quaternion")
            if abs(sum(x*x for x in result)-1)>1e-4:
                raise ValueError("INVALID_ROTATION: native quaternion has invalid norm")
        else:
            convert=getattr(raw,"tolist",None)
            result=convert() if callable(convert) else raw
            if isinstance(result,(list,tuple)) and len(result)==3:
                result=[float(x[0] if isinstance(x,(list,tuple)) and len(x)==1 else x) for x in result]
            if not isinstance(result,list) or len(result)!=3 or not all(math.isfinite(x) for x in result):
                raise ValueError("INCOMPLETE_CAPTURE: native position is not a finite observed vector")
        return result,mode

    # A finite independent-translation model rejects unknown scene behaviours
    # instead of guessing that their update dependencies cannot affect a driver.
    for text,obj in sorted(objects.items()):
        behaviours=[];parent=None;parent_observed=False
        for behaviour in sorted(bv.get_behaviours(obj),key=rt._id_string):
            name=str(bv.get_behaviour_name(behaviour));links=[]
            if name not in ("Basic","Node3d","Transform"):
                controllers.append({"object_id":text,"behaviour_id":rt._id_string(behaviour),"name":name})
            for prop in sorted(map(str,bv.get_behaviour_property_names(behaviour))):
                kind=_name(bv.get_property_type(behaviour,prop));entry={"property":prop,"type":kind}
                if kind=="ObjectType":
                    linked=bv.get_behaviour_object(behaviour,prop)
                    entry["id"]=None if linked.is_null() else rt._id_string(linked)
                    if name=="Basic" and prop=="parent":parent=entry["id"];parent_observed=True
                elif kind=="ObjectRangeType":
                    entry["ids"]=sorted(rt._id_string(x) for x in bv.get_behaviour_objects_range(behaviour,prop))
                elif kind=="DataType":
                    linked=bv.get_behaviour_data(behaviour,prop)
                    entry["id"]=None if linked.is_null() else rt._id_string(linked)
                    if not linked.is_null():entry["mode"]=_name(dv.get_data(linked).mode)
                elif kind=="SettingType":
                    linked=bv.get_behaviour_setting(behaviour,prop)
                    entry["id"]=None if linked.is_null() else rt._id_string(linked)
                    if not linked.is_null():entry["value"]=dv.get_setting_value(linked)
                elif kind in ("BehaviourType","BehaviourRangeType","AssetType","AssetRangeType","DataRangeType","SettingRangeType","StringType"):
                    # These are outside the independently qualified transform
                    # domain; presence is observed, dependency closure unknown.
                    entry["unobserved_dependency_reason"]="outside_independent_transform_domain"
                    controllers.append({"object_id":text,"behaviour_id":rt._id_string(behaviour),"property":prop,"type":kind})
                else:
                    entry["unobserved_dependency_reason"]="unsupported_property_type"
                    controllers.append({"object_id":text,"property":prop,"type":kind})
                links.append(entry)
            behaviours.append({"id":rt._id_string(behaviour),"name":name,"links":links})
        if not parent_observed or parent is not None:
            controllers.append({"object_id":text,"parent_id":parent,"parent_observed":parent_observed})
        object_scope.append({"id":text,"parent_id":parent,"behaviours":behaviours})
    if controllers:reasons.append("CONTROLLER_OR_PARENT_DEPENDENCY_UNQUALIFIED")
    blend=[]
    try:
        import csc.additive_layers
        manager=csc.additive_layers.get_manager(domain)
        count=int(manager.get_stacked_layers_count())
        if count<0:raise ValueError("negative stacked layer count")
        if count:
            blend.append({"stacked_layers_count":count,"current_layer_index":int(manager.get_current_layer_index()),
                          "unobserved":"SDK has no read-only enabled/weight getter"})
            reasons.append("ADDITIVE_LAYER_INFLUENCE_UNOBSERVED")
    except (ImportError,AttributeError,RuntimeError,TypeError,ValueError) as exc:
        blend.append({"unobserved_reason":type(exc).__name__+":"+str(exc)[:300]})
        reasons.append("ADDITIVE_LAYER_STATE_UNOBSERVED")

    def common(raw):
        return {"ik_fk":_name(rt._read_member(raw,"ik_fk")),"fixation":_name(rt._read_member(raw,"fixation"))}

    def label(raw):
        if raw==csc.layers.layer.Key.no_label_id():return None
        if raw is None or isinstance(raw,(str,int)):return raw
        return rt._id_string(raw)

    layers={};drivers=[];raw_samples=[];unresolved=[];candidate_models=[]
    channel_data={}
    for text in sorted(capture_ids):
        transform=bv.get_behaviour_by_name(objects[text],"Transform")
        if transform.is_null():
            channel_data[text]={};reasons.append("TRANSFORM_CHANNEL_UNOBSERVED");continue
        channel_data[text]={}
        for kind in ("position","rotation"):
            data_id=bv.get_behaviour_data(transform,space+"_"+kind)
            if not data_id.is_null():channel_data[text][kind]=data_id
    for frame in frames:
        for text in sorted(capture_ids):
            values={"frame":frame,"id":text,"position":None,"quaternion_wxyz":None}
            for kind,key in (("position","position"),("rotation","quaternion_wxyz")):
                data_id=channel_data[text].get(kind)
                if data_id is not None:values[key]=value(data_id,frame,kind)[0]
            raw_samples.append(values)
    raw_projection={"space":space,"frames":frames,"samples":raw_samples}
    samples_by_id={text:[x for x in raw_samples if x["id"]==text] for text in capture_ids}
    for text in sorted(ids):
        obj=objects[text];data_id=channel_data[text].get(channel)
        layer_id=lv.layer_id_by_obj_id_or_null(obj)
        if data_id is None or layer_id.is_null():
            unresolved.append({"id":text,"reason":"missing native channel or authored layer"})
            reasons.append("KEY_LAYOUT_INSUFFICIENT");continue
        layer_text=rt._id_string(layer_id);layer=lv.layer(layer_id)
        if layer_text not in layers:
            keys=sorted(map(int,layer.key_frame_indices()))
            sections=rt._read_member(layer,"sections")
            if len(keys)>2048 or len(sections)>4096:
                raise ValueError("RESOURCE_BUDGET_EXCEEDED: authored layer key/section count exceeds native read budget")
            section_rows=[]
            for frame,section in sorted(sections.items()):
                key=rt._read_member(section,"key");interval=rt._read_member(section,"interval")
                section_rows.append({"frame":int(frame),"is_key":bool(layer.is_key(int(frame))),
                    "interval_mode":_name(rt._read_member(interval,"interpolation")),
                    "interval_common":common(rt._read_member(interval,"common")),
                    "tangent":{"mode":_name(rt._read_member(key,"tangents")),
                               "left_weight_velocity":float(rt._read_member(key,"left_weight_velocity")),
                               "right_weight_velocity":float(rt._read_member(key,"right_weight_velocity"))},
                    "key_common":common(rt._read_member(key,"common")),"label":label(rt._read_member(key,"label"))})
            cycles=[]
            for cycle in csc.layers.CyclesViewer(layer).get_cycles_in_frames(0,frame_count-1):
                cycles.append({"first_active_frame":int(cycle.first_active_frame_index),
                    "last_active_frame":int(cycle.last_active_frame_index),
                    "left_inactive_frame":int(cycle.left_inactive_frame_index),
                    "right_inactive_frame":int(cycle.right_inactive_frame_index),
                    "left_frame":int(cycle.left_frame_index()),"right_frame":int(cycle.right_frame_index())})
            layers[layer_text]={"id":layer_text,"keys":keys,"sections":section_rows,
                "obj_ids":sorted(rt._id_string(x) for x in rt._read_member(layer,"obj_ids")),
                "locked":bool(rt._read_member(layer,"is_locked")),"visible":bool(rt._read_member(layer,"is_visible")),"cycles":cycles}
        observed=layers[layer_text];all_keys=observed["keys"]
        if not all_keys:
            unresolved.append({"id":text,"reason":"native layer has no authored keys"})
            reasons.append("KEY_LAYOUT_INSUFFICIENT");continue
        before=[x for x in all_keys if x<frames[0]];after=[x for x in all_keys if x>frames[-1]]
        keys=sorted(set([x for x in all_keys if frames[0]<=x<=frames[-1]]+
                        ([max(before)] if before else [])+([min(after)] if after else [])))
        if not keys:
            # One influence key is necessary even if every requested sample
            # lies on the same constant tail of the authored animation.
            keys=[all_keys[0] if frames[-1]<all_keys[0] else all_keys[-1]]
        by_frame={x["frame"]:x for x in observed["sections"]};driver_reasons=[];modes=[];tangents=[];boundaries=[]
        for frame in keys:
            if frame not in by_frame or not by_frame[frame]["is_key"]:
                driver_reasons.append("AUTHORED_KEY_SECTION_UNOBSERVED")
                tangents.append({"unobserved":"section missing"});continue
            row=by_frame[frame];tangents.append({**row["tangent"],"key_common":row["key_common"],"label":row["label"]})
            boundaries.append({"frame":frame,"key_id":layer_text+":"+str(frame),"key_id_kind":"layer_frame_locator",
                               "locked":observed["locked"],"event":row["label"] is not None,"label":row["label"]})
        for first,last in zip(keys,keys[1:]):
            mode=_name(rt._read_member(layer.interval(first),"interpolation"));modes.append(mode)
            if mode not in ("LINEAR","STEP"):driver_reasons.append("NONLINEAR_INTERPOLATION_EVALUATOR_UNQUALIFIED")
            affecting=[x for x in observed["sections"] if first<=x["frame"]<last]
            if any(x["interval_mode"]!=mode for x in affecting):driver_reasons.append("INTRA_SEGMENT_SECTION_CHANGE_UNQUALIFIED")
            if any(x["interval_common"]["fixation"]!="Free" for x in affecting):driver_reasons.append("FIXATION_INFLUENCE_UNQUALIFIED")
        if observed["locked"] or not observed["visible"]:driver_reasons.append("LAYER_NOT_EDITABLE")
        if observed["cycles"]:driver_reasons.append("CYCLE_MODEL_UNQUALIFIED")
        if channel!="position":driver_reasons.append("ROTATION_INTERPOLATION_MODEL_UNQUALIFIED")
        if keys[0]<frames[0] or keys[-1]>frames[-1]:driver_reasons.append("BOUNDARY_KEY_OUTSIDE_CANONICAL_CAPTURE")
        key_values=[];data_mode=None
        for frame in keys:
            sample,data_mode=value(data_id,frame,channel);key_values.append(sample)
        if len(keys)==1:model=CONSTANT_MODEL
        elif set(modes)=={"LINEAR"}:model=LINEAR_MODEL
        elif set(modes)=={"STEP"}:model=STEP_MODEL
        elif set(modes)<={"LINEAR","STEP"}:model=PIECEWISE_MODEL
        else:model=None
        # This current-projection check detects stale/nonlinear cached values.
        # It is explicitly not a fresh interpolation or perturbation proof.
        residual=0.
        if channel=="position" and model is not None:
            for sample in samples_by_id[text]:
                frame=sample["frame"];left=max(0,min(len(keys)-1,sum(key<=frame for key in keys)-1))
                if left==len(keys)-1 or frame<=keys[0] or modes[left]=="STEP":predicted=key_values[left]
                else:
                    alpha=(frame-keys[left])/(keys[left+1]-keys[left])
                    predicted=[a*(1-alpha)+b*alpha for a,b in zip(key_values[left],key_values[left+1])]
                residual=max(residual,math.sqrt(sum((a-b)**2 for a,b in zip(predicted,sample["position"]))))
            if residual>1e-5:driver_reasons.append("CACHED_SAMPLES_DISAGREE_WITH_AUTHORED_MODEL")
        if model is not None:candidate_models.append(model)
        reasons.extend(driver_reasons)
        drivers.append({"object_id":text,"channel":channel,"space":space,"layer_id":layer_text,
            "key_ids":[layer_text+":"+str(frame) for frame in keys],"key_id_kind":"layer_frame_locator",
            "frames":keys,"values":key_values,"segment_modes":modes,"tangents":tangents,"boundary_keys":boundaries,
            "influences":{"controllers":controllers,"blend":blend,"cycle":observed["cycles"]},
            "data_id":rt._id_string(data_id),"data_mode":data_mode,"layer_objects":observed["obj_ids"],
            "sections":observed["sections"],"native_model":model,"reason_codes":sorted(set(driver_reasons))})
    native_scope={"ids":sorted(ids),"capture_object_ids":sorted(capture_ids),"channel":channel,"space":space,
        "frames":frames,"frame_count":frame_count,"objects":object_scope,"layers":[layers[x] for x in sorted(layers)],
        "unresolved_drivers":unresolved,"candidate_models":sorted(set(candidate_models)),
        "cached_sample_check":{"method":"DataViewer.get_data_value; no interpolation refresh","units":"raw_scene_units"}}
    source_fingerprint=guards.digest({"scope":native_scope,"projection":raw_projection,"drivers":drivers})
    evaluator_fingerprint=guards.digest({"reader_contract":"native_key_layout_v1","native_build":build,
                                          "runtime_fingerprint":guards.LOADED_FINGERPRINT})
    binding={"status":"unverified","reason":"RUNTIME_ISSUED_MOTION_CAPTURE_UNAVAILABLE"};qualified=[]
    if callable(capture_lookup):
        record=capture_lookup(capture_digest)
        if isinstance(record,dict):
            canonical=record.get("canonical_batch")
            instance=guards.scene_instance(scene)
            if (isinstance(canonical,dict) and record.get("capture_digest")==capture_digest
                    and guards.digest(canonical)==capture_digest and canonical.get("context")==arguments.get("context")
                    and canonical.get("space")==space and canonical.get("object_ids")==capture_ids
                    and record.get("sample_projection")==raw_projection
                    and record.get("key_layout_source_fingerprint")==source_fingerprint
                    and record.get("native_build")==build and record.get("runtime_epoch")==guards.RUNTIME_EPOCH
                    and record.get("scene_instance_id")==instance["scene_instance_id"]
                    and record.get("evaluation_receipt_digest")):
                qualified=sorted(set(record.get("qualified_models",()))&set(FINITE_MODELS))
                binding={"status":"runtime_issued","capture_digest":capture_digest,
                    "evaluation_receipt_digest":record["evaluation_receipt_digest"],"source_fingerprint":source_fingerprint}
    if binding["status"]!="runtime_issued":reasons.append("RUNTIME_ISSUED_MOTION_CAPTURE_UNAVAILABLE")
    if set(candidate_models)-set(qualified):reasons.append("FINITE_INTERPOLATION_MODEL_NOT_QUALIFIED")
    reasons=sorted(set(reasons))
    return {"build_fingerprint":guards.digest({"native_build":build}),"evaluator_fingerprint":evaluator_fingerprint,
        "source_fingerprint":source_fingerprint,"capture_digest":capture_digest,"drivers":drivers,
        "evidence_ref":"pending-runtime-key-layout:"+source_fingerprint,
        "support_status":"supported" if not reasons else ("unsupported" if unresolved or controllers or blend else "unverified"),
        "reason_codes":reasons,"candidate_models":sorted(set(candidate_models)),"qualified_models":qualified,
        "native_source_scope":native_scope,"raw_sample_projection":raw_projection,"capture_binding":binding}
