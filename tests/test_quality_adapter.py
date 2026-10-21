from __future__ import annotations

import hashlib
from pathlib import Path
from uuid import UUID

from PIL import Image, ImageDraw, ImageFilter

from splatforge.adapters.quality import PillowQualityAdapter
from splatforge.core.media import ExecutableIdentity, MediaType
from splatforge.core.quality import (
    MeasurementAvailability,
    QualityAnalysisSettings,
    QualityReport,
    hamming_distance64,
    validate_quality_against_candidate,
)
from splatforge.core.views import (
    CandidateEncodingSettings,
    CandidatePoolSettings,
    CandidateView,
    CandidateViewSet,
    ImageFormat,
    PixelTransform,
    candidate_semantic_digest,
    parse_fps,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _view(path: Path, identity: int) -> CandidateView:
    view_id = UUID(int=identity)
    return CandidateView(
        view_id=view_id,
        source_id=UUID(int=100 + identity),
        source_revision=1,
        source_content_sha256=f"{identity:x}" * 64,
        source_group_id=UUID(int=200 + identity),
        camera_group_id=UUID(int=300 + identity),
        media_type=MediaType.PHOTO,
        selected_visual_stream_index=0,
        frame_identity="photo_singleton",
        occurrence_index=0,
        presentation_timestamp=None,
        image_path=f"images/{path.name}",
        image_sha256=_sha256(path),
        width=64,
        height=64,
        transform=PixelTransform(
            source_width=64,
            source_height=64,
            orientation_operation="identity",
            output_width=64,
            output_height=64,
        ),
    )


def test_real_pillow_quality_fixture_is_deterministic_and_non_mutating(
    tmp_path: Path,
) -> None:
    images = tmp_path / "images"
    images.mkdir()
    sharp_path = images / f"{UUID(int=1)}.png"
    blurred_path = images / f"{UUID(int=2)}.png"
    duplicate_path = images / f"{UUID(int=3)}.png"
    near_path = images / f"{UUID(int=4)}.png"

    checker = Image.new("L", (64, 64), 0)
    draw = ImageDraw.Draw(checker)
    for y in range(0, 64, 4):
        for x in range(0, 64, 4):
            if (x // 4 + y // 4) % 2 == 0:
                draw.rectangle((x, y, x + 3, y + 3), fill=255)
    checker.save(sharp_path, format="PNG")
    checker.save(duplicate_path, format="PNG")
    blurred = checker.filter(ImageFilter.GaussianBlur(radius=3))
    blurred.save(blurred_path, format="PNG")
    near = checker.copy()
    near_draw = ImageDraw.Draw(near)
    near_draw.rectangle((0, 0, 7, 31), fill=0)
    near.save(near_path, format="PNG")
    checker.close()
    blurred.close()
    near.close()

    before = {path: path.read_bytes() for path in images.iterdir()}
    views = tuple(
        _view(path, index)
        for index, path in enumerate((sharp_path, blurred_path, duplicate_path, near_path), start=1)
    )
    candidate = CandidateViewSet(
        backend=ExecutableIdentity(
            resolved_path="C:/Tools/ffmpeg.exe",
            size=1,
            last_write_ns=1,
            sha256="a" * 64,
        ),
        settings=CandidatePoolSettings(
            candidate_fps=parse_fps("2"),
            encoding=CandidateEncodingSettings(
                image_format=ImageFormat.PNG,
                png_compression_level=6,
            ),
        ),
        views=views,
    )
    adapter = PillowQualityAdapter()
    settings = QualityAnalysisSettings(quality_max_side=64)
    measurements = tuple(
        adapter.measure(tmp_path / view.image_path, view, settings) for view in candidate.views
    )
    identity = adapter.identity()
    report = QualityReport(
        candidate_artifact_id=UUID(int=500),
        candidate_semantic_digest=candidate_semantic_digest(candidate),
        pillow_version=identity.pillow_version,
        python_version=identity.python_version,
        settings=settings,
        measurements=measurements,
    )
    validate_quality_against_candidate(report, candidate)

    scores = [item.sharpness.score for item in measurements]
    assert all(score is not None for score in scores)
    assert scores[0].as_fraction() > scores[1].as_fraction()  # type: ignore[union-attr]
    assert measurements[0].duplicate.dhash64 == measurements[2].duplicate.dhash64
    assert (
        hamming_distance64(
            measurements[0].duplicate.dhash64,  # type: ignore[arg-type]
            measurements[2].duplicate.dhash64,  # type: ignore[arg-type]
        )
        == 0
    )
    near_distance = hamming_distance64(
        measurements[0].duplicate.dhash64,  # type: ignore[arg-type]
        measurements[3].duplicate.dhash64,  # type: ignore[arg-type]
    )
    assert 0 < near_distance <= 16
    assert all(
        item.sharpness.availability == MeasurementAvailability.AVAILABLE for item in measurements
    )
    assert {path: path.read_bytes() for path in images.iterdir()} == before
    with Image.open(sharp_path) as unchanged:
        assert unchanged.size == (64, 64)


def test_too_small_image_has_unavailable_sharpness_but_stable_dhash(
    tmp_path: Path,
) -> None:
    images = tmp_path / "images"
    images.mkdir()
    path = images / f"{UUID(int=1)}.png"
    Image.new("L", (2, 2), 128).save(path)
    view = CandidateView(
        **{
            **_view(path, 1).model_dump(),
            "width": 2,
            "height": 2,
            "transform": PixelTransform(
                source_width=2,
                source_height=2,
                orientation_operation="identity",
                output_width=2,
                output_height=2,
            ),
        }
    )
    measured = PillowQualityAdapter().measure(
        path, view, QualityAnalysisSettings(quality_max_side=64)
    )
    assert measured.sharpness.availability == MeasurementAvailability.UNAVAILABLE
    assert measured.duplicate.availability == MeasurementAvailability.AVAILABLE
