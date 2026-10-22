"""Corpus-bound global representations. No local features, poses or backend imports."""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, model_validator

from splatforge.core.pairs import Digest, PairingViewUniverse, pairing_universe_digest
from splatforge.core.views import MAX_VIEWS, FrozenModel, canonical_json_bytes, sha256_bytes

RETRIEVAL_ARTIFACT_TYPE = "retrieval.representation_set"
MAX_RETRIEVAL_METADATA_BYTES = 64 * 1024**2
MAX_DESCRIPTOR_BYTES = 256 * 1024**2
CandidateMethod = Literal[
    "retrieval.megaloc", "retrieval.anyloc", "retrieval.boq", "retrieval.salad"
]
Finite = Annotated[float, Field(allow_inf_nan=False)]


class RetrievalModelIdentity(FrozenModel):
    role: Literal["weights", "backbone", "vocabulary"]
    name: str = Field(min_length=1, max_length=256)
    source: str = Field(min_length=1, max_length=2048)
    sha256: Digest
    size: int = Field(ge=1, strict=True)


class RetrievalPreprocessing(FrozenModel):
    schema_version: Literal[1] = 1
    identity: str = Field(min_length=1, max_length=256)
    color: Literal["rgb"] = "rgb"
    orientation: Literal["selected_pixels"] = "selected_pixels"
    resize_policy: Literal["stretch", "short_side", "long_side"]
    width: int = Field(ge=14, le=4096, strict=True)
    height: int = Field(ge=14, le=4096, strict=True)
    crop_policy: Literal["none", "center"] = "none"
    interpolation: Literal["bicubic", "bilinear", "lanczos"] = "bicubic"
    antialias: bool = True
    pixel_scale: Finite = Field(default=1 / 255, gt=0)
    mean: tuple[Finite, Finite, Finite] = (0.485, 0.456, 0.406)
    std: tuple[Annotated[float, Field(gt=0, allow_inf_nan=False)], ...] = Field(
        default=(0.229, 0.224, 0.225),
        min_length=3,
        max_length=3,
    )


class RetrievalRepresentationSettings(FrozenModel):
    method_id: CandidateMethod
    method_version: str = Field(min_length=1, max_length=128)
    settings_schema_version: Literal[1] = 1
    models: tuple[RetrievalModelIdentity, ...] = Field(min_length=1, max_length=3)
    preprocessing: RetrievalPreprocessing
    descriptor_dtype: Literal["float32_le"] = "float32_le"
    descriptor_dimension: int = Field(ge=1, le=65536, strict=True)
    normalization: Literal["l2_unit_tolerance_1e-4"] = "l2_unit_tolerance_1e-4"
    metric: Literal["cosine_similarity"] = "cosine_similarity"
    index_method: Literal["flat_exact"] = "flat_exact"
    index_version: Literal[1] = 1
    accumulation: Literal["python_float64_fsum"] = "python_float64_fsum"
    backend_id: str = Field(min_length=1, max_length=256)
    runtime_identity: Digest
    inference_device: Literal["cpu", "gpu:0"]
    inference_provenance: Literal["external_export"] = "external_export"

    @model_validator(mode="after")
    def model_roles(self) -> RetrievalRepresentationSettings:
        roles = [m.role for m in self.models]
        if roles != sorted(set(roles)) or "weights" not in roles:
            raise ValueError("Model roles must be sorted/unique and include weights")
        if self.method_id == "retrieval.anyloc" and "vocabulary" not in roles:
            raise ValueError("AnyLoc VLAD requires an explicitly pinned vocabulary")
        return self


class RetrievalView(FrozenModel):
    view_id: UUID
    image_sha256: Digest
    pixel_transform_digest: Digest
    width: int = Field(ge=1, le=65536, strict=True)
    height: int = Field(ge=1, le=65536, strict=True)


def corpus_digest(universe: PairingViewUniverse, views: tuple[RetrievalView, ...]) -> str:
    return sha256_bytes(
        canonical_json_bytes(
            {
                "corpus_version": 1,
                "universe": pairing_universe_digest(universe),
                "pixels": [v.model_dump(mode="json") for v in views],
            }
        )
    )


class RetrievalExport(FrozenModel):
    """Offline export transport; row order is private and exactly follows indexed UUIDs."""

    export_version: Literal[1] = 1
    settings: RetrievalRepresentationSettings
    universe: PairingViewUniverse
    views: tuple[RetrievalView, ...] = Field(min_length=2, max_length=MAX_VIEWS)
    corpus_semantic_digest: Digest
    descriptor_sha256: Digest
    descriptor_bytes: int = Field(ge=8, le=MAX_DESCRIPTOR_BYTES, strict=True)

    @model_validator(mode="after")
    def exact_corpus(self) -> RetrievalExport:
        if tuple(v.view_id for v in self.views) != tuple(v.view_id for v in self.universe.views):
            raise ValueError("Indexed UUIDs must equal the complete canonical selected universe")
        if self.corpus_semantic_digest != corpus_digest(self.universe, self.views):
            raise ValueError("Retrieval corpus digest mismatch")
        if self.descriptor_bytes != len(self.views) * self.settings.descriptor_dimension * 4:
            raise ValueError("Descriptor storage differs from views * dimension * float32")
        return self

    def recipe_key(self) -> str:
        return sha256_bytes(
            canonical_json_bytes(
                {
                    "representation_recipe_version": 1,
                    "export": self.model_dump(mode="json"),
                }
            )
        )


class RetrievalRepresentationSet(RetrievalExport):
    contract_version: Literal[1] = 1
    candidate_artifact_id: UUID
    candidate_semantic_digest: Digest
    selected_artifact_id: UUID
    selected_semantic_digest: Digest
    semantic_digest: Digest

    def export(self) -> RetrievalExport:
        return RetrievalExport.model_validate(
            self.model_dump(include=set(RetrievalExport.model_fields))
        )

    @model_validator(mode="after")
    def valid_semantics(self) -> RetrievalRepresentationSet:
        if self.semantic_digest != self.export().recipe_key():
            raise ValueError("Retrieval representation semantic digest mismatch")
        return self


class RetrievalResourceLimits(FrozenModel):
    max_views: int = Field(default=4096, ge=2, le=MAX_VIEWS, strict=True)
    max_descriptor_bytes: int = Field(
        default=64 * 1024**2,
        ge=8,
        le=MAX_DESCRIPTOR_BYTES,
        strict=True,
    )
    max_similarity_evaluations: int = Field(default=1_000_000, ge=1, le=10_000_000, strict=True)
    max_scalar_products: int = Field(default=100_000_000, ge=1, le=1_000_000_000, strict=True)


def validate_storage(export: RetrievalExport, limits: RetrievalResourceLimits) -> None:
    if (
        len(export.views) > limits.max_views
        or export.descriptor_bytes > limits.max_descriptor_bytes
    ):
        raise ValueError("Retrieval views/descriptor storage exceed resource limits")
