"""Explicit absent-frame insertion observation; never runs on import."""


def command_name():
    return "Cascadeur Complete.Qualify key insertion adapter"


def command_description():
    return "Observe bounded new position keys in retained disposable scenes; requires explicit current-process finite-model qualification and an empty tab"


def run(scene):
    from .native_key_insertion import qualify_key_insertion

    result = qualify_key_insertion()
    if result.get("status") != "observed" or result.get("phase") != "complete":
        raise RuntimeError("KEY_INSERTION_QUALIFICATION_INCOMPLETE")
    return result
