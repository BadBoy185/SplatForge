"""Windows local-project writer locking.

The file contents are diagnostic only. Ownership is established exclusively by the
OS-held byte-range lock.
"""

from __future__ import annotations

import errno
import json
import os
from contextlib import suppress
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

        flags = os.O_RDWR | getattr(os, "O_BINARY", 0)
        try:
            descriptor = os.open(self._path, flags | os.O_CREAT | os.O_EXCL, 0o600)
            self.created = True
        except FileExistsError:
            descriptor = os.open(self._path, flags)

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
