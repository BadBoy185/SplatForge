"""Capture Materials import in exposed Windows Qt windows.

Drop feedback is produced by synthetic external Qt URL events, not Explorer input.
The supplied populated project and its originals are read-only. An owned empty
project and isolated preferences are created under the output directory.
"""

import argparse
import json
import time
from pathlib import Path
from uuid import uuid4

from capture_materials import visual_item
from PySide6.QtCore import QEventLoop, QMimeData, QPointF, QSettings, Qt, QTimer, QUrl
from PySide6.QtGui import QDragEnterEvent, QDragLeaveEvent, QGuiApplication

from splatforge.bootstrap import build_project_service
from splatforge_gui.preferences import Preferences
from splatforge_gui.qml_app import create_engine
from splatforge_gui.qml_bridge import DesktopViewModel


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--photo", default="")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    app = QGuiApplication([])
    empty = (args.output / ("empty-review-" + uuid4().hex[:8])).resolve()
    build_project_service().create(empty, "Media import review")
    prefs = Preferences(QSettings(str(args.output / "capture.ini"), QSettings.IniFormat))
    prefs.set("recent", [])
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
        assert predicate(), "Timed out waiting for capture state"

    def idle():
        until(lambda: not vm.controller.executor.busy and not vm.controller.mutating
              and not vm.media.preview_executor.busy)

    vm.openProject(str(args.project.resolve()))
    idle()
    row = next(r for r in vm.sources.rows if r.values["type"] == "photo"
               and (not args.photo or r.values["filename"] == args.photo))
    photo_id = str(row.identity)
    photo_path = vm.local_path(row.values["locator"])
    engine = create_engine(vm)
    window = engine.rootObjects()[0]
    captures = []

    def capture(name, *, synthetic_drag=False):
        idle()
        settle(300)
        assert window.isExposed()
        raster = window.grabWindow()
        assert raster.save(str(args.output / (name + ".png")))
        captures.append({"file": name + ".png", "logical_size": [window.width(), window.height()],
                         "physical_size": [raster.width(), raster.height()],
                         "dpr": window.devicePixelRatio(), "synthetic_drag": synthetic_drag})
        print(name, flush=True)

    try:
        for theme in ("Dark", "Light"):
            vm.setTheme(theme)
            for width, height in ((1440, 900), (1024, 640)):
                vm.openProject(str(empty))
                idle()
                vm.navigate(1)
                window.resize(width, height)
                settle()
                capture(f"{theme}-{width}-empty")
                mime = QMimeData()
                mime.setUrls([QUrl.fromLocalFile(str(photo_path))])
                drag = QDragEnterEvent(QPointF(650, 300), Qt.CopyAction, mime,
                                       Qt.LeftButton, Qt.NoModifier)
                QGuiApplication.sendEvent(window, drag)
                assert drag.isAccepted()
                feedback = visual_item(window.contentItem(), "materialsDropFeedback")
                assert feedback.isVisible()
                capture(f"{theme}-{width}-drop-active", synthetic_drag=True)
                QGuiApplication.sendEvent(window, QDragLeaveEvent())
                assert not feedback.isVisible()
                vm.openProject(str(args.project.resolve()))
                idle()
                vm.navigate(1)
                vm.media.showSource(photo_id)
                idle()
                until(lambda: vm.media.state["previewStatus"] == "Ready")
                capture(f"{theme}-{width}-populated")
        (args.output / "manifest.json").write_text(json.dumps({
            "project": str(args.project.resolve()), "owned_empty_project": str(empty),
            "captures": captures, "qml_warnings": engine.load_errors,
            "exposed": window.isExposed(),
            "native_title_bar": not bool(window.flags() & Qt.FramelessWindowHint),
            "drag_evidence": "Synthetic QDragEnterEvent/QDragLeaveEvent; Explorer not verified",
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
