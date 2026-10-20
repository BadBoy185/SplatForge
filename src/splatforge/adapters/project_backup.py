"""Internal preparation boundary for a future concrete project migration."""

from __future__ import annotations

import os
import shutil
import sqlite3
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

from splatforge.adapters.project_lock import (
    ProjectWriterLockFactory,
    WindowsProjectWriterLock,
)
from splatforge.adapters.project_storage import LocalProjectStore
from splatforge.application.projects import ProjectError
from splatforge.core.project import ProjectDocument

_WINDOWS_RESERVED_NAMES = {
    "AUX",
    "CON",
    "CONIN$",
    "CONOUT$",
    "NUL",
    "PRN",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}
_WINDOWS_INVALID_NAME_CHARACTERS = frozenset('<>:"/\\|?*')


def _no_fault(_path: Path) -> None:
    return


@dataclass(frozen=True)
class BackupFaultHooks:
    """Deterministic preparation boundaries; never used by ordinary project saves."""

    after_project_copy: Callable[[Path], None] = _no_fault
    before_sqlite_backup: Callable[[Path], None] = _no_fault
    before_publish: Callable[[Path], None] = _no_fault


@dataclass(frozen=True)
class PreparedMigrationBackup:
    """A validated backup input for a future migration-specific recovery plan."""

    root: Path
    project_id: UUID
    revision: int


class LocalMigrationBackupPreparer:
    """Prepare a snapshot while the future migration coordinator holds writer ownership."""

    def __init__(
        self,
        *,
        store: LocalProjectStore | None = None,
        lock_factory: ProjectWriterLockFactory = WindowsProjectWriterLock,
        fault_hooks: BackupFaultHooks | None = None,
    ) -> None:
        self._store = store or LocalProjectStore()
        self._lock_factory = lock_factory
        self._fault_hooks = fault_hooks or BackupFaultHooks()

    def prepare(self, project_root: Path, backup_id: str) -> PreparedMigrationBackup:
        project_root = project_root.resolve()
        self._validate_backup_id(backup_id)

        with self._lock_factory(project_root / "project.lock") as lease:
            document = self._store.load(project_root)
            backups_root = self._validated_backups_root(project_root)
            destination = self._backup_destination(backups_root, backup_id)
            self._require_available_destination(destination)
            lease.write_diagnostics(operation="migration-backup", owner_token=uuid4())
            return self.prepare_under_lease(
                project_root,
                backup_id,
                document,
            )

    def prepare_under_lease(
        self,
        project_root: Path,
        backup_id: str,
        expected_document: ProjectDocument,
    ) -> PreparedMigrationBackup:
        """Prepare a backup while the caller continuously owns project.lock."""

        project_root = project_root.resolve()
        self._validate_backup_id(backup_id)
        document = self._store.load(project_root)
        if document != expected_document:
            raise ProjectError("Project changed before migration backup preparation")

        backups_root = self._validated_backups_root(project_root)
        destination = self._backup_destination(backups_root, backup_id)
        self._require_available_destination(destination)
        backups_root.mkdir(exist_ok=True)
        staging = backups_root / f".{backup_id}.{uuid4().hex}.pending"
        staging.mkdir()

        project_bytes = (project_root / "project.json").read_bytes()
        copied_document = ProjectDocument.model_validate_json(project_bytes)
        if copied_document != document:
            raise ProjectError("Project changed while migration backup was being prepared")
        self._write_bytes(staging / "project.json", project_bytes)
        self._fault_hooks.after_project_copy(staging)

        if document.inventory_reference is not None:
            source_inventory = project_root / document.inventory_reference
            if not source_inventory.is_file():
                raise ProjectError("Referenced inventory is unavailable for migration backup")
            self._copy_file(
                source_inventory,
                staging / document.inventory_reference,
            )

        self._fault_hooks.before_sqlite_backup(staging)
        self._backup_sqlite(project_root / "state.sqlite", staging / "state.sqlite")

        backed_up = self._store.load(staging)
        if backed_up != document or self._store.load(project_root) != document:
            raise ProjectError("Project changed while migration backup was being prepared")

        self._fault_hooks.before_publish(staging)
        publish_root = self._validated_backups_root(project_root)
        if publish_root != backups_root:
            raise ProjectError("Project backups path changed during backup preparation")
        destination = self._backup_destination(publish_root, backup_id)
        self._require_available_destination(destination)
        os.replace(staging, destination)
        return PreparedMigrationBackup(
            root=destination,
            project_id=document.project_id,
            revision=document.revision,
        )

    @staticmethod
    def _validate_backup_id(backup_id: str) -> None:
        base_name = backup_id.split(".", maxsplit=1)[0].upper()
        if (
            not backup_id
            or len(backup_id) > 64
            or backup_id in {".", ".."}
            or backup_id[-1] in {" ", "."}
            or any(
                character in _WINDOWS_INVALID_NAME_CHARACTERS or ord(character) < 32
                for character in backup_id
            )
            or base_name in _WINDOWS_RESERVED_NAMES
        ):
            raise ProjectError("Invalid migration backup ID")

    @staticmethod
    def _validated_backups_root(project_root: Path) -> Path:
        candidate = project_root / "backups"
        if candidate.is_symlink() or candidate.is_junction():
            raise ProjectError("Project backups path must not be a filesystem redirection")
        resolved = candidate.resolve()
        if resolved != candidate or not resolved.is_relative_to(project_root):
            raise ProjectError("Project backups path escapes the project directory")
        if candidate.exists() and not candidate.is_dir():
            raise ProjectError("Project backups path must be a directory")
        return resolved

    @staticmethod
    def _backup_destination(backups_root: Path, backup_id: str) -> Path:
        destination = backups_root / backup_id
        if destination.resolve().parent != backups_root:
            raise ProjectError("Invalid migration backup destination")
        return destination

    @staticmethod
    def _require_available_destination(destination: Path) -> None:
        if destination.exists() or destination.is_symlink() or destination.is_junction():
            raise ProjectError(f"Migration backup already exists: {destination}")

    @staticmethod
    def _write_bytes(path: Path, payload: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())

    @staticmethod
    def _copy_file(source: Path, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with source.open("rb") as source_stream, destination.open("xb") as destination_stream:
            shutil.copyfileobj(source_stream, destination_stream)
            destination_stream.flush()
            os.fsync(destination_stream.fileno())

    @staticmethod
    def _backup_sqlite(source: Path, destination: Path) -> None:
        source_uri = source.resolve().as_uri() + "?mode=ro"
        with (
            closing(sqlite3.connect(source_uri, uri=True)) as source_connection,
            closing(sqlite3.connect(destination)) as destination_connection,
        ):
            source_connection.execute("PRAGMA foreign_keys = ON")
            destination_connection.execute("PRAGMA foreign_keys = ON")
            source_connection.backup(destination_connection)
        with destination.open("r+b") as stream:
            os.fsync(stream.fileno())
