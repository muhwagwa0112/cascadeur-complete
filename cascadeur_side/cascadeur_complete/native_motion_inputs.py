"""Read-only motion input discovery using the installed 2026.2 SDK viewers.

This reader deliberately returns a partial draft when the SDK observation does
not establish units, basis, physical FPS, semantic roles or rest transforms.
Skin inverse-bind assets can establish rest transforms for their exact ordered
joint mapping. Current-frame/default Transform values are never a bind pose.
"""
from __future__ import annotations

import hashlib
import json
import math


def _digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(",",":"),
                                     ensure_ascii=False,allow_nan=False).encode("utf-8")).hexdigest()


def _resolve_proto_root(topology,objects,selected_owner):
    """Resolve only the installed SDK's explicit proto constraint links.

    The topology is native-observed data, not a declaration of anatomical roles.
    Final-rig graph outputs and Root_T_Rotation constants are not substitutes.
    """
    evidence={"reader":"native_proto_root_links_v1","authority":"native_typed_topology",
              "status":"unobserved","declared":False,"reasons":[],"topology":topology}
    if selected_owner is None:
        evidence["reasons"]=["CHARACTER_OWNERSHIP_UNVERIFIED"]
        return None,evidence
    by_id={row["id"]:row for row in objects}
    relevant=[row for row in topology if selected_owner in row.get("related_ownership_candidates",[])]
    if not relevant:
        evidence["reasons"]=["PROTO_ROOT_TOPOLOGY_UNOBSERVED:final rig graph is not qualified by this reader"]
        return None,evidence
    if len(relevant)!=1:
        evidence["status"]="ambiguous"
        evidence["reasons"]=["PROTO_ROOT_TOPOLOGY_AMBIGUOUS:expected one selected-rig constraint"]
        return None,evidence
    row=relevant[0]
    if row.get("unobserved_reason"):
        evidence["reasons"]=["PROTO_ROOT_TOPOLOGY_INCOMPLETE:"+row["unobserved_reason"]]
        return None,evidence
    linked=(row.get("owner_id"),row.get("root_id"),row.get("rig_element_owner_id"),row.get("joint_owner_id"))
    if any(key not in by_id or by_id[key].get("ownership_candidates")!=[selected_owner] for key in linked):
        evidence["reasons"]=["PROTO_ROOT_OWNERSHIP_UNVERIFIED:constraint/root/TechnicalLinks/Joint must share one RigInfo owner"]
        return None,evidence
    root=by_id[row["root_id"]]
    transforms=[item for item in root.get("behaviors",[]) if item.get("name")=="Transform"]
    if len(transforms)!=1:
        evidence["reasons"]=["ROOT_ROTATION_UNAVAILABLE:expected one observed Transform"]
        return None,evidence
    channels={item["name"]:item for item in transforms[0]["properties"]}
    rotation_data={}
    for name in ("local_rotation","global_rotation"):
        item=channels.get(name,{})
        value=item.get("current_value")
        if (item.get("type")!="DataType" or not item.get("data_id") or item.get("unobserved_reason")
                or not isinstance(value,list) or len(value)!=4
                or any(type(x) not in (int,float) or not math.isfinite(x) for x in value)
                or sum(x*x for x in value)<1e-20):
            evidence["reasons"]=["ROOT_ROTATION_UNAVAILABLE:unobserved quaternion channel "+name]
            return None,evidence
        rotation_data[name]=item["data_id"]
    evidence.update(status="observed",root_object_id=root["id"],
        constraint_behaviour_id=row["behaviour_id"],rotation_data_ids=rotation_data)
    return root["id"],evidence


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
    if requested is not None and len(all_objects) == 1:
        from .native_independent_inputs import read_independent_inputs
        independent = read_independent_inputs(scene, arguments, requested)
        if independent is not None:
            return independent
    warnings=[];ownership={};rig_rows=[]

    def behaviour_reference(link):
        if link.is_null():return {"value":None}
        return {"value":rt._id_string(link),
                "referenced_owner_id":rt._id_string(bv.get_behaviour_owner(link)),
                "referenced_behaviour_name":str(bv.get_behaviour_name(link))}

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
    # Enumerate the complete typed proto-constraint inventory, including links
    # outside the selected scope, so competing/foreign links cannot be hidden.
    proto_constraints=list(bv.get_behaviours("ProtoRootConstraint"))
    if len(proto_constraints)>1024:
        raise ValueError("RESOURCE_BUDGET_EXCEEDED: native proto root inventory exceeds 1024 constraints")
    root_topology=[]
    for behaviour in sorted(proto_constraints,key=rt._id_string):
        row={"behaviour_id":rt._id_string(behaviour),
             "owner_id":rt._id_string(bv.get_behaviour_owner(behaviour))}
        linked=[row["owner_id"]]
        try:
            fields=set(map(str,bv.get_behaviour_property_names(behaviour)))
            if not {"root","rig_element"}<=fields:
                raise ValueError("missing ProtoRootConstraint.root/rig_element")
            if str(rt._read_member(bv.get_property_type(behaviour,"root"),"name"))!="ObjectType":
                raise ValueError("ProtoRootConstraint.root is not ObjectType")
            root=bv.get_behaviour_object(behaviour,"root")
            if root.is_null():raise ValueError("null ProtoRootConstraint.root")
            row["root_id"]=rt._id_string(root);linked.append(row["root_id"])
            if str(rt._read_member(bv.get_property_type(behaviour,"rig_element"),"name"))!="BehaviourType":
                raise ValueError("ProtoRootConstraint.rig_element is not BehaviourType")
            technical=bv.get_behaviour_reference(behaviour,"rig_element")
            ref=behaviour_reference(technical)
            row["rig_element_reference"]=ref
            if ref.get("referenced_owner_id"):linked.append(ref["referenced_owner_id"])
            if ref.get("referenced_behaviour_name")!="TechnicalLinks":
                raise ValueError("rig_element does not reference TechnicalLinks")
            row["rig_element_owner_id"]=ref["referenced_owner_id"]
            if ("joint" not in set(map(str,bv.get_behaviour_property_names(technical)))
                    or str(rt._read_member(bv.get_property_type(technical,"joint"),"name"))!="BehaviourType"):
                raise ValueError("TechnicalLinks.joint is not an observed BehaviourType")
            joint=behaviour_reference(bv.get_behaviour_reference(technical,"joint"))
            row["joint_reference"]=joint
            if joint.get("referenced_owner_id"):linked.append(joint["referenced_owner_id"])
            if joint.get("referenced_behaviour_name")!="Joint":
                raise ValueError("TechnicalLinks.joint does not reference Joint")
            row["joint_owner_id"]=joint["referenced_owner_id"]
        except (RuntimeError,ValueError,TypeError,AttributeError) as exc:
            row["unobserved_reason"]=type(exc).__name__+":"+str(exc)[:300]
        row["related_ownership_candidates"]=sorted({owner for key in linked for owner in ownership.get(key,[])})
        root_topology.append(row)
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
                        # MeshObject.linked_objects is indexed by inverse-bind
                        # matrices; sorting an SDK range destroys that mapping.
                        field["value"]=[rt._id_string(x) for x in bv.get_behaviour_objects_range(behaviour,prop)]
                    elif kind=="BehaviourType":
                        field.update(behaviour_reference(bv.get_behaviour_reference(behaviour,prop)))
                    elif kind=="BehaviourRangeType":
                        references=list(bv.get_behaviour_reference_range(behaviour,prop))
                        if len(references)>10000:
                            raise ValueError("RESOURCE_BUDGET_EXCEEDED: behaviour reference range exceeds 10000")
                        field["references"]=[behaviour_reference(link) for link in references]
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
    root_rotation_id,root_evidence=_resolve_proto_root(root_topology,objects,
        selected_owners[0] if len(selected_owners)==1 else None)
    if root_rotation_id is None:
        warnings.extend(root_evidence["reasons"])
    # Description values are native metadata, but no undocumented name is
    # treated as physical FPS/units or a canonical coordinate convention.
    descriptions={}
    for name in dv.get_description_names():
        text=str(name)
        try:descriptions[text]=str(dv.get_any_description_value_by_name(text))
        except (RuntimeError,ValueError,TypeError) as exc:descriptions[text]={"unobserved_reason":str(exc)[:300]}
    from .native_bind_rest import read_native_bind_rest
    bind_rest=read_native_bind_rest(scene,sorted(selected))
    bind_evidence_digest=_digest(bind_rest["raw_evidence"])
    for obj in objects:
        rest=bind_rest["rest_local_transforms"].get(obj["id"])
        if rest is not None:
            obj["rest_local_transform"]=rest
            obj["rest_local_transform_provenance"]={
                "reader":"native_mesh_inverse_bind_v1",
                "evidence_digest":bind_evidence_digest,
                "coordinate_space":bind_rest["coordinate_space"],"units":bind_rest["units"]}
    for reason in bind_rest["errors"]:
        warnings.append("NATIVE_BIND_REST_UNOBSERVED:"+str(reason)[:300])
    structure_objects=[]
    for obj in objects:
        behaviors=[]
        for behavior in obj["behaviors"]:
            properties=[{key:value for key,value in prop.items()
                         if key in ("name","type","data_id","setting_id","asset_id",
                                    "referenced_owner_id","referenced_behaviour_name","references")
                         or key=="value" and prop.get("type")=="BehaviourType"}
                        for prop in behavior["properties"]]
            behaviors.append({"id":behavior["id"],"name":behavior["name"],"properties":properties})
        structure_objects.append({"id":obj["id"],"parent_id":obj.get("parent_id"),
                                  "character_id":obj["character_id"],"behaviors":behaviors})
    # A sampled animated mesh-conversion value belongs to the source, not the
    # reusable rig structure. Native inverse-bind assets and ordered joint links
    # do change the structure's rest contract.
    bind_structure={"basic_parents":bind_rest["raw_evidence"].get("basic_parents",{}),
        "meshes":[{key:value for key,value in mesh.items() if key in (
            "mesh_object_id","behaviour_id","linked_object_ids","mesh_dependency_id",
            "inverse_bind_matrices","bind_shape_data_id")}
            for mesh in bind_rest["raw_evidence"].get("meshes",[])]}
    structure={"objects":structure_objects,"rig_membership":rig_rows,
               "bind_rest_evidence":bind_structure,"proto_root_topology":root_topology}
    source={"objects":source_rows,"layers":list(layers.values()),"descriptions":descriptions,
            "frame_range":list(frame_range),"current_frame":frame,"support_refs":arguments.get("support_refs",[]),
            "bind_rest_observation":bind_rest,"proto_root_topology":root_topology}
    values={"context":{"frames":list(range(first,last+1))},"objects":objects,
            "role_candidates":({"root_orientation":[root_rotation_id]} if root_rotation_id else {}),
            "root_rotation_id":root_rotation_id,"root_orientation_observation":root_evidence,
            "layers":list(layers.values()),"native_descriptions":descriptions,
            "native_bind_rest":bind_rest,
            "rig_metadata":rig_rows,"mesh_ids":[x["id"] for x in objects if any(b["name"]=="MeshObject" for b in x["behaviors"])],
            "name_candidates":[{"id":x["id"],"name":x["name"]} for x in objects],
            "source_coverage":"raw_native_properties_and_layer_keys_no_evaluation_refresh",
            "unobserved_fields":["physical_fps","metres_per_scene_unit","scene_to_solver_basis","rest_local_transforms",
                                 "joint_axes","joint_limits_rad","semantic_roles","root_rotation_role","support_evaluated_tracks"],
            "observation_warnings":sorted(set(warnings))}
    if objects and all("rest_local_transform" in obj for obj in objects):
        values["unobserved_fields"].remove("rest_local_transforms")
    if root_rotation_id is not None:
        values["unobserved_fields"].remove("root_rotation_role")
    build=installed_build()
    provenance={"objects":{"reader":"csc.model.ModelViewer/BehaviourViewer/DataViewer","build":build,
                            "ownership":"RigInfo object ranges; absent/overlap stays unresolved"},
                "layers":{"reader":"csc.layers.Viewer","build":build},
                "rest_local_transforms":{**bind_rest["provenance"],"build":build,
                    "status":bind_rest["status"],"unobserved":bind_rest["unobserved"]},
                "context":{"frames":"requested integer interval; physical metadata unobserved"},
                "role_candidates":{"status":"partial" if root_rotation_id else "unobserved",
                    "observed_roles":["root_orientation"] if root_rotation_id else [],
                    "reason":"only explicit typed proto root links are supported; anatomical roles remain unobserved"},
                "root_rotation_id":{**root_evidence,"build":build}}
    return {"values":values,"provenance":provenance,"source_fingerprint":_digest(source),
            "rig_structure_fingerprint":_digest(structure),"evidence_ref":"pending-native-registry:"+_digest(source)}


# Explicit alias for registries that use the entry-point name as their reader.
inspect_motion_inputs=read_motion_inputs
