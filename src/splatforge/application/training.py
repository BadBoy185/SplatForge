"""One M10 component per job, checkpoint segments and separate final scene receipts."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Protocol
from uuid import UUID, uuid4

from splatforge.application.dataset import DatasetRepository
from splatforge.application.execution import (
    ExecutionCancelledError,
    PublicationUnresolvedError,
    StateUpgradeRequiredError,
)
from splatforge.application.features import _Cancellation
from splatforge.application.features_contracts import (
    FeatureCancelledError,
    FeatureCapabilityError,
    FeatureTeardownError,
)
from splatforge.application.progress import ProgressSupport
from splatforge.application.reconstruction_validation import EvidenceRunResult
from splatforge.application.training_contracts import TrainingBackend
from splatforge.application.work_models import training_progress_plan
from splatforge.core.execution import (
    ArtifactHandle,
    FailureCategory,
    RunSnapshot,
    TrainingCheckpointRoute,
    TrainingJobRoute,
    TrainingRoute,
    TrainingRuntime,
    TrainingSceneRoute,
    TrainingSetRoute,
)
from splatforge.core.progress import WorkMetric
from splatforge.core.training import (
    SCENE_TYPE,
    GaussianScene,
    GaussianSceneReference,
    GaussianSceneSet,
    TrainingBackendIdentity,
    TrainingCheckpoint,
    TrainingLimits,
    TrainingSettings,
    required_training_features,
    training_recipe,
)
from splatforge.core.views import FrozenModel


class TrainingRepository(DatasetRepository, Protocol):
    def training_datasets(self, root: Path, run_id: UUID) -> tuple: ...
    def load_training(
        self, root: Path, handle: ArtifactHandle
    ) -> TrainingCheckpoint | GaussianScene | GaussianSceneSet: ...
    def training_groups(self, root: Path, handle: ArtifactHandle) -> dict[str, str]: ...
    def write_scene_set(self, workspace: Path, value: GaussianSceneSet) -> None: ...
    def inspect_training_run(self, root: Path, run_id: UUID) -> tuple: ...


class TrainingComponentPlan(FrozenModel):
    component_id: UUID
    dataset_digest: str
    images: int
    resolution: tuple[tuple[int, int], ...]
    sparse_points: int
    scale: Literal["unknown_arbitrary"]
    dataset_artifact: UUID
    cache_hit: bool
    checkpoint_every: int
    resource_class: Literal["unknown_until_measured"] = "unknown_until_measured"


class TrainingPlan(FrozenModel):
    settings: TrainingSettings
    backend: TrainingBackendIdentity | None
    components: tuple[TrainingComponentPlan, ...]
    runnable: bool
    diagnostics: tuple[str, ...]
    peak_vram_estimate: str = "unknown; device capacity is not predicted peak allocation"


class TrainingResult(FrozenModel):
    status: str
    jobs: tuple[EvidenceRunResult, ...]
    scene_set_run: UUID | None = None
    scene_set: GaussianSceneSet | None = None


def require_training_inputs(repo, root, route: TrainingRoute) -> None:
    if isinstance(route, TrainingJobRoute):
        value = repo.load_dataset(root, route.dataset)
        if value.semantic_digest != route.dataset.semantic_digest:
            raise ValueError("training.stale_dataset")
        held = set(route.settings.split.held_out_view_ids)
        if not held < set(value.selected_view_ids):
            raise ValueError("training.invalid_split: need training views and exact held-out IDs")
        if route.resume:
            checkpoint = repo.load_training(root, route.resume)
            checkpoint.require_compatible(value.semantic_digest, route.settings, route.backend)
            if checkpoint.step != route.start_step:
                raise ValueError("training.incompatible_checkpoint_step")
    else:
        if len(route.scenes) != len(route.scene_set.scenes):
            raise ValueError("training.scene_set_membership_mismatch")
        for handle, reference in zip(route.scenes, route.scene_set.scenes, strict=True):
            scene = repo.load_training(root, handle)
            if not isinstance(scene, GaussianScene) or (
                handle.artifact_id,
                scene.semantic_digest,
            ) != (reference.artifact_id, reference.semantic_digest):
                raise ValueError("training.scene_set_membership_mismatch")
            dataset = repo.load_dataset(root, repo.lineage_handle(root, handle, "dataset"))
            if dataset.source_component.component_id != reference.component_id:
                raise ValueError("training.scene_set_component_mismatch")


def require_training_payload(route, payload) -> None:
    if payload.recipe_key != route.recipe_key():
        raise ValueError("training.payload_recipe_mismatch")
    if isinstance(route, TrainingSetRoute):
        if payload != route.scene_set:
            raise ValueError("training.scene_set_mismatch")
    elif (payload.dataset_digest, payload.settings.numerical(), payload.backend) != (
        route.dataset.semantic_digest,
        route.settings.numerical(),
        route.backend,
    ):
        raise ValueError("training.payload_settings_mismatch")


class TrainingService:
    def __init__(
        self,
        repository: TrainingRepository,
        backend: TrainingBackend,
        *,
        progress: ProgressSupport | None = None,
        external_probe: Callable[[Path | None], dict] | None = None,
    ) -> None:
        self.repository, self.backend = repository, backend
        self.progress = progress or ProgressSupport()
        self.external_probe = external_probe

    def capability(self, runtime: TrainingRuntime, ordinal: int = 0) -> TrainingBackendIdentity:
        return self.backend.capability(runtime, ordinal)

    def handoff_report(self, root: Path, dataset_run: UUID, executable: Path | None = None) -> dict:
        return {
            "datasets": self.handoff(root, dataset_run),
            "lichtfeld": self.external_probe(executable)
            if self.external_probe
            else {"status": "not_configured", "version": None},
        }

    def handoff(self, root: Path, dataset_run: UUID) -> tuple[dict, ...]:
        root = root.resolve()
        with self.repository.validation_evidence_operation():
            return tuple(
                {
                    "component_id": str(d.source_component.component_id),
                    "directory": str(self.repository.artifact_directory(root, h)),
                    "dataset_digest": d.semantic_digest,
                    "images": d.image_count,
                    "camera_models": sorted({c.model for c in d.cameras}),
                    "sparse_points": d.sparse_point_count,
                    "scale": d.scale,
                    "layout": "images/ + sparse/0/{cameras,images,points3D}.bin",
                    "workflow": "Open this COLMAP dataset directory manually in LichtFeld Studio. "
                    "Choose a separate external output directory; keep this dataset read-only.",
                    "status": "structure_validated_manual_open_not_observed",
                }
                for h, d in self.repository.training_datasets(root, dataset_run)
            )

    def plan(
        self,
        root: Path,
        dataset_run: UUID,
        runtime: TrainingRuntime,
        settings: TrainingSettings | None = None,
    ) -> TrainingPlan:
        root = root.resolve()
        settings = settings or TrainingSettings()
        with self.repository.validation_evidence_operation():
            datasets = self.repository.training_datasets(root, dataset_run)
            diagnostics, backend = [], None
            try:
                backend = self.backend.capability(runtime)
                features = required_training_features(settings)
                if not features <= set(backend.features):
                    diagnostics.append("training.requested_feature_unavailable")
            except FeatureTeardownError:
                raise
            except (FeatureCapabilityError, ValueError, OSError) as exc:
                diagnostics.append(str(exc))
            components = []
            for handle, data in datasets:
                if data.sparse_point_count < 4:
                    diagnostics.append("training.sfm_initialization_requires_at_least_four_points")
                if settings.strategy.strategy == "mcmc" and (
                    data.sparse_point_count > settings.strategy.cap_max
                ):
                    diagnostics.append("training.initial_sfm_exceeds_mcmc_cap")
                if not set(settings.split.held_out_view_ids) < set(data.selected_view_ids):
                    diagnostics.append("training.invalid_split")
                cache = (
                    self.repository.find_cache(
                        root,
                        recipe_key=training_recipe(
                            data.semantic_digest, settings, backend.numerical_identity
                        ),
                        artifact_type=SCENE_TYPE,
                        contract_version=1,
                    )
                    if backend
                    else None
                )
                components.append(
                    TrainingComponentPlan.model_validate(
                        {
                            "component_id": str(data.source_component.component_id),
                            "dataset_digest": data.semantic_digest,
                            "images": data.image_count,
                            "resolution": sorted({(i.width, i.height) for i in data.images}),
                            "sparse_points": data.sparse_point_count,
                            "scale": data.scale,
                            "dataset_artifact": str(handle.artifact_id),
                            "cache_hit": bool(cache and cache.artifact),
                            "checkpoint_every": settings.checkpoint_every,
                            "resource_class": "unknown_until_measured",
                        }
                    )
                )
            return TrainingPlan(
                settings=settings,
                backend=backend,
                components=tuple(components),
                runnable=not diagnostics,
                diagnostics=tuple(diagnostics),
            )

    def run(
        self,
        root: Path,
        dataset_run: UUID,
        runtime: TrainingRuntime,
        settings: TrainingSettings | None = None,
        limits: TrainingLimits | None = None,
        *,
        resume_run: UUID | None = None,
        stop_after_step: int | None = None,
    ) -> TrainingResult:
        settings, limits = settings or TrainingSettings(), limits or TrainingLimits()
        terminal = settings.max_steps if stop_after_step is None else stop_after_step
        if not 1 <= terminal <= settings.max_steps:
            raise ValueError("training.invalid_stop_step")
        root, repo, owner = root.resolve(), self.repository, uuid4()
        with (
            repo.writer(root, owner_token=owner, operation="training"),
            repo.validation_evidence_operation(),
        ):
            repo.ensure_no_unfinished_run(root)
            plan = self.plan(root, dataset_run, runtime, settings)
            if not plan.runnable:
                raise ValueError("; ".join(plan.diagnostics))
            datasets = repo.training_datasets(root, dataset_run)
            if resume_run and len(datasets) != 1:
                raise ValueError("training.resume_requires_one_component_run")
            jobs, references, scene_handles = [], [], []
            for dataset, data in datasets:
                resume, start = None, 0
                if resume_run:
                    resume, value = repo.inspect_training_run(root, resume_run)
                    if not isinstance(value, TrainingCheckpoint):
                        raise ValueError("training.resume_requires_checkpoint")
                    value.require_compatible(data.semantic_digest, settings, plan.backend)
                    start = value.step
                    if terminal < start:
                        raise ValueError("training.stop_precedes_resume")
                common = dict(
                    dataset=dataset,
                    settings=settings,
                    backend=plan.backend,
                    runtime=runtime,
                    resource_limits=limits,
                    image_count=data.image_count,
                    megapixels=sum(i.width * i.height for i in data.images) / 1e6,
                    source_groups=repo.training_groups(root, dataset),
                )
                scene_route = None
                # Completed exact scenes can be reused without replaying checkpoints.
                cache = repo.find_cache(
                    root,
                    recipe_key=training_recipe(
                        data.semantic_digest, settings, plan.backend.numerical_identity
                    ),
                    artifact_type=SCENE_TYPE,
                    contract_version=1,
                )
                if cache.artifact and terminal == settings.max_steps and settings.final_export:
                    value = repo.load_training(root, cache.artifact)
                    # Use the original producer's validated checkpoint lineage for a legal route.
                    resume = repo.lineage_handle(root, cache.artifact, "checkpoint")
                    start = settings.max_steps
                while start < terminal:
                    end = min(
                        terminal,
                        (start // settings.checkpoint_every + 1) * settings.checkpoint_every,
                    )
                    if settings.split.held_out_view_ids:
                        end = min(
                            end,
                            (start // settings.evaluation_every + 1) * settings.evaluation_every,
                        )
                    route = TrainingCheckpointRoute(
                        **common, resume=resume, start_step=start, terminal_step=end
                    )
                    result = self._execute(root, owner, route)
                    jobs.append(result)
                    if result.status != "succeeded":
                        return TrainingResult(status=result.status, jobs=tuple(jobs))
                    resume, start = result.artifact, end
                if terminal < settings.max_steps or not settings.final_export:
                    continue
                scene_route = TrainingSceneRoute(
                    **common, resume=resume, start_step=start, terminal_step=settings.max_steps
                )
                result = self._execute(root, owner, scene_route)
                jobs.append(result)
                if result.status != "succeeded":
                    return TrainingResult(status=result.status, jobs=tuple(jobs))
                scene_handles.append(result.artifact)
                references.append(
                    GaussianSceneReference(
                        component_id=data.source_component.component_id,
                        artifact_id=result.artifact.artifact_id,
                        semantic_digest=result.artifact.semantic_digest,
                        manifest_path=result.artifact.manifest_path,
                    )
                )
            if not references:
                return TrainingResult(status="checkpointed", jobs=tuple(jobs))
            receipt = GaussianSceneSet(scenes=tuple(references))
            result = self._execute(
                root, owner, TrainingSetRoute(scenes=tuple(scene_handles), scene_set=receipt)
            )
            return TrainingResult(
                status=result.status,
                jobs=tuple(jobs),
                scene_set=receipt,
                scene_set_run=result.run_id,
            )

    def _execute(self, root, owner, route):
        repo, run_id = self.repository, uuid4()
        project = repo.inspect_project(root)
        if project.state_version != 4:
            raise StateUpgradeRequiredError("Run project upgrade-state first")
        require_training_inputs(repo, root, route)
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
            (training_progress_plan(route, self.progress.hardware),),
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
        try:
            control.checkpoint()
            cached = repo.find_cache(
                root,
                recipe_key=route.recipe_key(),
                artifact_type=route.target.artifact_type,
                contract_version=1,
            )
            if cached.artifact:
                require_training_payload(route, repo.load_training(root, cached.artifact))
                control.checkpoint()
                repo.bind_cached_output(
                    root,
                    run_id=run_id,
                    node_id=route.node_id,
                    output_name=route.target.output_name,
                    artifact_id=cached.artifact.artifact_id,
                )
                artifact = cached.artifact
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
                    environment={"adapter": "gsplat.worker_v1"},
                )
                control.attempt = attempt.attempt_id
                session.start(route.node_id, attempt.attempt_id)
                control.checkpoint()

                def on_event(event):
                    diagnostics = tuple(
                        WorkMetric(name=k, value=v)
                        for k, v in (
                            ("gaussians", event.gaussian_count),
                            ("loss", event.loss),
                            ("peak_allocated_cuda_bytes", event.peak_allocated_cuda_bytes),
                        )
                        if v is not None
                    )
                    diagnostics += (
                        WorkMetric(name="training_step", value=event.step),
                        WorkMetric(name="max_steps", value=event.total_steps),
                    )
                    session.report(
                        route.node_id, event.step, phase=event.event, diagnostics=diagnostics
                    )
                    repo.append_event(
                        root,
                        run_id,
                        code=event.event,
                        node_id=route.node_id,
                        attempt_id=attempt.attempt_id,
                        details=event.model_dump(mode="json"),
                    )

                def evidence(value):
                    with suppress(Exception):
                        repo.append_process_evidence(root, run_id, attempt.attempt_id, value)

                if isinstance(route, TrainingJobRoute):
                    payload = self.backend.produce(
                        Path(attempt.workspace),
                        route,
                        repo.artifact_directory(root, route.dataset),
                        repo.artifact_directory(root, route.resume) if route.resume else None,
                        control,
                        on_event,
                        evidence,
                    )
                else:
                    payload = route.scene_set
                    repo.write_scene_set(Path(attempt.workspace), payload)
                require_training_payload(route, payload)
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
            if not cached.artifact:
                session.complete(route.node_id)
            return EvidenceRunResult(
                run_id=run_id,
                status="succeeded",
                artifact=artifact,
                cache_hit=bool(cached.artifact),
            )
        except FeatureTeardownError as exc:
            repo.mark_external_interrupted(
                root, run_id=run_id, attempt_id=control.attempt, message=str(exc)
            )
            raise

        except (FeatureCancelledError, ExecutionCancelledError):
            if not control.accepted and not control.is_cancelled():
                raise ValueError("training.cancel_unaccepted") from None
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

    def inspect(
        self, root: Path, run_id: UUID
    ) -> tuple[ArtifactHandle, TrainingCheckpoint | GaussianScene | GaussianSceneSet]:
        with self.repository.validation_evidence_operation():
            return self.repository.inspect_training_run(root.resolve(), run_id)
