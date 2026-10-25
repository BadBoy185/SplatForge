"""Behavioral parity for the QML bridge; backend fixtures remain unchanged."""

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
    root = tmp_path / "Scene with spaces Žluťoučký"
    desktop.createProject(str(root), "Tiny scene")
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
