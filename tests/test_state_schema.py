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
        connection.execute("DROP TABLE run_outputs")
        connection.execute("DROP TABLE artifacts")
        connection.execute("DROP TABLE attempts")
        connection.execute("DROP TABLE runs")
        connection.execute(
            "UPDATE metadata SET value='1' WHERE key='state_schema_version'"
        )


def read_metadata(root: Path) -> dict[str, str]:
    with closing(sqlite3.connect(root / "state.sqlite")) as connection:
        return dict(connection.execute("SELECT key, value FROM metadata"))


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


def test_explicit_state_upgrade_preserves_project_document_and_is_idempotent(
    tmp_path: Path,
) -> None:
    service = build_project_service()
    project = service.create(tmp_path, "Upgrade")
    downgrade_to_real_state_v1(tmp_path)
    project_bytes = (tmp_path / "project.json").read_bytes()

    upgraded = service.upgrade_state(tmp_path)

    assert upgraded.upgraded is True
    assert (upgraded.previous_version, upgraded.current_version) == (1, 2)
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
    assert read_metadata(tmp_path)["state_schema_version"] == "2"
    with closing(sqlite3.connect(tmp_path / "state.sqlite")) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
    assert tables == {"metadata", "runs", "attempts", "artifacts", "run_outputs"}

    backups_before = {path.name for path in (tmp_path / "backups").iterdir()}
    again = service.upgrade_state(tmp_path)
    assert again.upgraded is False
    assert (again.previous_version, again.current_version) == (2, 2)
    assert again.backup_path is None
    assert {path.name for path in (tmp_path / "backups").iterdir()} == backups_before
    assert (tmp_path / "project.json").read_bytes() == project_bytes


def test_unsupported_newer_state_is_untouched_by_all_project_operations(
    tmp_path: Path,
) -> None:
    service = build_project_service()
    project = service.create(tmp_path, "Future state")
    with closing(sqlite3.connect(tmp_path / "state.sqlite")) as connection, connection:
        connection.execute(
            "UPDATE metadata SET value='3' WHERE key='state_schema_version'"
        )
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
