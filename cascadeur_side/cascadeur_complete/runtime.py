from __future__ import annotations

import hashlib
import hmac
import inspect
import json
import os
import re
import shutil
import subprocess
import time
import traceback
import uuid
from contextlib import suppress
from pathlib import Path

import csc

from . import handlers as _handlers  # noqa: F401
from .handler_registry import dispatch as dispatch_registered

PROTOCOL_VERSION = "2.0"
READ_ONLY_OPERATIONS = {
    "system.status",
    "system.logs",
    "system.tools",
    "system.introspect",
    "scene.summary",
    "scene.objects",
    "scene.list",
    "scene.validate",
    "selection.get",
    "selection.filter",
    "object.hierarchy",
    "object.properties",
    "object.behaviors",
    "timeline.get",
    "timeline.range",
    "animation.transform_get",
    "animation.key_list",
    "animation.graph_query",
    "animation.cycle_query",
    "layer.list",
    "render.viewport_state",
    "render.camera_catalog",
    "generation.state",
    "physics.state",
    "physics.auto_state",
    "rig.state",
    "rig.constraint_drivers",
}


class BridgeAuthenticationError(PermissionError):
    pass


def runtime_root():
    profile = os.environ.get("USERPROFILE")
    local = Path(profile) / "AppData" / "Local" if profile else Path(os.environ["LOCALAPPDATA"])
    return local / "CascadeurMCP" / "cascadeur-complete"


def ensure_dirs():
    root = runtime_root()
    for relative in (
        "state/requests",
        "state/responses",
        "state/jobs",
        "state/tokens",
        "state/seen",
        "snapshots",
        "logs",
    ):
        (root / relative).mkdir(parents=True, exist_ok=True)
    return root


def _canonical_payload(payload):
    unsigned = {key: value for key, value in payload.items() if key != "mac"}
    return json.dumps(
        unsigned,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _bridge_key(root):
    path = root / "state" / "bridge.key"
    value = path.read_bytes()
    if len(value) < 32:
        raise BridgeAuthenticationError("Bridge authentication key is invalid")
    return value


def _session_id(secret):
    return hashlib.sha256(b"cascadeur-complete-bridge-session\0" + secret).hexdigest()[:32]


def _sign_message(payload, secret):
    return hmac.new(secret, _canonical_payload(payload), hashlib.sha256).hexdigest()


def _verify_message(payload, secret):
    supplied = payload.get("mac")
    if not isinstance(supplied, str) or len(supplied) != 64:
        raise BridgeAuthenticationError("Queue message is unsigned")
    if not hmac.compare_digest(supplied, _sign_message(payload, secret)):
        raise BridgeAuthenticationError("Queue message authentication failed")
    if payload.get("session_id") != _session_id(secret):
        raise BridgeAuthenticationError("Queue session does not match this installation")
    nonce = payload.get("nonce")
    if not isinstance(nonce, str) or not re.fullmatch(r"[A-Za-z0-9_-]{20,64}", nonce):
        raise BridgeAuthenticationError("Queue nonce is invalid")
    request_id = str(payload.get("request_id", ""))
    try:
        if str(uuid.UUID(request_id)) != request_id.casefold():
            raise ValueError
    except ValueError as exc:
        raise BridgeAuthenticationError("Queue request id is invalid") from exc


def _claim_request_nonce(root, request):
    marker = root / "state" / "seen" / ("request-" + request["nonce"])
    try:
        descriptor = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise BridgeAuthenticationError("Queue request was already processed") from exc
    with os.fdopen(descriptor, "w", encoding="ascii") as stream:
        stream.write(str(request["request_id"]) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def _operation_is_mutating(operation):
    name = str(operation.get("name", ""))
    args = operation.get("arguments") or {}
    if name in READ_ONLY_OPERATIONS:
        return False
    if name == "system.view_mode":
        return str(args.get("action", "get")) not in {"get", "list"}
    return name not in {"safety.snapshot", "safety.rollback_internal"}


def _confirmation_signature(nonce, record, secret):
    approval = {
        "schema_version": record.get("schema_version"),
        "feature_id": record.get("feature_id"),
        "scene_id": record.get("scene_id"),
        "scene_revision": record.get("scene_revision"),
        "selection_fingerprint": record.get("selection_fingerprint"),
        "operation": record.get("operation"),
        "impact": record.get("impact"),
        "backup_path": record.get("backup_path"),
        "expires_at": record.get("expires_at"),
    }
    canonical = json.dumps(
        approval,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    message = ("cascadeur-complete-change-v2:" + nonce + ":").encode() + canonical.encode("utf-8")
    return hmac.new(secret, message, hashlib.sha256).hexdigest()


def _verify_confirmation(root, request, before):
    operations = request.get("operations") or []
    if not any(_operation_is_mutating(item) for item in operations):
        return
    safety = request.get("safety_context") or {}
    token = safety.get("confirmation_token")
    if not isinstance(token, str):
        raise BridgeAuthenticationError("Mutating operations require a consumed confirmation token")
    try:
        nonce, signature = token.split(".", 1)
    except ValueError as exc:
        raise BridgeAuthenticationError("Malformed confirmation token") from exc
    if not re.fullmatch(r"[A-Za-z0-9_-]{20,64}", nonce) or not re.fullmatch(r"[0-9a-f]{64}", signature):
        raise BridgeAuthenticationError("Malformed confirmation token")
    token_path = root / "state" / "tokens" / (nonce + ".used")
    try:
        record = json.loads(token_path.read_text(encoding="utf-8"))
        secret = (root / "state" / "confirmation.key").read_bytes()
    except (OSError, ValueError) as exc:
        raise BridgeAuthenticationError("Consumed confirmation token is unavailable") from exc
    expected = _confirmation_signature(nonce, record, secret)
    if not hmac.compare_digest(signature, expected) or record.get("token") != token or not record.get("used"):
        raise BridgeAuthenticationError("Confirmation token authentication failed")
    if float(record.get("expires_at", 0)) < time.time():
        raise BridgeAuthenticationError("Confirmation token expired")
    if record.get("feature_id") != request.get("feature_id"):
        raise BridgeAuthenticationError("Confirmation token feature binding differs")
    if record.get("scene_id") != before.get("scene_id") or record.get("scene_revision") != before.get("revision"):
        raise BridgeAuthenticationError("Confirmation token scene binding differs")
    if record.get("selection_fingerprint") != before.get("selection_fingerprint"):
        raise BridgeAuthenticationError("Confirmation token selection binding differs")
    approved = record.get("operation") or {}
    requested = operations[0] if len(operations) == 1 else None
    if approved != requested:
        ui_alias = (
            approved.get("name") == "system.ui_file_flow"
            and requested
            and requested.get("name") == "system.action_dispatch"
            and (approved.get("arguments") or {}).get("action_id")
            == (requested.get("arguments") or {}).get("action_id")
        )
        if not ui_alias:
            raise BridgeAuthenticationError("Confirmation token operation or arguments differ")
    marker = root / "state" / "seen" / ("confirmation-" + nonce)
    try:
        descriptor = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise BridgeAuthenticationError("Confirmation token was already executed by Cascadeur") from exc
    with os.fdopen(descriptor, "w", encoding="ascii") as stream:
        stream.write(str(request["request_id"]) + ":" + str(request["nonce"]) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def atomic_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name("." + path.name + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(payload, stream, ensure_ascii=False, separators=(",", ":"))
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def json_safe(value, depth=0):
    if depth > 8:
        return {"type": type(value).__name__, "repr": repr(value)[:300], "truncated": True}
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, bytes):
        return {"type": "bytes", "length": len(value), "sha256": hashlib.sha256(value).hexdigest()}
    if isinstance(value, dict):
        return {str(key): json_safe(item, depth + 1) for key, item in list(value.items())[:1000]}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [json_safe(item, depth + 1) for item in list(value)[:1000]]
    for method in ("to_string", "name"):
        attribute = getattr(value, method, None)
        if callable(attribute):
            try:
                return {"type": type(value).__name__, "value": str(attribute())}
            except Exception:
                pass
        elif isinstance(attribute, str):
            return {"type": type(value).__name__, "value": attribute}
    return {"type": type(value).__name__, "repr": repr(value)[:1000]}


def _domain_scene(scene):
    method = getattr(scene, "domain_scene", None)
    return method() if callable(method) else scene


def _scene_view():
    app = csc.app.get_application()
    if not app:
        return None
    # SceneManager is the authority used by Cascadeur's load/activate API.
    # app.current_scene() can lag one tab behind immediately after a scene
    # transition, which is enough to make a correctly bound queued request
    # fail its identity guard.
    with suppress(Exception):
        manager = app.get_scene_manager()
        current = manager.current_scene()
        if current is not None:
            return current
    return app.current_scene()


def _normalized_path(path):
    return os.path.normcase(os.path.abspath(str(path))) if path else ""


def _load_scene_verified(path, *, prefer_other_open=False, close_previous=False):
    """Activate or load a scene and verify the exact path.

    Cascadeur permits the same file to be loaded into multiple tabs.  A duplicate
    receives a ``(1)`` display name but can still report the original path, and a
    subsequent in-place save opens a Save As dialog.  Rollback therefore prefers
    an already-open *other* copy of the snapshot and retires the failed working
    tab after switching.
    """
    requested = os.path.normcase(os.path.abspath(str(path)))
    app = csc.app.get_application()
    manager = app.get_scene_manager()
    previous = manager.current_scene()
    matches = [item for item in manager.scenes() if _normalized_path(item.get_path_name()) == requested]
    target = None
    if prefer_other_open:
        target = next((item for item in matches if item != previous), None)
    elif matches:
        target = matches[0]
    result = None
    activated_existing = target is not None
    if target is not None:
        manager.set_current_scene(target)
    else:
        result = app.get_data_source_manager().load_scene(str(path))
    current = _scene_view()
    state = scene_state(current)
    observed_path = state.get("path")
    observed = _normalized_path(observed_path)
    if observed != requested:
        raise AssertionError("POSTCONDITION_FAILED: active scene path differs after load")
    closed_previous = False
    if close_previous and previous is not None and previous != current:
        manager.remove_application_scene(previous)
        closed_previous = previous not in list(manager.scenes())
        if not closed_previous:
            raise AssertionError("POSTCONDITION_FAILED: replaced working scene tab remains open")
    return {
        "path": observed_path,
        "loaded": True,
        "activated_existing": activated_existing,
        "closed_previous": closed_previous,
        "revision": state.get("revision"),
        "return_value": json_safe(result),
    }


def _license_state(app):
    """Use Cascadeur's own current-session license log; keep feature availability separate."""
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        log_path = Path(local_app_data) / "Nekki Limited" / "Cascadeur" / "logs" / "cascadeur_log.log"
        if log_path.is_file():
            with suppress(Exception):
                size = log_path.stat().st_size
                with log_path.open("rb") as stream:
                    stream.seek(max(0, size - 262144))
                    tail = stream.read().decode("utf-8", errors="replace")
                matches = re.findall(r"Actual license type:\s*([^\r\n]+)", tail, flags=re.IGNORECASE)
                if matches:
                    return matches[-1].strip().title()
    return "Pro" if bool(app and app.is_pro_features_available()) else "Basic"


def _id_string(value):
    method = getattr(value, "to_string", None)
    return str(method()) if callable(method) else str(value)


def _read_member(value, name):
    member = getattr(value, name)
    return member() if callable(member) else member


def _guid(value):
    return csc.Guid(str(value))


def _object_id(value):
    return csc.model.ObjectId(str(value))


def _float_list(value):
    """Normalize Cascadeur/numpy vector values without importing host-only packages."""
    if value is None:
        return None
    converter = getattr(value, "tolist", None)
    if callable(converter):
        value = converter()
    if isinstance(value, (list, tuple)):
        return [float(item) for item in value]
    return None


def _quaternion_list(rotation):
    if rotation is None:
        return None
    converter = getattr(rotation, "to_quaternion", None)
    quaternion = converter() if callable(converter) else rotation
    components = []
    for name in ("w", "x", "y", "z"):
        member = getattr(quaternion, name, None)
        if member is None:
            return None
        components.append(float(member() if callable(member) else member))
    return components


def _rotation_payload(rotation):
    if rotation is None:
        return None
    euler = None
    converter = getattr(rotation, "to_euler_angles_x_y_z", None)
    if callable(converter):
        with suppress(Exception):
            euler = _float_list(converter())
    return {"euler_xyz_radians": euler, "quaternion_wxyz": _quaternion_list(rotation)}


def _transform_data_ids(domain, object_id, space):
    behaviour_viewer = domain.behaviour_viewer()
    transform = behaviour_viewer.get_behaviour_by_name(object_id, "Transform")
    if transform.is_null():
        return None
    prefix = "global" if space == "global" else "local"
    result = {
        "position": behaviour_viewer.get_behaviour_data(transform, prefix + "_position"),
        "rotation": behaviour_viewer.get_behaviour_data(transform, prefix + "_rotation"),
    }
    if space == "local":
        result["scale"] = behaviour_viewer.get_behaviour_data(transform, "local_scale")
    return result


def _read_transforms(domain, ids, frame, space="local"):
    if space not in ("local", "global"):
        raise ValueError("space must be local or global")
    model_viewer = domain.model_viewer()
    data_viewer = domain.data_viewer()
    result = []
    for raw_id in ids:
        object_id = raw_id if isinstance(raw_id, csc.model.ObjectId) else _object_id(raw_id)
        data_ids = _transform_data_ids(domain, object_id, space)
        if data_ids is None:
            raise ValueError("Object has no Transform behaviour: " + _id_string(object_id))
        values = {}
        for component, data_id in data_ids.items():
            if data_id.is_null():
                values[component] = None
                continue
            value = data_viewer.get_data_value(data_id, frame)
            values[component] = _rotation_payload(value) if component == "rotation" else _float_list(value)
        result.append(
            {
                "id": _id_string(object_id),
                "name": str(model_viewer.get_object_name(object_id)),
                "type": str(model_viewer.get_object_type_name(object_id)),
                "frame": int(frame),
                "space": space,
                **values,
            }
        )
    return result


def _transform_fingerprint(domain, frame):
    """Hash current-frame transforms so revision checks catch direct manipulator edits."""
    behaviour_viewer = domain.behaviour_viewer()
    data_viewer = domain.data_viewer()
    rows = []
    for transform in behaviour_viewer.get_behaviours("Transform"):
        owner = behaviour_viewer.get_behaviour_owner(transform)
        row = [_id_string(owner)]
        for name in ("local_position", "local_rotation", "local_scale"):
            data_id = behaviour_viewer.get_behaviour_data(transform, name)
            if data_id.is_null():
                row.append(None)
                continue
            value = data_viewer.get_data_value(data_id, frame)
            row.append(_quaternion_list(value) or _float_list(value) or repr(value)[:200])
        rows.append(row)
    rows.sort(key=lambda item: item[0])
    raw = json.dumps(rows, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _model_data_fingerprint(domain, frame):
    """Hash model structure and property links, excluding evaluated values."""
    model_viewer = domain.model_viewer()
    behaviour_viewer = model_viewer.behaviour_viewer()
    digest = hashlib.sha256()

    def feed(kind, identifier, value):
        payload = json.dumps(
            [kind, _id_string(identifier), json_safe(value)],
            sort_keys=True,
            separators=(",", ":"),
        )
        digest.update(payload.encode("utf-8", errors="replace"))

    for object_id in sorted(model_viewer.get_objects(), key=_id_string):
        behaviour_ids = sorted(behaviour_viewer.get_behaviours(object_id), key=_id_string)
        for behaviour_id in behaviour_ids:
            behaviour_name = str(behaviour_viewer.get_behaviour_name(behaviour_id))
            feed(
                "behaviour",
                behaviour_id,
                {
                    "owner": _id_string(object_id),
                    "name": behaviour_name,
                    "hidden": bool(behaviour_viewer.is_hidden(behaviour_id)),
                },
            )
            property_names = sorted(behaviour_viewer.get_behaviour_property_names(behaviour_id))
            for property_name in property_names:
                property_type = behaviour_viewer.get_property_type(behaviour_id, property_name)
                property_type_name = str(_read_member(property_type, "name"))
                if property_type_name == "DataType":
                    identifier = behaviour_viewer.get_behaviour_data(behaviour_id, property_name)
                    if identifier.is_null():
                        continue
                    feed("data_link", identifier, property_name)
                elif property_type_name == "SettingType":
                    identifier = behaviour_viewer.get_behaviour_setting(behaviour_id, property_name)
                    if identifier.is_null():
                        continue
                    feed("setting_link", identifier, property_name)
    return digest.hexdigest()


def _rig_mass_fingerprint(domain):
    """Hash persisted rigid-body mass values without animation-time evaluation."""
    model_viewer = domain.model_viewer()
    behaviours = model_viewer.behaviour_viewer()
    data_viewer = model_viewer.data_viewer()
    rows = []
    seen_owners = set()
    for behaviour_name in ("PhysicsSettings", "RigidBody"):
        try:
            behaviour_ids = behaviours.get_behaviours(behaviour_name)
        except RuntimeError:
            continue
        for behaviour_id in behaviour_ids:
            owner = behaviours.get_behaviour_owner(behaviour_id)
            owner_text = _id_string(owner)
            if owner_text in seen_owners:
                continue
            data_id = behaviours.get_behaviour_data(behaviour_id, "mass")
            if data_id.is_null():
                continue
            try:
                value = float(data_viewer.get_data_value(data_id))
            except (RuntimeError, TypeError):
                value = float(data_viewer.get_data_value(data_id, 0))
            rows.append([owner_text, _id_string(data_id), value])
            seen_owners.add(owner_text)
    rows.sort(key=lambda item: item[0])
    raw = json.dumps(rows, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _casc_tool_state(view_scene):
    """Read normalized Ballistic tool state from Cascadeur's Zstandard ZIP member."""
    if view_scene is None:
        return {"fingerprint": None, "ballistic_count": 0, "members": {}}
    path = Path(str(view_scene.get_path_name()))
    if not path.is_file():
        return {"fingerprint": None, "ballistic_count": 0, "members": {}}
    # Cascadeur 2026.1 stores CASC JSON members with ZIP method 93 (Zstandard),
    # which embedded Python 3.11's zipfile cannot decode. Windows ships bsdtar,
    # so extract the one small semantic member without a shell or visible window.
    completed = subprocess.run(
        ["tar", "-xOf", str(path), "tool/ballistic.json"],
        capture_output=True,
        check=False,
        timeout=5,
        creationflags=0x08000000 if os.name == "nt" else 0,
    )
    if completed.returncode != 0:
        raise RuntimeError("Unable to read CASC ballistic state: " + completed.stderr.decode(errors="replace")[:500])
    payload = json.loads(completed.stdout.decode("utf-8"))
    members = {"tool/ballistic.json": payload.get("Data")}
    raw = json.dumps(members, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    ballistic = members.get("tool/ballistic.json")
    return {
        "fingerprint": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
        "ballistic_count": len(ballistic) if isinstance(ballistic, list) else 0,
        "members": members,
    }


def _save_current_scene(view_scene):
    """Synchronously persist the active copy-on-write scene for tool-state evidence."""
    if view_scene is None:
        raise RuntimeError("No application scene is available")
    app = csc.app.get_application()
    path = Path(str(view_scene.get_path_name()))
    errors = []
    for attempt in (
        lambda: app.get_data_source_manager().save_scene(view_scene),
        lambda: app.get_data_source_manager().save_current_scene(),
    ):
        try:
            attempt()
            if path.is_file() and not str(view_scene.name()).startswith("*"):
                return str(path)
        except Exception as exc:
            errors.append(str(exc))
    raise RuntimeError("Failed to persist current scene: " + " | ".join(errors))


def scene_state(scene):
    app = csc.app.get_application()
    view_scene = _scene_view()
    domain_scene = _domain_scene(scene) if scene is not None else None
    if view_scene is None or domain_scene is None:
        return {
            "scene_id": None,
            "revision": None,
            "name": None,
            "path": None,
            "current_frame": None,
            "selection": [],
            "objects": [],
            "layers": [],
            "folders": [],
            "layer_root_id": None,
            "active_layer_id": None,
        }
    name = None
    path = None
    for attr_name in ("name", "get_path_name"):
        attr = getattr(view_scene, attr_name, None)
        if callable(attr):
            try:
                value = attr()
                if attr_name == "name":
                    name = str(value)
                else:
                    path = str(value)
            except Exception:
                pass
    frame = None
    with suppress(Exception):
        frame = int(domain_scene.get_current_frame(False))
    selection = []
    try:
        selected = domain_scene.selector().selected()
        selection = sorted(_id_string(item) for item in selected.ids)
    except Exception:
        with suppress(Exception):
            selection = sorted(_id_string(item) for item in domain_scene.selector().selected().ids())
    objects = []
    try:
        viewer = domain_scene.model_viewer()
        for object_id in viewer.get_objects():
            objects.append(
                {
                    "id": _id_string(object_id),
                    "name": str(viewer.get_object_name(object_id)),
                    "type": str(viewer.get_object_type_name(object_id)),
                }
            )
        objects.sort(key=lambda item: item["id"])
    except Exception:
        pass
    layers = []
    folders = []
    layer_root_id = None
    active_layer_id = None
    try:
        viewer = domain_scene.layers_viewer()
        layer_root_id = _id_string(viewer.root_id())
        for layer_id in viewer.all_layer_ids():
            layer = viewer.layer(layer_id)
            header = viewer.header(layer_id)
            layers.append(
                {
                    "id": _id_string(layer_id),
                    "name": str(_read_member(header, "name")),
                    "parent": _id_string(_read_member(header, "parent")),
                    "visible": bool(_read_member(layer, "is_visible")),
                    "locked": bool(_read_member(layer, "is_locked")),
                    "keys": list(layer.key_frame_indices()),
                }
            )
        layers.sort(key=lambda item: item["id"])
        for folder_id, _folder in viewer.folders_map().items():
            header = viewer.header(folder_id)
            folders.append(
                {
                    "id": _id_string(folder_id),
                    "name": str(_read_member(header, "name")),
                    "parent": _id_string(_read_member(header, "parent")),
                }
            )
        folders.sort(key=lambda item: item["id"])
        active_layer_id = _id_string(domain_scene.get_layers_selector().top_layer_id())
    except Exception:
        pass
    transform_fingerprint = None
    model_data_fingerprint = None
    rig_mass_fingerprint = None
    tool_state = {"fingerprint": None, "ballistic_count": 0}
    if frame is not None:
        with suppress(Exception):
            transform_fingerprint = _transform_fingerprint(domain_scene, frame)
        with suppress(Exception):
            model_data_fingerprint = _model_data_fingerprint(domain_scene, frame)
        with suppress(Exception):
            rig_mass_fingerprint = _rig_mass_fingerprint(domain_scene)
    with suppress(Exception):
        tool_state = _casc_tool_state(view_scene)
    raw = json.dumps(
        {
            "name": name,
            "path": path,
            "frame": frame,
            "selection": selection,
            "objects": objects,
            "layers": layers,
            "folders": folders,
            "layer_root_id": layer_root_id,
            "active_layer_id": active_layer_id,
            "transform_fingerprint": transform_fingerprint,
            "model_data_fingerprint": model_data_fingerprint,
            "rig_mass_fingerprint": rig_mass_fingerprint,
            "tool_state_fingerprint": tool_state.get("fingerprint"),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    scene_id = hashlib.sha256((path or name or "untitled").encode("utf-8")).hexdigest()[:24]
    revision = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return {
        "scene_id": scene_id,
        "revision": revision,
        "name": name,
        "path": path,
        "current_frame": frame,
        "selection": selection,
        "selection_fingerprint": hashlib.sha256("\n".join(selection).encode()).hexdigest(),
        "objects": objects,
        "layers": layers,
        "folders": folders,
        "layer_root_id": layer_root_id,
        "active_layer_id": active_layer_id,
        "transform_fingerprint": transform_fingerprint,
        "model_data_fingerprint": model_data_fingerprint,
        "rig_mass_fingerprint": rig_mass_fingerprint,
        "tool_state_fingerprint": tool_state.get("fingerprint"),
        "ballistic_count": tool_state.get("ballistic_count", 0),
        "license": _license_state(app),
        "pro_features_available": bool(app and app.is_pro_features_available()),
    }


def tools_catalog():
    app = csc.app.get_application()
    manager = app.get_tools_manager() if app else None
    if manager is None:
        return []
    result = []
    for tool in manager.tools():
        try:
            result.append(str(tool.name()))
        except Exception:
            result.append(type(tool).__name__)
    return sorted(set(result))


def introspect_csc():
    """Create a JSON-safe schema directly from the installed embedded module."""

    def inspect_namespace(namespace, seen):
        identity = id(namespace)
        if identity in seen:
            return {}
        seen.add(identity)
        result = {}
        for name in sorted(dir(namespace)):
            if name.startswith("_"):
                continue
            try:
                value = getattr(namespace, name)
            except Exception:
                continue
            module_name = getattr(value, "__name__", "")
            if inspect.ismodule(value) and module_name.startswith("csc"):
                result[name] = inspect_namespace(value, seen)
                continue
            doc = (getattr(value, "__doc__", "") or "")[:12000]
            if isinstance(value, type):
                methods = []
                values = []
                for method_name in sorted(dir(value)):
                    if method_name.startswith("_"):
                        continue
                    try:
                        member = getattr(value, method_name)
                    except Exception:
                        continue
                    if callable(member) or isinstance(member, property):
                        methods.append(method_name)
                    else:
                        values.append(method_name)
                result[name] = {"type": "class", "methods": methods, "values": values, "doc": doc}
            elif inspect.isroutine(value) or callable(value):
                try:
                    signature = str(inspect.signature(value))
                except Exception:
                    signature = "(...)"
                result[name] = {"type": "function", "signature": signature, "doc": doc}
            else:
                result[name] = {"type": "value", "repr": repr(value)[:1000]}
        return result

    return {"csc": inspect_namespace(csc, set())}


def inspect_runtime_object(value):
    members = []
    for name in sorted(dir(value)):
        if name.startswith("_"):
            continue
        try:
            member = getattr(value, name)
        except Exception:
            continue
        entry = {"name": name, "callable": callable(member), "type": type(member).__name__}
        if callable(member):
            try:
                entry["signature"] = str(inspect.signature(member))
            except Exception:
                entry["signature"] = "(...)"
        else:
            entry["value"] = json_safe(member)
        members.append(entry)
    return {"type": type(value).__name__, "repr": repr(value)[:1000], "members": members}


def _save_snapshot(scene, snapshot_id, working_id):
    root = ensure_dirs()
    destination = root / "snapshots" / (snapshot_id + ".casc")
    working_destination = root / "snapshots" / (working_id + ".working.casc")
    app = csc.app.get_application()
    view_scene = _scene_view()
    snapshots_root = (root / "snapshots").resolve()
    current_path = Path(str(view_scene.get_path_name())) if view_scene is not None else None

    resolved_current = current_path.resolve() if current_path and current_path.is_file() else None
    current_is_working = bool(
        resolved_current
        and resolved_current.parent == snapshots_root
        and resolved_current.name.endswith(".working.casc")
    )
    errors = []
    if current_is_working:
        # Cascadeur does not consistently prefix view_scene.name() with '*'
        # for static update-graph edits. Always persist the writable working
        # document before cloning its immutable recovery snapshot.
        for attempt in (
            lambda: app.get_data_source_manager().save_scene(view_scene),
            lambda: app.get_data_source_manager().save_current_scene(),
        ):
            try:
                attempt()
                if resolved_current.is_file() and resolved_current.stat().st_size > 0:
                    break
            except Exception as exc:
                errors.append(str(exc))
        else:
            raise RuntimeError("In-place working-scene save failed: " + " | ".join(errors))
        working_path = resolved_current
    else:
        # Never make an immutable recovery snapshot the active document.  The
        # first protected change branches the live scene to a writable working
        # document, leaving the original and every recovery file untouched.
        for attempt in (
            lambda: app.get_data_source_manager().save_scene(view_scene, str(working_destination)),
            lambda: view_scene.save(str(working_destination)),
        ):
            try:
                attempt()
                if working_destination.is_file() and working_destination.stat().st_size > 0:
                    break
            except Exception as exc:
                errors.append(str(exc))
        else:
            raise RuntimeError("Working-scene branch failed: " + " | ".join(errors))
        working_path = working_destination.resolve()

    shutil.copy2(str(working_path), str(destination))
    if not destination.is_file() or destination.stat().st_size <= 0:
        raise RuntimeError("Immutable snapshot clone was not created")
    if destination.resolve() == working_path.resolve():
        raise RuntimeError("Snapshot and working scene paths must differ")
    return {"path": str(destination), "working_path": str(working_path)}


def _file_loader(tool_name, scene, method, path):
    app = csc.app.get_application()
    tool = app.get_tools_manager().get_tool(tool_name)
    target = tool
    getter = getattr(tool, "get_fbx_loader", None)
    if callable(getter):
        target = getter(_scene_view())
    function = getattr(target, method)
    return function(str(path).replace("\\", "/"))


def _run_operation(scene, operation, request):
    name = operation.get("name")
    args = operation.get("arguments") or {}
    handled, registered_result = dispatch_registered(
        name,
        scene,
        args,
        request,
        {
            "csc": csc,
            "domain_scene": _domain_scene,
            "scene_view": _scene_view,
            "scene_state": scene_state,
            "json_safe": json_safe,
            "id_string": _id_string,
            "read_member": _read_member,
            "guid": _guid,
            "object_id": _object_id,
            "save_current_scene": _save_current_scene,
            "casc_tool_state": _casc_tool_state,
        },
    )
    if handled:
        return registered_result
    if name in ("system.status", "scene.summary"):
        state = scene_state(scene)
        if name == "system.status":
            state["tools"] = tools_catalog()
            state["protocol_version"] = PROTOCOL_VERSION
            state["bridge_python"] = tuple(__import__("sys").version_info[:3])
        return state, []
    if name == "scene.objects":
        state = scene_state(scene)
        offset = max(0, int(args.get("offset", 0)))
        limit = min(1000, max(1, int(args.get("limit", 200))))
        return {
            "total": len(state["objects"]),
            "offset": offset,
            "items": state["objects"][offset : offset + limit],
        }, []
    if name == "system.tools":
        return tools_catalog(), []
    if name == "system.introspect":
        schema = introspect_csc()
        counts = {"symbols": 0, "classes": 0, "functions": 0, "methods": 0, "values": 0}

        def count(node):
            for value in node.values():
                if not isinstance(value, dict):
                    continue
                if "type" in value:
                    counts["symbols"] += 1
                    if value["type"] == "class":
                        counts["classes"] += 1
                    elif value["type"] == "function":
                        counts["functions"] += 1
                    counts["methods"] += len(value.get("methods", []))
                    counts["values"] += len(value.get("values", []))
                else:
                    count(value)

        count(schema)
        counts["class_members"] = counts["methods"] + counts["values"]
        return {"schema": schema, "counts": counts}, []
    if name == "system.action_invoke":
        action_id = str(args["action_id"])
        before = scene_state(scene)
        result = csc.app.get_application().get_action_manager().call_action(action_id)
        after = scene_state(scene)
        postcondition = args.get("postcondition")
        if postcondition:
            raise PermissionError("Generic action postcondition call chains are not available in production")
        elif args.get("expect_change", True) and before["revision"] == after["revision"]:
            raise AssertionError("POSTCONDITION_FAILED: action made no observable scene change")
        return {
            "action_id": action_id,
            "return_value": json_safe(result),
            "before": before["revision"],
            "after": after["revision"],
        }, []
    if name == "system.action_dispatch":
        # Internal half of a host-verified UI file flow.  The host fills the
        # exact owned dialog and independently verifies either a changed scene
        # revision or a stable non-empty output file before it can report
        # success.  This operation is intentionally not exposed as an MCP tool.
        action_id = str(args["action_id"])
        result = csc.app.get_application().get_action_manager().call_action(action_id)
        return {"action_id": action_id, "return_value": json_safe(result)}, []
    if name == "timeline.set_frame":
        frame = int(args["frame"])
        domain = _domain_scene(scene)

        def set_frame(_model, _update, _scene, session):
            session.set_current_frame(frame)

        domain.modify_with_session("Cascadeur Complete: set frame", set_frame)
        observed = int(domain.get_current_frame(False))
        if observed != frame:
            raise AssertionError("POSTCONDITION_FAILED: frame is " + str(observed))
        return {"frame": observed}, []
    if name == "timeline.get":
        domain = _domain_scene(scene)
        viewer = domain.layers_viewer()
        boundary = None
        with suppress(Exception):
            boundary = json_safe(_scene_view().animation_boundary())
        return {
            "current_frame": int(domain.get_current_frame(False)),
            "frames_count": int(viewer.frames_count()),
            "animation_boundary": boundary,
        }, []
    if name == "animation.transform_get":
        domain = _domain_scene(scene)
        frame = int(args.get("frame", domain.get_current_frame(False)))
        ids = [str(item) for item in args.get("ids", [])]
        if not ids:
            ids = [_id_string(item) for item in domain.selector().selected().ids]
        if not ids:
            raise ValueError("transform_get requires ids or a non-empty selection")
        return _read_transforms(domain, ids, frame, str(args.get("space", "local"))), []
    if name == "animation.transform_set":
        domain = _domain_scene(scene)
        current_frame = int(domain.get_current_frame(False))
        frame = int(args.get("frame", current_frame))
        if frame != current_frame:
            raise ValueError("transform_set writes the current frame only; set the playhead first")
        ids = [str(item) for item in args.get("ids", [])]
        if not ids:
            ids = [_id_string(item) for item in domain.selector().selected().ids]
        if not ids:
            raise ValueError("transform_set requires ids or a non-empty selection")
        space = str(args.get("space", "local"))
        if space not in ("local", "global"):
            raise ValueError("space must be local or global")
        provided = {
            key: args.get(key)
            for key in ("position", "rotation_euler_xyz_radians", "scale")
            if args.get(key) is not None
        }
        if not provided:
            raise ValueError("At least one transform component is required")
        if space == "global" and "scale" in provided:
            raise ValueError("Scale is only writable in local space")
        for key, value in provided.items():
            if not isinstance(value, (list, tuple)) or len(value) != 3:
                raise ValueError(key + " must contain exactly three numbers")
            provided[key] = [float(item) for item in value]

        targets = []
        for raw_id in ids:
            object_id = _object_id(raw_id)
            data_ids = _transform_data_ids(domain, object_id, space)
            if data_ids is None:
                raise ValueError("Object has no Transform behaviour: " + raw_id)
            targets.append((object_id, data_ids))

        def set_transforms(model, _update, scene_updater):
            editor = model.data_editor()
            changed = set()
            for _object, data_ids in targets:
                if "position" in provided:
                    editor.set_data_value(data_ids["position"], frame, tuple(provided["position"]))
                    changed.add(data_ids["position"])
                if "rotation_euler_xyz_radians" in provided:
                    rotation = csc.math.Rotation.from_euler(*provided["rotation_euler_xyz_radians"])
                    editor.set_data_value(data_ids["rotation"], frame, rotation)
                    changed.add(data_ids["rotation"])
                if "scale" in provided:
                    editor.set_data_value(data_ids["scale"], frame, tuple(provided["scale"]))
                    changed.add(data_ids["scale"])
            scene_updater.generate_update()
            scene_updater.run_update(changed, frame)

        domain.modify_update("Cascadeur Complete: set transform", set_transforms)
        observed = _read_transforms(domain, ids, frame, space)
        for item in observed:
            if "position" in provided and any(
                abs(actual - expected) > 1e-4
                for actual, expected in zip(item["position"], provided["position"], strict=True)
            ):
                raise AssertionError("POSTCONDITION_FAILED: position differs")
            if "scale" in provided and any(
                abs(actual - expected) > 1e-4 for actual, expected in zip(item["scale"], provided["scale"], strict=True)
            ):
                raise AssertionError("POSTCONDITION_FAILED: scale differs")
            if "rotation_euler_xyz_radians" in provided:
                expected_rotation = csc.math.Rotation.from_euler(*provided["rotation_euler_xyz_radians"])
                expected_quaternion = _quaternion_list(expected_rotation)
                observed_quaternion = item["rotation"]["quaternion_wxyz"]
                dot = abs(sum(a * b for a, b in zip(expected_quaternion, observed_quaternion, strict=True)))
                if abs(1.0 - dot) > 1e-4:
                    raise AssertionError("POSTCONDITION_FAILED: rotation differs")
        return observed, []
    if name == "selection.get":
        return scene_state(scene)["selection"], []
    if name == "selection.filter":
        domain = _domain_scene(scene)
        viewer = domain.model_viewer()
        selected_only = bool(args.get("selected_only", True))
        ids = domain.selector().selected().ids if selected_only else viewer.get_objects()
        type_name = str(args.get("type", "")).casefold()
        name_contains = str(args.get("name_contains", "")).casefold()
        matches = []
        for object_id in ids:
            if not isinstance(object_id, csc.model.ObjectId):
                continue
            object_name = str(viewer.get_object_name(object_id))
            object_type = str(viewer.get_object_type_name(object_id))
            if type_name and object_type.casefold() != type_name:
                continue
            if name_contains and name_contains not in object_name.casefold():
                continue
            matches.append({"id": _id_string(object_id), "name": object_name, "type": object_type})
        return matches, []
    if name in ("selection.set", "selection.add", "selection.remove"):
        domain = _domain_scene(scene)
        current = {_id_string(item) for item in domain.selector().selected().ids}
        supplied = {str(item) for item in args.get("ids", [])}
        if name == "selection.add":
            target = current | supplied
        elif name == "selection.remove":
            target = current - supplied
        else:
            target = supplied
        object_ids = {_object_id(item) for item in target}
        pivot = (
            _object_id(args["pivot_id"]) if args.get("pivot_id") else next(iter(object_ids), csc.model.ObjectId.null())
        )

        def change_selection(_model, _update, _scene, session):
            session.take_selector().select(object_ids, pivot)

        domain.modify_with_session("Cascadeur Complete: " + name, change_selection)
        observed = set(scene_state(_scene_view() or scene)["selection"])
        if observed != target:
            raise AssertionError("POSTCONDITION_FAILED: selection differs")
        return sorted(observed), []
    if name in ("layer.list", "animation.key_list"):
        state = scene_state(scene)
        if name == "layer.list":
            return state["layers"], []
        requested = args.get("layer_id")
        if requested:
            for layer in state["layers"]:
                if layer["id"] == str(requested):
                    return {"layer_id": requested, "keys": layer["keys"]}, []
            raise KeyError("Unknown layer id: " + str(requested))
        return {layer["id"]: layer["keys"] for layer in state["layers"]}, []
    if name in (
        "layer.create",
        "layer.delete",
        "layer.visibility",
        "layer.lock",
        "animation.key_add",
        "animation.key_delete",
    ):
        domain = _domain_scene(scene)
        created = []

        def edit_layers(model, _update, scene_updater):
            editor = model.layers_editor()
            if name == "layer.create":
                parent = _guid(args["parent_id"]) if args.get("parent_id") else scene_updater.layers_viewer().root_id()
                created.append(editor.create_layer(str(args["name"]), parent))
                return
            layer_id = _guid(args["layer_id"])
            if name == "layer.delete":
                editor.delete_layer(layer_id)
            elif name == "layer.visibility":
                editor.set_visible_for_layer(bool(args["visible"]), layer_id)
            elif name == "layer.lock":
                editor.set_locked_for_layer(bool(args["locked"]), layer_id)
            elif name == "animation.key_add":
                editor.set_fixed_interpolation_or_key_if_need(layer_id, int(args["frame"]), True)
            elif name == "animation.key_delete":
                editor.unset_section(int(args["frame"]), layer_id)

        domain.modify("Cascadeur Complete: " + name, edit_layers)
        state = scene_state(_scene_view() or scene)
        if name == "layer.create":
            created_id = _id_string(created[0])
            if not any(item["id"] == created_id for item in state["layers"]):
                raise AssertionError("POSTCONDITION_FAILED: created layer was not observed")
            return {"layer_id": created_id}, []
        layer_id_text = str(args["layer_id"])
        observed_layer = next((item for item in state["layers"] if item["id"] == layer_id_text), None)
        if name == "layer.delete":
            if observed_layer is not None:
                raise AssertionError("POSTCONDITION_FAILED: deleted layer still exists")
            return {"layer_id": layer_id_text, "deleted": True}, []
        if observed_layer is None:
            raise AssertionError("POSTCONDITION_FAILED: layer was not found")
        if name == "layer.visibility" and observed_layer["visible"] != bool(args["visible"]):
            raise AssertionError("POSTCONDITION_FAILED: visibility differs")
        if name == "layer.lock" and observed_layer["locked"] != bool(args["locked"]):
            raise AssertionError("POSTCONDITION_FAILED: lock state differs")
        if name == "animation.key_add" and int(args["frame"]) not in observed_layer["keys"]:
            raise AssertionError("POSTCONDITION_FAILED: key was not added")
        if name == "animation.key_delete" and int(args["frame"]) in observed_layer["keys"]:
            raise AssertionError("POSTCONDITION_FAILED: key was not deleted")
        return observed_layer, []
    if name == "scene.save":
        path = _save_current_scene(_scene_view())
        output = Path(path)
        if not output.is_file() or output.stat().st_size <= 0:
            raise AssertionError("POSTCONDITION_FAILED: current scene was not saved")
        return {"path": str(output), "bytes": output.stat().st_size}, []
    if name == "scene.new":
        result = csc.app.get_application().get_scene_manager().create_application_scene()
        return json_safe(result), []
    if name == "scene.open":
        path = str(args["path"])
        return _load_scene_verified(path), []
    if name == "io.import_fbx":
        result = _file_loader("FbxSceneLoader", scene, "import_scene", args["path"])
        return json_safe(result), []
    if name == "io.export_fbx":
        result = _file_loader("FbxSceneLoader", scene, "export_all_objects", args["path"])
        destination = Path(args["path"])
        if not destination.is_file():
            raise AssertionError("POSTCONDITION_FAILED: FBX output was not created")
        return {"path": str(destination), "bytes": destination.stat().st_size, "return_value": json_safe(result)}, []
    if name == "safety.snapshot":
        snapshot_id = str(args["snapshot_id"])
        working_id = str(args["working_id"])
        return {"snapshot_id": snapshot_id, **_save_snapshot(scene, snapshot_id, working_id)}, []
    if name in {"safety.rollback", "safety.rollback_internal"}:
        path = Path(str(args["path"]))
        if not path.is_file():
            raise FileNotFoundError(path)
        snapshots_root = (ensure_dirs() / "snapshots").resolve()
        working_path = (snapshots_root / (str(args["working_id"]) + ".working.casc")).resolve()
        if path.resolve().parent != snapshots_root or working_path.parent != snapshots_root:
            raise ValueError("Rollback paths must remain inside the snapshots directory")
        shutil.copy2(str(path.resolve()), str(working_path))
        loaded = _load_scene_verified(working_path, prefer_other_open=True, close_previous=True)
        loaded["restored_from"] = str(path.resolve())
        loaded["working_path"] = str(working_path)
        return loaded, []
    if name == "system.undo":
        return _run_operation(
            scene,
            {
                "name": "system.action_invoke",
                "arguments": {
                    "action_id": args.get("action_id", "Scene.Undo"),
                    "expect_change": args.get("expect_change", True),
                },
            },
            request,
        )
    if name == "system.redo":
        return _run_operation(
            scene,
            {
                "name": "system.action_invoke",
                "arguments": {
                    "action_id": args.get("action_id", "Scene.Redo"),
                    "expect_change": args.get("expect_change", True),
                },
            },
            request,
        )
    raise KeyError("Unknown operation: " + str(name))


def execute_request(scene, request):
    started = time.monotonic()
    feature_id = request.get("feature_id") or (request.get("operations") or [{}])[0].get("name", "batch")
    # Cascadeur may retain a Python command object created for a scene tab that
    # is no longer active. Always resolve the live scene view before enforcing
    # identity/revision guards; otherwise a menu fallback can reject a request
    # for the visible tab using the previous tab's identity.
    scene = _scene_view() or scene
    before = scene_state(scene)
    expected_scene = request.get("scene_id")
    expected_revision = request.get("expected_revision")
    if expected_scene and expected_scene != before["scene_id"]:
        return _error(feature_id, "SCENE_CHANGED", "Scene identity changed", started, before)
    if expected_revision and expected_revision != before["revision"]:
        return _error(feature_id, "SCENE_CHANGED", "Scene revision changed", started, before)
    try:
        _verify_confirmation(runtime_root(), request, before)
    except BridgeAuthenticationError as exc:
        return _error(feature_id, "INVALID_REQUEST", str(exc), started, before)
    safety = request.get("safety_context") or {}
    snapshot_id = None
    if safety.get("snapshot_required"):
        snapshot_id = request["request_id"]
        try:
            _save_snapshot(scene, snapshot_id)
        except Exception as exc:
            return _error(feature_id, "POSTCONDITION_FAILED", str(exc), started, before)
    results = []
    warnings = []
    try:
        current_scene = _scene_view() or scene
        for operation in request.get("operations", []):
            result, operation_warnings = _run_operation(current_scene, operation, request)
            results.append({"operation": operation["name"], "result": result})
            warnings.extend(operation_warnings)
            current_scene = _scene_view() or current_scene
        after = scene_state(current_scene)
        return {
            "ok": True,
            "feature_id": feature_id,
            "execution_mode": "Native",
            "scene_id": after["scene_id"],
            "scene_revision": after["revision"],
            "result": results[0]["result"] if len(results) == 1 else results,
            "warnings": warnings,
            "changed_entities": _changed_entities(before, after),
            "snapshot_id": snapshot_id,
            "job_id": None,
            "evidence": [
                {
                    "kind": "bridge_postcondition",
                    "detail": "Request completed on Cascadeur UI thread",
                    "observed_at": time.time(),
                }
            ],
            "duration_ms": int((time.monotonic() - started) * 1000),
            "error_code": None,
            "error_message": None,
            "operation_id": results[0]["operation"] if len(results) == 1 else "batch",
            "status": "succeeded",
            "scene_revision_before": before.get("revision"),
            "scene_revision_after": after.get("revision"),
            "postconditions": [
                {
                    "id": "bridge_execution",
                    "ok": True,
                    "detail": "Operation completed and live scene state was re-read",
                }
            ],
            "evidence_id": None,
        }
    except PermissionError as exc:
        return _error(feature_id, "LICENSE_GATED", str(exc), started, scene_state(_scene_view() or scene), snapshot_id)
    except AssertionError as exc:
        return _error(
            feature_id, "POSTCONDITION_FAILED", str(exc), started, scene_state(_scene_view() or scene), snapshot_id
        )
    except Exception as exc:
        detail = str(exc) + "\n" + traceback.format_exc(limit=8)
        return _error(
            feature_id, "POSTCONDITION_FAILED", detail, started, scene_state(_scene_view() or scene), snapshot_id
        )


def _changed_entities(before, after):
    changed = []
    if before.get("revision") != after.get("revision"):
        if before.get("current_frame") != after.get("current_frame"):
            changed.append("timeline.current_frame")
        if before.get("selection") != after.get("selection"):
            changed.append("scene.selection")
        if before.get("objects") != after.get("objects"):
            changed.append("scene.objects")
        if before.get("layers") != after.get("layers"):
            changed.append("scene.layers")
        if before.get("transform_fingerprint") != after.get("transform_fingerprint"):
            changed.append("scene.transforms")
        if before.get("model_data_fingerprint") != after.get("model_data_fingerprint"):
            changed.append("scene.behaviours")
        if before.get("rig_mass_fingerprint") != after.get("rig_mass_fingerprint"):
            changed.append("rig.rigid_body_masses")
        if before.get("tool_state_fingerprint") != after.get("tool_state_fingerprint"):
            changed.append("scene.tool_state")
        if not changed:
            changed.append("scene")
    return changed


def _error(feature_id, code, message, started, state, snapshot_id=None):
    return {
        "ok": False,
        "feature_id": feature_id,
        "execution_mode": "Native",
        "scene_id": state.get("scene_id"),
        "scene_revision": state.get("revision"),
        "result": None,
        "warnings": [],
        "changed_entities": [],
        "snapshot_id": snapshot_id,
        "job_id": None,
        "evidence": [{"kind": "bridge_error", "detail": message[:2000], "observed_at": time.time()}],
        "duration_ms": int((time.monotonic() - started) * 1000),
        "error_code": code,
        "error_message": message[:12000],
        "operation_id": None,
        "status": "failed",
        "scene_revision_before": state.get("revision"),
        "scene_revision_after": state.get("revision"),
        "postconditions": [],
        "evidence_id": None,
    }


def process_pending(scene, *, matching_scene_only=False):
    # Event and command callbacks can carry a stale per-tab scene argument.
    # Queue routing must follow the document that is actually active now.
    scene = _scene_view() or scene
    root = ensure_dirs()
    try:
        bridge_secret = _bridge_key(root)
    except Exception:
        return 0
    requests = root / "state" / "requests"
    responses = root / "state" / "responses"
    processed = 0
    active_scene_id = scene_state(scene).get("scene_id") if matching_scene_only else None
    for path in sorted(requests.glob("*.json")):
        if matching_scene_only:
            try:
                preview = json.loads(path.read_text(encoding="utf-8"))
                _verify_message(preview, bridge_secret)
            except Exception:
                preview = {}
            target_scene_id = preview.get("scene_id")
            if target_scene_id and target_scene_id != active_scene_id:
                # Leave the request unclaimed. A host tab nudge activates a
                # different scene first and then returns to the target scene;
                # only the matching activation may execute a mutating request.
                continue
        claimed = path.with_suffix(".processing")
        try:
            os.replace(path, claimed)
        except OSError:
            continue
        try:
            request = json.loads(claimed.read_text(encoding="utf-8"))
            request_id = str(request.get("request_id", ""))
            authenticated = True
            try:
                _verify_message(request, bridge_secret)
                _claim_request_nonce(root, request)
            except BridgeAuthenticationError as exc:
                authenticated = False
                result = _error(
                    "authentication",
                    "INVALID_REQUEST",
                    str(exc),
                    time.monotonic(),
                    scene_state(scene),
                )
            if authenticated and request.get("protocol_version") != PROTOCOL_VERSION:
                result = _error(
                    "protocol", "UNSUPPORTED_VERSION", "Bridge protocol mismatch", time.monotonic(), scene_state(scene)
                )
            elif authenticated and float(request.get("expires_at", 0)) < time.time():
                result = _error(
                    "timeout", "TIMEOUT", "Request TTL expired before execution", time.monotonic(), scene_state(scene)
                )
            elif authenticated:
                result = execute_request(_scene_view() or scene, request)
            try:
                valid_request_id = str(uuid.UUID(request_id)) == request_id.casefold()
            except ValueError:
                valid_request_id = False
            if valid_request_id:
                result.update(
                    {
                        "request_id": request_id,
                        "session_id": request.get("session_id"),
                        "nonce": request.get("nonce"),
                        "mac": "",
                    }
                )
                result["mac"] = _sign_message(result, bridge_secret)
                atomic_json(responses / (request_id + ".json"), result)
            processed += 1
        finally:
            claimed.unlink(missing_ok=True)
    return processed
