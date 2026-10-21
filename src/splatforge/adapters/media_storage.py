"""Immutable JSONL source inventories and durable source-verification evidence."""

from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Callable
from contextlib import closing, suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from uuid import UUID, uuid4

from pydantic import ValidationError

from splatforge.adapters.project_lock import (
    ProjectWriterLockFactory,
    WindowsProjectWriterLock,
)
from splatforge.adapters.project_storage import CommittedProject, LocalProjectStore
from splatforge.application.projects import ProjectError, StaleProjectRevisionError
from splatforge.core.media import (
    InventoryHeader,
    SourceEvidence,
    SourceInventory,
    SourceOccurrence,
    VerificationResult,
)
from splatforge.core.project import ProjectDocument

_MAX_INVENTORY_LINE = 1024 * 1024


def _no_fault(_path: Path) -> None:
    return


@dataclass(frozen=True)
class MediaStorageFaultHooks:
    after_inventory_publish: Callable[[Path], None] = _no_fault


class LocalMediaRepository:
    def __init__(
        self,
        *,
        project_store: LocalProjectStore | None = None,
        lock_factory: ProjectWriterLockFactory = WindowsProjectWriterLock,
        fault_hooks: MediaStorageFaultHooks | None = None,
    ) -> None:
        self._project_store = project_store or LocalProjectStore(lock_factory=lock_factory)
        self._lock_factory = lock_factory
        self._fault_hooks = fault_hooks or MediaStorageFaultHooks()

    def inspect_project(self, root: Path) -> CommittedProject:
        return self._project_store.inspect(root.resolve())

    def load_current_inventory(
        self, root: Path, document: ProjectDocument
    ) -> SourceInventory | None:
        if document.inventory_reference is None:
            return None
        return self.load_inventory(root, document.inventory_reference)

    def load_inventory(self, root: Path, reference: str) -> SourceInventory:
        root = root.resolve()
        path = self._inventory_path(root, reference, must_exist=True)
        records: list[SourceOccurrence] = []
        try:
            with path.open("rb") as stream:
                header_line = stream.readline(_MAX_INVENTORY_LINE + 1)
                if not header_line or len(header_line) > _MAX_INVENTORY_LINE:
                    raise ProjectError("Inventory header is missing or exceeds its size limit")
                header = InventoryHeader.model_validate_json(header_line)
                while line := stream.readline(_MAX_INVENTORY_LINE + 1):
                    if len(line) > _MAX_INVENTORY_LINE:
                        raise ProjectError("Inventory source record exceeds its size limit")
                    records.append(SourceOccurrence.model_validate_json(line))
        except (OSError, ValidationError, json.JSONDecodeError) as exc:
            raise ProjectError(f"Could not read source inventory: {exc}") from exc
        inventory = SourceInventory(header=header, sources=tuple(records))
        if reference != self.reference_for(inventory.header.inventory_id):
            raise ProjectError("Inventory ID does not match its project reference")
        return inventory

    def commit_inventory(
        self,
        root: Path,
        *,
        expected_document: ProjectDocument,
        inventory: SourceInventory,
        validate_sources: Callable[[], None],
    ) -> ProjectDocument:
        root = root.resolve()
        self._validate_candidate(expected_document, inventory)
        self._project_store.inspect(root)
        with self._lock_factory(root / "project.lock") as lease:
            committed = self._project_store.inspect(root)
            current = committed.document
            if (
                current.project_id != expected_document.project_id
                or current.revision != expected_document.revision
                or current.inventory_reference != expected_document.inventory_reference
            ):
                raise StaleProjectRevisionError(
                    "Project revision or inventory changed while media was being prepared"
                )
            if committed.versions.state != 4:
                raise ProjectError(
                    "State upgrade required: run 'splatforge project upgrade-state <project>'"
                )
            previous = self.load_current_inventory(root, current)
            expected_inventory_revision = (
                1 if previous is None else previous.header.inventory_revision + 1
            )
            expected_parent = None if previous is None else previous.header.inventory_id
            if (
                inventory.header.inventory_revision != expected_inventory_revision
                or inventory.header.parent_inventory_id != expected_parent
            ):
                raise StaleProjectRevisionError(
                    "Candidate inventory does not extend the committed inventory"
                )
            validate_sources()
            lease.write_diagnostics(operation="media-inventory-commit", owner_token=uuid4())
            target = self._publish_inventory(root, inventory)
            self._fault_hooks.after_inventory_publish(target)
            saved = ProjectDocument.model_validate(
                {
                    **current.model_dump(mode="json"),
                    "revision": current.revision + 1,
                    "updated_at": datetime.now(UTC),
                    "inventory_reference": self.reference_for(inventory.header.inventory_id),
                }
            )
            self._project_store.save_under_lease(root, saved, expected_revision=current.revision)
            return saved

    def record_verification(self, root: Path, result: VerificationResult) -> None:
        committed = self._project_store.inspect(root.resolve())
        if committed.versions.state != 4:
            raise ProjectError(
                "State upgrade required: run 'splatforge project upgrade-state <project>'"
            )
        baseline = self._evidence_json(result.baseline_evidence)
        current = self._evidence_json(result.current_evidence)
        diagnostic = json.dumps(
            {"code": result.diagnostic_code, "message": result.diagnostic_message},
            ensure_ascii=False,
            separators=(",", ":"),
        )
        if len(diagnostic.encode("utf-8")) > 4096:
            raise ProjectError("Verification diagnostic exceeds its storage limit")
        try:
            with closing(sqlite3.connect(root.resolve() / "state.sqlite")) as connection:
                connection.execute("PRAGMA foreign_keys = ON")
                with connection:
                    connection.execute(
                        """
                        INSERT INTO source_verifications (
                            verification_id, source_id, source_revision,
                            expected_content_digest, policy_id, policy_version,
                            checked_at, baseline_evidence_json, current_evidence_json,
                            full_hash_performed, observed_content_digest, rehash_reason,
                            assurance, stability_mechanism, outcome, diagnostic_json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            str(result.verification_id),
                            str(result.source_id),
                            result.source_revision,
                            result.expected_content_sha256,
                            result.policy_id.value,
                            result.policy_version,
                            result.checked_at.isoformat(),
                            baseline,
                            current,
                            int(result.full_hash_performed),
                            result.observed_content_sha256,
                            result.rehash_reason.value if result.rehash_reason else None,
                            result.assurance.value,
                            result.stability_mechanism,
                            result.outcome.value,
                            diagnostic,
                        ),
                    )
        except sqlite3.Error as exc:
            raise ProjectError(f"Could not persist source verification: {exc}") from exc

    def latest_full_evidence(
        self,
        root: Path,
        *,
        source_id: UUID,
        source_revision: int,
        content_sha256: str,
    ) -> SourceEvidence | None:
        try:
            uri = (root.resolve() / "state.sqlite").as_uri() + "?mode=ro"
            with closing(sqlite3.connect(uri, uri=True)) as connection:
                row = connection.execute(
                    """
                    SELECT current_evidence_json FROM source_verifications
                    WHERE source_id=? AND source_revision=?
                      AND expected_content_digest=?
                      AND full_hash_performed=1
                      AND observed_content_digest=expected_content_digest
                      AND assurance='content_verified' AND outcome='unchanged'
                    ORDER BY checked_at DESC, verification_id DESC LIMIT 1
                    """,
                    (str(source_id), source_revision, content_sha256),
                ).fetchone()
        except sqlite3.Error as exc:
            raise ProjectError(f"Could not read source verification baseline: {exc}") from exc
        if row is None or row[0] is None:
            return None
        try:
            return SourceEvidence.model_validate_json(row[0])
        except ValidationError as exc:
            raise ProjectError("Stored source verification evidence is invalid") from exc

    @staticmethod
    def reference_for(inventory_id: UUID) -> str:
        return f"sources/{inventory_id}.jsonl"

    @staticmethod
    def _evidence_json(evidence: SourceEvidence | None) -> str | None:
        return evidence.model_dump_json() if evidence is not None else None

    @staticmethod
    def _validate_candidate(document: ProjectDocument, inventory: SourceInventory) -> None:
        if inventory.header.project_id != document.project_id:
            raise ProjectError("Inventory belongs to a different project")
        if document.inventory_reference is not None:
            if (
                inventory.header.inventory_revision < 2
                or inventory.header.parent_inventory_id is None
            ):
                raise ProjectError("A later inventory revision must identify its parent")
        elif (
            inventory.header.inventory_revision != 1
            or inventory.header.parent_inventory_id is not None
        ):
            raise ProjectError("The first inventory must be revision 1 without a parent")

    def _publish_inventory(self, root: Path, inventory: SourceInventory) -> Path:
        sources = self._sources_root(root, create=True)
        target = self._inventory_path(
            root, self.reference_for(inventory.header.inventory_id), must_exist=False
        )
        if target.exists() or target.is_symlink() or target.is_junction():
            raise ProjectError("Inventory ID is already published")
        temporary: Path | None = None
        try:
            with NamedTemporaryFile(
                mode="w+b", dir=sources, prefix=".inventory-", suffix=".tmp", delete=False
            ) as stream:
                temporary = Path(stream.name)
                records = [inventory.header, *inventory.sources]
                for record in records:
                    payload = record.model_dump_json().encode("utf-8") + b"\n"
                    if len(payload) > _MAX_INVENTORY_LINE:
                        raise ProjectError("Inventory record exceeds its size limit")
                    if stream.write(payload) != len(payload):
                        raise OSError("Could not write complete inventory record")
                stream.flush()
                os.fsync(stream.fileno())
            staged = self._load_staged(temporary)
            if staged != inventory:
                raise ProjectError("Validated inventory differs from the candidate")
            if self._sources_root(root, create=False) != sources:
                raise ProjectError("Project sources path changed during publication")
            os.link(temporary, target)
            temporary.unlink()
            temporary = None
            return target
        except OSError as exc:
            raise ProjectError(f"Could not publish source inventory: {exc}") from exc
        finally:
            if temporary is not None:
                with suppress(OSError):
                    temporary.unlink(missing_ok=True)

    @staticmethod
    def _load_staged(path: Path) -> SourceInventory:
        with path.open("rb") as stream:
            header_line = stream.readline(_MAX_INVENTORY_LINE + 1)
            if not header_line or len(header_line) > _MAX_INVENTORY_LINE:
                raise ProjectError("Inventory header is missing or exceeds its size limit")
            header = InventoryHeader.model_validate_json(header_line)
            sources: list[SourceOccurrence] = []
            while line := stream.readline(_MAX_INVENTORY_LINE + 1):
                if len(line) > _MAX_INVENTORY_LINE:
                    raise ProjectError("Inventory source record exceeds its size limit")
                sources.append(SourceOccurrence.model_validate_json(line))
        return SourceInventory(header=header, sources=tuple(sources))

    def _inventory_path(self, root: Path, reference: str, *, must_exist: bool) -> Path:
        parts = reference.split("/")
        if len(parts) != 2 or parts[0] != "sources" or not parts[1].endswith(".jsonl"):
            raise ProjectError("Inventory reference must use sources/<inventory-id>.jsonl")
        try:
            UUID(parts[1][:-6])
        except ValueError as exc:
            raise ProjectError("Inventory reference has an invalid inventory ID") from exc
        sources = self._sources_root(root, create=False)
        path = sources / parts[1]
        if path.is_symlink() or path.is_junction():
            raise ProjectError("Inventory file must not be a filesystem redirection")
        resolved = path.resolve(strict=must_exist)
        if resolved.parent != sources:
            raise ProjectError("Inventory path escapes the project sources directory")
        if must_exist and not resolved.is_file():
            raise ProjectError("Referenced source inventory is unavailable")
        return resolved

    @staticmethod
    def _sources_root(root: Path, *, create: bool) -> Path:
        candidate = root / "sources"
        if candidate.is_symlink() or candidate.is_junction():
            raise ProjectError("Project sources path must not be a filesystem redirection")
        resolved = candidate.resolve()
        if resolved != candidate or not resolved.is_relative_to(root):
            raise ProjectError("Project sources path escapes the project directory")
        if create:
            candidate.mkdir(exist_ok=True)
        if candidate.exists() and not candidate.is_dir():
            raise ProjectError("Project sources path must be a directory")
        return resolved
