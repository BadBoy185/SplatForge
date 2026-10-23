"""M9b explicit decisions over exact frozen M9a evidence; no mapper dependency."""

from __future__ import annotations

from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

from splatforge.application.reconstruction_validation import (
    EvidenceRunResult,
    ReconstructionValidationService,
    ValidationRepository,
    require_geometry_evidence,
)
from splatforge.core.execution import ReconstructionSelectionRoute
from splatforge.core.reconstruction_selection import (
    DominanceSelectionPolicy,
    ReconstructionSelection,
    ReconstructionSelectionArtifact,
    SelectionDecision,
    ValidationFailureOverride,
    make_selection,
    recommend_components,
    selected_content,
)
from splatforge.core.reconstruction_validation import ReconstructionMetrics
from splatforge.core.validation_policy import ReconstructionValidationReport, evaluate_policy
from splatforge.core.views import FrozenModel


class ReconstructionSelectionResult(FrozenModel):
    status: Literal["succeeded", "ambiguous", "blocked", "cancelled"]
    run: EvidenceRunResult | None
    decision: SelectionDecision | None
    selection: ReconstructionSelection | None


class ReconstructionSelectionService:
    def __init__(self, executor: ReconstructionValidationService) -> None:
        self.executor, self.repository = executor, executor.repository

    def inspect(self, root: Path, run_id: UUID) -> ReconstructionSelectionArtifact:
        with self.repository.validation_evidence_operation():
            handle = self.repository.resolve_run_output(
                root, run_id, "reconstruction_selection", "selection"
            )
            return self.repository.load_validation_artifact(root, handle)

    def inspect_details(
        self, root: Path, run_id: UUID
    ) -> tuple[ReconstructionSelection, ReconstructionValidationReport, ReconstructionMetrics]:
        repo = self.repository
        with repo.validation_evidence_operation():
            handle = repo.resolve_run_output(root, run_id, "reconstruction_selection", "selection")
            selection = repo.load_validation_artifact(root, handle).selection
            report = repo.load_validation_artifact(
                root, repo.lineage_handle(root, handle, "validation_report")
            ).report
            metrics = repo.load_validation_artifact(
                root, repo.lineage_handle(root, handle, "reconstruction_metrics")
            ).metrics
        return selection, report, metrics

    def select(
        self,
        root: Path,
        *,
        validation_run_id: UUID,
        component_ids: tuple[UUID, ...] = (),
        mode: Literal["manual", "recommended"] | None = None,
        policy: DominanceSelectionPolicy | None = None,
        manual_reason: str = "Manual user choice.",
        override_issue_ids: tuple[str, ...] = (),
        override_reason: str | None = None,
        override: ValidationFailureOverride | None = None,
    ) -> ReconstructionSelectionResult:
        root, owner = root.resolve(), uuid4()
        mode = mode or ("manual" if component_ids else "recommended")
        if mode not in {"manual", "recommended"}:
            raise ValueError("Choose manual or recommended selection mode")
        if mode == "recommended" and (
            component_ids or override or override_issue_ids or override_reason
        ):
            raise ValueError(
                "Recommended selection accepts no manual components or failure overrides"
            )
        if mode == "manual" and policy is not None:
            raise ValueError("Manual choice does not accept a recommendation policy")
        if override is not None and (override_issue_ids or override_reason):
            raise ValueError("Supply one exact override object or issue IDs/reason, not both")
        if bool(override_issue_ids) != (override_reason is not None):
            raise ValueError("Override requires exact failure issue IDs plus a non-empty reason")
        policy = (
            DominanceSelectionPolicy.model_validate(
                (policy or DominanceSelectionPolicy()).model_dump()
            )
            if mode == "recommended"
            else None
        )
        if override is not None:
            override = ValidationFailureOverride.model_validate(override.model_dump())
        repo = self.repository
        with (
            repo.writer(root, owner_token=owner, operation="reconstruction-selection"),
            repo.validation_evidence_operation(),
        ):
            repo.ensure_no_unfinished_run(root)
            validation_route, report_handle = repo.validation_run_context(root, validation_run_id)
            reconstruction = repo.load_reconstruction(root, validation_route.reconstruction)
            report = repo.load_validation_artifact(root, report_handle).report
            metrics = repo.load_validation_artifact(root, validation_route.metrics).metrics
            geometry = repo.load_validation_artifact(
                root, validation_route.geometry_artifact
            ).geometry
            decision = None
            if mode == "recommended":
                decision = recommend_components(metrics, report, policy)
                if decision.status != "selected":
                    return ReconstructionSelectionResult(
                        status=decision.status, run=None, decision=decision, selection=None
                    )
                component_ids = decision.selected_component_ids
            content = selected_content(reconstruction, geometry, component_ids)
            if override_issue_ids:
                if len(set(override_issue_ids)) != len(override_issue_ids):
                    raise ValueError("Duplicate override issue IDs are not allowed")
                override = ValidationFailureOverride(
                    reconstruction_artifact_id=validation_route.reconstruction.artifact_id,
                    reconstruction_digest=reconstruction.semantic_digest,
                    geometry_digest=geometry.semantic_digest,
                    report_digest=report.semantic_digest,
                    selected_components=content,
                    issue_ids=tuple(sorted(override_issue_ids)),
                    reason=override_reason,
                )
            selection = make_selection(
                validation_route.reconstruction.artifact_id,
                reconstruction,
                metrics,
                report,
                geometry,
                component_ids,
                mode=mode,
                policy=policy,
                manual_reason=manual_reason,
                override=override,
            )
            route = ReconstructionSelectionRoute(
                reconstruction=validation_route.reconstruction,
                report=report_handle,
                metrics=validation_route.metrics,
                geometry_artifact=validation_route.geometry_artifact,
                decision=selection,
            )
            result = self.executor.execute(root, owner, route)
            return ReconstructionSelectionResult(
                status=result.status,
                run=result,
                decision=decision,
                selection=selection if result.status == "succeeded" else None,
            )


def require_selection_inputs(
    repo: ValidationRepository, root: Path, route: ReconstructionSelectionRoute
) -> None:
    reconstruction = repo.load_reconstruction(root, route.reconstruction)
    geometry = repo.load_validation_artifact(root, route.geometry_artifact)
    require_geometry_evidence(repo, root, route.reconstruction, geometry)
    report = repo.load_validation_artifact(root, route.report).report
    metrics = repo.load_validation_artifact(root, route.metrics).metrics
    expected_report = evaluate_policy(metrics, report.policy)
    if (
        report.semantic_digest != expected_report.semantic_digest
        or metrics.geometry != geometry.geometry
        or metrics.universe_digest != geometry.universe.semantic_digest
    ):
        raise ValueError("selection.stale_validation: report/metrics/detailed input differ")
    expected = make_selection(
        route.reconstruction.artifact_id,
        reconstruction,
        metrics,
        report,
        geometry.geometry,
        route.decision.selected_component_ids,
        mode=route.decision.mode,
        policy=route.decision.policy,
        manual_reason=route.decision.reasons[0].message,
        override=route.decision.override,
    )
    if expected.recipe_key != route.decision.recipe_key:
        raise ValueError("selection.stale_selection: frozen decision no longer applies")
