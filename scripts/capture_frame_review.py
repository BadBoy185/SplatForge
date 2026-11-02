"""Bounded native image-review smoke with generated photos and real publications."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path
from uuid import UUID

from capture_prepare import visual_item
from PySide6.QtCore import QEvent, QEventLoop, QObject, QPointF, QSettings, Qt, QTimer
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter
from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QTest

from splatforge.bootstrap import (
    build_frame_review_service,
    build_media_service,
    build_prepare_data_service,
    build_project_service,
)
from splatforge.core.quality import SharpestIntervalSettings, parse_non_negative_rational
from splatforge.core.views import parse_fps
from splatforge_gui.preferences import Preferences
from splatforge_gui.qml_app import create_engine
from splatforge_gui.qml_bridge import DesktopViewModel


def hashes(paths) -> dict[str, str]:
    return {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    output = parser.parse_args().output.absolute()
    output.mkdir(parents=True, exist_ok=False)
    deadline = time.monotonic() + 100
    app = QGuiApplication([])
    app.setQuitOnLastWindowClosed(False)
    assert app.platformName() != "offscreen", "Native smoke requires an exposed Windows window"
    fixture = output / "fixture"
    fixture.mkdir()
    paths = []
    for index in range(4):
        path = fixture / f"Generated photo {index + 1} Ž.png"
        raster = QImage(640, 400, QImage.Format.Format_RGB32)
        raster.fill(QColor(("#576e81", "#426679", "#81684d", "#4c6a52")[index]))
        if index:
            painter = QPainter(raster)
            for column in range(16):
                painter.fillRect(column * 40, 40, 20, 280, QColor("#d9e1df"))
            painter.setPen(QColor("#ffffff"))
            painter.drawText(raster.rect(), Qt.AlignCenter, f"Generated review photo {index + 1}")
            painter.end()
        assert raster.save(str(path))
        paths.append(path)
    projects, media = build_project_service(), build_media_service()
    root, other = fixture / "Image review Ž project", fixture / "Other empty project"
    document = projects.create(root, "Image review · generated photos")
    projects.create(other, "Empty project · generated fixture")
    settings = SharpestIntervalSettings(
        target_fps=parse_fps("2"), min_sharpness=parse_non_negative_rational("1"),
        reject_duplicates=False,
    )
    frame = document.settings.frame_selection.model_copy(update={
        "method_id": "frame_selection.sharpest_interval",
        "settings": settings.model_dump(mode="json"),
    })
    projects.save(root, document.model_copy(update={
        "settings": document.settings.model_copy(update={"frame_selection": frame}),
    }))
    media.add(root, paths)
    preparation = build_prepare_data_service(performance_path=output / "performance.json")
    document = projects.open(root)
    expected = dict(expected_project_id=document.project_id, expected_revision=document.revision)
    plan = preparation.plan(root, **expected)
    result = preparation.run(root, plan.request, **expected)
    assert result.status == "succeeded"
    review = build_frame_review_service()
    page = review.page(root, result.run_id, filter="all")
    assert (page.candidate_count, page.selected_count, page.rejected_count) == (4, 3, 1)
    rejected = next(str(i.view_id) for i in page.items if not i.included)
    originals = hashes(paths)
    publications = hashes(p for p in (root / "artifacts").rglob("*") if p.is_file())
    prefs = Preferences(QSettings(str(output / "smoke.ini"), QSettings.IniFormat))
    prefs.set("recent", [])
    vm = DesktopViewModel(preferences=prefs)
    engine, window = None, None
    report = {"generated_photos": True, "real_services": True, "captures": [], "passed": False}
    exceptions = []
    original_hook = sys.excepthook

    def hook(kind, value, trace):
        exceptions.append(str(value))
        original_hook(kind, value, trace)

    sys.excepthook = hook

    def settle(milliseconds=30):
        loop = QEventLoop()
        QTimer.singleShot(milliseconds, loop.quit)
        loop.exec()

    def until(predicate):
        end = min(deadline, time.monotonic() + 20)
        while not predicate() and time.monotonic() < end:
            settle(10)
        assert predicate(), f"Native review timeout: {vm.prepare.review.state}"

    def idle():
        until(lambda: not vm.controller.mutating and not vm.controller.executor.busy
              and not vm.media.preview_executor.busy and not vm.media.gallery.executor.busy
              and not vm.sources.thumbnails.executor.busy
              and not vm.videoUsage.filmstrip.executor.busy)

    def item(name):
        control = visual_item(window.contentItem(), name) or window.findChild(QObject, name)
        assert control is not None, name
        return control

    def click(name):
        control = item(name)
        assert isinstance(control, QQuickItem) and control.isVisible() and control.isEnabled(), name
        point = control.mapToScene(QPointF(control.width() / 2, control.height() / 2))
        QTest.mouseClick(window, Qt.LeftButton, pos=point.toPoint())
        settle()

    def capture(name):
        settle(80)
        assert window.isExposed()
        raster = window.grabWindow()
        assert not raster.isNull() and raster.save(str(output / f"{name}.png"))
        report["captures"].append(dict(
            name=name, logical=[window.width(), window.height()],
            raster=[raster.width(), raster.height()], dpr=window.devicePixelRatio(),
            exposed=window.isExposed(), state=vm.prepare.review.state,
        ))

    try:
        vm.openProject(str(root))
        idle()
        vm.controller.timer.stop()
        vm.navigate(1)
        engine = create_engine(vm)
        window = engine.rootObjects()[0]
        until(window.isExposed)
        window.resize(1440, 900)
        vm.setTheme("Dark")
        click("prepareDataEntry")
        idle()
        vm.prepare.selectRun(str(result.run_id))
        idle()
        presenter = vm.prepare.review
        assert presenter.state["selectedTotal"] == 3
        capture("Dark-selected-grid")
        click("reviewFilter_rejected")
        idle()
        click("viewFrame_" + rejected)
        idle()
        capture("Dark-rejected-preview")
        click("previewKeepFrame")
        idle()
        assert presenter.state["selectedTotal"] == 4 and presenter.state["total"] == 0
        capture("Dark-empty-rejected-after-keep")
        click("reviewFilter_all")
        idle()
        click("viewFrame_" + rejected)
        idle()
        click("previewResetFrame")
        idle()
        assert presenter.state["selectedTotal"] == 3
        assert presenter.state["viewed"]["autoSelected"] is False
        capture("Dark-reset-to-automatic")
        presenter.close()
        click("reviewFilter_selected")
        idle()
        identities = list(presenter.state["items"])
        first, second = identities[:2]
        click("selectFrame_" + first)
        click("viewFrame_" + second)
        idle()
        assert presenter.state["selectedIds"] == [first]
        capture("Dark-batch-distinct-from-preview")
        click("batchExcludeFrames")
        idle()
        assert presenter.state["selectedTotal"] == 2
        assert presenter.state["viewedId"] == second
        saved = review.page(root, result.run_id, filter="all")
        assert next(i for i in saved.items if str(i.view_id) == first).decision == "exclude"
        current = presenter.state["viewedId"]
        neighbor = presenter.state["viewed"]["nextId"] or presenter.state["viewed"]["previousId"]
        click("previewExcludeFrame")
        idle()
        assert presenter.state["viewedId"] == neighbor and current != neighbor
        capture("Dark-exclude-and-advance")
        for theme in ("Dark", "Light"):
            vm.setTheme(theme)
            window.resize(1024, 640)
            capture(theme + "-compact-preview")
        click("returnToSources")
        vm.openProject(str(other))
        idle()
        vm.prepare.enter()
        idle()
        assert not vm.prepare.state["history"] and not presenter.state["items"]
        capture("Light-empty-project")
        vm.openProject(str(root))
        idle()
        vm.prepare.enter()
        idle()
        vm.prepare.selectRun(str(result.run_id))
        idle()
        assert presenter.state["selectedTotal"] == 1 and presenter.state["manualTotal"] == 2
        window.resize(1440, 900)
        capture("Light-persisted-reopen")
        # A real competing metadata writer makes the retained UI revision stale.
        # The generated project's prior decisions must remain authoritative.
        saved_before_conflict = review.page(root, result.run_id, filter="all")
        current_document = projects.open(root)
        projects.save(root, current_document.model_copy(update={
            "label": "Review conflict fixture",
        }))
        presenter.view(next(iter(presenter.state["items"])))
        idle()
        click("previewExcludeFrame")
        idle()
        assert presenter.state["error"] and presenter.state["message"] != "Frame decisions saved."
        assert not presenter.state["canEdit"] and not presenter.state["items"]
        counts = item("prepareResultCounts").property("text")
        assert "Automatic: 3 selected" in counts and "Review membership unavailable" in counts
        unchanged = review.page(root, result.run_id, filter="all")
        assert unchanged.review_digest == saved_before_conflict.review_digest
        assert unchanged.effective_run_id == saved_before_conflict.effective_run_id
        window.resize(1024, 640)
        capture("Light-save-conflict")
        click("refreshPreparedHistory")
        idle()
        assert not presenter.state["error"] and presenter.state["selectedTotal"] == 1
        capture("Light-save-conflict-reloaded")
        assert hashes(paths) == originals
        assert hashes(Path(path) for path in publications) == publications
        assert projects.open(root).source_participation == document.source_participation
        effective = UUID(presenter.state["effectiveRun"])
        assert effective != result.run_id
        report["effective_run"] = str(effective)
        report["checks"] = [
            "real preparation/quality rejects the uniform generated photo",
            "Keep Anyway forces include; Reset restores automatic rejection",
            "page batch UUID differs from preview UUID; exclusion advances after save",
            "project switch clears rows; reopen restores exact decisions and counts",
            "real metadata revision conflict reports failure and preserves the committed head",
            "originals, candidate/automatic publications and source participation unchanged",
            "native exposed Dark/Light regular and compact windows",
        ]
        assert not engine.load_errors and not exceptions
        report["passed"] = True
    finally:
        deadline = time.monotonic() + 10
        vm.controller.timer.stop()
        vm.media.closePreview()
        vm.media.gallery.set_active(False)
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
            json.dumps(report, indent=2, default=str), encoding="utf-8",
        )
    print(f"Native review smoke passed: {len(report['captures'])} captures")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
