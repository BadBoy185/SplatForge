"""Immutable M3 view contracts, identities, fingerprints, and fixed-FPS selection."""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from collections.abc import Iterator, Sequence
from enum import StrEnum
from fractions import Fraction
from pathlib import PurePosixPath, PureWindowsPath
from typing import TYPE_CHECKING, Annotated, Any, Literal
from uuid import UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from splatforge.core.media import ExecutableIdentity, MediaType, SourceOccurrence

if TYPE_CHECKING:
    from splatforge.core.execution import ArtifactHandle

FINGERPRINT_SCHEMA_VERSION = 1
CANDIDATE_ARTIFACT_TYPE = "views.candidate_set"
SELECTED_ARTIFACT_TYPE = "views.selected_set"
VIEW_ARTIFACT_CONTRACT_VERSION = 1
CANDIDATE_METHOD_ID = "view_preparation.ffmpeg_fixed_pool"
SELECTION_METHOD_ID = "frame_selection.fixed_fps"
CANDIDATE_METHOD_VERSION = 1
SELECTION_METHOD_VERSION = 1
FFMPEG_ADAPTER_ID = "splatforge.ffmpeg"
FFMPEG_ADAPTER_VERSION = 2
MAX_RATIONAL_COMPONENT = 1_000_000_000
MAX_EXACT_COMPONENT = 9_000_000_000_000_000_000
MAX_VIEWS = 100_000
_VIEW_NAMESPACE = UUID("d3b75ca5-59aa-55a6-a89d-1c4ba879fd75")


class FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


class RationalValue(FrozenModel):
    """A canonical exact rational used for FPS, time bases, and target times."""

    numerator: int = Field(strict=True)
    denominator: int = Field(gt=0, le=MAX_EXACT_COMPONENT, strict=True)

    @model_validator(mode="after")
    def canonical_and_bounded(self) -> RationalValue:
        if abs(self.numerator) > MAX_EXACT_COMPONENT:
            raise ValueError("rational numerator exceeds its bound")
        common = math.gcd(self.numerator, self.denominator)
        if common != 1:
            raise ValueError("rational value must be in canonical lowest terms")
        return self

    @classmethod
    def from_fraction(cls, value: Fraction) -> RationalValue:
        return cls(numerator=value.numerator, denominator=value.denominator)

    def as_fraction(self) -> Fraction:
        return Fraction(self.numerator, self.denominator)


def parse_fps(value: str) -> RationalValue:
    """Parse an integer, decimal, or fraction without binary floating-point identity."""

    text = value.strip()
    if not text:
        raise ValueError("FPS must not be empty")
    if text.lower() in {"nan", "+nan", "-nan", "inf", "+inf", "-inf", "infinity"}:
        raise ValueError("FPS must be finite")
    try:
        parsed = Fraction(text)
    except (ValueError, ZeroDivisionError) as exc:
        raise ValueError(f"Invalid FPS value: {value}") from exc
    if parsed <= 0:
        raise ValueError("FPS must be positive")
    if (
        abs(parsed.numerator) > MAX_RATIONAL_COMPONENT
        or parsed.denominator > MAX_RATIONAL_COMPONENT
    ):
        raise ValueError("FPS numerator or denominator is unreasonable")
    return RationalValue.from_fraction(parsed)


def parse_gib_bytes(value: str) -> int:
    text = value.strip()
    if not text:
        raise ValueError("disk budget must not be empty")
    if text.lower() in {"nan", "+nan", "-nan", "inf", "+inf", "-inf", "infinity"}:
        raise ValueError("disk budget must be finite")
    try:
        gib = Fraction(text)
    except (ValueError, ZeroDivisionError) as exc:
        raise ValueError(f"Invalid disk budget: {value}") from exc
    if gib <= 0:
        raise ValueError("disk budget must be positive")
    byte_value = gib * 1024**3
    result = byte_value.numerator // byte_value.denominator
    if result < 1 or result > 2**63 - 1:
        raise ValueError("disk budget is outside the supported byte range")
    return result


class ImageFormat(StrEnum):
    JPEG = "jpeg"
    PNG = "png"


class OrientationOperation(StrEnum):
    IDENTITY = "identity"
    MIRROR_HORIZONTAL = "mirror_horizontal"
    ROTATE_180 = "rotate_180"
    MIRROR_VERTICAL = "mirror_vertical"
    TRANSPOSE = "transpose"
    ROTATE_90_CW = "rotate_90_cw"
    TRANSVERSE = "transverse"
    ROTATE_90_CCW = "rotate_90_ccw"


_SWAPS_AXES = {
    OrientationOperation.TRANSPOSE,
    OrientationOperation.ROTATE_90_CW,
    OrientationOperation.TRANSVERSE,
    OrientationOperation.ROTATE_90_CCW,
}


def photo_orientation_operation(value: int | None) -> OrientationOperation:
    mapping = {
        None: OrientationOperation.IDENTITY,
        1: OrientationOperation.IDENTITY,
        2: OrientationOperation.MIRROR_HORIZONTAL,
        3: OrientationOperation.ROTATE_180,
        4: OrientationOperation.MIRROR_VERTICAL,
        5: OrientationOperation.TRANSPOSE,
        6: OrientationOperation.ROTATE_90_CW,
        7: OrientationOperation.TRANSVERSE,
        8: OrientationOperation.ROTATE_90_CCW,
    }
    try:
        return mapping[value]
    except KeyError as exc:
        raise ValueError(f"Unsupported EXIF orientation: {value}") from exc


def video_orientation_operation(value: int | None) -> OrientationOperation:
    """FFprobe display-matrix degrees are CCW; apply that pixel rotation explicitly."""
    normalized = 0 if value is None else value % 360
    mapping = {
        0: OrientationOperation.IDENTITY,
        90: OrientationOperation.ROTATE_90_CCW,
        180: OrientationOperation.ROTATE_180,
        270: OrientationOperation.ROTATE_90_CW,
    }
    try:
        return mapping[normalized]
    except KeyError as exc:
        raise ValueError(
            f"M3 supports only right-angle video display rotation, received {value} degrees"
        ) from exc


class CandidateEncodingSettings(FrozenModel):
    image_format: ImageFormat = ImageFormat.JPEG
    jpeg_qscale: int | None = Field(default=2, ge=1, le=31, strict=True)
    jpeg_pixel_format: Literal["yuvj444p"] | None = "yuvj444p"
    png_compression_level: int | None = Field(default=6, ge=0, le=9, strict=True)

    @model_validator(mode="before")
    @classmethod
    def normalize_irrelevant_jpeg_setting(cls, value: Any) -> Any:
        if isinstance(value, dict) and value.get("image_format") in {
            ImageFormat.PNG,
            ImageFormat.PNG.value,
        }:
            return {
                **value,
                "jpeg_qscale": None,
                "jpeg_pixel_format": None,
            }
        if isinstance(value, dict) and value.get("image_format", ImageFormat.JPEG) in {
            ImageFormat.JPEG,
            ImageFormat.JPEG.value,
        }:
            return {**value, "png_compression_level": None}
        return value

    @model_validator(mode="after")
    def require_jpeg_quality(self) -> CandidateEncodingSettings:
        if self.image_format == ImageFormat.JPEG and (
            self.jpeg_qscale is None or self.jpeg_pixel_format is None
        ):
            raise ValueError("JPEG output requires jpeg_qscale and pixel format")
        if self.image_format == ImageFormat.PNG and self.png_compression_level is None:
            raise ValueError("PNG output requires a compression level")
        return self


class CandidatePoolSettings(FrozenModel):
    candidate_fps: RationalValue
    encoding: CandidateEncodingSettings
    orientation_policy: Literal["explicit_metadata_v1"] = "explicit_metadata_v1"
    sampling_policy: Literal["presentation_time_min_interval_v1"] = (
        "presentation_time_min_interval_v1"
    )

    @model_validator(mode="after")
    def positive_fps(self) -> CandidatePoolSettings:
        if self.candidate_fps.numerator <= 0:
            raise ValueError("candidate FPS must be positive")
        return self


class FixedFpsSettings(FrozenModel):
    target_fps: RationalValue
    selection_policy: Literal["nearest_unique_v1"] = "nearest_unique_v1"

    @model_validator(mode="after")
    def positive_fps(self) -> FixedFpsSettings:
        if self.target_fps.numerator <= 0:
            raise ValueError("target FPS must be positive")
        return self


def validate_fps_density(
    candidate: CandidatePoolSettings, selection: FixedFpsSettings
) -> None:
    if candidate.candidate_fps.as_fraction() < selection.target_fps.as_fraction():
        raise ValueError("candidate FPS must be greater than or equal to target FPS")


class CandidateResourceLimits(FrozenModel):
    max_candidates: int = Field(default=10_000, ge=1, le=MAX_VIEWS, strict=True)
    max_candidate_bytes: int = Field(default=20 * 1024**3, ge=1, strict=True)
    per_source_timeout_seconds: int = Field(default=3600, ge=1, le=86_400, strict=True)


class SourceCandidateEstimate(FrozenModel):
    source_id: UUID
    candidate_count: int = Field(ge=1, le=MAX_VIEWS, strict=True)
    candidate_bytes: int = Field(ge=1, strict=True)


class CandidateBudgetEstimate(FrozenModel):
    sources: tuple[SourceCandidateEstimate, ...]
    total_candidates: int = Field(ge=1, le=MAX_VIEWS, strict=True)
    candidate_bytes: int = Field(ge=1, strict=True)
    peak_workspace_bytes: int = Field(ge=1, strict=True)


def estimate_candidate_budget(
    sources: tuple[SourceOccurrence, ...],
    *,
    settings: CandidatePoolSettings,
    limits: CandidateResourceLimits,
) -> CandidateBudgetEstimate:
    """Conservatively bound retained pixels and small metadata before any decode."""

    if not sources:
        raise ValueError("At least one source is required")
    estimates: list[SourceCandidateEstimate] = []
    total_count = 0
    total_bytes = 0
    for source in sources:
        if source.probe.width <= 0 or source.probe.height <= 0:
            raise ValueError(f"Source {source.source_id} has invalid dimensions")
        if source.media_type == MediaType.PHOTO:
            count = 1
        else:
            if source.probe.duration is None:
                raise ValueError(
                    f"Video source {source.source_id} has no bounded duration; "
                    "M3 refuses unbounded decoding"
                )
            try:
                duration = Fraction(source.probe.duration)
            except (ValueError, ZeroDivisionError) as exc:
                raise ValueError(
                    f"Video source {source.source_id} has invalid duration "
                    f"{source.probe.duration!r}"
                ) from exc
            if duration <= 0:
                raise ValueError(
                    f"Video source {source.source_id} has non-positive duration"
                )
            sampled = duration * settings.candidate_fps.as_fraction()
            count = (sampled.numerator + sampled.denominator - 1) // sampled.denominator + 1
        if count > MAX_VIEWS:
            raise ValueError(
                f"Source {source.source_id} candidate estimate {count} exceeds "
                f"the hard contract bound {MAX_VIEWS}"
            )
        pixels = source.probe.width * source.probe.height
        if pixels > 2**63:
            raise ValueError(f"Source {source.source_id} dimensions exceed safe budgeting")
        # Eight bytes per source pixel plus container overhead is deliberately
        # conservative for both lossless PNG and high-quality JPEG.
        per_image = pixels * 8 + 64 * 1024
        source_bytes = count * per_image
        total_count += count
        total_bytes += source_bytes
        estimates.append(
            SourceCandidateEstimate(
                source_id=source.source_id,
                candidate_count=count,
                candidate_bytes=source_bytes,
            )
        )
        if total_count > limits.max_candidates:
            raise ValueError(
                f"Candidate estimate for source {source.source_id} raises total to "
                f"{total_count}, above max_candidates={limits.max_candidates}; "
                "lower candidate FPS or select fewer sources"
            )
        if total_bytes > limits.max_candidate_bytes:
            raise ValueError(
                f"Candidate disk estimate for source {source.source_id} raises total to "
                f"{total_bytes} bytes, above max_candidate_bytes="
                f"{limits.max_candidate_bytes}; lower candidate FPS or increase the budget"
            )
    metadata_and_manifest = total_count * 4096 + 4 * 1024 * 1024
    peak = total_bytes + metadata_and_manifest
    return CandidateBudgetEstimate(
        sources=tuple(estimates),
        total_candidates=total_count,
        candidate_bytes=total_bytes,
        peak_workspace_bytes=peak,
    )


class PixelTransform(FrozenModel):
    transform_schema_version: Literal[1] = 1
    source_width: int = Field(gt=0, strict=True)
    source_height: int = Field(gt=0, strict=True)
    orientation_operation: OrientationOperation
    output_width: int = Field(gt=0, strict=True)
    output_height: int = Field(gt=0, strict=True)
    crop: None = None
    resize: None = None

    @model_validator(mode="after")
    def dimensions_follow_orientation(self) -> PixelTransform:
        expected = (
            (self.source_height, self.source_width)
            if self.orientation_operation in _SWAPS_AXES
            else (self.source_width, self.source_height)
        )
        if (self.output_width, self.output_height) != expected:
            raise ValueError("output dimensions do not match the explicit orientation transform")
        return self


class FrameTimestamp(FrozenModel):
    pts: int = Field(strict=True)
    time_base: RationalValue

    @model_validator(mode="after")
    def positive_time_base(self) -> FrameTimestamp:
        if self.time_base.numerator <= 0:
            raise ValueError("frame time base must be positive")
        return self

    def seconds(self) -> Fraction:
        return self.pts * self.time_base.as_fraction()


class CandidateView(FrozenModel):
    view_id: UUID
    source_id: UUID
    source_revision: int = Field(ge=1, strict=True)
    source_content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_group_id: UUID
    camera_group_id: UUID
    media_type: MediaType
    selected_visual_stream_index: int = Field(ge=0, strict=True)
    frame_identity: str = Field(min_length=1, max_length=256)
    occurrence_index: int = Field(ge=0, strict=True)
    presentation_timestamp: FrameTimestamp | None
    image_path: str = Field(min_length=1, max_length=256)
    image_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    materialized_pixels: Literal[True] = True
    width: int = Field(gt=0, strict=True)
    height: int = Field(gt=0, strict=True)
    transform: PixelTransform
    display_filename: str | None = Field(default=None, max_length=1024)

    @field_validator("image_path")
    @classmethod
    def safe_image_path(cls, value: str) -> str:
        windows = PureWindowsPath(value)
        parts = value.split("/")
        if (
            windows.drive
            or windows.root
            or PurePosixPath(value).is_absolute()
            or "\\" in value
            or ":" in value
            or any(part in {"", ".", ".."} for part in parts)
            or len(parts) != 2
            or parts[0] != "images"
        ):
            raise ValueError("candidate image path must be a safe images/<view-id> path")
        return value

    @model_validator(mode="after")
    def media_timing_and_pixels(self) -> CandidateView:
        if self.media_type == MediaType.PHOTO and self.presentation_timestamp is not None:
            raise ValueError("photo candidates must not have timestamps")
        if self.media_type == MediaType.VIDEO and self.presentation_timestamp is None:
            raise ValueError("video candidates require an actual presentation timestamp")
        if self.width != self.transform.output_width or self.height != self.transform.output_height:
            raise ValueError("candidate dimensions differ from its transform output")
        expected_suffixes = {".jpg", ".png"}
        suffix = PurePosixPath(self.image_path).suffix.lower()
        if suffix not in expected_suffixes:
            raise ValueError("candidate image path must use .jpg or .png")
        if PurePosixPath(self.image_path).stem != str(self.view_id):
            raise ValueError("candidate image filename must equal its stable view ID")
        return self


class CandidateViewSet(FrozenModel):
    contract_version: Literal[1] = 1
    method_id: Literal["view_preparation.ffmpeg_fixed_pool"] = CANDIDATE_METHOD_ID
    method_version: Literal[1] = CANDIDATE_METHOD_VERSION
    adapter_id: Literal["splatforge.ffmpeg"] = FFMPEG_ADAPTER_ID
    adapter_version: Literal[1, 2] = FFMPEG_ADAPTER_VERSION
    backend: ExecutableIdentity
    settings: CandidatePoolSettings
    views: Annotated[tuple[CandidateView, ...], Field(min_length=1, max_length=MAX_VIEWS)]

    @model_validator(mode="after")
    def unique_and_consistent(self) -> CandidateViewSet:
        ids = [view.view_id for view in self.views]
        if len(ids) != len(set(ids)):
            raise ValueError("candidate set contains duplicate view IDs")
        paths = [view.image_path for view in self.views]
        if len(paths) != len(set(paths)):
            raise ValueError("candidate set contains duplicate image paths")
        expected_suffix = (
            ".jpg"
            if self.settings.encoding.image_format == ImageFormat.JPEG
            else ".png"
        )
        if any(PurePosixPath(path).suffix.lower() != expected_suffix for path in paths):
            raise ValueError("candidate image extension differs from the configured encoding")
        return self


class SelectionReason(StrEnum):
    FIXED_FPS = "fixed_fps"
    PHOTO_SINGLETON = "photo_singleton"


class SelectedView(FrozenModel):
    view_id: UUID
    source_id: UUID
    source_revision: int = Field(ge=1, strict=True)
    media_type: MediaType
    selection_order: int = Field(ge=0, strict=True)
    target_slot_index: int | None = Field(default=None, ge=0, strict=True)
    target_presentation_time: RationalValue | None = None
    actual_presentation_time: RationalValue | None = None
    time_error: RationalValue | None = None
    reason: SelectionReason

    @model_validator(mode="after")
    def timing_matches_reason(self) -> SelectedView:
        timed = (
            self.target_slot_index,
            self.target_presentation_time,
            self.actual_presentation_time,
            self.time_error,
        )
        if self.reason == SelectionReason.PHOTO_SINGLETON and any(
            item is not None for item in timed
        ):
            raise ValueError("photo selections must not invent timeline metadata")
        if (
            self.reason == SelectionReason.PHOTO_SINGLETON
            and self.media_type != MediaType.PHOTO
        ):
            raise ValueError("photo_singleton reason requires photo media")
        if self.reason == SelectionReason.FIXED_FPS and any(item is None for item in timed):
            raise ValueError("fixed-FPS selections require complete timing metadata")
        if self.reason == SelectionReason.FIXED_FPS:
            if self.media_type != MediaType.VIDEO:
                raise ValueError("fixed_fps reason requires video media")
            assert self.target_presentation_time is not None
            assert self.actual_presentation_time is not None
            assert self.time_error is not None
            expected_error = (
                self.actual_presentation_time.as_fraction()
                - self.target_presentation_time.as_fraction()
            )
            if self.time_error.as_fraction() != expected_error:
                raise ValueError("fixed-FPS time error does not equal actual minus target")
        return self


class UnsatisfiedSlot(FrozenModel):
    source_id: UUID
    source_revision: int = Field(ge=1, strict=True)
    target_slot_index: int = Field(ge=0, strict=True)
    target_presentation_time: RationalValue
    reason: Literal["nearest_candidate_already_selected"] = "nearest_candidate_already_selected"


class SourceSelectionCount(FrozenModel):
    source_id: UUID
    source_revision: int = Field(ge=1, strict=True)
    candidate_count: int = Field(ge=0, strict=True)
    selected_count: int = Field(ge=0, strict=True)
    unsatisfied_slot_count: int = Field(ge=0, strict=True)


class SelectedViewSet(FrozenModel):
    contract_version: Literal[1] = 1
    candidate_artifact_id: UUID
    candidate_semantic_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    selection_method_id: Literal["frame_selection.fixed_fps"] = SELECTION_METHOD_ID
    selection_method_version: Literal[1] = SELECTION_METHOD_VERSION
    settings: FixedFpsSettings
    selected_views: Annotated[tuple[SelectedView, ...], Field(max_length=MAX_VIEWS)]
    unsatisfied_slots: Annotated[tuple[UnsatisfiedSlot, ...], Field(max_length=MAX_VIEWS)] = ()
    counts_per_source: Annotated[
        tuple[SourceSelectionCount, ...], Field(max_length=MAX_VIEWS)
    ]
    total_selected_count: int = Field(ge=0, le=MAX_VIEWS, strict=True)

    @model_validator(mode="after")
    def unique_and_counted(self) -> SelectedViewSet:
        ids = [view.view_id for view in self.selected_views]
        if len(ids) != len(set(ids)):
            raise ValueError("selected set contains a duplicate selected view")
        orders = [view.selection_order for view in self.selected_views]
        if orders != list(range(len(orders))):
            raise ValueError("selected view order must be contiguous and deterministic")
        if self.total_selected_count != len(self.selected_views):
            raise ValueError("selected total count is incorrect")
        if sum(item.selected_count for item in self.counts_per_source) != len(ids):
            raise ValueError("per-source selected counts are incorrect")
        keys = [(item.source_id, item.source_revision) for item in self.counts_per_source]
        if len(keys) != len(set(keys)):
            raise ValueError("selected set contains duplicate source statistics")
        unsatisfied_keys = [
            (item.source_id, item.source_revision, item.target_slot_index)
            for item in self.unsatisfied_slots
        ]
        if len(unsatisfied_keys) != len(set(unsatisfied_keys)):
            raise ValueError("selected set contains duplicate unsatisfied slots")
        if sum(item.unsatisfied_slot_count for item in self.counts_per_source) != len(
            self.unsatisfied_slots
        ):
            raise ValueError("per-source unsatisfied-slot counts are incorrect")
        recorded_selected = Counter(
            (view.source_id, view.source_revision) for view in self.selected_views
        )
        recorded_unsatisfied = Counter(
            (slot.source_id, slot.source_revision) for slot in self.unsatisfied_slots
        )
        for item in self.counts_per_source:
            key = (item.source_id, item.source_revision)
            if item.selected_count != recorded_selected[key]:
                raise ValueError("per-source selected count differs from selected records")
            if item.unsatisfied_slot_count != recorded_unsatisfied[key]:
                raise ValueError(
                    "per-source unsatisfied count differs from unsatisfied records"
                )
        selected_slots = {
            (view.source_id, view.source_revision, view.target_slot_index)
            for view in self.selected_views
            if view.target_slot_index is not None
        }
        if selected_slots.intersection(unsatisfied_keys):
            raise ValueError("a target slot cannot be both selected and unsatisfied")
        return self


def deterministic_photo_view_id(source: SourceOccurrence) -> UUID:
    return _stable_view_id(
        {
            "identity_version": 1,
            "media_type": MediaType.PHOTO.value,
            "source_id": str(source.source_id),
            "source_revision": source.source_revision,
            "visual_stream_index": source.probe.selected_visual_stream_index,
            "frame_identity": "photo_singleton",
            "occurrence_index": 0,
        }
    )


def deterministic_video_view_id(
    source: SourceOccurrence,
    *,
    pts: int,
    time_base: RationalValue,
    occurrence_index: int,
) -> UUID:
    return _stable_view_id(
        {
            "identity_version": 1,
            "media_type": MediaType.VIDEO.value,
            "source_id": str(source.source_id),
            "source_revision": source.source_revision,
            "visual_stream_index": source.probe.selected_visual_stream_index,
            "pts": pts,
            "time_base": time_base.model_dump(mode="json"),
            "occurrence_index": occurrence_index,
        }
    )


def _stable_view_id(evidence: dict[str, object]) -> UUID:
    return uuid5(_VIEW_NAMESPACE, canonical_json_bytes(evidence).decode("utf-8"))


def candidate_semantic_digest(candidate: CandidateViewSet) -> str:
    views = []
    for view in candidate.views:
        item = view.model_dump(mode="json")
        item.pop("display_filename", None)
        views.append(item)
    evidence = {
        "semantic_schema_version": 1,
        "artifact_type": CANDIDATE_ARTIFACT_TYPE,
        "contract_version": candidate.contract_version,
        "materialization": candidate.settings.model_dump(mode="json"),
        "views": views,
    }
    return sha256_bytes(canonical_json_bytes(evidence))


def selected_semantic_digest(selected: SelectedViewSet) -> str:
    evidence = selected.model_dump(mode="json")
    evidence.pop("candidate_artifact_id", None)
    return sha256_bytes(canonical_json_bytes(evidence))


def candidate_recipe_key(
    *,
    sources: tuple[SourceOccurrence, ...],
    settings: CandidatePoolSettings,
    backend: ExecutableIdentity,
) -> str:
    source_records = []
    for source in sorted(sources, key=lambda item: (str(item.source_id), item.source_revision)):
        source_records.append(
            {
                "source_id": str(source.source_id),
                "source_revision": source.source_revision,
                "content_sha256": source.content_sha256,
                "source_group_id": str(source.source_group_id),
                "camera_group_id": str(source.camera_group_id),
                "media_type": source.media_type.value,
                "selected_visual_stream_index": source.probe.selected_visual_stream_index,
                "width": source.probe.width,
                "height": source.probe.height,
                "orientation": source.probe.orientation,
                "time_base": source.probe.time_base,
                "duration": source.probe.duration,
                "rotation_degrees": source.probe.rotation_degrees,
            }
        )
    evidence = {
        "fingerprint_schema_version": FINGERPRINT_SCHEMA_VERSION,
        "stage_contract_version": VIEW_ARTIFACT_CONTRACT_VERSION,
        "method_id": CANDIDATE_METHOD_ID,
        "method_version": CANDIDATE_METHOD_VERSION,
        "settings_schema_version": 1,
        "resolved_settings": settings.model_dump(mode="json"),
        "adapter_id": FFMPEG_ADAPTER_ID,
        "adapter_version": FFMPEG_ADAPTER_VERSION,
        "backend_identity": backend.model_dump(mode="json"),
        "selected_sources": source_records,
    }
    return sha256_bytes(canonical_json_bytes(evidence))


def selection_recipe_key(
    *, candidate: CandidateViewSet, candidate_digest: str, settings: FixedFpsSettings
) -> str:
    if candidate_digest != candidate_semantic_digest(candidate):
        raise ValueError("candidate digest does not match CandidateViewSet content")
    evidence = {
        "fingerprint_schema_version": FINGERPRINT_SCHEMA_VERSION,
        "stage_contract_version": VIEW_ARTIFACT_CONTRACT_VERSION,
        "method_id": SELECTION_METHOD_ID,
        "method_version": SELECTION_METHOD_VERSION,
        "settings_schema_version": 1,
        # Target FPS is retained even for a photo-only set because contract 1 stores
        # the resolved setting in SelectedViewSet metadata. Omitting it would let one
        # recipe key identify distinct semantic artifacts.
        "resolved_settings": settings.model_dump(mode="json"),
        "consumed_candidate": {
            "artifact_type": CANDIDATE_ARTIFACT_TYPE,
            "contract_version": candidate.contract_version,
            "semantic_digest": candidate_digest,
        },
    }
    return sha256_bytes(canonical_json_bytes(evidence))


def select_fixed_fps(
    candidate: CandidateViewSet,
    *,
    candidate_artifact: ArtifactHandle,
    settings: FixedFpsSettings,
) -> SelectedViewSet:
    """Select photos once and video candidates nearest independent per-source grids."""

    if candidate_artifact.artifact_type != CANDIDATE_ARTIFACT_TYPE:
        raise ValueError("fixed-FPS selection requires a CandidateViewSet artifact")
    if candidate_artifact.semantic_digest != candidate_semantic_digest(candidate):
        raise ValueError("candidate handle semantic digest does not match candidate content")
    grouped: dict[tuple[str, int], list[CandidateView]] = {}
    for view in candidate.views:
        grouped.setdefault((str(view.source_id), view.source_revision), []).append(view)

    provisional: list[SelectedView] = []
    unsatisfied: list[UnsatisfiedSlot] = []
    counts: list[SourceSelectionCount] = []
    target_step = Fraction(1, 1) / settings.target_fps.as_fraction()

    for source_key in sorted(grouped):
        source_views = grouped[source_key]
        photos = sorted(
            (view for view in source_views if view.media_type == MediaType.PHOTO),
            key=lambda view: str(view.view_id),
        )
        videos = sorted(
            (view for view in source_views if view.media_type == MediaType.VIDEO),
            key=lambda view: (
                view.presentation_timestamp.seconds() if view.presentation_timestamp else 0,
                str(view.view_id),
            ),
        )
        source_selected = 0
        source_unsatisfied = 0
        for photo in photos:
            provisional.append(
                SelectedView(
                    view_id=photo.view_id,
                    source_id=photo.source_id,
                    source_revision=photo.source_revision,
                    media_type=photo.media_type,
                    selection_order=len(provisional),
                    reason=SelectionReason.PHOTO_SINGLETON,
                )
            )
            source_selected += 1

        if videos:
            # Only the first stable ID at a timestamp can ever win. Collapsing
            # equal times prevents a duplicate from obstructing the forward sweep.
            timeline: list[tuple[Fraction, CandidateView]] = []
            for view in videos:
                assert view.presentation_timestamp is not None
                actual = view.presentation_timestamp.seconds()
                if not timeline or actual != timeline[-1][0]:
                    timeline.append((actual, view))
            first_time, last_time = timeline[0][0], timeline[-1][0]
            slot_count = math.floor((last_time - first_time) / target_step) + 1
            bound_timeline_expansion(
                source_key[0], slot_count,
                candidate_count=len(timeline), unsatisfied_count=len(unsatisfied),
            )
            used: set[UUID] = set()
            nearest_indices = _nearest_timeline_indices(
                [item[0] for item in timeline],
                (first_time + index * target_step for index in range(slot_count)),
            )
            for slot_index, nearest_index in enumerate(nearest_indices):
                target = first_time + slot_index * target_step
                actual, nearest = timeline[nearest_index]
                if nearest.view_id in used:
                    unsatisfied.append(
                        UnsatisfiedSlot(
                            source_id=nearest.source_id,
                            source_revision=nearest.source_revision,
                            target_slot_index=slot_index,
                            target_presentation_time=RationalValue.from_fraction(target),
                        )
                    )
                    source_unsatisfied += 1
                    continue
                used.add(nearest.view_id)
                provisional.append(
                    SelectedView(
                        view_id=nearest.view_id,
                        source_id=nearest.source_id,
                        source_revision=nearest.source_revision,
                        media_type=nearest.media_type,
                        selection_order=len(provisional),
                        target_slot_index=slot_index,
                        target_presentation_time=RationalValue.from_fraction(target),
                        actual_presentation_time=RationalValue.from_fraction(actual),
                        time_error=RationalValue.from_fraction(actual - target),
                        reason=SelectionReason.FIXED_FPS,
                    )
                )
                source_selected += 1
        first = source_views[0]
        counts.append(
            SourceSelectionCount(
                source_id=first.source_id,
                source_revision=first.source_revision,
                candidate_count=len(source_views),
                selected_count=source_selected,
                unsatisfied_slot_count=source_unsatisfied,
            )
        )

    selected = SelectedViewSet(
        candidate_artifact_id=candidate_artifact.artifact_id,
        candidate_semantic_digest=candidate_artifact.semantic_digest,
        settings=settings,
        selected_views=tuple(provisional),
        unsatisfied_slots=tuple(unsatisfied),
        counts_per_source=tuple(counts),
        total_selected_count=len(provisional),
    )
    validate_selected_against_candidate(selected, candidate)
    return selected


def bound_timeline_expansion(
    source_id: str, count: int, *, candidate_count: int, unsatisfied_count: int,
) -> None:
    """Each expanded slot must consume a candidate or remaining unsatisfied capacity."""
    bound = candidate_count + MAX_VIEWS - unsatisfied_count
    if count > bound:
        raise ValueError(
            f"Source {source_id} computed slots/intervals={count} exceeds expansion bound={bound}"
        )


def _nearest_timeline_indices(
    times: Sequence[Fraction], targets: Iterator[Fraction]
) -> Iterator[int]:
    """Sweep distinct ordered times in O(N + K); exact midpoint ties stay earlier."""
    cursor = 0
    for target in targets:
        while cursor + 1 < len(times) and 2 * target > times[cursor] + times[cursor + 1]:
            cursor += 1
        yield cursor


def validate_selected_against_candidate(
    selected: SelectedViewSet, candidate: CandidateViewSet
) -> None:
    if selected.candidate_semantic_digest != candidate_semantic_digest(candidate):
        raise ValueError("selected set candidate semantic digest does not match content")
    candidates = {view.view_id: view for view in candidate.views}
    for view in selected.selected_views:
        candidate_view = candidates.get(view.view_id)
        if candidate_view is None:
            raise ValueError(f"selected view {view.view_id} is absent from the candidate set")
        if (
            view.source_id != candidate_view.source_id
            or view.source_revision != candidate_view.source_revision
            or view.media_type != candidate_view.media_type
        ):
            raise ValueError("selected view source identity differs from its candidate")
        if view.media_type == MediaType.VIDEO:
            assert candidate_view.presentation_timestamp is not None
            if (
                view.actual_presentation_time is None
                or view.actual_presentation_time.as_fraction()
                != candidate_view.presentation_timestamp.seconds()
            ):
                raise ValueError(
                    "selected actual presentation time differs from its candidate"
                )
    expected_counts = Counter((view.source_id, view.source_revision) for view in candidate.views)
    recorded_counts = {
        (item.source_id, item.source_revision): item.candidate_count
        for item in selected.counts_per_source
    }
    if dict(expected_counts) != recorded_counts:
        raise ValueError("selected per-source candidate counts do not match CandidateViewSet")
    candidate_sources = set(expected_counts)
    if any(
        (slot.source_id, slot.source_revision) not in candidate_sources
        for slot in selected.unsatisfied_slots
    ):
        raise ValueError("unsatisfied slot source is absent from CandidateViewSet")
