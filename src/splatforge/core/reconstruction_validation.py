"""M9 immutable universe, detailed geometry and measurement contracts.

These contracts deliberately do not extend ReconstructionSet v1. Native identifiers
and native stored error summaries are not validation inputs.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from enum import StrEnum
from typing import Any, Literal, Protocol
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from splatforge.core.features import Digest, digest_json
from splatforge.core.geometry import ViewCameraPrior
from splatforge.core.media import MediaType
from splatforge.core.reconstruction import ReconstructionCamera, ReconstructionSet, RegisteredView
from splatforge.core.views import MAX_VIEWS, FrozenModel

GEOMETRY_ARTIFACT_TYPE = "validation.geometry_input"
METRICS_ARTIFACT_TYPE = "validation.reconstruction_metrics"
REPORT_ARTIFACT_TYPE = "validation.reconstruction_report"
MAX_VALIDATION_METADATA_BYTES = 64 * 1024**2


class ValidationView(FrozenModel):
    view_id: UUID
    source_id: UUID
    source_group_id: UUID
    camera_group_id: UUID
    media_type: MediaType


class ValidationUniverse(FrozenModel):
    contract_version: Literal[1] = 1
    views: tuple[ValidationView, ...] = Field(min_length=1, max_length=MAX_VIEWS)

    @model_validator(mode="after")
    def canonical(self) -> ValidationUniverse:
        ids = [v.view_id.int for v in self.views]
        if ids != sorted(set(ids)):
            raise ValueError("validation.input_mismatch: universe must be unique and canonical")
        sources: dict[UUID, tuple] = {}
        for v in self.views:
            source = (v.source_group_id, v.media_type)
            if v.source_id in sources and sources[v.source_id] != source:
                raise ValueError("validation.input_mismatch: inconsistent source metadata")
            sources[v.source_id] = source
        return self

    @property
    def semantic_digest(self) -> str:
        return digest_json(self.model_dump(mode="json"))

    def require_reconstruction(self, reconstruction: ReconstructionSet) -> None:
        if tuple(v.view_id for v in self.views) != reconstruction.input_view_ids:
            raise ValueError("validation.input_mismatch: exact selected-view universe differs")


class MetricAvailability(StrEnum):
    EXACT = "exact"
    SAMPLED = "sampled"
    UNAVAILABLE = "unavailable"


class SamplingEvidence(FrozenModel):
    method: Literal["sha256_bottom_k_v1", "uuid_bounded_rays_v1"]
    sample_count: int = Field(ge=1, strict=True)
    population_count: int | None = Field(default=None, ge=1, strict=True)
    upstream: SamplingEvidence | None = None

    @model_validator(mode="after")
    def counts(self) -> SamplingEvidence:
        if self.population_count is not None and self.sample_count > self.population_count:
            raise ValueError("Sample cannot exceed its population")
        return self


class MetricValue(FrozenModel):
    availability: MetricAvailability
    value: float | int | None = None
    reason: (
        Literal[
            "no_points",
            "no_tracks",
            "empty_population",
            "unsupported_camera_model",
            "missing_camera_prior",
            "undefined_projection",
            "insufficient_rays",
            "partial_projection_support",
            "unknown_camera_interpretation",
        ]
        | None
    ) = None
    sampling: SamplingEvidence | None = None

    @model_validator(mode="after")
    def explicit_evidence(self) -> MetricValue:
        unknown = self.availability == MetricAvailability.UNAVAILABLE
        if unknown != (self.value is None) or unknown != (self.reason is not None):
            raise ValueError("Unavailable metrics require a reason and no numerical value")
        if (self.availability == MetricAvailability.SAMPLED) != (self.sampling is not None):
            raise ValueError("Sampled metrics require exact sampling evidence")
        return self


def exact(value: float | int) -> MetricValue:
    return MetricValue(availability=MetricAvailability.EXACT, value=value)


def unavailable(reason: str) -> MetricValue:
    return MetricValue(availability=MetricAvailability.UNAVAILABLE, reason=reason)


class Measurement(FrozenModel):
    name: str = Field(min_length=1, max_length=96, pattern=r"^[a-z0-9_.]+$")
    unit: Literal["count", "ratio", "pixels", "degrees", "observations_per_view"]
    evidence: MetricValue


class MeasurementSettings(FrozenModel):
    method_id: Literal["validation.sparse_measurements_v1"] = "validation.sparse_measurements_v1"
    settings_version: Literal[1] = 1
    quantile_sample_bound: int = Field(default=10000, ge=1, le=1000000, strict=True)
    triangulation_ray_bound: int = Field(default=16, ge=2, le=128, strict=True)
    low_angle_degrees: float = Field(default=1.0, gt=0, lt=90)
    long_track_min_length: int = Field(default=10, ge=3, le=MAX_VIEWS, strict=True)
    projection_version: Literal[1] = 1
    quantile_method: Literal["sha256_bottom_k_nearest_rank_v1"] = "sha256_bottom_k_nearest_rank_v1"
    triangulation_method: Literal["max_acute_angle_bounded_uuid_rays_v1"] = (
        "max_acute_angle_bounded_uuid_rays_v1"
    )


class ValidationResourceLimits(FrozenModel):
    max_components: int = Field(default=1000, ge=1, le=MAX_VIEWS, strict=True)
    max_coverage_cells: int = Field(default=250000, ge=1, le=1000000, strict=True)
    max_native_bytes: int = Field(default=32 * 1024**3, ge=1, le=1024**4, strict=True)
    max_scratch_bytes: int = Field(default=128 * 1024**3, ge=1, le=1024**4, strict=True)
    timeout_seconds: int = Field(default=7200, ge=1, le=86400, strict=True)


def require_measurement_resources(
    reconstruction: ReconstructionSet,
    universe: ValidationUniverse,
    limits: ValidationResourceLimits,
) -> None:
    components = len(reconstruction.components)
    sources = len({v.source_id for v in universe.views})
    groups = len({v.source_group_id for v in universe.views})
    cells = components * (sources + groups)
    if components > limits.max_components or cells > limits.max_coverage_cells:
        raise ValueError(
            "validation.resource_limit: metadata plan requires "
            f"{components} components and {cells} source/component coverage cells; "
            "raise explicit max_components/max_coverage_cells within the metadata contract"
        )


class ValidationObservation(FrozenModel):
    view_id: UUID
    keypoint_index: int = Field(ge=0, strict=True)
    xy: tuple[float, float]


class ValidationPoint(FrozenModel):
    xyz: tuple[float, float, float]
    observations: tuple[ValidationObservation, ...] | None = Field(
        default=None, max_length=MAX_VIEWS
    )

    @model_validator(mode="after")
    def canonical(self) -> ValidationPoint:
        if self.observations is not None:
            ids = [(o.view_id.int, o.keypoint_index) for o in self.observations]
            if ids != sorted(set(ids)):
                raise ValueError("validation.corrupt_geometry: noncanonical observations")
        return self


class ValidationCamera(FrozenModel):
    """M9 may carry uninterpreted future projections without guessing equations."""

    camera_id: UUID
    model: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_]+$")
    width: int = Field(ge=1, le=32768, strict=True)
    height: int = Field(ge=1, le=32768, strict=True)
    parameters: tuple[float, ...] = Field(max_length=128)

    @model_validator(mode="after")
    def known_parameters(self) -> ValidationCamera:
        if self.model in {
            "SIMPLE_PINHOLE",
            "PINHOLE",
            "SIMPLE_RADIAL",
            "RADIAL",
            "OPENCV",
            "FULL_OPENCV",
        }:
            ViewCameraPrior(
                view_id=self.camera_id,
                model=self.model,
                width=self.width,
                height=self.height,
                parameters=self.parameters,
            )
        return self


class ValidationComponentInput(FrozenModel):
    component_id: UUID
    cameras: tuple[ValidationCamera, ...]
    views: tuple[RegisteredView, ...]
    priors: tuple[ViewCameraPrior, ...] = ()
    points_available: bool
    tracks_available: bool

    @field_validator("cameras", mode="before")
    @classmethod
    def normalize_cameras(cls, values: Any) -> Any:
        return tuple(c.model_dump() if isinstance(c, ReconstructionCamera) else c for c in values)

    @model_validator(mode="after")
    def consistent(self) -> ValidationComponentInput:
        if self.tracks_available and not self.points_available:
            raise ValueError("Tracks require points")
        cameras = {c.camera_id for c in self.cameras}
        if len(cameras) != len(self.cameras) or any(v.camera_id not in cameras for v in self.views):
            raise ValueError("validation.corrupt_geometry: invalid camera mapping")
        return self


class ValidationGeometrySource(Protocol):
    """Read-only normalized source. A component's points stream in canonical order."""

    def component(self, component_id: UUID) -> ValidationComponentInput: ...
    def points(self, component_id: UUID) -> Iterator[ValidationPoint]: ...


class ComponentGeometryIdentity(FrozenModel):
    component_id: UUID
    component_semantic_digest: Digest
    content_digest: Digest
    reference_digest: Digest
    points_available: bool
    tracks_available: bool
    point_count: int | None = Field(default=None, ge=0, strict=True)


class ValidationGeometryInput(FrozenModel):
    contract_version: Literal[1] = 1
    reconstruction_digest: Digest
    components: tuple[ComponentGeometryIdentity, ...] = Field(min_length=1, max_length=MAX_VIEWS)

    @model_validator(mode="after")
    def canonical(self) -> ValidationGeometryInput:
        ids = [c.component_id.int for c in self.components]
        if ids != sorted(set(ids)):
            raise ValueError("Geometry components must be unique and canonical")
        if any(c.tracks_available and not c.points_available for c in self.components):
            raise ValueError("Tracks require point capability")
        return self

    @property
    def semantic_digest(self) -> str:
        return digest_json(self.model_dump(mode="json"))


class Coverage(FrozenModel):
    input_views: int = Field(ge=1, strict=True)
    registered_views: int = Field(ge=0, strict=True)
    ratio: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def counts(self) -> Coverage:
        if self.registered_views > self.input_views or self.ratio != (
            self.registered_views / self.input_views
        ):
            raise ValueError("Coverage denominator/count mismatch")
        return self


def coverage(total: int, registered: int) -> Coverage:
    return Coverage(input_views=total, registered_views=registered, ratio=registered / total)


class ComponentCoverage(FrozenModel):
    component_id: UUID
    coverage: Coverage


class GroupCoverage(FrozenModel):
    group_id: UUID
    overall: Coverage
    components: tuple[ComponentCoverage, ...]


class TrackLengthBin(FrozenModel):
    length: int = Field(ge=0, le=MAX_VIEWS, strict=True)
    count: int = Field(ge=1, strict=True)


class CameraModelCount(FrozenModel):
    model: str = Field(min_length=1, max_length=128)
    count: int = Field(ge=1, strict=True)


class ComponentMetrics(FrozenModel):
    component_id: UUID
    component_semantic_digest: Digest
    geometry_digest: Digest
    registration: Coverage
    source_count: int = Field(ge=1, strict=True)
    source_group_count: int = Field(ge=1, strict=True)
    camera_group_count: int = Field(ge=1, strict=True)
    camera_models: tuple[CameraModelCount, ...]
    track_histogram: tuple[TrackLengthBin, ...]
    measurements: tuple[Measurement, ...]

    @model_validator(mode="after")
    def canonical(self) -> ComponentMetrics:
        names = [m.name for m in self.measurements]
        if names != sorted(set(names)):
            raise ValueError("Component measurements must be unique and canonical")
        lengths = [b.length for b in self.track_histogram]
        if lengths != sorted(set(lengths)):
            raise ValueError("Track histogram must be unique and canonical")
        measures = {m.name: m.evidence for m in self.measurements}
        if "point.count" not in measures or "track.observation_count" not in measures:
            raise ValueError("Missing required factual metric availability")
        if self.track_histogram:
            points = sum(b.count for b in self.track_histogram)
            observations = sum(b.length * b.count for b in self.track_histogram)
            if (
                measures["point.count"].value != points
                or measures["track.observation_count"].value != observations
            ):
                raise ValueError("Track histogram/count mismatch")
        return self

    def metric(self, name: str) -> MetricValue:
        return next(m.evidence for m in self.measurements if m.name == name)


class ReconstructionMetrics(FrozenModel):
    contract_version: Literal[1] = 1
    reconstruction_digest: Digest
    universe_digest: Digest
    geometry: ValidationGeometryInput
    settings: MeasurementSettings
    registration: Coverage
    unregistered_count: int = Field(ge=0, strict=True)
    component_count: int = Field(ge=1, strict=True)
    component_sizes: tuple[int, ...]
    largest_component: Coverage
    second_largest_component: Coverage | None
    registered_outside_largest_fraction: float = Field(ge=0, le=1)
    sources: tuple[GroupCoverage, ...]
    source_groups: tuple[GroupCoverage, ...]
    components: tuple[ComponentMetrics, ...]

    @model_validator(mode="after")
    def consistent(self) -> ReconstructionMetrics:
        identities = {c.component_id: c for c in self.geometry.components}
        ids = [c.component_id.int for c in self.components]
        if (
            ids != sorted(set(ids))
            or set(identities) != {c.component_id for c in self.components}
            or self.reconstruction_digest != self.geometry.reconstruction_digest
            or self.component_count != len(self.components)
        ):
            raise ValueError("Metrics component/geometry identity mismatch")
        sizes = tuple(
            sorted((c.registration.registered_views for c in self.components), reverse=True)
        )
        total = self.registration.input_views
        if (
            not sizes
            or self.component_sizes != sizes
            or sum(sizes) != self.registration.registered_views
            or self.unregistered_count != total - sum(sizes)
            or self.largest_component != coverage(total, sizes[0])
            or self.second_largest_component
            != (coverage(total, sizes[1]) if len(sizes) > 1 else None)
            or self.registered_outside_largest_fraction != (sum(sizes) - sizes[0]) / sum(sizes)
        ):
            raise ValueError("Metrics registration/fragmentation counts mismatch")
        for c in self.components:
            identity = identities[c.component_id]
            if (
                c.registration.input_views != total
                or c.component_semantic_digest != identity.component_semantic_digest
                or c.geometry_digest != identity.content_digest
            ):
                raise ValueError("Component metric evidence differs from detailed geometry")
        for collection in (self.sources, self.source_groups):
            keys = [g.group_id.int for g in collection]
            if (
                keys != sorted(set(keys))
                or sum(g.overall.input_views for g in collection) != total
                or sum(g.overall.registered_views for g in collection) != sum(sizes)
            ):
                raise ValueError("Metrics source universe counts mismatch")
            for g in collection:
                if (
                    [c.component_id.int for c in g.components] != ids
                    or sum(c.coverage.registered_views for c in g.components)
                    != g.overall.registered_views
                    or any(c.coverage.input_views != g.overall.input_views for c in g.components)
                ):
                    raise ValueError("Metrics source/component denominators mismatch")
        return self

    @property
    def semantic_digest(self) -> str:
        return digest_json(self.model_dump(mode="json"))

    @property
    def recipe_key(self) -> str:
        return measurements_recipe(
            self.reconstruction_digest,
            self.universe_digest,
            self.geometry.semantic_digest,
            self.settings,
        )


def measurements_recipe(
    reconstruction: str,
    universe: str,
    geometry: str,
    settings: MeasurementSettings,
) -> str:
    return digest_json(
        {
            "method_version": 1,
            "reconstruction": reconstruction,
            "universe": universe,
            "geometry": geometry,
            "settings": settings.model_dump(mode="json"),
        }
    )


Checkpoint = Callable[[], None]
