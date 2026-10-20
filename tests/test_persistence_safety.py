import errno
import json
import os
import sqlite3
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path
from types import TracebackType
from uuid import UUID

import pytest

from splatforge.adapters.project_backup import (
    BackupFaultHooks,
    LocalMigrationBackupPreparer,
)
from splatforge.adapters.project_storage import LocalProjectStore, PersistenceFaultHooks
from splatforge.application.projects import (
    ProjectError,
    ProjectService,
    ProjectSharingViolationError,
    ProjectWriterBusyError,
    StaleProjectRevisionError,
)
from splatforge.core import build_builtin_registry


class FakeWriterLease:
    def __init__(
        self,
        path: Path,
        *,
        factory: "FakeLockFactory",
        diagnostics: list[dict[str, object]],
        on_acquire: Callable[[], None] | None = None,
    ) -> None:
        self._path = path
        self._factory = factory
        self._diagnostics = diagnostics
        self._on_acquire = on_acquire
        self.created = not path.exists()

    def __enter__(self) -> "FakeWriterLease":
        self._factory.acquire()
        try:
            if self.created:
                self._path.touch()
            if self._on_acquire is not None:
                callback = self._on_acquire
                self._on_acquire = None
                callback()
        except BaseException:
            self._factory.release()
            raise
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self._factory.release()

    def write_diagnostics(self, *, operation: str, owner_token: UUID) -> None:
        self._diagnostics.append({"operation": operation, "owner_token": owner_token})


class FakeLockFactory:
    def __init__(
        self, *, on_acquire: Callable[[], None] | None = None, busy: bool = False
    ) -> None:
        self.diagnostics: list[dict[str, object]] = []
        self._on_acquire = on_acquire
        self._busy = busy
        self._held = False

    def acquire(self) -> None:
        if self._busy or self._held:
            raise ProjectWriterBusyError("Fake writer is busy")
        self._held = True

    def release(self) -> None:
        self._held = False

    def __call__(self, path: Path) -> FakeWriterLease:
        callback = self._on_acquire
        self._on_acquire = None
        return FakeWriterLease(
            path,
            factory=self,
            diagnostics=self.diagnostics,
            on_acquire=callback,
        )


def make_service(
    *,
    lock_factory: FakeLockFactory | None = None,
    replace_file=os.replace,
    fault_hooks: PersistenceFaultHooks | None = None,
) -> tuple[ProjectService, LocalProjectStore, FakeLockFactory]:
    lock_factory = lock_factory or FakeLockFactory()
    store = LocalProjectStore(
        lock_factory=lock_factory,
        replace_file=replace_file,
        fault_hooks=fault_hooks,
    )
    return ProjectService(store, build_builtin_registry()), store, lock_factory


def authoritative_bytes(root: Path) -> tuple[bytes, bytes]:
    return (root / "project.json").read_bytes(), (root / "state.sqlite").read_bytes()


def test_save_advances_revision_and_refuses_stale_document(tmp_path: Path) -> None:
    service, _, locks = make_service()
    created = service.create(tmp_path, "Revision")
    first = service.open(tmp_path)
    second = service.open(tmp_path)

    first.label = "First writer"
    saved = service.save(tmp_path, first)

    assert created.revision == 0
    assert first.revision == 0
    assert saved.revision == 1
    assert service.open(tmp_path) == saved

    second.label = "Stale writer"
    with pytest.raises(StaleProjectRevisionError, match="expected 0, committed 1"):
        service.save(tmp_path, second)

    assert service.open(tmp_path) == saved
    assert [entry["operation"] for entry in locks.diagnostics] == ["create", "save"]


def test_save_refuses_changed_creation_time_without_authoritative_writes(
    tmp_path: Path,
) -> None:
    service, _, locks = make_service()
    opened = service.create(tmp_path, "Immutable creation time")
    before = authoritative_bytes(tmp_path)
    opened.created_at += timedelta(seconds=1)

    with pytest.raises(ProjectError, match="Cannot change project created_at"):
        service.save(tmp_path, opened)

    assert authoritative_bytes(tmp_path) == before
    assert [entry["operation"] for entry in locks.diagnostics] == ["create"]
    assert not list(tmp_path.glob(".project-*.tmp"))


def test_storage_rejects_contradictory_revision_pair_before_io(tmp_path: Path) -> None:
    service, store, locks = make_service()
    created = service.create(tmp_path, "Revision contract")
    candidate = created.model_copy(update={"revision": 2})
    before = authoritative_bytes(tmp_path)

    with pytest.raises(ProjectError, match=r"expected_revision \+ 1"):
        store.save(tmp_path, candidate, expected_revision=0)

    assert authoritative_bytes(tmp_path) == before
    assert [entry["operation"] for entry in locks.diagnostics] == ["create"]


@pytest.mark.parametrize(
    "version_field",
    ["project_format_version", "config_schema_version", "state_schema_version"],
)
def test_versions_are_rechecked_after_writer_lock_before_diagnostics(
    tmp_path: Path, version_field: str
) -> None:
    setup, _, _ = make_service()
    opened = setup.create(tmp_path, "Version race")
    path = tmp_path / "project.json"

    def publish_newer_version() -> None:
        if version_field == "state_schema_version":
            with sqlite3.connect(tmp_path / "state.sqlite") as connection:
                connection.execute(
                    "UPDATE metadata SET value='2' WHERE key='state_schema_version'"
                )
            return
        raw = json.loads(path.read_text(encoding="utf-8"))
        target = raw["settings"] if version_field == "config_schema_version" else raw
        target[version_field] = 2
        path.write_text(json.dumps(raw), encoding="utf-8")

    locks = FakeLockFactory(on_acquire=publish_newer_version)
    racing, _, _ = make_service(lock_factory=locks)
    opened.label = "Must not commit"

    with pytest.raises(ProjectError, match="Unsupported newer"):
        racing.save(tmp_path, opened)

    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["label"] == "Version race"
    assert locks.diagnostics == []
    assert not list(tmp_path.glob(".project-*.tmp"))


def test_revision_is_rechecked_after_writer_lock_before_diagnostics(tmp_path: Path) -> None:
    setup, _, _ = make_service()
    opened = setup.create(tmp_path, "Revision race")
    path = tmp_path / "project.json"

    def publish_other_revision() -> None:
        raw = json.loads(path.read_text(encoding="utf-8"))
        raw["revision"] = 1
        raw["label"] = "Other writer"
        path.write_text(json.dumps(raw), encoding="utf-8")

    locks = FakeLockFactory(on_acquire=publish_other_revision)
    racing, _, _ = make_service(lock_factory=locks)
    opened.label = "Must not commit"

    with pytest.raises(StaleProjectRevisionError, match="expected 0, committed 1"):
        racing.save(tmp_path, opened)

    assert json.loads(path.read_text(encoding="utf-8"))["label"] == "Other writer"
    assert locks.diagnostics == []
    assert not list(tmp_path.glob(".project-*.tmp"))


def test_busy_writer_is_refused_without_authoritative_changes(tmp_path: Path) -> None:
    setup, _, _ = make_service()
    opened = setup.create(tmp_path, "Busy")
    before = authoritative_bytes(tmp_path)
    busy, _, _ = make_service(lock_factory=FakeLockFactory(busy=True))
    opened.label = "Must not commit"

    with pytest.raises(ProjectWriterBusyError):
        busy.save(tmp_path, opened)

    assert authoritative_bytes(tmp_path) == before
    assert not list(tmp_path.glob(".project-*.tmp"))


def test_create_rechecks_empty_destination_after_owned_lock_creation(
    tmp_path: Path,
) -> None:
    root = tmp_path / "create race"

    def concurrent_destination_change() -> None:
        (root / "unrelated.txt").write_text("not owned", encoding="utf-8")

    locks = FakeLockFactory(on_acquire=concurrent_destination_change)
    service, _, _ = make_service(lock_factory=locks)

    with pytest.raises(ProjectError, match="changed while acquiring writer lock"):
        service.create(root, "Must not create")

    assert (root / "unrelated.txt").read_text(encoding="utf-8") == "not owned"
    assert (root / "project.lock").exists()
    assert not (root / "project.json").exists()
    assert not (root / "state.sqlite").exists()
    assert locks.diagnostics == []


@pytest.mark.parametrize("boundary", ["write", "before_replace"])
def test_failure_before_replace_preserves_prior_document(
    tmp_path: Path, boundary: str
) -> None:
    setup, _, _ = make_service()
    opened = setup.create(tmp_path, "Previous")
    before = authoritative_bytes(tmp_path)

    def fail(_path: Path) -> None:
        if boundary == "write":
            raise OSError(errno.ENOSPC, "No space left")
        raise RuntimeError("Injected interruption before replace")

    hooks = PersistenceFaultHooks(
        after_temporary_write=fail if boundary == "write" else lambda _path: None,
        before_replace=fail if boundary == "before_replace" else lambda _path: None,
    )
    failing, _, _ = make_service(fault_hooks=hooks)
    opened.label = "Candidate"

    with pytest.raises((ProjectError, RuntimeError)):
        failing.save(tmp_path, opened)

    assert authoritative_bytes(tmp_path) == before
    assert setup.open(tmp_path).label == "Previous"
    assert not list(tmp_path.glob(".project-*.tmp"))


class InjectedSharingViolation(OSError):
    @property
    def winerror(self) -> int:
        return 32


def test_sharing_violation_preserves_prior_document(tmp_path: Path) -> None:
    setup, _, _ = make_service()
    opened = setup.create(tmp_path, "Previous")
    before = authoritative_bytes(tmp_path)

    def sharing_violation(_source: Path, _target: Path) -> None:
        raise InjectedSharingViolation(errno.EACCES, "File is in use")

    failing, _, _ = make_service(replace_file=sharing_violation)
    opened.label = "Candidate"

    with pytest.raises(ProjectSharingViolationError):
        failing.save(tmp_path, opened)

    assert authoritative_bytes(tmp_path) == before
    assert setup.open(tmp_path).label == "Previous"


def test_reopen_resolves_caller_failure_at_replace_commit_point(tmp_path: Path) -> None:
    setup, _, _ = make_service()
    opened = setup.create(tmp_path, "Previous")

    def commit_then_report_failure(source: Path, target: Path) -> None:
        os.replace(source, target)
        raise OSError("Injected caller-side loss after commit point")

    uncertain, _, _ = make_service(replace_file=commit_then_report_failure)
    opened.label = "Committed"

    with pytest.raises(ProjectError):
        uncertain.save(tmp_path, opened)

    committed = setup.open(tmp_path)
    assert committed.label == "Committed"
    assert committed.revision == 1
    with pytest.raises(StaleProjectRevisionError):
        setup.save(tmp_path, opened)


def test_migration_backup_copies_referenced_inputs_and_sqlite(tmp_path: Path) -> None:
    service, store, locks = make_service()
    document = service.create(tmp_path, "Backup")
    inventory = tmp_path / "sources" / "inventory.jsonl"
    inventory.parent.mkdir()
    inventory.write_text('{"source_id":"one"}\n', encoding="utf-8")
    document.inventory_reference = "sources/inventory.jsonl"
    saved = service.save(tmp_path, document)
    assert not (tmp_path / "backups").exists()

    prepared = LocalMigrationBackupPreparer(
        store=store, lock_factory=locks
    ).prepare(tmp_path, "future-step")

    assert prepared.project_id == saved.project_id
    assert prepared.revision == saved.revision
    assert store.load(prepared.root) == saved
    assert (prepared.root / "sources" / "inventory.jsonl").read_bytes() == inventory.read_bytes()
    assert [entry["operation"] for entry in locks.diagnostics] == [
        "create",
        "save",
        "migration-backup",
    ]


def test_migration_backup_excludes_competing_writer_until_publication(
    tmp_path: Path,
) -> None:
    service, store, locks = make_service()
    original = service.create(tmp_path, "Backup lock")
    candidate = service.open(tmp_path)
    candidate.label = "Competing writer"
    attempted = False

    def attempt_competing_save(_staging: Path) -> None:
        nonlocal attempted
        attempted = True
        with pytest.raises(ProjectWriterBusyError):
            service.save(tmp_path, candidate)

    prepared = LocalMigrationBackupPreparer(
        store=store,
        lock_factory=locks,
        fault_hooks=BackupFaultHooks(before_publish=attempt_competing_save),
    ).prepare(tmp_path, "locked-snapshot")

    assert attempted
    assert service.open(tmp_path) == original
    assert store.load(prepared.root) == original
    assert [entry["operation"] for entry in locks.diagnostics] == [
        "create",
        "migration-backup",
    ]


@pytest.mark.parametrize(
    "backup_id",
    [
        "",
        ".",
        "..",
        "C:drive",
        "name:stream",
        "nested/path",
        "nested\\path",
        "CON",
        "con.txt",
        "COM9.backup",
        "LPT1",
        "trailing.",
        "trailing ",
        "bad?name",
    ],
)
def test_migration_backup_rejects_ambiguous_windows_names(
    tmp_path: Path, backup_id: str
) -> None:
    service, store, locks = make_service()
    service.create(tmp_path, "Backup ID")
    before = authoritative_bytes(tmp_path)

    with pytest.raises(ProjectError, match="Invalid migration backup ID"):
        LocalMigrationBackupPreparer(store=store, lock_factory=locks).prepare(
            tmp_path, backup_id
        )

    assert authoritative_bytes(tmp_path) == before
    assert not (tmp_path / "backups").exists()
    assert [entry["operation"] for entry in locks.diagnostics] == ["create"]


def test_migration_backup_rejects_redirected_backups_root(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    outside = tmp_path / "outside"
    outside.mkdir()
    service, store, locks = make_service()
    service.create(project_root, "Redirected backup root")
    before = authoritative_bytes(project_root)
    try:
        (project_root / "backups").symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"Directory symlinks are unavailable: {exc}")

    with pytest.raises(ProjectError, match="filesystem redirection"):
        LocalMigrationBackupPreparer(store=store, lock_factory=locks).prepare(
            project_root, "must-not-escape"
        )

    assert authoritative_bytes(project_root) == before
    assert list(outside.iterdir()) == []
    assert [entry["operation"] for entry in locks.diagnostics] == ["create"]


@pytest.mark.parametrize(
    "boundary",
    ["after_project_copy", "before_sqlite_backup", "before_publish"],
)
def test_failed_backup_preparation_does_not_mutate_authoritative_state(
    tmp_path: Path, boundary: str
) -> None:
    service, store, locks = make_service()
    expected = service.create(tmp_path, "Backup failure")
    before = authoritative_bytes(tmp_path)

    def disk_full(_path: Path) -> None:
        raise OSError(errno.ENOSPC, "No space left during backup")

    preparer = LocalMigrationBackupPreparer(
        store=store,
        lock_factory=locks,
        fault_hooks=BackupFaultHooks(
            after_project_copy=disk_full
            if boundary == "after_project_copy"
            else lambda _path: None,
            before_sqlite_backup=disk_full
            if boundary == "before_sqlite_backup"
            else lambda _path: None,
            before_publish=disk_full if boundary == "before_publish" else lambda _path: None,
        ),
    )

    with pytest.raises(OSError):
        preparer.prepare(tmp_path, "failed-step")

    assert authoritative_bytes(tmp_path) == before
    assert store.load(tmp_path) == expected
    assert not (tmp_path / "backups" / "failed-step").exists()
