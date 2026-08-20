from __future__ import annotations

import time
import uuid
from collections.abc import Callable
from threading import Event, RLock, Thread

from .atomic_queue import AtomicQueue
from .models import BridgeRequest, ErrorCode, ExecutionMode, Operation, ResultEnvelope, SafetyContext
from .paths import RuntimePaths
from .uia import UIAutomationError, invoke_process_pending


class BridgeClient:
    def __init__(
        self, paths: RuntimePaths | None = None, trigger: Callable[[], object] | None = invoke_process_pending
    ):
        self.paths = paths or RuntimePaths.discover()
        self.queue = AtomicQueue(self.paths)
        self.trigger = trigger
        self._execute_lock = RLock()

    def execute(
        self,
        feature_id: str,
        operations: list[Operation],
        *,
        scene_id: str | None = None,
        expected_revision: str | None = None,
        timeout: float = 30.0,
        safety_context: SafetyContext | None = None,
    ) -> ResultEnvelope:
        with self._execute_lock:
            return self._execute_once(
                feature_id,
                operations,
                scene_id=scene_id,
                expected_revision=expected_revision,
                timeout=timeout,
                safety_context=safety_context,
            )

    def _execute_once(
        self,
        feature_id: str,
        operations: list[Operation],
        *,
        scene_id: str | None = None,
        expected_revision: str | None = None,
        timeout: float = 30.0,
        safety_context: SafetyContext | None = None,
    ) -> ResultEnvelope:
        started = time.monotonic()
        now = time.time()
        request = BridgeRequest(
            request_id=str(uuid.uuid4()),
            feature_id=feature_id,
            scene_id=scene_id,
            expected_revision=expected_revision,
            operations=operations,
            timeout=timeout,
            safety_context=safety_context or SafetyContext(),
            created_at=now,
            expires_at=now + timeout,
        )
        request_path = self.queue.submit(request)
        dispatch_attempts = 0
        if self.trigger:
            dispatch_attempts = 1
            trigger_error = self._trigger_error(min(timeout, 14.0))
            if trigger_error is not None and not trigger_error.not_running and not trigger_error.timed_out:
                remaining = timeout - (time.monotonic() - started)
                if remaining > 0.01:
                    trigger_error = self._trigger_error(min(remaining, 6.0))
            if trigger_error is not None:
                exc = trigger_error
                if exc.timed_out:
                    # InvokePattern may block until Cascadeur finishes the
                    # command even though the bridge has already claimed the
                    # request. Honor the caller's remaining TTL and recover a
                    # completed response without launching a duplicate UIA
                    # trigger. If it remains unclaimed, the unlink below is
                    # the atomic cancellation point.
                    remaining = timeout - (time.monotonic() - started)
                    if remaining > 0.01:
                        response = self.queue.wait_response(request.request_id, remaining)
                        if response is not None:
                            response.warnings.append(f"UI trigger exceeded its dispatch budget: {exc}")
                            response.duration_ms = int((time.monotonic() - started) * 1000)
                            return response
                try:
                    request_path.unlink()
                    canceled = True
                except FileNotFoundError:
                    canceled = False
                if not canceled:
                    response = self.queue.wait_response(request.request_id, min(timeout, 5.0))
                    if response is not None:
                        response.warnings.append(f"UI trigger reported an error after dispatch: {exc}")
                        response.duration_ms = int((time.monotonic() - started) * 1000)
                        return response
                return ResultEnvelope(
                    ok=False,
                    feature_id=feature_id,
                    execution_mode=ExecutionMode.UIA,
                    error_code=(
                        ErrorCode.CASCADEUR_NOT_RUNNING if canceled and exc.not_running else ErrorCode.UI_LOCKED
                    ),
                    error_message=(
                        str(exc)
                        if canceled
                        else f"UI trigger failed after request claim; execution outcome is unknown: {exc}"
                    ),
                    duration_ms=int((time.monotonic() - started) * 1000),
                )
            # QML menu input can be accepted without activating the submenu.
            # Retry only while the original .json request is still present:
            # once Cascadeur atomically renames it to .processing, another
            # dispatch is forbidden and we only wait for that claimed result.
            # Permit up to twelve total dispatches within the original TTL. In
            # live 2026.1.2 validation, a QML popup occasionally ignored a
            # longer sequence after repeated scene/snapshot transitions but
            # accepted a later exact invocation.
            # The request-file existence check keeps every retry idempotent.
            while dispatch_attempts < 12:
                remaining = timeout - (time.monotonic() - started)
                if remaining <= 0.01:
                    break
                response = self.queue.wait_response(request.request_id, min(0.35, remaining))
                if response is not None:
                    if dispatch_attempts > 1:
                        response.warnings.append(f"UI dispatch succeeded after {dispatch_attempts} attempts")
                    response.duration_ms = int((time.monotonic() - started) * 1000)
                    return response
                if not request_path.exists():
                    break
                remaining = timeout - (time.monotonic() - started)
                if remaining < 4.0:
                    break
                retry_error = self._trigger_error(min(remaining, 8.0))
                dispatch_attempts += 1
                if retry_error is not None:
                    break
        remaining = max(0.01, timeout - (time.monotonic() - started))
        response = self.queue.wait_response(request.request_id, remaining)
        if response is None:
            # A timed-out request must never remain queued and execute during a
            # later, unrelated Process Pending invocation. If the bridge has
            # already claimed it, the execution outcome is necessarily unknown.
            try:
                request_path.unlink()
                canceled = True
            except FileNotFoundError:
                canceled = False
            return ResultEnvelope(
                ok=False,
                feature_id=feature_id,
                execution_mode=ExecutionMode.NATIVE,
                error_code=ErrorCode.TIMEOUT if canceled else ErrorCode.UI_LOCKED,
                error_message=(
                    f"No bridge response within {timeout:.1f}s; queued request was canceled"
                    if canceled
                    else f"No bridge response within {timeout:.1f}s after request claim; execution outcome is unknown"
                ),
                duration_ms=int((time.monotonic() - started) * 1000),
            )
        response.duration_ms = int((time.monotonic() - started) * 1000)
        if dispatch_attempts > 1:
            response.warnings.append(f"UI dispatch succeeded after {dispatch_attempts} attempts")
        return response

    def _trigger_error(self, timeout: float) -> UIAutomationError | None:
        completed = Event()
        errors: list[UIAutomationError] = []

        def invoke() -> None:
            try:
                if self.trigger:
                    self.trigger()
            except UIAutomationError as exc:
                errors.append(exc)
            except Exception as exc:  # pragma: no cover - defensive adapter boundary
                errors.append(UIAutomationError(f"Unexpected UI Automation failure: {exc}"))
            finally:
                completed.set()

        Thread(target=invoke, name="cascadeur-uia-trigger", daemon=True).start()
        if not completed.wait(max(0.01, timeout)):
            # The daemon may eventually return and invoke the menu. Do not
            # start a second trigger concurrently; the caller will remove an
            # unclaimed queue file so a late invocation has nothing to run.
            return UIAutomationError(
                f"Cascadeur UI trigger did not return within {timeout:.1f}s",
                timed_out=True,
            )
        return errors[0] if errors else None
