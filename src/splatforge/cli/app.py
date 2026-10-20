from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

import typer

from splatforge import __version__
from splatforge.bootstrap import build_execution_service, build_project_service
from splatforge.core import build_builtin_registry, recommended_flat_video_profile

app = typer.Typer(no_args_is_help=True, help="SplatForge development CLI")
project_app = typer.Typer(no_args_is_help=True, help="Basic project persistence")
app.add_typer(project_app, name="project")
run_app = typer.Typer(no_args_is_help=True, help="Deterministic fake execution")
app.add_typer(run_app, name="run")


@project_app.command("create")
def create_project(path: Path, label: str = typer.Option(..., "--label")) -> None:
    try:
        document = build_project_service().create(path, label)
    except (ValueError, KeyError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(document.model_dump_json(indent=2))


@project_app.command("show")
def show_project(path: Path) -> None:
    try:
        rendered = build_project_service().show(path)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(rendered)


@project_app.command("upgrade-state")
def upgrade_project_state(path: Path) -> None:
    try:
        result = build_project_service().upgrade_state(path)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(result.model_dump_json(indent=2))


@run_app.command("fake")
def run_fake(
    path: Path,
    start: int = typer.Option(0, "--start"),
    count: int = typer.Option(3, "--count"),
    factor: int = typer.Option(2, "--factor"),
) -> None:
    try:
        result = build_execution_service().run(path, start=start, count=count, factor=factor)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(result.model_dump_json(indent=2))


@run_app.command("show")
def show_run(path: Path, run_id: UUID) -> None:
    try:
        rendered = build_execution_service().show(path, run_id)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(rendered)


@run_app.command("cancel")
def cancel_run(path: Path, run_id: UUID) -> None:
    try:
        result = build_execution_service().cancel(path, run_id)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(result.model_dump_json(indent=2))


@run_app.command("recover")
def recover_run(path: Path, run_id: UUID) -> None:
    try:
        result = build_execution_service().recover(path, run_id)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(result.model_dump_json(indent=2))


@run_app.command("retry")
def retry_run(path: Path, run_id: UUID) -> None:
    try:
        result = build_execution_service().retry(path, run_id)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(result.model_dump_json(indent=2))


@app.command()
def version() -> None:
    typer.echo(__version__)


@app.command()
def methods() -> None:
    registry = build_builtin_registry()
    for method in registry.list():
        suffix = " [experimental]" if method.experimental else ""
        typer.echo(f"{method.stage.value:20} {method.id:42} {method.display_name}{suffix}")


@app.command("show-default-config")
def show_default_config() -> None:
    config = recommended_flat_video_profile()
    registry = build_builtin_registry()
    registry.validate_pipeline(config)
    typer.echo(json.dumps(config.model_dump(mode="json"), indent=2))


if __name__ == "__main__":
    app()
