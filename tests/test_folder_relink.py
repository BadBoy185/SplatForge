"""Folder relocation verifies exact content and publishes one complete generation."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from uuid import uuid4

import pytest
from test_media import FakeProbe

from splatforge.adapters.media_storage import LocalMediaRepository, MediaStorageFaultHooks
from splatforge.adapters.relink_paths import LocalRelinkPathGuard
from splatforge.adapters.source_files import LocalSourceFiles
from splatforge.application.media import CallbackCancellation, MediaOperationCancelled, MediaService
from splatforge.application.media_contracts import SourceReadLease, SourceUnstableError
from splatforge.application.media_relink import FolderRelinkProgress, FolderRelinkService
from splatforge.application.projects import ProjectError, StaleProjectRevisionError
from splatforge.bootstrap import (
    build_folder_relink_service,
    build_gui_facade,
    build_project_service,
)
from splatforge.core.capture_metadata import CaptureMetadata
from splatforge.core.logical_source_groups import LogicalSourceGroup, LogicalSourceGroups
from splatforge.core.media import SourceInventory
from splatforge.core.source_participation import SourceParticipationIntent
from splatforge.core.video_usage import VideoUsageEntry, VideoUsageIntent, interval
from splatforge.core.views import (
    CandidateEncodingSettings,
    CandidatePoolSettings,
    candidate_recipe_key,
    parse_fps,
)


class CountingFiles(LocalSourceFiles):
    def __init__(self) -> None:
        super().__init__(chunk_size=3)
        self.active = 0
        self.hash_reads = 0
        self.after_hash: Callable[[], None] | None = None

    @contextmanager
    def lease(self, path: Path, *, strict: bool = False) -> Iterator[SourceReadLease]:
        with super().lease(path, strict=strict) as lease:
            self.active += 1
            try:
                yield lease
            finally:
                self.active -= 1

    def hash_lease(self, lease, control=None):
        self.hash_reads += 1
        result = super().hash_lease(lease, control)
        if self.after_hash is not None:
            self.after_hash()
        return result


class CaptureProbe(FakeProbe):
    def probe(self, path, media_type, *, cancellation=None):
        result = super().probe(path, media_type, cancellation=cancellation)
        return result.model_copy(
            update={
                "capture": CaptureMetadata(origin="container_tags", make="Test", model="Camera")
            }
        )


@dataclass
class Scenario:
    root: Path
    old: Path
    new: Path
    media: MediaService
    files: CountingFiles
    inventory: SourceInventory

    def service(self, repository=None) -> FolderRelinkService:
        return FolderRelinkService(
            repository or LocalMediaRepository(),
            self.files,
            LocalRelinkPathGuard(),
        )


@pytest.fixture
def scenario(tmp_path: Path) -> Scenario:
    root = tmp_path / "project"
    old = tmp_path / "old media"
    new = tmp_path / "nová média"
    paths = []
    for relative, content in (("foto/žluťoučký.png", b"photo bytes"), ("video/clip.mov", b"video")):
        for folder in (old, new):
            path = folder / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        paths.append(old / relative)
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"outside")
    build_project_service().create(root, "Relink fixture")
    files = CountingFiles()
    media = MediaService(LocalMediaRepository(), files, CaptureProbe())
    media.add(root, [*paths, paths[0], outside])
    inventory = media.list(root)
    assert inventory is not None
    return Scenario(root, old, new, media, files, inventory)


def snapshot(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()
    }


def test_preview_readonly_releases_leases_and_apply_preserves_identity_intent_and_recipe(
    scenario: Scenario,
) -> None:
    s = scenario
    projects = build_project_service()
    document = projects.open(s.root)
    photo, video = s.inventory.sources[:2]
    group = LogicalSourceGroup(group_id=uuid4(), label="My logical group")
    document.logical_source_groups = LogicalSourceGroups(
        groups=(group,),
        source_assignments={photo.source_id: group.group_id},
    )
    document.source_participation = SourceParticipationIntent(
        excluded_source_ids=(photo.source_id,)
    )
    document.video_usage = VideoUsageIntent(
        entries=(
            VideoUsageEntry(
                source_id=video.source_id,
                content_sha256=video.content_sha256,
                stream_index=0,
                intervals=(interval("0", "1/2"),),
            ),
        )
    )
    before_document = projects.save(s.root, document)
    history = s.root / "artifacts" / "historical.txt"
    history.parent.mkdir(exist_ok=True)
    history.write_bytes(b"immutable historical artifact")
    before_project = snapshot(s.root)
    before_sources = snapshot(s.old)
    before_new = snapshot(s.new)
    progress: list[FolderRelinkProgress] = []
    service = s.service()
    preview = service.preview(s.root, s.old, s.new, progress=progress.append)

    assert preview.total == preview.matched == 3 and preview.can_apply
    assert preview.entries[0].relative_path == "foto/žluťoučký.png"
    assert s.files.active == 0
    assert snapshot(s.root) == before_project
    assert {item.total for item in progress} == {3}
    assert progress[-1].completed == 3 and progress[-1].phase == "succeeded"
    hashes_before_apply = s.files.hash_reads
    result = service.apply(s.root, preview)
    assert s.files.hash_reads == hashes_before_apply + 2  # repeated occurrences share a read lease
    assert s.files.active == 0
    current = s.media.list(s.root)
    assert current is not None
    assert result.inventory_revision == s.inventory.header.inventory_revision + 1
    assert result.project_revision == before_document.revision + 1
    assert tuple(source.source_id for source in result.sources) == tuple(
        source.source_id for source in s.inventory.sources[:3]
    )
    for before, after in zip(s.inventory.sources, current.sources, strict=True):
        identity_fields = {
            "external_locator",
            "display_filename",
            "last_full_hash_at",
            "full_hash_evidence",
        }
        assert before.model_dump(exclude=identity_fields) == after.model_dump(
            exclude=identity_fields
        )
        assert (
            hashlib.sha256(Path(after.external_locator).read_bytes()).hexdigest()
            == before.content_sha256
        )
    assert current.sources[-1] == s.inventory.sources[-1]
    after_document = projects.open(s.root)
    assert after_document.logical_source_groups == before_document.logical_source_groups
    assert after_document.source_participation == before_document.source_participation
    assert after_document.video_usage == before_document.video_usage
    assert snapshot(s.old) == before_sources and snapshot(s.new) == before_new
    assert all(
        (s.root / relative).read_bytes() == data
        for relative, data in before_project.items()
        if relative != "project.json" and relative != "project.lock"
    )
    settings = CandidatePoolSettings(
        candidate_fps=parse_fps("2"), encoding=CandidateEncodingSettings()
    )
    assert candidate_recipe_key(
        sources=s.inventory.sources,
        settings=settings,
        backend=photo.probe.backend,
        video_usage=before_document.video_usage,
    ) == candidate_recipe_key(
        sources=current.sources,
        settings=settings,
        backend=photo.probe.backend,
        video_usage=after_document.video_usage,
    )


@pytest.mark.parametrize("problem", ["missing", "different"])
def test_preview_reports_all_problems_and_apply_never_partially_commits(
    scenario: Scenario,
    problem: str,
) -> None:
    s = scenario
    candidate = s.new / "video/clip.mov"
    if problem == "missing":
        candidate.unlink()
    else:
        candidate.write_bytes(b"different video")
    before = snapshot(s.root)
    preview = s.service().preview(s.root, s.old, s.new)
    assert preview.total == 3 and preview.matched == 2 and not preview.can_apply
    assert preview.entries[1].status == (
        "unavailable" if problem == "missing" else "different_content"
    )
    with pytest.raises((ProjectError, ValueError)):
        s.service().apply(s.root, preview)
    assert snapshot(s.root) == before and s.files.active == 0


def test_apply_rehashes_when_bytes_changed_after_preview(scenario: Scenario) -> None:
    s = scenario
    preview = s.service().preview(s.root, s.old, s.new)
    (s.new / "video/clip.mov").write_bytes(b"changed")
    before = snapshot(s.root)
    with pytest.raises(ProjectError, match="different content"):
        s.service().apply(s.root, preview)
    assert snapshot(s.root) == before and s.files.active == 0


@pytest.mark.parametrize("mutation", ["revision", "inventory", "inventory_contents", "project"])
def test_stale_preview_is_refused_without_writes(
    scenario: Scenario, mutation: str, tmp_path: Path
) -> None:
    s = scenario
    service = s.service()
    preview = service.preview(s.root, s.old, s.new)
    root = s.root
    if mutation == "revision":
        projects = build_project_service()
        document = projects.open(root)
        document.label = "Saved elsewhere"
        projects.save(root, document)
    elif mutation == "inventory":
        s.media.add(root, [s.old / "video/clip.mov"])
    elif mutation == "inventory_contents":
        reference = root / preview.inventory_reference
        lines = reference.read_text(encoding="utf-8").splitlines()
        record = json.loads(lines[1])
        record["display_filename"] = "tampered.png"
        lines[1] = json.dumps(record)
        reference.write_text("\n".join(lines) + "\n", encoding="utf-8")
    else:
        root = tmp_path / "other project"
        build_project_service().create(root, "Other")
        MediaService(LocalMediaRepository(), s.files, CaptureProbe()).add(
            root, [s.old / "video/clip.mov"]
        )
    before = snapshot(root)
    with pytest.raises(StaleProjectRevisionError):
        service.apply(root, preview)
    assert snapshot(root) == before


@pytest.mark.parametrize("mutation", ["subset", "source_id", "candidate", "relative"])
def test_apply_reconstructs_scope_and_refuses_forged_mapping(
    scenario: Scenario, mutation: str
) -> None:
    s = scenario
    service = s.service()
    preview = service.preview(s.root, s.old, s.new)
    entries = list(preview.entries)
    if mutation == "subset":
        entries.pop()
    else:
        updates = (
            {"source_id": uuid4()}
            if mutation == "source_id"
            else (
                {"candidate": s.new / "elsewhere.png"}
                if mutation == "candidate"
                else {"relative_path": "../escape.png"}
            )
        )
        entries[0] = entries[0].model_copy(update=updates)
    before = snapshot(s.root)
    with pytest.raises(ProjectError, match="scope changed"):
        service.apply(s.root, preview.model_copy(update={"entries": tuple(entries)}))
    assert snapshot(s.root) == before


def test_apply_never_trusts_forged_matched_status(scenario: Scenario) -> None:
    s = scenario
    (s.new / "video/clip.mov").write_bytes(b"not the registered video")
    preview = s.service().preview(s.root, s.old, s.new)
    forged = preview.model_copy(
        update={
            "entries": tuple(
                entry.model_copy(update={"status": "matched"}) for entry in preview.entries
            )
        }
    )
    before = snapshot(s.root)
    with pytest.raises(ProjectError, match="different content"):
        s.service().apply(s.root, forged)
    assert snapshot(s.root) == before


@pytest.mark.parametrize("phase", ["preview", "apply", "precommit"])
def test_cancel_during_hash_or_inside_publication_validation_leaves_locators_unchanged(
    scenario: Scenario,
    phase: str,
) -> None:
    s = scenario
    service = s.service()
    preview = service.preview(s.root, s.old, s.new)
    cancelled = Event()
    cancellation = CallbackCancellation(cancelled.is_set)
    if phase == "precommit":

        class CancelRepository(LocalMediaRepository):
            def commit_inventory(self, root, **kwargs):
                cancelled.set()  # service has already done all hashes and emitted finalizing
                assert s.files.active == 2
                return super().commit_inventory(root, **kwargs)

        service = s.service(CancelRepository())
    else:
        s.files.after_hash = cancelled.set
    before = snapshot(s.root)
    with pytest.raises(MediaOperationCancelled):
        if phase == "preview":
            service.preview(s.root, s.old, s.new, cancellation=cancellation)
        else:
            service.apply(s.root, preview, cancellation=cancellation)
    assert snapshot(s.root) == before and s.files.active == 0


def test_source_stability_failure_in_commit_validation_refuses_whole_folder(
    scenario: Scenario,
) -> None:
    s = scenario
    preview = s.service().preview(s.root, s.old, s.new)
    original_evidence = s.files.evidence
    changed = Event()

    def evidence(path):
        value = original_evidence(path)
        return value.model_copy(update={"size": value.size + 1}) if changed.is_set() else value

    class ChangedRepository(LocalMediaRepository):
        def commit_inventory(self, root, **kwargs):
            changed.set()
            return super().commit_inventory(root, **kwargs)

    s.files.evidence = evidence
    before = snapshot(s.root)
    with pytest.raises(SourceUnstableError):
        s.service(ChangedRepository()).apply(s.root, preview)
    assert snapshot(s.root) == before and s.files.active == 0


def test_revision_race_uses_existing_inventory_cas(scenario: Scenario) -> None:
    s = scenario
    preview = s.service().preview(s.root, s.old, s.new)
    inventories = snapshot(s.root / "sources")

    class RacingRepository(LocalMediaRepository):
        def commit_inventory(self, root, **kwargs):
            projects = build_project_service()
            document = projects.open(root)
            document.label = "Another writer"
            projects.save(root, document)
            return super().commit_inventory(root, **kwargs)

    with pytest.raises(StaleProjectRevisionError):
        s.service(RacingRepository()).apply(s.root, preview)
    assert snapshot(s.root / "sources") == inventories
    assert s.media.list(s.root) == s.inventory
    assert s.files.active == 0


def test_publication_fault_keeps_old_reference_and_retry_recovers(scenario: Scenario) -> None:
    s = scenario
    preview = s.service().preview(s.root, s.old, s.new)
    before = (s.root / "project.json").read_bytes()

    def fail(_path):
        assert s.files.active == 2
        raise RuntimeError("after inventory publish")

    repository = LocalMediaRepository(
        fault_hooks=MediaStorageFaultHooks(after_inventory_publish=fail)
    )
    with pytest.raises(RuntimeError, match="after inventory publish"):
        s.service(repository).apply(s.root, preview)
    assert (s.root / "project.json").read_bytes() == before
    assert s.media.list(s.root) == s.inventory
    assert len(list((s.root / "sources").glob("*.jsonl"))) == 2
    assert s.files.active == 0
    result = s.service().apply(s.root, preview)
    assert result.inventory_revision == 2


def test_disconnected_old_drive_is_lexical_and_new_drive_is_verified(
    scenario: Scenario,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if os.name != "nt":
        pytest.skip("Recorded disconnected Windows drive contract")
    s = scenario
    document = build_project_service().open(s.root)
    old = Path("Z:/disconnected/old média")
    sources = tuple(
        source.model_copy(
            update={"external_locator": str(old / Path(source.external_locator).relative_to(s.old))}
        )
        if index < 3
        else source
        for index, source in enumerate(s.inventory.sources)
    )
    inventory = s.inventory.model_copy(update={"sources": sources})
    # Model an inventory created while this drive was online; it is offline for both operations.
    reference = s.root / document.inventory_reference
    records = [
        inventory.header.model_dump_json(),
        *(source.model_dump_json() for source in sources),
    ]
    reference.write_text("\n".join(records) + "\n", encoding="utf-8")
    real_lstat = Path.lstat

    def checked_lstat(path, *args, **kwargs):
        assert path.drive.upper() != "Z:", "Old drive must never be inspected"
        return real_lstat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "lstat", checked_lstat)
    preview = s.service().preview(s.root, old, s.new)
    assert preview.can_apply and preview.total == 3
    s.service().apply(s.root, preview)
    current = s.media.list(s.root)
    assert current.sources[0].external_locator == str(s.new / "foto/žluťoučký.png")


@pytest.mark.parametrize(
    "relative",
    [
        "../outside.png",
        "folder/../file.png",
        "C:/file.png",
        "a\\file.png",
        "CON.png",
        "photo.png:stream",
    ],
)
def test_relative_paths_reject_escape_and_ambiguous_windows_names(
    tmp_path: Path, relative: str
) -> None:
    with pytest.raises(ProjectError):
        LocalRelinkPathGuard().candidate(tmp_path, relative)


@pytest.mark.parametrize(
    "paths",
    [
        ("A.png", "a.png"),
        ("Photos/a.png", "photos/b.png"),
    ],
)
def test_distinct_windows_case_collisions_are_refused(paths: tuple[str, ...]) -> None:
    with pytest.raises(ProjectError, match="case collision"):
        LocalRelinkPathGuard().validate_relative_paths(paths)
    LocalRelinkPathGuard().validate_relative_paths(("Photos/a.png", "Photos/a.png"))


def test_candidate_containment_and_folder_traversal_are_checked(tmp_path: Path) -> None:
    guard = LocalRelinkPathGuard()
    with pytest.raises(ProjectError, match="escapes"):
        guard.validate_candidate(tmp_path / "new", tmp_path / "outside.png")
    with pytest.raises(ProjectError, match="traversal"):
        guard.normalize_folder(tmp_path / "new" / ".." / "elsewhere", must_exist=False)


def test_reparse_point_in_new_root_ancestor_is_rejected(
    scenario: Scenario,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    s = scenario
    real_lstat = Path.lstat

    def reparse_lstat(path, *args, **kwargs):
        info = real_lstat(path, *args, **kwargs)
        if path == s.new.parent:
            return SimpleNamespace(st_mode=info.st_mode, st_file_attributes=0x400)
        return info

    monkeypatch.setattr(Path, "lstat", reparse_lstat)
    before = (s.root / "project.json").read_bytes()
    with pytest.raises(ProjectError, match="reparse point"):
        s.service().preview(s.root, s.old, s.new)
    assert (s.root / "project.json").read_bytes() == before


def test_symlink_candidate_is_diagnosed_and_cannot_be_applied(scenario: Scenario) -> None:
    s = scenario
    path = s.new / "video/clip.mov"
    path.unlink()
    try:
        path.symlink_to(s.old / "video/clip.mov")
    except OSError as exc:
        pytest.skip(f"Host cannot create test symlink: {exc}")
    preview = s.service().preview(s.root, s.old, s.new)
    assert preview.entries[1].status == "unsafe_path" and not preview.can_apply
    before = snapshot(s.root)
    with pytest.raises(ProjectError, match="symlink"):
        s.service().apply(s.root, preview)
    assert snapshot(s.root) == before


def test_new_ancestor_reparse_change_after_hash_is_refused_before_commit(
    scenario: Scenario,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    s = scenario
    preview = s.service().preview(s.root, s.old, s.new)
    changed = Event()
    real_lstat = Path.lstat

    def reparse_lstat(path, *args, **kwargs):
        info = real_lstat(path, *args, **kwargs)
        if changed.is_set() and path == s.new:
            return SimpleNamespace(st_mode=info.st_mode, st_file_attributes=0x400)
        return info

    monkeypatch.setattr(Path, "lstat", reparse_lstat)

    def progress(value):
        if value.phase == "finalizing":
            changed.set()

    before = snapshot(s.root)
    with pytest.raises(ProjectError, match="reparse point"):
        s.service().apply(s.root, preview, progress=progress)
    assert snapshot(s.root) == before and s.files.active == 0


def test_empty_scope_and_missing_new_root_are_explicit(scenario: Scenario) -> None:
    s = scenario
    preview = s.service().preview(s.root, s.old / "unregistered", s.new)
    assert preview.total == preview.matched == 0 and not preview.can_apply
    with pytest.raises(ProjectError, match="scope changed"):
        s.service().apply(s.root, preview)
    with pytest.raises(ProjectError, match="unavailable"):
        s.service().preview(s.root, s.old, s.new / "does not exist")


def test_bootstrap_exposes_folder_service_without_media_probe() -> None:
    assert isinstance(build_folder_relink_service(), FolderRelinkService)
    assert isinstance(build_gui_facade().service("folder_relink"), FolderRelinkService)


def test_long_nested_unicode_locators_relink_without_truncation(scenario: Scenario) -> None:
    s = scenario
    relative = Path(*(
        (f"nested Unicode ž segment {index} " * 2).rstrip() for index in range(6)
    )) / "写真.png"
    content = b"tiny long-path source fixture"
    for folder in (s.old, s.new):
        target = folder / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    assert len(str(s.new / relative)) > 260
    s.media.add(s.root, [s.old / relative])
    before = s.media.list(s.root).sources[-1]
    service = s.service()
    preview = service.preview(s.root, s.old, s.new)
    assert preview.total == preview.matched == 4
    service.apply(s.root, preview)
    after = s.media.list(s.root).sources[-1]
    assert after.source_id == before.source_id
    assert after.source_revision == before.source_revision
    assert after.external_locator == str(s.new / relative)
    assert (s.new / relative).read_bytes() == (s.old / relative).read_bytes() == content
