"""Qt Quick acceptance with real engines and deterministic application boundaries."""

import os
from uuid import uuid4

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6", reason="Install the optional GUI extra")

from PySide6.QtCore import QSettings, QUrl  # noqa: E402
from PySide6.QtGui import QGuiApplication, QImage  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

from splatforge.application.desktop import IndexRow, ThumbnailReference  # noqa: E402
from splatforge.core.training import TrainingSettings  # noqa: E402
from splatforge_gui.preferences import Preferences  # noqa: E402
from splatforge_gui.presentation import project_name_error, verification_label  # noqa: E402
from splatforge_gui.qml_app import create_engine  # noqa: E402
from splatforge_gui.qml_bridge import DesktopViewModel  # noqa: E402
from splatforge_gui.qml_dialogs import ExactSettingsModel  # noqa: E402
from splatforge_gui.qml_media import GalleryModel  # noqa: E402
from splatforge_gui.qml_models import PresentationModel  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QGuiApplication.instance() or QGuiApplication([])


@pytest.fixture
def desktop(app, tmp_path):
    prefs = Preferences(QSettings(str(tmp_path / "qml.ini"), QSettings.Format.IniFormat))
    vm = DesktopViewModel(preferences=prefs)
    yield vm
    vm.controller.timer.stop()
    until(lambda: not vm.controller.executor.busy)
    vm.deleteLater()
    app.processEvents()


def until(predicate, timeout=10000):
    import time

    deadline = time.monotonic() + timeout / 1000
    while not predicate() and time.monotonic() < deadline:
        QGuiApplication.processEvents()
        QTest.qWait(5)
    assert predicate()


def visual_item(parent, name):
    """Repeater delegates have visual parents distinct from QObject ownership."""
    if parent.objectName() == name:
        return parent
    return next(
        (found for child in parent.childItems() if (found := visual_item(child, name)) is not None),
        None,
    )


def test_qml_engine_loads_dark_light_and_all_destinations(desktop):
    engine = create_engine(desktop)
    errors = []
    engine.warnings.connect(lambda warnings: errors.extend(warnings))
    assert len(engine.rootObjects()) == 1
    window = engine.rootObjects()[0]
    for theme in ("Dark", "Light", "System"):
        desktop.setTheme(theme)
        for page in range(7):
            desktop.navigate(page)
            QTest.qWait(10)
    assert not errors
    window.close()
    engine.deleteLater()


def test_models_use_uuid_selection_and_qml_roles(app):
    model = PresentationModel()
    a, b = [IndexRow(identity=uuid4(), values={"filename": n}) for n in ("a", "b")]
    model.replace((a, b))
    model.select(str(a.identity))
    model.replace((b, a))
    assert model.selectedId == str(a.identity)
    assert model.data(model.index(1, 0), model.IdentityRole) == str(a.identity)
    assert model.selected["filename"] == "a"
    model.replace((b,))
    assert model.selectedId == "" and model.selected == {}


def test_bridge_mode_theme_and_local_urls(desktop):
    changed = []
    desktop.changed.connect(lambda: changed.append(1))
    desktop.setMode("Advanced")
    desktop.setTheme("Light")
    assert desktop.state["mode"] == "Advanced" and desktop.state["theme"] == "Light"
    assert desktop.preferences.get("theme") == "Light" and changed
    desktop.setTheme("unsupported")
    assert desktop.state["theme"] == "Light"
    path = desktop.local_path(QUrl.fromLocalFile("C:/Scene space/Žluťoučký").toString())
    assert "Žluťoučký" in str(path)
    assert not desktop.state["progress"]["visible"]


def test_exact_settings_validation_rejects_edits_and_returns_paths(app):
    editor, applied = ExactSettingsModel(), []
    editor.applied.connect(lambda kind, value: applied.append(value))
    editor.begin("training", "Training", TrainingSettings(), TrainingSettings())
    assert editor.validate()
    editor.setText('{"max_steps": 0}')
    editor.apply()
    assert not applied and not editor.validate()
    assert editor.state["errors"][0]["path"] == "max_steps"
    editor.restore()
    assert not editor.state["valid"] and editor.validate()
    editor.apply()
    assert applied == [TrainingSettings()]


def test_gallery_reports_loading_ready_and_unavailable_without_blocking(app, tmp_path):
    photo = tmp_path / "tiny.png"
    image = QImage(8, 8, QImage.Format.Format_RGB32)
    image.fill(0)
    assert image.save(str(photo))
    model = GalleryModel()
    model.replace(
        tuple(
            ThumbnailReference(identity=str(i), path=path, caption=path.name)
            for i, path in enumerate((photo, tmp_path / "missing.png"))
        )
    )
    updates = []
    model.dataChanged.connect(lambda first, last, roles: updates.append(roles))
    for row in range(2):
        assert model.data(model.index(row), model.StatusRole) == "Loading preview…"
        assert model.data(model.index(row), model.ImageRole) == ""
    until(lambda: len(model.cache) == 2 and not model.executor.busy)
    assert model.data(model.index(0), model.StatusRole) == "Ready"
    assert model.data(model.index(0), model.ImageRole) == model.image_url("0")
    assert model.data(model.index(1), model.StatusRole) == "Preview unavailable"
    assert model.data(model.index(1), model.ImageRole) == ""
    assert any(model.StatusRole in roles and model.ImageRole in roles for roles in updates)
    model.deleteLater()


def test_source_label_does_not_promote_metadata_reuse_to_content_verification():
    checked = "2026-10-24T20:02:44.649439+00:00"
    reused = verification_label(f"unchanged · metadata_unchanged · {checked}")
    verified = verification_label(f"unchanged · content_verified · {checked}")
    assert "no fresh content hash" in reused and "Content hash verified" not in reused
    assert "Content hash verified" in verified
    assert "UTC" in reused and "649439" not in reused
    unknown = "Full hash at ingest; current verification not recorded"
    assert verification_label(unknown) == unknown


@pytest.mark.parametrize(
    "name",
    [
        "", " ", ".", "..", "../escape", "..\\escape", "a/b", "a\\b", "C:scene",
        'a"b', "a<b", "a>b", "a|b", "a?b", "a*b", "a\x00b", "a\nb", "a\x1fb",
        "scene.", "scene ", "CON", "con.txt", "PRN", "AUX", "NUL.png", "COM1",
        "com9.txt", "LPT1", "lpt9.txt", "COM¹", "LPT².txt", "COM³.txt", "CONIN$",
        "CONOUT$", "CON .txt", "a" * 256, "😀" * 128,
    ],
)
def test_windows_project_name_rejects_invalid_components(name):
    assert project_name_error(name)


@pytest.mark.parametrize(
    "name",
    [
        "Lom Plešivec", "Карпати — Київ", "Русский проект", "Colorado Cabin (2026-10)",
        "COM0", "COM10", "LPT0", "CONifer", ".hidden", "scene..v2", "a" * 255,
        "😀" * 127,
    ],
)
def test_windows_project_name_preserves_valid_components(name):
    assert project_name_error(name) == ""
