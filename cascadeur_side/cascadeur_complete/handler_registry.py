from __future__ import annotations

_HANDLERS = {}
_POSTCONDITIONS = {}


def handler(*operation_names, postconditions=()):
    """Register a bridge handler and the postconditions it asserts on success.

    ``postconditions`` is either a tuple applied to every operation name or a
    mapping from operation name to tuple.  A declared postcondition must be
    enforced by the handler itself (it raises ``AssertionError`` when the
    observed state differs), because the runtime reports every declared id as
    satisfied whenever the handler returns normally.  Handlers whose checks
    depend on arguments return ``observed_postconditions`` in their result
    instead, which replaces the static declaration for that call.
    """

    def register(function):
        for name in operation_names:
            if name in _HANDLERS:
                raise RuntimeError("Duplicate Cascadeur Complete handler: " + name)
            _HANDLERS[name] = function
            declared = postconditions.get(name, ()) if isinstance(postconditions, dict) else postconditions
            _POSTCONDITIONS[name] = tuple(declared)
        return function

    return register


def dispatch(operation_name, scene, arguments, request, context):
    function = _HANDLERS.get(operation_name)
    if function is None:
        return False, None
    return True, function(scene, arguments, request, context)


def declared_postconditions(operation_name):
    return _POSTCONDITIONS.get(operation_name, ())


def registered_operations():
    return tuple(sorted(_HANDLERS))
