"""M12b2 preview, contextual drop, browser bounds and machine preferences."""

import os
from threading import Event
from uuid import uuid4

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6", reason="Install the optional GUI extra")

from PySide6.QtCore import QMetaObject, QObject, QPointF, Qt, QUrl  # noqa: E402
from PySide6.QtGui import QImage  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from test_qml import app as app  # noqa: E402
from test_qml import desktop as desktop  # noqa: E402
from test_qml import until, visual_item  # noqa: E402
from test_qml_interaction import click, dispose  # noqa: E402
from test_qml_sources import inject_media, photo, seed_preview_rows  # noqa: E402
from test_qml_workflows import open_project  # noqa: E402

from splatforge.application.desktop import IndexRow  # noqa: E402
from splatforge.application.media_scan import MediaScanResult, ScanProgress  # noqa: E402
from splatforge.bootstrap import build_gui_facade, build_project_service  # noqa: E402
from splatforge_gui.qml_app import create_engine  # noqa: E402


def idle(desktop):
    until(lambda: not desktop.controller.executor.busy)


def test_folder_picker_preview_counts_cancel_then_confirm_persisted(desktop, tmp_path):
    root = open_project(desktop, tmp_path)
    inject_media(desktop, root)
    folder = tmp_path / "Mixed ž"
    (folder / "nested").mkdir(parents=True)
    paths = [photo(folder / "a.png"), photo(folder / "nested" / "b.png")]
    video = folder / "nested" / "clip.MP4"
    video.write_bytes(b"tiny video probe fixture")
    (folder / "notes.txt").write_text("ignored")
    original = [p.read_bytes() for p in [*paths, video]]
    engine = create_engine(desktop)
    window = engine.rootObjects()[0]
    try:
        click(window, "addFolder")
        page = visual_item(window.contentItem(), "sourcesPage")
        picker = page.findChild(QObject, "folderPicker")
        assert picker.property("visible")
        picker.setProperty("selectedFolder", QUrl.fromLocalFile(str(folder)))
        assert QMetaObject.invokeMethod(picker, "accepted")
        picker.setProperty("visible", False)
        idle(desktop)
        dialog = window.findChild(QObject, "importPreviewDialog")
        assert dialog.property("visible")
        assert desktop.state["scan"]["photos"] == 2
        assert desktop.state["scan"]["videos"] == 1
        assert desktop.state["folderIgnored"] == 1
        assert desktop.state["scan"]["directories"] == 2
        assert desktop.sources.count == 0
        click(window, "reviewScanFiles")
        assert visual_item(window.contentItem(), "scanFiles").property("count") == 4
        click(window, "cancelFolderImport")
        assert desktop.sources.count == 0 and desktop._folder is None
        assert build_gui_facade().overview(root).sources == ()
        desktop.addFolder(str(folder))
        idle(desktop)
        click(window, "confirmFolderImport")
        idle(desktop)
        assert desktop.sources.count == 3
        assert [p.read_bytes() for p in [*paths, video]] == original
        desktop.openProject(str(root))
        idle(desktop)
        assert desktop.sources.count == 3
        assert not desktop.controller.overview.index.artifacts
        assert not desktop.controller.overview.index.runs
        # The backend permits repeated persisted occurrences. Preview says so.
        desktop.addFolder(str(folder))
        idle(desktop)
        assert desktop.state["scan"]["existing"] == 3
        click(window, "confirmFolderImport")
        idle(desktop)
        assert desktop.sources.count == len(build_gui_facade().overview(root).sources) == 6
        assert not engine.load_errors
    finally:
        idle(desktop)
        dispose(engine)


@pytest.mark.parametrize("contents", ["empty", "unsupported", "missing"])
def test_zero_supported_disables_import(desktop, tmp_path, contents):
    open_project(desktop, tmp_path)
    folder = tmp_path / "input"
    if contents != "missing":
        folder.mkdir()
    if contents == "unsupported":
        (folder / "points.ply").touch()
    engine = create_engine(desktop)
    window = engine.rootObjects()[0]
    try:
        desktop.addFolder(str(folder))
        idle(desktop)
        assert desktop.state["folderCount"] == 0
        assert not visual_item(window.contentItem(), "confirmFolderImport").isEnabled()
        desktop.confirmFolder()
        assert desktop.sources.count == 0
        click(window, "cancelFolderImport")
        assert not engine.load_errors
    finally:
        dispose(engine)


def test_sources_mixed_drop_scans_and_home_keeps_project_open(desktop, tmp_path):
    root = open_project(desktop, tmp_path)
    inject_media(desktop, root)
    folder = tmp_path / "media"
    folder.mkdir()
    source = photo(folder / "nested.png")
    extra = photo(tmp_path / "extra.png")
    desktop.dropUrls([str(source), str(folder), str(extra), str(folder)])
    idle(desktop)
    assert desktop.controller.root == root
    assert desktop.state["folderCount"] == 2 and desktop.sources.count == 0
    desktop.confirmFolder()
    idle(desktop)
    assert desktop.sources.count == 2
    other = tmp_path / "Other project"
    build_project_service().create(other, "Other")
    desktop.navigate(0)
    desktop.dropUrls([QUrl.fromLocalFile(str(other)).toString()])
    idle(desktop)
    assert desktop.controller.root == other and desktop.sources.count == 0


@pytest.mark.parametrize("late_result", [False, True])
def test_scan_cancel_is_responsive_and_publishes_nothing(desktop, tmp_path, late_result):
    root = open_project(desktop, tmp_path)
    entered = Event()

    class Scanner:
        def scan(self, paths, *, cancellation, progress, **kwargs):
            entered.set()
            progress(ScanProgress(entries=64, directories=4))
            assert desktop.controller.ingest_cancel.wait(10)
            if late_result:
                return MediaScanResult()
            cancellation.checkpoint()
            raise AssertionError("cancel checkpoint must raise")

    def factory():
        facade = build_gui_facade()
        facade.factories["media_scanner"] = Scanner
        return facade

    desktop.controller.factory = factory
    engine = create_engine(desktop)
    window = engine.rootObjects()[0]
    try:
        desktop.addFolder(str(tmp_path))
        until(entered.is_set)
        until(lambda: desktop.state["scan"]["progress"]["entries"] == 64)
        assert desktop.state["busy"] and desktop.controller.can_cancel
        assert window.findChild(QObject, "folderScanProgress").property("visible")
        click(window, "cancelFolderScan")
        idle(desktop)
        assert desktop._folder is None and desktop.sources.count == 0
        assert not window.findChild(QObject, "importPreviewDialog").property("visible")
        assert not build_gui_facade().overview(root).sources
        assert "Cancelled" in desktop.state["notice"]
        assert not engine.load_errors
    finally:
        desktop.controller.cancel()
        idle(desktop)
        dispose(engine)


def test_cancel_ingest_after_preview_keeps_inventory_atomic(desktop, tmp_path):
    root = open_project(desktop, tmp_path)
    _, probe = inject_media(desktop, root)
    folder = tmp_path / "media"
    folder.mkdir()
    photo(folder / "a.png")
    photo(folder / "b.png")
    entered = Event()
    original = probe.probe

    def cancelled(path, media_type, *, cancellation=None):
        entered.set()
        assert desktop.controller.ingest_cancel.wait(10)
        cancellation.checkpoint()
        return original(path, media_type, cancellation=cancellation)

    probe.probe = cancelled
    desktop.addFolder(str(folder))
    idle(desktop)
    desktop.confirmFolder()
    until(entered.is_set)
    desktop.cancel()
    idle(desktop)
    assert desktop.sources.count == 0 and not build_gui_facade().overview(root).sources
    assert "Cancelled" in desktop.state["notice"]


def test_grid_1500_sources_is_lazy_bounded_and_shares_selection(desktop, tmp_path, monkeypatch):
    from splatforge_gui import thumbnails

    open_project(desktop, tmp_path)
    decoded = []

    def decode(path, side=192):
        decoded.append((path, side))
        if path.name == "0.png":
            raise ValueError("missing thumbnail")
        image = QImage(32, 24, QImage.Format.Format_RGB32)
        image.fill(Qt.GlobalColor.green)
        return image

    monkeypatch.setattr(thumbnails, "decode_thumbnail", decode)
    rows = tuple(IndexRow(identity=uuid4(), values={
        "filename": f"{i}.png", "type": "photo", "locator": str(tmp_path / f"{i}.png"),
        "verification": "Full hash at ingest; current verification not recorded",
        "dimensions": "6000 × 4000",
    }) for i in range(1500))
    desktop._overview(desktop.controller.overview.model_copy(update={"sources": rows}))
    engine = create_engine(desktop)
    window = engine.rootObjects()[0]
    window.resize(1024, 640)
    try:
        QTest.qWait(50)
        assert not decoded
        click(window, "sourceGridMode")
        grid = visual_item(window.contentItem(), "sourceGrid")
        until(lambda: bool(decoded) and not desktop._source.thumbnails.executor.busy)
        assert grid.property("count") == 1500
        delegates = [c for c in grid.property("contentItem").childItems()
                     if c.objectName().startswith("tile-")]
        assert 0 < len(delegates) < 40
        assert len(decoded) < 40 and all(side == 192 for _, side in decoded)
        assert all(int(p.stem) < 40 for p, _ in decoded)
        first = visual_item(window.contentItem(), "tile-" + str(rows[0].identity))
        assert first.property("imageUrl") == ""
        assert visual_item(first, "thumbnailPlaceholder").isVisible()
        click(window, first.objectName())
        assert desktop.sources.selectedId == str(rows[0].identity)
        click(window, "sourceListMode")
        assert visual_item(window.contentItem(), "sourceList").property("currentIndex") == 0
        desktop.media.previewSource(str(rows[1].identity))
        until(lambda: desktop.media.state["previewStatus"] != "Loading preview…")
        assert desktop.sources.selectedId == str(rows[1].identity)
        assert desktop.media.state["previewIndex"] == 2
        QTest.keyClick(window, Qt.Key.Key_Escape)
        click(window, "sourceGridMode")
        assert visual_item(window.contentItem(), "sourceGrid").property("currentIndex") == 1
        for _ in range(3):
            click(window, "sourceListMode")
            click(window, "sourceGridMode")
            assert visual_item(window.contentItem(), "sourceGrid").property("currentIndex") == 1
        assert desktop.preferences.get("source_view_mode") == "Grid"
        assert not engine.load_errors
    finally:
        idle(desktop)
        until(lambda: not desktop._source.thumbnails.executor.busy)
        dispose(engine)


def test_last_project_parent_only_changes_after_success(desktop, tmp_path):
    first, second = tmp_path / "Projects ž", tmp_path / "Other Projects"
    first.mkdir()
    second.mkdir()
    desktop.createProject(str(first), "One")
    idle(desktop)
    assert desktop.lastProjectParent() == str(first)
    engine = create_engine(desktop)
    window = engine.rootObjects()[0]
    try:
        QTest.keyClick(window, Qt.Key.Key_N, Qt.KeyboardModifier.ControlModifier)
        location = visual_item(window.contentItem(), "projectLocation")
        assert location.property("text") == str(first)
        location.setProperty("text", str(second))
        click(window, "cancelCreateProject")
        assert desktop.lastProjectParent() == str(first)
        occupied = second / "Taken"
        occupied.mkdir()
        (occupied / "original.txt").write_text("preserve")
        desktop.createProject(str(second), "Taken")
        idle(desktop)
        assert desktop.lastProjectParent() == str(first)
        QTest.keyClick(window, Qt.Key.Key_Escape)
        desktop.createProject(str(second), "Two")
        idle(desktop)
        assert desktop.lastProjectParent() == str(second)
        QTest.keyClick(window, Qt.Key.Key_N, Qt.KeyboardModifier.ControlModifier)
        assert location.property("text") == str(second)
        click(window, "cancelCreateProject")
        # Missing preference is ignored; prefill never recreates it.
        absent = tmp_path / "Absent"
        desktop.preferences.set("last_project_parent", str(absent))
        assert desktop.lastProjectParent() == "" and not absent.exists()
        assert "last_project_parent" not in desktop.controller.overview.document.model_dump()
        assert not engine.load_errors
    finally:
        dispose(engine)


def test_grid_double_click_reuses_photo_popup_and_order(desktop, tmp_path):
    open_project(desktop, tmp_path)
    rows = seed_preview_rows(desktop, tmp_path)
    desktop.setSourceView("Grid")
    engine = create_engine(desktop)
    window = engine.rootObjects()[0]
    try:
        tile_name = "tile-" + str(rows[0].identity)
        until(lambda: visual_item(window.contentItem(), tile_name) is not None)
        tile = visual_item(window.contentItem(), "tile-" + str(rows[0].identity))
        point = tile.mapToScene(QPointF(tile.width() / 2, tile.height() / 2)).toPoint()
        QTest.mouseDClick(window, Qt.MouseButton.LeftButton, pos=point)
        until(lambda: desktop.media.state["previewStatus"] == "Ready")
        assert window.findChild(QObject, "imageDialog").property("visible")
        assert desktop.media.state["previewTitle"] == "m.png"
        assert desktop.sources.selectedId == str(rows[0].identity)
        click(window, "nextImage")
        until(lambda: desktop.media.state["previewStatus"] == "Ready")
        assert desktop.media.state["previewTitle"] == "z.png"
        assert desktop.sources.selectedId == str(rows[1].identity)
        assert not engine.load_errors
    finally:
        idle(desktop)
        until(lambda: not desktop._source.thumbnails.executor.busy)
        dispose(engine)


def test_project_switch_discards_old_scan_preview(desktop, tmp_path):
    open_project(desktop, tmp_path)
    folder = tmp_path / "media"
    folder.mkdir()
    photo(folder / "a.png")
    other = tmp_path / "Other"
    build_project_service().create(other, "Other")
    engine = create_engine(desktop)
    window = engine.rootObjects()[0]
    try:
        desktop.addFolder(str(folder))
        idle(desktop)
        assert desktop.state["folderCount"] == 1
        assert window.findChild(QObject, "importPreviewDialog").property("visible")
        desktop.openProject(str(other))
        idle(desktop)
        assert desktop._folder is None and desktop.state["folderCount"] == 0
        assert desktop.scanFiles.rowCount() == 0
        assert not window.findChild(QObject, "importPreviewDialog").property("visible")
        desktop.confirmFolder()
        assert desktop.sources.count == 0 and not engine.load_errors
    finally:
        dispose(engine)


@pytest.mark.parametrize("cancel_waiting", [False, True])
def test_ingest_drains_owned_readers_and_can_cancel_while_waiting(
    desktop, tmp_path, cancel_waiting
):
    root = open_project(desktop, tmp_path)
    files, _ = inject_media(desktop, root)
    source = photo(tmp_path / "source.png")
    reading, release = Event(), Event()

    def hold_reader(_):
        with (root / "project.json").open("rb"):
            reading.set()
            assert release.wait(10)

    desktop.controller.submit("held_metadata", hold_reader)
    until(reading.is_set)
    try:
        desktop.addFiles([str(source)])
        assert desktop.controller.mutating and desktop.controller.operation == "ingest"
        desktop.refresh()
        desktop.refresh_recents()
        desktop.controller.poll()
        QTest.qWait(30)
        assert files.hash_reads == 0 and len(desktop.controller.jobs) == 1
        if cancel_waiting:
            desktop.cancel()
        release.set()
        idle(desktop)
        assert not desktop.state["error"]
        assert desktop.sources.count == (0 if cancel_waiting else 1)
        assert files.hash_reads == (0 if cancel_waiting else 1)
    finally:
        release.set()
        idle(desktop)


def test_save_switch_callback_waits_for_finished_delivery(desktop, tmp_path):
    open_project(desktop, tmp_path)
    controller = desktop.controller
    calls = []
    desktop._after_save = lambda: calls.append(controller.mutating)
    controller.edit(controller.overview.document.model_copy(update={"label": "Saved"}))
    controller.mutating, controller.operation = True, "save"
    controller.jobs["delayed-save-finished"] = ("save", True, controller.generation)
    # Deliver the successful result, deliberately withholding the finished event.
    controller._result("delayed-save-finished", None)
    QTest.qWait(30)
    assert calls == [] and controller.mutating
    controller._finished("delayed-save-finished")
    until(lambda: bool(calls))
    assert calls == [False]
    idle(desktop)
