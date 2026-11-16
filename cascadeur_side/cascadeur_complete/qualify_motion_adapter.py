"""Explicit finite motion setup; never runs on package import."""


def command_name():
    return "Cascadeur Complete.Qualify independent motion adapter"


def command_description():
    return "Authenticated setup only: observe finite interpolation and position writes; retain fixtures"


def run(scene):
    from .incident_admission import assert_current_setup_admission
    assert_current_setup_admission()
    from .native_interpolation_qualification import ensure_independent_models
    from .native_independent_position import qualify_independent_position_writer
    models = ensure_independent_models()
    writer = qualify_independent_position_writer()
    return {"models": models, "writer": writer}
