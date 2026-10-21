from __future__ import annotations

from fractions import Fraction
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from splatforge.core.execution import ArtifactHandle
from splatforge.core.media import ExecutableIdentity, MediaType
from splatforge.core.quality import (
    QUALITY_ARTIFACT_TYPE,
    DuplicateMeasurement,
    MeasurementAvailability,
    MeasurementUnavailableReason,
    NonNegativeRational,
    QualityAnalysisSettings,
    QualityBackendIdentity,
    QualityReport,
    SharpestDecisionReason,
    SharpestIntervalSettings,
    SharpnessMeasurement,
    ViewQualityMeasurement,
    hamming_distance64,
    parse_non_negative_rational,
    quality_recipe_key,
    quality_semantic_digest,
    select_sharpest_interval,
    sharpest_selected_semantic_digest,
    sharpest_selection_recipe_key,
    validate_quality_against_candidate,
    validate_sharpest_candidate_density,
)
from splatforge.core.views import (
    CANDIDATE_ARTIFACT_TYPE,
    SELECTED_ARTIFACT_TYPE,
    CandidateEncodingSettings,
    CandidatePoolSettings,
    CandidateView,
    CandidateViewSet,
    FrameTimestamp,
    ImageFormat,
    PixelTransform,
    RationalValue,
    candidate_semantic_digest,
    parse_fps,
)

BACKEND = ExecutableIdentity(
    resolved_path="C:/Tools/ffmpeg.exe",
    size=123,
    last_write_ns=456,
    sha256="a" * 64,
    version_line="ffmpeg test",
)
QUALITY_BACKEND = QualityBackendIdentity(
    pillow_version="12.3.0",
    python_version="3.12.12",
)
SOURCE_A = UUID("00000000-0000-0000-0000-00000000000a")
SOURCE_B = UUID("00000000-0000-0000-0000-00000000000b")


def candidate_view(
    *,
    source_id: UUID = SOURCE_A,
    pts: int | None,
    identity: int,
) -> CandidateView:
    view_id = UUID(int=identity)
    media_type = MediaType.PHOTO if pts is None else MediaType.VIDEO
    return CandidateView(
        view_id=view_id,
        source_id=source_id,
        source_revision=1,
        source_content_sha256=f"{identity % 16:x}" * 64,
        source_group_id=UUID(int=100 + identity),
        camera_group_id=UUID(int=200 + identity),
        media_type=media_type,
        selected_visual_stream_index=0,
        frame_identity="photo_singleton" if pts is None else f"pts:{pts}@1/10",
        occurrence_index=0,
        presentation_timestamp=(
            None
            if pts is None
            else FrameTimestamp(
                pts=pts,
                time_base=RationalValue(numerator=1, denominator=10),
            )
        ),
        image_path=f"images/{view_id}.png",
        image_sha256=f"{(identity + 1) % 16:x}" * 64,
        width=64,
        height=48,
        transform=PixelTransform(
            source_width=64,
            source_height=48,
            orientation_operation="identity",
            output_width=64,
            output_height=48,
        ),
    )


def candidate_set(*views: CandidateView, candidate_fps: str = "4") -> CandidateViewSet:
    return CandidateViewSet(
        backend=BACKEND,
        settings=CandidatePoolSettings(
            candidate_fps=parse_fps(candidate_fps),
            encoding=CandidateEncodingSettings(
                image_format=ImageFormat.PNG,
                png_compression_level=6,
            ),
        ),
        views=views,
    )


def measurement(
    view: CandidateView,
    score: str | None,
    *,
    dhash: str | None = "0123456789abcdef",
) -> ViewQualityMeasurement:
    if score is None:
        sharpness = SharpnessMeasurement(
            availability=MeasurementAvailability.UNAVAILABLE,
            unavailable_reason=MeasurementUnavailableReason.IMAGE_TOO_SMALL,
        )
    else:
        sharpness = SharpnessMeasurement(
            availability=MeasurementAvailability.AVAILABLE,
            score=parse_non_negative_rational(score),
        )
    duplicate = (
        DuplicateMeasurement(
            availability=MeasurementAvailability.AVAILABLE,
            dhash64=dhash,
        )
        if dhash is not None
        else DuplicateMeasurement(
            availability=MeasurementAvailability.UNAVAILABLE,
            unavailable_reason=MeasurementUnavailableReason.DECODE_FAILED,
        )
    )
    return ViewQualityMeasurement(
        view_id=view.view_id,
        candidate_image_sha256=view.image_sha256,
        sharpness=sharpness,
        duplicate=duplicate,
    )


def report(
    candidate: CandidateViewSet,
    *measurements: ViewQualityMeasurement,
    artifact_id: UUID | None = None,
    settings: QualityAnalysisSettings | None = None,
) -> QualityReport:
    return QualityReport(
        candidate_artifact_id=artifact_id or uuid4(),
        candidate_semantic_digest=candidate_semantic_digest(candidate),
        pillow_version=QUALITY_BACKEND.pillow_version,
        python_version=QUALITY_BACKEND.python_version,
        settings=settings or QualityAnalysisSettings(),
        measurements=measurements,
    )


def handles(
    candidate: CandidateViewSet, quality: QualityReport
) -> tuple[ArtifactHandle, ArtifactHandle]:
    candidate_handle = ArtifactHandle(
        artifact_id=quality.candidate_artifact_id,
        artifact_type=CANDIDATE_ARTIFACT_TYPE,
        contract_version=1,
        recipe_key="c" * 64,
        semantic_digest=candidate_semantic_digest(candidate),
        manifest_path="artifacts/candidate/manifest.json",
    )
    quality_handle = ArtifactHandle(
        artifact_id=uuid4(),
        artifact_type=QUALITY_ARTIFACT_TYPE,
        contract_version=1,
        recipe_key="q" * 64,
        semantic_digest=quality_semantic_digest(quality),
        manifest_path="artifacts/quality/manifest.json",
    )
    return candidate_handle, quality_handle


def test_exact_metric_rational_is_canonical_and_non_negative() -> None:
    assert parse_non_negative_rational("1.50") == NonNegativeRational(numerator=3, denominator=2)
    with pytest.raises(ValueError, match="non-negative"):
        parse_non_negative_rational("-1/4")
    with pytest.raises(ValidationError, match="lowest terms"):
        NonNegativeRational(numerator=2, denominator=4)


def test_quality_measurement_contracts_are_strict() -> None:
    with pytest.raises(ValidationError, match="requires a score"):
        SharpnessMeasurement(availability=MeasurementAvailability.AVAILABLE)
    with pytest.raises(ValidationError, match="requires a reason"):
        SharpnessMeasurement(availability=MeasurementAvailability.UNAVAILABLE)
    for invalid in ("0" * 15, "0" * 17, "ABCDEF0123456789", "g" * 16):
        with pytest.raises(ValidationError, match="16 lowercase"):
            DuplicateMeasurement(
                availability=MeasurementAvailability.AVAILABLE,
                dhash64=invalid,
            )


def test_quality_report_requires_exact_candidate_coverage_and_pixel_binding() -> None:
    first = candidate_view(pts=0, identity=1)
    second = candidate_view(pts=1, identity=2)
    candidate = candidate_set(first, second)
    valid = report(candidate, measurement(first, "10"), measurement(second, "20"))
    validate_quality_against_candidate(valid, candidate)

    with pytest.raises(ValidationError, match="duplicate view IDs"):
        report(candidate, measurement(first, "10"), measurement(first, "20"))
    with pytest.raises(ValueError, match="exactly one measurement"):
        validate_quality_against_candidate(report(candidate, measurement(first, "10")), candidate)
    extra = candidate_view(pts=2, identity=3)
    with pytest.raises(ValueError, match="extra=1"):
        validate_quality_against_candidate(
            report(
                candidate,
                measurement(first, "10"),
                measurement(second, "20"),
                measurement(extra, "30"),
            ),
            candidate,
        )
    altered = measurement(first, "10").model_copy(update={"candidate_image_sha256": "f" * 64})
    with pytest.raises(ValueError, match="pixel digest"):
        validate_quality_against_candidate(
            report(candidate, altered, measurement(second, "20")), candidate
        )


def test_sharpest_settings_and_density_validation() -> None:
    settings = SharpestIntervalSettings(target_fps=parse_fps("2"))
    validate_sharpest_candidate_density(
        candidate_set(candidate_view(pts=None, identity=1)).settings,
        settings,
        has_video=False,
    )
    with pytest.raises(ValueError, match=r"2 \* target FPS"):
        validate_sharpest_candidate_density(
            candidate_set(candidate_view(pts=0, identity=1), candidate_fps="3").settings,
            settings,
            has_video=True,
        )
    for payload in (
        {"duplicate_hamming_threshold": 65},
        {"duplicate_hamming_threshold": -1},
        {"duplicate_lookback": 0},
        {"duplicate_lookback": 65},
        {"min_sharpness": {"numerator": -1, "denominator": 1}},
    ):
        with pytest.raises(ValidationError):
            SharpestIntervalSettings(target_fps=parse_fps("1"), **payload)


def test_sharpest_selects_score_then_time_then_stable_id_and_records_all_decisions() -> None:
    later = candidate_view(pts=2, identity=3)
    earlier_high_id = candidate_view(pts=1, identity=2)
    earlier_low_id = candidate_view(pts=1, identity=1)
    candidate = candidate_set(later, earlier_high_id, earlier_low_id)
    quality = report(
        candidate,
        measurement(later, "10", dhash="0000000000000001"),
        measurement(earlier_high_id, "10", dhash="0000000000000002"),
        measurement(earlier_low_id, "10", dhash="0000000000000004"),
    )
    candidate_handle, quality_handle = handles(candidate, quality)
    selected = select_sharpest_interval(
        candidate,
        quality,
        candidate_artifact=candidate_handle,
        quality_artifact=quality_handle,
        settings=SharpestIntervalSettings(target_fps=parse_fps("1"), reject_duplicates=False),
    )
    assert [item.view_id for item in selected.selected_views] == [earlier_low_id.view_id]
    reasons = {item.view_id: item.reason for item in selected.decisions}
    assert reasons[earlier_low_id.view_id] == SharpestDecisionReason.SHARPEST_IN_INTERVAL
    assert reasons[later.view_id] == SharpestDecisionReason.LOWER_SHARPNESS_IN_INTERVAL
    assert reasons[earlier_high_id.view_id] == (SharpestDecisionReason.LOWER_SHARPNESS_IN_INTERVAL)
    assert len(selected.decisions) == len(candidate.views)


def test_duplicate_winner_tries_next_ranked_and_threshold_is_inclusive() -> None:
    first = candidate_view(pts=0, identity=1)
    duplicate_best = candidate_view(pts=10, identity=2)
    fallback = candidate_view(pts=11, identity=3)
    candidate = candidate_set(first, duplicate_best, fallback)
    quality = report(
        candidate,
        measurement(first, "10", dhash="0000000000000000"),
        measurement(duplicate_best, "30", dhash="0000000000000001"),
        measurement(fallback, "20", dhash="ffffffffffffffff"),
    )
    candidate_handle, quality_handle = handles(candidate, quality)
    selected = select_sharpest_interval(
        candidate,
        quality,
        candidate_artifact=candidate_handle,
        quality_artifact=quality_handle,
        settings=SharpestIntervalSettings(
            target_fps=parse_fps("1"),
            duplicate_hamming_threshold=1,
        ),
    )
    assert [item.view_id for item in selected.selected_views] == [
        first.view_id,
        fallback.view_id,
    ]
    duplicate_decision = next(
        item for item in selected.decisions if item.view_id == duplicate_best.view_id
    )
    assert duplicate_decision.reason == (SharpestDecisionReason.DUPLICATE_OF_RECENT_SELECTION)
    assert duplicate_decision.hamming_distance == 1
    assert duplicate_decision.duplicate_of_view_id == first.view_id


def test_duplicate_history_is_bounded_and_source_local() -> None:
    source_a = [candidate_view(pts=index * 10, identity=index + 1) for index in range(3)]
    source_b = candidate_view(source_id=SOURCE_B, pts=0, identity=10)
    candidate = candidate_set(*source_a, source_b)
    quality = report(
        candidate,
        measurement(source_a[0], "10", dhash="0000000000000000"),
        measurement(source_a[1], "10", dhash="ffffffffffffffff"),
        measurement(source_a[2], "10", dhash="0000000000000000"),
        measurement(source_b, "10", dhash="0000000000000000"),
    )
    candidate_handle, quality_handle = handles(candidate, quality)
    selected = select_sharpest_interval(
        candidate,
        quality,
        candidate_artifact=candidate_handle,
        quality_artifact=quality_handle,
        settings=SharpestIntervalSettings(
            target_fps=parse_fps("1"),
            duplicate_hamming_threshold=0,
            duplicate_lookback=1,
        ),
    )
    assert {item.view_id for item in selected.selected_views} == {
        *(item.view_id for item in source_a),
        source_b.view_id,
    }


def test_quality_unavailable_threshold_photos_and_interval_gaps_are_reasoned() -> None:
    photo_ok = candidate_view(pts=None, identity=1)
    photo_low = candidate_view(pts=None, identity=2)
    unavailable = candidate_view(pts=0, identity=3)
    late = candidate_view(pts=30, identity=4)
    candidate = candidate_set(photo_ok, photo_low, unavailable, late)
    quality = report(
        candidate,
        measurement(photo_ok, "10"),
        measurement(photo_low, "1"),
        measurement(unavailable, None),
        measurement(late, "10", dhash="ffffffffffffffff"),
    )
    candidate_handle, quality_handle = handles(candidate, quality)
    selected = select_sharpest_interval(
        candidate,
        quality,
        candidate_artifact=candidate_handle,
        quality_artifact=quality_handle,
        settings=SharpestIntervalSettings(
            target_fps=parse_fps("1"),
            min_sharpness=parse_non_negative_rational("5"),
        ),
    )
    reasons = {item.view_id: item.reason for item in selected.decisions}
    assert reasons[photo_ok.view_id] == SharpestDecisionReason.PHOTO_QUALITY_PASS
    assert reasons[photo_low.view_id] == (SharpestDecisionReason.BELOW_SHARPNESS_THRESHOLD)
    assert reasons[unavailable.view_id] == SharpestDecisionReason.QUALITY_UNAVAILABLE
    assert {item.interval_index for item in selected.unsatisfied_intervals} == {0, 1, 2}
    assert selected.total_selected_count == 2


def test_no_minimum_sharpness_does_not_apply_absolute_blur_rejection() -> None:
    view = candidate_view(pts=0, identity=1)
    candidate = candidate_set(view)
    quality = report(candidate, measurement(view, "0"))
    candidate_handle, quality_handle = handles(candidate, quality)
    selected = select_sharpest_interval(
        candidate,
        quality,
        candidate_artifact=candidate_handle,
        quality_artifact=quality_handle,
        settings=SharpestIntervalSettings(target_fps=parse_fps("1"), reject_duplicates=False),
    )
    assert selected.total_selected_count == 1


def test_semantic_and_recipe_keys_separate_measurement_from_policy() -> None:
    view = candidate_view(pts=0, identity=1)
    candidate = candidate_set(view)
    quality_settings = QualityAnalysisSettings()
    quality = report(candidate, measurement(view, "10"), settings=quality_settings)
    candidate_handle, quality_handle = handles(candidate, quality)
    base_quality_key = quality_recipe_key(
        candidate=candidate,
        candidate_digest=candidate_handle.semantic_digest,
        settings=quality_settings,
        backend=QUALITY_BACKEND,
    )
    base_selection = SharpestIntervalSettings(target_fps=parse_fps("1"))
    base_selection_key = sharpest_selection_recipe_key(
        candidate=candidate,
        candidate_digest=candidate_handle.semantic_digest,
        quality=quality,
        quality_digest=quality_handle.semantic_digest,
        settings=base_selection,
    )
    for changed in (
        base_selection.model_copy(update={"min_sharpness": parse_non_negative_rational("5")}),
        base_selection.model_copy(update={"duplicate_hamming_threshold": 5}),
        base_selection.model_copy(update={"duplicate_lookback": 4}),
        base_selection.model_copy(update={"target_fps": parse_fps("2")}),
    ):
        assert (
            quality_recipe_key(
                candidate=candidate,
                candidate_digest=candidate_handle.semantic_digest,
                settings=quality_settings,
                backend=QUALITY_BACKEND,
            )
            == base_quality_key
        )
        assert (
            sharpest_selection_recipe_key(
                candidate=candidate,
                candidate_digest=candidate_handle.semantic_digest,
                quality=quality,
                quality_digest=quality_handle.semantic_digest,
                settings=changed,
            )
            != base_selection_key
        )

    resized_key = quality_recipe_key(
        candidate=candidate,
        candidate_digest=candidate_handle.semantic_digest,
        settings=QualityAnalysisSettings(quality_max_side=512),
        backend=QUALITY_BACKEND,
    )
    changed_method_key = quality_recipe_key(
        candidate=candidate,
        candidate_digest=candidate_handle.semantic_digest,
        settings=quality_settings,
        backend=QUALITY_BACKEND.model_copy(update={"quality_method_version": 2}),
    )
    assert resized_key != base_quality_key
    assert changed_method_key != base_quality_key


def test_deterministic_selection_and_semantic_digest_exclude_provenance_uuids() -> None:
    view = candidate_view(pts=0, identity=1)
    candidate = candidate_set(view)
    quality = report(candidate, measurement(view, "10"))
    candidate_handle, quality_handle = handles(candidate, quality)
    settings = SharpestIntervalSettings(target_fps=parse_fps("1"), reject_duplicates=False)
    first = select_sharpest_interval(
        candidate,
        quality,
        candidate_artifact=candidate_handle,
        quality_artifact=quality_handle,
        settings=settings,
    )
    second = select_sharpest_interval(
        candidate,
        quality,
        candidate_artifact=candidate_handle.model_copy(update={"artifact_id": uuid4()}),
        quality_artifact=quality_handle.model_copy(update={"artifact_id": uuid4()}),
        settings=settings,
    )
    assert first.decisions == second.decisions
    assert first.selected_views == second.selected_views
    assert sharpest_selected_semantic_digest(first) == (sharpest_selected_semantic_digest(second))
    assert hamming_distance64("0000000000000000", "0000000000000001") == 1
    assert first.selection_method_id == "frame_selection.sharpest_interval"
    assert first.contract_version == 1
    assert quality_handle.artifact_type == QUALITY_ARTIFACT_TYPE
    assert candidate_handle.artifact_type == CANDIDATE_ARTIFACT_TYPE
    assert SELECTED_ARTIFACT_TYPE == "views.selected_set"
    assert (
        Fraction(
            quality.measurements[0].sharpness.score.numerator,
            quality.measurements[0].sharpness.score.denominator,
        )
        == 10
    )
