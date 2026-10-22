"""Explicit Global mapping use case, immutable publication and restart recovery."""

from __future__ import annotations

from collections.abc import Callable
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
from splatforge.application.features_contracts import FeatureCancelledError, FeatureTeardownError
from splatforge.application.mapping_contracts import MappingAdapter
from splatforge.application.progress import ProgressSupport
from splatforge.application.work_models import mapping_progress_plan
from splatforge.core.execution import (
    ArtifactHandle,
    FailureCategory,
    MappingRoute,
    RunSnapshot,
    RunStatus,
)
from splatforge.core.geometry import VerifiedGeometrySet
from splatforge.core.process import ProcessInvocationEvidence
from splatforge.core.reconstruction import (
    ClassicalMappingReceipt,
    GlobalMapperSettings,
    MappingCalibrationPolicy,
    MappingResourceLimits,
    ReconstructionLineage,
    ReconstructionReader,
    ReconstructionSet,
    ViewGraphCalibrationSettings,
    calibration_summary,
    estimate_mapping_resources,
    reconstruction_semantic_digest,
    resolved_settings,
)
from splatforge.core.views import FrozenModel


class MappingRepository(ExecutionRepository, Protocol):
    def resolve_run_output(
        self, root: Path, run_id: UUID, node_id: str, output_name: str
    ) -> ArtifactHandle: ...
    def load_verified_geometry(self, root: Path, handle: ArtifactHandle) -> VerifiedGeometrySet: ...
    def load_reconstruction(self, root: Path, handle: ArtifactHandle) -> ReconstructionSet: ...
    def write_reconstruction_metadata(
        self, workspace: Path, payload: ReconstructionSet, receipt: ClassicalMappingReceipt
    ) -> None: ...
    def reconstruction_reader(self, root: Path, handle: ArtifactHandle) -> ReconstructionReader: ...


class MappingRunResult(FrozenModel):
    result_version: int = 1
    run_id: UUID
    status: RunStatus
    artifact: ArtifactHandle | None
    reconstruction: ReconstructionSet | None
    cache_hit: bool
    warnings: tuple[str, ...] = ()


class MappingService:
    def __init__(
        self,
        repository: MappingRepository,
        adapter: MappingAdapter,
        *,
        progress: ProgressSupport | None = None,
    ) -> None:
        self._repository, self._adapter = repository, adapter
        self._progress = progress or ProgressSupport()

    def inspect(self, root: Path, run_id: UUID) -> ReconstructionSet:
        handle = self._repository.resolve_run_output(
            root, run_id, "reconstruction", "reconstruction"
        )
        return self._repository.load_reconstruction(root, handle)

    def reader(self, root: Path, run_id: UUID) -> ReconstructionReader:
        handle = self._repository.resolve_run_output(
            root, run_id, "reconstruction", "reconstruction"
        )
        return self._repository.reconstruction_reader(root, handle)

    def run(
        self,
        root: Path,
        *,
        verification_run_id: UUID,
        settings: GlobalMapperSettings | None = None,
        calibration_policy: MappingCalibrationPolicy = MappingCalibrationPolicy.PRESERVE_PRIORS,
        calibration_settings: ViewGraphCalibrationSettings | None = None,
        resource_limits: MappingResourceLimits | None = None,
        colmap: Path | None = None,
    ) -> MappingRunResult:
        root, owner = root.resolve(), uuid4()
        settings = GlobalMapperSettings.model_validate(
            (settings or GlobalMapperSettings()).model_dump()
        )
        limits = MappingResourceLimits.model_validate(
            (resource_limits or MappingResourceLimits()).model_dump()
        )
        calibration_policy = MappingCalibrationPolicy(calibration_policy)
        if calibration_policy == MappingCalibrationPolicy.VIEW_GRAPH:
            calibration_settings = ViewGraphCalibrationSettings.model_validate(
                (calibration_settings or ViewGraphCalibrationSettings()).model_dump()
            )
        elif calibration_settings is not None:
            raise ValueError("preserve_priors does not accept view-graph calibration settings")
        repo = self._repository
        with repo.writer(root, owner_token=owner, operation="mapping-run"):
            repo.ensure_no_unfinished_run(root)
            handle = repo.resolve_run_output(
                root, verification_run_id, "verified_geometry", "geometry"
            )
            repo.load_verified_geometry(root, handle)
            directory = repo.artifact_directory(root, handle)
            mapping_input = self._adapter.input(directory)
            estimate = estimate_mapping_resources(
                mapping_input, (directory / "matches.db").stat().st_size, limits
            )
            backend = self._adapter.prepare(
                calibration_policy,
                colmap=colmap,
                settings=settings,
                calibration=calibration_settings,
            )
            route = MappingRoute(
                verification_run_id=verification_run_id,
                verification=handle,
                mapping_input=mapping_input,
                settings=settings,
                calibration_policy=calibration_policy,
                calibration_settings=calibration_settings,
                backend=backend,
                resource_limits=limits,
                estimate=estimate,
            )

            def produce(workspace, control, evidence, phase):
                calibrated, components = self._adapter.map(
                    workspace,
                    directory=directory,
                    mapping_input=mapping_input,
                    backend=backend,
                    settings=settings,
                    policy=calibration_policy,
                    calibration=calibration_settings,
                    limits=limits,
                    estimate=estimate,
                    cancellation=control,
                    evidence_sink=evidence,
                    phase_sink=phase,
                )
                registered = {v for component in components for v in component.registered_view_ids}
                unregistered = tuple(v for v in mapping_input.view_ids if v not in registered)
                receipt = ClassicalMappingReceipt(
                    verification_artifact_id=handle.artifact_id,
                    verification_semantic_digest=handle.semantic_digest,
                    mapping_input=mapping_input,
                    settings=settings,
                    calibration=calibrated,
                    backend_numerical_identity=backend.numerical_identity,
                )
                payload = ReconstructionSet.model_construct(
                    upstream=(
                        ReconstructionLineage(
                            input_name="verified_geometry",
                            artifact_id=handle.artifact_id,
                            semantic_digest=handle.semantic_digest,
                        ),
                    ),
                    mapping_input_digest=mapping_input.semantic_digest,
                    input_view_ids=mapping_input.view_ids,
                    method_id=settings.method_id,
                    resolved_settings=resolved_settings(settings),
                    calibration=calibration_summary(calibrated),
                    native_format="colmap.sparse.binary.v1",
                    backend_numerical_identity=backend.numerical_identity,
                    recipe_key=route.recipe_key(),
                    components=components,
                    component_count=len(components),
                    registered_view_count=len(registered),
                    unregistered_view_count=len(unregistered),
                    unregistered_view_ids=unregistered,
                    semantic_digest="0" * 64,
                )
                payload = ReconstructionSet.model_validate(
                    {
                        **payload.model_dump(),
                        "semantic_digest": reconstruction_semantic_digest(payload),
                    }
                )
                repo.write_reconstruction_metadata(workspace, payload, receipt)
                return payload

            return self._execute(root, owner, route, produce)

    def _execute(
        self,
        root: Path,
        owner: UUID,
        route: MappingRoute,
        produce: Callable,
    ) -> MappingRunResult:
        repo = self._repository
        project = repo.inspect_project(root)
        if project.state_version != 4:
            raise StateUpgradeRequiredError("Run 'splatforge project upgrade-state <project>'")
        repo.ensure_no_unfinished_run(root)
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
        progress = self._progress.session(
            run_id,
            (mapping_progress_plan(route, self._progress.hardware),),
            emit=lambda node, attempt, details: repo.append_event(
                root,
                run_id,
                code="progress.snapshot",
                node_id=node,
                attempt_id=attempt,
                details=details,
            ),
        )
        control = _Cancellation(repo, root, run_id)
        attempt, payload, artifact, cache_hit = None, None, None, False
        warnings = []

        def event(code: str, **details: object) -> None:
            try:
                warning = repo.append_event(
                    root,
                    run_id,
                    code=code,
                    node_id=route.node_id,
                    attempt_id=control.attempt,
                    details=details,
                )
                if warning:
                    warnings.append(warning.message)
            except Exception:
                warnings.append("events.append_failed")

        def evidence(record: ProcessInvocationEvidence) -> None:
            try:
                warning = repo.append_process_evidence(root, run_id, control.attempt, record)
                if warning:
                    warnings.append(warning.message)
            except Exception:
                warnings.append("process_diagnostics.append_failed")

        def phase(name: str) -> None:
            progress.report(route.node_id, 0, phase=name)

        try:
            event("mapping.run.started", method=route.settings.method_id)
            control.checkpoint()
            cached = repo.find_cache(
                root,
                recipe_key=route.recipe_key(),
                artifact_type=route.target.artifact_type,
                contract_version=1,
            )
            if cached.artifact:
                payload = repo.load_reconstruction(root, cached.artifact)
                require_mapping_payload(route, payload)
                control.checkpoint()
                repo.bind_cached_output(
                    root,
                    run_id=run_id,
                    node_id=route.node_id,
                    output_name=route.target.output_name,
                    artifact_id=cached.artifact.artifact_id,
                )
                artifact, cache_hit = cached.artifact, True
                progress.cached(route.node_id)
                event("mapping.stage.cache_hit", artifact_id=str(artifact.artifact_id))
            else:
                event("mapping.stage.cache_miss", reasons=[v.reason for v in cached.ineligible])
                attempt = repo.begin_attempt(
                    root,
                    run_id=run_id,
                    node_id=route.node_id,
                    output_name=route.target.output_name,
                    recipe_key=route.recipe_key(),
                    input_artifact_ids=tuple(i.artifact_id for i in route.input_lineage()),
                    literal_inputs=route.literal_inputs(),
                    environment=route.backend.model_dump(mode="json"),
                    source_verification={"policy": "artifact_integrity", "evidence": []},
                )
                control.attempt = attempt.attempt_id
                progress.start(route.node_id, attempt.attempt_id)
                payload = produce(Path(attempt.workspace), control, evidence, phase)
                require_mapping_payload(route, payload)
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
                event("mapping.stage.published", artifact_id=str(artifact.artifact_id))
            control.checkpoint()
            repo.mark_run_succeeded(root, run_id=run_id)
            status = RunStatus.SUCCEEDED
            if not cache_hit:
                progress.complete(route.node_id)
            event("mapping.run.completed")
        except FeatureTeardownError as exc:
            repo.mark_external_interrupted(
                root, run_id=run_id, attempt_id=control.attempt, message=str(exc)
            )
            raise
        except (ExecutionCancelledError, FeatureCancelledError) as exc:
            if not control.accepted and not control.is_cancelled():
                if attempt:
                    repo.mark_attempt_failed(
                        root,
                        attempt_id=attempt.attempt_id,
                        message=str(exc),
                        category=FailureCategory.NON_RETRYABLE,
                    )
                repo.mark_run_failed(root, run_id=run_id, message=str(exc))
                raise ValueError("Backend cancelled without durable owner acceptance") from exc
            status = repo.finish_cancellation(
                root, run_id=run_id, attempt_id=control.attempt, teardown_confirmed=True
            )
            payload, artifact = None, None
            event("mapping.run.cancelled")
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
            event("mapping.run.failed", error=str(exc))
            raise
        return MappingRunResult(
            run_id=run_id,
            status=status,
            artifact=artifact,
            reconstruction=payload,
            cache_hit=cache_hit,
            warnings=tuple(warnings) + progress.snapshot().warnings,
        )


def require_mapping_payload(route: MappingRoute, payload: ReconstructionSet) -> None:
    if (
        not isinstance(payload, ReconstructionSet)
        or payload.mapping_input_digest != route.mapping_input.semantic_digest
        or payload.resolved_settings != resolved_settings(route.settings)
        or payload.recipe_key != route.recipe_key()
        or payload.calibration.policy != route.calibration_policy
        or payload.calibration.settings
        != (resolved_settings(route.calibration_settings) if route.calibration_settings else ())
        or payload.backend_numerical_identity != route.backend.numerical_identity
    ):
        raise ValueError("mapping.input_mismatch: ReconstructionSet differs from frozen route")
