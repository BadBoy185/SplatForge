from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from splatforge.core.progress import (
    ExecutionHardwareProfile,
    PerformanceBackendIdentity,
    PerformanceSample,
    PerformanceSignature,
    PlannedStage,
    StageProgressObservation,
    WorkDescription,
    WorkMetric,
    WorkUnit,
)


@dataclass
class FakeClock:
    seconds: float = 0
    wall: datetime = datetime(2026, 10, 22, tzinfo=UTC)

    def monotonic(self) -> float:
        return self.seconds

    def utcnow(self) -> datetime:
        return self.wall + timedelta(seconds=self.seconds)

    def advance(self, seconds: float) -> None:
        self.seconds += seconds


def plan(total: float = 1000, *, node: str = "work") -> PlannedStage:
    work = WorkDescription(
        stage_id="test_processing",
        node_id=node,
        method_id="test.method",
        work_model_id="test.units_v1",
        unit=WorkUnit.WORK,
        total=total,
    )
    return PlannedStage(
        work=work,
        signature=PerformanceSignature(
            stage_id=work.stage_id,
            method_id=work.method_id,
            work_model_id=work.work_model_id,
            unit=work.unit,
            hardware=ExecutionHardwareProfile(
                platform_family="windows",
                cpu_family="test_cpu",
                logical_cpus=8,
                device="cpu",
            ),
            backend=PerformanceBackendIdentity(
                adapter_id="test.adapter",
                family="python",
                runtime_version="3.12",
            ),
            settings_key="a" * 64,
        ),
        workload=(WorkMetric(name="views", value=total),),
    )


def sample(
    stage: PlannedStage | None = None, *, rate: float = 100, clock: FakeClock | None = None
) -> PerformanceSample:
    stage = stage or plan()
    clock = clock or FakeClock()
    return PerformanceSample(
        recorded_at=clock.utcnow(),
        signature=stage.signature,
        workload=stage.workload,
        total_work=stage.work.total,
        elapsed_seconds=stage.work.total / rate,
        throughput=rate,
    )


def observation(stage: PlannedStage, completed: float, elapsed: float) -> StageProgressObservation:
    return StageProgressObservation(
        work=stage.work,
        completed=completed,
        observed_at=FakeClock(elapsed).utcnow(),
        elapsed_seconds=elapsed,
    )
