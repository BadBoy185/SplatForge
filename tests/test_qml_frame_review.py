"""Bounded frame-review interaction checks with deterministic service data."""

import os
from threading import Event
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6", reason="Install the optional GUI extra")

from test_qml import app as app  # noqa: E402
from test_qml import desktop as desktop  # noqa: E402
from test_qml import until, visual_item  # noqa: E402
from test_qml_interaction import click, dispose  # noqa: E402
from test_qml_prepare import configured, idle  # noqa: E402

from splatforge.application.desktop_prepare import preparation_request  # noqa: E402
from splatforge.bootstrap import build_project_service  # noqa: E402
from splatforge_gui.qml_app import create_engine  # noqa: E402


class ReviewFixture:
    """Models persisted decisions, canonical UUID order and bounded page readback."""

    def __init__(self, root, image, count=105):
        self.root, self.image = root, image
        self.ids = tuple(UUID(int=i + 1) for i in range(count))
        self.decisions = {}
        self.calls, self.pages = [], []
        self.fail_page = False
        self.fail_apply = False
        self.hold_apply = False
        self.entered, self.release = Event(), Event()
        self.read_entered, self.read_release = Event(), Event()
        self.hold_filter = ""

    def included(self, identity):
        return self.decisions.get(identity, "automatic") == "include" or (
            self.decisions.get(identity, "automatic") == "automatic" and identity != self.ids[0]
        )

    def page(
        self, root, run, *, filter="selected", offset=0, limit=100, anchor_view_id=None,
        scope="all",
    ):
        self.pages.append((run, filter, offset, anchor_view_id))
        if filter == self.hold_filter:
            self.read_entered.set()
            assert self.read_release.wait(5)
        if self.fail_page:
            raise ValueError("This published set could not be read")
        doc = build_project_service().open(root)
        sequence = [identity for identity in self.ids if filter == "all" or
                    self.included(identity) == (filter == "selected")]
        if anchor_view_id in sequence:
            offset = sequence.index(anchor_view_id) // limit * limit
        offset = min(offset, (max(0, len(sequence) - 1) // limit) * limit)
        items = tuple(SimpleNamespace(
            view_id=identity, path=self.image, caption=f"Frame {identity.int}",
            auto_selected=identity != self.ids[0],
            decision=self.decisions.get(identity, "automatic"),
            included=self.included(identity), auto_reason="Automatic quality reason",
            reason="Effective decision reason",
            previous_view_id=sequence[index - 1] if index else None,
            next_view_id=sequence[index + 1] if index + 1 < len(sequence) else None,
        ) for index, identity in enumerate(sequence) if offset <= index < offset + limit)
        return SimpleNamespace(
            project_id=doc.project_id, project_revision=doc.revision, run_id=run,
            review_digest=str(len(self.calls)), effective_run_id=run,
            candidate_count=len(self.ids), auto_selected_count=len(self.ids) - 1,
            selected_count=sum(self.included(identity) for identity in self.ids),
            rejected_count=sum(not self.included(identity) for identity in self.ids),
            manual_count=len(self.decisions), offset=offset, total=len(sequence), items=items,
        )

    def apply(self, root, run, ids, decision, **expected):
        self.entered.set()
        if self.hold_apply:
            assert self.release.wait(5)
        if self.fail_apply:
            raise ValueError("Saved decision revision changed")
        assert expected["expected_review_digest"] == str(len(self.calls))
        self.calls.append((run, ids, decision))
        for identity in ids:
            if decision == "automatic":
                self.decisions.pop(identity, None)
            else:
                self.decisions[identity] = decision
        return SimpleNamespace()


def reviewed(vm, tmp_path, *, count=105):
    root, image, prepare = configured(vm, tmp_path)
    document = build_project_service().open(root)
    prepare.run(root, preparation_request(document), expected_project_id=document.project_id,
                expected_revision=document.revision, cancellation_check=lambda: None)
    service = ReviewFixture(root, image, count)
    # A fixed-FPS omission need not appear in the automatic explicit rejection list.
    prepare.history = (prepare.history[0].model_copy(update={
        "candidate_count": count, "selected_count": count - 1, "rejected_count": 0,
    }),)
    factory = vm.controller.factory

    def injected():
        facade = factory()
        facade.factories["frame_review"] = lambda: service
        return facade

    vm.controller.factory = injected
    vm.prepare.enter()
    idle(vm)
    return vm.prepare.review, service, prepare


def test_batch_selection_is_independent_of_preview_and_reset_restores_automatic(desktop, tmp_path):
    review, service, _ = reviewed(desktop, tmp_path)
    first, second, viewed = map(str, service.ids[1:4])
    review.select(first, True)
    review.select(second, True)
    review.view(viewed)
    idle(desktop)
    assert review.state["selectedIds"] == [first, second]
    review.applyBatch("exclude")
    idle(desktop)
    assert service.calls[-1][1:] == ((UUID(first), UUID(second)), "exclude")
    assert review.state["viewedId"] == viewed and review.state["selectedCount"] == 0
    review.setFilter("rejected")
    idle(desktop)
    rejected = str(service.ids[0])
    review.view(rejected)
    idle(desktop)
    review.applyFrame(rejected, "include")
    idle(desktop)
    assert service.included(service.ids[0])
    review.setFilter("all")
    idle(desktop)
    review.applyFrame(rejected, "automatic")
    idle(desktop)
    assert not service.included(service.ids[0])
    assert review.state["items"][rejected]["decision"] == "automatic"
    assert review.state["items"][rejected]["autoReason"] == "Automatic quality reason"


@pytest.mark.parametrize("filter_name", ["selected", "all"])
def test_preview_exclude_uses_pre_action_uuid_neighbor_across_page(desktop, tmp_path, filter_name):
    review, service, _ = reviewed(desktop, tmp_path)
    review.setFilter(filter_name)
    idle(desktop)
    last = list(review.state["items"])[-1]
    expected = review.state["items"][last]["nextId"]
    review.view(last)
    idle(desktop)
    review.applyFrame(last, "exclude")
    # Double delivery cannot target the successor while persistence is pending.
    review.applyFrame(last, "exclude")
    idle(desktop)
    assert len(service.calls) == 1
    assert review.state["viewedId"] == expected
    assert service.pages[-1][3] == UUID(expected)
    assert review.state["items"][expected]["included"]


def test_frame_review_reserves_and_drains_readers_before_apply(desktop, tmp_path, monkeypatch):
    review, service, _ = reviewed(desktop, tmp_path)
    identity = next(iter(review.state["items"]))
    ready = False
    monkeypatch.setattr(desktop.prepare, "_readers_ready", lambda: ready)
    review.applyFrame(identity, "exclude")
    assert desktop.controller.mutating and desktop.controller.operation == "frame_review_apply"
    assert not service.entered.is_set() and review.state["saving"]
    existing = dict(desktop.controller.jobs)
    desktop.controller.refresh()
    desktop.controller.poll()
    assert desktop.controller.jobs == existing
    review.view(identity)
    review.applyBatch("include")
    assert not service.calls
    ready = True
    until(lambda: bool(service.calls))
    idle(desktop)
    assert len(service.calls) == 1 and not review.state["saving"]


def test_failed_run_page_clears_previous_metadata_and_actions(desktop, tmp_path):
    review, service, prepare = reviewed(desktop, tmp_path)
    old = next(iter(review.state["items"]))
    review.select(old, True)
    replacement = prepare.history[0].model_copy(update={"run_id": uuid4()})
    prepare.history = (replacement, *prepare.history)
    desktop.prepare.refreshHistory()
    idle(desktop)
    service.fail_page = True
    desktop.prepare.selectRun(str(replacement.run_id))
    idle(desktop)
    assert review.state["error"] and "loaded" in review.state["message"]
    assert not review.state["canEdit"] and not review.state["items"]
    assert review.state["selectedCount"] == review.state["selectedTotal"] == 0
    review.applyFrame(old, "exclude")
    assert not service.calls


def test_old_filter_response_cannot_replace_new_page(desktop, tmp_path):
    review, service, _ = reviewed(desktop, tmp_path)
    service.hold_filter = "rejected"
    review.setFilter("rejected")
    until(service.read_entered.is_set)
    review.setFilter("all")
    until(lambda: review.state["filter"] == "all" and not review.state["loading"])
    service.read_release.set()
    idle(desktop)
    assert review.state["filter"] == "all" and review.state["total"] == 105
    assert len(review.state["items"]) == 100


def test_save_failure_does_not_report_success_or_leave_stale_actions(desktop, tmp_path):
    review, service, _ = reviewed(desktop, tmp_path, count=4)
    identity = next(iter(review.state["items"]))
    review.applyFrame(identity, "exclude")
    idle(desktop)
    assert desktop.prepare.state["selectedSummary"]["selectedCount"] == 2
    engine = create_engine(desktop)
    window = engine.rootObjects()[0]
    try:
        identity = next(iter(review.state["items"]))
        service.fail_apply = True
        review.applyFrame(identity, "exclude")
        idle(desktop)
        assert "revision changed" in review.state["error"]
        assert "not confirmed" in review.state["message"]
        assert not review.state["canEdit"] and len(service.calls) == 1
        assert not review.state["items"]
        summary = desktop.prepare.state["selectedSummary"]
        assert summary["autoSelectedCount"] == 3 and summary["autoRejectedCount"] == 1
        assert not summary["reviewCountsAvailable"]
        assert summary["selectedCount"] is None and summary["rejectedCount"] is None
        text = visual_item(window.contentItem(), "prepareResultCounts").property("text")
        assert "Automatic: 3 selected · 1 rejected" in text
        assert "Review membership unavailable" in text and "Review:" not in text
        empty = visual_item(window.contentItem(), "frameReviewEmptyState").property("text")
        assert "unavailable" in empty and "No selected frames" not in empty
    finally:
        dispose(engine)


@pytest.mark.parametrize("count", [2, 4])
def test_preview_exclude_last_uses_previous_or_closes_empty(desktop, tmp_path, count):
    review, service, _ = reviewed(desktop, tmp_path, count=count)
    last = list(review.state["items"])[-1]
    previous = review.state["items"][last]["previousId"]
    review.view(last)
    idle(desktop)
    review.applyFrame(last, "exclude")
    idle(desktop)
    assert review.state["viewedId"] == previous
    if count == 2:
        assert review.state["total"] == 0 and not review.state["items"]
    else:
        assert review.state["items"][previous]["included"]


def test_project_switch_revokes_old_page_response(desktop, tmp_path):
    review, service, _ = reviewed(desktop, tmp_path)
    service.hold_filter = "rejected"
    review.setFilter("rejected")
    until(service.read_entered.is_set)
    other = tmp_path / "Other project"
    build_project_service().create(other, "Other")
    try:
        desktop.openProject(str(other))
        until(lambda: desktop.controller.root == other)
        service.read_release.set()
        idle(desktop)
        assert not desktop.prepare.state["active"]
        assert not review.state["items"] and not review.state["canEdit"]
        assert not desktop.media.state["galleryRun"]
    finally:
        service.read_release.set()


def test_batch_selection_clears_on_page_change(desktop, tmp_path):
    review, service, _ = reviewed(desktop, tmp_path)
    review.selectPage()
    assert review.state["selectedCount"] == 100
    review.nextPage()
    idle(desktop)
    assert review.state["offset"] == 100 and review.state["selectedCount"] == 0
    assert review.state["viewedId"] == ""


@pytest.mark.parametrize("theme", ["Dark", "Light"])
def test_frame_review_qml_filters_and_independent_checkbox(desktop, tmp_path, theme):
    review, service, _ = reviewed(desktop, tmp_path, count=4)
    desktop.setTheme(theme)
    engine = create_engine(desktop)
    window = engine.rootObjects()[0]
    window.resize(1024, 640)
    try:
        identity = str(service.ids[1])
        click(window, "selectFrame_" + identity)
        assert review.state["selectedCount"] == 1
        click(window, "viewFrame_" + identity)
        idle(desktop)
        assert review.state["viewedId"] == identity and review.state["selectedCount"] == 1
        assert "1 selected on this page" in visual_item(
            window.contentItem(), "frameBatchScope").property("text")
        click(window, "reviewFilter_rejected")
        idle(desktop)
        assert review.state["selectedCount"] == 0 and review.state["viewedId"] == ""
        assert review.state["total"] == 1 and not engine.load_errors
    finally:
        dispose(engine)
