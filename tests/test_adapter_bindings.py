"""Adapter bindings, product catalog rows and bridge handlers must agree."""

from __future__ import annotations

from cascadeur_complete.adapter_bindings import BINDINGS, BY_FEATURE
from cascadeur_complete.product_catalog import PRODUCT_CATALOG
from cascadeur_complete.service import HOST_POSTCONDITIONS
from tests.test_postcondition_contract import bridge  # noqa: F401  (fixture)


def test_catalog_rows_match_adapter_bindings():
    for binding in BINDINGS:
        row = PRODUCT_CATALOG.by_id[binding.feature_id]
        assert row.implementation_status == "implemented", binding.feature_id
        assert row.operation == binding.operation == row.route
        assert row.adapter_id == f"cascadeur_2026_1.{binding.operation}"
        assert row.postconditions == binding.postconditions
        assert dict(row.fixed_arguments) == dict(binding.fixed_arguments)
        assert binding.replaces is None or binding.replaces not in PRODUCT_CATALOG.by_id


def test_every_binding_operation_has_a_bridge_handler(bridge):  # noqa: F811
    _runtime, registry = bridge
    registered = set(registry.registered_operations())
    host_only = {"system.ui_file_flow"} & set(HOST_POSTCONDITIONS)
    assert sorted({item.operation for item in BINDINGS} - registered - host_only) == []


def test_shared_operations_are_disambiguated_by_fixed_arguments():
    by_operation: dict[str, list] = {}
    for binding in BINDINGS:
        by_operation.setdefault(binding.operation, []).append(binding)
    for operation, bindings in by_operation.items():
        if len(bindings) < 2 or operation == "system.ui_file_flow":
            # UI file flows are disambiguated by the per-feature dialog registry.
            continue
        signatures = {tuple(sorted(item.fixed_arguments.items())) for item in bindings}
        # Features sharing an operation must differ in fixed arguments unless they
        # are documented aliases with an identical contract (e.g. Root Constraint).
        contracts = {(tuple(sorted(item.fixed_arguments.items())), item.postconditions) for item in bindings}
        assert len(signatures) == len(contracts), operation


def test_binding_lookup_is_complete():
    assert set(BY_FEATURE) == {item.feature_id for item in BINDINGS}
