"""The bridge surfaces exceptions that Cascadeur swallows inside a transaction."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REGISTRY = Path(__file__).parents[1] / "cascadeur_side" / "cascadeur_complete" / "handler_registry.py"


def _registry():
    spec = importlib.util.spec_from_file_location("cascadeur_complete_bridge_registry", REGISTRY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _swallowing_modify(log):
    # Cascadeur logs a transaction exception, aborts the edit and returns.
    def modify(name, func):
        try:
            func("model", "update")
        except Exception as exc:
            log.append((name, type(exc).__name__))
        return True

    return modify


def test_transact_raises_the_swallowed_exception_after_abort():
    log = []

    def edit(_model, _update):
        raise ValueError("no Enforce Global")

    with pytest.raises(ValueError, match="no Enforce Global"):
        _registry().transact(_swallowing_modify(log), "edit", edit)
    # Re-raised inside, so Cascadeur still aborted the transaction.
    assert log == [("edit", "ValueError")]


def test_transact_passes_arguments_and_returns_result():
    seen = []
    result = _registry().transact(_swallowing_modify([]), "edit", lambda *args: seen.append(args))
    assert result is True
    assert seen == [("model", "update")]
