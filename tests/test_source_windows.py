import hashlib
import os
import subprocess
import sys
from pathlib import Path

import pytest
from test_media import FakeProbe, FakeSourceFiles

from splatforge.adapters.media_storage import LocalMediaRepository
from splatforge.adapters.project_storage import LocalProjectStore
from splatforge.adapters.source_files import LocalSourceFiles
from splatforge.application.media import MediaService
from splatforge.application.projects import ProjectError
from splatforge.bootstrap import build_project_service

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows source lease semantics")


def test_strict_lease_blocks_write_replace_delete_but_allows_read(tmp_path: Path) -> None:
    source = tmp_path / "strict space žluťoučký.bin"
    replacement = tmp_path / "replacement.bin"
    source.write_bytes(b"protected bytes")
    replacement.write_bytes(b"replacement")
    files = LocalSourceFiles(chunk_size=3)

    with files.lease(source, strict=True) as lease:
        hashed = files.hash_lease(lease)
        read_only = subprocess.run(
            [
                sys.executable,
                "-c",
                "import pathlib,sys;pathlib.Path(sys.argv[1]).read_bytes()",
                source,
            ],
            shell=False,
            check=False,
        )
        writer = subprocess.run(
            [
                sys.executable,
                "-c",
                "import pathlib,sys;pathlib.Path(sys.argv[1]).write_bytes(b'changed')",
                source,
            ],
            shell=False,
            check=False,
            capture_output=True,
        )
        with pytest.raises(OSError):
            os.replace(replacement, source)
        with pytest.raises(OSError):
            source.unlink()

        assert read_only.returncode == 0
        assert writer.returncode != 0
        assert hashed.sha256 == hashlib.sha256(b"protected bytes").hexdigest()
        assert hashed.evidence.evidence_before == hashed.evidence.evidence_after
        assert hashed.evidence.stability_mechanism == "windows_read_lease_no_write_delete"

    source.write_bytes(b"changed after release")
    assert source.read_bytes() == b"changed after release"


def test_project_sources_junction_is_refused(tmp_path: Path) -> None:
    project = tmp_path / "project"
    outside = tmp_path / "outside"
    source = tmp_path / "source.png"
    outside.mkdir()
    source.write_bytes(b"png")
    build_project_service().create(project, "Junction")
    result = subprocess.run(
        ["cmd.exe", "/d", "/c", "mklink", "/J", str(project / "sources"), str(outside)],
        shell=False,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        pytest.skip(f"junction creation unavailable: {result.stderr or result.stdout}")
    store = LocalProjectStore()
    service = MediaService(
        LocalMediaRepository(project_store=store), FakeSourceFiles(), FakeProbe()
    )

    with pytest.raises(ProjectError, match="redirection"):
        service.add(project, [source])

    assert not any(outside.iterdir())
    assert build_project_service().open(project).inventory_reference is None
