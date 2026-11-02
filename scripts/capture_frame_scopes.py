"""Short native scope/provenance smoke using owned generated photos and video.

Temporarily relocates one generated photo, records a missing check and explicitly
relinks it. No user originals or existing projects are touched.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

from capture_frame_review import hashes
from capture_prepare import visual_item
from PySide6.QtCore import QEvent, QEventLoop, QObject, QPointF, QSettings, Qt, QTimer
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter
from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QTest

from splatforge.application.video_usage import video_usage_draft
from splatforge.bootstrap import (
    build_frame_review_service,
    build_media_service,
    build_prepare_data_service,
    build_project_service,
)
from splatforge.core.logical_source_groups import LogicalSourceGroup, LogicalSourceGroups
from splatforge.core.media import MediaType
from splatforge.core.video_usage import VideoSource, interval
from splatforge.core.views import FixedFpsSettings, parse_fps
from splatforge_gui.preferences import Preferences
from splatforge_gui.qml_app import create_engine
from splatforge_gui.qml_bridge import DesktopViewModel


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    output = parser.parse_args().output.absolute()
    output.mkdir(parents=True, exist_ok=False)
    deadline = time.monotonic() + 120
    app = QGuiApplication([])
    app.setQuitOnLastWindowClosed(False)
    assert app.platformName() != "offscreen", "Native windows required"
    fixture = output / "fixture"
    fixture.mkdir()
    first = fixture / ("Long original folder Ž " + "a" * 32) / ("photo source " + "b" * 32)
    second = fixture / "Other source Ž"
    for directory in (first, second):
        directory.mkdir(parents=True)
    photos = [first / "same.png", second / "same.png"]
    for index, path in enumerate(photos):
        raster = QImage(640, 400, QImage.Format.Format_RGB32)
        raster.fill(QColor(("#426679", "#81684d")[index]))
        painter = QPainter(raster)
        for column in range(16):
            painter.fillRect(column * 40, 40, 20, 280, QColor("#d9e1df"))
        painter.setPen(QColor("white"))
        painter.drawText(raster.rect(), Qt.AlignCenter, f"Generated source {index + 1} · same.png")
        painter.end()
        assert raster.save(str(path))
    video = fixture / "Flight clip Ž.mp4"
    executable = shutil.which("ffmpeg")
    assert executable, "Installed FFmpeg required; do not install implicitly"
    subprocess.run([
        executable, "-hide_banner", "-nostdin", "-loglevel", "error", "-f", "lavfi",
        "-i", "testsrc2=size=320x180:rate=4:duration=4", "-c:v", "mpeg4", "-q:v", "2",
        "-output_ts_offset", "5", str(video),
    ], cwd=fixture, shell=False, capture_output=True, check=True, timeout=20)
    originals = hashes([*photos, video])
    projects, media = build_project_service(), build_media_service()
    root = fixture / "Scope review project Ž"
    projects.create(root, "Scopes · generated media")
    imported = media.add(root, [*photos, video])
    sources = imported.added_sources
    # Summary UUIDs are sufficient to find the complete saved inventory records.
    inventory = media.list(root)
    video_source = next(s for s in inventory.sources if s.media_type == MediaType.VIDEO)
    photo_source = next(s for s in inventory.sources if s.external_locator == str(photos[0]))
    photo_ids = tuple(s.source_id for s in inventory.sources if s.media_type == MediaType.PHOTO)
    photo_group, video_group, empty_group = uuid4(), uuid4(), uuid4()
    document = projects.open(root)
    document = video_usage_draft(
        document, VideoSource.from_source(video_source), "add", interval("6", "7.5"),
    )
    selection = FixedFpsSettings(target_fps=parse_fps("2"))
    frame = document.settings.frame_selection.model_copy(update={
        "method_id": "frame_selection.fixed_fps", "settings": selection.model_dump(mode="json"),
    })
    groups = LogicalSourceGroups(
        groups=(LogicalSourceGroup(group_id=photo_group, label="Tripod photos"),
                LogicalSourceGroup(group_id=video_group, label="Flight frames"),
                LogicalSourceGroup(group_id=empty_group, label="Empty saved group")),
        source_assignments={
            **{i: photo_group for i in photo_ids}, video_source.source_id: video_group,
        },
    )
    document = projects.save(root, document.model_copy(update={
        "settings": document.settings.model_copy(update={"frame_selection": frame}),
        "logical_source_groups": groups,
    }))
    prepare = build_prepare_data_service(performance_path=output / "performance.json")
    expected = dict(expected_project_id=document.project_id, expected_revision=document.revision)
    plan = prepare.plan(root, **expected)
    result = prepare.run(root, plan.request, **expected)
    assert result.status == "succeeded"
    review = build_frame_review_service()
    page = review.page(root, result.run_id, filter="all")
    video_rows = [i for i in page.items if i.source_id == video_source.source_id]
    assert video_rows and all(6 <= i.provenance.timestamp.seconds() < 7.5 for i in video_rows)
    excluded = video_rows[0]
    review.apply(root, result.run_id, (excluded.view_id,), "exclude",
                 expected_project_id=page.project_id, expected_revision=page.project_revision,
                 expected_review_digest=page.review_digest)
    saved = review.page(root, result.run_id, filter="all")
    before_document = projects.open(root)
    artifacts = hashes(p for p in (root / "artifacts").rglob("*") if p.is_file())
    relocated = fixture / "Relinked source Ž" / "same.png"
    relocated.parent.mkdir()
    assert photos[0].resolve().is_relative_to(fixture.resolve())
    assert relocated.resolve().is_relative_to(fixture.resolve())
    photos[0].rename(relocated)
    missing = media.verify(root, source_ids={photo_source.source_id})
    assert str(missing[0].outcome) == "missing"
    prefs = Preferences(QSettings(str(output / "smoke.ini"), QSettings.IniFormat))
    prefs.set("recent", [])
    vm = DesktopViewModel(preferences=prefs)
    engine, window = None, None
    report = dict(captures=[], passed=False, generated_sources=len(sources), real_services=True)
    exceptions = []
    original_hook = sys.excepthook

    def hook(kind, value, trace):
        exceptions.append(str(value))
        original_hook(kind, value, trace)

    sys.excepthook = hook

    def settle(ms=30):
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    def until(predicate):
        end = min(deadline, time.monotonic() + 20)
        while not predicate() and time.monotonic() < end:
            settle(10)
        assert predicate(), f"Native scope timeout: {vm.prepare.review.state}"

    def idle():
        until(lambda: not vm.controller.mutating and not vm.controller.executor.busy
              and not vm.media.preview_executor.busy and not vm.media.gallery.executor.busy
              and not vm.sources.thumbnails.executor.busy)

    def item(name):
        value = visual_item(window.contentItem(), name) or window.findChild(QObject, name)
        assert value is not None, name
        return value

    def click(name):
        value = item(name)
        assert isinstance(value, QQuickItem) and value.isVisible() and value.isEnabled(), name
        point = value.mapToScene(QPointF(value.width() / 2, value.height() / 2))
        QTest.mouseClick(window, Qt.LeftButton, pos=point.toPoint())
        settle()

    def scroll(name, fraction):
        flick = item(name).property("contentItem")
        maximum = max(0, float(flick.property("contentHeight")) - flick.height())
        flick.setProperty("contentY", maximum * fraction)
        settle()

    def scope(key):
        presenter = vm.prepare.review
        assert "undefined" not in item("prepareResultCounts").property("text")
        index = next(i for i, value in enumerate(presenter.state["scopes"]) if value["key"] == key)
        scroll("prepareInspectorScroll", 1)
        click("preparedFrameScope")
        QTest.keyClick(window, Qt.Key_Home)
        for _ in range(index):
            QTest.keyClick(window, Qt.Key_Down)
        QTest.keyClick(window, Qt.Key_Return)
        idle()
        assert presenter.state["scope"] == key

    def capture(name):
        settle(80)
        assert window.isExposed()
        raster = window.grabWindow()
        assert raster.save(str(output / (name + ".png")))
        report["captures"].append(dict(
            name=name, logical=[window.width(), window.height()],
            raster=[raster.width(), raster.height()], dpr=window.devicePixelRatio(),
            exposed=True, state=vm.prepare.review.state,
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
        presenter = vm.prepare.review
        capture("Dark-all-sources")
        scope(f"group/{video_group}")
        assert presenter.state["scopeSelectedTotal"] == len(video_rows) - 1
        capture("Dark-flight-selected")
        click("reviewFilter_all")
        idle()
        identity = str(excluded.view_id)
        click("viewFrame_" + identity)
        idle()
        provenance = presenter.state["viewed"]["provenance"]
        assert provenance["sourceName"] == video.name
        assert provenance["originalTime"].startswith(("00:00:06", "00:00:07"))
        assert not presenter.state["viewed"]["included"]
        capture("Dark-video-source-time")
        bar = item("frameProvenanceScrollbar")
        viewport = item("frameProvenanceScroll")
        assert bar.height() >= viewport.height() - 2
        assert bar.x() >= viewport.width() - bar.width() - 2
        point = bar.mapToScene(QPointF(bar.width() / 2, bar.height() * 0.8))
        QTest.mouseClick(window, Qt.LeftButton, pos=point.toPoint())
        settle()
        assert viewport.property("contentItem").property("contentY") > 0
        scroll("frameProvenanceScroll", 1)
        capture("Dark-video-details-scrolled")
        presenter.select(identity, True)
        scope(f"source/{photo_source.source_id}")
        assert not presenter.state["selectedIds"] and not presenter.state["viewedId"]
        photo_id = next(iter(presenter.state["items"]))
        click("viewFrame_" + photo_id)
        idle()
        assert item("frameProvenanceScroll").property("contentItem").property("contentY") == 0
        evidence = presenter.state["viewed"]["provenance"]
        assert evidence["originalTime"] == "Not applicable — photo"
        assert evidence["automaticScore"] == "Not recorded"
        assert evidence["pathAtPreparation"] == str(photos[0])
        assert "missing" in evidence["sourceCheck"]
        capture("Dark-missing-photo-provenance")
        scroll("frameProvenanceScroll", 0.5)
        capture("Dark-long-original-locator")
        idle()
        media.relink(root, photo_source.source_id, relocated)
        vm.controller.refresh()
        idle()
        until(lambda: presenter.state["count"] == 1 and not presenter.state["loading"])
        presenter.view(photo_id)
        idle()
        evidence = presenter.state["viewed"]["provenance"]
        assert evidence["currentLocator"] == str(relocated)
        assert evidence["pathAtPreparation"] == str(photos[0])
        vm.setTheme("Light")
        capture("Light-relinked-provenance")
        scroll("frameProvenanceScroll", 0.45)
        capture("Light-historical-and-current-locators")
        window.resize(1024, 640)
        scroll("frameProvenanceScroll", 0)
        viewport = item("frameProvenanceScroll")
        viewport_top = viewport.mapToScene(QPointF(0, 0)).y()
        for name in ("frameEffectiveStatus", "frameAutomaticStatus"):
            status = item(name)
            top = status.mapToScene(QPointF(0, 0)).y()
            assert top >= viewport_top and top + status.height() <= viewport_top + viewport.height()
        assert item("frameProvenanceScrollbar").isVisible()
        capture("Light-compact-provenance")
        vm.setTheme("Dark")
        capture("Dark-compact-provenance")
        scope(f"group/{empty_group}")
        assert not presenter.state["items"] and presenter.state["scopeCandidateTotal"] == 0
        assert not presenter.state["viewedId"] and not presenter.state["selectedIds"]
        capture("Dark-empty-scope")
        vm.setTheme("Light")
        capture("Light-empty-scope")
        scope("all")
        after = review.page(root, result.run_id, filter="all")
        assert after.review_digest == saved.review_digest
        assert after.effective_run_id == saved.effective_run_id
        assert projects.open(root).frame_review == before_document.frame_review
        assert projects.open(root).source_participation == before_document.source_participation
        assert hashes(Path(p) for p in artifacts) == artifacts
        assert hashes([relocated, photos[1], video])[str(relocated)] == originals[str(photos[0])]
        assert hashes([photos[1], video]) == {str(p): originals[str(p)] for p in (photos[1], video)}
        assert not engine.load_errors and not exceptions
        report.update(passed=True, original_video_time=True, real_missing_and_relink=True,
                      inspector_mouse_scroll_and_uuid_reset=True,
                      review_unchanged=True, immutable_artifacts_unchanged=True,
                      long_path_characters=len(str(photos[0])), duplicate_source_names=True)
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
            json.dumps(report, indent=2, default=str), encoding="utf8",
        )
    print(f"Native scopes smoke passed: {len(report['captures'])} captures")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
