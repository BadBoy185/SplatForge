"""Application orchestration for media inventories, verification and relinking."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from contextlib import ExitStack
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict

from splatforge.application.media_contracts import (
    MediaCancellation,
    MediaProbe,
    SourceFiles,
    SourceReadLease,
    SourceUnavailableError,
    SourceUnstableError,
    StrictSourceUnavailableError,
    classify_media_path,
)
from splatforge.application.media_progress import ImportReporter, MediaImportProgress
from splatforge.application.projects import ProjectError
from splatforge.core.logical_source_groups import LogicalSourceGroups
from splatforge.core.media import (
    InventoryHeader,
    MediaType,
    RehashReason,
    SourceEvidence,
    SourceInventory,
    SourceOccurrence,
    VerificationAssurance,
    VerificationOutcome,
    VerificationPolicyId,
    VerificationResult,
)
from splatforge.core.project import ProjectDocument


class MediaOperationCancelled(ProjectError):
    """Media preparation was cooperatively cancelled before commit."""


class StateV4RequiredError(ProjectError):
    """An M2 mutation requires the explicit state v4 upgrade."""


class _VersionView(Protocol):
    state: int


class _CommittedProject(Protocol):
    document: ProjectDocument
    versions: _VersionView


class MediaRepository(Protocol):
    def inspect_project(self, root: Path) -> _CommittedProject: ...

    def load_current_inventory(
        self, root: Path, document: ProjectDocument
    ) -> SourceInventory | None: ...

    def commit_inventory(
        self,
        root: Path,
        *,
        expected_document: ProjectDocument,
        inventory: SourceInventory,
        validate_sources: Callable[[], None],
        logical_groups: LogicalSourceGroups | None = None,
    ) -> ProjectDocument: ...

    def record_verification(self, root: Path, result: VerificationResult) -> None: ...

    def latest_full_evidence(
        self,
        root: Path,
        *,
        source_id: UUID,
        source_revision: int,
        content_sha256: str,
    ) -> SourceEvidence | None: ...


class MediaSourceSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_id: UUID
    source_revision: int
    filename: str
    media_type: MediaType
    byte_size: int
    content_sha256: str
    width: int
    height: int


class MediaAddResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    project_revision: int
    inventory_id: UUID
    inventory_reference: str
    inventory_revision: int
    added_sources: tuple[MediaSourceSummary, ...]


class MediaRelinkResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    project_revision: int
    inventory_id: UUID
    inventory_reference: str
    inventory_revision: int
    source: MediaSourceSummary


class CallbackCancellation:
    """Small cancellation bridge shared by streamed hashing and process polling."""

    def __init__(self, cancelled: Callable[[], bool] | None = None) -> None:
        self._cancelled = cancelled or (lambda: False)

    def checkpoint(self) -> None:
        if self.is_cancelled():
            raise MediaOperationCancelled("Media operation was cancelled")

    def is_cancelled(self) -> bool:
        return bool(self._cancelled())


class MediaService:
    def __init__(
        self,
        repository: MediaRepository,
        source_files: SourceFiles,
        probe: MediaProbe,
    ) -> None:
        self._repository = repository
        self._source_files = source_files
        self._probe = probe

    def add(
        self,
        root: Path,
        sources: Iterable[Path],
        *,
        source_group_id: UUID | None = None,
        camera_group_id: UUID | None = None,
        cancellation: MediaCancellation | None = None,
        progress: Callable[[MediaImportProgress], None] | None = None,
        folder_root: Path | None = None,
    ) -> MediaAddResult:
        paths = tuple(path.absolute() for path in sources)
        if not paths:
            raise ProjectError("At least one source is required")
        typed_paths = tuple((path, self._media_type(path)) for path in paths)
        reporter = ImportReporter(len(paths), progress)
        committed = self._require_v4(root)
        document = committed.document
        current = self._repository.load_current_inventory(root, document)
        prepared: list[SourceOccurrence] = []
        validations: list[tuple[Path, SourceReadLease, SourceEvidence]] = []
        with ExitStack() as stack:
            for path, media_type in typed_paths:
                if cancellation is not None:
                    cancellation.checkpoint()
                lease = stack.enter_context(self._source_files.lease(path))
                reporter.emit("hashing", len(prepared), path.name)
                hashed = self._source_files.hash_lease(lease, cancellation)
                reporter.emit("metadata", len(prepared), path.name)
                probe = self._probe.probe(path, media_type, cancellation=cancellation)
                if cancellation is not None:
                    cancellation.checkpoint()
                evidence = lease.current_evidence()
                if evidence != hashed.evidence.evidence_after:
                    raise SourceUnstableError(f"Source changed during probe: {path}")
                source_group = source_group_id or uuid4()
                camera_group = camera_group_id or uuid4()
                if camera_group_id is None:
                    while camera_group == source_group:
                        camera_group = uuid4()
                elif source_group_id is None:
                    while source_group == camera_group:
                        source_group = uuid4()
                prepared.append(
                    SourceOccurrence(
                        source_id=uuid4(),
                        source_revision=1,
                        external_locator=str(path),
                        display_filename=path.name,
                        original_filename=path.name,
                        media_type=media_type,
                        extension=path.suffix.lower(),
                        byte_size=hashed.evidence.byte_count,
                        content_sha256=hashed.sha256,
                        last_full_hash_at=hashed.evidence.hashed_at,
                        full_hash_evidence=hashed.evidence,
                        source_group_id=source_group,
                        camera_group_id=camera_group,
                        calibration_policy="metadata_only",
                        probe=probe,
                    )
                )
                validations.append((path, lease, evidence))
                reporter.emit("checked", len(prepared), path.name)
            inventory = self._next_inventory(
                document, current, [*(current.sources if current else ()), *prepared]
            )
            reporter.emit("finalizing", len(prepared))
            if cancellation is not None:
                cancellation.checkpoint()
            saved = self._repository.commit_inventory(
                root,
                expected_document=document,
                inventory=inventory,
                validate_sources=lambda: self._validate_leases(validations),
                **({"logical_groups": self._folder_groups(document, prepared, folder_root)}
                   if folder_root is not None else {}),
            )
        reporter.emit("succeeded", len(prepared))
        return MediaAddResult(
            project_revision=saved.revision,
            inventory_id=inventory.header.inventory_id,
            inventory_reference=saved.inventory_reference or "",
            inventory_revision=inventory.header.inventory_revision,
            added_sources=tuple(self._summary(source) for source in prepared),
        )

    def list(
        self, root: Path, *, document: ProjectDocument | None = None,
    ) -> SourceInventory | None:
        if document is None:
            document = self._repository.inspect_project(root).document
        return self._repository.load_current_inventory(root, document)

    def verify(
        self,
        root: Path,
        *,
        policy: VerificationPolicyId = VerificationPolicyId.BALANCED_LOCAL,
        source_ids: set[UUID] | None = None,
        cancellation: MediaCancellation | None = None,
        progress: Callable[[MediaImportProgress], None] | None = None,
    ) -> tuple[VerificationResult, ...]:
        committed = self._require_v4(root)
        inventory = self._repository.load_current_inventory(root, committed.document)
        sources = inventory.sources if inventory else ()
        if source_ids is not None:
            known = {source.source_id for source in sources}
            unknown = source_ids - known
            if unknown:
                raise ProjectError("Unknown source IDs: " + ", ".join(sorted(map(str, unknown))))
            sources = tuple(source for source in sources if source.source_id in source_ids)
        results: list[VerificationResult] = []
        reporter = ImportReporter(len(sources), progress, operation="verify")
        reporter.emit("checking", 0)
        for source in sources:
            if cancellation is not None:
                cancellation.checkpoint()
            reporter.emit("checking", len(results), source.display_filename)
            result = self._verify_source(root, source, policy, cancellation)
            self._repository.record_verification(root, result)
            results.append(result)
            reporter.emit("checked", len(results), source.display_filename)
        if cancellation is not None:
            cancellation.checkpoint()
        reporter.emit("succeeded", len(results))
        return tuple(results)

    @staticmethod
    def _folder_groups(
        document: ProjectDocument, sources: Iterable[SourceOccurrence], root: Path,
    ) -> LogicalSourceGroups:
        from splatforge.application.logical_source_groups import folder_groups_draft

        return folder_groups_draft(document, sources, root).logical_source_groups

    def relink(
        self,
        root: Path,
        source_id: UUID,
        new_path: Path,
        *,
        cancellation: MediaCancellation | None = None,
    ) -> MediaRelinkResult:
        candidate = new_path.absolute()
        self._media_type(candidate)
        committed = self._require_v4(root)
        document = committed.document
        current = self._repository.load_current_inventory(root, document)
        if current is None:
            raise ProjectError("Project has no source inventory")
        try:
            existing = next(source for source in current.sources if source.source_id == source_id)
        except StopIteration as exc:
            raise ProjectError(f"Unknown source {source_id}") from exc
        with self._source_files.lease(candidate) as lease:
            hashed = self._source_files.hash_lease(lease, cancellation)
            if hashed.sha256 != existing.content_sha256:
                raise ProjectError(
                    "Relink candidate has different content; use a future explicit "
                    "replacement workflow"
                )
            updated = existing.model_copy(
                update={
                    "external_locator": str(candidate),
                    "display_filename": candidate.name,
                    "byte_size": hashed.evidence.byte_count,
                    "last_full_hash_at": hashed.evidence.hashed_at,
                    "full_hash_evidence": hashed.evidence,
                }
            )
            records = tuple(
                updated if item.source_id == source_id else item for item in current.sources
            )
            inventory = self._next_inventory(document, current, records)
            saved = self._repository.commit_inventory(
                root,
                expected_document=document,
                inventory=inventory,
                validate_sources=lambda: self._validate_leases(
                    [(candidate, lease, hashed.evidence.evidence_after)]
                ),
            )
        return MediaRelinkResult(
            project_revision=saved.revision,
            inventory_id=inventory.header.inventory_id,
            inventory_reference=saved.inventory_reference or "",
            inventory_revision=inventory.header.inventory_revision,
            source=self._summary(updated),
        )

    def _verify_source(
        self,
        root: Path,
        source: SourceOccurrence,
        policy: VerificationPolicyId,
        cancellation: MediaCancellation | None,
    ) -> VerificationResult:
        checked_at = datetime.now(UTC)
        path = Path(source.external_locator)
        baseline = (
            self._repository.latest_full_evidence(
                root,
                source_id=source.source_id,
                source_revision=source.source_revision,
                content_sha256=source.content_sha256,
            )
            or source.full_hash_evidence.evidence_after
        )
        if policy == VerificationPolicyId.STRICT:
            return self._full_verification(
                source,
                path,
                baseline,
                checked_at,
                RehashReason.STRICT_POLICY,
                cancellation,
                strict=True,
            )
        try:
            current = self._source_files.evidence(path)
        except SourceUnavailableError as exc:
            outcome = (
                VerificationOutcome.MISSING if exc.missing else VerificationOutcome.UNAVAILABLE
            )
            return self._unavailable_result(source, policy, checked_at, baseline, outcome, str(exc))
        if baseline.trusted_local and current.trusted_local and baseline == current:
            return VerificationResult(
                verification_id=uuid4(),
                source_id=source.source_id,
                source_revision=source.source_revision,
                expected_content_sha256=source.content_sha256,
                policy_id=policy,
                checked_at=checked_at,
                baseline_evidence=baseline,
                current_evidence=current,
                full_hash_performed=False,
                observed_content_sha256=None,
                rehash_reason=None,
                assurance=VerificationAssurance.METADATA_UNCHANGED,
                stability_mechanism="trusted_windows_local_evidence",
                outcome=VerificationOutcome.UNCHANGED,
                diagnostic_code="source.metadata_unchanged",
                diagnostic_message="Trusted local source evidence is unchanged",
            )
        reason = self._rehash_reason(baseline, current)
        return self._full_verification(
            source,
            path,
            baseline,
            checked_at,
            reason,
            cancellation,
            strict=False,
        )

    def _full_verification(
        self,
        source: SourceOccurrence,
        path: Path,
        baseline: SourceEvidence,
        checked_at: datetime,
        reason: RehashReason,
        cancellation: MediaCancellation | None,
        *,
        strict: bool,
    ) -> VerificationResult:
        policy = VerificationPolicyId.STRICT if strict else VerificationPolicyId.BALANCED_LOCAL
        try:
            with self._source_files.lease(path, strict=strict) as lease:
                hashed = self._source_files.hash_lease(lease, cancellation)
        except StrictSourceUnavailableError as exc:
            return self._unavailable_result(
                source,
                policy,
                checked_at,
                baseline,
                VerificationOutcome.STRICT_UNAVAILABLE,
                str(exc),
            )
        except SourceUnavailableError as exc:
            outcome = (
                VerificationOutcome.MISSING if exc.missing else VerificationOutcome.UNAVAILABLE
            )
            return self._unavailable_result(source, policy, checked_at, baseline, outcome, str(exc))
        unchanged = hashed.sha256 == source.content_sha256
        return VerificationResult(
            verification_id=uuid4(),
            source_id=source.source_id,
            source_revision=source.source_revision,
            expected_content_sha256=source.content_sha256,
            policy_id=policy,
            checked_at=checked_at,
            baseline_evidence=baseline,
            current_evidence=hashed.evidence.evidence_after,
            full_hash_performed=True,
            observed_content_sha256=hashed.sha256,
            rehash_reason=reason,
            assurance=VerificationAssurance.CONTENT_VERIFIED,
            stability_mechanism=hashed.evidence.stability_mechanism,
            outcome=VerificationOutcome.UNCHANGED if unchanged else VerificationOutcome.CHANGED,
            diagnostic_code=("source.content_verified" if unchanged else "source.content_changed"),
            diagnostic_message=(
                "Full hash confirms the registered content"
                if unchanged
                else "Full hash differs from the registered content; dependent work is blocked"
            ),
        )

    @staticmethod
    def _unavailable_result(
        source: SourceOccurrence,
        policy: VerificationPolicyId,
        checked_at: datetime,
        baseline: SourceEvidence,
        outcome: VerificationOutcome,
        message: str,
    ) -> VerificationResult:
        return VerificationResult(
            verification_id=uuid4(),
            source_id=source.source_id,
            source_revision=source.source_revision,
            expected_content_sha256=source.content_sha256,
            policy_id=policy,
            checked_at=checked_at,
            baseline_evidence=baseline,
            current_evidence=None,
            full_hash_performed=False,
            observed_content_sha256=None,
            rehash_reason=None,
            assurance=VerificationAssurance.UNAVAILABLE,
            stability_mechanism=None,
            outcome=outcome,
            diagnostic_code=f"source.{outcome.value}",
            diagnostic_message=message[:1024] or "Source verification is unavailable",
        )

    def _validate_leases(
        self, validations: Iterable[tuple[Path, SourceReadLease, SourceEvidence]]
    ) -> None:
        for path, lease, expected in validations:
            if (
                lease.current_evidence() != expected
                or self._source_files.evidence(path) != expected
            ):
                raise SourceUnstableError(f"Source changed before inventory commit: {path}")

    @staticmethod
    def _rehash_reason(baseline: SourceEvidence, current: SourceEvidence) -> RehashReason:
        if current.storage_kind.value != "local_fixed":
            return RehashReason.UNTRUSTED_STORAGE
        if not baseline.trusted_local or not current.trusted_local:
            return RehashReason.INSUFFICIENT_EVIDENCE
        if baseline.volume_id != current.volume_id or baseline.file_id != current.file_id:
            return RehashReason.IDENTITY_CHANGED
        return RehashReason.METADATA_CHANGED

    @staticmethod
    def _media_type(path: Path) -> MediaType:
        media_type = classify_media_path(path)
        if media_type is not None:
            return media_type
        raise ProjectError(
            f"Unsupported media extension '{path.suffix}'; expected JPG, JPEG, PNG, MP4 or MOV"
        )

    @staticmethod
    def _next_inventory(
        document: ProjectDocument,
        current: SourceInventory | None,
        sources: Iterable[SourceOccurrence],
    ) -> SourceInventory:
        records = tuple(sources)
        revision = 1 if current is None else current.header.inventory_revision + 1
        return SourceInventory(
            header=InventoryHeader(
                inventory_id=uuid4(),
                project_id=document.project_id,
                inventory_revision=revision,
                parent_inventory_id=current.header.inventory_id if current else None,
                created_at=datetime.now(UTC),
                source_count=len(records),
            ),
            sources=records,
        )

    @staticmethod
    def _summary(source: SourceOccurrence) -> MediaSourceSummary:
        return MediaSourceSummary(
            source_id=source.source_id,
            source_revision=source.source_revision,
            filename=source.display_filename,
            media_type=source.media_type,
            byte_size=source.byte_size,
            content_sha256=source.content_sha256,
            width=source.probe.width,
            height=source.probe.height,
        )

    def _require_v4(self, root: Path) -> _CommittedProject:
        committed = self._repository.inspect_project(root)
        if committed.versions.state != 4:
            raise StateV4RequiredError(
                "State upgrade required: run 'splatforge project upgrade-state <project>'"
            )
        return committed
