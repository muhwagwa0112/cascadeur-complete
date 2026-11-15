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


def transact(method, name, func, before_write=None):
    """Run ``method(name, func)`` (a DomainScene ``modify*``) and surface failures.

    Cascadeur logs an exception raised inside a transaction and aborts it, but
    does not propagate it to the caller, so a failed edit looked like a silent
    no-op and surfaced later as a misleading postcondition. The exception is
    re-raised inside (keeping Cascadeur's abort) and raised again here.
    """
    errors = []
    permit = {"active": True, "entered": False, "completed": False}

    def guarded(*args):
        try:
            if not permit["active"] or permit["entered"]:
                raise RuntimeError("Callback permit expired or already consumed")
            permit["entered"] = True
            from . import guarded_runtime
            guarded_runtime.before_write(before_write)
            result = func(*args)
            guarded_runtime.finish_write()
            permit["completed"] = True
            return result
        except Exception as exc:
            errors.append(exc)
            raise

    try:
        result = method(name, guarded)
    finally:
        permit["active"] = False
    if errors:
        raise errors[0]
    if not permit["completed"]:
        raise RuntimeError("Native callback did not complete synchronously")
    return result
