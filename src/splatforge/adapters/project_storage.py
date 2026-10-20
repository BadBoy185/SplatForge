"""Durable local project document and versioned SQLite state storage."""

from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import closing, contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
from uuid import uuid4

from pydantic import ValidationError

from splatforge.adapters.project_lock import (
    ProjectWriterLease,
    ProjectWriterLockFactory,
    WindowsProjectWriterLock,
)
from splatforge.adapters.state_schema import (
    CURRENT_STATE_SCHEMA_VERSION,
    SUPPORTED_STATE_SCHEMA_VERSIONS,
    initialize_state_v2,
)
from splatforge.application.projects import (
    ProjectError,
    ProjectSharingViolationError,
    StaleProjectRevisionError,
)
from splatforge.core.project import ProjectDocument

CURRENT_PROJECT_FORMAT_VERSION = 1
CURRENT_CONFIG_SCHEMA_VERSION = 1
_WINDOWS_REPLACE_CONFLICT_ERRORS = {5, 32, 33}


def _no_fault(_path: Path) -> None:
    return


@dataclass(frozen=True)
class PersistenceFaultHooks:
    """Deterministic failure boundaries for persistence recovery tests."""

    after_temporary_write: Callable[[Path], None] = _no_fault
    before_replace: Callable[[Path], None] = _no_fault


@dataclass(frozen=True)
class StorageVersions:
    project: int
    config: int
    state: int


@dataclass(frozen=True)
class CommittedProject:
    document: ProjectDocument
    versions: StorageVersions


@contextmanager
def storage_errors() -> Iterator[None]:
    try:
        yield
    except (OSError, UnicodeError, sqlite3.Error, ValidationError, json.JSONDecodeError) as exc:
        raise ProjectError(f"Project storage error: {exc}") from exc


class LocalProjectStore:
    def __init__(
        self,
        *,
        lock_factory: ProjectWriterLockFactory = WindowsProjectWriterLock,
        replace_file: Callable[[Path, Path], None] = os.replace,
        fault_hooks: PersistenceFaultHooks | None = None,
    ) -> None:
        self._lock_factory = lock_factory
        self._replace_file = replace_file
        self._fault_hooks = fault_hooks or PersistenceFaultHooks()

    def create(self, root: Path, document: ProjectDocument) -> None:
        with storage_errors():
            root = root.resolve()
            if root.exists() and (not root.is_dir() or any(root.iterdir())):
                raise ProjectError("Project destination must be missing or empty")
            self._validate_document(root, document)
            root.mkdir(parents=True, exist_ok=True)

            with self._lock_factory(root / "project.lock") as lease:
                self._validate_create_destination_under_lock(root, lease)
                lease.write_diagnostics(operation="create", owner_token=uuid4())
                with closing(sqlite3.connect(root / "state.sqlite")) as connection:
                    connection.execute("PRAGMA foreign_keys = ON")
                    with connection:
                        initialize_state_v2(connection, document.project_id)
                self._write_document(root, document)

    def load(self, root: Path) -> ProjectDocument:
        return self.inspect(root).document

    def inspect(self, root: Path) -> CommittedProject:
        with storage_errors():
            return self._load_committed(root.resolve())

    def save(
        self, root: Path, document: ProjectDocument, *, expected_revision: int
    ) -> None:
        if type(expected_revision) is not int or expected_revision < 0:
            raise ProjectError("expected_revision must be a non-negative integer")
        if document.revision != expected_revision + 1:
            raise ProjectError(
                "Candidate revision must equal expected_revision + 1 "
                f"(candidate={document.revision}, expected={expected_revision})"
            )

        with storage_errors():
            root = root.resolve()
            # Unsupported projects are rejected without creating or updating project.lock.
            self._load_committed(root)

            with self._lock_factory(root / "project.lock") as lease:
                # Close the preflight/acquisition race before any diagnostic or temp write.
                current = self._load_committed(root).document
                if current.project_id != document.project_id:
                    raise ProjectError("Cannot save a different project into this directory")
                if current.revision != expected_revision:
                    raise StaleProjectRevisionError(
                        "Stale project revision: "
                        f"expected {expected_revision}, committed {current.revision}"
                    )
                if current.created_at != document.created_at:
                    raise ProjectError("Cannot change project created_at")
                self._validate_document(root, document)
                lease.write_diagnostics(operation="save", owner_token=uuid4())
                self._write_document(root, document)

    def _load_committed(self, root: Path) -> CommittedProject:
        raw = json.loads(self._owned_path(root, "project.json").read_text(encoding="utf-8"))
        project_version, config_version = self._document_versions(raw)
        metadata = self._read_metadata(root)
        state_version = self._state_version(metadata)
        versions = StorageVersions(
            project=project_version,
            config=config_version,
            state=state_version,
        )
        self._dispatch_versions(versions)
        document = ProjectDocument.model_validate(raw)
        self._validate_document(root, document)
        if metadata.get("project_id") != str(document.project_id):
            raise ProjectError("Project document and state database identities differ")
        return CommittedProject(document=document, versions=versions)

    def _read_metadata(self, root: Path) -> dict[str, str]:
        uri = self._owned_path(root, "state.sqlite").as_uri() + "?mode=ro"
        with closing(sqlite3.connect(uri, uri=True)) as connection:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("BEGIN")
            try:
                metadata = dict(connection.execute("SELECT key, value FROM metadata"))
            finally:
                connection.rollback()
        return metadata

    @staticmethod
    def _document_versions(raw: object) -> tuple[int, int]:
        if not isinstance(raw, dict) or type(raw.get("project_format_version")) is not int:
            raise ProjectError("Invalid project_format_version")
        settings = raw.get("settings")
        if not isinstance(settings, dict) or type(settings.get("config_schema_version")) is not int:
            raise ProjectError("Invalid config_schema_version")
        return raw["project_format_version"], settings["config_schema_version"]

    @staticmethod
    def _state_version(metadata: dict[str, str]) -> int:
        raw = metadata.get("state_schema_version")
        if raw is None:
            raise ProjectError("Invalid state_schema_version")
        try:
            version = int(raw)
        except ValueError as exc:
            raise ProjectError("Invalid state_schema_version") from exc
        if str(version) != raw:
            raise ProjectError("Invalid state_schema_version")
        return version

    @staticmethod
    def _dispatch_versions(versions: StorageVersions) -> None:
        if (
            versions.project == CURRENT_PROJECT_FORMAT_VERSION
            and versions.config == CURRENT_CONFIG_SCHEMA_VERSION
            and versions.state in SUPPORTED_STATE_SCHEMA_VERSIONS
        ):
            return
        if (
            versions.project > CURRENT_PROJECT_FORMAT_VERSION
            or versions.config > CURRENT_CONFIG_SCHEMA_VERSION
            or versions.state > CURRENT_STATE_SCHEMA_VERSION
        ):
            raise ProjectError(
                "Unsupported newer project versions: "
                f"project={versions.project}, config={versions.config}, state={versions.state}"
            )
        raise ProjectError(
            "Unsupported project versions: "
            f"project={versions.project}, config={versions.config}, state={versions.state}"
        )

    @staticmethod
    def _validate_create_destination_under_lock(
        root: Path, lease: ProjectWriterLease
    ) -> None:
        entries = list(root.iterdir())
        for entry in entries:
            if entry.name != "project.lock" or not lease.created:
                raise ProjectError("Project destination changed while acquiring writer lock")

    def _validate_document(self, root: Path, document: ProjectDocument) -> None:
        ProjectDocument.model_validate_json(document.model_dump_json())
        if document.inventory_reference is not None:
            self._owned_path(root, document.inventory_reference)

    @staticmethod
    def _owned_path(root: Path, relative: str) -> Path:
        path = (root / relative).resolve()
        if not path.is_relative_to(root):
            raise ProjectError("Owned reference escapes the project directory")
        return path

    def _write_document(self, root: Path, document: ProjectDocument) -> None:
        target = self._owned_path(root, "project.json")
        temporary: Path | None = None
        try:
            payload = document.model_dump_json(indent=2).encode("utf-8") + b"\n"
            with NamedTemporaryFile(
                mode="w+b",
                dir=root,
                prefix=".project-",
                suffix=".tmp",
                delete=False,
            ) as stream:
                temporary = Path(stream.name)
                if stream.write(payload) != len(payload):
                    raise OSError("Could not write complete temporary project document")
                self._fault_hooks.after_temporary_write(temporary)
                stream.flush()
                os.fsync(stream.fileno())

            validated = ProjectDocument.model_validate_json(temporary.read_bytes())
            self._validate_document(root, validated)
            if validated != document:
                raise ProjectError("Validated temporary project document differs from candidate")
            self._fault_hooks.before_replace(temporary)
            try:
                self._replace_file(temporary, target)
            except OSError as exc:
                if getattr(exc, "winerror", None) in _WINDOWS_REPLACE_CONFLICT_ERRORS:
                    raise ProjectSharingViolationError(
                        f"Windows sharing/access violation while replacing {target}"
                    ) from exc
                raise
            # os.replace is the commit point. Do not perform fallible persistence after it.
            temporary = None
        finally:
            if temporary is not None:
                with suppress(OSError):
                    temporary.unlink(missing_ok=True)
