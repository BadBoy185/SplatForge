"""Projects entry routes retain one session and obey existing mutation ownership."""
import os
from threading import Event

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QObject, QSettings, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from test_qml import app as app  # noqa: E402
from test_qml import desktop as desktop  # noqa: E402
from test_qml import until, visual_item  # noqa: E402
from test_qml_interaction import click, dispose  # noqa: E402
from test_qml_workflows import open_project  # noqa: E402

from splatforge.bootstrap import build_gui_facade, build_project_service  # noqa: E402
from splatforge_gui.preferences import Preferences  # noqa: E402
from splatforge_gui.qml_app import create_engine  # noqa: E402
from splatforge_gui.qml_bridge import DesktopViewModel  # noqa: E402


def idle(vm):
    until(lambda: not vm.controller.executor.busy and not vm.controller.mutating)


@pytest.mark.parametrize("saved_page", [0, 5, 6, "obsolete-page"])
def test_launch_ignores_legacy_page_but_explicit_open_enters_materials(app, tmp_path, saved_page):
    prefs = Preferences(QSettings(str(tmp_path / "legacy.ini"), QSettings.IniFormat))
    prefs.set("page", saved_page)
    root = tmp_path / "Remembered"
    doc = build_project_service().create(root, "Remembered")
    prefs.remember(root, project_id=str(doc.project_id), name=doc.label)
    vm = DesktopViewModel(preferences=prefs)
    vm.controller.timer.stop()
    try:
        idle(vm)
        assert vm.state["page"] == 0 and not vm.state["hasProject"]
        vm.openProject(str(root))
        idle(vm)
        assert vm.state["page"] == 1
    finally:
        vm.deleteLater()


@pytest.mark.parametrize("page", [1, 2, 4, 5])
def test_projects_button_retains_draft_section_and_session(desktop, tmp_path, page):
    root = open_project(desktop, tmp_path)
    desktop.controller.timer.stop()
    desktop.navigate(page)
    draft = desktop.controller.overview.document.model_copy(update={"label": "Unsaved draft"})
    desktop.controller.edit(draft)
    draft = desktop.controller.draft
    generation = desktop.controller.generation
    saved = (root / "project.json").read_bytes()
    engine = create_engine(desktop)
    window = engine.rootObjects()[0]
    window.resize(1024, 640)
    try:
        click(window, "nav-Projects")
        assert desktop.state["page"] == 0
        assert desktop.controller.draft is draft
        assert (root / "project.json").read_bytes() == saved
        assert visual_item(window.contentItem(), "resumeCurrentProject").isEnabled()
        desktop.openProject(str(root))
        idle(desktop)
        assert desktop.state["page"] == page
        assert desktop.controller.generation == generation
        assert desktop.controller.draft is draft
        assert not engine.load_errors
    finally:
        desktop.controller.discard()
        dispose(engine)


def test_same_path_replaced_identity_uses_switch_guard(desktop, tmp_path):
    root = open_project(desktop, tmp_path)
    desktop.controller.timer.stop()
    desktop.controller.edit(
        desktop.controller.overview.document.model_copy(update={"label": "Draft"})
    )
    original_id = desktop.controller.overview.document.project_id
    root.rename(root.with_name("Moved original"))
    build_project_service().create(root, "Replacement")
    desktop.navigate(0)
    dialogs = []
    desktop.dialogRequested.connect(dialogs.append)
    desktop.openProject(str(root))
    idle(desktop)
    assert dialogs[-1] == "unsaved"
    assert desktop.controller.overview.document.project_id == original_id
    desktop.resolveUnsaved("cancel")
    desktop.resumeProject()
    assert desktop.controller.dirty and desktop.state["page"] == 1


def test_failed_save_during_switch_keeps_draft_and_allows_retry(desktop, tmp_path):
    root = open_project(desktop, tmp_path)
    other = tmp_path / "Other"
    build_project_service().create(other, "Other")
    draft = desktop.controller.overview.document.model_copy(update={"label": "Draft"})
    desktop.controller.edit(draft)
    draft = desktop.controller.draft
    # External revision change produces a real CAS refusal through ProjectService.
    service = build_project_service()
    service.save(root, service.open(root).model_copy(update={"label": "External"}))
    desktop.navigate(0)
    desktop.openProject(str(other))
    desktop.resolveUnsaved("save")
    idle(desktop)
    assert desktop.controller.root == root and desktop.controller.draft is draft
    assert desktop.state["entryError"] and not desktop.state["entryPending"]
    assert desktop.state["page"] == 0
    desktop.resumeProject()
    assert desktop.controller.draft is draft


def test_create_error_retains_form_and_keyboard_submission(desktop, tmp_path):
    engine = create_engine(desktop)
    window = engine.rootObjects()[0]
    occupied = tmp_path / "Occupied"
    occupied.mkdir()
    (occupied / "keep.txt").write_text("Keep")
    try:
        click(window, "newProject")
        dialog = window.findChild(QObject, "createProjectDialog")
        name = window.findChild(QObject, "projectName")
        location = window.findChild(QObject, "projectLocation")
        name.setProperty("text", "CON")
        location.setProperty("text", str(tmp_path))
        QTest.keyClick(window, Qt.Key_Return)
        assert not desktop.state["hasProject"] and dialog.property("visible")
        name.setProperty("text", "Occupied")
        QTest.keyClick(window, Qt.Key_Return)
        idle(desktop)
        assert dialog.property("visible")
        assert name.property("text") == "Occupied"
        assert location.property("text") == str(tmp_path)
        assert "contains files" in desktop.state["entryError"]
        assert (occupied / "keep.txt").read_text() == "Keep"
        name.setProperty("text", "Corrected")
        name.forceActiveFocus()
        QTest.keyClick(window, Qt.Key_Tab)
        assert location.property("activeFocus")
        QTest.keyClick(window, Qt.Key_Tab)
        assert window.activeFocusItem().objectName() == "browseProjectLocation"
        QTest.keyClick(window, Qt.Key_Backtab)
        QTest.keyClick(window, Qt.Key_Return)
        idle(desktop)
        assert not dialog.property("visible") and desktop.state["page"] == 1
        assert desktop.controller.root == tmp_path / "Corrected"
        assert not engine.load_errors
    finally:
        idle(desktop)
        dispose(engine)


def test_create_pending_rejects_escape_and_duplicate_submit(desktop, tmp_path):
    entered, release = Event(), Event()

    class SlowFacade:
        def __init__(self):
            self.delegate = build_gui_facade()

        def __getattr__(self, name):
            return getattr(self.delegate, name)

        def create(self, root, label):
            entered.set()
            assert release.wait(10)
            return self.delegate.create(root, label)

    desktop.controller.factory = SlowFacade
    engine = create_engine(desktop)
    window = engine.rootObjects()[0]
    try:
        click(window, "newProject")
        window.findChild(QObject, "projectName").setProperty("text", "Created")
        window.findChild(QObject, "projectLocation").setProperty("text", str(tmp_path))
        click(window, "confirmCreateProject")
        until(entered.is_set)
        QTest.keyClick(window, Qt.Key_Escape)
        assert window.findChild(QObject, "createProjectDialog").property("visible")
        desktop.createProject(str(tmp_path), "Duplicate")
        assert not (tmp_path / "Duplicate").exists()
        release.set()
        idle(desktop)
        assert desktop.controller.root == tmp_path / "Created"
        assert not window.findChild(QObject, "createProjectDialog").property("visible")
    finally:
        release.set()
        idle(desktop)
        dispose(engine)


def test_unsaved_escape_releases_pending_switch(desktop, tmp_path):
    open_project(desktop, tmp_path)
    desktop.controller.edit(
        desktop.controller.overview.document.model_copy(update={"label": "Draft"})
    )
    engine = create_engine(desktop)
    window = engine.rootObjects()[0]
    try:
        desktop.navigate(0)
        desktop.createProject(str(tmp_path), "Another")
        QTest.qWait(50)
        assert window.findChild(QObject, "unsavedDialog").property("visible")
        QTest.keyClick(window, Qt.Key_Escape)
        assert not desktop.state["entryPending"] and desktop.controller.dirty
        assert not (tmp_path / "Another").exists()
    finally:
        desktop.controller.discard()
        dispose(engine)

def test_recent_keyboard_open_and_path_copy(desktop, tmp_path):
    from PySide6.QtGui import QGuiApplication

    first, second = tmp_path / "First", tmp_path / "Second"
    service = build_project_service()
    for root in (first, second):
        doc = service.create(root, root.name)
        desktop.preferences.remember(root, project_id=str(doc.project_id), name=doc.label)
    desktop.refresh_recents()
    idle(desktop)
    engine = create_engine(desktop)
    window = engine.rootObjects()[0]
    try:
        recent_list = visual_item(window.contentItem(), "recentProjects")
        recent_list.forceActiveFocus(Qt.TabFocusReason)
        recent_list.setProperty("currentIndex", 0)
        QTest.keyClick(window, Qt.Key_Down)
        assert recent_list.property("currentIndex") == 1
        QTest.keyClick(window, Qt.Key_Return)
        idle(desktop)
        assert desktop.controller.root == first and desktop.state["page"] == 1
        desktop.navigate(0)
        click(window, "recentProjectMenu")
        QTest.keyClick(window, Qt.Key_Down)
        QTest.keyClick(window, Qt.Key_Return)
        assert QGuiApplication.clipboard().text() == str(first)
        assert not engine.load_errors
    finally:
        idle(desktop)
        dispose(engine)
