from __future__ import annotations

import ctypes
import json
import multiprocessing
import os
import subprocess
from ctypes import wintypes
from multiprocessing.connection import Connection
from pathlib import Path
from uuid import uuid4

import pytest

from splatforge.adapters.project_backup import LocalMigrationBackupPreparer
from splatforge.adapters.project_lock import WindowsProjectWriterLock
from splatforge.application.projects import (
    ProjectError,
    ProjectSharingViolationError,
    ProjectWriterBusyError,
)
from splatforge.bootstrap import build_project_service

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows local-file semantics")


def test_windows_writer_lock_refuses_second_same_process_handle(tmp_path: Path) -> None:
    lock_path = tmp_path / "project.lock"

    with WindowsProjectWriterLock(lock_path) as lease:
        lease.write_diagnostics(operation="test", owner_token=uuid4())
        with pytest.raises(ProjectWriterBusyError), WindowsProjectWriterLock(lock_path):
            pass

    assert json.loads(lock_path.read_text(encoding="utf-8"))["diagnostic_only"] is True


def _hold_writer_lock(
    lock_path: str,
    release: multiprocessing.synchronize.Event,
    status: Connection,
) -> None:
    try:
        with WindowsProjectWriterLock(Path(lock_path)):
            status.send(None)
            if not release.wait(15):
                raise RuntimeError("Parent did not release Windows lock test worker")
    except BaseException as exc:
        status.send(repr(exc))
        raise
    finally:
        status.close()


def test_windows_writer_exclusion_allows_read_only_inspection(tmp_path: Path) -> None:
    root = tmp_path / "Windows lock project"
    service = build_project_service()
    original = service.create(root, "Committed")
    lock_path = root / "project.lock"
    lock_identity = lock_path.stat().st_ino
    lock_path.write_text('{"claims_ownership":true}\n', encoding="utf-8")

    context = multiprocessing.get_context("spawn")
    release = context.Event()
    parent_status, child_status = context.Pipe(duplex=False)
    process = context.Process(
        target=_hold_writer_lock,
        args=(str(lock_path), release, child_status),
    )
    process.start()
    child_status.close()
    assert parent_status.poll(15), "Windows lock worker did not report readiness"
    worker_error = parent_status.recv()
    try:
        assert worker_error is None

        assert service.open(root) == original
        candidate = service.open(root)
        candidate.label = "Blocked writer"
        before = (root / "project.json").read_bytes()
        with pytest.raises(ProjectWriterBusyError):
            service.save(root, candidate)
        assert (root / "project.json").read_bytes() == before
    finally:
        parent_status.close()
        release.set()
        process.join(15)
        if process.is_alive():
            process.terminate()
            process.join(15)

    assert process.exitcode == 0
    assert lock_path.stat().st_ino == lock_identity
    candidate = service.open(root)
    candidate.label = "Committed after release"
    saved = service.save(root, candidate)
    assert saved.revision == 1
    assert lock_path.stat().st_ino == lock_identity


def test_windows_sharing_violation_preserves_project_json(tmp_path: Path) -> None:
    root = tmp_path / "Windows sharing project"
    service = build_project_service()
    candidate = service.create(root, "Previous")
    target = root / "project.json"
    before = target.read_bytes()

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_file = kernel32.CreateFileW
    create_file.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    create_file.restype = wintypes.HANDLE
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [wintypes.HANDLE]
    close_handle.restype = wintypes.BOOL

    generic_read = 0x80000000
    file_share_read_write = 0x00000001 | 0x00000002
    open_existing = 3
    file_attribute_normal = 0x00000080
    handle = create_file(
        str(target),
        generic_read,
        file_share_read_write,
        None,
        open_existing,
        file_attribute_normal,
        None,
    )
    invalid_handle = ctypes.c_void_p(-1).value
    assert handle != invalid_handle, ctypes.WinError(ctypes.get_last_error())
    try:
        candidate.label = "Must not replace"
        with pytest.raises(ProjectSharingViolationError):
            service.save(root, candidate)
    finally:
        assert close_handle(handle)

    assert target.read_bytes() == before
    assert service.open(root).label == "Previous"
    assert not list(root.glob(".project-*.tmp"))


def test_windows_migration_backup_rejects_junction_root(tmp_path: Path) -> None:
    root = tmp_path / "Junction backup project"
    outside = tmp_path / "outside"
    service = build_project_service()
    service.create(root, "Junction backup")
    outside.mkdir()
    subprocess.run(
        [
            "cmd.exe",
            "/d",
            "/c",
            "mklink",
            "/J",
            str(root / "backups"),
            str(outside),
        ],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    assert (root / "backups").is_junction()
    before = (root / "project.json").read_bytes(), (root / "state.sqlite").read_bytes()

    with pytest.raises(ProjectError, match="filesystem redirection"):
        LocalMigrationBackupPreparer().prepare(root, "must-not-escape")

    assert ((root / "project.json").read_bytes(), (root / "state.sqlite").read_bytes()) == before
    assert list(outside.iterdir()) == []
