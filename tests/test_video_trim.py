"""Trim projection and delayed-player behavior, without native decoder timing."""

import json
import os
from fractions import Fraction
from pathlib import Path
from uuid import uuid4

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import Property, QObject, QUrl, Signal, Slot  # noqa: E402
from PySide6.QtMultimedia import QMediaPlayer  # noqa: E402
from PySide6.QtQml import QQmlComponent, QQmlEngine, QQmlExpression  # noqa: E402
from test_qml import app as app  # noqa: E402

from splatforge.core.video_usage import VideoSource, interval  # noqa: E402
from splatforge.core.views import RationalValue  # noqa: E402
from splatforge_gui.video_usage_vm import timeline_projection  # noqa: E402


def source(**kwargs):
    values = dict(source_id=uuid4(), content_sha256="a" * 64, stream_index=0,
                  start=RationalValue.from_fraction(Fraction("11/2")),
                  playback_start=RationalValue.from_fraction(Fraction("5")),
                  duration=RationalValue.from_fraction(Fraction("9/2")))
    return VideoSource(**(values | kwargs))


def test_projection_keeps_source_origin_exact_and_distinct_from_player_origin():
    video = source()
    bounds = (interval("17/3", "19/3"), interval("8", "9"))
    result = timeline_projection(video, bounds)
    assert result["available"]
    assert (result["start"], result["end"]) == ("11/2", "10")
    assert (result["startPosition"], result["endPosition"]) == (500, 5000)
    assert result["ranges"] == [{"start": 667, "end": 1333}, {"start": 3000, "end": 4000}]
    assert result["gaps"] == [
        {"start": 500, "end": 667}, {"start": 1333, "end": 3000},
        {"start": 4000, "end": 5000},
    ]
    assert str(bounds[0].start.as_fraction()) == "17/3"
    assert timeline_projection(video, None)["gaps"] == []
    assert timeline_projection(video, ())["gaps"] == [{"start": 500, "end": 5000}]


@pytest.mark.parametrize("field", ["start", "duration", "playback_start"])
def test_unknown_time_is_unavailable_with_a_reason(field):
    result = timeline_projection(source(**{field: None}), None)
    assert not result["available"] and result["reason"]
    assert "startPosition" not in result


class Usage(QObject):
    changed = Signal()

    def __init__(self):
        super().__init__()
        self.calls = 0
        self.value = {
            "contextKey": "1", "sourceId": "video-a", "canEdit": True,
            "restricted": True, "intervals": [{"start": "6", "end": "7"},
                                             {"start": "8", "end": "10"}],
            "timeline": {"available": True, "start": "5", "end": "11",
                         "startPosition": 0, "endPosition": 6000,
                         "ranges": [{"start": 1000, "end": 2000},
                                    {"start": 3000, "end": 5000}]},
        }

    @Property("QVariantMap", notify=changed)
    def state(self):
        return self.value

    @Slot(str, result=str)
    def playerPosition(self, seconds):
        self.calls += 1
        assert self.calls < 100, "Conversion notification reentry"
        self.changed.emit()
        return str(round((Fraction(seconds) - 5) * 1000))

    @Slot(str, result=str)
    def sourceTime(self, ms):
        self.changed.emit()
        return str(5 + Fraction(ms) / 1000)


@pytest.fixture
def session(app):
    engine = QQmlEngine()
    usage = Usage()
    engine.rootContext().setContextProperty("usageApi", usage)
    component = QQmlComponent(engine)
    directory = (Path(__file__).parents[1] / "src/splatforge_gui/qml/components").as_uri()
    component.setData(('''import QtQuick
import QtMultimedia
import "''' + directory + '''"
Item {
    property alias session: trim
    property alias player: fake
    QtObject {
        id: fake
        property int position: 0
        property int duration: 6000
        property bool seekable: true
        property int playbackState: MediaPlayer.PausedState
        property int mediaStatus: MediaPlayer.LoadedMedia
        property int requested: -1
        property int seeks: 0
        signal errorOccurred()
        function setPosition(value) { requested = value; seeks += 1; }
        function pause() { playbackState = MediaPlayer.PausedState; }
        function play() { playbackState = MediaPlayer.PlayingState; }
    }
    VideoTrimSession { id: trim; api: usageApi; player: fake; active: true; trimMode: true }
}''').encode(), QUrl())
    root = component.create()
    assert root is not None, [str(e) for e in component.errors()]

    def evaluate(code):
        expression = QQmlExpression(engine.rootContext(), root, code)
        result = expression.evaluate()[0]
        assert not expression.hasError(), expression.error().toString()
        return result

    yield usage, evaluate
    root.deleteLater()
    app.processEvents()
    engine.deleteLater()
    app.processEvents()


def test_delayed_seek_pause_and_source_switch_never_resume(session):
    usage, evaluate = session
    assert usage.calls <= 4  # success notifications must not recursively reproject
    evaluate("session.usedOnly = true; session.togglePlay()")
    assert evaluate("player.requested") == 1000
    assert evaluate("session.pendingSeek") == 1000
    evaluate("session.pause(); player.position = 1000")
    assert not evaluate("session.playIntent")
    assert evaluate("player.playbackState") == 2  # PausedState
    evaluate("session.seek(3000, true)")
    evaluate("session.beginScrub(1500); session.resumeAfterScrub = true")
    usage.value = usage.value | {"contextKey": "2", "sourceId": "video-a"}
    usage.changed.emit()  # Same source UUID/URL in a new project generation.
    evaluate("player.position = 3000")
    assert not evaluate("session.playIntent")
    assert not evaluate("session.usedOnly")
    assert not evaluate("session.scrubbing")
    evaluate("session.endScrub()")
    assert not evaluate("session.playIntent")
    assert evaluate("player.playbackState") == 2


def test_gap_seeks_once_last_end_stops_and_next_play_restarts(session):
    _, evaluate = session
    evaluate("session.usedOnly = true; session.togglePlay(); player.position = 1000")
    assert evaluate("player.playbackState") == 1
    evaluate("player.position = 2000")
    assert evaluate("player.seeks") == 2
    assert evaluate("player.requested") == 3000
    evaluate("player.position = 2100; player.position = 2300")
    assert evaluate("player.seeks") == 2
    evaluate("player.position = 3000; player.position = 5000")
    assert not evaluate("session.playIntent")
    assert evaluate("player.playbackState") == 2
    evaluate("session.togglePlay()")
    assert evaluate("player.requested") == 1000
    assert evaluate("player.seeks") == 3


def test_close_ranges_do_not_acknowledge_an_old_gap_position(session):
    usage, evaluate = session
    usage.value["timeline"]["ranges"] = [
        {"start": 1000, "end": 1010}, {"start": 1050, "end": 1060},
    ]
    usage.changed.emit()
    evaluate("session.usedOnly = true; player.position = 1000; session.togglePlay()")
    evaluate("player.position = 1011")
    assert evaluate("player.requested") == 1050
    assert evaluate("session.pendingSeek") == 1050
    assert evaluate("player.playbackState") == 2
    evaluate("player.position = 1020; player.position = 1040")
    assert evaluate("player.seeks") == 1
    assert evaluate("session.pendingSeek") == 1050
    evaluate("player.position = 1050")
    assert evaluate("session.pendingSeek") == -1
    assert evaluate("player.playbackState") == 1


def test_empty_collapsed_ranges_and_scrub_resume(session):
    usage, evaluate = session
    evaluate("session.usedOnly = true; session.togglePlay(); player.position = 1000")
    evaluate("session.beginScrub(1500); session.scrubPosition = 2500; session.endScrub()")
    assert evaluate("player.requested") == 3000
    evaluate("player.position = 3000")
    assert evaluate("player.playbackState") == 1
    for ranges in ([], [{"start": 2000, "end": 2000}]):
        usage.value = usage.value | {"timeline": usage.value["timeline"] | {"ranges": ranges},
                                     "intervals": []}
        usage.changed.emit()
        assert not evaluate("session.canPlay")
        before = evaluate("player.seeks")
        evaluate("session.togglePlay()")
        assert evaluate("player.seeks") == before


def test_selection_keeps_exact_strings_and_escape_restores_gesture(session):
    usage, evaluate = session
    usage.value["intervals"][0] = {"start": "6000000000000001/1000000000000000", "end": "7"}
    usage.changed.emit()
    evaluate("session.selectRange(0)")
    assert evaluate("session.startText") == usage.value["intervals"][0]["start"]
    original = json.loads(evaluate("JSON.stringify([session.startText, session.endText])"))
    evaluate("session.beginGesture(); session.setBoundary(true, 1200); session.cancelGesture()")
    assert json.loads(evaluate("JSON.stringify([session.startText, session.endText])")) == original


def test_play_during_loading_does_not_latch_intent_and_nonseekable_can_start(session):
    _, evaluate = session
    evaluate("player.seekable = false; player.duration = 0; player.mediaStatus = "
             + str(QMediaPlayer.NoMedia.value))
    evaluate("session.togglePlay()")  # NoMedia: the first metadata is not ready.
    assert not evaluate("session.playIntent")
    assert evaluate("player.playbackState") == 2
    evaluate(f"player.mediaStatus = {QMediaPlayer.LoadingMedia.value}; session.togglePlay()")
    assert not evaluate("session.playIntent")
    evaluate(f"player.mediaStatus = {QMediaPlayer.LoadedMedia.value}; session.togglePlay()")
    assert evaluate("session.playIntent")
    assert evaluate("player.playbackState") == 1
    assert evaluate("player.seeks") == 0


@pytest.mark.parametrize("interrupt", ["session.pause()", "player.errorOccurred()",
                                       "session.active = false"])
def test_pause_error_or_exit_during_scrub_revokes_resume(session, interrupt):
    _, evaluate = session
    evaluate("session.togglePlay(); session.beginScrub(1500)")
    assert evaluate("session.resumeAfterScrub")
    evaluate(interrupt)
    evaluate("session.active = true; session.endScrub(); player.position = 1500")
    assert not evaluate("session.playIntent")
    assert not evaluate("session.resumeAfterScrub")
    assert not evaluate("session.scrubbing")
    assert evaluate("player.playbackState") == 2
    assert evaluate("player.seeks") == 0
