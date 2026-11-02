"""Exact Trim admission happens before any encoded scratch image is written."""

from pathlib import Path

import pytest
from test_ffmpeg import IDENTITY, SHOWINFO, FakeRunner, result, settings, source

from splatforge.adapters.ffmpeg import FFmpegAdapter
from splatforge.application.views_contracts import (
    FFmpegBackendError,
    FFmpegCancelledError,
    FFmpegOutputError,
    FFmpegTimeoutError,
)
from splatforge.core.media import MediaType
from splatforge.core.video_usage import interval


def extract(tmp_path, runner, intervals, **kwargs):
    item = source(MediaType.VIDEO)
    return FFmpegAdapter(runner=runner, **kwargs).materialize(
        Path(item.external_locator), item, tmp_path / "frames", settings(),
        expected_backend=IDENTITY, timeout_seconds=30, used_intervals=intervals,
    )


def test_exact_prepass_writes_only_admitted_original_grid_candidate(tmp_path):
    evidence = []

    def callback(request, index):
        assert request.expected_executable == IDENTITY
        assert request.max_stderr_bytes == 8 * 1024 * 1024
        if index == 0:
            assert request.argv[-3:] == ("-f", "null", "-")
            assert not list((tmp_path / "frames").iterdir())
            return result(request, stderr=SHOWINFO)
        script = Path(request.argv[request.argv.index("-filter_script:v") + 1]).read_text()
        assert "between(n\\,1\\,1)" in script
        assert script.index("prev_selected_t") < script.index("between(n")
        assert "-ss" not in request.argv
        Path(str(request.argv[-1]).replace("%08d", "00000000")).write_bytes(b"included")
        return result(request, stderr=SHOWINFO.replace(
            b"n:   0 pts:      0 pts_time:0 pos:0\n", b""
        ).replace(b"n:   1", b"n:   0"))

    item = source(MediaType.VIDEO)
    runner = FakeRunner(callback)
    frames = FFmpegAdapter(runner=runner).materialize(
        Path(item.external_locator), item, tmp_path / "frames", settings(),
        expected_backend=IDENTITY, timeout_seconds=30,
        used_intervals=(interval("417/1000", "1/2"),), evidence_sink=evidence.append,
    )
    assert len(runner.requests) == 2
    assert frames[0].sequence_index == 1
    assert frames[0].pts == 417
    assert frames[0].temporary_path.read_bytes() == b"included"
    assert [item.tool_role for item in evidence] == [
        "ffmpeg.candidate_timestamps", "ffmpeg.materialize"
    ]
    assert not list(tmp_path.glob(".ffmpeg-*"))


def test_admission_does_not_round_large_pts_or_fractional_endpoints(tmp_path):
    pts = 2**53 + 1
    metadata = (
        "config in time_base: 1/1000\n"
        f"n: 0 pts: {pts} pts_time:0\n"
        f"n: 1 pts: {pts + 1} pts_time:0\n"
    ).encode()

    def callback(request, index):
        if index == 0:
            return result(request, stderr=metadata)
        Path(str(request.argv[-1]).replace("%08d", "00000000")).write_bytes(b"included")
        return result(request, stderr=metadata.split(b"n: 1")[0])

    frames = extract(
        tmp_path, FakeRunner(callback),
        (interval(f"{pts}/1000", f"{pts + 1}/1000"),),
    )
    assert [frame.pts for frame in frames] == [pts]


@pytest.mark.parametrize("intervals, expected_calls", [
    ((), 0), ((interval("1/10", "1/5"),), 1),
])
def test_empty_union_or_no_sample_creates_no_scratch_images(tmp_path, intervals, expected_calls):
    runner = FakeRunner(lambda request, index: result(request, stderr=SHOWINFO))
    assert extract(tmp_path, runner, intervals) == ()
    assert len(runner.requests) == expected_calls
    assert list((tmp_path / "frames").iterdir()) == []


@pytest.mark.parametrize("phase", [0, 1])
def test_cancellation_of_either_owned_pass_preserves_teardown_failure_contract(tmp_path, phase):
    def callback(request, index):
        return result(request, stderr=SHOWINFO, cancelled=index == phase)

    with pytest.raises(FFmpegCancelledError) as error:
        extract(tmp_path, FakeRunner(callback), (interval("0", "1/10"),))
    assert error.value.teardown_confirmed
    assert not list((tmp_path / "frames").iterdir())
    assert not list(tmp_path.glob(".ffmpeg-*"))


@pytest.mark.parametrize("bad_probe, expected_error", [
    ({"stderr_truncated": True}, FFmpegOutputError),
    ({"identity": IDENTITY.model_copy(update={"sha256": "f" * 64})}, FFmpegBackendError),
    ({"timed_out": True}, FFmpegTimeoutError),
])
def test_bad_prepass_cannot_start_image_encoding(tmp_path, bad_probe, expected_error):
    runner = FakeRunner(lambda request, index: result(request, stderr=SHOWINFO, **bad_probe))
    with pytest.raises(expected_error):
        extract(tmp_path, runner, (interval("0", "1/10"),))
    assert len(runner.requests) == 1
    assert list((tmp_path / "frames").iterdir()) == []


def test_second_pass_presentation_drift_is_rejected(tmp_path):
    def callback(request, index):
        if index == 0:
            return result(request, stderr=SHOWINFO)
        Path(str(request.argv[-1]).replace("%08d", "00000000")).write_bytes(b"included")
        return result(request, stderr=b"config in time_base: 1/1000\nn: 0 pts: 1 pts_time:0\n")

    with pytest.raises(FFmpegOutputError, match="identity changed"):
        extract(tmp_path, FakeRunner(callback), (interval("0", "1/10"),))
    assert not list(tmp_path.glob(".ffmpeg-*"))


def test_restricted_progress_has_bounded_phase_reports_and_no_progress_file(tmp_path):
    observations = []

    def callback(request, index):
        assert "-progress" not in request.argv
        assert not list(tmp_path.glob(".ffmpeg-progress-*"))
        if index == 1:
            Path(str(request.argv[-1]).replace("%08d", "00000000")).write_bytes(b"included")
        return result(request, stderr=(SHOWINFO if index == 0 else SHOWINFO.split(b"n:   1")[0]))

    item = source(MediaType.VIDEO)
    frames = FFmpegAdapter(runner=FakeRunner(callback)).materialize(
        Path(item.external_locator), item, tmp_path / "frames", settings(),
        expected_backend=IDENTITY, timeout_seconds=30,
        used_intervals=(interval("0", "1/10"),), progress_sink=observations.append,
    )
    assert frames
    assert [value.processed_source_seconds for value in observations] == [0, 0.5, 1]
    assert all(value.total_source_seconds == 1 for value in observations)
    assert not list(tmp_path.glob(".ffmpeg-*"))


def test_both_passes_share_the_existing_source_timeout(tmp_path):
    runner = FakeRunner(lambda request, index: result(request, stderr=SHOWINFO))
    times = iter([10, 41])
    with pytest.raises(FFmpegTimeoutError):
        extract(tmp_path, runner, (interval("0", "1/10"),), monotonic=lambda: next(times))
    assert len(runner.requests) == 1
    assert not list(tmp_path.glob(".ffmpeg-*"))


def test_cancellation_between_passes_never_starts_encoding(tmp_path):
    class Signal:
        cancelled = False

        def is_cancelled(self):
            return self.cancelled

    signal = Signal()

    def callback(request, index):
        signal.cancelled = True
        return result(request, stderr=SHOWINFO)

    runner = FakeRunner(callback)
    item = source(MediaType.VIDEO)
    with pytest.raises(FFmpegCancelledError):
        FFmpegAdapter(runner=runner).materialize(
            Path(item.external_locator), item, tmp_path / "frames", settings(),
            expected_backend=IDENTITY, timeout_seconds=30,
            used_intervals=(interval("0", "1/10"),), cancellation=signal,
        )
    assert len(runner.requests) == 1
    assert list((tmp_path / "frames").iterdir()) == []
    assert not list(tmp_path.glob(".ffmpeg-*"))


@pytest.mark.parametrize("failure_phase", [0, 0.5, 1])
def test_optional_phase_progress_failure_cannot_change_materialized_output(tmp_path, failure_phase):
    observations = []

    def sink(observation):
        observations.append(observation.processed_source_seconds)
        if observation.processed_source_seconds == failure_phase:
            raise RuntimeError("optional telemetry failed")

    def callback(request, index):
        if index == 1:
            Path(str(request.argv[-1]).replace("%08d", "00000000")).write_bytes(b"included")
        return result(request, stderr=(SHOWINFO if index == 0 else SHOWINFO.split(b"n:   1")[0]))

    item = source(MediaType.VIDEO)
    with pytest.warns(RuntimeWarning, match="progress unavailable"):
        frames = FFmpegAdapter(runner=FakeRunner(callback)).materialize(
            Path(item.external_locator), item, tmp_path / "frames", settings(),
            expected_backend=IDENTITY, timeout_seconds=30,
            used_intervals=(interval("0", "1/10"),), progress_sink=sink,
        )
    assert observations == [0, 0.5, 1]
    assert len(frames) == 1 and frames[0].temporary_path.read_bytes() == b"included"
