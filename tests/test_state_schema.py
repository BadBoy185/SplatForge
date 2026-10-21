import json
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from splatforge.application.execution import StateUpgradeRequiredError
from splatforge.application.projects import ProjectError
from splatforge.bootstrap import build_execution_service, build_project_service


def downgrade_to_real_state_v1(root: Path) -> None:
    with closing(sqlite3.connect(root / "state.sqlite")) as connection, connection:
        connection.execute("DROP TABLE source_verifications")
        connection.execute("DROP TABLE run_outputs")
        connection.execute("DROP TABLE artifacts")
        connection.execute("DROP TABLE attempts")
        connection.execute("DROP TABLE runs")
        connection.execute("UPDATE metadata SET value='1' WHERE key='state_schema_version'")


def read_metadata(root: Path) -> dict[str, str]:
    with closing(sqlite3.connect(root / "state.sqlite")) as connection:
        return dict(connection.execute("SELECT key, value FROM metadata"))


def downgrade_to_real_state_v2(root: Path) -> None:
    with closing(sqlite3.connect(root / "state.sqlite")) as connection, connection:
        connection.executescript(
            """
            DROP TABLE source_verifications;
            DROP TABLE run_outputs;
            DROP TABLE artifacts;
            DROP TABLE attempts;
            DROP TABLE runs;
            CREATE TABLE runs (
                run_id TEXT PRIMARY KEY, project_id TEXT NOT NULL,
                project_revision INTEGER NOT NULL, owner_token TEXT NOT NULL,
                snapshot_path TEXT NOT NULL, snapshot_digest TEXT NOT NULL,
                status TEXT NOT NULL, created_at TEXT NOT NULL,
                started_at TEXT NOT NULL, finished_at TEXT, failure_json TEXT
            );
            CREATE TABLE attempts (
                attempt_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL REFERENCES runs(run_id),
                node_id TEXT NOT NULL, output_name TEXT NOT NULL,
                recipe_key TEXT NOT NULL, input_artifacts_json TEXT NOT NULL,
                literal_inputs_json TEXT NOT NULL, status TEXT NOT NULL,
                environment_json TEXT NOT NULL,
                source_verification_json TEXT NOT NULL,
                created_at TEXT NOT NULL, started_at TEXT, finished_at TEXT,
                expected_artifact_id TEXT, expected_manifest_digest TEXT,
                failure_json TEXT
            );
            CREATE TABLE artifacts (
                artifact_id TEXT PRIMARY KEY,
                producer_attempt_id TEXT NOT NULL UNIQUE REFERENCES attempts(attempt_id),
                producer_run_id TEXT NOT NULL REFERENCES runs(run_id),
                node_id TEXT NOT NULL, output_name TEXT NOT NULL,
                artifact_type TEXT NOT NULL, contract_version INTEGER NOT NULL,
                recipe_key TEXT NOT NULL, semantic_digest TEXT NOT NULL,
                manifest_path TEXT NOT NULL, manifest_digest TEXT NOT NULL,
                published_at TEXT NOT NULL
            );
            CREATE TABLE run_outputs (
                run_id TEXT NOT NULL REFERENCES runs(run_id),
                node_id TEXT NOT NULL, output_name TEXT NOT NULL,
                artifact_id TEXT NOT NULL REFERENCES artifacts(artifact_id),
                binding_kind TEXT NOT NULL, bound_at TEXT NOT NULL,
                PRIMARY KEY (run_id, node_id, output_name)
            );
            CREATE INDEX artifacts_recipe_lookup
                ON artifacts(recipe_key, published_at, artifact_id);
            CREATE INDEX attempts_run_lookup
                ON attempts(run_id, node_id, created_at);
            UPDATE metadata SET value='2' WHERE key='state_schema_version';
            """
        )


def downgrade_to_real_state_v3(root: Path) -> None:
    with closing(sqlite3.connect(root / "state.sqlite")) as connection, connection:
        connection.execute("DROP TABLE source_verifications")
        connection.execute("UPDATE metadata SET value='3' WHERE key='state_schema_version'")


def test_state_v1_open_show_save_without_implicit_upgrade(tmp_path: Path) -> None:
    service = build_project_service()
    created = service.create(tmp_path, "State v1")
    downgrade_to_real_state_v1(tmp_path)

    assert service.open(tmp_path) == created
    assert json.loads(service.show(tmp_path))["revision"] == 0
    created.label = "Saved on v1"
    saved = service.save(tmp_path, created)

    assert saved.revision == 1
    assert read_metadata(tmp_path)["state_schema_version"] == "1"
    with closing(sqlite3.connect(tmp_path / "state.sqlite")) as connection:
        assert connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall() == [("metadata",)]


def test_fake_run_requires_explicit_state_upgrade_without_run_records(
    tmp_path: Path,
) -> None:
    build_project_service().create(tmp_path, "Needs upgrade")
    downgrade_to_real_state_v1(tmp_path)

    with pytest.raises(StateUpgradeRequiredError, match="State upgrade required"):
        build_execution_service().run(tmp_path)

    assert not (tmp_path / "runs").exists()
    assert not (tmp_path / "work").exists()
    assert not (tmp_path / "artifacts").exists()
    assert read_metadata(tmp_path)["state_schema_version"] == "1"


def test_state_v2_remains_readable_and_upgrades_directly_to_v4(tmp_path: Path) -> None:
    service = build_project_service()
    project = service.create(tmp_path, "State v2")
    downgrade_to_real_state_v2(tmp_path)
    project_bytes = (tmp_path / "project.json").read_bytes()

    assert service.open(tmp_path) == project
    project.label = "Saved on v2"
    saved = service.save(tmp_path, project)
    assert saved.revision == 1
    assert read_metadata(tmp_path)["state_schema_version"] == "2"
    with pytest.raises(StateUpgradeRequiredError, match="State upgrade required"):
        build_execution_service().run(tmp_path)

    before_upgrade = (tmp_path / "project.json").read_bytes()
    upgraded = service.upgrade_state(tmp_path)

    assert (upgraded.previous_version, upgraded.current_version) == (2, 4)
    assert upgraded.upgraded is True and upgraded.backup_path is not None
    backup = tmp_path / upgraded.backup_path
    assert read_metadata(backup)["state_schema_version"] == "2"
    assert (tmp_path / "project.json").read_bytes() == before_upgrade
    assert before_upgrade != project_bytes
    assert service.open(tmp_path).revision == 1
    with closing(sqlite3.connect(tmp_path / "state.sqlite")) as connection:
        run_columns = {row[1] for row in connection.execute("PRAGMA table_info(runs)")}
        attempt_columns = {row[1] for row in connection.execute("PRAGMA table_info(attempts)")}
    assert {"cancellation_accepted_at", "cancellation_request_digest"} <= run_columns
    assert {
        "retry_of_attempt_id",
        "failure_category",
        "cancellation_accepted_at",
        "teardown_state",
    } <= attempt_columns


def test_explicit_state_upgrade_preserves_project_document_and_is_idempotent(
    tmp_path: Path,
) -> None:
    service = build_project_service()
    project = service.create(tmp_path, "Upgrade")
    downgrade_to_real_state_v1(tmp_path)
    project_bytes = (tmp_path / "project.json").read_bytes()

    upgraded = service.upgrade_state(tmp_path)

    assert upgraded.upgraded is True
    assert (upgraded.previous_version, upgraded.current_version) == (1, 4)
    assert upgraded.backup_path is not None
    backup = tmp_path / upgraded.backup_path
    assert backup.is_dir()
    assert read_metadata(backup)["state_schema_version"] == "1"
    with closing(sqlite3.connect(backup / "state.sqlite")) as connection:
        assert connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall() == [("metadata",)]

    assert (backup / "project.json").read_bytes() == project_bytes
    assert (tmp_path / "project.json").read_bytes() == project_bytes
    assert service.open(tmp_path).revision == project.revision == 0
    assert read_metadata(tmp_path)["state_schema_version"] == "4"
    with closing(sqlite3.connect(tmp_path / "state.sqlite")) as connection:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    assert tables == {
        "metadata",
        "runs",
        "attempts",
        "artifacts",
        "run_outputs",
        "source_verifications",
    }

    backups_before = {path.name for path in (tmp_path / "backups").iterdir()}
    again = service.upgrade_state(tmp_path)
    assert again.upgraded is False
    assert (again.previous_version, again.current_version) == (4, 4)
    assert again.backup_path is None
    assert {path.name for path in (tmp_path / "backups").iterdir()} == backups_before
    assert (tmp_path / "project.json").read_bytes() == project_bytes


def test_unsupported_newer_state_is_untouched_by_all_project_operations(
    tmp_path: Path,
) -> None:
    service = build_project_service()
    project = service.create(tmp_path, "Future state")
    with closing(sqlite3.connect(tmp_path / "state.sqlite")) as connection, connection:
        connection.execute("UPDATE metadata SET value='5' WHERE key='state_schema_version'")
    before = {
        path.relative_to(tmp_path).as_posix(): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
    }

    for operation in (
        lambda: service.open(tmp_path),
        lambda: service.show(tmp_path),
        lambda: service.save(tmp_path, project),
        lambda: service.upgrade_state(tmp_path),
    ):
        with pytest.raises(ProjectError, match="Unsupported newer"):
            operation()
        assert {
            path.relative_to(tmp_path).as_posix(): path.read_bytes()
            for path in tmp_path.rglob("*")
            if path.is_file()
        } == before


def test_state_v3_fake_execution_and_upgrade_to_v4_preserve_history(tmp_path: Path) -> None:
    service = build_project_service()
    project = service.create(tmp_path, "Historical v3")
    downgrade_to_real_state_v3(tmp_path)
    assert service.open(tmp_path) == project
    assert json.loads(service.show(tmp_path))["revision"] == project.revision
    project.label = "Saved on v3"
    saved = service.save(tmp_path, project)
    assert read_metadata(tmp_path)["state_schema_version"] == "3"

    result = build_execution_service().run(tmp_path, start=2, count=2, factor=3)
    project_bytes = (tmp_path / "project.json").read_bytes()
    assert result.status == "succeeded"
    assert (
        json.loads(build_execution_service().show(tmp_path, result.run_id))["state"]["status"]
        == "succeeded"
    )

    upgraded = service.upgrade_state(tmp_path)

    assert (upgraded.previous_version, upgraded.current_version) == (3, 4)
    assert (tmp_path / "project.json").read_bytes() == project_bytes
    assert service.open(tmp_path).revision == saved.revision
    assert (
        json.loads(build_execution_service().show(tmp_path, result.run_id))["state"]["status"]
        == "succeeded"
    )
    with closing(sqlite3.connect(tmp_path / "state.sqlite")) as connection:
        assert connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='source_verifications'"
        ).fetchone() == ("source_verifications",)
