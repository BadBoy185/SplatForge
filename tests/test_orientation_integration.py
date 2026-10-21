"""Independent real-media oracles for display matrices and all PNG EXIF transforms."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from PIL import Image
from test_ffmpeg import source
from test_ffmpeg_integration import configured_ffmpeg, configured_ffprobe

from splatforge.adapters.ffmpeg import FFmpegAdapter
from splatforge.adapters.ffprobe import FFprobeAdapter
from splatforge.core.media import MediaType
from splatforge.core.views import (
    CandidateEncodingSettings,
    CandidatePoolSettings,
    ImageFormat,
    parse_fps,
)


def run(executable: str, cwd: Path, *args: str) -> bytes:
    result = subprocess.run(
        [executable, "-nostdin", "-hide_banner", "-loglevel", "error", *args],
        cwd=cwd, shell=False, capture_output=True, check=True, timeout=30,
    )
    return result.stdout


def asymmetric(path: Path) -> None:
    with Image.new("RGB", (4, 2)) as image:
        image.putdata([
            (255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0),
            (255, 0, 255), (0, 255, 255), (0, 0, 0), (255, 255, 255),
        ])
        image.save(path)


def pixels(path: Path) -> tuple[tuple[int, int], bytes]:
    with Image.open(path) as image:
        return image.size, image.convert("RGB").tobytes()


@pytest.fixture
def real_tools() -> tuple[str, str]:
    return configured_ffmpeg(), configured_ffprobe()


@pytest.mark.parametrize(
    "angle,transpose",
    [(0, None), (90, Image.Transpose.ROTATE_90), (-90, Image.Transpose.ROTATE_270),
     (180, Image.Transpose.ROTATE_180), (270, Image.Transpose.ROTATE_270)],
)
def test_real_display_matrix_matches_asymmetric_pixels_and_autorotate(
    tmp_path: Path, real_tools: tuple[str, str], angle: int, transpose: Image.Transpose | None,
) -> None:
    ffmpeg, ffprobe = real_tools
    photo = tmp_path / "asymmetric.png"
    asymmetric(photo)
    base = tmp_path / "base.mov"
    video = tmp_path / "display.mov"
    run(ffmpeg, tmp_path, "-i", str(photo), "-frames:v", "1", "-c:v", "png", str(base))
    run(ffmpeg, tmp_path, "-display_rotation", str(angle), "-i", str(base),
        "-c", "copy", str(video))
    original = video.read_bytes()
    probe = FFprobeAdapter(executable=ffprobe).probe(video, MediaType.VIDEO)
    assert (probe.rotation_degrees or 0) % 360 == angle % 360
    item = source(MediaType.VIDEO).model_copy(update={"probe": probe})
    adapter = FFmpegAdapter(executable=ffmpeg)
    frames = adapter.materialize(
        video, item, tmp_path / "explicit", CandidatePoolSettings(
            candidate_fps=parse_fps("100"),
            encoding=CandidateEncodingSettings(image_format=ImageFormat.PNG),
        ), timeout_seconds=30, expected_backend=adapter.identity(),
    )
    reference = tmp_path / "automatic.png"
    run(ffmpeg, tmp_path, "-i", str(video), "-frames:v", "1", str(reference))
    with Image.open(photo) as image:
        expected = image.transpose(transpose) if transpose is not None else image.copy()
        try:
            expected_pixels = expected.size, expected.tobytes()
        finally:
            expected.close()
    assert pixels(frames[0].temporary_path) == expected_pixels
    assert pixels(reference) == expected_pixels
    assert video.read_bytes() == original


@pytest.mark.parametrize("orientation,transpose", [
    (1, None), (2, Image.Transpose.FLIP_LEFT_RIGHT), (3, Image.Transpose.ROTATE_180),
    (4, Image.Transpose.FLIP_TOP_BOTTOM), (5, Image.Transpose.TRANSPOSE),
    (6, Image.Transpose.ROTATE_270), (7, Image.Transpose.TRANSVERSE),
    (8, Image.Transpose.ROTATE_90),
])
def test_real_png_exif_all_orientations_preserve_pixels_and_original_bytes(
    tmp_path: Path, real_tools: tuple[str, str], orientation: int,
    transpose: Image.Transpose | None,
) -> None:
    ffmpeg, ffprobe = real_tools
    photo = tmp_path / "oriented.png"
    asymmetric(photo)
    with Image.open(photo) as image:
        exif = Image.Exif()
        exif[274] = orientation
        image.save(tmp_path / "with-exif.png", exif=exif)
        expected = image.transpose(transpose) if transpose is not None else image.copy()
        try:
            expected_pixels = expected.size, expected.tobytes()
        finally:
            expected.close()
    photo = tmp_path / "with-exif.png"
    original = photo.read_bytes()
    probe = FFprobeAdapter(executable=ffprobe).probe(photo, MediaType.PHOTO)
    assert probe.orientation == orientation
    item = source(MediaType.PHOTO).model_copy(update={"probe": probe, "extension": ".png"})
    adapter = FFmpegAdapter(executable=ffmpeg)
    frames = adapter.materialize(
        photo, item, tmp_path / "explicit", CandidatePoolSettings(
            candidate_fps=parse_fps("100"),
            encoding=CandidateEncodingSettings(image_format=ImageFormat.PNG),
        ), timeout_seconds=30, expected_backend=adapter.identity(),
    )
    assert pixels(frames[0].temporary_path) == expected_pixels
    assert photo.read_bytes() == original
