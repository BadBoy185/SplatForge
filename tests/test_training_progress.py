import pytest
from progress_helpers import observation, plan
from training_helpers import backend_identity

from splatforge.application.eta import HybridThroughputEstimator
from splatforge.core.training import (
    NativeCheckpointFile,
    TrainingCheckpoint,
    TrainingSettings,
    training_recipe,
)


def test_resumed_eta_counts_only_new_steps():
    stage = plan(1000)
    stage = stage.model_copy(
        update={"work": stage.work.model_copy(update={"initial_completed": 500.0})}
    )
    estimator = HybridThroughputEstimator(stage)
    estimator.observe(observation(stage, 500, 0))
    estimator.observe(observation(stage, 500, 5))
    assert estimator.throughput is None
    estimator.observe(observation(stage, 600, 10))
    # Cumulative new work is 100/10=10; recent 100/5=20; hybrid live rate is 15.
    assert estimator.throughput == pytest.approx(15)
    assert estimator.estimate().likely_seconds == pytest.approx(400 / 15)


def test_checkpoint_step_identity_compatibility_and_provenance_exclusions():
    settings = TrainingSettings(max_steps=100)
    backend = backend_identity()
    checkpoint = TrainingCheckpoint(
        dataset_digest="a" * 64,
        settings=settings,
        backend=backend,
        step=50,
        gaussian_count=4,
        native=NativeCheckpointFile(sha256="b" * 64, size=32),
        state_evidence="parameters_optimizers_schedulers_strategy_python_numpy_torch_cuda_rng_v1",
    )
    assert checkpoint.recipe_key != checkpoint.model_copy(update={"step": 100}).recipe_key
    checkpoint.require_compatible("a" * 64, settings, backend)
    for digest, config, runtime in (
        ("c" * 64, settings, backend),
        ("a" * 64, settings.model_copy(update={"max_steps": 101}), backend),
        ("a" * 64, settings, backend.model_copy(update={"driver": "changed"})),
    ):
        with pytest.raises(ValueError, match="incompatible_checkpoint"):
            checkpoint.require_compatible(digest, config, runtime)
    metadata = checkpoint.metadata()
    assert metadata["compatibility_identity"] == checkpoint.compatibility_identity
    assert metadata["backend_numerical_identity"] == backend.numerical_identity
    first = TrainingSettings.model_validate(
        {
            "split": {
                "policy": "explicit_views_v1",
                "held_out_view_ids": ["00000000-0000-0000-0000-000000000001"],
                "warning": "first label",
            }
        }
    )
    second = TrainingSettings.model_validate(
        {**first.model_dump(), "split": {**first.split.model_dump(), "warning": "another label"}}
    )
    assert training_recipe("a" * 64, first, "b" * 64) == training_recipe("a" * 64, second, "b" * 64)
