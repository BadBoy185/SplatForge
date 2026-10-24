"""Inward-owned disposable trainer boundary."""

from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from splatforge.application.features_contracts import FeatureCancellation
from splatforge.core.execution import TrainingJobRoute, TrainingRuntime
from splatforge.core.process import ProcessInvocationEvidence
from splatforge.core.training import GaussianScene, TrainingBackendIdentity, TrainingCheckpoint
from splatforge.core.training_protocol import WorkerEvent


class TrainingBackend(Protocol):
    def capability(self, runtime: TrainingRuntime, ordinal: int = 0) -> TrainingBackendIdentity: ...

    def produce(
        self,
        workspace: Path,
        route: TrainingJobRoute,
        dataset: Path,
        resume: Path | None,
        cancellation: FeatureCancellation,
        events: Callable[[WorkerEvent], None],
        evidence: Callable[[ProcessInvocationEvidence], None],
    ) -> GaussianScene | TrainingCheckpoint: ...
