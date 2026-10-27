"""Behavioral parity for the QML bridge; backend fixtures remain unchanged."""

import json
import os
from threading import Event
from uuid import uuid4

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6", reason="Install the optional GUI extra")

from PySide6.QtCore import QEvent, Qt  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from test_qml import app as app  # noqa: E402
from test_qml import desktop as desktop
from test_qml import until

from splatforge.application.desktop import PreviewData  # noqa: E402
from splatforge.bootstrap import build_project_service  # noqa: E402
from splatforge.core.cleanup import CleanupPlan  # noqa: E402
from splatforge.core.progress import (  # noqa: E402
    PipelineProgressSnapshot,
    ProgressStatus,
    StageProgressSnapshot,
    WorkDescription,
    WorkUnit,
)
from splatforge_gui.qml_app import create_engine  # noqa: E402


def open_project(desktop, tmp_path):
    root = tmp_path / "Scene with spaces Žluťoučký" / "Tiny scene"
    desktop.createProject(str(root.parent), root.name)
    until(lambda: desktop.controller.overview is not None)
    until(lambda: not desktop.controller.executor.busy)
    return root


def test_create_save_external_refresh_and_reopen(desktop, tmp_path):
    root = open_project(desktop, tmp_path)
    assert desktop.state["project"]["name"] == "Tiny scene"
    assert desktop.sources.count == 0
    doc = desktop.controller.overview.document.model_copy(update={"label": "GUI edited"})
    desktop.controller.edit(doc)
    desktop.save()
    until(lambda: not desktop.controller.executor.busy)
    assert not desktop.controller.dirty, desktop.state["error"]
    service = build_project_service()
    assert service.open(root).label == "GUI edited"
    service.save(root, service.open(root).model_copy(update={"label": "CLI edited"}))
    desktop.refresh()
    until(lambda: desktop.state["project"]["name"] == "CLI edited")
    desktop.openProject(str(root))
    until(lambda: desktop.controller.overview is not None)
    assert desktop.controller.overview.document == service.open(root)


def test_destination_preview_is_pure_and_create_round_trips_with_cli(desktop, tmp_path):
    from typer.testing import CliRunner

    from splatforge.cli.app import app as cli

    parent, name = tmp_path / "Projects with spaces", "Lom Plešivec — Київ (1)"
    preview = desktop.projectDestination(str(parent), name)
    root = parent / name
    assert preview == {"path": str(root), "error": "", "valid": True}
    assert not parent.exists()
    assert desktop.projectDestination(str(parent), "Other")["path"] == str(parent / "Other")
    assert desktop.projectDestination(str(tmp_path), name)["path"] == str(tmp_path / name)
    assert not desktop.projectDestination("relative", name)["valid"]
    assert not desktop.projectDestination("https://example.test", name)["valid"]
    assert not desktop.projectDestination(str(parent), "CON.txt")["valid"]
    assert not parent.exists()
    desktop.preferences.set("page", 5)
    desktop.createProject(str(parent), name)
    until(lambda: not desktop.controller.executor.busy)
    assert desktop.state["hasProject"] and desktop.state["page"] == 1
    assert desktop.controller.root == root
    document = desktop.controller.overview.document
    result = CliRunner().invoke(cli, ["project", "show", str(root)])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == document.model_dump(mode="json")
    assert desktop.state["project"]["id"] == str(document.project_id)
    assert desktop.sources.count == 0 and not desktop.controller.overview.index.runs
    assert not desktop.controller.overview.index.artifacts
    assert desktop.preferences.recent() == [str(root)]
    assert desktop.state["recents"][0]["projectId"] == str(document.project_id)
    assert desktop.state["recents"][0]["summary"] == "Available"


def test_gui_opens_cli_project_and_reopens_gui_identity(app, desktop, tmp_path):
    from PySide6.QtCore import QSettings
    from typer.testing import CliRunner

    from splatforge.cli.app import app as cli
    from splatforge_gui.preferences import Preferences
    from splatforge_gui.qml_bridge import DesktopViewModel

    root = open_project(desktop, tmp_path)
    identity = desktop.controller.overview.document.project_id
    # A fresh desktop session reads only persisted project state.
    desktop.controller.timer.stop()
    reopened = DesktopViewModel(
        preferences=Preferences(QSettings(str(tmp_path / "reopen.ini"), QSettings.Format.IniFormat))
    )
    reopened.controller.timer.stop()
    try:
        reopened.openProject(str(root))
        until(lambda: not reopened.controller.executor.busy)
        assert reopened.controller.overview.document.project_id == identity
        assert reopened.state["project"]["name"] == root.name
        cli_root = tmp_path / "CLI project"
        result = CliRunner().invoke(
            cli, ["project", "create", str(cli_root), "--label", "CLI name"]
        )
        assert result.exit_code == 0, result.output
        reopened.openProject(str(cli_root))
        until(lambda: not reopened.controller.executor.busy)
        assert reopened.controller.overview.document.model_dump(mode="json") == json.loads(
            result.output
        )
        assert reopened.state["project"]["name"] == "CLI name"
        assert not reopened.controller.overview.index.runs and not reopened.controller.active
    finally:
        until(lambda: not reopened.controller.executor.busy)
        reopened.deleteLater()
        app.processEvents()


@pytest.mark.parametrize("kind", ["nonempty", "existing_project", "file", "permission", "readback"])
def test_failed_create_preserves_workspace_and_recents(desktop, tmp_path, kind):
    from splatforge.bootstrap import build_gui_facade

    root = open_project(desktop, tmp_path)
    desktop.navigate(2)
    previous = desktop.controller.overview
    recents = desktop.preferences.recent()
    target = tmp_path / "Refused"
    if kind == "nonempty":
        target.mkdir()
        (target / "keep.txt").write_bytes(b"keep")
    elif kind == "file":
        target.write_bytes(b"keep")
    elif kind == "existing_project":
        build_project_service().create(target, "Existing")
    before = (target / "project.json").read_bytes() if kind == "existing_project" else None

    class Facade:
        def __init__(self):
            self.delegate = build_gui_facade()

        def __getattr__(self, name):
            return getattr(self.delegate, name)

        def create(self, directory, label):
            if kind == "permission":
                raise PermissionError("Access denied for selected location")
            return self.delegate.create(directory, label)

        def overview(self, directory):
            if kind == "readback" and directory == target:
                raise OSError("Cannot read created project state")
            return self.delegate.overview(directory)

    desktop.controller.factory = Facade
    desktop.createProject(str(tmp_path), target.name)
    until(lambda: not desktop.controller.executor.busy)
    assert desktop.controller.root == root
    assert desktop.controller.overview.document == previous.document
    assert desktop.state["page"] == 2 and desktop.preferences.recent() == recents
    assert desktop.state["error"]["message"] and "Traceback" in desktop.state["error"]["details"]
    if kind == "existing_project":
        assert (target / "project.json").read_bytes() == before
    elif kind == "nonempty":
        assert (target / "keep.txt").read_bytes() == b"keep"
    elif kind == "file":
        assert target.read_bytes() == b"keep"


@pytest.mark.parametrize("kind", ["missing", "corrupt", "unsupported", "corrupt_state"])
def test_failed_open_does_not_publish_partial_workspace(desktop, tmp_path, kind):
    root = open_project(desktop, tmp_path)
    previous = desktop.controller.overview
    recents = desktop.preferences.recent()
    target = tmp_path / "Bad project"
    if kind != "missing":
        build_project_service().create(target, "Bad")
        if kind == "corrupt":
            (target / "project.json").write_text("{broken", encoding="utf-8")
        elif kind == "unsupported":
            raw = json.loads((target / "project.json").read_text(encoding="utf-8"))
            raw["project_format_version"] = 999
            (target / "project.json").write_text(json.dumps(raw), encoding="utf-8")
        else:
            (target / "state.sqlite").write_bytes(b"broken database")
    desktop.openProject(str(target))
    until(lambda: not desktop.controller.executor.busy)
    assert desktop.controller.root == root
    assert desktop.controller.overview.document == previous.document
    assert desktop.preferences.recent() == recents
    assert desktop.state["error"]["message"] and desktop.state["error"]["details"]


def test_create_dialog_preview_validation_cancel_and_sources(desktop, tmp_path):
    from PySide6.QtCore import QObject
    from test_qml import visual_item
    from test_qml_interaction import click, dispose

    engine = create_engine(desktop)
    window = engine.rootObjects()[0]
    try:
        assert not visual_item(window.contentItem(), "nav-Sources").isVisible()
        click(window, "newProject")
        name = window.findChild(QObject, "projectName")
        location = window.findChild(QObject, "projectLocation")
        preview = window.findChild(QObject, "projectDestination")
        create = window.findChild(QObject, "confirmCreateProject")
        location.setProperty("text", str(tmp_path / "Uncreated parent"))
        name.setProperty("text", "Lom Plešivec")
        QTest.qWait(10)
        assert preview.property("text") == str(tmp_path / "Uncreated parent" / "Lom Plešivec")
        location.setProperty("text", str(tmp_path))
        name.setProperty("text", "CON.txt")
        QTest.qWait(10)
        assert not create.property("enabled")
        assert "reserved" in window.findChild(QObject, "projectNameError").property("text")
        name.setProperty("text", "Lom Plešivec (1)")
        QTest.qWait(10)
        root = tmp_path / "Lom Plešivec (1)"
        assert preview.property("text") == str(root) and create.property("enabled")
        assert not root.exists() and not (tmp_path / "Uncreated parent").exists()
        click(window, "cancelCreateProject")
        assert not root.exists() and not desktop.state["hasProject"]
        assert not desktop.preferences.recent()
        click(window, "newProject")
        click(window, "confirmCreateProject")
        until(lambda: not desktop.controller.executor.busy)
        assert desktop.state["page"] == 1 and desktop.controller.root == root
        assert visual_item(window.contentItem(), "sourcesEmptyState").isVisible()
        assert visual_item(window.contentItem(), "addPhotos").isEnabled()
        assert visual_item(window.contentItem(), "addVideo").isEnabled()
        assert not engine.load_errors
    finally:
        until(lambda: not desktop.controller.executor.busy)
        dispose(engine)


def test_recent_projects_use_actual_names_and_remove_missing(desktop, tmp_path):
    root = open_project(desktop, tmp_path)
    until(lambda: bool(desktop.state["recents"]))
    assert desktop.state["recents"][0]["name"] == "Tiny scene"
    missing = tmp_path / "Unavailable"
    desktop.preferences.remember(missing)
    desktop.refresh_recents()
    until(lambda: len(desktop.state["recents"]) == 2)
    assert not desktop.state["recents"][0]["available"]
    desktop.removeRecent(str(missing))
    until(lambda: len(desktop.state["recents"]) == 1)
    assert not missing.exists() and root.exists()


def test_unsaved_switch_save_discard_cancel(desktop, tmp_path):
    root = open_project(desktop, tmp_path)
    other = tmp_path / "Second"
    build_project_service().create(other, "Second")
    events = []
    desktop.dialogRequested.connect(events.append)
    desktop.controller.edit(
        desktop.controller.overview.document.model_copy(update={"label": "Draft"})
    )
    desktop.openProject(str(other))
    assert events[-1] == "unsaved" and desktop.controller.root == root
    desktop.resolveUnsaved("cancel")
    assert desktop.controller.dirty and desktop.controller.root == root
    desktop.openProject(str(other))
    desktop.resolveUnsaved("save")
    until(lambda: desktop.controller.overview is not None and desktop.controller.root == other)
    assert build_project_service().open(root).label == "Draft"
    desktop.controller.edit(
        desktop.controller.overview.document.model_copy(update={"label": "Discard"})
    )
    desktop.openProject(str(root))
    desktop.resolveUnsaved("discard")
    until(lambda: desktop.controller.root == root and desktop.controller.overview is not None)
    assert build_project_service().open(other).label == "Second"


@pytest.mark.parametrize("choice", ["save", "discard", "cancel"])
def test_create_uses_existing_unsaved_lifecycle(desktop, tmp_path, choice):
    root = open_project(desktop, tmp_path)
    document = desktop.controller.overview.document
    desktop.controller.edit(document.model_copy(update={"label": "Draft"}))
    dialogs = []
    desktop.dialogRequested.connect(dialogs.append)
    target = tmp_path / "New project"
    desktop.createProject(str(tmp_path), target.name)
    assert dialogs == ["unsaved"] and not target.exists()
    desktop.resolveUnsaved(choice)
    if choice != "cancel":
        until(lambda: desktop.controller.root == target)
    until(lambda: not desktop.controller.executor.busy)
    if choice == "cancel":
        assert desktop.controller.root == root and desktop.controller.dirty
        assert not target.exists()
    else:
        assert desktop.controller.root == target and desktop.state["page"] == 1
        assert build_project_service().open(root).label == (
            "Draft" if choice == "save" else document.label
        )


def test_create_and_open_respect_busy_ownership(desktop, tmp_path):
    root = open_project(desktop, tmp_path)
    active = PipelineProgressSnapshot(run_id=uuid4(), status="running", elapsed_seconds=0)
    for field, value in (("mutating", True), ("active", (active,))):
        setattr(desktop.controller, field, value)
        target = tmp_path / "Blocked"
        desktop.createProject(str(tmp_path), target.name)
        desktop.openProject(str(target))
        assert desktop.controller.root == root and not target.exists()
        assert "active work" in desktop.state["error"]["message"]
        setattr(desktop.controller, field, False if field == "mutating" else ())


def test_reconstruction_choices_preserve_unrelated_exact_settings(desktop, tmp_path):
    from splatforge.core.pairs import SequentialSettings
    from splatforge.core.reconstruction import GlobalAcceleratedSettings, IncrementalMapperSettings
    from splatforge.core.sfm_profiles import SfmQualityProfile

    open_project(desktop, tmp_path)
    work = desktop._workflow
    request = desktop.controller.request.model_copy(
        update={
            "pairing": SequentialSettings(forward_neighbors=37),
            "mapper": GlobalAcceleratedSettings(num_threads=3),
        }
    )
    work.apply_exact("reconstruction", request)
    work.setReconstruction("profile", SfmQualityProfile.HIGH.value)
    assert desktop.controller.request.mapper == request.mapper
    assert desktop.controller.request.pairing == request.pairing
    exact = request.model_copy(update={"mapper": IncrementalMapperSettings(num_threads=7)})
    work.apply_exact("reconstruction", exact)
    assert work.state["mapper"] == "incremental"
    work.setReconstruction("profile", "")
    assert desktop.controller.request.mapper.num_threads == 7
    assert desktop.controller.request.pairing.forward_neighbors == 37


def test_unknown_methods_preserved_and_unrelated_targets_open(desktop, tmp_path):
    root = open_project(desktop, tmp_path)
    service = build_project_service()
    doc = service.open(root)
    envelope = doc.settings.mapping.model_copy(
        update={"method_id": "mapping.future", "settings": {"future": 99}}
    )
    service.save(
        root,
        doc.model_copy(update={"settings": doc.settings.model_copy(update={"mapping": envelope})}),
    )
    desktop.refresh()
    until(lambda: "unavailable" in desktop._workflow.state["messages"].get("reconstruction", ""))
    assert not desktop._workflow.state["requestAvailable"]
    assert desktop._workflow.state["choices"]["selection"]
    assert service.open(root).settings.mapping.settings == {"future": 99}


def test_dataset_routes_exact_settings_and_rejects_stale_plan(desktop, tmp_path, monkeypatch):
    open_project(desktop, tmp_path)
    work, calls = desktop._workflow, []
    run = str(uuid4())
    work._choices["selection"] = [{"label": "Selection", "value": run}]
    work.chooseInput("selection", run)
    work.setDatasetMaximum(512)
    monkeypatch.setattr(desktop.controller, "dataset", lambda *args: calls.append(args))
    work.action("planDataset")
    assert calls[0][0] == UUID(run) and calls[0][1].max_image_size == 512 and calls[0][-1]
    work.completed("dataset_plan", {"runnable": True, "images": 17, "disk_bytes": 123456})
    assert work.state["plans"]["dataset"]["images"] == 17
    work.action("planDataset")
    work.setDatasetMaximum(1024)
    work.completed("dataset_plan", {"runnable": True, "images": 17})
    assert "dataset" not in work.state["plans"]
    work.action("prepareDataset")
    assert calls[-1][1].max_image_size == 1024 and not calls[-1][-1]


def test_training_capability_and_resume_tokens(desktop, tmp_path, monkeypatch):
    from training_helpers import backend_identity

    open_project(desktop, tmp_path)
    work, calls = desktop._workflow, []
    desktop.setMachine("trainer_python", "C:/Trainer/python.exe")
    work.setTraining("strategy", "mcmc")
    monkeypatch.setattr(desktop.controller, "trainer_capability", lambda *args: None)
    work.action("probeTrainer")
    work.completed(
        "trainer_capability", backend_identity().model_copy(update={"features": ("default",)})
    )
    assert work.state["strategy"] == "mcmc"
    assert not work.state["strategyChoices"][1]["supported"]
    for key in ("dataset", "checkpoint"):
        run = str(uuid4())
        work._choices[key] = [{"label": key, "value": run}]
        work.chooseInput(key, run)
    monkeypatch.setattr(desktop.controller, "resume_check", lambda *args: calls.append(args))
    work.action("checkResume")
    token = calls[-1][-1]
    work.completed(
        "resume_check", {"compatible": True, "reason": "Exact match", "request_token": token}
    )
    assert work.state["resumeReady"]
    work.setTraining("max_steps", "12")
    work.completed(
        "resume_check", {"compatible": True, "reason": "Obsolete", "request_token": token}
    )
    assert not work.state["resumeReady"]
    errors = []
    desktop.controller.error.connect(errors.append)
    work.action("resumeTraining")
    assert errors and "compatibility" in errors[-1].message
    work.action("probeTrainer")
    desktop.setMachine("trainer_python", "C:/Other/python.exe")
    work.completed("trainer_capability", backend_identity())
    assert work.state["capability"] == {}


def test_m9_starts_empty_and_requires_exact_failures_reason_confirmation(desktop):
    from validation_helpers import measured

    from splatforge.core.validation_policy import ReconstructionValidationPolicy, evaluate_policy

    _, _, _, metrics = measured([(i * 2 + 1, 10) for i in range(6)], [[0, 1, 2], [3, 4, 5]])
    report = evaluate_policy(metrics, ReconstructionValidationPolicy())
    selection = desktop._components
    selection.begin(report, metrics, True)
    assert not selection.state["selected"] and not selection.state["valid"]
    for c in selection.state["components"]:
        selection.toggleComponent(c["id"])
    assert selection.state["count"] == 2 and selection.state["valid"]
    failed = evaluate_policy(
        metrics, ReconstructionValidationPolicy(policy_id="custom_v1", minimum_viable_cameras=4)
    )
    selection.begin(failed, metrics, False)
    component = selection.state["components"][0]["id"]
    selection.toggleComponent(component)
    for issue in failed.issues:
        if issue.severity == "failure" and (
            issue.scope.component_id is None or str(issue.scope.component_id) == component
        ):
            selection.toggleIssue(str(issue.issue_id))
    assert not selection.state["valid"]
    selection.setReason("Reviewed these exact failures")
    assert selection.state["valid"] and not selection.confirm(False)
    assert selection.confirm(True)


def test_progress_is_truthful_and_idle_collapses(desktop):
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
        run_id=uuid4(), status="running", elapsed_seconds=14, stages=(stage,)
    )
    desktop.controller.active = (run,)
    assert desktop.state["progress"]["fraction"] == 0.4 and desktop.state["progress"]["eta"] == ""
    desktop.controller.active = (
        run.model_copy(update={"stages": (stage.model_copy(update={"fraction": None}),)}),
    )
    assert desktop.state["progress"]["fraction"] == -1
    desktop.controller.active = (
        run.model_copy(update={"stages": (stage.model_copy(update={"status": "failed"}),)}),
    )
    assert desktop.state["progress"]["fraction"] == -1
    desktop.controller.active = ()
    assert not desktop.state["progress"]["visible"]


def test_close_waits_for_confirmed_cancel_and_non_cancelable_work(desktop, tmp_path):
    from splatforge.application.media import MediaOperationCancelled

    open_project(desktop, tmp_path)
    release, entered, closed, dialogs = Event(), Event(), [], []
    desktop.closeReady.connect(lambda: closed.append(True))
    desktop.dialogRequested.connect(dialogs.append)

    def action(_):
        entered.set()
        release.wait(3)
        raise MediaOperationCancelled("Confirmed cancellation")

    desktop.controller.submit("ingest", action, mutation=True)
    until(entered.is_set)
    assert not desktop.requestClose() and dialogs[-1] == "activeClose"
    desktop.cancelAndClose()
    assert desktop.state["progress"]["cancelling"] and not closed
    release.set()
    until(lambda: bool(closed))
    until(lambda: not desktop.controller.executor.busy)
    desktop.controller.mutating, desktop.controller.operation = True, "cleanup_apply"
    assert not desktop.requestClose() and not desktop.state["progress"]["canCancel"]
    desktop.controller.mutating, desktop.controller.operation = False, None


def test_cleanup_requires_exact_digest_and_confirmation(desktop, monkeypatch):
    calls = []
    plan = CleanupPlan(project_id=uuid4(), candidates=(), protected_artifact_ids=(), total_bytes=0)
    desktop._inspection._cleanup = plan
    monkeypatch.setattr(desktop.controller, "cleanup", lambda p=None: calls.append(p))
    desktop.inspection.applyCleanup(plan.preview_digest, False)
    desktop.inspection.applyCleanup("wrong", True)
    assert not calls
    desktop.inspection.applyCleanup(plan.preview_digest, True)
    assert calls == [plan] and desktop._inspection._cleanup is None


def test_recovery_is_exclusive_but_available_with_unresolved_work(desktop, tmp_path):
    from splatforge.adapters.execution_storage import ExecutionFaultHooks, LocalExecutionRepository
    from splatforge.adapters.fake_stages import LocalFakeStages
    from splatforge.application.execution import FakeExecutionService, PublicationUnresolvedError

    root = open_project(desktop, tmp_path)

    def fail(_):
        raise OSError("Injected publication interruption")

    repo = LocalExecutionRepository(fault_hooks=ExecutionFaultHooks(after_artifact_move=fail))
    with pytest.raises(PublicationUnresolvedError):
        FakeExecutionService(repo, LocalFakeStages()).run(root, start=0, count=2, factor=2)
    desktop.refresh()
    until(lambda: not desktop.controller.executor.busy)
    # Publication interruption may leave a running attempt until explicit recovery.
    assert desktop.controller.active or desktop.controller.has_unresolved
    assert not desktop.state["canMutate"]
    run = desktop.controller.overview.index.runs[0].identity
    desktop.controller.recover_run(run)
    assert desktop.controller.mutating
    desktop.controller.pin(uuid4(), True)
    assert desktop.state["error"]["category"] == "ProjectBusy"
    until(lambda: not desktop.controller.executor.busy)
    assert not desktop.controller.has_unresolved
    assert not desktop.controller.active


def test_point_preview_bound_and_interaction(desktop, tmp_path):
    from test_qml import visual_item

    from splatforge.application.desktop import IndexRow

    open_project(desktop, tmp_path)
    desktop._outputs.replace(
        (
            IndexRow(
                identity=uuid4(),
                values={"title": "Preview fixture", "storage_status": "published", "pinned": False},
            ),
        )
    )
    engine = create_engine(desktop)
    desktop.navigate(5)
    QTest.qWait(40)
    window = engine.rootObjects()[0]
    preview = visual_item(window.contentItem(), "pointCenterPreview")
    assert preview is not None
    preview.set_data(
        PreviewData(
            artifact_id=uuid4(),
            semantic_digest="a" * 64,
            directory=tmp_path,
            metadata={},
            points=((0, 0, 0), (1, 2, 3)),
            cameras=((2, 1, 0),),
        )
    )
    preview.forceActiveFocus()
    original = preview.yaw
    QTest.keyClick(window, Qt.Key.Key_Right)
    assert preview.yaw != original
    QTest.keyClick(window, Qt.Key.Key_Plus)
    assert preview.zoom > 1
    QTest.keyClick(window, Qt.Key.Key_R)
    assert preview.zoom == 1
    window.close()
    engine.deleteLater()
    QGuiApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def test_health_never_promotes_gpu_presence_to_ready(desktop):
    desktop._inspection.completed(
        "doctor",
        {
            "colmap_learned_gpu": {"gpu": {"devices": [{"name": "Test GPU"}]}},
            "lichtfeld": {"status": "not_configured"},
        },
    )
    health = {r["title"]: r for r in desktop.inspection.state["health"]}
    assert health["GPU"]["status"] == "Detected"
    assert health["Trainer"]["status"] == "Not checked"
    assert health["Media"]["status"] == "Not checked"


from uuid import UUID  # noqa: E402
