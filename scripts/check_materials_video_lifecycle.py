"""Targeted native Qt playback lifetime check with owned temporary projects.

Requires an existing small ordinary video and installed ffprobe. Uses the actual
Qt decoder and automated controls; this is not manual Windows or Explorer evidence.
No input file or supplied project is changed, and no tool is installed.
"""

import argparse
import json
import shutil
import time
from pathlib import Path
from uuid import uuid4

from capture_materials import visual_item
from PySide6.QtCore import QEventLoop, QPointF, QSettings, Qt, QTimer
from PySide6.QtGui import QGuiApplication, QImage
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtQml import QQmlExpression, qmlContext
from PySide6.QtTest import QTest
from shiboken6 import isValid

from splatforge.bootstrap import build_media_service, build_project_service
from splatforge_gui.preferences import Preferences
from splatforge_gui.qml_app import create_engine
from splatforge_gui.qml_bridge import DesktopViewModel


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--ffprobe", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    fixture = args.output.resolve() / ("fixture-" + uuid4().hex[:8])
    fixture.mkdir()
    video = fixture / "Playback ž.mp4"
    shutil.copyfile(args.video, video)
    image = fixture / "Photo ž.png"
    raster = QImage(32, 24, QImage.Format_RGB32)
    raster.fill(Qt.green)
    assert raster.save(str(image))
    service, media = build_project_service(), build_media_service(ffprobe_path=args.ffprobe)
    roots = [fixture / name for name in ("First", "Second")]
    identities = {}
    for root in roots:
        service.create(root, root.name)
        media.add(root, [video, image])
        identities[root] = str(next(s.source_id for s in media.list(root).sources
                                   if s.media_type.value == "video"))

    app = QGuiApplication([])
    prefs = Preferences(QSettings(str(fixture / "review.ini"), QSettings.IniFormat))
    prefs.set("theme", "Dark")
    vm = DesktopViewModel(preferences=prefs)
    vm.controller.timer.stop()

    def until(predicate):
        deadline = time.monotonic() + 25
        while not predicate() and time.monotonic() < deadline:
            loop = QEventLoop()
            QTimer.singleShot(20, loop.quit)
            loop.exec()
        assert predicate(), "Timed out in native video lifecycle check"

    def idle():
        until(lambda: not vm.controller.executor.busy and not vm.controller.mutating
              and not vm.media.preview_executor.busy)

    vm.openProject(str(roots[0]))
    idle()
    engine = create_engine(vm)
    window = engine.rootObjects()[0]
    window.resize(1440, 900)
    until(lambda: visual_item(window.contentItem(), "materialViewer") is not None)
    records = []

    def playback(name):
        viewer = visual_item(window.contentItem(), "materialViewer")
        assert viewer is not None and isValid(viewer)
        context = qmlContext(viewer)
        assert context is not None and isValid(context)
        expression = f"playback.{name}"
        if name == "source":
            expression = "String(playback.source)"
        elif name == "playbackState":
            expression = "Number(playback.playbackState)"
        query = QQmlExpression(context, viewer, expression)
        result = query.evaluate()[0]
        assert not query.hasError(), query.error().toString()
        return result

    def click(name):
        until(lambda: (item := visual_item(window.contentItem(), name)) is not None
              and item.isVisible() and item.isEnabled())
        item = visual_item(window.contentItem(), name)
        point = item.mapToScene(QPointF(item.width() / 2, item.height() / 2)).toPoint()
        QTest.mouseClick(window, Qt.LeftButton, pos=point)

    def stopped():
        return (playback("source") == ""
                and playback("playbackState") == QMediaPlayer.StoppedState.value)

    def start(root):
        vm.media.showSource(identities[root])
        until(lambda: playback("hasVideo") and playback("duration") > 0)
        click("playPauseVideo")
        until(lambda: playback("playbackState") == QMediaPlayer.PlayingState.value
              and playback("position") > 0)
        records.append({"event": "playing", "project": root.name,
                        "source": playback("source"),
                        "position": playback("position")})

    try:
        until(window.isExposed)
        start(roots[0])
        vm.media.closePreview()
        until(stopped)
        idle()
        assert vm.media.state["videoUrl"] == ""
        assert vm.media.state["sourceDetails"] == {"fields": [], "technical": ""}
        assert window.grabWindow().save(str(args.output / "closed-review.png"))
        records.append({"event": "close_preview_unloaded"})

        start(roots[0])
        vm.sources.selectAllVisible()
        selected = vm.sources.selectedIds
        generation = vm.controller.generation
        click("nav-Projects")
        until(stopped)
        assert vm.media.state["previewSource"]["identity"] == identities[roots[0]]
        assert vm.sources.selectedIds == selected
        click("resumeCurrentProject")
        until(lambda: playback("hasVideo"))
        assert playback("playbackState") == QMediaPlayer.StoppedState.value
        assert vm.controller.generation == generation
        assert vm.sources.selectedIds == selected
        click("playPauseVideo")
        until(lambda: playback("position") > 0
              and playback("playbackState") == QMediaPlayer.PlayingState.value)
        records.append({"event": "projects_unloaded_and_resume_paused"})

        vm.openProject(str(roots[1]))
        idle()
        until(stopped)
        assert vm.media.state["previewSource"] == {}
        assert vm.media.state["videoUrl"] == ""
        assert vm.media.state["largeImage"] == ""
        assert vm.sources.selectedIds == []
        records.append({"event": "project_switch_unloaded_and_cleared"})
        # Both projects reference the same locator; their review generations differ.
        start(roots[1])
        assert vm.media.state["previewSource"]["identity"] == identities[roots[1]]
        idle()
        window.close()
        until(lambda: not window.isVisible())
        until(stopped)
        records.append({"event": "window_close_stopped_playback"})
        (args.output / "manifest.json").write_text(json.dumps({
            "records": records, "fixture": str(fixture), "qml_warnings": engine.load_errors,
            "native_title_bar": not bool(window.flags() & Qt.FramelessWindowHint),
            "logical_size": [window.width(), window.height()],
            "dpr": window.devicePixelRatio(), "manual_windows_check": False,
        }, indent=2), encoding="utf-8")
        assert not engine.load_errors, engine.load_errors
    finally:
        vm.media.closePreview()
        idle()
        window.close()
        engine.deleteLater()
        app.processEvents()
    print("Native video lifecycle passed", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
