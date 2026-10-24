"""Read-only reconciliation: SQLite lifecycle always outranks diagnostic progress."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from splatforge.application.eta import zero_eta
from splatforge.application.progress import RuntimeClock, aggregate_pipeline
from splatforge.application.progress_contracts import ProgressClock, ProgressRepository
from splatforge.core.execution import (
    DatasetRoute,
    FakeRoute,
    FeatureExtractionRoute,
    FeatureMatchingRoute,
    GeometricVerificationRoute,
    MappingRoute,
    PairSelectionRoute,
    ReconstructionEvidenceRoute,
    RetrievalBuildRoute,
    SharpestViewPreparationRoute,
    TrainingRoute,
)
from splatforge.core.progress import (
    EtaEstimate,
    PipelineProgressSnapshot,
    ProgressMode,
    ProgressStatus,
    StageProgressSnapshot,
    WorkDescription,
    WorkUnit,
)


class RunProgressService:
    def __init__(self, repository: ProgressRepository, clock: ProgressClock | None = None) -> None:
        self._repository = repository
        self._clock = clock or RuntimeClock()

    def active(self, root: Path) -> tuple[PipelineProgressSnapshot, ...]:
        return tuple(self.get(root, run) for run in self._repository.active_run_ids(root))

    def get(self, root: Path, run_id: UUID) -> PipelineProgressSnapshot:
        evidence = self._repository.read_progress_evidence(root, run_id)
        now = self._clock.utcnow()
        route = evidence.snapshot.route
        if isinstance(route, FakeRoute):
            nodes = (route.sequence, route.scale)
        elif isinstance(route, (PairSelectionRoute, FeatureExtractionRoute, RetrievalBuildRoute,
                                FeatureMatchingRoute, GeometricVerificationRoute, MappingRoute,
                                ReconstructionEvidenceRoute, DatasetRoute, TrainingRoute)):
            nodes = ()
        elif isinstance(route, SharpestViewPreparationRoute):
            nodes = (route.candidate, route.quality, route.selection)
        else:
            nodes = (route.candidate, route.selection)
        descriptions = [(node.node_id, node.method_id) for node in nodes]
        if isinstance(route, (ReconstructionEvidenceRoute, DatasetRoute, TrainingRoute)):
            descriptions = [(route.node_id, route.method_id)]
        if isinstance(route, (PairSelectionRoute, FeatureExtractionRoute, RetrievalBuildRoute,
                              FeatureMatchingRoute, GeometricVerificationRoute, MappingRoute)):
            descriptions = [(route.node_id, route.settings.method_id)]
        previous = evidence.latest
        snapshots = {stage.work.node_id: stage for stage in previous.stages} if previous else {}
        attempts = {attempt.node_id: attempt for attempt in evidence.attempts}
        bindings = {binding.node_id: binding.binding_kind for binding in evidence.outputs}
        cancelling = evidence.status == "running" and (
            evidence.cancellation_requested or evidence.cancellation_accepted
        )
        stages = []
        for node_id, method_id in descriptions:
            stage = snapshots.get(node_id) or StageProgressSnapshot(
                work=WorkDescription(
                    node_id=node_id,
                    stage_id=method_id.split(".")[0],
                    method_id=method_id,
                    work_model_id="unavailable_v1",
                    unit=WorkUnit.WORK,
                    total=None,
                    mode=ProgressMode.INDETERMINATE,
                ),
                throughput_unit=WorkUnit.WORK,
            )
            attempt = attempts.get(node_id)
            binding = bindings.get(node_id)
            status = ProgressStatus.PLANNED
            if binding is not None:
                status = (
                    ProgressStatus.CACHED if binding == "cache_hit" else ProgressStatus.SUCCEEDED
                )
            elif attempt is not None:
                status = (
                    ProgressStatus.PLANNED
                    if attempt.status == "pending"
                    else (ProgressStatus(attempt.status))
                )
                # A succeeded observation without its binding is insufficient.
                if status == ProgressStatus.SUCCEEDED:
                    status = ProgressStatus.INTERRUPTED
            if cancelling and status == ProgressStatus.RUNNING:
                status = ProgressStatus.STOPPING
            elapsed = stage.elapsed_seconds
            if attempt is not None and attempt.started_at is not None:
                elapsed = max(
                    0, ((attempt.finished_at or now) - attempt.started_at).total_seconds()
                )
            age = max(0, (now - stage.observed_at).total_seconds()) if stage.observed_at else None
            # A stale snapshot may refer to an earlier attempt; never replay its rates.
            mismatched = attempt is not None and attempt.attempt_id != stage.attempt_id
            stale = age is not None and age > 5
            done = status in {
                ProgressStatus.CACHED,
                ProgressStatus.SKIPPED,
                ProgressStatus.SUCCEEDED,
            }
            eta = stage.eta
            if done:
                eta = zero_eta()
            elif cancelling or evidence.status != "running" or stale or mismatched:
                eta = EtaEstimate(reasons=("stale_or_inactive",))
            stages.append(
                stage.model_copy(
                    update={
                        "status": status,
                        "elapsed_seconds": 0 if status == ProgressStatus.CACHED else elapsed,
                        "attempt_id": attempt.attempt_id if attempt else None,
                        "fraction": 1 if done else None if mismatched else stage.fraction,
                        "completed": 0 if mismatched else stage.completed,
                        "throughput": None
                        if done or stale or mismatched or cancelling
                        else stage.throughput,
                        "eta": eta,
                        "stale": stale,
                        "observation_age_seconds": age,
                    }
                )
            )
        result = aggregate_pipeline(
            run_id,
            tuple(stages),
            status=("stopping" if evidence.cancellation_accepted else "cancellation_requested")
            if cancelling
            else evidence.status,
            elapsed_seconds=max(
                0, ((evidence.finished_at or now) - evidence.started_at).total_seconds()
            ),
            previous_fraction=previous.fraction if previous else None,
            warnings=evidence.warnings
            + (previous.warnings if previous else ("progress.unavailable",)),
        )
        # Readers do not invent newer display fractions from wall-clock elapsed.
        # Otherwise two stateless clients could observe a reversal at the next
        # owner's estimate update. Only the executing owner advances this display.
        if previous is not None and evidence.status != "succeeded":
            result = result.model_copy(update={"fraction": previous.fraction})
        return result
