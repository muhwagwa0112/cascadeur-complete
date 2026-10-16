"""Host ↔ bridge operation contract.

The host and the Cascadeur bridge each keep their own list of operation names
and their own idea of which operations are read-only. These tests pin both
sides together so a refactor on either side cannot silently drift.

The ``KNOWN_*`` sets are deliberate snapshots of today's gaps
(docs/REFACTOR_PREP.md §5). Fixing a gap makes its test fail on purpose:
remove the entry in the same change.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from cascadeur_complete.adapter_bindings import BINDINGS
from cascadeur_complete.product_catalog import PRODUCT_CATALOG
from cascadeur_complete.service import CascadeurService
from tests.bridge_support import inline_operations, loaded_bridge

HOST_ROOT = Path(__file__).parents[1] / "src" / "cascadeur_complete"
BRIDGE_FAMILIES = (
    "animation",
    "editing",
    "generation",
    "io",
    "layer",
    "mesh",
    "object",
    "objects",
    "physics",
    "render",
    "rig",
    "safety",
    "scene",
    "selection",
    "system",
    "timeline",
    "view",
)
OPERATION = re.compile(r"^(?:" + "|".join(BRIDGE_FAMILIES) + r")\.[a-z_]*[a-z]$")

# Sent by the host but executed host-side or deliberately absent from the bridge.
HOST_ONLY_OPERATIONS = {
    # UIA file-dialog flow; its in-app half is system.action_dispatch.
    "system.ui_file_flow",
    # Gated: export_vrm is reported unsupported_version.
    "io.export_vrm",
    # Developer-only generic executors; tests/test_bridge_security.py forbids them in the bridge.
    "system.csc_query",
    "system.csc_mutate",
    "system.developer_execute_python",
}

# Bridge handlers the host never sends (system.tools only appears in the host's
# fallback read-only table). Remove or bind them.
KNOWN_UNREFERENCED_BRIDGE_OPERATIONS = {
    "system.tools",
    "physics.collision_material",
    "physics.fulcrum_point",
    "physics.mass_set",
    "render.mesh_material",
}

# Host sends these without a confirmation token, but the bridge requires one.
KNOWN_READ_ONLY_MISMATCHES: set[str] = set()

# Host treats these as mutations while the bridge accepts them without a token.
# system.view_mode: the bridge exempts its get/list actions. safety.snapshot and
# safety.rollback_internal: issued by the host itself inside an already-gated change.
KNOWN_HOST_STRICTER = {"system.view_mode", "safety.snapshot", "safety.rollback_internal"}


def _server_operations() -> set[str]:
    tree = ast.parse((HOST_ROOT / "server.py").read_text(encoding="utf-8"))
    return {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and OPERATION.match(node.value)
    }


def _constructed_operations() -> set[str]:
    """Names passed as ``Operation(name="...")`` anywhere in the host package."""
    names: set[str] = set()
    for path in HOST_ROOT.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not (isinstance(node, ast.Call) and getattr(node.func, "id", None) == "Operation"):
                continue
            for keyword in node.keywords:
                if keyword.arg == "name" and isinstance(keyword.value, ast.Constant):
                    names.add(keyword.value.value)
    return {name for name in names if OPERATION.match(name)}


def _host_operations() -> set[str]:
    catalog = {item.operation for item in PRODUCT_CATALOG.features if item.operation}
    bindings = {item.operation for item in BINDINGS}
    return {
        name for name in catalog | bindings | _server_operations() | _constructed_operations() if OPERATION.match(name)
    }


def _host_is_mutating(name: str) -> bool:
    # The classifier reads only the catalog and a literal table, never instance state.
    return CascadeurService._operation_is_mutating(None, name)  # type: ignore[arg-type]


@pytest.fixture(scope="module")
def bridge():
    with loaded_bridge("cascadeur_complete_bridge_operation_contract") as loaded:
        yield loaded


@pytest.fixture(scope="module")
def bridge_operations(bridge) -> set[str]:
    _runtime, registry = bridge
    return set(registry.registered_operations()) | inline_operations()


def test_inline_operation_scan_finds_the_inline_chain():
    inline = inline_operations()
    assert {"system.status", "timeline.set_frame", "safety.snapshot", "system.undo"} <= inline


def test_every_host_operation_is_handled_by_the_bridge(bridge_operations):
    unhandled = _host_operations() - bridge_operations
    assert unhandled == HOST_ONLY_OPERATIONS


def test_every_bridge_operation_is_reachable_from_the_host(bridge_operations):
    unreferenced = bridge_operations - _host_operations()
    assert unreferenced == KNOWN_UNREFERENCED_BRIDGE_OPERATIONS


def test_host_read_only_operations_are_read_only_in_the_bridge(bridge, bridge_operations):
    runtime, _registry = bridge
    mismatches = {
        name
        for name in _host_operations() & bridge_operations
        if not _host_is_mutating(name) and runtime._operation_is_mutating({"name": name, "arguments": {}})
    }
    assert mismatches == KNOWN_READ_ONLY_MISMATCHES


def test_bridge_read_only_operations_are_read_only_on_the_host(bridge, bridge_operations):
    runtime, _registry = bridge
    stricter = {
        name
        for name in _host_operations() & bridge_operations
        if _host_is_mutating(name) and not runtime._operation_is_mutating({"name": name, "arguments": {}})
    }
    assert stricter == KNOWN_HOST_STRICTER


def test_every_bridge_view_operation_yields_to_the_event_loop(bridge):
    from cascadeur_complete.service import VIEW_OPERATIONS

    runtime, _registry = bridge
    assert set(VIEW_OPERATIONS) <= set(runtime.YIELDING_OPERATIONS)
