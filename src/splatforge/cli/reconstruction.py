"""Thin M9 clients; decisions and metrics belong to Application/Core."""

from pathlib import Path
from typing import Annotated, Any
from uuid import UUID

import typer
from pydantic import TypeAdapter

from splatforge.bootstrap import (
    build_reconstruction_selection_service,
    build_reconstruction_validation_service,
)
from splatforge.core.reconstruction_selection import (
    DominanceSelectionPolicy,
    ReconstructionSelection,
)
from splatforge.core.reconstruction_validation import (
    MeasurementSettings,
    ReconstructionMetrics,
    ValidationResourceLimits,
)
from splatforge.core.validation_policy import (
    ReconstructionValidationPolicy,
    ReconstructionValidationReport,
    ValidationIssue,
)
from splatforge.core.views import parse_gib_bytes

app = typer.Typer(no_args_is_help=True, help="Reconstruction validation and explicit selection")


def _scope_label(issue: ValidationIssue) -> str:
    scope = issue.scope
    return ":".join(
        str(v) for v in (scope.kind, scope.component_id, scope.source_group_id) if v is not None
    )


def settings_file(path: Path, annotation: Any) -> Any:
    with path.open("rb") as stream:
        data = stream.read(65537)
    if len(data) > 65536:
        raise ValueError("M9 settings exceed the 64 KiB bound")
    return TypeAdapter(annotation).validate_json(data)


def validation_summary(
    report: ReconstructionValidationReport, metrics: ReconstructionMetrics
) -> None:
    typer.echo(
        f"Project: {report.status.upper()} (project-wide gates: {report.project_status.upper()})"
    )
    registered = metrics.registration
    typer.echo(
        f"Registered: {registered.registered_views} / {registered.input_views} "
        f"({registered.ratio:.1%})"
    )
    typer.echo(f"Components: {metrics.component_count}")
    for component in metrics.components:
        typer.echo(
            f"Component {component.component_id}: {component.registration.registered_views} views"
        )
        for group in metrics.source_groups:
            cov = next(
                c.coverage for c in group.components if c.component_id == component.component_id
            )
            typer.echo(
                f"  Source group {group.group_id}: {cov.registered_views} / "
                f"{cov.input_views} ({cov.ratio:.1%})"
            )
        for name in (
            "camera.focal_ratio_max",
            "point.count",
            "track.mean",
            "reprojection.p95",
            "triangulation.median",
        ):
            metric = component.metric(name)
            unit = next(m.unit for m in component.measurements if m.name == name)
            typer.echo(
                f"  {name}: {metric.value if metric.value is not None else metric.reason} "
                f"{unit} [{metric.availability}]"
            )
    for issue in report.issues:
        typer.echo(
            f"{issue.severity.upper()} {issue.code} [{_scope_label(issue)}]: "
            f"{issue.message} [issue {issue.issue_id}]"
        )
    typer.echo(f"Unknown measurements: {len(report.unknown_metrics)} (see --json for evidence)")


@app.command("validate")
def validate(
    project: Path,
    mapping_run: Annotated[UUID, typer.Option("--mapping-run")],
    profile: str = "baseline_v1",
    policy: Annotated[Path | None, typer.Option("--policy")] = None,
    measurement_settings: Annotated[Path | None, typer.Option("--measurement-settings")] = None,
    max_native_gib: str = "32",
    max_scratch_gib: str = "128",
    timeout: Annotated[int, typer.Option(min=1, max=86400)] = 7200,
    max_components: Annotated[int, typer.Option(min=1, max=100000)] = 1000,
    max_coverage_cells: Annotated[int, typer.Option(min=1, max=1000000)] = 250000,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    try:
        if profile != "baseline_v1":
            raise ValueError("Only baseline_v1 is available; use --policy for custom_v1")
        service = build_reconstruction_validation_service()
        result = service.validate(
            project,
            mapping_run_id=mapping_run,
            policy=settings_file(policy, ReconstructionValidationPolicy) if policy else None,
            settings=settings_file(measurement_settings, MeasurementSettings)
            if measurement_settings
            else None,
            resource_limits=ValidationResourceLimits(
                max_components=max_components,
                max_coverage_cells=max_coverage_cells,
                max_native_bytes=parse_gib_bytes(max_native_gib),
                max_scratch_bytes=parse_gib_bytes(max_scratch_gib),
                timeout_seconds=timeout,
            ),
        )
        if json_output:
            typer.echo(result.model_dump_json(indent=2))
        else:
            typer.echo(f"Validation run: {result.run_id} ({result.status})")
            if result.report:
                report, metrics = service.inspect_details(project, result.run_id)
                validation_summary(report, metrics)
    except (ValueError, OSError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc


@app.command("validation-show")
def validation_show(
    project: Path, run_id: UUID, json_output: Annotated[bool, typer.Option("--json")] = False
) -> None:
    try:
        report, metrics = build_reconstruction_validation_service().inspect_details(project, run_id)
        if json_output:
            import json

            typer.echo(
                json.dumps(
                    {
                        "report": report.model_dump(mode="json"),
                        "metrics": metrics.model_dump(mode="json"),
                    },
                    indent=2,
                )
            )
        else:
            validation_summary(report, metrics)
    except (ValueError, OSError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc


def selection_summary(
    selection: ReconstructionSelection,
    report: ReconstructionValidationReport,
    metrics: ReconstructionMetrics,
) -> None:
    typer.echo(
        f"Selection: {selection.mode}; {len(selection.selected_components)} separate component(s)"
    )
    for component in selection.selected_components:
        measured = next(c for c in metrics.components if c.component_id == component.component_id)
        typer.echo(
            f"Selected {component.component_id}: "
            f"{measured.registration.registered_views} / {measured.registration.input_views} "
            f"({measured.registration.ratio:.1%})"
        )
        for group in metrics.source_groups:
            cov = next(
                c.coverage for c in group.components if c.component_id == component.component_id
            )
            typer.echo(
                f"  Source group {group.group_id}: {cov.registered_views} / "
                f"{cov.input_views} ({cov.ratio:.1%})"
            )
    for reason in selection.reasons:
        typer.echo(f"Reason [{reason.code}]: {reason.message}")
    for issue in report.issues:
        if issue.issue_id in selection.warning_issue_ids:
            typer.echo(
                f"WARNING {issue.code} [{_scope_label(issue)}]: "
                f"{issue.message} [issue {issue.issue_id}]"
            )
    if selection.override:
        typer.echo("Explicit overridden failures: " + ", ".join(selection.override.issue_ids))
        typer.echo("Override reason: " + selection.override.reason)
    typer.echo("Selection content digest: " + selection.semantic_digest)


@app.command("select")
def select(
    project: Path,
    validation_run: Annotated[UUID, typer.Option("--validation-run")],
    component: Annotated[list[UUID] | None, typer.Option("--component")] = None,
    mode: Annotated[str | None, typer.Option("--mode")] = None,
    policy: Annotated[Path | None, typer.Option("--policy")] = None,
    reason: str = "Manual user choice.",
    override_issue: Annotated[list[str] | None, typer.Option("--override-issue")] = None,
    override_reason: Annotated[str | None, typer.Option("--override-reason")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    try:
        service = build_reconstruction_selection_service()
        result = service.select(
            project,
            validation_run_id=validation_run,
            component_ids=tuple(component or ()),
            mode=mode,
            policy=settings_file(policy, DominanceSelectionPolicy) if policy else None,
            manual_reason=reason,
            override_issue_ids=tuple(override_issue or ()),
            override_reason=override_reason,
        )
        if json_output:
            typer.echo(result.model_dump_json(indent=2))
        elif result.status == "succeeded":
            typer.echo(f"Selection run: {result.run.run_id}")
            selection_summary(*service.inspect_details(project, result.run.run_id))
        elif result.decision:
            typer.echo("Automatic selection: " + result.decision.status.upper())
            for candidate in result.decision.candidates:
                typer.echo(
                    f"Candidate {candidate.component_id}: "
                    f"{candidate.registration.registered_views} registered; "
                    f"{candidate.validation_status}; eligible={candidate.eligible}"
                )
                for group in candidate.source_groups:
                    cov = group.coverage
                    typer.echo(
                        f"  Source group {group.source_group_id}: "
                        f"{cov.registered_views} / {cov.input_views} ({cov.ratio:.1%})"
                    )
                if candidate.blocking_issue_ids:
                    typer.echo("  FAIL issues: " + ", ".join(candidate.blocking_issue_ids))
                for name, metric in candidate.required_metrics:
                    typer.echo(
                        f"  {name}: {metric.value if metric.value is not None else metric.reason} "
                        f"[{metric.availability}]"
                    )
            typer.echo("; ".join(result.decision.reasons))
            typer.echo("Manual selection required.")
        else:
            typer.echo("Selection: " + result.status)
        if result.status in {"ambiguous", "blocked"}:
            raise typer.Exit(2)
    except (ValueError, OSError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc


@app.command("selection-show")
def selection_show(
    project: Path, run_id: UUID, json_output: Annotated[bool, typer.Option("--json")] = False
) -> None:
    try:
        service = build_reconstruction_selection_service()
        if json_output:
            import json

            artifact = service.inspect(project, run_id)
            typer.echo(
                json.dumps(
                    {
                        **artifact.model_dump(mode="json"),
                        "semantic_digest": artifact.semantic_digest,
                        "recipe_key": artifact.recipe_key,
                    },
                    indent=2,
                )
            )
        else:
            selection, report, metrics = service.inspect_details(project, run_id)
            selection_summary(selection, report, metrics)
    except (ValueError, OSError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
