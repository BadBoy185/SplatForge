from __future__ import annotations

from datetime import UTC, datetime
from fractions import Fraction
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from splatforge.core.execution import ArtifactHandle
from splatforge.core.media import (
    ExecutableIdentity,
    FullHashEvidence,
    MediaType,
    NormalizedProbe,
    SourceEvidence,
    SourceOccurrence,
    StorageKind,
)
from splatforge.core.views import (
    CANDIDATE_ARTIFACT_TYPE,
    CandidateEncodingSettings,
    CandidatePoolSettings,
    CandidateResourceLimits,
    CandidateView,
    CandidateViewSet,
    FixedFpsSettings,
    FrameTimestamp,
    ImageFormat,
    PixelTransform,
    RationalValue,
    SelectedView,
    SelectedViewSet,
    SelectionReason,
    SourceSelectionCount,
    candidate_recipe_key,
    candidate_semantic_digest,
    deterministic_photo_view_id,
    deterministic_video_view_id,
    estimate_candidate_budget,
    parse_fps,
    parse_gib_bytes,
    select_fixed_fps,
    selection_recipe_key,
    validate_fps_density,
    validate_selected_against_candidate,
)

BACKEND = ExecutableIdentity(
    resolved_path="C:/Tools/ffmpeg.exe",
    size=123,
    last_write_ns=456,
    sha256="a" * 64,
    version_line="ffmpeg version test",
)
EVIDENCE = SourceEvidence(
    size=10,
    last_write_ns=20,
    volume_id="volume",
    file_id="file",
    change_time_ns=30,
    storage_kind=StorageKind.LOCAL_FIXED,
    evidence_available=True,
)


def source(
    media_type: MediaType,
    *,
    source_id: UUID | None = None,
    locator: str = "C:/media/input.mp4",
    digest: str = "b" * 64,
) -> SourceOccurrence:
    now = datetime.now(UTC)
    extension = ".jpg" if media_type == MediaType.PHOTO else ".mp4"
    return SourceOccurrence(
        source_id=source_id or uuid4(),
        source_revision=1,
        external_locator=locator,
        display_filename=PathLike.name(locator),
        media_type=media_type,
        extension=extension,
        byte_size=10,
        content_sha256=digest,
        last_full_hash_at=now,
        full_hash_evidence=FullHashEvidence(
            hashed_at=now,
            byte_count=10,
            evidence_before=EVIDENCE,
            evidence_after=EVIDENCE,
            stability_mechanism="test",
        ),
        source_group_id=uuid4(),
        camera_group_id=uuid4(),
        probe=NormalizedProbe(
            backend=BACKEND,
            selected_visual_stream_index=0,
            width=640,
            height=480,
            orientation=1 if media_type == MediaType.PHOTO else None,
            time_base="1/1000" if media_type == MediaType.VIDEO else None,
            duration="3" if media_type == MediaType.VIDEO else None,
            rotation_degrees=0 if media_type == MediaType.VIDEO else None,
        ),
    )


class PathLike:
    @staticmethod
    def name(value: str) -> str:
        return value.replace("\\", "/").rsplit("/", maxsplit=1)[-1]


def settings(fps: str = "2", image_format: ImageFormat = ImageFormat.JPEG):
    return CandidatePoolSettings(
        candidate_fps=parse_fps(fps),
        encoding=CandidateEncodingSettings(image_format=image_format, jpeg_qscale=2),
    )


def video_view(item: SourceOccurrence, pts: int, *, view_id: UUID | None = None) -> CandidateView:
    time_base = RationalValue(numerator=1, denominator=10)
    identity = view_id or deterministic_video_view_id(
        item, pts=pts, time_base=time_base, occurrence_index=0
    )
    return CandidateView(
        view_id=identity,
        source_id=item.source_id,
        source_revision=item.source_revision,
        source_content_sha256=item.content_sha256,
        source_group_id=item.source_group_id,
        camera_group_id=item.camera_group_id,
        media_type=MediaType.VIDEO,
        selected_visual_stream_index=0,
        frame_identity=f"pts:{pts}@1/10",
        occurrence_index=0,
        presentation_timestamp=FrameTimestamp(pts=pts, time_base=time_base),
        image_path=f"images/{identity}.jpg",
        image_sha256=f"{pts % 16:x}" * 64,
        width=640,
        height=480,
        transform=PixelTransform(
            source_width=640,
            source_height=480,
            orientation_operation="identity",
            output_width=640,
            output_height=480,
        ),
    )


def photo_view(item: SourceOccurrence) -> CandidateView:
    identity = deterministic_photo_view_id(item)
    return CandidateView(
        view_id=identity,
        source_id=item.source_id,
        source_revision=item.source_revision,
        source_content_sha256=item.content_sha256,
        source_group_id=item.source_group_id,
        camera_group_id=item.camera_group_id,
        media_type=MediaType.PHOTO,
        selected_visual_stream_index=0,
        frame_identity="photo_singleton",
        occurrence_index=0,
        presentation_timestamp=None,
        image_path=f"images/{identity}.jpg",
        image_sha256="c" * 64,
        width=640,
        height=480,
        transform=PixelTransform(
            source_width=640,
            source_height=480,
            orientation_operation="identity",
            output_width=640,
            output_height=480,
        ),
    )


def candidate(*views: CandidateView) -> CandidateViewSet:
    return CandidateViewSet(backend=BACKEND, settings=settings(), views=views)


def handle(value: CandidateViewSet, *, artifact_id: UUID | None = None) -> ArtifactHandle:
    return ArtifactHandle(
        artifact_id=artifact_id or uuid4(),
        artifact_type=CANDIDATE_ARTIFACT_TYPE,
        contract_version=1,
        recipe_key="d" * 64,
        semantic_digest=candidate_semantic_digest(value),
        manifest_path="artifacts/candidate/manifest.json",
    )


@pytest.mark.parametrize(
    ("text", "numerator", "denominator"),
    [("2", 2, 1), ("2.5", 5, 2), ("30000/1001", 30000, 1001)],
)
def test_parse_fps_is_exact(text: str, numerator: int, denominator: int) -> None:
    assert parse_fps(text) == RationalValue(numerator=numerator, denominator=denominator)


@pytest.mark.parametrize("text", ["0", "-1", "nan", "inf", "1/0", "1000000001"])
def test_parse_fps_rejects_invalid_or_unreasonable_values(text: str) -> None:
    with pytest.raises(ValueError):
        parse_fps(text)


def test_parse_gib_bytes_is_exact_and_finite() -> None:
    assert parse_gib_bytes("1.5") == 3 * 1024**3 // 2
    with pytest.raises(ValueError):
        parse_gib_bytes("nan")


def test_candidate_fps_cannot_be_lower_than_target() -> None:
    with pytest.raises(ValueError, match="candidate FPS"):
        validate_fps_density(settings("1"), FixedFpsSettings(target_fps=parse_fps("2")))


def test_candidate_budget_accepts_bounded_input_and_refuses_all_unbounded_cases() -> None:
    video = source(MediaType.VIDEO)
    allowed = estimate_candidate_budget(
        (video,),
        settings=settings("2"),
        limits=CandidateResourceLimits(
            max_candidates=10,
            max_candidate_bytes=100_000_000,
            per_source_timeout_seconds=30,
        ),
    )
    assert allowed.total_candidates == 7

    with pytest.raises(ValueError, match="max_candidates"):
        estimate_candidate_budget(
            (video,),
            settings=settings("2"),
            limits=CandidateResourceLimits(
                max_candidates=1,
                max_candidate_bytes=100_000_000,
                per_source_timeout_seconds=30,
            ),
        )
    with pytest.raises(ValueError, match="max_candidate_bytes"):
        estimate_candidate_budget(
            (video,),
            settings=settings("2"),
            limits=CandidateResourceLimits(
                max_candidates=10,
                max_candidate_bytes=1,
                per_source_timeout_seconds=30,
            ),
        )
    unknown = video.model_copy(update={"probe": video.probe.model_copy(update={"duration": None})})
    with pytest.raises(ValueError, match="no bounded duration"):
        estimate_candidate_budget(
            (unknown,),
            settings=settings("2"),
            limits=CandidateResourceLimits(),
        )
    invalid = video.model_copy(update={"probe": video.probe.model_copy(update={"duration": "0"})})
    with pytest.raises(ValueError, match="non-positive duration"):
        estimate_candidate_budget(
            (invalid,),
            settings=settings("2"),
            limits=CandidateResourceLimits(),
        )
    enormous = video.model_copy(
        update={
            "probe": video.probe.model_copy(
                update={"width": 4_000_000_000, "height": 4_000_000_000}
            )
        }
    )
    with pytest.raises(ValueError, match="safe budgeting"):
        estimate_candidate_budget(
            (enormous,),
            settings=settings("2"),
            limits=CandidateResourceLimits(),
        )


def test_stable_photo_and_video_ids_ignore_locator_and_repeat() -> None:
    identifier = uuid4()
    first_photo = source(MediaType.PHOTO, source_id=identifier, locator="C:/old/a.jpg")
    relinked_photo = first_photo.model_copy(
        update={"external_locator": "D:/new/a.jpg", "display_filename": "a.jpg"}
    )
    assert deterministic_photo_view_id(first_photo) == deterministic_photo_view_id(
        relinked_photo
    )
    video = source(MediaType.VIDEO)
    time_base = RationalValue(numerator=1, denominator=1000)
    assert deterministic_video_view_id(
        video, pts=123, time_base=time_base, occurrence_index=0
    ) == deterministic_video_view_id(
        video, pts=123, time_base=time_base, occurrence_index=0
    )
    assert deterministic_video_view_id(
        video, pts=123, time_base=time_base, occurrence_index=0
    ) != deterministic_video_view_id(
        video, pts=123, time_base=time_base, occurrence_index=1
    )


def test_candidate_contract_rejects_duplicate_ids_and_unsafe_paths() -> None:
    item = source(MediaType.VIDEO)
    first = video_view(item, 0)
    duplicate = video_view(item, 1, view_id=first.view_id).model_copy(
        update={"image_path": first.image_path}
    )
    with pytest.raises(ValidationError, match="duplicate view IDs"):
        candidate(first, duplicate)
    with pytest.raises(ValidationError, match="safe images"):
        CandidateView.model_validate(
            {**first.model_dump(mode="python"), "image_path": "../escape.jpg"}
        )


def test_selected_contract_and_candidate_cross_validation_are_strict() -> None:
    item = source(MediaType.PHOTO)
    view = photo_view(item)
    value = candidate(view)
    selected_view = SelectedView(
        view_id=view.view_id,
        source_id=view.source_id,
        source_revision=1,
        media_type=MediaType.PHOTO,
        selection_order=0,
        reason=SelectionReason.PHOTO_SINGLETON,
    )
    with pytest.raises(ValidationError, match="duplicate selected view"):
        SelectedViewSet(
            candidate_artifact_id=uuid4(),
            candidate_semantic_digest=candidate_semantic_digest(value),
            settings=FixedFpsSettings(target_fps=parse_fps("1")),
            selected_views=(selected_view, selected_view.model_copy(update={"selection_order": 1})),
            counts_per_source=(
                SourceSelectionCount(
                    source_id=item.source_id,
                    source_revision=1,
                    candidate_count=1,
                    selected_count=2,
                    unsatisfied_slot_count=0,
                ),
            ),
            total_selected_count=2,
        )
    invalid = selected_view.model_copy(update={"view_id": uuid4()})
    selected = SelectedViewSet(
        candidate_artifact_id=uuid4(),
        candidate_semantic_digest=candidate_semantic_digest(value),
        settings=FixedFpsSettings(target_fps=parse_fps("1")),
        selected_views=(invalid,),
        counts_per_source=(
            SourceSelectionCount(
                source_id=item.source_id,
                source_revision=1,
                candidate_count=1,
                selected_count=1,
                unsatisfied_slot_count=0,
            ),
        ),
        total_selected_count=1,
    )
    with pytest.raises(ValueError, match="absent"):
        validate_selected_against_candidate(selected, value)

    video = source(MediaType.VIDEO)
    video_candidate = candidate(video_view(video, 10))
    valid_video_selection = select_fixed_fps(
        video_candidate,
        candidate_artifact=handle(video_candidate),
        settings=FixedFpsSettings(target_fps=parse_fps("1")),
    )
    selected_video = valid_video_selection.selected_views[0]
    with pytest.raises(ValidationError, match="actual minus target"):
        SelectedView.model_validate(
            {
                **selected_video.model_dump(mode="python"),
                "time_error": RationalValue(numerator=1, denominator=1),
            }
        )
    wrong_actual = selected_video.model_copy(
        update={"actual_presentation_time": RationalValue(numerator=2, denominator=1)}
    )
    inconsistent = valid_video_selection.model_copy(
        update={"selected_views": (wrong_actual,)}
    )
    with pytest.raises(ValueError, match="differs from its candidate"):
        validate_selected_against_candidate(inconsistent, video_candidate)


def test_fixed_fps_handles_even_vfr_ties_gaps_and_no_duplicates() -> None:
    item = source(MediaType.VIDEO)
    value = candidate(*(video_view(item, pts) for pts in (0, 4, 11, 20)))
    selected = select_fixed_fps(
        value,
        candidate_artifact=handle(value),
        settings=FixedFpsSettings(target_fps=parse_fps("1")),
    )
    assert [entry.actual_presentation_time.as_fraction() for entry in selected.selected_views] == [
        0,
        Fraction(11, 10),
        2,
    ]
    assert len({entry.view_id for entry in selected.selected_views}) == len(
        selected.selected_views
    )
    assert selected.unsatisfied_slots == ()


def test_fixed_fps_tie_prefers_earlier_and_omits_duplicate_slot() -> None:
    item = source(MediaType.VIDEO)
    value = candidate(video_view(item, 0), video_view(item, 20))
    selected = select_fixed_fps(
        value,
        candidate_artifact=handle(value),
        settings=FixedFpsSettings(target_fps=parse_fps("1")),
    )
    assert [entry.actual_presentation_time.as_fraction() for entry in selected.selected_views] == [
        0,
        2,
    ]
    assert [slot.target_slot_index for slot in selected.unsatisfied_slots] == [1]


def test_photos_and_multiple_clips_have_deterministic_separate_timelines() -> None:
    photo = source(MediaType.PHOTO, source_id=UUID(int=1))
    clip_a = source(MediaType.VIDEO, source_id=UUID(int=2))
    clip_b = source(MediaType.VIDEO, source_id=UUID(int=3))
    value = candidate(
        video_view(clip_b, 100),
        photo_view(photo),
        video_view(clip_a, 0),
        video_view(clip_b, 110),
        video_view(clip_a, 10),
    )
    selected = select_fixed_fps(
        value,
        candidate_artifact=handle(value),
        settings=FixedFpsSettings(target_fps=parse_fps("1")),
    )
    assert [entry.source_id for entry in selected.selected_views] == [
        photo.source_id,
        clip_a.source_id,
        clip_a.source_id,
        clip_b.source_id,
        clip_b.source_id,
    ]
    assert selected.selected_views[0].reason == SelectionReason.PHOTO_SINGLETON
    assert [item.selected_count for item in selected.counts_per_source] == [1, 2, 2]


def test_candidate_key_excludes_target_locator_and_project_bookkeeping() -> None:
    item = source(MediaType.VIDEO, locator="C:/old/clip.mp4")
    first = candidate_recipe_key(sources=(item,), settings=settings("2"), backend=BACKEND)
    relinked = item.model_copy(update={"external_locator": "D:/new/clip.mp4"})
    assert candidate_recipe_key(
        sources=(relinked,), settings=settings("2"), backend=BACKEND
    ) == first
    assert candidate_recipe_key(
        sources=(item,), settings=settings("3"), backend=BACKEND
    ) != first
    assert candidate_recipe_key(
        sources=(item,), settings=settings("2", ImageFormat.PNG), backend=BACKEND
    ) != first
    changed = item.model_copy(update={"content_sha256": "e" * 64})
    assert candidate_recipe_key(
        sources=(changed,), settings=settings("2"), backend=BACKEND
    ) != first


def test_irrelevant_encoding_options_do_not_change_candidate_identity() -> None:
    item = source(MediaType.VIDEO)
    png_low_jpeg_quality = CandidatePoolSettings(
        candidate_fps=parse_fps("2"),
        encoding=CandidateEncodingSettings(
            image_format=ImageFormat.PNG,
            jpeg_qscale=2,
            png_compression_level=6,
        ),
    )
    png_high_jpeg_quality = CandidatePoolSettings(
        candidate_fps=parse_fps("2"),
        encoding=CandidateEncodingSettings(
            image_format=ImageFormat.PNG,
            jpeg_qscale=20,
            png_compression_level=6,
        ),
    )
    assert candidate_recipe_key(
        sources=(item,), settings=png_low_jpeg_quality, backend=BACKEND
    ) == candidate_recipe_key(
        sources=(item,), settings=png_high_jpeg_quality, backend=BACKEND
    )
    jpeg_low_png = CandidatePoolSettings(
        candidate_fps=parse_fps("2"),
        encoding=CandidateEncodingSettings(
            image_format=ImageFormat.JPEG,
            jpeg_qscale=2,
            png_compression_level=1,
        ),
    )
    jpeg_high_png = CandidatePoolSettings(
        candidate_fps=parse_fps("2"),
        encoding=CandidateEncodingSettings(
            image_format=ImageFormat.JPEG,
            jpeg_qscale=2,
            png_compression_level=9,
        ),
    )
    assert candidate_recipe_key(
        sources=(item,), settings=jpeg_low_png, backend=BACKEND
    ) == candidate_recipe_key(
        sources=(item,), settings=jpeg_high_png, backend=BACKEND
    )


def test_selection_key_uses_candidate_semantics_not_artifact_uuid() -> None:
    item = source(MediaType.VIDEO)
    value = candidate(video_view(item, 0), video_view(item, 10))
    digest = candidate_semantic_digest(value)
    first = selection_recipe_key(
        candidate=value,
        candidate_digest=digest,
        settings=FixedFpsSettings(target_fps=parse_fps("1")),
    )
    assert handle(value, artifact_id=uuid4()).semantic_digest == handle(
        value, artifact_id=uuid4()
    ).semantic_digest
    second = selection_recipe_key(
        candidate=value,
        candidate_digest=digest,
        settings=FixedFpsSettings(target_fps=parse_fps("2")),
    )
    assert first != second


def test_photo_only_selection_key_preserves_resolved_target_fps_metadata() -> None:
    item = source(MediaType.PHOTO)
    value = candidate(photo_view(item))
    digest = candidate_semantic_digest(value)
    one = selection_recipe_key(
        candidate=value,
        candidate_digest=digest,
        settings=FixedFpsSettings(target_fps=parse_fps("1")),
    )
    ten = selection_recipe_key(
        candidate=value,
        candidate_digest=digest,
        settings=FixedFpsSettings(target_fps=parse_fps("10")),
    )
    assert one != ten
