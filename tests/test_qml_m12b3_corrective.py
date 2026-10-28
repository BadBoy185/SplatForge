"""Corrective Sources UX through real Qt delegates and committed application state."""

import os
from datetime import UTC, datetime, timedelta
from threading import Event
from uuid import UUID

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6", reason="Install the optional GUI extra")

from PySide6.QtCore import QPointF, Qt  # noqa: E402
from PySide6.QtGui import QImage  # noqa: E402
from PySide6.QtQml import QQmlExpression, qmlContext  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from test_qml import app as app  # noqa: E402
from test_qml import desktop as desktop  # noqa: E402
from test_qml import until, visual_item  # noqa: E402
from test_qml_interaction import click, dispose  # noqa: E402
from test_qml_source_participation import idle  # noqa: E402
from test_qml_sources import inject_media, photo  # noqa: E402
from test_qml_workflows import open_project  # noqa: E402

from splatforge.application.media_progress import ImportReporter  # noqa: E402
from splatforge.bootstrap import build_project_service  # noqa: E402
from splatforge_gui.qml_app import create_engine  # noqa: E402


def populate(vm, tmp_path, count=6):
    root = open_project(vm, tmp_path)
    vm.controller.timer.stop()
    files, _ = inject_media(vm, root)
    paths = [photo(tmp_path / f"{i}.png") for i in range(count)]
    vm.addFiles([str(p) for p in paths])
    idle(vm)
    return root, paths, files, [str(r.identity) for r in vm.sources.rows]


def mouse(window, name, modifiers=Qt.KeyboardModifier.NoModifier):
    item = visual_item(window.contentItem(), name)
    assert item is not None and item.isVisible(), name
    # Stay in identity/content area, away from the child action buttons.
    pos = item.mapToScene(QPointF(28, item.height() / 2)).toPoint()
    QTest.mouseClick(window, Qt.MouseButton.LeftButton, modifiers, pos)
    QTest.qWait(20)


def value(engine, item, expression):
    query = QQmlExpression(qmlContext(item), item, expression)
    result = query.evaluate()[0]
    assert not query.hasError(), query.error().toString()
    return result


@pytest.mark.parametrize("start", ["List", "Grid"])
def test_availability_updates_both_retained_presentations(desktop, tmp_path, start):
    root, paths, _, ids = populate(desktop, tmp_path, 3)
    desktop.setSourceFilter("All")
    desktop.sources.selectAllVisible()
    desktop.createSourceGroup("Drone")
    idle(desktop)
    desktop.sources.clearSelection()
    desktop.setSourceIncluded(ids[2], False)
    idle(desktop)
    group = desktop.controller.overview.document.logical_source_groups.groups[0]
    desktop.setSourceSection("group/" + str(group.group_id))
    desktop.setSourceView("Grid" if start == "List" else "List")
    engine = create_engine(desktop)
    window = engine.rootObjects()[0]
    try:
        QTest.qWait(80)
        desktop.setSourceView(start)
        QTest.qWait(80)
        until(lambda: not desktop.sources.thumbnails.executor.busy)
        paths[1].unlink()
        paths[2].write_bytes(b"changed source bytes")
        desktop.verifySources()
        idle(desktop)
        expected = ["Available", "Missing", "Needs attention"]
        for view, prefix in [(start, "source-" if start == "List" else "tile-"),
                             ("Grid" if start == "List" else "List",
                              "tile-" if start == "List" else "source-")]:
            desktop.setSourceView(view)
            QTest.qWait(80)
            for identity, status in zip(ids, expected, strict=True):
                item = visual_item(window.contentItem(), prefix + identity)
                assert value(engine, item, "record.availability") == status
        desktop.openProject(str(root))
        idle(desktop)
        assert all(r.values["availabilityState"] == "neutral" for r in desktop.sources.rows)
        assert not engine.load_errors
    finally:
        idle(desktop)
        until(lambda: not desktop.sources.thumbnails.executor.busy)
        dispose(engine)


@pytest.mark.parametrize("view", ["List", "Grid"])
def test_desktop_selection_and_selected_unselected_icon_batch_rule(desktop, tmp_path, view):
    root, paths, _, ids = populate(desktop, tmp_path)
    desktop.setSourceView(view)
    desktop.setSourceFilter("All")
    engine = create_engine(desktop)
    window = engine.rootObjects()[0]
    window.resize(1440, 900)
    prefix = "source-" if view == "List" else "tile-"
    action_prefix = "" if view == "List" else "tile-"
    try:
        QTest.qWait(100)
        mouse(window, prefix + ids[0])
        mouse(window, prefix + ids[2], Qt.KeyboardModifier.ControlModifier)
        mouse(window, prefix + ids[4], Qt.KeyboardModifier.ControlModifier)
        assert set(desktop.sources.selectedIds) == {ids[0], ids[2], ids[4]}
        mouse(window, prefix + ids[2], Qt.KeyboardModifier.ControlModifier)
        assert set(desktop.sources.selectedIds) == {ids[0], ids[4]}
        mouse(window, prefix + ids[1])
        mouse(window, prefix + ids[4], Qt.KeyboardModifier.ShiftModifier)
        assert desktop.sources.selectedIds == ids[1:5]
        before = build_project_service().open(root).revision
        click(window, action_prefix + "participation-" + ids[2])
        idle(desktop)
        saved = build_project_service().open(root)
        assert saved.revision == before + 1
        assert set(map(str, saved.source_participation.excluded_source_ids)) == set(ids[1:5])
        assert desktop.media.state["previewIndex"] == 0
        click(window, action_prefix + "participation-" + ids[0])
        idle(desktop)
        saved = build_project_service().open(root)
        assert set(map(str, saved.source_participation.excluded_source_ids)) == set(ids[:5])
        assert desktop.sources.selectedIds == ids[1:5]
        desktop.setSourceView("Grid" if view == "List" else "List")
        assert desktop.sources.selectedIds == ids[1:5]
        desktop.setSelectedIncluded(True)
        idle(desktop)
        saved = build_project_service().open(root)
        assert set(map(str, saved.source_participation.excluded_source_ids)) == {ids[0]}
        desktop.setSourceFilter("Included")
        assert desktop.sources.selectedIds == []
        QTest.keyClick(window, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
        assert set(desktop.sources.selectedIds) == set(ids[1:])
        assert all(p.exists() for p in paths)
    finally:
        idle(desktop)
        until(lambda: not desktop.sources.thumbnails.executor.busy)
        dispose(engine)


@pytest.mark.parametrize("scope,index,included,expected", [
    ("Included", 1, False, 2), ("Included", 3, False, 2),
    ("Excluded", 1, True, 2), ("All", 1, False, 2),
])
def test_preview_mutation_uses_pre_mutation_uuid_neighbors_and_only_current(
    desktop, tmp_path, scope, index, included, expected,
):
    root, _, _, ids = populate(desktop, tmp_path, 4)
    desktop.sources.selectAllVisible()
    if scope == "Excluded":
        desktop.setSelectedIncluded(False)
        idle(desktop)
    desktop.setSourceFilter(scope)
    desktop.sources.selectAllVisible()
    desktop.media.previewSource(ids[index])
    idle(desktop)
    old_token = desktop.media._preview_token
    assert desktop.sources.selectedCount == 4
    desktop.media.togglePreviewParticipation()
    idle(desktop)
    assert desktop.media.state["previewTitle"] == f"{expected}.png"
    assert desktop.media.state["previewCount"] == (4 if scope == "All" else 3)
    saved = build_project_service().open(root)
    excluded = set(map(str, saved.source_participation.excluded_source_ids))
    assert excluded == (set(ids) - {ids[index]} if included else {ids[index]})
    large = desktop.media.state["largeImage"]
    desktop.media.completed("qml_image", (old_token, QImage(), "late old image"))
    assert desktop.media.state["largeImage"] == large
    assert desktop.media.state["previewStatus"] == "Ready"


def test_preview_only_item_closes_and_project_switch_clears_state(desktop, tmp_path):
    root, _, _, ids = populate(desktop, tmp_path, 1)
    desktop.media.previewSource(ids[0])
    idle(desktop)
    desktop.media.togglePreviewParticipation()
    idle(desktop)
    assert desktop.media.state["previewIndex"] == 0
    assert desktop.media.state["largeImage"] == ""
    desktop.setSourceFilter("Excluded")
    desktop.media.previewSource(ids[0])
    idle(desktop)
    other = tmp_path / "Other"
    build_project_service().create(other, "Other")
    desktop.openProject(str(other))
    idle(desktop)
    assert desktop.sources.selectedCount == 0
    assert desktop.media.state["previewSource"] == {}
    assert desktop.media.state["largeImage"] == ""


def test_verification_observations_guard_job_generation_and_stale_eta(desktop, tmp_path):
    populate(desktop, tmp_path)
    controller = desktop.controller
    controller.operation, controller.mutating = "verify", True
    controller.verify_status, controller._verify_token = "running", "current"
    now, events = [0.0], []
    reporter = ImportReporter(30, events.append, clock=lambda: now[0], operation="verify")
    reporter.emit("checking", 0, "A.png")
    event = events[-1]
    controller._verification_observed(controller.generation, "stale", event)
    controller._verification_observed(controller.generation - 1, "current", event)
    assert controller.verify_progress is None
    controller._verification_observed(controller.generation, "current", event)
    assert desktop.state["progress"]["work"] == "0 / 30 checked · A.png"
    assert desktop.state["progress"]["eta"] == "Estimating…"
    for i in range(1, 10):
        now[0] += 2
        reporter.emit("checked", i, "B.png")
    live = events[-1]
    controller._verification_observed(controller.generation, "current", live)
    assert desktop.state["progress"]["eta"].startswith("About ")
    old = live.model_copy(update={"observation": live.observation.model_copy(update={
        "observed_at": datetime.now(UTC) - timedelta(seconds=10),
    })})
    controller.verify_progress = old
    assert desktop.state["progress"]["eta"] == "Time remaining unavailable"
    controller.operation, controller.mutating = None, False


def test_batch_group_create_and_move_single_revision(desktop, tmp_path):
    root, _, _, ids = populate(desktop, tmp_path)
    desktop.sources.selectWithModifiers(ids[1], 0)
    desktop.sources.selectWithModifiers(ids[4], Qt.KeyboardModifier.ShiftModifier.value)
    before = build_project_service().open(root).revision
    desktop.createSourceGroup("Selected batch")
    idle(desktop)
    saved = build_project_service().open(root)
    assert saved.revision == before + 1
    assert set(saved.logical_source_groups.source_assignments) == {UUID(s) for s in ids[1:5]}
    assert desktop.sources.selectedCount == 4
    desktop.assignSelectedGroup("")
    idle(desktop)
    saved = build_project_service().open(root)
    assert saved.revision == before + 2
    assert not saved.logical_source_groups.source_assignments


@pytest.mark.parametrize("view", ["List", "Grid"])
def test_icon_details_preview_keyboard_and_no_event_bubbling(desktop, tmp_path, view):
    _, _, _, ids = populate(desktop, tmp_path, 3)
    desktop.setSourceView(view)
    engine = create_engine(desktop)
    window = engine.rootObjects()[0]
    window.resize(1024, 640)
    prefix = "" if view == "List" else "tile-"
    try:
        QTest.qWait(100)
        desktop.sources.selectAllVisible()
        QTest.qWait(80)
        if view == "Grid":
            grid = visual_item(window.contentItem(), "sourceGrid")
            thumb = visual_item(grid, "photoThumbnail")
            assert thumb.height() > 32  # Batch controls must leave a usable thumbnail.
        info = visual_item(window.contentItem(), prefix + "details-" + ids[1])
        assert info.property("text") == ""
        assert value(engine, info, "Accessible.name") == "Details"
        click(window, info.objectName())
        assert desktop.sources.selectedId == ids[1]
        assert desktop.sources.selectedCount == 3
        assert desktop.media.state["previewIndex"] == 0
        click(window, "closeSourceDetails")
        preview = visual_item(window.contentItem(), prefix + "preview-" + ids[1])
        assert value(engine, preview, "Accessible.name") == "Preview"
        preview.forceActiveFocus(Qt.FocusReason.TabFocusReason)
        QTest.keyClick(window, Qt.Key.Key_Space)
        idle(desktop)
        assert desktop.media.state["previewTitle"] == "1.png"
        assert desktop.sources.selectedCount == 3
        action = visual_item(window.contentItem(), "previewParticipation")
        assert value(engine, action, "Accessible.name") == "Exclude from processing"
        assert action.property("text") == ""
        click(window, "previewParticipation")
        idle(desktop)
        assert desktop.media.state["previewTitle"] == "2.png"
        assert desktop.sources.selectedCount == 2
        assert desktop.media.state["previewIndex"] == 2
        click(window, "closeImagePreview")
        assert not engine.load_errors
    finally:
        idle(desktop)
        until(lambda: not desktop.sources.thumbnails.executor.busy)
        dispose(engine)


def test_folder_preview_exposes_groups_and_unsupported_folders_stay_empty(desktop, tmp_path):
    root = open_project(desktop, tmp_path)
    desktop.controller.timer.stop()
    inject_media(desktop, root)
    folder = tmp_path / "Photos"
    (folder / "Drone").mkdir(parents=True)
    (folder / "Ignored").mkdir()
    photo(folder / "a.png")
    photo(folder / "Drone" / "b.png")
    (folder / "Ignored" / "text.txt").write_text("ignored")
    desktop.addFolder(str(folder))
    idle(desktop)
    assert desktop.state["scan"]["groups"] == [{"label": "Drone", "count": 1}]
    desktop.confirmFolder()
    idle(desktop)
    saved = build_project_service().open(root)
    assert [g.label for g in saved.logical_source_groups.groups] == ["Drone"]
    assert len(saved.logical_source_groups.source_assignments) == 1


@pytest.mark.parametrize("action", ["exclude", "restore", "create", "move", "preview"])
def test_failed_batch_or_preview_save_retains_committed_model(desktop, tmp_path, action):
    root, _, _, ids = populate(desktop, tmp_path, 4)
    desktop.sources.selectAllVisible()
    desktop.createSourceGroup("Existing")
    idle(desktop)
    if action == "restore":
        desktop.setSelectedIncluded(False)
        idle(desktop)
        desktop.setSourceFilter("Excluded")
    desktop.sources.selectAllVisible()
    before = build_project_service().open(root)
    original_factory = desktop.controller.factory

    def factory():
        facade = original_factory()

        def fail(*args):
            raise OSError("Batch metadata write failed")

        facade.save = fail
        return facade

    desktop.controller.factory = factory
    if action == "create":
        desktop.createSourceGroup("Never saved")
    elif action == "move":
        desktop.assignSelectedGroup("")
    elif action == "preview":
        desktop.media.previewSource(ids[1])
        idle(desktop)
        desktop.media.togglePreviewParticipation()
    else:
        desktop.setSelectedIncluded(action == "restore")
    idle(desktop)
    after = build_project_service().open(root)
    assert before == after
    assert desktop.sources.selectedCount == 4
    assert not desktop.controller.dirty
    assert desktop.state["error"]["message"] == "Batch metadata write failed"
    assert desktop.controller.overview.document == before
    if action == "preview":
        assert desktop.media.state["previewTitle"] == "1.png"
        assert desktop.media._review_mutation is None


@pytest.mark.parametrize("cancel", [False, True])
def test_real_verification_cancel_or_failure_has_no_completed_ui(desktop, tmp_path, cancel):
    populate(desktop, tmp_path, 4)
    entered, release = Event(), Event()
    original_factory = desktop.controller.factory

    def factory():
        facade = original_factory()
        service = facade.service("media")
        original = service.verify

        def verify(root, *, cancellation=None, progress=None):
            def observe(event):
                progress(event)
                if event.phase == "checked" and event.observation.completed == 1:
                    entered.set()
                    assert release.wait(10)
                    if not cancel:
                        raise OSError("Source check storage unavailable")

            return original(root, cancellation=cancellation, progress=observe)

        service.verify = verify
        facade.factories["media"] = lambda: service
        return facade

    desktop.controller.factory = factory
    desktop.verifySources()
    try:
        until(entered.is_set)
        until(lambda: desktop.controller.verify_progress.observation.completed == 1)
        assert desktop.state["progress"]["work"].startswith("1 / 4 checked")
        if cancel:
            desktop.cancel()
    finally:
        release.set()
    idle(desktop)
    assert desktop.controller.verify_status == ("cancelled" if cancel else "failed")
    assert desktop.controller.verify_progress.phase != "succeeded"
    assert desktop.state["sourceCheckResult"] == ""
    if not cancel:
        assert desktop.state["error"]["message"] == "Source check storage unavailable"
