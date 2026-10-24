"""Thin bounded M10 clients; lifecycle controls remain under run."""

from pathlib import Path
from typing import Annotated
from uuid import UUID

import typer

from splatforge.bootstrap import build_dataset_service
from splatforge.core.dataset import DatasetResourceLimits, DatasetSettings
from splatforge.core.views import parse_gib_bytes

app = typer.Typer(
    no_args_is_help=True, help="Prepare flat-camera datasets from explicit M9 selections"
)


def _execute(
    project,
    selection_run,
    max_image_size,
    max_workspace_gib,
    minimum_free_gib,
    timeout,
    colmap,
    json_output,
    planning,
):
    try:
        service = build_dataset_service()
        result = (service.plan if planning else service.prepare)(
            project,
            selection_run_id=selection_run,
            settings=DatasetSettings(max_image_size=max_image_size),
            resource_limits=DatasetResourceLimits(
                max_workspace_bytes=parse_gib_bytes(max_workspace_gib),
                minimum_free_bytes=parse_gib_bytes(minimum_free_gib),
                timeout_seconds=timeout,
            ),
            colmap=colmap,
        )
    except (ValueError, OSError, KeyError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    if json_output:
        typer.echo(result.model_dump_json(indent=2))
    elif planning:
        typer.echo(
            f"Selection valid; dataset preparation {'runnable' if result.runnable else 'blocked'}"
        )
        typer.echo(f"Historical pixels: {result.candidate.artifact_id}")
        typer.echo(f"COLMAP image_undistorter: {'verified' if result.backend else 'unavailable'}")
        typer.echo(f"Maximum image side: {result.settings.max_image_size or 'native/full'}")
        typer.echo(
            f"Disk required/free: {result.required_free_disk_bytes:,} / "
            f"{result.available_disk_bytes:,} bytes"
        )
        for component in result.components:
            typer.echo(
                f"Component {component.source_component.component_id}: "
                f"{component.registered_views} registered images; "
                f"cameras={component.input_camera_models}; "
                f"undistortion={component.undistortion_required}; cache={component.cache_hit}"
            )
            typer.echo(
                f"  Input pixels {component.estimate.input_pixel_bytes:,} bytes; "
                f"output expected/conservative {component.estimate.output_bytes_expected:,} / "
                f"{component.estimate.output_bytes_conservative:,}; "
                f"workspace {component.estimate.peak_workspace_bytes:,}"
            )
            for reason in component.cache_reasons:
                typer.echo("  Cache: " + reason)
        override_status = "present and current" if result.provenance.override else "none"
        typer.echo(
            f"Validation: {result.provenance.validation_status}; override: {override_status}"
        )
        for warning in (*result.provenance.warnings, *result.diagnostics):
            typer.echo(warning)
        typer.echo(result.provenance.production_multi_video_gate)
    else:
        typer.echo(f"Dataset run {result.run_id}: {result.status}; cache={result.cache_hit}")
        if result.dataset:
            for component in result.dataset.components:
                typer.echo(
                    f"Component {component.component_id}: {component.image_count} images; "
                    f"trainer-ready directory: {project / Path(component.manifest_path).parent}"
                )
        typer.echo("Production multi-video acceptance: pending M7c production VPR selection")
    if (planning and not result.runnable) or (not planning and result.status != "succeeded"):
        raise typer.Exit(code=2)


@app.command("plan")
def plan(
    project: Path,
    selection_run: Annotated[UUID, typer.Option("--selection-run")],
    max_image_size: Annotated[int | None, typer.Option(min=1, max=32768)] = None,
    max_workspace_gib: str = "32",
    minimum_free_gib: str = "0.25",
    timeout: Annotated[int, typer.Option(min=1, max=86400)] = 7200,
    colmap: Path | None = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    _execute(
        project,
        selection_run,
        max_image_size,
        max_workspace_gib,
        minimum_free_gib,
        timeout,
        colmap,
        json_output,
        True,
    )


@app.command("prepare")
def prepare(
    project: Path,
    selection_run: Annotated[UUID, typer.Option("--selection-run")],
    max_image_size: Annotated[int | None, typer.Option(min=1, max=32768)] = None,
    max_workspace_gib: str = "32",
    minimum_free_gib: str = "0.25",
    timeout: Annotated[int, typer.Option(min=1, max=86400)] = 7200,
    colmap: Path | None = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    _execute(
        project,
        selection_run,
        max_image_size,
        max_workspace_gib,
        minimum_free_gib,
        timeout,
        colmap,
        json_output,
        False,
    )


@app.command("show")
def show(
    project: Path,
    dataset_run_id: UUID,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    try:
        dataset = build_dataset_service().inspect(project, dataset_run_id)
    except (ValueError, OSError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(
        dataset.model_dump_json(indent=2)
        if json_output
        else "\n".join(
            f"{c.component_id}: {c.image_count} images; {project / Path(c.manifest_path).parent}"
            for c in dataset.components
        )
    )
