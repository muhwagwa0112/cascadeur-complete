from __future__ import annotations

import os
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from threading import RLock

from .atomic_queue import atomic_write_json, read_json
from .models import ErrorCode, ExecutionMode, JobRecord, ResultEnvelope
from .paths import RuntimePaths
from .store_lock import process_is_alive, process_start_identity, store_lock

_HOST_INSTANCE_ID = str(uuid.uuid4())
_TERMINAL = frozenset({"succeeded", "failed", "canceled"})


class JobStore:
    def __init__(self, paths: RuntimePaths):
        self.paths = paths
        self._lock = RLock()
        self._writer_path = paths.jobs / ".writer.lock"
        paths.ensure()

    def create(
        self,
        feature_id: str,
        *,
        operation_name: str | None = None,
        arguments: dict | None = None,
        scene_id: str | None = None,
        expected_revision: str | None = None,
        timeout: float = 300,
        attempt: int = 1,
        retry_of: str | None = None,
    ) -> JobRecord:
        now = time.time()
        record = JobRecord(
            job_id=str(uuid.uuid4()),
            status="queued",
            feature_id=feature_id,
            created_at=now,
            updated_at=now,
            owner_pid=os.getpid(),
            owner_host_instance_id=_HOST_INSTANCE_ID,
            owner_process_started_at=process_start_identity(os.getpid()),
            heartbeat_at=now,
            operation_name=operation_name,
            arguments=arguments or {},
            scene_id=scene_id,
            expected_revision=expected_revision,
            timeout=timeout,
            attempt=attempt,
            retry_of=retry_of,
        )
        self.save(record)
        return record

    def path(self, job_id: str) -> Path:
        try:
            canonical = str(uuid.UUID(str(job_id)))
        except (ValueError, AttributeError, TypeError) as exc:
            raise ValueError("Invalid job id") from exc
        if canonical != str(job_id).casefold():
            raise ValueError("Invalid job id")
        path = (self.paths.jobs / f"{canonical}.json").resolve()
        if path.parent != self.paths.jobs.resolve():
            raise ValueError("Invalid job id")
        return path

    def save(self, record: JobRecord) -> None:
        with self._lock, store_lock(self._writer_path):
            existing = self.get(record.job_id)
            if existing is not None:
                if existing.status in _TERMINAL:
                    if existing.model_dump() != record.model_dump():
                        raise ValueError("Terminal job records are immutable")
                    return
                if record.state_version != existing.state_version:
                    raise ValueError("Job state version conflict")
                record.cancel_requested = existing.cancel_requested or record.cancel_requested
                record.state_version += 1
            record.updated_at = time.time()
            atomic_write_json(self.path(record.job_id), record.model_dump(mode="json"))

    def get(self, job_id: str) -> JobRecord | None:
        with self._lock, store_lock(self._writer_path):
            path = self.path(job_id)
            if not path.is_file():
                return None
            try:
                return JobRecord.model_validate(read_json(path))
            except Exception as exc:
                # Never echo validation input: it may contain local file data.
                raise ValueError("Stored job record is invalid") from exc

    def update(
        self,
        job_id: str,
        *,
        status: str | None = None,
        progress: float | None = None,
        log: str | None = None,
        result: ResultEnvelope | None = None,
    ) -> JobRecord:
        with self._lock, store_lock(self._writer_path):
            record = self.get(job_id)
            if record is None:
                raise KeyError(job_id)
            if record.status in _TERMINAL:
                return record
            if status is not None:
                if status not in {"queued", "running", *_TERMINAL}:
                    raise ValueError("Invalid job state")
                if status == "queued" and record.status != "queued":
                    raise ValueError("A claimed job cannot be requeued")
                record.status = status  # type: ignore[assignment]
            if progress is not None:
                if not 0 <= progress <= 1:
                    raise ValueError("Invalid job progress")
                record.progress = progress
            if log:
                record.logs.append(log)
            if result is not None:
                record.result = result
                record.execution_outcome = result.outcome
            record.heartbeat_at = time.time()
            self.save(record)
            return record

    def claim(self, job_id: str) -> JobRecord | None:
        with self._lock, store_lock(self._writer_path):
            record = self.get(job_id)
            if record is None or record.status != "queued" or record.cancel_requested:
                return None
            record.status = "running"
            record.progress = 0.05
            record.logs.append("Read-only job claimed before bridge dispatch")
            record.owner_pid = os.getpid()
            record.owner_host_instance_id = _HOST_INSTANCE_ID
            record.owner_process_started_at = process_start_identity(os.getpid())
            record.heartbeat_at = time.time()
            self.save(record)
            return record

    def run_job(self, job_id: str, execute: Callable[[], ResultEnvelope]) -> None:
        record = self.claim(job_id)
        if record is None:
            return
        try:
            result = execute()
        except Exception as exc:
            result = ResultEnvelope(
                ok=False, feature_id=record.feature_id, execution_mode=ExecutionMode.NATIVE,
                error_code=ErrorCode.POSTCONDITION_FAILED,
                error_message=f"Read-only job worker failed ({type(exc).__name__})",
                outcome="outcome_unknown", status="outcome_unknown",
                result={"error_details": {"code": "WORKER_EXCEPTION"}},
            )
        finally:
            # execute may fail before assigning result only for process-level
            # interruption; startup recovery preserves that outcome as unknown.
            self.heartbeat(job_id)
        with self._lock, store_lock(self._writer_path):
            current = self.get(job_id)
            if current is None or current.status in _TERMINAL:
                return
            unknown = result.outcome == "outcome_unknown" or result.status == "outcome_unknown"
            status = "failed" if unknown else "canceled" if current.cancel_requested else "succeeded" if result.ok else "failed"
            self.update(
                job_id, status=status, progress=1, result=result,
                log=("Result unknown; never automatically retried" if unknown else
                     "Claimed operation completed; cancellation intent and result retained" if current.cancel_requested
                     else "Bridge operation completed"),
            )

    def heartbeat(self, job_id: str) -> None:
        with self._lock, store_lock(self._writer_path):
            record = self.get(job_id)
            if record is not None and record.status not in _TERMINAL:
                record.heartbeat_at = time.time()
                self.save(record)

    def cancel(self, job_id: str) -> JobRecord:
        with self._lock, store_lock(self._writer_path):
            record = self.get(job_id)
            if record is None:
                raise KeyError(job_id)
            if record.status in _TERMINAL:
                return record
            record.cancel_requested = True
            if record.status == "queued":
                record.status = "canceled"
                record.execution_outcome = "canceled_pre_dispatch"
                record.progress = 1
                record.logs.append("Canceled before bridge dispatch")
            else:
                record.logs.append("Cancellation requested after dispatch; waiting for the claimed operation")
            self.save(record)
            return record

    def recover_incomplete(self) -> int:
        recovered = 0
        with self._lock, store_lock(self._writer_path):
            for path in self.paths.jobs.glob("*.json"):
                try:
                    record = JobRecord.model_validate(read_json(path))
                    if self.path(record.job_id) != path.resolve():
                        continue
                except (ValueError, OSError):
                    # A corrupt record remains available for explicit diagnosis;
                    # it does not prevent recovery of independent jobs.
                    continue
                if record.status not in ("queued", "running"):
                    continue
                if (record.owner_pid and record.owner_process_started_at
                        and process_start_identity(record.owner_pid) == record.owner_process_started_at):
                    continue
                if record.owner_pid and process_start_identity(record.owner_pid) is None and process_is_alive(record.owner_pid) is not False:
                    continue
                record.status = "failed"
                record.execution_outcome = "outcome_unknown"
                record.progress = 1
                record.logs.append("Host ownership lost; execution outcome unknown; no automatic retry")
                self.save(record)
                recovered += 1
        return recovered
