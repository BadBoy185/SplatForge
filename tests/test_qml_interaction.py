"""Real Qt Quick controls exercised with tiny published application artifacts."""

import os
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6", reason="Install the optional GUI extra")

from PySide6.QtCore import QEvent, QObject, QPointF, Qt, QTimer  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from test_desktop import publications as publications  # noqa: E402
from test_qml import app as app  # noqa: E402
from test_qml import desktop as desktop
from test_qml import until

from splatforge.adapters.execution_storage import LocalExecutionRepository  # noqa: E402
from splatforge.adapters.fake_stages import LocalFakeStages  # noqa: E402
from splatforge.application.execution import FakeExecutionService  # noqa: E402
from splatforge.bootstrap import build_project_service  # noqa: E402
from splatforge_gui.qml_app import create_engine  # noqa: E402


def click(window, name):
    from test_qml import visual_item

    item = visual_item(window.contentItem(), name)
    assert item is not None and item.isVisible() and item.isEnabled(), name
    center = item.mapToScene(QPointF(item.width() / 2, item.height() / 2)).toPoint()
    QTest.mouseClick(window, Qt.MouseButton.LeftButton, pos=center)
    QTest.qWait(15)


def dispose(engine):
    engine.rootObjects()[0].close()
    engine.deleteLater()
    QGuiApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_populated_pages_dialogs_history_and_preview(desktop, publications):
    root = publications[0]
    desktop.openProject(str(root))
    until(lambda: desktop.controller.overview is not None)
    until(lambda: not desktop.controller.executor.busy)
    desktop.controller.timer.stop()
    engine = create_engine(desktop)
    window = engine.rootObjects()[0]
    errors = []
    engine.warnings.connect(lambda warnings: errors.extend(map(str, warnings)))
    for width, height in ((1280, 720), (1440, 900), (1920, 1080)):
        window.resize(width, height)
        for theme in ("Dark", "Light"):
            desktop.setTheme(theme)
            for mode in ("Guided", "Advanced"):
                desktop.setMode(mode)
                for page in range(7):
                    desktop.navigate(page)
                    QTest.qWait(15)
    click(window, "nav-Home")
    assert desktop.state["page"] == 0
    QTest.keyClick(window, Qt.Key.Key_Comma, Qt.KeyboardModifier.ControlModifier)
    QTest.qWait(30)
    assert window.findChild(QObject, "settingsDialog").property("visible")
    QTest.keyClick(window, Qt.Key.Key_Escape)
    for kind in ("intent", "reconstruction", "dataset", "training"):
        desktop.workflow.editExact(kind)
        QTest.qWait(30)
        assert window.findChild(QObject, "exactDialog").property("visible")
        QTest.keyClick(window, Qt.Key.Key_Escape)
    workflow = desktop._workflow
    validation = workflow.state["choices"]["validation"][1]["value"]
    workflow.chooseInput("validation", validation)
    workflow.action("inspectValidation")
    until(lambda: workflow.state["canSelect"] or bool(desktop.state["error"]), timeout=30000)
    assert workflow.state["canSelect"], desktop.state["error"]
    workflow.action("manualSelection")
    QTest.qWait(30)
    assert window.findChild(QObject, "componentDialog").property("visible")
    assert not desktop.components.state["selected"]
    QTest.keyClick(window, Qt.Key.Key_Escape)
    desktop.navigate(5)
    for kind in ("training.gaussian_scene", "mapping.reconstruction_set"):
        row = next(r for r in desktop._artifacts.rows if r.values["artifact_type"] == kind)
        desktop.inspection.inspectArtifact(str(row.identity))
        until(lambda: desktop.inspection.state["hasPreview"])
        assert desktop.inspection.state["pointCount"] > 0
        assert desktop.inspection.state["pointCount"] <= 20000
        assert desktop.inspection.state["cameraCount"] <= 2000
    desktop.inspection.action("copyPath")
    assert QGuiApplication.clipboard().text() == desktop.inspection.state["path"]
    desktop.inspection.inspectRun(str(desktop._runs.rows[0].identity))
    until(lambda: bool(desktop.inspection.state["details"]))
    assert not errors, "\n".join(errors)
    until(lambda: not desktop.controller.executor.busy)
    dispose(engine)


def test_external_operation_remains_responsive_until_confirmed_cancel(desktop, tmp_path):
    entered = Event()

    class LongStage(LocalFakeStages):
        def execute_sequence(self, workspace, *, start, settings, control):
            entered.set()
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                time.sleep(0.01)
                control.checkpoint()
            super().execute_sequence(workspace, start=start, settings=settings, control=control)

    root = tmp_path / "External fake run"
    build_project_service().create(root, "Active")
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(
            FakeExecutionService(LocalExecutionRepository(), LongStage()).run,
            root,
            start=0,
            count=3,
            factor=2,
        )
        until(entered.is_set)
        desktop.openProject(str(root))
        until(lambda: bool(desktop.controller.active))
        engine = create_engine(desktop)
        window = engine.rootObjects()[0]
        ticks = []
        timer = QTimer()
        timer.setInterval(5)
        timer.timeout.connect(lambda: ticks.append(1))
        timer.start()
        click(window, "nav-Diagnostics")
        QTest.qWait(50)
        assert len(ticks) >= 2 and not future.done()
        click(window, "cancelOperation")
        assert desktop.state["progress"]["cancelling"]
        until(future.done)
        assert future.result().status == "cancelled"
        desktop.controller.poll()
        until(lambda: not desktop.controller.active and not desktop.controller.executor.busy)
        assert not desktop.state["progress"]["visible"]
        timer.stop()
        dispose(engine)


def test_doctor_ignores_obsolete_machine_evidence(desktop, monkeypatch):
    monkeypatch.setattr(desktop.controller, "doctor", lambda *args: None)
    desktop.inspection.action("doctor")
    desktop.setMachine("colmap", "C:/Other/colmap.exe")
    desktop.inspection.completed(
        "doctor", {"colmap_learned_gpu": {"gpu": {"devices": [{"name": "Obsolete device"}]}}}
    )
    assert all(row["status"] == "Not checked" for row in desktop.inspection.state["health"])
