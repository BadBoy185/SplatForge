"""Single-node metadata-only PairSelection use case."""

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
from splatforge.core.execution import (
    ArtifactHandle,
    FailureCategory,
    PairSelectionRoute,
    RunSnapshot,
)
from splatforge.core.pairs import (
    ExhaustiveSettings,
    PairEndpoints,
    PairResourceLimits,
    PairSet,
    SequentialSettings,
    canonical_explicit_pairs,
    compute_coverage,
    exhaustive_recipe_key,
    generate_pairs,
    pair_graph_digest,
    pairing_universe_digest,
    project_pairing_universe,
    sequential_recipe_key,
)
from splatforge.core.quality import SharpestSelectedViewSet
from splatforge.core.views import CandidateViewSet, FrozenModel, SelectedViewSet


class PairRepository(ExecutionRepository, Protocol):
    def resolve_run_output(
        self,
        root: Path,
        run_id: UUID,
        node_id: str,
        output_name: str,
    ) -> ArtifactHandle: ...

    def load_pairing_inputs(
        self,
        root: Path,
        candidate: ArtifactHandle,
        selected: ArtifactHandle,
    ) -> tuple[CandidateViewSet, SelectedViewSet | SharpestSelectedViewSet]: ...

    def load_pair_set(self, root: Path, handle: ArtifactHandle) -> PairSet: ...


class PairWorkspace(Protocol):
    def write_pair_set(self, workspace: Path, payload: PairSet) -> None: ...


class PairsRunResult(FrozenModel):
    run_id: UUID
    status: str
    method: str
    pair_set_artifact: ArtifactHandle | None
    cache_hit: bool
    selected_view_count: int
    pair_count: int = 0
    isolated_view_count: int = 0
    component_count: int = 0
    within_source_pair_count: int = 0
    cross_source_pair_count: int = 0
    cross_group_pair_count: int = 0
    warnings: tuple[str, ...] = ()


class PairsService:
    def __init__(self, repository: PairRepository, workspace: PairWorkspace) -> None:
        self._repository = repository
        self._workspace = workspace

    def build(
        self,
        root: Path,
        *,
        views_run_id: UUID,
        settings: SequentialSettings | ExhaustiveSettings,
        resource_limits: PairResourceLimits,
        explicit_pairs: tuple[PairEndpoints, ...] = (),
    ) -> PairsRunResult:
        root = root.resolve()
        repo = self._repository
        run_id, owner_token = uuid4(), uuid4()
        handle = None
        payload = None
        attempt = None
        cache_hit = False
        event_warnings: list[str] = []
        with repo.writer(root, owner_token=owner_token, operation="pairs-build"):
            project = repo.inspect_project(root)
            if project.state_version != 4:
                raise StateUpgradeRequiredError("Run 'splatforge project upgrade-state <project>'")
            repo.ensure_no_unfinished_run(root)
            candidate_handle = repo.resolve_run_output(
                root, views_run_id, "candidate_views", "candidate_set"
            )
            selected_handle = repo.resolve_run_output(
                root, views_run_id, "selected_views", "selected_set"
            )
            candidate, selected = repo.load_pairing_inputs(root, candidate_handle, selected_handle)
            universe = project_pairing_universe(candidate, selected)
            explicit_pairs = canonical_explicit_pairs(universe, explicit_pairs)
            if len(explicit_pairs) > resource_limits.max_pairs:
                raise ValueError("Explicit pairs exceed max_pairs")
            route = PairSelectionRoute(
                views_run_id=views_run_id,
                candidate=candidate_handle,
                selected=selected_handle,
                universe=universe,
                settings=settings,
                explicit_pairs=explicit_pairs,
                resource_limits=resource_limits,
            )
            snapshot = RunSnapshot(
                run_id=run_id,
                project_id=project.document.project_id,
                project_revision=project.document.revision,
                owner_token=owner_token,
                created_at=datetime.now(UTC),
                project_intent=project.document,
                route=route,
            )
            key_function = (
                sequential_recipe_key
                if isinstance(settings, SequentialSettings)
                else exhaustive_recipe_key
            )
            key = key_function(universe, settings, explicit_pairs)
            repo.create_run(root, snapshot)

            def event(code: str, **details: object) -> None:
                warning = repo.append_event(
                    root,
                    run_id,
                    code=code,
                    node_id=route.node_id,
                    attempt_id=attempt.attempt_id if attempt else None,
                    details=details,
                )
                if warning:
                    event_warnings.append(warning.message)

            def checkpoint() -> None:
                attempt_id = attempt.attempt_id if attempt else None
                if repo.accept_cancellation(root, run_id=run_id, attempt_id=attempt_id):
                    raise ExecutionCancelledError(attempt_id)

            try:
                event("pairs.run.started")
                checkpoint()
                cached = repo.find_cache(
                    root,
                    recipe_key=key,
                    artifact_type=route.target.artifact_type,
                    contract_version=route.target.contract_version,
                )
                if cached.artifact is not None:
                    payload = repo.load_pair_set(root, cached.artifact)
                    if (
                        payload.universe != universe
                        or payload.settings != settings
                        or payload.explicit_pairs != explicit_pairs
                    ):
                        raise ValueError("Cached PairSet does not match its recipe")
                    if len(payload.pairs) > resource_limits.max_pairs:
                        raise ValueError(
                            f"Cached pair count={len(payload.pairs)} exceeds "
                            f"max_pairs={resource_limits.max_pairs}"
                        )
                    checkpoint()
                    repo.bind_cached_output(
                        root,
                        run_id=run_id,
                        node_id=route.node_id,
                        output_name=route.target.output_name,
                        artifact_id=cached.artifact.artifact_id,
                    )
                    handle = cached.artifact
                    cache_hit = True
                    event("pairs.stage.cache_hit", artifact_id=str(handle.artifact_id))
                else:
                    event("pairs.stage.cache_miss", reasons=[v.reason for v in cached.ineligible])
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
                        environment={"adapter_id": "splatforge.pairs_python", "adapter_version": 1},
                        source_verification={"policy": "not_applicable", "evidence": []},
                    )
                    event("pairs.stage.started")
                    pairs = generate_pairs(
                        universe,
                        settings=settings,
                        limits=resource_limits,
                        explicit_pairs=explicit_pairs,
                        checkpoint=checkpoint,
                        progress=lambda count: event("pairs.stage.progress", pair_count=count),
                    )
                    event("pairs.stage.progress", pair_count=len(pairs))
                    checkpoint()
                    payload = PairSet(
                        candidate_artifact_id=candidate_handle.artifact_id,
                        candidate_semantic_digest=candidate_handle.semantic_digest,
                        selected_artifact_id=selected_handle.artifact_id,
                        selected_semantic_digest=selected_handle.semantic_digest,
                        selected_method_id=selected.selection_method_id,
                        universe=universe,
                        universe_digest=pairing_universe_digest(universe),
                        settings=settings,
                        explicit_pairs=explicit_pairs,
                        pairs=pairs,
                        coverage=compute_coverage(universe, pairs),
                        semantic_digest=pair_graph_digest(universe, pairs),
                    )
                    self._workspace.write_pair_set(Path(attempt.workspace), payload)
                    checkpoint()
                    handle = repo.publish_attempt(
                        root,
                        run_id=run_id,
                        node_id=route.node_id,
                        output_name=route.target.output_name,
                        artifact_type=route.target.artifact_type,
                        contract_version=route.target.contract_version,
                        recipe_key=key,
                        attempt=attempt,
                        input_lineage=route.input_lineage(),
                    )
                    event("pairs.stage.published", artifact_id=str(handle.artifact_id))
                checkpoint()
                repo.mark_run_succeeded(root, run_id=run_id)
                status = "succeeded"
                event("pairs.run.completed")
            except ExecutionCancelledError as exc:
                status = repo.finish_cancellation(
                    root,
                    run_id=run_id,
                    attempt_id=exc.attempt_id,
                    teardown_confirmed=True,
                ).value
                event("pairs.run.cancelled")
                handle, payload = None, None
            except PublicationUnresolvedError:
                raise
            except Exception as exc:
                if attempt is not None:
                    repo.mark_attempt_failed(
                        root,
                        attempt_id=attempt.attempt_id,
                        message=str(exc),
                        category=FailureCategory.NON_RETRYABLE,
                    )
                repo.mark_run_failed(root, run_id=run_id, message=str(exc))
                event("pairs.run.failed", error=str(exc))
                raise
        counts = (
            {}
            if payload is None
            else payload.coverage.model_dump(
                include={
                    "pair_count",
                    "isolated_view_count",
                    "component_count",
                    "within_source_pair_count",
                    "cross_source_pair_count",
                    "cross_group_pair_count",
                }
            )
        )
        return PairsRunResult(
            run_id=run_id,
            status=status,
            method=settings.method_id,
            pair_set_artifact=handle,
            cache_hit=cache_hit,
            selected_view_count=len(universe.views),
            warnings=tuple(event_warnings) + (() if payload is None else payload.coverage.warnings),
            **counts,
        )
