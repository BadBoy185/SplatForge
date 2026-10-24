"""Narrow inward-owned M10 native execution and validation boundary."""

from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from splatforge.application.features_contracts import FeatureCancellation
from splatforge.core.dataset import DatasetBackend, DatasetSettings, PreparedDatasetComponent
from splatforge.core.execution import DatasetComponentRoute
from splatforge.core.process import ProcessInvocationEvidence
from splatforge.core.reconstruction import ReconstructionComponent


class DatasetPreparer(Protocol):
    def prepare_backend(self, settings: DatasetSettings, colmap: Path | None) -> DatasetBackend: ...
    def inspect_input(
        self,
        directory: Path,
        component: ReconstructionComponent,
    ) -> tuple[dict[str, int], int, str]: ...
    def produce(
        self,
        workspace: Path,
        route: DatasetComponentRoute,
        reconstruction_directory: Path,
        candidate_directory: Path,
        cancellation: FeatureCancellation,
        evidence: Callable[[ProcessInvocationEvidence], None],
        phase: Callable[[str], None],
    ) -> PreparedDatasetComponent: ...
