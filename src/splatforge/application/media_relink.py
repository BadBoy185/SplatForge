"""Reviewed, all-or-nothing relocation of registered source occurrences."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from contextlib import ExitStack
from pathlib import Path
from typing import Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from splatforge.application.media import (
    MediaOperationCancelled,
    MediaRepository,
    MediaService,
    MediaSourceSummary,
    StateV4RequiredError,
)
from splatforge.application.media_contracts import (
    MediaCancellation,
    SourceFiles,
    SourceReadLease,
    SourceUnavailableError,
    SourceUnstableError,
)
from splatforge.application.projects import ProjectError, StaleProjectRevisionError
from splatforge.core.media import SourceEvidence, SourceInventory, SourceOccurrence
from splatforge.core.project import ProjectDocument


class RelinkPathGuard(Protocol):
    """Filesystem checks stay in the adapter; old locations are purely lexical."""

    def normalize_folder(self, path: Path, *, must_exist: bool) -> Path: ...

    def relative_path(self, locator: Path, old_folder: Path) -> str | None: ...

    def candidate(self, new_folder: Path, relative_path: str) -> Path: ...

    def validate_candidate(self, new_folder: Path, candidate: Path) -> None: ...

    def validate_relative_paths(self, paths: tuple[str, ...]) -> None: ...


class FolderRelinkEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_id: UUID
    relative_path: str
    candidate: Path
    status: Literal["matched", "unavailable", "different_content", "unsafe_path", "unstable"]
    diagnostic: str = ""


class FolderRelinkPreview(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    project_id: UUID
    project_revision: int
    inventory_reference: str
    inventory_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    old_folder: Path
    new_folder: Path
    entries: tuple[FolderRelinkEntry, ...]

    @property
    def total(self) -> int:
        return len(self.entries)

    @property
    def matched(self) -> int:
        return sum(entry.status == "matched" for entry in self.entries)

    @property
    def can_apply(self) -> bool:
        return self.total > 0 and self.matched == self.total


class FolderRelinkProgress(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    completed: int = Field(ge=0)
    total: int = Field(ge=0)
    filename: str | None = None
    phase: Literal["checking", "hashing", "checked", "finalizing", "succeeded"]


class FolderRelinkResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    project_revision: int
    inventory_id: UUID
    inventory_reference: str
    inventory_revision: int
    sources: tuple[MediaSourceSummary, ...]


Progress = Callable[[FolderRelinkProgress], None]
Mapping = tuple[tuple[SourceOccurrence, str, Path], ...]


class FolderRelinkService:
    def __init__(
        self,
        repository: MediaRepository,
        source_files: SourceFiles,
        paths: RelinkPathGuard,
    ) -> None:
        self._repository = repository
        self._source_files = source_files
        self._paths = paths

    def preview(
        self,
        root: Path,
        old_folder: Path,
        new_folder: Path,
        *,
        cancellation: MediaCancellation | None = None,
        progress: Progress | None = None,
    ) -> FolderRelinkPreview:
        self._checkpoint(cancellation)
        document, current = self._current(root)
        old = self._paths.normalize_folder(old_folder, must_exist=False)
        new = self._paths.normalize_folder(new_folder, must_exist=True)
        mapping = self._mapping(current, old, new, cancellation)
        entries: list[FolderRelinkEntry] = []
        self._emit(progress, "checking", 0, len(mapping))
        for source, relative, candidate in mapping:
            self._checkpoint(cancellation)
            self._emit(progress, "hashing", len(entries), len(mapping), relative)
            status: Literal[
                "matched", "unavailable", "different_content", "unsafe_path", "unstable"
            ] = "matched"
            diagnostic = "Full SHA-256 matches the registered source"
            try:
                self._paths.validate_candidate(new, candidate)
                with self._source_files.lease(candidate) as lease:
                    hashed = self._source_files.hash_lease(lease, cancellation)
                    self._validate_source(candidate, lease, hashed.evidence.evidence_after)
                    self._paths.validate_candidate(new, candidate)
                    if hashed.sha256 != source.content_sha256:
                        status = "different_content"
                        diagnostic = "Full SHA-256 differs from the registered source"
            except MediaOperationCancelled:
                raise
            except SourceUnavailableError as exc:
                status, diagnostic = "unavailable", str(exc)
            except SourceUnstableError as exc:
                status, diagnostic = "unstable", str(exc)
            except ProjectError as exc:
                status, diagnostic = "unsafe_path", str(exc)
            entries.append(
                FolderRelinkEntry(
                    source_id=source.source_id,
                    relative_path=relative,
                    candidate=candidate,
                    status=status,
                    diagnostic=diagnostic,
                )
            )
            self._checkpoint(cancellation)
            self._emit(progress, "checked", len(entries), len(mapping), relative)
        self._checkpoint(cancellation)
        self._emit(progress, "succeeded", len(entries), len(mapping))
        return FolderRelinkPreview(
            project_id=document.project_id,
            project_revision=document.revision,
            inventory_reference=document.inventory_reference or "",
            inventory_digest=self._digest(current),
            old_folder=old,
            new_folder=new,
            entries=tuple(entries),
        )

    def apply(
        self,
        root: Path,
        preview: FolderRelinkPreview,
        *,
        cancellation: MediaCancellation | None = None,
        progress: Progress | None = None,
    ) -> FolderRelinkResult:
        self._checkpoint(cancellation)
        document, current = self._current(root)
        self._validate_provenance(document, current, preview)
        old = self._paths.normalize_folder(preview.old_folder, must_exist=False)
        new = self._paths.normalize_folder(preview.new_folder, must_exist=True)
        mapping = self._mapping(current, old, new, cancellation)
        expected = tuple(
            (source.source_id, relative, str(path)) for source, relative, path in mapping
        )
        supplied = tuple(
            (entry.source_id, entry.relative_path, str(entry.candidate))
            for entry in preview.entries
        )
        if not mapping or expected != supplied:
            raise ProjectError("Relink preview scope changed; preview the complete folder again")
        # Status and hashes from a client are never evidence. Every candidate is hashed again.
        updated: dict[UUID, SourceOccurrence] = {}
        validations: dict[str, tuple[Path, SourceReadLease, SourceEvidence]] = {}
        hashes = {}
        self._emit(progress, "checking", 0, len(mapping))
        with ExitStack() as stack:
            for source, relative, candidate in mapping:
                self._checkpoint(cancellation)
                self._paths.validate_candidate(new, candidate)
                self._emit(progress, "hashing", len(updated), len(mapping), relative)
                key = str(candidate)
                if key not in validations:
                    lease = stack.enter_context(self._source_files.lease(candidate))
                    hashed = self._source_files.hash_lease(lease, cancellation)
                    validations[key] = (candidate, lease, hashed.evidence.evidence_after)
                    hashes[key] = hashed
                hashed = hashes[key]
                if hashed.sha256 != source.content_sha256:
                    raise ProjectError(f"Relink candidate has different content: {relative}")
                updated[source.source_id] = source.model_copy(
                    update={
                        "external_locator": str(candidate),
                        "display_filename": candidate.name,
                        "byte_size": hashed.evidence.byte_count,
                        "last_full_hash_at": hashed.evidence.hashed_at,
                        "full_hash_evidence": hashed.evidence,
                    }
                )
                self._checkpoint(cancellation)
                self._emit(progress, "checked", len(updated), len(mapping), relative)
            inventory = MediaService._next_inventory(
                document,
                current,
                (updated.get(source.source_id, source) for source in current.sources),
            )
            self._emit(progress, "finalizing", len(updated), len(mapping))

            def validate() -> None:
                self._checkpoint(cancellation)
                self._paths.normalize_folder(new, must_exist=True)
                for candidate, lease, evidence in validations.values():
                    self._checkpoint(cancellation)
                    self._paths.validate_candidate(new, candidate)
                    self._validate_source(candidate, lease, evidence)
                # Inventory contents are immutable, but reject a changed on-disk generation too.
                latest = self._repository.load_current_inventory(root, document)
                if latest is None or self._digest(latest) != preview.inventory_digest:
                    raise StaleProjectRevisionError("Source inventory changed; preview again")
                self._checkpoint(cancellation)

            saved = self._repository.commit_inventory(
                root,
                expected_document=document,
                inventory=inventory,
                validate_sources=validate,
            )
        self._emit(progress, "succeeded", len(updated), len(mapping))
        return FolderRelinkResult(
            project_revision=saved.revision,
            inventory_id=inventory.header.inventory_id,
            inventory_reference=saved.inventory_reference or "",
            inventory_revision=inventory.header.inventory_revision,
            sources=tuple(MediaService._summary(source) for source in updated.values()),
        )

    def _current(self, root: Path) -> tuple[ProjectDocument, SourceInventory]:
        committed = self._repository.inspect_project(root)
        if committed.versions.state != 4:
            raise StateV4RequiredError("State upgrade required before folder relinking")
        current = self._repository.load_current_inventory(root, committed.document)
        if current is None:
            raise ProjectError("Project has no source inventory")
        return committed.document, current

    def _mapping(
        self,
        current: SourceInventory,
        old: Path,
        new: Path,
        cancellation: MediaCancellation | None,
    ) -> Mapping:
        entries = []
        for source in current.sources:
            self._checkpoint(cancellation)
            relative = self._paths.relative_path(Path(source.external_locator), old)
            if relative is not None:
                entries.append((source, relative, self._paths.candidate(new, relative)))
        self._paths.validate_relative_paths(tuple(relative for _, relative, _ in entries))
        return tuple(entries)

    def _validate_source(
        self,
        candidate: Path,
        lease: SourceReadLease,
        expected: SourceEvidence,
    ) -> None:
        if (
            lease.current_evidence() != expected
            or self._source_files.evidence(candidate) != expected
        ):
            raise SourceUnstableError(f"Source changed before inventory commit: {candidate}")

    @staticmethod
    def _digest(inventory: SourceInventory) -> str:
        canonical = json.dumps(
            inventory.model_dump(mode="json"),
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @classmethod
    def _validate_provenance(
        cls,
        document: ProjectDocument,
        inventory: SourceInventory,
        preview: FolderRelinkPreview,
    ) -> None:
        if (
            document.project_id != preview.project_id
            or document.revision != preview.project_revision
            or document.inventory_reference != preview.inventory_reference
            or cls._digest(inventory) != preview.inventory_digest
        ):
            raise StaleProjectRevisionError("Project or source inventory changed; preview again")

    @staticmethod
    def _checkpoint(cancellation: MediaCancellation | None) -> None:
        if cancellation is not None:
            cancellation.checkpoint()

    @staticmethod
    def _emit(
        progress: Progress | None,
        phase: Literal["checking", "hashing", "checked", "finalizing", "succeeded"],
        completed: int,
        total: int,
        filename: str | None = None,
    ) -> None:
        if progress is not None:
            progress(
                FolderRelinkProgress(
                    phase=phase,
                    completed=completed,
                    total=total,
                    filename=filename,
                )
            )
