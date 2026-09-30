from __future__ import annotations

import time
import uuid
from collections.abc import Callable
from threading import Event, RLock, Thread

from .atomic_queue import AtomicQueue, read_json
from .models import BridgeRequest, ErrorCode, ExecutionMode, Operation, ResultEnvelope, SafetyContext
from .paths import RuntimePaths
from .pump_client import read_pump, wake_pump
from .queue_auth import QueueAuthenticationError
from .uia import UIAutomationError, dismiss_feature_gate, invoke_process_pending

# How long a live UI-thread pump may take to claim a request before the host
# falls back to the Process Pending menu (e.g. the request targets another scene
# tab, or a modal dialog is blocking the main window).
PUMP_CLAIM_SECONDS = 2.5


class BridgeClient:
    def __init__(
        self,
        paths: RuntimePaths | None = None,
        trigger: Callable[[], object] | None = invoke_process_pending,
        gate_probe: Callable[[], str | None] | None = None,
    ):
        self.paths = paths or RuntimePaths.discover()
        self.queue = AtomicQueue(self.paths)
        self.trigger = trigger
        # Cascadeur's "Feature not available" gate is modal: it blocks the UI
        # thread (and the bridge) until closed. Watch for it with the real UI.
        self.gate_probe = gate_probe or (dismiss_feature_gate if trigger is invoke_process_pending else None)
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
        lingering_until = self.lingering_until()
        if lingering_until is not None:
            # The bridge is still draining on the UI thread after the previous
            # request; it claims this one without another UI trigger.
            wait = min(timeout, max(0.0, lingering_until - time.time()) + 0.75)
            response = self._wait_response(request, wait)
            if response is not None:
                response.duration_ms = int((time.monotonic() - started) * 1000)
                return response
        pump = read_pump(self.paths)
        if pump is not None and request_path.exists():
            # A live pump drains on Cascadeur's UI thread from its own timer; the
            # wake-up post only shortens the wait. No window is activated.
            wake_pump(pump)
            response = self._wait_claim_or_response(
                request,
                request_path,
                min(timeout, PUMP_CLAIM_SECONDS),
                timeout - (time.monotonic() - started),
            )
            if response is not None:
                response.duration_ms = int((time.monotonic() - started) * 1000)
                return response
        if self.trigger and request_path.exists():
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
                        response = self._wait_response(request, remaining)
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
                    response = self._wait_response(request, min(timeout, 5.0))
                    if response is not None:
                        response.warnings.append(f"UI trigger reported an error after dispatch: {exc}")
                        response.duration_ms = int((time.monotonic() - started) * 1000)
                        return response
                return ResultEnvelope(
                    ok=False,
                    feature_id=feature_id,
                    execution_mode=ExecutionMode.UIA,
                    error_code=(
                        ErrorCode.LICENSE_GATED
                        if exc.license_gated
                        else ErrorCode.CASCADEUR_NOT_RUNNING
                        if canceled and exc.not_running
                        else ErrorCode.UI_LOCKED
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
            # live 2026.1 validation, a QML popup occasionally ignored a
            # longer sequence after repeated scene/snapshot transitions but
            # accepted a later exact invocation.
            # The request-file existence check keeps every retry idempotent.
            while dispatch_attempts < 12:
                remaining = timeout - (time.monotonic() - started)
                if remaining <= 0.01:
                    break
                response = self._wait_response(request, min(0.35, remaining))
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
        response = self._wait_response(request, remaining)
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

    def lingering_until(self) -> float | None:
        marker = self.paths.state / "drain_active.json"
        try:
            until = float(read_json(marker).get("until", 0.0))
        except (OSError, ValueError, TypeError):
            return None
        return until if until > time.time() else None

    def pump_state(self) -> dict[str, object]:
        pump = read_pump(self.paths)
        if pump is None:
            return {"active": False}
        return {"active": True, "pid": pump.pid, "heartbeat_age_s": round(pump.age(), 2)}

    def _wait_claim_or_response(
        self, request: BridgeRequest, request_path, timeout: float, limit: float
    ) -> ResultEnvelope | None:
        """Wait until the bridge answers or claims the request; None if claimed or unclaimed.

        The claim window is extended while the pump reports that it is busy with
        an earlier request (the UI thread could not run the menu trigger then
        either), but never beyond ``limit``.
        """
        started = time.monotonic()
        deadline = started + timeout
        while True:
            response = self._wait_response_once(request, 0.03)
            if response is not None or not request_path.exists():
                return response
            now = time.monotonic()
            if now < deadline:
                continue
            pump = read_pump(self.paths)
            if pump is None or not pump.busy or now - started >= limit:
                return None
            deadline = now + 0.25

    def _wait_response(self, request: BridgeRequest, timeout: float) -> ResultEnvelope | None:
        if self.gate_probe is None or timeout < 2.0:
            return self._wait_response_once(request, timeout)
        deadline = time.monotonic() + timeout
        gate = None
        while True:
            response = self._wait_response_once(request, min(2.0, max(0.01, deadline - time.monotonic())))
            if response is not None or time.monotonic() >= deadline:
                break
            if gate is None:
                gate = self.gate_probe()
        if gate is None:
            return response
        if response is None:
            # Never leave the refused request queued for a later Process Pending.
            for path in self.paths.requests.glob(f"*-{request.request_id}.json"):
                path.unlink(missing_ok=True)
        # The gate was closed, so the bridge could finish; its result is not the
        # requested feature, which Cascadeur refused under the current license.
        return ResultEnvelope(
            ok=False,
            feature_id=request.feature_id,
            execution_mode=ExecutionMode.GATED,
            request_id=request.request_id,
            session_id=request.session_id,
            nonce=request.nonce,
            error_code=ErrorCode.LICENSE_GATED,
            error_message=f"Cascadeur reported 'Feature not available' (license does not include it): {gate}",
            warnings=[] if response is None else [f"bridge result after the gate closed: ok={response.ok}"],
        )

    def _wait_response_once(self, request: BridgeRequest, timeout: float) -> ResultEnvelope | None:
        try:
            return self.queue.wait_response(request.request_id, timeout)
        except QueueAuthenticationError as exc:
            self.queue.response_path(request.request_id).unlink(missing_ok=True)
            return ResultEnvelope(
                ok=False,
                feature_id=request.feature_id,
                execution_mode=ExecutionMode.NATIVE,
                request_id=request.request_id,
                session_id=request.session_id,
                nonce=request.nonce,
                error_code=ErrorCode.INVALID_REQUEST,
                error_message=f"Bridge response authentication failed: {exc}",
            )

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
