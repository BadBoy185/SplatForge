"""Native Trim interaction/capture on an owned project; no user project is edited."""

import argparse
import json
import time
from pathlib import Path
from uuid import uuid4

from capture_materials import visual_item
from PySide6.QtCore import QEventLoop, QMetaObject, QObject, QPointF, QSettings, Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtQml import QQmlExpression, qmlContext
from PySide6.QtTest import QTest

from splatforge.bootstrap import build_media_service, build_project_service
from splatforge_gui.preferences import Preferences
from splatforge_gui.qml_app import create_engine
from splatforge_gui.qml_bridge import DesktopViewModel


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", required=True, type=Path)
    parser.add_argument("--photo", type=Path)
    parser.add_argument("--ffprobe", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    root = (args.output / ("Trim project " + uuid4().hex[:8])).resolve()
    build_project_service().create(root, "Trim review fixture")
    paths = [args.video.resolve()] + ([args.photo.resolve()] if args.photo else [])
    build_media_service(ffprobe_path=args.ffprobe).add(root, paths)
    app = QGuiApplication([])
    prefs = Preferences(QSettings(str(args.output / "capture.ini"), QSettings.IniFormat))
    prefs.set("recent", [])
    prefs.set("theme", "Dark")
    vm = DesktopViewModel(preferences=prefs)
    vm.controller.timer.stop()

    def settle(ms=50):
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    def until(predicate, timeout=25):
        deadline = time.monotonic() + timeout
        while not predicate() and time.monotonic() < deadline:
            settle(15)
        assert predicate(), "Timed out waiting for native Trim state"

    def idle():
        until(lambda: not vm.controller.executor.busy and not vm.controller.mutating
              and not vm.media.preview_executor.busy)

    vm.openProject(str(root))
    idle()
    vm.navigate(1)
    video = str(next(r.identity for r in vm.sources.rows if r.values["type"] == "video"))
    vm.media.showSource(video)
    engine = create_engine(vm)
    window = engine.rootObjects()[0]
    window.resize(1440, 900)

    def item(name):
        value = visual_item(window.contentItem(), name)
        assert value is not None, name
        return value

    def evaluate(code):
        target = item("materialViewer")
        expression = QQmlExpression(qmlContext(target), target, code)
        result = expression.evaluate()[0]
        assert not expression.hasError(), expression.error().toString()
        return result

    def click(name):
        control = item(name)
        assert control.isVisible() and control.isEnabled(), name
        point = control.mapToScene(QPointF(control.width() / 2, control.height() / 2))
        QTest.mouseClick(window, Qt.LeftButton, pos=point.toPoint())
        settle()

    def select_range(start, end):
        surface = item("trimRangeSurface")
        a = surface.mapToScene(QPointF(surface.width() * start / 6, surface.height() / 2))
        b = surface.mapToScene(QPointF(surface.width() * end / 6, surface.height() / 2))
        QTest.mousePress(window, Qt.LeftButton, pos=a.toPoint())
        QTest.mouseMove(window, b.toPoint(), 80)
        QTest.mouseRelease(window, Qt.LeftButton, pos=b.toPoint())
        settle()

    records = []

    def capture(name):
        idle()
        QTest.mouseMove(window, QPointF(window.width() / 2, window.height() / 3).toPoint())
        settle(200)
        timeline = item("videoTrimTimeline")
        if timeline.isVisible():
            assert QMetaObject.invokeMethod(timeline, "requestFrames")
            until(lambda: not vm.videoUsage.filmstrip.executor.busy
                  and not vm.videoUsage.filmstrip.queue)
        assert window.isExposed()
        image = window.grabWindow()
        assert image.save(str(args.output / (name + ".png")))
        records.append({"file": name + ".png", "size": [window.width(), window.height()],
                        "dpr": window.devicePixelRatio()})
        print(name, flush=True)

    try:
        until(lambda: bool(evaluate("playback.hasVideo")))
        click("materialsTrimMode")
        evaluate("trimSession.seek(500, false)")
        until(lambda: evaluate("trimSession.pendingSeek") < 0)
        until(lambda: len(vm.videoUsage.filmstrip.cache) >= 2
              or bool(vm.videoUsage.thumbnails.state["message"]))
        until(lambda: not vm.videoUsage.filmstrip.executor.busy
              and not vm.videoUsage.filmstrip.queue)
        assert len(vm.videoUsage.filmstrip.cache) >= 2, vm.videoUsage.thumbnails.state
        capture("Dark-1440-entire-clip")
        select_range(1, 5)
        click("trimIncludeRange")
        assert len(vm.videoUsage.state["intervals"]) == 1
        select_range(2, 3)
        click("trimExcludeRange")
        assert len(vm.videoUsage.state["intervals"]) == 2
        capture("Dark-1440-two-ranges")
        click("trimUsedRange1")
        capture("Dark-1440-selected-range")
        ranges_before_seek = vm.videoUsage.state["intervals"]
        ruler = item("trimRulerSeek")
        point = ruler.mapToScene(QPointF(ruler.width() * 3.2 / 6, 8))
        QTest.mouseClick(window, Qt.LeftButton, pos=point.toPoint())
        until(lambda: evaluate("trimSession.pendingSeek") < 0
              and evaluate("playback.position") > 3100)
        playhead = item("trimPlayhead")
        a = playhead.mapToScene(QPointF(playhead.width() / 2, playhead.height() / 2))
        b = a + QPointF(ruler.width() * 0.3 / 6, 0)
        QTest.mousePress(window, Qt.LeftButton, pos=a.toPoint())
        QTest.mouseMove(window, b.toPoint(), 80)
        QTest.mouseRelease(window, Qt.LeftButton, pos=b.toPoint())
        until(lambda: evaluate("trimSession.pendingSeek") < 0
              and evaluate("playback.position") > 3400)
        assert vm.videoUsage.state["intervals"] == ranges_before_seek
        item("materialViewer").forceActiveFocus()
        QTest.keyClick(window, Qt.Key_I)
        until(lambda: evaluate("trimSession.startText") != "3")
        QTest.keyClick(window, Qt.Key_Escape)
        until(lambda: evaluate("trimSession.startText") == "3")
        assert vm.videoUsage.state["intervals"] == ranges_before_seek
        click("playUsedRangesOnly")
        assert evaluate("trimSession.usedOnly")
        item("playUsedRangesOnly").forceActiveFocus()
        assert item("playUsedRangesOnly").hasActiveFocus()
        QTest.keyClick(window, Qt.Key_Space)
        until(lambda: not evaluate("trimSession.usedOnly"))  # focused checkbox owns Space
        QTest.keyClick(window, Qt.Key_Space)
        until(lambda: bool(evaluate("trimSession.usedOnly")))
        assert not evaluate("trimSession.playIntent")
        evaluate("trimSession.seek(0, false)")
        until(lambda: evaluate("trimSession.pendingSeek") < 0)
        positions = []
        player = evaluate("playback")
        assert isinstance(player, QMediaPlayer)
        player.positionChanged.connect(lambda *args: positions.append(player.property("position")))
        click("playPauseVideo")
        until(lambda: evaluate("playback.position") >= 3000)
        until(lambda: not evaluate("trimSession.playIntent"))
        assert evaluate("playback.position") >= 4900
        assert not evaluate("trimSession.playbackError")
        assert any(1500 <= a <= 2500 and 2900 <= b <= 3300 and b - a > 350
                   for a, b in zip(positions, positions[1:], strict=False)), positions
        saved = vm.videoUsage.state["intervals"]
        def save_button(node):
            if node.property("text") == "Save" and node.property("iconName") == "save":
                return node
            return next((found for child in node.childItems()
                         if (found := save_button(child)) is not None), None)

        control = save_button(window.contentItem())
        assert control is not None and control.isVisible()
        point = control.mapToScene(QPointF(control.width() / 2, control.height() / 2))
        QTest.mouseClick(window, Qt.LeftButton, pos=point.toPoint())
        until(lambda: not vm.controller.dirty)
        idle()
        assert not vm.controller.dirty
        vm.openProject(str(root))
        idle()
        vm.media.showSource(video)
        idle()
        until(lambda: bool(evaluate("playback.hasVideo")))
        assert vm.videoUsage.state["intervals"] == saved
        evaluate("trimMode = true; trimSession.selectRange(1); trimSession.seek(3500, false)")
        until(lambda: evaluate("trimSession.pendingSeek") < 0)
        assert not vm.controller.dirty
        vm.setTheme("Light")
        until(lambda: len(vm.videoUsage.filmstrip.cache) >= 2
              or bool(vm.videoUsage.thumbnails.state["message"]))
        until(lambda: not vm.videoUsage.filmstrip.executor.busy
              and not vm.videoUsage.filmstrip.queue)
        capture("Light-1440-selected-range")
        vm.setTheme("Dark")
        window.resize(1024, 640)
        settle()
        capture("Dark-1024-timeline")
        vm.setTheme("Light")
        capture("Light-1024-timeline")
        vm.setTheme("Dark")
        click("restoreMaterialProperties")
        capture("Dark-1024-range-properties")
        QTest.keyClick(window, Qt.Key_Escape)
        settle()
        vm.videoUsage.clearIntervals()
        assert vm.videoUsage.state["restricted"] and not vm.videoUsage.state["intervals"]
        evaluate("trimSession.usedOnly = true")
        assert not item("playPauseVideo").isEnabled()
        vm.videoUsage.resetIntervals()
        assert not vm.videoUsage.state["restricted"]
        vm.controller.discard()
        idle()
        vm.navigate(0)
        until(lambda: evaluate("String(playback.source)") == "")
        vm.resumeProject()
        until(lambda: bool(evaluate("playback.hasVideo")))
        click("materialsReviewMode")
        assert item("videoSeek").isVisible()
        click("playPauseVideo")
        until(lambda: evaluate("playback.position") > 100)
        click("playPauseVideo")
        if args.photo:
            photo_id = str(next(r.identity for r in vm.sources.rows if r.values["type"] == "photo"))
            vm.media.showSource(photo_id)
            until(lambda: vm.media.state["previewStatus"] == "Ready")
            assert not item("materialsTrimMode").isEnabled()
            click("zoomIn")
            click("fitPhoto")
            QTest.keyClick(window, Qt.Key_Comma, Qt.ControlModifier)
            settings = window.findChild(QObject, "settingsDialog")
            until(lambda: settings.property("visible"))
            QTest.keyClick(window, Qt.Key_Right)
            assert vm.media.state["previewSource"]["identity"] == photo_id
            QTest.keyClick(window, Qt.Key_Escape)
            until(lambda: not settings.property("visible"))
            QTest.keyClick(window, Qt.Key_Right)
            until(lambda: vm.media.state["previewSource"]["identity"] == video)
            until(lambda: bool(evaluate("playback.hasVideo")))
        other = (args.output / ("Empty switch " + uuid4().hex[:8])).resolve()
        build_project_service().create(other, "Owned switch target")
        click("playPauseVideo")
        until(lambda: bool(evaluate("trimSession.playIntent")))
        vm.openProject(str(other))
        idle()
        until(lambda: evaluate("String(playback.source)") == "")
        assert not evaluate("trimSession.playIntent")
        manifest = {"owned_project": str(root), "captures": records,
                    "saved_intervals": saved, "qml_warnings": engine.load_errors,
                    "used_playback_positions": positions,
                    "filmstrip": "Real individually input-seeked FFmpeg frames",
                    "input": "QtTest events in an exposed native window; not manual Windows input",
                    "native_title_bar": not bool(window.flags() & Qt.FramelessWindowHint)}
        (args.output / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        assert not engine.load_errors, engine.load_errors
    finally:
        vm.videoUsage.filmstrip.stop()
        vm.media.closePreview()
        until(lambda: not vm.videoUsage.filmstrip.executor.busy)
        idle()
        vm.controller.discard()
        window.close()
        engine.deleteLater()
        app.processEvents()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
