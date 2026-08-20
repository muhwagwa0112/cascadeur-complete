from .runtime import process_pending


def command_name():
    return "Cascadeur Complete.Process Pending"


def command_description():
    return "Process queued Cascadeur Complete MCP requests on the Cascadeur UI thread"


def run(scene):
    count = process_pending(scene, matching_scene_only=True)
    if count:
        scene.success(f"Cascadeur Complete processed {count} request(s)")
