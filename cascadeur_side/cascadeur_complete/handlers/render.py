from __future__ import annotations

from pathlib import Path

from ..handler_registry import handler


@handler("render.camera_create", "render.camera_aim", "render.light_point", "render.light_spot")
def create_render_object(scene, _arguments, request, context):
    operation = str((request.get("operations") or [{}])[0].get("name", ""))
    runners = {
        "render.camera_create": ("commands.add.camera.add_camera", "Camera"),
        "render.camera_aim": ("commands.add.camera.add_camera_with_aim", "Camera"),
        "render.light_point": ("commands.add.add_point_light", "PointLight"),
        "render.light_spot": ("commands.add.add_spot_light", "SpotLight"),
    }
    module_name, behaviour_name = runners[operation]
    module = __import__(module_name, fromlist=["run"])
    viewer = context["domain_scene"](scene).model_viewer()
    before_ids = {context["id_string"](item) for item in viewer.get_objects()}
    behaviours = viewer.behaviour_viewer()
    try:
        before_behaviour_count = len(list(behaviours.get_behaviours(behaviour_name)))
    except RuntimeError:
        before_behaviour_count = 0
    module.run(context["domain_scene"](scene))
    after_ids = {context["id_string"](item) for item in viewer.get_objects()}
    created_ids = sorted(after_ids - before_ids)
    try:
        after_behaviour_count = len(list(behaviours.get_behaviours(behaviour_name)))
    except RuntimeError:
        after_behaviour_count = 0
    if not created_ids:
        raise AssertionError("POSTCONDITION_FAILED: render object command created no objects")
    if operation.startswith("render.light_") and after_behaviour_count <= before_behaviour_count:
        raise AssertionError("POSTCONDITION_FAILED: light behaviour count did not increase")
    return {
        "operation": operation,
        "created_ids": created_ids,
        "before_behaviour_count": before_behaviour_count,
        "after_behaviour_count": after_behaviour_count,
    }, []


def _vector(value):
    converter = getattr(value, "tolist", None)
    if callable(converter):
        value = converter()
    try:
        return [float(item) for item in value]
    except TypeError:
        return None


def _viewport_row(viewport, active, context):
    domain_viewport = viewport.domain_viewport()
    camera = domain_viewport.camera_struct()
    return {
        "id": context["json_safe"](context["read_member"](domain_viewport, "id")),
        "active": viewport == active,
        "main": bool(context["read_member"](domain_viewport, "is_main")),
        "selectable_types": context["json_safe"](viewport.selectable_types()),
        "camera": {
            "position": _vector(context["read_member"](camera, "position")),
            "target": _vector(context["read_member"](camera, "target")),
            "type": str(context["read_member"](context["read_member"](camera, "type"), "name")),
        },
    }


@handler("render.viewport_state")
def viewport_state(_scene, _arguments, _request, context):
    view_scene = context["scene_view"]()
    active = view_scene.active_viewport()
    rows = [_viewport_row(viewport, active, context) for viewport in view_scene.viewports()]
    return {"viewports": rows, "count": len(rows)}, []


@handler("render.camera_catalog")
def camera_catalog(_scene, _arguments, _request, context):
    view_scene = context["scene_view"]()
    active_viewport = view_scene.active_viewport()
    rows = []
    for camera in context["csc"].view.camera_utils.get_cameras(view_scene):
        rows.append(
            {
                "id": context["id_string"](context["read_member"](camera, "id")),
                "name": str(context["read_member"](camera, "name")),
                "custom": bool(context["read_member"](camera, "isCustom")),
                "active": bool(context["csc"].view.camera_utils.is_camera_active(active_viewport, camera)),
            }
        )
    return {"cameras": rows}, []


@handler("render.camera_view")
def camera_view(_scene, arguments, _request, context):
    view_scene = context["scene_view"]()
    viewport = view_scene.active_viewport()
    domain_viewport = viewport.domain_viewport()
    camera = domain_viewport.camera_struct()
    for name in ("position", "target"):
        if arguments.get(name) is not None:
            value = tuple(float(item) for item in arguments[name])
            if len(value) != 3:
                raise ValueError(name + " must contain exactly three numbers")
            setattr(camera, name, value)
    if arguments.get("camera_type"):
        camera_type = str(arguments["camera_type"]).upper()
        try:
            camera.type = getattr(context["csc"].view.CameraType, camera_type)
        except AttributeError as exc:
            raise ValueError("camera_type must be PERSPECTIVE or ISOMETRIC") from exc
    domain_viewport.set_camera_struct(camera)
    observed = _viewport_row(viewport, viewport, context)["camera"]
    for name in ("position", "target"):
        expected = arguments.get(name)
        if expected is not None and any(
            abs(actual - float(wanted)) > 1e-4 for actual, wanted in zip(observed[name], expected, strict=True)
        ):
            raise AssertionError("POSTCONDITION_FAILED: camera " + name + " differs")
    if arguments.get("camera_type") and observed["type"].upper() != str(arguments["camera_type"]).upper():
        raise AssertionError("POSTCONDITION_FAILED: camera type differs")
    return observed, []


@handler("render.camera_activate")
def camera_activate(_scene, arguments, _request, context):
    view_scene = context["scene_view"]()
    viewport = view_scene.active_viewport()
    requested = str(arguments["camera_id"])
    cameras = context["csc"].view.camera_utils.get_cameras(view_scene)
    camera = next(
        (item for item in cameras if context["id_string"](context["read_member"](item, "id")) == requested),
        None,
    )
    if camera is None:
        raise KeyError("Unknown camera ID: " + requested)
    context["csc"].view.camera_utils.set_camera_active(viewport, camera)
    if not context["csc"].view.camera_utils.is_camera_active(viewport, camera):
        raise AssertionError("POSTCONDITION_FAILED: camera did not become active")
    return {"camera_id": requested, "active": True}, []


def _render_parameters(arguments, context):
    width = int(arguments.get("width", 1920))
    height = int(arguments.get("height", 1080))
    samples = int(arguments.get("samples", 64))
    if not 16 <= width <= 16384 or not 16 <= height <= 16384:
        raise ValueError("width and height must be between 16 and 16384")
    if not 1 <= samples <= 4096:
        raise ValueError("samples must be between 1 and 4096")
    parameters = context["csc"].tools.RenderParameters()
    parameters.width = width
    parameters.height = height
    parameters.samples = samples
    return parameters, {"width": width, "height": height, "samples": samples}


@handler("render.viewport_capture", "render.image", "io.export_image")
def render_to_file(_scene, arguments, _request, context):
    path = Path(str(arguments["path"]))
    if not path.is_absolute():
        raise ValueError("An absolute output path is required")
    if not path.parent.is_dir():
        raise FileNotFoundError("Output directory does not exist: " + str(path.parent))
    parameters, settings = _render_parameters(arguments, context)
    view_scene = context["scene_view"]()
    if view_scene is None:
        raise RuntimeError("No application scene is available")
    renderer = context["csc"].app.get_application().get_tools_manager().get_tool("RenderToFile")
    renderer.take_image(view_scene, parameters, str(path))
    kind = "image"
    return {
        "path": str(path),
        "kind": kind,
        "scheduled": True,
        "parameters": settings,
    }, []
