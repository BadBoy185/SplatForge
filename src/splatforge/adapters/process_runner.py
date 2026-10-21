"""Bounded external-process execution with Windows Job Object containment."""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from splatforge.core.media import ExecutableIdentity
from splatforge.core.process import ProcessResult

if os.name == "nt":  # pragma: win32 cover - declarations are exercised by Windows tests
    from ctypes import wintypes


class ProcessBoundaryError(ValueError):
    """The requested executable or contained launch cannot be used."""


class ExecutableNotFoundError(ProcessBoundaryError):
    """An explicitly configured or PATH-resolved executable was not found."""


class ProcessCancellation(Protocol):
    def is_cancelled(self) -> bool: ...


@dataclass(frozen=True)
class ProcessRequest:
    executable: str
    argv: tuple[str, ...]
    working_directory: Path
    environment: Mapping[str, str]
    timeout_seconds: float
    max_stdout_bytes: int = 4 * 1024 * 1024
    max_stderr_bytes: int = 1024 * 1024
    teardown_timeout_seconds: float = 5.0


class ExecutableResolver:
    def __init__(self) -> None:
        self._identity_cache: dict[tuple[str, int, int], ExecutableIdentity] = {}

    def resolve(self, requested: str) -> ExecutableIdentity:
        candidate = Path(requested)
        if candidate.is_absolute() or candidate.parent != Path("."):
            path = candidate.absolute()
        else:
            path = self._search_path(requested)
        if not path.is_file():
            raise ExecutableNotFoundError(f"Executable not found: {requested}")
        path = path.resolve(strict=True)
        stat = path.stat()
        key = (str(path), stat.st_size, stat.st_mtime_ns)
        cached = self._identity_cache.get(key)
        if cached is not None:
            return cached
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
        identity = ExecutableIdentity(
            resolved_path=str(path),
            size=stat.st_size,
            last_write_ns=stat.st_mtime_ns,
            sha256=digest.hexdigest(),
        )
        self._identity_cache[key] = identity
        return identity

    @staticmethod
    def _search_path(name: str) -> Path:
        suffixes = [""]
        if os.name == "nt" and not Path(name).suffix:
            suffixes = [
                item.lower() for item in os.environ.get("PATHEXT", ".EXE").split(os.pathsep)
            ]
        for entry in os.environ.get("PATH", "").split(os.pathsep):
            if not entry:
                continue
            directory = Path(entry)
            if not directory.is_absolute():
                continue
            for suffix in suffixes:
                candidate = directory / f"{name}{suffix}"
                if candidate.is_file():
                    return candidate
        raise ExecutableNotFoundError(
            f"Executable '{name}' was not found on a safe absolute PATH entry"
        )


class _BoundedCollector:
    def __init__(self, stream: object, limit: int) -> None:
        self._stream = stream
        self._limit = limit
        self.data = bytearray()
        self.truncated = False
        self.thread = threading.Thread(target=self._drain, daemon=True)

    def _drain(self) -> None:
        stream = self._stream
        while True:
            chunk = stream.read(65536)  # type: ignore[attr-defined]
            if not chunk:
                return
            remaining = self._limit - len(self.data)
            if remaining > 0:
                self.data.extend(chunk[:remaining])
            if len(chunk) > remaining:
                self.truncated = True


if os.name == "nt":  # pragma: win32 cover
    _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
    _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
    _JOB_OBJECT_BASIC_ACCOUNTING_INFORMATION = 1

    class _IoCounters(ctypes.Structure):
        _fields_ = [
            ("read_operations", ctypes.c_ulonglong),
            ("write_operations", ctypes.c_ulonglong),
            ("other_operations", ctypes.c_ulonglong),
            ("read_bytes", ctypes.c_ulonglong),
            ("write_bytes", ctypes.c_ulonglong),
            ("other_bytes", ctypes.c_ulonglong),
        ]

    class _BasicLimitInformation(ctypes.Structure):
        _fields_ = [
            ("per_process_user_time_limit", ctypes.c_longlong),
            ("per_job_user_time_limit", ctypes.c_longlong),
            ("limit_flags", wintypes.DWORD),
            ("minimum_working_set_size", ctypes.c_size_t),
            ("maximum_working_set_size", ctypes.c_size_t),
            ("active_process_limit", wintypes.DWORD),
            ("affinity", ctypes.c_size_t),
            ("priority_class", wintypes.DWORD),
            ("scheduling_class", wintypes.DWORD),
        ]

    class _ExtendedLimitInformation(ctypes.Structure):
        _fields_ = [
            ("basic_limit_information", _BasicLimitInformation),
            ("io_info", _IoCounters),
            ("process_memory_limit", ctypes.c_size_t),
            ("job_memory_limit", ctypes.c_size_t),
            ("peak_process_memory_used", ctypes.c_size_t),
            ("peak_job_memory_used", ctypes.c_size_t),
        ]

    class _BasicAccountingInformation(ctypes.Structure):
        _fields_ = [
            ("total_user_time", ctypes.c_longlong),
            ("total_kernel_time", ctypes.c_longlong),
            ("this_period_total_user_time", ctypes.c_longlong),
            ("this_period_total_kernel_time", ctypes.c_longlong),
            ("total_page_fault_count", wintypes.DWORD),
            ("total_processes", wintypes.DWORD),
            ("active_processes", wintypes.DWORD),
            ("total_terminated_processes", wintypes.DWORD),
        ]

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _create_job = _kernel32.CreateJobObjectW
    _create_job.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    _create_job.restype = wintypes.HANDLE
    _set_job_information = _kernel32.SetInformationJobObject
    _set_job_information.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    _set_job_information.restype = wintypes.BOOL
    _assign_job = _kernel32.AssignProcessToJobObject
    _assign_job.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    _assign_job.restype = wintypes.BOOL
    _query_job = _kernel32.QueryInformationJobObject
    _query_job.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    _query_job.restype = wintypes.BOOL
    _terminate_job = _kernel32.TerminateJobObject
    _terminate_job.argtypes = [wintypes.HANDLE, wintypes.UINT]
    _terminate_job.restype = wintypes.BOOL
    _close_handle = _kernel32.CloseHandle
    _close_handle.argtypes = [wintypes.HANDLE]
    _close_handle.restype = wintypes.BOOL


class _WindowsJob:
    def __init__(self) -> None:
        handle = _create_job(None, None)
        if not handle:
            raise ProcessBoundaryError(f"Could not create Windows Job Object: {ctypes.WinError()}")
        self._handle = handle
        limits = _ExtendedLimitInformation()
        limits.basic_limit_information.limit_flags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not _set_job_information(
            handle,
            _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
            ctypes.byref(limits),
            ctypes.sizeof(limits),
        ):
            error = ctypes.WinError(ctypes.get_last_error())
            self.close()
            raise ProcessBoundaryError(f"Could not configure Windows Job Object: {error}")

    def assign(self, process: subprocess.Popen[bytes]) -> None:
        if not _assign_job(self._handle, int(process._handle)):  # type: ignore[attr-defined]
            error = ctypes.WinError(ctypes.get_last_error())
            raise ProcessBoundaryError(f"Could not contain process before backend launch: {error}")

    def active_processes(self) -> int:
        information = _BasicAccountingInformation()
        if not _query_job(
            self._handle,
            _JOB_OBJECT_BASIC_ACCOUNTING_INFORMATION,
            ctypes.byref(information),
            ctypes.sizeof(information),
            None,
        ):
            raise ProcessBoundaryError(
                f"Could not query Windows Job Object: {ctypes.WinError(ctypes.get_last_error())}"
            )
        return information.active_processes

    def terminate(self) -> None:
        if not _terminate_job(self._handle, 1):
            error = ctypes.WinError(ctypes.get_last_error())
            raise ProcessBoundaryError(f"Could not terminate Windows Job Object: {error}")

    def close(self) -> None:
        handle = getattr(self, "_handle", None)
        self._handle = None
        if handle:
            _close_handle(handle)


class LocalProcessRunner:
    def __init__(self, resolver: ExecutableResolver | None = None) -> None:
        self._resolver = resolver or ExecutableResolver()

    def run(
        self,
        request: ProcessRequest,
        *,
        cancellation: ProcessCancellation | None = None,
    ) -> ProcessResult:
        if request.timeout_seconds <= 0 or request.teardown_timeout_seconds <= 0:
            raise ValueError("Process timeouts must be positive")
        if request.max_stdout_bytes < 0 or request.max_stderr_bytes < 0:
            raise ValueError("Process output limits must be non-negative")
        identity = self._resolver.resolve(request.executable)
        cwd = request.working_directory.absolute()
        if not cwd.is_dir():
            raise ProcessBoundaryError(f"Process working directory does not exist: {cwd}")
        environment = dict(os.environ)
        environment.update(request.environment)
        message = (
            json.dumps(
                {
                    "executable": identity.resolved_path,
                    "argv": list(request.argv),
                    "cwd": str(cwd),
                    "env": environment,
                },
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
            + b"\n"
        )
        if len(message) > 1024 * 1024:
            raise ProcessBoundaryError("Process launch message exceeds 1 MiB")

        started = time.monotonic()
        worker = Path(__file__).with_name("process_worker.py").resolve()
        popen_kwargs: dict[str, object] = {}
        if os.name != "nt":
            popen_kwargs["start_new_session"] = True
        process = subprocess.Popen(
            [sys.executable, str(worker)],
            shell=False,
            cwd=str(cwd),
            env=dict(os.environ),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            close_fds=True,
            **popen_kwargs,
        )
        stdout = _BoundedCollector(process.stdout, request.max_stdout_bytes)
        stderr = _BoundedCollector(process.stderr, request.max_stderr_bytes)
        job = _WindowsJob() if os.name == "nt" else None
        timed_out = False
        cancelled = False
        teardown_confirmed = False
        exit_code: int | None = None
        try:
            if job is not None:
                job.assign(process)
            stdout.thread.start()
            stderr.thread.start()
            assert process.stdin is not None
            process.stdin.write(message)
            process.stdin.flush()
            process.stdin.close()
            deadline = started + request.timeout_seconds
            while process.poll() is None:
                if cancellation is not None and cancellation.is_cancelled():
                    cancelled = True
                    self._terminate(process, job)
                    break
                if time.monotonic() >= deadline:
                    timed_out = True
                    self._terminate(process, job)
                    break
                time.sleep(0.02)
            process.wait(timeout=request.teardown_timeout_seconds)
            if not timed_out and not cancelled:
                exit_code = process.returncode
            teardown_confirmed = self._wait_tree_empty(
                process, job, request.teardown_timeout_seconds
            )
        except BaseException:
            self._terminate(process, job)
            self._wait_tree_empty(process, job, request.teardown_timeout_seconds)
            raise
        finally:
            if process.stdin is not None and not process.stdin.closed:
                process.stdin.close()
            stdout.thread.join(timeout=request.teardown_timeout_seconds)
            stderr.thread.join(timeout=request.teardown_timeout_seconds)
            if job is not None:
                job.close()
        return ProcessResult(
            executable=identity,
            argv=request.argv,
            working_directory=str(cwd),
            exit_code=exit_code,
            elapsed_seconds=time.monotonic() - started,
            stdout=bytes(stdout.data),
            stderr=bytes(stderr.data),
            stdout_truncated=stdout.truncated,
            stderr_truncated=stderr.truncated,
            timed_out=timed_out,
            cancelled=cancelled,
            teardown_confirmed=teardown_confirmed,
        )

    @staticmethod
    def _terminate(process: subprocess.Popen[bytes], job: _WindowsJob | None) -> None:
        if job is not None:
            job.terminate()
        elif process.poll() is None:
            with suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)

    @staticmethod
    def _wait_tree_empty(
        process: subprocess.Popen[bytes], job: _WindowsJob | None, timeout: float
    ) -> bool:
        deadline = time.monotonic() + timeout
        if job is None:
            try:
                process.wait(timeout=max(0.0, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                return False
            return True
        while time.monotonic() < deadline:
            if job.active_processes() == 0:
                return True
            time.sleep(0.02)
        try:
            job.terminate()
        except ProcessBoundaryError:
            return False
        while time.monotonic() < deadline + timeout:
            if job.active_processes() == 0:
                return True
            time.sleep(0.02)
        return False
