"""Opt-in generated media: old full scratch versus exact prewrite Trim admission."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import time
from dataclasses import replace
from fractions import Fraction
from pathlib import Path

import pytest
from PIL import Image
from test_ffmpeg_integration import configured_ffmpeg, configured_ffprobe

from splatforge.adapters.execution_storage import LocalExecutionRepository
from splatforge.adapters.ffmpeg import FFmpegAdapter
from splatforge.adapters.process_runner import LocalProcessRunner
from splatforge.application.video_usage import video_usage_draft
from splatforge.application.views_contracts import FFmpegCancelledError
from splatforge.bootstrap import build_media_service, build_project_service, build_views_service
from splatforge.core.media import VerificationPolicyId
from splatforge.core.quality import QualityAnalysisSettings, SharpestIntervalSettings
from splatforge.core.video_usage import VideoSource, interval
from splatforge.core.views import (
    CandidateEncodingSettings,
    CandidatePoolSettings,
    CandidateResourceLimits,
    FixedFpsSettings,
    ImageFormat,
    parse_fps,
)


class ScratchMeasurement(FFmpegAdapter):
    def __init__(self, executable: str, *, legacy: bool) -> None:
        super().__init__(executable=executable)
        self.legacy = legacy
        self.observations: list[dict[str, int]] = []

    def materialize(self, *args, used_intervals=None, **kwargs):
        frames = super().materialize(
            *args, used_intervals=None if self.legacy else used_intervals, **kwargs
        )
        scratch = list(args[2].iterdir())
        self.observations.append({
            "images": len(scratch), "bytes": sum(path.stat().st_size for path in scratch),
        })
        return frames


def generated_video(tmp_path: Path, ffmpeg: str, ffprobe: str, *, vfr: bool):
    for index in range(6):
        image = Image.new("RGB", (32, 24))
        image.putdata([
            ((x * 37 + index * 31) % 256, (y * 43 + index * 61) % 256,
             ((x + y) * 29 + index * 71) % 256)
            for y in range(24) for x in range(32)
        ])
        image.save(tmp_path / f"pattern-{index}.ppm")
    durations = ["0.12", "0.37", "0.41", "0.21", "0.39", "0.18"] if vfr else ["0.2"] * 6
    concat = tmp_path / "generated.concat"
    concat.write_text("".join(
        f"file 'pattern-{index}.ppm'\nduration {duration}\n"
        for index, duration in enumerate(durations)
    ) + "file 'pattern-5.ppm'\n", encoding="utf-8")
    video = tmp_path / "Generated ž VFR.mp4"
    subprocess.run(
        [ffmpeg, "-hide_banner", "-nostdin", "-loglevel", "error", "-y",
         "-f", "concat", "-safe", "0", "-i", str(concat), "-fps_mode", "vfr",
         "-c:v", "mpeg4", "-q:v", "2", "-output_ts_offset", "5" if vfr else "0",
         str(video)],
        cwd=tmp_path, shell=False, check=True, capture_output=True, timeout=30,
    )
    oracle = json.loads(subprocess.run(
        [ffprobe, "-v", "error", "-select_streams", "v:0", "-show_frames",
         "-show_streams", "-of", "json", str(video)],
        cwd=tmp_path, shell=False, capture_output=True, check=True, timeout=30,
    ).stdout)
    time_base = Fraction(oracle["streams"][0]["time_base"])
    times = [int(frame["pts"]) * time_base for frame in oracle["frames"]]
    assert times[0] == (5 if vfr else 0)
    if vfr:
        assert len({b - a for a, b in zip(times, times[1:], strict=False)}) > 1
    return video, times, time_base


@pytest.mark.parametrize("vfr", [False, True], ids=["regular-zero-origin", "vfr-nonzero"])
@pytest.mark.parametrize("image_format", [ImageFormat.JPEG, ImageFormat.PNG])
def test_generated_trim_matches_old_pixels_pts_ids_both_selectors_and_cache(
    tmp_path: Path, vfr: bool, image_format: ImageFormat,
):
    ffmpeg, ffprobe = configured_ffmpeg(), configured_ffprobe()
    video, times, time_base = generated_video(tmp_path, ffmpeg, ffprobe, vfr=vfr)
    original_hash = hashlib.sha256(video.read_bytes()).hexdigest()
    projects = build_project_service()
    seed = tmp_path / "Seed project"
    projects.create(seed, "Generated Trim comparison")
    media = build_media_service(ffprobe_path=ffprobe)
    media.add(seed, [video])
    source_occurrence = media.list(seed).sources[0]
    source = VideoSource.from_source(source_occurrence)
    document = projects.open(seed)
    # Include start exactly and exclude end exactly; retain two disjoint pieces.
    ranges = [(times[0], times[1]), (times[3], times[5])]
    for start, end in ranges:
        document = video_usage_draft(document, source, "add", interval(str(start), str(end)))
    projects.save(seed, document)
    encoding = CandidatePoolSettings(
        candidate_fps=parse_fps("4"),
        encoding=CandidateEncodingSettings(image_format=image_format),
    )
    full = FFmpegAdapter(executable=ffmpeg)
    baseline_frames = full.materialize(
        video, source_occurrence, tmp_path / "Full-grid oracle", encoding,
        expected_backend=full.identity(), timeout_seconds=30,
    )
    expected = [frame for frame in baseline_frames if any(
        a <= frame.pts * frame.time_base.as_fraction() < b for a, b in ranges
    )]
    assert 0 < len(expected) < len(baseline_frames)
    expected_times = [frame.pts * frame.time_base.as_fraction() for frame in expected]
    assert times[0] in expected_times
    assert times[1] not in expected_times and times[5] not in expected_times
    results = {}
    measurements = {}
    for mode in ("legacy", "trim"):
        root = tmp_path / f"{mode} project"
        shutil.copytree(seed, root)
        service = build_views_service(ffmpeg_path=ffmpeg, performance_path=tmp_path / f"{mode}.db")
        meter = ScratchMeasurement(ffmpeg, legacy=mode == "legacy")
        service._materializer = meter
        method_results = {}
        for method in ("fixed", "sharpest"):
            arguments = {
                "candidate_settings": encoding,
                "selection_settings": (
                    FixedFpsSettings(target_fps=parse_fps("1")) if method == "fixed"
                    else SharpestIntervalSettings(target_fps=parse_fps("1"),
                                                  reject_duplicates=False)
                ),
                "resource_limits": CandidateResourceLimits(
                    max_candidates=100, max_candidate_bytes=10**7,
                ),
                "verification_policy": VerificationPolicyId.STRICT,
            }
            if method == "sharpest":
                arguments["quality_settings"] = QualityAnalysisSettings()
            run = service.prepare(root, **arguments)
            assert run.status == "succeeded"
            repository = LocalExecutionRepository()
            candidate = repository.load_candidate_views(root, run.candidate_artifact)
            assert [v.presentation_timestamp.seconds() for v in candidate.views] == expected_times
            assert all(view.presentation_timestamp.time_base.as_fraction() == time_base
                       for view in candidate.views)
            assert [view.image_sha256 for view in candidate.views] == [
                hashlib.sha256(frame.temporary_path.read_bytes()).hexdigest() for frame in expected
            ]
            selected = repository.load_selected_views(root, run.selected_artifact)
            assert selected.selected_views
            method_results[method] = (run, candidate, selected)
            again = service.prepare(root, **arguments)
            assert "candidate_views" in again.cache_hits and "selected_views" in again.cache_hits
            if method == "sharpest":
                assert "quality_assessment" in again.cache_hits
        assert len(meter.observations) == 1  # both selectors and retries share candidates
        measurements[mode] = meter.observations[0]
        results[mode] = method_results
    for method in ("fixed", "sharpest"):
        old_run, old_candidate, old_selection = results["legacy"][method]
        new_run, new_candidate, new_selection = results["trim"][method]
        assert old_candidate == new_candidate
        assert old_run.candidate_artifact.recipe_key == new_run.candidate_artifact.recipe_key
        assert (old_run.candidate_artifact.semantic_digest
                == new_run.candidate_artifact.semantic_digest)
        assert (old_run.selected_artifact.semantic_digest
                == new_run.selected_artifact.semantic_digest)
        assert old_selection.selected_views == new_selection.selected_views
        if method == "sharpest":
            assert (old_run.quality_artifact.semantic_digest
                    == new_run.quality_artifact.semantic_digest)
            assert old_selection.decisions == new_selection.decisions
            assert old_selection.unsatisfied_intervals == new_selection.unsatisfied_intervals
        else:
            assert old_selection.unsatisfied_slots == new_selection.unsatisfied_slots
    assert measurements["legacy"]["images"] == len(baseline_frames)
    assert measurements["trim"]["images"] == len(expected)
    assert measurements["trim"]["bytes"] < measurements["legacy"]["bytes"]
    assert hashlib.sha256(video.read_bytes()).hexdigest() == original_hash
    report = {"vfr": vfr, "format": image_format.value, **measurements,
              "retained_source_times": [str(t) for t in expected_times],
              "candidate_semantic_digest": (
                  results["trim"]["fixed"][0].candidate_artifact.semantic_digest)}
    (tmp_path / "scratch-measurement.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    print(json.dumps(report))


def test_generated_short_middle_end_disjoint_empty_and_unrestricted_scratch(tmp_path):
    ffmpeg, ffprobe = configured_ffmpeg(), configured_ffprobe()
    video, times, _ = generated_video(tmp_path, ffmpeg, ffprobe, vfr=False)
    original = video.read_bytes()
    root = tmp_path / "Matrix project"
    build_project_service().create(root, "Tiny matrix")
    media = build_media_service(ffprobe_path=ffprobe)
    media.add(root, [video])
    source = media.list(root).sources[0]
    adapter = FFmpegAdapter(executable=ffmpeg)
    backend = adapter.identity()
    settings = CandidatePoolSettings(
        candidate_fps=parse_fps("4"), encoding=CandidateEncodingSettings(),
    )
    baseline = adapter.materialize(
        video, source, tmp_path / "Full", settings, expected_backend=backend,
        timeout_seconds=30,
    )
    first = baseline[0].pts * baseline[0].time_base.as_fraction()
    last = baseline[-1].pts * baseline[-1].time_base.as_fraction()
    variants = {
        "unrestricted": None,
        "single_short": (interval(str(first), str(first + Fraction(1, 100))),),
        "middle_off_grid": (interval(str(times[1]), str(times[4])),),
        "near_end": (interval(str(last), str(last + Fraction(1, 100))),),
        "disjoint": (interval(str(first), str(times[1])),
                     interval(str(last), str(last + Fraction(1, 100)))),
        "explicit_empty": (),
        "no_sample": (interval(str(first + Fraction(1, 100)),
                               str(first + Fraction(2, 100))),),
    }
    reports = {}
    for name, used in variants.items():
        evidence = []
        directory = tmp_path / name
        actual = adapter.materialize(
            video, source, directory, settings, expected_backend=backend,
            timeout_seconds=30, used_intervals=used, evidence_sink=evidence.append,
        )
        expected = [frame for frame in baseline if used is None or any(
            item.start.as_fraction() <= frame.pts * frame.time_base.as_fraction()
            < item.end.as_fraction() for item in used
        )]
        assert [(f.sequence_index, f.pts, f.time_base) for f in actual] == [
            (f.sequence_index, f.pts, f.time_base) for f in expected
        ]
        assert [hashlib.sha256(f.temporary_path.read_bytes()).hexdigest() for f in actual] == [
            hashlib.sha256(f.temporary_path.read_bytes()).hexdigest() for f in expected
        ]
        assert len(list(directory.iterdir())) == len(expected)
        if name == "explicit_empty":
            assert evidence == []
        elif name == "no_sample":
            assert len(evidence) == 1
        reports[name] = {"images": len(actual),
                         "bytes": sum(path.stat().st_size for path in directory.iterdir())}
    assert reports["single_short"]["images"] == reports["near_end"]["images"] == 1
    assert reports["explicit_empty"]["images"] == reports["no_sample"]["images"] == 0
    assert video.read_bytes() == original
    assert not list(tmp_path.glob(".ffmpeg-*"))
    (tmp_path / "matrix-measurements.json").write_text(
        json.dumps(reports, indent=2), encoding="utf-8"
    )
    print(json.dumps(reports))


@pytest.mark.parametrize("phase", ["timestamps", "images"])
def test_real_contained_trim_cancellation_stops_the_running_pass(tmp_path, phase):
    ffmpeg, ffprobe = configured_ffmpeg(), configured_ffprobe()
    video, _, _ = generated_video(tmp_path, ffmpeg, ffprobe, vfr=False)
    original = video.read_bytes()
    root = tmp_path / "Cancellation project"
    build_project_service().create(root, "Cancellation")
    media = build_media_service(ffprobe_path=ffprobe)
    media.add(root, [video])
    source = media.list(root).sources[0]

    class Cancellation:
        started = None

        def is_cancelled(self):
            return self.started is not None and time.monotonic() - self.started > 0.7

    signal = Cancellation()
    cancelled_results = []

    class PacedRunner(LocalProcessRunner):
        def run(self, request, *, cancellation=None, poll=None):
            # Test-only pacing guarantees the tiny real process is still decoding
            # when cancellation is requested. Production input arguments stay intact.
            target = ("-i" in request.argv and (
                (phase == "timestamps" and request.argv[-1] == "-")
                or (phase == "images" and request.argv[-1] != "-")
            ))
            if target:
                argv = list(request.argv)
                position = argv.index("-i")
                argv[position:position] = ["-re", "-threads", "1"]
                request = replace(request, argv=tuple(argv))
                signal.started = time.monotonic()
            try:
                result = super().run(request, cancellation=cancellation, poll=poll)
                if target:
                    cancelled_results.append(result)
                return result
            finally:
                if target:
                    signal.started = None

    adapter = FFmpegAdapter(runner=PacedRunner(), executable=ffmpeg)
    backend = adapter.identity()
    evidence = []
    with pytest.raises(FFmpegCancelledError) as error:
        adapter.materialize(
            video, source, tmp_path / "Cancelled frames",
            CandidatePoolSettings(
                candidate_fps=parse_fps("4"), encoding=CandidateEncodingSettings(),
            ),
            expected_backend=backend, timeout_seconds=30,
            used_intervals=(interval("0", "2"),), cancellation=signal,
            evidence_sink=evidence.append,
        )
    assert error.value.teardown_confirmed
    assert len(cancelled_results) == 1
    result = cancelled_results[0]
    assert result.cancelled and result.teardown_confirmed
    assert b"showinfo" in result.stderr  # FFmpeg itself began decoding before cancellation
    assert evidence[-1].cancelled and evidence[-1].teardown_confirmed
    assert not list(tmp_path.glob(".ffmpeg-*"))
    assert video.read_bytes() == original
    # A completed contained teardown releases both the source and partial outputs.
    with video.open("r+b"):
        pass
    for path in (tmp_path / "Cancelled frames").iterdir():
        with path.open("r+b"):
            pass
