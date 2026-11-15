"""Qualified existing-key position writes for a finite independent object.

This module never registers from caller evidence. Its explicit disposable probe
must exercise the same writer before immutable process-local proof is published.
Domain.modify performs observed native graph/interpolation work. A durable
explicit interpolation receipt is still issued only by its separate operation.
"""
from __future__ import annotations

import copy
import json
import math
import threading

from . import guarded_runtime as guards
from .native_scene_adapter import NativeSceneAdapter

_OPERATIONS = ("animation.transform_set", "animation.position_keys_set")
_WRITER_BYTES = None
_PROBE = None
_ALLOWED_DIAGNOSTICS = {"RUNTIME_ISSUED_MOTION_CAPTURE_UNAVAILABLE", "FINITE_INTERPOLATION_MODEL_NOT_QUALIFIED"}
_MISSING=object()
_FAILURE_CONTRACT="synchronous_returned_write_prefix_exact_projection_v1"


def _freeze(value):
    return json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False).encode()


def _scope_failure(before,expected,actual,*,operation,space,data_id,callbacks,active_scene):
    """Bound diagnostics without changing the exact projection postcondition."""
    changes=[]
    truncated=[False]
    def short(value):
        if value is _MISSING: return "<absent>"
        if isinstance(value,str): return value if len(value)<=48 else value[:45]+"..."
        if isinstance(value,list):
            return {"type":"list","length":len(value),
                    "head":[short(x) if not isinstance(x,(dict,list)) else type(x).__name__ for x in value[:3]]}
        if isinstance(value,dict):
            return {"type":"dict","keys":[str(key)[:32] for key in sorted(value)[:4]]}
        return value
    def child(value,key):
        if isinstance(value,dict): return value.get(key,_MISSING)
        if isinstance(value,list) and isinstance(key,int) and key<len(value): return value[key]
        return _MISSING
    def add(path,old,wanted,found):
        row={"path":"/"+"/".join(str(key).replace("~","~0").replace("/","~1") for key in path),
             "before":short(old),"expected":short(wanted),"actual":short(found)}
        if len(path)>=2 and path[0]=="data" and isinstance(path[1],int):
            item=child(actual.get("data",[]),path[1])
            if isinstance(item,dict): row["data_name"]=short(item.get("name"))
        changes.append(row)
    def walk(old,wanted,found,path):
        if wanted==found: return
        if len(changes)>=12:
            truncated[0]=True
            return
        if isinstance(wanted,dict) and isinstance(found,dict):
            for key in sorted(set(wanted)|set(found)):
                walk(child(old,key),child(wanted,key),child(found,key),path+[key])
                if truncated[0]: return
        elif isinstance(wanted,list) and isinstance(found,list) and len(wanted)==len(found):
            for key in range(len(wanted)):
                walk(child(old,key),wanted[key],found[key],path+[key])
                if truncated[0]: return
        else:
            add(path,old,wanted,found)
    walk(before,expected,actual,[])
    report={"operation":operation,"space":space,"target_data_id":data_id,
            "callback_complete":callbacks==["authored_existing_positions"],"active_scene":bool(active_scene),
            "changes":changes,"truncated":truncated[0]}
    prefix="POSTCONDITION_FAILED: native write changed values outside exact existing-key scope; "
    while True:
        message=prefix+json.dumps(report,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False)
        if len(message.encode("utf-8"))<=2048: return message
        report["truncated"]=True
        if report["changes"]:
            report["changes"].pop()
        else:
            # All static context fields above are bounded native identifiers.
            # This fallback also protects diagnostics for an unexpected SDK ID.
            report["target_data_id"]=str(report["target_data_id"])[:48]
            report["operation"]=str(report["operation"])[:64]
            report["space"]=str(report["space"])[:16]


def _model_proof():
    from .native_interpolation_qualification import qualification
    value = qualification()
    if value is None:
        raise ValueError("FINITE_MODEL_UNQUALIFIED: run explicit native interpolation qualification first")
    return value


def _position(value):
    import numpy as np
    if (not isinstance(value, list) or len(value) != 3
            or any(isinstance(x, bool) or not isinstance(x, (int,float)) or not math.isfinite(x) or abs(x)>10000 for x in value)):
        raise ValueError("INVALID_POLICY: bounded finite three-component position required")
    native = np.asarray(value,dtype=np.float32).reshape(3,1)
    if np.max(np.abs(native[:,0].astype(float)-np.asarray(value,dtype=float)))>1e-5:
        raise ValueError("POSITION_PRECISION_UNSUPPORTED: requested position exceeds native float32 error bound")
    return native


def _writes(operation, arguments, object_id, current_frame):
    if not isinstance(arguments,dict):
        raise ValueError("INVALID_POLICY: exact position arguments required")
    if operation == "animation.transform_set":
        if set(arguments)!={"ids","frame","space","position"} or arguments["ids"]!=[object_id]:
            raise ValueError("INVALID_WRITE_SCOPE: exact single-object position-only transform request required")
        if type(arguments["frame"]) is not int or arguments["frame"]!=current_frame:
            raise ValueError("INVALID_WRITE_SCOPE: transform_set writes the exact current frame only")
        values=[{"id":object_id,"frame":arguments["frame"],"position":arguments["position"]}]
    elif operation == "animation.position_keys_set":
        if set(arguments)!={"writes","space"}:
            raise ValueError("INVALID_POLICY: position_keys_set accepts only exact writes and space")
        values=arguments["writes"]
        if not isinstance(values,list) or not 1<=len(values)<=256:
            raise ValueError("RESOURCE_BUDGET_EXCEEDED: one to 256 existing-key writes required")
    else:
        raise ValueError("RIG_ADAPTER_UNVERIFIED: operation outside independent existing-key writer")
    if arguments["space"] not in ("local","global"):
        raise ValueError("INVALID_POLICY: explicit local/global position space required")
    seen=set()
    for row in values:
        if (not isinstance(row,dict) or set(row)!={"id","frame","position"} or row["id"]!=object_id
                or type(row["frame"]) is not int or row["frame"]<0 or row["frame"] in seen):
            raise ValueError("INVALID_WRITE_SCOPE: unique exact existing frames for the single object required")
        _position(row["position"])
        seen.add(row["frame"])
    return copy.deepcopy(values)


def _interpolated_positions(frames,values,modes,count):
    import numpy as np
    keys=np.asarray(values,dtype=np.float32)
    result=[]
    for frame in range(count):
        left=max(0,min(len(frames)-1,sum(key<=frame for key in frames)-1))
        if left==len(frames)-1 or frame<=frames[0] or modes[left]=="STEP":
            row=keys[left]
        else:
            alpha=np.float32((frame-frames[left])/(frames[left+1]-frames[left]))
            row=(np.float32(1)-alpha)*keys[left]+alpha*keys[left+1]
        result.append(np.asarray(row,dtype=np.float32).astype(float).tolist())
    return result


def _position_closure(projection,driver):
    """Require and model all four actually observed dependent data channels."""
    import numpy as np
    obj=projection["objects"][0]
    object_id=obj["id"]
    count=projection["frames"]
    data={row["id"]:row for row in projection["data"]}
    behaviours={row["name"]:{prop["name"]:prop for prop in row["properties"]} for row in obj["behaviours"]}
    def link(behaviour,name,modes=("Static","Animation")):
        prop=behaviours.get(behaviour,{}).get(name)
        row=data.get(prop.get("value")) if isinstance(prop,dict) and prop.get("kind")=="DataType" else None
        if (row is None or row["owner"]!=object_id or row["mode"] not in modes
                or len(row["values"])!=(count if row["mode"]=="Animation" else 1)):
            raise ValueError("INDEPENDENT_CLOSURE_UNVERIFIED: exact owned "+behaviour+"."+name+" data required")
        return row
    def vector(value):
        array=np.asarray(value,dtype=float)
        if array.shape not in ((3,),(3,1)) or not np.isfinite(array).all():
            raise ValueError("INDEPENDENT_CLOSURE_UNVERIFIED: native vector shape/value unavailable")
        return array.reshape(3)
    conditions={}
    for behaviour,name,expected,allowed in (
        ("Transform","local_rotation",[1.,0.,0.,0.],("Static","Animation")),
        ("Transform","global_rotation",[1.,0.,0.,0.],("Static","Animation")),
        ("Node3d","model_local_rotation",[1.,0.,0.,0.],("Static",)),
        ("Transform","local_scale",[1.,1.,1.],("Static","Animation")),
        ("Node3d","model_local_scale",[1.,1.,1.],("Static",)),
        ("Node3d","model_local_position",[0.,0.,0.],("Static",))):
        row=link(behaviour,name,allowed)
        shapes=[]
        for value in row["values"]:
            array=np.asarray(value,dtype=float)
            if len(expected)==3: array=vector(value)
            if array.shape!=(len(expected),) or not np.array_equal(array,np.asarray(expected)):
                raise ValueError("INDEPENDENT_CLOSURE_UNVERIFIED: identity rotation/unit scale/zero model position required")
            shapes.append(list(np.asarray(value).shape))
        conditions[behaviour+"."+name]={"mode":row["mode"],"shape":shapes[0]}
        if any(shape!=shapes[0] for shape in shapes):
            raise ValueError("INDEPENDENT_CLOSURE_UNVERIFIED: native constraint shape varies across frames")
    ssc=link("Node3d","ssc",("Static",))
    if type(ssc["values"][0]) is not bool:
        raise ValueError("INDEPENDENT_CLOSURE_UNVERIFIED: observed Static scalar boolean SSC required")
    conditions["Node3d.ssc"]={"mode":"Static","value":ssc["values"][0]}
    channels={"local_position":link("Transform","local_position",("Animation",)),
              "global_position":link("Transform","global_position",("Animation",)),
              "global_matrix":link("Node3d","global_matrix",("Animation",))}
    inverse=[row for row in projection["data"] if row["owner"]==object_id and row["name"]=="Inverse Matrix"]
    if (len(inverse)!=1 or inverse[0]["mode"]!="Animation" or inverse[0]["description"] is not None
            or len(inverse[0]["values"])!=count):
        raise ValueError("INDEPENDENT_CLOSURE_UNVERIFIED: unique owned animated Inverse Matrix with null description required")
    channels["inverse_matrix"]=inverse[0]
    if len({row["id"] for row in channels.values()})!=4:
        raise ValueError("INDEPENDENT_CLOSURE_UNVERIFIED: distinct four-channel native closure required")
    if driver["data_id"] not in (channels["local_position"]["id"],channels["global_position"]["id"]):
        raise ValueError("INDEPENDENT_CLOSURE_UNVERIFIED: requested driver is outside observed position closure")
    positions=[vector(value).tolist() for value in channels["local_position"]["values"]]
    key_values=[positions[frame] for frame in driver["frames"]]
    if positions!=_interpolated_positions(driver["frames"],key_values,driver["segment_modes"],count):
        raise ValueError("INDEPENDENT_CLOSURE_UNVERIFIED: baseline cached positions disagree with finite authored model")
    for frame,position in enumerate(positions):
        if not np.array_equal(vector(channels["global_position"]["values"][frame]),np.asarray(position)):
            raise ValueError("INDEPENDENT_CLOSURE_UNVERIFIED: baseline local/global positions differ")
        for name,sign in (("global_matrix",1),("inverse_matrix",-1)):
            actual=np.asarray(channels[name]["values"][frame],dtype=float)
            expected=np.eye(4,dtype=float)
            expected[:3,3]=sign*np.asarray(position)
            if actual.shape!=(4,4) or not np.array_equal(actual,expected):
                raise ValueError("INDEPENDENT_CLOSURE_UNVERIFIED: baseline matrix is not exact identity plus observed translation")
    for name,row in channels.items():
        shapes=[list(np.asarray(value).shape) for value in row["values"]]
        if any(shape!=shapes[0] for shape in shapes):
            raise ValueError("INDEPENDENT_CLOSURE_UNVERIFIED: native closure shape varies across frames")
        conditions[name]={"name":row["name"],"mode":row["mode"],"shape":shapes[0]}
    return {"data_ids":{name:row["id"] for name,row in channels.items()},"conditions":conditions}


def _expected_projection(before,driver,writes):
    import numpy as np
    closure=driver["position_closure"]
    data={row["id"]:row for row in before["data"]}
    positions=data[closure["data_ids"]["local_position"]]["values"]
    keys={frame:np.asarray(positions[frame],dtype=np.float32).reshape(3).tolist() for frame in driver["frames"]}
    for row in writes: keys[row["frame"]]=_position(row["position"])[:,0].tolist()
    evaluated=_interpolated_positions(driver["frames"],[keys[frame] for frame in driver["frames"]],
                                     driver["segment_modes"],before["frames"])
    expected=copy.deepcopy(before)
    target={row["id"]:row for row in expected["data"]}
    for name,identifier in closure["data_ids"].items():
        row=target[identifier]
        for frame,position in enumerate(evaluated):
            if name in ("local_position","global_position"):
                shape=np.asarray(row["values"][frame]).shape
                row["values"][frame]=np.asarray(position,dtype=float).reshape(shape).tolist()
            else:
                matrix=np.eye(4,dtype=float)
                matrix[:3,3]=np.asarray(position)*(1 if name=="global_matrix" else -1)
                row["values"][frame]=matrix.tolist()
    return expected


class NativeIndependentPositionAdapter(NativeSceneAdapter):
    file_bootstrap=False

    def __init__(self):
        if _WRITER_BYTES is None:
            raise ValueError("POSITION_WRITER_UNQUALIFIED: explicit disposable writer probe required")
        super().__init__(_WRITER_BYTES)
        self.qualified_capabilities={}
        self._assert_qualified()

    def _assert_qualified(self):
        guards.assert_loaded_package()
        model=_model_proof()
        if _PROBE is not None and _PROBE[0] is self:
            return model
        if self.evidence_bytes!=_WRITER_BYTES:
            raise ValueError("POSITION_WRITER_UNQUALIFIED: executor differs from private issued evidence")
        proof=json.loads(self.evidence_bytes)
        if (proof["runtime_epoch"]!=guards.RUNTIME_EPOCH or proof["runtime_fingerprint"]!=guards.LOADED_FINGERPRINT
                or proof["native_build"]!=self.observed_build() or proof["model_qualification_digest"]!=guards.digest(model)):
            raise ValueError("POSITION_WRITER_UNQUALIFIED: writer/native model evidence is stale")
        return model

    def _inspect(self,scene,operation,arguments):
        from . import runtime as rt
        from .native_interpolation_qualification import independent_projection_identity
        from .native_key_layout import read_key_layout
        model=self._assert_qualified()
        if rt._scene_view() is not scene:
            raise ValueError("SCENE_CHANGED: independent position source is not the active scene")
        if _PROBE is not None and _PROBE[0] is self and _PROBE[1] is not scene:
            raise ValueError("FIXTURE_SCOPE_UNAVAILABLE: unregistered probe cannot write another scene")
        projection=self.read_scene(scene)
        if len(projection["objects"])!=1 or not 1<=projection["frames"]<=256:
            raise ValueError("RIG_ADAPTER_UNVERIFIED: bounded single independent object required")
        object_id=projection["objects"][0]["id"]
        if not independent_projection_identity(projection,object_id):
            raise ValueError("RIG_ADAPTER_UNVERIFIED: actual closure differs from qualified independent Transform")
        domain=rt._domain_scene(scene)
        writes=_writes(operation,arguments,object_id,int(domain.get_current_frame(False)))
        # Native domain.modify also updates the finite dependent graph. Check
        # that complete baseline here; this is not a durable evaluation receipt.
        descriptor=read_key_layout(scene,{"ids":[object_id],"space":arguments["space"],"channel":"position",
            "frames":list(range(projection["frames"])),"capture_digest":"0"*64,
            "capture_object_ids":[object_id],"context":None})
        blockers=set(descriptor["reason_codes"])-_ALLOWED_DIAGNOSTICS
        if blockers or len(descriptor["drivers"])!=1:
            raise ValueError("INTERPOLATION_MODEL_UNVERIFIED: "+", ".join(sorted(blockers or {"DRIVER_SCOPE_UNOBSERVED"})))
        driver=descriptor["drivers"][0]
        if driver["native_model"] not in model["qualified_models"] or driver["data_mode"]!="Animation":
            raise ValueError("INTERPOLATION_MODEL_UNVERIFIED: actual driver is outside qualified finite models")
        if any(row["frame"] not in driver["frames"] for row in writes):
            raise ValueError("KEY_INSERTION_NOT_SUPPORTED: every write must target an existing authored key")
        if any(row.get("event") or row.get("locked") for row in driver["boundary_keys"]
               if row["frame"] in {write["frame"] for write in writes}):
            raise ValueError("INTENT_LOCK_VIOLATION: protected existing key cannot be rewritten")
        driver["position_closure"]=_position_closure(projection,driver)
        if _PROBE is None or _PROBE[0] is not self:
            proof=json.loads(self.evidence_bytes)
            if driver["position_closure"]["conditions"]!=proof["closure_conditions"]:
                raise ValueError("INDEPENDENT_CLOSURE_UNVERIFIED: actual constraints differ from privately observed writer domain")
        return projection,driver,writes

    def required_scope(self,scene,scope):
        from .native_adapters import _WORKSPACES
        operation,arguments=scope.get("operation_name"),scope.get("operation_arguments")
        projection,driver,writes=self._inspect(scene,operation,arguments)
        model=self._assert_qualified()
        probing=_PROBE is not None and _PROBE[0] is self
        required={"operation_name":operation,"operation_arguments":copy.deepcopy(arguments),
            "operation_arguments_digest":guards.digest(arguments),"adapter_id":"native-independent-existing-position-v1",
            "object_ids":[projection["objects"][0]["id"]],"layer_ids":[row["id"] for row in projection["layers"]],
            "frames":[0,projection["frames"]-1],"input_files":[],"write_frames":sorted(row["frame"] for row in writes),
            "channel_space":arguments["space"],"position_data_id":driver["data_id"],
            "declared_channel_space":arguments["space"],"requested_position_data_id":driver["data_id"],
            "authoritative_write_data_id":driver["position_closure"]["data_ids"]["local_position"],
            "position_conversion":"independent_identity_global_to_local" if arguments["space"]=="global" else "identity_local",
            "position_readback_contract":"native_float32_xyz_exact_v1",
            "position_closure":driver["position_closure"],
            "model_qualification_digest":guards.digest(model),
            "writer_qualification_digest":None if probing else guards.digest(json.loads(self.evidence_bytes))}
        manifest=_WORKSPACES.get(guards.scene_instance(scene)["scene_instance_id"])
        if manifest is not None: required["snapshot_manifest"]=copy.deepcopy(manifest)
        return required

    def capture(self,scene,scope):
        projection,_,_=self._inspect(scene,scope["operation_name"],scope["operation_arguments"])
        return {"coverage_complete":True,"authored_projection":projection,"sample_projection":projection}

    def _source(self,scene,source,operation,arguments):
        if _PROBE is None or _PROBE[0] is not self:
            return guards.assert_source(scene,source,operation_name=operation,arguments=arguments)
        # The disposable probe uses the real reader/executor before any route
        # is advertised. Its source is privately issued with this exact adapter
        # instead of temporarily registering an unqualified production route.
        if (not isinstance(source,dict) or guards._ISSUED_SOURCES.get(guards.digest(source))!=source
                or source["scope"].get("operation_name")!=operation
                or source["scope"].get("operation_arguments_digest")!=guards.digest(arguments)):
            raise ValueError("BINDING_UNAVAILABLE: exact privately issued probe source required")
        actual=guards._capture_with_adapter(scene,source["scope"],source["inputs_digest"],source["sample_digest"],
            source["binding"].get("selection_digest"),self)
        if actual!=source: raise ValueError("SCENE_CHANGED: disposable probe source differs")
        return actual

    def _observe_failed_write(self,scene,request,operation,arguments,before,driver,writes,identity,trace,error):
        """Attest an actual failure only after a bounded, returned native call.

        A setter that raised is in flight even if its immediate value looks
        plausible. Native exceptions, False replies, callback replay/yield and
        unexpected graph changes likewise provide no completion evidence.
        Successful qualification trials never manufacture failure evidence.
        """
        from . import runtime as rt
        reason="NATIVE_FAILURE_COMPLETION_UNBOUNDED"
        try:
            self._assert_qualified()
            count=len(trace["returned"])
            if (not request.get("request_id") or getattr(guards._LOCAL,"request",None) is not request
                    or (_PROBE is not None and _PROBE[0] is self)
                    or not trace["native_returned"] or not trace["native_succeeded"]
                    or trace["native_active"] or trace["unbounded_callback"]
                    or trace["callback_attempts"]!=1 or not trace["callback_entered"]
                    or not trace["callback_exited"] or trace["started"]!=list(range(count))
                    or trace["returned"]!=list(range(count)) or not 1<=count<=len(writes)):
                raise ValueError(reason)
            bounded_trace=copy.deepcopy(trace)
            if rt._scene_view() is not scene or dict(guards.scene_instance(scene))!=identity:
                raise ValueError("SCENE_CHANGED_DURING_NATIVE_FAILURE")
            expected=_expected_projection(before,driver,writes[:count])
            after=self.read_scene(scene)
            if after!=expected:
                raise ValueError("NATIVE_FAILURE_OUTSIDE_EXACT_COMPLETED_WRITE_PREFIX")
            # Issue from an independent complete read using the same public
            # source path as runtime's subsequent post-dispatch capture.
            original=request["source_binding"]
            post=guards.capture_source(scene,original["scope"],original["inputs_digest"])
            self._source(scene,post,operation,arguments)
            if (post["sample_digest"]!=guards.digest(after) or self.read_scene(scene)!=after
                    or rt._scene_view() is not scene or dict(guards.scene_instance(scene))!=identity):
                raise ValueError("NATIVE_FAILURE_POST_SOURCE_CHANGED")
            detail={"failure_contract":_FAILURE_CONTRACT,"request_digest":guards.digest(request),
                "requested_write_count":len(writes),"completed_write_count":count,
                "native_transaction":bounded_trace,"post_source_digest":guards.digest(post),
                "authored_projection_digest":guards.digest(after),
                "evaluation":"domain_modify_native_graph_observed",
                "durable_interpolation_receipt":"separate_explicit_operation_required"}
            if after==before:
                if trace!=bounded_trace:
                    raise ValueError("NATIVE_FAILURE_CALLBACK_BOUNDARY_CHANGED")
                return guards.observe_effect(operation,"no_effect",scene_before=identity,scene_after=identity,detail=detail)
            observation={"operation_name":operation,"completion":"completed",
                         "scene_before":identity,"scene_after":identity,"detail":detail}
            record={"schema_version":1,"contract":_FAILURE_CONTRACT,
                "runtime_fingerprint":guards.LOADED_FINGERPRINT,"runtime_epoch":guards.RUNTIME_EPOCH,
                "installed_build":self.observed_build(),"request_id":request["request_id"],
                "request_digest":guards.digest(request),"operation_name":operation,
                "original_source_digest":guards.digest(original),"post_source":post,
                "before_projection_digest":guards.digest(before),"after_projection_digest":guards.digest(after),
                "writer_evidence_digest":guards.digest(json.loads(self.evidence_bytes)),
                "native_transaction":bounded_trace,"effect_observation":observation,
                "failure_type":type(error).__name__}
            # Keep the trace reference as well as immutable evidence: a late
            # rejected callback invalidates eligibility rather than being
            # hidden by the already serialized observation.
            frozen=_freeze(record)
            attestation={"runtime_fingerprint":guards.LOADED_FINGERPRINT,
                "installed_build":record["installed_build"],"known_effect_classes":["scene"],
                "evidence_sha256":guards.digest(record),"request_digest":record["request_digest"],
                "post_source_digest":guards.digest(post),"contract":_FAILURE_CONTRACT}
            if trace!=bounded_trace:
                raise ValueError("NATIVE_FAILURE_CALLBACK_BOUNDARY_CHANGED")
            observed=guards.observe_effect(operation,"completed",scene_before=identity,scene_after=identity,detail=detail)
            self._failure_evidence_bytes=frozen
            self._failure_trace=trace
            self.verification["recovery_after_partial_write_observed"]=attestation
            return observed
        except Exception as observation_error:
            reason=str(observation_error).split(":",1)[0][:128]
        # Preserve the original executor error; this observation cannot turn
        # it into a success or an eligible recovery.
        self._failure_evidence_bytes=None
        self._failure_trace=None
        self.verification.pop("recovery_after_partial_write_observed",None)
        return guards.observe_effect(operation,"unknown",scene_before=identity,scene_after=None,
            detail={"failure_contract":_FAILURE_CONTRACT,"reason_code":reason,
                    "native_transaction":copy.deepcopy(trace)})

    def prepare_recovery_binding(self,scene,request,result):
        """Recheck private request-specific failure evidence before restoration."""
        from . import runtime as rt
        self._assert_qualified()
        frozen=getattr(self,"_failure_evidence_bytes",None)
        trace=getattr(self,"_failure_trace",None)
        if not isinstance(frozen,bytes) or not isinstance(trace,dict):
            raise ValueError("RECOVERY_FAILURE_ATTESTATION_UNAVAILABLE")
        record=json.loads(frozen)
        post=(result.get("result") or {}).get("post_source_binding")
        effects=guards.effect_observations()
        attestation=self.verification.get("recovery_after_partial_write_observed") or {}
        if (result.get("ok") is not False or result.get("outcome")!="failed_after_dispatch"
                or result.get("dispatched") is not True or result.get("write_phase") not in ("started","completed")
                or result.get("failure_kind")=="guard_rejected_before_first_write"
                or record["contract"]!=_FAILURE_CONTRACT or record["request_id"]!=request.get("request_id")
                or record["request_digest"]!=guards.digest(request)
                or record["runtime_epoch"]!=guards.RUNTIME_EPOCH
                or record["runtime_fingerprint"]!=guards.LOADED_FINGERPRINT
                or record["installed_build"]!=self.observed_build()
                or record["writer_evidence_digest"]!=guards.digest(json.loads(self.evidence_bytes))
                or record["original_source_digest"]!=guards.digest(request.get("source_binding"))
                or post!=record["post_source"] or trace!=record["native_transaction"]
                or attestation.get("evidence_sha256")!=guards.digest(record)
                or attestation.get("request_digest")!=record["request_digest"]
                or attestation.get("post_source_digest")!=guards.digest(post)
                or not effects or effects[-1]!=record["effect_observation"]
                or (result.get("result") or {}).get("native_effect_observations")!=effects
                or rt._scene_view() is not scene
                or dict(guards.scene_instance(scene))!=record["effect_observation"]["scene_after"]):
            raise ValueError("RECOVERY_FAILURE_ATTESTATION_DIFFERS")
        self._source(scene,post,record["operation_name"],request["operations"][0]["arguments"])
        if guards.digest(self.read_scene(scene))!=record["after_projection_digest"]:
            raise ValueError("RECOVERY_FAILURE_POST_SOURCE_CHANGED")
        return super().prepare_recovery_binding(scene,request,result)

    def execute(self,scene,arguments,request):
        import csc
        import numpy as np
        from . import runtime as rt
        from .handler_registry import transact
        self._failure_evidence_bytes=None
        self._failure_trace=None
        self.verification.pop("recovery_after_partial_write_observed",None)
        operations=request.get("operations")
        if not isinstance(operations,list) or len(operations)!=1 or operations[0].get("arguments")!=arguments:
            raise ValueError("INVALID_POLICY: one exact independent position operation required")
        operation=operations[0].get("name")
        self._source(scene,request.get("source_binding"),operation,arguments)
        before,driver,writes=self._inspect(scene,operation,arguments)
        identity=dict(guards.scene_instance(scene))
        # A parentless identity Transform has identical local/global physical
        # coordinates, but the SDK's global output cache is not authoritative.
        # The complete verified closure above permits this exact identity
        # conversion; all writes go to its actual local position input.
        requested_data_id=csc.model.DataId(driver["data_id"])
        authoritative_id=driver["position_closure"]["data_ids"]["local_position"]
        write_data_id=csc.model.DataId(authoritative_id)
        domain=rt._domain_scene(scene)
        expected=_expected_projection(before,driver,writes)
        encoded=[(row,_position(row["position"])) for row in writes]
        def guard():
            current=getattr(guards._LOCAL,"guard",None)
            if current is not None: current()
            self._source(scene,request.get("source_binding"),operation,arguments)
            if self.read_scene(scene)!=before:
                raise ValueError("SCENE_CHANGED: independent position source changed before write")
        callbacks=[]
        owner_thread=threading.get_ident()
        completion=[None]
        trace={"native_entered":False,"native_active":False,"native_returned":False,
            "native_succeeded":False,"callback_attempts":0,"callback_entered":False,
            "callback_exited":False,"callback_completed":False,"unbounded_callback":False,
            "started":[],"returned":[]}
        def modify(label,callback):
            trace["native_entered"]=True
            trace["native_active"]=True
            def observed_callback(*args):
                trace["callback_attempts"]+=1
                if (not trace["native_active"] or trace["callback_attempts"]!=1
                        or threading.get_ident()!=owner_thread):
                    trace["unbounded_callback"]=True
                    # Keep a retained completion observation truthful if the
                    # SDK attempts a late callback after returning. The
                    # expired callback never reaches the author or setters.
                    if completion[0] is not None:
                        completion[0]["completion"]="unknown"
                        completion[0]["detail"]["reason_code"]="NATIVE_CALLBACK_OUTSIDE_SYNCHRONOUS_PERMIT"
                    if getattr(self,"_failure_trace",None) is trace:
                        self._failure_evidence_bytes=None
                        self._failure_trace=None
                        self.verification.pop("recovery_after_partial_write_observed",None)
                    raise RuntimeError("NATIVE_COMPLETION_UNKNOWN: callback yielded, changed thread or replayed")
                try:
                    value=callback(*args)
                    trace["callback_completed"]=True
                    return value
                finally:
                    trace["callback_exited"]=True
            try:
                value=domain.modify(label,observed_callback)
                trace["native_returned"]=True
                trace["native_succeeded"]=value is True
                return value
            finally:
                trace["native_active"]=False
        def author(model,_update,_callback_scene):
            trace["callback_entered"]=True
            for index,(row,value) in enumerate(encoded):
                editor=model.data_editor()
                trace["started"].append(index)
                editor.set_data_value(write_data_id,row["frame"],value)
                trace["returned"].append(index)
            callbacks.append("authored_existing_positions")
        try:
            transact(modify,"Cascadeur Complete: author independent existing position keys",author,before_write=guard)
            if (not trace["native_succeeded"] or trace["unbounded_callback"]
                    or trace["callback_attempts"]!=1 or not trace["callback_completed"]):
                raise ValueError("NATIVE_COMPLETION_UNKNOWN: native transaction did not return synchronous success")
            after=self.read_scene(scene)
            if callbacks!=["authored_existing_positions"] or after!=expected or rt._scene_view() is not scene:
                raise ValueError(_scope_failure(before,expected,after,operation=operation,space=arguments["space"],
                    data_id=authoritative_id,callbacks=callbacks,active_scene=rt._scene_view() is scene))
            readback=[]
            worst=0.
            for row,value in encoded:
                actual=np.asarray(domain.data_viewer().get_data_value(requested_data_id,row["frame"]),dtype=float).reshape(-1)
                if actual.shape!=(3,) or not np.array_equal(actual,value[:,0].astype(float)):
                    raise ValueError("POSTCONDITION_FAILED: exact native float32 key readback differs")
                worst=max(worst,float(np.linalg.norm(actual-np.asarray(row["position"],dtype=float))))
                readback.append({"id":row["id"],"frame":row["frame"],"position":actual.tolist()})
        except Exception as exc:
            completion[0]=self._observe_failed_write(scene,request,operation,arguments,before,driver,writes,identity,trace,exc)
            raise
        completion[0]=guards.observe_effect(operation,"completed" if after!=before else "no_effect",scene_before=identity,
            scene_after=dict(guards.scene_instance(scene)),detail={"readback":readback,"evaluation":"domain_modify_native_graph_observed",
                "durable_interpolation_receipt":"separate_explicit_operation_required",
                "declared_channel_space":arguments["space"],"requested_position_data_id":driver["data_id"],
                "authoritative_write_data_id":authoritative_id,
                "native_transaction":copy.deepcopy(trace),
                "authored_projection_digest":guards.digest(after),"key_id_kind":"layer_frame_locator"})
        return {"native_completion":"observed","space":arguments["space"],"write_count":len(writes),
            "object_count":1,"frame_count":len(writes),"transforms":readback,"max_position_error":worst,
            "observed_postconditions":["transform_equals_requested" if operation=="animation.transform_set" else "position_keys_equal_request"],
            "evaluation":"domain_modify_native_graph_observed","durable_interpolation_receipt":"separate_explicit_operation_required",
            "native_transaction":copy.deepcopy(trace),
            "authored_projection_digest":guards.digest(after)},[]


def register_independent_position_writer():
    """Register only a writer already observed by this module in this epoch."""
    adapter=NativeIndependentPositionAdapter()
    for operation in _OPERATIONS: guards.register_adapter(operation,adapter)
    return {"adapter_id":"native-independent-existing-position-v1","operations":list(_OPERATIONS),
            "qualification_digest":guards.digest(json.loads(adapter.evidence_bytes))}


def qualify_independent_position_writer():
    """Explicit real writer probe; no fixture edits occur on ordinary import."""
    global _WRITER_BYTES,_PROBE
    import csc
    from . import runtime as rt
    from .native_fixture import create_disposable_scene,create_independent_transform,set_independent_keys,release_disposable_scene
    model=_model_proof()
    guards.assert_loaded_package()
    previous=csc.app.get_application().get_scene_manager().current_scene()
    if previous is not None and rt._domain_scene(previous).model_viewer().get_objects():
        raise ValueError("QUALIFICATION_REQUIRES_EMPTY_CURRENT_SCENE: writer probe does not inspect populated scenes")
    if _PROBE is not None:
        raise ValueError("POSITION_WRITER_PROBE_ACTIVE")
    saved_local=dict(vars(guards._LOCAL))
    scene=None
    trials=[]
    closure_conditions=None
    try:
        scene=create_disposable_scene()
        baseline=[(0,[0.,0.,0.]),(2,[2.,1.,0.]),(4,[0.,2.,1.])]
        fixture=create_independent_transform(scene,"MCPPositionWriterQualification",baseline,["LINEAR","LINEAR"])
        # This unregistered probe has no advertised operation capability.
        probe=object.__new__(NativeIndependentPositionAdapter)
        NativeSceneAdapter.__init__(probe,json.dumps({"operations":[]}).encode())
        probe.qualified_capabilities={}
        _PROBE=(probe,scene)
        for modes in (["LINEAR","LINEAR"],["STEP","STEP"],["LINEAR","STEP"],["STEP","LINEAR"]):
            for space in ("local","global"):
                for operation in _OPERATIONS:
                    fixture=set_independent_keys(scene,fixture["object_id"],baseline,modes)
                    domain=rt._domain_scene(scene)
                    domain.set_current_frame(2)
                    if operation=="animation.transform_set":
                        arguments={"ids":[fixture["object_id"]],"frame":2,"space":space,"position":[2.25,.75,.25]}
                    else:
                        arguments={"space":space,"writes":[{"id":fixture["object_id"],"frame":frame,
                            "position":[position[0]+.25,position[1]-.25,position[2]+.25]} for frame,position in baseline]}
                    scope=probe.required_scope(scene,{"operation_name":operation,"operation_arguments":arguments})
                    if closure_conditions is None:
                        closure_conditions=copy.deepcopy(scope["position_closure"]["conditions"])
                    elif scope["position_closure"]["conditions"]!=closure_conditions:
                        raise ValueError("INDEPENDENT_CLOSURE_UNVERIFIED: fixture constraints changed between writer probes")
                    source=guards._capture_with_adapter(scene,scope,guards.digest({"purpose":"independent_position_writer_probe"}),None,None,probe)
                    request={"operations":[{"name":operation,"arguments":arguments}],"source_binding":source}
                    guards.begin_request(request)
                    guards.set_write_guard(lambda: None)
                    result,_=probe.execute(scene,arguments,request)
                    if result.get("native_completion")!="observed" or guards.write_observation()[0]!="completed":
                        raise ValueError("POSITION_WRITER_COMPLETION_UNOBSERVED")
                    observed=probe.read_scene(scene)
                    ids=set(scope["position_closure"]["data_ids"].values())
                    trials.append({"operation":operation,"space":space,"segment_modes":modes,"arguments":arguments,
                        "source_digest":guards.digest(source),"result":result,"effects":guards.effect_observations(),
                        "observed_position_closure":[row for row in observed["data"] if row["id"] in ids],
                        "observed_full_projection_digest":guards.digest(observed)})
        evidence={"schema_version":1,"operations":list(_OPERATIONS),"native_build":probe.observed_build(),
            "runtime_epoch":guards.RUNTIME_EPOCH,"runtime_fingerprint":guards.LOADED_FINGERPRINT,
            "model_qualification_digest":guards.digest(model),"writer_contract":"existing_position_authoritative_local_graph_v4",
            "failure_observation_contract":_FAILURE_CONTRACT,"failure_trials":[],
            "closure_conditions":closure_conditions,"evaluation":"domain_modify_native_graph_observed",
            "durable_interpolation_receipt":"separate_explicit_operation_required","trials":trials}
    finally:
        _PROBE=None
        vars(guards._LOCAL).clear()
        vars(guards._LOCAL).update(saved_local)
        if scene is not None: release_disposable_scene(scene)
    _WRITER_BYTES=json.dumps(evidence,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False).encode()
    return {**register_independent_position_writer(),"trial_count":len(trials),
            "model_qualification_digest":guards.digest(model)}
