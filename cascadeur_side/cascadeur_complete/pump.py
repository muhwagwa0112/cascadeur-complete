"""UI-thread queue pump: drain MCP requests without a UI Automation trigger.

Cascadeur runs Python only from menu commands and scene events, and ``csc``
offers no timer or idle callback. Qt's event loop on Windows still dispatches
ordinary Win32 messages, so a hidden message-only window created on the UI
thread receives its ``WM_TIMER`` ticks (and host wake-up posts) on that same
thread. Its window procedure drains the queue exactly like
``Commands > Cascadeur Complete > Process Pending``, without stealing focus or
synthesizing clicks.

The pump publishes a heartbeat to ``state/pump.json``. The host dispatches
through the pump only while that heartbeat is fresh and falls back to the menu
trigger otherwise, so a pump that never starts (or a UI thread that is busy)
degrades to the previous behaviour. Creating ``state/pump.disabled`` turns the
pump off without reinstalling.
"""

from __future__ import annotations

import ctypes
import json
import os
import sys
import time
from contextlib import suppress
from ctypes import wintypes

WINDOW_CLASS = "CascadeurCompletePump"
WM_TIMER = 0x0113
WM_APP_WAKE = 0x8000 + 0x43
TIMER_ID = 1
INTERVAL_MS = 150
HEARTBEAT_SECONDS = 1.0
PUMP_SCHEMA = 1

_LRESULT = ctypes.c_ssize_t
_WNDPROC = ctypes.WINFUNCTYPE(_LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
_HWND_MESSAGE = wintypes.HWND(-3)


class _WNDCLASSEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.UINT),
        ("style", wintypes.UINT),
        ("lpfnWndProc", _WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
        ("hIconSm", wintypes.HICON),
    ]


_state = {
    "hwnd": None,
    "thread_id": None,
    "wndproc": None,
    "busy": False,
    "last_heartbeat": 0.0,
    "processed": 0,
    "last_error": None,
    "handler_stamp": None,
    "handlers_reloaded": 0,
}


def _user32():
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.DefWindowProcW.restype = _LRESULT
    user32.RegisterClassExW.argtypes = [ctypes.POINTER(_WNDCLASSEXW)]
    user32.RegisterClassExW.restype = wintypes.ATOM
    user32.CreateWindowExW.argtypes = [
        wintypes.DWORD,
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        wintypes.DWORD,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.HWND,
        wintypes.HMENU,
        wintypes.HINSTANCE,
        wintypes.LPVOID,
    ]
    user32.CreateWindowExW.restype = wintypes.HWND
    user32.SetTimer.argtypes = [wintypes.HWND, ctypes.c_size_t, wintypes.UINT, ctypes.c_void_p]
    user32.SetTimer.restype = ctypes.c_size_t
    user32.EnumThreadWindows.argtypes = [
        wintypes.DWORD,
        ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM),
        wintypes.LPARAM,
    ]
    return user32


def _runtime_state_dir():
    from .runtime import runtime_root

    return runtime_root() / "state"


def _disabled(state_dir):
    return (state_dir / "pump.disabled").exists()


def _write_heartbeat(now=None):
    now = time.time() if now is None else now
    _state["last_heartbeat"] = now
    with suppress(Exception):
        _replace_json(
            _runtime_state_dir() / "pump.json",
            {
                "schema": PUMP_SCHEMA,
                "pid": os.getpid(),
                "hwnd": int(_state["hwnd"] or 0),
                "thread_id": int(_state["thread_id"] or 0),
                "window_class": WINDOW_CLASS,
                "wake_message": WM_APP_WAKE,
                "interval_ms": INTERVAL_MS,
                "heartbeat": now,
                "busy": _state["busy"],
                "processed": _state["processed"],
                "handlers_reloaded": _state["handlers_reloaded"],
                "last_error": _state["last_error"],
            },
        )


def _replace_json(path, payload):
    """Replace ``path`` atomically, retrying while the host has it open.

    Windows refuses to replace a file another process is reading, and a lost
    heartbeat makes the host fall back to the menu trigger. The heartbeat is
    rewritten every second, so it skips fsync.
    """
    temporary = path.with_name("." + path.name + ".tmp")
    temporary.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    for attempt in range(5):
        try:
            os.replace(temporary, path)
            return
        except PermissionError:
            if attempt == 4:
                raise
            time.sleep(0.005)


def _modal_window_open(user32):
    """Return True while another window of this UI thread blocks the main window.

    Qt disables the windows a modal dialog blocks. Process Pending could not be
    invoked from the menu in that state either, so the pump waits as well; its
    own nested dialogs are already excluded by the ``busy`` guard.
    """
    blocked = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def visit(handle, _lparam):
        if user32.IsWindowVisible(handle) and not user32.IsWindowEnabled(handle):
            blocked.append(handle)
            return False
        return True

    user32.EnumThreadWindows(_state["thread_id"], visit, 0)
    return bool(blocked)


def _handler_stamp():
    root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "handlers")
    entries = []
    for name in sorted(os.listdir(root)):
        if name.endswith(".py"):
            info = os.stat(os.path.join(root, name))
            entries.append((name, info.st_size, info.st_mtime_ns))
    return tuple(entries)


def _reload_handlers_if_changed():
    """Hot-reload the handler modules after a reinstall replaced them on disk.

    Cascadeur imports Python modules once at startup, so handler fixes used to
    require restarting Cascadeur. Handlers register into the registry's dicts,
    which runtime dispatches through, so clearing those dicts and re-executing
    the handler modules swaps the implementations in place. A failed reload
    restores the previous handlers. runtime.py and this module still need a
    restart to change.
    """
    import importlib
    import sys

    stamp = _handler_stamp()
    if _state["handler_stamp"] is None or stamp == _state["handler_stamp"]:
        _state["handler_stamp"] = stamp
        return
    _state["handler_stamp"] = stamp
    from . import handler_registry, handlers

    saved = (dict(handler_registry._HANDLERS), dict(handler_registry._POSTCONDITIONS))
    handler_registry._HANDLERS.clear()
    handler_registry._POSTCONDITIONS.clear()
    try:
        for name in list(handlers.__all__):
            module = sys.modules.get(handlers.__name__ + "." + name)
            if module is not None:
                importlib.reload(module)
        # Re-executing the package imports submodules added by the new version.
        importlib.reload(handlers)
    except Exception as exc:
        handler_registry._HANDLERS.clear()
        handler_registry._HANDLERS.update(saved[0])
        handler_registry._POSTCONDITIONS.clear()
        handler_registry._POSTCONDITIONS.update(saved[1])
        _state["last_error"] = f"handler reload: {type(exc).__name__}: {exc}"
        print("[cascadeur-complete-pump] handler reload failed:", exc)
        return
    _state["handlers_reloaded"] += 1


def _drain(user32):
    if _state["busy"]:
        return
    now = time.time()
    if now - _state["last_heartbeat"] >= HEARTBEAT_SECONDS:
        with suppress(Exception):
            _reload_handlers_if_changed()
        _write_heartbeat(now)
    state_dir = _runtime_state_dir()
    if _disabled(state_dir) or not any((state_dir / "requests").glob("*.json")):
        return
    if _modal_window_open(user32):
        return
    from .runtime import _scene_view, process_pending

    if _scene_view() is None:
        return
    _state["busy"] = True
    # Announce the drain so the host keeps waiting instead of falling back to
    # the menu trigger while an earlier request is still executing.
    _write_heartbeat()
    try:
        _state["processed"] += process_pending(None, matching_scene_only=True, linger=False)
        _state["last_error"] = None
    except Exception as exc:
        _state["last_error"] = f"{type(exc).__name__}: {exc}"
        print("[cascadeur-complete-pump] drain failed:", exc)
    finally:
        _state["busy"] = False
        _write_heartbeat()


def _window_procedure(user32, kernel32):
    def procedure(hwnd, message, wparam, lparam):
        if (message == WM_TIMER and wparam == TIMER_ID) or message == WM_APP_WAKE:
            # Only the pump that owns the current install may drain: csc is not
            # thread-safe, so a superseded pump on another thread stays idle.
            if hwnd != _state["hwnd"] or kernel32.GetCurrentThreadId() != _state["thread_id"]:
                return 0
            try:
                _drain(user32)
            except Exception as exc:  # pragma: no cover - never raise into Qt's loop
                _state["last_error"] = f"{type(exc).__name__}: {exc}"
            return 0
        return user32.DefWindowProcW(hwnd, message, wparam, lparam)

    return _WNDPROC(procedure)


def _inside_cascadeur(kernel32):
    """Only Cascadeur's own process may host the pump (never tests or the MCP host)."""
    buffer = ctypes.create_unicode_buffer(32768)
    kernel32.GetModuleFileNameW.argtypes = [wintypes.HMODULE, wintypes.LPWSTR, wintypes.DWORD]
    if not kernel32.GetModuleFileNameW(None, buffer, len(buffer)):
        return False
    return os.path.basename(buffer.value).casefold() == "cascadeur.exe"


def draining():
    """True while the pump (not a menu command) is executing requests."""
    return bool(_state["busy"])


def status():
    return {key: _state[key] for key in ("hwnd", "thread_id", "busy", "processed", "last_error")}


def ensure_installed():
    """Create the pump window on the calling (UI) thread; idempotent.

    Safe to call from every command and event entry point. A pump created on a
    thread without a message loop never writes a heartbeat, so a later call from
    a thread that does run one reinstalls it there.
    """
    if sys.platform != "win32":
        return False
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    if not _inside_cascadeur(kernel32):
        return False
    thread_id = kernel32.GetCurrentThreadId()
    if _state["hwnd"] and (
        _state["thread_id"] == thread_id or time.time() - _state["last_heartbeat"] < 5 * HEARTBEAT_SECONDS
    ):
        return True
    try:
        user32 = _user32()
        kernel32.GetModuleHandleW.restype = wintypes.HMODULE
        instance = kernel32.GetModuleHandleW(None)
        wndproc = _window_procedure(user32, kernel32)
        window_class = _WNDCLASSEXW()
        window_class.cbSize = ctypes.sizeof(_WNDCLASSEXW)
        window_class.lpfnWndProc = wndproc
        window_class.hInstance = instance
        window_class.lpszClassName = WINDOW_CLASS + str(thread_id)
        if not user32.RegisterClassExW(ctypes.byref(window_class)):
            raise OSError(ctypes.get_last_error(), "RegisterClassExW failed")
        hwnd = user32.CreateWindowExW(
            0, window_class.lpszClassName, WINDOW_CLASS, 0, 0, 0, 0, 0, _HWND_MESSAGE, None, instance, None
        )
        if not hwnd:
            raise OSError(ctypes.get_last_error(), "CreateWindowExW failed")
        if not user32.SetTimer(hwnd, TIMER_ID, INTERVAL_MS, None):
            user32.DestroyWindow(hwnd)
            raise OSError(ctypes.get_last_error(), "SetTimer failed")
    except Exception as exc:
        _state["last_error"] = f"install: {exc}"
        print("[cascadeur-complete-pump] install failed:", exc)
        return False
    _state.update(hwnd=hwnd, thread_id=thread_id, wndproc=wndproc, last_heartbeat=0.0)
    return True
