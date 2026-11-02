"""Catalog actions use highlighted UUIDs independently of the viewed material."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6", reason="Install the optional GUI extra")

from PySide6.QtCore import Qt  # noqa: E402
from test_qml import app as app  # noqa: E402
from test_qml import desktop as desktop  # noqa: E402
from test_qml import until, visual_item  # noqa: E402
from test_qml_capture_groups import choose  # noqa: E402
from test_qml_interaction import click, dispose  # noqa: E402
from test_qml_m12b3_corrective import populate  # noqa: E402
from test_qml_source_participation import idle  # noqa: E402

from splatforge.bootstrap import build_project_service  # noqa: E402
from splatforge_gui.qml_app import create_engine  # noqa: E402


def test_group_move_and_ungroup_use_single_batch_uuid_after_viewer_navigation(desktop, tmp_path):
    root, paths, _, ids = populate(desktop, tmp_path, 3)
    desktop.createSourceGroup("Target")
    idle(desktop)
    group = desktop.state["logicalGroups"][1]["value"]
    desktop.sources.select(ids[0])
    desktop.media.showSource(ids[0])
    desktop.media.stepPreview(1)
    idle(desktop)
    assert desktop.sources.selectedIds == [ids[0]]
    assert desktop.sources.selectedId == ids[1]
    engine = create_engine(desktop)
    window = engine.rootObjects()[0]
    try:
        click(window, "sourceGroups")
        label = visual_item(window.contentItem(), "groupSelectedSource").property("text")
        assert "1 selected source" in label
        destination = visual_item(window.contentItem(), "sourceGroupDestination")
        choose(engine, destination, group)
        before = build_project_service().open(root).revision
        click(window, "moveSourceToGroup")
        idle(desktop)
        saved = build_project_service().open(root)
        assert saved.revision == before + 1
        assert {str(k) for k in saved.logical_source_groups.source_assignments} == {ids[0]}
        assert desktop.media.state["previewSource"]["identity"] == ids[1]
        choose(engine, destination, "")
        click(window, "moveSourceToGroup")
        idle(desktop)
        assert not build_project_service().open(root).logical_source_groups.source_assignments
        desktop.sources.clearSelection()
        assert not visual_item(window.contentItem(), "moveSourceToGroup").isEnabled()
        assert all(p.exists() for p in paths)
        assert not engine.load_errors
    finally:
        idle(desktop)
        until(lambda: not desktop.sources.thumbnails.executor.busy)
        dispose(engine)


@pytest.mark.parametrize("restore", [False, True])
def test_catalog_participation_uses_explicit_operation_on_batch(desktop, tmp_path, restore):
    root, paths, _, ids = populate(desktop, tmp_path, 3)
    desktop.setSourceFilter("All")
    # Highlighted A/B and viewed C have opposite participation.
    desktop.sources.select(ids[0])
    desktop.sources.selectWithModifiers(ids[1], Qt.ControlModifier.value)
    if restore:
        desktop.setSelectedIncluded(False)
    else:
        desktop.setSourceIncluded(ids[2], False)
    idle(desktop)
    desktop.media.showSource(ids[2])
    idle(desktop)
    assert set(desktop.sources.selectedIds) == set(ids[:2])
    assert desktop.sources.selectedId == ids[2]
    engine = create_engine(desktop)
    window = engine.rootObjects()[0]
    try:
        click(window, "catalogOptions")
        click(window, "restoreSelectedSources" if restore else "sourceParticipation")
        idle(desktop)
        saved = build_project_service().open(root)
        assert set(map(str, saved.source_participation.excluded_source_ids)) == (
            set() if restore else set(ids)
        )
        assert desktop.media.state["previewSource"]["identity"] == ids[2]
        assert all(p.exists() for p in paths)
        assert not engine.load_errors
    finally:
        idle(desktop)
        until(lambda: not desktop.sources.thumbnails.executor.busy)
        dispose(engine)
