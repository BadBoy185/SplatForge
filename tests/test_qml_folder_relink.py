"""Folder recovery crosses the real worker boundary and preserves project guards."""

import os
from threading import Event
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6", reason="Install the optional GUI extra")

from PySide6.QtCore import QObject, QTimer  # noqa: E402
from PySide6.QtGui import QImage  # noqa: E402
from test_qml import app as app  # noqa: E402
from test_qml import desktop as desktop  # noqa: E402
from test_qml import until, visual_item  # noqa: E402
from test_qml_interaction import click, dispose  # noqa: E402
from test_qml_sources import inject_media, photo  # noqa: E402
from test_qml_workflows import open_project  # noqa: E402

from splatforge.application.media import MediaOperationCancelled  # noqa: E402
from splatforge.bootstrap import build_media_service, build_project_service  # noqa: E402
from splatforge_gui import thumbnails  # noqa: E402
from splatforge_gui.qml_app import create_engine  # noqa: E402


def idle(vm):
    until(lambda: not vm.controller.mutating and not vm.controller.executor.busy
          and not vm.media.preview_executor.busy and not vm.sources.thumbnails.executor.busy)


def populated(vm, tmp_path):
    root = open_project(vm, tmp_path)
    vm.controller.timer.stop()
    inject_media(vm, root)
    old = tmp_path / "Recorded folder Ž"
    old.mkdir()
    path = photo(old / "photo.png")
    vm.addFiles([str(path)])
    idle(vm)
    return root, old, path


class FakeRelink:
    def __init__(self, vm, *, matched=True):
        self.vm, self.matched = vm, matched
        self.previews, self.applies = [], []
        self.entered, self.release = Event(), Event()
        self.hold = False

    def preview(self, root, old, new, *, cancellation, progress):
        self.previews.append((root, old, new))
        self.entered.set()
        if self.hold:
            assert self.release.wait(10)
        if cancellation.is_cancelled():
            raise MediaOperationCancelled("Folder check cancelled")
        progress(SimpleNamespace(completed=1, total=1, filename="photo.png", phase="checked"))
        doc = build_project_service().open(root)
        return SimpleNamespace(
            project_revision=doc.revision, total=1, matched=int(self.matched),
            can_apply=self.matched,
            entries=(SimpleNamespace(relative_path="photo.png",
                                     status="matched" if self.matched else "different_content",
                                     diagnostic="" if self.matched else "Full hash differs"),),
        )

    def apply(self, root, preview, *, cancellation, progress):
        self.applies.append((root, preview))
        if cancellation.is_cancelled():
            raise MediaOperationCancelled("Relink cancelled")
        return SimpleNamespace(project_revision=preview.project_revision, sources=())


def inject_relink(vm, service):
    original = vm.controller.factory

    def factory():
        facade = original()
        facade.factories["folder_relink"] = lambda: service
        return facade

    vm.controller.factory = factory


def folders(vm, old, new):
    vm.folderRelink.begin()
    vm.folderRelink.setOldFolder(str(old))
    vm.folderRelink.setNewFolder(str(new))


@pytest.mark.parametrize("theme", ["Dark", "Light"])
@pytest.mark.parametrize("matched", [True, False])
def test_dialog_checks_complete_scope_and_requires_all_matches(desktop, tmp_path, theme, matched):
    root, old, _ = populated(desktop, tmp_path)
    desktop.setTheme(theme)
    service = FakeRelink(desktop, matched=matched)
    inject_relink(desktop, service)
    before = (root / "project.json").read_bytes()
    engine = create_engine(desktop)
    window = engine.rootObjects()[0]
    window.resize(1024, 640)
    try:
        click(window, "catalogOptions")
        click(window, "locateSourceFolder")
        page = visual_item(window.contentItem(), "sourcesPage")
        dialog = page.findChild(QObject, "folderRelinkDialog")
        assert dialog.property("visible")
        desktop.folderRelink.setNewFolder(str(tmp_path / "Replacement"))
        click(window, "previewFolderRelink")
        idle(desktop)
        state = desktop.folderRelink.state
        assert state["status"] == "ready" and state["total"] == 1
        assert state["matched"] == int(matched) and state["canApply"] is matched
        assert service.previews[0] == (root, old, tmp_path / "Replacement")
        assert desktop.folderRelink.rows.rowCount() == 1
        assert (root / "project.json").read_bytes() == before
        assert visual_item(window.contentItem(), "applyFolderRelink").isEnabled() is matched
        if matched:
            click(window, "applyFolderRelink")
            idle(desktop)
            assert desktop.folderRelink.state["status"] == "succeeded"
            assert len(service.applies) == 1
        else:
            desktop.folderRelink.apply()
            assert not service.applies
            assert "Resolve every problem" in state["message"]
        click(window, "closeFolderRelink")
        assert not dialog.property("visible")
        assert not engine.load_errors
    finally:
        service.release.set()
        idle(desktop)
        dispose(engine)


def test_preview_cancel_is_responsive_and_retryable(desktop, tmp_path):
    root, old, _ = populated(desktop, tmp_path)
    before = (root / "project.json").read_bytes()
    service = FakeRelink(desktop)
    service.hold = True
    inject_relink(desktop, service)
    folders(desktop, old, tmp_path / "New")
    engine = create_engine(desktop)
    window = engine.rootObjects()[0]
    desktop.dialogRequested.emit("folderRelink")
    ticks = []
    try:
        click(window, "previewFolderRelink")
        until(service.entered.is_set)
        assert desktop.controller.can_cancel and desktop.folderRelink.state["busy"]
        QTimer.singleShot(0, lambda: ticks.append(True))
        until(lambda: bool(ticks))
        click(window, "cancelFolderRelink")
        assert desktop.controller.ingest_cancel.is_set()
        service.release.set()
        idle(desktop)
        assert desktop.folderRelink.state["status"] == "cancelled"
        assert (root / "project.json").read_bytes() == before
        assert not service.applies and desktop.folderRelink.state["canPreview"]
        service.hold = False
        click(window, "previewFolderRelink")
        idle(desktop)
        assert desktop.folderRelink.state["canApply"]
    finally:
        service.release.set()
        idle(desktop)
        dispose(engine)


@pytest.mark.parametrize("choice", ["save", "discard", "cancel"])
def test_unsaved_entry_uses_existing_decision_flow(desktop, tmp_path, choice):
    root, _, _ = populated(desktop, tmp_path)
    document = desktop.controller.overview.document
    desktop.controller.edit(document.model_copy(update={"label": "Edited name"}))
    dialogs = []
    desktop.dialogRequested.connect(dialogs.append)
    desktop.folderRelink.begin()
    assert dialogs[-1] == "unsaved"
    desktop.resolveUnsaved(choice)
    idle(desktop)
    if choice == "cancel":
        assert desktop.controller.dirty and "folderRelink" not in dialogs
    else:
        until(lambda: "folderRelink" in dialogs)
        assert not desktop.controller.dirty
        assert build_project_service().open(root).label == (
            "Edited name" if choice == "save" else document.label
        )


def test_path_edit_and_project_switch_revoke_preview(desktop, tmp_path):
    _, old, _ = populated(desktop, tmp_path)
    service = FakeRelink(desktop)
    inject_relink(desktop, service)
    folders(desktop, old, tmp_path / "New")
    desktop.folderRelink.preview()
    idle(desktop)
    assert desktop.folderRelink.state["canApply"]
    desktop.folderRelink.setNewFolder(str(tmp_path / "Different"))
    assert not desktop.folderRelink.state["canApply"]
    desktop.folderRelink.preview()
    idle(desktop)
    old_token, preview = desktop.folderRelink._token, desktop.folderRelink._preview
    other = tmp_path / "Other"
    build_project_service().create(other, "Other")
    desktop.openProject(str(other))
    idle(desktop)
    desktop.controller.completed.emit("relink_preview", (old_token, preview))
    assert desktop.folderRelink.state["status"] == "idle"
    assert not desktop.folderRelink.state["canApply"] and not service.applies


def test_apply_reserves_writer_until_owned_readers_stop_and_cancel_keeps_locators(
    desktop, tmp_path, monkeypatch,
):
    root, old, _ = populated(desktop, tmp_path)
    service = FakeRelink(desktop)
    inject_relink(desktop, service)
    folders(desktop, old, tmp_path / "New")
    desktop.folderRelink.preview()
    idle(desktop)
    before = (root / "project.json").read_bytes()
    entered, release = Event(), Event()

    def decode(path, side=192):
        entered.set()
        assert release.wait(10)
        return QImage(8, 8, QImage.Format.Format_RGB32)

    monkeypatch.setattr(thumbnails, "decode_thumbnail", decode)
    desktop.sources.set_thumbnails_active(True)
    desktop.sources.data(desktop.sources.index(0, 0), desktop.sources.ImageRole)
    try:
        until(entered.is_set)
        desktop.folderRelink.apply()
        assert desktop.controller.operation == "relink_apply" and desktop.controller.mutating
        assert desktop.controller.can_cancel and not service.applies
        assert desktop.controller.submit("late_reader", lambda _: None) == ""
        desktop.controller.refresh()
        desktop.controller.poll()
        assert not any(job[0] in {"refresh", "progress"}
                       for job in desktop.controller.jobs.values())
        desktop.folderRelink.cancel()
        release.set()
        idle(desktop)
        assert not service.applies and desktop.folderRelink.state["status"] == "cancelled"
        assert desktop.sources.thumbnails_active
        assert (root / "project.json").read_bytes() == before
    finally:
        release.set()
        idle(desktop)


def test_real_folder_relink_commits_all_occurrences_restores_viewer_and_reopens(
    desktop, tmp_path,
):
    root, old, first = populated(desktop, tmp_path)
    nested = old / "Nested source Ž"
    nested.mkdir()
    second = photo(nested / "Other photo.png")
    desktop.addFiles([str(second)])
    idle(desktop)
    identities = [str(row.identity) for row in desktop.sources.all_rows]
    desktop.sources.select(identities[0])
    desktop.createSourceGroup("Saved source group")
    idle(desktop)
    desktop.setSourceIncluded(identities[1], False)
    idle(desktop)
    projects = build_project_service()
    before = projects.open(root)
    originals = {path.relative_to(old): path.read_bytes() for path in (first, second)}
    engine = create_engine(desktop)
    try:
        desktop.media.showSource(identities[0])
        until(lambda: desktop.media.state["previewStatus"] == "Ready")
        new = tmp_path / "Relocated source folder"
        old.rename(new)
        folders(desktop, old, new)
        desktop.folderRelink.preview()
        idle(desktop)
        assert desktop.folderRelink.state["canApply"]
        assert desktop.folderRelink.state["matched"] == 2
        desktop.folderRelink.apply()
        idle(desktop)
        until(lambda: desktop.media.state["previewStatus"] == "Ready")
        state = desktop.folderRelink.state
        assert state["status"] == "succeeded" and not state["canApply"]
        assert state["matched"] == state["total"] == 2
        saved = projects.open(root)
        assert saved.revision == before.revision + 1
        assert saved.inventory_reference != before.inventory_reference
        assert saved.logical_source_groups == before.logical_source_groups
        assert saved.source_participation == before.source_participation
        assert saved.video_usage == before.video_usage and saved.settings == before.settings
        inventory = build_media_service().list(root)
        assert [str(source.source_id) for source in inventory.sources] == identities
        assert all(source.external_locator.startswith(str(new)) for source in inventory.sources)
        assert all(row.values["availabilityState"] == "available"
                   for row in desktop.sources.all_rows)
        assert desktop.media.state["previewSource"]["locator"] == str(new / first.relative_to(old))
        desktop.folderRelink.dismiss()
        other = tmp_path / "Other project after relink"
        projects.create(other, "Other")
        desktop.openProject(str(other))
        idle(desktop)
        assert not desktop.folderRelink.state["canApply"]
        desktop.openProject(str(root))
        idle(desktop)
        desktop.media.showSource(identities[0])
        until(lambda: desktop.media.state["previewStatus"] == "Ready")
        assert [str(row.identity) for row in desktop.sources.all_rows] == identities
        assert {relative: (new / relative).read_bytes() for relative in originals} == originals
        assert not engine.load_errors
    finally:
        idle(desktop)
        dispose(engine)


def test_real_apply_content_change_reports_error_restores_readers_and_can_retry(desktop, tmp_path):
    root, old, original = populated(desktop, tmp_path)
    replacement = tmp_path / "Replacement changed after preview"
    replacement.mkdir()
    candidate = replacement / original.name
    original_bytes = original.read_bytes()
    candidate.write_bytes(original_bytes)
    before = (root / "project.json").read_bytes()
    folders(desktop, old, replacement)
    desktop.folderRelink.preview()
    idle(desktop)
    assert desktop.folderRelink.state["canApply"]
    candidate.write_bytes(b"different bytes after preview")
    desktop.folderRelink.apply()
    idle(desktop)
    state = desktop.folderRelink.state
    assert state["status"] == "failed" and not state["canApply"]
    assert "different content" in state["message"]
    assert state["matched"] == state["total"] == 0
    assert desktop.folderRelink.rows.rowCount() == 0
    assert desktop.sources.thumbnails_active and state["canPreview"]
    assert (root / "project.json").read_bytes() == before
    assert original.read_bytes() == original_bytes
    candidate.write_bytes(original_bytes)  # All failed-worker read handles must be released.
    desktop.folderRelink.preview()
    idle(desktop)
    desktop.folderRelink.apply()
    idle(desktop)
    assert desktop.folderRelink.state["status"] == "succeeded"
    assert desktop.folderRelink.state["matched"] == desktop.folderRelink.state["total"] == 1
    assert build_media_service().list(root).sources[0].external_locator == str(candidate)
