"""Explicit finite motion setup; never runs on package import."""


def command_name():
    return "Cascadeur Complete.Qualify independent motion adapter"


def command_description():
    return "Observe finite interpolation and existing-position-key writes in owned disposable scenes; select an empty tab"


def run(scene):
    from .native_interpolation_qualification import qualify_independent_models
    from .native_independent_position import qualify_independent_position_writer
    models = qualify_independent_models()
    writer = qualify_independent_position_writer()
    scene.success("Qualified independent position models and existing-key writer")
    return {"models": models, "writer": writer}
