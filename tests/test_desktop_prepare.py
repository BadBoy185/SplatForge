"""Prepare Data contract tests with tiny fake media and no native processing."""

from uuid import uuid4

import pytest
from test_quality_execution import sharp_prepare, with_quality
from test_source_participation import change
from test_video_usage_execution import edit
from test_views_execution import harness, prepare, query

from splatforge.adapters.desktop_prepare import LocalPrepareReader
from splatforge.application.desktop_prepare import PrepareService, preparation_request
from splatforge.application.media import MediaService
from splatforge.application.projects import StaleProjectRevisionError
from splatforge.bootstrap import build_gui_facade, build_project_service
from splatforge.core.quality import SharpestIntervalSettings
from splatforge.core.views import FixedFpsSettings, parse_fps


def service(value):
    return PrepareService(
        LocalPrepareReader(value.execution),
        MediaService(value.media, value.sources, None),
        value.service,
    )


def saved(value):
    document = build_project_service().open(value.root)
    return {"expected_project_id": document.project_id, "expected_revision": document.revision}


@pytest.mark.parametrize("sharpest", [False, True])
def test_request_resolves_only_saved_frame_slot_and_preserves_typed_settings(tmp_path, sharpest):
    value = harness(tmp_path)
    projects = build_project_service()
    document = projects.open(value.root)
    selection = (
        SharpestIntervalSettings(target_fps=parse_fps("3/2"), duplicate_lookback=13)
        if sharpest else FixedFpsSettings(target_fps=parse_fps("3/2"))
    )
    frame = document.settings.frame_selection.model_copy(update={
        "method_id": "frame_selection.sharpest_interval" if sharpest
        else "frame_selection.fixed_fps",
        "settings": selection.model_dump(mode="json"),
    })
    future = document.settings.mapping.model_copy(update={
        "method_id": "mapping.future", "settings_schema_version": 99, "settings": {"x": [1]},
    })
    document = projects.save(value.root, document.model_copy(update={
        "settings": document.settings.model_copy(update={
            "frame_selection": frame, "mapping": future,
        }),
    }))
    request = preparation_request(document)
    assert request.selection == selection
    assert request.candidate.candidate_fps.as_fraction() == (3 if sharpest else 1.5)
    assert (request.quality is not None) == sharpest
    plan = service(value).plan(value.root, **saved(value))
    assert plan.runnable and plan.request == request
    assert projects.open(value.root).settings.mapping == future


def test_legacy_request_preserves_real_supported_behavior_and_unknown_frame_refuses(tmp_path):
    value = harness(tmp_path)
    document = build_project_service().open(value.root)
    request = preparation_request(document)
    assert isinstance(request.selection, SharpestIntervalSettings)
    assert request.selection.target_fps == parse_fps("2")
    assert request.selection.min_sharpness is None
    frame = document.settings.frame_selection.model_copy(update={"method_id": "selection.future"})
    document = document.model_copy(update={
        "settings": document.settings.model_copy(update={"frame_selection": frame}),
    })
    with pytest.raises(ValueError, match="Unsupported frame selection"):
        preparation_request(document)


def test_plan_uses_saved_participation_and_video_intervals_without_source_io(tmp_path):
    value = harness(tmp_path)
    first = service(value).plan(value.root, **saved(value))
    assert (first.photo_count, first.video_count, first.used_video_count) == (1, 1, 1)
    assert first.candidate_count > 1 and first.peak_workspace_bytes > first.candidate_bytes
    assert not value.materializer.calls
    edit(value, "empty")
    second = service(value).plan(value.root, **saved(value))
    assert (second.photo_count, second.video_count, second.used_video_count) == (1, 1, 0)
    assert second.runnable and second.candidate_count == 1
    photo = next(s for s in value.source_ids if s != value.source_ids[0])
    change(value.root, (photo,), included=False)
    third = service(value).plan(value.root, **saved(value))
    assert not third.runnable and third.candidate_count is None
    assert third.warnings
    assert not query(value.root, "SELECT run_id FROM runs")


def test_run_delegates_exact_request_guard_and_cancellation_before_native_work(
    tmp_path, monkeypatch,
):
    value = harness(tmp_path)
    use_case = service(value)
    expected = saved(value)
    request = use_case.plan(value.root, **expected).request
    calls = []
    monkeypatch.setattr(value.service, "prepare", lambda *args, **kwargs: calls.append(kwargs))
    use_case.run(value.root, request, **expected)
    assert calls[0] == {
        "candidate_settings": request.candidate, "selection_settings": request.selection,
        "quality_settings": request.quality, "resource_limits": request.limits,
        "verification_policy": request.verification_policy, **expected,
    }
    with pytest.raises(ValueError, match="exact saved"):
        use_case.run(value.root, request.model_copy(update={"limits": request.limits.model_copy(
            update={"max_candidates": 1},
        )}), **expected)

    def cancelled():
        raise RuntimeError("Cancelled before delegate")

    with pytest.raises(RuntimeError, match="Cancelled before delegate"):
        use_case.run(value.root, request, **expected, cancellation_check=cancelled)
    assert len(calls) == 1
    with pytest.raises(StaleProjectRevisionError):
        use_case.run(value.root, request, **{**expected, "expected_project_id": uuid4()})


def test_revision_race_is_refused_inside_writer_before_run_creation(tmp_path):
    value = harness(tmp_path)
    with_quality(value)
    use_case = service(value)
    expected = saved(value)
    plan = use_case.plan(value.root, **expected)

    def external_save():
        projects = build_project_service()
        document = projects.open(value.root)
        projects.save(value.root, document.model_copy(update={"label": "External edit"}))

    with pytest.raises(StaleProjectRevisionError, match="Project changed"):
        use_case.run(value.root, plan.request, **expected, cancellation_check=external_save)
    assert not value.materializer.calls
    assert not query(value.root, "SELECT run_id FROM runs")


def test_reopened_results_include_cache_hit_runs_and_exclude_incomplete_or_corrupt(tmp_path):
    value = harness(tmp_path)
    first, second = prepare(value), prepare(value)
    assert second.cache_hits
    reopened = LocalPrepareReader()
    results = reopened.results(value.root)
    assert [r.run_id for r in results] == [second.run_id, first.run_id]
    assert results[0].cache_hits == ("candidate_views", "selected_views")
    assert results[0].candidate_count == first.candidate_count
    assert results[0].selected_count == first.selected_count
    assert results[0].rejected_count == 0 and results[0].quality_measured_count is None
    assert len(build_gui_facade().gallery(value.root, second.run_id)) == first.selected_count
    value.materializer.mode = "unresolved"
    incomplete = prepare(value, candidate_fps="3")
    assert incomplete.status == "interrupted"
    assert [r.run_id for r in reopened.results(value.root)] == [second.run_id, first.run_id]
    with pytest.raises(ValueError, match="succeeded"):
        reopened.summary(value.root, incomplete.run_id)
    metadata = value.root / first.selected_artifact.manifest_path
    (metadata.parent / "selected_views.json").write_bytes(b"corrupt")
    assert reopened.results(value.root) == ()
    with pytest.raises(ValueError):
        reopened.summary(value.root, first.run_id)


def test_sharpest_summary_preserves_frozen_policy_counts_and_quality_lineage(tmp_path):
    value = harness(tmp_path)
    with_quality(value)
    result = sharp_prepare(value)
    summary = LocalPrepareReader().summary(value.root, result.run_id)
    assert summary.method_id == "frame_selection.sharpest_interval"
    assert summary.request.selection.reject_duplicates is False
    assert summary.selected_count == result.selected_count
    assert summary.rejected_count == result.rejected_count
    assert summary.quality_measured_count == result.quality_measured_count
    assert summary.quality_unavailable_count == result.quality_unavailable_count


def test_history_is_bounded_and_uses_run_bindings_instead_of_artifact_producers(tmp_path):
    value = harness(tmp_path)
    first = prepare(value)
    repo = value.execution
    snapshot = repo._load_run_snapshot(value.root, first.run_id)
    with repo.writer(value.root, owner_token=uuid4(), operation="test-cache-history"):
        for _ in range(26):
            cached = snapshot.model_copy(update={"run_id": uuid4(), "owner_token": uuid4()})
            repo.create_run(value.root, cached)
            for node, output, artifact in (
                ("candidate_views", "candidate_set", first.candidate_artifact),
                ("selected_views", "selected_set", first.selected_artifact),
            ):
                repo.bind_cached_output(
                    value.root, run_id=cached.run_id, node_id=node, output_name=output,
                    artifact_id=artifact.artifact_id,
                )
            repo.mark_run_succeeded(value.root, run_id=cached.run_id)
    results = LocalPrepareReader().results(value.root)
    expected = query(
        value.root, "SELECT run_id FROM runs ORDER BY started_at DESC,run_id DESC LIMIT 25",
    )
    assert len(results) == 25
    assert [str(r.run_id) for r in results] == [r[0] for r in expected]
    assert first.run_id not in {r.run_id for r in results}
    assert all(r.cache_hits == ("candidate_views", "selected_views") for r in results)


def test_sharpest_summary_refuses_quality_binding_from_another_valid_publication(tmp_path):
    value = harness(tmp_path)
    with_quality(value)
    first = sharp_prepare(value)
    second = sharp_prepare(value, quality_max_side=512)
    with (
        value.execution.writer(value.root, owner_token=uuid4(), operation="test-wrong-binding"),
        value.execution._write_connection(value.root) as connection,
        connection,
    ):
        connection.execute(
            "UPDATE run_outputs SET artifact_id=? WHERE run_id=? "
            "AND node_id='quality_assessment'",
            (str(second.quality_artifact.artifact_id), str(first.run_id)),
        )
    with pytest.raises(ValueError, match="quality binding differs"):
        LocalPrepareReader().summary(value.root, first.run_id)
    assert [r.run_id for r in LocalPrepareReader().results(value.root)] == [second.run_id]
