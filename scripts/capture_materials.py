"""Capture the real Materials workspace without mutating the supplied project.

Use a review project with at least one decodable photo and ordinary video. The
optional filename arguments avoid deliberately corrupt fixtures in that project.
No processing, import, or generated product data is performed by this harness.
"""

import argparse
import json
import time
from pathlib import Path

from PySide6.QtCore import QEventLoop, QMetaObject, QPointF, QSettings, Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlExpression, qmlContext
from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QTest

from splatforge_gui.preferences import Preferences
from splatforge_gui.qml_app import create_engine
from splatforge_gui.qml_bridge import DesktopViewModel


def visual_item(parent: QQuickItem, name: str) -> QQuickItem | None:
    if parent.objectName() == name:
        return parent
    return next((item for child in parent.childItems()
                 if (item := visual_item(child, name)) is not None), None)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--photo", default="")
    parser.add_argument("--video", default="")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    app = QGuiApplication([])
    prefs = Preferences(QSettings(str(args.output / "review.ini"), QSettings.IniFormat))
    prefs.set("recent", [])
    prefs.set("theme", "Dark")
    vm = DesktopViewModel(preferences=prefs)
    vm.controller.timer.stop()

    def settle(ms=150):
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    def until(predicate):
        deadline = time.monotonic() + 25
        while not predicate() and time.monotonic() < deadline:
            settle(20)
        assert predicate(), "Timed out waiting for Materials state"

    def idle():
        until(lambda: not vm.controller.executor.busy and not vm.controller.mutating
              and not vm.media.preview_executor.busy)

    vm.openProject(str(args.project.resolve()))
    idle()
    assert vm.controller.overview, vm.state["error"]
    vm.navigate(1)
    vm.setSourceView("List")
    engine = create_engine(vm)
    window = engine.rootObjects()[0]

    def item(name):
        result = visual_item(window.contentItem(), name)
        assert result is not None, name
        return result

    def click(name):
        control = item(name)
        assert control.isVisible() and control.isEnabled(), name
        point = control.mapToScene(QPointF(control.width() / 2, control.height() / 2))
        QTest.mouseClick(window, Qt.LeftButton, pos=point.toPoint())
        settle()

    def playback(code):
        viewer = item("materialViewer")
        expression = QQmlExpression(qmlContext(viewer), viewer, "playback." + code)
        result = expression.evaluate()[0]
        assert not expression.hasError(), expression.error().toString()
        return result

    def identity(kind, filename):
        return str(next(row.identity for row in vm.sources.rows
                        if row.values["type"] == kind
                        and (not filename or row.values["filename"] == filename)))

    photo_id = identity("photo", args.photo)
    video_id = identity("video", args.video)
    records = []

    def capture(name):
        idle()
        settle(350)
        assert window.isExposed(), "Native exposed window required"
        raster = window.grabWindow()
        assert raster.save(str(args.output / (name + ".png")))
        records.append({"file": name + ".png", "logical_size": [window.width(), window.height()],
                        "physical_size": [raster.width(), raster.height()],
                        "dpr": window.devicePixelRatio()})
        print(name, flush=True)

    try:
        for width, height in ((1440, 900), (1024, 640)):
            window.resize(width, height)
            settle(400)
            vm.media.activateSource(photo_id)
            until(lambda: vm.media.state["previewStatus"] == "Ready")
            capture(f"Dark-{width}-photo")
            if width == 1440:
                for _ in range(5):
                    QMetaObject.invokeMethod(item("zoomIn"), "clicked")
                viewport = item("photoViewport")
                settle()
                center = viewport.mapToScene(QPointF(viewport.width() / 2, viewport.height() / 2))
                QTest.mousePress(window, Qt.LeftButton, pos=center.toPoint())
                QTest.mouseMove(window, (center - QPointF(120, 0)).toPoint(), 100)
                QTest.mouseRelease(window, Qt.LeftButton, pos=(center - QPointF(120, 0)).toPoint())
                assert viewport.property("zoom") <= 1
                capture("Dark-1440-photo-zoom-pan")
                click("fitPhoto")
            vm.sources.selectAllVisible()
            capture(f"Dark-{width}-batch")
            vm.sources.clearSelection()
            vm.media.showSource(video_id)
            until(lambda: bool(playback("hasVideo")))
            click("playPauseVideo")
            until(lambda: playback("position") > 100)
            click("playPauseVideo")
            seek = item("videoSeek")
            point = seek.mapToScene(QPointF(seek.width() * 0.55, seek.height() / 2))
            QTest.mouseClick(window, Qt.LeftButton, pos=point.toPoint())
            settle(300)
            assert playback("position") > playback("duration") * 0.4
            capture(f"Dark-{width}-video")
            if width == 1024:
                click("restoreMaterialProperties")
                capture("Dark-1024-properties-overlay")
                QTest.keyClick(window, Qt.Key_Escape)
                settle()
            vm.media.showSource(photo_id)
            idle()
        window.resize(1440, 900)
        settle()
        vm.setSourceView("Grid")
        click("expandMaterialsGrid")
        capture("Dark-1440-grid")
        click("expandMaterialsGrid")
        click("sourceListMode")
        capture("Dark-1440-visible-import-actions")
        click("collapseMaterialsCatalog")
        click("collapseMaterialProperties")
        capture("Dark-1440-panels-collapsed")
        click("restoreMaterialsCatalog")
        click("restoreMaterialProperties")
        vm.setTheme("Light")
        capture("Light-1440-photo")
        (args.output / "manifest.json").write_text(json.dumps({
            "project": str(args.project.resolve()), "captures": records,
            "qml_warnings": engine.load_errors,
            "native_title_bar": not bool(window.flags() & Qt.FramelessWindowHint),
            "exposed": window.isExposed(),
            "video": "Played, paused and sought through actual installed Qt Multimedia",
        }, indent=2), encoding="utf-8")
        assert not engine.load_errors, engine.load_errors
    finally:
        vm.media.closePreview()
        idle()
        window.close()
        engine.deleteLater()
        app.processEvents()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
