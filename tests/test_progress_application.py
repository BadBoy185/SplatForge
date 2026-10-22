from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from progress_helpers import FakeClock, plan, sample

from splatforge.adapters.performance import LocalPerformanceHistory
from splatforge.application.eta import zero_eta
from splatforge.application.progress import ProgressSession, aggregate_pipeline, estimate_plan
from splatforge.core.progress import (
    Confidence,
    EtaEstimate,
    EvidenceMode,
    PlannedStage,
    ProgressMode,
    ProgressStatus,
    StageProgressSnapshot,
)


def snapshot(stage: PlannedStage | None = None, **changes: object) -> StageProgressSnapshot:
    stage = stage or plan()
    return StageProgressSnapshot(
        work=stage.work,
        throughput_unit=stage.work.unit,
    ).model_copy(update=changes)


def eta(seconds: float) -> EtaEstimate:
    return EtaEstimate(
        likely_seconds=seconds,
        lower_seconds=seconds * 0.8,
        upper_seconds=seconds * 1.2,
        confidence=Confidence.MEDIUM,
        evidence_mode=EvidenceMode.HISTORICAL,
    )


def test_duration_weighted_pipeline_is_not_equal_mean() -> None:
    done = snapshot(
        plan(node="pairs"),
        status=ProgressStatus.SUCCEEDED,
        elapsed_seconds=10,
        fraction=1,
        eta=zero_eta(),
    )
    future = snapshot(plan(node="heavy"), eta=eta(2400), fraction=0)
    result = aggregate_pipeline(uuid4(), (done, future))
    assert result.fraction == pytest.approx(10 / 2410)
    assert result.eta.likely_seconds == 2400
    assert result.eta.lower_seconds == 1920
    assert result.eta.upper_seconds == 2880
    assert result.completed_stages == ("pairs",)


@pytest.mark.parametrize("status", [ProgressStatus.CACHED, ProgressStatus.SKIPPED])
def test_cached_and_skipped_have_no_remaining_runtime(status: ProgressStatus) -> None:
    done = snapshot(plan(node="first"), status=status, eta=zero_eta(), fraction=1)
    active = snapshot(
        plan(node="second"),
        status=ProgressStatus.RUNNING,
        fraction=0.5,
        elapsed_seconds=10,
        eta=eta(10),
    )
    result = aggregate_pipeline(uuid4(), (done, active))
    assert result.fraction == 0.5
    assert result.eta.likely_seconds == 10
    assert result.cached_stages + result.skipped_stages == ("first",)


def test_pipeline_eta_increases_and_decreases_while_display_never_recedes() -> None:
    run_id = uuid4()
    active = snapshot(status=ProgressStatus.RUNNING, fraction=0.5, elapsed_seconds=10, eta=eta(10))
    future = snapshot(plan(node="later"), eta=eta(10), fraction=0)
    first = aggregate_pipeline(run_id, (active, future))
    assert first.fraction == pytest.approx(1 / 3)
    slow = aggregate_pipeline(
        run_id,
        (active, future.model_copy(update={"eta": eta(100)})),
        previous_fraction=first.fraction,
    )
    assert slow.eta.likely_seconds > first.eta.likely_seconds
    assert slow.recalculated_fraction < first.fraction
    assert slow.fraction == first.fraction
    fast = aggregate_pipeline(
        run_id, (active, future.model_copy(update={"eta": eta(1)})), previous_fraction=slow.fraction
    )
    assert fast.eta.likely_seconds < slow.eta.likely_seconds
    assert fast.fraction > slow.fraction
    done = active.model_copy(
        update={
            "status": ProgressStatus.SUCCEEDED,
            "fraction": 1,
            "eta": zero_eta(),
            "elapsed_seconds": 20,
        }
    )
    completion = aggregate_pipeline(run_id, (done, future), previous_fraction=fast.fraction)
    assert completion.fraction > fast.fraction


def test_unknown_nonlinear_stage_keeps_partial_eta_honest() -> None:
    known = snapshot(eta=eta(240))
    unknown_work = plan(node="mapping").work.model_copy(
        update={
            "total": None,
            "mode": ProgressMode.INDETERMINATE,
        }
    )
    mapping = snapshot(plan(node="mapping")).model_copy(update={"work": unknown_work})
    result = aggregate_pipeline(uuid4(), (known, mapping))
    assert result.unknown_stages == ("mapping",)
    assert result.fraction is None
    assert result.eta.likely_seconds == 240
    assert result.eta.confidence == Confidence.LOW
    assert result.eta.reasons == ("partial_known_remaining",)
    all_unknown = aggregate_pipeline(uuid4(), (mapping,))
    assert all_unknown.eta.likely_seconds is None
    assert all_unknown.eta.confidence == Confidence.UNAVAILABLE


@pytest.mark.parametrize("status", ["failed", "cancelled", "interrupted", "stopping"])
def test_terminal_and_stopping_runs_have_no_active_eta(status: str) -> None:
    active = snapshot(status=ProgressStatus.RUNNING, eta=eta(100))
    result = aggregate_pipeline(uuid4(), (active,), status=status)
    assert result.eta.likely_seconds is None
    assert result.current_stage.eta.likely_seconds is None


def test_plan_estimation_never_reads_history_for_cached_or_skipped_stage(tmp_path: Path) -> None:
    history = LocalPerformanceHistory(tmp_path / "performance.sqlite")
    history.record(sample())
    cached = plan().model_copy(update={"disposition": "cached"})
    skipped = plan(node="skip").model_copy(update={"disposition": "skipped"})
    result = estimate_plan(uuid4(), (cached, skipped), history)
    assert result.eta.likely_seconds == 0
    assert result.fraction == 1
    assert result.stages[0].eta.sample_count == 0
    assert result.cached_stages == ("work",)
    assert result.skipped_stages == ("skip",)


def test_cold_success_second_run_learning_and_scale_normalization(tmp_path: Path) -> None:
    path = tmp_path / "executing-worker" / "performance.sqlite"
    history = LocalPerformanceHistory(path)
    clock = FakeClock()
    events = []

    def emit(node: str | None, attempt: object, details: dict[str, object]) -> None:
        events.append(details)

    stage = plan()
    first = ProgressSession(uuid4(), (stage,), emit=emit, history=history, clock=clock)
    first.start("work", uuid4())
    assert first.snapshot().current_stage.eta.likely_seconds is None
    for second in range(1, 11):
        clock.advance(1)
        first.report("work", second * 100)
        if second == 5:
            live = first.snapshot().current_stage.eta
            assert live.likely_seconds == 5
            assert live.evidence_mode == EvidenceMode.LIVE
    assert history.statistics().sample_count == 0
    first.complete("work")
    first.complete("work")  # successful completion cannot teach twice
    assert first.snapshot().stages[0].elapsed_seconds == 10
    assert history.statistics().sample_count == 1
    second = ProgressSession(uuid4(), (stage,), emit=emit, history=history, clock=clock)
    second.start("work", uuid4())
    prior = second.snapshot().current_stage.eta
    assert prior.likely_seconds == 10
    assert prior.sample_count == 1
    assert prior.confidence == Confidence.LOW
    assert prior.evidence_mode == EvidenceMode.HISTORICAL
    for index in range(1, 9):
        clock.advance(1)
        second.report("work", index * 100)
    assert second.snapshot().current_stage.eta.likely_seconds == 2
    scaled = estimate_plan(uuid4(), (plan(2000),), history)
    assert scaled.eta.likely_seconds == 20
    changed = stage.model_copy(
        update={
            "signature": stage.signature.model_copy(
                update={
                    "backend": stage.signature.backend.model_copy(
                        update={"runtime_version": "other"}
                    ),
                }
            )
        }
    )
    assert estimate_plan(uuid4(), (changed,), history).eta.likely_seconds is None
    assert events[-1]["snapshot"]["progress_schema_version"] == 1


def test_progress_throttles_fast_observations_and_phase_changes(tmp_path: Path) -> None:
    clock = FakeClock()
    events = []
    stage = plan(10000)
    session = ProgressSession(
        uuid4(), (stage,), clock=clock, emit=lambda *args: events.append(args)
    )
    session.start("work", uuid4())
    for index in range(1, 10001):
        clock.advance(0.001)
        session.report("work", index, phase="phase_a" if index % 2 else "phase_b")
    session.complete("work")
    assert len(events) <= 23  # 2 Hz + initial/start/terminal boundaries
    assert session.snapshot().fraction == 1
    assert session.snapshot().stages[0].completed == 10000


def test_plan_revision_is_explicit_and_invalid_observation_only_warns() -> None:
    clock = FakeClock()
    session = ProgressSession(uuid4(), (plan(),), emit=lambda *args: None, clock=clock)
    session.start("work", uuid4(), plan(2000))
    assert session.snapshot().current_stage.work.plan_revision == 2
    clock.advance(1)
    session.report("work", 2001)
    assert session.snapshot().current_stage.completed == 0
    assert "progress.observation_rejected" in session.snapshot().warnings
    session.complete("work", actual_plan=plan(1500))
    assert session.snapshot().stages[0].work.plan_revision == 3
    assert session.snapshot().stages[0].work.total == 1500


def test_history_and_event_failures_cannot_fail_progress_or_execution() -> None:
    class BrokenHistory:
        def read(self, *args: object) -> None:
            raise RuntimeError("private source path")

        def record(self, *args: object) -> None:
            raise RuntimeError("private source path")

    def broken_emit(*args: object) -> None:
        raise OSError("private source path")

    clock = FakeClock()
    session = ProgressSession(
        uuid4(), (plan(),), emit=broken_emit, history=BrokenHistory(), clock=clock
    )
    session.start("work", uuid4())
    clock.advance(5)
    session.report("work", 500)
    assert session.snapshot().current_stage.eta.evidence_mode == EvidenceMode.LIVE
    session.complete("work")
    assert session.snapshot().stages[0].status == ProgressStatus.SUCCEEDED
    assert session.snapshot().warnings == ("history.unavailable", "progress.append_failed")


def test_unfinished_attempts_and_cache_hits_are_never_learned(tmp_path: Path) -> None:
    history = LocalPerformanceHistory(tmp_path / "performance.sqlite")
    clock = FakeClock()
    session = ProgressSession(
        uuid4(), (plan(),), emit=lambda *args: None, history=history, clock=clock
    )
    session.start("work", uuid4())
    clock.advance(10)
    session.report("work", 900)
    assert history.statistics().sample_count == 0
    cached = ProgressSession(
        uuid4(), (plan(),), emit=lambda *args: None, history=history, clock=clock
    )
    cached.cached("work")
    assert cached.snapshot().eta.likely_seconds == 0
    assert history.statistics().sample_count == 0


def test_rate_calculation_ignores_wall_clock_skew() -> None:
    clock = FakeClock()
    session = ProgressSession(uuid4(), (plan(),), emit=lambda *args: None, clock=clock)
    session.start("work", uuid4())
    clock.advance(5)
    clock.wall = clock.wall.replace(year=2020)
    session.report("work", 500)
    assert session.snapshot().current_stage.throughput == 100
    assert session.snapshot().current_stage.eta.likely_seconds == 5
