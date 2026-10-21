"""Windows local-project writer locking.

The file contents are diagnostic only. Ownership is established exclusively by the
OS-held byte-range lock.
"""

from __future__ import annotations

import ctypes
import errno
import json
import os
from contextlib import suppress
from ctypes import wintypes
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from typing import BinaryIO, Protocol
from uuid import UUID, uuid4

from splatforge.application.projects import ProjectError, ProjectWriterBusyError

try:
    import msvcrt
except ImportError:  # pragma: no cover - exercised only on non-Windows hosts
    msvcrt = None  # type: ignore[assignment]


_PROCESS_INSTANCE_STARTED_AT = datetime.now(UTC)
_PROCESS_INSTANCE_TOKEN = uuid4()


def _validate_lock_handle(descriptor: int, path: Path) -> None:
    """Inspect the opened object, never a path subsequently reopened for writing."""
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)

    class FileInformation(ctypes.Structure):
        _fields_ = [
            ("attributes", wintypes.DWORD),
            ("created", wintypes.FILETIME),
            ("accessed", wintypes.FILETIME),
            ("written", wintypes.FILETIME),
            ("volume", wintypes.DWORD),
            ("size_high", wintypes.DWORD),
            ("size_low", wintypes.DWORD),
            ("links", wintypes.DWORD),
            ("index_high", wintypes.DWORD),
            ("index_low", wintypes.DWORD),
        ]

    handle = wintypes.HANDLE(msvcrt.get_osfhandle(descriptor))
    query = kernel.GetFileInformationByHandle
    query.argtypes = [wintypes.HANDLE, ctypes.POINTER(FileInformation)]
    query.restype = wintypes.BOOL
    info = FileInformation()
    if not query(handle, ctypes.byref(info)):
        raise ProjectError(f"Cannot inspect project lock: {ctypes.WinError()}")
    file_type = kernel.GetFileType
    file_type.argtypes = [wintypes.HANDLE]
    file_type.restype = wintypes.DWORD
    if info.attributes & (0x10 | 0x400) or info.links != 1 or file_type(handle) != 1:
        raise ProjectError("Project lock must be a plain file with exactly one hard link")
    final_path = kernel.GetFinalPathNameByHandleW
    final_path.argtypes = [wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD]
    final_path.restype = wintypes.DWORD
    buffer = ctypes.create_unicode_buffer(32768)
    length = final_path(handle, buffer, len(buffer), 0)
    if not length or length >= len(buffer):
        raise ProjectError("Cannot establish the opened project lock location")
    actual = buffer.value
    if actual.startswith("\\\\?\\UNC\\"):
        actual = "\\\\" + actual[8:]
    elif actual.startswith("\\\\?\\"):
        actual = actual[4:]
    expected = path.parent.resolve(strict=True) / path.name
    if os.path.normcase(actual) != os.path.normcase(str(expected)):
        raise ProjectError("Opened project lock resolves outside its owned project path")


def _open_lock(path: Path) -> tuple[int, bool]:
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    create = kernel.CreateFileW
    create.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
        wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
    ]
    create.restype = wintypes.HANDLE
    # OPEN_ALWAYS never truncates. OPEN_REPARSE_POINT opens the link itself;
    # BACKUP_SEMANTICS lets inspection reject directories and directory reparses.
    # Omitting FILE_SHARE_DELETE keeps this object at its inspected name while held.
    handle = create(str(path.absolute()), 0xC0000000, 0x3, None, 4, 0x02200000, None)
    error = ctypes.get_last_error()
    if handle == wintypes.HANDLE(-1).value:
        if error in {32, 33}:
            raise ProjectWriterBusyError(f"Another writer owns the project lock: {path}")
        raise ProjectError(f"Cannot safely open project lock: {ctypes.WinError(error)}")
    try:
        descriptor = msvcrt.open_osfhandle(handle, os.O_RDWR | os.O_BINARY)
    except BaseException:
        close = kernel.CloseHandle
        close.argtypes = [wintypes.HANDLE]
        close(handle)
        raise
    try:
        _validate_lock_handle(descriptor, path)
    except BaseException:
        os.close(descriptor)
        raise
    return descriptor, error != 183


class ProjectWriterLease(Protocol):
    created: bool

    def __enter__(self) -> ProjectWriterLease: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...

    def write_diagnostics(self, *, operation: str, owner_token: UUID) -> None: ...


class ProjectWriterLockFactory(Protocol):
    def __call__(self, path: Path) -> ProjectWriterLease: ...


class WindowsProjectWriterLock:
    """Non-blocking exclusive lock on byte zero of a stable local file."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._stream: BinaryIO | None = None
        self.created = False

    def __enter__(self) -> WindowsProjectWriterLock:
        if msvcrt is None:
            raise ProjectError("Project writes require Windows local-file locking")

        descriptor, self.created = _open_lock(self._path)

        stream = os.fdopen(descriptor, "r+b", buffering=0)
        try:
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            stream.close()
            if exc.errno in {errno.EACCES, errno.EDEADLK}:
                raise ProjectWriterBusyError(
                    f"Another writer owns the project lock: {self._path}"
                ) from exc
            raise
        self._stream = stream
        return self

    def write_diagnostics(self, *, operation: str, owner_token: UUID) -> None:
        stream = self._require_stream()
        _validate_lock_handle(stream.fileno(), self._path)
        data = (
            json.dumps(
                {
                    "diagnostic_only": True,
                    "operation": operation,
                    "owner_token": str(owner_token),
                    "pid": os.getpid(),
                    "process_instance_started_at": _PROCESS_INSTANCE_STARTED_AT.isoformat(),
                    "process_instance_token": str(_PROCESS_INSTANCE_TOKEN),
                    "recorded_at": datetime.now(UTC).isoformat(),
                },
                sort_keys=True,
            ).encode("utf-8")
            + b"\n"
        )
        stream.seek(0)
        stream.truncate(0)
        view = memoryview(data)
        while view:
            written = stream.write(view)
            if written is None or written <= 0:
                raise OSError("Could not write project lock diagnostics")
            view = view[written:]
        stream.flush()
        os.fsync(stream.fileno())

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        stream = self._stream
        self._stream = None
        if stream is None:
            return
        try:
            stream.seek(0)
            if msvcrt is not None:
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            # Closing the Windows handle also releases its byte-range locks. Never
            # turn an already committed project save into a reported failure here.
            pass
        with suppress(OSError):
            stream.close()

    def _require_stream(self) -> BinaryIO:
        if self._stream is None:
            raise RuntimeError("Project writer lock is not held")
        return self._stream
