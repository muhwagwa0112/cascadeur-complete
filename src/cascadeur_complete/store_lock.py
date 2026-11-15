"""Process-shared, reentrant locks for small durable store transactions."""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from threading import RLock, local

_registry_lock = RLock()
_locks: dict[str, tuple[RLock, local]] = {}


@contextmanager
def store_lock(path: Path):
    key = str(path.resolve()).casefold() if os.name == "nt" else str(path.resolve())
    with _registry_lock:
        mutex, state = _locks.setdefault(key, (RLock(), local()))
    with mutex:
        if getattr(state, "depth", 0):
            state.depth += 1
            try:
                yield
            finally:
                state.depth -= 1
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a+b") as stream:
            if stream.seek(0, os.SEEK_END) == 0:
                stream.write(b"\0")
                stream.flush()
            stream.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
            else:
                import fcntl

                fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            state.depth = 1
            try:
                yield
            finally:
                state.depth = 0
                stream.seek(0)
                if os.name == "nt":
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def process_start_identity(process_id: int) -> str | None:
    """A creation-time identity, so PID reuse never proves store ownership."""
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel.GetProcessTimes.argtypes = (
            wintypes.HANDLE, ctypes.POINTER(wintypes.FILETIME), ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME), ctypes.POINTER(wintypes.FILETIME),
        )
        handle = kernel.OpenProcess(0x1000, False, process_id)
        if not handle:
            return None
        try:
            times = [wintypes.FILETIME() for _ in range(4)]
            if not kernel.GetProcessTimes(handle, *(ctypes.byref(value) for value in times)):
                return None
            return f"win32:{(times[0].dwHighDateTime << 32) | times[0].dwLowDateTime}"
        finally:
            kernel.CloseHandle(handle)
    try:
        text = Path(f"/proc/{process_id}/stat").read_text()
        fields = text[text.rfind(")") + 2:].split()
        return f"proc:{fields[19]}"
    except (OSError, IndexError):
        return None


def process_is_alive(process_id: int) -> bool | None:
    """Distinguish absent owners from owners whose identity cannot be read."""
    if type(process_id) is not int or process_id <= 0:
        return None
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
        handle = kernel.OpenProcess(0x1000, False, process_id)
        if handle:
            kernel.CloseHandle(handle)
            return True
        error = ctypes.get_last_error()
        return False if error == 87 else None
    try:
        os.kill(process_id, 0)
        return True
    except ProcessLookupError:
        return False
    except (PermissionError, OSError):
        return None
