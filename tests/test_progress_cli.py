from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID, uuid4

from progress_helpers import FakeClock, plan, sample
from typer.testing import CliRunner

from splatforge.adapters.execution_storage import LocalExecutionRepository
from splatforge.adapters.performance import LocalPerformanceHistory
from splatforge.adapters.project_storage import LocalProjectStore
from splatforge.application.progress import PerformanceService, ProgressSession
from splatforge.application.progress_reader import RunProgressService
from splatforge.bootstrap import build_execution_service, build_project_service
from splatforge.cli.app import app
from splatforge.core.execution import RunSnapshot
from splatforge.core.fake_pipeline import build_fake_route, sequence_recipe_key
from splatforge.core.progress import ProgressMode, ProgressStatus


def test_old_run_show_and_progress_without_rewriting_historical_events(tmp_path: Path) -> None:
    root = tmp_path / "old project Ž"
    build_project_service().create(root, "old")
    service = build_execution_service()
    result = service.run(root)
    path = root / "runs" / str(result.run_id) / "events.jsonl"
    original = path.read_bytes()
    runner = CliRunner()
    shown = runner.invoke(app, ["run", "show", str(root), str(result.run_id)])
    assert shown.exit_code == 0, shown.output
    assert "progress.unavailable" in json.loads(shown.stdout)["progress"]["warnings"]
    progress = runner.invoke(app, ["run", "progress", str(root), str(result.run_id), "--json"])
    assert progress.exit_code == 0, progress.output
    payload = json.loads(progress.stdout)
    assert payload["status"] == "succeeded"
    assert payload["progress_schema_version"] == 1
    assert path.read_bytes() == original
    human = runner.invoke(app, ["run", "progress", str(root), str(result.run_id)])
    assert human.exit_code == 0
    assert "succeeded" in human.stdout
    assert "Cached: none" in human.stdout
    assert "progress.unavailable" in human.stdout


def test_cli_renders_stage_range_speed_unknown_and_cached_status(
    tmp_path: Path,
    monkeypatch,
) -> None:
    clock = FakeClock()
    mapping = plan(node="mapping")
    mapping = mapping.model_copy(
        update={
            "work": mapping.work.model_copy(
                update={
                    "total": None,
                    "mode": ProgressMode.INDETERMINATE,
                }
            )
        }
    )
    session = ProgressSession(
        uuid4(),
        (
            plan(),
            plan(node="cached"),
            mapping,
            plan(node="skip").model_copy(update={"disposition": "skipped"}),
        ),
        clock=clock,
        emit=lambda *args: None,
    )
    session.cached("cached")
    session.start("work", uuid4())
    clock.advance(5)
    session.report("work", 500)

    class Reader:
        def get(self, *args):
            return session.snapshot()

    monkeypatch.setattr("splatforge.cli.app.build_run_progress_service", lambda: Reader())
    runner = CliRunner()
    result = runner.invoke(app, ["run", "progress", str(tmp_path), str(session.run_id)])
    assert result.exit_code == 0, result.output
    assert "test_processing / processing" in result.stdout
    assert "500.0/1000.0 work" in result.stdout
    assert "100 work/s" in result.stdout
    assert "confidence" in result.stdout
    assert "Cached: cached" in result.stdout
    assert "Skipped: skip" in result.stdout
    assert "Unknown ETA stages: mapping" in result.stdout
    result = runner.invoke(app, ["run", "progress", str(tmp_path), str(session.run_id), "--json"])
    assert result.exit_code == 0
    value = json.loads(result.stdout)
    assert value["fraction"] is None
    assert value["current_stage"]["throughput"] == 100
    assert value["current_stage"]["eta"]["lower_seconds"] <= 5
    assert value["current_stage"]["eta"]["upper_seconds"] >= 5


def test_progress_events_cannot_override_sqlite_or_resume_crashed_work(tmp_path: Path) -> None:
    root = tmp_path / "crashed"
    document = build_project_service().create(root, "crashed")
    repo = LocalExecutionRepository(project_store=LocalProjectStore())
    clock = FakeClock()
    run_id = uuid4()
    route = build_fake_route(start=0, count=3, factor=2)
    frozen = RunSnapshot(
        run_id=run_id,
        project_id=document.project_id,
        project_revision=document.revision,
        owner_token=uuid4(),
        created_at=clock.utcnow(),
        project_intent=document,
        route=route,
    )
    repo.create_run(root, frozen)
    attempt = repo.begin_attempt(
        root,
        run_id=run_id,
        node_id="numbers",
        output_name=route.sequence.output.output_name,
        recipe_key=sequence_recipe_key(start=0, settings=route.sequence.settings),
        input_artifact_ids=(),
        literal_inputs={"start": 0},
    )
    session = ProgressSession(
        run_id,
        (plan(node="numbers"),),
        clock=clock,
        emit=lambda node, attempt, details: repo.append_event(
            root,
            run_id,
            code="progress.snapshot",
            node_id=node,
            attempt_id=attempt,
            details=details,
        ),
    )
    session.start("numbers", attempt.attempt_id)
    clock.advance(9)
    session.report("numbers", 900)
    reader = RunProgressService(repo, clock)
    live = reader.get(root, run_id)
    assert live.status == "running"
    assert live.current_stage.fraction == 0.9
    clock.advance(6)
    stale = reader.get(root, run_id)
    assert stale.current_stage.stale
    assert stale.current_stage.eta.likely_seconds is None
    # Fake success telemetry must not commit publication or stage/run success.
    forged = session.snapshot().model_copy(update={"status": "succeeded", "fraction": 1})
    repo.append_event(
        root, run_id, code="progress.snapshot", details={"snapshot": forged.model_dump(mode="json")}
    )
    assert reader.get(root, run_id).status == "running"
    assert reader.get(root, run_id).stages[0].status == ProgressStatus.RUNNING
    recovered = build_execution_service().recover(root, run_id)
    assert recovered.status == "interrupted"
    final = reader.get(root, run_id)
    assert final.status == "interrupted"
    assert final.eta.likely_seconds is None
    assert final.stages[0].status == ProgressStatus.INTERRUPTED


def test_read_ignores_partial_malformed_progress_and_does_not_promote_failure(
    tmp_path: Path,
) -> None:
    root = tmp_path / "failed"
    build_project_service().create(root, "failed")
    result = build_execution_service().run(root)
    repo = LocalExecutionRepository(project_store=LocalProjectStore())
    repo.append_event(root, result.run_id, code="progress.snapshot", details={"snapshot": {}})
    path = root / "runs" / str(result.run_id) / "events.jsonl"
    with path.open("ab") as stream:
        stream.write(b'{"partial":')
    value = RunProgressService(repo, FakeClock()).get(root, result.run_id)
    assert value.status == "succeeded"
    assert "progress.malformed_event" in value.warnings
    assert "progress.unavailable" in value.warnings


def test_performance_cli_has_bounded_anonymous_stats_and_explicit_reset(
    tmp_path: Path,
    monkeypatch,
) -> None:
    history = LocalPerformanceHistory(tmp_path / "worker-local" / "performance.sqlite")
    history.record(sample())
    monkeypatch.setattr(
        "splatforge.cli.app.build_performance_service", lambda: PerformanceService(history)
    )
    runner = CliRunner()
    result = runner.invoke(app, ["performance", "show", "--json"])
    assert result.exit_code == 0
    assert json.loads(result.stdout)["sample_count"] == 1
    assert str(tmp_path) not in result.stdout
    assert runner.invoke(app, ["performance", "reset"]).exit_code == 0
    assert history.statistics().sample_count == 0
    assert not list(tmp_path.glob("project.json"))


def test_unknown_run_reports_bounded_error(tmp_path: Path) -> None:
    root = tmp_path / "empty"
    build_project_service().create(root, "empty")
    result = CliRunner().invoke(app, ["run", "progress", str(root), str(UUID(int=1)), "--json"])
    assert result.exit_code == 1
    assert "Unknown run" in result.output
