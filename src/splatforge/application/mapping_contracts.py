"""Inward-owned mapping adapter contract; application never parses native payloads."""

from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from splatforge.application.features_contracts import FeatureCancellation
from splatforge.core.process import ProcessInvocationEvidence
from splatforge.core.reconstruction import (
    CalibrationResult,
    GlobalMapperSettings,
    HierarchicalMapperSettings,
    IncrementalMapperSettings,
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
        settings: GlobalMapperSettings | IncrementalMapperSettings | HierarchicalMapperSettings,
        calibration: ViewGraphCalibrationSettings | None,
    ) -> MappingBackend: ...

    def input(self, directory: Path) -> MappingInput: ...

    def validate_incremental_input(
        self, directory: Path, frozen: MappingInput, settings: IncrementalMapperSettings,
    ) -> None: ...

    def map(
        self,
        workspace: Path,
        *,
        directory: Path,
        mapping_input: MappingInput,
        backend: MappingBackend,
        settings: GlobalMapperSettings | IncrementalMapperSettings | HierarchicalMapperSettings,
        policy: MappingCalibrationPolicy,
        calibration: ViewGraphCalibrationSettings | None,
        limits: MappingResourceLimits,
        estimate: MappingResourceEstimate,
        cancellation: FeatureCancellation,
        evidence_sink: Callable[[ProcessInvocationEvidence], None],
        phase_sink: Callable[[str], None],
        diagnostics_sink: Callable[[dict[str, object]], None],
    ) -> tuple[CalibrationResult, tuple[ReconstructionComponent, ...]]: ...
