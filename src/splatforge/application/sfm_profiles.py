"""Explainable profile/advanced planning using the same production adapters."""

from pathlib import Path

from splatforge.application.features_contracts import FeatureExtractor
from splatforge.application.matching_contracts import MatchingAdapter
from splatforge.core.capabilities import CapabilityStatus
from splatforge.core.sfm_profiles import (
    FeatureMatchingChoice,
    ResolvedFeatureMatchingRoute,
    RouteCapabilityDecision,
    SfmDevicePolicy,
    SfmQualityProfile,
    resolve_advanced,
    resolve_profile,
)


class SfmProfileService:
    def __init__(self, extractor: FeatureExtractor, matcher: MatchingAdapter) -> None:
        self._extractor, self._matcher = extractor, matcher

    def resolve(
        self,
        *,
        profile: SfmQualityProfile | None = None,
        choice: FeatureMatchingChoice | None = None,
        use_gpu: bool | None = None,
        device_policy: SfmDevicePolicy | None = None,
        colmap: Path | None = None,
        model_directory: Path | None = None,
    ) -> ResolvedFeatureMatchingRoute:
        if (profile is None) == (choice is None):
            raise ValueError("Select exactly one Simple profile or explicit Advanced choice")

        def assess(value: FeatureMatchingChoice) -> RouteCapabilityDecision:
            evidence = []
            try:
                feature = self._extractor.prepare(
                    value.extractor, colmap=colmap, model_directory=model_directory
                )
                evidence.extend(feature.capability_evidence)
                match = self._matcher.prepare(
                    value.matcher,
                    feature_settings=value.extractor,
                    colmap=colmap,
                    model_directory=model_directory,
                )
                evidence.extend(match.capability_evidence)
                verification = self._matcher.prepare(
                    value.verification, colmap=colmap, model_directory=model_directory
                )
                evidence.extend(verification.capability_evidence)
            except ValueError as exc:
                evidence.extend(getattr(exc, "evidence", ()))
                return RouteCapabilityDecision(
                    choice=value,
                    status=CapabilityStatus.UNAVAILABLE,
                    reason=str(exc)[:4096],
                    evidence=tuple(evidence),
                )
            return RouteCapabilityDecision(
                choice=value,
                status=CapabilityStatus.AVAILABLE,
                reason="Exact extraction, matching and standalone verification verified",
                evidence=tuple(evidence),
                extractor_backend_identity=feature.numerical_identity,
                matcher_backend_identity=match.numerical_identity,
                verification_backend_identity=verification.numerical_identity,
                extractor_models=feature.model_identities(),
                matcher_models=match.model_identities(),
            )

        if choice is not None:
            if use_gpu is not None:
                if device_policy is not None:
                    raise ValueError("Choose device_policy or use_gpu")
                device_policy = SfmDevicePolicy.GPU if use_gpu else SfmDevicePolicy.CPU
            return resolve_advanced(choice, assess, device_policy=device_policy)
        return resolve_profile(profile, assess, use_gpu=use_gpu, device_policy=device_policy)
