"""Recovery control boundaries and real journal/filesystem checks, without DCCs."""
import hashlib
import uuid
from types import SimpleNamespace
import pytest

from cascadeur_complete.change_flow import ChangeFlowMixin
from cascadeur_complete.models import ResultEnvelope, ExecutionMode, SourceBinding, RequestReceipt
from cascadeur_complete.paths import RuntimePaths
from cascadeur_complete.request_ledger import canonical_digest
from cascadeur_complete.safety import ChangeManager


@pytest.mark.parametrize("scenario", ["success", "unknown", "stale_snapshot", "stale_source"])
def test_source_bound_recovery_uses_protected_lane_once_and_keeps_original_failure(tmp_path, scenario):
    paths = RuntimePaths.discover(tmp_path)
    ChangeManager(paths)
    request_id, snapshot_id, working_id = (str(uuid.uuid4()) for _ in range(3))
    snapshot = paths.snapshots / (snapshot_id + ".casc")
    working = paths.snapshots / "failed.working.casc"
    snapshot.write_bytes(b"immutable ancestor")
    working.write_bytes(b"partial failed changes")
    manifest = {"snapshot_id": snapshot_id, "path": str(snapshot),
        "sha256": hashlib.sha256(snapshot.read_bytes()).hexdigest(), "working_path": str(working),
        "document_lineage_id": "lineage", "working_scene_instance_id": "failed-instance"}
    binding = {"runtime_epoch": "epoch", "scene_instance_id": "failed-instance", "document_lineage_id": "lineage",
               "scope_digest": "scope", "content_revision": "after"}
    original_scope = {"operation_name": "objects.edit", "snapshot_manifest": manifest}
    post = SourceBinding(binding=binding, scope=original_scope, sample_digest="sample", inputs_digest="inputs",
                         adapter_fingerprint="fingerprint", complete=True)
    args = {"path": str(snapshot), "snapshot_id": snapshot_id, "working_id": working_id,
            "failed_request_id": request_id, "snapshot_manifest_digest": canonical_digest(manifest),
            "post_source_digest": canonical_digest(post.model_dump(mode="json"))}
    recovery = post.model_copy(update={"scope": {"operation_name": "safety.rollback",
        "operation_arguments": args, "operation_arguments_digest": canonical_digest(args),
        "snapshot_manifest": manifest, "recovery": {"failed_request_id": request_id,
            "snapshot_manifest_digest": canonical_digest(manifest), "post_source_digest": args["post_source_digest"]}}})
    original = post.model_copy(update={"binding": post.binding.model_copy(update={"content_revision": "before"})})
    failed = ResultEnvelope(ok=False, feature_id="original", execution_mode=ExecutionMode.NATIVE,
        request_id=request_id, receipt_id=request_id, phase="terminal", outcome="failed_after_dispatch",
        dispatched=True, write_phase="completed", recovery_eligible=True,
        scene_before=original.binding, scene_after=post.binding,
        error_message="original write failed", result={"post_source_binding": post.model_dump(mode="json"),
            "recovery_source_binding": recovery.model_dump(mode="json")})
    receipt = RequestReceipt(request_id=request_id, request_digest="request", operation_digest="operation",
        session_id="session", runtime_epoch="epoch", host_instance_id="host", phase="terminal",
        outcome="failed_after_dispatch", dispatched=True, effect_class="scene", write_phase="completed",
        recovery_eligible=True, scene_before=original.binding, scene_after=post.binding,
        terminal_result=failed.model_dump(mode="json"), seq=1)
    record = SimpleNamespace(mutation_request_id=request_id, source_binding=original,
        snapshot_manifest_id=canonical_digest(manifest), execution_context=None,
        operation=SimpleNamespace(name="objects.edit"))
    request = {"source_binding": original.model_dump(mode="json"), "execution_context": None}

    class Service(ChangeFlowMixin):
        def __init__(self):
            self.paths = paths
            self.calls = []
            self.client = SimpleNamespace(queue=SimpleNamespace(ledger=SimpleNamespace(
                read_receipt=lambda _: receipt, read_request=lambda _: request)))

        def validate_source(self, source, **kwargs):
            self.calls.append("validate")
            return SimpleNamespace(ok=scenario != "stale_source")

        def prepare_change(self, feature, operation, arguments, ttl, **kwargs):
            self.calls.append(("prepare", feature, operation, arguments, kwargs))
            self.recovery_request_id = kwargs["execution_context"]["request_id"]
            return {"ok": True, "confirmation_token": "signed-change-token"}

        def commit_change(self, token, timeout):
            self.calls.append(("commit", token))
            if scenario == "unknown":
                return ResultEnvelope(ok=False, feature_id="change_rollback", execution_mode=ExecutionMode.NATIVE,
                    request_id=self.recovery_request_id, receipt_id=self.recovery_request_id,
                    phase="dispatch_started", outcome="outcome_unknown", write_phase="unknown")
            target = paths.snapshots / (working_id + ".working.casc")
            target.write_bytes(snapshot.read_bytes())
            return ResultEnvelope(ok=True, feature_id="change_rollback", execution_mode=ExecutionMode.NATIVE,
                request_id=self.recovery_request_id, receipt_id=self.recovery_request_id,
                phase="terminal", outcome="succeeded", dispatched=True,
                write_phase="completed", scene_after=post.binding.model_copy(update={"scene_instance_id": "restored"}),
                result={"restored_from": str(snapshot), "working_path": str(target)})

    service = Service()
    if scenario == "stale_snapshot":
        snapshot.write_bytes(b"replaced ancestor")
    result = service._restore_failed_change(record, failed)
    assert not result.ok and result.error_message == "original write failed"
    assert result.request_id == request_id and result.outcome == "failed_after_dispatch"
    assert result.recovery_state == {"success": "recovered", "unknown": "blocked_recovery_outcome_unknown",
        "stale_snapshot": "blocked_recovery_guard", "stale_source": "blocked_recovery_guard"}[scenario]
    expected_calls = int(scenario in {"success", "unknown"})
    assert sum(isinstance(call, tuple) and call[0] == "commit" for call in service.calls) == expected_calls
    service._restore_failed_change(record, failed)
    assert sum(isinstance(call, tuple) and call[0] == "commit" for call in service.calls) == expected_calls
    unknown = failed.model_copy(update={"outcome": "outcome_unknown"})
    assert service._restore_failed_change(record, unknown).recovery_state == "not_eligible"
    first_write_rejection = failed.model_copy(update={"failure_kind": "guard_rejected_before_first_write"})
    assert service._restore_failed_change(record, first_write_rejection).recovery_state == "not_eligible"


def test_runtime_rollback_requires_registered_completion_evidence_for_observed_build():
    from tests.bridge_support import loaded_bridge
    with loaded_bridge("recovery_bound_bridge") as (runtime, _):
        assert runtime._verified_rollback_adapter() is None
        fingerprint = runtime.guards.LOADED_FINGERPRINT
        adapter = SimpleNamespace(verification={"runtime_fingerprint": fingerprint,
            "dispatch_semantics": "synchronous_no_yield", "identity_stable": True,
            "evidence_sha256": "a"*64, "installed_build": "test-build"}, observed_build=lambda: "test-build")
        runtime.guards.register_adapter("safety.rollback", adapter)
        assert runtime._verified_rollback_adapter() is None
        adapter.verification["rollback_completion_observed"] = {"installed_build": "test-build",
            "runtime_fingerprint": fingerprint, "dispatch_semantics": "synchronous_no_yield",
            "evidence_sha256": "b"*64}
        assert runtime._verified_rollback_adapter() is adapter
        adapter.observed_build = lambda: "different-build"
        assert runtime._verified_rollback_adapter() is None
