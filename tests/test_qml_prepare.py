"""Bounded Prepare GUI automation; native/real pipeline acceptance is separate."""

import json
import os
from datetime import UTC, datetime
from threading import Event
from types import SimpleNamespace
from uuid import uuid4

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6", reason="Install the optional GUI extra")

from test_qml import app as app  # noqa: E402
from test_qml import desktop as desktop  # noqa: E402
from test_qml import until, visual_item  # noqa: E402
from test_qml_interaction import click, dispose  # noqa: E402
from test_qml_sources import inject_media, photo  # noqa: E402
from test_qml_workflows import open_project  # noqa: E402

from splatforge.application.desktop import ThumbnailReference  # noqa: E402
from splatforge.application.desktop_prepare import (  # noqa: E402
    PreparePlan,
    PrepareSummary,
    preparation_request,
)
from splatforge.bootstrap import build_project_service  # noqa: E402
from splatforge_gui.controller import ProjectController  # noqa: E402
from splatforge_gui.qml_app import create_engine  # noqa: E402
from splatforge_gui.tasks import TaskError  # noqa: E402


def idle(vm):
    until(lambda: not vm.controller.executor.busy and not vm.controller.mutating
          and not vm.media.preview_executor.busy and not vm.media.gallery.executor.busy
          and not vm.sources.thumbnails.executor.busy)


def inspector_click(window, name):
    """Reach an action in the longer direct-settings inspector before hit testing."""
    from PySide6.QtCore import QPointF
    from PySide6.QtTest import QTest

    scroll = visual_item(window.contentItem(), "prepareInspectorScroll").property("contentItem")
    scroll.setProperty("contentY", 0)
    QTest.qWait(20)
    control = visual_item(window.contentItem(), name)
    y = control.mapToItem(scroll, QPointF(0, control.height() / 2)).y()
    maximum = max(0, scroll.property("contentHeight") - scroll.height())
    scroll.setProperty("contentY", max(0, min(maximum, y - scroll.height() / 2)))
    click(window, name)


class PreparedFixture:
    """Deterministic application substitute; no invented production result."""

    def __init__(self, root, image):
        self.root, self.image = root, image
        self.plans, self.runs, self.pages = [], [], []
        self.history = ()
        self.fail_plan = False
        self.fail_run = False
        self.gallery_entered, self.gallery_release = Event(), Event()
        self.hold_gallery = False

    def plan(self, root, *, expected_project_id, expected_revision):
        self.plans.append((expected_project_id, expected_revision))
        if self.fail_plan:
            raise ValueError("Saved frame method is unsupported")
        doc = build_project_service().open(root)
        assert (doc.project_id, doc.revision) == (expected_project_id, expected_revision)
        return PreparePlan(
            project_id=doc.project_id, project_revision=doc.revision,
            request=preparation_request(doc), photo_count=1, video_count=1, used_video_count=0,
            candidate_count=1, candidate_bytes=100, peak_workspace_bytes=200,
            warnings=("Saved intervals omit this video's frames",), runnable=True,
        )

    def run(self, root, request, *, expected_project_id, expected_revision, cancellation_check):
        cancellation_check()
        if self.fail_run:
            raise ValueError("The source is unavailable; restore its location and retry")
        self.runs.append((expected_project_id, expected_revision, request))
        run_id = uuid4()
        self.history = (PrepareSummary(
            run_id=run_id, created_at=datetime.now(UTC), project_id=expected_project_id,
            project_revision=expected_revision, request=request, candidate_count=1,
            selected_count=1, rejected_count=0, method_id="frame_selection.fixed_fps",
        ),)
        return SimpleNamespace(status="succeeded", run_id=run_id)

    def results(self, root):
        return self.history

    def gallery(self, root, run, offset):
        self.pages.append((run, offset))
        self.gallery_entered.set()
        if self.hold_gallery:
            assert self.gallery_release.wait(5)
        return (ThumbnailReference(identity=str(run), path=self.image, caption="Fixture image"),)

    def page(
        self, root, run, *, filter="selected", offset=0, limit=100, anchor_view_id=None,
        scope="all",
    ):
        # Same deterministic boundary as the original M12c1 gallery substitute.
        # Delegating keeps its delayed success/error scenarios meaningful.
        rows = self.gallery(root, run, offset)
        document = build_project_service().open(root)
        items = tuple(SimpleNamespace(
            view_id=run, path=row.path, caption=row.caption, auto_selected=True,
            decision="automatic", included=True, reason="Selected automatically",
            auto_reason="Selected automatically",
            next_view_id=None, previous_view_id=None,
        ) for row in rows) if filter != "rejected" else ()
        return SimpleNamespace(
            project_id=document.project_id, project_revision=document.revision,
            run_id=run, review_digest="0" * 64, effective_run_id=run,
            candidate_count=1, auto_selected_count=1, selected_count=1,
            rejected_count=0, manual_count=0, offset=0, total=len(items), items=items,
        )


def configured(vm, tmp_path):
    root = open_project(vm, tmp_path)
    vm.controller.timer.stop()
    inject_media(vm, root)
    image = photo(tmp_path / "Original Ž.png")
    vm.addFiles([str(image)])
    idle(vm)
    service = PreparedFixture(root, image)
    factory = vm.controller.factory

    def injected():
        facade = factory()
        facade.factories["prepare_data"] = lambda: service
        facade.factories["frame_review"] = lambda: service
        facade.gallery = service.gallery
        return facade

    vm.controller.factory = injected
    return root, image, service


@pytest.mark.parametrize("theme", ["Dark", "Light"])
def test_prepare_entry_plan_run_history_and_source_restore(desktop, tmp_path, theme):
    root, image, service = configured(desktop, tmp_path)
    identity = str(desktop.sources.rows[0].identity)
    desktop.media.showSource(identity)
    idle(desktop)
    desktop.setTheme(theme)
    engine = create_engine(desktop)
    window = engine.rootObjects()[0]
    window.resize(1024, 640)
    try:
        click(window, "prepareDataEntry")
        idle(desktop)
        assert desktop.prepare.state["active"] and desktop.state["page"] == 1
        assert not desktop.media.state["videoUrl"]
        assert not desktop.sources.thumbnails_active
        inspector_click(window, "planPrepare")
        idle(desktop)
        state = desktop.prepare.state
        assert state["canRun"] and state["plan"]["usedVideoCount"] == 0
        assert state["plan"]["candidateCount"] == 1
        inspector_click(window, "runPrepare")
        idle(desktop)
        state = desktop.prepare.state
        assert state["status"] == "succeeded" and state["selectedSummary"]["selectedCount"] == 1
        assert state["galleryCount"] == 1 and service.pages[-1][1] == 0
        assert service.runs[0][:2] == service.plans[-1]
        assert service.runs[0][2] == preparation_request(build_project_service().open(root))
        assert visual_item(window.contentItem(), "preparedFramesGrid").property("count") == 1
        click(window, "returnToSources")
        idle(desktop)
        assert not desktop.prepare.state["active"]
        assert desktop.media.state["previewSource"]["identity"] == identity
        assert desktop.media.state["galleryRun"] == ""
        assert image.exists() and desktop.sources.thumbnails_active
        assert not engine.load_errors
    finally:
        service.gallery_release.set()
        idle(desktop)
        dispose(engine)


@pytest.mark.parametrize("choice", ["save", "discard", "cancel"])
def test_prepare_unsaved_entry_uses_existing_decision_flow(desktop, tmp_path, choice):
    _, _, service = configured(desktop, tmp_path)
    doc = desktop.controller.overview.document
    desktop.controller.edit(doc.model_copy(update={"label": "Unsaved preparation"}))
    dialogs = []
    desktop.dialogRequested.connect(dialogs.append)
    desktop.prepare.enter()
    assert dialogs[-1] == "unsaved" and not desktop.prepare.state["active"]
    desktop.resolveUnsaved(choice)
    idle(desktop)
    assert desktop.prepare.state["active"] is (choice != "cancel")
    assert not service.runs


def test_prepare_plan_errors_are_local_and_retryable(desktop, tmp_path):
    _, _, service = configured(desktop, tmp_path)
    dialogs = []
    desktop.dialogRequested.connect(dialogs.append)
    desktop.prepare.enter()
    idle(desktop)
    service.fail_plan = True
    desktop.prepare.plan()
    idle(desktop)
    assert desktop.prepare.state["status"] == "failed"
    assert "unsupported" in desktop.prepare.state["error"]
    assert "error" not in dialogs and not desktop.prepare.state["canRun"]
    service.fail_plan = False
    desktop.prepare.plan()
    idle(desktop)
    assert desktop.prepare.state["canRun"] and not desktop.prepare.state["error"]


@pytest.mark.parametrize("theme", ["Dark", "Light"])
def test_blocked_plan_shows_unknown_count_reason_and_explicit_retry(app, desktop, tmp_path, theme):
    from PySide6.QtCore import QPointF
    from PySide6.QtTest import QTest

    root, _, service = configured(desktop, tmp_path)
    video = tmp_path / "Metadata-only clip.mp4"
    video.write_bytes(b"tiny synthetic fixture, never decoded")
    desktop.addFiles([str(video)])
    idle(desktop)
    before = (root / "project.json").read_bytes()
    normal_plan = service.plan
    count = [None]
    reason = (
        "Candidate storage bound is at least 26.97 GiB, above the 20.00 GiB limit. "
        "Reduce the sources Included in preparation or lower candidate frames/second. "
        "Sharpest video needs at least 2 × target FPS, "
        "so increase the output interval as needed. "
        "Save settings, then check the plan again."
    )
    note = "Full video extraction precedes Trim; this is a conservative storage bound."

    def blocked(*args, **kwargs):
        return normal_plan(*args, **kwargs).model_copy(update={
            "runnable": False, "candidate_count": count[0], "candidate_bytes": None,
            "used_video_count": 1,
            "peak_workspace_bytes": None, "warnings": (note, reason), "blockers": (reason,),
        })

    service.plan = blocked
    desktop.setTheme(theme)
    engine = create_engine(desktop)
    window = engine.rootObjects()[0]
    captures = []

    def capture(name):
        if app.platformName() == "offscreen":
            return
        until(window.isExposed)
        QTest.qWait(40)
        raster = window.grabWindow()
        assert not raster.isNull() and raster.save(str(tmp_path / f"{theme}-{name}.png"))
        captures.append(dict(name=name, exposed=window.isExposed(),
                             logical=[window.width(), window.height()],
                             raster=[raster.width(), raster.height()],
                             dpr=window.devicePixelRatio()))

    def assert_reason_visible():
        scroll = visual_item(window.contentItem(), "prepareInspectorScroll")
        reason_item = visual_item(window.contentItem(), "preparePlanBlockers")
        top = reason_item.mapToScene(QPointF(0, 0)).y()
        viewport = scroll.mapToScene(QPointF(0, 0)).y()
        assert top >= viewport - 1
        assert top + reason_item.height() <= viewport + scroll.height() + 1

    try:
        window.resize(1440, 900)
        click(window, "prepareDataEntry")
        idle(desktop)
        click(window, "planPrepare")
        idle(desktop)
        state = desktop.prepare.state
        assert state["status"] == "blocked" and not state["canRun"]
        assert "ready" not in state["message"].lower()
        assert state["plan"]["blockers"] == [reason]
        assert state["plan"]["warnings"] == [note]
        counts = visual_item(window.contentItem(), "preparePlanCounts")
        assert "Candidate count unavailable" in counts.property("text")
        assert "undefined" not in counts.property("text")
        assert not visual_item(window.contentItem(), "runPrepare").isEnabled()
        desktop.prepare.run()
        assert not service.runs
        click(window, "showPrepareBlockingReason")
        assert_reason_visible()
        capture("blocked-reason")
        window.resize(1024, 640)
        QTest.qWait(30)
        scroll = visual_item(window.contentItem(), "prepareInspectorScroll").property("contentItem")
        scroll.setProperty("contentY", max(0, scroll.property("contentHeight") - scroll.height()))
        click(window, "showPrepareBlockingReason")
        assert_reason_visible()
        capture("compact-blocked-reason")
        assert (root / "project.json").read_bytes() == before
        # A recorded zero is distinct from missing/undefined QVariant metadata.
        count[0] = 0
        click(window, "planPrepare")
        idle(desktop)
        assert "Up to 0 candidates" in counts.property("text")
        service.plan = normal_plan
        desktop.prepare.settings.setField("interval_seconds", "1")
        desktop.prepare.settings.setField("candidate_fps", "2")
        assert not desktop.prepare.state["plan"] and not desktop.prepare.state["canRun"]
        desktop.prepare.settings.save()
        idle(desktop)
        click(window, "planPrepare")
        idle(desktop)
        assert desktop.prepare.state["status"] == "ready" and desktop.prepare.state["canRun"]
        assert not visual_item(window.contentItem(), "showPrepareBlockingReason").isVisible()
        assert desktop.prepare.state["message"] == "Saved plan ready."
        assert not service.runs and not engine.load_errors
    finally:
        (tmp_path / "native-budget.json").write_text(json.dumps(dict(
            platform=app.platformName(), captures=captures, theme=theme,
            synthetic_plan=True, real_video_decode=False,
            qml_warnings=engine.load_errors,
        ), indent=2), encoding="utf-8")
        idle(desktop)
        dispose(engine)


def test_prepare_cancel_before_run_handle_drains_and_can_restart(desktop, tmp_path, monkeypatch):
    _, _, service = configured(desktop, tmp_path)
    desktop.prepare.enter()
    idle(desktop)
    desktop.prepare.plan()
    idle(desktop)
    monkeypatch.setattr(desktop.prepare, "_readers_ready", lambda: False)
    desktop.prepare.run()
    assert desktop.controller.operation == "prepare" and desktop.controller.can_cancel
    desktop.prepare.cancel()
    until(lambda: not desktop.controller.mutating)
    idle(desktop)
    assert desktop.prepare.state["status"] == "cancelled" and not service.runs
    monkeypatch.setattr(desktop.prepare, "_readers_ready", lambda: True)
    desktop.prepare.run()
    idle(desktop)
    assert desktop.prepare.state["status"] == "succeeded" and len(service.runs) == 1


def test_stale_prepared_gallery_cannot_replace_returned_source(desktop, tmp_path):
    _, _, service = configured(desktop, tmp_path)
    identity = str(desktop.sources.rows[0].identity)
    desktop.media.showSource(identity)
    idle(desktop)
    desktop.prepare.enter()
    idle(desktop)
    desktop.prepare.plan()
    idle(desktop)
    desktop.prepare.run()
    idle(desktop)
    service.hold_gallery = True
    service.gallery_entered.clear()
    desktop.prepare.selectRun(desktop.prepare.state["selectedRun"])
    until(service.gallery_entered.is_set)
    desktop.prepare.sources()
    service.gallery_release.set()
    idle(desktop)
    assert desktop.media.state["galleryRun"] == ""
    assert desktop.media.state["previewSource"]["identity"] == identity
    assert desktop.media.gallery.references[0].identity == identity


def test_project_generation_revokes_prepare_plan_history_and_local_error(desktop, tmp_path):
    _, _, _ = configured(desktop, tmp_path)
    desktop.prepare.enter()
    idle(desktop)
    desktop.prepare.plan()
    idle(desktop)
    token = desktop.prepare._token
    plan = desktop.prepare._plan
    desktop.controller.generation += 1
    desktop.changed.emit()
    desktop.prepare._completed("prepare_plan", (token, plan))
    assert not desktop.prepare.state["active"] and not desktop.prepare.state["plan"]
    assert not desktop.prepare.state["history"]
    # Obsolete or unbound factory errors cannot contaminate the new context either.
    desktop.prepare._failed(TaskError("Old failure", "ValueError", "", "prepare_plan", token))
    desktop.prepare._failed(TaskError("Unbound failure", "ValueError", "", "prepare_plan"))
    assert not desktop.prepare.state["error"]
    desktop.prepare._failed(TaskError(
        "Local failure", "ValueError", "", "prepare_plan", desktop.prepare._token,
    ))
    assert desktop.prepare.state["error"] == "Local failure"


def test_prepare_cancel_is_forwarded_when_progress_reveals_late_run_handle(app, monkeypatch):
    controller = ProjectController()
    controller.timer.stop()
    controller.mutating, controller.operation = True, "prepare"
    controller.ingest_cancel.set()
    identity, run_id = "progress-reply", uuid4()
    controller.jobs[identity] = ("progress", False, controller.generation)
    calls = []
    monkeypatch.setattr(controller, "submit", lambda name, action: calls.append(name))
    controller._result(identity, ((SimpleNamespace(run_id=run_id),), {}))
    assert calls == ["cancel"]
    assert str(run_id) in controller.cancelled_runs and controller.ingest_cancel.is_set()
    assert controller.mutating and controller.can_cancel
    controller.deleteLater()


def test_prepare_run_failure_keeps_published_history_and_replaces_running_message(
    desktop, tmp_path,
):
    _, image, service = configured(desktop, tmp_path)
    desktop.prepare.enter()
    idle(desktop)
    desktop.prepare.plan()
    idle(desktop)
    desktop.prepare.run()
    idle(desktop)
    published = desktop.prepare.state["selectedRun"]
    service.fail_run = True
    desktop.prepare.run()
    idle(desktop)
    state = desktop.prepare.state
    assert state["status"] == "failed" and not state["busy"]
    assert "source is unavailable" in state["error"] and "did not finish" in state["message"]
    assert state["selectedRun"] == published and len(state["history"]) == 1
    assert image.exists() and state["canRun"]
    service.fail_run = False
    desktop.prepare.run()
    idle(desktop)
    assert desktop.prepare.state["status"] == "succeeded"
    assert not desktop.prepare.state["error"]


@pytest.mark.parametrize("destination", ["another_run", "sources"])
def test_stale_gallery_failure_cannot_contaminate_new_context(desktop, tmp_path, destination):
    _, _, service = configured(desktop, tmp_path)
    desktop.prepare.enter()
    idle(desktop)
    desktop.prepare.plan()
    idle(desktop)
    desktop.prepare.run()
    idle(desktop)
    old = service.history[0]
    new = old.model_copy(update={"run_id": uuid4()})
    service.history = (new, old)
    desktop.prepare.refreshHistory()
    idle(desktop)
    entered, release = Event(), Event()
    gallery = service.gallery

    def delayed(root, run, offset):
        if run == old.run_id:
            entered.set()
            assert release.wait(5)
            raise ValueError("Obsolete prepared set unavailable")
        return gallery(root, run, offset)

    service.gallery = delayed
    dialogs = []
    desktop.dialogRequested.connect(dialogs.append)
    try:
        desktop.prepare.selectRun(str(old.run_id))
        until(entered.is_set)
        if destination == "another_run":
            desktop.prepare.selectRun(str(new.run_id))
            until(lambda: desktop.media.gallery.rowCount() == 1)
            assert desktop.prepare.state["selectedRun"] == str(new.run_id)
        else:
            desktop.prepare.sources()
            assert not desktop.prepare.state["active"]
        release.set()
        idle(desktop)
        assert not desktop.prepare.state["error"]
        assert "error" not in dialogs and not desktop.prepare.state["galleryLoading"]
        assert desktop.media.state["galleryRun"] == (
            str(new.run_id) if destination == "another_run" else ""
        )
    finally:
        release.set()
        idle(desktop)
