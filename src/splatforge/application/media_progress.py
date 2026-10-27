"""Real source-ingest observations and live-only M6.5 ETA; no history or identity changes."""

from collections.abc import Callable
from datetime import UTC, datetime
from time import monotonic
from typing import Literal

from splatforge.application.eta import HybridThroughputEstimator
from splatforge.core.progress import (
    EtaEstimate,
    ExecutionHardwareProfile,
    PerformanceBackendIdentity,
    PerformanceSignature,
    PlannedStage,
    StageProgressObservation,
    WorkDescription,
    WorkUnit,
)
from splatforge.core.views import FrozenModel

ImportPhase = Literal["hashing", "metadata", "checked", "finalizing", "succeeded"]


class MediaImportProgress(FrozenModel):
    phase: ImportPhase
    filename: str = ""
    observation: StageProgressObservation
    eta: EtaEstimate


class ImportReporter:
    def __init__(
        self,
        total: int,
        callback: Callable[[MediaImportProgress], None] | None,
        *,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self.callback, self.clock, self.started = callback, clock, clock()
        self.work = WorkDescription(
            stage_id="media.ingest",
            node_id="media.ingest",
            method_id="media.ingest",
            work_model_id="media.checked_sources_v1",
            unit=WorkUnit.WORK,
            total=float(total),
        )
        # No fabricated hardware measurement and no persistent throughput samples.
        signature = PerformanceSignature(
            stage_id=self.work.stage_id,
            method_id=self.work.method_id,
            work_model_id=self.work.work_model_id,
            unit=self.work.unit,
            hardware=ExecutionHardwareProfile(device="cpu"),
            backend=PerformanceBackendIdentity(
                adapter_id="media.ingest",
                family="local_sources",
                runtime_version="v1",
            ),
            settings_key="0" * 64,
        )
        self.estimator = HybridThroughputEstimator(
            PlannedStage(work=self.work, signature=signature)
        )

    def emit(self, phase: ImportPhase, completed: int, filename: str = "") -> None:
        if self.callback is None:
            return
        observation = StageProgressObservation(
            work=self.work,
            phase_id=phase,
            completed=float(completed),
            observed_at=datetime.now(UTC),
            elapsed_seconds=max(0.0, self.clock() - self.started),
        )
        self.estimator.observe(observation)
        eta = self.estimator.estimate()
        if {"live_stalled", "variable_live"}.intersection(eta.reasons):
            eta = EtaEstimate(reasons=eta.reasons)
        # Whole files vary greatly in cost. Require several completed sources and
        # stable live evidence; final publication has no measured remaining work.
        if phase == "finalizing" or (phase != "succeeded" and "stable_live" not in eta.reasons):
            eta = EtaEstimate(reasons=("live_warmup",))
        self.callback(
            MediaImportProgress(
                phase=phase,
                filename=filename,
                observation=observation,
                eta=eta,
            )
        )
