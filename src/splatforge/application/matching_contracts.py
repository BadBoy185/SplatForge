"""Inward-owned M7b native execution interfaces."""

from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from splatforge.application.features_contracts import FeatureCancellation
from splatforge.core.features import FeatureSettings, LocalFeatureSet
from splatforge.core.geometry import CameraPriorSet, GeometryPairSummary, VerificationSettings
from splatforge.core.matching import (
    MatcherSettings,
    MatchingBackend,
    MatchingResourceEstimate,
    MatchingResourceLimits,
    MatchSet,
    RawPairSummary,
)
from splatforge.core.pairs import PairSet
from splatforge.core.process import ProcessInvocationEvidence


class MatchingAdapter(Protocol):
    def prepare(
        self,
        settings: MatcherSettings | VerificationSettings,
        *,
        feature_settings: FeatureSettings | None = None,
        colmap: Path | None = None,
        model_directory: Path | None = None,
    ) -> MatchingBackend: ...

    def match(
        self,
        workspace: Path,
        *,
        backend: MatchingBackend,
        settings: MatcherSettings,
        feature_directory: Path,
        pair_directory: Path,
        features: LocalFeatureSet,
        pairs: PairSet,
        limits: MatchingResourceLimits,
        estimate: MatchingResourceEstimate,
        cancellation: FeatureCancellation,
        evidence_sink: Callable[[ProcessInvocationEvidence], None],
        phase_sink: Callable[[str], None],
    ) -> tuple[RawPairSummary, ...]: ...

    def verify(
        self,
        workspace: Path,
        *,
        backend: MatchingBackend,
        settings: VerificationSettings,
        match_directory: Path,
        matches: MatchSet,
        features: LocalFeatureSet,
        pairs: PairSet,
        cameras: CameraPriorSet,
        limits: MatchingResourceLimits,
        estimate: MatchingResourceEstimate,
        cancellation: FeatureCancellation,
        evidence_sink: Callable[[ProcessInvocationEvidence], None],
        phase_sink: Callable[[str], None],
    ) -> tuple[GeometryPairSummary, ...]: ...
