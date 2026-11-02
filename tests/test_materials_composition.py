"""Changed Materials controls preserve real selection, readback and panel geometry."""

import os
from uuid import UUID

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QObject, QPointF, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from test_materials_workspace import idle, imported  # noqa: E402
from test_qml import app as app  # noqa: E402
from test_qml import desktop as desktop  # noqa: E402
from test_qml import until, visual_item  # noqa: E402
from test_qml_interaction import click, dispose  # noqa: E402
from test_qml_sources import accept_files, inject_media, photo  # noqa: E402
from test_qml_workflows import open_project  # noqa: E402

from splatforge.bootstrap import build_project_service  # noqa: E402
from splatforge_gui.qml_app import create_engine  # noqa: E402


def test_compact_properties_stay_inside_workspace_and_reopen(desktop, tmp_path):
    _, ids = imported(desktop, tmp_path)
    desktop.media.showSource(ids[0])
    engine = create_engine(desktop)
    window = engine.rootObjects()[0]
    try:
        window.resize(1024, 640)
        idle(desktop)
        click(window, "restoreMaterialProperties")
        header = visual_item(window.contentItem(), "collapseMaterialProperties")
        position = header.mapToScene(QPointF(0, 0))
        assert 50 <= position.y() <= 70
        assert 700 <= position.x() < 1024 - header.width()
        click(window, "sourceDetails")
        assert visual_item(window.contentItem(), "sourceHumanDimensions").isVisible()
        click(window, "closeSourceDetails")
        QTest.keyClick(window, Qt.Key_Escape)
        QTest.qWait(40)
        assert not visual_item(window.contentItem(), "sourcesPage").property("propertiesVisible")
        click(window, "restoreMaterialProperties")
        click(window, "collapseMaterialProperties")
        click(window, "collapseMaterialsCatalog")
        viewer = visual_item(window.contentItem(), "materialViewer")
        assert viewer.width() > 1000
        click(window, "restoreMaterialsCatalog")
        assert viewer.width() < 800
        assert not engine.load_errors
    finally:
        idle(desktop)
        dispose(engine)


@pytest.mark.parametrize("view", ["List", "Grid"])
def test_current_inspector_and_batch_actions_have_independent_saved_scope(desktop, tmp_path, view):
    root, ids = imported(desktop, tmp_path)
    desktop.setSourceView(view)
    desktop.media.showSource(ids[0])
    desktop.sources.selectAllVisible()
    engine = create_engine(desktop)
    window = engine.rootObjects()[0]
    try:
        idle(desktop)
        click(window, "materialNext")
        idle(desktop)
        assert desktop.media.state["previewSource"]["identity"] == ids[1]
        assert set(desktop.sources.selectedIds) == set(ids)
        click(window, "sourceDetails")
        assert visual_item(window.contentItem(), "sourceHumanDimensions").isVisible()
        assert set(desktop.sources.selectedIds) == set(ids)
        click(window, "closeSourceDetails")
        click(window, "currentMaterialParticipation")
        idle(desktop)
        document = build_project_service().open(root)
        assert set(document.source_participation.excluded_source_ids) == {UUID(ids[1])}
        assert desktop.media.state["previewSource"]["identity"] == ids[2]
        assert desktop.sources.selectedCount == 2
        click(window, "batchExclude")
        idle(desktop)
        assert desktop.sources.count == 0
        assert set(build_project_service().open(root).source_participation.excluded_source_ids) == {
            UUID(value) for value in ids
        }
        click(window, "filterExcluded")
        QTest.keyClick(window, Qt.Key_A, Qt.ControlModifier)
        click(window, "batchRestore")
        idle(desktop)
        assert not build_project_service().open(root).source_participation.excluded_source_ids
        assert not engine.load_errors
    finally:
        idle(desktop)
        dispose(engine)


@pytest.mark.parametrize("view", ["List", "Grid"])
def test_catalog_modifier_selection_and_view_switch(desktop, tmp_path, view):
    _, ids = imported(desktop, tmp_path)
    desktop.setSourceView(view)
    engine = create_engine(desktop)
    window = engine.rootObjects()[0]
    try:
        prefix = "source-" if view == "List" else "tile-"

        def select(identity, modifiers=Qt.NoModifier):
            until(lambda: visual_item(window.contentItem(), prefix + identity) is not None)
            control = visual_item(window.contentItem(), prefix + identity)
            QTest.qWait(80)
            # Thumbnail is the row body, away from the contextual menu hit area.
            pos = control.mapToScene(QPointF(30, 30)).toPoint()
            QTest.mouseClick(window, Qt.LeftButton, modifiers, pos)
            idle(desktop)

        select(ids[0])
        select(ids[1], Qt.ControlModifier)
        assert set(desktop.sources.selectedIds) == set(ids[:2])
        select(ids[2], Qt.ShiftModifier)
        assert set(desktop.sources.selectedIds) == set(ids[1:])
        click(window, "sourceGridMode" if view == "List" else "sourceListMode")
        assert set(desktop.sources.selectedIds) == set(ids[1:])
        QTest.keyClick(window, Qt.Key_A, Qt.ControlModifier)
        assert set(desktop.sources.selectedIds) == set(ids)
        assert not engine.load_errors
    finally:
        idle(desktop)
        dispose(engine)


def test_catalog_check_is_disclosed_and_updates_committed_evidence(desktop, tmp_path):
    imported(desktop, tmp_path)
    engine = create_engine(desktop)
    window = engine.rootObjects()[0]
    try:
        click(window, "catalogOptions")
        click(window, "checkSourceFiles")
        summary = visual_item(window.contentItem(), "sourceCheckSummary")
        assert summary.isVisible()
        click(window, "runSourceCheck")
        idle(desktop)
        assert desktop.state["sourceCheckResult"]
        assert not engine.load_errors
    finally:
        idle(desktop)
        dispose(engine)


@pytest.mark.parametrize("kind", ["photos", "videos"])
def test_compact_import_buttons_retain_explicit_picker_and_readback(desktop, tmp_path, kind):
    root = open_project(desktop, tmp_path)
    inject_media(desktop, root)
    path = tmp_path / ("sample.png" if kind == "photos" else "sample.mp4")
    photo(path) if kind == "photos" else path.write_bytes(b"tiny probe fixture")
    original = path.read_bytes()
    engine = create_engine(desktop)
    window = engine.rootObjects()[0]
    try:
        click(window, "addPhotos" if kind == "photos" else "addVideo")
        page = visual_item(window.contentItem(), "sourcesPage")
        picker = page.findChild(QObject, kind + "Picker")
        assert picker.property("visible")
        accept_files(engine, picker, [path])
        idle(desktop)
        assert desktop.sources.count == 1
        assert desktop.sources.rows[0].values["type"] == ("photo" if kind == "photos" else "video")
        assert path.read_bytes() == original
        desktop.controller.open(root)
        idle(desktop)
        assert desktop.sources.count == 1
        assert not engine.load_errors
    finally:
        idle(desktop)
        dispose(engine)


def test_row_menu_keeps_batch_and_opens_requested_details(desktop, tmp_path):
    _, ids = imported(desktop, tmp_path)
    desktop.media.showSource(ids[0])
    desktop.sources.selectAllVisible()
    engine = create_engine(desktop)
    window = engine.rootObjects()[0]
    try:
        idle(desktop)
        row = visual_item(window.contentItem(), "source-" + ids[1])
        row.forceActiveFocus()
        click(window, "actions-" + ids[1])
        click(window, "details-" + ids[1])
        assert set(desktop.sources.selectedIds) == set(ids)
        assert desktop.sources.selectedId == ids[1]
        assert desktop.media.state["previewSource"]["identity"] == ids[0]
        click(window, "closeSourceDetails")
        click(window, "sourceDetails")
        assert desktop.sources.selectedId == ids[0]
        assert set(desktop.sources.selectedIds) == set(ids)
        click(window, "closeSourceDetails")
        row.forceActiveFocus()
        click(window, "actions-" + ids[1])
        click(window, "participation-" + ids[1])
        idle(desktop)
        assert desktop.sources.count == 0
        assert not engine.load_errors
    finally:
        idle(desktop)
        dispose(engine)


def test_split_resize_retains_width_through_collapse(desktop, tmp_path):
    imported(desktop, tmp_path)
    engine = create_engine(desktop)
    window = engine.rootObjects()[0]
    try:
        QTest.qWait(100)
        catalog = visual_item(window.contentItem(), "materialsCatalog")
        handle = catalog.mapToScene(QPointF(catalog.width() + 2, 260)).toPoint()
        QTest.mousePress(window, Qt.LeftButton, pos=handle)
        QTest.mouseMove(window, handle + QPointF(60, 0).toPoint(), 100)
        QTest.mouseRelease(window, Qt.LeftButton, pos=handle + QPointF(60, 0).toPoint())
        QTest.qWait(80)
        assert catalog.width() > 320
        width = catalog.width()
        click(window, "collapseMaterialsCatalog")
        click(window, "restoreMaterialsCatalog")
        assert catalog.width() == pytest.approx(width)
        click(window, "sourceGridMode")
        click(window, "expandMaterialsGrid")
        click(window, "collapseMaterialsCatalog")
        assert visual_item(window.contentItem(), "materialViewer").isVisible()
        click(window, "restoreMaterialsCatalog")
        assert not engine.load_errors
    finally:
        idle(desktop)
        dispose(engine)
