"""Inward-owned execution boundary for local-feature extraction."""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from splatforge.core.capabilities import CapabilityEvidence
from splatforge.core.features import FeatureBackend, FeatureSettings, FeatureViewSummary
from splatforge.core.process import ProcessInvocationEvidence
from splatforge.core.views import CandidateView


class FeatureCapabilityError(ValueError):
    """Missing or unverified backend, model, schema or numerical option."""

    def __init__(self, message: str, *, evidence: tuple[CapabilityEvidence, ...] = ()) -> None:
        super().__init__(message)
        self.evidence = evidence


class FeatureProcessError(ValueError):
    """Contained backend failed; diagnostics retain its precise process outcome."""


class FeatureTimeoutError(FeatureProcessError):
    pass


class FeatureResourceError(FeatureProcessError):
    pass


class FeatureCancelledError(FeatureProcessError):
    pass


class FeatureTeardownError(FeatureProcessError):
    """Owned process-tree teardown is unresolved; retry/publication are blocked."""


class FeatureCancellation(Protocol):
    def is_cancelled(self) -> bool: ...


@dataclass(frozen=True)
class FeatureProgress:
    completed_views: int
    features: int


class FeatureExtractor(Protocol):
    def prepare(
        self,
        settings: FeatureSettings,
        *,
        colmap: Path | None,
        model_directory: Path | None,
    ) -> FeatureBackend: ...

    def extract(
        self,
        workspace: Path,
        *,
        backend: FeatureBackend,
        settings: FeatureSettings,
        candidate_directory: Path,
        views: tuple[CandidateView, ...],
        timeout_seconds: int,
        maximum_database_bytes: int,
        minimum_free_bytes: int,
        cancellation: FeatureCancellation,
        evidence_sink: Callable[[ProcessInvocationEvidence], None],
        progress_sink: Callable[[FeatureProgress], None] | None = None,
    ) -> tuple[FeatureViewSummary, ...]: ...
