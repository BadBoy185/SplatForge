from __future__ import annotations

import pytest
from progress_helpers import observation, plan, sample

from splatforge.application.eta import HybridThroughputEstimator, workload_similarity
from splatforge.core.progress import Confidence, EvidenceMode


def test_cold_start_live_refinement_and_completion() -> None:
    stage = plan()
    estimator = HybridThroughputEstimator(stage)
    assert estimator.estimate().likely_seconds is None
    estimator.observe(observation(stage, 0, 0))
    estimator.observe(observation(stage, 10, 0.1))
    assert estimator.estimate().likely_seconds is None
    for second in range(1, 9):
        estimator.observe(observation(stage, second * 100, second))
    estimate = estimator.estimate()
    assert estimate.evidence_mode == EvidenceMode.LIVE
    assert estimate.likely_seconds == pytest.approx(2)
    assert estimate.confidence == Confidence.HIGH
    estimator.observe(observation(stage, 1000, 10))
    assert estimator.estimate().likely_seconds == 0
    assert estimator.estimate().lower_seconds == 0


@pytest.mark.parametrize(
    "rates,confidence",
    [
        ([], Confidence.UNAVAILABLE),
        ([100], Confidence.LOW),
        ([98, 100, 102], Confidence.MEDIUM),
        ([100] * 10, Confidence.HIGH),
        ([1, 10, 100, 1000, 10000] * 4, Confidence.LOW),
    ],
)
def test_history_confidence_depends_on_count_and_dispersion(
    rates: list[float],
    confidence: Confidence,
) -> None:
    estimator = HybridThroughputEstimator(plan(), tuple(sample(rate=rate) for rate in rates))
    value = estimator.estimate()
    assert value.confidence == confidence
    if rates:
        assert value.lower_seconds <= value.likely_seconds <= value.upper_seconds
        assert value.sample_count == len(rates)


def test_historical_prior_then_live_convergence() -> None:
    stage = plan()
    estimator = HybridThroughputEstimator(stage, tuple(sample() for _ in range(8)))
    assert estimator.estimate().likely_seconds == 10
    assert estimator.estimate().evidence_mode == EvidenceMode.HISTORICAL
    estimator.observe(observation(stage, 0, 0))
    for second in range(1, 17):
        estimator.observe(observation(stage, second * 50, second))
    value = estimator.estimate()
    assert value.evidence_mode == EvidenceMode.HYBRID
    assert 3.5 < value.likely_seconds < 4.1
    assert value.evidence.live_weight == pytest.approx(0.95)


def test_spike_is_damped_and_sustained_slowdown_increases_eta() -> None:
    stage = plan(10_000)
    estimator = HybridThroughputEstimator(stage, (sample(stage),) * 5)
    estimator.observe(observation(stage, 0, 0))
    for second in range(1, 6):
        estimator.observe(observation(stage, second * 100, second))
    before = estimator.estimate().likely_seconds
    estimator.observe(observation(stage, 600, 5.001))
    spike = estimator.estimate().likely_seconds
    assert spike > before * 0.8
    assert estimator.throughput < 200
    completed = 600
    for second in range(6, 56):
        completed += 10
        estimator.observe(observation(stage, completed, second))
    slow = estimator.estimate()
    assert slow.likely_seconds > spike
    assert slow.evidence.live_throughput < 35
    assert slow.lower_seconds <= slow.likely_seconds <= slow.upper_seconds


def test_fast_startup_sample_does_not_collapse_prior() -> None:
    stage = plan()
    estimator = HybridThroughputEstimator(stage, (sample(),) * 8)
    estimator.observe(observation(stage, 0, 0))
    estimator.observe(observation(stage, 50, 0.001))
    assert estimator.estimate().likely_seconds == pytest.approx(9.5)


def test_stalled_live_work_reduces_confidence_and_widens_range() -> None:
    stage = plan()
    estimator = HybridThroughputEstimator(stage)
    estimator.observe(observation(stage, 0, 0))
    for index in range(1, 9):
        estimator.observe(observation(stage, index * 100, index))
    before = estimator.estimate()
    estimator.observe(observation(stage, 800, 30))
    stalled = estimator.estimate()
    assert stalled.likely_seconds > before.likely_seconds
    assert stalled.confidence == Confidence.LOW
    assert (
        stalled.upper_seconds / stalled.lower_seconds > before.upper_seconds / before.lower_seconds
    )
    assert "live_stalled" in stalled.reasons


def test_work_scale_is_explainable_and_weak_similarity_widens_range() -> None:
    old = sample()
    exact = HybridThroughputEstimator(plan(), (old,) * 10).estimate()
    scaled_plan = plan(2000)
    assert workload_similarity(scaled_plan, old) == pytest.approx(0.8)
    scaled = HybridThroughputEstimator(scaled_plan, (old,) * 10).estimate()
    assert scaled.likely_seconds == 20
    assert scaled.confidence == Confidence.MEDIUM
    assert scaled.upper_seconds / scaled.lower_seconds > exact.upper_seconds / exact.lower_seconds
    weak = HybridThroughputEstimator(plan(64000), (old,) * 10).estimate()
    assert weak.confidence == Confidence.LOW


@pytest.mark.parametrize(
    "part,changes",
    [
        ("backend", {"runtime_version": "other"}),
        ("backend", {"executable_sha256": "b" * 64}),
        ("backend", {"model_sha256": "c" * 64}),
        ("hardware", {"logical_cpus": 16}),
        ("hardware", {"device": "gpu"}),
    ],
)
def test_backend_and_hardware_mismatches_never_pool_exact_history(
    part: str,
    changes: dict[str, object],
) -> None:
    current = plan()
    signature = current.signature.model_copy(
        update={part: getattr(current.signature, part).model_copy(update=changes)}
    )
    current = current.model_copy(update={"signature": signature})
    result = HybridThroughputEstimator(current, (sample(),) * 10).estimate()
    assert result.sample_count == 0
    assert result.likely_seconds is None


def test_empirical_range_reflects_spread_and_never_claims_statistical_interval() -> None:
    estimate = HybridThroughputEstimator(
        plan(),
        tuple(sample(rate=value) for value in (50, 75, 100, 150, 200)),
    ).estimate()
    assert estimate.likely_seconds == 10
    assert estimate.lower_seconds < 7
    assert estimate.upper_seconds > 15
    assert estimate.confidence == Confidence.LOW
    assert "95" not in estimate.model_dump_json()
