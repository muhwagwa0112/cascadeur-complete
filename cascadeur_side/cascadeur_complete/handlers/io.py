from __future__ import annotations

from pathlib import Path

from ..handler_registry import handler


def _fbx_loader(context):
    tool = context["csc"].app.get_application().get_tools_manager().get_tool("FbxSceneLoader")
    return tool.get_fbx_loader(context["scene_view"]())


@handler("io.import_dae")
def import_dae(scene, arguments, _request, context):
    path = Path(str(arguments["path"]))
    if path.suffix.casefold() != ".dae":
        raise ValueError("DAE import requires a .dae file")
    viewer = context["domain_scene"](scene).model_viewer()
    before_ids = {context["id_string"](item) for item in viewer.get_objects()}
    loader = _fbx_loader(context)
    normalized = str(path).replace("\\", "/")
    result = loader.import_scene(normalized)
    after_ids = {context["id_string"](item) for item in viewer.get_objects()}
    created_ids = sorted(after_ids - before_ids)
    execution = "FbxLoader.import_scene"
    if not created_ids:
        result = loader.import_model(normalized)
        after_ids = {context["id_string"](item) for item in viewer.get_objects()}
        created_ids = sorted(after_ids - before_ids)
        execution = "FbxLoader.import_model"
    if not created_ids:
        raise AssertionError("POSTCONDITION_FAILED: DAE import created no scene objects")
    return {
        "path": str(path),
        "created_ids": created_ids,
        "execution": execution,
        "return_value": context["json_safe"](result),
    }, []


@handler("io.export_dae")
def export_dae(_scene, arguments, _request, context):
    path = Path(str(arguments["path"]))
    if path.suffix.casefold() != ".dae":
        raise ValueError("DAE export requires a .dae destination")
    result = _fbx_loader(context).export_all_objects(str(path).replace("\\", "/"))
    if not path.is_file() or path.stat().st_size <= 0:
        raise AssertionError("POSTCONDITION_FAILED: DAE output was not created")
    return {"path": str(path), "bytes": path.stat().st_size, "return_value": context["json_safe"](result)}, []


@handler("io.import_audio")
def import_audio(scene, arguments, _request, context):
    from add_function.topology_add import add_audio

    path = Path(str(arguments["path"]))
    duration = float(arguments.get("duration", 0.0))
    if duration <= 0:
        raise ValueError("duration must be a positive number of seconds")
    domain = context["domain_scene"](scene)
    behaviours = domain.model_viewer().behaviour_viewer()
    try:
        before_count = len(list(behaviours.get_behaviours("Audio")))
    except RuntimeError:
        before_count = 0
    add_audio(domain, str(path).replace("\\", "/"), duration)
    after_count = len(list(behaviours.get_behaviours("Audio")))
    if after_count <= before_count:
        raise AssertionError("POSTCONDITION_FAILED: Audio behaviour count did not increase")
    return {
        "path": str(path),
        "duration": duration,
        "before_count": before_count,
        "after_count": after_count,
    }, []
