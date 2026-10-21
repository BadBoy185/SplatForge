from __future__ import annotations

import hashlib
import json
import os
import subprocess
from collections import defaultdict
from datetime import UTC, datetime
from fractions import Fraction
from pathlib import Path
from uuid import uuid4

import pytest

from splatforge.adapters.artifact_validation import (
    stream_sha256,
    validate_workspace_output,
)
from splatforge.adapters.ffmpeg import FFmpegAdapter
from splatforge.core.media import (
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
    CandidateView,
    CandidateViewSet,
    FrameTimestamp,
    ImageFormat,
    PixelTransform,
    deterministic_video_view_id,
    parse_fps,
)


def configured_ffmpeg() -> str:
    configured = os.environ.get("SPLATFORGE_TEST_FFMPEG")
    if not configured:
        pytest.skip("SPLATFORGE_TEST_FFMPEG is not configured")
    if configured.lower() in {"1", "true", "yes"}:
        return os.environ.get("SPLATFORGE_FFMPEG", "ffmpeg")
    return configured


def configured_ffprobe() -> str:
    configured = os.environ.get("SPLATFORGE_TEST_FFPROBE")
    if not configured:
        pytest.skip("SPLATFORGE_TEST_FFPROBE is not configured")
    return configured


def ppm(path: Path, rgb: tuple[int, int, int]) -> None:
    path.write_bytes(b"P6\n4 2\n255\n" + bytes(rgb) * 8)


def test_real_ffmpeg_preserves_vfr_pts_explicit_rotation_and_original_bytes(
    tmp_path: Path,
) -> None:
    executable = configured_ffmpeg()
    ffprobe = configured_ffprobe()
    frames = []
    for index, color in enumerate(((255, 0, 0), (0, 255, 0), (0, 0, 255))):
        path = tmp_path / f"source-{index}.ppm"
        ppm(path, color)
        frames.append(path)
    concat = tmp_path / "vfr.concat"
    concat.write_text(
        "file 'source-0.ppm'\nduration 0.12\n"
        "file 'source-1.ppm'\nduration 0.37\n"
        "file 'source-2.ppm'\nduration 0.21\n"
        "file 'source-2.ppm'\n",
        encoding="utf-8",
    )
    video = tmp_path / "uneven presentation.mp4"
    generated = subprocess.run(
        [
            executable,
            "-hide_banner",
            "-nostdin",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat),
            "-fps_mode",
            "vfr",
            "-c:v",
            "mpeg4",
            "-q:v",
            "2",
            "-output_ts_offset",
            "5",
            str(video),
        ],
        cwd=tmp_path,
        shell=False,
        check=False,
        capture_output=True,
        timeout=30,
    )
    if generated.returncode != 0:
        pytest.fail(
            "configured FFmpeg cannot generate the tiny MPEG-4 VFR fixture: "
            + generated.stderr.decode("utf-8", errors="replace")[:300]
        )
    original = video.read_bytes()
    oracle_result = subprocess.run(
        [ffprobe, "-v", "error", "-select_streams", "v:0", "-show_frames",
         "-show_streams", "-of", "json", str(video)],
        cwd=tmp_path, shell=False, capture_output=True, check=True, timeout=30,
    )
    oracle = json.loads(oracle_result.stdout)
    source_time_base = Fraction(oracle["streams"][0]["time_base"])
    source_times = [int(frame["pts"]) * source_time_base for frame in oracle["frames"]]
    assert source_times[0] >= 5
    digest = hashlib.sha256(original).hexdigest()
    stat = video.stat()
    evidence = SourceEvidence(
        size=stat.st_size,
        last_write_ns=stat.st_mtime_ns,
        volume_id=str(stat.st_dev),
        file_id=str(stat.st_ino),
        change_time_ns=stat.st_ctime_ns,
        storage_kind=StorageKind.UNKNOWN,
        evidence_available=True,
    )
    now = datetime.now(UTC)
    adapter = FFmpegAdapter(executable=executable)
    backend = adapter.identity()
    source = SourceOccurrence(
        source_id=uuid4(),
        source_revision=1,
        external_locator=str(video),
        display_filename=video.name,
        media_type=MediaType.VIDEO,
        extension=".mp4",
        byte_size=len(original),
        content_sha256=digest,
        last_full_hash_at=now,
        full_hash_evidence=FullHashEvidence(
            hashed_at=now,
            byte_count=len(original),
            evidence_before=evidence,
            evidence_after=evidence,
            stability_mechanism="integration_fixture",
        ),
        source_group_id=uuid4(),
        camera_group_id=uuid4(),
        probe=NormalizedProbe(
            backend=backend,
            selected_visual_stream_index=0,
            codec_name="mpeg4",
            width=4,
            height=2,
            time_base="1/12800",
            duration="0.8",
            rotation_degrees=90,
        ),
    )
    settings = CandidatePoolSettings(
        candidate_fps=parse_fps("100"),
        encoding=CandidateEncodingSettings(
            image_format=ImageFormat.PNG,
            png_compression_level=1,
        ),
    )
    decoded = tmp_path / "decoded"
    materialized = adapter.materialize(
        video,
        source,
        decoded,
        settings,
        timeout_seconds=30,
        expected_backend=backend,
    )
    assert len(materialized) >= 3
    actual_times = [frame.pts * frame.time_base.as_fraction() for frame in materialized]
    assert actual_times == source_times
    assert actual_times[0] != 0
    intervals = [
        right - left
        for left, right in zip(actual_times, actual_times[1:], strict=False)
    ]
    assert len(set(intervals)) > 1
    target_grid = [Fraction(index, 100) for index in range(len(actual_times))]
    assert actual_times != target_grid

    output = tmp_path / "output"
    images = output / "images"
    images.mkdir(parents=True)
    occurrences: defaultdict[tuple[int, int, int], int] = defaultdict(int)
    views = []
    for frame in materialized:
        key = (frame.pts, frame.time_base.numerator, frame.time_base.denominator)
        occurrence = occurrences[key]
        occurrences[key] += 1
        view_id = deterministic_video_view_id(
            source,
            pts=frame.pts,
            time_base=frame.time_base,
            occurrence_index=occurrence,
        )
        destination = images / f"{view_id}.png"
        frame.temporary_path.replace(destination)
        _, image_digest = stream_sha256(destination)
        views.append(
            CandidateView(
                view_id=view_id,
                source_id=source.source_id,
                source_revision=1,
                source_content_sha256=digest,
                source_group_id=source.source_group_id,
                camera_group_id=source.camera_group_id,
                media_type=MediaType.VIDEO,
                selected_visual_stream_index=0,
                frame_identity=(
                    f"pts:{frame.pts}@{frame.time_base.numerator}/"
                    f"{frame.time_base.denominator}"
                ),
                occurrence_index=occurrence,
                presentation_timestamp=FrameTimestamp(
                    pts=frame.pts, time_base=frame.time_base
                ),
                image_path=f"images/{view_id}.png",
                image_sha256=image_digest,
                width=2,
                height=4,
                transform=PixelTransform(
                    source_width=4,
                    source_height=2,
                    orientation_operation="rotate_90_ccw",
                    output_width=2,
                    output_height=4,
                ),
            )
        )
    candidate = CandidateViewSet(backend=backend, settings=settings, views=tuple(views))
    (output / "candidate_views.json").write_text(
        candidate.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )

    validated = validate_workspace_output(output, CANDIDATE_ARTIFACT_TYPE)

    assert validated.parsed == candidate
    assert all((output / view.image_path).is_file() for view in candidate.views)
    assert video.read_bytes() == original
