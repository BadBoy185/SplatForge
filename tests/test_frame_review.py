"""Manual review uses tiny synthetic artifacts, never native processing or Qt."""

from uuid import UUID, uuid4

import pytest
from test_quality_execution import sharp_prepare, with_quality
from test_source_participation import change
from test_views_execution import harness, prepare, query

from splatforge.adapters.desktop_prepare import LocalPrepareReader
from splatforge.adapters.execution_storage import ExecutionFaultHooks, LocalExecutionRepository
from splatforge.adapters.frame_review import LocalFrameReviewRepository
from splatforge.adapters.pair_workspace import LocalPairWorkspace
from splatforge.application.execution import PublicationUnresolvedError
from splatforge.application.frame_review import FrameReviewService
from splatforge.application.pairs import PairsService
from splatforge.application.projects import StaleProjectRevisionError
from splatforge.bootstrap import build_project_service
from splatforge.core.frame_review import FrameReviewIntent, ReviewedSelectedViewSet, reviewed_digest
from splatforge.core.media import MediaType
from splatforge.core.pairs import ExhaustiveSettings, PairResourceLimits, project_pairing_universe


def service(value):
    return FrameReviewService(LocalFrameReviewRepository(value.execution))


def apply(value, page, ids, decision):
    return service(value).apply(
        value.root,
        page.run_id,
        tuple(ids),
        decision,
        expected_project_id=page.project_id,
        expected_revision=page.project_revision,
        expected_review_digest=page.review_digest,
    )


@pytest.mark.parametrize("sharpest", [False, True])
def test_review_all_candidates_keep_exclude_reset_and_reopen(tmp_path, sharpest):
    value = harness(tmp_path)
    if sharpest:
        with_quality(value)
    run = sharp_prepare(value) if sharpest else prepare(value)
    sources = {p: p.read_bytes() for p in value.source_paths}
    auto_path = value.root / run.selected_artifact.manifest_path
    immutable = {p: p.read_bytes() for p in auto_path.parent.iterdir()}
    use_case = service(value)
    page = use_case.page(value.root, run.run_id, filter="all")
    assert page.candidate_count == 4 and page.selected_count == 3 and page.rejected_count == 1
    assert [i.view_id.int for i in page.items] == sorted(i.view_id.int for i in page.items)
    rejected = next(i for i in page.items if not i.included)
    assert rejected.reason
    if not sharpest:
        assert rejected.reason == "Automatic reason not recorded"
    kept = apply(value, page, [rejected.view_id], "include")
    assert kept.effective_run_id != run.run_id
    reopened = FrameReviewService(LocalFrameReviewRepository())
    page = reopened.page(value.root, run.run_id, filter="all")
    assert (page.selected_count, page.rejected_count, page.manual_count) == (4, 0, 1)
    assert next(i for i in page.items if i.view_id == rejected.view_id).reason == "Kept manually"
    candidate_handle = value.execution.resolve_run_output(
        value.root,
        kept.effective_run_id,
        "candidate_views",
        "candidate_set",
    )
    effective_handle = value.execution.resolve_run_output(
        value.root,
        kept.effective_run_id,
        "selected_views",
        "selected_set",
    )
    candidate, effective = value.execution.load_pairing_inputs(
        value.root,
        candidate_handle,
        effective_handle,
    )
    assert isinstance(effective, ReviewedSelectedViewSet)
    assert len(project_pairing_universe(candidate, effective).views) == 4
    excluded = apply(value, page, [rejected.view_id], "exclude")
    assert excluded.review_digest != kept.review_digest
    page = use_case.page(value.root, run.run_id, filter="all")
    assert (page.selected_count, page.manual_count) == (3, 1)
    reset = apply(value, page, [rejected.view_id], "automatic")
    assert reset.effective_run_id == run.run_id
    page = use_case.page(value.root, run.run_id, filter="all")
    assert (page.selected_count, page.manual_count) == (3, 0)
    assert reset.review_digest == page.review_digest
    assert sources == {p: p.read_bytes() for p in value.source_paths}
    assert immutable == {p: p.read_bytes() for p in auto_path.parent.iterdir()}
    again = apply(value, page, [rejected.view_id], "include")
    repeated_handle = value.execution.resolve_run_output(
        value.root,
        again.effective_run_id,
        "selected_views",
        "selected_set",
    )
    assert again.effective_run_id != kept.effective_run_id
    assert repeated_handle.semantic_digest == effective_handle.semantic_digest
    assert reviewed_digest(effective) == repeated_handle.recipe_key


def test_atomic_invalid_uuid_stale_identity_digest_and_independent_cached_runs(tmp_path):
    value = harness(tmp_path)
    first, second = prepare(value), prepare(value)
    assert second.cache_hits
    use_case = service(value)
    page = use_case.page(value.root, first.run_id, filter="all")
    runs_before = query(value.root, "SELECT run_id FROM runs")
    for expected in (
        {"expected_project_id": uuid4()},
        {"expected_revision": page.project_revision + 1},
        {"expected_review_digest": "f" * 64},
    ):
        kwargs = dict(
            expected_project_id=page.project_id,
            expected_revision=page.project_revision,
            expected_review_digest=page.review_digest,
        )
        kwargs.update(expected)
        with pytest.raises(StaleProjectRevisionError):
            use_case.apply(value.root, first.run_id, (page.items[0].view_id,), "exclude", **kwargs)
    with pytest.raises(ValueError, match="unknown candidate UUID"):
        apply(value, page, [page.items[0].view_id, uuid4()], "exclude")
    assert query(value.root, "SELECT run_id FROM runs") == runs_before
    apply(value, page, [page.items[0].view_id], "exclude")
    independent = use_case.page(value.root, second.run_id, filter="all")
    assert independent.manual_count == 0 and independent.effective_run_id == second.run_id
    with pytest.raises(StaleProjectRevisionError):
        apply(value, page, [page.items[0].view_id], "include")


def test_pagination_neighbors_anchor_and_excluding_all_candidates(tmp_path):
    value = harness(tmp_path)
    run = prepare(value)
    use_case = service(value)
    full = use_case.page(value.root, run.run_id, filter="all")
    second = use_case.page(value.root, run.run_id, filter="all", offset=1, limit=1)
    assert second.items[0].previous_view_id == full.items[0].view_id
    assert second.items[0].next_view_id == full.items[2].view_id
    anchor = use_case.page(
        value.root, run.run_id, filter="all", limit=1, anchor_view_id=full.items[3].view_id
    )
    assert anchor.offset == 3 and anchor.items[0].next_view_id is None
    apply(value, full, [i.view_id for i in full.items], "exclude")
    empty = use_case.page(value.root, run.run_id, offset=1000)
    assert empty.items == () and empty.offset == 0 and empty.total == 0
    rejected = use_case.page(value.root, run.run_id, filter="rejected")
    assert rejected.total == 4 and rejected.rejected_count == 4
    apply(value, rejected, [i.view_id for i in rejected.items], "automatic")
    assert use_case.page(value.root, run.run_id).selected_count == 3
    for limit in (0, 101):
        with pytest.raises(ValueError, match="limit"):
            use_case.page(value.root, run.run_id, limit=limit)


def test_unknown_review_schema_preserves_unrelated_saves_and_refuses_operations(tmp_path):
    value = harness(tmp_path)
    run = prepare(value)
    projects = build_project_service()
    document = projects.open(value.root)
    future = FrameReviewIntent.model_validate(
        {
            "schema_version": 999,
            "bindings": {"future": [1, {"x": True}]},
            "future": "retained",
        }
    )
    document = projects.save(value.root, document.model_copy(update={"frame_review": future}))
    document = projects.save(value.root, document.model_copy(update={"label": "Renamed"}))
    assert projects.open(value.root).frame_review == future
    with pytest.raises(ValueError, match="Unsupported frame review schema"):
        service(value).page(value.root, run.run_id)


def test_project_save_failure_leaves_committed_head_authoritative(tmp_path, monkeypatch):
    value = harness(tmp_path)
    run = prepare(value)
    page = service(value).page(value.root, run.run_id, filter="all")

    def fail(*args, **kwargs):
        raise OSError("Synthetic CAS write failure")

    monkeypatch.setattr(value.execution._project_store, "save_under_lease", fail)
    with pytest.raises(OSError, match="CAS write failure"):
        apply(value, page, [page.items[0].view_id], "exclude")
    reopened = service(value).page(value.root, run.run_id, filter="all")
    assert reopened == page
    assert len(query(value.root, "SELECT run_id FROM runs WHERE status='succeeded'")) == 2


def test_moved_publication_recovery_does_not_commit_unsaved_review_head(tmp_path):
    value = harness(tmp_path)
    run = prepare(value)
    page = service(value).page(value.root, run.run_id, filter="all")

    def fail(_path):
        raise OSError("Synthetic death after move")

    value.execution._fault_hooks = ExecutionFaultHooks(after_artifact_move=fail)
    with pytest.raises(PublicationUnresolvedError):
        apply(value, page, [page.items[0].view_id], "exclude")
    pending = query(value.root, "SELECT run_id FROM runs WHERE status='running'")[0][0]
    repository = LocalExecutionRepository()
    with repository.writer(value.root, owner_token=uuid4(), operation="test-review-recovery"):
        recovered = repository.recover_run(value.root, run_id=UUID(pending))
    assert recovered.status == "succeeded" and len(recovered.adopted_attempts) == 1
    assert service(value).page(value.root, run.run_id, filter="all") == page


def test_non_succeeded_preparation_runs_are_refused(tmp_path):
    value = harness(tmp_path)
    value.materializer.mode = "unresolved"
    incomplete = prepare(value)
    assert incomplete.status == "interrupted"
    with pytest.raises(ValueError, match="succeeded views run"):
        service(value).page(value.root, incomplete.run_id)


def test_single_photo_review_does_not_require_pairing_minimum(tmp_path):
    value = harness(tmp_path)
    document = build_project_service().open(value.root)
    inventory = value.media.load_inventory(value.root, document.inventory_reference)
    video = next(s.source_id for s in inventory.sources if s.media_type == MediaType.VIDEO)
    change(value.root, (video,), included=False)
    run = prepare(value)
    assert run.candidate_count == 1
    page = service(value).page(value.root, run.run_id)
    apply(value, page, (page.items[0].view_id,), "exclude")
    page = service(value).page(value.root, run.run_id, filter="rejected")
    assert (page.selected_count, page.rejected_count, page.total) == (0, 1, 1)


def test_pairs_service_consumes_explicit_effective_run_and_keeps_automatic_history(tmp_path):
    value = harness(tmp_path)
    run = prepare(value)
    pairs = PairsService(value.execution, LocalPairWorkspace())
    assert pairs.validate_views_input(value.root, run.run_id) == 3
    original = pairs.build(
        value.root,
        views_run_id=run.run_id,
        settings=ExhaustiveSettings(),
        resource_limits=PairResourceLimits(),
    )
    page = service(value).page(value.root, run.run_id, filter="all")
    rejected = next(i for i in page.items if not i.included)
    result = apply(value, page, (rejected.view_id,), "include")
    assert pairs.validate_views_input(value.root, result.effective_run_id) == 4
    reviewed = pairs.build(
        value.root,
        views_run_id=result.effective_run_id,
        settings=ExhaustiveSettings(),
        resource_limits=PairResourceLimits(),
    )
    assert original.selected_view_count == 3 and original.pair_count == 3
    assert reviewed.status == "succeeded" and not reviewed.cache_hit
    assert reviewed.selected_view_count == 4 and reviewed.pair_count == 6
    assert original.pair_set_artifact.recipe_key != reviewed.pair_set_artifact.recipe_key
    assert pairs.validate_views_input(value.root, run.run_id) == 3
    historical = pairs.build(
        value.root,
        views_run_id=run.run_id,
        settings=ExhaustiveSettings(),
        resource_limits=PairResourceLimits(),
    )
    assert historical.cache_hit and historical.pair_set_artifact == original.pair_set_artifact


def test_prepare_history_survives_twenty_five_review_publications(tmp_path, monkeypatch):
    value = harness(tmp_path)
    base = prepare(value)
    cached = prepare(value)
    assert cached.cache_hits and len(value.materializer.calls) == 2
    use_case = service(value)
    page = use_case.page(value.root, base.run_id, filter="all")
    rejected = next(item for item in page.items if not item.included)
    expected_revision = page.project_revision
    expected_digest = page.review_digest
    for index in range(25):
        saved = use_case.apply(
            value.root, base.run_id, (rejected.view_id,),
            "include" if index % 2 == 0 else "exclude",
            expected_project_id=page.project_id,
            expected_revision=expected_revision,
            expected_review_digest=expected_digest,
        )
        expected_revision, expected_digest = saved.project_revision, saved.review_digest
    assert query(value.root, "SELECT count(*) FROM runs WHERE status='succeeded'") == [(27,)]
    reader = LocalPrepareReader()
    inspected = []
    summary = reader.summary

    def record_summary(root, run_id):
        inspected.append(run_id)
        return summary(root, run_id)

    monkeypatch.setattr(reader, "summary", record_summary)
    results = reader.results(value.root)
    assert [result.run_id for result in results] == [cached.run_id, base.run_id]
    assert inspected == [cached.run_id, base.run_id]
    reopened = FrameReviewService(LocalFrameReviewRepository()).page(
        value.root, base.run_id, filter="all",
    )
    assert (reopened.selected_count, reopened.manual_count) == (4, 1)
    assert reopened.project_revision == expected_revision
    assert reopened.review_digest == expected_digest
    assert next(item for item in reopened.items if item.view_id == rejected.view_id).decision == (
        "include"
    )
