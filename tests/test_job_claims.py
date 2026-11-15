import threading
from concurrent.futures import ThreadPoolExecutor

from cascadeur_complete.jobs import JobStore
from cascadeur_complete.models import ExecutionMode, ResultEnvelope
from cascadeur_complete.paths import RuntimePaths


def test_only_one_worker_claims_and_cancel_retains_success_result(tmp_path):
    paths = RuntimePaths.discover(tmp_path)
    stores = [JobStore(paths), JobStore(paths)]
    job = stores[0].create("status")
    started, finish = threading.Event(), threading.Event()
    calls = []

    def execute():
        calls.append(1)
        started.set()
        assert finish.wait(5)
        return ResultEnvelope(ok=True, feature_id="status", execution_mode=ExecutionMode.NATIVE,
                              outcome="succeeded", status="succeeded")

    with ThreadPoolExecutor(max_workers=2) as pool:
        worker = pool.submit(stores[0].run_job, job.job_id, execute)
        assert started.wait(5)
        duplicate = pool.submit(stores[1].run_job, job.job_id, execute)
        duplicate.result(timeout=5)
        stores[1].cancel(job.job_id)
        finish.set()
        worker.result(timeout=5)
    result = stores[0].get(job.job_id)
    assert calls == [1]
    assert result.status == "canceled"
    assert result.cancel_requested and result.result.ok
    assert result.execution_outcome == "succeeded"


def test_worker_exception_is_terminal_unknown_and_not_requeued(tmp_path):
    store = JobStore(RuntimePaths.discover(tmp_path))
    job = store.create("status")

    def execute():
        raise RuntimeError("private exception detail")

    store.run_job(job.job_id, execute)
    result = store.get(job.job_id)
    assert result.status == "failed" and result.execution_outcome == "outcome_unknown"
    assert "private exception detail" not in result.result.error_message
    assert store.claim(job.job_id) is None
