"""Source scopes are presentation context, independent of the saved decision UUIDs."""

from threading import Event
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

pytest.importorskip("PySide6", reason="Install the optional GUI extra")

from test_qml import app as app  # noqa: E402
from test_qml import desktop as desktop  # noqa: E402
from test_qml import until, visual_item  # noqa: E402
from test_qml_frame_review import ReviewFixture, reviewed  # noqa: E402
from test_qml_interaction import click, dispose  # noqa: E402
from test_qml_prepare import idle  # noqa: E402

from splatforge.bootstrap import build_project_service  # noqa: E402
from splatforge.core.frame_review import ReviewProvenance  # noqa: E402
from splatforge.core.views import FrameTimestamp, RationalValue  # noqa: E402
from splatforge_gui.frame_review_vm import FrameReviewViewModel  # noqa: E402
from splatforge_gui.qml_app import create_engine  # noqa: E402


class ScopedFixture(ReviewFixture):
    def __init__(self, previous):
        super().__init__(previous.root, previous.image, count=206)
        self.sources = (UUID(int=1001), UUID(int=1002))
        self.keys = tuple("source/" + str(value) for value in self.sources)
        self.scope_reads = []
        self.hold_scope = ""
        self.fail_scope = ""

    def page(self, root, run, *, scope="all", filter="selected", offset=0, limit=100,
             anchor_view_id=None):
        self.scope_reads.append((scope, filter, offset, anchor_view_id))
        if scope == self.hold_scope:
            self.read_entered.set()
            assert self.read_release.wait(5)
        if scope == self.fail_scope:
            raise ValueError("Old scope failed to load")
        base = super().page(root, run, filter="all", limit=1000)
        subsets = {"all": self.ids, self.keys[0]: self.ids[:103],
                   self.keys[1]: self.ids[103:], "group/empty": ()}
        labels = {"all": "All sources", self.keys[0]: "Repeated.mov · first source",
                  self.keys[1]: "Repeated.mov · second source", "group/empty": "Empty saved group"}
        subset = subsets[scope]
        sequence = [value for value in subset if filter == "all"
                    or self.included(value) == (filter == "selected")]
        if anchor_view_id in sequence:
            offset = sequence.index(anchor_view_id) // limit * limit
        offset = min(offset, max(0, len(sequence) - 1) // limit * limit)
        items = {item.view_id: item for item in base.items}
        rows = tuple(SimpleNamespace(**dict(
            vars(items[value]),
            previous_view_id=sequence[index - 1] if index else None,
            next_view_id=sequence[index + 1] if index + 1 < len(sequence) else None,
            provenance=provenance(self.sources[0] if value in self.ids[:103] else self.sources[1]),
        )) for index, value in enumerate(sequence) if offset <= index < offset + limit)
        options = tuple(SimpleNamespace(
            key=key, label=labels[key], kind="all" if key == "all" else
            "group" if key == "group/empty" else "source", source_count=2 if key == "all"
            else 0 if key == "group/empty" else 1, candidate_count=len(values),
            selected_count=sum(self.included(value) for value in values),
            rejected_count=sum(not self.included(value) for value in values),
        ) for key, values in subsets.items())
        return SimpleNamespace(**dict(
            vars(base), items=rows, offset=offset, total=len(sequence), scope_key=scope,
            scope_label=labels[scope], scopes=options, scope_candidate_count=len(subset),
            scope_auto_selected_count=sum(value != self.ids[0] for value in subset),
            scope_selected_count=sum(self.included(value) for value in subset),
            scope_rejected_count=sum(not self.included(value) for value in subset),
            scope_manual_count=sum(value in self.decisions for value in subset),
        ))


def provenance(source, **changes):
    fields = dict(
        source_id=source, source_revision=1, media_type="video", source_name="Repeated.mov",
        path_at_preparation="C:/Original long folder/Repeated.mov",
        current_locator="D:/Relinked long folder/Repeated.mov", current_source_state="same_source",
        timestamp=FrameTimestamp(pts=12525, time_base=RationalValue(numerator=1, denominator=1000)),
        width=1920, height=1080, stream_index=0,
    )
    fields.update(changes)
    return ReviewProvenance(**fields)


def scoped(vm, tmp_path):
    review, original, prepare = reviewed(vm, tmp_path)
    service = ScopedFixture(original)
    factory = vm.controller.factory

    def injected():
        facade = factory()
        facade.factories["frame_review"] = lambda: service
        return facade

    vm.controller.factory = injected
    review.set_run(review._run)
    idle(vm)
    return review, service, prepare


def test_scope_status_pagination_clear_and_captured_apply_readback(desktop, tmp_path):
    review, service, _ = scoped(desktop, tmp_path)
    review.setScope(service.keys[0])
    idle(desktop)
    assert review.state["candidateTotal"] == 206
    assert review.state["scopeCandidateTotal"] == 103 and review.state["total"] == 102
    review.selectPage()
    review.view(next(iter(review.state["items"])))
    idle(desktop)
    review.nextPage()
    idle(desktop)
    assert review.state["offset"] == 100 and review.state["selectedCount"] == 0
    last = list(review.state["items"])[-1]
    assert not review.state["items"][last]["nextId"]
    review.select(last, True)
    review.view(last)
    idle(desktop)
    review.setScope(service.keys[1])
    assert not review.state["viewedId"] and not review.state["selectedIds"]
    idle(desktop)
    assert review.state["offset"] == 0 and not review.state["viewedId"]
    identity = next(iter(review.state["items"]))
    review.select(identity, True)
    review.applyBatch("exclude")
    idle(desktop)
    assert service.calls[-1][1] == (UUID(identity),)
    assert service.scope_reads[-1][:2] == (service.keys[1], "selected")
    assert review.state["scopeSelectedTotal"] == 102 and review.state["selectedTotal"] == 204
    review.setFilter("rejected")
    idle(desktop)
    assert review.state["total"] == 1 and identity in review.state["items"]
    review.setScope("group/empty")
    idle(desktop)
    assert review.state["total"] == review.state["scopeCandidateTotal"] == 0
    assert review.state["scopeLabel"] == "Empty saved group"


@pytest.mark.parametrize("failure", [False, True])
def test_stale_scope_service_success_and_failure_are_revoked(desktop, tmp_path, failure):
    review, service, _ = scoped(desktop, tmp_path)
    service.hold_scope = service.keys[0]
    service.fail_scope = service.keys[0] if failure else ""
    review.setScope(service.keys[0])
    until(service.read_entered.is_set)
    try:
        review.setScope(service.keys[1])
        until(lambda: not review.state["loading"])
        service.read_release.set()
        idle(desktop)
        assert review.state["scope"] == service.keys[1] and not review.state["error"]
        assert review.state["scopeCandidateTotal"] == 103
        assert all(UUID(value) in service.ids[103:] for value in review.state["items"])
    finally:
        service.read_release.set()


def test_factory_error_is_correlated_to_current_scope(desktop, tmp_path):
    review, service, _ = scoped(desktop, tmp_path)
    factory = desktop.controller.factory
    entered, release = Event(), Event()
    hold = True

    def failing_factory():
        nonlocal hold
        if hold:
            hold = False
            entered.set()
            assert release.wait(5)
            raise ValueError("Old factory failed")
        return factory()

    desktop.controller.factory = failing_factory
    review.setScope(service.keys[0])
    until(entered.is_set)
    try:
        review.setScope(service.keys[1])
        until(lambda: not review.state["loading"])
        release.set()
        idle(desktop)
        assert not review.state["error"] and review.state["scope"] == service.keys[1]
        hold = True
        review.setScope("all")
        idle(desktop)
        assert not review.state["loading"] and "Old factory failed" in review.state["error"]
        assert not review.state["items"]
    finally:
        release.set()


def test_scope_resets_when_prepared_run_or_project_changes(desktop, tmp_path):
    review, service, prepare = scoped(desktop, tmp_path)
    review.setScope(service.keys[0])
    idle(desktop)
    replacement = prepare.history[0].model_copy(update={"run_id": uuid4()})
    prepare.history = (replacement, *prepare.history)
    desktop.prepare.refreshHistory()
    idle(desktop)
    desktop.prepare.selectRun(str(replacement.run_id))
    idle(desktop)
    assert review.state["scope"] == "all"
    review.setScope(service.keys[1])
    idle(desktop)
    other = tmp_path / "Other project"
    build_project_service().create(other, "Other")
    desktop.openProject(str(other))
    idle(desktop)
    assert review.state["scope"] == "all" and not review.state["scopes"]


def test_provenance_uses_original_timestamp_and_explicit_missing_evidence():
    original = provenance(UUID(int=1001))
    value = FrameReviewViewModel._provenance(original)
    assert value["originalTime"] == "00:00:12.525"
    assert value["pathAtPreparation"].startswith("C:")
    assert value["currentLocator"].startswith("D:")
    assert value["automaticScore"] == "Not recorded" and value["sourceCheck"] == "No recorded check"
    assert "12525" in value["technical"]
    photo = original.model_copy(update={"media_type": "photo", "timestamp": None})
    assert FrameReviewViewModel._provenance(photo)["originalTime"] == "Not applicable — photo"
    missing = original.model_copy(update={"timestamp": None, "width": None})
    value = FrameReviewViewModel._provenance(missing)
    assert value["originalTime"] == value["dimensions"] == "Not recorded"
    assert FrameReviewViewModel._provenance(None) == {}


@pytest.mark.parametrize("theme", ["Dark", "Light"])
def test_scope_qml_empty_and_single_provenance(desktop, tmp_path, theme):
    review, service, _ = scoped(desktop, tmp_path)
    desktop.setTheme(theme)
    engine = create_engine(desktop)
    window = engine.rootObjects()[0]
    window.resize(1024, 640)
    try:
        counts = visual_item(window.contentItem(), "prepareResultCounts").property("text")
        assert "Quality measurements not recorded" in counts and "undefined" not in counts
        review.setScope(service.keys[0])
        idle(desktop)
        scope = visual_item(window.contentItem(), "preparedFrameScope")
        assert scope.property("currentValue") == service.keys[0]
        assert "Current scope · 103 candidates" in visual_item(
            window.contentItem(), "preparedScopeCounts").property("text")
        identity = next(iter(review.state["items"]))
        click(window, "viewFrame_" + identity)
        idle(desktop)
        assert review.state["viewed"]["provenance"]["originalTime"] == "00:00:12.525"
        assert visual_item(window.contentItem(), "frameProvenanceScroll").isVisible()
        status = visual_item(window.contentItem(), "frameEffectiveStatus")
        assert "Effective: Selected" in status.property("text")
        bar = visual_item(window.contentItem(), "frameProvenanceScrollbar")
        viewport = visual_item(window.contentItem(), "frameProvenanceScroll")
        assert bar.isVisible() and bar.height() >= viewport.height() - 2
        assert bar.x() >= viewport.width() - bar.width() - 2
        review.setScope("group/empty")
        idle(desktop)
        empty = visual_item(window.contentItem(), "frameReviewEmptyState").property("text")
        assert "No prepared candidates in this scope" in empty and "Empty saved group" in empty
        assert not review.state["viewedId"] and not engine.load_errors
    finally:
        dispose(engine)
