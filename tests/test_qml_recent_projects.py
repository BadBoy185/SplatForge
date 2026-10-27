"""Machine-local project history with identity-checked relocation, never deletion."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6", reason="Install the optional GUI extra")

from PySide6.QtCore import QSettings  # noqa: E402
from test_qml import app as app  # noqa: E402
from test_qml import desktop as desktop  # noqa: E402
from test_qml import until, visual_item  # noqa: E402
from test_qml_interaction import click, dispose  # noqa: E402

from splatforge.bootstrap import build_project_service  # noqa: E402
from splatforge_gui.preferences import Preferences  # noqa: E402
from splatforge_gui.qml_app import create_engine  # noqa: E402
from splatforge_gui.qml_bridge import DesktopViewModel  # noqa: E402


def idle(vm):
    until(lambda: not vm.controller.executor.busy)


def test_successful_create_open_order_restart_and_home_open(desktop, tmp_path):
    desktop.createProject(str(tmp_path), "First")
    idle(desktop)
    desktop.createProject(str(tmp_path), "Second")
    idle(desktop)
    entries = desktop.preferences.entries()
    assert [e["name"] for e in entries] == ["Second", "First"]
    assert all(e["lastOpened"] and e["projectId"] for e in entries)
    desktop.openProject(str(tmp_path / "First"))
    idle(desktop)
    entries = desktop.preferences.entries()
    assert [e["name"] for e in entries] == ["First", "Second"]
    stamp = entries[0]["lastOpened"]
    desktop.refresh()
    idle(desktop)
    assert desktop.preferences.entries()[0]["lastOpened"] == stamp
    preferences = Preferences(
        QSettings(desktop.preferences.settings.fileName(), QSettings.IniFormat)
    )
    restarted = DesktopViewModel(preferences=preferences)
    restarted.controller.timer.stop()
    engine = None
    try:
        idle(restarted)
        assert preferences.entries() == entries
        assert [e["name"] for e in restarted.state["recents"]] == ["First", "Second"]
        assert "Last opened:" in restarted.state["recents"][0]["lastOpenedLabel"]
        engine = create_engine(restarted)
        window = engine.rootObjects()[0]
        click(window, "openRecentProject")
        idle(restarted)
        assert restarted.controller.root == tmp_path / "First"
        restarted.navigate(0)
        assert visual_item(window.contentItem(), "recentProjects").isVisible()
        assert not restarted.controller.overview.index.runs
        assert not engine.load_errors
    finally:
        idle(restarted)
        if engine:
            dispose(engine)
        restarted.deleteLater()


def test_locate_validates_identity_preserves_order_and_remove_never_touches_disk(desktop, tmp_path):
    desktop.createProject(str(tmp_path), "Moved")
    idle(desktop)
    desktop.controller.timer.stop()
    old = tmp_path / "Moved"
    before = desktop.preferences.entries()[0]
    moved = tmp_path / "New location"
    old.rename(moved)
    desktop.refresh_recents()
    idle(desktop)
    assert not desktop.state["recents"][0]["available"]
    assert desktop.state["recents"][0]["summary"] == "Project not found"
    other = tmp_path / "Other"
    build_project_service().create(other, "Other")
    desktop.locateRecent(str(old), str(other))
    idle(desktop)
    assert "different SplatForge project" in desktop.state["error"]["message"]
    assert desktop.preferences.entries() == [before]
    invalid = tmp_path / "Not a project"
    invalid.mkdir()
    desktop.locateRecent(str(old), str(invalid))
    idle(desktop)
    assert desktop.preferences.entries() == [before]
    desktop.locateRecent(str(old), str(moved))
    idle(desktop)
    after = desktop.preferences.entries()[0]
    assert after["path"] == str(moved)
    assert after["projectId"] == before["projectId"] and after["lastOpened"] == before["lastOpened"]
    assert desktop.state["recents"][0]["available"]
    desktop.openProject(str(moved))
    idle(desktop)
    assert desktop.controller.root == moved
    contents = {p.name: p.read_bytes() for p in moved.iterdir() if p.is_file()}
    desktop.removeRecent(str(moved))
    idle(desktop)
    assert desktop.preferences.entries() == [] and moved.exists()
    assert contents == {p.name: p.read_bytes() for p in moved.iterdir() if p.is_file()}


def test_legacy_unknown_identity_locate_requires_explicit_confirmation(desktop, tmp_path):
    old, target = tmp_path / "Missing legacy", tmp_path / "Candidate"
    build_project_service().create(target, "Candidate")
    desktop.preferences.set("recent", [str(old)])
    desktop.refresh_recents()
    idle(desktop)
    dialogs = []
    desktop.dialogRequested.connect(dialogs.append)
    desktop.locateRecent(str(old), str(target))
    idle(desktop)
    assert dialogs[-1] == "confirmRecentLocation"
    assert desktop.preferences.recent() == [str(old)]
    assert desktop.controller.root is None
    desktop.confirmRecentLocation()
    idle(desktop)
    assert desktop.preferences.recent() == [str(target)]
    assert desktop.preferences.entries()[0]["projectId"]
    assert desktop.controller.root is None  # Locate never starts processing or opens implicitly.


def test_missing_recent_exposes_locate_and_safe_remove(desktop, tmp_path):
    missing = tmp_path / "Disconnected drive"
    desktop.preferences.remember(missing, name="Lom Plešivec")
    desktop.refresh_recents()
    idle(desktop)
    engine = create_engine(desktop)
    window = engine.rootObjects()[0]
    try:
        assert visual_item(window.contentItem(), "openRecentProject") is None
        assert visual_item(window.contentItem(), "locateRecentProject").isEnabled()
        click(window, "removeRecentProject")
        idle(desktop)
        assert not desktop.state["recents"] and not missing.exists()
        assert not engine.load_errors
    finally:
        dispose(engine)
