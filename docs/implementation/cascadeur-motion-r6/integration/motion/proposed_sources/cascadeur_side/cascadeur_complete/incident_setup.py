"""Finite setup plans, exact operator signatures and private native dispatch input.

Approval tokens are issued only by the local operator command after reviewing the
immutable plan. The MCP prepare/commit interface does not issue its own approval.
"""
from __future__ import annotations

from dataclasses import asdict
import hashlib
from pathlib import Path
import time
import uuid

from . import incident_policy as p
from . import incident_store as store

PURPOSE = b"cascadeur-complete/explicit-setup-plan/v1\0"
APPROVAL = b"cascadeur-complete/explicit-setup-operator/v1\0"
_HELPERS = {
    "setup.qualify_native_adapter": ("native_adapters.py", 2, 5),
    "setup.qualify_independent_models": ("native_interpolation_qualification.py", 1, 2),
    "setup.qualify_independent_position_writer": ("native_independent_position.py", 1, 2),
    "setup.qualify_geometry_calculation": ("native_geometry_qualification.py", 1, 2),
    "setup.qualify_owned_pair_geometry": ("native_owned_pair_binding.py", 1, 2),
}
_SEMANTIC_LIMITS = {"setup.qualify_geometry_calculation": {
    "maximum_geometry_calculations": 5, "maximum_evaluations": 2, "maximum_driver_mutations": 1},
    "setup.qualify_owned_pair_geometry": {"maximum_geometry_calculations": 10,
        "maximum_evaluations": 2, "maximum_driver_mutations": 1, "maximum_update_graph_captures": 2}}


def _bridge_directory():
    if (Path(__file__).parent / "guarded_runtime.py").is_file():
        return Path(__file__).parent
    source = Path(__file__).resolve().parents[2] / "cascadeur_side" / "cascadeur_complete"
    return source if source.is_dir() else None


def helper_bytes():
    # Full loaded code, not only the top-level helper source. This includes
    # nested fixture writers, callbacks and their admission checks.
    root = _bridge_directory()
    if root is None:
        from .package_fingerprint import expected_bridge_manifest
        manifest = expected_bridge_manifest()
        if manifest is None:
            raise p.EvidenceUnavailable("HOST_BRIDGE_MANIFEST_UNAVAILABLE")
        return manifest["files"]
    return {str(path.relative_to(root)).replace("\\", "/"): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(root.rglob("*.py"))}


def validate_helper_bytes(plan):
    if plan["helper_files"] != helper_bytes() or plan["loaded_fingerprint"] != p.digest(helper_bytes()):
        raise p.PolicyError("SETUP_HELPER_LOADED_BYTES_CHANGED")


def prepare(root, steps, runtime_epoch, loaded_fingerprint, workspace):
    from .incident_admission import PersistedEvidence, snapshot, intent_for
    if (not isinstance(steps, list) or not steps or len(set(steps)) != len(steps)
            or any(step not in _HELPERS for step in steps)):
        raise p.PolicyError("EXACT_FINITE_SETUP_SEQUENCE_REQUIRED")
    if "setup.qualify_independent_position_writer" in steps:
        writer = steps.index("setup.qualify_independent_position_writer")
        if "setup.qualify_independent_models" not in steps or steps.index("setup.qualify_independent_models") > writer:
            raise p.PolicyError("SETUP_MODEL_QUALIFICATION_MUST_PRECEDE_WRITER")
    workspace = Path(workspace).absolute()
    if workspace.exists():
        raise p.PolicyError("SETUP_WORKSPACE_MUST_BE_FRESH")
    if workspace.parent != (Path(root).resolve() / "snapshots"):
        raise p.PolicyError("SETUP_WORKSPACE_MUST_BE_OWNED_SNAPSHOT_DIRECTORY")
    parent = store.physical_identity(workspace.parent)
    if not isinstance(runtime_epoch, str) or not runtime_epoch or loaded_fingerprint != p.digest(helper_bytes()):
        raise p.PolicyError("SETUP_MATCHING_RUNTIME_HANDSHAKE_REQUIRED")
    with store.locked_registry(root) as (registry, stores):
        active = next(s for s in stores if s.root == Path(root).resolve())
        now = time.time()
        request = {"request_id": str(uuid.uuid4()), "operations": [{"name": steps[0], "arguments": {}}],
            "runtime_epoch": runtime_epoch, "adapter_fingerprint": loaded_fingerprint,
            "source_binding": None, "execution_context": None}
        _, heads = snapshot(registry, stores, request, active)
        plan = {"schema_version": 1, "plan_id": str(uuid.uuid4()), "domain": asdict(active.domain),
            "registry_digest": p.digest(registry), "heads": heads, "runtime_epoch": runtime_epoch,
            "loaded_fingerprint": loaded_fingerprint, "helper_files": helper_bytes(),
            "workspace": str(workspace), "workspace_parent_identity": parent,
            "created_at": now, "expires_at": now+300,
            "steps": [{"operation": step, "workspace_path": str(workspace / str(index)),
                       "maximum_new_tabs": _HELPERS[step][1], "maximum_casc_files": _HELPERS[step][2],
                       "semantic_limits": _SEMANTIC_LIMITS.get(step)}
                      for index, step in enumerate(steps)]}
        envelope = store.seal(plan, active.secret, PURPOSE)
        digest = p.digest(envelope)
        store.publish_new(active.directory / "setup-plans" / (digest+".json"), envelope)
        return {"plan_digest": digest, "plan": plan, "approval_required": True}


def approve_local(root, plan_digest):
    """Local operator entry; never called by MCP prepare/commit automatically."""
    active = store.IncidentStore(root)
    value = store.read(active.directory / "setup-plans" / (p._digest_string(plan_digest, "plan digest")+".json"))
    store.verify(value, active.secret, PURPOSE)
    if p.digest(value) != plan_digest or value["expires_at"] <= time.time():
        raise p.PolicyError("SETUP_PLAN_EXPIRED_OR_DIFFERS")
    validate_helper_bytes(value)
    approval = store.seal({"schema_version": 1, "plan_digest": plan_digest,
        "domain": asdict(active.domain), "expires_at": value["expires_at"]}, active.secret, APPROVAL)
    return approval


def validate_setup_plan(active, request, registry, heads):
    operations = request["operations"]
    if len(operations) != 1 or operations[0]["name"] not in _HELPERS:
        raise p.PolicyError("EXACT_SETUP_REQUEST_REQUIRED")
    args = store.exact(operations[0]["arguments"], {"plan_digest", "operator_authorization"})
    digest = p._digest_string(args["plan_digest"], "plan digest")
    plan = store.read(active.directory / "setup-plans" / (digest+".json"))
    store.verify(plan, active.secret, PURPOSE)
    approval = store.exact(args["operator_authorization"], {"schema_version", "plan_digest", "domain", "expires_at", "mac"})
    store.verify(approval, active.secret, APPROVAL)
    if (p.digest(plan) != digest or approval["schema_version"] != 1 or approval["plan_digest"] != digest
            or request["request_id"] != plan["plan_id"]
            or approval["domain"] != asdict(active.domain) or approval["expires_at"] != plan["expires_at"]
            or plan["expires_at"] <= time.time() or plan["registry_digest"] != p.digest(registry)
            or plan["heads"] != heads or plan["runtime_epoch"] != request.get("runtime_epoch")
            or plan["loaded_fingerprint"] != request.get("adapter_fingerprint")
            or operations[0]["name"] != plan["steps"][0]["operation"]):
        raise p.PolicyError("SETUP_PLAN_APPROVAL_SNAPSHOT_DIFFERS")
    validate_helper_bytes(plan)
    if store.physical_identity(Path(plan["workspace"]).parent) != plan["workspace_parent_identity"]:
        raise p.PolicyError("SETUP_WORKSPACE_PARENT_CHANGED")
    # Once claimed, directories may be created only inside the exact manifest.
    return plan
