"""Phase-only mapping reuses M6.5 history without a linear display fraction."""

from datetime import UTC, datetime
from uuid import UUID

from progress_helpers import FakeClock

from splatforge.application.eta import HybridThroughputEstimator
from splatforge.application.progress import ProgressSupport
from splatforge.core.progress import (
    ExecutionHardwareProfile,
    PerformanceBackendIdentity,
    PerformanceSample,
    PerformanceSignature,
    PlannedStage,
    ProgressMode,
    WorkDescription,
    WorkMetric,
    WorkUnit,
)


def test_historical_phase_job_has_eta_but_no_live_or_pipeline_percentage():
    plan = PlannedStage(
        work=WorkDescription(
            node_id="reconstruction",
            stage_id="mapping",
            method_id="mapping.colmap_global",
            work_model_id="mapping.global_phases_v1",
            unit=WorkUnit.WORK,
            mode=ProgressMode.PHASE,
            historical_job_duration=True,
            total=1.0,
        ),
        signature=PerformanceSignature(
            stage_id="mapping",
            method_id="mapping.colmap_global",
            work_model_id="mapping.global_phases_v1",
            unit=WorkUnit.WORK,
            backend=PerformanceBackendIdentity(
                adapter_id="test", family="colmap", runtime_version="a" * 64
            ),
            hardware=ExecutionHardwareProfile(),
            settings_key="b" * 64,
        ),
        workload=(WorkMetric(name="views", value=3.0),),
    )
    sample = PerformanceSample(
        recorded_at=datetime.now(UTC),
        signature=plan.signature,
        workload=plan.workload,
        total_work=1.0,
        elapsed_seconds=60.0,
        throughput=1.0 / 60,
    )
    estimator = HybridThroughputEstimator(plan, (sample,))
    eta = estimator.estimate()
    assert eta.evidence_mode == "historical" and eta.confidence in {"low", "medium"}
    assert eta.lower_seconds < eta.likely_seconds < eta.upper_seconds
    clock = FakeClock()
    session = ProgressSupport(clock=clock).session(UUID(int=1), (plan,), emit=lambda *_: None)
    session.start("reconstruction", UUID(int=2))
    clock.advance(30)
    session.report("reconstruction", 0, phase="global_mapping")
    assert session.snapshot().stages[0].fraction is None
    assert session.snapshot().fraction is None
    assert session.snapshot().stages[0].throughput is None
