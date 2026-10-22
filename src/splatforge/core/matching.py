"""M7b typed matching recipes, compatibility and immutable raw correspondences."""

from __future__ import annotations

import hashlib
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, model_validator

from splatforge.core.capabilities import ModelEvidence
from splatforge.core.features import (
    DescriptorFamily,
    DescriptorSignature,
    Digest,
    FeatureBackend,
    LearnedModelIdentity,
    LocalFeatureSet,
    digest_json,
)
from splatforge.core.pairs import MAX_PAIRS, PairEndpoints, PairSet
from splatforge.core.views import FrozenModel, canonical_json_bytes

MATCH_ARTIFACT_TYPE = "matching.match_set"
MAX_MATCH_METADATA_BYTES = 768 * 1024 * 1024
MAX_MATCHES_PER_PAIR = 100_000


class MatchingSettings(FrozenModel):
    settings_version: Literal[1] = 1
    use_gpu: bool = Field(default=False, strict=True)
    num_threads: int = Field(default=1, ge=1, le=64, strict=True)
    max_num_matches: int = Field(default=32768, ge=1, le=MAX_MATCHES_PER_PAIR, strict=True)
    random_seed: int = Field(default=0, ge=0, le=2**31 - 1, strict=True)


class SiftBruteforceSettings(MatchingSettings):
    method_id: Literal["feature_matching.sift_bruteforce"] = "feature_matching.sift_bruteforce"
    variant: Literal["SIFT_BRUTEFORCE"] = "SIFT_BRUTEFORCE"
    max_ratio: float = Field(default=0.8, gt=0, le=1)
    max_distance: float = Field(default=0.7, gt=0, le=2)
    cross_check: bool = Field(default=True, strict=True)
    cpu_brute_force_matcher: bool = Field(default=False, strict=True)


class LightGlueSettings(MatchingSettings):
    # Preserve existing published/catalogued SplatForge IDs.
    method_id: Literal["feature_matching.lightglue_sift", "feature_matching.lightglue_aliked"]
    variant: Literal["SIFT_LIGHTGLUE", "ALIKED_LIGHTGLUE"]
    min_score: float = Field(default=0.1, ge=0, le=1)

    @model_validator(mode="after")
    def correct_variant(self) -> LightGlueSettings:
        if self.method_id != f"feature_matching.lightglue_{self.variant.split('_')[0].lower()}":
            raise ValueError("LightGlue method and variant differ")
        return self


class LearnedBruteforceSettings(MatchingSettings):
    method_id: Literal["feature_matching.aliked_bruteforce", "feature_matching.loma_bruteforce"]
    variant: Literal["ALIKED_BRUTEFORCE", "LOMA_BRUTEFORCE"]
    min_cossim: float = Field(default=0.85, ge=-1, le=1)
    max_ratio: float = Field(default=1.0, gt=0, le=1)
    cross_check: bool = Field(default=True, strict=True)

    @model_validator(mode="after")
    def correct_variant(self) -> LearnedBruteforceSettings:
        if self.method_id != f"feature_matching.{self.variant.lower()}":
            raise ValueError("Brute-force method and variant differ")
        return self


class LomaMatchingSettings(MatchingSettings):
    method_id: Literal[
        "feature_matching.loma_b",
        "feature_matching.loma_b128",
        "feature_matching.loma_r",
        "feature_matching.loma_l",
        "feature_matching.loma_g",
    ] = "feature_matching.loma_b"
    variant: Literal["LOMA_B", "LOMA_B128", "LOMA_R", "LOMA_L", "LOMA_G"] = "LOMA_B"
    min_score: float = Field(default=0.1, ge=0, le=1)
    use_bf16: Literal[False] = False

    @model_validator(mode="after")
    def correct_variant(self) -> LomaMatchingSettings:
        if self.method_id != f"feature_matching.{self.variant.lower()}":
            raise ValueError("LoMa matcher method and variant differ")
        return self


MatcherSettings = Annotated[
    SiftBruteforceSettings | LightGlueSettings | LearnedBruteforceSettings | LomaMatchingSettings,
    Field(discriminator="method_id"),
]

COMPATIBLE_MATCHERS = {
    DescriptorFamily.SIFT: ("SIFT_BRUTEFORCE", "SIFT_LIGHTGLUE"),
    DescriptorFamily.ALIKED: ("ALIKED_BRUTEFORCE", "ALIKED_LIGHTGLUE"),
    DescriptorFamily.LOMA_B: ("LOMA_BRUTEFORCE", "LOMA_B", "LOMA_R", "LOMA_L", "LOMA_G"),
    DescriptorFamily.LOMA_B128: ("LOMA_BRUTEFORCE", "LOMA_B128"),
}


def validate_matcher_compatibility(
    signature: DescriptorSignature, settings: MatcherSettings
) -> None:
    # DescriptorSignature itself validates dtype/dimension/storage/keypoint convention.
    DescriptorSignature.model_validate(signature.model_dump())
    if settings.variant not in COMPATIBLE_MATCHERS[signature.family]:
        raise ValueError(
            f"Incompatible descriptor {signature.family}/{signature.scalar_type}/"
            f"{signature.dimension} and {settings.variant}; compatible: "
            + ", ".join(COMPATIBLE_MATCHERS[signature.family])
        )


def resolve_matching_settings(variant: str, **values: object) -> MatcherSettings:
    token = variant.upper()
    if token == "SIFT_BRUTEFORCE":
        return SiftBruteforceSettings(**values)
    if token in ("SIFT_LIGHTGLUE", "ALIKED_LIGHTGLUE"):
        return LightGlueSettings(
            method_id=f"feature_matching.lightglue_{token.split('_')[0].lower()}",
            variant=token,
            **values,
        )
    if token in ("ALIKED_BRUTEFORCE", "LOMA_BRUTEFORCE"):
        return LearnedBruteforceSettings(
            method_id=f"feature_matching.{token.lower()}",
            variant=token,
            **values,
        )
    if token in ("LOMA_B", "LOMA_B128", "LOMA_R", "LOMA_L", "LOMA_G"):
        return LomaMatchingSettings(
            method_id=f"feature_matching.{token.lower()}",
            variant=token,
            **values,
        )
    raise ValueError(f"Unknown matcher {variant}")


def matcher_model_role(settings: MatcherSettings) -> str | None:
    if isinstance(settings, SiftBruteforceSettings):
        return None
    if isinstance(settings, LightGlueSettings):
        return f"lightglue.{settings.variant.split('_')[0].lower()}"
    if isinstance(settings, LearnedBruteforceSettings):
        return f"bruteforce.{settings.variant.split('_')[0].lower()}"
    return f"loma.matcher.{settings.variant.removeprefix('LOMA_').lower()}"


def numerical_models(models: tuple[LearnedModelIdentity, ...]) -> list[dict[str, object]]:
    return [m.model_dump(include={"role", "sha256", "size"}) for m in models]


class MatchingBackend(FeatureBackend):
    adapter_id: Literal["splatforge.colmap_matching"] = "splatforge.colmap_matching"
    models: tuple[ModelEvidence, ...] = Field(default=(), max_length=1)
    operation: Literal["matches_importer", "geometric_verifier"]
    # "integer" remains readable in early M7b development snapshots. SIFT's
    # uint8 descriptor representation does not establish its arithmetic precision.
    actual_precision: Literal["native_sift", "integer", "fp32", "float64"]


class RawPairSummary(PairEndpoints):
    requested: Literal[True] = True
    processed: Literal[True] = True
    raw_match_count: int = Field(ge=0, le=MAX_MATCHES_PER_PAIR, strict=True)
    correspondences_digest: Digest


class MatchSet(FrozenModel):
    contract_version: Literal[1] = 1
    features_artifact_id: UUID
    features_semantic_digest: Digest
    pairs_artifact_id: UUID
    pairs_semantic_digest: Digest
    method_id: str = Field(min_length=1, max_length=128)
    method_version: Literal[1] = 1
    settings: MatcherSettings
    descriptor: DescriptorSignature
    backend_numerical_identity: Digest
    models: tuple[LearnedModelIdentity, ...] = Field(default=(), max_length=1)
    requested_pair_count: int = Field(ge=1, le=MAX_PAIRS, strict=True)
    processed_pair_count: int = Field(ge=1, le=MAX_PAIRS, strict=True)
    matched_pair_count: int = Field(ge=0, le=MAX_PAIRS, strict=True)
    zero_match_pair_count: int = Field(ge=0, le=MAX_PAIRS, strict=True)
    total_raw_match_count: int = Field(ge=0, le=MAX_PAIRS * MAX_MATCHES_PER_PAIR, strict=True)
    pairs: tuple[RawPairSummary, ...] = Field(min_length=1, max_length=MAX_PAIRS)
    semantic_digest: Digest

    @model_validator(mode="after")
    def consistent(self) -> MatchSet:
        validate_matcher_compatibility(self.descriptor, self.settings)
        keys = [(p.left_view_id.int, p.right_view_id.int) for p in self.pairs]
        if keys != sorted(set(keys)):
            raise ValueError("Raw pairs require unique canonical endpoint order")
        if self.requested_pair_count != len(keys) or self.processed_pair_count != len(keys):
            raise ValueError("Every requested pair must be processed and explained")
        matched = sum(p.raw_match_count > 0 for p in self.pairs)
        if (
            self.matched_pair_count != matched
            or self.zero_match_pair_count != len(keys) - matched
            or self.total_raw_match_count != sum(p.raw_match_count for p in self.pairs)
        ):
            raise ValueError("Raw matching totals differ from pair summaries")
        if self.method_id != self.settings.method_id:
            raise ValueError("Matcher method differs from settings")
        role = matcher_model_role(self.settings)
        if tuple(m.role for m in self.models) != (() if role is None else (role,)):
            raise ValueError("Matcher model role differs from settings")
        if any(p.raw_match_count > self.settings.max_num_matches for p in self.pairs):
            raise ValueError("Raw matches exceed per-pair budget")
        if match_semantic_digest(self) != self.semantic_digest:
            raise ValueError("MatchSet semantic digest mismatch")
        return self


def match_semantic_digest(value: MatchSet) -> str:
    header = value.model_dump(
        mode="json",
        exclude={
            "features_artifact_id",
            "pairs_artifact_id",
            "pairs",
            "semantic_digest",
            "models",
        },
    )
    header["models"] = numerical_models(value.models)
    digest = hashlib.sha256(canonical_json_bytes(header))
    for pair in value.pairs:
        digest.update(canonical_json_bytes(pair.model_dump(mode="json")))
    return digest.hexdigest()


def matching_recipe_key(
    features_digest: str,
    pairs_digest: str,
    settings: MatcherSettings,
    backend_identity: str,
    models: tuple[LearnedModelIdentity, ...],
) -> str:
    return digest_json(
        {
            "fingerprint_version": 1,
            "contract_version": 1,
            "method_version": 1,
            "features": features_digest,
            "pairs": pairs_digest,
            "settings": settings.model_dump(mode="json"),
            "backend": backend_identity,
            "models": numerical_models(models),
        }
    )


class MatchingResourceLimits(FrozenModel):
    max_pairs: int = Field(default=100_000, ge=1, le=MAX_PAIRS, strict=True)
    max_total_features: int = Field(default=100_000_000, ge=1, le=10**10, strict=True)
    max_raw_matches: int = Field(default=100_000_000, ge=1, le=10**11, strict=True)
    max_workspace_bytes: int = Field(default=64 * 1024**3, ge=1, le=1024**4, strict=True)
    timeout_seconds: int = Field(default=3600, ge=1, le=86400, strict=True)
    max_pair_working_bytes: int = Field(default=4 * 1024**3, ge=1, le=1024**4, strict=True)
    max_model_bytes: int = Field(default=8 * 1024**3, ge=1, le=8 * 1024**3, strict=True)


class MatchingResourceEstimate(FrozenModel):
    pair_count: int = Field(ge=0, le=MAX_PAIRS, strict=True)
    view_count: int = Field(ge=1, strict=True)
    total_features: int = Field(ge=0, strict=True)
    raw_matches: int = Field(ge=0, strict=True)
    database_bytes: int = Field(ge=1, strict=True)
    peak_workspace_bytes: int = Field(ge=1, strict=True)


def estimate_matching_resources(
    features: LocalFeatureSet,
    pairs: PairSet,
    settings: MatcherSettings,
    limits: MatchingResourceLimits,
    *,
    upstream_bytes: int,
    model_bytes: int = 0,
) -> MatchingResourceEstimate:
    counts = {v.view_id: v.feature_count for v in features.views}
    if set(counts) != {v.view_id for v in pairs.universe.views}:
        raise ValueError("PairSet and LocalFeatureSet view universes differ")
    maximum = 0
    pair_memory = 0
    for pair in pairs.pairs:
        left, right = counts[pair.left_view_id], counts[pair.right_view_id]
        # Non-cross-checked routes can map several query features to one target;
        # the smaller endpoint's count is not a valid raw-output upper bound.
        maximum += min(max(left, right), settings.max_num_matches)
        pair_memory = max(pair_memory, left * right * 4 * settings.num_threads)
    if (
        len(pairs.pairs) > limits.max_pairs
        or features.total_feature_count > limits.max_total_features
        or maximum > limits.max_raw_matches
        or pair_memory > limits.max_pair_working_bytes
        or model_bytes > limits.max_model_bytes
    ):
        raise ValueError(
            "Matching pair/feature/correspondence/model/working-memory budget exceeded"
        )
    database = upstream_bytes + maximum * 32 + 1024**2
    peak = 3 * database + model_bytes
    if peak > limits.max_workspace_bytes:
        raise ValueError("Matching workspace budget exceeded")
    return MatchingResourceEstimate(
        pair_count=len(pairs.pairs),
        view_count=len(features.views),
        total_features=features.total_feature_count,
        raw_matches=maximum,
        database_bytes=database,
        peak_workspace_bytes=peak,
    )
