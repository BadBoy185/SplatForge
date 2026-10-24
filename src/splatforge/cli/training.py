"""Thin M11 clients; active/progress/cancel/recover remain generic run commands."""

import json
from pathlib import Path
from typing import Annotated
from uuid import UUID

import typer

from splatforge.bootstrap import build_training_service
from splatforge.core.execution import TrainingRuntime
from splatforge.core.training import TrainingLimits, TrainingSettings

app = typer.Typer(no_args_is_help=True, help="External handoff and managed Gaussian training")


def bounded_json(path: Path):
    if path.stat().st_size > 4 * 1024**2:
        raise ValueError("training.config_resource_limit")
    return json.loads(path.read_text(encoding="utf-8-sig"))


def load_settings(path, strategy):
    if path:
        value = TrainingSettings.model_validate(bounded_json(path))
        if strategy and value.strategy.strategy != strategy:
            raise ValueError("training.strategy_conflicts_with_settings")
        return value
    return TrainingSettings.model_validate({"strategy": {"strategy": strategy or "default"}})


def run_command(action):
    try:
        result = action()
        typer.echo(
            result.model_dump_json(indent=2)
            if hasattr(result, "model_dump_json")
            else json.dumps(result, indent=2)
        )
    except (ValueError, OSError, KeyError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    return result


@app.command("handoff")
def handoff(
    project: Path,
    dataset_run: Annotated[UUID, typer.Option("--dataset-run")],
    lichtfeld: Path | None = None,
) -> None:
    run_command(lambda: build_training_service().handoff_report(project, dataset_run, lichtfeld))


@app.command("capability")
def capability(runtime: Path) -> None:
    run_command(
        lambda: build_training_service().capability(
            TrainingRuntime.model_validate(bounded_json(runtime))
        )
    )


@app.command("plan")
def plan(
    project: Path,
    dataset_run: Annotated[UUID, typer.Option("--dataset-run")],
    runtime: Annotated[Path, typer.Option("--runtime")],
    settings: Path | None = None,
    strategy: str | None = None,
) -> None:
    result = run_command(
        lambda: build_training_service().plan(
            project,
            dataset_run,
            TrainingRuntime.model_validate(bounded_json(runtime)),
            load_settings(settings, strategy),
        )
    )
    if not result.runnable:
        raise typer.Exit(2)


@app.command("run")
def train(
    project: Path,
    dataset_run: Annotated[UUID, typer.Option("--dataset-run")],
    runtime: Annotated[Path, typer.Option("--runtime")],
    settings: Path | None = None,
    strategy: str | None = None,
    limits: Path | None = None,
    resume_run: UUID | None = None,
    stop_after_step: int | None = None,
) -> None:
    result = run_command(
        lambda: build_training_service().run(
            project,
            dataset_run,
            TrainingRuntime.model_validate(bounded_json(runtime)),
            load_settings(settings, strategy),
            TrainingLimits.model_validate(bounded_json(limits)) if limits else TrainingLimits(),
            resume_run=resume_run,
            stop_after_step=stop_after_step,
        )
    )
    if result.status not in {"succeeded", "checkpointed"}:
        raise typer.Exit(2)


@app.command("show")
def show(project: Path, run_id: UUID) -> None:
    def inspect():
        value = build_training_service().inspect(project, run_id)[1]
        return value.metadata() if hasattr(value, "metadata") else value
    run_command(inspect)


@app.command("compare")
def compare(
    project: Path,
    dataset_run: Annotated[UUID, typer.Option("--dataset-run")],
    runtime: Annotated[Path, typer.Option("--runtime")],
    settings: Annotated[Path, typer.Option("--settings")],
    limits: Path | None = None,
) -> None:
    from splatforge.application.training_benchmark import compare_training
    from splatforge.core.training_benchmark import candidate_recipes

    run_command(
        lambda: compare_training(
            build_training_service(),
            project,
            dataset_run,
            TrainingRuntime.model_validate(bounded_json(runtime)),
            candidate_recipes(TrainingSettings.model_validate(bounded_json(settings))),
            TrainingLimits.model_validate(bounded_json(limits)) if limits else TrainingLimits(),
        )
    )
