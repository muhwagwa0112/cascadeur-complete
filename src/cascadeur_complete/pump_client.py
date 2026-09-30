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
        )
    except (OSError, ValueError, TypeError, KeyError):
        return None
    age = info.age()
    if age < -1.0 or age > fresh_seconds:
        return None
    return info


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
