"""Windows children whose lifetime is owned by a non-inherited Job Object.

Use ``process, job = spawn_in_job(command, cwd=..., stdout=..., env=...)``.
Keep ``job`` alive until the child is finished, then call ``job.close()`` in a
``finally`` block. Closing the job also terminates surviving descendants. A
crashed owner loses its only job handle, so Windows terminates the whole job.
There is deliberately no unprotected fallback when containment fails.
"""
from __future__ import annotations

import ctypes
import os
import subprocess
import threading
from ctypes import wintypes
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Any

_KILL_ON_JOB_CLOSE = 0x00002000
_CREATE_SUSPENDED = 0x00000004
_JOB_EXTENDED_LIMIT_INFORMATION = 9
_SNAPTHREAD = 0x00000004
_THREAD_SUSPEND_RESUME = 0x0002
_INVALID_HANDLE = ctypes.c_void_p(-1).value
_ERROR_NO_MORE_FILES = 18
# A raw handle has no Python finalizer: the OS closes it only when this owner
# exits. Closing a self-containing guard during interpreter teardown would kill
# the owner before its remaining cleanup completed.
_process_guard_handle = None
_process_guard_lock = threading.Lock()
_process_ownership_handles: list[int] = []


class _BasicLimits(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class _IoCounters(ctypes.Structure):
    _fields_ = [(name, ctypes.c_uint64) for name in (
        "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
        "ReadTransferCount", "WriteTransferCount", "OtherTransferCount",
    )]


class _ExtendedLimits(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _BasicLimits),
        ("IoInfo", _IoCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class _ThreadEntry(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ThreadID", wintypes.DWORD),
        ("th32OwnerProcessID", wintypes.DWORD),
        ("tpBasePri", wintypes.LONG),
        ("tpDeltaPri", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
    ]


@lru_cache(maxsize=1)
def _kernel():
    if os.name != "nt":
        raise OSError("Windows Job Objects are available only on Windows.")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    signatures = {
        "CreateJobObjectW": ([ctypes.c_void_p, wintypes.LPCWSTR], wintypes.HANDLE),
        "SetInformationJobObject": (
            [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD], wintypes.BOOL,
        ),
        "AssignProcessToJobObject": ([wintypes.HANDLE, wintypes.HANDLE], wintypes.BOOL),
        "CloseHandle": ([wintypes.HANDLE], wintypes.BOOL),
        "CreateToolhelp32Snapshot": ([wintypes.DWORD, wintypes.DWORD], wintypes.HANDLE),
        "Thread32First": ([wintypes.HANDLE, ctypes.POINTER(_ThreadEntry)], wintypes.BOOL),
        "Thread32Next": ([wintypes.HANDLE, ctypes.POINTER(_ThreadEntry)], wintypes.BOOL),
        "OpenThread": ([wintypes.DWORD, wintypes.BOOL, wintypes.DWORD], wintypes.HANDLE),
        "ResumeThread": ([wintypes.HANDLE], wintypes.DWORD),
        "GetCurrentProcess": ([], wintypes.HANDLE),
        "GetProcessTimes": (
            [wintypes.HANDLE, *([ctypes.POINTER(wintypes.FILETIME)] * 4)], wintypes.BOOL,
        ),
        "GetModuleFileNameW": ([wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD], wintypes.DWORD),
        "GetCommandLineW": ([], wintypes.LPWSTR),
        "CreateFileW": (
            [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
             wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE], wintypes.HANDLE,
        ),
    }
    for name, (arguments, result) in signatures.items():
        function = getattr(kernel, name)
        function.argtypes, function.restype = arguments, result
    return kernel


def retain_process_ownership(path: str | os.PathLike[str]) -> None:
    """Exclusively own a state record until this process fully exits.

    Acquire before any state/archive/ready publication. The non-inherited raw
    file handle deliberately has no finalizer or explicit close: ownership must
    survive interpreter cleanup and is released by Windows on process exit.
    Another bootstrap fails before it can replace the live owner's identity.
    """
    handle = _kernel().CreateFileW(
        os.fspath(path), 0x80000000 | 0x40000000, 0, None, 4, 0x80, None,
    )  # GENERIC_READ|WRITE, no sharing, non-inherited, OPEN_ALWAYS, normal file.
    if handle == _INVALID_HANDLE:
        error = ctypes.WinError(ctypes.get_last_error())
        error.add_note("Cannot acquire IGNIS process ownership; no identity was published.")
        raise error
    _process_ownership_handles.append(handle)


def current_process_identity() -> dict:
    """Native identity matching Win32_Process, including PID reuse protection."""
    kernel = _kernel()
    creation, exit_time, kernel_time, user_time = (wintypes.FILETIME() for _ in range(4))
    if not kernel.GetProcessTimes(kernel.GetCurrentProcess(), ctypes.byref(creation),
                                  ctypes.byref(exit_time), ctypes.byref(kernel_time), ctypes.byref(user_time)):
        raise ctypes.WinError(ctypes.get_last_error())
    ticks = creation.dwLowDateTime | (creation.dwHighDateTime << 32)
    created = datetime(1601, 1, 1, tzinfo=timezone.utc) + timedelta(microseconds=ticks // 10)
    filename = ctypes.create_unicode_buffer(32768)
    length = kernel.GetModuleFileNameW(None, filename, len(filename))
    if not length or length == len(filename):
        raise ctypes.WinError(ctypes.get_last_error())
    return {
        "pid": os.getpid(),
        # WMI exposes microseconds; .NET round-trip format writes seven digits.
        "creation_utc": created.isoformat(timespec="microseconds").replace("+00:00", "0Z"),
        "executable": filename.value,
        "command_line": kernel.GetCommandLineW(),
    }


class WindowsJob:
    """Own one unnamed, non-inheritable KILL_ON_JOB_CLOSE handle."""

    def __init__(self):
        self._handle = None
        kernel = _kernel()
        # NULL security attributes make the handle non-inheritable. An inherited
        # handle in the child would defeat KILL_ON_JOB_CLOSE on parent failure.
        handle = kernel.CreateJobObjectW(None, None)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        self._handle = handle
        limits = _ExtendedLimits()
        limits.BasicLimitInformation.LimitFlags = _KILL_ON_JOB_CLOSE
        if not kernel.SetInformationJobObject(
            handle, _JOB_EXTENDED_LIMIT_INFORMATION, ctypes.byref(limits), ctypes.sizeof(limits),
        ):
            error = ctypes.WinError(ctypes.get_last_error())
            self.close()
            raise error

    def assign(self, process: subprocess.Popen) -> None:
        if self._handle is None:
            raise RuntimeError("The Windows job is already closed.")
        # CPython 3.11/3.12 retains this native handle for Popen's entire lifetime.
        # Reopening by PID would introduce a process-ID reuse race.
        if not _kernel().AssignProcessToJobObject(self._handle, int(process._handle)):
            raise ctypes.WinError(ctypes.get_last_error())

    def close(self) -> None:
        """Idempotently release ownership; Windows kills remaining job members."""
        if self._handle is not None:
            handle, self._handle = self._handle, None
            if not _kernel().CloseHandle(handle):
                raise ctypes.WinError(ctypes.get_last_error())

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

    def __del__(self):
        try:
            self.close()
        except Exception:
            # Explicit close reports errors. Finalization cannot usefully do so.
            pass


def _ensure_process_guard() -> None:
    """Contain the owner before creation, including the pre-assignment window.

    All children inherit this outer job atomically at CreateProcess time. The
    individual child job remains useful for cancellation. Windows 8+ supports
    these nested jobs. This guard is never explicitly closed while we are alive.
    """
    global _process_guard_handle
    with _process_guard_lock:
        if _process_guard_handle is not None:
            return
        guard = WindowsJob()
        if not _kernel().AssignProcessToJobObject(guard._handle, _kernel().GetCurrentProcess()):
            error = ctypes.WinError(ctypes.get_last_error())
            guard.close()
            raise error
        _process_guard_handle, guard._handle = guard._handle, None


def _resume_initial_thread(process: subprocess.Popen) -> None:
    """Find the suspended initial thread without undocumented NT APIs.

    Popen closes CreateProcess's thread handle. Toolhelp/OpenThread recover it
    through documented APIs before any child user code has been allowed to run.
    """
    kernel = _kernel()
    snapshot = kernel.CreateToolhelp32Snapshot(_SNAPTHREAD, 0)
    if snapshot == _INVALID_HANDLE:
        raise ctypes.WinError(ctypes.get_last_error())
    thread_ids = []
    try:
        entry = _ThreadEntry()
        entry.dwSize = ctypes.sizeof(entry)
        present = kernel.Thread32First(snapshot, ctypes.byref(entry))
        while present:
            if entry.th32OwnerProcessID == process.pid:
                thread_ids.append(entry.th32ThreadID)
            entry.dwSize = ctypes.sizeof(entry)
            present = kernel.Thread32Next(snapshot, ctypes.byref(entry))
        error = ctypes.get_last_error()
        if error != _ERROR_NO_MORE_FILES:
            raise ctypes.WinError(error)
    finally:
        kernel.CloseHandle(snapshot)
    if len(thread_ids) != 1:
        raise RuntimeError(f"Expected one initial suspended thread, found {len(thread_ids)}.")
    thread = kernel.OpenThread(_THREAD_SUSPEND_RESUME, False, thread_ids[0])
    if not thread:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        count = kernel.ResumeThread(thread)
        if count == 0xFFFFFFFF:
            raise ctypes.WinError(ctypes.get_last_error())
        if count != 1:
            raise RuntimeError(f"Unexpected initial thread suspend count: {count}.")
    finally:
        kernel.CloseHandle(thread)


def spawn_in_job(args, **kwargs: Any) -> tuple[subprocess.Popen, WindowsJob]:
    """Start a Popen child suspended, contain it, then permit execution.

    Accepts ordinary Popen keyword arguments except ``shell=True`` and flags
    that would allow breakaway or debugging. Caller-provided CREATE_NO_WINDOW,
    stdout/stderr, cwd and env are preserved. If containment/resume fails, the
    child is terminated and reaped before the exception is propagated.
    """
    if os.name != "nt":
        raise OSError("spawn_in_job requires Windows; use Popen explicitly on other systems.")
    if kwargs.get("shell"):
        raise ValueError("Use an executable argument list, not shell=True.")
    flags = kwargs.pop("creationflags", 0)
    if flags & (0x01000000 | 0x00000001 | 0x00000002):
        raise ValueError("Breakaway and debugger creation flags are not supported.")
    _ensure_process_guard()
    job = WindowsJob()
    process = None
    try:
        process = subprocess.Popen(args, creationflags=flags | _CREATE_SUSPENDED, **kwargs)
        job.assign(process)
        _resume_initial_thread(process)
        return process, job
    except BaseException:
        try:
            if process is not None and process.poll() is None:
                process.kill()
                process.wait(timeout=10)
        finally:
            job.close()
        raise
