"""Finite FBX export for the installed 2026.2 SDK; never self-registers.

``observe_export_call`` is an explicit setup helper for a caller-owned disposable
scene. Its completion observations are process-local. They establish synchronous
completion, not a complete rig reader or exported FBX conformance. The root
adapter must additionally bind actual artifact readback before production use.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from . import guarded_runtime as guards

SUPPORTED_BUILD = "2026.2.3.0.16863"
METHOD = "export_scene_selected_objects"
_COMPLETIONS = {}
_SUCCESS_TEXT = "Custom export: animation exported from 0 to 0 (only one frame)"
_OBSERVED_COMPLETION_RANGE = (0, 0)
_MAX_OBJECTS = 256
_MAX_FRAMES = 2001


def _source_installation():
    """Code root comes only from the bridge layout, never the mutable state root."""
    bridge = Path(__file__).resolve()
    root = bridge.parents[2]
    module = root / 'src' / 'cascadeur_complete' / 'native_export_readback.py'
    python = root / '.venv' / 'Scripts' / 'python.exe'
    if (bridge != root / 'cascadeur_side' / 'cascadeur_complete' / 'native_export.py'
            or not (root / 'pyproject.toml').is_file() or not python.is_file() or python.is_symlink()
            or not module.is_file() or module.is_symlink()):
        return None
    return root, python, module, hashlib.sha256(module.read_bytes()).hexdigest()


# Bind parser bytes when this bridge code is loaded. Subsequent host parser
# replacement requires a clean bridge import, as does a native package change.
_HOST_INSTALLATION = _source_installation()


class NativeExportError(ValueError):
    def __init__(self, code, detail, *, observation=None):
        self.code, self.observation = code, observation
        super().__init__(code + ": " + detail)


def _plain(value):
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return json.loads(json.dumps(value, allow_nan=False))


def profile_contract(profile):
    """Settings/semantics qualified by one fixture; object IDs/paths stay per request."""
    profile = _plain(profile)
    keys = ("schema_version", "take_name", "first_frame", "last_frame", "fps_num", "fps_den",
            "time_origin", "axes", "metres_per_export_unit", "bake", "include_mesh", "weights_normalization")
    result = {key: profile.get(key) for key in keys}
    root = profile.get("root_motion") or {}
    result["root_motion"] = {key: root.get(key) for key in ("mode", "translation_axes", "preserve_yaw")}
    result["sdk_method"] = METHOD
    result["sdk_settings"] = {"mode": "Binary", "bake_animation": True, "apply_euler_filter": False,
                              "up_axis": (profile.get("axes") or {}).get("up_axis")}
    return result


def _request_arguments(arguments, request, profile, *, _completed_output=False):
    arguments, request, profile = _plain(arguments), _plain(request), _plain(profile)
    allowed = {"path", "export_profile_digest", "export_profile", "max_output_bytes"}
    if set(arguments) - allowed or not {"path", "export_profile_digest", "max_output_bytes"} <= set(arguments):
        raise NativeExportError("NATIVE_EXPORT_ARGUMENTS_UNSUPPORTED", "Exact path, profile digest and output budget required")
    if arguments["export_profile_digest"] != guards.digest(profile):
        raise NativeExportError("EXPORT_PROFILE_MISMATCH", "Request names different profile bytes")
    if "export_profile" in arguments and guards.digest(arguments["export_profile"]) != guards.digest(profile):
        raise NativeExportError("EXPORT_PROFILE_MISMATCH", "Embedded export profile differs")
    if request.get("operations") != [{"name": "io.export_fbx", "arguments": arguments}]:
        raise NativeExportError("EXPORT_REQUEST_MISMATCH", "One exact export operation is required")
    context = request.get("execution_context") or {}
    if (not request.get("request_id") or any(not isinstance(context.get(key), str) or not context[key]
                                            for key in ("run_id", "step_id", "attempt_id"))
            or type(context.get("lease_epoch")) is not int or context["lease_epoch"] < 1):
        raise NativeExportError("EXPORT_REQUEST_MISMATCH", "Recipe run/step/attempt/lease identities are required")
    maximum = arguments["max_output_bytes"]
    if type(maximum) is not int or not 0 < maximum <= 2 * 1024**3:
        raise NativeExportError("RESOURCE_BUDGET_EXCEEDED", "Output byte budget must be within 2 GiB")
    path = Path(arguments["path"])
    if (not path.is_absolute() or path.suffix.lower() != ".fbx" or not path.parent.is_dir()
            or (path.exists() and not _completed_output) or path.is_symlink()):
        raise NativeExportError("EXPORT_PATH_UNAVAILABLE", "A new absolute .fbx path in an existing owned directory is required")
    ancestor = path.parent
    while ancestor != ancestor.parent:
        if ancestor.is_symlink() or getattr(ancestor.stat(follow_symlinks=False), 'st_file_attributes', 0) & 0x400:
            raise NativeExportError("EXPORT_PATH_UNAVAILABLE", "Export path has a symbolic-link ancestor")
        ancestor = ancestor.parent
    first, last = profile.get("first_frame"), profile.get("last_frame")
    if (type(first) is not int or type(last) is not int or first != 0 or last < first or last >= _MAX_FRAMES):
        raise NativeExportError("NATIVE_EXPORT_RANGE_UNSUPPORTED", "Finite route exports the entire interval starting at zero")
    if (profile.get("include_mesh") is not False or profile.get("mesh_refs") or profile.get("allowed_helper_nodes")
            or profile.get("bake") != "dense" or profile.get("time_origin") not in ("zero", "preserve")
            or (profile.get("root_motion") or {}).get("mode") != "preserve_world"):
        raise NativeExportError("NATIVE_EXPORT_PROFILE_UNSUPPORTED", "Finite route requires dense selected objects, preserved root and no mesh/helpers")
    for key in ("fps_num", "fps_den"):
        if type(profile.get(key)) is not int or profile[key] <= 0:
            raise NativeExportError("NATIVE_EXPORT_FPS_UNSUPPORTED", "Positive rational FPS required")
    if not 0 < profile["fps_num"] / profile["fps_den"] <= 1000:
        raise NativeExportError("NATIVE_EXPORT_FPS_UNSUPPORTED", "Finite FPS budget exceeded")
    axis = (profile.get("axes") or {}).get("up_axis")
    if type(axis) is not int or axis not in (0, 1, 2) or profile["axes"].get("up_sign") != 1:
        raise NativeExportError("NATIVE_EXPORT_AXES_UNSUPPORTED", "SDK settings expose only a positive up axis")
    mapping = profile.get("skeleton_map")
    if not isinstance(mapping, list) or not 0 < len(mapping) <= _MAX_OBJECTS:
        raise NativeExportError("NATIVE_EXPORT_SCOPE_UNSUPPORTED", "Explicit skeleton of at most 256 objects required")
    ids = [row.get("source_id") for row in mapping]
    paths = [row.get("node_path") for row in mapping]
    if (any(not isinstance(value, str) or not value for value in (*ids, *paths))
            or len(set(ids)) != len(ids) or len(set(paths)) != len(paths)):
        raise NativeExportError("NATIVE_EXPORT_SCOPE_UNSUPPORTED", "Stable unique source IDs and node paths are required")
    return arguments, request, profile


def inspect_export(scene, arguments, request, profile, *, _completed_output=False):
    """Read the exact selection/export flags; never change selection or settings."""
    arguments, request, profile = _request_arguments(arguments, request, profile, _completed_output=_completed_output)
    from . import runtime as rt
    from .native_adapters import installed_build
    guards.assert_loaded_package()
    if installed_build() != SUPPORTED_BUILD:
        raise NativeExportError("UNSUPPORTED_VERSION", "Native FBX helper is specific to " + SUPPORTED_BUILD)
    domain = rt._domain_scene(scene)
    viewer = domain.model_viewer()
    behaviours, data = viewer.behaviour_viewer(), viewer.data_viewer()
    native = {rt._id_string(obj): obj for obj in viewer.get_objects()}
    if len(native) > 10000:
        raise NativeExportError("RESOURCE_BUDGET_EXCEEDED", "Scene object closure exceeds 10000")
    selected = sorted(rt._id_string(obj) for obj in domain.selector().selected().ids)
    mapping = {row["source_id"]: row for row in profile["skeleton_map"]}
    if set(selected) != set(mapping) or not set(mapping) <= set(native):
        raise NativeExportError("EXPORT_SELECTION_MISMATCH", "Current selection must equal the exact profile object closure")
    count = int(domain.layers_viewer().frames_count())
    if count != profile["last_frame"] + 1:
        raise NativeExportError("NATIVE_EXPORT_RANGE_UNSUPPORTED", "Profile must cover the whole observed native interval")
    parents = {}
    for key, obj in native.items():
        basic = behaviours.get_behaviour_by_name(obj, "Basic")
        if basic.is_null():
            if key in mapping:
                raise NativeExportError("EXPORT_PARENT_UNVERIFIED", "Selected object has no Basic parent property")
            continue
        parent = behaviours.get_behaviour_object(basic, "parent")
        parents[key] = None if parent.is_null() else rt._id_string(parent)
    rows = []
    for key in selected:
        obj = native[key]
        names = set(str(behaviours.get_behaviour_name(behaviour)) for behaviour in behaviours.get_behaviours(obj))
        if any("mesh" in name.lower() for name in names):
            raise NativeExportError("NATIVE_EXPORT_MESH_UNSUPPORTED", "Selected mesh behaviour is outside this route")
        parent = parents[key]
        if parent is not None and parent not in mapping:
            raise NativeExportError("EXPORT_PARENT_UNVERIFIED", "An exported parent lies outside the selected scope")
        name = str(viewer.get_object_name(obj))
        if "/" in name or "\\" in name:
            raise NativeExportError("EXPORT_PATH_MAPPING_UNSUPPORTED", "Object names containing path separators are ambiguous")
        expected_path = (mapping[parent]["node_path"] + "/" if parent is not None else "") + name
        expected_parent = mapping[parent]["node_path"] if parent is not None else None
        if mapping[key]["node_path"] != expected_path or mapping[key].get("parent_path") != expected_parent:
            raise NativeExportError("EXPORT_PARENT_UNVERIFIED", "Observed names/parent hierarchy differs from profile paths")
        export = behaviours.get_behaviour_by_name(obj, "FbxExport")
        if export.is_null():
            raise NativeExportError("NATIVE_EXPORT_FLAGS_UNVERIFIED", "Selected object lacks FbxExport behaviour")
        fields = set(map(str, behaviours.get_behaviour_property_names(export)))
        flags = {}
        for field in ("is_exported", "export_translate_animation", "export_rotate_animation", "export_scale_animation"):
            if field not in fields:
                raise NativeExportError("NATIVE_EXPORT_FLAGS_UNVERIFIED", "Missing native export flag " + field)
            identifier = behaviours.get_behaviour_data(export, field)
            if identifier.is_null() or str(getattr(data.get_data(identifier).mode, "name", "")) != "Static":
                raise NativeExportError("NATIVE_EXPORT_FLAGS_UNVERIFIED", "Export flags must be observed static data")
            value = data.get_data_value(identifier)
            if type(value) is not bool:
                raise NativeExportError("NATIVE_EXPORT_FLAGS_UNVERIFIED", "Export flag is not a native bool")
            flags[field] = value
        if not flags["is_exported"]:
            raise NativeExportError("NATIVE_EXPORT_FLAGS_UNVERIFIED", "Selected object is disabled for FBX export")
        for channel in profile.get('required_channels', []):
            flag = {'Lcl Translation':'export_translate_animation', 'Lcl Rotation':'export_rotate_animation',
                    'Lcl Scaling':'export_scale_animation'}.get(channel.get('property'))
            if channel.get('node_path') == expected_path and channel.get('animated') is True and (flag is None or not flags[flag]):
                raise NativeExportError('NATIVE_EXPORT_FLAGS_UNVERIFIED', 'A required animated channel is disabled natively')
        rows.append({"source_id": key, "node_path": expected_path, "parent_id": parent,
                     "behaviours": sorted(names), "flags": flags})
    # Reject implicit unselected descendants without guessing how the exporter
    # traverses controls, joints or behaviours outside the explicit scope.
    if any(key not in mapping and parent in mapping for key, parent in parents.items()):
        raise NativeExportError("EXPORT_DESCENDANT_CLOSURE_UNVERIFIED", "An unselected child exists under the export scope")
    handler = domain.get_event_log_or_null()
    if handler is None:
        raise NativeExportError("NATIVE_EXPORT_COMPLETION_UNAVAILABLE", "Native event log handler is absent")
    import csc
    if csc.app.get_application().is_export_available() is not True:
        raise NativeExportError("NATIVE_EXPORT_LICENSE_UNAVAILABLE", "Installed application reports export unavailable")
    return {"schema_version": 1, "installed_build": SUPPORTED_BUILD, "runtime_epoch": guards.RUNTIME_EPOCH,
            "runtime_fingerprint": guards.LOADED_FINGERPRINT, "scene": dict(guards.scene_instance(scene)),
            "method": METHOD, "selected_ids": selected, "frame_count": count, "objects": rows,
            "profile_digest": guards.digest(profile), "profile_contract_digest": guards.digest(profile_contract(profile)),
            "request_id": request["request_id"], "execution_context": request["execution_context"],
            "operation_digest": guards.digest(request["operations"]),
            "native_readback_unavailable": ["loader_settings_getter", "front_axis", "coordinate_axis", "export_unit"],
            "artifact_readback_required": True}


class _LockedArtifact:
    """Hash the completed output while denying native writers/replacement."""
    def __init__(self, path, maximum):
        self.path, self.maximum = path, maximum

    def __enter__(self):
        import ctypes
        import msvcrt
        api = ctypes.windll.kernel32.CreateFileW
        api.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p,
                        ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p]
        api.restype = ctypes.c_void_p
        handle = api(str(self.path), 0x80000000, 1, None, 3, 0, None)
        if handle == ctypes.c_void_p(-1).value:
            raise NativeExportError("NATIVE_COMPLETION_UNKNOWN", "Completed artifact is still open for writing or cannot be locked")
        self.stream = os.fdopen(msvcrt.open_osfhandle(handle, os.O_RDONLY), "rb")
        before = os.fstat(self.stream.fileno())
        count, hasher = 0, hashlib.sha256()
        try:
            while block := self.stream.read(1024 * 1024):
                count += len(block)
                if count > self.maximum:
                    raise NativeExportError("RESOURCE_BUDGET_EXCEEDED", "Native export exceeded the exact output budget")
                hasher.update(block)
            after = os.fstat(self.stream.fileno())
            if count == 0 or count != before.st_size or not os.path.samestat(before, after) or after.st_size != count:
                raise NativeExportError("NATIVE_COMPLETION_UNKNOWN", "Completed artifact changed while locked")
            return {"path": str(self.path), "sha256": hasher.hexdigest(), "bytes": count}
        except Exception:
            self.stream.close()
            raise

    def __exit__(self, *args):
        self.stream.close()


def _selected_call(scene, path, maximum, fps, up_axis, *, expected_range, progress=None):
    """The sole SDK dispatch implementation, shared with disposable setup."""
    from . import runtime as rt
    import csc
    from events import event_message_manager
    if tuple(expected_range) != _OBSERVED_COMPLETION_RANGE:
        raise NativeExportError('NATIVE_EXPORT_RANGE_COMPLETION_UNQUALIFIED',
            'Only the observed selected-export completion for native frames 0..0 is qualified; whole-timeline export remains unsupported')
    domain = rt._domain_scene(scene)
    if progress:
        progress.mark('fbx_loader_constructor')
    loader = csc.fbx.FbxLoader(fps, domain.get_event_log_or_null(), scene)
    if progress:
        progress.mark('fbx_loader_constructor', 'complete')
    if not callable(getattr(loader, METHOD, None)):
        raise NativeExportError("NATIVE_EXPORT_METHOD_UNAVAILABLE", "Installed loader lacks the explicit selected-object method")
    settings = csc.fbx.FbxSettings()
    settings.mode = csc.fbx.FbxSettingsMode.Binary
    settings.up_axis = (csc.fbx.FbxSettingsAxis.X, csc.fbx.FbxSettingsAxis.Y, csc.fbx.FbxSettingsAxis.Z)[up_axis]
    settings.bake_animation = True
    settings.apply_euler_filter = False
    applied = {"mode": str(settings.mode.name), "up_axis": int(settings.up_axis.value),
               "bake_animation": bool(settings.bake_animation), "apply_euler_filter": bool(settings.apply_euler_filter),
               "constructor_fps": fps}
    messages, active, capture_errors = [], [False], []

    def message(emitter, full, level, simple):
        if not active[0] or (emitter is not scene and emitter is not domain):
            return
        if len(messages) >= 128:
            if not capture_errors:
                capture_errors.append('native_event_budget_exceeded')
            return
        full, simple = str(full), str(simple)
        if len(full) + len(simple) > 8192:
            if not capture_errors:
                capture_errors.append('native_event_text_budget_exceeded')
            return
        raw_level = getattr(level, 'value', level)
        level_name = {0: 'None', 1: 'Info', 2: 'Warning', 3: 'Error', 4: 'Success'}.get(raw_level, 'Unknown')
        messages.append({"full": full, "simple": simple, "level": level_name,
                         "raw_level": raw_level, "during_call": True})

    subscription = event_message_manager.subscribe(message)
    try:
        guards.before_write()
        if progress:
            progress.mark('fbx_set_settings')
        loader.set_settings(settings)
        if progress:
            progress.mark('fbx_set_settings', 'complete')
            progress.mark('fbx_export_selected_objects')
        active[0] = True
        value = getattr(loader, METHOD)(str(path).replace("\\", "/"))
        active[0] = False
        if progress:
            progress.mark('fbx_export_selected_objects', 'complete')
    finally:
        active[0] = False
        event_message_manager.unsubscribe(subscription)
    success = [row for row in messages if row["level"] == "Success"
               and _SUCCESS_TEXT in (row["full"].strip(), row["simple"].strip())]
    errors = [row for row in messages if row["level"] in ("Error", "Warning")]
    if len(success) != 1 or errors or capture_errors:
        raise NativeExportError("NATIVE_COMPLETION_UNKNOWN", "Exactly one same-scene synchronous native success and no warnings/errors required",
                                observation={"messages": messages, "return_value": rt.json_safe(value)})
    # The same operation's actual output is checked independently of completion.
    if progress:
        progress.mark('fbx_artifact_lock_and_hash')
    with _LockedArtifact(Path(path), maximum) as artifact:
        if progress:
            progress.mark('fbx_artifact_lock_and_hash', 'complete')
            progress.mark('fbx_get_takes')
        takes = list(map(str, loader.get_takes(str(path).replace("\\", "/"))))
        if progress:
            progress.mark('fbx_get_takes', 'complete')
    return artifact, takes, applied, messages


def observe_export_call(scene, arguments, request, profile, *, _progress=None):
    """Execute once with synchronous native completion; never grants a route."""
    before = inspect_export(scene, arguments, request, profile)
    arguments, request, profile = _request_arguments(arguments, request, profile)
    artifact, takes, applied, messages = _selected_call(scene, arguments['path'], arguments['max_output_bytes'],
        profile['fps_num'] / profile['fps_den'], profile['axes']['up_axis'],
        expected_range=(profile['first_frame'], profile['last_frame']), progress=_progress)
    if takes != [profile['take_name']]:
        raise NativeExportError('EXPORT_TAKE_READBACK_MISMATCH', 'Native output take differs: ' + repr(takes))
    after = inspect_export(scene, arguments, request, profile, _completed_output=True)
    for key in ("selected_ids", "frame_count", "objects", "scene"):
        if after[key] != before[key]:
            raise NativeExportError("NATIVE_COMPLETION_UNKNOWN", "Export changed observed scene/selection closure")
    observation = {"schema_version": 1, "native_completion": "observed", "installed_build": SUPPORTED_BUILD,
        "runtime_epoch": guards.RUNTIME_EPOCH, "runtime_fingerprint": guards.LOADED_FINGERPRINT,
        "method": METHOD, "request_id": request["request_id"], "execution_context": request["execution_context"],
        "operation_digest": guards.digest(request["operations"]), "profile_contract_digest": before["profile_contract_digest"],
        "profile_digest": guards.digest(profile), "artifact": artifact, "take_readback": takes,
        "sdk_settings_object_readback": applied, "scope_before": before, "scope_after_digest": guards.digest(after["objects"]),
        "completion_messages": messages, "dispatch_semantics": "synchronous_no_yield",
        "artifact_settings_readback_required": True}
    digest = guards.digest(observation)
    _COMPLETIONS[digest] = json.loads(json.dumps(observation))
    protected = {getattr(adapter, 'verification', {}).get('export_completion_observation_digest')
                 for adapter in guards._ADAPTERS.values()}
    for old in list(_COMPLETIONS):
        if len(_COMPLETIONS) <= 128:
            break
        if old != digest and old not in protected:
            del _COMPLETIONS[old]
    guards.finish_write()
    guards.observe_effect("io.export_fbx", "completed", scene_before=before["scene"], scene_after=after["scene"],
                          detail={"artifact": artifact, "completion_observation_digest": digest})
    return {"native_completion": "observed", "export_profile_digest": guards.digest(profile),
            "raw_path": artifact["path"], "artifact_sha256": artifact["sha256"], "artifact_bytes": artifact["bytes"],
            "settings": applied, "take_readback": takes, "selection_closure": before["objects"],
            "exported_closure": "requires_bounded_artifact_validation", "settings_readback": "requires_bounded_artifact_validation",
            "completion_observation_digest": digest, "completion_observation": observation}, []


def execute_export(scene, arguments, request, profile, *, adapter):
    """Production helper used only by the root's qualified coupled adapter."""
    registered = guards._ADAPTERS.get("io.export_fbx")
    proof = getattr(adapter, "verification", {})
    observation_digest = proof.get("export_completion_observation_digest")
    observed = _COMPLETIONS.get(observation_digest)
    evidence = getattr(adapter, "evidence_bytes", None)
    readback = getattr(adapter, "export_settings_readback", None)
    if (registered is not adapter or not isinstance(evidence, bytes)
            or hashlib.sha256(evidence).hexdigest() != proof.get("evidence_sha256")
            or not observed or observed["runtime_epoch"] != guards.RUNTIME_EPOCH
            or observed["runtime_fingerprint"] != guards.LOADED_FINGERPRINT
            or observed["profile_contract_digest"] != guards.digest(profile_contract(profile))
            or not isinstance(readback, dict) or readback.get("status") != "pass"
            or readback.get("artifact_sha256") != observed["artifact"]["sha256"]
            or readback.get("profile_contract_digest") != observed["profile_contract_digest"]
            or guards.digest(readback) != proof.get("export_settings_readback_digest")):
        raise NativeExportError("NATIVE_EXPORT_ADAPTER_UNVERIFIED", "Installed completion and exact artifact settings have not been qualified by the root adapter")
    material = json.loads(evidence)
    if (not isinstance(material, dict) or material.get('native_export_observation') != observed
            or material.get('export_settings_readback') != readback
            or readback.get('completion_observation_digest') != observation_digest):
        raise NativeExportError('NATIVE_EXPORT_ADAPTER_UNVERIFIED', 'Adapter evidence does not contain the actual completion/readback pair')
    _assert_stage(arguments, request, profile)
    guards.assert_loaded_package()
    guards.assert_source(scene, request.get("source_binding"), operation_name="io.export_fbx", arguments=arguments)
    return observe_export_call(scene, arguments, request, profile)


def _assert_stage(arguments, request, profile):
    arguments, request, profile = _request_arguments(arguments, request, profile)
    path = Path(arguments['path'])
    if path.name != 'raw.fbx':
        raise NativeExportError('EXPORT_STAGE_MISMATCH', 'Production export must target its staged raw.fbx')
    records = {}
    for name in ('stage.json', 'stage-dispatch.json'):
        record = path.parent / name
        if record.is_symlink() or not record.is_file() or record.stat().st_size > 4 * 1024**2:
            raise NativeExportError('EXPORT_STAGE_MISMATCH', 'Bounded immutable stage dispatch records required')
        records[name] = json.loads(record.read_text(encoding='utf-8'))
    stage, dispatch = records['stage.json'], records['stage-dispatch.json']
    context = request['execution_context']
    if (stage.get('raw_path') != str(path) or stage.get('profile_digest') != guards.digest(profile)
            or any(stage.get(key) != context[key] for key in ('run_id', 'step_id'))
            or dispatch.get('request_id') != request['request_id'] or dispatch.get('raw_path') != str(path)
            or dispatch.get('operation_digest') != guards.digest(request['operations'])
            or dispatch.get('arguments') != arguments or dispatch.get('source_binding') != request.get('source_binding')
            or any(dispatch.get(key) != context[key] for key in ('run_id', 'step_id', 'attempt_id', 'lease_epoch'))):
        raise NativeExportError('EXPORT_STAGE_MISMATCH', 'Stage belongs to different request/profile/source arguments')


def completion_observation(digest):
    """Return only an actual observation issued in this running SDK epoch."""
    value = _COMPLETIONS.get(digest)
    if value is None:
        raise NativeExportError("NATIVE_EXPORT_COMPLETION_UNVERIFIED", "Observation was not issued in this runtime")
    return json.loads(json.dumps(value))


def _host_readback(folder, stem, payload):
    """Invoke only this installed package's fixed bounded FBX parser."""
    import subprocess
    installation = _source_installation()
    if not installation or installation != _HOST_INSTALLATION:
        raise NativeExportError('NATIVE_EXPORT_HOST_READBACK_UNAVAILABLE',
            'Unchanged code-owned source layout and Python/parser are required; copied bridge and frozen routes need a trusted installation manifest')
    root, python, module, module_digest = installation
    manifest, output = folder / (stem + '-input.json'), folder / (stem + '-output.json')
    with manifest.open('x', encoding='utf-8') as stream:
        json.dump(payload, stream, allow_nan=False)
    # Logs go to an owned file, never an unbounded captured pipe. Result bytes
    # are independently bounded before reading. No shell or arbitrary command.
    with (folder / (stem + '-host.log')).open('xb') as log:
        try:
            # -I discards environment import paths; the fixed bootstrap selects
            # this code-owned src directory before loading the fixed module.
            bootstrap = ('import runpy,sys;sys.path.insert(0,sys.argv.pop(1));'
                         'runpy.run_module("cascadeur_complete.native_export_readback",run_name="__main__")')
            result = subprocess.run([str(python), '-I', '-c', bootstrap, str(root / 'src'),
                '--manifest', str(manifest), '--output', str(output)], cwd=str(root),
                stdin=subprocess.DEVNULL, stdout=log, stderr=log, timeout=30,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), check=False)
        except subprocess.TimeoutExpired as exc:
            raise NativeExportError('NATIVE_EXPORT_READBACK_TIMEOUT', 'Fixed host parser exceeded 30 seconds') from exc
    if result.returncode != 0 or not output.is_file() or output.is_symlink() or output.stat().st_size > 4 * 1024**2:
        raise NativeExportError('NATIVE_EXPORT_READBACK_UNAVAILABLE', 'Fixed host parser did not return a bounded result')
    return json.loads(output.read_text(encoding='utf-8'))


class _QualificationProgress:
    """Small durable phase markers locate a native call that never returns."""
    def __init__(self, folder):
        self.path = folder / 'progress.jsonl'
        self.sequence = 0
        with self.path.open('xb'):
            pass

    def mark(self, phase, state='begin', **detail):
        import time
        self.sequence += 1
        if self.sequence > 96 or self.path.stat().st_size > 128 * 1024:
            raise NativeExportError('RESOURCE_BUDGET_EXCEEDED', 'Qualification progress budget exceeded')
        record = {'sequence': self.sequence, 'phase': phase, 'state': state,
                  'monotonic_s': time.monotonic(), **detail}
        encoded = (json.dumps(record, allow_nan=False) + '\n').encode('utf-8')
        if len(encoded) > 4096:
            raise NativeExportError('RESOURCE_BUDGET_EXCEEDED', 'Qualification progress record exceeded budget')
        with self.path.open('ab', buffering=0) as stream:
            stream.write(encoded)
            os.fsync(stream.fileno())


def qualify_export_disposable(adapter):
    """Observe real SDK completion/settings using an owned independent object.

    The supplied full NativeSceneAdapter is a reader, not a caller proof flag.
    This function never registers a route. Its static fixture does not establish
    animated channels, a rig, skinning, target import, rest or motion quality.
    """
    import uuid
    import csc
    from commands.add.add_transform import add_transform_mod
    from . import runtime as rt
    from .native_adapters import installed_build
    from .native_scene_adapter import NativeSceneAdapter
    guards.assert_loaded_package()
    if not isinstance(adapter, NativeSceneAdapter) or not callable(getattr(adapter, 'read_scene', None)):
        raise NativeExportError('SOURCE_READER_UNVERIFIED', 'Full code-owned NativeSceneAdapter reader required')
    if installed_build() != SUPPORTED_BUILD:
        raise NativeExportError('UNSUPPORTED_VERSION', 'Disposable export helper requires ' + SUPPORTED_BUILD)
    if csc.app.get_application().is_export_available() is not True:
        raise NativeExportError('NATIVE_EXPORT_LICENSE_UNAVAILABLE', 'Installed application reports export unavailable')
    # Fail before creating a scene if the fixed parser is not installed.
    root = rt.runtime_root()
    if not _HOST_INSTALLATION or _source_installation() != _HOST_INSTALLATION:
        raise NativeExportError('NATIVE_EXPORT_HOST_READBACK_UNAVAILABLE',
            'Unchanged code-owned source installation is required; state location does not select executable code')
    token = str(uuid.uuid4())
    folder = root / 'snapshots' / ('export-qualification-' + token)
    folder.mkdir(parents=True)
    progress = _QualificationProgress(folder)
    progress.mark('scene_manager')
    manager = csc.app.get_application().get_scene_manager()
    previous = manager.current_scene()
    progress.mark('scene_manager', 'complete')
    local_before = dict(vars(guards._LOCAL))
    disposable, previous_projection = None, None
    try:
        if previous is not None:
            # Do not run a whole character reader just to set up an independent
            # disposable fixture. The previous implementation did that before
            # its first observable phase and could not bound native allocation.
            progress.mark('previous_scene_scope')
            previous_domain = rt._domain_scene(previous)
            count = len(previous_domain.model_viewer().get_objects())
            frames = int(previous_domain.layers_viewer().frames_count())
            progress.mark('previous_scene_scope', 'complete', objects=count, frames=frames)
            if count != 0 or not 1 <= frames <= _MAX_FRAMES:
                raise NativeExportError('NATIVE_EXPORT_QUALIFICATION_REQUIRES_EMPTY_CURRENT_SCENE',
                    'Select an empty scene before explicit qualification; a populated current scene is never fully scanned by fixture setup')
            progress.mark('previous_scene_capture')
            previous_projection = adapter.read_scene(previous)
            progress.mark('previous_scene_capture', 'complete')
        progress.mark('create_application_scene')
        disposable = manager.create_application_scene()
        progress.mark('create_application_scene', 'complete')
        progress.mark('activate_disposable')
        manager.set_current_scene(disposable)
        progress.mark('activate_disposable', 'complete')
        domain = rt._domain_scene(disposable)
        created, callback_completed = [], []

        def create_fixture(model, update, callback_scene, session):
            if callback_completed or created:
                raise NativeExportError('NATIVE_EXPORT_FIXTURE_UNAVAILABLE', 'Fixture callback was replayed')
            progress.mark('installed_add_transform_mod')
            # Use the installed Add.Transform command's exact callback and its
            # pycsc part/FbxExport/selector implementation. Unlike PyScene.edit,
            # domain.modify_with_session passes (model, update, domain, session)
            # and does not append a whole SceneUpdater.update. A view Scene only
            # exposes domain_scene(); it does not implement this transaction.
            identifier = add_transform_mod(model, update, callback_scene, session, False)
            model.set_object_name(identifier, 'MCPExportQualification')
            created.append(rt._id_string(identifier))
            callback_completed.append(True)
            progress.mark('installed_add_transform_mod', 'complete')

        progress.mark('fixture_modify_with_session')
        transaction = getattr(domain, 'modify_with_session', None)
        if not callable(transaction):
            raise NativeExportError('NATIVE_EXPORT_FIXTURE_UNAVAILABLE', 'Native domain Scene lacks modify_with_session')
        completed = transaction('Create owned MCP export qualification object', create_fixture)
        progress.mark('fixture_modify_with_session', 'complete', returned=bool(completed),
                      callback_count=len(callback_completed))
        if completed is not True or callback_completed != [True]:
            raise NativeExportError('NATIVE_EXPORT_FIXTURE_UNAVAILABLE', 'Installed Add.Transform transaction did not complete')
        if len(created) != 1:
            raise NativeExportError('NATIVE_EXPORT_FIXTURE_UNAVAILABLE', 'Installed pycsc did not create one independent object')
        progress.mark('fixture_capture')
        before = adapter.read_scene(disposable)
        progress.mark('fixture_capture', 'complete')
        rows = before.get('objects', [])
        if len(rows) != 1 or rows[0]['id'] != created[0] or rows[0]['name'] != 'MCPExportQualification':
            raise NativeExportError('NATIVE_EXPORT_FIXTURE_SCOPE_MISMATCH', 'Disposable full reader did not observe exact object closure')
        frame_count = int(domain.layers_viewer().frames_count())
        if not 1 <= frame_count <= _MAX_FRAMES:
            raise NativeExportError('NATIVE_EXPORT_RANGE_UNSUPPORTED', 'Disposable frame interval exceeds finite route')
        selected = [rt._id_string(obj) for obj in domain.selector().selected().ids]
        if selected != created:
            raise NativeExportError('EXPORT_SELECTION_MISMATCH', 'Installed selector did not retain exact fixture object')

        def unchanged():
            guards.assert_loaded_package()
            progress.mark('first_write_source_capture')
            if adapter.read_scene(disposable) != before:
                raise NativeExportError('SCENE_CHANGED', 'Disposable source changed before native export')
            progress.mark('first_write_source_capture', 'complete')

        # These are explicit qualification inputs, not guessed scene settings.
        discovery_request = {'request_id': token + '-discover', 'operations': []}
        guards.begin_request(discovery_request)
        guards.set_write_guard(unchanged)
        progress.mark('discovery_export')
        artifact, takes, applied, messages = _selected_call(disposable, folder / 'discover.fbx', 64 * 1024**2,
            30.0, 1, expected_range=(0, frame_count - 1), progress=progress)
        progress.mark('discovery_export', 'complete', artifact_sha256=artifact['sha256'], artifact_bytes=artifact['bytes'])
        progress.mark('discovery_source_capture')
        if adapter.read_scene(disposable) != before:
            raise NativeExportError('NATIVE_COMPLETION_UNKNOWN', 'Discovery export changed the full authored source')
        progress.mark('discovery_source_capture', 'complete')
        progress.mark('discovery_host_readback')
        discovery = _host_readback(folder, 'discover', {'mode': 'discover', 'artifact': artifact,
            'take_readback': takes, 'source_id': created[0], 'node_path': rows[0]['name'], 'frame_count': frame_count})
        progress.mark('discovery_host_readback', 'complete', status=discovery.get('status'))
        if discovery.get('status') != 'discovered':
            raise NativeExportError('NATIVE_EXPORT_SETTINGS_UNVERIFIED', 'Actual FBX metadata discovery failed', observation=discovery)
        profile = discovery['profile']
        confirmed = folder / 'confirmed'
        confirmed.mkdir()
        # The observed SDK derives the take name from the file basename. Keep
        # that input identical while writing independent, no-clobber bytes.
        arguments = {'path': str(confirmed / 'discover.fbx'), 'export_profile_digest': guards.digest(profile),
                     'max_output_bytes': 64 * 1024**2}
        request = {'request_id': token + '-confirm', 'operations': [{'name': 'io.export_fbx', 'arguments': arguments}],
                   'execution_context': {'run_id': 'qualification-' + token, 'step_id': 'native-export',
                                         'attempt_id': token, 'lease_epoch': 1}}
        guards.begin_request(request)
        guards.set_write_guard(unchanged)
        progress.mark('confirmed_export')
        native, _ = observe_export_call(disposable, arguments, request, profile, _progress=progress)
        progress.mark('confirmed_export', 'complete')
        progress.mark('confirmed_source_capture')
        actual_after = adapter.read_scene(disposable)
        if actual_after != before:
            raise NativeExportError('NATIVE_COMPLETION_UNKNOWN', 'Confirmed export changed full authored source')
        progress.mark('confirmed_source_capture', 'complete')
        observation = native['completion_observation']
        progress.mark('confirmed_host_readback')
        readback = _host_readback(folder, 'confirm', {'mode': 'validate', 'artifact': observation['artifact'],
            'profile': profile, 'completion_observation': observation})
        progress.mark('confirmed_host_readback', 'complete', status=readback.get('status'))
        if (readback.get('status') != 'pass' or readback.get('completion_observation_digest') != guards.digest(observation)
                or readback.get('profile_digest') != guards.digest(profile)):
            raise NativeExportError('NATIVE_EXPORT_SETTINGS_UNVERIFIED', 'Second actual export did not match discovered contract', observation=readback)
        progress.mark('qualification', 'observed_structural_only')
        return {'status': 'observed_structural_only', 'qualified_operations': [], 'production_ready': False,
            'reason_codes': ['ANIMATED_EXPORT_FIXTURE_UNQUALIFIED', 'TARGET_ROUNDTRIP_UNVERIFIED'],
            'profile': profile, 'native_export_observation': observation, 'export_settings_readback': readback,
            'discovery': {'artifact': artifact, 'settings': applied, 'completion_messages': messages},
            'source_before_digest': guards.digest(before), 'source_after_digest': guards.digest(actual_after),
            'retained_directory': str(folder), 'quality': 'not_evaluated'}
    except Exception as exc:
        progress.mark('qualification', 'failed', code=getattr(exc, 'code', type(exc).__name__), detail=str(exc)[:1000])
        if isinstance(exc, NativeExportError):
            exc.observation = {'retained_directory': str(folder), 'progress_path': str(progress.path),
                               'failure_observation': exc.observation}
        raise
    finally:
        try:
            if disposable is not None:
                progress.mark('restore_previous_scene')
                if previous is not None:
                    manager.set_current_scene(previous)
                progress.mark('restore_previous_scene', 'complete')
                progress.mark('remove_owned_disposable')
                manager.remove_application_scene(disposable)
                progress.mark('remove_owned_disposable', 'complete')
                if previous is not None and previous_projection is not None:
                    progress.mark('previous_scene_final_capture')
                    if adapter.read_scene(previous) != previous_projection:
                        raise NativeExportError('QUALIFICATION_ORIGINAL_SCENE_CHANGED', 'Original full authored source changed')
                    progress.mark('previous_scene_final_capture', 'complete')
        finally:
            vars(guards._LOCAL).clear()
            vars(guards._LOCAL).update(local_before)
