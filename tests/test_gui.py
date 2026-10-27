"""Offscreen desktop acceptance using tiny projects and deterministic fake work."""

import os
import time
from pathlib import Path
from uuid import uuid4

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6", reason="Install the optional GUI extra to run Qt acceptance")
from PySide6.QtCore import QSettings, Qt, QTimer  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

from splatforge.bootstrap import build_project_service  # noqa: E402
from splatforge_gui.controller import ProjectController  # noqa: E402
from splatforge_gui.preferences import Preferences  # noqa: E402
from splatforge_gui.tasks import TaskExecutor  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QGuiApplication.instance() or QGuiApplication([])


def until(app, predicate, timeout=10000):
    deadline = time.monotonic() + timeout / 1000
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        QTest.qWait(5)
    assert predicate()


def preferences(tmp_path):
    return Preferences(QSettings(str(tmp_path / "ui.ini"), QSettings.Format.IniFormat))


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


def test_gui_typed_intent_save_and_external_refresh(app, tmp_path):
    from splatforge.application.desktop_workflow import reconstruction_request
    from splatforge.core.reconstruction import IncrementalMapperSettings

    root = tmp_path / "Parity"
    build_project_service().create(root, "CLI created")
    controller = ProjectController()
    controller.timer.stop()
    controller.open(root)
    until(app, lambda: controller.overview is not None and not controller.executor.busy)
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


def test_save_drains_readers_and_pauses_polling_until_atomic_write_finishes(app, tmp_path):
    from threading import Event

    from splatforge.bootstrap import build_gui_facade

    root = tmp_path / "Metadata ownership"
    build_project_service().create(root, "Before")
    controller = ProjectController()
    controller.timer.stop()
    controller.open(root)
    until(app, lambda: controller.overview is not None and not controller.executor.busy)
    reading, release, writing, finish_write = Event(), Event(), Event(), Event()
    calls, errors = [], []

    class Facade:
        def __init__(self):
            self.delegate = build_gui_facade()

        def __getattr__(self, name):
            return getattr(self.delegate, name)

        def progress(self, directory):
            calls.append("read")
            reading.set()
            assert release.wait(10)
            return ()

        def save(self, directory, document):
            assert release.is_set()
            calls.append("write")
            writing.set()
            assert finish_write.wait(10)
            return self.delegate.save(directory, document)

    controller.factory = Facade
    controller.error.connect(errors.append)
    controller.poll()
    until(app, reading.is_set)
    controller.edit(controller.overview.document.model_copy(update={"label": "After"}))
    controller.save()
    assert controller.mutating and controller.operation == "save" and not writing.is_set()
    controller.poll()
    controller.refresh()
    assert len(controller.jobs) == 1
    release.set()
    until(app, writing.is_set)
    controller.poll()
    controller.refresh()
    assert calls == ["read", "write"]
    finish_write.set()
    until(app, lambda: not controller.executor.busy and not controller.dirty)
    assert not errors and build_project_service().open(root).label == "After"


def test_failed_create_keeps_previous_project_authority(app, tmp_path):
    root = tmp_path / "Existing"
    build_project_service().create(root, "Existing project")
    controller = ProjectController()
    controller.timer.stop()
    controller.open(root)
    until(app, lambda: controller.overview is not None and not controller.executor.busy)
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


def test_project_adoption_discards_reads_started_while_opening(app, tmp_path):
    from threading import Event

    from splatforge.bootstrap import build_gui_facade

    root, other = tmp_path / "Current", tmp_path / "Other"
    service = build_project_service()
    service.create(root, "Current")
    service.create(other, "Other")
    controller = ProjectController()
    controller.timer.stop()
    controller.open(root)
    until(app, lambda: not controller.executor.busy)
    loading, adopt, reading, release_read = Event(), Event(), Event(), Event()
    completed = []
    controller.completed.connect(lambda name, value: completed.append((name, value)))

    class Facade:
        def overview(self, directory):
            if directory == other:
                loading.set()
                assert adopt.wait(10)
            return build_gui_facade().overview(directory)

    def retained_workspace_read(_):
        reading.set()
        assert release_read.wait(10)
        return "Reply from previous workspace"

    controller.factory = Facade
    try:
        controller.open(other)
        until(app, loading.is_set)
        assert controller.root == root and controller.mutating
        controller.submit("retained_workspace_read", retained_workspace_read)
        until(app, reading.is_set)
        adopt.set()
        until(app, lambda: controller.root == other)
        release_read.set()
        until(app, lambda: not controller.executor.busy)
        assert controller.overview.document.label == "Other"
        assert not any(name == "retained_workspace_read" for name, _ in completed)
    finally:
        adopt.set()
        release_read.set()
        until(app, lambda: not controller.executor.busy)


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
    until(app, lambda: controller.overview is not None and not controller.executor.busy)

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
