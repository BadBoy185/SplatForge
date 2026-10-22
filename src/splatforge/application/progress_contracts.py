"""Small injected boundaries for optional progress diagnostics."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol
from uuid import UUID

from splatforge.core.execution import RunSnapshot
from splatforge.core.progress import (
    ExecutionHardwareProfile,
    HistoryRead,
    PerformanceSample,
    PerformanceSignature,
    PerformanceStatistics,
    PipelineProgressSnapshot,
)


class ProgressClock(Protocol):
    def monotonic(self) -> float: ...

    def utcnow(self) -> datetime: ...


class HardwareObserver(Protocol):
    def observe(self) -> ExecutionHardwareProfile: ...


class PerformanceHistory(Protocol):
    def read(self, signature: PerformanceSignature) -> HistoryRead: ...

    def record(self, sample: PerformanceSample) -> tuple[str, ...]: ...

    def statistics(self) -> PerformanceStatistics: ...

    def reset(self) -> tuple[str, ...]: ...


@dataclass(frozen=True)
class AttemptLifecycle:
    node_id: str
    attempt_id: UUID
    status: str
    started_at: datetime | None
    finished_at: datetime | None


@dataclass(frozen=True)
class OutputBinding:
    node_id: str
    binding_kind: str


@dataclass(frozen=True)
class RunProgressEvidence:
    snapshot: RunSnapshot
    status: str
    started_at: datetime
    finished_at: datetime | None
    cancellation_requested: bool
    cancellation_accepted: bool
    attempts: tuple[AttemptLifecycle, ...]
    outputs: tuple[OutputBinding, ...]
    latest: PipelineProgressSnapshot | None
    warnings: tuple[str, ...] = ()


class ProgressRepository(Protocol):
    def read_progress_evidence(self, root: Path, run_id: UUID) -> RunProgressEvidence: ...
