"""Inward-owned contracts for M3 candidate-view materialization."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from splatforge.core.media import ExecutableIdentity, SourceOccurrence
from splatforge.core.process import ProcessInvocationEvidence
from splatforge.core.quality import (
    QualityAnalysisSettings,
    QualityBackendIdentity,
    QualityReport,
    SharpestSelectedViewSet,
    ViewQualityMeasurement,
)
from splatforge.core.views import (
    CandidatePoolSettings,
    CandidateView,
    CandidateViewSet,
    RationalValue,
    SelectedViewSet,
)


class ViewPreparationError(ValueError):
    code = "view_preparation_failed"


class FFmpegMissingError(ViewPreparationError):
    code = "ffmpeg_missing"


class FFmpegTimeoutError(ViewPreparationError):
    code = "timeout"


class FFmpegCancelledError(ViewPreparationError):
    code = "cancelled"

    def __init__(self, message: str, *, teardown_confirmed: bool) -> None:
        super().__init__(message)
        self.teardown_confirmed = teardown_confirmed


class FFmpegTeardownError(ViewPreparationError):
    code = "teardown_unconfirmed"


class FFmpegForcedCleanupError(ViewPreparationError):
    code = "forced_tree_termination"


class FFmpegBackendError(ViewPreparationError):
    code = "backend_failure"


class FFmpegOutputError(ViewPreparationError):
    code = "invalid_ffmpeg_output"


@dataclass(frozen=True)
class MaterializedFrame:
    temporary_path: Path
    sequence_index: int
    pts: int | None
    time_base: RationalValue | None


@dataclass(frozen=True)
class MaterializedFile:
    size: int
    sha256: str


@dataclass(frozen=True)
class MaterializationProgress:
    """Structured source-duration evidence from the owned FFmpeg process."""

    processed_source_seconds: float
    total_source_seconds: float
    elapsed_seconds: float


class CancellationSignal(Protocol):
    def is_cancelled(self) -> bool: ...


class CandidateMaterializer(Protocol):
    def identity(self, cancellation: CancellationSignal | None = None) -> ExecutableIdentity: ...

    def materialize(
        self,
        source_path: Path,
        source: SourceOccurrence,
        output_directory: Path,
        settings: CandidatePoolSettings,
        *,
        timeout_seconds: int,
        expected_backend: ExecutableIdentity,
        cancellation: CancellationSignal | None = None,
        evidence_sink: Callable[[ProcessInvocationEvidence], None] | None = None,
        progress_sink: Callable[[MaterializationProgress], None] | None = None,
    ) -> tuple[MaterializedFrame, ...]: ...


class QualityAssessor(Protocol):
    def identity(self) -> QualityBackendIdentity: ...

    def measure(
        self,
        image_path: Path,
        view: CandidateView,
        settings: QualityAnalysisSettings,
    ) -> ViewQualityMeasurement: ...


class ViewWorkspace(Protocol):
    def free_bytes(self, workspace: Path) -> int: ...

    def prepare_candidate(self, workspace: Path) -> None: ...

    def source_output_directory(self, workspace: Path, source_index: int) -> Path: ...

    def publish_candidate_image(
        self, workspace: Path, temporary_path: Path, relative_path: str
    ) -> MaterializedFile: ...

    def write_candidate_metadata(self, workspace: Path, candidate: CandidateViewSet) -> None: ...

    def write_selected_metadata(
        self, workspace: Path, selected: SelectedViewSet | SharpestSelectedViewSet
    ) -> None: ...

    def write_quality_metadata(self, workspace: Path, quality: QualityReport) -> None: ...
