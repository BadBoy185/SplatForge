from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated
from uuid import UUID

import typer

from splatforge import __version__
from splatforge.application.doctor import render_doctor_report
from splatforge.bootstrap import (
    build_doctor_service,
    build_execution_service,
    build_media_service,
    build_project_service,
    build_views_service,
)
from splatforge.core import build_builtin_registry, recommended_flat_video_profile
from splatforge.core.media import VerificationPolicyId
from splatforge.core.quality import (
    QualityAnalysisSettings,
    SharpestIntervalSettings,
    parse_non_negative_rational,
)
from splatforge.core.views import (
    CandidateEncodingSettings,
    CandidatePoolSettings,
    CandidateResourceLimits,
    FixedFpsSettings,
    ImageFormat,
    RationalValue,
    parse_fps,
    parse_gib_bytes,
)

app = typer.Typer(no_args_is_help=True, help="SplatForge development CLI")
project_app = typer.Typer(no_args_is_help=True, help="Basic project persistence")
app.add_typer(project_app, name="project")
run_app = typer.Typer(no_args_is_help=True, help="Run inspection and control")
app.add_typer(run_app, name="run")
media_app = typer.Typer(no_args_is_help=True, help="Read-only media registration")
app.add_typer(media_app, name="media")
views_app = typer.Typer(no_args_is_help=True, help="Candidate views and frame selection")
app.add_typer(views_app, name="views")


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


@media_app.command("add")
def add_media(
    path: Path,
    sources: Annotated[list[Path], typer.Argument()],
    ffprobe: Annotated[Path | None, typer.Option("--ffprobe")] = None,
    source_group: Annotated[UUID | None, typer.Option("--source-group")] = None,
    camera_group: Annotated[UUID | None, typer.Option("--camera-group")] = None,
) -> None:
    try:
        result = build_media_service(
            ffprobe_path=str(ffprobe.absolute()) if ffprobe is not None else None
        ).add(
            path,
            sources,
            source_group_id=source_group,
            camera_group_id=camera_group,
        )
    except (ValueError, KeyError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(result.model_dump_json(indent=2))


@media_app.command("list")
def list_media(path: Path) -> None:
    try:
        inventory = build_media_service().list(path)
    except (ValueError, KeyError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(
        json.dumps(
            {"inventory": inventory.model_dump(mode="json") if inventory else None},
            indent=2,
        )
    )


@media_app.command("verify")
def verify_media(
    path: Path,
    policy: str = typer.Option("balanced", "--policy"),
    source_id: Annotated[list[UUID] | None, typer.Option("--source-id")] = None,
) -> None:
    policies = {
        "balanced": VerificationPolicyId.BALANCED_LOCAL,
        "strict": VerificationPolicyId.STRICT,
    }
    if policy not in policies:
        typer.echo("--policy must be 'balanced' or 'strict'", err=True)
        raise typer.Exit(code=1)
    try:
        results = build_media_service().verify(
            path,
            policy=policies[policy],
            source_ids=set(source_id) if source_id else None,
        )
    except (ValueError, KeyError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(
        json.dumps(
            {"results": [result.model_dump(mode="json") for result in results]},
            indent=2,
        )
    )


@media_app.command("relink")
def relink_media(path: Path, source_id: UUID, new_path: Path) -> None:
    try:
        result = build_media_service().relink(path, source_id, new_path)
    except (ValueError, KeyError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(result.model_dump_json(indent=2))


@views_app.command("prepare")
def prepare_views(
    path: Path,
    target_fps: Annotated[str, typer.Option("--target-fps")],
    selection: Annotated[str, typer.Option("--selection")] = "fixed-fps",
    candidate_fps: Annotated[str | None, typer.Option("--candidate-fps")] = None,
    source_id: Annotated[list[UUID] | None, typer.Option("--source-id")] = None,
    verification: Annotated[str, typer.Option("--verification")] = "balanced",
    ffmpeg: Annotated[Path | None, typer.Option("--ffmpeg")] = None,
    image_format: Annotated[str, typer.Option("--image-format")] = "jpeg",
    jpeg_qscale: Annotated[int, typer.Option("--jpeg-qscale")] = 2,
    max_candidates: Annotated[int, typer.Option("--max-candidates")] = 10_000,
    max_disk_gib: Annotated[str, typer.Option("--max-disk-gib")] = "20",
    process_timeout: Annotated[int, typer.Option("--process-timeout")] = 3600,
    quality_max_side: Annotated[int, typer.Option("--quality-max-side")] = 1024,
    min_sharpness: Annotated[str | None, typer.Option("--min-sharpness")] = None,
    duplicate_hamming_threshold: Annotated[int, typer.Option("--duplicate-hamming-threshold")] = 4,
    duplicate_lookback: Annotated[int, typer.Option("--duplicate-lookback")] = 8,
    allow_duplicates: Annotated[bool, typer.Option("--allow-duplicates")] = False,
) -> None:
    policies = {
        "balanced": VerificationPolicyId.BALANCED_LOCAL,
        "strict": VerificationPolicyId.STRICT,
    }
    formats = {"jpeg": ImageFormat.JPEG, "png": ImageFormat.PNG}
    selections = {"fixed-fps", "sharpest-interval"}
    if verification not in policies:
        typer.echo("--verification must be 'balanced' or 'strict'", err=True)
        raise typer.Exit(code=1)
    if image_format not in formats:
        typer.echo("--image-format must be 'jpeg' or 'png'", err=True)
        raise typer.Exit(code=1)
    if selection not in selections:
        typer.echo("--selection must be 'fixed-fps' or 'sharpest-interval'", err=True)
        raise typer.Exit(code=1)
    try:
        target = parse_fps(target_fps)
        if candidate_fps is None and selection == "sharpest-interval":
            candidate = RationalValue.from_fraction(2 * target.as_fraction())
        else:
            candidate = parse_fps(candidate_fps or target_fps)
        if selection == "sharpest-interval":
            selection_settings: FixedFpsSettings | SharpestIntervalSettings = (
                SharpestIntervalSettings(
                    target_fps=target,
                    min_sharpness=(
                        parse_non_negative_rational(min_sharpness)
                        if min_sharpness is not None
                        else None
                    ),
                    reject_duplicates=not allow_duplicates,
                    duplicate_hamming_threshold=duplicate_hamming_threshold,
                    duplicate_lookback=duplicate_lookback,
                )
            )
            quality_settings: QualityAnalysisSettings | None = QualityAnalysisSettings(
                quality_max_side=quality_max_side
            )
        else:
            selection_settings = FixedFpsSettings(target_fps=target)
            quality_settings = None
        result = build_views_service(
            ffmpeg_path=str(ffmpeg.absolute()) if ffmpeg is not None else None
        ).prepare(
            path,
            candidate_settings=CandidatePoolSettings(
                candidate_fps=candidate,
                encoding=CandidateEncodingSettings(
                    image_format=formats[image_format],
                    jpeg_qscale=jpeg_qscale,
                ),
            ),
            selection_settings=selection_settings,
            quality_settings=quality_settings,
            resource_limits=CandidateResourceLimits(
                max_candidates=max_candidates,
                max_candidate_bytes=parse_gib_bytes(max_disk_gib),
                per_source_timeout_seconds=process_timeout,
            ),
            verification_policy=policies[verification],
            source_ids=set(source_id) if source_id else None,
        )
    except (ValueError, KeyError) as exc:
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


@app.command()
def doctor(
    colmap: Annotated[Path | None, typer.Option("--colmap")] = None,
    colmap_model_dir: Annotated[Path | None, typer.Option("--colmap-model-dir")] = None,
    deep: Annotated[bool, typer.Option("--deep")] = False,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    try:
        report = build_doctor_service().report(
            colmap=colmap,
            model_directory=colmap_model_dir,
            deep=deep,
        )
    except Exception as exc:
        typer.echo(
            f"Doctor could not complete its internal contract: {str(exc)[:1024]}", err=True
        )
        raise typer.Exit(code=1) from exc
    if json_output:
        typer.echo(report.model_dump_json(indent=2))
    else:
        typer.echo(render_doctor_report(report))


@app.command("show-default-config")
def show_default_config() -> None:
    config = recommended_flat_video_profile()
    registry = build_builtin_registry()
    registry.validate_pipeline(config)
    typer.echo(json.dumps(config.model_dump(mode="json"), indent=2))


if __name__ == "__main__":
    app()
