"""Static dependency declarations for the exact owned-pair setup helper.

This module never imports the installed leaf, imports csc, queries a scene,
creates a directory, claims admission, or executes a qualification callback.
Presence and Python shape are prerequisites, not native completion evidence.
"""
from __future__ import annotations

import ast
import hashlib
from pathlib import Path

_PAIR_HELPER = "setup.qualify_owned_pair_geometry"
_LEAF = "native_installed_update_facts.py"
_MAXIMUM_SOURCE_BYTES = 2 * 1024**2


def validate_declared_pair_dependency(plan, bridge_directory, loaded_fingerprint):
    """Consume an already authenticated exact setup sidecar before its claim.

    Returns False when the plan does not contain the pair helper. The caller
    supplies the native package directory from its own __file__, never wire
    input. A declaration match does not enable any native adapter.
    """
    if not isinstance(plan, dict) or not isinstance(plan.get("steps"), list):
        raise ValueError("AUTHENTICATED_SETUP_PLAN_REQUIRED")
    if not any(step.get("operation") == _PAIR_HELPER for step in plan["steps"]):
        return False
    if plan.get("loaded_fingerprint") != loaded_fingerprint:
        raise ValueError("PAIR_SETUP_LOADED_PACKAGE_DIFFERS")
    expected = plan.get("helper_files", {}).get(_LEAF)
    if not isinstance(expected, str) or len(expected) != 64:
        raise ValueError("INSTALLED_UPDATE_FACTS_IMPLEMENTATION_REQUIRED")
    path = Path(bridge_directory) / _LEAF
    if not path.is_file() or path.is_symlink():
        raise ValueError("INSTALLED_UPDATE_FACTS_IMPLEMENTATION_REQUIRED")
    with path.open("rb") as stream:
        raw = stream.read(_MAXIMUM_SOURCE_BYTES + 1)
    if len(raw) > _MAXIMUM_SOURCE_BYTES:
        raise ValueError("INSTALLED_UPDATE_FACTS_SOURCE_BUDGET_EXCEEDED")
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError("INSTALLED_UPDATE_FACTS_DECLARED_BYTES_DIFFER")
    try:
        tree = ast.parse(raw, filename=str(path), feature_version=(3, 11))
    except (SyntaxError, ValueError) as error:
        raise ValueError("INSTALLED_UPDATE_FACTS_DECLARATION_INVALID") from error
    functions = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                 and node.name == "extract_installed_update_facts"]
    if len(functions) != 1 or not isinstance(functions[0], ast.FunctionDef):
        raise ValueError("INSTALLED_UPDATE_FACTS_SYNCHRONOUS_DECLARATION_REQUIRED")
    function = functions[0]
    arguments = function.args
    positional = arguments.posonlyargs + arguments.args
    if (function.decorator_list or [argument.arg for argument in positional] != ["model", "update", "updater"]
            or arguments.defaults or arguments.vararg or arguments.kwarg or arguments.kwonlyargs):
        raise ValueError("INSTALLED_UPDATE_FACTS_EXACT_DECLARATION_REQUIRED")
    return True
