"""Offscreen desktop acceptance using tiny projects and deterministic fake work."""

import os
import time
from pathlib import Path
from uuid import uuid4

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6", reason="Install the optional GUI extra to run Qt acceptance")
from PySide6.QtCore import QSettings, Qt, QTimer  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QTableView  # noqa: E402

from splatforge.application.desktop import IndexRow  # noqa: E402
from splatforge.bootstrap import build_project_service  # noqa: E402
from splatforge_gui.controller import ProjectController  # noqa: E402
from splatforge_gui.models import SOURCE_COLUMNS, RecordModel  # noqa: E402
from splatforge_gui.preferences import Preferences  # noqa: E402
from splatforge_gui.tasks import TaskExecutor  # noqa: E402
from splatforge_gui.widgets.common import JsonEditor  # noqa: E402
from splatforge_gui.widgets.window import MainWindow  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def until(app, predicate, timeout=10000):
    deadline = time.monotonic() + timeout / 1000
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        QTest.qWait(5)
    assert predicate()


def preferences(tmp_path):
    return Preferences(QSettings(str(tmp_path / "ui.ini"), QSettings.Format.IniFormat))


def test_main_window_create_reopen_and_cli_parity(app, tmp_path):
    window = MainWindow(preferences=preferences(tmp_path))
    errors = []
    window.controller.error.connect(errors.append)
    window.show()
    assert window.controller.overview is None
    root = tmp_path / "Scene with spaces Žluťoučký"
    window.controller.create(root, "Tiny scene")
    until(app, lambda: window.controller.overview is not None)
    assert not errors
    assert window.controller.overview.document.label == "Tiny scene"
    assert window.source_model.rowCount() == 0
    document = window.controller.overview.document.model_copy(update={"label": "Edited"})
    window.controller.edit(document)
    window.controller.save()
    until(app, lambda: not window.controller.dirty and not window.controller.mutating)
    assert build_project_service().open(root).label == "Edited"
    window.controller.timer.stop()
    until(app, lambda: not window.controller.executor.busy)
    window.close()
    second = MainWindow(preferences=preferences(tmp_path))
    second.open_project(root)
    until(app, lambda: second.controller.overview is not None)
    assert second.controller.overview.document == build_project_service().open(root)
    second.controller.timer.stop()
    until(app, lambda: not second.controller.executor.busy)
    second.close()


def test_task_executor_responsive_error_and_fresh_runnables(app):
    executor, values, errors, ticks = TaskExecutor(), [], [], []
    executor.result.connect(lambda key, value: values.append(value))
    executor.error.connect(lambda key, value: errors.append(value))
    timer = QTimer()
    timer.setInterval(10)
    timer.timeout.connect(lambda: ticks.append(1))
    timer.start()
    executor.submit("fake long stage", lambda: (time.sleep(0.2), Path("typed result"))[1])
    until(app, lambda: not executor.busy)
    assert len(ticks) >= 5 and values == [Path("typed result")]
    executor.submit("failure", lambda: 1 / 0)
    until(app, lambda: not executor.busy)
    assert errors[0].category == "ZeroDivisionError"
    assert "Traceback" in errors[0].traceback
    timer.stop()


def test_source_model_stable_selection(app):
    model, table = RecordModel(SOURCE_COLUMNS), QTableView()
    table.setModel(model)
    a, b = (IndexRow(identity=uuid4(), values={"filename": name}) for name in ("a", "b"))
    assert model.rowCount() == 0
    model.replace((a,), table)
    table.setCurrentIndex(model.index(0, 0))
    model.replace((b, a), table)
    assert table.currentIndex().data(Qt.ItemDataRole.UserRole) == a.identity
    assert model.rowCount() == 2


def test_qsettings_allowlist(app, tmp_path):
    ui = preferences(tmp_path)
    ui.set("theme", "Dark")
    ui.set("geometry", b"geometry")
    ui.set("colmap", "C:/Tools/COLMAP.exe")
    ui.remember(tmp_path / "Unavailable scene")
    other = preferences(tmp_path)
    assert other.get("theme") == "Dark" and len(other.recent()) == 1
    with pytest.raises(KeyError):
        ui.set("max_steps", 2)
    assert "max_steps" not in ui.settings.allKeys()


def test_json_editor_validates_exact_paths(app):
    from splatforge.core.training import TrainingSettings

    editor = JsonEditor("Training", TrainingSettings(), defaults=TrainingSettings())
    assert editor.validate()
    editor.text.setPlainText('{"max_steps": 0}')
    assert not editor.validate() and "max_steps" in editor.errors.text()
    editor.text.setPlainText('{"strategy": {"strategy": "unknown"}}')
    assert not editor.validate() and "strategy" in editor.errors.text()
    editor.text.setPlainText('{"hidden": true}')
    assert not editor.validate() and "hidden" in editor.errors.text()
    editor.text.setPlainText('{"strategy": {"strategy": "mcmc", "cap_max": 12}}')
    assert editor.validate() and editor.value.strategy.cap_max == 12
    editor.text.setPlainText("{/* comment */}")
    assert not editor.validate()


def test_folder_inventory_is_bounded_deterministic_and_explicit(tmp_path):
    from splatforge.application.desktop import enumerate_media

    for name in ("B.JPG", "a.png", "unsupported.txt"):
        (tmp_path / name).touch()
    (tmp_path / "subdirectory").mkdir()
    inventory = enumerate_media(tmp_path)
    assert [p.name for p in inventory.supported] == ["a.png", "B.JPG"]
    assert inventory.ignored == 2
    with pytest.raises(ValueError, match="folder_limit"):
        enumerate_media(tmp_path, limit=2)


def test_thumbnails_are_scaled_lazy_and_bounded(app, tmp_path):
    from PIL import Image

    from splatforge.application.desktop import ThumbnailReference
    from splatforge_gui.thumbnails import ThumbnailModel, decode_thumbnail

    path = tmp_path / "image.png"
    Image.new("RGB", (4096, 2048)).save(path)
    image = decode_thumbnail(path)
    assert image.width() == 192 and image.height() == 96
    model = ThumbnailModel()
    reference = ThumbnailReference(identity="digest:view", path=path, caption="Tiny")
    model.replace((reference,))
    assert not model.cache
    assert model.data(model.index(0), Qt.ItemDataRole.DecorationRole) is None
    until(app, lambda: bool(model.cache))
    assert model.data(model.index(0), Qt.ItemDataRole.DecorationRole) is not None
    until(app, lambda: not model.executor.busy)
    for i in range(200):
        model._store(str(i), image)
    assert len(model.cache) == 128
    path.write_bytes(b"corrupt")
    with pytest.raises(ValueError):
        decode_thumbnail(path)


def test_saved_default_reconstruction_resolves_without_changing_methods(app, tmp_path):
    from splatforge.application.desktop_workflow import reconstruction_request

    document = build_project_service().create(tmp_path / "project", "Test")
    request = reconstruction_request(document)
    assert request.mapper.method_id == document.settings.mapping.method_id
    assert request.features.extractor.method_id == document.settings.feature_extraction.method_id
    assert request.features.matcher.method_id == document.settings.feature_matching.method_id


def test_m9_ambiguous_multiple_and_exact_override_ui(app, monkeypatch):
    from PySide6.QtWidgets import QDialogButtonBox, QMessageBox
    from validation_helpers import measured

    from splatforge.core.reconstruction_selection import (
        DominanceSelectionPolicy,
        recommend_components,
    )
    from splatforge.core.validation_policy import ReconstructionValidationPolicy, evaluate_policy
    from splatforge_gui.widgets.workflow import ComponentDialog

    _, _, _, metrics = measured([(i * 2 + 1, 10) for i in range(6)], [[0, 1, 2], [3, 4, 5]])
    report = evaluate_policy(metrics, ReconstructionValidationPolicy())
    assert recommend_components(metrics, report, DominanceSelectionPolicy()).status == "ambiguous"
    dialog = ComponentDialog(report, metrics, advanced=True)
    assert not dialog.list.selectedItems()
    dialog.list.item(0).setSelected(True)
    dialog.list.item(1).setSelected(True)
    dialog.update_state()
    assert len(dialog.request()[0]) == 2
    assert "2 separate datasets/scenes" in dialog.notice.text()
    assert dialog.buttons.button(QDialogButtonBox.StandardButton.Ok).isEnabled()
    failed = evaluate_policy(
        metrics, ReconstructionValidationPolicy(policy_id="custom_v1", minimum_viable_cameras=4)
    )
    override = ComponentDialog(failed, metrics, advanced=True)
    override.list.item(0).setSelected(True)
    override.update_state()
    assert not override.buttons.button(QDialogButtonBox.StandardButton.Ok).isEnabled()
    component = override.request()[0][0]
    for i in range(override.issues.count()):
        item = override.issues.item(i)
        issue = item.data(Qt.ItemDataRole.UserRole)
        if issue.scope.component_id is None or issue.scope.component_id == component:
            item.setCheckState(Qt.CheckState.Checked)
    assert not override.buttons.button(QDialogButtonBox.StandardButton.Ok).isEnabled()
    override.reason.setText("Reviewed these exact failures")
    assert override.buttons.button(QDialogButtonBox.StandardButton.Ok).isEnabled()
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: QMessageBox.StandardButton.Cancel)
    override.confirm()
    assert override.result() != override.DialogCode.Accepted
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: QMessageBox.StandardButton.Yes)
    override.confirm()
    assert override.result() == override.DialogCode.Accepted
    assert override.request()[2] == "Reviewed these exact failures"


def test_progress_semantics_determinate_phase_cached_failed(app):
    from splatforge.core.progress import (
        PipelineProgressSnapshot,
        ProgressMode,
        ProgressStatus,
        StageProgressSnapshot,
        WorkDescription,
        WorkUnit,
    )
    from splatforge_gui.widgets.common import ProgressPanel

    panel = ProgressPanel()
    work = WorkDescription(
        stage_id="training",
        node_id="training",
        method_id="gsplat.default",
        work_model_id="training.steps_v1",
        unit=WorkUnit.STEPS,
        total=10,
    )
    stage = StageProgressSnapshot(
        work=work,
        status=ProgressStatus.RUNNING,
        completed=4,
        fraction=0.4,
        throughput_unit=WorkUnit.STEPS,
    )
    run = PipelineProgressSnapshot(
        run_id=uuid4(), status="running", elapsed_seconds=1, stages=(stage,)
    )
    panel.update_progress((run,))
    assert panel.bar.maximum() == 1000 and panel.bar.value() == 400
    phase = stage.model_copy(
        update={
            "work": work.model_copy(
                update={"mode": ProgressMode.PHASE, "unit": WorkUnit.WORK, "total": 1}
            ),
            "fraction": None,
        }
    )
    panel.update_progress((run.model_copy(update={"stages": (phase,)}),))
    assert panel.bar.maximum() == 0
    cached = stage.model_copy(update={"status": "cached", "fraction": 1.0})
    panel.update_progress((run.model_copy(update={"status": "succeeded", "stages": (cached,)}),))
    assert panel.bar.value() == 1000
    failed = stage.model_copy(update={"status": "failed"})
    panel.update_progress((run.model_copy(update={"status": "failed", "stages": (failed,)}),))
    assert "Failed" in panel.label.text() and panel.bar.maximum() == 0


def test_external_fake_run_responsiveness_and_cancel_via_application(app, tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    from splatforge.adapters.execution_storage import LocalExecutionRepository
    from splatforge.adapters.fake_stages import LocalFakeStages
    from splatforge.application.execution import FakeExecutionService

    entered = Event()

    class LongStage(LocalFakeStages):
        def execute_sequence(self, workspace, *, start, settings, control):
            entered.set()
            deadline = time.monotonic() + 10
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
        until(app, entered.is_set)
        controller = ProjectController()
        controller.timer.stop()
        window = MainWindow(controller, preferences(tmp_path))
        window.show()
        window.open_project(root)
        until(app, lambda: bool(controller.active))
        run_id = controller.active[0].run_id
        assert str(run_id) in window.progress.label.text()
        assert "Running" in window.progress.label.text()
        ticks = []
        timer = QTimer()
        timer.setInterval(5)
        timer.timeout.connect(lambda: ticks.append(1))
        timer.start()
        QTest.mouseClick(window.sidebar.viewport(), Qt.MouseButton.LeftButton)
        QTest.qWait(50)
        app.processEvents()
        assert len(ticks) >= 2 and not future.done()
        QTest.mouseClick(window.cancel_button, Qt.MouseButton.LeftButton)
        assert window.cancel_button.text() == "Cancelling…"
        until(app, future.done)
        assert future.result().status == "cancelled"
        controller.poll()
        until(app, lambda: not controller.active and not controller.executor.busy)
        timer.stop()
        window.close()


def test_recoverable_publication_detected_and_recovered(app, tmp_path):
    from splatforge.adapters.execution_storage import ExecutionFaultHooks, LocalExecutionRepository
    from splatforge.adapters.fake_stages import LocalFakeStages
    from splatforge.application.execution import FakeExecutionService, PublicationUnresolvedError
    from splatforge.bootstrap import build_gui_facade

    root = tmp_path / "Recovery"
    build_project_service().create(root, "Interrupted")

    def fail(path):
        raise OSError("Injected interruption")

    repository = LocalExecutionRepository(fault_hooks=ExecutionFaultHooks(after_artifact_move=fail))
    with pytest.raises(PublicationUnresolvedError):
        FakeExecutionService(repository, LocalFakeStages()).run(root, start=0, count=2, factor=2)
    controller = ProjectController()
    controller.timer.stop()
    window = MainWindow(controller, preferences(tmp_path))
    window.open_project(root)
    until(app, lambda: controller.overview is not None)
    diagnostics = window.workflow_pages[4]
    assert "Recovery required" in diagnostics.summary.text()
    run = controller.overview.index.runs[0].identity
    results = []
    controller.completed.connect(lambda name, value: results.append(name))
    controller.recover_run(run)
    until(app, lambda: "recovery" in results)
    until(app, lambda: not controller.executor.busy)
    assert not build_gui_facade().progress(root)
    window.close()
