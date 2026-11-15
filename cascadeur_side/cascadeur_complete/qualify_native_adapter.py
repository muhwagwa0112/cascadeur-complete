"""Explicit setup command: qualify a native adapter in its own disposable tab."""

def command_name():
    return "Cascadeur Complete.Qualify native adapter"


def command_description():
    return "Observe installed-SDK reader, existing-key writer and checkpoint clone in a disposable scene"


def run(scene):
    from .native_adapters import qualify_disposable
    result = qualify_disposable()
    scene.success("Qualified " + result["adapter_id"] + " on " + result["installed_build"])
    return result
