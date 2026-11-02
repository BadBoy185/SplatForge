"""Exact-run frame review using the existing writer, CAS and artifact publication."""

import re
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from splatforge.adapters.execution_storage import LocalExecutionRepository
from splatforge.adapters.media_storage import LocalMediaRepository
from splatforge.application.execution import (
    ExecutionCancelledError,
    PublicationUnresolvedError,
    StateUpgradeRequiredError,
)
from splatforge.application.frame_review_projection import review_provenance, review_scopes
from splatforge.application.projects import ProjectError, StaleProjectRevisionError
from splatforge.core.execution import (
    ArtifactHandle,
    FailureCategory,
    FrameReviewRoute,
    RunSnapshot,
    SharpestViewPreparationRoute,
    ViewPreparationRoute,
)
from splatforge.core.frame_review import (
    AutomaticSelection,
    FrameReviewIntent,
    ManualDecision,
    ReviewBinding,
    ReviewDecision,
    ReviewedSelectedViewSet,
    ReviewFilter,
    ReviewItem,
    ReviewPage,
    ReviewResult,
    build_reviewed_selection,
)
from splatforge.core.project import ProjectDocument
from splatforge.core.quality import SharpestSelectedViewSet
from splatforge.core.views import (
    SELECTED_ARTIFACT_TYPE,
    CandidateViewSet,
    SelectedViewSet,
    validate_selected_against_candidate,
)


def _natural_text_key(value: str) -> tuple[tuple[int, int | str], ...]:
    """Human ordering for photo captions without changing numerical artifact identity."""
    return tuple(
        (0, int(part)) if part.isdigit() else (1, part.casefold())
        for part in re.split(r"(\d+)", value or "")
        if part
    )


def _review_order(view, source_order: dict[UUID, int]) -> tuple:
    """Presentation-only order: photos naturally, video frames chronologically per source."""
    source_index = source_order.get(view.source_id, len(source_order))
    if view.presentation_timestamp is not None:
        return (
            1,
            source_index,
            view.presentation_timestamp.seconds(),
            view.occurrence_index,
            view.view_id.int,
        )
    return (
        0,
        _natural_text_key(view.display_filename or view.frame_identity),
        source_index,
        view.occurrence_index,
        view.view_id.int,
    )


class LocalFrameReviewRepository:
    def __init__(self, repository: LocalExecutionRepository | None = None) -> None:
        self._repository = repository or LocalExecutionRepository()

    def _load(
        self,
        root: Path,
        run_id: UUID,
        document: ProjectDocument,
    ) -> tuple[ArtifactHandle, ArtifactHandle, CandidateViewSet, AutomaticSelection, ReviewBinding]:
        repo = self._repository
        if document.frame_review.schema_version != 1:
            raise ValueError("Unsupported frame review schema; review is unavailable")
        snapshot = repo._load_run_snapshot(root, run_id)
        if not isinstance(snapshot.route, (ViewPreparationRoute, SharpestViewPreparationRoute)):
            raise ValueError("Frame review requires an exact automatic preparation run")
        candidate_handle = repo.resolve_run_output(root, run_id, "candidate_views", "candidate_set")
        automatic_handle = repo.resolve_run_output(root, run_id, "selected_views", "selected_set")
        candidate = repo._validate_indexed_artifact(
            root,
            candidate_handle,
            metadata_only=True,
        )[2].parsed
        automatic = repo._validate_indexed_artifact(
            root,
            automatic_handle,
            metadata_only=True,
        )[2].parsed
        if not isinstance(candidate, CandidateViewSet) or not isinstance(
            automatic,
            (SelectedViewSet, SharpestSelectedViewSet),
        ):
            raise ValueError("Frame review requires candidate and automatic selection contracts")
        if (
            candidate.settings != snapshot.route.candidate.settings
            or candidate.backend != snapshot.route.ffmpeg_backend
            or automatic.settings != snapshot.route.selection.settings
            or automatic.candidate_semantic_digest != candidate_handle.semantic_digest
        ):
            raise ValueError("Frame review inputs differ from the exact preparation run")
        if isinstance(automatic, SelectedViewSet):
            validate_selected_against_candidate(automatic, candidate)
        base = ReviewBinding(
            run_id=run_id,
            candidate_artifact_id=candidate_handle.artifact_id,
            candidate_semantic_digest=candidate_handle.semantic_digest,
            automatic_artifact_id=automatic_handle.artifact_id,
            automatic_semantic_digest=automatic_handle.semantic_digest,
            decisions=(),
            effective_run_id=run_id,
        )
        raw = document.frame_review.bindings.get(str(run_id))
        binding = ReviewBinding.model_validate(raw) if raw is not None else base
        if binding.model_dump(exclude={"decisions", "effective_run_id"}) != base.model_dump(
            exclude={"decisions", "effective_run_id"},
        ):
            raise ValueError("Saved frame review differs from its exact run and artifact binding")
        expected = build_reviewed_selection(binding, candidate, automatic)
        if binding.decisions:
            effective_candidate = repo.resolve_run_output(
                root,
                binding.effective_run_id,
                "candidate_views",
                "candidate_set",
            )
            effective = repo.resolve_run_output(
                root,
                binding.effective_run_id,
                "selected_views",
                "selected_set",
            )
            payload = repo._validate_indexed_artifact(root, effective, metadata_only=True)[2].parsed
            if effective_candidate != candidate_handle or payload != expected:
                raise ValueError(
                    "Saved review head differs from its effective selection publication"
                )
        elif binding.effective_run_id != run_id:
            raise ValueError("Automatic review must resolve to its original preparation run")
        return candidate_handle, automatic_handle, candidate, automatic, binding

    def page(
        self,
        root: Path,
        run_id: UUID,
        *,
        filter: ReviewFilter = "selected",
        scope: str = "all",
        offset: int = 0,
        limit: int = 100,
        anchor_view_id: UUID | None = None,
    ) -> ReviewPage:
        root = root.resolve()
        repo = self._repository
        with repo.validation_operation():
            document = repo.inspect_project(root).document
            handle, _, candidate, automatic, binding = self._load(root, run_id, document)
            route = repo._load_run_snapshot(root, run_id).route
            assert isinstance(route, (ViewPreparationRoute, SharpestViewPreparationRoute))
            sources = {s.source_id: s for s in route.sources}
            source_order = {source.source_id: index for index, source in enumerate(route.sources)}
            selected = {
                v.view_id
                for v in build_reviewed_selection(
                    binding,
                    candidate,
                    automatic,
                ).selected_views
            }
            auto_ids = {v.view_id for v in automatic.selected_views}
            decisions = {v.view_id: v.decision for v in binding.decisions}
            reasons = {
                v.view_id: v.reason.value.replace("_", " ")
                for v in (
                    automatic.decisions
                    if isinstance(automatic, SharpestSelectedViewSet)
                    else automatic.selected_views
                )
            }
            scores = {
                item.view_id: item.sharpness_score for item in automatic.decisions
            } if isinstance(automatic, SharpestSelectedViewSet) else {}
            projection = review_scopes(
                candidate, route.sources, document.logical_source_groups,
                selected, auto_ids, set(decisions), scope,
            )
            views = tuple(
                v
                for v in sorted(candidate.views, key=lambda v: _review_order(v, source_order))
                if v.source_id in projection.source_ids
                and (filter == "all" or (v.view_id in selected) == (filter == "selected"))
            )
            if anchor_view_id is not None:
                index = next((i for i, v in enumerate(views) if v.view_id == anchor_view_id), None)
                if index is not None:
                    offset = index // limit * limit
            offset = min(offset, ((len(views) - 1) // limit * limit) if views else 0)
            directory = repo._owned_path(root, handle.manifest_path).parent
            # This reads saved inventory only. Never stat, probe or hash originals.
            inventory_available = True
            current_sources = {}
            try:
                inventory = LocalMediaRepository().load_current_inventory(root, document)
                if inventory is not None:
                    current_sources = {s.source_id: s for s in inventory.sources}
            except (ProjectError, OSError):
                inventory_available = False
            page_views = views[offset:offset + limit]
            checks = {}
            with repo._read_connection(root) as connection:
                for source_id in {v.source_id for v in page_views}:
                    source = sources[source_id]
                    row = connection.execute(
                        """SELECT outcome, checked_at FROM source_verifications
                           WHERE source_id=? AND source_revision=? AND expected_content_digest=?
                           ORDER BY checked_at DESC, verification_id DESC LIMIT 1""",
                        (str(source_id), source.source_revision, source.content_sha256),
                    ).fetchone()
                    if row is not None:
                        checks[source_id] = (row[0], datetime.fromisoformat(row[1]))
            items = []
            for index in range(offset, min(offset + limit, len(views))):
                view = views[index]
                decision = decisions.get(view.view_id, "automatic")
                auto_reason = reasons.get(view.view_id, "Automatic reason not recorded")
                reason = {"include": "Kept manually", "exclude": "Excluded manually"}.get(
                    decision,
                    auto_reason,
                )
                items.append(
                    ReviewItem(
                        view_id=view.view_id,
                        source_id=view.source_id,
                        path=repo._artifact_payload_path(directory, view.image_path),
                        caption=view.display_filename or view.frame_identity,
                        auto_selected=view.view_id in auto_ids,
                        decision=decision,
                        included=view.view_id in selected,
                        reason=reason,
                        auto_reason=auto_reason,
                        previous_view_id=views[index - 1].view_id if index else None,
                        next_view_id=views[index + 1].view_id if index + 1 < len(views) else None,
                        provenance=review_provenance(
                            view, sources[view.source_id], current_sources.get(view.source_id),
                            inventory_available=inventory_available,
                            organization=document.logical_source_groups,
                            source_check=checks.get(view.source_id),
                            automatic_score=scores.get(view.view_id),
                        ),
                    )
                )
            return ReviewPage(
                project_id=document.project_id,
                project_revision=document.revision,
                run_id=run_id,
                review_digest=binding.review_digest,
                effective_run_id=binding.effective_run_id,
                candidate_count=len(candidate.views),
                auto_selected_count=len(auto_ids),
                selected_count=len(selected),
                rejected_count=len(candidate.views) - len(selected),
                manual_count=len(decisions),
                offset=offset,
                total=len(views),
                items=tuple(items),
                scope_key=scope,
                scope_label=projection.selected_option.label,
                scopes=projection.options,
                scope_candidate_count=projection.selected_option.candidate_count,
                scope_auto_selected_count=projection.auto_selected_count,
                scope_selected_count=projection.selected_option.selected_count,
                scope_rejected_count=projection.selected_option.rejected_count,
                scope_manual_count=projection.manual_count,
            )

    def apply(
        self,
        root: Path,
        run_id: UUID,
        view_ids: tuple[UUID, ...],
        decision: ReviewDecision,
        *,
        expected_project_id: UUID,
        expected_revision: int,
        expected_review_digest: str,
    ) -> ReviewResult:
        root = root.resolve()
        repo = self._repository
        token = uuid4()
        with repo.writer(root, owner_token=token, operation="frame-review"):
            project = repo.inspect_project(root)
            document = project.document
            if document.project_id != expected_project_id or document.revision != expected_revision:
                raise StaleProjectRevisionError(
                    "Project changed; refresh frame review before saving"
                )
            if project.state_version != 4:
                raise StateUpgradeRequiredError("State upgrade required before frame review")
            repo.ensure_no_unfinished_run(root)
            candidate_handle, auto_handle, candidate, automatic, binding = self._load(
                root,
                run_id,
                document,
            )
            if binding.review_digest != expected_review_digest:
                raise StaleProjectRevisionError("Frame review changed; refresh before saving")
            if not set(view_ids) <= {v.view_id for v in candidate.views}:
                raise ValueError("Review batch contains an unknown candidate UUID")
            decisions = {item.view_id: item.decision for item in binding.decisions}
            for view_id in view_ids:
                if decision == "automatic":
                    decisions.pop(view_id, None)
                else:
                    decisions[view_id] = decision
            canonical = tuple(
                ManualDecision(view_id=view_id, decision=decisions[view_id])
                for view_id in sorted(decisions, key=lambda v: v.int)
            )
            if canonical == binding.decisions:
                return ReviewResult(
                    project_revision=document.revision,
                    review_digest=binding.review_digest,
                    effective_run_id=binding.effective_run_id,
                )
            effective_run_id = uuid4() if canonical else run_id
            binding = binding.model_copy(
                update={
                    "decisions": canonical,
                    "effective_run_id": effective_run_id,
                }
            )
            if canonical:
                self._publish(
                    root,
                    document,
                    token,
                    candidate_handle,
                    auto_handle,
                    build_reviewed_selection(binding, candidate, automatic),
                )
            bindings = dict(document.frame_review.bindings)
            if canonical:
                bindings[str(run_id)] = binding.model_dump(mode="json")
            else:
                bindings.pop(str(run_id), None)
            intent = FrameReviewIntent.model_validate(
                {
                    **document.frame_review.model_dump(mode="json"),
                    "bindings": bindings,
                }
            )
            saved = ProjectDocument.model_validate(
                {
                    **document.model_dump(mode="json"),
                    "frame_review": intent.model_dump(mode="json"),
                    "revision": document.revision + 1,
                    "updated_at": datetime.now(UTC),
                }
            )
            repo._project_store.save_under_lease(root, saved, expected_revision=document.revision)
            return ReviewResult(
                project_revision=saved.revision,
                review_digest=binding.review_digest,
                effective_run_id=effective_run_id,
            )

    def _publish(
        self,
        root: Path,
        document: ProjectDocument,
        token: UUID,
        candidate: ArtifactHandle,
        automatic: ArtifactHandle,
        selected: ReviewedSelectedViewSet,
    ) -> None:
        repo = self._repository
        route = FrameReviewRoute(candidate=candidate, automatic=automatic, selection=selected)
        run_id = selected.binding.effective_run_id
        attempt = None
        try:
            repo.create_run(
                root,
                RunSnapshot(
                    run_id=run_id,
                    project_id=document.project_id,
                    project_revision=document.revision,
                    owner_token=token,
                    created_at=datetime.now(UTC),
                    project_intent=document,
                    route=route,
                ),
            )
            repo.bind_cached_output(
                root,
                run_id=run_id,
                node_id="candidate_views",
                output_name="candidate_set",
                artifact_id=candidate.artifact_id,
            )
            attempt = repo.begin_attempt(
                root,
                run_id=run_id,
                node_id=route.node_id,
                output_name=route.target.output_name,
                recipe_key=route.recipe_key(),
                input_artifact_ids=(candidate.artifact_id, automatic.artifact_id),
                literal_inputs=route.literal_inputs(),
            )
            output = Path(attempt.workspace) / "output"
            output.mkdir()
            repo._write_new_file(
                output / "selected_views.json",
                selected.model_dump_json(indent=2).encode("utf-8") + b"\n",
            )
            repo.publish_attempt(
                root,
                run_id=run_id,
                node_id=route.node_id,
                output_name=route.target.output_name,
                artifact_type=SELECTED_ARTIFACT_TYPE,
                contract_version=1,
                recipe_key=route.recipe_key(),
                attempt=attempt,
                input_lineage=route.input_lineage(),
            )
            repo.mark_run_succeeded(root, run_id=run_id)
        except PublicationUnresolvedError:
            # Preserve owned pending publication for the normal orphan recovery path.
            raise
        except ExecutionCancelledError:
            repo.finish_cancellation(
                root,
                run_id=run_id,
                attempt_id=attempt.attempt_id if attempt is not None else None,
                teardown_confirmed=True,
            )
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
            raise
