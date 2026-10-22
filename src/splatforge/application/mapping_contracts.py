"""Inward-owned mapping adapter contract; application never parses native payloads."""

from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from splatforge.application.features_contracts import FeatureCancellation
from splatforge.core.process import ProcessInvocationEvidence
from splatforge.core.reconstruction import (
    CalibrationResult,
    GlobalMapperSettings,
    MappingBackend,
    MappingCalibrationPolicy,
    MappingInput,
    MappingResourceEstimate,
    MappingResourceLimits,
    ReconstructionComponent,
    ViewGraphCalibrationSettings,
)


class MappingAdapter(Protocol):
    def prepare(
        self,
        policy: MappingCalibrationPolicy,
        *,
        colmap: Path | None = None,
        settings: GlobalMapperSettings,
        calibration: ViewGraphCalibrationSettings | None,
    ) -> MappingBackend: ...

    def input(self, directory: Path) -> MappingInput: ...

    def map(
        self,
        workspace: Path,
        *,
        directory: Path,
        mapping_input: MappingInput,
        backend: MappingBackend,
        settings: GlobalMapperSettings,
        policy: MappingCalibrationPolicy,
        calibration: ViewGraphCalibrationSettings | None,
        limits: MappingResourceLimits,
        estimate: MappingResourceEstimate,
        cancellation: FeatureCancellation,
        evidence_sink: Callable[[ProcessInvocationEvidence], None],
        phase_sink: Callable[[str], None],
    ) -> tuple[CalibrationResult, tuple[ReconstructionComponent, ...]]: ...
