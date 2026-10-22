from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from progress_helpers import FakeClock
from test_ffmpeg import IDENTITY, SHOWINFO, FakeRunner, result, settings, source
from test_ffmpeg_integration import configured_ffmpeg

from splatforge.adapters.ffmpeg import FFmpegAdapter, FFmpegProgressReader
from splatforge.adapters.process_runner import LocalProcessRunner, ProcessRequest
from splatforge.core.media import MediaType


@pytest.mark.parametrize("origin", [0, 5_000_000, -2_000_000])
def test_structured_vfr_progress_normalizes_nonzero_and_negative_pts(
    tmp_path: Path,
    origin: int,
) -> None:
    clock = FakeClock()
    observations = []
    reader = FFmpegProgressReader(
        tmp_path / "progress", 1, observations.append, monotonic=clock.monotonic
    )
    reader.feed(f"out_time_us={origin}\nprogress=continue\n".encode())
    assert observations[-1].processed_source_seconds == 0
    clock.advance(2)
    reader.feed(f"frame=2\nout_time_us={origin + 120000}\nprogr".encode())
    assert len(observations) == 1
    reader.feed(b"ess=continue\n")
    clock.advance(1)
    reader.feed(f"frame=3\nout_time_us={origin + 490000}\nprogress=continue\n".encode())
    reader.feed(f"out_time_us={origin + 200000}\nprogress=continue\n".encode())
    assert [value.processed_source_seconds for value in observations] == [0, 0.12, 0.49, 0.49]
    assert observations[-1].elapsed_seconds == 3
    reader.feed(f"out_time_us={origin + 720000}\nprogress=end\n".encode())
    assert observations[-1].processed_source_seconds == 1


def test_malformed_or_unbounded_progress_does_not_create_fake_work(tmp_path: Path) -> None:
    observations = []
    clock = FakeClock()
    reader = FFmpegProgressReader(
        tmp_path / "progress", 1, observations.append, monotonic=clock.monotonic
    )
    reader.feed(b"out_time_us=N/A\nprogress=continue\n")
    reader.feed(b"frame=1000\nprogress=continue\n")
    reader.feed(b"x" * 100000)
    assert len(reader._pending) <= 1024
    assert observations == []


def test_owned_poll_delivers_progress_before_ffmpeg_returns_and_preserves_frames(
    tmp_path: Path,
) -> None:
    class ProgressRunner(FakeRunner):
        finished = False

        def run(self, request, *, cancellation=None, poll=None):
            if "-version" in request.argv:
                return super().run(request, cancellation=cancellation)
            self.requests.append(request)
            path = Path(request.argv[request.argv.index("-progress") + 1])
            pattern = Path(request.argv[-1])
            path.write_bytes(b"out_time_us=5000000\nprogress=continue\n")
            poll()
            with path.open("ab") as stream:
                stream.write(b"out_time_us=5417000\nprogress=continue\n")
            poll()
            for index in range(2):
                Path(str(pattern).replace("%08d", f"{index:08d}")).write_bytes(b"image")
            with path.open("ab") as stream:
                stream.write(b"out_time_us=5700000\nprogress=end\n")
            self.finished = True
            return result(request, stderr=SHOWINFO)

    runner = ProgressRunner()
    adapter = FFmpegAdapter(runner=runner, monotonic=FakeClock().monotonic)
    backend = adapter.identity()
    values = []

    def observe(value) -> None:
        values.append((runner.finished, value))

    frames = adapter.materialize(
        tmp_path / "original.mp4",
        source(MediaType.VIDEO),
        tmp_path / "decoded",
        settings(),
        timeout_seconds=30,
        expected_backend=backend,
        progress_sink=observe,
    )
    assert [value[0] for value in values] == [False, False, True]
    assert values[1][1].processed_source_seconds == 0.417
    assert values[-1][1].processed_source_seconds == 1
    assert [frame.pts for frame in frames] == [0, 417]
    assert "showinfo" in runner.requests[-1].argv[runner.requests[-1].argv.index("-vf") + 1]
    assert not list(tmp_path.glob(".ffmpeg-progress-*"))
    assert len(list((tmp_path / "decoded").iterdir())) == 2
    assert backend.sha256 == IDENTITY.sha256


def test_generic_poll_failure_is_diagnostic_only_even_under_warning_as_error() -> None:
    def broken() -> None:
        raise RuntimeError("optional progress failed")

    with pytest.warns(RuntimeWarning, match="progress callback failed"):
        assert LocalProcessRunner._poll_safely(broken) is False
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert LocalProcessRunner._poll_safely(broken) is False


@pytest.mark.integration
def test_real_ffmpeg_emits_live_progress_before_owned_process_returns(tmp_path: Path) -> None:
    executable = configured_ffmpeg()
    video = tmp_path / "live fixture.mp4"
    generated = LocalProcessRunner().run(
        ProcessRequest(
            executable=executable,
            argv=(
                "-hide_banner",
                "-nostdin",
                "-loglevel",
                "error",
                "-f",
                "lavfi",
                "-i",
                "testsrc=size=64x48:rate=30:duration=3",
                "-c:v",
                "mpeg4",
                str(video),
            ),
            working_directory=tmp_path,
            environment={},
            timeout_seconds=30,
        )
    )
    assert generated.exit_code == 0
    original = video.read_bytes()

    class PacedRunner(LocalProcessRunner):
        running = False

        def run(self, request, *, cancellation=None, poll=None):
            if "-i" not in request.argv:
                return super().run(request, cancellation=cancellation, poll=poll)
            # Integration-only input pacing makes the live owner poll observable;
            # it changes no selected pixels/PTS and production argv stays unchanged.
            argv = list(request.argv)
            argv.insert(argv.index("-i"), "-re")
            self.running = True
            try:
                return super().run(
                    replace(request, argv=tuple(argv)), cancellation=cancellation, poll=poll
                )
            finally:
                self.running = False

    runner = PacedRunner()
    adapter = FFmpegAdapter(runner=runner, executable=executable)
    backend = adapter.identity()
    fixture = source(MediaType.VIDEO)
    fixture = fixture.model_copy(
        update={
            "probe": fixture.probe.model_copy(
                update={
                    "width": 64,
                    "height": 48,
                    "duration": "3",
                    "selected_visual_stream_index": 0,
                }
            )
        }
    )
    observations = []
    frames = adapter.materialize(
        video,
        fixture,
        tmp_path / "decoded",
        settings(),
        timeout_seconds=30,
        expected_backend=backend,
        progress_sink=lambda value: observations.append((runner.running, value)),
    )
    assert frames
    assert any(
        running and 0 < value.processed_source_seconds < 3 for running, value in observations
    ), [
        (running, value.processed_source_seconds, value.elapsed_seconds)
        for running, value in observations
    ]
    assert observations[-1][1].processed_source_seconds == 3
    assert video.read_bytes() == original
