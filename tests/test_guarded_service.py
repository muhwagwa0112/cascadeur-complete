"""Argument-sensitive read lanes use the real host service, with no UI."""
from types import SimpleNamespace

import pytest

from cascadeur_complete import service as module
from cascadeur_complete.models import ErrorCode
from cascadeur_complete.paths import RuntimePaths
from cascadeur_complete.product_catalog import PRODUCT_CATALOG


def test_effectful_read_arguments_are_refused_before_execute_batch_or_job(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "discover_installation", lambda: {"version": PRODUCT_CATALOG.supported_build})
    monkeypatch.setattr(module, "load_csc_schema", lambda **_: {})
    monkeypatch.setattr(module, "discover_commands", lambda: [])
    monkeypatch.setattr(module, "available_dependencies", lambda: {})
    def no_dispatch(*_, **__):
        raise AssertionError("Evaluation disguised as a read must not reach the bridge")
    service = module.CascadeurService(RuntimePaths.discover(tmp_path), SimpleNamespace(execute=no_dispatch, runtime_status={}))
    service._scene_available = True
    service._rebuild_features()
    args = {"ids": ["p"], "refresh": True}
    direct = service.execute("transform_get", "animation.transform_get", args)
    batch = service.batch("transform_get", [{"name": "animation.transform_get", "arguments": args}], scene_id=None, expected_revision=None)
    job = service.submit_job("transform_get", "animation.transform_get", args)
    assert direct.error_code == batch.error_code == ErrorCode.CONFIRMATION_REQUIRED
    assert job["error_code"] == "CONFIRMATION_REQUIRED"
    assert direct.dispatched is False and batch.dispatched is False
    assert not list(service.paths.jobs.glob("*.json"))


def test_host_failure_retains_native_receipt_identity(monkeypatch):
    from cascadeur_complete.host_postconditions import HostPostconditionsMixin, CommitObservation
    from cascadeur_complete.models import ResultEnvelope, ExecutionMode
    class Host(HostPostconditionsMixin):
        def _check_settled_writes(self, *args):
            return module.CascadeurService._host_error("rotation_keys", ErrorCode.POSTCONDITION_FAILED, "missing actual readback")
    result = ResultEnvelope(ok=True, feature_id="rotation_keys", execution_mode=ExecutionMode.NATIVE,
        request_id="original", receipt_id="original", outcome="succeeded", dispatched=True, phase="terminal")
    record = SimpleNamespace(operation=SimpleNamespace(name="animation.rotation_keys_set"), feature_id="rotation_keys")
    failed = Host()._apply_host_postconditions(record, result, CommitObservation(1))
    assert not failed.ok and failed.request_id == "original" and failed.receipt_id == "original"
    assert failed.outcome == "succeeded" and failed.dispatched is True
    assert failed.quality == "unverified"
