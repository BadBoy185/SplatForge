from __future__ import annotations

import hashlib
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from uuid import uuid4

import pytest

from splatforge.adapters.media_storage import (
    LocalMediaRepository,
    MediaStorageFaultHooks,
)
from splatforge.adapters.project_storage import LocalProjectStore
from splatforge.application.media import CallbackCancellation, MediaService
from splatforge.application.media_contracts import (
    ProbeBackendError,
    ProbeCancelledError,
    SourceUnavailableError,
    StrictSourceUnavailableError,
)
from splatforge.application.projects import ProjectError, StaleProjectRevisionError
from splatforge.bootstrap import build_project_service
from splatforge.core.media import (
    ExecutableIdentity,
    FullHashEvidence,
    MediaType,
    NormalizedProbe,
    SourceEvidence,
    StorageKind,
    VerificationAssurance,
    VerificationOutcome,
    VerificationPolicyId,
)


def evidence(
    path: Path,
    *,
    generation: int = 1,
    file_id: str | None = None,
    storage: StorageKind = StorageKind.LOCAL_FIXED,
) -> SourceEvidence:
    return SourceEvidence(
        size=path.stat().st_size,
        last_write_ns=generation,
        volume_id="volume",
        file_id=file_id or f"file-{path.name}",
        change_time_ns=generation,
        storage_kind=storage,
        evidence_available=True,
    )


@dataclass
class FakeHash:
    sha256: str
    evidence: FullHashEvidence


class FakeLease:
    def __init__(self, files: FakeSourceFiles, path: Path, strict: bool) -> None:
        self._files = files
        self.path = path
        self.strict = strict
        self.stream = None
        self.evidence_before = files.evidence(path)
        self.stability_mechanism = (
            "windows_read_lease_no_write_delete" if strict else "fake_stable_read_lease"
        )

    def __enter__(self) -> FakeLease:
        if self.strict and not self._files.strict_supported:
            raise StrictSourceUnavailableError("strict lease is unavailable")
        return self

    def current_evidence(self) -> SourceEvidence:
        return self._files.evidence(self.path)

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None


class FakeSourceFiles:
    def __init__(self) -> None:
        self.overrides: dict[Path, SourceEvidence] = {}
        self.failures: dict[Path, SourceUnavailableError] = {}
        self.hash_reads = 0
        self.strict_supported = True

    def evidence(self, path: Path) -> SourceEvidence:
        path = path.absolute()
        if path in self.failures:
            raise self.failures[path]
        if not path.is_file():
            raise SourceUnavailableError(f"missing source: {path}", missing=True)
        return self.overrides.get(path, evidence(path))

    def lease(self, path: Path, *, strict: bool = False) -> FakeLease:
        return FakeLease(self, path.absolute(), strict)

    def hash_lease(self, lease: FakeLease, control=None) -> FakeHash:  # type: ignore[no-untyped-def]
        if control is not None:
            control.checkpoint()
        self.hash_reads += 1
        data = lease.path.read_bytes()
        observed = lease.current_evidence()
        from datetime import UTC, datetime

        return FakeHash(
            hashlib.sha256(data).hexdigest(),
            FullHashEvidence(
                hashed_at=datetime.now(UTC),
                byte_count=len(data),
                evidence_before=observed,
                evidence_after=observed,
                stability_mechanism=lease.stability_mechanism,
            ),
        )


class FakeProbe:
    def __init__(self) -> None:
        self.failure: Exception | None = None

    def probe(self, path: Path, media_type: MediaType, *, cancellation=None) -> NormalizedProbe:  # type: ignore[no-untyped-def]
        if self.failure is not None:
            raise self.failure
        return NormalizedProbe(
            backend=ExecutableIdentity(
                resolved_path="C:/tools/ffprobe.exe",
                size=10,
                last_write_ns=1,
                sha256="a" * 64,
                version_line="ffprobe test",
            ),
            selected_visual_stream_index=0,
            codec_name="h264" if media_type == MediaType.VIDEO else "png",
            width=16,
            height=12,
            time_base="1/90000" if media_type == MediaType.VIDEO else None,
        )


def media_service(
    root: Path,
    *,
    files: FakeSourceFiles | None = None,
    probe: FakeProbe | None = None,
    hooks: MediaStorageFaultHooks | None = None,
) -> tuple[MediaService, FakeSourceFiles, FakeProbe]:
    store = LocalProjectStore()
    repository = LocalMediaRepository(project_store=store, fault_hooks=hooks)
    source_files = files or FakeSourceFiles()
    fake_probe = probe or FakeProbe()
    return MediaService(repository, source_files, fake_probe), source_files, fake_probe


def test_empty_project_and_two_immutable_inventory_revisions(tmp_path: Path) -> None:
    project = tmp_path / "project"
    first = tmp_path / "one" / "same.png"
    second = tmp_path / "two" / "same.png"
    first.parent.mkdir()
    second.parent.mkdir()
    first.write_bytes(b"identical")
    second.write_bytes(b"identical")
    original = first.read_bytes()
    build_project_service().create(project, "Media")
    service, _, _ = media_service(project)

    assert service.list(project) is None
    added_first = service.add(project, [first])
    first_reference = project / added_first.inventory_reference
    first_bytes = first_reference.read_bytes()
    added_second = service.add(project, [second])
    inventory = service.list(project)

    assert added_first.inventory_revision == 1
    assert added_second.inventory_revision == 2
    assert first_reference.read_bytes() == first_bytes
    assert inventory is not None and len(inventory.sources) == 2
    assert inventory.sources[0].source_id != inventory.sources[1].source_id
    assert inventory.sources[0].display_filename == inventory.sources[1].display_filename
    assert inventory.sources[0].content_sha256 == inventory.sources[1].content_sha256
    assert inventory.sources[0].source_group_id != inventory.sources[0].camera_group_id
    assert inventory.sources[0].source_group_id != inventory.sources[1].source_group_id
    assert first.read_bytes() == original
    assert not any(path.suffix == ".png" for path in project.rglob("*"))


def test_explicit_groups_are_preserved_and_source_ids_are_occurrences(tmp_path: Path) -> None:
    project = tmp_path / "project"
    source_a = tmp_path / "a.jpg"
    source_b = tmp_path / "b.jpg"
    source_a.write_bytes(b"same")
    source_b.write_bytes(b"same")
    build_project_service().create(project, "Groups")
    service, _, _ = media_service(project)
    source_group = uuid4()
    camera_group = uuid4()

    service.add(
        project,
        [source_a, source_b],
        source_group_id=source_group,
        camera_group_id=camera_group,
    )
    inventory = service.list(project)

    assert inventory is not None
    assert {item.source_group_id for item in inventory.sources} == {source_group}
    assert {item.camera_group_id for item in inventory.sources} == {camera_group}
    assert len({item.source_id for item in inventory.sources}) == 2


@pytest.mark.parametrize("name", ["missing.png", "unsupported.txt"])
def test_invalid_input_refuses_before_commit(tmp_path: Path, name: str) -> None:
    project = tmp_path / "project"
    source = tmp_path / name
    if source.suffix == ".txt":
        source.write_text("unsupported", encoding="utf-8")
    build_project_service().create(project, "Invalid")
    before = (project / "project.json").read_bytes()
    service, _, _ = media_service(project)

    with pytest.raises(ValueError):
        service.add(project, [source])

    assert (project / "project.json").read_bytes() == before
    assert not (project / "sources").exists()


@pytest.mark.parametrize(
    "failure",
    [ProbeBackendError("probe failed"), ProbeCancelledError("probe cancelled")],
)
def test_failed_or_cancelled_probe_leaves_inventory_uncommitted(
    tmp_path: Path, failure: Exception
) -> None:
    project = tmp_path / "project"
    source = tmp_path / "photo.png"
    source.write_bytes(b"png")
    build_project_service().create(project, "Probe failure")
    probe = FakeProbe()
    probe.failure = failure
    service, _, _ = media_service(project, probe=probe)
    before = (project / "project.json").read_bytes()

    with pytest.raises(type(failure)):
        service.add(project, [source])

    assert (project / "project.json").read_bytes() == before
    assert service.list(project) is None


def test_cancelled_hash_leaves_inventory_uncommitted(tmp_path: Path) -> None:
    project = tmp_path / "project"
    source = tmp_path / "photo.png"
    source.write_bytes(b"png")
    build_project_service().create(project, "Cancelled hash")
    service, _, _ = media_service(project)
    before = (project / "project.json").read_bytes()

    with pytest.raises(ProjectError, match="cancelled"):
        service.add(project, [source], cancellation=CallbackCancellation(lambda: True))

    assert (project / "project.json").read_bytes() == before
    assert service.list(project) is None


def test_stale_commit_refuses_without_inventory_publication(tmp_path: Path) -> None:
    project = tmp_path / "project"
    source = tmp_path / "photo.png"
    source.write_bytes(b"png")
    project_service = build_project_service()
    project_service.create(project, "Stale")
    store = LocalProjectStore()

    class RacingRepository(LocalMediaRepository):
        def commit_inventory(self, root, **kwargs):  # type: ignore[no-untyped-def]
            current = project_service.open(root)
            current.label = "Competing save"
            project_service.save(root, current)
            return super().commit_inventory(root, **kwargs)

    service = MediaService(RacingRepository(project_store=store), FakeSourceFiles(), FakeProbe())

    with pytest.raises(StaleProjectRevisionError):
        service.add(project, [source])

    assert project_service.open(project).inventory_reference is None
    assert not (project / "sources").exists()


def test_failure_after_inventory_publish_leaves_unreferenced_inventory(tmp_path: Path) -> None:
    project = tmp_path / "project"
    source = tmp_path / "photo.png"
    source.write_bytes(b"png")
    created = build_project_service().create(project, "Publication failure")

    def fail(_path: Path) -> None:
        raise RuntimeError("replace fault")

    service, _, _ = media_service(
        project, hooks=MediaStorageFaultHooks(after_inventory_publish=fail)
    )

    with pytest.raises(RuntimeError, match="replace fault"):
        service.add(project, [source])

    reopened = build_project_service().open(project)
    assert reopened.revision == created.revision
    assert reopened.inventory_reference is None
    assert len(list((project / "sources").glob("*.jsonl"))) == 1


def test_unicode_and_space_paths(tmp_path: Path) -> None:
    project = tmp_path / "Příliš project"
    source = tmp_path / "média space" / "žluťoučký.png"
    source.parent.mkdir()
    source.write_bytes(b"unicode")
    build_project_service().create(project, "Unicode")
    service, _, _ = media_service(project)

    service.add(project, [source])
    inventory = service.list(project)

    assert inventory is not None
    assert inventory.sources[0].external_locator == str(source.absolute())
    assert inventory.sources[0].display_filename == source.name


def test_balanced_unchanged_uses_zero_hash_reads_and_does_not_mutate_project(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    source = tmp_path / "photo.png"
    source.write_bytes(b"unchanged")
    build_project_service().create(project, "Verify")
    service, files, _ = media_service(project)
    service.add(project, [source])
    files.hash_reads = 0
    before = (project / "project.json").read_bytes()

    result = service.verify(project)[0]

    assert result.outcome == VerificationOutcome.UNCHANGED
    assert result.assurance == VerificationAssurance.METADATA_UNCHANGED
    assert result.full_hash_performed is False
    assert files.hash_reads == 0
    assert (project / "project.json").read_bytes() == before


def test_balanced_rehash_updates_durable_baseline_without_inventory_revision(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    source = tmp_path / "photo.png"
    source.write_bytes(b"same content")
    build_project_service().create(project, "Baseline")
    service, files, _ = media_service(project)
    added = service.add(project, [source])
    files.overrides[source.absolute()] = evidence(source, generation=2)
    before = (project / "project.json").read_bytes()

    rehashed = service.verify(project)[0]
    files.hash_reads = 0
    next_result = service.verify(project)[0]

    assert rehashed.full_hash_performed is True
    assert rehashed.assurance == VerificationAssurance.CONTENT_VERIFIED
    assert next_result.assurance == VerificationAssurance.METADATA_UNCHANGED
    assert files.hash_reads == 0
    assert (project / "project.json").read_bytes() == before
    assert build_project_service().open(project).revision == added.project_revision
    with closing(sqlite3.connect(project / "state.sqlite")) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM source_verifications WHERE full_hash_performed=1"
        ).fetchone() == (1,)


@pytest.mark.parametrize(
    ("storage", "file_id"),
    [(StorageKind.LOCAL_FIXED, "replacement"), (StorageKind.NETWORK, "network")],
)
def test_identity_change_or_untrusted_storage_forces_rehash(
    tmp_path: Path, storage: StorageKind, file_id: str
) -> None:
    project = tmp_path / f"project-{storage.value}"
    source = tmp_path / f"{storage.value}.png"
    source.write_bytes(b"same")
    build_project_service().create(project, "Evidence")
    service, files, _ = media_service(project)
    service.add(project, [source])
    files.hash_reads = 0
    files.overrides[source.absolute()] = evidence(
        source, generation=2, file_id=file_id, storage=storage
    )

    result = service.verify(project)[0]

    assert result.full_hash_performed is True
    assert files.hash_reads == 1


def test_changed_missing_and_metadata_failure_are_explicit(tmp_path: Path) -> None:
    project = tmp_path / "project"
    source = tmp_path / "photo.png"
    source.write_bytes(b"original")
    build_project_service().create(project, "Diagnostics")
    service, files, _ = media_service(project)
    service.add(project, [source])
    source.write_bytes(b"changed bytes")
    files.overrides[source.absolute()] = evidence(source, generation=3)

    changed = service.verify(project)[0]
    source.unlink()
    missing = service.verify(project)[0]

    assert changed.outcome == VerificationOutcome.CHANGED
    assert changed.observed_content_sha256 != changed.expected_content_sha256
    assert missing.outcome == VerificationOutcome.MISSING
    assert missing.assurance == VerificationAssurance.UNAVAILABLE


def test_metadata_access_failure_is_unavailable_not_unchanged(tmp_path: Path) -> None:
    project = tmp_path / "project"
    source = tmp_path / "photo.png"
    source.write_bytes(b"original")
    build_project_service().create(project, "Metadata failure")
    service, files, _ = media_service(project)
    service.add(project, [source])
    files.hash_reads = 0
    files.failures[source.absolute()] = SourceUnavailableError(
        "metadata access denied", missing=False
    )

    result = service.verify(project)[0]

    assert result.outcome == VerificationOutcome.UNAVAILABLE
    assert result.assurance == VerificationAssurance.UNAVAILABLE
    assert result.full_hash_performed is False
    assert files.hash_reads == 0


def test_strict_always_hashes_and_never_falls_back(tmp_path: Path) -> None:
    project = tmp_path / "project"
    source = tmp_path / "photo.png"
    source.write_bytes(b"strict")
    build_project_service().create(project, "Strict")
    service, files, _ = media_service(project)
    service.add(project, [source])
    files.hash_reads = 0

    verified = service.verify(project, policy=VerificationPolicyId.STRICT)[0]
    files.strict_supported = False
    unavailable = service.verify(project, policy=VerificationPolicyId.STRICT)[0]

    assert verified.full_hash_performed is True
    assert verified.assurance == VerificationAssurance.CONTENT_VERIFIED
    assert verified.stability_mechanism == "windows_read_lease_no_write_delete"
    assert unavailable.outcome == VerificationOutcome.STRICT_UNAVAILABLE
    assert unavailable.full_hash_performed is False
    assert files.hash_reads == 1


def test_relink_missing_source_preserves_identity_and_rejects_different_bytes(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    source = tmp_path / "old.png"
    same = tmp_path / "new.png"
    different = tmp_path / "different.png"
    source.write_bytes(b"identity")
    same.write_bytes(b"identity")
    different.write_bytes(b"different")
    build_project_service().create(project, "Relink")
    service, _, _ = media_service(project)
    service.add(project, [source])
    original = service.list(project).sources[0]  # type: ignore[union-attr]
    source.unlink()

    relinked = service.relink(project, original.source_id, same)
    current = service.list(project).sources[0]  # type: ignore[union-attr]
    project_before = (project / "project.json").read_bytes()
    with pytest.raises(ProjectError, match="different content"):
        service.relink(project, original.source_id, different)

    assert relinked.inventory_revision == 2
    assert relinked.project_revision == 2
    assert current.source_id == original.source_id
    assert current.source_revision == original.source_revision
    assert current.source_group_id == original.source_group_id
    assert current.camera_group_id == original.camera_group_id
    assert current.probe == original.probe
    assert current.external_locator == str(same.absolute())
    assert (project / "project.json").read_bytes() == project_before


def test_media_mutation_requires_explicit_v4_upgrade(tmp_path: Path) -> None:
    project = tmp_path / "project"
    source = tmp_path / "photo.png"
    source.write_bytes(b"photo")
    build_project_service().create(project, "Historical")
    with closing(sqlite3.connect(project / "state.sqlite")) as connection, connection:
        connection.execute("DROP TABLE source_verifications")
        connection.execute("UPDATE metadata SET value='3' WHERE key='state_schema_version'")
    service, files, _ = media_service(project)

    with pytest.raises(ProjectError, match="upgrade-state"):
        service.add(project, [source])

    assert files.hash_reads == 0
