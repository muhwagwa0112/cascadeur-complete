from __future__ import annotations

_HANDLERS = {}


def handler(*operation_names):
    def register(function):
        for name in operation_names:
            if name in _HANDLERS:
                raise RuntimeError("Duplicate Cascadeur Complete handler: " + name)
            _HANDLERS[name] = function
        return function

    return register


def dispatch(operation_name, scene, arguments, request, context):
    function = _HANDLERS.get(operation_name)
    if function is None:
        return False, None
    return True, function(scene, arguments, request, context)


def registered_operations():
    return tuple(sorted(_HANDLERS))
