"""Materials lifetime and session boundaries under controlled in-flight worker results."""

import os
from threading import Event

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import Qt  # noqa: E402
from test_materials_workspace import idle, imported  # noqa: E402
from test_qml import app as app  # noqa: E402
from test_qml import desktop as desktop  # noqa: E402
from test_qml import until  # noqa: E402
from test_qml_interaction import click, dispose  # noqa: E402
from test_qml_sources import inject_media, photo  # noqa: E402

from splatforge.application.desktop import GuiFacade  # noqa: E402
from splatforge.bootstrap import build_project_service  # noqa: E402
from splatforge_gui import qml_media  # noqa: E402
from splatforge_gui.qml_app import create_engine  # noqa: E402


@pytest.mark.parametrize("change", ["close", "project"])
def test_late_properties_error_cannot_restore_closed_review(desktop, tmp_path, monkeypatch, change):
    _, ids = imported(desktop, tmp_path)
    entered, release = Event(), Event()

    def delayed_error(*_):
        entered.set()
        assert release.wait(10)
        raise OSError("old review properties error")

    monkeypatch.setattr(GuiFacade, "source_details", delayed_error)
    desktop.media.showSource(ids[0])
    try:
        until(entered.is_set)
        if change == "close":
            desktop.media.closePreview()
        else:
            other = tmp_path / "Other"
            build_project_service().create(other, "Other")
            desktop.openProject(str(other))
            until(lambda: desktop.controller.root == other)
        release.set()
        idle(desktop)
        assert desktop.media.state["previewSource"] == {}
        assert desktop.media.state["sourceDetails"] == {"fields": [], "technical": ""}
        assert not desktop.state["error"]
    finally:
        release.set()
        idle(desktop)


def test_old_decode_finishes_after_switch_without_cross_project_image(
    desktop, tmp_path, monkeypatch,
):
    _, ids = imported(desktop, tmp_path)
    other = tmp_path / "Other ž"
    build_project_service().create(other, "Other ž")
    entered, release = Event(), Event()
    original = qml_media.decode_preview

    def delayed(path):
        if path.name == "image 0.png":
            entered.set()
            assert release.wait(10)
        return original(path)

    monkeypatch.setattr(qml_media, "decode_preview", delayed)
    desktop.media.showSource(ids[0])
    try:
        until(entered.is_set)
        desktop.openProject(str(other))
        until(lambda: desktop.controller.root == other and not desktop.controller.executor.busy)
        inject_media(desktop, other)
        new_path = photo(tmp_path / "New green.png", Qt.GlobalColor.green)
        desktop.addFiles([str(new_path)])
        until(lambda: desktop.sources.count == 1 and not desktop.controller.executor.busy)
        new_id = str(desktop.sources.rows[0].identity)
        desktop.media.showSource(new_id)
        assert desktop.media.state["largeImage"] == ""
        release.set()
        idle(desktop)
        assert desktop.media.state["previewSource"]["identity"] == new_id
        assert desktop.media.state["previewTitle"] == new_path.name
        assert desktop.media.provider.large.pixelColor(0, 0) == Qt.GlobalColor.green
        assert not desktop.state["error"]
    finally:
        release.set()
        idle(desktop)


def test_projects_resume_keeps_current_batch_group_filter_and_saved_readback(desktop, tmp_path):
    root, ids = imported(desktop, tmp_path)
    desktop.sources.selectAllVisible()
    desktop.createSourceGroup("Review ž")
    idle(desktop)
    group = desktop.controller.overview.document.logical_source_groups.groups[0]
    desktop.setSourceSection("group/" + str(group.group_id))
    desktop.setSourceFilter("All")
    desktop.sources.selectWithModifiers(ids[0], 0)
    desktop.sources.selectWithModifiers(ids[1], Qt.ControlModifier.value)
    desktop.media.showSource(ids[2])
    idle(desktop)
    generation = desktop.controller.generation
    engine = create_engine(desktop)
    window = engine.rootObjects()[0]
    try:
        click(window, "nav-Projects")
        click(window, "resumeCurrentProject")
        assert desktop.controller.generation == generation
        assert desktop.state["sourceSection"] == "group/" + str(group.group_id)
        assert desktop.state["sourceFilter"] == "All"
        assert set(desktop.sources.selectedIds) == set(ids[:2])
        assert desktop.media.state["previewSource"]["identity"] == ids[2]
        desktop.setSelectedIncluded(False)
        idle(desktop)
        desktop.controller.open(root)
        idle(desktop)
        saved = build_project_service().open(root)
        assert set(map(str, saved.source_participation.excluded_source_ids)) == set(ids[:2])
        assert saved.logical_source_groups.groups[0].label == "Review ž"
        assert not engine.load_errors
    finally:
        idle(desktop)
        dispose(engine)
