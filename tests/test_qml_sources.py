"""M12b1 source UX over real inventory persistence and bounded async previews."""

import json
import os
from threading import Event
from uuid import uuid4

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6", reason="Install the optional GUI extra")

from PySide6.QtCore import QMetaObject, QObject, QPointF, Qt, QTimer, QUrl  # noqa: E402
from PySide6.QtGui import QImage  # noqa: E402
from PySide6.QtQml import QQmlExpression  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from test_media import FakeProbe, FakeSourceFiles, media_service  # noqa: E402
from test_qml import app as app  # noqa: E402
from test_qml import desktop as desktop  # noqa: E402
from test_qml import until, visual_item  # noqa: E402
from test_qml_interaction import click, dispose  # noqa: E402
from test_qml_workflows import open_project  # noqa: E402

from splatforge.application.desktop import IndexRow  # noqa: E402
from splatforge.bootstrap import build_gui_facade  # noqa: E402
from splatforge_gui.presentation import source_availability, source_description  # noqa: E402
from splatforge_gui.qml_app import create_engine  # noqa: E402


def photo(path, color=Qt.GlobalColor.red):
    image = QImage(16, 12, QImage.Format.Format_RGB32)
    image.fill(color)
    assert image.save(str(path))
    return path


def inject_media(desktop, root, probe=None):
    """Use the real service/repository, substituting only file evidence and probing."""
    files, probe = FakeSourceFiles(), probe or FakeProbe()

    def factory():
        facade = build_gui_facade()
        facade.factories["media"] = lambda: media_service(root, files=files, probe=probe)[0]
        return facade

    desktop.controller.factory = factory
    return files, probe


def accept_files(engine, picker, paths):
    # Exercise the actual FileDialog accepted handler, without depending on OS dialogs.
    urls = [QUrl.fromLocalFile(str(p)).toString() for p in paths]
    expression = QQmlExpression(engine.rootContext(), picker, "currentFiles = " + json.dumps(urls))
    expression.evaluate()
    assert not expression.hasError(), expression.error().toString()
    # Simulate OS-delivered selection/acceptance; accept() would reread an empty
    # platform helper selection in offscreen tests.
    assert QMetaObject.invokeMethod(picker, "accepted")
    picker.setProperty("visible", False)


@pytest.mark.parametrize("kind,count", [("photos", 1), ("photos", 3), ("videos", 1), ("videos", 2)])
def test_explicit_pickers_import_and_reopen_persisted_types(desktop, tmp_path, kind, count):
    root = open_project(desktop, tmp_path)
    files, _ = inject_media(desktop, root)
    paths = [tmp_path / f"capture {i}.{'png' if kind == 'photos' else 'MP4'}" for i in range(count)]
    for p in paths:
        photo(p) if kind == "photos" else p.write_bytes(b"tiny synthetic video probe fixture")
    originals = [p.read_bytes() for p in paths]
    engine = create_engine(desktop)
    window = engine.rootObjects()[0]
    try:
        click(window, "addPhotos" if kind == "photos" else "addVideo")
        page = visual_item(window.contentItem(), "sourcesPage")
        picker = page.findChild(QObject, kind + "Picker")
        assert picker.property("visible")
        assert QQmlExpression(engine.rootContext(), picker, "Number(fileMode)").evaluate()[0] == 1
        accept_files(engine, picker, paths)
        until(lambda: desktop.sources.count == count and not desktop.controller.executor.busy)
        assert files.hash_reads == count
        identities = [r.identity for r in desktop._source.rows]
        expected = "photo" if kind == "photos" else "video"
        assert all(r.values["type"] == expected for r in desktop._source.rows)
        assert all(r.values["availability"] == "Not checked recently" for r in desktop._source.rows)
        assert desktop.state["sourcesSummary"][kind] == count
        desktop.openProject(str(root))
        until(lambda: not desktop.controller.executor.busy)
        assert [r.identity for r in desktop._source.rows] == identities
        assert all(r.values["type"] == expected for r in desktop._source.rows)
        assert [p.read_bytes() for p in paths] == originals
        assert not desktop.controller.overview.index.artifacts
        assert not desktop.controller.overview.index.runs
        assert not engine.load_errors
    finally:
        until(lambda: not desktop.controller.executor.busy)
        dispose(engine)


def test_import_failure_keeps_committed_rows_responsive_and_retryable(desktop, tmp_path):
    root = open_project(desktop, tmp_path)
    _, probe = inject_media(desktop, root)
    old = photo(tmp_path / "old.png")
    desktop.addFiles([str(old)])
    until(lambda: desktop.sources.count == 1 and not desktop.controller.executor.busy)
    before = desktop.controller.overview.document
    identity = desktop._source.rows[0].identity
    entered, release = Event(), Event()
    original_probe = probe.probe

    def fail(path, media_type, *, cancellation=None):
        if path.name == "new.png":
            return original_probe(path, media_type, cancellation=cancellation)
        entered.set()
        assert release.wait(10)
        raise ValueError("The selected source could not be read")

    probe.probe = fail
    new = photo(tmp_path / "new.png")
    second = photo(tmp_path / "second.png")
    ticks = []
    timer = QTimer()
    timer.setInterval(5)
    timer.timeout.connect(lambda: ticks.append(1))
    timer.start()
    try:
        desktop.addFiles([str(new), str(second)])
        until(entered.is_set)
        QTest.qWait(50)
        assert ticks and desktop.state["busy"]
        assert desktop.sources.count == 1 and desktop._source.rows[0].identity == identity
        assert desktop.state["progress"]["title"] == "Adding source files…"
        release.set()
        until(lambda: not desktop.controller.executor.busy)
        assert desktop.sources.count == 1 and desktop.controller.overview.document == before
        assert "could not be read" in desktop.state["error"]["message"]
        assert "Traceback" in desktop.state["error"]["details"]
        probe.probe = original_probe
        desktop.addFiles([str(new), str(second)])
        until(lambda: not desktop.controller.executor.busy)
        assert desktop.sources.count == 3, desktop.state["error"]
    finally:
        release.set()
        timer.stop()


def test_source_check_uses_recorded_evidence_and_never_hashes_on_refresh(desktop, tmp_path):
    root = open_project(desktop, tmp_path)
    files, _ = inject_media(desktop, root)
    paths = [photo(tmp_path / f"photo {i}.png") for i in range(2)]
    desktop.addFiles([str(p) for p in paths])
    until(lambda: desktop.sources.count == 2 and not desktop.controller.executor.busy)
    hashes = files.hash_reads
    assert "not been checked recently" in desktop.state["sourcesSummary"]["checkMessage"]
    engine = create_engine(desktop)
    window = engine.rootObjects()[0]
    try:
        button = visual_item(window.contentItem(), "checkSourceFiles")
        assert button.isEnabled() and button.opacity() == 1
        assert button.property("kind") == "secondary"
        click(window, "checkSourceFiles")
        until(lambda: not desktop.controller.executor.busy)
        assert "All source files were available" in desktop.state["sourcesSummary"]["checkMessage"]
        assert all(
            r.values["availability"] == "Available at last check" for r in desktop._source.rows
        )
        assert "no fresh content hash" in desktop._source.rows[0].values["verificationLabel"]
        paths[1].unlink()
        desktop.refresh()
        until(lambda: not desktop.controller.executor.busy)
        # Refresh/reopen does not pretend to have checked the current source files.
        assert desktop._source.rows[1].values["availability"] == "Available at last check"
        click(window, "checkSourceFiles")
        until(lambda: not desktop.controller.executor.busy)
        assert desktop._source.rows[1].values["availability"] == "Missing at last check"
        assert "1 source file was missing" in desktop.state["sourcesSummary"]["checkMessage"]
        assert files.hash_reads == hashes
        assert not engine.load_errors
    finally:
        dispose(engine)


@pytest.mark.parametrize("value,expected", [
    ("Full hash at ingest; current verification not recorded", "Not checked recently"),
    ("unchanged · metadata_unchanged · 2026-10-01", "Available at last check"),
    ("unchanged · content_verified · 2026-10-01", "Available at last check"),
    ("changed · content_verified · 2026-10-01", "File changed"),
    ("missing · unavailable · 2026-10-01", "Missing at last check"),
    ("strict_unavailable · unavailable · 2026-10-01", "Could not check"),
])
def test_standard_source_status_has_no_primary_hash_terminology(value, expected):
    assert source_availability(value) == expected


@pytest.mark.parametrize("value,expected", [
    ("102.5", "Video · 3840 × 2160 · 01:42"),
    (None, "Video · 3840 × 2160"),
    ("N/A", "Video · 3840 × 2160"),
    ("nan", "Video · 3840 × 2160"),
])
def test_video_metadata_never_invents_duration(value, expected):
    values = {"type": "video", "dimensions": "3840 × 2160", "duration": value}
    assert source_description(values) == expected


def seed_preview_rows(desktop, tmp_path):
    rows = tuple(IndexRow(identity=uuid4(), values={
        "filename": name, "type": "photo", "locator": str(photo(tmp_path / name, color)),
        "description": "Photo · 16 × 12", "availability": "Not checked recently",
    }) for name, color in [("z.png", Qt.GlobalColor.red), ("a.png", Qt.GlobalColor.green),
                          ("m.png", Qt.GlobalColor.blue)])
    video = IndexRow(identity=uuid4(), values={
        "filename": "clip.mp4", "type": "video", "description": "Video",
        "availability": "Not checked recently",
    })
    desktop._source.replace((rows[2], video, rows[0], rows[1]))
    return rows[2], rows[0], rows[1]


def test_preview_x_escape_arrows_boundaries_filename_and_selected_row(desktop, tmp_path):
    open_project(desktop, tmp_path)
    rows = seed_preview_rows(desktop, tmp_path)
    engine = create_engine(desktop)
    window = engine.rootObjects()[0]
    try:
        desktop.media.previewSource(str(rows[0].identity))
        dialog = window.findChild(QObject, "imageDialog")
        until(lambda: desktop.media.state["previewStatus"] == "Ready")
        assert dialog.property("visible") and dialog.property("title") == "m.png"
        previous = visual_item(window.contentItem(), "previousImage")
        following = visual_item(window.contentItem(), "nextImage")
        assert not previous.isEnabled() and following.isEnabled()
        assert visual_item(window.contentItem(), "previewPosition").property("text") == "1 of 3"
        url = desktop.media.state["largeImage"]
        click(window, "nextImage")
        until(lambda: desktop.media.state["previewStatus"] == "Ready")
        assert dialog.property("title") == "z.png"
        assert desktop.media.state["largeImage"] != url
        assert desktop.sources.selectedId == str(rows[1].identity)
        QTest.keyClick(window, Qt.Key.Key_Right)
        until(lambda: desktop.media.state["previewStatus"] == "Ready")
        assert dialog.property("title") == "a.png" and not following.isEnabled()
        QTest.keyClick(window, Qt.Key.Key_Right)
        assert desktop.media.state["previewIndex"] == 3
        QTest.keyClick(window, Qt.Key.Key_Left)
        until(lambda: desktop.media.state["previewIndex"] == 2)
        until(lambda: desktop.media.state["previewStatus"] == "Ready")
        click(window, "closeImagePreview")
        assert not dialog.property("visible") and desktop.media.state["largeImage"] == ""
        desktop.media.previewSource(str(rows[0].identity))
        until(lambda: desktop.media.state["previewStatus"] == "Ready")
        QTest.keyClick(window, Qt.Key.Key_Escape)
        assert not dialog.property("visible")
        assert not engine.load_errors
    finally:
        until(lambda: not desktop.controller.executor.busy)
        dispose(engine)


def test_preview_failed_decode_is_inspectable_and_can_navigate(desktop, tmp_path):
    open_project(desktop, tmp_path)
    rows = seed_preview_rows(desktop, tmp_path)
    from pathlib import Path

    Path(rows[0].values["locator"]).write_bytes(b"invalid image")
    engine = create_engine(desktop)
    try:
        desktop.media.previewSource(str(rows[0].identity))
        until(lambda: desktop.media.state["previewStatus"] == "Preview unavailable")
        assert desktop.media.state["largeImage"] == ""
        assert "Traceback" in desktop.media.state["previewDetails"]
        assert desktop.sources.selectedId == str(rows[0].identity)
        assert engine.rootObjects()[0].findChild(QObject, "imageDialog").property("visible")
        desktop.media.stepPreview(1)
        until(lambda: desktop.media.state["previewStatus"] == "Ready")
        assert desktop.media.state["previewTitle"] == "z.png"
        assert not desktop.media.state["previewDetails"]
        assert not engine.load_errors
    finally:
        until(lambda: not desktop.controller.executor.busy)
        dispose(engine)


def test_preview_tracks_current_model_order_on_refresh(desktop, tmp_path):
    open_project(desktop, tmp_path)
    rows = seed_preview_rows(desktop, tmp_path)
    desktop.media.previewSource(str(rows[0].identity))
    until(lambda: desktop.media.state["previewStatus"] == "Ready")
    desktop._source.replace(tuple(reversed(desktop._source.rows)))
    assert desktop.media.state["previewIndex"] == 3
    assert desktop.media.state["canPrevious"] and not desktop.media.state["canNext"]
    desktop.media.stepPreview(-1)
    until(lambda: desktop.media.state["previewStatus"] == "Ready")
    assert desktop.media.state["previewTitle"] == "z.png"
    assert desktop.sources.selectedId == str(rows[1].identity)


def test_preview_click_outside_closes(desktop, tmp_path):
    open_project(desktop, tmp_path)
    rows = seed_preview_rows(desktop, tmp_path)
    engine = create_engine(desktop)
    window = engine.rootObjects()[0]
    try:
        desktop.media.previewSource(str(rows[0].identity))
        until(lambda: desktop.media.state["previewStatus"] == "Ready")
        QTest.mouseClick(window, Qt.MouseButton.LeftButton, pos=QPointF(5, 5).toPoint())
        assert not window.findChild(QObject, "imageDialog").property("visible")
        assert not desktop.media.state["largeImage"]
        assert not engine.load_errors
    finally:
        until(lambda: not desktop.controller.executor.busy)
        dispose(engine)


def test_thousands_of_sources_use_bounded_delegates_without_decoding(
    desktop, tmp_path, monkeypatch
):
    from splatforge_gui import thumbnails

    open_project(desktop, tmp_path)
    decoded = []
    monkeypatch.setattr(thumbnails, "decode_thumbnail", lambda *args: decoded.append(args))
    rows = tuple(IndexRow(identity=uuid4(), values={
        "filename": f"photo-{i}.png", "type": "photo", "locator": str(tmp_path / f"{i}.png"),
        "verification": "Full hash at ingest; current verification not recorded",
        "dimensions": "16 × 12",
    }) for i in range(1500))
    desktop._overview(desktop.controller.overview.model_copy(update={"sources": rows}))
    engine = create_engine(desktop)
    window = engine.rootObjects()[0]
    window.resize(1024, 640)
    try:
        listing = visual_item(window.contentItem(), "sourceList")
        assert listing.property("count") == 1500
        desktop.sources.select(str(rows[-1].identity))
        QTest.qWait(50)
        delegates = [c for c in listing.property("contentItem").childItems()
                     if c.objectName().startswith("source-")]
        assert 0 < len(delegates) < 30
        assert listing.property("currentIndex") == 1499
        assert not decoded and not desktop.media.provider.large.width()
        assert not engine.load_errors
    finally:
        until(lambda: not desktop.controller.executor.busy)
        dispose(engine)


def test_preview_ignores_late_responses_after_navigation_and_close(desktop, tmp_path, monkeypatch):
    from splatforge_gui import qml_media

    open_project(desktop, tmp_path)
    rows = seed_preview_rows(desktop, tmp_path)
    entered, release = Event(), Event()
    decode = qml_media.decode_thumbnail

    def delayed(path, side):
        if path.name == "m.png":
            entered.set()
            assert release.wait(10)
        return decode(path, side)

    monkeypatch.setattr(qml_media, "decode_thumbnail", delayed)
    try:
        desktop.media.previewSource(str(rows[0].identity))
        until(entered.is_set)
        assert desktop.media.state["largeImage"] == ""
        desktop.media.stepPreview(1)
        assert desktop.media.state["largeImage"] == ""
        until(lambda: desktop.media.state["previewStatus"] == "Ready")
        current = desktop.media.state["largeImage"]
        release.set()
        until(lambda: not desktop.controller.executor.busy)
        assert desktop.media.state["largeImage"] == current
        assert desktop.media.state["previewTitle"] == "z.png"
        entered.clear()
        release.clear()
        desktop.media.previewSource(str(rows[0].identity))
        until(entered.is_set)
        desktop.media.closePreview()
        release.set()
        until(lambda: not desktop.controller.executor.busy)
        assert desktop.media.state["largeImage"] == "" and desktop.media.state["previewIndex"] == 0
    finally:
        release.set()
        until(lambda: not desktop.controller.executor.busy)


@pytest.mark.parametrize("size", [(1024, 640), (1440, 900)])
def test_sources_actions_footer_and_no_empty_pagination(desktop, tmp_path, size):
    root = open_project(desktop, tmp_path)
    inject_media(desktop, root)
    engine = create_engine(desktop)
    window = engine.rootObjects()[0]
    window.resize(*size)
    try:
        for theme in ("Dark", "Light"):
            desktop.setTheme(theme)
            for populated in (False, True):
                if populated and not desktop.sources.count:
                    desktop.addFiles([str(photo(tmp_path / "source.png"))])
                    until(lambda: desktop.sources.count == 1)
                    until(lambda: not desktop.controller.executor.busy)
                QTest.qWait(30)
                for name in ("addPhotos", "addVideo", "checkSourceFiles", "sourcesContinue"):
                    item = visual_item(window.contentItem(), name)
                    assert item and item.isVisible()
                    point = item.mapToScene(QPointF(0, 0))
                    assert point.y() >= 0 and point.y() + item.height() <= window.height(), name
                assert not visual_item(window.contentItem(), "sourcesContinue").isEnabled()
                pagination = visual_item(window.contentItem(), "viewsPagination")
                assert pagination is None or not pagination.isVisible()
                if desktop.sources.count:
                    row = desktop._source.rows[0]
                    desktop.media.selectSource(str(row.identity))
                    click(window, "sourceDetails")
                    assert not visual_item(window.contentItem(), "viewsPagination").isVisible()
                    QTest.keyClick(window, Qt.Key.Key_Escape)
                    def visible_labels(item):
                        texts = [str(item.property("text") or "")] if item.isVisible() else []
                        return texts + [s for c in item.childItems() for s in visible_labels(c)]

                    assert "Full hash" not in " ".join(visible_labels(window.contentItem()))
        assert not engine.load_errors
    finally:
        dispose(engine)
