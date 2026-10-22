"""Application-owned progress aggregation and best-effort runtime learning."""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID

from splatforge.application.eta import HybridThroughputEstimator, zero_eta
from splatforge.application.progress_contracts import PerformanceHistory, ProgressClock
from splatforge.core.progress import (
    Confidence,
    EtaEstimate,
    EvidenceMode,
    ExecutionHardwareProfile,
    PerformanceSample,
    PerformanceStatistics,
    PipelineProgressSnapshot,
    PlannedStage,
    ProgressMode,
    ProgressStatus,
    StageProgressObservation,
    StageProgressSnapshot,
    WorkMetric,
)

_DONE = {ProgressStatus.SUCCEEDED, ProgressStatus.CACHED, ProgressStatus.SKIPPED}
_STOPPED = {"failed", "cancelled", "interrupted", "cancellation_requested", "stopping"}
_CONFIDENCE = [Confidence.UNAVAILABLE, Confidence.LOW, Confidence.MEDIUM, Confidence.HIGH]


class RuntimeClock:
    def monotonic(self) -> float:
        return time.monotonic()

    def utcnow(self) -> datetime:
        return datetime.now(UTC)


def aggregate_pipeline(
    run_id: UUID,
    stages: tuple[StageProgressSnapshot, ...],
    *,
    status: str = "running",
    elapsed_seconds: float = 0,
    previous_fraction: float | None = None,
    warnings: tuple[str, ...] = (),
) -> PipelineProgressSnapshot:
    """Duration-weighted display; summed ranges are planning approximations only."""
    if status in _STOPPED:
        stages = tuple(
            stage.model_copy(
                update={
                    "eta": EtaEstimate(reasons=("run_not_active",)),
                    "throughput": None,
                }
            )
            if stage.status not in _DONE
            else stage
            for stage in stages
        )
    unknown = tuple(
        stage.work.node_id
        for stage in stages
        if stage.status not in _DONE and stage.eta.likely_seconds is None
    )
    remaining = [
        stage.eta
        for stage in stages
        if stage.status not in _DONE and stage.eta.likely_seconds is not None
    ]
    known = [stage for stage in stages if stage.status not in _DONE]
    eta = EtaEstimate(reasons=("unknown_remaining",))
    if not known:
        eta = zero_eta()
    elif remaining:
        confidence = min((value.confidence for value in remaining), key=_CONFIDENCE.index)
        if unknown:
            confidence = Confidence.LOW
        eta = EtaEstimate(
            likely_seconds=sum(value.likely_seconds for value in remaining),
            lower_seconds=sum(value.lower_seconds for value in remaining),
            upper_seconds=sum(value.upper_seconds for value in remaining),
            confidence=confidence,
            evidence_mode=EvidenceMode.HYBRID,
            sample_count=sum(value.sample_count for value in remaining),
            reasons=("partial_known_remaining",) if unknown else ("summed_planning_ranges",),
        )
    credited = total = 0.0
    for stage in stages:
        if stage.status in {ProgressStatus.CACHED, ProgressStatus.SKIPPED}:
            continue
        if stage.status == ProgressStatus.SUCCEEDED:
            total += stage.elapsed_seconds
            credited += stage.elapsed_seconds
        elif stage.eta.likely_seconds is not None:
            duration = stage.elapsed_seconds + stage.eta.likely_seconds
            total += duration
            credited += duration * (stage.fraction or 0)
    raw = None if unknown or total <= 0 else min(1, credited / total)
    if stages and all(stage.status in _DONE for stage in stages):
        raw = 1.0
    fraction = (
        max(previous_fraction or 0, raw or 0)
        if (previous_fraction is not None or raw is not None)
        else None
    )
    current = next(
        (
            stage
            for stage in stages
            if stage.status
            in {
                ProgressStatus.RUNNING,
                ProgressStatus.STOPPING,
            }
        ),
        None,
    )
    if status in _STOPPED:
        eta = EtaEstimate(reasons=("run_not_active",))
    return PipelineProgressSnapshot(
        run_id=run_id,
        status=status,
        elapsed_seconds=max(0, elapsed_seconds),
        stages=stages,
        current_node_id=current.work.node_id if current else None,
        current_stage=current,
        completed_stages=tuple(
            s.work.node_id for s in stages if s.status == ProgressStatus.SUCCEEDED
        ),
        cached_stages=tuple(s.work.node_id for s in stages if s.status == ProgressStatus.CACHED),
        skipped_stages=tuple(s.work.node_id for s in stages if s.status == ProgressStatus.SKIPPED),
        unknown_stages=unknown,
        fraction=fraction,
        recalculated_fraction=raw,
        eta=eta,
        warnings=tuple(sorted(set(warnings)))[:16],
    )


def estimate_plan(
    run_id: UUID,
    stages: tuple[PlannedStage, ...],
    history: PerformanceHistory | None = None,
) -> PipelineProgressSnapshot:
    """Estimate an already resolved plan, without processing or choosing methods."""
    snapshots = []
    warnings = []
    for stage in stages:
        samples = ()
        if history is not None and stage.disposition == "planned":
            try:
                result = history.read(stage.signature)
                samples = result.samples
                warnings.extend(result.warnings)
            except Exception:
                warnings.append("history.unavailable")
        cached = stage.disposition != "planned"
        snapshots.append(
            StageProgressSnapshot(
                work=stage.work,
                status=ProgressStatus(stage.disposition),
                fraction=1 if cached else None,
                throughput_unit=stage.work.unit,
                eta=zero_eta() if cached else HybridThroughputEstimator(stage, samples).estimate(),
            )
        )
    return aggregate_pipeline(run_id, tuple(snapshots), status="planned", warnings=tuple(warnings))


class ProgressSession:
    """One run, one executing owner. Never shared mutable application/global state.

    Live observations are cheap. Snapshot persistence is at most 2 Hz, requiring a
    1% work change or phase change, or a 1s heartbeat. Start/revision/cache/success
    boundaries are additive. No observation can authorize publication or resume.
    """

    def __init__(
        self,
        run_id: UUID,
        stages: tuple[PlannedStage, ...],
        *,
        emit: Callable[[str | None, UUID | None, dict[str, object]], object],
        history: PerformanceHistory | None = None,
        clock: ProgressClock | None = None,
    ) -> None:
        self.run_id = run_id
        self._clock = clock or RuntimeClock()
        self._history = history
        self._emit = emit
        self._plans = {stage.work.node_id: stage for stage in stages}
        self._estimators: dict[str, HybridThroughputEstimator] = {}
        self._started: dict[str, float] = {}
        self._run_started = self._clock.monotonic()
        initial = estimate_plan(run_id, stages, history)
        self._stages = {stage.work.node_id: stage for stage in initial.stages}
        self._warnings = set(initial.warnings)
        self._fraction: float | None = None
        self._last_persist = -float("inf")
        self._last_fraction = 0.0
        self._last_phase: str | None = None
        self._persist()

    def snapshot(self) -> PipelineProgressSnapshot:
        result = aggregate_pipeline(
            self.run_id,
            tuple(self._stages.values()),
            previous_fraction=self._fraction,
            elapsed_seconds=max(0, self._clock.monotonic() - self._run_started),
            warnings=tuple(self._warnings),
        )
        self._fraction = result.fraction
        return result

    def _persist(self, observation: StageProgressObservation | None = None) -> None:
        snapshot = self.snapshot()
        details: dict[str, object] = {"snapshot": snapshot.model_dump(mode="json")}
        if observation is not None:
            details["observation"] = observation.model_dump(mode="json")
        try:
            warning = self._emit(
                snapshot.current_node_id,
                snapshot.current_stage.attempt_id if snapshot.current_stage else None,
                details,
            )
            if warning is not None:
                self._warnings.add("progress.append_failed")
        except Exception:
            self._warnings.add("progress.append_failed")
        self._last_persist = self._clock.monotonic()
        if observation is not None:
            self._last_fraction = (
                observation.completed / observation.work.total if observation.work.total else 0
            )
            self._last_phase = observation.phase_id

    def start(self, node_id: str, attempt_id: UUID, plan: PlannedStage | None = None) -> None:
        if plan is not None:
            previous = self._plans[node_id]
            if plan != previous:
                plan = plan.model_copy(
                    update={
                        "work": plan.work.model_copy(
                            update={"plan_revision": previous.work.plan_revision + 1}
                        )
                    }
                )
            self._plans[node_id] = plan
        stage = self._plans[node_id]
        samples = ()
        if self._history is not None:
            try:
                history = self._history.read(stage.signature)
                samples = history.samples
                self._warnings.update(history.warnings)
            except Exception:
                self._warnings.add("history.unavailable")
        self._estimators[node_id] = HybridThroughputEstimator(stage, samples)
        self._started[node_id] = self._clock.monotonic()
        self._stages[node_id] = StageProgressSnapshot(
            work=stage.work,
            status=ProgressStatus.RUNNING,
            attempt_id=attempt_id,
            fraction=0 if stage.work.mode == ProgressMode.DETERMINATE else None,
            throughput_unit=stage.work.unit,
            eta=self._estimators[node_id].estimate(),
        )
        self.report(node_id, 0, phase="processing", force=True)

    def report(
        self,
        node_id: str,
        completed: float,
        *,
        phase: str = "processing",
        diagnostics: tuple[WorkMetric, ...] = (),
        force: bool = False,
    ) -> None:
        try:
            stage = self._stages[node_id]
            now = self._clock.monotonic()
            observation = StageProgressObservation(
                work=stage.work,
                phase_id=phase,
                phase_code=phase,
                completed=completed,
                observed_at=self._clock.utcnow(),
                elapsed_seconds=max(0, now - self._started[node_id]),
                diagnostics=diagnostics,
            )
            estimator = self._estimators[node_id]
            estimator.observe(observation)
            fraction = (
                (completed / stage.work.total if stage.work.total else 0)
                if (stage.work.mode == ProgressMode.DETERMINATE)
                else None
            )
            self._stages[node_id] = stage.model_copy(
                update={
                    "phase_id": phase,
                    "phase_code": phase,
                    "elapsed_seconds": observation.elapsed_seconds,
                    "completed": completed,
                    "fraction": fraction,
                    "throughput": estimator.throughput,
                    "eta": estimator.estimate(),
                    "observed_at": observation.observed_at,
                    "observation_age_seconds": 0,
                }
            )
            since = now - self._last_persist
            if force or (
                since >= 0.5
                and (
                    since >= 1
                    or phase != self._last_phase
                    or (fraction or 0) - self._last_fraction >= 0.01
                )
            ):
                self._persist(observation)
        except Exception:
            self._warnings.add("progress.observation_rejected")

    def cached(self, node_id: str) -> None:
        stage = self._stages[node_id]
        self._stages[node_id] = stage.model_copy(
            update={
                "status": ProgressStatus.CACHED,
                "fraction": 1,
                "eta": zero_eta(),
                "completed": stage.work.total or 0,
                "elapsed_seconds": 0,
                "throughput": None,
            }
        )
        self._persist()

    def complete(self, node_id: str, *, actual_plan: PlannedStage | None = None) -> None:
        """Call only after validated output and authoritative success have committed."""
        stage = self._stages[node_id]
        if stage.status == ProgressStatus.SUCCEEDED:
            return
        if actual_plan is not None:
            revision = stage.work.plan_revision + (actual_plan.work.total != stage.work.total)
            work = actual_plan.work.model_copy(update={"plan_revision": revision})
            self._plans[node_id] = actual_plan.model_copy(update={"work": work})
            stage = stage.model_copy(update={"work": work})
        elapsed = max(0, self._clock.monotonic() - self._started[node_id])
        self._stages[node_id] = stage.model_copy(
            update={
                "status": ProgressStatus.SUCCEEDED,
                "elapsed_seconds": elapsed,
                "completed": stage.work.total or stage.completed,
                "fraction": 1,
                "eta": zero_eta(),
                "observed_at": self._clock.utcnow(),
            }
        )
        if self._history is not None and (stage.work.total or 0) > 0 and elapsed > 0:
            plan = self._plans[node_id]
            try:
                self._warnings.update(
                    self._history.record(
                        PerformanceSample(
                            recorded_at=self._clock.utcnow(),
                            signature=plan.signature,
                            workload=plan.workload,
                            total_work=stage.work.total,
                            elapsed_seconds=elapsed,
                            throughput=stage.work.total / elapsed,
                        )
                    )
                )
            except Exception:
                self._warnings.add("history.unavailable")
        self._persist()


class ProgressSupport:
    """Injected execution-side dependencies, without run-specific mutable state."""

    def __init__(
        self,
        *,
        history: PerformanceHistory | None = None,
        clock: ProgressClock | None = None,
        hardware: ExecutionHardwareProfile | None = None,
    ) -> None:
        self.history = history
        self.clock = clock or RuntimeClock()
        self.hardware = hardware or ExecutionHardwareProfile()

    def session(
        self,
        run_id: UUID,
        stages: tuple[PlannedStage, ...],
        *,
        emit: Callable[[str | None, UUID | None, dict[str, object]], object],
    ) -> ProgressSession:
        return ProgressSession(run_id, stages, emit=emit, history=self.history, clock=self.clock)


class PerformanceService:
    """Project-independent inspection/reset use cases for private prediction data."""

    def __init__(self, history: PerformanceHistory) -> None:
        self._history = history

    def show(self) -> PerformanceStatistics:
        try:
            return self._history.statistics()
        except Exception:
            return PerformanceStatistics(warnings=("history.unavailable",))

    def reset(self) -> tuple[str, ...]:
        try:
            return self._history.reset()
        except Exception:
            return ("history.unavailable",)
