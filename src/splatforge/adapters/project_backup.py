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

from splatforge.adapters.project_storage import LocalProjectStore
from splatforge.application.projects import ProjectError
from splatforge.core.project import ProjectDocument


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
        fault_hooks: BackupFaultHooks | None = None,
    ) -> None:
        self._store = store or LocalProjectStore()
        self._fault_hooks = fault_hooks or BackupFaultHooks()

    def prepare(self, project_root: Path, backup_id: str) -> PreparedMigrationBackup:
        project_root = project_root.resolve()
        backups_root = (project_root / "backups").resolve()
        destination = backups_root / backup_id
        if (
            not backup_id
            or backup_id in {".", ".."}
            or "/" in backup_id
            or "\\" in backup_id
            or destination.parent != backups_root
        ):
            raise ProjectError("Invalid migration backup ID")
        if destination.exists():
            raise ProjectError(f"Migration backup already exists: {destination}")

        document = self._store.load(project_root)
        backups_root.mkdir(parents=True, exist_ok=True)
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

        # Validate the complete backup using the normal current-version read path.
        backed_up = self._store.load(staging)
        if backed_up != document or self._store.load(project_root) != document:
            raise ProjectError("Project changed while migration backup was being prepared")

        self._fault_hooks.before_publish(staging)
        os.replace(staging, destination)
        return PreparedMigrationBackup(
            root=destination,
            project_id=document.project_id,
            revision=document.revision,
        )

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
