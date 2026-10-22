"""Versioned, backend-neutral local-feature metadata and numerical identities."""

from __future__ import annotations

import hashlib
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, model_validator

from splatforge.core.capabilities import (
    CapabilityEvidence,
    DatabaseCompatibility,
    ExecutableSelection,
    ModelEvidence,
)
from splatforge.core.views import MAX_VIEWS, FrozenModel, canonical_json_bytes

FEATURE_ARTIFACT_TYPE = "features.local_feature_set"
FEATURE_CONTRACT_VERSION = 1
MAX_FEATURES_PER_VIEW = 100_000
MAX_FEATURE_METADATA_BYTES = 64 * 1024 * 1024
MAX_FEATURE_DATABASE_BYTES = 1024**4
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class DescriptorFamily(StrEnum):
    SIFT = "sift"
    ALIKED = "aliked"
    LOMA_B = "loma_b"
    LOMA_B128 = "loma_b128"


class ExtractionSettings(FrozenModel):
    settings_version: Literal[1] = 1
    max_features: int = Field(default=2048, ge=1, le=MAX_FEATURES_PER_VIEW, strict=True)
    max_image_size: int = Field(default=2048, ge=32, le=32768, strict=True)
    use_gpu: bool = Field(default=False, strict=True)


class SiftExtractionSettings(ExtractionSettings):
    method_id: Literal["feature_extraction.sift"] = "feature_extraction.sift"
    variant: Literal["SIFT"] = "SIFT"
    max_features: int = Field(default=8192, ge=1, le=MAX_FEATURES_PER_VIEW, strict=True)


class AlikedExtractionSettings(ExtractionSettings):
    method_id: Literal["feature_extraction.aliked"] = "feature_extraction.aliked"
    variant: Literal["ALIKED_N16ROT", "ALIKED_N32"] = "ALIKED_N16ROT"
    min_score: float = Field(default=0.2, ge=0, le=1)


class LomaExtractionSettings(ExtractionSettings):
    method_id: Literal["feature_extraction.loma_b", "feature_extraction.loma_b128"] = (
        "feature_extraction.loma_b"
    )
    variant: Literal["LOMA_B", "LOMA_B128"] = "LOMA_B"
    min_score: float = Field(default=0.0, ge=0, le=1)
    # BF16 has backend fallback semantics; M7a deliberately supports pinned FP32 only.
    use_bf16: Literal[False] = False
    use_fast_resize: bool = Field(default=False, strict=True)

    @model_validator(mode="after")
    def matching_variant(self) -> LomaExtractionSettings:
        if self.method_id != f"feature_extraction.{self.variant.lower()}":
            raise ValueError("LoMa method and variant differ")
        return self


FeatureSettings = Annotated[
    SiftExtractionSettings | AlikedExtractionSettings | LomaExtractionSettings,
    Field(discriminator="method_id"),
]


class DescriptorSignature(FrozenModel):
    family: DescriptorFamily
    dimension: int = Field(ge=1, le=256, strict=True)
    scalar_type: Literal["uint8", "float32_le"]
    storage: Literal["row_major"] = "row_major"
    keypoint_coordinates: Literal["pixel_corner_origin_xy_center_0.5_v1"] = (
        "pixel_corner_origin_xy_center_0.5_v1"
    )

    @model_validator(mode="after")
    def family_representation(self) -> DescriptorSignature:
        dimension = 256 if self.family == DescriptorFamily.LOMA_B else 128
        scalar = "uint8" if self.family == DescriptorFamily.SIFT else "float32_le"
        if (self.dimension, self.scalar_type) != (dimension, scalar):
            raise ValueError("Descriptor dimensions/scalar type differ from family")
        return self

    @property
    def row_bytes(self) -> int:
        return self.dimension * (1 if self.scalar_type == "uint8" else 4)


def descriptor_signature(settings: FeatureSettings) -> DescriptorSignature:
    family = DescriptorFamily(settings.method_id.removeprefix("feature_extraction."))
    return DescriptorSignature(
        family=family,
        dimension=256 if family == DescriptorFamily.LOMA_B else 128,
        scalar_type="uint8" if family == DescriptorFamily.SIFT else "float32_le",
    )


class LearnedModelIdentity(FrozenModel):
    role: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=512)
    source: str = Field(min_length=1, max_length=2048)
    sha256: Digest
    size: int = Field(gt=0, le=8 * 1024**3, strict=True)


class FeatureViewSummary(FrozenModel):
    view_id: UUID
    image_sha256: Digest
    width: int = Field(gt=0, le=32768, strict=True)
    height: int = Field(gt=0, le=32768, strict=True)
    feature_count: int = Field(ge=0, le=MAX_FEATURES_PER_VIEW, strict=True)
    keypoint_columns: Literal[2, 4, 6]
    content_digest: Digest


class LocalFeatureSet(FrozenModel):
    contract_version: Literal[1] = FEATURE_CONTRACT_VERSION
    selected_artifact_id: UUID
    selected_semantic_digest: Digest
    method_id: str = Field(min_length=1, max_length=128)
    method_version: Literal[1] = 1
    descriptor: DescriptorSignature
    settings: FeatureSettings
    backend_numerical_identity: Digest
    models: tuple[LearnedModelIdentity, ...] = Field(default=(), max_length=2)
    selected_view_count: int = Field(ge=1, le=MAX_VIEWS, strict=True)
    total_feature_count: int = Field(ge=0, le=MAX_VIEWS * MAX_FEATURES_PER_VIEW, strict=True)
    views: tuple[FeatureViewSummary, ...] = Field(min_length=1, max_length=MAX_VIEWS)
    semantic_digest: Digest

    @model_validator(mode="after")
    def bounded_consistent_content(self) -> LocalFeatureSet:
        ids = [v.view_id.int for v in self.views]
        if ids != sorted(set(ids)):
            raise ValueError("Feature views require unique UUID order")
        if self.selected_view_count != len(ids):
            raise ValueError("Selected view count differs from summaries")
        if self.total_feature_count != sum(v.feature_count for v in self.views):
            raise ValueError("Total feature count differs from summaries")
        if any(v.feature_count > self.settings.max_features for v in self.views):
            raise ValueError("Per-view feature count exceeds configured bound")
        if self.method_id != self.settings.method_id:
            raise ValueError("Extractor method differs from settings")
        if self.descriptor != descriptor_signature(self.settings):
            raise ValueError("Descriptor signature differs from extractor")
        roles = model_roles(self.settings)
        if tuple(m.role for m in self.models) != roles:
            raise ValueError("Learned model roles differ from extractor variant")
        if feature_semantic_digest(self) != self.semantic_digest:
            raise ValueError("Feature semantic digest mismatch")
        return self


def model_roles(settings: FeatureSettings) -> tuple[str, ...]:
    if isinstance(settings, SiftExtractionSettings):
        return ()
    if isinstance(settings, AlikedExtractionSettings):
        return ("aliked.n32" if settings.variant == "ALIKED_N32" else "aliked.n16rot",)
    return ("loma.detector", "loma.b128" if settings.variant == "LOMA_B128" else "loma.b")


def resolve_extraction_settings(
    variant: str,
    *,
    max_features: int | None = None,
    max_image_size: int = 2048,
    use_gpu: bool = False,
    min_score: float | None = None,
    use_fast_resize: bool = False,
) -> FeatureSettings:
    values = {"max_image_size": max_image_size, "use_gpu": use_gpu}
    if max_features is not None:
        values["max_features"] = max_features
    if variant.upper() == "SIFT":
        if min_score is not None or use_fast_resize:
            raise ValueError("SIFT does not support learned min_score/fast_resize settings")
        return SiftExtractionSettings(**values)
    if min_score is not None:
        values["min_score"] = min_score
    if variant.upper() in {"ALIKED_N16ROT", "ALIKED_N32"}:
        if use_fast_resize:
            raise ValueError("fast_resize is a LoMa extraction setting")
        return AlikedExtractionSettings(variant=variant.upper(), **values)
    if variant.upper() in {"LOMA_B", "LOMA_B128"}:
        return LomaExtractionSettings(
            method_id=f"feature_extraction.{variant.lower()}",
            variant=variant.upper(),
            use_fast_resize=use_fast_resize,
            **values,
        )
    raise ValueError(
        "Unknown extractor; choose SIFT, ALIKED_N16ROT, ALIKED_N32, LOMA_B or LOMA_B128"
    )


def digest_json(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def feature_semantic_digest(features: LocalFeatureSet) -> str:
    # Exact producer handles and backend-local IDs belong only to lineage/payload.
    return digest_json(
        features.model_dump(
            mode="json",
            exclude={"semantic_digest", "selected_artifact_id"},
        )
    )


def feature_recipe_key(
    selected_digest: str,
    settings: FeatureSettings,
    backend_identity: str,
    models: tuple[LearnedModelIdentity, ...],
) -> str:
    return digest_json(
        {
            "fingerprint_version": 1,
            "contract_version": FEATURE_CONTRACT_VERSION,
            "method_version": 1,
            "settings": settings.model_dump(mode="json"),
            "selected_semantic_digest": selected_digest,
            "backend_numerical_identity": backend_identity,
            "models": [m.model_dump(mode="json") for m in models],
        }
    )


class FeatureResourceLimits(FrozenModel):
    max_views: int = Field(default=10_000, ge=1, le=MAX_VIEWS, strict=True)
    max_source_megapixels: int = Field(default=100_000, ge=1, le=6_400_000, strict=True)
    max_workspace_bytes: int = Field(
        default=64 * 1024**3, ge=1, le=MAX_FEATURE_DATABASE_BYTES, strict=True
    )
    timeout_seconds: int = Field(default=3600, ge=1, le=86400, strict=True)


class FeatureResourceEstimate(FrozenModel):
    views: int = Field(ge=1, le=MAX_VIEWS, strict=True)
    source_megapixels: float = Field(gt=0)
    maximum_features: int = Field(ge=1, strict=True)
    descriptor_bytes: int = Field(ge=0, strict=True)
    database_bytes: int = Field(ge=0, strict=True)
    peak_workspace_bytes: int = Field(ge=0, strict=True)


class FeatureRuntimeFile(FrozenModel):
    name: str = Field(min_length=1, max_length=512)
    path: str = Field(min_length=1, max_length=4096)
    sha256: Digest
    size: int = Field(ge=1, le=2 * 1024**3, strict=True)


class FeatureBackend(FrozenModel):
    """Frozen verified adapter evidence; paths never enter numerical identity."""

    adapter_id: Literal["splatforge.colmap_features"] = "splatforge.colmap_features"
    adapter_version: Literal[1] = 1
    selection: ExecutableSelection
    database: DatabaseCompatibility
    option_names: tuple[str, ...] = Field(max_length=512)
    models: tuple[ModelEvidence, ...] = Field(default=(), max_length=2)
    runtime_files: tuple[FeatureRuntimeFile, ...] = Field(default=(), max_length=1024)
    live_progress_profile: Literal["colmap_4.2.1_v1"] | None = None
    numerical_identity: Digest
    capability_evidence: tuple[CapabilityEvidence, ...] = Field(default=(), max_length=4)

    def model_identities(self) -> tuple[LearnedModelIdentity, ...]:
        return tuple(
            LearnedModelIdentity(
                role=m.role,
                name=m.expected_name,
                source=m.source_uri or m.configured_source,
                sha256=m.sha256,
                size=m.size,
            )
            for m in self.models
        )


def estimate_feature_resources(
    *,
    views: int,
    pixels: int,
    encoded_bytes: int,
    settings: FeatureSettings,
    limits: FeatureResourceLimits,
    model_bytes: int = 0,
) -> FeatureResourceEstimate:
    if not 1 <= views <= limits.max_views or pixels <= 0 or encoded_bytes < 0 or model_bytes < 0:
        raise ValueError("Invalid feature resource inputs or view budget exceeded")
    descriptors = views * settings.max_features * descriptor_signature(settings).row_bytes
    # Keypoints, SQLite pages/indexes, journal, copied pixels and pinned models.
    database = (descriptors + views * settings.max_features * 24) * 2 + views * 8192 + 1024**2
    peak = database * 2 + encoded_bytes + model_bytes
    estimate = FeatureResourceEstimate(
        views=views,
        source_megapixels=pixels / 1_000_000,
        maximum_features=views * settings.max_features,
        descriptor_bytes=descriptors,
        database_bytes=database,
        peak_workspace_bytes=peak,
    )
    if estimate.source_megapixels > limits.max_source_megapixels:
        raise ValueError("Feature source megapixel budget exceeded")
    if peak > limits.max_workspace_bytes or database > MAX_FEATURE_DATABASE_BYTES:
        raise ValueError("Feature workspace budget exceeded")
    return estimate
