"""Durable recipe plans, one-run grants, and compare-and-update run state."""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time
import uuid
from pathlib import Path
from typing import Any

from .atomic_queue import atomic_write_json, read_json
from .paths import RuntimePaths
from .queue_auth import load_or_create_secret, sign_payload
from .recipe_models import (
    ArtifactRef, RecipeRunRecord, ScopedAuthorization, StepRecord, WorkflowPlan, canonical_bytes, digest,
)
from .store_lock import process_is_alive, process_start_identity, store_lock
from .stage_contracts import BootstrapGrant, StageEffect

HOST_INSTANCE_ID = str(uuid.uuid4())
TERMINAL_RUNS = frozenset({"succeeded", "failed", "canceled"})
TERMINAL_STEPS = frozenset({"succeeded", "no_change", "skipped", "failed", "canceled"})
_TRANSITIONS = {
    "queued": {"running", "cancel_requested", "blocked", "failed", "canceled"},
    "running": {"running", "cancel_requested", "blocked", "succeeded", "failed", "canceled"},
    "cancel_requested": {"cancel_requested", "blocked", "canceled", "failed"},
    "blocked": {"blocked", "running", "cancel_requested", "failed", "canceled"},
}


class RecipeConflict(ValueError):
    pass


def canonical_id(value: str) -> str:
    try:
        result = str(uuid.UUID(value))
    except (ValueError, TypeError, AttributeError) as exc:
        raise RecipeConflict("Invalid recipe identifier") from exc
    if result != value:
        raise RecipeConflict("Noncanonical recipe identifier")
    return result


def file_sha256(path: Path) -> tuple[str, int]:
    sha = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            sha.update(block)
            size += len(block)
    return sha.hexdigest(), size


def write_immutable(path: Path, value: dict[str, Any]) -> None:
    """Publish complete bytes without ever replacing an existing record."""
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = canonical_bytes(value)
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(12)}.tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            if path.read_bytes() != raw:
                raise RecipeConflict("Immutable recipe record conflict") from None
    finally:
        temporary.unlink(missing_ok=True)


class RecipeRunStore:
    def __init__(self, paths: RuntimePaths):
        self.paths = paths
        self.root = paths.state / "runs"
        self.root.mkdir(parents=True, exist_ok=True)
        self._secret = load_or_create_secret(paths.confirmation_key)
        self.lock_path = self.root / ".writer.lock"

    def _signature(self, kind: str, value: dict[str, Any]) -> str:
        return sign_payload({"domain": "cascadeur-complete-recipe-v1", "kind": kind,
                             "record": {key: item for key, item in value.items() if key != "mac"}}, self._secret)

    def _signed(self, kind: str, value: dict[str, Any]) -> dict[str, Any]:
        return {**value, "mac": self._signature(kind, value)}

    def _verified(self, path: Path, kind: str) -> dict[str, Any]:
        value = read_json(path)
        if not hmac.compare_digest(str(value.get("mac", "")), self._signature(kind, value)):
            raise RecipeConflict("Recipe record authentication failed")
        return value

    def save_plan(self, plan: WorkflowPlan) -> WorkflowPlan:
        with store_lock(self.lock_path):
            path = self.root / "plans" / f"{canonical_id(plan.plan_id)}.json"
            write_immutable(path, self._signed("plan", plan.model_dump(mode="json")))
        return plan

    def read_plan(self, plan_id: str) -> WorkflowPlan:
        value = self._verified(self.root / "plans" / f"{canonical_id(plan_id)}.json", "plan")
        value.pop("mac")
        return WorkflowPlan.model_validate(value)

    def issue_bootstrap(self, plan, run, step, effect: StageEffect, *, attempt_id, request_id):
        """Issue a narrow signed initial-clone capability, never an ordinary write grant."""
        grant = self.read_grant(run.authorization_id)
        self.verify_grant(grant, plan)
        if step.stage != "initial_checkpoint" or effect.step_id != step.step_id:
            raise RecipeConflict("BOOTSTRAP_SCOPE_MISMATCH")
        runtime = plan.runtime_fingerprints
        value = dict(grant_id=str(uuid.uuid4()), authorization_id=grant.authorization_id,
            authorization_digest=digest(grant), plan_digest=plan.plan_digest,
            declaration_digest=step.fixed_parameters_digest, run_id=run.run_id, step_id=step.step_id,
            attempt_id=attempt_id, lease_epoch=run.lease_epoch, request_id=request_id,
            operation_name=effect.operation_name, arguments_digest=effect.arguments_digest,
            source_binding=None if effect.source_binding is None else effect.source_binding.model_dump(mode="json"),
            input_file=None if not effect.input_files else effect.input_files[0].model_dump(mode="json"),
            output_paths=effect.output_paths, runtime_epoch=runtime.get("runtime_epoch"),
            adapter_fingerprint=runtime.get("loaded_adapter_fingerprint"),
            application_build=runtime.get("installation_version"), expires_at=min(grant.expires_at, run.deadline), mac="")
        result = BootstrapGrant.model_validate(self._signed("bootstrap", value))
        with store_lock(self.lock_path):
            write_immutable(self.run_dir(run.run_id) / "bootstrap" / f"{result.grant_id}.json", result.model_dump(mode="json"))
        return result

    def verify_bootstrap(self, value):
        value = BootstrapGrant.model_validate(value)
        stored = BootstrapGrant.model_validate(self._verified(self.run_dir(value.run_id) / "bootstrap" / f"{canonical_id(value.grant_id)}.json", "bootstrap"))
        if value != stored or time.time() >= value.expires_at:
            raise RecipeConflict("BOOTSTRAP_GRANT_INVALID_OR_EXPIRED")
        run = self.read(value.run_id)
        plan = self.read_plan(run.plan_id)
        record = next(item for item in run.steps if item.step_id == value.step_id)
        self.verify_grant(self.read_grant(run.authorization_id), plan)
        if (run.cancel_requested or run.lease_epoch != value.lease_epoch or record.request_id != value.request_id
                or record.attempt_id != value.attempt_id or record.stage_effect is None
                or record.stage_effect.arguments_digest != value.arguments_digest or plan.plan_digest != value.plan_digest):
            raise RecipeConflict("BOOTSTRAP_GRANT_SCOPE_CHANGED")
        return stored

    def authorize(self, plan: WorkflowPlan, expires_at: float) -> ScopedAuthorization:
        now = time.time()
        if not now < expires_at <= now + 86400:
            raise RecipeConflict("Authorization expiry must be in the next 24 hours")
        if plan.blocked_reasons:
            raise RecipeConflict("A blocked plan cannot be authorized")
        payload = dict(
            schema_version=1, authorization_id=str(uuid.uuid4()), plan_id=plan.plan_id,
            plan_digest=plan.plan_digest, scope_digest=plan.scope_digest, issued_at=now,
            expires_at=expires_at, mac="",
        )
        grant = ScopedAuthorization.model_validate(self._signed("grant", payload))
        with store_lock(self.lock_path):
            write_immutable(self.root / "authorizations" / grant.authorization_id / "grant.json", grant.model_dump(mode="json"))
        return grant

    def read_grant(self, authorization_id: str) -> ScopedAuthorization:
        path = self.root / "authorizations" / canonical_id(authorization_id) / "grant.json"
        return ScopedAuthorization.model_validate(self._verified(path, "grant"))

    def verify_grant(self, grant: ScopedAuthorization, plan: WorkflowPlan, *, allow_expired: bool = False) -> None:
        if not hmac.compare_digest(grant.mac, self._signature("grant", grant.model_dump(mode="json"))):
            raise RecipeConflict("Invalid authorization signature")
        if (grant.plan_id, grant.plan_digest, grant.scope_digest) != (plan.plan_id, plan.plan_digest, plan.scope_digest):
            raise RecipeConflict("Authorization does not match the exact plan and scope")
        if not allow_expired and time.time() >= grant.expires_at:
            raise RecipeConflict("Authorization expired; a fresh explicit authorization is required")

    def create(self, plan: WorkflowPlan, grant: ScopedAuthorization, idempotency_key: str) -> RecipeRunRecord:
        if not isinstance(idempotency_key, str) or not 1 <= len(idempotency_key) <= 256:
            raise RecipeConflict("A bounded nonempty idempotency key is required")
        with store_lock(self.lock_path):
            allocation_path = self.root / "authorizations" / grant.authorization_id / "allocation.json"
            if allocation_path.exists():
                self.verify_grant(grant, plan, allow_expired=True)
                allocation = self._verified(allocation_path, "allocation")
                if allocation["idempotency_key_digest"] != digest(idempotency_key) or allocation["plan_digest"] != plan.plan_digest:
                    raise RecipeConflict("Authorization is already assigned to another run")
                try:
                    return self.read(allocation["run_id"])
                except FileNotFoundError as exc:
                    raise RecipeConflict("Interrupted run allocation requires reconciliation; no new run was created") from exc
            self.verify_grant(grant, plan)
            now = time.time()
            run = RecipeRunRecord(
                run_id=str(uuid.uuid4()), plan_id=plan.plan_id, plan_digest=plan.plan_digest,
                authorization_id=grant.authorization_id, idempotency_key=idempotency_key,
                owner_host_instance_id=HOST_INSTANCE_ID, lease_epoch=1, created_at=now, updated_at=now,
                deadline=now + plan.spec.budgets.total_wall_seconds,
                current_binding=plan.spec.input.source_binding,
                steps=tuple(StepRecord(step_id=step.step_id) for step in plan.steps),
            )
            # Reserve the grant before publishing a runnable record. A crash can
            # block this grant, but can never allocate a second dispatching run.
            write_immutable(allocation_path, self._signed("allocation", {
                "run_id": run.run_id, "plan_digest": plan.plan_digest,
                "idempotency_key_digest": digest(idempotency_key),
            }))
            run_dir = self.run_dir(run.run_id)
            run_dir.mkdir(parents=True, exist_ok=True)
            write_immutable(run_dir / "plan.json", self._signed("plan", plan.model_dump(mode="json")))
            write_immutable(run_dir / "grant.json", grant.model_dump(mode="json"))
            write_immutable(run_dir / "owner.json", self._signed("owner", {
                "host_instance_id": HOST_INSTANCE_ID, "pid": os.getpid(),
                "process_started_at": process_start_identity(os.getpid()), "lease_epoch": 1,
            }))
            self._write(run)
            return self.read(run.run_id)

    def run_dir(self, run_id: str) -> Path:
        return self.root / canonical_id(run_id)

    def renew_authorization(self, run_id: str, grant: ScopedAuthorization) -> RecipeRunRecord:
        """Assign a new exact-scope approval to an existing run, never a new run."""
        with store_lock(self.lock_path):
            run = self.read(run_id)
            plan = self.read_plan(run.plan_id)
            self.verify_grant(grant, plan)
            if run.state in TERMINAL_RUNS or time.time() >= run.deadline:
                raise RecipeConflict("A terminal run or exhausted total wall budget cannot be renewed")
            if run.owner_host_instance_id != HOST_INSTANCE_ID:
                raise RecipeConflict("Only the current host lease can attach a fresh authorization")
            allocation_path = self.root / "authorizations" / grant.authorization_id / "allocation.json"
            allocation = {"run_id": run_id, "plan_digest": plan.plan_digest,
                          "idempotency_key_digest": digest(run.idempotency_key)}
            if allocation_path.exists():
                if self._verified(allocation_path, "allocation") != self._signed("allocation", allocation):
                    raise RecipeConflict("Fresh authorization is already allocated to another run")
            else:
                write_immutable(allocation_path, self._signed("allocation", allocation))
            write_immutable(self.run_dir(run_id) / "authorizations" / f"{grant.authorization_id}.json",
                            grant.model_dump(mode="json"))
            if run.authorization_id == grant.authorization_id:
                return run
            value = run.model_dump(mode="json")
            value.update(authorization_id=grant.authorization_id, seq=run.seq + 1, updated_at=time.time(), mac="")
            self._write(RecipeRunRecord.model_validate(value))
            return self.read(run_id)

    def read(self, run_id: str) -> RecipeRunRecord:
        value = self._verified(self.run_dir(run_id) / "manifest.json", "run")
        run = RecipeRunRecord.model_validate(value)
        if run.run_id != run_id:
            raise RecipeConflict("Run identity mismatch")
        return run

    def _write(self, run: RecipeRunRecord) -> None:
        atomic_write_json(self.run_dir(run.run_id) / "manifest.json", self._signed("run", run.model_dump(mode="json")))

    def compare_and_update(
        self, run_id: str, *, expected_seq: int, lease_epoch: int, transition: dict[str, Any],
    ) -> RecipeRunRecord:
        with store_lock(self.lock_path):
            current = self.read(run_id)
            if current.seq != expected_seq or current.lease_epoch != lease_epoch:
                raise RecipeConflict("Run state or lease epoch conflict")
            if current.state in TERMINAL_RUNS:
                raise RecipeConflict("Terminal run records are immutable")
            forbidden = set(transition) & {
                "run_id", "plan_id", "plan_digest", "idempotency_key", "created_at", "deadline",
                "owner_host_instance_id", "lease_epoch", "seq", "mac", "authorization_id",
            }
            if forbidden:
                raise RecipeConflict("Immutable run identity cannot be changed by a transition")
            state = transition.get("state", current.state)
            if state not in _TRANSITIONS[current.state]:
                raise RecipeConflict("Invalid recipe state transition")
            updated = {**current.model_dump(mode="json"), **transition,
                       "seq": current.seq + 1, "updated_at": time.time(), "mac": ""}
            updated["cancel_requested"] = current.cancel_requested or updated["cancel_requested"]
            candidate = RecipeRunRecord.model_validate(updated)
            if any(getattr(candidate.budgets_used, name) < getattr(current.budgets_used, name)
                   for name in type(current.budgets_used).model_fields):
                raise RecipeConflict("Resource usage cannot decrease")
            if candidate.artifacts[:len(current.artifacts)] != current.artifacts:
                raise RecipeConflict("Run artifacts are append-only")
            if candidate.derived_targets[:len(current.derived_targets)] != current.derived_targets:
                raise RecipeConflict("Derived mappings are append-only")
            if len(candidate.steps) != len(current.steps):
                raise RecipeConflict("Run cannot add or remove steps")
            for before, after in zip(current.steps, candidate.steps, strict=True):
                if before.step_id != after.step_id:
                    raise RecipeConflict("Run step identity changed")
                if before.state in TERMINAL_STEPS and before != after:
                    raise RecipeConflict("Terminal step records are immutable")
                if before.request_id is not None and before.request_id != after.request_id:
                    raise RecipeConflict("A dispatched step cannot acquire a new request identity")
                if before.dispatch_lease_epoch is not None and before.dispatch_lease_epoch != after.dispatch_lease_epoch:
                    raise RecipeConflict("The original dispatch lease is immutable")
                for field in ("stage_effect", "bootstrap_grant", "checkpoint_observation"):
                    if getattr(before, field) is not None and getattr(before, field) != getattr(after, field):
                        raise RecipeConflict("Persisted stage evidence is immutable")
            self._write(candidate)
            return self.read(run_id)

    def record_cancel_intent(self, run_id: str) -> RecipeRunRecord:
        with store_lock(self.lock_path):
            current = self.read(run_id)
            if current.state in TERMINAL_RUNS or current.cancel_requested:
                return current
            return self.compare_and_update(
                run_id, expected_seq=current.seq, lease_epoch=current.lease_epoch,
                transition={"cancel_requested": True,
                            "state": "blocked" if current.state == "blocked" else "cancel_requested"},
            )

    def adopt(self, run_id: str) -> RecipeRunRecord:
        with store_lock(self.lock_path):
            run = self.read(run_id)
            if run.owner_host_instance_id == HOST_INSTANCE_ID:
                return run
            owner_path = self.run_dir(run_id) / "owner.json"
            owner = self._verified(owner_path, "owner")
            if owner.get("host_instance_id") != run.owner_host_instance_id or owner.get("lease_epoch") != run.lease_epoch:
                raise RecipeConflict("Interrupted owner transfer requires reconciliation")
            identity = process_start_identity(owner["pid"])
            if identity is not None and identity == owner.get("process_started_at"):
                raise RecipeConflict("Another live host owns this recipe run")
            if identity is None and process_is_alive(owner["pid"]) is not False:
                raise RecipeConflict("Cannot prove previous recipe owner has exited")
            # Ownership transfer does not resolve outstanding native execution.
            update = run.model_dump(mode="json")
            update.update(owner_host_instance_id=HOST_INSTANCE_ID, lease_epoch=run.lease_epoch + 1,
                          seq=run.seq + 1, updated_at=time.time(), mac="")
            adopted = RecipeRunRecord.model_validate(update)
            atomic_write_json(owner_path, self._signed("owner", {
                "host_instance_id": HOST_INSTANCE_ID, "pid": os.getpid(),
                "process_started_at": process_start_identity(os.getpid()), "lease_epoch": adopted.lease_epoch,
            }))
            self._write(adopted)
            return self.read(run_id)

    def artifact(self, run_id: str, kind: str, value: dict[str, Any]) -> ArtifactRef:
        with store_lock(self.lock_path):
            run = self.read(run_id)
            plan = self.read_plan(run.plan_id)
            raw = canonical_bytes(value)
            sha = hashlib.sha256(raw).hexdigest()
            path = self.run_dir(run_id) / "artifacts" / f"{sha}.json"
            # Include crash-orphaned artifacts, not just manifest references.
            used = sum(item.stat().st_size for item in path.parent.glob("*.json"))
            if used + (0 if path.exists() else len(raw)) > plan.spec.budgets.disk_bytes:
                raise RecipeConflict("RESOURCE_BUDGET_EXCEEDED: recipe artifact disk budget")
            write_immutable(path, value)
            return ArtifactRef(artifact_id=sha, kind=kind, path=str(path), sha256=sha, length=len(raw))

    def read_artifact(self, run_id: str, artifact: ArtifactRef) -> dict[str, Any]:
        path = Path(artifact.path).resolve()
        expected_parent = (self.run_dir(run_id) / "artifacts").resolve()
        if path.parent != expected_parent or path.name != f"{artifact.sha256}.json":
            raise RecipeConflict("Artifact is outside the owning recipe")
        sha, size = file_sha256(path)
        if sha != artifact.sha256 or size != artifact.length:
            raise RecipeConflict("Immutable recipe artifact integrity mismatch")
        return read_json(path)
