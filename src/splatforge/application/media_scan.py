"""Read-only discovery contract. Confirmation and ingest are separate use cases."""

from collections.abc import Callable
from pathlib import Path
from typing import Literal, Protocol

from pydantic import Field

from splatforge.application.media_contracts import MediaCancellation
from splatforge.core.media import MediaType
from splatforge.core.views import FrozenModel


class ScanLimits(FrozenModel):
    max_entries: int = Field(default=20000, ge=1, le=100000)
    max_directories: int = Field(default=1000, ge=1, le=10000)
    max_depth: int = Field(default=32, ge=0, le=128)
    max_seconds: float = Field(default=30, gt=0, le=300)


class ScanEntry(FrozenModel):
    path: Path
    media_type: MediaType | None = None
    reason: str = ""


class ScanProgress(FrozenModel):
    entries: int = 0
    directories: int = 0


class MediaScanResult(FrozenModel):
    entries: tuple[ScanEntry, ...] = ()
    scanned: int = 0
    directories: int = 0
    stopped: Literal["", "entries", "directories", "depth", "time"] = ""

    @property
    def supported(self) -> tuple[Path, ...]:
        return tuple(e.path for e in self.entries if e.media_type is not None)

    @property
    def ignored(self) -> int:
        return sum(e.media_type is None for e in self.entries)


class MediaScanner(Protocol):
    def scan(
        self,
        paths: tuple[Path, ...],
        *,
        limits: ScanLimits | None = None,
        cancellation: MediaCancellation | None = None,
        progress: Callable[[ScanProgress], None] | None = None,
    ) -> MediaScanResult: ...
