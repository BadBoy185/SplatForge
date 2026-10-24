"""Desktop goal pages preserve exact application requests and explicit user choices."""

import os
import time
from uuid import uuid4

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6", reason="Install the optional GUI extra")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QMessageBox
from test_gui import preferences, until  # noqa: E402

from splatforge.bootstrap import build_project_service
from splatforge_gui.controller import ProjectController
from splatforge_gui.widgets.window import MainWindow


@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def test_gui_typed_intent_save_and_external_refresh(app, tmp_path):
    from splatforge.application.desktop_workflow import reconstruction_request
    from splatforge.core.reconstruction import IncrementalMapperSettings

    root = tmp_path / "Parity"
    build_project_service().create(root, "CLI created")
    controller = ProjectController()
    controller.timer.stop()
    controller.open(root)
    until(app, lambda: controller.overview is not None)
    controller.request = reconstruction_request(controller.overview.document).model_copy(
        update={"mapper": IncrementalMapperSettings(num_threads=2)}
    )
    controller.stage_request_as_intent()
    assert controller.dirty
    controller.save()
    until(app, lambda: not controller.dirty and not controller.executor.busy)
    saved = build_project_service().open(root)
    assert saved.settings.mapping.method_id == "mapping.colmap_incremental"
    assert saved.settings.mapping.settings["num_threads"] == 2
    assert reconstruction_request(saved).mapper.num_threads == 2
    build_project_service().save(root, saved.model_copy(update={"label": "CLI changed"}))
    controller.refresh()
    until(app, lambda: controller.overview.document.label == "CLI changed")
    until(app, lambda: not controller.executor.busy)


def test_dataset_plan_is_exact_service_result_and_option_is_forwarded(app, tmp_path):
    from splatforge_gui.widgets.workflow import DatasetPage

    requests = []
    expected = {
        "images": 17,
        "camera_models": ["PINHOLE"],
        "disk_bytes": 123456,
        "cache_hit": True,
        "capability": "positively_verified",
    }

    class Dataset:
        def plan(self, root, **kwargs):
            requests.append(kwargs)
            return expected

    class Facade:
        def service(self, name):
            assert name == "dataset"
            return Dataset()

    controller = ProjectController(factory=Facade)
    controller.timer.stop()
    controller.root = tmp_path
    page = DatasetPage(controller, preferences(tmp_path))
    page.run.addItem("Exact selection", uuid4())
    page.maximum.setValue(512)
    page.execute(True)
    until(app, lambda: not controller.executor.busy)
    assert requests[0]["settings"].max_image_size == 512
    assert all(str(v) in page.details.toPlainText() for v in (17, 123456, "PINHOLE"))
    page.maximum.setValue(1024)
    page.execute(True)
    until(app, lambda: not controller.executor.busy)
    assert requests[-1]["settings"].max_image_size == 1024


def test_training_capability_no_substitution_and_stale_resume_disabled(app, tmp_path):
    from training_helpers import backend_identity

    from splatforge_gui.widgets.workflow import TrainingPage

    controller = ProjectController()
    controller.timer.stop()
    page = TrainingPage(controller, preferences(tmp_path))
    page.strategy.setCurrentIndex(1)
    capability = backend_identity().model_copy(update={"features": ("default",)})
    page.completed("trainer_capability", capability)
    assert page.strategy.currentIndex() == 1
    assert not page.strategy.model().item(1).isEnabled()
    assert "test GPU" in page.details.toPlainText() and "1.5.3" in page.details.toPlainText()
    page.resume_token = "exact-request"
    page.completed(
        "resume_check",
        {"compatible": True, "reason": "exact match", "request_token": "exact-request"},
    )
    assert page.resume.isEnabled()
    page.steps.setValue(page.steps.value() + 1)
    page.completed(
        "resume_check", {"compatible": True, "reason": "obsolete", "request_token": "exact-request"}
    )
    assert not page.resume.isEnabled()
    page.completed("resume_check", {"compatible": False, "reason": "settings/runtime differ"})
    assert "settings/runtime differ" in page.resume.toolTip()


def test_point_preview_paints_and_keyboard_orbit_zoom_reset(app, tmp_path):
    from splatforge.application.desktop import PreviewData
    from splatforge_gui.widgets.point_preview import PointPreview

    widget = PointPreview()
    widget.resize(500, 300)
    widget.set_data(
        PreviewData(
            artifact_id=uuid4(),
            semantic_digest="a" * 64,
            directory=tmp_path,
            metadata={},
            points=((0.0, 0.0, 0.0), (1.0, 2.0, 3.0)),
            cameras=((2.0, 1.0, 0.0),),
        )
    )
    widget.show()
    assert not widget.grab().isNull()
    original = widget.yaw
    QTest.keyClick(widget, Qt.Key.Key_Right)
    assert widget.yaw != original
    QTest.keyClick(widget, Qt.Key.Key_Plus)
    assert widget.zoom > 1
    QTest.keyClick(widget, Qt.Key.Key_R)
    assert widget.zoom == 1
    widget.close()


def test_poll_skips_overlap_and_keeps_timer_responsive(app, tmp_path):
    calls = []

    class Facade:
        def progress(self, root):
            calls.append(root)
            time.sleep(0.1)
            return ()

        def live_metrics(self, root, runs):
            return {}

    controller = ProjectController(factory=Facade)
    controller.timer.stop()
    controller.root = tmp_path
    controller.poll()
    controller.poll()
    assert len(controller.jobs) == 1
    until(app, lambda: not controller.executor.busy)
    assert calls == [tmp_path] and not controller.polling


def test_cleanup_apply_requires_confirmation_and_exact_preview(app, tmp_path, monkeypatch):
    from splatforge.core.cleanup import CleanupPlan
    from splatforge_gui.widgets.inspection import DiagnosticsPage

    controller = ProjectController()
    controller.timer.stop()
    received = []
    monkeypatch.setattr(controller, "cleanup", lambda plan=None: received.append(plan))
    page = DiagnosticsPage(controller, preferences(tmp_path))
    page.plan = CleanupPlan(
        project_id=uuid4(), candidates=(), protected_artifact_ids=(), total_bytes=0
    )
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: QMessageBox.StandardButton.Cancel)
    page.apply_cleanup()
    assert not received
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: QMessageBox.StandardButton.Yes)
    page.apply_cleanup()
    assert received[0].preview_digest == page.plan.preview_digest


def test_recent_bound_and_missing_removal_never_recreates(app, tmp_path):
    ui = preferences(tmp_path)
    for i in range(20):
        ui.remember(tmp_path / f"Missing {i}")
    assert len(ui.recent()) == 15
    window = MainWindow(preferences=ui)
    assert "Unavailable" in window.recent.item(0).text()
    window.recent.setCurrentRow(0)
    window._remove_recent()
    assert len(ui.recent()) == 14
    assert not (tmp_path / "Missing 19").exists()
    window.controller.timer.stop()
    window.close()


def test_json_restore_defaults_and_apply_requires_revalidation(app):
    from PySide6.QtWidgets import QPushButton

    from splatforge.core.training import TrainingSettings
    from splatforge_gui.widgets.common import JsonEditor

    editor = JsonEditor("Training", TrainingSettings(max_steps=7), defaults=TrainingSettings())
    assert editor.validate() and editor.apply.isEnabled()
    editor.text.setPlainText('{"max_steps": -1}')
    assert not editor.apply.isEnabled()
    QTest.mouseClick(editor.findChild(QPushButton, "restoreDefaults"), Qt.MouseButton.LeftButton)
    assert editor.validate() and editor.value == TrainingSettings()


def test_close_during_active_work_offers_only_cancel_or_return(app, tmp_path, monkeypatch):
    labels = []
    window = MainWindow(preferences=preferences(tmp_path))
    window.show()
    window.controller.active = (object(),)

    def inspect_dialog(dialog):
        labels.extend(button.text() for button in dialog.buttons())
        return 0

    monkeypatch.setattr(QMessageBox, "exec", inspect_dialog)
    assert not window.close()
    assert window.isVisible()
    assert set(labels) == {"Cancel run and close", "Return"}
    window.controller.active = ()
    window.controller.timer.stop()
    window.close()


def test_unknown_saved_methods_preserved_without_blocking_other_pages(app, tmp_path):
    root = tmp_path / "Future methods"
    service = build_project_service()
    document = service.create(root, "Preserved")
    envelope = document.settings.mapping.model_copy(
        update={"method_id": "mapping.future", "settings": {"future_value": 99}}
    )
    service.save(
        root,
        document.model_copy(
            update={"settings": document.settings.model_copy(update={"mapping": envelope})}
        ),
    )
    window = MainWindow(preferences=preferences(tmp_path))
    window.open_project(root)
    until(app, lambda: window.controller.overview is not None)
    until(app, lambda: not window.controller.executor.busy)
    assert "unavailable" in window.workflow_pages[0].summary.text()
    assert "Empty" in window.workflow_pages[1].summary.text()
    assert "unavailable" not in window.workflow_pages[1].summary.text()
    assert service.open(root).settings.mapping.settings == {"future_value": 99}
    window.controller.timer.stop()
    window.close()


def test_system_light_dark_use_actual_qt_palettes(app):
    from PySide6.QtGui import QPalette

    from splatforge_gui.preferences import apply_theme

    apply_theme(app, "Light")
    light = app.palette().color(QPalette.ColorRole.Base).lightness()
    apply_theme(app, "Dark")
    dark = app.palette().color(QPalette.ColorRole.Base).lightness()
    assert light > dark
    assert app.palette().color(QPalette.ColorRole.Text).lightness() > dark
    apply_theme(app, "System")


def test_failed_create_keeps_previous_project_authority(app, tmp_path):
    root = tmp_path / "Existing"
    build_project_service().create(root, "Existing project")
    controller = ProjectController()
    controller.timer.stop()
    controller.open(root)
    until(app, lambda: controller.overview is not None)
    other = tmp_path / "Nonempty"
    other.mkdir()
    (other / "keep.txt").write_text("User file", encoding="utf-8")
    errors = []
    controller.error.connect(errors.append)
    controller.create(other, "Refused")
    until(app, lambda: not controller.executor.busy)
    assert errors and controller.root == root
    assert controller.overview.document.label == "Existing project"
    assert (other / "keep.txt").read_text(encoding="utf-8") == "User file"


def test_cancel_and_close_waits_for_application_completion(app, tmp_path):
    from threading import Event

    from splatforge.application.media import MediaOperationCancelled

    root = tmp_path / "Close cancellation"
    build_project_service().create(root, "Close")
    window = MainWindow(preferences=preferences(tmp_path))
    window.open_project(root)
    window.show()
    until(app, lambda: window.controller.overview is not None)
    release, entered = Event(), Event()

    def operation(facade):
        entered.set()
        release.wait(2)
        raise MediaOperationCancelled("Confirmed cooperative cancellation")

    window.controller.submit("ingest", operation, mutation=True)
    until(app, entered.is_set)
    window.pending_close = True
    window._cancel()
    QTest.qWait(20)
    assert window.isVisible() and window.cancel_button.text() == "Cancelling…"
    release.set()
    until(app, lambda: not window.isVisible())


def test_control_tasks_are_not_starved_by_long_work(app):
    from threading import Event

    from splatforge_gui.tasks import TaskExecutor

    executor = TaskExecutor()
    executor.pool.setMaxThreadCount(1)
    release, entered = Event(), Event()
    values = []

    def long_work():
        entered.set()
        release.wait(2)

    executor.result.connect(lambda key, value: values.append(value))
    executor.submit("long work", long_work)
    until(app, entered.is_set)
    executor.submit("control", lambda: "cancel accepted", control=True)
    until(app, lambda: "cancel accepted" in values)
    assert not release.is_set()
    release.set()
    until(app, lambda: not executor.busy)


def test_project_actions_are_keyboard_accessible(app, tmp_path, monkeypatch):
    from PySide6.QtGui import QAction
    from PySide6.QtWidgets import QToolBar

    controller = ProjectController()
    controller.timer.stop()
    saved = []
    monkeypatch.setattr(controller, "save", lambda: saved.append(True))
    window = MainWindow(controller, preferences(tmp_path))
    window.show()
    action = window.findChild(QAction, "saveProjectAction")
    assert action.shortcut().toString() == "Ctrl+S"
    toolbar = window.findChild(QToolBar, "projectToolbar")
    assert toolbar.widgetForAction(action).focusPolicy() == Qt.FocusPolicy.StrongFocus
    window.activateWindow()
    QTest.qWait(20)
    QTest.keyClick(window, Qt.Key.Key_S, Qt.KeyboardModifier.ControlModifier)
    until(app, lambda: bool(saved))
    window.close()


def test_goal_pages_display_terminal_service_outcomes(app, tmp_path):
    from types import SimpleNamespace

    from splatforge_gui.widgets.workflow import DatasetPage, TrainingPage

    controller = ProjectController()
    controller.timer.stop()
    dataset = DatasetPage(controller, preferences(tmp_path))
    training = TrainingPage(controller, preferences(tmp_path))
    dataset.completed("dataset", SimpleNamespace(status="failed"))
    training.completed("training", SimpleNamespace(status="cancelled"))
    assert "Failed" in dataset.summary.text()
    assert "Cancelled" in training.summary.text()


def test_start_without_project_shows_home_before_restoring_page(app, tmp_path):
    ui = preferences(tmp_path)
    ui.set("page", 4)
    root = tmp_path / "Existing project"
    build_project_service().create(root, "Open")
    window = MainWindow(preferences=ui)
    assert window.sidebar.currentRow() == 0
    assert window.stack.currentWidget() == window.home
    window.open_project(root)
    until(app, lambda: window.controller.overview is not None)
    assert window.sidebar.currentRow() == 4
    window.controller.timer.stop()
    until(app, lambda: not window.controller.executor.busy)
    window.close()


def test_cancellation_waits_for_late_application_run_handle(app, tmp_path):
    from threading import Event

    from splatforge.bootstrap import build_gui_facade
    from splatforge.core.progress import PipelineProgressSnapshot

    root = tmp_path / "Late handle"
    build_project_service().create(root, "Late handle")
    announced, cancelled = Event(), Event()
    run_id, requests = uuid4(), []

    class Facade:
        def overview(self, root):
            return build_gui_facade().overview(root)

        def progress(self, root):
            return (
                (PipelineProgressSnapshot(run_id=run_id, status="running", elapsed_seconds=0),)
                if announced.is_set() and not cancelled.is_set()
                else ()
            )

        def live_metrics(self, root, runs):
            return {}

        def cancel(self, root, run):
            requests.append(run)
            cancelled.set()

    controller = ProjectController(factory=Facade)
    controller.timer.stop()
    controller.open(root)
    until(app, lambda: controller.overview is not None)

    def operation(facade):
        announced.wait(2)
        cancelled.wait(2)

    controller.submit("training", operation, mutation=True)
    controller.cancel()
    assert not requests
    announced.set()
    controller.poll()
    until(app, cancelled.is_set)
    until(app, lambda: not controller.executor.busy)
    assert requests == [run_id]


def test_cancel_request_error_can_be_retried_explicitly(app, tmp_path):
    from splatforge.core.progress import PipelineProgressSnapshot

    calls, errors = [], []

    class Facade:
        def cancel(self, root, run):
            calls.append(run)
            if len(calls) == 1:
                raise OSError("Injected cancellation write failure")

    controller = ProjectController(factory=Facade)
    controller.timer.stop()
    controller.root = tmp_path
    controller.active = (
        PipelineProgressSnapshot(run_id=uuid4(), status="running", elapsed_seconds=0),
    )
    controller.error.connect(errors.append)
    controller.cancel()
    until(app, lambda: not controller.executor.busy)
    assert errors and not controller.cancelled_runs
    controller.cancel()
    until(app, lambda: not controller.executor.busy)
    assert len(calls) == 2


def test_non_cancellable_metadata_operation_does_not_promise_cancel(app, tmp_path, monkeypatch):
    labels = []
    window = MainWindow(preferences=preferences(tmp_path))
    window.show()
    window.controller.mutating = True
    window.controller.operation = "cleanup_apply"
    window._progress(())
    assert not window.cancel_button.isEnabled()

    def inspect_dialog(dialog):
        labels.extend(button.text() for button in dialog.buttons())
        return 0

    monkeypatch.setattr(QMessageBox, "exec", inspect_dialog)
    assert not window.close()
    assert labels == ["Return"]
    window.controller.mutating = False
    window.controller.operation = None
    window.controller.timer.stop()
    window.close()


def test_reconstruction_controls_preserve_exact_unrelated_settings(app, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QDialog

    from splatforge.application.desktop_workflow import reconstruction_request
    from splatforge.core.pairs import SequentialSettings
    from splatforge.core.reconstruction import GlobalAcceleratedSettings, IncrementalMapperSettings
    from splatforge.core.sfm_profiles import SfmQualityProfile
    from splatforge_gui.widgets import workflow

    document = build_project_service().create(tmp_path / "Exact settings", "Exact")
    controller = ProjectController()
    controller.timer.stop()
    page = workflow.ReconstructionPage(controller, preferences(tmp_path))
    request = reconstruction_request(document).model_copy(update={
        "pairing": SequentialSettings(forward_neighbors=37),
        "mapper": GlobalAcceleratedSettings(num_threads=3),
    })
    page.completed("request", request)
    page.profile.setCurrentIndex(1)
    assert controller.request.pairing == request.pairing
    assert controller.request.mapper == request.mapper

    exact = request.model_copy(update={
        "mapper": IncrementalMapperSettings(num_threads=7),
        "profile": SfmQualityProfile.HIGH,
    })

    class Editor:
        def __init__(self, *args):
            self.value = exact

        def exec(self):
            return QDialog.DialogCode.Accepted

    monkeypatch.setattr(workflow, "JsonEditor", Editor)
    page.edit_exact()
    assert page.mapper.currentText() == "Incremental"
    assert page.profile.currentData() == exact.profile
    assert page.pairing.currentIndex() == 0
    page.profile.setCurrentIndex(0)
    assert controller.request.mapper == exact.mapper
    assert controller.request.pairing.forward_neighbors == 37
    page.completed("request", request)
    assert page.profile.currentData() is None
