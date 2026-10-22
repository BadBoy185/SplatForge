"""Version 1 feature/matching/verification intent; never an execution fallback."""

from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum
from typing import Literal

from pydantic import Field, model_validator

from splatforge.core.capabilities import CapabilityEvidence, CapabilityStatus
from splatforge.core.features import (
    Digest,
    FeatureSettings,
    LearnedModelIdentity,
    descriptor_signature,
    resolve_extraction_settings,
)
from splatforge.core.geometry import VerificationSettings
from splatforge.core.matching import (
    MatcherSettings,
    resolve_matching_settings,
    validate_matcher_compatibility,
)
from splatforge.core.views import FrozenModel


class SfmUserMode(StrEnum):
    SIMPLE = "simple"
    ADVANCED = "advanced"


class SfmQualityProfile(StrEnum):
    FAST = "fast"
    MEDIUM = "medium"
    HIGH = "high"
    MAX_HIGH = "max_high"


class SfmDevicePolicy(StrEnum):
    AUTO = "auto"
    CPU = "cpu"
    GPU = "gpu:0"


def device_choices(policy: SfmDevicePolicy) -> tuple[str, ...]:
    return ("gpu:0", "cpu") if policy == SfmDevicePolicy.AUTO else (policy.value,)


def on_device(choice: FeatureMatchingChoice, device: str) -> FeatureMatchingChoice:
    """Resolve only the supported device; preserve every other numerical setting."""
    if device not in ("cpu", "gpu:0"):
        raise ValueError("Supported concrete devices are cpu and gpu:0")
    return choice.model_copy(update={
        "extractor": choice.extractor.model_copy(update={"use_gpu": device == "gpu:0"}),
        "matcher": choice.matcher.model_copy(update={"use_gpu": device == "gpu:0"}),
    })


PROFILE_CANDIDATES_V1 = {
    SfmQualityProfile.FAST: (("LOMA_B128", "LOMA_B128"),),
    SfmQualityProfile.MEDIUM: (("LOMA_B", "LOMA_B"), ("LOMA_B128", "LOMA_B128")),
    SfmQualityProfile.HIGH: (("LOMA_B", "LOMA_L"), ("LOMA_B", "LOMA_B")),
    SfmQualityProfile.MAX_HIGH: (
        ("LOMA_B", "LOMA_G"),
        ("LOMA_B", "LOMA_L"),
        ("LOMA_B", "LOMA_B"),
    ),
}


class FeatureMatchingChoice(FrozenModel):
    extractor: FeatureSettings
    matcher: MatcherSettings
    verification: VerificationSettings = VerificationSettings()

    @model_validator(mode="after")
    def compatible(self) -> FeatureMatchingChoice:
        validate_matcher_compatibility(descriptor_signature(self.extractor), self.matcher)
        return self


class RouteCapabilityDecision(FrozenModel):
    choice: FeatureMatchingChoice
    status: CapabilityStatus
    reason: str = Field(min_length=1, max_length=4096)
    evidence: tuple[CapabilityEvidence, ...] = Field(default=(), max_length=32)
    extractor_backend_identity: Digest | None = None
    matcher_backend_identity: Digest | None = None
    verification_backend_identity: Digest | None = None
    extractor_models: tuple[LearnedModelIdentity, ...] = Field(default=(), max_length=2)
    matcher_models: tuple[LearnedModelIdentity, ...] = Field(default=(), max_length=1)

    @model_validator(mode="after")
    def positive_evidence(self) -> RouteCapabilityDecision:
        if self.status == CapabilityStatus.AVAILABLE and (
            not self.evidence or any(e.status != CapabilityStatus.AVAILABLE for e in self.evidence)
        ):
            raise ValueError("Available profile route requires positive capability evidence")
        return self


class ResolvedFeatureMatchingRoute(FrozenModel):
    requested_mode: SfmUserMode
    requested_profile: SfmQualityProfile | None = None
    profile_version: Literal[1] | None = None
    choice: FeatureMatchingChoice
    decisions: tuple[RouteCapabilityDecision, ...] = Field(min_length=1, max_length=5)
    downgrade_reason: str | None = Field(default=None, max_length=8192)
    requested_device_policy: SfmDevicePolicy | None = None
    resolved_device: Literal["cpu", "gpu:0"] | None = None
    device_decisions: tuple[RouteCapabilityDecision, ...] = Field(default=(), max_length=10)

    @model_validator(mode="after")
    def exact_resolution(self) -> ResolvedFeatureMatchingRoute:
        if self.choice != self.decisions[-1].choice or self.decisions[-1].status != "available":
            raise ValueError("Resolution must select its last positively verified candidate")
        if any(d.status == "available" for d in self.decisions[:-1]):
            raise ValueError("Resolution cannot skip an available higher-priority candidate")
        if self.requested_mode == SfmUserMode.ADVANCED:
            if (
                self.requested_profile is not None
                or self.profile_version is not None
                or len(self.decisions) != 1
            ):
                raise ValueError("Advanced explicit intent has no profile or automatic fallback")
        else:
            if self.requested_profile is None or self.profile_version != 1:
                raise ValueError("Simple resolution requires a versioned profile")
            expected = profile_candidates(self.requested_profile)
            if tuple(on_device(d.choice, "cpu") for d in self.decisions) != expected[
                : len(self.decisions)
            ]:
                raise ValueError("Simple resolution differs from deterministic profile v1 policy")
        if self.requested_device_policy is None:
            if self.resolved_device is not None or self.device_decisions:
                raise ValueError("Device provenance requires an explicit requested policy")
            if self.requested_mode == SfmUserMode.SIMPLE and any(
                d.choice != on_device(d.choice, "gpu:0" if self.choice.extractor.use_gpu else "cpu")
                for d in self.decisions
            ):
                raise ValueError("Legacy Simple resolution must retain its explicit device")
        else:
            devices = device_choices(self.requested_device_policy)
            candidates = (
                profile_candidates(self.requested_profile)
                if self.requested_mode == SfmUserMode.SIMPLE else (self.choice,)
            )
            expected_attempts = tuple(on_device(c, d) for c in candidates for d in devices)
            actual = tuple(d.choice for d in self.device_decisions)
            if not actual or actual != expected_attempts[:len(actual)]:
                raise ValueError("Device resolution differs from ordered route/device policy")
            if (self.device_decisions[-1] != self.decisions[-1]
                    or any(d.status == "available" for d in self.device_decisions[:-1])):
                raise ValueError("Device resolution must stop at its first positive assessment")
            completed = tuple(self.device_decisions[i] for i in range(len(actual))
                              if (i + 1) % len(devices) == 0 or i == len(actual) - 1)
            if completed != self.decisions:
                raise ValueError("Candidate summaries must preserve all device assessments")
            selected = "gpu:0" if self.choice.extractor.use_gpu else "cpu"
            if (self.resolved_device != selected
                    or self.choice.matcher.use_gpu != self.choice.extractor.use_gpu):
                raise ValueError("Concrete device must agree with the frozen numerical settings")
        return self


class ProfileResolutionError(ValueError):
    def __init__(self, decisions: tuple[RouteCapabilityDecision, ...], *,
                 device_decisions: tuple[RouteCapabilityDecision, ...] = ()) -> None:
        self.decisions = decisions
        self.device_decisions = device_decisions
        super().__init__(
            "No runnable route: "
            + "; ".join(
                f"{d.choice.extractor.variant}+{d.choice.matcher.variant} / "
                f"{'gpu:0' if d.choice.extractor.use_gpu else 'cpu'}: {d.reason}"
                for d in (device_decisions or decisions)
            )
        )


def profile_candidates(
    profile: SfmQualityProfile,
    *,
    use_gpu: bool = False,
    profile_version: int = 1,
) -> tuple[FeatureMatchingChoice, ...]:
    if profile_version != 1:
        raise ValueError("Unsupported feature/matching profile version")
    tokens = (
        *PROFILE_CANDIDATES_V1[profile],
        ("ALIKED_N16ROT", "ALIKED_LIGHTGLUE"),
        ("SIFT", "SIFT_BRUTEFORCE"),
    )
    # Use existing extraction and verified native matching/geometry defaults. V1
    # varies model route only; feature/threshold tuning awaits SplatForge benchmarks.
    return tuple(
        FeatureMatchingChoice(
            extractor=resolve_extraction_settings(e, use_gpu=use_gpu),
            matcher=resolve_matching_settings(m, use_gpu=use_gpu),
        )
        for e, m in tokens
    )


def resolve_profile(
    profile: SfmQualityProfile,
    assess: Callable[[FeatureMatchingChoice], RouteCapabilityDecision],
    *,
    use_gpu: bool | None = None,
    device_policy: SfmDevicePolicy | None = None,
    profile_version: int = 1,
) -> ResolvedFeatureMatchingRoute:
    if use_gpu is not None and device_policy is not None:
        raise ValueError("Choose device_policy or the legacy use_gpu setting")
    policy = device_policy or (
        SfmDevicePolicy.AUTO if use_gpu is None else
        SfmDevicePolicy.GPU if use_gpu else SfmDevicePolicy.CPU
    )
    decisions, attempts = [], []
    for candidate in profile_candidates(profile, profile_version=profile_version):
        for device in device_choices(policy):
            choice = on_device(candidate, device)
            decision = assess(choice)
            if decision.choice != choice:
                raise ValueError("Capability assessment changed the requested numerical route")
            attempts.append(decision)
            if decision.status == CapabilityStatus.AVAILABLE:
                break
        decisions.append(decision)
        if decision.status == CapabilityStatus.AVAILABLE:
            return ResolvedFeatureMatchingRoute(
                requested_mode=SfmUserMode.SIMPLE,
                requested_profile=profile,
                profile_version=1,
                choice=choice,
                decisions=tuple(decisions),
                downgrade_reason="; ".join(d.reason for d in decisions[:-1])[:8192] or None,
                requested_device_policy=policy,
                resolved_device=device,
                device_decisions=tuple(attempts),
            )
    raise ProfileResolutionError(tuple(decisions), device_decisions=tuple(attempts))


def resolve_advanced(
    choice: FeatureMatchingChoice,
    assess: Callable[[FeatureMatchingChoice], RouteCapabilityDecision],
    *,
    device_policy: SfmDevicePolicy | None = None,
) -> ResolvedFeatureMatchingRoute:
    if device_policy is not None:
        attempts = []
        for device in device_choices(device_policy):
            selected = on_device(choice, device)
            decision = assess(selected)
            if decision.choice != selected:
                raise ValueError("Capability assessment changed explicit advanced settings")
            attempts.append(decision)
            if decision.status == CapabilityStatus.AVAILABLE:
                return ResolvedFeatureMatchingRoute(
                    requested_mode=SfmUserMode.ADVANCED, choice=selected,
                    decisions=(decision,), requested_device_policy=device_policy,
                    resolved_device=device, device_decisions=tuple(attempts),
                )
        raise ProfileResolutionError((decision,), device_decisions=tuple(attempts))
    decision = assess(choice)
    if decision.choice != choice:
        raise ValueError("Capability assessment changed explicit advanced settings")
    if decision.status != CapabilityStatus.AVAILABLE:
        raise ProfileResolutionError((decision,))
    return ResolvedFeatureMatchingRoute(
        requested_mode=SfmUserMode.ADVANCED,
        choice=choice,
        decisions=(decision,),
    )
