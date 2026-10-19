from __future__ import annotations

import json

import typer

from splatforge import __version__
from splatforge.core import build_builtin_registry, recommended_flat_video_profile

app = typer.Typer(no_args_is_help=True, help="SplatForge development CLI")


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
