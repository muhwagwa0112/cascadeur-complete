"""Host side of the Cascadeur UI-thread queue pump.

The bridge publishes ``state/pump.json`` from a timer on Cascadeur's UI thread
(see ``cascadeur_side/cascadeur_complete/pump.py``). While its heartbeat is
fresh the host dispatches by posting a wake-up message to the pump's hidden
message-only window instead of driving the Process Pending menu through UI
Automation, so Cascadeur is never brought to the foreground.
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass

from .atomic_queue import read_json
from .paths import RuntimePaths

PUMP_FRESH_SECONDS = 3.0
PUMP_WINDOW_CLASS = "CascadeurCompletePump"


@dataclass(frozen=True)
class PumpInfo:
    pid: int
    hwnd: int
    wake_message: int
    heartbeat: float
    busy: bool = False

    def age(self, now: float | None = None) -> float:
        return (time.time() if now is None else now) - self.heartbeat


def read_pump(paths: RuntimePaths, *, fresh_seconds: float = PUMP_FRESH_SECONDS) -> PumpInfo | None:
    """Return the pump description while its heartbeat is fresh, else None."""
    if (paths.state / "pump.disabled").exists():
        return None
    try:
        data = read_json(paths.state / "pump.json")
        info = PumpInfo(
            pid=int(data["pid"]),
            hwnd=int(data.get("hwnd") or 0),
            wake_message=int(data.get("wake_message") or 0),
            heartbeat=float(data["heartbeat"]),
            busy=bool(data.get("busy", False)),
        )
    except (OSError, ValueError, TypeError, KeyError):
        return None
    age = info.age()
    # A draining pump cannot refresh its heartbeat until the request returns;
    # it stays usable as long as the Cascadeur process that owns it is alive.
    if age < -1.0 or (age > fresh_seconds and not (info.busy and _process_alive(info.pid))):
        return None
    return info


def _process_alive(pid: int) -> bool:
    if sys.platform != "win32":
        return False
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return False
    try:
        code = wintypes.DWORD()
        return bool(kernel32.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259  # STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


def wake_pump(info: PumpInfo) -> bool:
    """Post the wake-up message; best effort, the pump timer drains regardless."""
    if sys.platform != "win32" or not info.hwnd or not info.wake_message:
        return False
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.IsWindow.argtypes = [wintypes.HWND]
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    hwnd = wintypes.HWND(info.hwnd)
    if not user32.IsWindow(hwnd):
        return False
    # Window handles are recycled: post only to the pump window of that process.
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    name = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, name, len(name))
    if pid.value != info.pid or not name.value.startswith(PUMP_WINDOW_CLASS):
        return False
    return bool(user32.PostMessageW(hwnd, info.wake_message, 0, 0))
