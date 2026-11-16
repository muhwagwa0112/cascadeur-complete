"""Explicit setup command: qualify a native adapter in its own disposable tab."""

def command_name():
    return "Cascadeur Complete.Qualify native adapter"


def command_description():
    return "Authenticated setup only: observe finite native adapter and retain its qualification tabs"


def run(scene):
    from .incident_admission import assert_current_setup_admission
    assert_current_setup_admission()
    from .native_adapters import qualify_disposable
    result = qualify_disposable()
    return result
