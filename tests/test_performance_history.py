from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from progress_helpers import FakeClock, plan, sample

from splatforge.adapters.performance import (
    LocalHardwareObserver,
    LocalPerformanceHistory,
    default_performance_path,
    signature_key,
)


def test_missing_empty_supported_history_and_explicit_reset(tmp_path: Path) -> None:
    path = tmp_path / "local worker Ž" / "performance.sqlite"
    history = LocalPerformanceHistory(path)
    assert history.read(plan().signature).samples == ()
    assert history.statistics().sample_count == 0
    assert history.reset() == ()
    assert not path.exists()
    assert history.record(sample()) == ()
    assert history.read(plan().signature).samples == (sample(),)
    statistics = history.statistics()
    assert statistics.performance_schema_version == 1
    assert statistics.sample_count == 1
    assert statistics.signatures[0].median_throughput == 100
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone() == (1,)
    assert history.reset() == ()
    assert path.exists()
    assert history.statistics().sample_count == 0


def test_newer_or_unversioned_database_is_preserved(tmp_path: Path) -> None:
    for version in (0, 2, 100):
        path = tmp_path / f"schema-{version}.sqlite"
        with sqlite3.connect(path) as connection:
            connection.execute("CREATE TABLE future(value TEXT)")
            connection.execute("INSERT INTO future VALUES('preserve')")
            connection.execute(f"PRAGMA user_version={version}")
        original = path.read_bytes()
        history = LocalPerformanceHistory(path)
        assert history.read(plan().signature).warnings == ("history.unsupported_schema",)
        assert history.record(sample()) == ("history.unsupported_schema",)
        assert history.reset() == ("history.unsupported_schema",)
        assert path.read_bytes() == original


def test_corruption_degrades_without_deleting_database(tmp_path: Path) -> None:
    path = tmp_path / "corrupt.sqlite"
    path.write_bytes(b"not a database")
    history = LocalPerformanceHistory(path)
    assert history.read(plan().signature).samples == ()
    assert history.read(plan().signature).warnings == ("history.unavailable",)
    assert history.record(sample()) == ("history.unavailable",)
    assert history.statistics().warnings == ("history.unavailable",)
    assert history.reset() == ("history.unavailable",)
    assert path.read_bytes() == b"not a database"


def test_malformed_rows_are_ignored_with_bounded_warning(tmp_path: Path) -> None:
    history = LocalPerformanceHistory(tmp_path / "history.sqlite")
    history.record(sample())
    with sqlite3.connect(history.path) as connection:
        connection.executemany(
            "INSERT INTO samples(signature_key, recorded_at, sample_json) VALUES(?,?,?)",
            [
                (signature_key(plan().signature), "2026-10-22", text)
                for text in ("{}", "malformed", "x" * 17000)
            ],
        )
    value = history.read(plan().signature)
    assert value.samples == (sample(),)
    assert value.warnings == ("history.malformed_row",)
    assert history.statistics().sample_count == 1
    assert history.statistics().warnings == ("history.malformed_row",)


def test_locked_store_never_changes_execution_requirements(tmp_path: Path) -> None:
    history = LocalPerformanceHistory(tmp_path / "history.sqlite")
    history.record(sample())
    blocker = sqlite3.connect(history.path)
    try:
        blocker.execute("BEGIN EXCLUSIVE")
        assert history.read(plan().signature).warnings == ("history.unavailable",)
        assert history.record(sample()) == ("history.unavailable",)
        assert history.reset() == ("history.unavailable",)
    finally:
        blocker.rollback()
        blocker.close()
    assert history.statistics().sample_count == 1


@pytest.mark.parametrize("failure", ["directory", "readonly", "write"])
def test_permission_and_write_failures_are_bounded_and_private(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    history = LocalPerformanceHistory(tmp_path / "history.sqlite")
    if failure == "directory":

        def denied(*args: object, **kwargs: object) -> None:
            raise PermissionError("C:/Users/private/project/source.mp4 API_KEY=secret")

        monkeypatch.setattr(Path, "mkdir", denied)
    else:
        history.record(sample())
        original_connect = sqlite3.connect

        def denied_connect(*args: object, **kwargs: object) -> sqlite3.Connection:
            if failure == "readonly":
                raise sqlite3.OperationalError("readonly C:/Users/private")
            connection = original_connect(*args, **kwargs)
            connection.execute("PRAGMA query_only=ON")
            return connection

        monkeypatch.setattr(sqlite3, "connect", denied_connect)
    assert history.record(sample()) == ("history.unavailable",)


def test_retention_is_oldest_first_per_signature_and_globally(tmp_path: Path) -> None:
    history = LocalPerformanceHistory(tmp_path / "history.sqlite", per_signature=3, max_samples=4)
    clock = FakeClock()
    stage = plan()
    for rate in (10, 20, 30, 40, 50):
        clock.advance(1)
        assert history.record(sample(stage, rate=rate, clock=clock)) == ()
    assert [row.throughput for row in history.read(stage.signature).samples] == [50, 40, 30]
    other = stage.model_copy(
        update={"signature": stage.signature.model_copy(update={"settings_key": "b" * 64})}
    )
    for rate in (60, 70):
        clock.advance(1)
        history.record(sample(other, rate=rate, clock=clock))
    assert history.statistics().sample_count == 4
    assert [row.throughput for row in history.read(stage.signature).samples] == [50, 40]


def test_history_contains_only_performance_data_not_local_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SECRET_CANARY", "private_secret_canary")
    history = LocalPerformanceHistory(tmp_path / "private_project_canary" / "performance.sqlite")
    assert history.record(sample()) == ()
    raw = history.path.read_bytes()
    for prohibited in (
        b"private_project_canary",
        b"private_secret_canary",
        b"source_id",
        b"project_id",
        b"filename",
        b"hostname",
        b"username",
        b"source_path",
    ):
        assert prohibited not in raw
    assert b"test_cpu" in raw
    assert b"test.adapter" in raw
    assert b"throughput" in raw


def test_default_location_and_safe_hardware_classification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert default_performance_path() == tmp_path / "SplatForge" / "performance.sqlite"
    hardware = LocalHardwareObserver().observe()
    assert hardware.hardware_schema_version == 1
    assert hardware.device == "cpu"
    assert hardware.logical_cpus is not None
    assert set(type(hardware).model_fields) == {
        "hardware_schema_version",
        "platform_family",
        "cpu_family",
        "logical_cpus",
        "ram_gib_bucket",
        "device",
        "gpu_family",
        "vram_gib_bucket",
        "driver_version",
    }
