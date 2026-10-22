"""Full compatibility matrix and deterministic profile v1 decisions."""

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from splatforge.core.capabilities import CapabilityEvidence
from splatforge.core.features import descriptor_signature, resolve_extraction_settings
from splatforge.core.geometry import VerificationSettings, verification_recipe_key
from splatforge.core.matching import (
    LomaMatchingSettings,
    matching_recipe_key,
    resolve_matching_settings,
    validate_matcher_compatibility,
)
from splatforge.core.sfm_profiles import (
    FeatureMatchingChoice,
    ProfileResolutionError,
    RouteCapabilityDecision,
    SfmQualityProfile,
    profile_candidates,
    resolve_advanced,
    resolve_profile,
)

MATRIX = {
    "SIFT": ("SIFT_BRUTEFORCE", "SIFT_LIGHTGLUE"),
    "ALIKED_N16ROT": ("ALIKED_BRUTEFORCE", "ALIKED_LIGHTGLUE"),
    "ALIKED_N32": ("ALIKED_BRUTEFORCE", "ALIKED_LIGHTGLUE"),
    "LOMA_B": ("LOMA_BRUTEFORCE", "LOMA_B", "LOMA_R", "LOMA_L", "LOMA_G"),
    "LOMA_B128": ("LOMA_BRUTEFORCE", "LOMA_B128"),
}
TOKENS = tuple(dict.fromkeys(m for matches in MATRIX.values() for m in matches))


@pytest.mark.parametrize("extractor", MATRIX)
@pytest.mark.parametrize("matcher", TOKENS)
def test_full_matrix_uses_signature_not_dimension(extractor, matcher):
    signature = descriptor_signature(resolve_extraction_settings(extractor))
    settings = resolve_matching_settings(matcher)
    if matcher in MATRIX[extractor]:
        validate_matcher_compatibility(signature, settings)
    else:
        with pytest.raises(ValueError, match="Incompatible descriptor"):
            validate_matcher_compatibility(signature, settings)


def assess(choice, unavailable=()):
    missing = any(t in unavailable for t in (choice.extractor.variant, choice.matcher.variant))
    now = datetime.now(UTC)
    evidence = CapabilityEvidence(
        capability_id="fixture.inference",
        diagnostic_code="fixture",
        status="unavailable" if missing else "available",
        message="model missing" if missing else "verified",
        observed_at=now,
        expires_at=now + timedelta(seconds=30),
        freshness_seconds=30,
    )
    return RouteCapabilityDecision(
        choice=choice, status=evidence.status, reason=evidence.message, evidence=(evidence,)
    )


@pytest.mark.parametrize(
    "profile,preferred",
    [
        ("fast", ("LOMA_B128", "LOMA_B128")),
        ("medium", ("LOMA_B", "LOMA_B")),
        ("high", ("LOMA_B", "LOMA_L")),
        ("max_high", ("LOMA_B", "LOMA_G")),
    ],
)
def test_profiles_freeze_exact_preferred_routes(profile, preferred):
    result = resolve_profile(SfmQualityProfile(profile), assess)
    assert (result.choice.extractor.variant, result.choice.matcher.variant) == preferred
    assert result.profile_version == 1 and result.requested_mode == "simple"
    assert result.choice.verification == VerificationSettings()
    assert result.choice.matcher.settings_version == 1
    assert "LOMA_R" not in [
        c.matcher.variant for c in profile_candidates(SfmQualityProfile(profile))
    ]


@pytest.mark.parametrize(
    "missing,selected",
    [
        (("LOMA_G",), "LOMA_L"),
        (("LOMA_G", "LOMA_L"), "LOMA_B"),
        (("LOMA_G", "LOMA_L", "LOMA_B"), "ALIKED_LIGHTGLUE"),
        (("LOMA_G", "LOMA_L", "LOMA_B", "ALIKED_N16ROT"), "SIFT_BRUTEFORCE"),
    ],
)
def test_explainable_ordered_planning_downgrade(missing, selected):
    first = resolve_profile(SfmQualityProfile.MAX_HIGH, lambda c: assess(c, missing))
    second = resolve_profile(SfmQualityProfile.MAX_HIGH, lambda c: assess(c, missing))
    assert first.choice == second.choice and first.choice.matcher.variant == selected
    assert first.downgrade_reason and all(d.status == "unavailable" for d in first.decisions[:-1])
    assert [d.choice.matcher.variant for d in first.decisions] == [
        "LOMA_G",
        "LOMA_L",
        "LOMA_B",
        "ALIKED_LIGHTGLUE",
        "SIFT_BRUTEFORCE",
    ][: len(first.decisions)]


def test_long_downgrade_summary_preserves_complete_candidate_decisions():
    def long_reason(choice):
        return assess(choice, ("LOMA_B", "ALIKED_N16ROT")).model_copy(
            update={"reason": "x" * 4096}
        )

    result = resolve_profile(SfmQualityProfile.MAX_HIGH, long_reason)
    assert result.choice.matcher.variant == "SIFT_BRUTEFORCE"
    assert len(result.downgrade_reason) == 8192
    assert len(result.decisions) == 5 and all(len(d.reason) == 4096 for d in result.decisions)


def test_no_candidate_and_advanced_never_fallback():
    with pytest.raises(ProfileResolutionError) as exc:
        resolve_profile(SfmQualityProfile.FAST, lambda c: assess(c, TOKENS))
    assert len(exc.value.decisions) == 3 and "model missing" in str(exc.value)
    choice = FeatureMatchingChoice(
        extractor=resolve_extraction_settings("LOMA_B"), matcher=resolve_matching_settings("LOMA_R")
    )
    with pytest.raises(ProfileResolutionError) as exc:
        resolve_advanced(choice, lambda c: assess(c, ("LOMA_R",)))
    assert len(exc.value.decisions) == 1
    assert resolve_advanced(choice, assess).choice == choice


def test_numerical_recipe_boundaries_and_unknown_controls():
    settings = resolve_matching_settings("SIFT_BRUTEFORCE")
    key = matching_recipe_key("a" * 64, "b" * 64, settings, "c" * 64, ())
    for a, b, s in (
        ("e" * 64, "b" * 64, settings),
        ("a" * 64, "e" * 64, settings),
        ("a" * 64, "b" * 64, settings.model_copy(update={"max_ratio": 0.6})),
    ):
        assert key != matching_recipe_key(a, b, s, "c" * 64, ())
    verification = VerificationSettings()
    vk = verification_recipe_key(key, "d" * 64, verification, "c" * 64)
    assert vk != verification_recipe_key(key, "e" * 64, verification, "c" * 64)
    assert vk != verification_recipe_key(
        key, "d" * 64, verification.model_copy(update={"max_error": 2.0}), "c" * 64
    )
    with pytest.raises(ValidationError):
        LomaMatchingSettings(use_bf16=True)
    with pytest.raises(ValidationError):
        resolve_matching_settings("SIFT_BRUTEFORCE", raw_flags="--foo")
    with pytest.raises(ValueError):
        profile_candidates(SfmQualityProfile.HIGH, profile_version=2)
