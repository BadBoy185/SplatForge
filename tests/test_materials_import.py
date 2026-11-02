"""Materials import controls and external Qt URL drags (not manual Explorer evidence)."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QMetaObject, QMimeData, QObject, QPointF, Qt, QUrl  # noqa: E402
from PySide6.QtGui import QDragEnterEvent, QDragLeaveEvent, QDropEvent, QGuiApplication  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from test_materials_workspace import idle, imported  # noqa: E402
from test_qml import app as app  # noqa: E402
from test_qml import desktop as desktop  # noqa: E402
from test_qml import visual_item  # noqa: E402
from test_qml_interaction import click, dispose  # noqa: E402
from test_qml_sources import accept_files, inject_media, photo  # noqa: E402
from test_qml_workflows import open_project  # noqa: E402

from splatforge.bootstrap import build_gui_facade  # noqa: E402
from splatforge_gui.qml_app import create_engine  # noqa: E402


def enter(window, paths=(), *, text=""):
    mime = QMimeData()
    if text:
        mime.setText(text)
    else:
        mime.setUrls([QUrl.fromLocalFile(str(p)) for p in paths])
    event = QDragEnterEvent(QPointF(650, 300), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
    QGuiApplication.sendEvent(window, event)
    QTest.qWait(30)
    return mime, event.isAccepted()


def drop(window, mime):
    event = QDropEvent(QPointF(650, 300), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
    QGuiApplication.sendEvent(window, event)
    QTest.qWait(30)
    return event.isAccepted()


@pytest.mark.parametrize("size", [(1440, 900), (1024, 640)])
@pytest.mark.parametrize("theme", ["Dark", "Light"])
def test_empty_inventory_offers_import_without_review_controls(desktop, tmp_path, size, theme):
    open_project(desktop, tmp_path)
    desktop.setTheme(theme)
    engine = create_engine(desktop)
    window = engine.rootObjects()[0]
    try:
        window.resize(*size)
        QTest.qWait(100)
        title = visual_item(window.contentItem(), "emptyMediaTitle")
        assert title.isVisible() and title.property("text") == "Add your media"
        for name in ("fitPhoto", "zoomIn", "materialNavigation", "sourceDetails"):
            item = visual_item(window.contentItem(), name)
            assert item is None or not item.isVisible(), name
        for prefix in ("", "empty-"):
            for name in ("addPhotos", "addVideo", "addFolder"):
                control = visual_item(window.contentItem(), prefix + name)
                assert control.isVisible() and control.isEnabled()
                pos = control.mapToScene(QPointF(0, 0))
                assert 0 <= pos.x() <= window.width() - control.width()
                assert 0 <= pos.y() <= window.height() - control.height()
        last = visual_item(window.contentItem(), "empty-addFolder")
        actions = visual_item(window.contentItem(), "emptyMediaActions")
        # Font metrics may legitimately wrap Flow; its final row must fit inside it.
        bottom = last.mapToItem(actions, QPointF(0, last.height())).y()
        assert bottom <= actions.height() + 1
        if size[0] == 1440:
            assert visual_item(window.contentItem(), "emptySourceProperties").isVisible()
        assert not engine.load_errors
    finally:
        idle(desktop)
        dispose(engine)


@pytest.mark.parametrize("prefix", ["", "empty-"])
@pytest.mark.parametrize("kind", ["photos", "videos", "folder"])
def test_all_import_buttons_use_existing_pickers_and_persist(desktop, tmp_path, prefix, kind):
    root = open_project(desktop, tmp_path)
    inject_media(desktop, root)
    folder = tmp_path / "Media ž #1"
    folder.mkdir()
    source = folder / ("clip ą.MP4" if kind == "videos" else "photo ą.png")
    source.write_bytes(b"tiny probe fixture") if kind == "videos" else photo(source)
    original = source.read_bytes()
    engine = create_engine(desktop)
    window = engine.rootObjects()[0]
    try:
        name = {"photos": "addPhotos", "videos": "addVideo", "folder": "addFolder"}[kind]
        click(window, prefix + name)
        page = visual_item(window.contentItem(), "sourcesPage")
        picker = page.findChild(QObject, kind + "Picker")
        assert picker.property("visible")
        if kind == "folder":
            picker.setProperty("selectedFolder", QUrl.fromLocalFile(str(folder)))
            assert QMetaObject.invokeMethod(picker, "accepted")
            picker.setProperty("visible", False)
            idle(desktop)
            click(window, "cancelFolderImport")
            assert not build_gui_facade().overview(root).sources
            desktop.addFolder(str(folder))
            idle(desktop)
            click(window, "confirmFolderImport")
        else:
            accept_files(engine, picker, [source])
        idle(desktop)
        assert desktop.sources.count == 1
        assert source.read_bytes() == original
        # Catalog buttons remain visible after the empty invitation disappears.
        assert visual_item(window.contentItem(), "addPhotos").isVisible()
        assert not visual_item(window.contentItem(), "emptyMediaState").isVisible()
        desktop.controller.open(root)
        idle(desktop)
        assert desktop.sources.count == 1
        assert not engine.load_errors
    finally:
        idle(desktop)
        dispose(engine)


def test_external_mixed_drop_confirmation_cancel_duplicates_and_unicode(desktop, tmp_path):
    root = open_project(desktop, tmp_path)
    inject_media(desktop, root)
    folder = tmp_path / "Capture ž.2026"
    (folder / "Detail ą").mkdir(parents=True)
    image = photo(folder / "Detail ą" / "photo #1.png")
    video = tmp_path / "Clip ž.MOV"
    video.write_bytes(b"tiny probe fixture")
    (folder / "notes.txt").write_text("ignored")
    before = {p: p.read_bytes() for p in (image, video)}
    engine = create_engine(desktop)
    window = engine.rootObjects()[0]
    try:
        QTest.qWait(80)
        mime, accepted = enter(window, [folder, image, video, folder])
        assert accepted
        assert visual_item(window.contentItem(), "materialsDropFeedback").isVisible()
        assert drop(window, mime)
        idle(desktop)
        assert not visual_item(window.contentItem(), "materialsDropFeedback").isVisible()
        assert desktop.state["folderCount"] == 2 and desktop.state["folderIgnored"] == 1
        click(window, "cancelFolderImport")
        assert desktop.sources.count == 0
        assert not build_gui_facade().overview(root).sources
        for count in (2, 4):
            mime, accepted = enter(window, [folder, video])
            assert accepted and drop(window, mime)
            idle(desktop)
            assert desktop.state["scan"]["existing"] == (0 if count == 2 else 2)
            click(window, "confirmFolderImport")
            idle(desktop)
            assert desktop.sources.count == count
        assert {p: p.read_bytes() for p in before} == before
        assert not engine.load_errors
    finally:
        idle(desktop)
        dispose(engine)


def test_folder_drop_uses_same_group_root_and_drag_leave_clears_feedback(desktop, tmp_path):
    root = open_project(desktop, tmp_path)
    inject_media(desktop, root)
    folder = tmp_path / "Trip.2026"
    (folder / "Detail ž").mkdir(parents=True)
    photo(folder / "Detail ž" / "one.png")
    engine = create_engine(desktop)
    window = engine.rootObjects()[0]
    try:
        mime, accepted = enter(window, [folder])
        assert accepted
        QGuiApplication.sendEvent(window, QDragLeaveEvent())
        QTest.qWait(30)
        assert not visual_item(window.contentItem(), "materialsDropFeedback").isVisible()
        assert desktop._folder is None
        mime, accepted = enter(window, [folder])
        assert accepted and drop(window, mime)
        idle(desktop)
        assert desktop.state["scan"]["groups"] == [{"label": "Detail ž", "count": 1}]
        click(window, "confirmFolderImport")
        idle(desktop)
        assert desktop.sources.rows[0].values["logicalGroupLabel"] == "Detail ž"
        assert not engine.load_errors
    finally:
        idle(desktop)
        dispose(engine)


@pytest.mark.parametrize("kind,count", [("photo", 1), ("photo", 2), ("video", 1), ("video", 2)])
def test_external_file_drop_accepts_single_and_multiple_media(desktop, tmp_path, kind, count):
    root = open_project(desktop, tmp_path)
    inject_media(desktop, root)
    paths = [tmp_path / f"Source ž {i}.{'PNG' if kind == 'photo' else 'MP4'}"
             for i in range(count)]
    for path in paths:
        photo(path) if kind == "photo" else path.write_bytes(b"tiny video probe fixture")
    engine = create_engine(desktop)
    window = engine.rootObjects()[0]
    try:
        mime, accepted = enter(window, paths)
        assert accepted and drop(window, mime)
        idle(desktop)
        assert desktop.sources.count == 0  # OS drop is never an implicit confirmation.
        assert desktop.state["folderCount"] == count
        click(window, "confirmFolderImport")
        idle(desktop)
        assert desktop.sources.count == count
        assert all(row.values["type"] == kind for row in desktop.sources.rows)
        assert not engine.load_errors
    finally:
        idle(desktop)
        dispose(engine)


def test_unsupported_text_remote_and_relative_drops_are_rejected(desktop, tmp_path):
    open_project(desktop, tmp_path)
    unsupported = tmp_path / "mesh.ply"
    unsupported.write_text("not media")
    engine = create_engine(desktop)
    window = engine.rootObjects()[0]
    try:
        for paths, text in (([unsupported], ""), ([], "hello")):
            mime, accepted = enter(window, paths, text=text)
            assert not accepted
            assert not visual_item(window.contentItem(), "materialsDropFeedback").isVisible()
        for urls in (["https://example.com/photo.jpg"], ["relative.jpg"], ["file:relative.jpg"]):
            assert not desktop.canDropMedia(urls)
            desktop.dropUrls(urls)
        assert not desktop.controller.mutating and desktop.sources.count == 0
        assert desktop._folder is None
        assert not engine.load_errors
    finally:
        idle(desktop)
        dispose(engine)


def test_drop_enter_over_loaded_photo_preserves_review_and_selection(desktop, tmp_path):
    _, ids = imported(desktop, tmp_path)
    desktop.media.showSource(ids[0])
    desktop.sources.selectAllVisible()
    idle(desktop)
    extra = photo(tmp_path / "Extra ž.png")
    engine = create_engine(desktop)
    window = engine.rootObjects()[0]
    try:
        url = desktop.media.state["largeImage"]
        mime, accepted = enter(window, [extra])
        assert accepted
        assert desktop.media.state["largeImage"] == url
        assert set(desktop.sources.selectedIds) == set(ids)
        QGuiApplication.sendEvent(window, QDragLeaveEvent())
        assert not visual_item(window.contentItem(), "materialsDropFeedback").isVisible()
        mime, accepted = enter(window, [extra])
        assert accepted and drop(window, mime)
        idle(desktop)
        click(window, "confirmFolderImport")
        idle(desktop)
        assert desktop.sources.count == 4
        assert desktop.media.state["previewSource"]["identity"] == ids[0]
        assert set(desktop.sources.selectedIds) == set(ids)
        assert not engine.load_errors
    finally:
        idle(desktop)
        dispose(engine)


def test_filter_empty_no_selection_and_decode_error_are_distinct(desktop, tmp_path):
    _, ids = imported(desktop, tmp_path)
    desktop.media.closePreview()
    engine = create_engine(desktop)
    window = engine.rootObjects()[0]
    try:
        QTest.qWait(80)
        status = visual_item(window.contentItem(), "previewStatus")
        assert status.isVisible() and status.property("text") == "Select a photo or video"
        assert not visual_item(window.contentItem(), "emptyMediaState").isVisible()
        click(window, "filterExcluded")
        assert status.property("text") == "No materials match this filter"
        click(window, "viewerResetFilters")
        assert desktop.sources.count == 3
        source = desktop.local_path(desktop.sources.rows[0].values["locator"])
        source.write_bytes(b"owned corrupt test fixture")
        desktop.media.showSource(ids[0])
        idle(desktop)
        assert status.property("text") == "Preview unavailable"
        assert visual_item(window.contentItem(), "retryMaterialPreview").isVisible()
        click(window, "materialNext")
        idle(desktop)
        assert desktop.media.state["previewStatus"] == "Ready"
        assert not engine.load_errors
    finally:
        idle(desktop)
        dispose(engine)
