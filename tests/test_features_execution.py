"""Native fixture through application, immutable storage, cache and recovery."""

import json

import pytest
from feature_helpers import NativeFixture
from test_views_execution import harness, prepare, query

from splatforge.adapters.colmap_features import hash_file
from splatforge.adapters.execution_storage import ExecutionFaultHooks, LocalExecutionRepository
from splatforge.adapters.fake_stages import LocalFakeStages
from splatforge.adapters.project_storage import LocalProjectStore
from splatforge.application.execution import FakeExecutionService, PublicationUnresolvedError
from splatforge.application.features import FeaturesService
from splatforge.application.progress import ProgressSupport
from splatforge.application.progress_reader import RunProgressService
from splatforge.core.features import FeatureResourceLimits, resolve_extraction_settings


def build(value, views, fixture, *, variant="SIFT", repository=None, progress=None, **kwargs):
    service = FeaturesService(repository or value.execution, fixture.adapter(), progress=progress)
    return service.extract(
        value.root,
        views_run_id=views.run_id,
        settings=resolve_extraction_settings(variant),
        colmap=fixture.exe,
        model_directory=fixture.model_root,
        **kwargs,
    )


@pytest.mark.parametrize("variant", ["SIFT", "ALIKED_N16ROT", "ALIKED_N32", "LOMA_B", "LOMA_B128"])
def test_publication_cache_and_immutable_upstream(tmp_path, variant):
    value, fixture = harness(tmp_path), NativeFixture(tmp_path)
    views = prepare(value)
    original = {p: hash_file(p) for p in (value.root / "artifacts").rglob("*") if p.is_file()}
    result = build(value, views, fixture, variant=variant)
    assert result.status == "succeeded" and not result.cache_hit
    assert result.selected_view_count == 3 and result.total_feature_count == 9
    parsed = value.execution.load_local_features(value.root, result.feature_artifact)
    selected = value.execution.load_selected_views(value.root, views.selected_artifact)
    assert {v.view_id for v in parsed.views} == {v.view_id for v in selected.selected_views}
    second = build(value, views, fixture, variant=variant)
    assert second.cache_hit and second.feature_artifact == result.feature_artifact
    assert all(hash_file(p) == digest for p, digest in original.items())
    assert query(
        value.root, "SELECT count(*) FROM attempts WHERE run_id=?", (str(second.run_id),)
    ) == [(0,)]
    progress = RunProgressService(value.execution).get(value.root, result.run_id)
    assert progress.stages[0].work.unit == "views"
    assert progress.stages[0].work.work_model_id == "features.selected_views_v1"
    assert progress.stages[0].work.total == 3


def test_invalidation_corrupt_cache_selected_pixels_and_pair_settings(tmp_path):
    value, fixture = harness(tmp_path), NativeFixture(tmp_path)
    views = prepare(value)
    first = build(value, views, fixture)
    # Saved matcher/pair settings are irrelevant to explicit local extraction.
    from splatforge.bootstrap import build_project_service

    service = build_project_service()
    document = service.open(value.root)
    document.settings.pair_selection.settings["forward_neighbors"] = 99
    document.settings.feature_matching.settings["future_threshold"] = 0.3
    service.save(value.root, document)
    assert build(value, views, fixture).cache_hit
    learned = build(value, views, fixture, variant="ALIKED_N16ROT")
    assert learned.feature_artifact.recipe_key != first.feature_artifact.recipe_key
    path = (value.root / first.feature_artifact.manifest_path).parent / "features.db"
    path.write_bytes(b"corrupt")
    rebuilt = build(value, views, fixture)
    assert not rebuilt.cache_hit and rebuilt.feature_artifact != first.feature_artifact
    changed = prepare(value, target="2")
    assert not build(value, changed, fixture).cache_hit


@pytest.mark.parametrize(
    "mode",
    ["timeout", "failed", "oom", "extra", "missing", "dimension", "counts", "family", "forced"],
)
def test_failure_never_publishes_or_teaches(tmp_path, mode):
    value, fixture = harness(tmp_path), NativeFixture(tmp_path)
    views = prepare(value)
    fixture.mode = mode
    with pytest.raises(ValueError):
        build(value, views, fixture)
    assert query(
        value.root,
        "SELECT count(*) FROM artifacts WHERE artifact_type='features.local_feature_set'",
    ) == [(0,)]
    assert query(value.root, "SELECT status FROM runs ORDER BY created_at DESC LIMIT 1") == [
        ("failed",)
    ]


def test_durable_cancellation_and_unresolved_teardown(tmp_path):
    value, fixture = harness(tmp_path), NativeFixture(tmp_path)
    views = prepare(value)

    def cancel(control):
        value.execution.request_cancellation(value.root, run_id=control.run)
        assert control.is_cancelled()

    fixture.on_extract = cancel
    fixture.mode = "cancelled"
    assert build(value, views, fixture).status == "cancelled"
    fixture.on_extract = None
    fixture.mode = "unresolved"
    with pytest.raises(ValueError, match="teardown"):
        build(value, views, fixture)
    assert query(
        value.root, "SELECT teardown_state FROM attempts ORDER BY started_at DESC LIMIT 1"
    ) == [("unresolved",)]
    with pytest.raises(ValueError):
        build(value, views, fixture)


def test_budget_fails_before_probe_and_corrupt_upstream(tmp_path):
    value, fixture = harness(tmp_path), NativeFixture(tmp_path)
    views = prepare(value)
    with pytest.raises(ValueError, match="budget"):
        build(value, views, fixture, resource_limits=FeatureResourceLimits(max_views=1))
    assert not fixture.requests
    path = (value.root / views.candidate_artifact.manifest_path).parent / "images"
    next(path.iterdir()).write_bytes(b"broken")
    with pytest.raises(ValueError):
        build(value, views, fixture)
    assert not fixture.requests


def test_changed_selected_pixels_invalidate_with_same_view_ids(tmp_path, monkeypatch):
    import io

    import test_views_execution as upstream
    from PIL import Image

    value, fixture = harness(tmp_path), NativeFixture(tmp_path)
    first_views = prepare(value)
    first = build(value, first_views, fixture)

    def pixels(width, height):
        with io.BytesIO() as stream:
            Image.new("RGB", (width, height), (90, 80, 10)).save(stream, format="PNG")
            return stream.getvalue()

    monkeypatch.setattr(upstream, "png", pixels)
    value.materializer.backend = value.materializer.backend.model_copy(update={"sha256": "e" * 64})
    next_views = prepare(value)
    changed = build(value, next_views, fixture)
    old = value.execution.load_local_features(value.root, first.feature_artifact)
    new = value.execution.load_local_features(value.root, changed.feature_artifact)
    assert {v.view_id for v in old.views} == {v.view_id for v in new.views}
    assert (
        not changed.cache_hit
        and first.feature_artifact.recipe_key != changed.feature_artifact.recipe_key
    )


def test_interrupted_attempt_recovery_requires_stage_restart(tmp_path, monkeypatch):
    value, fixture = harness(tmp_path), NativeFixture(tmp_path)
    views = prepare(value)
    original = value.execution.write_feature_metadata

    def crash(*args):
        raise KeyboardInterrupt("fixture interruption before publication")

    monkeypatch.setattr(value.execution, "write_feature_metadata", crash)
    with pytest.raises(KeyboardInterrupt):
        build(value, views, fixture)
    run_id = query(value.root, "SELECT run_id FROM runs WHERE status='running'")[0][0]
    from uuid import UUID

    recovered = FakeExecutionService(value.execution, LocalFakeStages()).recover(
        value.root, UUID(run_id)
    )
    assert recovered.status == "interrupted"
    monkeypatch.setattr(value.execution, "write_feature_metadata", original)
    assert not build(value, views, fixture).cache_hit


def test_publication_recovery_adopts_only_valid_frozen_route(tmp_path):
    value, fixture = harness(tmp_path), NativeFixture(tmp_path)
    views = prepare(value)

    def fail(_path):
        raise OSError("publication fixture crash")

    repository = LocalExecutionRepository(
        project_store=LocalProjectStore(), fault_hooks=ExecutionFaultHooks(after_artifact_move=fail)
    )
    with pytest.raises(PublicationUnresolvedError):
        build(value, views, fixture, repository=repository)
    run_id = query(value.root, "SELECT run_id FROM runs WHERE status='running'")[0][0]
    from uuid import UUID

    recovered = FakeExecutionService(value.execution, LocalFakeStages()).recover(
        value.root, UUID(run_id)
    )
    assert recovered.status == "succeeded" and len(recovered.adopted_attempts) == 1


def test_progress_history_only_success_with_failure_degradation(tmp_path):
    from splatforge.adapters.performance import LocalPerformanceHistory

    history = LocalPerformanceHistory(tmp_path / "private-history.sqlite")
    support = ProgressSupport(history=history)
    value, fixture = harness(tmp_path), NativeFixture(tmp_path)
    views = prepare(value)
    first = build(value, views, fixture, progress=support)
    assert history.statistics().sample_count == 1
    assert build(value, views, fixture, progress=support).cache_hit
    assert history.statistics().sample_count == 1
    events = [
        json.loads(line)
        for line in (value.root / "runs" / str(first.run_id) / "events.jsonl")
        .read_text()
        .splitlines()
    ]
    snapshots = [e["details"]["snapshot"] for e in events if e["code"] == "progress.snapshot"]
    running = [s["stages"][0] for s in snapshots if s["stages"][0]["status"] == "running"]
    assert running and all(s["fraction"] == 0 for s in running)
    assert all(s["completed"] == 0 for s in running)
