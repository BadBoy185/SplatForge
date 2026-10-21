"""M4 quality measurements and sharpest-per-interval selection contracts."""

from __future__ import annotations

import math
from collections.abc import Callable
from enum import StrEnum
from fractions import Fraction
from typing import TYPE_CHECKING, Annotated, Literal
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from splatforge.core.media import MediaType
from splatforge.core.views import (
    CANDIDATE_ARTIFACT_TYPE,
    FINGERPRINT_SCHEMA_VERSION,
    MAX_EXACT_COMPONENT,
    MAX_VIEWS,
    SELECTED_ARTIFACT_TYPE,
    VIEW_ARTIFACT_CONTRACT_VERSION,
    CandidatePoolSettings,
    CandidateView,
    CandidateViewSet,
    FrozenModel,
    RationalValue,
    bound_timeline_expansion,
    candidate_semantic_digest,
    canonical_json_bytes,
    sha256_bytes,
)

if TYPE_CHECKING:
    from splatforge.core.execution import ArtifactHandle

QUALITY_ARTIFACT_TYPE = "views.quality_report"
QUALITY_ARTIFACT_CONTRACT_VERSION = 1
QUALITY_METHOD_ID = "quality_assessment.pillow_edge_dhash"
QUALITY_METHOD_VERSION = 1
QUALITY_ADAPTER_ID = "splatforge.pillow_quality"
QUALITY_ADAPTER_VERSION = 1
SHARPNESS_METHOD_ID = "sharpness.edge_variance_8bit_v1"
SHARPNESS_METHOD_VERSION = 1
DUPLICATE_METHOD_ID = "duplicate.dhash64_v1"
DUPLICATE_METHOD_VERSION = 1
SHARPEST_METHOD_ID = "frame_selection.sharpest_interval"
SHARPEST_METHOD_VERSION = 1


class NonNegativeRational(FrozenModel):
    """Canonical non-negative exact rational for implementation-defined metrics."""

    numerator: int = Field(ge=0, le=MAX_EXACT_COMPONENT, strict=True)
    denominator: int = Field(gt=0, le=MAX_EXACT_COMPONENT, strict=True)

    @model_validator(mode="after")
    def canonical(self) -> NonNegativeRational:
        if math.gcd(self.numerator, self.denominator) != 1:
            raise ValueError("metric rational must be in canonical lowest terms")
        return self

    @classmethod
    def from_fraction(cls, value: Fraction) -> NonNegativeRational:
        if value < 0:
            raise ValueError("metric rational must be non-negative")
        return cls(numerator=value.numerator, denominator=value.denominator)

    def as_fraction(self) -> Fraction:
        return Fraction(self.numerator, self.denominator)


def parse_non_negative_rational(value: str) -> NonNegativeRational:
    text = value.strip()
    if not text:
        raise ValueError("metric value must not be empty")
    if text.lower() in {"nan", "+nan", "-nan", "inf", "+inf", "-inf", "infinity"}:
        raise ValueError("metric value must be finite")
    try:
        parsed = Fraction(text)
    except (ValueError, ZeroDivisionError) as exc:
        raise ValueError(f"Invalid exact metric value: {value}") from exc
    if parsed < 0:
        raise ValueError("metric value must be non-negative")
    if parsed.numerator > MAX_EXACT_COMPONENT or parsed.denominator > MAX_EXACT_COMPONENT:
        raise ValueError("metric numerator or denominator is unreasonable")
    return NonNegativeRational.from_fraction(parsed)


class QualityAnalysisSettings(FrozenModel):
    quality_max_side: int = Field(default=1024, ge=64, le=4096, strict=True)
    preprocessing_policy: Literal["grayscale8_bounded_v1"] = "grayscale8_bounded_v1"
    analysis_resampling: Literal["lanczos"] = "lanczos"
    dhash_resampling: Literal["bilinear"] = "bilinear"


class QualityBackendIdentity(FrozenModel):
    adapter_id: str = Field(default=QUALITY_ADAPTER_ID, min_length=1, max_length=128)
    adapter_version: int = Field(default=QUALITY_ADAPTER_VERSION, ge=1, strict=True)
    quality_method_id: str = Field(default=QUALITY_METHOD_ID, min_length=1, max_length=128)
    quality_method_version: int = Field(default=QUALITY_METHOD_VERSION, ge=1, strict=True)
    pillow_version: str = Field(min_length=1, max_length=64)
    python_version: str = Field(min_length=1, max_length=64)


class MeasurementAvailability(StrEnum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


class MeasurementUnavailableReason(StrEnum):
    IMAGE_TOO_SMALL = "image_too_small"
    DECODE_FAILED = "decode_failed"


class SharpnessMeasurement(FrozenModel):
    availability: MeasurementAvailability
    method_id: Literal["sharpness.edge_variance_8bit_v1"] = SHARPNESS_METHOD_ID
    method_version: Literal[1] = SHARPNESS_METHOD_VERSION
    score: NonNegativeRational | None = None
    units: Literal["8bit_edge_response_variance"] = "8bit_edge_response_variance"
    unavailable_reason: MeasurementUnavailableReason | None = None

    @model_validator(mode="after")
    def availability_matches_payload(self) -> SharpnessMeasurement:
        if self.availability == MeasurementAvailability.AVAILABLE:
            if self.score is None or self.unavailable_reason is not None:
                raise ValueError("available sharpness requires a score and no reason")
        elif self.score is not None or self.unavailable_reason is None:
            raise ValueError("unavailable sharpness requires a reason and no score")
        return self


class DuplicateMeasurement(FrozenModel):
    availability: MeasurementAvailability
    method_id: Literal["duplicate.dhash64_v1"] = DUPLICATE_METHOD_ID
    method_version: Literal[1] = DUPLICATE_METHOD_VERSION
    dhash64: str | None = None
    unavailable_reason: MeasurementUnavailableReason | None = None

    @field_validator("dhash64")
    @classmethod
    def exact_lowercase_hex(cls, value: str | None) -> str | None:
        if value is not None and (
            len(value) != 16 or any(character not in "0123456789abcdef" for character in value)
        ):
            raise ValueError("dHash64 must be exactly 16 lowercase hexadecimal characters")
        return value

    @model_validator(mode="after")
    def availability_matches_payload(self) -> DuplicateMeasurement:
        if self.availability == MeasurementAvailability.AVAILABLE:
            if self.dhash64 is None or self.unavailable_reason is not None:
                raise ValueError("available duplicate measurement requires a hash and no reason")
        elif self.dhash64 is not None or self.unavailable_reason is None:
            raise ValueError("unavailable duplicate measurement requires a reason and no hash")
        return self


class ViewQualityMeasurement(FrozenModel):
    view_id: UUID
    candidate_image_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    sharpness: SharpnessMeasurement
    duplicate: DuplicateMeasurement


class QualityReport(FrozenModel):
    contract_version: Literal[1] = QUALITY_ARTIFACT_CONTRACT_VERSION
    candidate_artifact_id: UUID
    candidate_semantic_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    quality_method_id: Literal["quality_assessment.pillow_edge_dhash"] = QUALITY_METHOD_ID
    quality_method_version: Literal[1] = QUALITY_METHOD_VERSION
    adapter_id: Literal["splatforge.pillow_quality"] = QUALITY_ADAPTER_ID
    adapter_version: Literal[1] = QUALITY_ADAPTER_VERSION
    pillow_version: str = Field(min_length=1, max_length=64)
    python_version: str = Field(min_length=1, max_length=64)
    settings: QualityAnalysisSettings
    measurements: Annotated[
        tuple[ViewQualityMeasurement, ...], Field(min_length=1, max_length=MAX_VIEWS)
    ]

    @model_validator(mode="after")
    def unique_measurements(self) -> QualityReport:
        identifiers = [item.view_id for item in self.measurements]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("quality report contains duplicate view IDs")
        return self


class SharpestIntervalSettings(FrozenModel):
    target_fps: RationalValue
    min_sharpness: NonNegativeRational | None = None
    reject_duplicates: bool = True
    duplicate_hamming_threshold: int = Field(default=4, ge=0, le=64, strict=True)
    duplicate_lookback: int = Field(default=8, ge=1, le=64, strict=True)
    interval_tie_policy: Literal["anchored_half_open_score_time_id_v1"] = (
        "anchored_half_open_score_time_id_v1"
    )

    @model_validator(mode="after")
    def positive_fps(self) -> SharpestIntervalSettings:
        if self.target_fps.numerator <= 0:
            raise ValueError("target FPS must be positive")
        return self


class SharpestDecisionReason(StrEnum):
    SHARPEST_IN_INTERVAL = "sharpest_in_interval"
    PHOTO_QUALITY_PASS = "photo_quality_pass"
    QUALITY_UNAVAILABLE = "quality_unavailable"
    BELOW_SHARPNESS_THRESHOLD = "below_sharpness_threshold"
    DUPLICATE_OF_RECENT_SELECTION = "duplicate_of_recent_selection"
    LOWER_SHARPNESS_IN_INTERVAL = "lower_sharpness_in_interval"


class UnsatisfiedIntervalReason(StrEnum):
    NO_CANDIDATE_IN_INTERVAL = "no_candidate_in_interval"
    ALL_CANDIDATES_REJECTED = "all_candidates_rejected"


_SELECTED_REASONS = {
    SharpestDecisionReason.SHARPEST_IN_INTERVAL,
    SharpestDecisionReason.PHOTO_QUALITY_PASS,
}


class SharpestSelectedView(FrozenModel):
    view_id: UUID
    source_id: UUID
    source_revision: int = Field(ge=1, strict=True)
    media_type: MediaType
    selection_order: int = Field(ge=0, strict=True)
    reason: SharpestDecisionReason
    interval_index: int | None = Field(default=None, ge=0, strict=True)
    interval_start: RationalValue | None = None
    interval_end: RationalValue | None = None

    @model_validator(mode="after")
    def selected_reason_and_timing(self) -> SharpestSelectedView:
        if self.reason not in _SELECTED_REASONS:
            raise ValueError("selected view requires a selected decision reason")
        timing = (self.interval_index, self.interval_start, self.interval_end)
        if self.media_type == MediaType.PHOTO:
            if self.reason != SharpestDecisionReason.PHOTO_QUALITY_PASS or any(
                value is not None for value in timing
            ):
                raise ValueError("photo selection must not invent interval metadata")
        elif self.reason != SharpestDecisionReason.SHARPEST_IN_INTERVAL or any(
            value is None for value in timing
        ):
            raise ValueError("video selection requires complete interval metadata")
        return self


class SharpestDecision(FrozenModel):
    view_id: UUID
    source_id: UUID
    source_revision: int = Field(ge=1, strict=True)
    media_type: MediaType
    reason: SharpestDecisionReason
    interval_index: int | None = Field(default=None, ge=0, strict=True)
    sharpness_score: NonNegativeRational | None = None
    sharpness_threshold: NonNegativeRational | None = None
    duplicate_of_view_id: UUID | None = None
    hamming_distance: int | None = Field(default=None, ge=0, le=64, strict=True)
    duplicate_threshold: int | None = Field(default=None, ge=0, le=64, strict=True)
    selected_winner_view_id: UUID | None = None

    @model_validator(mode="after")
    def reason_payload_is_consistent(self) -> SharpestDecision:
        if self.media_type == MediaType.PHOTO and self.interval_index is not None:
            raise ValueError("photo decisions must not invent interval metadata")
        if self.media_type == MediaType.VIDEO and self.interval_index is None:
            raise ValueError("video decisions require an interval index")
        if self.reason == SharpestDecisionReason.BELOW_SHARPNESS_THRESHOLD:
            if self.sharpness_score is None or self.sharpness_threshold is None:
                raise ValueError("threshold rejection requires score and threshold")
            if self.sharpness_score.as_fraction() >= self.sharpness_threshold.as_fraction():
                raise ValueError("threshold rejection score must be below the threshold")
        elif self.sharpness_threshold is not None:
            raise ValueError("only threshold rejection records a sharpness threshold")
        if self.reason == SharpestDecisionReason.DUPLICATE_OF_RECENT_SELECTION:
            if (
                self.duplicate_of_view_id is None
                or self.hamming_distance is None
                or self.duplicate_threshold is None
                or self.hamming_distance > self.duplicate_threshold
            ):
                raise ValueError("duplicate rejection requires an inclusive matching record")
        elif any(
            value is not None
            for value in (
                self.duplicate_of_view_id,
                self.hamming_distance,
                self.duplicate_threshold,
            )
        ):
            raise ValueError("only duplicate rejection records duplicate match metadata")
        if self.reason == SharpestDecisionReason.LOWER_SHARPNESS_IN_INTERVAL:
            if self.selected_winner_view_id is None:
                raise ValueError("lower-sharpness rejection requires the selected winner")
        elif self.selected_winner_view_id is not None:
            raise ValueError("only lower-sharpness rejection records the selected winner")
        if self.reason in _SELECTED_REASONS and self.sharpness_score is None:
            raise ValueError("selected quality decisions require a sharpness score")
        return self


class UnsatisfiedInterval(FrozenModel):
    source_id: UUID
    source_revision: int = Field(ge=1, strict=True)
    interval_index: int = Field(ge=0, strict=True)
    interval_start: RationalValue
    interval_end: RationalValue
    candidate_count: int = Field(ge=0, le=MAX_VIEWS, strict=True)
    reason: UnsatisfiedIntervalReason

    @model_validator(mode="after")
    def reason_matches_count(self) -> UnsatisfiedInterval:
        if (
            self.reason == UnsatisfiedIntervalReason.NO_CANDIDATE_IN_INTERVAL
            and self.candidate_count != 0
        ):
            raise ValueError("no-candidate interval must have zero candidates")
        if (
            self.reason == UnsatisfiedIntervalReason.ALL_CANDIDATES_REJECTED
            and self.candidate_count == 0
        ):
            raise ValueError("all-rejected interval must have candidates")
        if self.interval_end.as_fraction() <= self.interval_start.as_fraction():
            raise ValueError("interval end must be after its start")
        return self


class SharpestSourceCount(FrozenModel):
    source_id: UUID
    source_revision: int = Field(ge=1, strict=True)
    candidate_count: int = Field(ge=0, le=MAX_VIEWS, strict=True)
    selected_count: int = Field(ge=0, le=MAX_VIEWS, strict=True)
    rejected_count: int = Field(ge=0, le=MAX_VIEWS, strict=True)
    unsatisfied_interval_count: int = Field(ge=0, le=MAX_VIEWS, strict=True)

    @model_validator(mode="after")
    def candidates_are_partitioned(self) -> SharpestSourceCount:
        if self.selected_count + self.rejected_count != self.candidate_count:
            raise ValueError("source selected and rejected counts must partition candidates")
        return self


class SharpestSelectedViewSet(FrozenModel):
    contract_version: Literal[1] = VIEW_ARTIFACT_CONTRACT_VERSION
    candidate_artifact_id: UUID
    candidate_semantic_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    quality_artifact_id: UUID
    quality_semantic_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    selection_method_id: Literal["frame_selection.sharpest_interval"] = SHARPEST_METHOD_ID
    selection_method_version: Literal[1] = SHARPEST_METHOD_VERSION
    settings: SharpestIntervalSettings
    selected_views: Annotated[tuple[SharpestSelectedView, ...], Field(max_length=MAX_VIEWS)]
    decisions: Annotated[tuple[SharpestDecision, ...], Field(min_length=1, max_length=MAX_VIEWS)]
    unsatisfied_intervals: Annotated[
        tuple[UnsatisfiedInterval, ...], Field(max_length=MAX_VIEWS)
    ] = ()
    counts_per_source: Annotated[
        tuple[SharpestSourceCount, ...], Field(min_length=1, max_length=MAX_VIEWS)
    ]
    total_candidate_count: int = Field(ge=1, le=MAX_VIEWS, strict=True)
    total_selected_count: int = Field(ge=0, le=MAX_VIEWS, strict=True)
    total_rejected_count: int = Field(ge=0, le=MAX_VIEWS, strict=True)

    @model_validator(mode="after")
    def unique_and_counted(self) -> SharpestSelectedViewSet:
        selected_ids = [item.view_id for item in self.selected_views]
        if len(selected_ids) != len(set(selected_ids)):
            raise ValueError("sharpest selected set contains duplicate selected views")
        if [item.selection_order for item in self.selected_views] != list(
            range(len(self.selected_views))
        ):
            raise ValueError("sharpest selected order must be contiguous")
        decision_ids = [item.view_id for item in self.decisions]
        if len(decision_ids) != len(set(decision_ids)):
            raise ValueError("sharpest selected set contains duplicate decisions")
        decision_selected = {
            item.view_id for item in self.decisions if item.reason in _SELECTED_REASONS
        }
        if decision_selected != set(selected_ids):
            raise ValueError("selected views and selected decisions disagree")
        if self.total_candidate_count != len(self.decisions):
            raise ValueError("total candidate count differs from decisions")
        if self.total_selected_count != len(self.selected_views):
            raise ValueError("total selected count is incorrect")
        if self.total_rejected_count != len(self.decisions) - len(self.selected_views):
            raise ValueError("total rejected count is incorrect")
        source_keys = [(item.source_id, item.source_revision) for item in self.counts_per_source]
        if len(source_keys) != len(set(source_keys)):
            raise ValueError("sharpest selected set contains duplicate source counts")
        if sum(item.candidate_count for item in self.counts_per_source) != len(self.decisions):
            raise ValueError("per-source candidate counts are incorrect")
        if sum(item.selected_count for item in self.counts_per_source) != len(self.selected_views):
            raise ValueError("per-source selected counts are incorrect")
        if sum(item.rejected_count for item in self.counts_per_source) != (
            len(self.decisions) - len(self.selected_views)
        ):
            raise ValueError("per-source rejected counts are incorrect")
        if sum(item.unsatisfied_interval_count for item in self.counts_per_source) != len(
            self.unsatisfied_intervals
        ):
            raise ValueError("per-source unsatisfied interval counts are incorrect")
        interval_keys = [
            (item.source_id, item.source_revision, item.interval_index)
            for item in self.unsatisfied_intervals
        ]
        if len(interval_keys) != len(set(interval_keys)):
            raise ValueError("sharpest selected set contains duplicate unsatisfied intervals")
        return self


def validate_sharpest_candidate_density(
    candidate: CandidatePoolSettings,
    selection: SharpestIntervalSettings,
    *,
    has_video: bool,
) -> None:
    if not has_video:
        return
    actual = candidate.candidate_fps.as_fraction()
    required = 2 * selection.target_fps.as_fraction()
    if actual < required:
        raise ValueError(
            "sharpest-per-interval requires candidate FPS at least 2 * target FPS for "
            f"video inputs; candidate FPS is {actual}, target FPS is "
            f"{selection.target_fps.as_fraction()}, required minimum is {required}. "
            "Increase --candidate-fps."
        )


def quality_recipe_key(
    *,
    candidate: CandidateViewSet,
    candidate_digest: str,
    settings: QualityAnalysisSettings,
    backend: QualityBackendIdentity,
) -> str:
    if candidate_digest != candidate_semantic_digest(candidate):
        raise ValueError("candidate digest does not match CandidateViewSet content")
    evidence = {
        "fingerprint_schema_version": FINGERPRINT_SCHEMA_VERSION,
        "stage_contract_version": QUALITY_ARTIFACT_CONTRACT_VERSION,
        "method_id": backend.quality_method_id,
        "method_version": backend.quality_method_version,
        "settings_schema_version": 1,
        "resolved_settings": settings.model_dump(mode="json"),
        "adapter_id": backend.adapter_id,
        "adapter_version": backend.adapter_version,
        "pillow_version": backend.pillow_version,
        "consumed_candidate": {
            "artifact_type": CANDIDATE_ARTIFACT_TYPE,
            "contract_version": candidate.contract_version,
            "semantic_digest": candidate_digest,
        },
    }
    return sha256_bytes(canonical_json_bytes(evidence))


def quality_semantic_digest(report: QualityReport) -> str:
    evidence = report.model_dump(mode="json")
    evidence.pop("candidate_artifact_id", None)
    evidence.pop("python_version", None)
    evidence["semantic_schema_version"] = 1
    evidence["artifact_type"] = QUALITY_ARTIFACT_TYPE
    return sha256_bytes(canonical_json_bytes(evidence))


def validate_quality_against_candidate(report: QualityReport, candidate: CandidateViewSet) -> None:
    expected_digest = candidate_semantic_digest(candidate)
    if report.candidate_semantic_digest != expected_digest:
        raise ValueError("quality report candidate semantic digest does not match content")
    candidate_by_id = {item.view_id: item for item in candidate.views}
    measurement_by_id = {item.view_id: item for item in report.measurements}
    missing = set(candidate_by_id) - set(measurement_by_id)
    extra = set(measurement_by_id) - set(candidate_by_id)
    if missing or extra:
        raise ValueError(
            "quality report must contain exactly one measurement per candidate; "
            f"missing={len(missing)}, extra={len(extra)}"
        )
    for view_id, view in candidate_by_id.items():
        if measurement_by_id[view_id].candidate_image_sha256 != view.image_sha256:
            raise ValueError(f"quality measurement pixel digest differs for {view_id}")


def sharpest_selection_recipe_key(
    *,
    candidate: CandidateViewSet,
    candidate_digest: str,
    quality: QualityReport,
    quality_digest: str,
    settings: SharpestIntervalSettings,
) -> str:
    if candidate_digest != candidate_semantic_digest(candidate):
        raise ValueError("candidate digest does not match CandidateViewSet content")
    if quality_digest != quality_semantic_digest(quality):
        raise ValueError("quality digest does not match QualityReport content")
    validate_quality_against_candidate(quality, candidate)
    evidence = {
        "fingerprint_schema_version": FINGERPRINT_SCHEMA_VERSION,
        "stage_contract_version": VIEW_ARTIFACT_CONTRACT_VERSION,
        "method_id": SHARPEST_METHOD_ID,
        "method_version": SHARPEST_METHOD_VERSION,
        "settings_schema_version": 1,
        "resolved_settings": settings.model_dump(mode="json"),
        "consumed_candidate": {
            "artifact_type": CANDIDATE_ARTIFACT_TYPE,
            "contract_version": candidate.contract_version,
            "semantic_digest": candidate_digest,
        },
        "consumed_quality": {
            "artifact_type": QUALITY_ARTIFACT_TYPE,
            "contract_version": quality.contract_version,
            "semantic_digest": quality_digest,
        },
    }
    return sha256_bytes(canonical_json_bytes(evidence))


def sharpest_selected_semantic_digest(selected: SharpestSelectedViewSet) -> str:
    evidence = selected.model_dump(mode="json")
    evidence.pop("candidate_artifact_id", None)
    evidence.pop("quality_artifact_id", None)
    evidence["semantic_schema_version"] = 1
    evidence["artifact_type"] = SELECTED_ARTIFACT_TYPE
    return sha256_bytes(canonical_json_bytes(evidence))


def hamming_distance64(left: str, right: str) -> int:
    return (int(left, 16) ^ int(right, 16)).bit_count()


def select_sharpest_interval(
    candidate: CandidateViewSet,
    quality: QualityReport,
    *,
    candidate_artifact: ArtifactHandle,
    quality_artifact: ArtifactHandle,
    settings: SharpestIntervalSettings,
    checkpoint: Callable[[], None] | None = None,
) -> SharpestSelectedViewSet:
    if candidate_artifact.artifact_type != CANDIDATE_ARTIFACT_TYPE:
        raise ValueError("sharpest selection requires a CandidateViewSet artifact")
    if quality_artifact.artifact_type != QUALITY_ARTIFACT_TYPE:
        raise ValueError("sharpest selection requires a QualityReport artifact")
    if candidate_artifact.semantic_digest != candidate_semantic_digest(candidate):
        raise ValueError("candidate handle semantic digest does not match candidate content")
    if quality_artifact.semantic_digest != quality_semantic_digest(quality):
        raise ValueError("quality handle semantic digest does not match quality content")
    validate_quality_against_candidate(quality, candidate)
    return _select_sharpest_interval(
        candidate,
        quality,
        candidate_artifact=candidate_artifact,
        quality_artifact=quality_artifact,
        settings=settings,
        checkpoint=checkpoint,
    )


def _select_sharpest_interval(
    candidate: CandidateViewSet,
    quality: QualityReport,
    *,
    candidate_artifact: ArtifactHandle,
    quality_artifact: ArtifactHandle,
    settings: SharpestIntervalSettings,
    checkpoint: Callable[[], None] | None,
) -> SharpestSelectedViewSet:
    measurements = {item.view_id: item for item in quality.measurements}
    grouped: dict[tuple[str, int], list[CandidateView]] = {}
    for view in candidate.views:
        grouped.setdefault((str(view.source_id), view.source_revision), []).append(view)

    selected: list[SharpestSelectedView] = []
    decisions: list[SharpestDecision] = []
    unsatisfied: list[UnsatisfiedInterval] = []
    counts: list[SharpestSourceCount] = []
    step = Fraction(1, 1) / settings.target_fps.as_fraction()

    for source_key in sorted(grouped):
        if checkpoint is not None:
            checkpoint()
        source_views = grouped[source_key]
        source_decision_start = len(decisions)
        source_selected_start = len(selected)
        source_unsatisfied_start = len(unsatisfied)
        photos = sorted(
            (view for view in source_views if view.media_type == MediaType.PHOTO),
            key=lambda item: str(item.view_id),
        )
        for photo in photos:
            measurement = measurements[photo.view_id]
            score = measurement.sharpness.score
            if score is None:
                decisions.append(_decision(photo, SharpestDecisionReason.QUALITY_UNAVAILABLE))
            elif (
                settings.min_sharpness is not None
                and score.as_fraction() < settings.min_sharpness.as_fraction()
            ):
                decisions.append(
                    _decision(
                        photo,
                        SharpestDecisionReason.BELOW_SHARPNESS_THRESHOLD,
                        score=score,
                        threshold=settings.min_sharpness,
                    )
                )
            else:
                selected.append(
                    SharpestSelectedView(
                        view_id=photo.view_id,
                        source_id=photo.source_id,
                        source_revision=photo.source_revision,
                        media_type=photo.media_type,
                        selection_order=len(selected),
                        reason=SharpestDecisionReason.PHOTO_QUALITY_PASS,
                    )
                )
                decisions.append(
                    _decision(
                        photo,
                        SharpestDecisionReason.PHOTO_QUALITY_PASS,
                        score=score,
                    )
                )

        videos = sorted(
            (view for view in source_views if view.media_type == MediaType.VIDEO),
            key=lambda item: (
                item.presentation_timestamp.seconds(),  # type: ignore[union-attr]
                str(item.view_id),
            ),
        )
        accepted_history: list[tuple[CandidateView, str]] = []
        if videos:
            anchor = videos[0].presentation_timestamp.seconds()  # type: ignore[union-attr]
            last_time = videos[-1].presentation_timestamp.seconds()  # type: ignore[union-attr]
            interval_count = math.floor((last_time - anchor) / step) + 1
            bound_timeline_expansion(
                source_key[0], interval_count,
                candidate_count=len(videos), unsatisfied_count=len(unsatisfied),
            )
            by_interval: dict[int, list[CandidateView]] = {}
            for view in videos:
                actual = view.presentation_timestamp.seconds()  # type: ignore[union-attr]
                interval_index = math.floor((actual - anchor) / step)
                by_interval.setdefault(interval_index, []).append(view)
            for interval_index in range(interval_count):
                if checkpoint is not None and interval_index % 32 == 0:
                    checkpoint()
                interval_start = anchor + interval_index * step
                interval_end = interval_start + step
                interval_views = by_interval.get(interval_index, [])
                if not interval_views:
                    unsatisfied.append(
                        UnsatisfiedInterval(
                            source_id=videos[0].source_id,
                            source_revision=videos[0].source_revision,
                            interval_index=interval_index,
                            interval_start=RationalValue.from_fraction(interval_start),
                            interval_end=RationalValue.from_fraction(interval_end),
                            candidate_count=0,
                            reason=UnsatisfiedIntervalReason.NO_CANDIDATE_IN_INTERVAL,
                        )
                    )
                    continue
                interval_decisions: dict[UUID, SharpestDecision] = {}
                eligible: list[CandidateView] = []
                for view in interval_views:
                    measurement = measurements[view.view_id]
                    score = measurement.sharpness.score
                    if score is None:
                        interval_decisions[view.view_id] = _decision(
                            view,
                            SharpestDecisionReason.QUALITY_UNAVAILABLE,
                            interval_index=interval_index,
                        )
                    elif (
                        settings.min_sharpness is not None
                        and score.as_fraction() < settings.min_sharpness.as_fraction()
                    ):
                        interval_decisions[view.view_id] = _decision(
                            view,
                            SharpestDecisionReason.BELOW_SHARPNESS_THRESHOLD,
                            interval_index=interval_index,
                            score=score,
                            threshold=settings.min_sharpness,
                        )
                    elif settings.reject_duplicates and measurement.duplicate.dhash64 is None:
                        interval_decisions[view.view_id] = _decision(
                            view,
                            SharpestDecisionReason.QUALITY_UNAVAILABLE,
                            interval_index=interval_index,
                            score=score,
                        )
                    else:
                        eligible.append(view)
                ranked = sorted(
                    eligible,
                    key=lambda item: (
                        -_score_or_negative(measurements[item.view_id]),
                        item.presentation_timestamp.seconds(),  # type: ignore[union-attr]
                        str(item.view_id),
                    ),
                )
                winner: CandidateView | None = None
                winner_score: NonNegativeRational | None = None
                for view in ranked:
                    measurement = measurements[view.view_id]
                    score = measurement.sharpness.score
                    if score is None:
                        interval_decisions[view.view_id] = _decision(
                            view,
                            SharpestDecisionReason.QUALITY_UNAVAILABLE,
                            interval_index=interval_index,
                        )
                        continue
                    if (
                        settings.min_sharpness is not None
                        and score.as_fraction() < settings.min_sharpness.as_fraction()
                    ):
                        interval_decisions[view.view_id] = _decision(
                            view,
                            SharpestDecisionReason.BELOW_SHARPNESS_THRESHOLD,
                            interval_index=interval_index,
                            score=score,
                            threshold=settings.min_sharpness,
                        )
                        continue
                    duplicate_hash = measurement.duplicate.dhash64
                    if settings.reject_duplicates and duplicate_hash is None:
                        interval_decisions[view.view_id] = _decision(
                            view,
                            SharpestDecisionReason.QUALITY_UNAVAILABLE,
                            interval_index=interval_index,
                            score=score,
                        )
                        continue
                    match = (
                        _nearest_duplicate(
                            duplicate_hash,
                            accepted_history[-settings.duplicate_lookback :],
                            threshold=settings.duplicate_hamming_threshold,
                        )
                        if settings.reject_duplicates and duplicate_hash is not None
                        else None
                    )
                    if match is not None:
                        duplicate_view, distance = match
                        interval_decisions[view.view_id] = _decision(
                            view,
                            SharpestDecisionReason.DUPLICATE_OF_RECENT_SELECTION,
                            interval_index=interval_index,
                            score=score,
                            duplicate_of=duplicate_view.view_id,
                            hamming_distance=distance,
                            duplicate_threshold=settings.duplicate_hamming_threshold,
                        )
                        continue
                    winner = view
                    winner_score = score
                    selected.append(
                        SharpestSelectedView(
                            view_id=view.view_id,
                            source_id=view.source_id,
                            source_revision=view.source_revision,
                            media_type=view.media_type,
                            selection_order=len(selected),
                            reason=SharpestDecisionReason.SHARPEST_IN_INTERVAL,
                            interval_index=interval_index,
                            interval_start=RationalValue.from_fraction(interval_start),
                            interval_end=RationalValue.from_fraction(interval_end),
                        )
                    )
                    interval_decisions[view.view_id] = _decision(
                        view,
                        SharpestDecisionReason.SHARPEST_IN_INTERVAL,
                        interval_index=interval_index,
                        score=score,
                    )
                    if duplicate_hash is not None:
                        accepted_history.append((view, duplicate_hash))
                    break
                if winner is None:
                    unsatisfied.append(
                        UnsatisfiedInterval(
                            source_id=videos[0].source_id,
                            source_revision=videos[0].source_revision,
                            interval_index=interval_index,
                            interval_start=RationalValue.from_fraction(interval_start),
                            interval_end=RationalValue.from_fraction(interval_end),
                            candidate_count=len(interval_views),
                            reason=UnsatisfiedIntervalReason.ALL_CANDIDATES_REJECTED,
                        )
                    )
                else:
                    assert winner_score is not None
                    for view in ranked:
                        if view.view_id not in interval_decisions:
                            score = measurements[view.view_id].sharpness.score
                            interval_decisions[view.view_id] = _decision(
                                view,
                                SharpestDecisionReason.LOWER_SHARPNESS_IN_INTERVAL,
                                interval_index=interval_index,
                                score=score,
                                selected_winner=winner.view_id,
                            )
                decisions.extend(
                    interval_decisions[view.view_id]
                    for view in sorted(interval_views, key=lambda item: str(item.view_id))
                )

        first = source_views[0]
        source_selected = len(selected) - source_selected_start
        source_decisions = len(decisions) - source_decision_start
        counts.append(
            SharpestSourceCount(
                source_id=first.source_id,
                source_revision=first.source_revision,
                candidate_count=source_decisions,
                selected_count=source_selected,
                rejected_count=source_decisions - source_selected,
                unsatisfied_interval_count=len(unsatisfied) - source_unsatisfied_start,
            )
        )

    return SharpestSelectedViewSet(
        candidate_artifact_id=candidate_artifact.artifact_id,
        candidate_semantic_digest=candidate_artifact.semantic_digest,
        quality_artifact_id=quality_artifact.artifact_id,
        quality_semantic_digest=quality_artifact.semantic_digest,
        settings=settings,
        selected_views=tuple(selected),
        decisions=tuple(decisions),
        unsatisfied_intervals=tuple(unsatisfied),
        counts_per_source=tuple(counts),
        total_candidate_count=len(decisions),
        total_selected_count=len(selected),
        total_rejected_count=len(decisions) - len(selected),
    )


def validate_sharpest_against_inputs(
    selected: SharpestSelectedViewSet,
    candidate: CandidateViewSet,
    quality: QualityReport,
    *,
    candidate_artifact: ArtifactHandle,
    quality_artifact: ArtifactHandle,
) -> None:
    if selected.candidate_semantic_digest != candidate_artifact.semantic_digest:
        raise ValueError("sharpest payload references different candidate semantics")
    if selected.quality_semantic_digest != quality_artifact.semantic_digest:
        raise ValueError("sharpest payload references different quality semantics")
    provenance_candidate = candidate_artifact.model_copy(
        update={"artifact_id": selected.candidate_artifact_id}
    )
    provenance_quality = quality_artifact.model_copy(
        update={"artifact_id": selected.quality_artifact_id}
    )
    expected = select_sharpest_interval(
        candidate,
        quality,
        candidate_artifact=provenance_candidate,
        quality_artifact=provenance_quality,
        settings=selected.settings,
    )
    if selected != expected:
        raise ValueError("sharpest selected payload differs from deterministic policy output")


def _decision(
    view: CandidateView,
    reason: SharpestDecisionReason,
    *,
    interval_index: int | None = None,
    score: NonNegativeRational | None = None,
    threshold: NonNegativeRational | None = None,
    duplicate_of: UUID | None = None,
    hamming_distance: int | None = None,
    duplicate_threshold: int | None = None,
    selected_winner: UUID | None = None,
) -> SharpestDecision:
    return SharpestDecision(
        view_id=view.view_id,
        source_id=view.source_id,
        source_revision=view.source_revision,
        media_type=view.media_type,
        reason=reason,
        interval_index=interval_index,
        sharpness_score=score,
        sharpness_threshold=threshold,
        duplicate_of_view_id=duplicate_of,
        hamming_distance=hamming_distance,
        duplicate_threshold=duplicate_threshold,
        selected_winner_view_id=selected_winner,
    )


def _score_or_negative(measurement: ViewQualityMeasurement) -> Fraction:
    score = measurement.sharpness.score
    return score.as_fraction() if score is not None else Fraction(-1, 1)


def _nearest_duplicate(
    candidate_hash: str,
    history: list[tuple[CandidateView, str]],
    *,
    threshold: int,
) -> tuple[CandidateView, int] | None:
    matches: list[tuple[int, int, str, CandidateView]] = []
    for history_index, (view, previous_hash) in enumerate(history):
        distance = hamming_distance64(candidate_hash, previous_hash)
        if distance <= threshold:
            matches.append((distance, -history_index, str(view.view_id), view))
    if not matches:
        return None
    distance, _, _, view = min(matches)
    return view, distance


__all__ = [
    "DUPLICATE_METHOD_ID",
    "MeasurementAvailability",
    "MeasurementUnavailableReason",
    "NonNegativeRational",
    "QUALITY_ADAPTER_ID",
    "QUALITY_ARTIFACT_CONTRACT_VERSION",
    "QUALITY_ARTIFACT_TYPE",
    "QUALITY_METHOD_ID",
    "QualityAnalysisSettings",
    "QualityBackendIdentity",
    "QualityReport",
    "SHARPEST_METHOD_ID",
    "SharpestDecisionReason",
    "SharpestIntervalSettings",
    "SharpestSelectedViewSet",
    "ViewQualityMeasurement",
    "hamming_distance64",
    "parse_non_negative_rational",
    "quality_recipe_key",
    "quality_semantic_digest",
    "select_sharpest_interval",
    "sharpest_selected_semantic_digest",
    "sharpest_selection_recipe_key",
    "validate_quality_against_candidate",
    "validate_sharpest_against_inputs",
    "validate_sharpest_candidate_density",
]
