"""Basic JSON replacement and SQLite metadata, without recovery/locking guarantees."""

import json
import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from pathlib import Path
from tempfile import NamedTemporaryFile

from pydantic import ValidationError

from splatforge.application.projects import ProjectError
from splatforge.core.project import ProjectDocument


@contextmanager
def storage_errors() -> Iterator[None]:
    try:
        yield
    except (OSError, UnicodeError, sqlite3.Error, ValidationError, json.JSONDecodeError) as exc:
        raise ProjectError(f"Project storage error: {exc}") from exc


class LocalProjectStore:
    def create(self, root: Path, document: ProjectDocument) -> None:
        with storage_errors():
            root = root.resolve()
            if root.exists() and (not root.is_dir() or any(root.iterdir())):
                raise ProjectError("Project destination must be missing or empty")
            self._validate_document(root, document)
            root.mkdir(parents=True, exist_ok=True)
            with closing(sqlite3.connect(root / "state.sqlite")) as connection, connection:
                connection.execute(
                    "CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
                )
                connection.executemany(
                    "INSERT INTO metadata (key, value) VALUES (?, ?)",
                    [("state_schema_version", "1"), ("project_id", str(document.project_id))],
                )
            self._write_document(root, document)

    def load(self, root: Path) -> ProjectDocument:
        with storage_errors():
            root = root.resolve()
            document = self._read_document(root)
            # Read-only mode must not create/repair missing or unsupported state.
            uri = self._owned_path(root, "state.sqlite").as_uri() + "?mode=ro"
            with closing(sqlite3.connect(uri, uri=True)) as connection:
                metadata = dict(connection.execute("SELECT key, value FROM metadata"))
            if metadata.get("state_schema_version") != "1":
                raise ProjectError("Unsupported state_schema_version")
            if metadata.get("project_id") != str(document.project_id):
                raise ProjectError("Project document and state database identities differ")
            return document

    def save(self, root: Path, document: ProjectDocument) -> None:
        with storage_errors():
            root = root.resolve()
            existing = self.load(root)
            if existing.project_id != document.project_id:
                raise ProjectError("Cannot save a different project into this directory")
            self._validate_document(root, document)
            self._write_document(root, document)

    def _read_document(self, root: Path) -> ProjectDocument:
        raw = json.loads(self._owned_path(root, "project.json").read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or type(raw.get("project_format_version")) is not int:
            raise ProjectError("Invalid project_format_version")
        if raw["project_format_version"] != 1:
            raise ProjectError("Unsupported project_format_version")
        settings = raw.get("settings")
        if not isinstance(settings, dict) or type(settings.get("config_schema_version")) is not int:
            raise ProjectError("Invalid config_schema_version")
        if settings["config_schema_version"] != 1:
            raise ProjectError("Unsupported config_schema_version")
        document = ProjectDocument.model_validate(raw)
        self._validate_document(root, document)
        return document

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
            with NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=root,
                prefix=".project-",
                suffix=".tmp",
                delete=False,
            ) as stream:
                temporary = Path(stream.name)
                stream.write(document.model_dump_json(indent=2) + "\n")
            # Validate actual bytes before replacement; no crash-recovery guarantee.
            ProjectDocument.model_validate_json(temporary.read_text(encoding="utf-8"))
            temporary.replace(target)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
