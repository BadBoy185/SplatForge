"""Manual preview/apply and explicit artifact pins over existing project storage."""

from pathlib import Path
from typing import Protocol
from uuid import UUID, uuid4

from splatforge.core.cleanup import CleanupPlan


class CleanupRepository(Protocol):
    def writer(self, root: Path, *, owner_token: UUID, operation: str): ...
    def cleanup_preview_lease(self, root: Path): ...
    def cleanup_plan(self, root: Path, requested: tuple[UUID, ...]) -> CleanupPlan: ...
    def apply_cleanup(self, root: Path, plan: CleanupPlan) -> None: ...
    def set_artifact_pin(self, root: Path, artifact_id: UUID, pinned: bool) -> None: ...


class CleanupService:
    def __init__(self, repository: CleanupRepository) -> None:
        self.repository = repository

    def preview(self, root: Path, artifact_ids: tuple[UUID, ...] = ()) -> CleanupPlan:
        # A coherent preview takes the same lease; it mutates no artifacts/state.
        with self.repository.cleanup_preview_lease(root):
            return self.repository.cleanup_plan(root, artifact_ids)

    def apply(
        self, root: Path, *, preview_digest: str, artifact_ids: tuple[UUID, ...] = ()
    ) -> CleanupPlan:
        with self.repository.writer(root, owner_token=uuid4(), operation="cleanup-apply"):
            plan = self.repository.cleanup_plan(root, artifact_ids)
            if plan.preview_digest != preview_digest:
                raise ValueError("cleanup.stale_preview: inspect a fresh dry-run before apply")
            self.repository.apply_cleanup(root, plan)
            return plan

    def pin(self, root: Path, artifact_id: UUID, pinned: bool = True) -> None:
        with self.repository.writer(root, owner_token=uuid4(), operation="artifact-pin"):
            self.repository.set_artifact_pin(root, artifact_id, pinned)
