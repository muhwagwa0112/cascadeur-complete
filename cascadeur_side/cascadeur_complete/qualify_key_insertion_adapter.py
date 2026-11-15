"""Explicit absent-frame insertion observation; never runs on import."""


def command_name():
    return "Cascadeur Complete.Qualify key insertion adapter"


def command_description():
    return "Observe bounded new position keys and register the owned-checkpoint guarded route; requires current-process finite-model qualification and an empty tab"


def run(scene):
    from .native_key_insertion import qualify_key_insertion

    result = qualify_key_insertion()
    if result.get("status") != "observed" or result.get("phase") != "complete":
        raise RuntimeError("KEY_INSERTION_QUALIFICATION_INCOMPLETE")
    from .native_key_insertion_adapter import register_key_insertion_adapter
    result["guarded_registration"] = register_key_insertion_adapter()
    result["production_registered"] = True
    result["recipe_topology_write"] = False
    return result
