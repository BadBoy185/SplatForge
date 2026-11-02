"""Exercise folder relinking in exposed Windows windows using owned synthetic photos.

Creates a NEW output directory and moves only the PNG subtree generated inside it.
The optional worker hold exercises pending/Cancel, not measured processing speed.
No user project, original, runtime, model or system setting is modified.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path
from threading import Event

from PySide6.QtCore import QEvent, QEventLoop, QObject, QPointF, QSettings, Qt, QTimer
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter
from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QTest
from shiboken6 import isValid

from splatforge.application.logical_source_groups import logical_groups_draft
from splatforge.application.source_participation import participation_draft
from splatforge.bootstrap import build_gui_facade, build_media_service, build_project_service
from splatforge_gui.preferences import Preferences
from splatforge_gui.qml_app import create_engine
from splatforge_gui.qml_bridge import DesktopViewModel


def visual_item(parent: QQuickItem, name: str) -> QQuickItem | None:
    if parent.objectName() == name:
        return parent
    return next((found for child in parent.childItems()
                 if (found := visual_item(child, name)) is not None), None)


class WorkerHold:
    """An explicit synthetic scheduling fixture around the real application service."""

    def __init__(self) -> None:
        self.operation = ""
        self.entered = Event()
        self.release = Event()

    def wait(self, name: str, cancellation) -> None:
        if name != self.operation:
            return
        self.entered.set()
        while not self.release.wait(0.01):
            cancellation.checkpoint()
        cancellation.checkpoint()


class HeldRelink:
    def __init__(self, delegate, hold: WorkerHold) -> None:
        self.delegate, self.hold = delegate, hold

    def preview(self, *args, **kwargs):
        self.hold.wait("preview", kwargs["cancellation"])
        return self.delegate.preview(*args, **kwargs)

    def apply(self, *args, **kwargs):
        self.hold.wait("apply", kwargs["cancellation"])
        return self.delegate.apply(*args, **kwargs)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.absolute()
    output.mkdir(parents=True, exist_ok=False)
    app = QGuiApplication([])
    app.setQuitOnLastWindowClosed(False)
    assert app.platformName() != "offscreen", "Native capture requires a window platform"
    fixture = output / "fixture"
    fixture.mkdir()
    old, relocated, wrong = [fixture / name for name in (
        "Original photos Ž", "Relocated photos Ž", "Different candidate",
    )]
    names = ("Drone/Обзор 01.png", "Drone/Detail 02.png", "Phone/Photo 03.png")
    for index, name in enumerate(names):
        path = old / name
        path.parent.mkdir(parents=True, exist_ok=True)
        raster = QImage(480, 300, QImage.Format.Format_RGB32)
        raster.fill(QColor(("#456879", "#8c7157", "#55705c")[index]))
        painter = QPainter(raster)
        painter.setPen(QColor("#ffffff"))
        painter.drawText(raster.rect(), Qt.AlignCenter, f"Synthetic photo {index + 1}")
        painter.end()
        assert raster.save(str(path))
    projects, media = build_project_service(), build_media_service()
    root = fixture / "Relink review project"
    projects.create(root, "Folder relink · synthetic photos")
    imported = media.add(root, [old / name for name in names])
    ids = tuple(source.source_id for source in imported.added_sources)
    draft = logical_groups_draft(
        projects.open(root), ids, action="create", label="Synthetic photos",
        source_ids=frozenset(ids),
    )
    projects.save(root, draft)
    projects.save(root, participation_draft(projects.open(root), ids, {ids[-1]}, included=False))
    before = projects.open(root)
    sources_before = media.list(root).sources
    original_hashes = {
        name: hashlib.sha256((old / name).read_bytes()).hexdigest() for name in names
    }
    # Both directories are owned and contained in the newly generated fixture.
    assert old.resolve().is_relative_to(fixture.resolve())
    assert relocated.absolute().is_relative_to(fixture.resolve()) and not relocated.exists()
    old.rename(relocated)
    for name in names:
        path = wrong / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((relocated / name).read_bytes())
    with (wrong / names[-1]).open("ab") as stream:
        stream.write(b"different candidate content")
    hold = WorkerHold()

    def factory():
        facade = build_gui_facade()
        builder = facade.factories["folder_relink"]
        facade.factories["folder_relink"] = lambda: HeldRelink(builder(), hold)
        return facade

    prefs = Preferences(QSettings(str(output / "review.ini"), QSettings.IniFormat))
    prefs.set("recent", [])
    vm = DesktopViewModel(preferences=prefs)
    vm.controller.factory = factory
    vm.controller.timer.stop()
    engine, window = None, None
    controls = {}
    report = {
        "synthetic_fixture": True, "synthetic_worker_hold": True, "captures": [], "checks": []
    }
    exceptions = []
    original_hook = sys.excepthook

    def record_exception(kind, value, trace):
        exceptions.append(str(value))
        original_hook(kind, value, trace)

    sys.excepthook = record_exception

    def settle(milliseconds: int = 120) -> None:
        loop = QEventLoop()
        QTimer.singleShot(milliseconds, loop.quit)
        loop.exec()

    def until(predicate) -> None:
        deadline = time.monotonic() + 30
        while not predicate() and time.monotonic() < deadline:
            settle(20)
        assert predicate(), f"Timed out: {vm.state.get('error')}"

    def idle() -> None:
        until(lambda: not vm.controller.executor.busy and not vm.controller.mutating
              and not vm.media.preview_executor.busy and not vm.media.gallery.executor.busy
              and not vm.sources.thumbnails.executor.busy
              and not vm.videoUsage.filmstrip.executor.busy)

    def item(name: str) -> QObject:
        cached = controls.get(name)
        if cached is not None and isValid(cached):
            return cached
        result = visual_item(window.contentItem(), name) or window.findChild(QObject, name)
        if result is None:
            page = visual_item(window.contentItem(), "sourcesPage")
            if page is not None:
                controls["sourcesPage"] = page
            result = page.findChild(QObject, name) if page is not None else None
        assert result is not None and isValid(result), name
        controls[name] = result
        return result

    def click(name: str) -> None:
        settle(80)
        control = item(name)
        assert isinstance(control, QQuickItem), name
        assert control.isVisible() and control.isEnabled(), name
        point = control.mapToScene(QPointF(control.width() / 2, control.height() / 2))
        QTest.mouseClick(window, Qt.LeftButton, pos=point.toPoint())
        settle()

    def capture(name: str) -> None:
        settle(200)
        assert window.isExposed()
        raster = window.grabWindow()
        assert not raster.isNull() and raster.save(str(output / f"{name}.png"))
        report["captures"].append({
            "name": name, "logical": [window.width(), window.height()],
            "raster": [raster.width(), raster.height()], "dpr": window.devicePixelRatio(),
            "native_title_bar": not bool(window.flags() & Qt.FramelessWindowHint),
            "exposed": window.isExposed(), "state": vm.folderRelink.state,
        })

    def open_relink() -> None:
        click("catalogOptions")
        click("locateSourceFolder")
        until(lambda: item("folderRelinkDialog").property("visible"))
        vm.folderRelink.setOldFolder(str(old))

    def preview(folder: Path) -> None:
        vm.folderRelink.setNewFolder(str(folder))
        click("previewFolderRelink")
        idle()
        assert not vm.folderRelink.state["busy"]

    try:
        vm.openProject(str(root))
        idle()
        vm.navigate(1)
        vm.setSourceFilter("All")
        vm.verifySources()
        idle()
        assert all(row.values["availabilityState"] == "missing" for row in vm.sources.all_rows)
        engine = create_engine(vm)
        window = engine.rootObjects()[0]
        until(window.isExposed)
        for theme in ("Dark", "Light"):
            vm.setTheme(theme)
            for width, height in ((1440, 900), (1024, 640)):
                window.resize(width, height)
                settle()
                prefix = f"{theme}-{width}"
                open_relink()
                capture(prefix + "-locate")
                preview(wrong)
                assert vm.folderRelink.state["matched"] == 2
                assert vm.folderRelink.state["total"] == 3
                assert not vm.folderRelink.state["canApply"]
                capture(prefix + "-mismatch")
                preview(relocated)
                assert vm.folderRelink.state["canApply"]
                capture(prefix + "-matched")
                click("closeFolderRelink")
                assert projects.open(root) == before
        vm.setTheme("Dark")
        window.resize(1440, 900)
        open_relink()
        vm.folderRelink.setNewFolder(str(relocated))
        hold.operation = "preview"
        click("previewFolderRelink")
        until(hold.entered.is_set)
        assert vm.folderRelink.state["busy"]
        capture("Dark-loading-controlled-worker")
        click("cancelFolderRelink")
        idle()
        assert vm.folderRelink.state["status"] == "cancelled"
        assert projects.open(root) == before
        capture("Dark-cancelled")
        hold.operation = ""
        hold.release.set()
        click("previewFolderRelink")
        idle()
        assert vm.folderRelink.state["canApply"]
        click("applyFolderRelink")
        idle()
        assert vm.folderRelink.state["status"] == "succeeded"
        saved = projects.open(root)
        sources_after = media.list(root).sources
        assert saved.revision == before.revision + 1
        assert saved.source_participation == before.source_participation
        assert saved.logical_source_groups == before.logical_source_groups
        assert saved.video_usage == before.video_usage and saved.settings == before.settings
        ignored = {
            "external_locator", "display_filename", "last_full_hash_at", "full_hash_evidence"
        }
        assert [s.model_dump(exclude=ignored) for s in sources_after] == [
            s.model_dump(exclude=ignored) for s in sources_before
        ]
        assert all(
            Path(source.external_locator).is_relative_to(relocated) for source in sources_after
        )
        assert all(row.values["availabilityState"] == "available" for row in vm.sources.all_rows)
        for theme in ("Dark", "Light"):
            vm.setTheme(theme)
            capture(theme + "-success")
        click("closeFolderRelink")
        vm.media.showSource(str(ids[0]))
        until(lambda: vm.media.state["previewStatus"] == "Ready")
        capture("Light-restored-photo")
        other = fixture / "Other project"
        projects.create(other, "Other empty project")
        vm.openProject(str(other))
        idle()
        assert not vm.folderRelink.state["canApply"] and vm.sources.count == 0
        vm.openProject(str(root))
        idle()
        vm.setSourceFilter("All")
        vm.media.showSource(str(ids[0]))
        until(lambda: vm.media.state["previewStatus"] == "Ready")
        capture("Light-persisted-reopen")
        assert {name: hashlib.sha256((relocated / name).read_bytes()).hexdigest()
                for name in names} == original_hashes
        assert not old.exists()
        assert projects.open(root).inventory_reference == saved.inventory_reference
        report["checks"] = [
            "real whole-folder full hashes; all three occurrences including excluded source",
            "mismatch blocks Apply; preview/Close/Cancel leave committed document unchanged",
            "controlled pending worker is cancellable and retryable",
            "one atomic saved revision; source UUID/revision/probe/intent preserved",
            "new locators decode; project switch revokes preview; persisted reopen decodes",
            "generated originals byte-identical; no processing or runtime provisioning",
        ]
        assert not engine.load_errors and not exceptions
    finally:
        hold.release.set()
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
        settle(180)
        report["exceptions"] = exceptions
        sys.excepthook = original_hook
        (output / "manifest.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    assert not exceptions and not report.get("qml_warnings")
    report["passed"] = True
    (output / "manifest.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"passed": report.get("passed", False), "captures": len(report["captures"])}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
