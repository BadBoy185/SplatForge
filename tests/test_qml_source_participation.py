"""Committed participation in the real Qt browser; no QML-only processing state."""

import os
from threading import Event
from uuid import uuid4

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6", reason="Install the optional GUI extra")

from PySide6.QtCore import QObject, QSettings, Qt  # noqa: E402
from PySide6.QtGui import QImage  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from test_qml import app as app  # noqa: E402
from test_qml import desktop as desktop  # noqa: E402
from test_qml import until, visual_item  # noqa: E402
from test_qml_interaction import click, dispose  # noqa: E402
from test_qml_sources import inject_media, photo  # noqa: E402
from test_qml_workflows import open_project  # noqa: E402

from splatforge.application.desktop import IndexRow  # noqa: E402
from splatforge.application.projects import StaleProjectRevisionError  # noqa: E402
from splatforge.bootstrap import build_project_service  # noqa: E402
from splatforge_gui.preferences import Preferences  # noqa: E402
from splatforge_gui.qml_app import create_engine  # noqa: E402
from splatforge_gui.qml_bridge import DesktopViewModel  # noqa: E402


def idle(vm):
    until(lambda: not vm.controller.executor.busy and not vm.controller.mutating)


def populated(vm, tmp_path):
    root = open_project(vm, tmp_path)
    files, _ = inject_media(vm, root)
    paths = [photo(tmp_path / "Photo ž.png"), tmp_path / "Video.MP4"]
    paths[1].write_bytes(b"tiny synthetic video")
    vm.addFiles([str(p) for p in paths])
    idle(vm)
    return root, files, paths, tuple(vm.sources.rows)


@pytest.mark.parametrize("view", ["List", "Grid"])
@pytest.mark.parametrize("kind", ["photo", "video"])
def test_exclude_restore_filters_details_preview_and_availability(desktop, tmp_path, view, kind):
    root, files, paths, rows = populated(desktop, tmp_path)
    desktop.setSourceView(view)
    engine = create_engine(desktop)
    window = engine.rootObjects()[0]
    row = next(r for r in rows if r.values["type"] == kind)
    identity = str(row.identity)
    try:
        desktop.media.selectSource(identity)
        click(window, "sourceParticipation")
        idle(desktop)
        assert desktop.sources.count == 1 and desktop.sources.selectedId == ""
        assert desktop.state["sourcesSummary"] == {
            "registered": 2, "included": 1, "excluded": 1, "photos": 1, "videos": 1,
            "checkMessage": "All source files were available when checked this session.",
        }
        assert "Original file was not deleted" in desktop.state["notice"]
        assert all(p.exists() for p in paths)
        assert build_project_service().open(root).source_participation.excluded_source_ids == (
            row.identity,
        )
        click(window, "filterExcluded")
        assert desktop.sources.count == 1
        desktop.media.selectSource(identity)
        assert desktop.sources.selected["isIncluded"] is False
        assert desktop.sources.selected["availabilityState"] == "available"
        click(window, "sourceDetails")
        assert "Excluded" in visual_item(window.contentItem(), "sourceParticipationLabel").property(
            "text"
        )
        click(window, "closeSourceDetails")
        if kind == "photo":
            desktop.media.previewSource(identity)
            until(lambda: desktop.media.state["previewStatus"] == "Ready")
            assert window.findChild(QObject, "imageDialog").property("visible")
            QTest.keyClick(window, Qt.Key.Key_Escape)
        click(window, "filterAll")
        assert desktop.sources.count == 2 and desktop.sources.selectedId == identity
        click(window, "sourceListMode" if view == "Grid" else "sourceGridMode")
        assert desktop.sources.selectedId == identity
        click(window, "sourceDetails")
        click(window, "detailsParticipation")
        idle(desktop)
        assert desktop.sources.selected["isIncluded"] is True
        click(window, "closeSourceDetails")
        click(window, "filterExcluded")
        assert desktop.sources.count == 0
        empty = visual_item(window.contentItem(), "participationEmptyState")
        assert empty.isVisible() and empty.property("text") == "No excluded sources."
        assert not visual_item(window.contentItem(), "sourcesEmptyState").isVisible()
        hashes = files.hash_reads
        click(window, "filterIncluded")
        assert desktop.sources.count == 2 and files.hash_reads == hashes
        assert not engine.load_errors
    finally:
        idle(desktop)
        until(lambda: not desktop.sources.thumbnails.executor.busy)
        dispose(engine)


def test_all_excluded_empty_state_restart_and_project_switch(desktop, tmp_path):
    root, _, paths, rows = populated(desktop, tmp_path)
    for row in rows:
        desktop.setSourceIncluded(str(row.identity), False)
        idle(desktop)
    engine = create_engine(desktop)
    window = engine.rootObjects()[0]
    restarted = None
    try:
        empty = visual_item(window.contentItem(), "participationEmptyState")
        assert empty.isVisible() and "All sources are excluded" in empty.property("text")
        click(window, "viewExcluded")
        assert desktop.sources.count == 2
        desktop.media.selectSource(str(rows[0].identity))
        # A fresh VM (simulated application restart) reads the portable document.
        preferences = Preferences(QSettings(str(tmp_path / "restart.ini"), QSettings.IniFormat))
        restarted = DesktopViewModel(preferences=preferences)
        restarted.controller.timer.stop()
        restarted.openProject(str(root))
        idle(restarted)
        assert restarted.state["sourceFilter"] == "Included" and restarted.sources.count == 0
        restarted.setSourceFilter("Excluded")
        assert len(restarted.sources.rows) == 2
        assert all(r.values["availabilityState"] == "neutral" for r in restarted.sources.rows)
        assert all(p.exists() for p in paths)
        other = tmp_path / "Other"
        build_project_service().create(other, "Other")
        desktop.openProject(str(other))
        idle(desktop)
        assert desktop.state["sourceFilter"] == "Included"
        assert desktop.sources.selectedId == "" and desktop.sources.count == 0
        assert visual_item(window.contentItem(), "sourcesEmptyState").isVisible()
        assert not engine.load_errors
    finally:
        if restarted:
            idle(restarted)
            restarted.deleteLater()
        dispose(engine)


@pytest.mark.parametrize("failure", ["write", "stale"])
def test_failed_save_keeps_committed_participation_and_drops_action_draft(
    desktop, tmp_path, failure,
):
    root, _, _, rows = populated(desktop, tmp_path)
    original_factory = desktop.controller.factory

    def factory():
        facade = original_factory()

        def fail(*args):
            if failure == "stale":
                service = build_project_service()
                latest = service.open(root)
                latest.label = "External change"
                service.save(root, latest)
                raise StaleProjectRevisionError("Project changed; reopen and retry")
            raise OSError("Disk write failed")

        facade.save = fail
        return facade

    desktop.controller.factory = factory
    desktop.setSourceIncluded(str(rows[0].identity), False)
    idle(desktop)
    assert desktop.sources.count == 2
    assert all(r.values["isIncluded"] for r in desktop.sources.rows)
    assert not desktop.controller.dirty
    assert not build_project_service().open(root).source_participation.excluded_source_ids
    assert desktop.state["error"]["message"]
    assert desktop.state["notice"] == ""
    if failure == "stale":
        assert desktop.controller.overview.document.label == "External change"


@pytest.mark.parametrize("choice", ["save", "discard", "cancel"])
def test_existing_dirty_save_discard_cancel_before_participation(desktop, tmp_path, choice):
    root, _, _, rows = populated(desktop, tmp_path)
    original_label = desktop.controller.overview.document.label
    desktop.controller.edit(
        desktop.controller.overview.document.model_copy(update={"label": "Draft"}),
    )
    dialogs = []
    desktop.dialogRequested.connect(dialogs.append)
    desktop.setSourceIncluded(str(rows[0].identity), False)
    assert dialogs[-1] == "unsaved"
    assert desktop.sources.count == 2
    desktop.resolveUnsaved(choice)
    idle(desktop)
    document = build_project_service().open(root)
    if choice == "cancel":
        assert desktop.controller.dirty and not document.source_participation.excluded_source_ids
    else:
        assert not desktop.controller.dirty
        assert document.label == ("Draft" if choice == "save" else original_label)
        assert document.source_participation.excluded_source_ids == (rows[0].identity,)
        assert desktop.sources.count == 1


def test_action_drains_readers_and_only_changes_ui_after_committed_save(desktop, tmp_path):
    root, _, _, rows = populated(desktop, tmp_path)
    entered, release = Event(), Event()

    def hold(_):
        with (root / "project.json").open("rb"):
            entered.set()
            assert release.wait(10)

    desktop.controller.submit("held_reader", hold)
    until(entered.is_set)
    try:
        desktop.setSourceIncluded(str(rows[0].identity), False)
        assert desktop.controller.operation == "save" and desktop.controller.mutating
        assert desktop.sources.count == 2 and desktop.sources.rows[0].values["isIncluded"]
        assert not build_project_service().open(root).source_participation.excluded_source_ids
        desktop.setSourceIncluded(str(rows[1].identity), False)
        assert desktop.state["error"]["category"] == "ValueError"
    finally:
        release.set()
        idle(desktop)
    assert desktop.sources.count == 1
    assert build_project_service().open(root).source_participation.excluded_source_ids == (
        rows[0].identity,
    )


def test_missing_is_independent_and_restore_never_verifies_originals(desktop, tmp_path):
    _, files, paths, rows = populated(desktop, tmp_path)
    paths[0].rename(tmp_path / "temporarily relocated.png")
    desktop.verifySources()
    idle(desktop)
    row = next(r for r in desktop.sources.rows if r.values["type"] == "photo")
    assert row.values["isIncluded"] and row.values["availabilityState"] == "missing"
    hashes = files.hash_reads
    desktop.setSourceIncluded(str(row.identity), False)
    idle(desktop)
    desktop.setSourceFilter("Excluded")
    assert desktop.sources.rows[0].values["availabilityState"] == "missing"
    desktop.setSourceIncluded(str(row.identity), True)
    idle(desktop)
    desktop.setSourceFilter("Included")
    row = next(r for r in desktop.sources.rows if r.values["type"] == "photo")
    assert row.values["isIncluded"] and row.values["availabilityState"] == "missing"
    assert files.hash_reads == hashes


def test_keyboard_selection_and_participation_filters(desktop, tmp_path):
    _, _, _, rows = populated(desktop, tmp_path)
    engine = create_engine(desktop)
    window = engine.rootObjects()[0]
    try:
        until(lambda: visual_item(
            window.contentItem(), "source-" + str(rows[0].identity),
        ) is not None)
        item = visual_item(window.contentItem(), "source-" + str(rows[0].identity))
        item.forceActiveFocus(Qt.FocusReason.TabFocusReason)
        assert item.property("visualFocus")
        QTest.keyClick(window, Qt.Key.Key_Space)
        assert desktop.sources.selectedId == str(rows[0].identity)
        action = visual_item(window.contentItem(), "sourceParticipation")
        action.forceActiveFocus(Qt.FocusReason.TabFocusReason)
        QTest.keyClick(window, Qt.Key.Key_Space)
        idle(desktop)
        excluded = visual_item(window.contentItem(), "filterExcluded")
        excluded.forceActiveFocus(Qt.FocusReason.TabFocusReason)
        assert excluded.property("visualFocus")
        QTest.keyClick(window, Qt.Key.Key_Space)
        assert desktop.state["sourceFilter"] == "Excluded" and desktop.sources.count == 1
        assert not engine.load_errors
    finally:
        dispose(engine)


def test_future_participation_version_is_inspectable_but_cannot_process(desktop, tmp_path):
    root, _, _, rows = populated(desktop, tmp_path)
    projects = build_project_service()
    document = projects.open(root)
    document.source_participation = document.source_participation.model_copy(
        update={"schema_version": 99},
    )
    projects.save(root, document)
    desktop.openProject(str(root))
    idle(desktop)
    engine = create_engine(desktop)
    window = engine.rootObjects()[0]
    try:
        assert desktop.sources.count == 2 and desktop.state["sourceFilter"] == "All"
        assert not desktop.state["participationSupported"]
        assert "unsupported version" in desktop.state["participationWarnings"][0]
        desktop.media.selectSource(str(rows[0].identity))
        assert not visual_item(window.contentItem(), "sourceParticipation").isEnabled()
        click(window, "sourceDetails")
        assert not visual_item(window.contentItem(), "detailsParticipation").isEnabled()
        assert not engine.load_errors
        click(window, "closeSourceDetails")
    finally:
        dispose(engine)


def test_filter_1500_sources_preserves_thumbnail_namespace_and_bounds(
    desktop, tmp_path, monkeypatch,
):
    from splatforge_gui import thumbnails

    open_project(desktop, tmp_path)
    decoded = []

    def decode(path, side=192):
        decoded.append(path)
        image = QImage(32, 24, QImage.Format_RGB32)
        image.fill(Qt.GlobalColor.green)
        return image

    monkeypatch.setattr(thumbnails, "decode_thumbnail", decode)
    rows = tuple(IndexRow(identity=uuid4(), values={
        "filename": f"{i}.png", "type": "photo", "locator": str(tmp_path / f"{i}.png"),
        "verification": "", "dimensions": "16 × 12", "isIncluded": i % 2 == 0,
        "participationLabel": "Included" if i % 2 == 0 else "Excluded from processing",
    }) for i in range(1500))
    desktop._overview(desktop.controller.overview.model_copy(update={"sources": rows}))
    desktop.setSourceView("Grid")
    engine = create_engine(desktop)
    window = engine.rootObjects()[0]
    try:
        until(lambda: bool(decoded) and not desktop.sources.thumbnails.executor.busy)
        namespace = desktop.sources.thumbnails.namespace
        for value, expected in [("Excluded", 750), ("All", 1500), ("Included", 750)]:
            desktop.setSourceFilter(value)
            QTest.qWait(50)
            grid = visual_item(window.contentItem(), "sourceGrid")
            assert grid.property("count") == expected
            delegates = [c for c in grid.property("contentItem").childItems()
                         if c.objectName().startswith("tile-")]
            assert 0 < len(delegates) < 40
            assert desktop.sources.thumbnails.namespace == namespace
        assert len(decoded) < 100
        assert not engine.load_errors
    finally:
        until(lambda: not desktop.sources.thumbnails.executor.busy)
        dispose(engine)
