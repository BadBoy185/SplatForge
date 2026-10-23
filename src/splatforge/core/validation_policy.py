"""Explicit conservative M9 policy evaluation, separate from numerical scanning."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from splatforge.core.features import Digest, digest_json
from splatforge.core.reconstruction_validation import (
    MetricValue,
    ReconstructionMetrics,
    exact,
)
from splatforge.core.views import FrozenModel


class ValidationStatus(StrEnum):
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"


class RequiredMetric(FrozenModel):
    name: str = Field(min_length=1, max_length=96)
    unavailable_severity: Literal["warning", "failure"] = "warning"
    sampled_acceptable: bool = True


class ReconstructionValidationPolicy(FrozenModel):
    policy_id: Literal["baseline_v1", "custom_v1"] = "baseline_v1"
    policy_version: Literal[1] = 1
    minimum_viable_cameras: int = Field(default=3, ge=1, le=100000, strict=True)
    warn_registration_below: float | None = Field(default=0.7, ge=0, le=1)
    warn_largest_coverage_below: float | None = Field(default=0.6, ge=0, le=1)
    warn_source_group_below: float | None = Field(default=0.25, ge=0, le=1)
    warn_registered_outside_largest_above: float | None = Field(default=0.25, ge=0, le=1)
    warn_focal_ratio_below: float | None = Field(default=0.1, gt=0)
    warn_focal_ratio_above: float | None = Field(default=10.0, gt=0)
    warn_principal_offset_above: float | None = Field(default=0.5, ge=0)
    warn_distortion_abs_above: float | None = Field(default=1.0, ge=0)
    warn_focal_change_above: float | None = Field(default=0.5, ge=0)
    warn_sharing_mismatch_above: int | None = Field(default=0, ge=0, strict=True)
    warn_reprojection_p95_above: float | None = Field(default=4.0, ge=0)
    warn_triangulation_median_below: float | None = Field(default=1.0, ge=0, le=90)
    warn_two_view_fraction_above: float | None = Field(default=0.8, ge=0, le=1)
    fail_registration_below: float | None = Field(default=None, ge=0, le=1)
    fail_component_coverage_below: float | None = Field(default=None, ge=0, le=1)
    fail_source_group_below: float | None = Field(default=None, ge=0, le=1)
    fail_reprojection_p95_above: float | None = Field(default=None, ge=0)
    fail_triangulation_median_below: float | None = Field(default=None, ge=0, le=90)
    required_metrics: tuple[RequiredMetric, ...] = Field(default=(), max_length=64)

    @model_validator(mode="after")
    def profile(self) -> ReconstructionValidationPolicy:
        if self.policy_id == "baseline_v1":
            defaults = {
                k: f.default
                for k, f in type(self).model_fields.items()
                if k not in {"policy_id", "policy_version"}
            }
            if any(getattr(self, k) != v for k, v in defaults.items()):
                raise ValueError("Changed thresholds require explicit policy_id=custom_v1")
        names = [m.name for m in self.required_metrics]
        if names != sorted(set(names)):
            raise ValueError("Required metrics must be unique and canonical")
        return self


class IssueScope(FrozenModel):
    kind: Literal["project", "component", "source_group"]
    component_id: UUID | None = None
    source_group_id: UUID | None = None

    @model_validator(mode="after")
    def consistent(self) -> IssueScope:
        if (
            (self.kind == "project" and (self.component_id or self.source_group_id))
            or (self.kind == "component" and (not self.component_id or self.source_group_id))
            or (self.kind == "source_group" and not self.source_group_id)
        ):
            raise ValueError("Issue scope identity mismatch")
        return self


class ValidationIssue(FrozenModel):
    issue_id: Digest
    code: str = Field(min_length=1, max_length=128)
    scope: IssueScope
    severity: Literal["warning", "failure"]
    metric: str = Field(min_length=1, max_length=96)
    observed: MetricValue
    condition: Literal["below", "above", "unavailable", "exact_required"]
    threshold: float | None = None
    message: str = Field(min_length=1, max_length=512)


class UnknownMetric(FrozenModel):
    scope: IssueScope
    metric: str
    evidence: MetricValue
    required: bool


class ComponentValidationStatus(FrozenModel):
    component_id: UUID
    status: ValidationStatus


class ReconstructionValidationReport(FrozenModel):
    contract_version: Literal[1] = 1
    reconstruction_digest: Digest
    metrics_digest: Digest
    policy: ReconstructionValidationPolicy
    status: ValidationStatus
    project_status: ValidationStatus
    components: tuple[ComponentValidationStatus, ...]
    issues: tuple[ValidationIssue, ...]
    unknown_metrics: tuple[UnknownMetric, ...]
    semantic_digest: Digest

    @model_validator(mode="after")
    def identity(self) -> ReconstructionValidationReport:
        def status(values):
            severities = {i.severity for i in values}
            return (
                ValidationStatus.FAIL
                if "failure" in severities
                else (ValidationStatus.WARN if "warning" in severities else ValidationStatus.PASS)
            )

        components = [c.component_id.int for c in self.components]
        known = {c.component_id for c in self.components}
        if (
            not components
            or components != sorted(set(components))
            or self.status != status(self.issues)
            or self.project_status != status(i for i in self.issues if i.scope.component_id is None)
            or any(
                i.scope.component_id is not None and i.scope.component_id not in known
                for i in self.issues
            )
            or any(
                c.status != status(i for i in self.issues if i.scope.component_id == c.component_id)
                for c in self.components
            )
        ):
            raise ValueError("Validation report status/scope inconsistency")
        if self.semantic_digest != report_digest(self):
            raise ValueError("Validation report semantic identity mismatch")
        keys = []
        for issue in self.issues:
            key = issue_key(issue)
            keys.append(key)
            if issue.issue_id != issue_identity(self.semantic_digest, issue):
                raise ValueError("Validation issue identity mismatch")
        if keys != sorted(set(keys)):
            raise ValueError("Validation issues must be unique and canonical")
        return self

    @property
    def recipe_key(self) -> str:
        return report_recipe(self.metrics_digest, self.policy)


def issue_key(issue: ValidationIssue) -> str:
    return digest_json({"code": issue.code, "scope": issue.scope.model_dump(mode="json")})


def issue_identity(report: str, issue: ValidationIssue) -> str:
    return digest_json({"report": report, "issue": issue_key(issue)})


def report_digest(report: ReconstructionValidationReport) -> str:
    data = report.model_dump(mode="json", exclude={"semantic_digest", "issues"})
    data["issues"] = [
        i.model_dump(mode="json", exclude={"issue_id", "message"}) for i in report.issues
    ]
    return digest_json(data)


def report_recipe(metrics_digest: str, policy: ReconstructionValidationPolicy) -> str:
    return digest_json(
        {
            "contract_version": 1,
            "evaluation_version": 1,
            "metrics": metrics_digest,
            "policy": policy.model_dump(mode="json"),
        }
    )


def evaluate_policy(
    metrics: ReconstructionMetrics,
    policy: ReconstructionValidationPolicy,
) -> ReconstructionValidationReport:
    issues, unknown = [], []
    required = {r.name: r for r in policy.required_metrics}
    known_names = {m.name for c in metrics.components for m in c.measurements}
    if set(required) - known_names:
        raise ValueError("validation.unknown_required_metric: unsupported required metric name")

    def check(code, scope, name, observed, threshold, condition, severity, message):
        if threshold is None or observed.value is None:
            return
        triggered = (
            observed.value < threshold if condition == "below" else (observed.value > threshold)
        )
        if triggered:
            issues.append(
                ValidationIssue(
                    issue_id="0" * 64,
                    code=code,
                    scope=scope,
                    severity=severity,
                    metric=name,
                    observed=observed,
                    threshold=threshold,
                    condition=condition,
                    message=message,
                )
            )

    project = IssueScope(kind="project")
    for severity, threshold in (
        ("warning", policy.warn_registration_below),
        ("failure", policy.fail_registration_below),
    ):
        check(
            "registration." + severity,
            project,
            "registration.coverage",
            exact(metrics.registration.ratio),
            threshold,
            "below",
            severity,
            "Inspect unregistered sources and overlap; start a new mapping plan explicitly.",
        )
    check(
        "fragmentation.largest_coverage",
        project,
        "fragmentation.largest_coverage",
        exact(metrics.largest_component.ratio),
        policy.warn_largest_coverage_below,
        "below",
        "warning",
        "Inspect whether disconnected scenes are intentional.",
    )
    check(
        "fragmentation.outside_largest",
        project,
        "fragmentation.outside_largest_fraction",
        exact(metrics.registered_outside_largest_fraction),
        policy.warn_registered_outside_largest_above,
        "above",
        "warning",
        "Components remain separate; inspect scene connectivity before selection.",
    )
    for group in metrics.source_groups:
        for component_id, cov in [
            (None, group.overall),
            *[(c.component_id, c.coverage) for c in group.components],
        ]:
            scope = IssueScope(
                kind="source_group", component_id=component_id, source_group_id=group.group_id
            )
            for severity, threshold in (
                ("warning", policy.warn_source_group_below),
                ("failure", policy.fail_source_group_below),
            ):
                check(
                    "source_group.coverage." + severity,
                    scope,
                    "source_group.coverage",
                    exact(cov.ratio),
                    threshold,
                    "below",
                    severity,
                    "Inspect this source group's missing selected views and capture overlap.",
                )
    checks = (
        ("camera.focal_ratio_min", policy.warn_focal_ratio_below, "below", "warning"),
        ("camera.focal_ratio_max", policy.warn_focal_ratio_above, "above", "warning"),
        ("camera.principal_offset_max", policy.warn_principal_offset_above, "above", "warning"),
        ("camera.distortion_abs_max", policy.warn_distortion_abs_above, "above", "warning"),
        ("camera.focal_change_max", policy.warn_focal_change_above, "above", "warning"),
        ("camera.sharing_mismatch_count", policy.warn_sharing_mismatch_above, "above", "warning"),
        ("reprojection.p95", policy.warn_reprojection_p95_above, "above", "warning"),
        ("reprojection.p95", policy.fail_reprojection_p95_above, "above", "failure"),
        ("triangulation.median", policy.warn_triangulation_median_below, "below", "warning"),
        ("triangulation.median", policy.fail_triangulation_median_below, "below", "failure"),
        ("track.two_view_fraction", policy.warn_two_view_fraction_above, "above", "warning"),
    )
    for component in metrics.components:
        scope = IssueScope(kind="component", component_id=component.component_id)
        check(
            "component.minimum_cameras",
            scope,
            "registration.registered_views",
            exact(component.registration.registered_views),
            policy.minimum_viable_cameras,
            "below",
            "failure",
            "Select a component with enough registered cameras.",
        )
        check(
            "component.coverage.failure",
            scope,
            "registration.coverage",
            exact(component.registration.ratio),
            policy.fail_component_coverage_below,
            "below",
            "failure",
            "Inspect component coverage or explicitly change policy.",
        )
        for name, threshold, condition, severity in checks:
            check(
                name + "." + severity,
                scope,
                name,
                component.metric(name),
                threshold,
                condition,
                severity,
                "Inspect " + name + " and its explicit policy threshold.",
            )
        for measurement in component.measurements:
            evidence = measurement.evidence
            requirement = required.get(measurement.name)
            missing = evidence.availability == "unavailable"
            insufficient = (
                requirement
                and not requirement.sampled_acceptable
                and (evidence.availability == "sampled")
            )
            if missing:
                unknown.append(
                    UnknownMetric(
                        scope=scope,
                        metric=measurement.name,
                        evidence=evidence,
                        required=requirement is not None,
                    )
                )
            if requirement and (missing or insufficient):
                issues.append(
                    ValidationIssue(
                        issue_id="0" * 64,
                        code="required." + measurement.name,
                        scope=scope,
                        severity=requirement.unavailable_severity,
                        metric=measurement.name,
                        observed=evidence,
                        condition="unavailable" if missing else "exact_required",
                        message=(
                            "Required measurement evidence is missing or insufficient; "
                            "inspect capability."
                        ),
                    )
                )

    def status(values):
        severities = {i.severity for i in values}
        return (
            ValidationStatus.FAIL
            if "failure" in severities
            else (ValidationStatus.WARN if "warning" in severities else ValidationStatus.PASS)
        )

    issues.sort(key=issue_key)
    report = ReconstructionValidationReport.model_construct(
        reconstruction_digest=metrics.reconstruction_digest,
        metrics_digest=metrics.semantic_digest,
        policy=policy,
        status=status(issues),
        project_status=status(i for i in issues if i.scope.component_id is None),
        components=tuple(
            ComponentValidationStatus(
                component_id=c.component_id,
                status=status(i for i in issues if i.scope.component_id == c.component_id),
            )
            for c in metrics.components
        ),
        issues=tuple(issues),
        unknown_metrics=tuple(unknown),
        semantic_digest="0" * 64,
    )
    digest = report_digest(report)
    return ReconstructionValidationReport.model_validate(
        {
            **report.model_dump(),
            "semantic_digest": digest,
            "issues": [
                i.model_copy(update={"issue_id": issue_identity(digest, i)}) for i in issues
            ],
        }
    )
