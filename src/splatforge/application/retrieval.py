"""Offline representation publication, capability errors and inspectable export requests."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Protocol
from uuid import UUID, uuid4

from splatforge.application.execution import (
    ExecutionCancelledError,
    PublicationUnresolvedError,
    StateUpgradeRequiredError,
)
from splatforge.application.pairs import PairRepository
from splatforge.application.progress import ProgressSupport
from splatforge.application.work_models import retrieval_progress_plan
from splatforge.core.execution import (
    ArtifactHandle,
    FailureCategory,
    RetrievalBuildRoute,
    RunSnapshot,
)
from splatforge.core.pairs import Digest, PairingViewUniverse, project_pairing_universe
from splatforge.core.quality import SharpestSelectedViewSet
from splatforge.core.retrieval import (
    RetrievalExport,
    RetrievalRepresentationSet,
    RetrievalResourceLimits,
    RetrievalView,
    corpus_digest,
    validate_storage,
)
from splatforge.core.views import (
    CandidateViewSet,
    FrozenModel,
    SelectedViewSet,
    canonical_json_bytes,
    sha256_bytes,
)


class RetrievalCapabilityError(ValueError):
    code = "retrieval.production_backend_unselected"


class RetrievalRepository(PairRepository, Protocol):
    def load_retrieval(self, root: Path, handle: ArtifactHandle) -> RetrievalRepresentationSet: ...

    def artifact_directory(self, root: Path, artifact: ArtifactHandle) -> Path: ...


class RetrievalAdapter(Protocol):
    def inspect_export(self, path: Path) -> RetrievalExport: ...

    def import_export(
        self,
        workspace: Path,
        path: Path,
        payload: RetrievalRepresentationSet,
        *,
        checkpoint: Callable[[], None],
        progress: Callable[[int], None],
    ) -> None: ...


def require_corpus(
    export: RetrievalExport,
    candidate: CandidateViewSet,
    selected: SelectedViewSet | SharpestSelectedViewSet,
) -> None:
    universe = project_pairing_universe(candidate, selected)
    pixels = {v.view_id: v for v in candidate.views}
    expected = tuple(
        RetrievalView(
            view_id=v.view_id,
            image_sha256=pixels[v.view_id].image_sha256,
            pixel_transform_digest=sha256_bytes(
                canonical_json_bytes(
                    pixels[v.view_id].transform.model_dump(mode="json"),
                )
            ),
            width=pixels[v.view_id].width,
            height=pixels[v.view_id].height,
        )
        for v in universe.views
    )
    if (
        export.universe != universe
        or export.views != expected
        or export.corpus_semantic_digest != corpus_digest(universe, expected)
    ):
        raise ValueError("Retrieval export differs from exact selected corpus/pixels/metadata")


class RetrievalRunResult(FrozenModel):
    run_id: UUID
    status: str
    representation_artifact: ArtifactHandle | None
    cache_hit: bool
    indexed_view_count: int
    descriptor_bytes: int
    representation: RetrievalExport
    warnings: tuple[str, ...] = ()


class RetrievalCorpusRequest(FrozenModel):
    request_version: Literal[1] = 1
    universe: PairingViewUniverse
    views: tuple[RetrievalView, ...]
    corpus_semantic_digest: Digest
    image_paths: tuple[str, ...]


class RetrievalService:
    def __init__(
        self,
        repository: RetrievalRepository,
        adapter: RetrievalAdapter,
        *,
        progress: ProgressSupport | None = None,
    ) -> None:
        self._repository, self._adapter = repository, adapter
        self._progress = progress or ProgressSupport()

    def request(self, root: Path, *, views_run_id: UUID) -> RetrievalCorpusRequest:
        repo = self._repository
        candidate_handle = repo.resolve_run_output(
            root,
            views_run_id,
            "candidate_views",
            "candidate_set",
        )
        selected_handle = repo.resolve_run_output(
            root, views_run_id, "selected_views", "selected_set"
        )
        candidate, selected = repo.load_pairing_inputs(root, candidate_handle, selected_handle)
        universe = project_pairing_universe(candidate, selected)
        pixels = {v.view_id: v for v in candidate.views}
        views = tuple(
            RetrievalView(
                view_id=v.view_id,
                image_sha256=pixels[v.view_id].image_sha256,
                pixel_transform_digest=sha256_bytes(
                    canonical_json_bytes(
                        pixels[v.view_id].transform.model_dump(mode="json"),
                    )
                ),
                width=pixels[v.view_id].width,
                height=pixels[v.view_id].height,
            )
            for v in universe.views
        )
        directory = repo.artifact_directory(root, candidate_handle)
        return RetrievalCorpusRequest(
            universe=universe,
            views=views,
            corpus_semantic_digest=corpus_digest(universe, views),
            image_paths=tuple(
                str(directory / pixels[v.view_id].image_path) for v in universe.views
            ),
        )

    def build(
        self,
        root: Path,
        *,
        views_run_id: UUID,
        descriptor_export: Path | None = None,
        resource_limits: RetrievalResourceLimits | None = None,
    ) -> RetrievalRunResult:
        if descriptor_export is None:
            raise RetrievalCapabilityError(
                "No production retrieval model selected: representative M7b benchmark is pending. "
                "Provide --descriptor-export from an explicitly provisioned offline benchmark "
                "runtime. No model download or Exhaustive fallback is performed."
            )
        root, repo, run_id, owner = root.resolve(), self._repository, uuid4(), uuid4()
        limits = resource_limits or RetrievalResourceLimits()
        attempt = handle = None
        hit = False
        with repo.writer(root, owner_token=owner, operation="retrieval-build"):
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
            export = self._adapter.inspect_export(descriptor_export)
            require_corpus(export, candidate, selected)
            validate_storage(export, limits)
            route = RetrievalBuildRoute(
                views_run_id=views_run_id,
                candidate=candidate_handle,
                selected=selected_handle,
                export=export,
                export_locator=str(descriptor_export.absolute()),
                resource_limits=limits,
            )
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
                (retrieval_progress_plan(route, self._progress.hardware),),
                emit=lambda node, attempt, details: repo.append_event(
                    root,
                    run_id,
                    code="progress.snapshot",
                    node_id=node,
                    attempt_id=attempt,
                    details=details,
                ),
            )

            def event(code: str, **details: object) -> None:
                repo.append_event(
                    root,
                    run_id,
                    code=code,
                    node_id=route.node_id,
                    attempt_id=attempt.attempt_id if attempt else None,
                    details=details,
                )

            def checkpoint() -> None:
                aid = attempt.attempt_id if attempt else None
                if repo.accept_cancellation(root, run_id=run_id, attempt_id=aid):
                    raise ExecutionCancelledError(aid)

            try:
                event("retrieval.run.started", inference="external_export", views=len(export.views))
                checkpoint()
                cached = repo.find_cache(
                    root,
                    recipe_key=route.recipe_key(),
                    artifact_type=route.target.artifact_type,
                    contract_version=1,
                )
                if cached.artifact:
                    payload = repo.load_retrieval(root, cached.artifact)
                    if payload.export() != export:
                        raise ValueError("Cached representation differs from frozen export")
                    checkpoint()
                    repo.bind_cached_output(
                        root,
                        run_id=run_id,
                        node_id=route.node_id,
                        output_name=route.target.output_name,
                        artifact_id=cached.artifact.artifact_id,
                    )
                    handle, hit = cached.artifact, True
                    progress.cached(route.node_id)
                    event("retrieval.stage.cache_hit")
                else:
                    event(
                        "retrieval.stage.cache_miss", reasons=[x.reason for x in cached.ineligible]
                    )
                    attempt = repo.begin_attempt(
                        root,
                        run_id=run_id,
                        node_id=route.node_id,
                        output_name=route.target.output_name,
                        recipe_key=route.recipe_key(),
                        input_artifact_ids=tuple(x.artifact_id for x in route.input_lineage()),
                        literal_inputs=route.literal_inputs(),
                        environment={
                            "adapter_id": "splatforge.retrieval_offline",
                            "adapter_version": 1,
                        },
                        source_verification={"policy": "published_selected_pixels", "evidence": []},
                    )
                    progress.start(route.node_id, attempt.attempt_id)
                    payload = RetrievalRepresentationSet(
                        **export.model_dump(),
                        candidate_artifact_id=candidate_handle.artifact_id,
                        candidate_semantic_digest=candidate_handle.semantic_digest,
                        selected_artifact_id=selected_handle.artifact_id,
                        selected_semantic_digest=selected_handle.semantic_digest,
                        semantic_digest=export.recipe_key(),
                    )
                    self._adapter.import_export(
                        Path(attempt.workspace),
                        descriptor_export,
                        payload,
                        checkpoint=checkpoint,
                        progress=lambda n: progress.report(route.node_id, n),
                    )
                    checkpoint()
                    handle = repo.publish_attempt(
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
                    progress.complete(route.node_id)
                    event("retrieval.stage.published", artifact_id=str(handle.artifact_id))
                checkpoint()
                repo.mark_run_succeeded(root, run_id=run_id)
                status = "succeeded"
                event("retrieval.run.completed")
            except ExecutionCancelledError as exc:
                status = repo.finish_cancellation(
                    root, run_id=run_id, attempt_id=exc.attempt_id, teardown_confirmed=True
                ).value
                handle = None
                event("retrieval.run.cancelled")
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
                event("retrieval.run.failed", error=str(exc))
                raise
        return RetrievalRunResult(
            run_id=run_id,
            status=status,
            representation_artifact=handle,
            cache_hit=hit,
            indexed_view_count=len(export.views),
            descriptor_bytes=export.descriptor_bytes,
            representation=export,
            warnings=progress.snapshot().warnings,
        )
