"""Explicitly provisioned FFmpeg integration: real VFR, nonzero origin, published pixels."""

import json
import subprocess
from fractions import Fraction

from test_ffmpeg_integration import configured_ffmpeg, configured_ffprobe, ppm

from splatforge.adapters.execution_storage import LocalExecutionRepository
from splatforge.application.video_usage import video_usage_draft
from splatforge.bootstrap import build_media_service, build_project_service, build_views_service
from splatforge.core.media import VerificationPolicyId
from splatforge.core.video_usage import VideoSource, interval
from splatforge.core.views import (
    CandidateEncodingSettings,
    CandidatePoolSettings,
    CandidateResourceLimits,
    FixedFpsSettings,
    ImageFormat,
    parse_fps,
)


def test_real_restricted_vfr_publication_preserves_source_pts_and_original(tmp_path):
    ffmpeg, ffprobe = configured_ffmpeg(), configured_ffprobe()
    for index, color in enumerate(((255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0))):
        ppm(tmp_path / f"frame-{index}.ppm", color)
    concat = tmp_path / "vfr.concat"
    concat.write_text(
        "file 'frame-0.ppm'\nduration 0.12\n"
        "file 'frame-1.ppm'\nduration 0.37\n"
        "file 'frame-2.ppm'\nduration 0.41\n"
        "file 'frame-3.ppm'\nduration 0.21\nfile 'frame-3.ppm'\n",
        encoding="utf-8",
    )
    video = tmp_path / "Фрагменты VFR ž.mp4"
    subprocess.run(
        [
            ffmpeg,
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
        capture_output=True,
        check=True,
        timeout=30,
    )
    original = video.read_bytes()
    oracle = json.loads(
        subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_frames",
                "-show_streams",
                "-of",
                "json",
                str(video),
            ],
            cwd=tmp_path,
            shell=False,
            capture_output=True,
            check=True,
            timeout=30,
        ).stdout
    )
    time_base = Fraction(oracle["streams"][0]["time_base"])
    source_times = [int(f["pts"]) * time_base for f in oracle["frames"]]
    assert source_times[0] >= 5
    assert len(set(b - a for a, b in zip(source_times, source_times[1:], strict=False))) > 1
    root = tmp_path / "Real interval project"
    projects = build_project_service()
    projects.create(root, "Intervals")
    media = build_media_service(ffprobe_path=ffprobe)
    media.add(root, [video])
    source = VideoSource.from_source(media.list(root).sources[0])
    assert source.start.as_fraction() == source_times[0]
    assert source.player_time("120").as_fraction() == source_times[0] + Fraction(12, 100)
    # Two separate allowed pieces; the frame exactly at the first end is forbidden.
    ranges = [(source_times[0], source_times[1]), (source_times[3], source_times[-1])]
    document = projects.open(root)
    for start, end in ranges:
        document = video_usage_draft(document, source, "add", interval(str(start), str(end)))
    projects.save(root, document)
    service = build_views_service(ffmpeg_path=ffmpeg, performance_path=tmp_path / "perf.sqlite")
    result = service.prepare(
        root,
        candidate_settings=CandidatePoolSettings(
            candidate_fps=parse_fps("25"),
            encoding=CandidateEncodingSettings(image_format=ImageFormat.PNG),
        ),
        selection_settings=FixedFpsSettings(target_fps=parse_fps("10")),
        resource_limits=CandidateResourceLimits(max_candidates=100, max_candidate_bytes=10**7),
        verification_policy=VerificationPolicyId.STRICT,
    )
    assert result.status == "succeeded"
    repository = LocalExecutionRepository()
    candidates = repository.load_candidate_views(root, result.candidate_artifact)
    retained = [v.presentation_timestamp.seconds() for v in candidates.views]
    assert retained == [source_times[0], source_times[3]]
    assert all(any(a <= t < b for a, b in ranges) for t in retained)
    assert all(v.source_id == source.source_id for v in candidates.views)
    assert all(
        v.presentation_timestamp.time_base.as_fraction() == time_base for v in candidates.views
    )
    selected = repository.load_selected_views(root, result.selected_artifact)
    assert {v.view_id for v in selected.selected_views} <= {v.view_id for v in candidates.views}
    assert {v.actual_presentation_time.as_fraction() for v in selected.selected_views} == set(
        retained
    )
    manifest = json.loads((root / result.candidate_artifact.manifest_path).read_text())
    assert len(manifest["payloads"]) == len(retained) + 1  # no excluded scratch images published
    assert video.read_bytes() == original
