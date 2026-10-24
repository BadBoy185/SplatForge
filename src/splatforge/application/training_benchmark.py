"""Sequential comparison, one exact component and split, no implicit winner/fallback."""

from pathlib import Path
from uuid import UUID

from splatforge.application.training import TrainingService
from splatforge.core.execution import TrainingRuntime
from splatforge.core.training import TrainingLimits, TrainingMetrics, TrainingSettings
from splatforge.core.training_benchmark import require_fair_comparison
from splatforge.core.views import FrozenModel


class TrainingComparisonRow(FrozenModel):
    settings: TrainingSettings
    status: str
    run_id: UUID | None = None
    scene_digest: str | None = None
    gaussian_count: int | None = None
    ply_size: int | None = None
    checkpoint_size: int | None = None
    metrics: TrainingMetrics | None = None
    recipe_key: str | None = None
    backend_numerical_identity: str | None = None
    error: str | None = None


class TrainingComparison(FrozenModel):
    comparison_version: int = 1
    dataset_digest: str
    candidates: tuple[TrainingComparisonRow, ...]
    recommendation: str = "none; candidate evidence only"


def compare_training(
    service: TrainingService,
    root: Path,
    dataset_run: UUID,
    runtime: TrainingRuntime,
    candidates: tuple[TrainingSettings, ...],
    limits: TrainingLimits,
) -> TrainingComparison:
    root = root.resolve()
    require_fair_comparison(candidates)
    handoff = service.handoff(root, dataset_run)
    if len(handoff) != 1:
        raise ValueError("training.comparison_requires_one_component")
    rows = []
    for settings in candidates:
        try:
            result = service.run(root, dataset_run, runtime, settings, limits)
            if result.status != "succeeded" or not result.scene_set:
                rows.append(TrainingComparisonRow(settings=settings, status=result.status))
                if result.status != "succeeded":
                    break
                continue
            scene_job = result.jobs[-1]
            with service.repository.validation_evidence_operation():
                _, scene = service.inspect(root, scene_job.run_id)
                checkpoint = service.repository.lineage_handle(
                    root, scene_job.artifact, "checkpoint"
                )
                size = service.repository.load_training(root, checkpoint).native.size
            rows.append(
                TrainingComparisonRow(
                    settings=settings,
                    status="succeeded",
                    run_id=scene_job.run_id,
                    scene_digest=scene.semantic_digest,
                    gaussian_count=scene.gaussian_count,
                    ply_size=scene.ply_size,
                    checkpoint_size=size,
                    metrics=scene.metrics,
                    recipe_key=scene.recipe_key,
                    backend_numerical_identity=scene.backend.numerical_identity,
                )
            )
        except Exception as exc:
            rows.append(TrainingComparisonRow(settings=settings, status="failed", error=str(exc)))
    return TrainingComparison(dataset_digest=handoff[0]["dataset_digest"], candidates=tuple(rows))
