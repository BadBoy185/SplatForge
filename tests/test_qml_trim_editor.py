"""Real interval backend through the new QML fields, gestures, focus and Save."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QObject, QPointF, Qt  # noqa: E402
from PySide6.QtQml import QQmlExpression, qmlContext  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from test_media import FakeProbe  # noqa: E402
from test_qml import app as app  # noqa: E402
from test_qml import desktop as desktop  # noqa: E402
from test_qml import until, visual_item  # noqa: E402
from test_qml_interaction import click, dispose  # noqa: E402
from test_qml_source_participation import idle  # noqa: E402
from test_qml_sources import inject_media, photo  # noqa: E402
from test_qml_workflows import open_project  # noqa: E402

from splatforge.adapters.video_preview import FFmpegVideoPreview  # noqa: E402
from splatforge.bootstrap import build_project_service  # noqa: E402
from splatforge_gui.qml_app import create_engine  # noqa: E402
from splatforge_gui.video_filmstrip import VideoFilmstrip  # noqa: E402


class TimedProbe(FakeProbe):
    def probe(self, path, media_type, *, cancellation=None):
        result = super().probe(path, media_type, cancellation=cancellation)
        return result.model_copy(update={
            "start_time": "5", "playback_start_time": "5", "duration": "6",
        })


def setup(desktop, tmp_path, *, known=True):
    root = open_project(desktop, tmp_path)
    inject_media(desktop, root, TimedProbe() if known else FakeProbe())
    image = photo(tmp_path / "Photo ž.png")
    video = tmp_path / "Clip ž.MP4"
    video.write_bytes(b"Inventory-only fake video, no native decoder needed")
    desktop.addFiles([str(image), str(video)])
    idle(desktop)
    rows = {r.values["type"]: str(r.identity) for r in desktop.sources.rows}
    desktop.sources.select(rows["photo"])
    desktop.media.showSource(rows["video"])
    idle(desktop)
    engine = create_engine(desktop)
    window = engine.rootObjects()[0]
    window.resize(1440, 900)
    click(window, "materialsTrimMode")

    def item(name):
        result = visual_item(window.contentItem(), name)
        assert result is not None, name
        return result

    def evaluate(code):
        viewer = item("materialViewer")
        expression = QQmlExpression(qmlContext(viewer), viewer, code)
        result = expression.evaluate()[0]
        assert not expression.hasError(), expression.error().toString()
        return result

    def type_field(name, text):
        click(window, name)
        QTest.keyClick(window, Qt.Key_A, Qt.ControlModifier)
        for char in text:
            QTest.keyClick(window, Qt.Key(ord(char.upper())))
        assert item(name).property("text") == text

    return root, rows, engine, window, item, evaluate, type_field


def finish(desktop, engine):
    desktop.videoUsage.filmstrip.stop()
    until(lambda: not desktop.videoUsage.filmstrip.executor.busy)
    desktop.controller.discard()
    idle(desktop)
    dispose(engine)


def test_fields_normalization_gestures_escape_and_save_readback(desktop, tmp_path):
    root, rows, engine, window, item, evaluate, type_field = setup(desktop, tmp_path)
    try:
        before = (root / "project.json").read_bytes()
        type_field("trimStartInput", "6")
        type_field("trimEndInput", "10")
        click(window, "trimIncludeRange")
        assert desktop.videoUsage.state["intervals"] == [{"start": "6", "end": "10"}]
        assert evaluate("trimSession.selectedIndex") == 0
        # New transient selection, subtract the middle through the same fields/API.
        evaluate("trimSession.selectRange(-1)")
        type_field("trimStartInput", "7")
        type_field("trimEndInput", "8")
        assert evaluate("trimSession.startText") == "7"
        assert evaluate("trimSession.endText") == "8"
        click(window, "trimExcludeRange")
        until(lambda: len(desktop.videoUsage.state["intervals"]) == 2)
        assert desktop.videoUsage.state["error"] == {}
        assert desktop.videoUsage.state["intervals"] == [
            {"start": "6", "end": "7"}, {"start": "8", "end": "10"},
        ]
        assert evaluate("trimSession.startText") == "7"  # can restore the excluded selection
        assert desktop.sources.selectedIds == [rows["photo"]]
        click(window, "trimUsedRange1")
        type_field("trimStartInput", "17/2")
        type_field("trimEndInput", "21/2")
        click(window, "trimApplyBounds")
        assert evaluate("trimSession.selectedIndex") == 1
        assert item("trimStartInput").property("text") == "17/2"
        assert item("trimEndInput").property("text") == "21/2"
        type_field("trimStartInput", "9")
        QTest.keyClick(window, Qt.Key_Escape)
        assert item("trimStartInput").property("text") == "17/2"
        assert desktop.videoUsage.state["intervals"][1]["start"] == "17/2"
        # An invalid edit keeps the draft and shows the backend's validation error.
        type_field("trimEndInput", "5")
        click(window, "trimApplyBounds")
        assert desktop.videoUsage.state["error"]["code"] == "invalid_interval"
        assert item("trimValidationError").isVisible()
        click(window, "trimUsedRange1")
        assert not desktop.videoUsage.state["error"]
        # A handle commits one endpoint on release, preserving the untouched fraction.
        handle = item("trimStartHandle")
        start = handle.mapToScene(QPointF(handle.width() / 2, handle.height() / 2))
        end = start + QPointF(25, 0)
        QTest.mousePress(window, Qt.LeftButton, pos=start.toPoint())
        QTest.mouseMove(window, end.toPoint(), 50)
        assert desktop.videoUsage.state["intervals"][1]["start"] == "17/2"
        QTest.mouseRelease(window, Qt.LeftButton, pos=end.toPoint())
        assert desktop.videoUsage.state["intervals"][1]["start"] != "17/2"
        assert desktop.videoUsage.state["intervals"][1]["end"] == "21/2"
        saved = desktop.videoUsage.state["intervals"]
        # Zoom/scroll/Fit and playhead movement are presentation state only.
        click(window, "timelineZoomIn")
        timeline = item("videoTrimTimeline")
        assert timeline.property("zoom") == 2
        item("trimTimelineScroll").setProperty("contentX", 100)
        click(window, "fitTimeline")
        assert timeline.property("zoom") == 1
        assert item("trimTimelineScroll").property("contentX") == 0
        assert (root / "project.json").read_bytes() == before
        desktop.save()
        idle(desktop)
        assert not desktop.controller.dirty
        assert len(build_project_service().open(root).video_usage.entries[0].intervals) == 2
        desktop.openProject(str(root))
        idle(desktop)
        desktop.media.showSource(rows["video"])
        idle(desktop)
        assert desktop.videoUsage.state["intervals"] == saved
        # Ordinary photo review remains available and Trim has an explicit reason.
        desktop.media.showSource(rows["photo"])
        idle(desktop)
        assert not item("materialsTrimMode").isEnabled()
        assert not evaluate("trimMode")
        assert item("fitPhoto").isVisible()
        item("materialViewer").forceActiveFocus()
        for modifier in (Qt.ControlModifier, Qt.ShiftModifier):
            QTest.keyClick(window, Qt.Key_Right, modifier)
            assert desktop.media.state["previewSource"]["identity"] == rows["photo"]
        QTest.keyClick(window, Qt.Key_Right)
        until(lambda: desktop.media.state["previewSource"]["identity"] == rows["video"])
        assert not engine.load_errors
    finally:
        finish(desktop, engine)


def test_unknown_origin_exact_edit_empty_reset_and_reselection(desktop, tmp_path):
    _, _, engine, window, item, evaluate, type_field = setup(desktop, tmp_path, known=False)
    try:
        assert not evaluate("trimSession.mapped")
        assert not item("playUsedRangesOnly").isEnabled()
        assert "origin" in desktop.videoUsage.state["timeline"]["reason"]
        type_field("trimStartInput", "10/3")
        type_field("trimEndInput", "20/3")
        click(window, "trimIncludeRange")
        assert evaluate("trimSession.selectedIndex") == 0
        assert item("trimStartInput").property("text") == "10/3"
        type_field("trimStartInput", "11/3")
        QTest.keyClick(window, Qt.Key_Return)
        assert evaluate("trimSession.selectedIndex") == 0
        assert desktop.videoUsage.state["intervals"][0]["start"] == "11/3"
        click(window, "trimRemoveRange")
        assert desktop.videoUsage.state["restricted"]
        assert desktop.videoUsage.state["intervals"] == []
        assert item("videoUsageSummary").property("text") == "No used ranges"
        click(window, "trimUseEntireClip")
        assert not desktop.videoUsage.state["restricted"]
        assert item("videoUsageSummary").property("text") == "Entire clip is used"
        assert not engine.load_errors
    finally:
        finish(desktop, engine)


def test_entering_trim_automatically_requests_visible_filmstrip(desktop, tmp_path, monkeypatch):
    requests = []
    monkeypatch.setattr(VideoFilmstrip, "request", lambda self, *args: requests.append(args))
    _, _, engine, window, item, _, _ = setup(desktop, tmp_path)
    try:
        click(window, "materialsReviewMode")
        requests.clear()
        # Native windows can receive no animation ticks while occluded. Enter Trim
        # without waiting for a rendered frame, and stop its animation-based debounce.
        item("materialViewer").setProperty("trimMode", True)
        timeline = item("videoTrimTimeline")
        timer = timeline.findChild(QObject, "trimFrameRequest")
        assert timer is not None
        timer.setProperty("running", False)
        until(lambda: bool(requests))
        assert 2 <= len(requests[-1][3]) <= 12
        assert all(0 <= position <= 6000 for position in requests[-1][3])
        assert not engine.load_errors
    finally:
        finish(desktop, engine)


def test_missing_filmstrip_tool_explains_failure_without_blocking_trim(
    desktop, tmp_path, monkeypatch,
):
    def unavailable(*args):
        raise FileNotFoundError("FFmpeg unavailable")

    monkeypatch.setattr(FFmpegVideoPreview, "frame", unavailable)
    _, _, engine, window, item, _, _ = setup(desktop, tmp_path)
    try:
        until(lambda: bool(desktop.videoUsage.thumbnails.state["message"]))
        hint = item("timelineThumbnailsMessage")
        assert hint.isVisible()
        assert "Timeline thumbnails unavailable" in hint.property("text")
        click(window, "trimIncludeRange")
        assert desktop.videoUsage.state["intervals"] == [{"start": "5", "end": "11"}]
        assert not desktop.videoUsage.state["error"]
        assert not engine.load_errors
    finally:
        finish(desktop, engine)
