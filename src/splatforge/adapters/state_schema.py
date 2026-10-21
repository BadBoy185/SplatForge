"""The concrete state schema v4 and its explicit historical migrations."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Protocol
from uuid import UUID, uuid4

from splatforge.adapters.project_lock import (
    ProjectWriterLockFactory,
    WindowsProjectWriterLock,
)
from splatforge.application.projects import ProjectError, StateUpgradeResult
from splatforge.core.project import ProjectDocument

CURRENT_STATE_SCHEMA_VERSION = 4
SUPPORTED_STATE_SCHEMA_VERSIONS = frozenset({1, 2, 3, 4})

_EXECUTION_TABLES = (
    """
    CREATE TABLE runs (
        run_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL,
        project_revision INTEGER NOT NULL,
        owner_token TEXT NOT NULL,
        snapshot_path TEXT NOT NULL,
        snapshot_digest TEXT NOT NULL,
        status TEXT NOT NULL,
        created_at TEXT NOT NULL,
        started_at TEXT NOT NULL,
        finished_at TEXT,
        failure_json TEXT,
        cancellation_accepted_at TEXT,
        cancellation_request_digest TEXT
    )
    """,
    """
    CREATE TABLE attempts (
        attempt_id TEXT PRIMARY KEY,
        run_id TEXT NOT NULL REFERENCES runs(run_id),
        node_id TEXT NOT NULL,
        output_name TEXT NOT NULL,
        recipe_key TEXT NOT NULL,
        input_artifacts_json TEXT NOT NULL,
        literal_inputs_json TEXT NOT NULL,
        status TEXT NOT NULL,
        environment_json TEXT NOT NULL,
        source_verification_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        started_at TEXT,
        finished_at TEXT,
        expected_artifact_id TEXT,
        expected_manifest_digest TEXT,
        retry_of_attempt_id TEXT REFERENCES attempts(attempt_id),
        failure_category TEXT,
        cancellation_accepted_at TEXT,
        teardown_state TEXT NOT NULL DEFAULT 'not_required',
        failure_json TEXT
    )
    """,
    """
    CREATE TABLE artifacts (
        artifact_id TEXT PRIMARY KEY,
        producer_attempt_id TEXT NOT NULL UNIQUE REFERENCES attempts(attempt_id),
        producer_run_id TEXT NOT NULL REFERENCES runs(run_id),
        node_id TEXT NOT NULL,
        output_name TEXT NOT NULL,
        artifact_type TEXT NOT NULL,
        contract_version INTEGER NOT NULL,
        recipe_key TEXT NOT NULL,
        semantic_digest TEXT NOT NULL,
        manifest_path TEXT NOT NULL,
        manifest_digest TEXT NOT NULL,
        published_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE run_outputs (
        run_id TEXT NOT NULL REFERENCES runs(run_id),
        node_id TEXT NOT NULL,
        output_name TEXT NOT NULL,
        artifact_id TEXT NOT NULL REFERENCES artifacts(artifact_id),
        binding_kind TEXT NOT NULL,
        bound_at TEXT NOT NULL,
        PRIMARY KEY (run_id, node_id, output_name)
    )
    """,
    "CREATE INDEX artifacts_recipe_lookup ON artifacts(recipe_key, published_at, artifact_id)",
    "CREATE INDEX attempts_run_lookup ON attempts(run_id, node_id, created_at)",
)

_SOURCE_VERIFICATION_TABLES = (
    """
    CREATE TABLE source_verifications (
        verification_id TEXT PRIMARY KEY,
        source_id TEXT NOT NULL,
        source_revision INTEGER NOT NULL,
        expected_content_digest TEXT NOT NULL,
        policy_id TEXT NOT NULL,
        policy_version INTEGER NOT NULL,
        checked_at TEXT NOT NULL,
        baseline_evidence_json TEXT,
        current_evidence_json TEXT,
        full_hash_performed INTEGER NOT NULL,
        observed_content_digest TEXT,
        rehash_reason TEXT,
        assurance TEXT NOT NULL,
        stability_mechanism TEXT,
        outcome TEXT NOT NULL,
        diagnostic_json TEXT NOT NULL
    )
    """,
    """
    CREATE INDEX source_verifications_lookup
    ON source_verifications(source_id, source_revision, expected_content_digest, checked_at)
    """,
)


class _VersionView(Protocol):
    state: int


class _Inspection(Protocol):
    document: ProjectDocument
    versions: _VersionView


class _InspectableStore(Protocol):
    def inspect(self, root: Path) -> _Inspection: ...


class _BackupResult(Protocol):
    root: Path


class _BackupPreparer(Protocol):
    def prepare_under_lease(
        self,
        project_root: Path,
        backup_id: str,
        expected_document: ProjectDocument,
    ) -> _BackupResult: ...


def create_execution_tables(connection: sqlite3.Connection) -> None:
    for statement in _EXECUTION_TABLES:
        connection.execute(statement)


def create_source_verification_tables(connection: sqlite3.Connection) -> None:
    for statement in _SOURCE_VERIFICATION_TABLES:
        connection.execute(statement)


def initialize_state_v4(connection: sqlite3.Connection, project_id: UUID) -> None:
    connection.execute("CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    create_execution_tables(connection)
    create_source_verification_tables(connection)
    connection.executemany(
        "INSERT INTO metadata (key, value) VALUES (?, ?)",
        [
            ("state_schema_version", str(CURRENT_STATE_SCHEMA_VERSION)),
            ("project_id", str(project_id)),
        ],
    )


class LocalStateSchemaUpgrader:
    """Upgrade state v1/v2/v3 directly to v4 after a validated backup."""

    def __init__(
        self,
        *,
        store: _InspectableStore,
        backup_preparer: _BackupPreparer,
        lock_factory: ProjectWriterLockFactory = WindowsProjectWriterLock,
    ) -> None:
        self._store = store
        self._backup_preparer = backup_preparer
        self._lock_factory = lock_factory

    def upgrade(self, root: Path) -> StateUpgradeResult:
        root = root.resolve()
        preflight = self._store.inspect(root)
        if preflight.versions.state == CURRENT_STATE_SCHEMA_VERSION:
            return StateUpgradeResult(
                previous_version=CURRENT_STATE_SCHEMA_VERSION,
                current_version=CURRENT_STATE_SCHEMA_VERSION,
                upgraded=False,
            )
        if preflight.versions.state not in {1, 2, 3}:
            raise ProjectError(
                f"No state migration from version {preflight.versions.state} is supported"
            )

        with self._lock_factory(root / "project.lock") as lease:
            committed = self._store.inspect(root)
            if committed.versions.state == CURRENT_STATE_SCHEMA_VERSION:
                return StateUpgradeResult(
                    previous_version=CURRENT_STATE_SCHEMA_VERSION,
                    current_version=CURRENT_STATE_SCHEMA_VERSION,
                    upgraded=False,
                )
            if committed.versions.state not in {1, 2, 3}:
                raise ProjectError(
                    f"No state migration from version {committed.versions.state} is supported"
                )
            previous_version = committed.versions.state
            lease.write_diagnostics(operation="state-upgrade", owner_token=uuid4())
            backup = self._backup_preparer.prepare_under_lease(
                root,
                f"state-v{previous_version}-to-v4-{uuid4().hex}",
                committed.document,
            )
            if not backup.root.is_dir():
                raise ProjectError("State migration backup was not published")

            try:
                with closing(sqlite3.connect(root / "state.sqlite")) as connection:
                    connection.execute("PRAGMA foreign_keys = ON")
                    with connection:
                        connection.execute("BEGIN IMMEDIATE")
                        if previous_version == 1:
                            create_execution_tables(connection)
                            create_source_verification_tables(connection)
                        elif previous_version == 2:
                            connection.execute(
                                "ALTER TABLE runs ADD COLUMN cancellation_accepted_at TEXT"
                            )
                            connection.execute(
                                "ALTER TABLE runs ADD COLUMN cancellation_request_digest TEXT"
                            )
                            connection.execute(
                                "ALTER TABLE attempts ADD COLUMN retry_of_attempt_id TEXT "
                                "REFERENCES attempts(attempt_id)"
                            )
                            connection.execute(
                                "ALTER TABLE attempts ADD COLUMN failure_category TEXT"
                            )
                            connection.execute(
                                "ALTER TABLE attempts ADD COLUMN cancellation_accepted_at TEXT"
                            )
                            connection.execute(
                                "ALTER TABLE attempts ADD COLUMN teardown_state TEXT NOT NULL "
                                "DEFAULT 'not_required'"
                            )
                            create_source_verification_tables(connection)
                        else:
                            create_source_verification_tables(connection)
                        updated = connection.execute(
                            """
                            UPDATE metadata SET value=?
                            WHERE key='state_schema_version' AND value=?
                            """,
                            (str(CURRENT_STATE_SCHEMA_VERSION), str(previous_version)),
                        )
                        if updated.rowcount != 1:
                            raise ProjectError("Committed state version changed during migration")
            except sqlite3.Error as exc:
                raise ProjectError(f"State migration failed: {exc}") from exc

            return StateUpgradeResult(
                previous_version=previous_version,
                current_version=CURRENT_STATE_SCHEMA_VERSION,
                upgraded=True,
                backup_path=backup.root.relative_to(root).as_posix(),
            )
