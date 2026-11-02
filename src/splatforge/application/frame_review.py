"""Frame-review use cases; storage and publication remain injected adapters."""

from pathlib import Path
from typing import Protocol
from uuid import UUID

from splatforge.core.frame_review import ReviewDecision, ReviewFilter, ReviewPage, ReviewResult


class FrameReviewRepository(Protocol):
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
    ) -> ReviewPage: ...

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
    ) -> ReviewResult: ...


class FrameReviewService:
    def __init__(self, repository: FrameReviewRepository) -> None:
        self._repository = repository

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
        if filter not in {"selected", "rejected", "all"}:
            raise ValueError("Unknown review filter")
        if not isinstance(scope, str) or not scope:
            raise ValueError("Unknown review scope")
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("Review pages require non-negative offset and limit between 1 and 100")
        return self._repository.page(
            root,
            run_id,
            filter=filter,
            scope=scope,
            offset=offset,
            limit=limit,
            anchor_view_id=anchor_view_id,
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
        if decision not in {"automatic", "exclude", "include"}:
            raise ValueError("Unknown manual review decision")
        if not view_ids or any(not isinstance(v, UUID) for v in view_ids):
            raise ValueError("Review requires candidate UUIDs")
        return self._repository.apply(
            root,
            run_id,
            tuple(sorted(set(view_ids), key=lambda v: v.int)),
            decision,
            expected_project_id=expected_project_id,
            expected_revision=expected_revision,
            expected_review_digest=expected_review_digest,
        )
