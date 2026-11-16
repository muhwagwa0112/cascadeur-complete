"""Installed-SDK adapter for a deliberately finite native transform domain.

No humanoid/controller/physics/mesh coverage is implied. Qualification creates
its own tab and exercises the same reader and executor used for real requests.
Evidence bytes are produced by that observation, never supplied on the wire.
"""
from __future__ import annotations

import hashlib
import json
import math
import sys
import uuid
from pathlib import Path

import csc

from . import guarded_runtime as guards

SUPPORTED_BUILD = "2026.2.3.0.16863"
_OBSERVATIONS = {}
_WORKSPACES = {}
_INITIALIZED = False
_ERROR = None


def installed_build():
    # Read the PE resource belonging to this running interpreter, not an
    # installation discovered elsewhere on PATH.
    import ctypes
    from ctypes import wintypes
    path = ctypes.create_unicode_buffer(32768)
    ctypes.windll.kernel32.GetModuleFileNameW(None, path, len(path))
    size = ctypes.windll.version.GetFileVersionInfoSizeW(path.value, None)
    data = ctypes.create_string_buffer(size)
    if not size or not ctypes.windll.version.GetFileVersionInfoW(path.value, 0, size, data):
        raise ValueError("Installed executable version unavailable")
    pointer, length = ctypes.c_void_p(), wintypes.UINT()
    if not ctypes.windll.version.VerQueryValueW(data, "\\VarFileInfo\\Translation", ctypes.byref(pointer), ctypes.byref(length)):
        raise ValueError("Installed executable version translation unavailable")
    translation = ctypes.cast(pointer, ctypes.POINTER(wintypes.WORD))
    block = "\\StringFileInfo\\%04x%04x\\ProductVersion" % (translation[0], translation[1])
    if not ctypes.windll.version.VerQueryValueW(data, block, ctypes.byref(pointer), ctypes.byref(length)):
        raise ValueError("Installed executable product version unavailable")
    return ctypes.wstring_at(pointer.value).strip()


def _value(value):
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if hasattr(value, "to_quaternion"):
        value = value.to_quaternion()
    if all(hasattr(value, name) for name in ("w", "x", "y", "z")):
        return [float(getattr(value, name)() if callable(getattr(value, name)) else getattr(value, name))
                for name in ("w", "x", "y", "z")]
    if hasattr(value, "tolist"):
        return value.tolist()
    if isinstance(value, (list, tuple)):
        return [_value(item) for item in value]
    raise ValueError("INCOMPLETE_CAPTURE: unsupported native value " + type(value).__name__)


def read_scene(scene):
    """Capture every data value, setting, link and key in the supported domain."""
    from . import runtime as rt
    domain = rt._domain_scene(scene)
    mv, bv, dv, lv = domain.model_viewer(), domain.behaviour_viewer(), domain.data_viewer(), domain.layers_viewer()
    objects = sorted(mv.get_objects(), key=str)
    if len(objects) != 1 or int(lv.frames_count()) > 256:
        raise ValueError("RIG_ADAPTER_UNVERIFIED: requires one independent Transform, at most 256 frames")
    layers = list(lv.all_layer_ids())
    if len(layers) != 1:
        raise ValueError("RIG_ADAPTER_UNVERIFIED: requires one animation layer")
    layer = lv.layer(layers[0])
    if layer.is_locked or not layer.is_visible or list(layer.key_frame_indices()) != [0]:
        raise ValueError("RIG_ADAPTER_UNVERIFIED: requires visible unlocked single existing key at frame zero")
    from .handlers.animation import _cycles, _sections
    ctx = {"read_member": rt._read_member, "id_string": rt._id_string,
           "json_safe": rt.json_safe, "csc": csc, "guid": rt._guid}
    cycles = _cycles(domain, layers, 0, int(lv.frames_count()) - 1, ctx)
    if cycles:
        raise ValueError("RIG_ADAPTER_UNVERIFIED: cycles are outside this adapter")
    rows = []
    for obj in objects:
        behaviours = sorted(bv.get_behaviours(obj), key=str)
        if sorted(bv.get_behaviour_name(b) for b in behaviours) != ["Basic", "Node3d", "Transform"]:
            raise ValueError("RIG_ADAPTER_UNVERIFIED: controller/rig/mesh behaviours unsupported")
        basic = bv.get_behaviour_by_name(obj, "Basic")
        if not bv.get_behaviour_object(basic, "parent").is_null():
            raise ValueError("RIG_ADAPTER_UNVERIFIED: parented transforms unsupported")
        links = []
        for beh in behaviours:
            for name in sorted(bv.get_behaviour_property_names(beh)):
                kind = bv.get_property_type(beh, name).name
                if kind == "DataType":
                    link = str(bv.get_behaviour_data(beh, name))
                elif kind == "SettingType":
                    link = str(bv.get_behaviour_setting(beh, name))
                elif kind == "ObjectType":
                    link = str(bv.get_behaviour_object(beh, name))
                else:
                    raise ValueError("INCOMPLETE_CAPTURE: unsupported property " + kind)
                links.append([str(beh), bv.get_behaviour_name(beh), name, kind, link])
        data = []
        for identifier in sorted(dv.get_all_data_id(obj), key=str):
            native = dv.get_data(identifier)
            animated = native.mode == csc.model.DataMode.Animation
            values = [_value(dv.get_data_value(identifier, frame)) for frame in range(int(lv.frames_count()))] if animated else [_value(dv.get_data_value(identifier))]
            data.append([str(identifier), dv.get_data_name(identifier), native.mode.name, values])
        settings = [[str(i), _value(dv.get_setting_value(i))] for i in sorted(dv.get_all_settings_id(obj), key=str)]
        rows.append({"id": str(obj), "name": mv.get_object_name(obj), "type": mv.get_object_type_name(obj),
                     "links": links, "data": data, "settings": settings,
                     "layer_id": str(lv.layer_id_by_obj_id(obj))})
    return {"objects": rows, "layers": rt.scene_state(scene)["layers"],
            "sections": _sections(domain, {}, ctx), "frame_count": int(lv.frames_count()),
            "cycles": cycles}


class TransformAdapter:
    def __init__(self, evidence):
        self.evidence_bytes = json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode()
        self.verification = {"runtime_fingerprint": guards.LOADED_FINGERPRINT,
            "installed_build": installed_build(), "identity_stable": True,
            "operations": evidence.get("operations", []),
            "dispatch_semantics": "synchronous_no_yield",
            "evidence_sha256": hashlib.sha256(self.evidence_bytes).hexdigest()}

    observed_build = staticmethod(installed_build)

    def required_scope(self, scene, scope):
        projection = read_scene(scene)
        operation = scope.get("operation_name")
        arguments = scope.get("operation_arguments")
        if not isinstance(arguments, dict) or operation not in {"animation.transform_set", "safety.bootstrap", "safety.checkpoint"}:
            raise ValueError("BINDING_UNAVAILABLE: exact native operation arguments required")
        if operation == "animation.transform_set":
            allowed = {"ids", "position", "frame", "space"}
            if set(arguments) - allowed or arguments.get("ids") != [projection["objects"][0]["id"]] or arguments.get("space", "local") != "local" or arguments.get("frame", 0) != 0:
                raise ValueError("RIG_ADAPTER_UNVERIFIED: only explicit local position at existing key zero")
            position = arguments.get("position")
            if not isinstance(position, list) or len(position) != 3 or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in position):
                raise ValueError("Invalid position")
        required = {"operation_name": operation, "operation_arguments": arguments,
            "operation_arguments_digest": guards.digest(arguments), "adapter_id": "independent-transform-key0-v1",
            "object_ids": [item["id"] for item in projection["objects"]],
            "layer_ids": [item["id"] for item in projection["layers"]], "frames": [0, projection["frame_count"] - 1]}
        workspace = _WORKSPACES.get(guards.scene_instance(scene)["scene_instance_id"])
        if workspace is not None:
            required["snapshot_manifest"] = workspace
        return required

    def capture(self, scene, scope):
        projection = read_scene(scene)
        return {"coverage_complete": True, "sample_projection": projection,
                "authored_projection": projection}

    def execute(self, scene, arguments, request):
        from . import runtime as rt
        name = request["operations"][0]["name"]
        before = dict(guards.scene_instance(scene))
        if name == "animation.transform_set":
            result = rt._run_operation_legacy(scene, {"name": name, "arguments": arguments}, request)
            observed = rt._read_transforms(rt._domain_scene(scene), arguments["ids"], 0, "local")
            if any(abs(a-b) > 1e-5 for a,b in zip(observed[0]["position"], arguments["position"])):
                raise ValueError("POSTCONDITION_FAILED: native position readback differs")
            guards.observe_effect(name, "completed", scene_before=before, scene_after=dict(guards.scene_instance(scene)), detail={"readback": observed})
            return {"transforms": observed, "native_completion": "observed"}, result[1]
        return checkpoint(scene, arguments, request, self)


def _save_observed(scene, path):
    from events import event_message_manager
    messages, capture_errors = [], []
    domain = scene.domain_scene()
    def message(emitter, full, level, simple):
        if emitter is scene or emitter is domain:
            if len(messages) >= 128 or len(str(full)) + len(str(simple)) > 8192:
                capture_errors.append("native_save_event_budget_exceeded")
                return
            messages.append({"full": str(full), "simple": str(simple), "level": str(getattr(level, "name", level))})
    subscription = event_message_manager.subscribe(message)
    try:
        scene.save(str(path))
    finally:
        event_message_manager.unsubscribe(subscription)
    completed = [row for row in messages if row["full"].strip() == "Saving is completed"]
    errors = [row for row in messages if row["level"] in {"2", "3", "Warning", "Error"}]
    if len(completed) != 1 or completed[0]["level"] not in {"1", "Info"} or errors or capture_errors:
        raise ValueError("NATIVE_COMPLETION_UNKNOWN: save completion event absent")
    with _locked_input(path) as manifest:
        pass
    if not manifest["length"]:
        raise ValueError("NATIVE_COMPLETION_UNKNOWN: empty checkpoint")
    return {"schema_version": 1, **manifest}


def checkpoint(scene, arguments, request, adapter):
    from . import runtime as rt
    def current_admission():
        from .incident_admission import assert_request_admission, assert_current_setup_admission
        assert_request_admission()
        if not request.get("request_id"):
            # Qualification's local sub-operation cannot escape the privately
            # admitted explicit setup step by manufacturing a wire request.
            assert_current_setup_admission()
    name = request["operations"][0]["name"]
    reader = getattr(adapter, "read_scene", read_scene)
    file_input = name == "safety.bootstrap" and arguments.get("input_kind", "active_scene") == "casc_file"
    if name == "safety.bootstrap" and arguments.get("input_kind", "active_scene") != "active_scene":
        if not file_input or not getattr(adapter, "file_bootstrap", False):
            raise ValueError("RIG_ADAPTER_UNVERIFIED: file bootstrap has no qualified loader")
    backup = Path(arguments["checkpoint_path"]).resolve()
    working = Path(arguments["working_path"]).resolve()
    if backup == working or any(p.exists() for p in (backup, working)):
        raise ValueError("Checkpoint requires two distinct new paths")
    root = (rt.runtime_root() / "snapshots").resolve()
    context = request.get("execution_context") or {}
    run_id = context.get("run_id")
    run_root = (rt.runtime_root() / "state" / "runs" / str(run_id)).resolve() if run_id else None
    if run_id:
        if str(uuid.UUID(run_id)) != run_id or run_root.parent != (rt.runtime_root() / "state" / "runs").resolve():
            raise ValueError("Invalid run workspace")
    if not all((p.is_relative_to(root) or (run_root is not None and p.parent in (run_root / "workspace", run_root / "checkpoints")))
               and p.suffix.lower() == ".casc" for p in (backup, working)):
        raise ValueError("Checkpoint paths must be owned .casc snapshot paths")
    original = reader(scene)
    expected_target = original
    original_path = str(scene.get_path_name())
    def original_unchanged():
        if reader(scene) != original or str(scene.get_path_name()) != original_path:
            raise ValueError("CHECKPOINT_ORIGINAL_SOURCE_CHANGED")
    before = dict(guards.scene_instance(scene))
    source = request.get("source_binding")
    manager = csc.app.get_application().get_scene_manager()
    target = scene
    load_observation = None
    if name == "safety.bootstrap":
        # Never save the original document just to obtain a clone. A persisted
        # source is usable only after native reload proves its complete content
        # equals the captured live source (unsaved edits therefore block).
        path = Path(arguments["input_path"]) if file_input else Path(original_path)
        if (not file_input and not original_path) or not path.is_file():
            raise ValueError("CHECKPOINT_UNAVAILABLE: save the initial document before bootstrap")
        guards.before_write()
        from .native_project_io import load_project_copy
        with _locked_input(path) as manifest:
            if file_input and (manifest["sha256"] != arguments.get("input_sha256")
                    or manifest["length"] != arguments.get("input_length")):
                raise ValueError("INPUT_DIGEST_MISMATCH: locked bootstrap bytes changed")
            # ProjectLoader only loads domain data and silently resets scene
            # FPS/units. Load a fresh owned file through the complete project
            # API, retaining source bytes and all preexisting tabs.
            target, load_observation = load_project_copy(path, working,
                expected_sha256=manifest["sha256"], expected_length=manifest["length"], source_guard=original_unchanged)
            expected_target = reader(target)
            if not file_input and expected_target != original:
                raise ValueError("CHECKPOINT_UNAVAILABLE: persisted source differs from live source")
        if not file_input:
            guards.link_clone(scene, target)
        manager.set_current_scene(target)
    else:
        if before["scene_instance_id"] not in _WORKSPACES:
            raise ValueError("CHECKPOINT_UNAVAILABLE: current scene is not an owned working instance")
        guards.before_write()
    current_admission()
    backup.parent.mkdir(parents=True, exist_ok=True)
    current_admission()
    working.parent.mkdir(parents=True, exist_ok=True)
    from .native_scene_adapter import NativeSceneAdapter
    serialization_anchor = None
    def phase_guard():
        current_admission()
        if target is not scene:
            original_unchanged()
    if isinstance(adapter, NativeSceneAdapter):
        from .native_serialization import pin_reference, compare_with_private_policy
        serialization_anchor = pin_reference(target, phase_guard=phase_guard, expected_projection=expected_target)
    current_admission()
    checkpoint_file = _save_observed(target, backup)
    checkpoint_observation = (compare_with_private_policy(target, serialization_anchor, phase="checkpoint_save", phase_guard=phase_guard)
                              if serialization_anchor is not None else None)
    current_admission()
    working_file = _save_observed(target, working)
    working_observation = (compare_with_private_policy(target, serialization_anchor, phase="working_save", phase_guard=phase_guard)
                           if serialization_anchor is not None else None)
    saved_projection = reader(target)
    if ((serialization_anchor is None and saved_projection != expected_target)
            or (working_observation is not None and saved_projection != working_observation.projection)
            or (target is not scene and (reader(scene) != original or str(scene.get_path_name()) != original_path))):
        raise ValueError("NATIVE_COMPLETION_UNKNOWN: clone or source changed during checkpoint")
    identity = dict(guards.scene_instance(target))
    snapshot = {"schema_version": 1, "snapshot_id": str(uuid.uuid4()), "path": str(backup),
        "sha256": checkpoint_file["sha256"], "bytes": checkpoint_file["length"],
        "working_path": str(working), "working_scene_instance_id": identity["scene_instance_id"],
        "document_lineage_id": identity["document_lineage_id"], "runtime_epoch": guards.RUNTIME_EPOCH,
        "adapter_fingerprint": guards.LOADED_FINGERPRINT, "native_completion": "observed",
        "authored_projection_digest": guards.digest(saved_projection)}
    if serialization_anchor is not None:
        fixed = {"reference_projection_digest": serialization_anchor.reference_projection_digest,
            "checkpoint_observed_projection_digest": guards.digest(checkpoint_observation.projection),
            "checkpoint_file": checkpoint_file,
            "serialization_policy_digest": checkpoint_observation.as_dict()["serialization_policy_digest"],
            "runtime_epoch": guards.RUNTIME_EPOCH, "adapter_fingerprint": guards.LOADED_FINGERPRINT}
        snapshot.update(schema_version=2, checkpoint_anchor_digest=guards.digest(fixed),
            reference_projection_digest=fixed["reference_projection_digest"],
            checkpoint_observed_projection_digest=fixed["checkpoint_observed_projection_digest"],
            working_projection_digest=guards.digest(saved_projection), working_file_sha256=working_file["sha256"],
            working_file_bytes=working_file["length"], serialization_policy_digest=fixed["serialization_policy_digest"],
            serialization_observation_digest=guards.digest(working_observation.as_dict()))
    _WORKSPACES[identity["scene_instance_id"]] = snapshot
    if isinstance(adapter, NativeSceneAdapter):
        from .native_checkpoint_restore import remember_checkpoint
        remember_checkpoint(target, snapshot, saved_projection, run_id=run_id,
            immutable_anchor=serialization_anchor, checkpoint_projection=checkpoint_observation.projection,
            checkpoint_observation=checkpoint_observation.as_dict(),
            serialization_observation=working_observation.as_dict())
    scope = adapter.required_scope(target, source["scope"])
    successor = guards._capture_with_adapter(target, scope, source["inputs_digest"], None, None, adapter)
    observation = {"schema_version": 1, "completion": "native_observed", "checkpoint": checkpoint_file,
        "project_load": load_observation,
        "working_file": working_file, "source_before": source, "source_after": successor,
        "parent_scene_instance_id": before["scene_instance_id"], "working_scene_instance_id": identity["scene_instance_id"],
        "document_lineage_id": identity["document_lineage_id"], "authored_digest": successor["binding"]["content_revision"],
        "sample_digest": successor["sample_digest"]}
    guards.finish_write()
    guards.observe_effect(name, "completed", scene_before=before, scene_after=identity, detail={"checkpoint": checkpoint_file})
    return {"native_completion": "observed", "source_binding": successor,
            "post_source_binding": successor, "checkpoint_observation": observation}, []


class _locked_input:
    """Deny write/delete sharing across hash + native path load on Windows."""
    def __init__(self, path):
        self.path = path

    def __enter__(self):
        import ctypes
        import msvcrt
        import os
        api = ctypes.windll.kernel32.CreateFileW
        api.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p,
                        ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p]
        api.restype = ctypes.c_void_p
        handle = api(str(self.path), 0x80000000, 1, None, 3, 0, None)
        if handle == ctypes.c_void_p(-1).value:
            raise OSError("Input file cannot be locked against replacement")
        self.stream = os.fdopen(msvcrt.open_osfhandle(handle, os.O_RDONLY), "rb")
        digest, count = hashlib.sha256(), 0
        try:
            while block := self.stream.read(1024 * 1024):
                count += len(block)
                if count > 512 * 1024 * 1024:
                    raise ValueError("RESOURCE_BUDGET_EXCEEDED: bootstrap file exceeds 512 MiB")
                digest.update(block)
        except Exception:
            self.stream.close()
            raise
        return {"path": str(self.path), "sha256": digest.hexdigest(), "length": count}

    def __exit__(self, *args):
        self.stream.close()


def qualify_disposable(*, include_scene_adapter=False):
    """Explicit native setup; retain the owned fixture and checkpoint tabs."""
    global _ERROR
    from .incident_admission import assert_setup_admission
    assert_setup_admission("setup.qualify_native_adapter")
    from .native_probe_retention import RetainedProbe, retained_probe_result
    if include_scene_adapter:
        raise ValueError("BROAD_SCENE_QUALIFICATION_UNSUPPORTED: requires a separately admitted lifecycle")
    guards.assert_loaded_package()
    ensure_installed()
    if installed_build() != SUPPORTED_BUILD:
        raise ValueError("Unsupported native SDK build")
    result = retained_probe_result("native_adapter")
    if result is not None:
        operations = ("animation.transform_set", "safety.bootstrap", "safety.checkpoint")
        registered = [guards._ADAPTERS.get(name) for name in operations]
        adapter = registered[0]
        if (type(adapter) is not TransformAdapter
                or any(value is not adapter for value in registered)
                or adapter.verification.get("evidence_sha256") != result.get("evidence_sha256")):
            raise ValueError("NATIVE_QUALIFICATION_REPLACED: inspect current qualified operations; no probe repeated")
        # Revalidate the same private registered instance with the existing
        # evidence/build/loaded-byte checks. Do not replace a broader adapter.
        for name in operations:
            guards.register_adapter(name, adapter)
    if result is None:
        import pycsc
        from . import runtime as rt
        retained = RetainedProbe("native_adapter")
        manager = retained.manager
        local_before = dict(vars(guards._LOCAL))
        qualification_error = None
        try:
            retained.before_new_tab()
            disposable = manager.create_application_scene()
            retained.track(disposable, "fixture")
            retained.before_effect()
            manager.set_current_scene(disposable)
            retained.before_effect()
            pycsc.wrap(disposable.domain_scene()).create_object("MCP adapter qualification")
            original = read_scene(disposable)
            object_id = original["objects"][0]["id"]
            request = {"operations": [{"name": "animation.transform_set", "arguments": {
                "ids": [object_id], "position": [1.25, 2.5, -0.75], "space": "local", "frame": 0}}]}
            guards.begin_request(request)
            guards.set_write_guard(lambda: read_scene(disposable) == original or (_ for _ in ()).throw(ValueError("SCENE_CHANGED")))
            adapter = TransformAdapter({})
            retained.before_effect()
            adapter.execute(disposable, request["operations"][0]["arguments"], request)
            after = read_scene(disposable)
            if original == after or guards.effect_observations()[0]["completion"] != "completed":
                raise ValueError("Native qualification did not observe changed data")
            observed_id = dict(guards.scene_instance(disposable))
            if observed_id != guards.scene_instance(disposable):
                raise ValueError("Scene identity is unstable")
            folder = retained.directory
            source_file = retained.save_fixture(disposable, "source.casc", read_scene)
            args = {"checkpoint_path": str(folder / "backup.casc"), "working_path": str(folder / "working.casc"),
                    "input_kind": "active_scene"}
            retained.plan_file("backup.casc")
            retained.plan_file("working.casc")
            scope = adapter.required_scope(disposable, {"operation_name": "safety.bootstrap", "operation_arguments": args})
            source = guards._capture_with_adapter(disposable, scope, guards.digest({"qualification": True}), None, None, adapter)
            bootstrap_request = {"operations": [{"name": "safety.bootstrap", "arguments": args}], "source_binding": source}
            guards.begin_request(bootstrap_request)
            guards.set_write_guard(lambda: read_scene(disposable) == after or (_ for _ in ()).throw(ValueError("SCENE_CHANGED")))
            retained.before_new_tab()
            checkpoint_result, _ = checkpoint(disposable, args, bootstrap_request, adapter)
            successor_scene = manager.current_scene()
            retained.track(successor_scene, "working")
            retained.record_file(checkpoint_result["checkpoint_observation"]["checkpoint"])
            retained.record_file(checkpoint_result["checkpoint_observation"]["working_file"])
            next_args = {"checkpoint_path": str(folder / "next-backup.casc"),
                         "working_path": str(folder / "next-working.casc")}
            retained.plan_file("next-backup.casc")
            retained.plan_file("next-working.casc")
            next_scope = adapter.required_scope(successor_scene, {"operation_name": "safety.checkpoint", "operation_arguments": next_args})
            next_source = guards._capture_with_adapter(successor_scene, next_scope, source["inputs_digest"], None, None, adapter)
            next_request = {"operations": [{"name": "safety.checkpoint", "arguments": next_args}], "source_binding": next_source}
            guards.begin_request(next_request)
            guards.set_write_guard(lambda: read_scene(successor_scene) == after or (_ for _ in ()).throw(ValueError("SCENE_CHANGED")))
            retained.before_effect()
            repeated_checkpoint, _ = checkpoint(successor_scene, next_args, next_request, adapter)
            retained.record_file(repeated_checkpoint["checkpoint_observation"]["checkpoint"])
            retained.record_file(repeated_checkpoint["checkpoint_observation"]["working_file"])
            evidence = {"build": installed_build(), "runtime_fingerprint": guards.LOADED_FINGERPRINT,
                "sdk": "csc.model.DataEditor.set_data_value/Scene.modify_update",
                "before": original, "after": after, "effect": guards.effect_observations(),
                "identity": observed_id, "source_file": source_file,
                "checkpoint": checkpoint_result, "successor_checkpoint": repeated_checkpoint,
                "operations": ["animation.transform_set", "safety.bootstrap", "safety.checkpoint"]}
        except Exception as error:
            qualification_error = error
            _ERROR = str(error)
            raise
        finally:
            try:
                retention = retained.finish(qualification_error)
            finally:
                vars(guards._LOCAL).clear()
                vars(guards._LOCAL).update(local_before)
        retained.before_effect()
        evidence["retention"] = retention
        adapter = TransformAdapter(evidence)
        evidence_path = folder / "qualification.json"
        with evidence_path.open("xb") as stream:
            import os
            stream.write(adapter.evidence_bytes)
            stream.flush()
            os.fsync(stream.fileno())
        adapter.verification["evidence_path"] = str(evidence_path)
        for name in ("animation.transform_set", "safety.bootstrap", "safety.checkpoint"):
            retained.before_effect()
            guards.register_adapter(name, adapter)
        _ERROR = None
        result = retained.complete({"adapter_id": "independent-transform-key0-v1", "installed_build": installed_build(),
            "evidence_sha256": adapter.verification["evidence_sha256"], "qualified_operations": evidence["operations"],
            "checkpoint_completion": "observed_native_save_and_clone_equivalence", "retention": retention,
            "scene_adapter": {"status": "not_requested", "reason": "Complete-scene qualification is an explicit separate setup action"}})
    return result


def ensure_installed():
    global _INITIALIZED, _ERROR
    if _INITIALIZED:
        return
    _INITIALIZED = True
    try:
        if installed_build() != SUPPORTED_BUILD:
            raise ValueError("No qualified SDK adapter for " + installed_build())
        # Qualification is explicit: it is never a hidden mutation at import.
        _ERROR = "Native qualification not run in this runtime epoch"
    except Exception as exc:
        _ERROR = str(exc)


def status():
    ensure_installed()
    from .native_unbaking import step_contract_status, STEPS
    from .native_geometry_capture import geometry_contract_status
    return {"installed_build": installed_build(), "adapter_id": "independent-transform-key0-v1", "qualification_error": _ERROR,
            "unbaking_steps": {step: step_contract_status(step) for step in STEPS},
            "geometry_capture": geometry_contract_status()}


def verify_observation(observation, digest, kind):
    if kind == "geometry_capture":
        from .native_geometry_capture import verify_geometry_capture
        return verify_geometry_capture(observation, digest)
    if digest != guards.digest(observation) or _OBSERVATIONS.get((kind, digest)) != observation:
        raise ValueError("RIG_ADAPTER_UNVERIFIED: observation not issued by this runtime")
    if kind == "motion_capture":
        from .native_motion_capture import verify_capture
        return verify_capture(observation, digest)
    if kind == "recipe_target":
        from .native_recipe_target import verify_recipe_target
        return verify_recipe_target(observation, digest)
    return {"key_layout_digest" if kind == "key_layout" else "observation_digest": digest}


def observe_motion_inputs(scene, arguments):
    from .native_motion_inputs import read_motion_inputs
    guards.assert_loaded_package()
    value = read_motion_inputs(scene, arguments)
    value["evidence_ref"] = "native-motion-input:" + guards.RUNTIME_EPOCH + ":" + value["source_fingerprint"]
    key = guards.digest(value)
    # A wire object can only authenticate bytes actually read in this epoch.
    _OBSERVATIONS[("motion_inputs", key)] = json.loads(json.dumps(value, allow_nan=False))
    return value


def observe_recipe_target(scene, arguments):
    from .native_recipe_target import observe_recipe_target as read_target
    value = read_target(scene, arguments)
    _OBSERVATIONS[("recipe_target", guards.digest(value))] = json.loads(json.dumps(value, allow_nan=False))
    return value


def observe_key_layout(scene, arguments):
    from .native_key_layout import read_key_layout
    from .native_motion_capture import lookup_capture
    guards.assert_loaded_package()
    value = read_key_layout(scene, arguments, capture_lookup=lambda key: lookup_capture(key, arguments))
    value["evidence_ref"] = "native-key-layout:" + guards.RUNTIME_EPOCH + ":" + value["source_fingerprint"]
    key = guards.digest(value)
    _OBSERVATIONS[("key_layout", key)] = json.loads(json.dumps(value, allow_nan=False))
    return value


def observe_motion_capture(scene, arguments):
    from .native_motion_capture import observe_motion_capture as read_capture
    guards.assert_loaded_package()
    value = read_capture(scene, arguments)
    batch, key = value["canonical_batch"], value["capture_digest"]
    if guards.digest(batch) != key:
        raise ValueError("INCOMPLETE_CAPTURE: native canonical digest differs")
    _OBSERVATIONS[("motion_capture", key)] = json.loads(json.dumps(batch, allow_nan=False))
    return value
