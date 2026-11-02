"""Preview process bounds and one-worker stale-delivery/cache behavior."""

import os
from threading import Event
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QObject  # noqa: E402
from test_qml import app as app  # noqa: E402
from test_qml import until  # noqa: E402
from test_qml_sources import photo  # noqa: E402

from splatforge.adapters.video_preview import FFmpegVideoPreview  # noqa: E402
from splatforge_gui.video_filmstrip import VideoFilmstrip  # noqa: E402


class Cancellation:
    def is_cancelled(self):
        return False


def test_preview_arguments_unicode_spaces_bounds_and_teardown(tmp_path):
    requests = []
    result = SimpleNamespace(exit_code=0, cancelled=False, timed_out=False,
                             teardown_confirmed=True, stdout_truncated=False, stdout=b"jpeg",
                             stderr_text=lambda: "bounded failure")

    class Runner:
        def run(self, request, *, cancellation):
            requests.append((request, cancellation))
            return result

    adapter = FFmpegVideoPreview(Runner(), executable="C:/tools/ffmpeg.exe")
    path = tmp_path / "Видео ž with spaces.mp4"
    cancellation = Cancellation()
    assert adapter.frame(path, 2, 1001, cancellation) == b"jpeg"
    request, observed = requests[0]
    assert observed is cancellation
    assert request.argv[request.argv.index("-i") + 1] == str(path)
    assert request.argv[request.argv.index("-map") + 1] == "0:2"
    assert request.argv.index("-ss") < request.argv.index("-i")  # input seek, not full decode
    assert request.argv[request.argv.index("-ss") + 1] == "1.001"
    assert request.argv[request.argv.index("-frames:v") + 1] == "1"
    assert request.max_stdout_bytes == 256 * 1024 and request.timeout_seconds == 8
    assert request.working_directory == tmp_path
    for key in ("cancelled", "timed_out", "stdout_truncated"):
        setattr(result, key, True)
        with pytest.raises(ValueError):
            adapter.frame(path, 2, 1, cancellation)
        setattr(result, key, False)
    result.teardown_confirmed = False
    with pytest.raises(ValueError):
        adapter.frame(path, 2, 1, cancellation)


def make_strip(backend):
    desktop = QObject()
    desktop.controller = SimpleNamespace(factory=lambda: SimpleNamespace(service=lambda _: backend))
    return desktop, VideoFilmstrip(desktop)


def test_single_worker_latest_queue_stale_source_and_cache_bound(app, tmp_path):
    raw = photo(tmp_path / "frame.png").read_bytes()
    started, release = Event(), Event()
    calls = []

    class Backend:
        def frame(self, path, stream, position, cancellation):
            calls.append((path, position, cancellation))
            if len(calls) == 1:
                started.set()
                assert release.wait(5)
            return raw

    desktop, strip = make_strip(Backend())
    try:
        strip.request("old", tmp_path / "old.mp4", 0, list(range(12)))
        until(started.is_set)
        old_namespace = strip.namespace
        strip.request("new", tmp_path / "new.mp4", 0, list(range(20, 50)))
        assert len(strip.jobs) == 1 and len(strip.queue) == 12
        assert calls[0][2].is_cancelled()
        release.set()
        until(lambda: not strip.executor.busy and not strip.queue)
        assert all(not key.startswith(old_namespace) for key in strip.cache)
        assert len(strip.cache) == 12
        for first in (100, 200, 300):
            strip.request("new", tmp_path / "new.mp4", 0, list(range(first, first + 12)))
            until(lambda: not strip.executor.busy and not strip.queue)
        assert len(strip.cache) == 32
        assert all(row["url"] for row in strip.state["frames"])
        strip.stop()
        assert not strip.cache and strip.state["frames"] == []
    finally:
        release.set()
        strip.stop()
        until(lambda: not strip.executor.busy)
        desktop.deleteLater()
        app.processEvents()


def test_missing_tool_fails_once_and_keeps_timeline_usable(app, tmp_path):
    calls = []

    class Backend:
        def frame(self, *args):
            calls.append(args)
            raise ValueError("FFmpeg is unavailable")

    desktop, strip = make_strip(Backend())
    try:
        strip.request("a", tmp_path / "video.mp4", 0, list(range(12)))
        until(lambda: not strip.executor.busy)
        assert len(calls) == 1 and strip.state["message"]
        strip.request("a", tmp_path / "video.mp4", 0, list(range(20, 32)))
        assert len(calls) == 1 and not strip.executor.busy
        assert len(strip.state["frames"]) == 12  # honest empty URLs, no invented images
    finally:
        strip.stop()
        desktop.deleteLater()
        app.processEvents()
