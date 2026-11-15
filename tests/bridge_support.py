"""Load the Cascadeur-side bridge package outside Cascadeur.

The bridge imports ``csc`` at module level; a bare module stands in for it so
the package imports, and individual tests stub the scene-facing helpers they
exercise. The package is imported under a private name so it never shadows the
host ``cascadeur_complete`` package.
"""

from __future__ import annotations

import ast
import importlib
import importlib.util
import sys
import types
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

BRIDGE_ROOT = Path(__file__).parents[1] / "cascadeur_side" / "cascadeur_complete"


@contextmanager
def loaded_bridge(package: str) -> Iterator[tuple[types.ModuleType, types.ModuleType]]:
    """Yield ``(runtime, handler_registry)`` imported under ``package``."""
    fake_csc = types.ModuleType("csc")
    previous_csc = sys.modules.get("csc")
    sys.modules["csc"] = fake_csc
    spec = importlib.util.spec_from_file_location(
        package, BRIDGE_ROOT / "__init__.py", submodule_search_locations=[str(BRIDGE_ROOT)]
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[package] = module
    spec.loader.exec_module(module)
    try:
        runtime = importlib.import_module(package + ".runtime")
        registry = importlib.import_module(package + ".handler_registry")
        yield runtime, registry
    finally:
        for name in [item for item in sys.modules if item == package or item.startswith(package + ".")]:
            del sys.modules[name]
        if previous_csc is None:
            sys.modules.pop("csc", None)
        else:
            sys.modules["csc"] = previous_csc


def inline_operations() -> set[str]:
    """Operation names handled by the inline chain in ``runtime._run_operation``."""
    tree = ast.parse((BRIDGE_ROOT / "runtime.py").read_text(encoding="utf-8"))
    function = next(
        node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "_run_operation"
    )
    names: set[str] = set()
    for node in ast.walk(function):
        if not (isinstance(node, ast.Compare) and isinstance(node.left, ast.Name) and node.left.id == "name"):
            continue
        for operator, comparator in zip(node.ops, node.comparators, strict=True):
            if isinstance(operator, ast.Eq) and isinstance(comparator, ast.Constant):
                names.add(comparator.value)
            elif isinstance(operator, ast.In) and isinstance(comparator, (ast.Tuple, ast.Set, ast.List)):
                names.update(item.value for item in comparator.elts if isinstance(item, ast.Constant))
    return names
