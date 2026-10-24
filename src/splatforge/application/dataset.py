"""Explicit M9 selection -> independent component publications -> small DatasetSet."""

from __future__ import annotations

from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol
from uuid import UUID, uuid4

from splatforge.application.dataset_contracts import DatasetPreparer
from splatforge.application.execution import (
    ExecutionCancelledError,
    PublicationUnresolvedError,
    StateUpgradeRequiredError,
)
from splatforge.application.features import _Cancellation
from splatforge.application.features_contracts import (
    FeatureCancelledError,
    FeatureCapabilityError,
    FeatureResourceError,
    FeatureTeardownError,
)
from splatforge.application.progress import ProgressSupport
from splatforge.application.reconstruction_validation import EvidenceRunResult, ValidationRepository
from splatforge.application.work_models import dataset_progress_plan
from splatforge.core.dataset import (
    INPUT_MODELS,
    OUTPUT_MODELS,
    DatasetBackend,
    DatasetComponentReference,
    DatasetInputImage,
    DatasetProvenance,
    DatasetResourceEstimate,
    DatasetResourceLimits,
    DatasetSettings,
    PreparedDatasetComponent,
    PreparedDatasetSet,
    estimate_dataset_resources,
)
from splatforge.core.execution import (
    ArtifactHandle,
    DatasetComponentRoute,
    DatasetRoute,
    DatasetSetRoute,
    FailureCategory,
    ReconstructionSelectionRoute,
    RunSnapshot,
)
from splatforge.core.reconstruction import ReconstructionComponent
from splatforge.core.reconstruction_selection import SelectedComponentContent
from splatforge.core.views import FrozenModel


class DatasetRepository(ValidationRepository, Protocol):
    def selection_route(
        self, root: Path, handle: ArtifactHandle
    ) -> ReconstructionSelectionRoute: ...
    def load_dataset(
        self,
        root: Path,
        handle: ArtifactHandle,
    ) -> PreparedDatasetComponent | PreparedDatasetSet: ...
    def input_image_size(self, root: Path, handle: ArtifactHandle, path: str) -> int: ...
    def disk_free(self, root: Path) -> int: ...
    def write_dataset_set(self, workspace: Path, value: PreparedDatasetSet) -> None: ...
    def dataset_pairing_method(self, root: Path, reconstruction: ArtifactHandle) -> str: ...


class DatasetComponentPlan(FrozenModel):
    source_component: SelectedComponentContent
    registered_views: int
    input_camera_models: dict[str, int]
    undistortion_required: bool
    estimate: DatasetResourceEstimate
    cache_hit: bool
    cache_reasons: tuple[str, ...]


class DatasetPlan(FrozenModel):
    selection: ArtifactHandle
    candidate: ArtifactHandle
    selected: ArtifactHandle
    provenance: DatasetProvenance
    settings: DatasetSettings
    backend: DatasetBackend | None
    components: tuple[DatasetComponentPlan, ...]
    required_free_disk_bytes: int
    available_disk_bytes: int
    runnable: bool
    diagnostics: tuple[str, ...]


class DatasetResult(FrozenModel):
    status: str
    run_id: UUID
    artifact: ArtifactHandle | None
    dataset: PreparedDatasetSet | None
    component_runs: tuple[EvidenceRunResult, ...]
    cache_hit: bool


def require_dataset_inputs(repo: DatasetRepository, root: Path, route: DatasetRoute) -> None:
    selection = repo.selection_route(root, route.selection)
    if isinstance(route, DatasetComponentRoute):
        candidate, selected, _universe = repo.validation_universe(root, selection.reconstruction)
        if (route.reconstruction, route.candidate, route.selected) != (
            selection.reconstruction,
            candidate,
            selected,
        ) or route.content not in selection.decision.selected_components:
            raise ValueError("dataset.stale_selection: frozen component/historical lineage differs")
        images, _ = dataset_images(repo, root, candidate, selected, route.content, selection)
        if route.images != images:
            raise ValueError("dataset.corrupt_pixels: frozen historical input differs")
    else:
        require_dataset_payload(route, route.dataset)
        ids = []
        for handle, reference in zip(route.components, route.dataset.components, strict=True):
            payload = repo.load_dataset(root, handle)
            if (
                not isinstance(payload, PreparedDatasetComponent)
                or payload.source_component not in selection.decision.selected_components
                or (
                    payload.source_component.component_id,
                    payload.semantic_digest,
                    handle.artifact_id,
                    handle.manifest_path,
                    payload.image_count,
                )
                != (
                    reference.component_id,
                    reference.semantic_digest,
                    reference.artifact_id,
                    reference.manifest_path,
                    reference.image_count,
                )
            ):
                raise ValueError("dataset.input_mismatch: component reference/content differs")
            ids.append(reference.component_id)
        if tuple(ids) != selection.decision.selected_component_ids:
            raise ValueError("dataset.membership_mismatch: all explicit components required")


def require_dataset_payload(
    route: DatasetRoute,
    payload: PreparedDatasetComponent | PreparedDatasetSet,
    *,
    exact_lineage: bool = False,
) -> None:
    if payload.recipe_key != route.recipe_key():
        raise ValueError("dataset.input_mismatch: payload recipe differs from frozen preparation")
    if isinstance(route, DatasetComponentRoute):
        if (
            not isinstance(payload, PreparedDatasetComponent)
            or payload.selected_view_ids != tuple(i.view_id for i in route.images)
            or (exact_lineage and payload.provenance != route.provenance)
        ):
            raise ValueError("dataset.input_mismatch: payload membership/provenance differs")
    elif not isinstance(payload, PreparedDatasetSet) or payload != route.dataset:
        raise ValueError("dataset.input_mismatch: DatasetSet differs from frozen receipt")


def dataset_images(
    repo: DatasetRepository,
    root: Path,
    candidate: ArtifactHandle,
    selected: ArtifactHandle,
    content: SelectedComponentContent,
    selection: ReconstructionSelectionRoute,
) -> tuple[tuple[DatasetInputImage, ...], ReconstructionComponent]:
    candidates, selected_views = repo.load_pairing_inputs(root, candidate, selected)
    reconstruction = repo.load_reconstruction(root, selection.reconstruction)
    component = next(c for c in reconstruction.components if c.component_id == content.component_id)
    members = set(component.registered_view_ids)
    if not members <= {v.view_id for v in selected_views.selected_views}:
        raise ValueError(
            "dataset.membership_mismatch: registered pixels outside historical selection"
        )
    images = tuple(
        DatasetInputImage(
            view_id=v.view_id,
            name=f"{v.view_id}.{'png' if v.image_path.endswith('.png') else 'jpg'}",
            sha256=v.image_sha256,
            width=v.width,
            height=v.height,
            size=repo.input_image_size(root, candidate, v.image_path),
        )
        for v in sorted(candidates.views, key=lambda v: v.view_id.int)
        if v.view_id in members
    )
    if len(images) != len(members):
        raise ValueError("dataset.missing_historical_pixels: rebuild upstream views explicitly")
    return images, component


class DatasetService:
    def __init__(
        self,
        repository: DatasetRepository,
        preparer: DatasetPreparer,
        *,
        progress: ProgressSupport | None = None,
    ) -> None:
        self.repository, self.preparer = repository, preparer
        self.progress = progress or ProgressSupport()

    def _plan(self, root, selection_run_id, settings, limits, colmap):
        repo = self.repository
        selection_handle = repo.resolve_run_output(
            root, selection_run_id, "reconstruction_selection", "selection"
        )
        selection = repo.selection_route(root, selection_handle)
        candidate, selected, _universe = repo.validation_universe(root, selection.reconstruction)
        report = repo.load_validation_artifact(root, selection.report).report
        pairing = repo.dataset_pairing_method(root, selection.reconstruction)
        provenance = DatasetProvenance(
            selection_artifact_id=selection_handle.artifact_id,
            selection_digest=selection.decision.semantic_digest,
            reconstruction_artifact_id=selection.reconstruction.artifact_id,
            reconstruction_digest=selection.reconstruction.semantic_digest,
            candidate_artifact_id=candidate.artifact_id,
            selected_artifact_id=selected.artifact_id,
            validation_report_digest=report.semantic_digest,
            validation_status=report.status,
            warnings=tuple(
                f"{i.issue_id}: {i.code}: {i.message}"
                for i in report.issues
                if i.severity == "warning"
            ),
            override=selection.decision.override.model_dump(mode="json")
            if selection.decision.override
            else None,
            pairing_method=pairing,
            practical_multi_video_pairing_status="explicit_reference_pairing"
            if pairing in {"pair_selection.exhaustive", "pair_selection.sequential"}
            else "unknown",
        )
        if len(selection.decision.selected_components) > limits.max_components:
            raise FeatureResourceError("dataset.resource_limit: too many selected components")
        backend, diagnostics = None, []
        try:
            backend = self.preparer.prepare_backend(settings, colmap)
        except FeatureCapabilityError as exc:
            diagnostics.append(str(exc))
        plans, routes = [], []
        for content in selection.decision.selected_components:
            images, component = dataset_images(repo, root, candidate, selected, content, selection)
            models, sparse_bytes, source_sparse_digest = self.preparer.inspect_input(
                repo.artifact_directory(root, selection.reconstruction), component
            )
            if set(models) - INPUT_MODELS:
                raise ValueError(
                    "dataset.unsupported_projection: ordinary perspective flat cameras "
                    "only; panorama/360 preparation belongs to later preprocessing"
                )
            estimate = estimate_dataset_resources(images, sparse_bytes, settings, limits)
            cache_hit, reasons = False, ()
            if backend:
                route = DatasetComponentRoute(
                    selection=selection_handle,
                    reconstruction=selection.reconstruction,
                    candidate=candidate,
                    selected=selected,
                    content=content,
                    source_sparse_digest=source_sparse_digest,
                    images=images,
                    settings=settings,
                    backend=backend,
                    resource_limits=limits,
                    estimate=estimate,
                    provenance=provenance,
                )
                cached = repo.find_cache(
                    root,
                    recipe_key=route.recipe_key(),
                    artifact_type=route.target.artifact_type,
                    contract_version=1,
                )
                cache_hit, reasons = (
                    cached.artifact is not None,
                    tuple(i.reason for i in cached.ineligible),
                )
                routes.append(route)
            if not cache_hit and estimate.peak_workspace_bytes > limits.max_workspace_bytes:
                diagnostics.append(
                    "dataset.resource_limit: estimated component workspace exceeds "
                    "configured budget; change budget or explicit resolution"
                )
            plans.append(
                DatasetComponentPlan(
                    source_component=content,
                    registered_views=len(images),
                    input_camera_models=models,
                    undistortion_required=bool(set(models) - OUTPUT_MODELS),
                    estimate=estimate,
                    cache_hit=cache_hit,
                    cache_reasons=reasons,
                )
            )
        # Completed component payloads accumulate. At each step reserve preceding
        # outputs plus the current peak; publication itself is a same-volume rename.
        retained, peak = 0, 0
        for plan in plans:
            if not plan.cache_hit:
                peak = max(peak, retained + plan.estimate.peak_workspace_bytes)
                retained += plan.estimate.output_bytes_conservative
        required = peak + limits.minimum_free_bytes
        available = repo.disk_free(root)
        if required > available:
            diagnostics.append(
                "dataset.resource_limit: insufficient free disk before native execution"
            )
        return DatasetPlan(
            selection=selection_handle,
            candidate=candidate,
            selected=selected,
            provenance=provenance,
            settings=settings,
            backend=backend,
            components=tuple(plans),
            required_free_disk_bytes=required,
            available_disk_bytes=available,
            runnable=not diagnostics,
            diagnostics=tuple(diagnostics),
        ), tuple(routes)

    def plan(
        self,
        root: Path,
        *,
        selection_run_id: UUID,
        settings: DatasetSettings | None = None,
        resource_limits: DatasetResourceLimits | None = None,
        colmap: Path | None = None,
    ) -> DatasetPlan:
        with self.repository.validation_evidence_operation():
            return self._plan(
                root.resolve(),
                selection_run_id,
                settings or DatasetSettings(),
                resource_limits or DatasetResourceLimits(),
                colmap,
            )[0]

    def prepare(
        self,
        root: Path,
        *,
        selection_run_id: UUID,
        settings: DatasetSettings | None = None,
        resource_limits: DatasetResourceLimits | None = None,
        colmap: Path | None = None,
    ) -> DatasetResult:
        root, repo, owner = root.resolve(), self.repository, uuid4()
        with (
            repo.writer(root, owner_token=owner, operation="dataset-prepare"),
            repo.validation_evidence_operation(),
        ):
            repo.ensure_no_unfinished_run(root)
            plan, routes = self._plan(
                root,
                selection_run_id,
                settings or DatasetSettings(),
                resource_limits or DatasetResourceLimits(),
                colmap,
            )
            if not plan.runnable:
                raise ValueError("; ".join(plan.diagnostics))
            completed, references, handles = [], [], []
            for route in routes:
                result = self._execute(root, owner, route)
                completed.append(result)
                if result.status != "succeeded":
                    return DatasetResult(
                        status=result.status,
                        run_id=result.run_id,
                        artifact=None,
                        dataset=None,
                        component_runs=tuple(completed),
                        cache_hit=False,
                    )
                value = repo.load_dataset(root, result.artifact)
                handles.append(result.artifact)
                references.append(
                    DatasetComponentReference(
                        component_id=value.source_component.component_id,
                        artifact_id=result.artifact.artifact_id,
                        semantic_digest=value.semantic_digest,
                        manifest_path=result.artifact.manifest_path,
                        image_count=value.image_count,
                    )
                )
            dataset = PreparedDatasetSet(provenance=plan.provenance, components=tuple(references))
            receipt = self._execute(
                root,
                owner,
                DatasetSetRoute(
                    selection=plan.selection, components=tuple(handles), dataset=dataset
                ),
            )
            return DatasetResult(
                status=receipt.status,
                run_id=receipt.run_id,
                artifact=receipt.artifact,
                dataset=dataset if receipt.artifact else None,
                component_runs=tuple(completed),
                cache_hit=receipt.cache_hit and all(r.cache_hit for r in completed),
            )

    def inspect(self, root: Path, run_id: UUID) -> PreparedDatasetSet:
        with self.repository.validation_evidence_operation():
            handle = self.repository.resolve_run_output(root, run_id, "dataset_set", "dataset_set")
            return self.repository.load_dataset(root, handle)

    def _execute(self, root, owner, route):
        repo = self.repository
        project = repo.inspect_project(root)
        if project.state_version != 4:
            raise StateUpgradeRequiredError("Run 'splatforge project upgrade-state <project>'")
        require_dataset_inputs(repo, root, route)
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
            (dataset_progress_plan(route, self.progress.hardware),),
            emit=lambda node, attempt, details: repo.append_event(
                root,
                run_id,
                code="progress.snapshot",
                node_id=node,
                attempt_id=attempt,
                details=details,
            ),
        )
        control, attempt, artifact, cache_hit = _Cancellation(repo, root, run_id), None, None, False

        def phase(name):
            session.report(route.node_id, 0, phase=name)

        def evidence(record):
            try:
                repo.append_process_evidence(root, run_id, control.attempt, record)
            except Exception:
                # Optional retained diagnostics cannot reverse a validated native
                # result. The runner's teardown result remains authoritative.
                with suppress(Exception):
                    repo.append_event(
                        root,
                        run_id,
                        code="dataset.process_diagnostics_unavailable",
                        node_id=route.node_id,
                        attempt_id=control.attempt,
                    )

        try:
            repo.append_event(root, run_id, code="dataset.stage.started", node_id=route.node_id)
            control.checkpoint()
            cached = repo.find_cache(
                root,
                recipe_key=route.recipe_key(),
                artifact_type=route.target.artifact_type,
                contract_version=1,
            )
            if cached.artifact:
                payload = repo.load_dataset(root, cached.artifact)
                require_dataset_payload(route, payload)
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
                if isinstance(route, DatasetComponentRoute) and repo.disk_free(root) < (
                    route.estimate.peak_workspace_bytes + route.resource_limits.minimum_free_bytes
                ):
                    raise FeatureResourceError("dataset.resource_limit: free disk changed")
                attempt = repo.begin_attempt(
                    root,
                    run_id=run_id,
                    node_id=route.node_id,
                    output_name=route.target.output_name,
                    recipe_key=route.recipe_key(),
                    input_artifact_ids=tuple(i.artifact_id for i in route.input_lineage()),
                    literal_inputs=route.literal_inputs(),
                    environment=route.backend.model_dump(mode="json")
                    if isinstance(route, DatasetComponentRoute)
                    else {"adapter_id": "dataset.receipt"},
                    source_verification={"policy": "artifact_integrity", "evidence": []},
                )
                control.attempt = attempt.attempt_id
                session.start(route.node_id, attempt.attempt_id)
                if isinstance(route, DatasetComponentRoute):
                    payload = self.preparer.produce(
                        Path(attempt.workspace),
                        route,
                        repo.artifact_directory(root, route.reconstruction),
                        repo.artifact_directory(root, route.candidate),
                        control,
                        evidence,
                        phase,
                    )
                else:
                    payload = route.dataset
                    repo.write_dataset_set(Path(attempt.workspace), payload)
                require_dataset_payload(route, payload, exact_lineage=True)
                control.checkpoint()
                phase("publishing")
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
            return EvidenceRunResult(
                run_id=run_id, status="succeeded", artifact=artifact, cache_hit=cache_hit
            )
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
                raise ValueError(
                    "dataset.cancel_unaccepted: native cancellation lacks owner request"
                ) from exc
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
