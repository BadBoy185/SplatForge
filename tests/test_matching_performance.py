"""Diagnostic signatures follow numerical settings, never profile labels."""

import json

import pytest
from test_matching_core import assess
from test_matching_database import published as published

from splatforge.application.eta import HybridThroughputEstimator
from splatforge.application.work_models import matching_progress_plan
from splatforge.core.capabilities import ModelEvidence
from splatforge.core.execution import RunSnapshot
from splatforge.core.progress import ExecutionHardwareProfile
from splatforge.core.sfm_profiles import SfmQualityProfile, resolve_profile


def test_cold_historical_profile_independence_and_precision_model_partition(published):
    from progress_helpers import sample

    *_, raw, _geometry = published
    manifest = json.loads((raw / "manifest.json").read_text(encoding="utf-8"))
    root = raw.parents[2]
    route = RunSnapshot.model_validate_json(
        (root / "runs" / manifest["producer_run_id"] / "run.json").read_bytes()
    ).route
    hardware = ExecutionHardwareProfile(
        platform_family="windows",
        cpu_family="fixture",
        logical_cpus=4,
        ram_gib_bucket=16,
        device="cpu",
    )
    plan = matching_progress_plan(route, hardware)
    assert HybridThroughputEstimator(plan).estimate().likely_seconds is None
    samples = tuple(sample(plan, rate=1) for _ in range(3))
    assert HybridThroughputEstimator(plan, samples).estimate().likely_seconds is not None
    missing = ("LOMA_B128", "LOMA_B", "LOMA_L", "ALIKED_N16ROT")
    signatures = []
    for profile in (SfmQualityProfile.FAST, SfmQualityProfile.HIGH):
        resolved = resolve_profile(profile, lambda c: assess(c, missing))
        changed = route.model_copy(update={"resolution": resolved})
        signatures.append(matching_progress_plan(changed, hardware).signature)
        assert changed.recipe_key() == route.recipe_key()
    assert signatures[0] == signatures[1] == plan.signature
    precision = route.model_copy(
        update={"backend": route.backend.model_copy(update={"actual_precision": "fp32"})}
    )
    assert matching_progress_plan(precision, hardware).signature != plan.signature
    model = ModelEvidence(
        role="lightglue.sift",
        configured_source="fixture",
        expected_name="fixture.onnx",
        size=100,
        sha256="a" * 64,
        evidence=route.backend.capability_evidence[0],
    )
    with_model = route.model_copy(
        update={"backend": route.backend.model_copy(update={"models": (model,)})}
    )
    first = matching_progress_plan(with_model, hardware)
    with_model = with_model.model_copy(
        update={
            "backend": with_model.backend.model_copy(
                update={"models": (model.model_copy(update={"sha256": "b" * 64}),)}
            )
        }
    )
    assert matching_progress_plan(with_model, hardware).signature != first.signature


def test_nonreciprocal_resource_upper_bound(published):
    from splatforge.core.matching import (
        MatchingResourceLimits,
        estimate_matching_resources,
        resolve_matching_settings,
    )

    features, pairs, *_ = published
    modified = features.model_copy(
        update={
            "views": tuple(
                v.model_copy(update={"feature_count": 4 if index == 1 else 24})
                for index, v in enumerate(features.views)
            ),
            "total_feature_count": 52,
        }
    )
    estimate = estimate_matching_resources(
        modified,
        pairs,
        resolve_matching_settings("SIFT_BRUTEFORCE", cross_check=False),
        MatchingResourceLimits(),
        upstream_bytes=10000,
    )
    assert estimate.raw_matches == 72  # a many-to-one pair can exceed its smaller endpoint count


def test_actual_device_partitions_history_and_numerical_recipe(published):
    *_, raw, _geometry = published
    manifest = json.loads((raw / "manifest.json").read_text(encoding="utf-8"))
    route = RunSnapshot.model_validate_json(
        (raw.parents[2] / "runs" / manifest["producer_run_id"] / "run.json").read_bytes()
    ).route
    hardware = ExecutionHardwareProfile(platform_family="windows", cpu_family="fixture",
                                        logical_cpus=4, ram_gib_bucket=16, device="cpu")
    gpu = route.model_copy(update={"settings": route.settings.model_copy(update={"use_gpu": True})})
    assert gpu.recipe_key() != route.recipe_key()
    assert matching_progress_plan(gpu, hardware).signature != matching_progress_plan(
        route, hardware
    ).signature


def test_verification_memory_budget_accounts_for_threads_and_batch(published):
    from splatforge.core.geometry import VerificationSettings, estimate_verification_resources
    from splatforge.core.matching import MatchingResourceLimits

    features, _pairs, matches, *_ = published
    counts = sorted((p.raw_match_count for p in matches.pairs if p.raw_match_count), reverse=True)
    assert len(counts) >= 2
    single = matches.total_raw_match_count * 8 + features.total_feature_count * 16 + counts[0] * 32
    limits = MatchingResourceLimits(max_pair_working_bytes=single)
    estimate_verification_resources(
        features, matches, VerificationSettings(), limits, upstream_bytes=10000
    )
    with pytest.raises(ValueError, match="working-memory budget"):
        estimate_verification_resources(
            features, matches, VerificationSettings(num_threads=2), limits, upstream_bytes=10000
        )
    estimate_verification_resources(
        features,
        matches,
        VerificationSettings(num_threads=2, batch_size=1),
        limits,
        upstream_bytes=10000,
    )
