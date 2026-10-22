from __future__ import annotations

import json
from pathlib import Path

import pytest
from progress_helpers import FakeClock
from test_quality_execution import FakeQualityAssessor, sharp_prepare
from test_views_execution import harness, prepare, query

from splatforge.adapters.execution_storage import LocalExecutionRepository
from splatforge.adapters.pair_workspace import LocalPairWorkspace
from splatforge.adapters.performance import LocalPerformanceHistory
from splatforge.adapters.project_storage import LocalProjectStore
from splatforge.adapters.view_workspace import LocalViewWorkspace
from splatforge.application.pairs import PairsService
from splatforge.application.progress import ProgressSupport
from splatforge.application.progress_reader import RunProgressService
from splatforge.application.views import ViewsService
from splatforge.application.work_models import analyzed_megapixels, views_progress_plan
from splatforge.core.pairs import ExhaustiveSettings, PairResourceLimits, SequentialSettings
from splatforge.core.progress import ExecutionHardwareProfile, ProgressStatus


def progress_events(root: Path, run_id: object) -> list[dict[str, object]]:
    return [
        event
        for line in (root / "runs" / str(run_id) / "events.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if (event := json.loads(line))["code"] == "progress.snapshot"
    ]


def support(tmp_path: Path, clock: FakeClock) -> ProgressSupport:
    return ProgressSupport(
        clock=clock,
        history=LocalPerformanceHistory(tmp_path / "worker-local" / "performance.sqlite"),
        hardware=ExecutionHardwareProfile(
            platform_family="windows", cpu_family="test_cpu", logical_cpus=8, device="cpu"
        ),
    )


class TimedViewWorkspace(LocalViewWorkspace):
    def __init__(self, clock: FakeClock) -> None:
        super().__init__(free_bytes=lambda _path: 10**9)
        self.clock = clock

    def write_selected_metadata(self, *args: object) -> None:
        self.clock.advance(1)
        super().write_selected_metadata(*args)


def test_m3_m4_m6_learn_only_committed_work_and_cache_remains_identical(tmp_path: Path) -> None:
    value = harness(tmp_path)
    clock = FakeClock()
    progress = support(tmp_path, clock)
    quality = FakeQualityAssessor()
    quality.on_measure = lambda _count: clock.advance(1)
    value.materializer.on_call = lambda _control: clock.advance(2)
    value.service = ViewsService(
        value.execution,
        value.media,
        value.sources,
        value.materializer,
        TimedViewWorkspace(clock),
        quality,
        progress=progress,
    )
    first = sharp_prepare(value)
    assert first.status == "succeeded"
    assert progress.history.statistics().sample_count == 3
    route = value.execution.read_progress_evidence(value.root, first.run_id).snapshot.route
    broken_sources = tuple(
        source.model_copy(update={"probe": source.probe.model_copy(update={"duration": None})})
        for source in route.sources
    )
    unavailable = views_progress_plan(
        route.model_copy(update={"sources": broken_sources}), progress.hardware
    )
    assert all(stage.work.total is None for stage in unavailable)
    assert views_progress_plan(route, progress.hardware)[0].signature.backend.adapter_version == 2
    assert analyzed_megapixels(1000, 500, 64) == 64 * 32 / 1_000_000
    assert analyzed_megapixels(500, 1000, 64) == 64 * 32 / 1_000_000
    events = progress_events(value.root, first.run_id)
    nodes = {event["node_id"] for event in events}
    assert {"candidate_views", "quality_assessment", "selected_views"} <= nodes
    observations = [
        event["details"]["observation"] for event in events if "observation" in event["details"]
    ]
    quality_work = [
        item for item in observations if item["work"]["node_id"] == "quality_assessment"
    ]
    assert quality_work[-1]["work"]["unit"] == "megapixels"
    assert quality_work[-1]["completed"] > 0
    assert quality_work[-1]["diagnostics"][-1]["name"] == "completed_views"
    reader = RunProgressService(LocalExecutionRepository(project_store=LocalProjectStore()), clock)
    completed = reader.get(value.root, first.run_id)
    assert completed.status == "succeeded" and completed.fraction == 1
    assert completed.eta.likely_seconds == 0

    class TimedPairs(LocalPairWorkspace):
        def write_pair_set(self, *args: object) -> None:
            clock.advance(2)
            super().write_pair_set(*args)

    pairs = PairsService(value.execution, TimedPairs(), progress=progress)
    for settings in (SequentialSettings(), ExhaustiveSettings()):
        result = pairs.build(
            value.root,
            views_run_id=first.run_id,
            settings=settings,
            resource_limits=PairResourceLimits(),
        )
        stage = reader.get(value.root, result.run_id).stages[0]
        assert stage.status == ProgressStatus.SUCCEEDED
        assert stage.fraction == 1
        assert stage.completed == stage.work.total
        if isinstance(settings, SequentialSettings):
            assert stage.work.total == first.selected_count
        pair_route = value.execution.read_progress_evidence(
            value.root, result.run_id
        ).snapshot.route
        from splatforge.application.work_models import pairs_progress_plan

        signature = pairs_progress_plan(pair_route, progress.hardware).signature
        learned = progress.history.read(signature).samples[0]
        assert {metric.name: metric.value for metric in learned.workload}[
            "pairs"
        ] == result.pair_count
    assert progress.history.statistics().sample_count == 5
    # History can be reset and repopulated without changing a numerical recipe/output.
    assert progress.history.reset() == ()
    second = sharp_prepare(value)
    assert set(second.cache_hits) == {"candidate_views", "quality_assessment", "selected_views"}
    assert second.candidate_artifact == first.candidate_artifact
    assert second.quality_artifact == first.quality_artifact
    assert second.selected_artifact == first.selected_artifact
    cached = reader.get(value.root, second.run_id)
    assert len(cached.cached_stages) == 3
    assert all(stage.eta.likely_seconds == 0 for stage in cached.stages)
    assert progress.history.statistics().sample_count == 0
    cached_pair = pairs.build(
        value.root,
        views_run_id=second.run_id,
        settings=ExhaustiveSettings(),
        resource_limits=PairResourceLimits(),
    )
    assert cached_pair.cache_hit
    assert reader.get(value.root, cached_pair.run_id).eta.likely_seconds == 0
    assert progress.history.statistics().sample_count == 0


def test_second_process_reads_running_and_requested_accepted_cancellation(tmp_path: Path) -> None:
    value = harness(tmp_path, mixed=False)
    clock = FakeClock()
    progress = support(tmp_path, clock)
    value.service = ViewsService(
        value.execution,
        value.media,
        value.sources,
        value.materializer,
        TimedViewWorkspace(clock),
        progress=progress,
    )
    states = []
    read_repository = LocalExecutionRepository(project_store=LocalProjectStore())
    reader = RunProgressService(read_repository, clock)

    def cancel(control) -> None:
        run_id = query(value.root, "SELECT run_id FROM runs")[-1][0]
        from uuid import UUID

        run_id = UUID(run_id)
        live = reader.get(value.root, run_id)
        assert live.current_node_id == "candidate_views"
        assert live.current_stage.status == ProgressStatus.RUNNING
        read_repository.request_cancellation(value.root, run_id=run_id)
        states.append(reader.get(value.root, run_id))
        assert control.is_cancelled()
        states.append(reader.get(value.root, run_id))
        clock.advance(1)

    value.materializer.on_call = cancel
    result = prepare(value)
    assert result.status == "cancelled"
    assert [state.status for state in states] == ["cancellation_requested", "stopping"]
    assert all(state.eta.likely_seconds is None for state in states)
    assert all(state.current_stage.eta.likely_seconds is None for state in states)
    final = reader.get(value.root, result.run_id)
    assert final.status == "cancelled"
    assert final.eta.likely_seconds is None
    assert progress.history.statistics().sample_count == 0


@pytest.mark.parametrize("mode", ["cancelled", "unresolved", "failed"])
def test_unsuccessful_attempts_never_teach_history(tmp_path: Path, mode: str) -> None:
    value = harness(tmp_path, mixed=False)
    clock = FakeClock()
    progress = support(tmp_path, clock)
    value.service = ViewsService(
        value.execution,
        value.media,
        value.sources,
        value.materializer,
        TimedViewWorkspace(clock),
        progress=progress,
    )
    value.materializer.mode = mode

    def execute(_control) -> None:
        clock.advance(9)
        if mode == "cancelled":
            from uuid import UUID

            run_id = UUID(query(value.root, "SELECT run_id FROM runs")[-1][0])
            value.execution.request_cancellation(value.root, run_id=run_id)
            assert _control.is_cancelled()
        if mode == "failed":
            raise ValueError("test backend failure")

    value.materializer.on_call = execute
    if mode == "failed":
        with pytest.raises(ValueError, match="backend failure"):
            prepare(value)
    else:
        prepare(value)
    assert progress.history.statistics().sample_count == 0


def test_history_failure_and_event_failure_leave_numerical_outputs_valid(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = harness(tmp_path, mixed=False)
    clock = FakeClock()
    progress = support(tmp_path, clock)
    progress.history.path.parent.mkdir()
    progress.history.path.write_bytes(b"corrupt")
    original = value.execution.append_event

    def append(*args: object, **kwargs: object):
        if kwargs.get("code") == "progress.snapshot":
            raise OSError("injected optional telemetry failure")
        return original(*args, **kwargs)

    monkeypatch.setattr(value.execution, "append_event", append)
    value.materializer.on_call = lambda _control: clock.advance(1)
    value.service = ViewsService(
        value.execution,
        value.media,
        value.sources,
        value.materializer,
        TimedViewWorkspace(clock),
        progress=progress,
    )
    result = prepare(value)
    assert result.status == "succeeded"
    assert result.candidate_artifact is not None and result.selected_artifact is not None
    assert {warning.code for warning in result.warnings} >= {
        "history.unavailable",
        "progress.append_failed",
    }
    assert value.execution.load_selected_views(
        value.root, result.selected_artifact
    ).total_selected_count
