"""Bounded sequential comparison over normal mapping attempts and canonical artifacts."""

from pathlib import Path
from time import monotonic
from uuid import UUID, uuid4

from splatforge.application.features_contracts import FeatureCapabilityError, FeatureTeardownError
from splatforge.application.mapping import MappingService
from splatforge.core.mapping_comparison import (
    MappingComparisonEntry,
    MappingComparisonPlan,
    MappingComparisonReport,
)


class MappingComparisonService:
    def __init__(self, mapping: MappingService) -> None:
        self.mapping = mapping

    def compare(
        self,
        root: Path,
        *,
        verification_run_id: UUID,
        plan: MappingComparisonPlan,
        colmap: Path | None = None,
    ) -> MappingComparisonReport:
        plan = MappingComparisonPlan.model_validate(plan.model_dump())
        frozen = self.mapping.comparison_input(root, verification_run_id)
        entries = []
        stopped = None
        for request in plan.routes:
            started = monotonic()
            common = dict(
                label=request.label, request=request, mapping_input_digest=frozen.semantic_digest
            )
            if stopped:
                entries.append(
                    MappingComparisonEntry(
                        **common, status="skipped", api_seconds=0, reason=stopped
                    )
                )
                continue
            if self.mapping.comparison_input(root, verification_run_id) != frozen:
                raise ValueError("Comparison immutable upstream MappingInput changed")
            try:
                result = self.mapping.run(
                    root,
                    verification_run_id=verification_run_id,
                    settings=request.settings,
                    calibration_policy=request.calibration_policy,
                    calibration_settings=request.calibration_settings,
                    resource_limits=request.resource_limits,
                    colmap=colmap,
                )
            except (ValueError, OSError) as exc:
                route = getattr(exc, "mapping_route", None)
                status = (
                    "unavailable"
                    if isinstance(exc, FeatureCapabilityError) and route is None
                    else "failed"
                )
                entries.append(
                    MappingComparisonEntry(
                        **common,
                        status=status,
                        api_seconds=monotonic() - started,
                        reason=str(exc),
                        failure_category=type(exc).__name__,
                        run_id=getattr(exc, "mapping_run_id", None),
                        recipe_key=route.recipe_key() if route else None,
                        backend=(
                            route.backend.model_dump(mode="json")
                            if route
                            else getattr(exc, "mapping_backend", None)
                        ),
                        estimated_workspace_bytes=route.estimate.peak_workspace_bytes
                        if route
                        else None,
                        native_seconds=getattr(exc, "mapping_native_seconds", None),
                    )
                )
                if isinstance(exc, FeatureTeardownError):
                    stopped = "Owned process teardown unresolved; comparison stopped"
                continue
            if result.mapping_input_digest != frozen.semantic_digest:
                raise ValueError("Comparison run consumed a different MappingInput")
            value = result.reconstruction
            points = [c.point_count for c in value.components] if value else []
            entries.append(
                MappingComparisonEntry(
                    **common,
                    status=result.status,
                    run_id=result.run_id,
                    artifact=result.artifact,
                    recipe_key=result.recipe_key,
                    backend=result.backend,
                    api_seconds=monotonic() - started,
                    native_seconds=result.native_seconds,
                    estimated_workspace_bytes=result.estimated_workspace_bytes,
                    component_count=value.component_count if value else None,
                    registered_views=value.registered_view_count if value else None,
                    unregistered_views=value.unregistered_view_count if value else None,
                    registration_coverage=value.registered_view_count / len(frozen.view_ids)
                    if value
                    else None,
                    native_point_count=sum(points) if points and None not in points else None,
                    semantic_digest=value.semantic_digest if value else None,
                    cache_hit=result.cache_hit,
                    warnings=result.warnings,
                    diagnostics=result.diagnostics,
                )
            )
            if result.status == "cancelled":
                stopped = "Comparison cancelled; no later routes launched"
        return MappingComparisonReport(
            comparison_id=uuid4(),
            verification_run_id=verification_run_id,
            mapping_input_digest=frozen.semantic_digest,
            hardware=self.mapping.hardware,
            data_kind=plan.data_kind,
            routes=tuple(entries),
        )
