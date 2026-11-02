"""Saved source scopes/provenance use tiny generated artifacts, never Qt or native tools."""

from datetime import UTC, datetime
from fractions import Fraction
from uuid import uuid4

import pytest
from PIL import Image
from test_frame_review import apply, service
from test_quality_execution import sharp_prepare, with_quality
from test_video_usage_execution import edit
from test_views_execution import FakeProbe, harness, limits, png, prepare, query

from splatforge.adapters.media_storage import LocalMediaRepository
from splatforge.application.frame_review_projection import review_provenance, review_scopes
from splatforge.application.media import MediaService
from splatforge.application.projects import ProjectError
from splatforge.application.views_contracts import MaterializedFrame
from splatforge.bootstrap import build_project_service
from splatforge.core.capture_metadata import CaptureMetadata
from splatforge.core.frame_review import ReviewItem, ReviewPage
from splatforge.core.logical_source_groups import LogicalSourceGroup, LogicalSourceGroups
from splatforge.core.media import (
    MediaType,
    VerificationAssurance,
    VerificationOutcome,
    VerificationPolicyId,
    VerificationResult,
)
from splatforge.core.quality import NonNegativeRational
from splatforge.core.views import RationalValue


def frozen(value, run):
    route = value.execution._load_run_snapshot(value.root, run.run_id).route
    candidate = value.execution.load_candidate_views(value.root, run.candidate_artifact)
    return route.sources, candidate


def test_scope_status_counts_pagination_neighbors_and_readonly_browsing(tmp_path, monkeypatch):
    value = harness(tmp_path)
    run = prepare(value)
    use_case = service(value)
    page = use_case.page(value.root, run.run_id, filter="all")
    rejected = next(i for i in page.items if not i.included)
    apply(value, page, [rejected.view_id], "include")
    page = use_case.page(value.root, run.run_id, filter="all")
    video = next(i.source_id for i in page.items if i.provenance.media_type == MediaType.VIDEO)
    document = build_project_service().open(value.root)
    immutable = {
        path: path.read_bytes()
        for artifact in (run.candidate_artifact, run.selected_artifact)
        for path in (value.root / artifact.manifest_path).parent.rglob("*") if path.is_file()
    }
    tables = {
        table: query(value.root, f"SELECT * FROM {table}")
        for table in ("runs", "attempts", "artifacts", "source_verifications")
    }

    def no_decode(*args, **kwargs):
        raise AssertionError("Scope browsing must not decode images")

    monkeypatch.setattr(Image, "open", no_decode)
    scope = f"source/{video}"
    scoped = use_case.page(value.root, run.run_id, scope=scope, filter="all", limit=1, offset=999)
    assert (scoped.candidate_count, scoped.selected_count, scoped.manual_count) == (4, 4, 1)
    assert (scoped.scope_candidate_count, scoped.scope_selected_count) == (3, 3)
    assert (scoped.scope_auto_selected_count, scoped.scope_manual_count) == (2, 1)
    assert scoped.scope_rejected_count == 0 and scoped.offset == 2 and scoped.total == 3
    full = use_case.page(value.root, run.run_id, scope=scope, filter="selected")
    assert {i.source_id for i in full.items} == {video}
    assert scoped.items[0].previous_view_id == full.items[1].view_id
    assert scoped.items[0].next_view_id is None
    anchored = use_case.page(
        value.root, run.run_id, scope=scope, filter="all", limit=1,
        anchor_view_id=full.items[1].view_id,
    )
    assert anchored.offset == 1 and anchored.items[0].next_view_id == full.items[2].view_id
    empty = use_case.page(value.root, run.run_id, scope=scope, filter="rejected", offset=100)
    assert empty.total == empty.offset == 0 and empty.items == ()
    assert empty.scope_candidate_count == 3 and empty.scope_manual_count == 1
    assert build_project_service().open(value.root) == document
    assert immutable == {path: path.read_bytes() for path in immutable}
    assert tables == {table: query(value.root, f"SELECT * FROM {table}") for table in tables}
    assert empty.review_digest == page.review_digest
    assert empty.effective_run_id == page.effective_run_id
    for invalid in ("group/" + str(uuid4()), "source/" + str(uuid4()), "", 7):
        with pytest.raises(ValueError, match="Unknown review scope"):
            use_case.page(value.root, run.run_id, scope=invalid)
    with pytest.raises(ValueError, match="limit"):
        use_case.page(value.root, run.run_id, scope=scope, limit=101)


def test_logical_groups_are_current_display_and_empty_groups_survive(tmp_path):
    value = harness(tmp_path)
    run = prepare(value)
    sources, _ = frozen(value, run)
    project = build_project_service()
    doc = project.open(value.root)
    group, empty = uuid4(), uuid4()
    organization = LogicalSourceGroups(
        groups=(LogicalSourceGroup(group_id=group, label="Shoot"),
                LogicalSourceGroup(group_id=empty, label="Empty")),
        source_assignments={sources[0].source_id: group},
    )
    saved = project.save(value.root, doc.model_copy(update={"logical_source_groups": organization}))
    page = service(value).page(value.root, run.run_id, filter="all", scope=f"group/{group}")
    assert page.scope_label == "Shoot"
    assert {i.source_id for i in page.items} == {sources[0].source_id}
    assert all(i.provenance.current_group_label == "Shoot" for i in page.items)
    empty_page = service(value).page(value.root, run.run_id, scope=f"group/{empty}")
    assert empty_page.items == () and empty_page.scope_candidate_count == 0
    option = next(o for o in empty_page.scopes if o.key == f"group/{empty}")
    assert option.source_count == option.candidate_count == option.selected_count == 0
    assert {o.key for o in page.scopes}.isdisjoint(f"group/{s.source_group_id}" for s in sources)
    assert project.open(value.root) == saved
    assert page.review_digest == empty_page.review_digest and page.effective_run_id == run.run_id


def test_scope_precedence_device_fallback_duplicate_names_and_exact_identity(tmp_path):
    value = harness(tmp_path)
    run = prepare(value)
    sources, candidate = frozen(value, run)
    video, photo = (next(s for s in sources if s.media_type == kind)
                    for kind in (MediaType.VIDEO, MediaType.PHOTO))
    capture = CaptureMetadata(origin="exif", make="Sony", model="Sony A7")
    photo = photo.model_copy(update={
        "original_filename": "same.png",
        "external_locator": "C:/Captured/Flight A/same.png",
        "probe": photo.probe.model_copy(update={"capture": capture}),
    })
    video = video.model_copy(update={
        "original_filename": "same.png", "external_locator": "C:/Captured/Flight B/same.png",
    })
    ids = {v.view_id for v in candidate.views}
    projection = review_scopes(
        candidate, (photo, video), LogicalSourceGroups(), ids, ids, set(), "all",
    )
    assert {o.label for o in projection.options if o.kind == "source"} == {
        "same.png · Flight A", "same.png · Flight B",
    }
    assert len({o.key for o in projection.options if o.kind == "source"}) == 2
    same_folder = video.model_copy(update={"external_locator": photo.external_locator})
    ordinals = review_scopes(
        candidate, (photo, same_folder), LogicalSourceGroups(), ids, ids, set(), "all",
    )
    assert {o.label for o in ordinals.options if o.kind == "source"} == {
        "same.png · Flight A (1)", "same.png · Flight A (2)",
    }
    assert {o.key for o in projection.options} >= {"device/sony a7", "videos"}
    group = uuid4()
    organization = LogicalSourceGroups(
        groups=(LogicalSourceGroup(group_id=group, label="User group"),),
        source_assignments={photo.source_id: group},
    )
    grouped = review_scopes(
        candidate, (photo, video), organization, ids, ids, set(), f"group/{group}",
    )
    assert grouped.source_ids == {photo.source_id}
    assert "device/sony a7" not in {o.key for o in grouped.options}
    partial = photo.model_copy(update={"probe": photo.probe.model_copy(update={
        "capture": CaptureMetadata(origin="exif", make="Sony"),
    })})
    unknown = review_scopes(
        candidate, (partial, video), LogicalSourceGroups(), ids, ids, set(), "unknown",
    )
    assert unknown.source_ids == {photo.source_id}
    stale = photo.model_copy(update={"source_revision": 2})
    with pytest.raises(ValueError, match="frozen preparation run"):
        review_scopes(candidate, (stale, video), organization, ids, ids, set(), "all")


def test_trim_provenance_keeps_absolute_pts_and_bounded_construction(tmp_path, monkeypatch):
    import splatforge.adapters.frame_review as adapter

    value = harness(tmp_path)
    edit(value, "add", "7/10", "11/10")
    run = prepare(value)
    count = []
    original = adapter.review_provenance

    def record(view, *args, **kwargs):
        count.append(view.view_id)
        return original(view, *args, **kwargs)

    monkeypatch.setattr(adapter, "review_provenance", record)
    page = service(value).page(value.root, run.run_id, filter="all", scope="videos", limit=1)
    assert len(count) == len(page.items) == 1
    full = service(value).page(value.root, run.run_id, filter="all", scope="videos")
    assert {i.provenance.timestamp.seconds() for i in full.items} == {Fraction(7, 10), Fraction(1)}
    assert {i.provenance.timestamp.pts for i in full.items} == {7, 10}
    assert all(i.provenance.timestamp.time_base.denominator == 10 for i in full.items)
    assert all((i.provenance.width, i.provenance.height, i.provenance.stream_index) == (16, 12, 0)
               for i in full.items)


def test_historical_locator_and_matching_current_relink_metadata_without_originals(tmp_path):
    value = harness(tmp_path)
    run = prepare(value)
    sources, _ = frozen(value, run)
    source = next(s for s in sources if s.media_type == MediaType.VIDEO)
    target = tmp_path / ("Moved ž " + "long name " * 9 + ".mp4")
    target.write_bytes(b"original-video")
    MediaService(value.media, value.sources, FakeProbe()).relink(
        value.root, source.source_id, target,
    )
    target.unlink()
    for path in value.source_paths:
        path.unlink()
    page = service(value).page(
        value.root, run.run_id, filter="all", scope=f"source/{source.source_id}",
    )
    for item in page.items:
        provenance = item.provenance
        assert provenance.source_name == (source.original_filename or source.display_filename)
        assert provenance.path_at_preparation == source.external_locator
        assert provenance.current_locator == str(target)
        assert provenance.current_source_state == "same_source"  # Saved identity, no fresh check.
        assert provenance.source_check is not None and provenance.source_checked_at is not None
        assert provenance.automatic_score is None


@pytest.mark.parametrize("current_state", ["revision_mismatch", "not_in_inventory", "unavailable"])
def test_missing_or_changed_current_metadata_does_not_replace_history(
    tmp_path, monkeypatch, current_state,
):
    value = harness(tmp_path)
    run = prepare(value)
    sources, _ = frozen(value, run)
    source = sources[0]
    document = build_project_service().open(value.root)
    inventory = value.media.load_current_inventory(value.root, document)

    def current(*args, **kwargs):
        if current_state == "unavailable":
            raise ProjectError("Saved inventory unreadable")
        records = tuple(
            s.model_copy(update={"source_revision": s.source_revision + 1})
            if s.source_id == source.source_id else s for s in inventory.sources
        ) if current_state == "revision_mismatch" else tuple(
            s for s in inventory.sources if s.source_id != source.source_id
        )
        return inventory.model_copy(update={"sources": records})

    monkeypatch.setattr(LocalMediaRepository, "load_current_inventory", current)
    page = service(value).page(
        value.root, run.run_id, filter="all", scope=f"source/{source.source_id}",
    )
    assert page.items
    assert all(i.provenance.current_source_state == current_state for i in page.items)
    assert all(i.provenance.current_locator is None for i in page.items)
    assert all(i.provenance.path_at_preparation == source.external_locator for i in page.items)


def test_absent_evidence_legacy_read_models_and_recorded_zero_score(tmp_path):
    value = harness(tmp_path)
    run = prepare(value)
    sources, candidate = frozen(value, run)
    source = next(s for s in sources if s.source_id == candidate.views[0].source_id)
    old_source = source.model_copy(update={"original_filename": None})
    provenance = review_provenance(
        candidate.views[0], old_source, None, inventory_available=True,
        organization=LogicalSourceGroups(),
    )
    assert provenance.source_name == source.display_filename
    assert provenance.source_check is provenance.source_checked_at is None
    assert provenance.device_label is None
    assert provenance.automatic_score is None
    zero = review_provenance(
        candidate.views[0], source, source, inventory_available=True,
        organization=LogicalSourceGroups(),
        automatic_score=NonNegativeRational(numerator=0, denominator=1),
        source_check=("missing", datetime(2026, 10, 29, tzinfo=UTC)),
    )
    assert zero.automatic_score.as_fraction() == 0 and zero.source_check == "missing"
    page = service(value).page(value.root, run.run_id, filter="all")
    missing_reason = next(i for i in page.items if not i.auto_selected)
    assert missing_reason.auto_reason == "Automatic reason not recorded"
    assert all(i.auto_reason != "Automatic reason not recorded"
               for i in page.items if i.auto_selected)
    old_item = ReviewItem.model_validate(
        page.items[0].model_dump(exclude={"source_id", "provenance"}),
    )
    assert old_item.provenance is None and old_item.source_id is None
    old_page = ReviewPage.model_validate(page.model_dump(exclude={
        "scope_key", "scope_label", "scopes", "scope_candidate_count", "scope_auto_selected_count",
        "scope_selected_count", "scope_rejected_count", "scope_manual_count",
    }))
    assert old_page.scope_key == "all" and old_page.scopes == ()
    assert old_page.scope_selected_count is None


def test_sharpest_provenance_uses_actual_saved_decision_score_and_reason(tmp_path):
    value = harness(tmp_path)
    with_quality(value)
    run = sharp_prepare(value)
    automatic = value.execution._validate_indexed_artifact(
        value.root, run.selected_artifact, metadata_only=True,
    )[2].parsed
    decisions = {d.view_id: d for d in automatic.decisions}
    page = service(value).page(value.root, run.run_id, filter="all")
    assert all(i.provenance.automatic_score == decisions[i.view_id].sharpness_score
               for i in page.items)
    assert all(i.auto_reason == decisions[i.view_id].reason.value.replace("_", " ")
               for i in page.items)
    assert page.scope_candidate_count == page.candidate_count == 4
    assert page.scope_selected_count == page.selected_count


def test_last_recorded_check_requires_exact_source_revision_and_hash(tmp_path):
    value = harness(tmp_path)
    run = prepare(value)
    sources, _ = frozen(value, run)
    source = sources[0]
    use_case = service(value)
    kwargs = {"filter": "all", "scope": f"source/{source.source_id}"}
    before = use_case.page(value.root, run.run_id, **kwargs).items[0].provenance
    assert before.source_check == "unchanged"
    result = VerificationResult(
        verification_id=uuid4(), source_id=source.source_id,
        source_revision=source.source_revision,
        expected_content_sha256=source.content_sha256,
        policy_id=VerificationPolicyId.BALANCED_LOCAL,
        checked_at=datetime(2030, 1, 1, tzinfo=UTC),
        baseline_evidence=None, current_evidence=None,
        full_hash_performed=False, rehash_reason=None,
        assurance=VerificationAssurance.UNAVAILABLE,
        outcome=VerificationOutcome.MISSING,
        diagnostic_code="synthetic_missing", diagnostic_message="Generated test evidence",
    )
    for changes in (
        {"source_revision": source.source_revision + 1},
        {"expected_content_sha256": "f" * 64},
    ):
        value.media.record_verification(value.root, result.model_copy(update={
            **changes, "verification_id": uuid4(),
        }))
        after = use_case.page(value.root, run.run_id, **kwargs).items[0].provenance
        assert after.source_check == before.source_check
        assert after.source_checked_at == before.source_checked_at
    value.media.record_verification(value.root, result)
    after = use_case.page(value.root, run.run_id, **kwargs).items[0].provenance
    assert after.source_check == "missing" and after.source_checked_at == result.checked_at
    assert after.current_source_state == "same_source"  # Inventory identity, not availability.


def test_one_hundred_item_bound_with_more_candidates(tmp_path, monkeypatch):
    import splatforge.adapters.frame_review as adapter

    value = harness(tmp_path, mixed=False)

    def materialize(source_path, source, output_directory, settings, **kwargs):
        output_directory.mkdir(parents=True)
        frames = []
        for index in range(105):
            path = output_directory / f"frame-{index:08d}.png"
            path.write_bytes(png(16, 12))
            frames.append(MaterializedFrame(
                path, index, index, RationalValue(numerator=1, denominator=100),
            ))
        return tuple(frames)

    monkeypatch.setattr(value.materializer, "materialize", materialize)
    run = prepare(value, candidate_fps="100", resource_limits=limits(count=200))
    assert run.status == "succeeded" and run.candidate_count == 105
    count = []
    original = adapter.review_provenance

    def record(view, *args, **kwargs):
        count.append(view.view_id)
        return original(view, *args, **kwargs)

    monkeypatch.setattr(adapter, "review_provenance", record)
    page = service(value).page(value.root, run.run_id, filter="all", scope="videos")
    assert len(page.items) == len(count) == 100
    assert page.total == page.scope_candidate_count == 105
    assert page.items[-1].next_view_id is not None
