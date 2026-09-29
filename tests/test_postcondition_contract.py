"""Every implemented product feature must have each required postcondition
asserted by the Cascadeur bridge or verified by the host.

Live evidence is only recorded when all catalog postconditions are observed,
so an unasserted postcondition silently makes a feature unverifiable.
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
import types
from pathlib import Path

import pytest

from cascadeur_complete.product_catalog import PRODUCT_CATALOG
from cascadeur_complete.service import HOST_POSTCONDITIONS

BRIDGE_ROOT = Path(__file__).parents[1] / "cascadeur_side" / "cascadeur_complete"
PACKAGE = "cascadeur_complete_bridge_contract"


@pytest.fixture(scope="module")
def bridge():
    fake_csc = types.ModuleType("csc")
    previous_csc = sys.modules.get("csc")
    sys.modules["csc"] = fake_csc
    spec = importlib.util.spec_from_file_location(
        PACKAGE, BRIDGE_ROOT / "__init__.py", submodule_search_locations=[str(BRIDGE_ROOT)]
    )
    package = importlib.util.module_from_spec(spec)
    sys.modules[PACKAGE] = package
    spec.loader.exec_module(package)
    try:
        runtime = importlib.import_module(PACKAGE + ".runtime")
        registry = importlib.import_module(PACKAGE + ".handler_registry")
        yield runtime, registry
    finally:
        for name in [item for item in sys.modules if item == PACKAGE or item.startswith(PACKAGE + ".")]:
            del sys.modules[name]
        if previous_csc is None:
            sys.modules.pop("csc", None)
        else:
            sys.modules["csc"] = previous_csc


def _bridge_postconditions(runtime, registry, operation):
    declared = set(registry.declared_postconditions(operation))
    declared |= set(runtime.INLINE_POSTCONDITIONS.get(operation, ()))
    if operation in ("system.undo", "system.redo", "system.action_invoke"):
        declared.add("scene_revision_changed")
    return declared


def _live_features():
    return [
        item
        for item in PRODUCT_CATALOG.core_features
        if item.implementation_status == "implemented"
        and item.operation
        and not item.operation.startswith("host.")
    ]


def test_every_live_feature_postcondition_is_asserted(bridge):
    runtime, registry = bridge
    uncovered = {}
    for feature in _live_features():
        covered = _bridge_postconditions(runtime, registry, feature.operation)
        covered |= set(HOST_POSTCONDITIONS.get(feature.operation, ()))
        missing = sorted(set(feature.postconditions) - covered)
        if missing:
            uncovered[feature.id] = missing
    assert uncovered == {}


def test_every_live_feature_operation_is_executable_by_the_bridge(bridge):
    runtime, registry = bridge
    source = (BRIDGE_ROOT / "runtime.py").read_text(encoding="utf-8")
    registered = set(registry.registered_operations())
    missing = sorted(
        feature.id
        for feature in _live_features()
        if feature.operation not in registered
        and f'"{feature.operation}"' not in source
        and feature.operation not in HOST_POSTCONDITIONS
    )
    assert missing == []


def test_dynamic_postconditions_override_static_declaration(bridge):
    runtime, _registry = bridge
    assert runtime.operation_postconditions(
        "physics.center_of_mass", {}, {"observed_postconditions": ["scene_revision_changed"]}
    ) == ("scene_revision_changed",)
    assert runtime.operation_postconditions("system.undo", {"expect_change": False}, {}) == ()
    assert runtime.operation_postconditions("timeline.set_frame", {}, {}) == ("frame_equals_requested",)
