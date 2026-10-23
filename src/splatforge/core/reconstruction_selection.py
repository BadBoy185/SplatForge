"""M9b explicit immutable choices, transparent dominance and exact gate overrides."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from splatforge.core.features import Digest, digest_json
from splatforge.core.reconstruction import ReconstructionSet
from splatforge.core.reconstruction_validation import (
    Coverage,
    MetricValue,
    ReconstructionMetrics,
    ValidationGeometryInput,
)
from splatforge.core.validation_policy import (
    ReconstructionValidationReport,
    ValidationIssue,
    ValidationStatus,
)
from splatforge.core.views import MAX_VIEWS, FrozenModel

SELECTION_ARTIFACT_TYPE = "reconstruction.selection"


class RankingMetric(FrozenModel):
    name: Literal[
        "reprojection.mean",
        "reprojection.rms",
        "reprojection.p95",
        "reprojection.p99",
        "triangulation.median",
    ]
    direction: Literal["higher", "lower"]
    sampled_acceptable: bool = True

    @model_validator(mode="after")
    def meaningful_direction(self) -> RankingMetric:
        expected = "higher" if self.name == "triangulation.median" else "lower"
        if self.direction != expected:
            raise ValueError("Selection geometry comparison direction contradicts the metric")
        return self


class DominanceSelectionPolicy(FrozenModel):
    policy_id: Literal["selection.dominance_v1"] = "selection.dominance_v1"
    policy_version: Literal[1] = 1
    compare_validation_severity: bool = True
    # Coverage and every source group are always required comparable dimensions.
    # Geometry is used only if explicitly requested; unknown never ranks as best.
    required_ranking_metrics: tuple[RankingMetric, ...] = Field(default=(), max_length=64)

    @model_validator(mode="after")
    def canonical(self) -> DominanceSelectionPolicy:
        names = [m.name for m in self.required_ranking_metrics]
        if names != sorted(set(names)):
            raise ValueError("Selection ranking metrics must be unique and canonical")
        return self


class SelectedComponentContent(FrozenModel):
    component_id: UUID
    component_semantic_digest: Digest
    validation_geometry_digest: Digest


class ValidationFailureOverride(FrozenModel):
    reconstruction_artifact_id: UUID
    reconstruction_digest: Digest
    geometry_digest: Digest
    report_digest: Digest
    selected_components: tuple[SelectedComponentContent, ...] = Field(
        min_length=1, max_length=MAX_VIEWS
    )
    issue_ids: tuple[Digest, ...] = Field(min_length=1, max_length=100000)
    reason: str = Field(min_length=1, max_length=2048)

    @model_validator(mode="after")
    def explicit(self) -> ValidationFailureOverride:
        canonical_content(self.selected_components)
        if list(self.issue_ids) != sorted(set(self.issue_ids)) or not self.reason.strip():
            raise ValueError(
                "selection.invalid_override: unique canonical issues and reason required"
            )
        return self


class SelectionReason(FrozenModel):
    code: Literal[
        "manual_user_choice",
        "multiple_components_retained",
        "only_eligible_component",
        "dominates_all_required_dimensions",
    ]
    message: str = Field(min_length=1, max_length=2048)


class SourceGroupSelectionEvidence(FrozenModel):
    source_group_id: UUID
    coverage: Coverage


class SelectionCandidate(FrozenModel):
    component_id: UUID
    eligible: bool
    blocking_issue_ids: tuple[Digest, ...]
    registration: Coverage
    source_groups: tuple[SourceGroupSelectionEvidence, ...]
    validation_status: ValidationStatus
    required_metrics: tuple[tuple[str, MetricValue], ...] = ()


class SelectionDecision(FrozenModel):
    status: Literal["selected", "ambiguous", "blocked"]
    selected_component_ids: tuple[UUID, ...] = ()
    candidates: tuple[SelectionCandidate, ...]
    reasons: tuple[str, ...]

    @model_validator(mode="after")
    def genuine(self) -> SelectionDecision:
        if (self.status == "selected") != bool(self.selected_component_ids):
            raise ValueError("Ambiguous/blocked decisions cannot invent a selected component")
        return self


def canonical_content(content: tuple[SelectedComponentContent, ...]) -> None:
    ids = [c.component_id.int for c in content]
    if not ids or ids != sorted(set(ids)):
        raise ValueError("selection.invalid_components: content must be unique and canonical")


def selected_content(
    reconstruction: ReconstructionSet,
    geometry: ValidationGeometryInput,
    component_ids: tuple[UUID, ...],
) -> tuple[SelectedComponentContent, ...]:
    if not component_ids or len(set(component_ids)) != len(component_ids):
        raise ValueError("selection.invalid_components: supply nonempty unique component IDs")
    components = {c.component_id: c for c in reconstruction.components}
    details = {c.component_id: c for c in geometry.components}
    if geometry.reconstruction_digest != reconstruction.semantic_digest:
        raise ValueError("selection.stale_geometry: camera/pose reconstruction changed")
    if set(components) != set(details):
        raise ValueError("selection.stale_geometry: detailed component universe changed")
    if set(component_ids) - set(components):
        raise ValueError("selection.unknown_component: selected component does not exist")
    result = []
    for identity in sorted(component_ids, key=lambda v: v.int):
        if details[identity].component_semantic_digest != components[identity].semantic_digest:
            raise ValueError("selection.stale_geometry: component camera/pose content changed")
        result.append(
            SelectedComponentContent(
                component_id=identity,
                component_semantic_digest=components[identity].semantic_digest,
                validation_geometry_digest=details[identity].content_digest,
            )
        )
    return tuple(result)


def applicable_issues(
    report: ReconstructionValidationReport, selected: tuple[UUID, ...]
) -> tuple[ValidationIssue, ...]:
    return tuple(
        i for i in report.issues if i.scope.component_id is None or i.scope.component_id in selected
    )


def require_validation_evidence(
    reconstruction: ReconstructionSet,
    metrics: ReconstructionMetrics,
    report: ReconstructionValidationReport,
    geometry: ValidationGeometryInput,
) -> None:
    if (
        reconstruction.semantic_digest != metrics.reconstruction_digest
        or geometry != metrics.geometry
        or report.reconstruction_digest != reconstruction.semantic_digest
        or report.metrics_digest != metrics.semantic_digest
    ):
        raise ValueError(
            "selection.stale_validation: exact report/metrics/geometry no longer apply"
        )


def recommend_components(
    metrics: ReconstructionMetrics,
    report: ReconstructionValidationReport,
    policy: DominanceSelectionPolicy,
) -> SelectionDecision:
    if report.metrics_digest != metrics.semantic_digest:
        raise ValueError("selection.stale_validation: report does not evaluate these measurements")
    required = policy.required_ranking_metrics
    known = {m.name for c in metrics.components for m in c.measurements}
    if {r.name for r in required} - known:
        raise ValueError("selection.unknown_ranking_metric: unsupported measurement name")
    statuses = {c.component_id: c.status for c in report.components}
    by_group = {c.component_id: [] for c in metrics.components}
    for group in metrics.source_groups:
        for item in group.components:
            by_group[item.component_id].append(
                SourceGroupSelectionEvidence(source_group_id=group.group_id, coverage=item.coverage)
            )
    candidates, vectors = [], {}
    missing = False
    for component in metrics.components:
        identity = component.component_id
        failures = tuple(
            sorted(
                i.issue_id
                for i in applicable_issues(report, (identity,))
                if i.severity == "failure"
            )
        )
        evidence = tuple((r.name, component.metric(r.name)) for r in required)
        candidates.append(
            SelectionCandidate(
                component_id=identity,
                eligible=not failures,
                blocking_issue_ids=failures,
                registration=component.registration,
                source_groups=tuple(by_group[identity]),
                validation_status=statuses[identity],
                required_metrics=evidence,
            )
        )
        if failures:
            continue
        vector = [component.registration.registered_views, component.registration.ratio]
        vector.extend(g.coverage.ratio for g in by_group[identity])
        if policy.compare_validation_severity:
            vector.append(
                -{ValidationStatus.PASS: 0, ValidationStatus.WARN: 1, ValidationStatus.FAIL: 2}[
                    statuses[identity]
                ]
            )
        for rule, (_name, metric) in zip(required, evidence, strict=True):
            if metric.value is None or (
                not rule.sampled_acceptable and metric.availability == "sampled"
            ):
                missing = True
            else:
                vector.append(metric.value if rule.direction == "higher" else -metric.value)
        vectors[identity] = tuple(vector)
    if not vectors:
        return SelectionDecision(
            status="blocked",
            candidates=tuple(candidates),
            reasons=("no_eligible_component", "Inspect applicable FAIL issue IDs."),
        )
    if len(vectors) == 1:
        return SelectionDecision(
            status="selected",
            selected_component_ids=tuple(vectors),
            candidates=tuple(candidates),
            reasons=("only_eligible_component",),
        )
    if missing:
        return SelectionDecision(
            status="ambiguous",
            candidates=tuple(candidates),
            reasons=("required_comparison_evidence_unavailable", "Manual selection required."),
        )
    # A total dominator must attain every coordinate's optimum. This is O(N*D),
    # with no pairwise N^2 scan, scores, UUID ordering or largest tie-break.
    optimum = tuple(max(values) for values in zip(*vectors.values(), strict=True))
    dominant = tuple(identity for identity, vector in vectors.items() if vector == optimum)
    if len(dominant) != 1:
        return SelectionDecision(
            status="ambiguous",
            candidates=tuple(candidates),
            reasons=(
                "coverage_or_severity_tradeoff_or_equal_evidence",
                "Manual selection required.",
            ),
        )
    return SelectionDecision(
        status="selected",
        selected_component_ids=dominant,
        candidates=tuple(candidates),
        reasons=("dominates_all_required_dimensions",),
    )


class ReconstructionSelection(FrozenModel):
    contract_version: Literal[1] = 1
    reconstruction_digest: Digest
    report_digest: Digest
    selected_components: tuple[SelectedComponentContent, ...] = Field(
        min_length=1, max_length=MAX_VIEWS
    )
    mode: Literal["manual", "recommended"]
    policy: DominanceSelectionPolicy | None
    reasons: tuple[SelectionReason, ...] = Field(min_length=1, max_length=4)
    override: ValidationFailureOverride | None = None
    warning_issue_ids: tuple[Digest, ...]

    @model_validator(mode="after")
    def explicit(self) -> ReconstructionSelection:
        canonical_content(self.selected_components)
        if (self.mode == "recommended") != (self.policy is not None):
            raise ValueError("Manual choice must not be reinterpreted as a policy recommendation")
        if self.mode == "recommended" and len(self.selected_components) != 1:
            raise ValueError("Dominance v1 recommends exactly one component")
        if list(self.warning_issue_ids) != sorted(set(self.warning_issue_ids)):
            raise ValueError("Selection warnings must be canonical")
        return self

    @property
    def selected_component_ids(self) -> tuple[UUID, ...]:
        return tuple(c.component_id for c in self.selected_components)

    @property
    def semantic_digest(self) -> str:
        return digest_json(
            {
                "contract_version": 1,
                "reconstruction": self.reconstruction_digest,
                "separate_components": [
                    c.model_dump(mode="json") for c in self.selected_components
                ],
            }
        )

    @property
    def recipe_key(self) -> str:
        return digest_json({"decision_version": 1, **self.model_dump(mode="json")})

    def require_current(
        self,
        reconstruction: ReconstructionSet,
        geometry: ValidationGeometryInput,
        report: ReconstructionValidationReport,
        reconstruction_artifact_id: UUID,
    ) -> None:
        expected = selected_content(reconstruction, geometry, self.selected_component_ids)
        if (
            expected != self.selected_components
            or reconstruction.semantic_digest != self.reconstruction_digest
            or report.semantic_digest != self.report_digest
        ):
            raise ValueError("selection.stale_selection: content or validation evidence changed")
        require_override(
            reconstruction_artifact_id, reconstruction, geometry, report, expected, self.override
        )


def require_override(
    reconstruction_artifact_id: UUID,
    reconstruction: ReconstructionSet,
    geometry: ValidationGeometryInput,
    report: ReconstructionValidationReport,
    selected: tuple[SelectedComponentContent, ...],
    override: ValidationFailureOverride | None,
) -> None:
    identities = tuple(c.component_id for c in selected)
    failures = {
        i.issue_id for i in applicable_issues(report, identities) if i.severity == "failure"
    }
    if override is None:
        if failures:
            raise ValueError(
                "selection.validation_failed: explicitly target applicable failure "
                "issue IDs and provide a reason: " + ", ".join(sorted(failures))
            )
        return
    ValidationFailureOverride.model_validate(override.model_dump())
    if (
        override.reconstruction_artifact_id != reconstruction_artifact_id
        or override.reconstruction_digest != reconstruction.semantic_digest
        or override.geometry_digest != geometry.semantic_digest
        or override.report_digest != report.semantic_digest
        or override.selected_components != selected
    ):
        raise ValueError("selection.stale_override: create new explicit evidence for these inputs")
    if set(override.issue_ids) != failures:
        raise ValueError(
            "selection.invalid_override: target every applicable FAIL issue exactly; "
            "unknown, warning and unselected issues cannot be overridden"
        )


def make_selection(
    reconstruction_artifact_id: UUID,
    reconstruction: ReconstructionSet,
    metrics: ReconstructionMetrics,
    report: ReconstructionValidationReport,
    geometry: ValidationGeometryInput,
    component_ids: tuple[UUID, ...],
    *,
    mode: Literal["manual", "recommended"] = "manual",
    policy: DominanceSelectionPolicy | None = None,
    manual_reason: str = "Manual user choice.",
    override: ValidationFailureOverride | None = None,
) -> ReconstructionSelection:
    require_validation_evidence(reconstruction, metrics, report, geometry)
    content = selected_content(reconstruction, geometry, component_ids)
    require_override(
        reconstruction_artifact_id, reconstruction, geometry, report, content, override
    )
    if mode == "manual":
        if policy is not None or not manual_reason.strip():
            raise ValueError("Manual selection requires a reason and no recommendation policy")
        reasons = (
            SelectionReason(
                code="multiple_components_retained" if len(content) > 1 else "manual_user_choice",
                message=manual_reason,
            ),
        )
    else:
        policy = policy or DominanceSelectionPolicy()
        if override is not None:
            raise ValueError(
                "Automatic failure overrides require an explicit manual component choice"
            )
        decision = recommend_components(metrics, report, policy)
        if decision.status != "selected" or decision.selected_component_ids != tuple(
            c.component_id for c in content
        ):
            raise ValueError("selection.not_recommended: no unique dominant eligible component")
        code = decision.reasons[0]
        reasons = (
            SelectionReason(
                code=code,
                message=(
                    "Only eligible component."
                    if code == "only_eligible_component"
                    else "No worse on every required comparable dimension; "
                    "strictly better on at least one dimension against every alternative."
                ),
            ),
        )
    return ReconstructionSelection(
        reconstruction_digest=reconstruction.semantic_digest,
        report_digest=report.semantic_digest,
        selected_components=content,
        mode=mode,
        policy=policy,
        reasons=reasons,
        override=override,
        warning_issue_ids=tuple(
            sorted(i.issue_id for i in report.issues if i.severity == "warning")
        ),
    )


class ReconstructionSelectionArtifact(FrozenModel):
    contract_version: Literal[1] = 1
    reconstruction_artifact_id: UUID
    report_artifact_id: UUID
    metrics_artifact_id: UUID
    geometry_artifact_id: UUID
    selection: ReconstructionSelection

    @property
    def semantic_digest(self) -> str:
        return self.selection.semantic_digest

    @property
    def recipe_key(self) -> str:
        return self.selection.recipe_key
