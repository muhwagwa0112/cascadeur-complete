"""Explicit finite selected-object export setup after complete scene setup."""


def command_name():
    return "Cascadeur Complete.Qualify independent export adapter"


def command_description():
    return "Observe two animated SDK exports and exact FBX settings; select an empty tab after complete scene qualification"


def run(scene):
    from .native_export_adapter import qualify_and_register_export
    result = qualify_and_register_export()
    scene.success("Qualified independent selected-object export; target roundtrip and quality remain unverified")
    return result
