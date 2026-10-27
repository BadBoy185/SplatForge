"""Inward-owned contracts and diagnostics for media ingest adapters."""

from __future__ import annotations

from contextlib import AbstractContextManager
from pathlib import Path
from typing import BinaryIO, Protocol

from splatforge.core.media import FullHashEvidence, MediaType, NormalizedProbe, SourceEvidence


def classify_media_path(path: Path) -> MediaType | None:
    """Extension candidacy only; ingest still probes and validates actual content."""
    if path.suffix.lower() in {".jpg", ".jpeg", ".png"}:
        return MediaType.PHOTO
    if path.suffix.lower() in {".mp4", ".mov"}:
        return MediaType.VIDEO
    return None


class MediaAdapterError(ValueError):
    code = "media_adapter_failure"


class SourceUnavailableError(MediaAdapterError):
    code = "source_unavailable"

    def __init__(self, message: str, *, missing: bool = False) -> None:
        super().__init__(message)
        self.missing = missing


class SourceUnstableError(MediaAdapterError):
    code = "source_unstable"


class StrictSourceUnavailableError(MediaAdapterError):
    code = "strict_unavailable"


class ProbeError(MediaAdapterError):
    code = "probe_failed"


class ProbeUnsupportedError(ProbeError):
    code = "probe_unsupported"


class ProbeMissingError(ProbeError):
    code = "ffprobe_missing"


class ProbeTimeoutError(ProbeError):
    code = "timeout"


class ProbeCancelledError(ProbeError):
    code = "cancelled"


class ProbeBackendError(ProbeError):
    code = "backend_failure"


class ProbeOutputError(ProbeError):
    code = "invalid_ffprobe_output"


class MediaCancellation(Protocol):
    def checkpoint(self) -> None: ...

    def is_cancelled(self) -> bool: ...


class HashResult(Protocol):
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
        self, lease: SourceReadLease, control: MediaCancellation | None = None
    ) -> HashResult: ...


class MediaProbe(Protocol):
    def probe(
        self,
        path: Path,
        media_type: MediaType,
        *,
        cancellation: MediaCancellation | None = None,
    ) -> NormalizedProbe: ...
