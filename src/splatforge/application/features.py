"""Explicit selected-view feature extraction through existing execution foundations."""

from __future__ import annotations

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
from splatforge.application.features_contracts import (
    FeatureCancelledError,
    FeatureExtractor,
    FeatureTeardownError,
)
from splatforge.application.progress import ProgressSupport
from splatforge.application.work_models import features_progress_plan
from splatforge.core.execution import (
    ArtifactHandle,
    FailureCategory,
    FeatureExtractionRoute,
    RunSnapshot,
    RunStatus,
)
from splatforge.core.features import (
    FEATURE_ARTIFACT_TYPE,
    FeatureResourceLimits,
    FeatureSettings,
    FeatureViewSummary,
    LocalFeatureSet,
    descriptor_signature,
    estimate_feature_resources,
    feature_recipe_key,
    feature_semantic_digest,
)
from splatforge.core.process import ProcessInvocationEvidence
from splatforge.core.progress import WorkMetric
from splatforge.core.quality import SharpestSelectedViewSet
from splatforge.core.views import CandidateView, CandidateViewSet, FrozenModel, SelectedViewSet


class FeatureRepository(ExecutionRepository, Protocol):
    def resolve_run_output(
        self, root: Path, run_id: UUID, node_id: str, output_name: str
    ) -> ArtifactHandle: ...

    def load_pairing_inputs(
        self, root: Path, candidate: ArtifactHandle, selected: ArtifactHandle
    ) -> tuple[CandidateViewSet, SelectedViewSet | SharpestSelectedViewSet]: ...

    def load_local_features(self, root: Path, handle: ArtifactHandle) -> LocalFeatureSet: ...

    def write_feature_metadata(self, workspace: Path, features: LocalFeatureSet) -> None: ...


class FeaturesRunResult(FrozenModel):
    result_version: int = 1
    run_id: UUID
    status: RunStatus
    method_id: str
    feature_artifact: ArtifactHandle | None
    selected_view_count: int
    total_feature_count: int
    cache_hit: bool
    warnings: tuple[str, ...] = ()


class _Cancellation:
    def __init__(self, repository: ExecutionRepository, root: Path, run: UUID) -> None:
        self.repo, self.root, self.run = repository, root, run
        self.attempt: UUID | None = None
        self.accepted = False

    def is_cancelled(self) -> bool:
        self.accepted = (
            self.repo.accept_cancellation(
                self.root,
                run_id=self.run,
                attempt_id=self.attempt,
            )
            or self.accepted
        )
        return self.accepted

    def checkpoint(self) -> None:
        if self.is_cancelled():
            raise ExecutionCancelledError(self.attempt)


class FeaturesService:
    def __init__(
        self,
        repository: FeatureRepository,
        extractor: FeatureExtractor,
        *,
        progress: ProgressSupport | None = None,
    ) -> None:
        self._repository, self._extractor = repository, extractor
        self._progress = progress or ProgressSupport()

    def extract(
        self,
        root: Path,
        *,
        views_run_id: UUID,
        settings: FeatureSettings,
        resource_limits: FeatureResourceLimits | None = None,
        colmap: Path | None = None,
        model_directory: Path | None = None,
    ) -> FeaturesRunResult:
        root = root.resolve()
        limits = resource_limits or FeatureResourceLimits()
        repo = self._repository
        run_id, owner = uuid4(), uuid4()
        attempt = None
        handle = None
        payload = None
        cache_hit = False
        warnings = []
        with repo.writer(root, owner_token=owner, operation="features-extract"):
            project = repo.inspect_project(root)
            if project.state_version != 4:
                raise StateUpgradeRequiredError("Run 'splatforge project upgrade-state <project>'")
            repo.ensure_no_unfinished_run(root)
            candidate_handle = repo.resolve_run_output(
                root,
                views_run_id,
                "candidate_views",
                "candidate_set",
            )
            selected_handle = repo.resolve_run_output(
                root,
                views_run_id,
                "selected_views",
                "selected_set",
            )
            candidate, selected = repo.load_pairing_inputs(root, candidate_handle, selected_handle)
            if selected.candidate_artifact_id != candidate_handle.artifact_id:
                raise ValueError("Selected views must reference the exact candidate artifact")
            selected_ids = {v.view_id for v in selected.selected_views}
            views = tuple(v for v in candidate.views if v.view_id in selected_ids)
            directory = repo.artifact_directory(root, candidate_handle)
            pixels = sum(v.width * v.height for v in views)
            encoded = sum((directory / v.image_path).stat().st_size for v in views)
            # Cheap gates before capability probes, then refine with pinned model copies.
            estimate_feature_resources(
                views=len(views),
                pixels=pixels,
                encoded_bytes=encoded,
                settings=settings,
                limits=limits,
            )
            backend = self._extractor.prepare(
                settings, colmap=colmap, model_directory=model_directory
            )
            estimate = estimate_feature_resources(
                views=len(views),
                pixels=pixels,
                encoded_bytes=encoded,
                settings=settings,
                limits=limits,
                model_bytes=sum(m.size for m in backend.model_identities()),
            )
            route = FeatureExtractionRoute(
                views_run_id=views_run_id,
                candidate=candidate_handle,
                selected=selected_handle,
                settings=settings,
                backend=backend,
                resource_limits=limits,
                estimate=estimate,
            )
            snapshot = RunSnapshot(
                run_id=run_id,
                project_id=project.document.project_id,
                project_revision=project.document.revision,
                owner_token=owner,
                created_at=datetime.now(UTC),
                project_intent=project.document,
                route=route,
            )
            key = feature_recipe_key(
                selected_handle.semantic_digest,
                settings,
                backend.numerical_identity,
                backend.model_identities(),
            )
            repo.create_run(root, snapshot)
            progress = self._progress.session(
                run_id,
                (features_progress_plan(route, self._progress.hardware),),
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

            try:
                event("features.run.started")
                control.checkpoint()
                cached = repo.find_cache(
                    root, recipe_key=key, artifact_type=FEATURE_ARTIFACT_TYPE, contract_version=1
                )
                if cached.artifact:
                    payload = repo.load_local_features(root, cached.artifact)
                    _require_selected_views(payload.views, views)
                    if (
                        payload.settings != settings
                        or payload.selected_semantic_digest != selected_handle.semantic_digest
                        or payload.backend_numerical_identity != backend.numerical_identity
                        or payload.models != backend.model_identities()
                    ):
                        raise ValueError("Cached features differ from their frozen recipe")
                    control.checkpoint()
                    repo.bind_cached_output(
                        root,
                        run_id=run_id,
                        node_id=route.node_id,
                        output_name=route.target.output_name,
                        artifact_id=cached.artifact.artifact_id,
                    )
                    handle, cache_hit = cached.artifact, True
                    progress.cached(route.node_id)
                    event("features.stage.cache_hit", artifact_id=str(handle.artifact_id))
                else:
                    event(
                        "features.stage.cache_miss", reasons=[v.reason for v in cached.ineligible]
                    )
                    attempt = repo.begin_attempt(
                        root,
                        run_id=run_id,
                        node_id=route.node_id,
                        output_name=route.target.output_name,
                        recipe_key=key,
                        input_artifact_ids=(
                            candidate_handle.artifact_id,
                            selected_handle.artifact_id,
                        ),
                        literal_inputs=route.literal_inputs(),
                        environment=backend.model_dump(mode="json"),
                        source_verification={"policy": "artifact_integrity", "evidence": []},
                    )
                    control.attempt = attempt.attempt_id
                    progress.start(route.node_id, attempt.attempt_id)
                    summaries = self._extractor.extract(
                        Path(attempt.workspace),
                        backend=backend,
                        settings=settings,
                        candidate_directory=directory,
                        views=views,
                        timeout_seconds=limits.timeout_seconds,
                        maximum_database_bytes=estimate.database_bytes,
                        minimum_free_bytes=estimate.peak_workspace_bytes,
                        cancellation=control,
                        evidence_sink=evidence,
                        progress_sink=lambda value: progress.report(
                            route.node_id,
                            value.completed_views,
                            diagnostics=(
                                WorkMetric(name="completed_views", value=value.completed_views),
                                WorkMetric(name="features", value=value.features),
                            ),
                            force=value.completed_views == len(views),
                        ),
                    )
                    _require_selected_views(summaries, views)
                    control.checkpoint()
                    # model_construct is used only to calculate the self-excluding digest;
                    # complete validation occurs immediately before serialization.
                    provisional = LocalFeatureSet.model_construct(
                        selected_artifact_id=selected_handle.artifact_id,
                        selected_semantic_digest=selected_handle.semantic_digest,
                        method_id=settings.method_id,
                        descriptor=descriptor_signature(settings),
                        settings=settings,
                        backend_numerical_identity=backend.numerical_identity,
                        models=backend.model_identities(),
                        selected_view_count=len(views),
                        total_feature_count=sum(v.feature_count for v in summaries),
                        views=summaries,
                        semantic_digest="0" * 64,
                    )
                    payload = LocalFeatureSet.model_validate(
                        {
                            **provisional.model_dump(),
                            "semantic_digest": feature_semantic_digest(provisional),
                        }
                    )
                    repo.write_feature_metadata(Path(attempt.workspace), payload)
                    control.checkpoint()
                    handle = repo.publish_attempt(
                        root,
                        run_id=run_id,
                        node_id=route.node_id,
                        output_name=route.target.output_name,
                        artifact_type=FEATURE_ARTIFACT_TYPE,
                        contract_version=1,
                        recipe_key=key,
                        attempt=attempt,
                        input_lineage=route.input_lineage(),
                    )
                    event("features.stage.published", artifact_id=str(handle.artifact_id))
                control.checkpoint()
                repo.mark_run_succeeded(root, run_id=run_id)
                status = RunStatus.SUCCEEDED
                if not cache_hit:
                    progress.complete(route.node_id)
                event("features.run.completed")
            except FeatureTeardownError as exc:
                repo.mark_external_interrupted(
                    root, run_id=run_id, attempt_id=control.attempt, message=str(exc)
                )
                raise
            except (ExecutionCancelledError, FeatureCancelledError) as exc:
                # Backend cancellation without durable owner acceptance is a failure.
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
                handle, payload = None, None
                event("features.run.cancelled")
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
                event("features.run.failed", error=str(exc))
                raise
        return FeaturesRunResult(
            run_id=run_id,
            status=status,
            method_id=settings.method_id,
            feature_artifact=handle,
            selected_view_count=len(views),
            total_feature_count=payload.total_feature_count if payload else 0,
            cache_hit=cache_hit,
            warnings=tuple(warnings) + progress.snapshot().warnings,
        )


def _require_selected_views(
    summaries: tuple[FeatureViewSummary, ...],
    views: tuple[CandidateView, ...],
) -> None:
    expected = {v.view_id: (v.width, v.height, v.image_sha256) for v in views}
    if (
        len(summaries) != len(views)
        or {v.view_id for v in summaries} != set(expected)
        or any((v.width, v.height, v.image_sha256) != expected[v.view_id] for v in summaries)
    ):
        raise ValueError("Feature summaries differ from the exact selected published pixels")
