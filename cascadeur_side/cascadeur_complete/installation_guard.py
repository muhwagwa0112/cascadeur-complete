"""Process-lifetime runtime readers versus an exclusive Windows installer.

The gate lives beside the runtime so directory replacement cannot replace the
lock. Existence carries no authority; only the OS-held handle blocks an upgrade.
Keep this dependency-free module identical in the host and embedded bridge.
"""
from __future__ import annotations

import atexit
import os
from pathlib import Path
from threading import Lock

_mutex = Lock()
_leases = {}


def maintenance_path(runtime_root):
    root = Path(runtime_root).resolve()
    if not root.name:
        raise ValueError("A filesystem root cannot be a runtime installation")
    return root.parent / ("." + root.name + ".maintenance.lock")


def hold_runtime_lease(runtime_root):
    """Reject maintenance before creating keys/state; retain a shared read lease.

    The installer uses ReadWrite/FileShare.None on this same file. Windows
    releases the lease on process exit, including crashes; no PID/TTL guessing,
    stale-marker deletion, bypass flag or authentication-key replacement occurs.
    """
    path = maintenance_path(runtime_root)
    key = os.path.normcase(str(path))
    with _mutex:
        if key in _leases:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes

            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.CreateFileW.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE)
            kernel.CreateFileW.restype = wintypes.HANDLE
            kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
            kernel.CloseHandle.restype = wintypes.BOOL
            handle = kernel.CreateFileW(str(path), 0x80000000, 1, None, 4, 0x80, None)
            if handle == wintypes.HANDLE(-1).value:
                code = ctypes.get_last_error()
                if code in (32, 33):
                    raise RuntimeError("INSTALLATION_BUSY: close this client and retry after installation")
                raise ctypes.WinError(code)
            _leases[key] = (kernel, handle)
        else:
            import fcntl

            stream = path.open("a+b")
            try:
                fcntl.flock(stream.fileno(), fcntl.LOCK_SH | fcntl.LOCK_NB)
            except OSError:
                stream.close()
                raise RuntimeError("INSTALLATION_BUSY: close this client and retry after installation") from None
            _leases[key] = stream


def _close_leases():
    with _mutex:
        for lease in _leases.values():
            if os.name == "nt":
                kernel, handle = lease
                kernel.CloseHandle(handle)
            else:
                lease.close()
        _leases.clear()


atexit.register(_close_leases)
