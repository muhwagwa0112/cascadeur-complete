"""Read-only motion input discovery using the installed 2026.2 SDK viewers.

This reader deliberately returns a partial draft when the SDK observation does
not establish units, basis, physical FPS, semantic roles or rest transforms.
Current-frame/default Transform values are never relabelled as a bind pose.
"""
from __future__ import annotations

import hashlib
import json


def _digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(",",":"),
                                     ensure_ascii=False,allow_nan=False).encode("utf-8")).hexdigest()


def read_motion_inputs(scene,arguments):
    from . import runtime as rt
    from .native_adapters import installed_build
    domain=rt._domain_scene(scene)
    if domain is None:
        raise ValueError("MISSING_ACTIVE_SCENE: no native scene to inspect")
    mv=domain.model_viewer();bv=mv.behaviour_viewer();dv=mv.data_viewer();lv=domain.layers_viewer()
    requested=arguments.get("character_ref")
    if isinstance(requested,dict):requested=requested.get("id")
    frame_range=arguments.get("frame_range")
    if (not isinstance(frame_range,(list,tuple)) or len(frame_range)!=2
            or any(type(x) is not int or x<0 for x in frame_range) or frame_range[1]<frame_range[0]
            or frame_range[1]-frame_range[0]>20000):
        raise ValueError("RESOURCE_BUDGET_EXCEEDED: exact frame interval of at most 20001 frames required")
    all_objects={rt._id_string(obj):obj for obj in mv.get_objects()}
    if len(all_objects)>10000:
        raise ValueError("RESOURCE_BUDGET_EXCEEDED: native input discovery exceeds 10000 objects")
    if requested is not None and requested not in all_objects:
        raise ValueError("INVALID_WRITE_SCOPE: character reference is not an observed stable object ID")
    warnings=[];ownership={};rig_rows=[]

    def read_value(data_id,frame):
        data=dv.get_data(data_id)
        mode=str(getattr(data.mode,"name",data.mode))
        value=dv.get_data_value(data_id) if mode=="Static" else dv.get_data_value(data_id,frame)
        # Keep the SDK's quaternion component order explicitly, never Euler.
        converted=rt._quaternion_list(value)
        if converted is None:
            converter=getattr(value,"tolist",None)
            converted=converter() if callable(converter) else rt.json_safe(value)
        # Reject nonfinite/unsupported values before producing a digest.
        if len(json.dumps(converted,allow_nan=False))>65536:
            raise ValueError("RESOURCE_BUDGET_EXCEEDED: native property exceeds 64 KiB")
        return converted,mode

    for behaviour in sorted(bv.get_behaviours("RigInfo"),key=rt._id_string):
        owner=rt._id_string(bv.get_behaviour_owner(behaviour))
        fields=set(map(str,bv.get_behaviour_property_names(behaviour)))
        members={owner}
        row={"owner_id":owner,"behaviour_id":rt._id_string(behaviour),"membership":{}}
        for name in ("rig_objects","related_joints","related_objects"):
            if name not in fields:continue
            linked=sorted(rt._id_string(x) for x in bv.get_behaviour_objects_range(behaviour,name))
            row["membership"][name]=linked;members.update(linked)
        for object_id in members:ownership.setdefault(object_id,[]).append(owner)
        for name in ("proto_json","qrt_json"):
            if name in fields:
                raw=str(bv.get_behaviour_string(behaviour,name))
                if len(raw.encode("utf-8"))>2*1024*1024:
                    warnings.append("RIG_METADATA_RESOURCE_BUDGET_EXCEEDED:"+owner+":"+name)
                    row[name+"_digest"]=_digest(raw)
                else:row[name]=raw
        rig_rows.append(row)
    selected_owners=ownership.get(requested,[]) if requested else []
    if len(selected_owners)==1:
        selected={key for key,owners in ownership.items() if selected_owners[0] in owners}
    elif requested is not None:
        selected={requested}
        warnings.append("CHARACTER_OWNERSHIP_UNVERIFIED:no unique RigInfo membership for selected object")
    else:
        selected=set(all_objects)
        warnings.append("CHARACTER_SELECTION_REQUIRED:select an observed RigInfo owner/member")
    if len(selected)>5000:
        raise ValueError("RESOURCE_BUDGET_EXCEEDED: selected native input scope exceeds 5000 objects")
    unknown=selected-set(all_objects)
    if unknown:
        warnings.append("DANGLING_RIG_MEMBERSHIP:"+",".join(sorted(unknown)))
        selected-=unknown
    first,last=frame_range
    frame=int(domain.get_current_frame(False))
    objects=[];layers={};source_rows=[];read_count=0
    for object_id in sorted(selected):
        obj=all_objects[object_id]
        row={"id":object_id,"name":str(mv.get_object_name(obj)),"type":str(mv.get_object_type_name(obj)),
             "character_id":ownership.get(object_id,[None])[0] if len(ownership.get(object_id,[]))==1 else None,
             "ownership_candidates":sorted(ownership.get(object_id,[])),"behaviors":[],"rotation_channel_observed":False}
        layer_id=lv.layer_id_by_obj_id_or_null(obj)
        key_frames=[]
        if not layer_id.is_null():
            layer_text=rt._id_string(layer_id);layer=lv.layer(layer_id)
            key_frames=list(map(int,layer.key_frame_indices()))
            header=lv.header(layer_id)
            layers[layer_text]={"id":layer_text,"name":str(rt._read_member(header,"name")),
                "key_frames":key_frames,"locked":bool(rt._read_member(layer,"is_locked")),
                "visible":bool(rt._read_member(layer,"is_visible"))}
            row["layer_id"]=layer_text
        inside=[x for x in key_frames if first<=x<=last]
        earlier=[x for x in key_frames if x<first];later=[x for x in key_frames if x>last]
        authored_grid=sorted(set(inside+([max(earlier)] if earlier else [])+([min(later)] if later else [])+[first,last]))
        if len(authored_grid)>2000:
            warnings.append("KEY_COVERAGE_RESOURCE_BUDGET_EXCEEDED:"+object_id)
            authored_grid=[]
        for behaviour in sorted(bv.get_behaviours(obj),key=rt._id_string):
            name=str(bv.get_behaviour_name(behaviour))
            entry={"id":rt._id_string(behaviour),"name":name,"properties":[]}
            for prop in sorted(map(str,bv.get_behaviour_property_names(behaviour))):
                kind=str(rt._read_member(bv.get_property_type(behaviour,prop),"name"))
                field={"name":prop,"type":kind}
                try:
                    if kind=="ObjectType":
                        link=bv.get_behaviour_object(behaviour,prop)
                        field["value"]=None if link.is_null() else rt._id_string(link)
                        if name=="Basic" and prop=="parent":row["parent_id"]=field["value"]
                    elif kind=="ObjectRangeType":
                        field["value"]=sorted(rt._id_string(x) for x in bv.get_behaviour_objects_range(behaviour,prop))
                    elif kind=="AssetType":
                        link=bv.get_behaviour_asset(behaviour,prop)
                        field["asset_id"]=None if link.is_null() else rt._id_string(link)
                    elif kind=="DataType":
                        link=bv.get_behaviour_data(behaviour,prop)
                        if not link.is_null():
                            field["data_id"]=rt._id_string(link)
                            field["current_value"],field["mode"]=read_value(link,frame)
                            if name=="Transform" and prop=="local_rotation":
                                row["rotation_channel_observed"]=isinstance(field["current_value"],list) and len(field["current_value"])==4
                            values=[]
                            if read_count+len(authored_grid)<=100000:
                                for key in authored_grid:
                                    value,_=read_value(link,key);values.append([key,value]);read_count+=1
                            else:warnings.append("SOURCE_COVERAGE_RESOURCE_BUDGET_EXCEEDED:"+object_id)
                            field["authored_or_cached_samples"]=values
                    elif kind=="SettingType":
                        link=bv.get_behaviour_setting(behaviour,prop)
                        if not link.is_null():
                            field["setting_id"]=rt._id_string(link)
                            field["value"]=rt.json_safe(dv.get_setting_value(link))
                    elif kind=="StringType":
                        raw=str(bv.get_behaviour_string(behaviour,prop))
                        field["value"]=raw if len(raw)<65536 else {"sha256":_digest(raw),"length":len(raw)}
                except (RuntimeError,ValueError,TypeError,AttributeError) as exc:
                    field["unobserved_reason"]=type(exc).__name__+":"+str(exc)[:300]
                    warnings.append("PROPERTY_UNOBSERVED:"+object_id+":"+name+":"+prop)
                entry["properties"].append(field)
            row["behaviors"].append(entry)
        objects.append(row);source_rows.append(row)
    # Description values are native metadata, but no undocumented name is
    # treated as physical FPS/units or a canonical coordinate convention.
    descriptions={}
    for name in dv.get_description_names():
        text=str(name)
        try:descriptions[text]=str(dv.get_any_description_value_by_name(text))
        except (RuntimeError,ValueError,TypeError) as exc:descriptions[text]={"unobserved_reason":str(exc)[:300]}
    structure_objects=[]
    for obj in objects:
        behaviors=[]
        for behavior in obj["behaviors"]:
            properties=[{key:value for key,value in prop.items()
                         if key in ("name","type","data_id","setting_id","asset_id")}
                        for prop in behavior["properties"]]
            behaviors.append({"id":behavior["id"],"name":behavior["name"],"properties":properties})
        structure_objects.append({"id":obj["id"],"parent_id":obj.get("parent_id"),
                                  "character_id":obj["character_id"],"behaviors":behaviors})
    structure={"objects":structure_objects,"rig_membership":rig_rows}
    source={"objects":source_rows,"layers":list(layers.values()),"descriptions":descriptions,
            "frame_range":list(frame_range),"current_frame":frame,"support_refs":arguments.get("support_refs",[])}
    values={"context":{"frames":list(range(first,last+1))},"objects":objects,"role_candidates":{},
            "root_rotation_id":None,"layers":list(layers.values()),"native_descriptions":descriptions,
            "rig_metadata":rig_rows,"mesh_ids":[x["id"] for x in objects if any(b["name"]=="MeshObject" for b in x["behaviors"])],
            "name_candidates":[{"id":x["id"],"name":x["name"]} for x in objects],
            "source_coverage":"raw_native_properties_and_layer_keys_no_evaluation_refresh",
            "unobserved_fields":["physical_fps","metres_per_scene_unit","scene_to_solver_basis","rest_local_transforms",
                                 "joint_axes","joint_limits_rad","semantic_roles","root_rotation_role","support_evaluated_tracks"],
            "observation_warnings":sorted(set(warnings))}
    build=installed_build()
    provenance={"objects":{"reader":"csc.model.ModelViewer/BehaviourViewer/DataViewer","build":build,
                            "ownership":"RigInfo object ranges; absent/overlap stays unresolved"},
                "layers":{"reader":"csc.layers.Viewer","build":build},
                "context":{"frames":"requested integer interval; physical metadata unobserved"},
                "role_candidates":{"status":"unobserved","reason":"names and raw QRT JSON are not semantic authority"},
                "root_rotation_id":{"status":"unobserved","reason":"rotation channel existence does not identify root orientation role"}}
    return {"values":values,"provenance":provenance,"source_fingerprint":_digest(source),
            "rig_structure_fingerprint":_digest(structure),"evidence_ref":"pending-native-registry:"+_digest(source)}


# Explicit alias for registries that use the entry-point name as their reader.
inspect_motion_inputs=read_motion_inputs
