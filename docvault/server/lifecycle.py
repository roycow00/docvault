"""Single-instance lockfile + port probe."""

from __future__ import annotations

import json
import os
import socket
import sys
from contextlib import contextmanager
from pathlib import Path


def _is_pid_alive(pid: int) -> bool:
    if sys.platform == "win32":
        # os.kill(pid, 0) on Windows is *not* a signal-zero probe: CPython
        # implements it via TerminateProcess, which raises OSError with
        # various winerror codes whether or not the process exists. Use
        # OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION) — the lowest access
        # right — and read the exit code instead.
        import ctypes
        from ctypes import wintypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259

        kernel32 = ctypes.windll.kernel32
        kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
        kernel32.GetExitCodeProcess.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel32.CloseHandle.restype = wintypes.BOOL

        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        try:
            exit_code = wintypes.DWORD()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return False
            return exit_code.value == STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _is_port_listening(port: int, host: str = "127.0.0.1") -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.2)
    try:
        s.connect((host, port))
        s.close()
        return True
    except OSError:
        return False


def existing_instance(vault_root: Path, port: int) -> tuple[int, int] | None:
    """Return (pid, port) of a running instance if one is detected, else None."""
    lock = vault_root / ".lock"
    if not lock.is_file():
        return None
    try:
        info = json.loads(lock.read_text(encoding="utf-8"))
        pid = int(info.get("pid", 0))
        lock_port = int(info.get("port", port))
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    if pid and _is_pid_alive(pid) and _is_port_listening(lock_port):
        return (pid, lock_port)
    return None


@contextmanager
def lockfile(vault_root: Path, port: int):
    """Write `.lock` for the duration of the context, remove on exit.

    Only unlinks the file if it still names the current process. If a sibling
    invocation overwrote the lock, or the user replaced it, we leave it alone
    instead of stomping on whoever currently owns it.
    """
    lock = vault_root / ".lock"
    my_pid = os.getpid()
    lock.write_text(
        json.dumps({"pid": my_pid, "port": port}, indent=2),
        encoding="utf-8",
    )
    try:
        yield
    finally:
        try:
            if lock.is_file():
                info = json.loads(lock.read_text(encoding="utf-8"))
                if int(info.get("pid", 0)) == my_pid:
                    lock.unlink(missing_ok=True)
        except (OSError, ValueError, json.JSONDecodeError):
            pass
