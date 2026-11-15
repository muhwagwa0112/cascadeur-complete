"""Explicit finite full-reader setup, separate from character qualification."""


def command_name():
    return "Cascadeur Complete.Qualify independent scene adapter"


def command_description():
    return "Observe finite independent Transform models, file bootstrap, evaluation and checkpoint; select an empty tab"


def run(scene):
    from .native_interpolation_qualification import qualify_independent_models
    from .native_independent_scene import qualify_independent_scene_adapter
    models = qualify_independent_models()
    adapter = qualify_independent_scene_adapter()
    scene.success("Qualified independent complete-scene bootstrap, evaluation and checkpoint")
    return {"models": models, "scene_adapter": adapter}
