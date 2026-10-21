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
    import msvcrt
    from ctypes import wintypes

    class _ExecutableBasicInfo(ctypes.Structure):
        _fields_ = [
            ("creation_time", ctypes.c_longlong),
            ("last_access_time", ctypes.c_longlong),
            ("last_write_time", ctypes.c_longlong),
            ("change_time", ctypes.c_longlong),
            ("attributes", wintypes.DWORD),
        ]

    _get_executable_information = ctypes.WinDLL(
        "kernel32", use_last_error=True
    ).GetFileInformationByHandleEx
    _get_executable_information.argtypes = [
        wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
    ]
    _get_executable_information.restype = wintypes.BOOL
    _read_executable_usn = ctypes.WinDLL(
        "kernel32", use_last_error=True
    ).DeviceIoControl
    _read_executable_usn.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
        ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p,
    ]
    _read_executable_usn.restype = wintypes.BOOL


def _executable_change_sequence(stream: object) -> int | None:
    """Read existing NTFS/ReFS USN evidence; never create or alter a journal."""

    if os.name != "nt":
        return 0  # POSIX ctime is already in the concrete file key.
    versions = (ctypes.c_ushort * 2)(2, 3)
    buffer = ctypes.create_string_buffer(4096)
    returned = wintypes.DWORD()
    handle = msvcrt.get_osfhandle(stream.fileno())  # type: ignore[attr-defined]
    if not _read_executable_usn(
        handle, 0x000900EB, ctypes.byref(versions), ctypes.sizeof(versions),
        buffer, ctypes.sizeof(buffer), ctypes.byref(returned), None,
    ):
        return None
    data = buffer.raw[:returned.value]
    if len(data) < 8:
        return None
    version = int.from_bytes(data[4:6], "little")
    offset = {2: 24, 3: 40}.get(version)
    if offset is None or len(data) < offset + 8:
        return None
    sequence = int.from_bytes(data[offset:offset + 8], "little", signed=True)
    return sequence if sequence > 0 else None


def _executable_change_time(stream: object, stat: os.stat_result) -> int:
    if os.name != "nt":
        return stat.st_ctime_ns
    information = _ExecutableBasicInfo()
    handle = msvcrt.get_osfhandle(stream.fileno())  # type: ignore[attr-defined]
    if not _get_executable_information(
        handle, 0, ctypes.byref(information), ctypes.sizeof(information)
    ):
        raise OSError(ctypes.get_last_error(), "Cannot observe executable change time")
    return information.change_time * 100


class ProcessBoundaryError(ValueError):
    """The requested executable or contained launch cannot be used."""


class ExecutableNotFoundError(ProcessBoundaryError):
    """An explicitly configured or PATH-resolved executable was not found."""


class ProcessCleanupError(ProcessBoundaryError):
    """Original process failure plus evidence from exceptional containment teardown."""

    def __init__(
        self, original_error: BaseException, *, teardown_confirmed: bool,
        forced_tree_termination: bool, cleanup_errors: tuple[str, ...] = (),
    ) -> None:
        self.original_error = original_error
        self.teardown_confirmed = teardown_confirmed
        self.forced_tree_termination = forced_tree_termination
        self.cleanup_errors = cleanup_errors
        super().__init__(
            f"{type(original_error).__name__}: {original_error}; "
            f"teardown_confirmed={teardown_confirmed}; "
            f"forced_tree_termination={forced_tree_termination}"
            + (f"; cleanup errors: {'; '.join(cleanup_errors)}" if cleanup_errors else "")
        )


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
    expected_executable: ExecutableIdentity | None = None


class ExecutableResolver:
    def __init__(self) -> None:
        self._identity_cache: dict[
            tuple[str, int, int, int, int, int, int | None], ExecutableIdentity
        ] = {}

    def resolve(
        self,
        requested: str,
        *,
        environment: Mapping[str, str] | None = None,
    ) -> ExecutableIdentity:
        candidate = Path(requested)
        if candidate.is_absolute() or candidate.parent != Path("."):
            path = candidate.absolute()
        else:
            path = self._search_path(requested, environment=environment)
        self._require_native(path)
        if not path.is_file():
            raise ExecutableNotFoundError(f"Executable not found: {requested}")
        path = path.resolve(strict=True)
        self._require_native(path)
        for _attempt in range(2):
            with path.open("rb") as stream:
                before = os.fstat(stream.fileno())
                change_before = _executable_change_time(stream, before)
                sequence_before = _executable_change_sequence(stream)
                key = self._cache_key(path, before, change_before, sequence_before)
                cached = self._identity_cache.get(key)
                if cached is not None and before.st_ino != 0 and sequence_before is not None:
                    return cached
                digest = hashlib.sha256()
                while chunk := stream.read(1024 * 1024):
                    digest.update(chunk)
                after = os.fstat(stream.fileno())
                change_after = _executable_change_time(stream, after)
                sequence_after = _executable_change_sequence(stream)
            if self._cache_key(path, after, change_after, sequence_after) != key:
                continue
            path_after = path.stat()
            if (
                path_after.st_dev, path_after.st_ino, path_after.st_size, path_after.st_mtime_ns
            ) != (
                after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns
            ):
                continue
            identity = ExecutableIdentity(
                resolved_path=str(path),
                size=after.st_size,
                last_write_ns=after.st_mtime_ns,
                volume_id=str(after.st_dev),
                file_id=str(after.st_ino),
                change_time_ns=change_after,
                sha256=digest.hexdigest(),
            )
            if cached is not None and cached == identity:
                return cached
            self._identity_cache = {
                item_key: value for item_key, value in self._identity_cache.items()
                if item_key[0] != str(path)
            }
            if len(self._identity_cache) >= 128:
                self._identity_cache.clear()
            self._identity_cache[key] = identity
            return identity
        raise ProcessBoundaryError(
            f"Executable changed while establishing its identity: {path}"
        )

    def verify_expected_identity(self, expected: ExecutableIdentity) -> bool:
        """Re-observe a frozen executable identity immediately before later use."""

        try:
            current = self.resolve(expected.resolved_path)
        except (ExecutableNotFoundError, ProcessBoundaryError, OSError):
            return False
        return current.model_copy(update={"version_line": None}) == expected.model_copy(
            update={"version_line": None}
        )

    @staticmethod
    def _cache_key(
        path: Path, stat: os.stat_result, change_time_ns: int, change_sequence: int | None
    ) -> tuple[str, int, int, int, int, int, int | None]:
        return (
            str(path),
            stat.st_dev,
            stat.st_ino,
            stat.st_size,
            stat.st_mtime_ns,
            change_time_ns,
            change_sequence,
        )

    @staticmethod
    def _require_native(path: Path) -> None:
        if os.name == "nt" and path.suffix.lower() != ".exe":
            raise ProcessBoundaryError(
                f"Windows process execution requires a native .exe entrypoint: {path}"
            )

    @staticmethod
    def _search_path(
        name: str,
        *,
        environment: Mapping[str, str] | None = None,
    ) -> Path:
        values = os.environ if environment is None else environment
        suffixes = [""]
        if os.name == "nt" and not Path(name).suffix:
            suffixes = [
                item.lower() for item in values.get("PATHEXT", ".EXE").split(os.pathsep)
                if item.lower() == ".exe"
            ]
        for entry in values.get("PATH", "").split(os.pathsep):
            if not entry:
                continue
            directory = Path(entry)
            if not directory.is_absolute():
                continue
            if directory.resolve() == Path.cwd().resolve():
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
        if request.expected_executable is not None and identity != (
            request.expected_executable.model_copy(update={"version_line": None})
        ):
            raise ProcessBoundaryError("Executable changed after its identity was frozen")
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
        job = _WindowsJob() if os.name == "nt" else None
        try:
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
        except BaseException:
            if job is not None:
                with suppress(Exception):
                    job.close()
            raise
        try:
            stdout = _BoundedCollector(process.stdout, request.max_stdout_bytes)
            stderr = _BoundedCollector(process.stderr, request.max_stderr_bytes)
            if job is not None:
                job.assign(process)
        except BaseException as exc:
            errors: list[str] = []
            confirmed = False
            try:
                self._stop_uncontained_worker(process, request.teardown_timeout_seconds)
                confirmed = True
            except BaseException as cleanup_exc:
                errors.append(repr(cleanup_exc))
            actions = [lambda: self._close_process_pipes(process)]
            if job is not None:
                actions.append(job.close)
            for action in actions:
                try:
                    action()
                except BaseException as cleanup_exc:
                    errors.append(repr(cleanup_exc))
            raise ProcessCleanupError(
                exc, teardown_confirmed=confirmed, forced_tree_termination=True,
                cleanup_errors=tuple(errors),
            ) from exc
        timed_out = False
        cancelled = False
        teardown_confirmed = False
        forced_tree_termination = False
        exit_code: int | None = None
        stdout_started = False
        stderr_started = False
        original_error: BaseException | None = None
        cleanup_errors: list[str] = []
        try:
            stdout.thread.start()
            stdout_started = True
            stderr.thread.start()
            stderr_started = True
            assert process.stdin is not None
            process.stdin.write(message)
            process.stdin.flush()
            process.stdin.close()
            deadline = started + request.timeout_seconds
            while process.poll() is None:
                if cancellation is not None and cancellation.is_cancelled():
                    cancelled = True
                    forced_tree_termination = True
                    self._terminate(process, job)
                    break
                if time.monotonic() >= deadline:
                    timed_out = True
                    forced_tree_termination = True
                    self._terminate(process, job)
                    break
                time.sleep(0.02)
            process.wait(timeout=request.teardown_timeout_seconds)
            if not timed_out and not cancelled:
                exit_code = process.returncode
            teardown_confirmed, cleanup_forced = self._wait_tree_empty(
                process, job, request.teardown_timeout_seconds
            )
            forced_tree_termination = forced_tree_termination or cleanup_forced
        except BaseException as exc:
            original_error = exc
            forced_tree_termination = True
            try:
                self._terminate(process, job)
            except BaseException as cleanup_exc:
                cleanup_errors.append(repr(cleanup_exc))
            # Confirmation must still run when termination itself failed.
            try:
                teardown_confirmed, _ = self._wait_tree_empty(
                    process, job, request.teardown_timeout_seconds
                )
                if teardown_confirmed:
                    process.wait(timeout=request.teardown_timeout_seconds)
            except BaseException as cleanup_exc:
                teardown_confirmed = False
                cleanup_errors.append(repr(cleanup_exc))
        finally:
            # A close/join failure must never mask the original exception or
            # erase the independently observed tree-empty result.
            actions = []
            # Closing the job is a final kill-on-close fallback, before touching
            # pipes whose readers may still be blocked in an unresolved child.
            if job is not None:
                actions.append(job.close)
            if stdout_started:
                actions.append(lambda: stdout.thread.join(
                    timeout=request.teardown_timeout_seconds
                ))
            if stderr_started:
                actions.append(lambda: stderr.thread.join(
                    timeout=request.teardown_timeout_seconds
                ))
            actions.append(lambda: self._close_process_pipes(
                process,
                skip_stdout=stdout_started and stdout.thread.is_alive(),
                skip_stderr=stderr_started and stderr.thread.is_alive(),
            ))
            for action in actions:
                try:
                    action()
                except BaseException as cleanup_exc:
                    if original_error is None:
                        original_error = cleanup_exc
                    else:
                        cleanup_errors.append(repr(cleanup_exc))
        if original_error is not None:
            raise ProcessCleanupError(
                original_error, teardown_confirmed=teardown_confirmed,
                forced_tree_termination=forced_tree_termination,
                cleanup_errors=tuple(cleanup_errors),
            ) from original_error
        if (
            request.expected_executable is not None
            and teardown_confirmed
            and not forced_tree_termination
            and not self._resolver.verify_expected_identity(request.expected_executable)
        ):
            raise ProcessBoundaryError("Executable changed during execution")
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
            forced_tree_termination=forced_tree_termination,
        )

    @staticmethod
    def _terminate(process: subprocess.Popen[bytes], job: _WindowsJob | None) -> None:
        if job is not None:
            job.terminate()
        elif process.poll() is None:
            with suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)

    @staticmethod
    def _stop_uncontained_worker(process: subprocess.Popen[bytes], timeout: float) -> None:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=timeout)

    @staticmethod
    def _close_process_pipes(
        process: subprocess.Popen[bytes], *, skip_stdout: bool = False, skip_stderr: bool = False,
    ) -> None:
        for stream in (
            process.stdin, None if skip_stdout else process.stdout,
            None if skip_stderr else process.stderr,
        ):
            if stream is not None and not stream.closed:
                with suppress(OSError):
                    stream.close()

    @staticmethod
    def _wait_tree_empty(
        process: subprocess.Popen[bytes], job: _WindowsJob | None, timeout: float
    ) -> tuple[bool, bool]:
        deadline = time.monotonic() + timeout
        if job is None:
            try:
                process.wait(timeout=max(0.0, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                return False, False
            return True, False
        while time.monotonic() < deadline:
            if job.active_processes() == 0:
                return True, False
            time.sleep(0.02)
        try:
            job.terminate()
        except ProcessBoundaryError:
            return False, True
        while time.monotonic() < deadline + timeout:
            if job.active_processes() == 0:
                return True, True
            time.sleep(0.02)
        return False, True
