from uuid import UUID

import pytest
from pydantic import ValidationError

from splatforge.core.training import TrainingLimits, TrainingSettings, training_recipe
from splatforge.core.training_benchmark import (
    baseline_split,
    candidate_recipes,
    require_fair_comparison,
)


def test_candidate_fairness_and_identity():
    split = baseline_split(tuple(UUID(int=i) for i in range(10)), count=2)
    base = TrainingSettings(max_steps=50, split=split)
    candidates = candidate_recipes(base)
    require_fair_comparison(candidates)
    keys = {training_recipe("a" * 64, c, "b" * 64) for c in candidates}
    assert len(keys) == 3
    assert candidates[1].strategy.grow_grad2d == 0.0008
    assert candidates[2].strategy.cap_max == 1000000
    changed = base.model_copy(update={"max_steps": 100})
    with pytest.raises(ValueError, match="unfair"):
        require_fair_comparison((base, changed))
    for field in ("data_factor", "sh_degree", "seed", "max_steps"):
        value = base.model_dump()
        value[field] += 1 if field != "sh_degree" else -1
        assert (
            training_recipe("a" * 64, TrainingSettings.model_validate(value), "b" * 64) not in keys
        )
    assert training_recipe("c" * 64, base, "b" * 64) not in keys
    assert training_recipe("a" * 64, base, "c" * 64) not in keys
    assert TrainingLimits(timeout_seconds=1) != TrainingLimits(timeout_seconds=2)
    assert base.numerical() == TrainingSettings.model_validate(base.model_dump()).numerical()


def test_split_not_filesystem_order_and_no_hidden_options():
    ids = tuple(UUID(int=i) for i in range(12))
    assert baseline_split(ids, count=3) == baseline_split(ids[::-1], count=3)
    for data in (
        {"pose_opt": True},
        {"normalize_world_space": True},
        {"sparse_grad": True},
        {"strategy": {"strategy": "mcmc", "cap_max": 0}},
        {"ssim_weight": float("nan")},
    ):
        with pytest.raises(ValidationError):
            TrainingSettings.model_validate(data)
    with pytest.raises(ValueError, match="evaluation"):
        require_fair_comparison(candidate_recipes(TrainingSettings()))


def test_training_recipe_uses_content_not_artifact_or_runtime_locator():
    from test_training_adapter import handle, route

    original = route()
    relocated = original.model_copy(
        update={
            "dataset": handle(),
            "runtime": original.runtime.model_copy(update={"python": "D:/Trainer/python.exe"}),
            "resource_limits": TrainingLimits(timeout_seconds=1),
        }
    )
    assert original.dataset.artifact_id != relocated.dataset.artifact_id
    assert original.recipe_key() == relocated.recipe_key()
    changed = relocated.model_copy(
        update={"dataset": relocated.dataset.model_copy(update={"semantic_digest": "d" * 64})}
    )
    assert original.recipe_key() != changed.recipe_key()
    base = TrainingSettings(strategy={"strategy": "mcmc", "cap_max": 1000})
    larger = base.model_copy(
        update={"strategy": base.strategy.model_copy(update={"cap_max": 2000})}
    )
    assert training_recipe("a" * 64, base, "b" * 64) != training_recipe(
        "a" * 64, larger, "b" * 64
    )
