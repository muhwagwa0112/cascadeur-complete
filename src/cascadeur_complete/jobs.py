from __future__ import annotations

import os
import time
import uuid
from pathlib import Path
from threading import RLock

from .atomic_queue import atomic_write_json, read_json
from .models import JobRecord, ResultEnvelope
from .paths import RuntimePaths


class JobStore:
    def __init__(self, paths: RuntimePaths):
        self.paths = paths
        self._lock = RLock()
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
        with self._lock:
            record.updated_at = time.time()
            atomic_write_json(self.path(record.job_id), record.model_dump(mode="json"))

    def get(self, job_id: str) -> JobRecord | None:
        with self._lock:
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
        record = self.get(job_id)
        if record is None:
            raise KeyError(job_id)
        if status is not None:
            record.status = status  # type: ignore[assignment]
        if progress is not None:
            record.progress = progress
        if log:
            record.logs.append(log)
        if result is not None:
            record.result = result
        self.save(record)
        return record

    def cancel(self, job_id: str) -> JobRecord:
        record = self.get(job_id)
        if record is None:
            raise KeyError(job_id)
        if record.status in ("succeeded", "failed", "canceled"):
            return record
        record.cancel_requested = True
        if record.status == "queued":
            record.status = "canceled"
            record.progress = 1
            record.logs.append("Canceled before bridge dispatch")
        else:
            record.logs.append("Cancellation requested after dispatch; waiting for the claimed operation")
        self.save(record)
        return record

    def recover_incomplete(self) -> int:
        recovered = 0
        for path in self.paths.jobs.glob("*.json"):
            record = JobRecord.model_validate(read_json(path))
            if record.status not in ("queued", "running"):
                continue
            if record.owner_pid and _process_alive(record.owner_pid):
                continue
            record.status = "failed"
            record.progress = 1
            record.logs.append("Host restarted before job completion; execution outcome was not assumed")
            self.save(record)
            recovered += 1
        return recovered


def _process_alive(process_id: int) -> bool:
    try:
        os.kill(process_id, 0)
    except OSError:
        return False
    return True
