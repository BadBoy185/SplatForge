"""Bounded native direct-settings smoke with owned tiny photos/video and real services."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from fractions import Fraction
from pathlib import Path

from capture_frame_review import hashes
from capture_prepare import visual_item
from PySide6.QtCore import QEvent, QEventLoop, QObject, QPointF, QSettings, Qt, QTimer
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter
from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QTest

from splatforge.adapters.execution_storage import LocalExecutionRepository
from splatforge.application.source_participation import participation_draft
from splatforge.application.video_usage import video_usage_draft
from splatforge.bootstrap import (
    build_frame_review_service,
    build_gui_facade,
    build_media_service,
    build_prepare_data_service,
    build_project_service,
)
from splatforge.core.media import MediaType
from splatforge.core.video_usage import VideoSource, interval
from splatforge_gui.preferences import Preferences
from splatforge_gui.qml_app import create_engine
from splatforge_gui.qml_bridge import DesktopViewModel


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    output = parser.parse_args().output.absolute()
    output.mkdir(parents=True, exist_ok=False)
    fixture = output / "fixture"
    fixture.mkdir()
    app = QGuiApplication([])
    app.setQuitOnLastWindowClosed(False)
    assert app.platformName() != "offscreen", "Native exposed windows required"
    deadline = time.monotonic() + 120
    photos = [fixture / f"Photo {i} Ž.png" for i in range(2)]
    for index, path in enumerate(photos):
        raster = QImage(320, 200, QImage.Format.Format_RGB32)
        raster.fill(QColor(("#426679", "#81684d")[index]))
        painter = QPainter(raster)
        for column in range(12):
            painter.fillRect(column * 26, 20, 12, 140, QColor("#d9e1df"))
        painter.setPen(QColor("white"))
        painter.drawText(raster.rect(), Qt.AlignCenter, f"Generated photo {index}")
        painter.end()
        assert raster.save(str(path))
    video = fixture / "Original timeline Ž.mp4"
    executable = shutil.which("ffmpeg")
    assert executable, "Use installed FFmpeg; no implicit installation"
    subprocess.run([
        executable, "-hide_banner", "-nostdin", "-loglevel", "error", "-f", "lavfi",
        "-i", "testsrc2=size=320x180:rate=6:duration=2", "-c:v", "mpeg4", "-q:v", "2",
        "-output_ts_offset", "5", str(video),
    ], cwd=fixture, shell=False, check=True, capture_output=True, timeout=20)
    originals = hashes([*photos, video])
    projects, media = build_project_service(), build_media_service()
    root, photo_root = fixture / "Direct settings project Ž", fixture / "Photos only project"
    projects.create(root, "Prepare settings · generated media")
    projects.create(photo_root, "Photos only · generated media")
    media.add(root, [*photos, video])
    media.add(photo_root, [photos[0]])
    inventory = media.list(root)
    clip = next(s for s in inventory.sources if s.media_type == MediaType.VIDEO)
    excluded = next(s.source_id for s in inventory.sources if s.external_locator == str(photos[1]))
    document = participation_draft(
        projects.open(root), tuple(s.source_id for s in inventory.sources),
        {excluded}, included=False,
    )
    document = video_usage_draft(
        document, VideoSource.from_source(clip), "add", interval("5.25", "6.75"),
    )
    before = projects.save(root, document)

    def factory():
        facade = build_gui_facade()
        facade.factories["prepare_data"] = lambda: build_prepare_data_service(
            performance_path=output / "performance.json",
        )
        return facade

    prefs = Preferences(QSettings(str(output / "smoke.ini"), QSettings.IniFormat))
    prefs.set("recent", [])
    vm = DesktopViewModel(preferences=prefs)
    vm.controller.factory = factory
    engine, window = None, None
    report = dict(captures=[], passed=False, generated_sources=3, real_services=True)
    exceptions = []
    original_hook = sys.excepthook

    def hook(kind, value, trace):
        exceptions.append(str(value))
        original_hook(kind, value, trace)

    sys.excepthook = hook

    def settle(ms=25):
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    def until(predicate):
        end = min(deadline, time.monotonic() + 20)
        while not predicate() and time.monotonic() < end:
            settle(10)
        assert predicate(), f"Native settings timeout: {vm.prepare.state}"

    def idle():
        until(lambda: not vm.controller.mutating and not vm.controller.executor.busy
              and not vm.media.preview_executor.busy and not vm.media.gallery.executor.busy
              and not vm.sources.thumbnails.executor.busy
              and not vm.videoUsage.filmstrip.executor.busy)

    def item(name):
        result = visual_item(window.contentItem(), name) or window.findChild(QObject, name)
        assert result is not None, name
        return result

    def reveal(name):
        value = item(name)
        scroll = item("prepareInspectorScroll").property("contentItem")
        scroll.setProperty("contentY", 0)
        settle()
        center = value.mapToItem(scroll, QPointF(0, value.height() / 2)).y()
        maximum = max(0, scroll.property("contentHeight") - scroll.height())
        scroll.setProperty("contentY", max(0, min(maximum, center - scroll.height() / 2)))
        settle()
        return value

    def click(name):
        value = reveal(name)
        assert isinstance(value, QQuickItem) and value.isVisible() and value.isEnabled(), name
        point = value.mapToScene(QPointF(value.width() / 2, value.height() / 2))
        QTest.mouseClick(window, Qt.LeftButton, pos=point.toPoint())
        settle()

    def choose(key, value):
        name = "prepareSetting_" + key
        reveal(name)
        # Keyboard activation uses the actual ComboBox model and handler.
        options = ["fixed_fps", "sharpest_interval"] if key == "method" else ["jpeg", "png"]
        index = options.index(value)
        click(name)
        QTest.keyClick(window, Qt.Key_Home)
        for _ in range(index):
            QTest.keyClick(window, Qt.Key_Down)
        QTest.keyClick(window, Qt.Key_Return)
        settle()
        assert vm.prepare.settings.state["fields"][key] == value

    def text(key, value):
        click("prepareSetting_" + key)
        QTest.keyClick(window, Qt.Key_A, Qt.ControlModifier)
        for character in value:
            QTest.keyClick(window, Qt.Key(ord(character)))
        settle()
        assert vm.prepare.settings.state["fields"][key] == value

    def checked(key, value):
        name = "prepareSetting_" + key
        if item(name).property("checked") != value:
            click(name)
        assert item(name).property("checked") == value

    def capture(name, focus="prepareSetting_method"):
        reveal(focus)
        settle(70)
        assert window.isExposed()
        for control_name in ("prepareInspectorHeading", "savePrepareSettings", "planPrepare",
                             "runPrepare"):
            control = item(control_name)
            point = control.mapToScene(QPointF(0, 0))
            assert control.isVisible() and point.x() >= 0 and point.y() >= 95
            assert point.x() + control.width() <= 321
            assert point.y() + control.height() <= window.height()
        raster = window.grabWindow()
        assert raster.save(str(output / (name + ".png")))
        report["captures"].append(dict(
            name=name, logical=[window.width(), window.height()],
            raster=[raster.width(), raster.height()], dpr=window.devicePixelRatio(),
            exposed=True, form=vm.prepare.settings.state,
        ))

    def run():
        click("planPrepare")
        idle()
        assert vm.prepare.state["canRun"], vm.prepare.state
        request = vm.prepare._plan.request
        click("runPrepare")
        idle()
        assert vm.prepare.state["status"] == "succeeded", vm.prepare.state
        run_id = vm.prepare._history[0].run_id
        snapshot = LocalExecutionRepository()._load_run_snapshot(root, run_id)
        assert snapshot.route.candidate.settings == request.candidate
        assert snapshot.route.selection.settings == request.selection
        if request.quality is not None:
            assert snapshot.route.quality.settings == request.quality
        return run_id, request

    try:
        vm.openProject(str(root))
        idle()
        vm.controller.timer.stop()
        vm.navigate(1)
        vm.prepare.enter()
        idle()
        engine = create_engine(vm)
        window = engine.rootObjects()[0]
        until(window.isExposed)
        window.resize(1440, 900)
        vm.setTheme("Dark")
        capture("Dark-basic")
        vm.setTheme("Light")
        capture("Light-basic")
        choose("method", "sharpest_interval")
        text("interval_seconds", "1")
        text("candidate_fps", "3")
        choose("image_format", "png")
        text("png_compression_level", "3")
        click("togglePrepareOptions")
        checked("min_sharpness_enabled", True)
        assert not vm.prepare.settings.state["valid"]
        vm.setTheme("Dark")
        capture("Dark-threshold-validation", "prepareSetting_min_sharpness")
        text("min_sharpness", "0")
        checked("reject_duplicates", True)
        text("duplicate_hamming_threshold", "0")
        text("duplicate_lookback", "2")
        text("quality_max_side", "256")
        assert vm.prepare.settings.state["valid"]
        capture("Dark-optional-filters", "prepareSetting_reject_duplicates")
        vm.setTheme("Light")
        capture("Light-optional-filters", "prepareSetting_reject_duplicates")
        window.resize(1024, 640)
        capture("Light-compact-expanded", "prepareSetting_quality_max_side")
        vm.setTheme("Dark")
        capture("Dark-compact-expanded", "prepareSetting_quality_max_side")
        window.resize(1440, 900)
        vm.setTheme("Light")
        click("togglePrepareOptions")
        text("candidate_fps", "1")
        assert not vm.prepare.settings.state["valid"] and not vm.prepare.state["canPlan"]
        capture("Light-density-validation", "prepareSetting_candidate_fps")
        text("candidate_fps", "3")
        click("savePrepareSettings")
        idle()
        sharp_run, sharp_request = run()
        assert sharp_request.quality.quality_max_side == 256
        assert sharp_request.candidate.encoding.png_compression_level == 3
        assert sharp_request.selection.min_sharpness.as_fraction() == 0
        assert sharp_request.selection.duplicate_lookback == 2
        review = build_frame_review_service()
        page = review.page(root, sharp_run, filter="all")
        video_rows = [i for i in page.items if i.provenance.media_type == "video"]
        assert video_rows and all(
            Fraction("5.25") <= i.provenance.timestamp.seconds() < Fraction("6.75")
            for i in video_rows
        )
        assert all(i.provenance.width == 320 for i in page.items)
        review.apply(root, sharp_run, (video_rows[0].view_id,), "exclude",
                     expected_project_id=page.project_id, expected_revision=page.project_revision,
                     expected_review_digest=page.review_digest)
        vm.controller.refresh()
        idle()
        reviewed = projects.open(root).frame_review
        artifacts = hashes(p for p in (root / "artifacts").rglob("*") if p.is_file())
        vm.setTheme("Dark")
        capture("Dark-published-sharpest", "prepareHistory")
        choose("method", "fixed_fps")
        text("interval_seconds", "2")
        text("candidate_fps", "2")
        choose("image_format", "jpeg")
        text("jpeg_qscale", "5")
        click("savePrepareSettings")
        idle()
        assert projects.open(root).frame_review == reviewed
        fixed_run, fixed_request = run()
        assert fixed_request.quality is None
        assert fixed_request.candidate.encoding.jpeg_qscale == 5
        assert fixed_request.selection.target_fps.as_fraction() == Fraction(1, 2)
        fixed_summary = build_prepare_data_service().summary(root, fixed_run)
        assert fixed_summary.quality_measured_count is None
        vm.setTheme("Light")
        capture("Light-published-fixed", "prepareHistory")
        vm.prepare.selectRun(str(sharp_run))
        idle()
        click("togglePreparedRunSettings")
        frozen = vm.prepare.state["selectedSummary"]["settingsText"]
        assert "Sharpest" in frozen and "PNG · compression 3" in frozen
        assert vm.prepare.settings.state["fields"]["method"] == "fixed_fps"
        capture("Light-historical-settings", "preparedRunSettings")
        assert review.page(root, sharp_run, filter="all").manual_count == 1
        assert hashes(Path(p) for p in artifacts) == artifacts
        after = projects.open(root)
        assert after.source_participation == before.source_participation
        assert after.video_usage == before.video_usage and after.frame_review == reviewed
        vm.openProject(str(photo_root))
        idle()
        vm.navigate(1)
        vm.prepare.enter()
        idle()
        assert not vm.prepare.settings.state["hasVideo"]
        assert not item("prepareSetting_interval_seconds").isEnabled()
        window.resize(1024, 640)
        vm.setTheme("Dark")
        capture("Dark-photo-only-compact")
        assert hashes([*photos, video]) == originals
        assert not engine.load_errors and not exceptions
        report.update(passed=True, sharpest_run=str(sharp_run), fixed_run=str(fixed_run),
                      real_runs_with_pinned_settings=True, original_video_pts_after_trim=True,
                      review_and_sources_preserved=True, old_artifacts_preserved=True,
                      photo_timing_disabled=True, historical_settings_frozen=True)
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
        settle(80)
        report["exceptions"] = exceptions
        sys.excepthook = original_hook
        (output / "manifest.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Native direct-settings smoke passed: {len(report['captures'])} captures")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
