"""Short native Prepare Data smoke with three generated photos and real services.

Creates a fresh output directory. Moves only one owned generated photo temporarily
to exercise source-unavailable recovery. No user media, runtime or model is changed.
This is a bounded GUI scenario, not a full verification or performance benchmark.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

from PySide6.QtCore import QEvent, QEventLoop, QObject, QPointF, QSettings, Qt, QTimer
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter
from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QTest
from shiboken6 import isValid

from splatforge.application.source_participation import participation_draft
from splatforge.bootstrap import (
    build_gui_facade,
    build_media_service,
    build_prepare_data_service,
    build_project_service,
)
from splatforge_gui.preferences import Preferences
from splatforge_gui.qml_app import create_engine
from splatforge_gui.qml_bridge import DesktopViewModel


def visual_item(parent: QQuickItem, name: str) -> QQuickItem | None:
    if parent.objectName() == name:
        return parent
    return next((found for child in parent.childItems()
                 if (found := visual_item(child, name)) is not None), None)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.absolute()
    output.mkdir(parents=True, exist_ok=False)
    deadline = time.monotonic() + 90
    app = QGuiApplication([])
    app.setQuitOnLastWindowClosed(False)
    assert app.platformName() != "offscreen", "Native capture requires an exposed window"
    fixture = output / "fixture"
    fixture.mkdir()
    paths = []
    for index in range(3):
        path = fixture / f"Synthetic photo {index + 1} Ž.png"
        raster = QImage(480, 300, QImage.Format.Format_RGB32)
        raster.fill(QColor(("#426679", "#81684d", "#4c6a52")[index]))
        painter = QPainter(raster)
        for column in range(12):
            painter.fillRect(column * 40, 40, 20, 180,
                             QColor(("#c9d8da", "#afaa91", "#a2c5ad")[index]))
        painter.setPen(QColor("#ffffff"))
        painter.drawText(raster.rect(), Qt.AlignCenter, f"Synthetic photo {index + 1}")
        painter.end()
        assert raster.save(str(path))
        paths.append(path)
    projects, media = build_project_service(), build_media_service()
    root, empty = fixture / "Preparation project", fixture / "Empty project"
    projects.create(root, "Prepare Data · generated photos")
    projects.create(empty, "Empty project · generated fixture")
    imported = media.add(root, paths)
    ids = tuple(source.source_id for source in imported.added_sources)
    projects.save(root, participation_draft(projects.open(root), ids, {ids[-1]}, included=False))
    before = projects.open(root)
    original_hashes = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}

    def factory():
        facade = build_gui_facade()
        facade.factories["prepare_data"] = lambda: build_prepare_data_service(
            performance_path=output / "performance.json"
        )
        return facade

    prefs = Preferences(QSettings(str(output / "smoke.ini"), QSettings.IniFormat))
    prefs.set("recent", [])
    vm = DesktopViewModel(preferences=prefs)
    vm.controller.factory = factory
    engine, window = None, None
    controls: dict[str, QObject] = {}
    report = {"synthetic_photos": True, "real_prepare_service": True,
              "captures": [], "checks": [], "passed": False}
    exceptions = []
    original_hook = sys.excepthook

    def record_exception(kind, value, trace):
        exceptions.append(str(value))
        original_hook(kind, value, trace)

    sys.excepthook = record_exception

    def settle(milliseconds: int = 50) -> None:
        loop = QEventLoop()
        QTimer.singleShot(milliseconds, loop.quit)
        loop.exec()

    def until(predicate) -> None:
        local_deadline = min(deadline, time.monotonic() + 25)
        while not predicate() and time.monotonic() < local_deadline:
            settle(10)
        assert predicate(), f"Smoke timed out: {vm.prepare.state}"

    def idle() -> None:
        until(lambda: not vm.controller.mutating and not vm.controller.executor.busy
              and not vm.media.preview_executor.busy and not vm.media.gallery.executor.busy
              and not vm.sources.thumbnails.executor.busy
              and not vm.videoUsage.filmstrip.executor.busy)

    def item(name: str) -> QObject:
        previous = controls.get(name)
        if previous is not None and isValid(previous):
            return previous
        result = visual_item(window.contentItem(), name) or window.findChild(QObject, name)
        assert result is not None and isValid(result), name
        controls[name] = result
        return result

    def click(name: str) -> None:
        control = item(name)
        assert isinstance(control, QQuickItem) and control.isVisible() and control.isEnabled(), name
        point = control.mapToScene(QPointF(control.width() / 2, control.height() / 2))
        QTest.mouseClick(window, Qt.LeftButton, pos=point.toPoint())
        settle(20)

    def capture(name: str) -> None:
        settle(70)
        assert window.isExposed()
        raster = window.grabWindow()
        assert not raster.isNull() and raster.save(str(output / f"{name}.png"))
        report["captures"].append({
            "name": name, "logical": [window.width(), window.height()],
            "raster": [raster.width(), raster.height()], "dpr": window.devicePixelRatio(),
            "native_title_bar": not bool(window.flags() & Qt.FramelessWindowHint),
            "exposed": window.isExposed(), "state": vm.prepare.state,
        })

    def scroll_inspector(bottom: bool) -> None:
        flick = item("prepareInspectorScroll").property("contentItem")
        controls["inspectorFlickable"] = flick
        maximum = max(0, float(flick.property("contentHeight")) - flick.height())
        assert flick.setProperty("contentY", maximum if bottom else 0)
        settle(50)

    def assert_inspector_contains(name: str) -> None:
        viewport, control = item("prepareInspectorScroll"), item(name)
        top = control.mapToScene(QPointF(0, 0)).y()
        viewport_top = viewport.mapToScene(QPointF(0, 0)).y()
        assert control.isVisible() and top >= viewport_top - 1
        assert top + control.height() <= viewport_top + viewport.height() + 1

    missing = fixture / "Temporarily unavailable generated photo.png"
    try:
        vm.openProject(str(root))
        idle()
        vm.navigate(1)
        engine = create_engine(vm)
        window = engine.rootObjects()[0]
        until(window.isExposed)
        vm.setTheme("Dark")
        window.resize(1440, 900)
        click("prepareDataEntry")
        idle()
        if not vm.prepare.state["plan"]:
            click("planPrepare")
            idle()
        assert vm.prepare.state["canRun"]
        capture("Dark-plan")
        # Both exact file targets are owned by this newly created fixture.
        assert paths[0].resolve().is_relative_to(fixture.resolve())
        assert missing.absolute().is_relative_to(fixture.resolve()) and not missing.exists()
        paths[0].rename(missing)
        try:
            click("runPrepare")
            idle()
            assert vm.prepare.state["error"] and not vm.prepare.state["selectedRun"]
            assert "did not finish" in vm.prepare.state["message"]
            capture("Dark-source-error")
            vm.setTheme("Light")
            window.resize(1024, 640)
            scroll_inspector(True)
            assert_inspector_contains("prepareError")
            capture("Light-compact-error-scrolled")
        finally:
            if missing.exists():
                missing.rename(paths[0])
        vm.setTheme("Dark")
        window.resize(1440, 900)
        scroll_inspector(False)
        click("planPrepare")
        idle()
        click("runPrepare")
        if vm.prepare.state["busy"]:
            capture("Dark-preparing")
        idle()
        until(lambda: vm.prepare.state["selectedSummary"].get("selectedCount") == 2)
        until(lambda: vm.media.gallery.rowCount() == 2
              and all(vm.media.gallery.cache.get(ref.identity) is not None
                      for ref in vm.media.gallery.references))
        run_id = vm.prepare.state["selectedRun"]
        capture("Dark-published")
        for theme in ("Dark", "Light"):
            vm.setTheme(theme)
            window.resize(1024, 640)
            capture(theme + "-compact-published")
        scroll_inspector(True)
        assert_inspector_contains("prepareResultCounts")
        capture("Light-compact-summary-scrolled")
        click("returnToSources")
        assert not vm.prepare.state["active"]
        vm.openProject(str(empty))
        idle()
        vm.prepare.enter()
        idle()
        assert not vm.prepare.state["canRun"] and not vm.prepare.state["history"]
        capture("Light-empty-project")
        vm.openProject(str(root))
        idle()
        vm.prepare.enter()
        idle()
        vm.prepare.selectRun(run_id)
        idle()
        until(lambda: vm.prepare.state["selectedSummary"].get("selectedCount") == 2)
        window.resize(1440, 900)
        scroll_inspector(False)
        capture("Light-persisted-reopen")
        assert projects.open(root) == before
        assert {str(path): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in paths} == original_hashes
        assert not engine.load_errors and not exceptions
        report["checks"] = [
            "real plan and ViewsService pipeline; only two Included photo occurrences processed",
            "missing owned source fails without a selected publication; restore and retry succeed",
            "saved succeeded run readback and bounded image gallery after switch/reopen",
            "source bytes, project intent, participation and source UUIDs unchanged",
            "native Dark/Light compact windows; no runtime provisioning or benchmark",
            "compact inspector scroll exposes full error and published counts",
        ]
    finally:
        deadline = time.monotonic() + 10
        vm.controller.timer.stop()
        vm.controller.cancel()
        vm.media.closePreview()
        vm.videoUsage.filmstrip.stop()
        vm.sources.set_thumbnails_active(False)
        idle()
        if window is not None:
            window.close()
        if engine is not None:
            report["qml_warnings"] = engine.load_errors
            engine.deleteLater()
        vm.deleteLater()
        app.sendPostedEvents(None, QEvent.DeferredDelete)
        settle(100)
        report["exceptions"] = exceptions
        sys.excepthook = original_hook
        (output / "manifest.json").write_text(
            json.dumps(report, indent=2, default=str), encoding="utf-8"
        )
    assert not exceptions and not report.get("qml_warnings")
    report["passed"] = True
    (output / "manifest.json").write_text(
        json.dumps(report, indent=2, default=str), encoding="utf-8"
    )
    print(f"Native Prepare smoke passed: {len(report['captures'])} captures")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
