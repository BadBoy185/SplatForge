"""Streamed source hashing and Windows stable source-read leases."""

from __future__ import annotations

import ctypes
import hashlib
import os
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from typing import BinaryIO, Protocol

from splatforge.application.media_contracts import (
    SourceUnavailableError,
    SourceUnstableError,
    StrictSourceUnavailableError,
)
from splatforge.core.media import FullHashEvidence, SourceEvidence, StorageKind

if os.name == "nt":  # pragma: win32 cover - declarations are exercised by Windows tests
    import msvcrt
    from ctypes import wintypes


class CancellationCheckpoint(Protocol):
    def checkpoint(self) -> None: ...


@dataclass(frozen=True)
class HashResult:
    sha256: str
    evidence: FullHashEvidence


class SourceReadLease(Protocol):
    path: Path
    stream: BinaryIO
    evidence_before: SourceEvidence
    stability_mechanism: str

    def current_evidence(self) -> SourceEvidence: ...


class SourceFiles(Protocol):
    def evidence(self, path: Path) -> SourceEvidence: ...

    def lease(
        self, path: Path, *, strict: bool = False
    ) -> AbstractContextManager[SourceReadLease]: ...

    def hash_lease(
        self, lease: SourceReadLease, control: CancellationCheckpoint | None = None
    ) -> HashResult: ...


def _storage_kind(path: Path) -> StorageKind:
    if os.name != "nt":
        return StorageKind.UNKNOWN
    root = path.anchor
    if not root:
        return StorageKind.UNKNOWN
    drive_type = ctypes.windll.kernel32.GetDriveTypeW(str(root))
    if drive_type == 3:
        return StorageKind.LOCAL_FIXED
    if drive_type == 2:
        return StorageKind.REMOVABLE
    if drive_type == 4:
        return StorageKind.NETWORK
    return StorageKind.UNKNOWN


if os.name == "nt":  # pragma: win32 cover
    _GENERIC_READ = 0x80000000
    _FILE_SHARE_READ = 0x00000001
    _FILE_SHARE_WRITE = 0x00000002
    _FILE_SHARE_DELETE = 0x00000004
    _OPEN_EXISTING = 3
    _FILE_ATTRIBUTE_NORMAL = 0x00000080
    _FILE_FLAG_SEQUENTIAL_SCAN = 0x08000000
    _INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
    _FILE_BASIC_INFO_CLASS = 0

    class _FileTime(ctypes.Structure):
        _fields_ = [("low", wintypes.DWORD), ("high", wintypes.DWORD)]

        def integer(self) -> int:
            return (self.high << 32) | self.low

    class _ByHandleFileInformation(ctypes.Structure):
        _fields_ = [
            ("attributes", wintypes.DWORD),
            ("creation_time", _FileTime),
            ("last_access_time", _FileTime),
            ("last_write_time", _FileTime),
            ("volume_serial", wintypes.DWORD),
            ("size_high", wintypes.DWORD),
            ("size_low", wintypes.DWORD),
            ("links", wintypes.DWORD),
            ("file_index_high", wintypes.DWORD),
            ("file_index_low", wintypes.DWORD),
        ]

    class _FileBasicInfo(ctypes.Structure):
        _fields_ = [
            ("creation_time", ctypes.c_longlong),
            ("last_access_time", ctypes.c_longlong),
            ("last_write_time", ctypes.c_longlong),
            ("change_time", ctypes.c_longlong),
            ("attributes", wintypes.DWORD),
        ]

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _create_file = _kernel32.CreateFileW
    _create_file.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    _create_file.restype = wintypes.HANDLE
    _get_file_information = _kernel32.GetFileInformationByHandle
    _get_file_information.argtypes = [wintypes.HANDLE, ctypes.POINTER(_ByHandleFileInformation)]
    _get_file_information.restype = wintypes.BOOL
    _get_file_information_ex = _kernel32.GetFileInformationByHandleEx
    _get_file_information_ex.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    _get_file_information_ex.restype = wintypes.BOOL
    _close_handle = _kernel32.CloseHandle
    _close_handle.argtypes = [wintypes.HANDLE]
    _close_handle.restype = wintypes.BOOL


def _win_error(path: Path, operation: str) -> SourceUnavailableError:
    error = ctypes.get_last_error()
    return SourceUnavailableError(
        f"Could not {operation} source {path}: {ctypes.WinError(error)}",
        missing=error in {2, 3},
    )


def _windows_evidence(handle: int, path: Path) -> SourceEvidence:
    information = _ByHandleFileInformation()
    if not _get_file_information(handle, ctypes.byref(information)):
        raise _win_error(path, "inspect")
    basic = _FileBasicInfo()
    if not _get_file_information_ex(
        handle, _FILE_BASIC_INFO_CLASS, ctypes.byref(basic), ctypes.sizeof(basic)
    ):
        raise _win_error(path, "inspect change time for")
    size = (information.size_high << 32) | information.size_low
    file_index = (information.file_index_high << 32) | information.file_index_low
    return SourceEvidence(
        size=size,
        last_write_ns=information.last_write_time.integer() * 100,
        volume_id=f"{information.volume_serial:08x}",
        file_id=f"{file_index:016x}",
        change_time_ns=basic.change_time * 100,
        storage_kind=_storage_kind(path),
        evidence_available=True,
    )


class _WindowsLease:
    def __init__(self, path: Path, *, strict: bool, stable: bool = True) -> None:
        self.path = path.absolute()
        self.stream: BinaryIO
        self.evidence_before: SourceEvidence
        self.stability_mechanism = (
            "windows_read_lease_no_write_delete" if stable else "windows_shared_metadata_handle"
        )
        self._strict = strict
        self._stable = stable
        self._handle: int | None = None

    def __enter__(self) -> _WindowsLease:
        if self._strict and (self.path.is_symlink() or self.path.is_junction()):
            raise StrictSourceUnavailableError(
                "Strict verification is unavailable through a symlink or junction locator"
            )
        share = _FILE_SHARE_READ
        if not self._stable:
            share |= _FILE_SHARE_WRITE | _FILE_SHARE_DELETE
        handle = _create_file(
            str(self.path),
            _GENERIC_READ,
            share,
            None,
            _OPEN_EXISTING,
            _FILE_ATTRIBUTE_NORMAL | _FILE_FLAG_SEQUENTIAL_SCAN,
            None,
        )
        if handle == _INVALID_HANDLE_VALUE:
            raise _win_error(self.path, "open")
        self._handle = int(handle)
        try:
            self.evidence_before = _windows_evidence(self._handle, self.path)
            if self._strict and self.evidence_before.storage_kind != StorageKind.LOCAL_FIXED:
                raise StrictSourceUnavailableError(
                    "Strict verification currently requires a Windows local fixed-volume source"
                )
            descriptor = msvcrt.open_osfhandle(
                self._handle, os.O_RDONLY | getattr(os, "O_BINARY", 0)
            )
            self._handle = None
            self.stream = os.fdopen(descriptor, "rb", buffering=0)
            return self
        except BaseException:
            if self._handle is not None:
                _close_handle(self._handle)
                self._handle = None
            raise

    def current_evidence(self) -> SourceEvidence:
        handle = msvcrt.get_osfhandle(self.stream.fileno())
        return _windows_evidence(handle, self.path)

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.stream.close()


class _PortableLease:
    def __init__(self, path: Path, *, strict: bool) -> None:
        if strict:
            raise StrictSourceUnavailableError(
                "Strict verification requires the Windows stable read-lease adapter"
            )
        self.path = path.absolute()
        self.stability_mechanism = "before_after_file_evidence"
        self.stream: BinaryIO
        self.evidence_before: SourceEvidence

    def __enter__(self) -> _PortableLease:
        try:
            self.stream = self.path.open("rb", buffering=0)
            self.evidence_before = self.current_evidence()
        except OSError as exc:
            raise SourceUnavailableError(
                f"Could not open source {self.path}: {exc}",
                missing=isinstance(exc, FileNotFoundError),
            ) from exc
        return self

    def current_evidence(self) -> SourceEvidence:
        stat = os.fstat(self.stream.fileno())
        return SourceEvidence(
            size=stat.st_size,
            last_write_ns=stat.st_mtime_ns,
            volume_id=str(stat.st_dev),
            file_id=str(stat.st_ino),
            change_time_ns=stat.st_ctime_ns,
            storage_kind=StorageKind.UNKNOWN,
            evidence_available=True,
        )

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.stream.close()


class LocalSourceFiles:
    """Read external sources without copying them into project storage."""

    def __init__(self, *, chunk_size: int = 1024 * 1024) -> None:
        if chunk_size <= 0:
            raise ValueError("Hash chunk size must be positive")
        self._chunk_size = chunk_size

    def evidence(self, path: Path) -> SourceEvidence:
        absolute = path.absolute()
        try:
            if os.name == "nt":
                with _WindowsLease(absolute, strict=False, stable=False) as lease:
                    return lease.evidence_before
            with _PortableLease(absolute, strict=False) as lease:
                return lease.evidence_before
        except (SourceUnavailableError, SourceUnstableError, StrictSourceUnavailableError):
            raise
        except OSError as exc:
            raise SourceUnavailableError(
                f"Could not inspect source {absolute}: {exc}",
                missing=isinstance(exc, FileNotFoundError),
            ) from exc

    def lease(self, path: Path, *, strict: bool = False) -> AbstractContextManager[SourceReadLease]:
        absolute = path.absolute()
        if os.name == "nt":
            return _WindowsLease(absolute, strict=strict)
        return _PortableLease(absolute, strict=strict)

    def hash_lease(
        self, lease: SourceReadLease, control: CancellationCheckpoint | None = None
    ) -> HashResult:
        digest = hashlib.sha256()
        byte_count = 0
        buffer = bytearray(self._chunk_size)
        lease.stream.seek(0)
        while True:
            if control is not None:
                control.checkpoint()
            count = lease.stream.readinto(buffer)
            if not count:
                break
            digest.update(memoryview(buffer)[:count])
            byte_count += count
        if control is not None:
            control.checkpoint()
        after = lease.current_evidence()
        before = lease.evidence_before
        if before != after or byte_count != after.size:
            raise SourceUnstableError(f"Source changed while being hashed: {lease.path}")
        hashed_at = datetime.now(UTC)
        return HashResult(
            sha256=digest.hexdigest(),
            evidence=FullHashEvidence(
                hashed_at=hashed_at,
                byte_count=byte_count,
                evidence_before=before,
                evidence_after=after,
                stability_mechanism=lease.stability_mechanism,
            ),
        )
