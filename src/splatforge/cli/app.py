from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Annotated
from uuid import UUID

import typer
from pydantic import TypeAdapter

from splatforge import __version__
from splatforge.application.doctor import render_doctor_report
from splatforge.bootstrap import (
    build_doctor_service,
    build_execution_service,
    build_features_service,
    build_mapping_service,
    build_matching_service,
    build_media_service,
    build_pairs_service,
    build_performance_service,
    build_project_service,
    build_retrieval_benchmark_service,
    build_retrieval_service,
    build_run_progress_service,
    build_sfm_profile_service,
    build_views_service,
)
from splatforge.core import build_builtin_registry, recommended_flat_video_profile
from splatforge.core.features import (
    FeatureResourceLimits,
    FeatureSettings,
    resolve_extraction_settings,
)
from splatforge.core.geometry import CameraPriorSet, VerificationSettings
from splatforge.core.matching import (
    MatcherSettings,
    MatchingResourceLimits,
    resolve_matching_settings,
)
from splatforge.core.media import VerificationPolicyId
from splatforge.core.pairs import (
    ExhaustiveSettings,
    HybridPairSettings,
    PairResourceLimits,
    RetrievalPairSettings,
    SequentialSettings,
    parse_explicit_pair,
)
from splatforge.core.progress import EtaEstimate
from splatforge.core.quality import (
    QualityAnalysisSettings,
    SharpestIntervalSettings,
    parse_non_negative_rational,
)
from splatforge.core.reconstruction import (
    GlobalMapperSettings,
    IncrementalMapperSettings,
    MappingCalibrationPolicy,
    MappingResourceLimits,
    ViewGraphCalibrationSettings,
)
from splatforge.core.retrieval import RetrievalResourceLimits
from splatforge.core.sfm_profiles import (
    FeatureMatchingChoice,
    ResolvedFeatureMatchingRoute,
    SfmQualityProfile,
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


pairs_app = typer.Typer(no_args_is_help=True, help="Deterministic candidate view graphs")
app.add_typer(pairs_app, name="pairs")
retrieval_app = typer.Typer(
    no_args_is_help=True, help="Offline global representations and benchmark",
)
app.add_typer(retrieval_app, name="retrieval")
features_app = typer.Typer(
    no_args_is_help=True, help="Local features from published selected views",
)
app.add_typer(features_app, name="features")
matches_app = typer.Typer(no_args_is_help=True, help="Raw matching of an exact PairSet")
app.add_typer(matches_app, name="matches")
verification_app = typer.Typer(no_args_is_help=True, help="Standalone geometric verification")
app.add_typer(verification_app, name="verification")
mapping_app = typer.Typer(no_args_is_help=True, help="Explicit Global or single-model Incremental")
app.add_typer(mapping_app, name="mapping")
sfm_app = typer.Typer(no_args_is_help=True, help="Feature/matching profile and Advanced planning")
app.add_typer(sfm_app, name="sfm")
performance_app = typer.Typer(no_args_is_help=True, help="Private local runtime history")
app.add_typer(performance_app, name="performance")


def _typed_settings(path: Path, annotation):
    limit = (64 * 1024**2 if annotation in (CameraPriorSet, ResolvedFeatureMatchingRoute)
             else 64 * 1024)
    with path.open("rb") as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError(f"Typed settings input exceeds its {limit}-byte bound")
    return TypeAdapter(annotation).validate_json(data)


@mapping_app.command("run")
def mapping_run(
    project: Path,
    verification_run: Annotated[UUID, typer.Option("--verification-run")],
    method: str = typer.Option("global", "--method"),
    ba_backend: str | None = typer.Option(
        None, "--ba-backend", help="Incremental: ceres or caspar"),
    gpu_index: int | None = typer.Option(
        None, "--gpu-index", help="Caspar concrete CUDA device index"),
    calibration: str = typer.Option("preserve-priors", "--calibration"),
    settings: Annotated[Path | None, typer.Option("--settings")] = None,
    calibration_settings: Annotated[Path | None, typer.Option("--calibration-settings")] = None,
    min_model_size: int | None = typer.Option(None, "--min-model-size"),
    num_threads: int | None = typer.Option(None, "--num-threads"),
    max_views: int = typer.Option(10000, "--max-views"),
    max_pairs: int = typer.Option(100000, "--max-pairs"),
    max_workspace_gib: str = typer.Option("128", "--max-workspace-gib"),
    max_output_gib: str = typer.Option("16", "--max-output-gib"),
    timeout: int = typer.Option(7200, "--timeout"),
    colmap: Annotated[Path | None, typer.Option("--colmap")] = None,
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    try:
        if method not in {"global", "incremental"}:
            raise ValueError(
                "Choose explicit global or incremental mapping; Hierarchical is planned")
        if method == "global" and (ba_backend is not None or gpu_index is not None):
            raise ValueError("--ba-backend and --gpu-index are Incremental-only settings")
        if settings and any(v is not None for v in (
            min_model_size, num_threads, ba_backend, gpu_index,
        )):
            raise ValueError("Choose typed --settings or individual mapper settings")
        settings_type = (IncrementalMapperSettings if method == "incremental"
                         else GlobalMapperSettings)
        values = {k: v for k, v in (
            ("min_model_size", min_model_size), ("num_threads", num_threads))
                  if v is not None}
        if method == "incremental" and not settings:
            backend = (ba_backend or "ceres").upper()
            if backend not in {"CERES", "CASPAR"}:
                raise ValueError("--ba-backend requires ceres or caspar")
            if backend == "CERES" and gpu_index is not None:
                raise ValueError("--gpu-index requires explicit Caspar BA; Ceres is CPU-only")
            values.update(ba_local_backend=backend, ba_global_backend=backend)
            if gpu_index is not None or backend == "CASPAR":
                values["ba_gpu_index"] = gpu_index if gpu_index is not None else 0
        numerical = (_typed_settings(settings, settings_type) if settings
                     else settings_type(**values))
        policy = MappingCalibrationPolicy(calibration.replace("-", "_"))
        result = build_mapping_service().run(
            project, verification_run_id=verification_run, settings=numerical,
            calibration_policy=policy,
            calibration_settings=_typed_settings(calibration_settings, ViewGraphCalibrationSettings)
            if calibration_settings else None,
            resource_limits=MappingResourceLimits(max_views=max_views, max_pairs=max_pairs,
                max_workspace_bytes=parse_gib_bytes(max_workspace_gib),
                max_output_bytes=parse_gib_bytes(max_output_gib), timeout_seconds=timeout),
            colmap=colmap,
        )
    except (ValueError, OSError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    if json_output:
        typer.echo(result.model_dump_json(indent=2))
    else:
        typer.echo(f"{result.status}: {result.run_id}; cache_hit={result.cache_hit}")
        if result.reconstruction:
            _mapping_summary(result.reconstruction)


@mapping_app.command("show")
def mapping_show(project: Path, run_id: UUID,
                 json_output: bool = typer.Option(False, "--json")) -> None:
    try:
        value = build_mapping_service().inspect(project, run_id)
    except (ValueError, OSError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    if json_output:
        typer.echo(value.model_dump_json(indent=2))
    else:
        _mapping_summary(value)


def _mapping_summary(value) -> None:
    typer.echo(f"Mapper: {value.method_id}; calibration: {value.calibration.policy}; "
               f"components: {value.component_count}; registered: {value.registered_view_count}; "
               f"unregistered: {value.unregistered_view_count}; scale: {value.scale}")
    for component in value.components:
        typer.echo(f"{component.component_id}: views={component.registered_view_count}, "
                   f"cameras={component.camera_count}, native_points={component.point_count}; "
                   f"points={component.points}, tracks={component.tracks}")


@sfm_app.command("resolve")
def sfm_resolve(
    profile: str | None = typer.Option(None, "--profile"),
    extractor: str | None = typer.Option(None, "--extractor"),
    matcher: str | None = typer.Option(None, "--matcher"),
    extractor_settings: Annotated[Path | None, typer.Option("--extractor-settings")] = None,
    matcher_settings: Annotated[Path | None, typer.Option("--matcher-settings")] = None,
    verification_settings: Annotated[Path | None, typer.Option("--verification-settings")] = None,
    gpu: bool | None = typer.Option(None, "--gpu/--cpu"),
    device: str | None = typer.Option(None, "--device", help="auto, cpu, gpu or gpu:0"),
    colmap: Annotated[Path | None, typer.Option("--colmap")] = None,
    model_directory: Annotated[Path | None, typer.Option("--colmap-model-dir")] = None,
) -> None:
    """Print a resolved versioned JSON recipe without processing a project."""
    try:
        from splatforge.core.sfm_profiles import SfmDevicePolicy

        if device is not None and gpu is not None:
            raise ValueError("Choose --device or --gpu/--cpu")
        policy = SfmDevicePolicy("gpu:0" if device == "gpu" else device) if device else None
        if profile and any(
            (extractor, matcher, extractor_settings, matcher_settings, verification_settings)
        ):
            raise ValueError("Simple profile and explicit Advanced settings are mutually exclusive")
        choice = None
        if profile is None:
            if (extractor is None) == (extractor_settings is None) or (
                (matcher is None) == (matcher_settings is None)
            ):
                raise ValueError("Advanced mode requires one extractor and one matcher selection")
            choice = FeatureMatchingChoice(
                extractor=_typed_settings(extractor_settings, FeatureSettings)
                if extractor_settings
                else resolve_extraction_settings(extractor, use_gpu=bool(gpu)),
                matcher=_typed_settings(matcher_settings, MatcherSettings)
                if matcher_settings
                else resolve_matching_settings(matcher, use_gpu=bool(gpu)),
                verification=_typed_settings(verification_settings, VerificationSettings)
                if verification_settings
                else VerificationSettings(),
            )
        result = build_sfm_profile_service().resolve(
            profile=SfmQualityProfile(profile.replace("-", "_")) if profile else None,
            choice=choice,
            use_gpu=gpu,
            device_policy=policy,
            colmap=colmap,
            model_directory=model_directory,
        )
        typer.echo(result.model_dump_json(indent=2))
    except (ValueError, OSError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc


@matches_app.command("run")
def matches_run(
    path: Path,
    features_run: Annotated[UUID, typer.Option("--features-run")],
    pairs_run: Annotated[UUID, typer.Option("--pairs-run")],
    matcher: str | None = typer.Option(None, "--matcher"),
    settings_file: Annotated[Path | None, typer.Option("--settings")] = None,
    resolved_route: Annotated[Path | None, typer.Option("--resolved-route")] = None,
    resource_limits_file: Annotated[Path | None, typer.Option("--resource-limits")] = None,
    gpu: bool = typer.Option(False, "--gpu/--cpu"),
    num_threads: int = typer.Option(1, "--num-threads"),
    max_matches: int = typer.Option(32768, "--max-matches"),
    colmap: Annotated[Path | None, typer.Option("--colmap")] = None,
    model_directory: Annotated[Path | None, typer.Option("--colmap-model-dir")] = None,
    max_pairs: int = typer.Option(100_000, "--max-pairs"),
    max_workspace_gib: str = typer.Option("64", "--max-workspace-gib"),
    timeout: int = typer.Option(3600, "--timeout"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    try:
        if sum(v is not None for v in (matcher, settings_file, resolved_route)) != 1:
            raise ValueError("Choose exactly one --matcher, --settings or --resolved-route")
        resolution = (
            _typed_settings(resolved_route, ResolvedFeatureMatchingRoute)
            if resolved_route
            else None
        )
        settings = (
            resolution.choice.matcher
            if resolution
            else _typed_settings(settings_file, MatcherSettings)
            if settings_file
            else resolve_matching_settings(
                matcher, use_gpu=gpu, num_threads=num_threads, max_num_matches=max_matches
            )
        )
        result = build_matching_service().match(
            path,
            features_run_id=features_run,
            pairs_run_id=pairs_run,
            settings=settings,
            resolution=resolution,
            colmap=colmap,
            model_directory=model_directory,
            resource_limits=_typed_settings(resource_limits_file, MatchingResourceLimits)
            if resource_limits_file
            else MatchingResourceLimits(
                max_pairs=max_pairs,
                max_workspace_bytes=parse_gib_bytes(max_workspace_gib),
                timeout_seconds=timeout,
            ),
        )
    except (ValueError, OSError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(
        result.model_dump_json(indent=2)
        if json_output
        else f"Matching run {result.run_id}: {result.status.value}; {result.pair_count} pairs, "
        f"{result.raw_matches} raw matches; cache_hit={result.cache_hit}"
    )
    if result.status != "succeeded":
        raise typer.Exit(code=2)


@verification_app.command("run")
def verification_run(
    path: Path,
    matches_run: Annotated[UUID, typer.Option("--matches-run")],
    settings_file: Annotated[Path | None, typer.Option("--settings")] = None,
    resolved_route: Annotated[Path | None, typer.Option("--resolved-route")] = None,
    resource_limits_file: Annotated[Path | None, typer.Option("--resource-limits")] = None,
    camera_priors: Annotated[Path | None, typer.Option("--camera-priors")] = None,
    min_inliers: int = typer.Option(15, "--min-inliers"),
    max_error: float = typer.Option(4.0, "--max-error"),
    num_threads: int = typer.Option(1, "--num-threads"),
    colmap: Annotated[Path | None, typer.Option("--colmap")] = None,
    max_pairs: int = typer.Option(100_000, "--max-pairs"),
    max_workspace_gib: str = typer.Option("64", "--max-workspace-gib"),
    timeout: int = typer.Option(3600, "--timeout"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    try:
        if settings_file and resolved_route:
            raise ValueError("Select --settings or --resolved-route")
        resolution = (
            _typed_settings(resolved_route, ResolvedFeatureMatchingRoute)
            if resolved_route
            else None
        )
        settings = (
            resolution.choice.verification
            if resolution
            else _typed_settings(settings_file, VerificationSettings)
            if settings_file
            else VerificationSettings(
                min_num_inliers=min_inliers, max_error=max_error, num_threads=num_threads
            )
        )
        result = build_matching_service().verify(
            path,
            matches_run_id=matches_run,
            settings=settings,
            resolution=resolution,
            cameras=_typed_settings(camera_priors, CameraPriorSet) if camera_priors else None,
            colmap=colmap,
            resource_limits=_typed_settings(resource_limits_file, MatchingResourceLimits)
            if resource_limits_file
            else MatchingResourceLimits(
                max_pairs=max_pairs,
                max_workspace_bytes=parse_gib_bytes(max_workspace_gib),
                timeout_seconds=timeout,
            ),
        )
    except (ValueError, OSError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(
        result.model_dump_json(indent=2)
        if json_output
        else f"Verification run {result.run_id}: {result.status.value}; "
        f"{result.accepted_pairs} verified pairs, {result.verified_inliers} inliers; "
        f"cache_hit={result.cache_hit}"
    )
    if result.status != "succeeded":
        raise typer.Exit(code=2)


@features_app.command("extract")
def features_extract(
    path: Path, views_run: Annotated[UUID, typer.Option("--views-run")],
    method: str = typer.Option(..., "--method"),
    max_features: int | None = typer.Option(None, "--max-features"),
    max_image_size: int = typer.Option(2048, "--max-image-size"),
    gpu: bool = typer.Option(False, "--gpu/--cpu"),
    min_score: float | None = typer.Option(None, "--min-score"),
    fast_resize: bool = typer.Option(False, "--fast-resize"),
    colmap: Annotated[Path | None, typer.Option("--colmap")] = None,
    model_directory: Annotated[Path | None, typer.Option("--colmap-model-dir")] = None,
    max_views: int = typer.Option(10_000, "--max-views"),
    max_workspace_gib: str = typer.Option("64", "--max-workspace-gib"),
    timeout: int = typer.Option(3600, "--timeout"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    try:
        settings = resolve_extraction_settings(
            method, max_features=max_features, max_image_size=max_image_size,
            use_gpu=gpu, min_score=min_score, use_fast_resize=fast_resize,
        )
        result = build_features_service().extract(
            path, views_run_id=views_run, settings=settings, colmap=colmap,
            model_directory=model_directory, resource_limits=FeatureResourceLimits(
                max_views=max_views, max_workspace_bytes=parse_gib_bytes(max_workspace_gib),
                timeout_seconds=timeout,
            ),
        )
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    if json_output:
        typer.echo(result.model_dump_json(indent=2))
    else:
        typer.echo(f"Features run {result.run_id}: {result.status.value}; "
                   f"{result.selected_view_count} views, {result.total_feature_count} features; "
                   f"cache_hit={result.cache_hit}")
    if result.status != "succeeded":
        raise typer.Exit(code=2)


def _eta_text(eta: EtaEstimate) -> str:
    if eta.likely_seconds is None:
        return "ETA unavailable"
    if eta.likely_seconds == 0:
        return "0s"
    divisor, unit = (60, "min") if eta.upper_seconds >= 120 else (1, "s")
    lower = math.floor(eta.lower_seconds / divisor)
    upper = math.ceil(eta.upper_seconds / divisor)
    return f"~{lower}–{upper} {unit} · {eta.confidence.value} confidence"


@run_app.command("progress")
def run_progress(
    path: Path, run_id: UUID, json_output: bool = typer.Option(False, "--json"),
) -> None:
    try:
        snapshot = build_run_progress_service().get(path, run_id)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    if json_output:
        typer.echo(snapshot.model_dump_json(indent=2))
        return
    typer.echo(f"Run {snapshot.run_id}: {snapshot.status} · "
               f"elapsed {snapshot.elapsed_seconds:.0f}s")
    stage = snapshot.current_stage
    if stage is not None:
        total = "unknown" if stage.work.total is None else f"{stage.work.total:.1f}"
        fraction = "unavailable" if stage.fraction is None else f"{stage.fraction:.0%}"
        speed = "unavailable" if stage.throughput is None else (
            f"{stage.throughput:.3g} {stage.throughput_unit.value}/s"
        )
        typer.echo(f"Stage {stage.work.stage_id} / {stage.phase_code or 'unknown phase'}: "
                   f"{stage.completed:.1f}/{total} {stage.work.unit.value} · {fraction}")
        typer.echo(f"Speed {speed} · elapsed {stage.elapsed_seconds:.0f}s · {_eta_text(stage.eta)}")
        if stage.stale:
            typer.echo(f"Last observation is stale ({stage.observation_age_seconds:.0f}s old)")
    else:
        typer.echo("Current stage: unavailable")
    fraction = "unavailable" if snapshot.fraction is None else f"{snapshot.fraction:.0%}"
    typer.echo(f"Pipeline {fraction} · {_eta_text(snapshot.eta)}")
    typer.echo(f"Cached: {', '.join(snapshot.cached_stages) or 'none'}")
    typer.echo(f"Skipped: {', '.join(snapshot.skipped_stages) or 'none'}")
    typer.echo(f"Unknown ETA stages: {', '.join(snapshot.unknown_stages) or 'none'}")
    if snapshot.warnings:
        typer.echo(f"Warnings: {', '.join(snapshot.warnings)}")


@performance_app.command("show")
def performance_show(json_output: bool = typer.Option(False, "--json")) -> None:
    statistics = build_performance_service().show()
    if json_output:
        typer.echo(statistics.model_dump_json(indent=2))
    else:
        typer.echo(f"Performance schema v1 · {statistics.sample_count} successful samples")
        for signature in statistics.signatures:
            typer.echo(f"{signature.signature_key[:12]} {signature.signature.method_id}: "
                       f"{signature.count} samples · "
                       f"median {signature.median_throughput:.3g} "
                       f"{signature.signature.unit.value}/s · "
                       f"range {signature.lower_throughput:.3g}–{signature.upper_throughput:.3g}")
        for warning in statistics.warnings:
            typer.echo(warning, err=True)


@performance_app.command("reset")
def performance_reset() -> None:
    warnings = build_performance_service().reset()
    if warnings:
        typer.echo(", ".join(warnings), err=True)
        raise typer.Exit(code=1)
    typer.echo("Local performance samples cleared")


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
        note = f" — {method.notes}" if method.notes else ""
        typer.echo(f"{method.stage.value:20} {method.id:42} {method.display_name}{suffix}{note}")


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


@pairs_app.command("build")
def build_pairs(
    path: Path,
    views_run: Annotated[UUID, typer.Option("--views-run")],
    method: str = typer.Option("sequential", "--method"),
    forward_neighbors: int | None = typer.Option(None, "--forward-neighbors"),
    max_time_gap: str | None = typer.Option(None, "--max-time-gap"),
    pair: Annotated[list[str] | None, typer.Option("--pair")] = None,
    max_pairs: int = typer.Option(100_000, "--max-pairs"),
    retrieval_run: Annotated[UUID | None, typer.Option("--retrieval-run")] = None,
    retrieval_settings: Annotated[Path | None, typer.Option("--retrieval-settings")] = None,
    retrieval_resources: Annotated[Path | None, typer.Option("--retrieval-resources")] = None,
) -> None:
    try:
        if method not in ("retrieval", "hybrid") and (
            retrieval_run or retrieval_settings or retrieval_resources
        ):
            raise ValueError("Retrieval options require --method retrieval or hybrid")
        if method == "sequential":
            settings = SequentialSettings(
                forward_neighbors=5 if forward_neighbors is None else forward_neighbors,
                max_time_gap=(
                    parse_non_negative_rational(max_time_gap) if max_time_gap is not None else None
                ),
            )
        elif method == "exhaustive":
            if forward_neighbors is not None or max_time_gap is not None:
                raise ValueError("Exhaustive rejects --forward-neighbors and --max-time-gap")
            settings = ExhaustiveSettings()
        elif method in ("retrieval", "hybrid"):
            if retrieval_run is None:
                raise ValueError(
                    "Retrieval/hybrid requires --retrieval-run; no Exhaustive fallback",
                )
            query_settings = (_typed_settings(retrieval_settings, RetrievalPairSettings)
                              if retrieval_settings else RetrievalPairSettings())
            if method == "retrieval":
                if forward_neighbors is not None or max_time_gap is not None:
                    raise ValueError("Retrieval rejects Sequential settings; choose hybrid")
                settings = query_settings
            else:
                settings = HybridPairSettings(
                    sequential=SequentialSettings(
                        forward_neighbors=5 if forward_neighbors is None else forward_neighbors,
                        max_time_gap=parse_non_negative_rational(max_time_gap)
                        if max_time_gap is not None else None,
                    ), retrieval=query_settings,
                )
        else:
            raise ValueError("--method must be sequential, exhaustive, retrieval or hybrid")
        result = build_pairs_service().build(
            path,
            views_run_id=views_run,
            settings=settings,
            resource_limits=PairResourceLimits(max_pairs=max_pairs),
            explicit_pairs=tuple(parse_explicit_pair(v) for v in (pair or [])),
            retrieval_run_id=retrieval_run,
            retrieval_resources=_typed_settings(retrieval_resources, RetrievalResourceLimits)
            if retrieval_resources else None,
        )
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(result.model_dump_json(indent=2))


@retrieval_app.command("build")
def retrieval_build(
    path: Path,
    views_run: Annotated[UUID, typer.Option("--views-run")],
    descriptor_export: Annotated[Path | None, typer.Option("--descriptor-export")] = None,
    resources: Annotated[Path | None, typer.Option("--resource-limits")] = None,
) -> None:
    try:
        result = build_retrieval_service().build(
            path, views_run_id=views_run, descriptor_export=descriptor_export,
            resource_limits=_typed_settings(resources, RetrievalResourceLimits)
            if resources else None,
        )
    except ValueError as exc:
        typer.echo(json.dumps({"code": getattr(exc, "code", "retrieval.invalid_input"),
                               "message": str(exc)}), err=True)
        raise typer.Exit(1) from exc
    typer.echo(result.model_dump_json(indent=2))


@retrieval_app.command("request")
def retrieval_request(
    path: Path, views_run: Annotated[UUID, typer.Option("--views-run")],
) -> None:
    try:
        result = build_retrieval_service().request(path, views_run_id=views_run)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    typer.echo(result.model_dump_json(indent=2))


@retrieval_app.command("capabilities")
def retrieval_capabilities() -> None:
    from splatforge.application.retrieval_benchmark import retrieval_availability

    typer.echo(json.dumps(retrieval_availability(), indent=2))


@retrieval_app.command("benchmark")
def retrieval_benchmark(
    fixture: Path,
    colmap: Annotated[Path | None, typer.Option("--colmap")] = None,
    model_directory: Annotated[Path | None, typer.Option("--colmap-model-dir")] = None,
) -> None:
    from splatforge.application.retrieval_benchmark import RetrievalBenchmarkFixture

    try:
        result = build_retrieval_benchmark_service().run(
            _typed_settings(fixture, RetrievalBenchmarkFixture), colmap=colmap,
            model_directory=model_directory,
        )
    except ValueError as exc:
        typer.echo(json.dumps({"code": "retrieval.benchmark_unavailable", "message": str(exc)}),
                   err=True)
        raise typer.Exit(1) from exc
    typer.echo(json.dumps(result, indent=2))


if __name__ == "__main__":
    app()
