"""Explicit candidate recipes and fair comparison checks; no automatic winner."""

import hashlib
from uuid import UUID

from splatforge.core.training import (
    DefaultStrategySettings,
    EvaluationSplit,
    MCMCStrategySettings,
    TrainingSettings,
)


def baseline_split(view_ids: tuple[UUID, ...], *, count: int) -> EvaluationSplit:
    if not 0 < count < len(view_ids):
        raise ValueError("training.invalid_split: need held-out and training views")
    selected = sorted(view_ids, key=lambda i: hashlib.sha256(i.bytes).digest())[:count]
    return EvaluationSplit(
        policy="sha256_views_v1",
        held_out_view_ids=tuple(sorted(selected, key=lambda i: i.int)),
        warning=(
            "Hash-based baseline; spatial/source balance is not guaranteed. Prefer explicit IDs."
        ),
    )


def candidate_recipes(base: TrainingSettings) -> tuple[TrainingSettings, ...]:
    return tuple(
        TrainingSettings.model_validate({**base.model_dump(), "strategy": s.model_dump()})
        for s in (
            DefaultStrategySettings(),
            DefaultStrategySettings(absgrad=True, grow_grad2d=0.0008),
            MCMCStrategySettings(cap_max=1000000),
        )
    )


def require_fair_comparison(candidates: tuple[TrainingSettings, ...]) -> None:
    if len(candidates) < 2:
        raise ValueError("training.comparison_requires_multiple_candidates")
    projections = [{k: v for k, v in c.numerical().items() if k != "strategy"} for c in candidates]
    if any(p != projections[0] for p in projections[1:]):
        raise ValueError("training.unfair_comparison: common settings/split must be identical")
    if not candidates[0].split.held_out_view_ids:
        raise ValueError("training.benchmark_requires_explicit_evaluation_split")
