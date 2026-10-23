"""M9a orchestration: frozen lineage -> geometry -> measurements -> policy.

Each explicit stage uses normal run/attempt/publication machinery. There is no
mapping adapter dependency and no possible feedback loop to M8.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol
from uuid import UUID, uuid4

from splatforge.application.execution import (
    ExecutionCancelledError,
    ExecutionRepository,
    PublicationUnresolvedError,
    StateUpgradeRequiredError,
)
from splatforge.application.features import _Cancellation
from splatforge.application.progress import ProgressSupport
from splatforge.application.work_models import validation_progress_plan
from splatforge.core.execution import (
    ArtifactHandle,
    FailureCategory,
    ReconstructionEvidenceRoute,
    ReconstructionMeasurementRoute,
    ReconstructionSelectionRoute,
    ReconstructionValidationRoute,
    RunSnapshot,
    RunStatus,
    ValidationGeometryRoute,
)
from splatforge.core.progress import WorkMetric
from splatforge.core.reconstruction import ReconstructionSet
from splatforge.core.reconstruction_selection import ReconstructionSelectionArtifact
from splatforge.core.reconstruction_validation import (
    MeasurementSettings,
    ReconstructionMetrics,
    ValidationGeometrySource,
    ValidationResourceLimits,
    ValidationUniverse,
    require_measurement_resources,
)
from splatforge.core.validation_artifacts import (
    ReconstructionMetricsArtifact,
    ReconstructionReportArtifact,
    ValidationArtifact,
    ValidationGeometryArtifact,
)
from splatforge.core.validation_measurements import geometry_identity, measure_reconstruction
from splatforge.core.validation_policy import (
    ReconstructionValidationPolicy,
    ReconstructionValidationReport,
    evaluate_policy,
)
from splatforge.core.views import FrozenModel


class ValidationRepository(ExecutionRepository, Protocol):
    def validation_operation(self) -> AbstractContextManager: ...
    def validation_evidence_operation(self) -> AbstractContextManager: ...

    def lineage_handle(self, root: Path, handle: ArtifactHandle, name: str) -> ArtifactHandle: ...
    def validation_run_context(
        self, root: Path, run_id: UUID
    ) -> tuple[ReconstructionValidationRoute, ArtifactHandle]: ...
    def resolve_run_output(
        self, root: Path, run_id: UUID, node_id: str, output_name: str
    ) -> ArtifactHandle: ...
    def load_reconstruction(self, root: Path, handle: ArtifactHandle) -> ReconstructionSet: ...
    def artifact_directory(self, root: Path, handle: ArtifactHandle) -> Path: ...
    def validation_universe(
        self, root: Path, reconstruction: ArtifactHandle
    ) -> tuple[ArtifactHandle, ArtifactHandle, ValidationUniverse]: ...
    def validation_native_digest(self, root: Path, handle: ArtifactHandle) -> str: ...
    def load_validation_artifact(
        self, root: Path, handle: ArtifactHandle
    ) -> ValidationArtifact: ...
    def write_validation_artifact(self, workspace: Path, value: ValidationArtifact) -> None: ...


class ValidationSourceFactory(Protocol):
    def __call__(
        self,
        directory: Path,
        reconstruction: ReconstructionSet,
        workspace: Path,
        limits: ValidationResourceLimits,
        checkpoint: Callable[[], None],
    ) -> ValidationGeometrySource: ...


class EvidenceRunResult(FrozenModel):
    run_id: UUID
    status: RunStatus
    artifact: ArtifactHandle | None
    cache_hit: bool


class ReconstructionValidationResult(FrozenModel):
    run_id: UUID
    status: RunStatus
    geometry_run: EvidenceRunResult
    metrics_run: EvidenceRunResult | None
    report_run: EvidenceRunResult | None
    report: ReconstructionValidationReport | None


class ReconstructionValidationService:
    def __init__(
        self,
        repository: ValidationRepository,
        source_factory: ValidationSourceFactory,
        *,
        progress: ProgressSupport | None = None,
    ) -> None:
        self.repository, self.source_factory = repository, source_factory
        self.progress = progress or ProgressSupport()

    def inspect(self, root: Path, run_id: UUID) -> ReconstructionReportArtifact:
        with self.repository.validation_evidence_operation():
            handle = self.repository.resolve_run_output(
                root, run_id, "reconstruction_validation", "report"
            )
            return self.repository.load_validation_artifact(root, handle)

    def inspect_details(
        self, root: Path, run_id: UUID
    ) -> tuple[ReconstructionValidationReport, ReconstructionMetrics]:
        repo = self.repository
        with repo.validation_evidence_operation():
            handle = repo.resolve_run_output(root, run_id, "reconstruction_validation", "report")
            report = repo.load_validation_artifact(root, handle).report
            metrics_handle = repo.lineage_handle(root, handle, "reconstruction_metrics")
            metrics = repo.load_validation_artifact(root, metrics_handle).metrics
        return report, metrics

    def validate(
        self,
        root: Path,
        *,
        mapping_run_id: UUID,
        settings: MeasurementSettings | None = None,
        policy: ReconstructionValidationPolicy | None = None,
        resource_limits: ValidationResourceLimits | None = None,
    ) -> ReconstructionValidationResult:
        root, owner = root.resolve(), uuid4()
        repo = self.repository
        settings = MeasurementSettings.model_validate(
            (settings or MeasurementSettings()).model_dump()
        )
        policy = ReconstructionValidationPolicy.model_validate(
            (policy or ReconstructionValidationPolicy()).model_dump()
        )
        limits = ValidationResourceLimits.model_validate(
            (resource_limits or ValidationResourceLimits()).model_dump()
        )
        with (
            repo.writer(root, owner_token=owner, operation="reconstruction-validation"),
            repo.validation_evidence_operation(),
        ):
            repo.ensure_no_unfinished_run(root)
            reconstruction = repo.resolve_run_output(
                root, mapping_run_id, "reconstruction", "reconstruction"
            )
            value = repo.load_reconstruction(root, reconstruction)
            candidate, selected, universe = repo.validation_universe(root, reconstruction)
            require_measurement_resources(value, universe, limits)
            route = ValidationGeometryRoute(
                reconstruction=reconstruction,
                candidate=candidate,
                selected=selected,
                universe=universe,
                native_payload_digest=repo.validation_native_digest(root, reconstruction),
                resource_limits=limits,
                point_total=sum(c.point_count for c in value.components)
                if all(c.point_count is not None for c in value.components)
                else None,
            )
            geometry_run = self.execute(root, owner, route)
            if geometry_run.status != "succeeded":
                return ReconstructionValidationResult(
                    run_id=geometry_run.run_id,
                    status=geometry_run.status,
                    geometry_run=geometry_run,
                    metrics_run=None,
                    report_run=None,
                    report=None,
                )
            geometry = repo.load_validation_artifact(root, geometry_run.artifact)
            route = ReconstructionMeasurementRoute(
                reconstruction=reconstruction,
                geometry_artifact=geometry_run.artifact,
                geometry=geometry.geometry,
                universe=universe,
                settings=settings,
                resource_limits=limits,
            )
            metrics_run = self.execute(root, owner, route)
            if metrics_run.status != "succeeded":
                return ReconstructionValidationResult(
                    run_id=metrics_run.run_id,
                    status=metrics_run.status,
                    geometry_run=geometry_run,
                    metrics_run=metrics_run,
                    report_run=None,
                    report=None,
                )
            route = ReconstructionValidationRoute(
                reconstruction=reconstruction,
                metrics=metrics_run.artifact,
                geometry_artifact=geometry_run.artifact,
                policy=policy,
                resource_limits=limits,
            )
            report_run = self.execute(root, owner, route)
            report = (
                repo.load_validation_artifact(root, report_run.artifact).report
                if report_run.artifact
                else None
            )
            return ReconstructionValidationResult(
                run_id=report_run.run_id,
                status=report_run.status,
                geometry_run=geometry_run,
                metrics_run=metrics_run,
                report_run=report_run,
                report=report,
            )

    def produce(
        self,
        root: Path,
        route: ReconstructionEvidenceRoute,
        workspace: Path,
        checkpoint: Callable[[], None],
        progress: Callable[[int, int], None],
    ) -> ValidationArtifact:
        repo = self.repository
        reconstruction = repo.load_reconstruction(root, route.reconstruction)
        if isinstance(route, ReconstructionSelectionRoute):
            return ReconstructionSelectionArtifact(
                reconstruction_artifact_id=route.reconstruction.artifact_id,
                report_artifact_id=route.report.artifact_id,
                metrics_artifact_id=route.metrics.artifact_id,
                geometry_artifact_id=route.geometry_artifact.artifact_id,
                selection=route.decision,
            )
        if isinstance(route, ReconstructionValidationRoute):
            metrics = repo.load_validation_artifact(root, route.metrics).metrics
            return ReconstructionReportArtifact(
                reconstruction_artifact_id=route.reconstruction.artifact_id,
                metrics_artifact_id=route.metrics.artifact_id,
                geometry_artifact_id=route.geometry_artifact.artifact_id,
                report=evaluate_policy(metrics, route.policy),
            )
        source = self.source_factory(
            repo.artifact_directory(root, route.reconstruction),
            reconstruction,
            workspace,
            route.resource_limits,
            checkpoint,
        )
        # The native adapter throttles expensive durable cancellation checks; pure
        # test/future sources can use the supplied owner checkpoint directly.
        guard = getattr(source, "checkpoint", checkpoint)
        if isinstance(route, ValidationGeometryRoute):
            geometry = geometry_identity(reconstruction, source, guard, progress)
            return ValidationGeometryArtifact(
                reconstruction_artifact_id=route.reconstruction.artifact_id,
                candidate_artifact_id=route.candidate.artifact_id,
                selected_artifact_id=route.selected.artifact_id,
                universe=route.universe,
                native_payload_digest=route.native_payload_digest,
                geometry=geometry,
            )
        metrics = measure_reconstruction(
            reconstruction,
            route.universe,
            route.geometry,
            source,
            route.settings,
            guard,
            progress,
            resource_limits=route.resource_limits,
        )
        return ReconstructionMetricsArtifact(
            reconstruction_artifact_id=route.reconstruction.artifact_id,
            geometry_artifact_id=route.geometry_artifact.artifact_id,
            metrics=metrics,
        )

    def execute(
        self, root: Path, owner: UUID, route: ReconstructionEvidenceRoute
    ) -> EvidenceRunResult:
        """One of the bounded M9 stages; callers already hold the project writer."""
        repo = self.repository
        project = repo.inspect_project(root)
        if project.state_version != 4:
            raise StateUpgradeRequiredError("Run 'splatforge project upgrade-state <project>'")
        repo.ensure_no_unfinished_run(root)
        require_validation_inputs(repo, root, route)
        run_id = uuid4()
        repo.create_run(
            root,
            RunSnapshot(
                run_id=run_id,
                project_id=project.document.project_id,
                project_revision=project.document.revision,
                owner_token=owner,
                created_at=datetime.now(UTC),
                project_intent=project.document,
                route=route,
            ),
        )
        session = self.progress.session(
            run_id,
            (validation_progress_plan(route, self.progress.hardware),),
            emit=lambda node, attempt, details: repo.append_event(
                root,
                run_id,
                code="progress.snapshot",
                node_id=node,
                attempt_id=attempt,
                details=details,
            ),
        )
        control, attempt = _Cancellation(repo, root, run_id), None
        artifact, cache_hit = None, False
        latest_scan: tuple[int, int] | None = None

        def report(points, observations):
            nonlocal latest_scan
            latest_scan = (points, observations)
            if points % 128 == 0:
                session.report(
                    route.node_id,
                    points,
                    phase="scanning_points",
                    diagnostics=(WorkMetric(name="observations", value=observations),),
                )

        try:
            repo.append_event(root, run_id, code="validation.stage.started", node_id=route.node_id)
            control.checkpoint()
            cached = repo.find_cache(
                root,
                recipe_key=route.recipe_key(),
                artifact_type=route.target.artifact_type,
                contract_version=1,
            )
            if cached.artifact:
                payload = repo.load_validation_artifact(root, cached.artifact)
                require_validation_payload(repo, root, route, payload)
                control.checkpoint()
                repo.bind_cached_output(
                    root,
                    run_id=run_id,
                    node_id=route.node_id,
                    output_name=route.target.output_name,
                    artifact_id=cached.artifact.artifact_id,
                )
                artifact, cache_hit = cached.artifact, True
                session.cached(route.node_id)
            else:
                attempt = repo.begin_attempt(
                    root,
                    run_id=run_id,
                    node_id=route.node_id,
                    output_name=route.target.output_name,
                    recipe_key=route.recipe_key(),
                    input_artifact_ids=tuple(i.artifact_id for i in route.input_lineage()),
                    literal_inputs=route.literal_inputs(),
                    environment={"adapter_id": "splatforge.validation_python", "version": 1},
                    source_verification={"policy": "artifact_integrity", "evidence": []},
                )
                control.attempt = attempt.attempt_id
                session.start(route.node_id, attempt.attempt_id)
                payload = self.produce(
                    root, route, Path(attempt.workspace), control.checkpoint, report
                )
                if latest_scan is not None:
                    session.report(
                        route.node_id,
                        latest_scan[0],
                        phase="validating_output",
                        diagnostics=(WorkMetric(name="observations", value=latest_scan[1]),),
                        force=True,
                    )
                require_validation_payload(repo, root, route, payload, exact_lineage=True)
                repo.write_validation_artifact(Path(attempt.workspace), payload)
                control.checkpoint()
                artifact = repo.publish_attempt(
                    root,
                    run_id=run_id,
                    node_id=route.node_id,
                    output_name=route.target.output_name,
                    artifact_type=route.target.artifact_type,
                    contract_version=1,
                    recipe_key=route.recipe_key(),
                    attempt=attempt,
                    input_lineage=route.input_lineage(),
                )
            control.checkpoint()
            repo.mark_run_succeeded(root, run_id=run_id)
            if not cache_hit:
                session.complete(route.node_id)
            repo.append_event(
                root,
                run_id,
                code="validation.stage.completed",
                node_id=route.node_id,
                details={"cache_hit": cache_hit},
            )
            return EvidenceRunResult(
                run_id=run_id, status="succeeded", artifact=artifact, cache_hit=cache_hit
            )
        except ExecutionCancelledError:
            status = repo.finish_cancellation(
                root, run_id=run_id, attempt_id=control.attempt, teardown_confirmed=True
            )
            return EvidenceRunResult(run_id=run_id, status=status, artifact=None, cache_hit=False)
        except PublicationUnresolvedError:
            raise
        except Exception as exc:
            if attempt:
                repo.mark_attempt_failed(
                    root,
                    attempt_id=attempt.attempt_id,
                    message=str(exc),
                    category=FailureCategory.NON_RETRYABLE,
                )
            repo.mark_run_failed(root, run_id=run_id, message=str(exc))
            raise


def require_validation_inputs(
    repo: ValidationRepository, root: Path, route: ReconstructionEvidenceRoute
) -> None:
    reconstruction = repo.load_reconstruction(root, route.reconstruction)
    if isinstance(route, ReconstructionSelectionRoute):
        from splatforge.application.reconstruction_selection import require_selection_inputs

        require_selection_inputs(repo, root, route)
        return
    if isinstance(route, ValidationGeometryRoute):
        candidate, selected, universe = repo.validation_universe(root, route.reconstruction)
        if (candidate, selected, universe) != (
            route.candidate,
            route.selected,
            route.universe,
        ) or repo.validation_native_digest(
            root, route.reconstruction
        ) != route.native_payload_digest:
            raise ValueError("validation.input_mismatch: frozen universe/native evidence differs")
    elif isinstance(route, ReconstructionMeasurementRoute):
        geometry = repo.load_validation_artifact(root, route.geometry_artifact)
        if geometry.geometry != route.geometry or geometry.universe != route.universe:
            raise ValueError("validation.input_mismatch: frozen detailed geometry/universe differs")
        route.universe.require_reconstruction(reconstruction)
        if route.geometry.reconstruction_digest != reconstruction.semantic_digest:
            raise ValueError("validation.input_mismatch: stale detailed geometry")
        require_geometry_evidence(repo, root, route.reconstruction, geometry)
    else:
        metrics = repo.load_validation_artifact(root, route.metrics).metrics
        geometry = repo.load_validation_artifact(root, route.geometry_artifact)
        require_geometry_evidence(repo, root, route.reconstruction, geometry)
        if (
            metrics.reconstruction_digest != reconstruction.semantic_digest
            or metrics.geometry != geometry.geometry
            or metrics.universe_digest != geometry.universe.semantic_digest
        ):
            raise ValueError("validation.input_mismatch: stale measurement evidence")


def require_geometry_evidence(
    repo: ValidationRepository,
    root: Path,
    reconstruction: ArtifactHandle,
    geometry: ValidationGeometryArtifact,
) -> None:
    if (
        geometry.geometry.reconstruction_digest != reconstruction.semantic_digest
        or repo.validation_native_digest(root, reconstruction) != geometry.native_payload_digest
    ):
        raise ValueError("validation.input_mismatch: detailed geometry belongs to another input")


def require_validation_payload(
    repo: ValidationRepository,
    root: Path,
    route: ReconstructionEvidenceRoute,
    payload: ValidationArtifact,
    *,
    exact_lineage: bool = False,
) -> None:
    if payload.recipe_key != route.recipe_key():
        raise ValueError("validation.input_mismatch: payload recipe differs from frozen route")
    if exact_lineage and payload.reconstruction_artifact_id != route.reconstruction.artifact_id:
        raise ValueError("validation.input_mismatch: reconstruction publication differs")
    if isinstance(route, ReconstructionSelectionRoute):
        if not isinstance(payload, ReconstructionSelectionArtifact) or (
            payload.selection != route.decision
            or (
                exact_lineage
                and (
                    payload.report_artifact_id != route.report.artifact_id
                    or payload.metrics_artifact_id != route.metrics.artifact_id
                    or payload.geometry_artifact_id != route.geometry_artifact.artifact_id
                )
            )
        ):
            raise ValueError("selection.input_mismatch: selection differs from frozen decision")
        return
    if isinstance(route, ValidationGeometryRoute):
        if not isinstance(payload, ValidationGeometryArtifact) or (
            payload.universe != route.universe
            or payload.geometry.reconstruction_digest != route.reconstruction.semantic_digest
            or payload.native_payload_digest != route.native_payload_digest
            or (
                exact_lineage
                and (
                    payload.candidate_artifact_id != route.candidate.artifact_id
                    or payload.selected_artifact_id != route.selected.artifact_id
                )
            )
        ):
            raise ValueError("validation.input_mismatch: geometry receipt differs")
    elif isinstance(route, ReconstructionMeasurementRoute):
        if not isinstance(payload, ReconstructionMetricsArtifact) or (
            payload.metrics.geometry != route.geometry
            or payload.metrics.universe_digest != route.universe.semantic_digest
            or payload.metrics.settings != route.settings
            or (
                exact_lineage
                and payload.geometry_artifact_id != route.geometry_artifact.artifact_id
            )
        ):
            raise ValueError("validation.input_mismatch: measurement receipt differs")
    elif isinstance(route, ReconstructionValidationRoute):
        expected = evaluate_policy(
            repo.load_validation_artifact(root, route.metrics).metrics, route.policy
        )
        if not isinstance(payload, ReconstructionReportArtifact) or (
            payload.report.semantic_digest != expected.semantic_digest
            or (exact_lineage and payload.metrics_artifact_id != route.metrics.artifact_id)
            or (
                exact_lineage
                and payload.geometry_artifact_id != route.geometry_artifact.artifact_id
            )
        ):
            raise ValueError("validation.input_mismatch: policy evaluation differs")
