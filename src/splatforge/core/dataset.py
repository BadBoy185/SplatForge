"""M10 immutable flat-camera datasets; decisions and numerical content are separate."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from splatforge.core.capabilities import CapabilityEvidence, ExecutableSelection
from splatforge.core.features import Digest, FeatureRuntimeFile, digest_json
from splatforge.core.reconstruction import (
    CONVENTION,
    ReconstructionCamera,
    RegisteredView,
    component_semantic_digest,
)
from splatforge.core.reconstruction_selection import SelectedComponentContent
from splatforge.core.views import MAX_VIEWS, FrozenModel

COMPONENT_ARTIFACT_TYPE = "dataset.prepared_component"
SET_ARTIFACT_TYPE = "dataset.prepared_set"
METHOD_ID = "dataset.colmap_undistorted_v1"
INPUT_MODELS = frozenset(
    {
        "SIMPLE_PINHOLE",
        "PINHOLE",
        "SIMPLE_RADIAL",
        "RADIAL",
        "OPENCV",
        "FULL_OPENCV",
    }
)
OUTPUT_MODELS = frozenset({"SIMPLE_PINHOLE", "PINHOLE"})
MAX_METADATA_BYTES = 64 * 1024**2
POSE_ABSOLUTE_TOLERANCE = 1e-8


class DatasetSettings(FrozenModel):
    settings_version: Literal[1] = 1
    method_id: Literal["dataset.colmap_undistorted_v1"] = METHOD_ID
    max_image_size: int | None = Field(default=None, ge=1, le=32768, strict=True)
    # Full ROI; retain FOV at the native bounded scale, permitting blank borders.
    # No user-defined crop, encoding layer, scale or resolution pyramid in M10.
    blank_pixels: Literal[1.0] = 1.0
    min_scale: Literal[0.2] = 0.2
    max_scale: Literal[2.0] = 2.0
    jpeg_quality: Literal[-1] = -1
    num_threads: Literal[2] = 2
    observation_policy: Literal["registered_sparse_tracks_v1"] = "registered_sparse_tracks_v1"


class DatasetBackend(FrozenModel):
    adapter_id: Literal["splatforge.colmap_dataset"] = "splatforge.colmap_dataset"
    adapter_version: Literal[1] = 1
    selection: ExecutableSelection
    option_names: tuple[str, ...] = Field(max_length=512)
    runtime_files: tuple[FeatureRuntimeFile, ...] = Field(default=(), max_length=1024)
    numerical_identity: Digest
    capability_evidence: tuple[CapabilityEvidence, ...] = Field(default=(), max_length=4)


class DatasetInputImage(FrozenModel):
    view_id: UUID
    name: str = Field(pattern=r"^[0-9a-f-]{36}\.(png|jpg)$")
    sha256: Digest
    width: int = Field(gt=0, le=32768, strict=True)
    height: int = Field(gt=0, le=32768, strict=True)
    size: int = Field(gt=0, strict=True)

    @model_validator(mode="after")
    def public_name(self) -> DatasetInputImage:
        if self.name != f"{self.view_id}.{self.name.rsplit('.', 1)[1]}":
            raise ValueError("dataset.invalid_image_name: name must derive from public view UUID")
        return self


class DatasetImage(DatasetInputImage):
    pass


class DatasetProvenance(FrozenModel):
    pixel_source: Literal["historical_materialized_artifacts"] = "historical_materialized_artifacts"
    original_media_verification: Literal["not_required_not_checked"] = "not_required_not_checked"
    selection_artifact_id: UUID
    selection_digest: Digest
    reconstruction_artifact_id: UUID
    reconstruction_digest: Digest
    candidate_artifact_id: UUID
    selected_artifact_id: UUID
    validation_report_digest: Digest
    validation_status: Literal["pass", "warn", "fail"] = "pass"
    warnings: tuple[str, ...] = Field(default=(), max_length=100000)
    override: dict[str, object] | None = None
    practical_multi_video_pairing_status: Literal[
        "explicit_reference_pairing", "small_fixture_pairing", "unknown"
    ] = "unknown"
    production_multi_video_gate: Literal["pending_m7c_production_vpr"] = (
        "pending_m7c_production_vpr"
    )
    pairing_method: str | None = None


def component_recipe(
    content: SelectedComponentContent,
    images: tuple[DatasetInputImage, ...],
    settings: DatasetSettings,
    backend_identity: str,
    source_sparse_digest: str,
) -> str:
    return digest_json(
        {
            "dataset_recipe_version": 1,
            "component": content.model_dump(mode="json"),
            "images": [i.model_dump(mode="json") for i in images],
            "settings": settings.model_dump(mode="json"),
            "backend": backend_identity,
            "source_sparse_digest": source_sparse_digest,
        }
    )


class PreparedDatasetComponent(FrozenModel):
    contract_version: Literal[1] = 1
    dataset_format: Literal["colmap_undistorted_v1"] = "colmap_undistorted_v1"
    source_component: SelectedComponentContent
    source_sparse_digest: Digest
    settings: DatasetSettings
    backend_numerical_identity: Digest
    input_images: tuple[DatasetInputImage, ...] = Field(min_length=3, max_length=MAX_VIEWS)
    images: tuple[DatasetImage, ...] = Field(min_length=3, max_length=MAX_VIEWS)
    cameras: tuple[ReconstructionCamera, ...] = Field(min_length=1, max_length=MAX_VIEWS)
    views: tuple[RegisteredView, ...] = Field(min_length=3, max_length=MAX_VIEWS)
    sparse_point_count: int = Field(ge=0, strict=True)
    input_unassociated_observations_omitted: int = Field(default=0, ge=0, strict=True)
    sparse_geometry_digest: Digest
    preserved_world_points_digest: Digest
    camera_convention: Literal[CONVENTION] = CONVENTION
    scale: Literal["unknown_arbitrary"] = "unknown_arbitrary"
    output_layout: Literal["images+sparse/0+dataset.json"] = "images+sparse/0+dataset.json"
    provenance: DatasetProvenance

    @model_validator(mode="after")
    def canonical(self) -> PreparedDatasetComponent:
        ids = [i.view_id.int for i in self.images]
        if ids != sorted(set(ids)) or ids != [v.view_id.int for v in self.views]:
            raise ValueError("dataset.membership_mismatch: unique canonical images/poses required")
        if ids != [v.view_id.int for v in self.input_images]:
            raise ValueError("dataset.membership_mismatch: input/output views differ")
        if [i.name for i in self.images] != [i.name for i in self.input_images]:
            raise ValueError("dataset.membership_mismatch: output image names changed")
        camera_ids = [c.camera_id.int for c in self.cameras]
        if camera_ids != sorted(set(camera_ids)):
            raise ValueError("dataset.invalid_cameras: duplicate/noncanonical cameras")
        if {v.camera_id for v in self.views} != {c.camera_id for c in self.cameras}:
            raise ValueError("dataset.invalid_cameras: missing/unused camera")
        if any(c.model not in OUTPUT_MODELS for c in self.cameras):
            raise ValueError("dataset.distorted_output: only PINHOLE/SIMPLE_PINHOLE supported")
        return self

    @property
    def image_count(self) -> int:
        return len(self.images)

    @property
    def camera_count(self) -> int:
        return len(self.cameras)

    @property
    def selected_view_ids(self) -> tuple[UUID, ...]:
        return tuple(i.view_id for i in self.images)

    @property
    def recipe_key(self) -> str:
        return component_recipe(
            self.source_component,
            self.input_images,
            self.settings,
            self.backend_numerical_identity,
            self.source_sparse_digest,
        )

    @property
    def semantic_digest(self) -> str:
        return digest_json(
            {
                "numerical_camera_pose_digest": component_semantic_digest(
                    self.cameras, self.views, point_count=self.sparse_point_count
                ),
                "content": self.model_dump(
                    mode="json",
                    exclude={
                        "provenance",
                        "backend_numerical_identity",
                        "input_images",
                        "cameras",
                        "views",
                        "input_unassociated_observations_omitted",
                    },
                ),
            }
        )

    def metadata(self) -> dict:
        return {
            **self.model_dump(mode="json"),
            "numerical_semantic_digest": self.semantic_digest,
            "recipe_key": self.recipe_key,
            "image_count": self.image_count,
            "camera_count": self.camera_count,
            "selected_view_ids": [str(i) for i in self.selected_view_ids],
            "output_camera_models": sorted({c.model for c in self.cameras}),
        }


class DatasetComponentReference(FrozenModel):
    component_id: UUID
    artifact_id: UUID
    semantic_digest: Digest
    manifest_path: str
    image_count: int = Field(ge=3, le=MAX_VIEWS, strict=True)

    @model_validator(mode="after")
    def owned_locator(self) -> DatasetComponentReference:
        if self.manifest_path != f"artifacts/dataset_component/{self.artifact_id}/manifest.json":
            raise ValueError("dataset.unsafe_reference: require exact project-owned component path")
        return self


class PreparedDatasetSet(FrozenModel):
    contract_version: Literal[1] = 1
    dataset_format: Literal["colmap_undistorted_v1"] = "colmap_undistorted_v1"
    provenance: DatasetProvenance
    components: tuple[DatasetComponentReference, ...] = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def canonical(self) -> PreparedDatasetSet:
        ids = [c.component_id.int for c in self.components]
        if ids != sorted(set(ids)):
            raise ValueError("dataset.invalid_components: unique canonical components required")
        return self

    @property
    def semantic_digest(self) -> str:
        return digest_json(
            {
                "dataset_set_version": 1,
                "separate_components": [
                    (str(c.component_id), c.semantic_digest) for c in self.components
                ],
            }
        )

    @property
    def recipe_key(self) -> str:
        # A small receipt freezes the exact current decision/provenance, even on
        # component cache hits. It never duplicates the component image payloads.
        return digest_json(self.model_dump(mode="json"))


class DatasetResourceLimits(FrozenModel):
    max_workspace_bytes: int = Field(default=32 * 1024**3, ge=1, le=1024**4, strict=True)
    minimum_free_bytes: int = Field(default=256 * 1024**2, ge=0, strict=True)
    timeout_seconds: int = Field(default=7200, ge=1, le=86400, strict=True)
    max_components: int = Field(default=1000, ge=1, le=1000, strict=True)


class DatasetResourceEstimate(FrozenModel):
    input_pixel_bytes: int
    sparse_input_bytes: int
    input_megapixels: float
    output_megapixels_upper: float
    output_bytes_expected: int
    output_bytes_conservative: int
    peak_workspace_bytes: int
    decoded_working_memory_bytes: int
    disk_safety_margin_bytes: int
    assumptions: tuple[str, ...]


def estimate_dataset_resources(
    images: tuple[DatasetInputImage, ...],
    sparse_bytes: int,
    settings: DatasetSettings,
    limits: DatasetResourceLimits,
) -> DatasetResourceEstimate:
    encoded = sum(i.size for i in images)
    pixels = sum(i.width * i.height for i in images)
    output_pixels = []
    conservative, expected = 0, 0
    for image in images:
        # Distortion removal can expand each dimension up to max_scale. Already
        # flat inputs can be overestimated here; this is inspectable, never exact.
        w, h = image.width * settings.max_scale, image.height * settings.max_scale
        scale = min(1, settings.max_image_size / max(w, h)) if settings.max_image_size else 1
        count = int(w * h * scale**2)
        output_pixels.append(count)
        ratio = count / (image.width * image.height)
        expected += max(int(image.size * ratio), int(count * 0.3))
        conservative += (
            max(
                int(image.size * ratio * 2),
                int(count * (3.2 if image.name.endswith(".png") else 2)),
            )
            + 65536
        )
    overhead = 4 * sparse_bytes + len(images) * 4096 + 8 * 1024**2
    return DatasetResourceEstimate(
        input_pixel_bytes=encoded,
        sparse_input_bytes=sparse_bytes,
        input_megapixels=pixels / 1e6,
        output_megapixels_upper=sum(output_pixels) / 1e6,
        output_bytes_expected=expected + sparse_bytes,
        output_bytes_conservative=conservative + sparse_bytes,
        # Same-volume publication is a rename; no second large publication copy.
        peak_workspace_bytes=encoded + conservative + overhead,
        decoded_working_memory_bytes=max((i.width * i.height for i in images), default=0) * 64,
        disk_safety_margin_bytes=limits.minimum_free_bytes,
        assumptions=(
            "Encoded input is measured; compressed output size is an estimate, not a bound.",
            "Output dimensions may grow by native max_scale=2 per axis; optional max side applies.",
            "Expected: scaled input or 0.3 bytes/pixel; conservative: twice scaled input or "
            "2 JPEG / 3.2 PNG bytes/pixel plus 64 KiB/image.",
            "Sparse input/output/index allowance: 4x sparse bytes; metadata 4 KiB/image + 8 MiB.",
            "Two native threads; decoded memory is separate from compressed disk estimates.",
            "Same-volume publication renames output; completed components remain on disk.",
        ),
    )
