"""Explicit full reader/checkpoint/evaluation qualification on shipped input."""


def command_name():
    return "Cascadeur Complete.Qualify complete scene adapter"


def command_description():
    return "Load shipped Cascy in owned tabs and observe full reader, checkpoint and evaluation; select an empty tab"


def run(scene):
    from .native_scene_adapter import qualify_scene_adapter
    result = qualify_scene_adapter()
    scene.success("Qualified complete scene checkpoint/evaluation; restore qualification is separate")
    return result
