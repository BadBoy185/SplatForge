from __future__ import annotations

import hashlib
import io
import json
import os
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from uuid import UUID

import pytest
from PIL import Image

from splatforge.adapters.execution_storage import ExecutionFaultHooks, LocalExecutionRepository
from splatforge.adapters.fake_stages import LocalFakeStages
from splatforge.adapters.media_storage import LocalMediaRepository
from splatforge.adapters.project_storage import LocalProjectStore
from splatforge.adapters.view_workspace import LocalViewWorkspace
from splatforge.application.execution import (
    FakeExecutionService,
    PublicationUnresolvedError,
    RetryNotAllowedError,
    UnresolvedExecutionError,
)
from splatforge.application.media import MediaService
from splatforge.application.media_contracts import StrictSourceUnavailableError
from splatforge.application.views import ViewsService
from splatforge.application.views_contracts import (
    FFmpegCancelledError,
    FFmpegTeardownError,
    MaterializedFrame,
)
from splatforge.bootstrap import build_project_service
from splatforge.core.media import (
    ExecutableIdentity,
    FullHashEvidence,
    MediaType,
    NormalizedProbe,
    SourceEvidence,
    StorageKind,
    VerificationPolicyId,
)
from splatforge.core.views import (
    CandidateEncodingSettings,
    CandidatePoolSettings,
    CandidateResourceLimits,
    FixedFpsSettings,
    ImageFormat,
    RationalValue,
    parse_fps,
)

BACKEND = ExecutableIdentity(
    resolved_path="C:/Tools/ffmpeg.exe",
    size=100,
    last_write_ns=200,
    sha256="a" * 64,
    version_line="ffmpeg version fake",
)


def evidence(path: Path, *, generation: int = 1) -> SourceEvidence:
    stat = path.stat()
    return SourceEvidence(
        size=stat.st_size,
        last_write_ns=generation,
        volume_id="volume",
        file_id=f"file-{path.name}",
        change_time_ns=generation,
        storage_kind=StorageKind.LOCAL_FIXED,
        evidence_available=True,
    )


@dataclass
class FakeHash:
    sha256: str
    evidence: FullHashEvidence


class FakeLease:
    def __init__(self, files: FakeSourceFiles, path: Path, strict: bool) -> None:
        self.files = files
        self.path = path.absolute()
        self.strict = strict
        self.stream = None
        self.evidence_before = files.evidence(self.path)
        self.stability_mechanism = (
            "windows_read_lease_no_write_delete" if strict else "fake_stable_read_lease"
        )

    def __enter__(self) -> FakeLease:
        if self.strict and not self.files.strict_supported:
            raise StrictSourceUnavailableError("strict lease is unavailable")
        self.files.active.add(self.path)
        if self.strict:
            self.files.strict_leases += 1
        return self

    def current_evidence(self) -> SourceEvidence:
        return self.files.evidence(self.path)

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.files.active.remove(self.path)


class FakeSourceFiles:
    def __init__(self) -> None:
        self.active: set[Path] = set()
        self.hash_reads = 0
        self.strict_leases = 0
        self.strict_supported = True
        self.generations: dict[Path, int] = {}
        self.on_hash = None

    def evidence(self, path: Path) -> SourceEvidence:
        absolute = path.absolute()
        if not absolute.is_file():
            from splatforge.application.media_contracts import SourceUnavailableError

            raise SourceUnavailableError(f"missing source: {absolute}", missing=True)
        return evidence(absolute, generation=self.generations.get(absolute, 1))

    def lease(self, path: Path, *, strict: bool = False) -> FakeLease:
        return FakeLease(self, path, strict)

    def hash_lease(self, lease: FakeLease, control=None) -> FakeHash:  # type: ignore[no-untyped-def]
        if control is not None:
            control.checkpoint()
        if self.on_hash is not None:
            self.on_hash(control)
        self.hash_reads += 1
        data = lease.path.read_bytes()
        observed = lease.current_evidence()
        return FakeHash(
            sha256=hashlib.sha256(data).hexdigest(),
            evidence=FullHashEvidence(
                hashed_at=datetime.now(UTC),
                byte_count=len(data),
                evidence_before=observed,
                evidence_after=observed,
                stability_mechanism=lease.stability_mechanism,
            ),
        )


class FakeProbe:
    def probe(self, path: Path, media_type: MediaType, *, cancellation=None) -> NormalizedProbe:  # type: ignore[no-untyped-def]
        return NormalizedProbe(
            backend=BACKEND,
            selected_visual_stream_index=0,
            codec_name="h264" if media_type == MediaType.VIDEO else "png",
            width=16,
            height=12,
            orientation=1 if media_type == MediaType.PHOTO else None,
            time_base="1/10" if media_type == MediaType.VIDEO else None,
            duration="1.1" if media_type == MediaType.VIDEO else None,
            rotation_degrees=0 if media_type == MediaType.VIDEO else None,
        )


class FakeMaterializer:
    def __init__(self, source_files: FakeSourceFiles) -> None:
        self.source_files = source_files
        self.calls: list[Path] = []
        self.mode = "success"
        self.on_call = None
        self.backend = BACKEND

    def identity(self, cancellation=None) -> ExecutableIdentity:  # type: ignore[no-untyped-def]
        return self.backend

    def materialize(
        self,
        source_path: Path,
        source,
        output_directory: Path,
        settings: CandidatePoolSettings,
        *,
        timeout_seconds: int,
        expected_backend: ExecutableIdentity,
        cancellation=None,
    ) -> tuple[MaterializedFrame, ...]:
        absolute = source_path.absolute()
        assert absolute in self.source_files.active
        assert expected_backend == self.backend
        self.calls.append(absolute)
        output_directory.mkdir(parents=True)
        if self.on_call is not None:
            self.on_call(cancellation)
        if self.mode in {"cancelled", "cancelled_unconfirmed"}:
            (output_directory / "frame-00000000.png").write_bytes(png(16, 12))
            raise FFmpegCancelledError(
                "cancelled",
                teardown_confirmed=self.mode == "cancelled",
            )
        if self.mode == "unresolved":
            (output_directory / "frame-00000000.png").write_bytes(png(16, 12))
            raise FFmpegTeardownError("teardown unconfirmed")
        if source.media_type == MediaType.PHOTO:
            path = output_directory / "frame-00000000.png"
            path.write_bytes(png(16, 12))
            return (MaterializedFrame(path, 0, None, None),)
        time_base = RationalValue(numerator=1, denominator=10)
        frames = []
        timestamps = (0, 2, 4, 6, 8, 10) if self.mode == "too_many" else (0, 7, 10)
        for index, pts in enumerate(timestamps):
            path = output_directory / f"frame-{index:08d}.png"
            payload = png(16, 12)
            if self.mode == "large":
                payload += b"x" * 150_000
            path.write_bytes(payload)
            frames.append(MaterializedFrame(path, index, pts, time_base))
        return tuple(frames)


def png(width: int, height: int) -> bytes:
    with io.BytesIO() as stream:
        with Image.new("RGB", (width, height), (20, 40, 60)) as image:
            image.save(stream, format="PNG")
        return stream.getvalue()


def query(root: Path, statement: str, parameters: tuple[object, ...] = ()) -> list[tuple]:
    with closing(sqlite3.connect(root / "state.sqlite")) as connection:
        return connection.execute(statement, parameters).fetchall()


@dataclass
class Harness:
    root: Path
    execution: LocalExecutionRepository
    media: LocalMediaRepository
    sources: FakeSourceFiles
    materializer: FakeMaterializer
    service: ViewsService
    source_ids: tuple[UUID, ...]
    source_paths: tuple[Path, ...]


def harness(tmp_path: Path, *, mixed: bool = True, free_bytes: int = 10**9) -> Harness:
    root = tmp_path / "M3 Příliš žluťoučký project"
    build_project_service().create(root, "M3 route")
    video = tmp_path / "clip one.mp4"
    video.write_bytes(b"original-video")
    paths = [video]
    if mixed:
        photo = tmp_path / "unordered photo.png"
        photo.write_bytes(b"original-photo")
        paths.append(photo)
    store = LocalProjectStore()
    media = LocalMediaRepository(project_store=store)
    sources = FakeSourceFiles()
    added = MediaService(media, sources, FakeProbe()).add(root, paths)
    execution = LocalExecutionRepository(project_store=store)
    materializer = FakeMaterializer(sources)
    service = ViewsService(
        execution,
        media,
        sources,
        materializer,
        LocalViewWorkspace(free_bytes=lambda _path: free_bytes),
    )
    return Harness(
        root=root,
        execution=execution,
        media=media,
        sources=sources,
        materializer=materializer,
        service=service,
        source_ids=tuple(item.source_id for item in added.added_sources),
        source_paths=tuple(paths),
    )


def candidate_settings(fps: str = "2") -> CandidatePoolSettings:
    return CandidatePoolSettings(
        candidate_fps=parse_fps(fps),
        encoding=CandidateEncodingSettings(
            image_format=ImageFormat.PNG,
            png_compression_level=6,
        ),
    )


def limits(*, count: int = 100, byte_count: int = 10**7) -> CandidateResourceLimits:
    return CandidateResourceLimits(
        max_candidates=count,
        max_candidate_bytes=byte_count,
        per_source_timeout_seconds=30,
    )


def prepare(
    value: Harness,
    *,
    target: str = "1",
    candidate_fps: str = "2",
    policy: VerificationPolicyId = VerificationPolicyId.BALANCED_LOCAL,
    resource_limits: CandidateResourceLimits | None = None,
):
    return value.service.prepare(
        value.root,
        candidate_settings=candidate_settings(candidate_fps),
        selection_settings=FixedFpsSettings(target_fps=parse_fps(target)),
        resource_limits=resource_limits or limits(),
        verification_policy=policy,
    )


def test_concrete_route_publishes_multifile_artifacts_and_reuses_both(tmp_path: Path) -> None:
    value = harness(tmp_path)
    originals = {path: path.read_bytes() for path in value.source_paths}

    first = prepare(value)

    assert first.status == "succeeded"
    assert first.candidate_count == 4
    assert first.selected_count == 3
    assert first.cache_hits == ()
    assert len(value.materializer.calls) == 2
    assert [row[0] for row in query(value.root, "SELECT node_id FROM attempts")] == [
        "candidate_views",
        "selected_views",
    ]
    candidate_manifest = value.root / first.candidate_artifact.manifest_path
    manifest = __import__("json").loads(candidate_manifest.read_text(encoding="utf-8"))
    assert len(manifest["payloads"]) == first.candidate_count + 1
    assert {item["path"] for item in manifest["payloads"]} >= {"candidate_views.json"}
    assert all(path.read_bytes() == originals[path] for path in value.source_paths)

    second = prepare(value)

    assert second.cache_hits == ("candidate_views", "selected_views")
    assert second.candidate_artifact.artifact_id == first.candidate_artifact.artifact_id
    assert second.selected_artifact.artifact_id == first.selected_artifact.artifact_id
    assert len(value.materializer.calls) == 2
    assert query(
        value.root,
        "SELECT count(*) FROM attempts WHERE run_id=?",
        (str(second.run_id),),
    ) == [(0,)]


def test_same_service_reobserves_ffmpeg_before_cache_lookup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from splatforge.adapters.ffmpeg import FFmpegAdapter
    from splatforge.core.process import ProcessResult

    value = harness(tmp_path, mixed=False)
    probes = []

    class VersionRunner:
        def run(self, request, *, cancellation=None):  # type: ignore[no-untyped-def]
            identity = value.materializer.backend
            probes.append(identity)
            return ProcessResult(
                executable=identity.model_copy(update={"version_line": None}),
                argv=request.argv, working_directory=str(request.working_directory),
                exit_code=0, elapsed_seconds=0.01,
                stdout=identity.version_line.encode() + b"\n", stderr=b"",
                stdout_truncated=False, stderr_truncated=False, timed_out=False,
                cancelled=False, teardown_confirmed=True, forced_tree_termination=False,
            )

    adapter = FFmpegAdapter(runner=VersionRunner(), executable=BACKEND.resolved_path)
    monkeypatch.setattr(value.materializer, "identity", adapter.identity)
    first = prepare(value)
    value.materializer.backend = BACKEND.model_copy(update={"sha256": "b" * 64})
    original_find = value.execution.find_cache

    def assert_refreshed(*args, **kwargs):  # type: ignore[no-untyped-def]
        assert probes[-1] == value.materializer.backend
        assert len(probes) >= 2
        return original_find(*args, **kwargs)

    monkeypatch.setattr(value.execution, "find_cache", assert_refreshed)
    second = prepare(value)
    assert "candidate_views" not in second.cache_hits
    assert first.candidate_artifact.recipe_key != second.candidate_artifact.recipe_key
    assert len(value.materializer.calls) == 2
    third = prepare(value)
    assert third.cache_hits == ("candidate_views", "selected_views")
    assert third.candidate_artifact.recipe_key == second.candidate_artifact.recipe_key
    assert len(value.materializer.calls) == 2
    assert len(probes) == 3


def test_old_candidate_adapter_recipe_is_not_reused_and_remains_readable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import splatforge.core.views as contracts

    value = harness(tmp_path, mixed=False)
    with monkeypatch.context() as patch:
        patch.setattr(contracts, "FFMPEG_ADAPTER_VERSION", 1)
        first = prepare(value)
    metadata = value.root / first.candidate_artifact.manifest_path
    payload = json.loads((metadata.parent / "candidate_views.json").read_text())
    payload["adapter_version"] = 1
    assert contracts.CandidateViewSet.model_validate(payload).adapter_version == 1
    second = prepare(value)
    assert first.candidate_artifact.recipe_key != second.candidate_artifact.recipe_key
    assert "candidate_views" not in second.cache_hits


def test_historical_png_unknown_orientation_is_refused_before_plan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from splatforge.application.projects import ProjectError

    value = harness(tmp_path)
    load = value.media.load_current_inventory
    historical_id = value.source_ids[1]

    def historical(*args):  # type: ignore[no-untyped-def]
        inventory = load(*args)
        sources = tuple(source.model_copy(update={"probe": source.probe.model_copy(
            update={"orientation": None}
        )}) if source.source_id == historical_id else source for source in inventory.sources)
        return inventory.model_copy(update={"sources": sources})

    monkeypatch.setattr(value.media, "load_current_inventory", historical)
    with pytest.raises(ProjectError, match="ambiguous historical orientation.*re-ingest"):
        prepare(value)
    assert value.materializer.calls == []
    assert query(value.root, "SELECT count(*) FROM runs") == [(0,)]
    added = MediaService(value.media, value.sources, FakeProbe()).add(
        value.root, [value.source_paths[1]],
    )
    fresh_id = added.added_sources[0].source_id
    result = value.service.prepare(
        value.root, source_ids={fresh_id}, candidate_settings=candidate_settings(),
        selection_settings=FixedFpsSettings(target_fps=parse_fps("1")),
        resource_limits=limits(), verification_policy=VerificationPolicyId.BALANCED_LOCAL,
    )
    assert result.status == "succeeded" and result.candidate_count == 1
    document = LocalProjectStore().inspect(value.root).document
    records = value.media.load_current_inventory(value.root, document).sources
    historical_source = next(source for source in records if source.source_id == historical_id)
    assert historical_source.probe.orientation is None


def test_exceptional_ffmpeg_teardown_quarantines_attempt_and_blocks_next_processing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from splatforge.adapters.ffmpeg import FFmpegAdapter
    from splatforge.adapters.process_runner import ProcessCleanupError

    value = harness(tmp_path, mixed=False)

    class FailingRunner:
        def run(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            cause = RuntimeError("live callback failed")
            raise ProcessCleanupError(
                cause, teardown_confirmed=False, forced_tree_termination=True,
            ) from cause

    adapter = FFmpegAdapter(runner=FailingRunner())
    monkeypatch.setattr(value.materializer, "materialize", adapter.materialize)
    result = prepare(value)
    assert result.status == "interrupted"
    assert query(value.root, "SELECT teardown_state FROM attempts") == [("unresolved",)]
    assert "live callback failed" in query(value.root, "SELECT failure_json FROM attempts")[0][0]
    with pytest.raises(UnresolvedExecutionError, match="teardown"):
        prepare(value)


def test_target_and_candidate_fps_invalidate_only_actual_consumers(tmp_path: Path) -> None:
    value = harness(tmp_path, mixed=False)
    first = prepare(value, target="1", candidate_fps="2")
    target_changed = prepare(value, target="2", candidate_fps="2")
    assert target_changed.cache_hits == ("candidate_views",)
    assert target_changed.candidate_artifact.artifact_id == first.candidate_artifact.artifact_id
    assert target_changed.selected_artifact.artifact_id != first.selected_artifact.artifact_id
    calls_after_target = len(value.materializer.calls)

    candidate_changed = prepare(value, target="2", candidate_fps="3")
    assert candidate_changed.cache_hits == ()
    assert candidate_changed.candidate_artifact.artifact_id != first.candidate_artifact.artifact_id
    assert (
        candidate_changed.selected_artifact.artifact_id
        != target_changed.selected_artifact.artifact_id
    )
    assert len(value.materializer.calls) == calls_after_target + 1


def test_locator_only_relink_keeps_candidate_cache_reusable(tmp_path: Path) -> None:
    value = harness(tmp_path, mixed=False)
    first = prepare(value)
    replacement = tmp_path / "moved clip.mp4"
    replacement.write_bytes(value.source_paths[0].read_bytes())
    MediaService(value.media, value.sources, FakeProbe()).relink(
        value.root, value.source_ids[0], replacement
    )

    second = prepare(value)

    assert "candidate_views" in second.cache_hits
    assert second.candidate_artifact.artifact_id == first.candidate_artifact.artifact_id
    assert len(value.materializer.calls) == 1


def test_strict_does_not_reuse_balanced_but_then_supports_offline_reuse(
    tmp_path: Path,
) -> None:
    value = harness(tmp_path, mixed=False)
    balanced = prepare(value)
    ingest_hash_reads = value.sources.hash_reads

    strict = prepare(value, policy=VerificationPolicyId.STRICT)

    assert "candidate_views" not in strict.cache_hits
    assert strict.candidate_artifact.artifact_id != balanced.candidate_artifact.artifact_id
    assert value.sources.hash_reads == ingest_hash_reads + 1
    assert value.sources.strict_leases == 1
    assert len(value.materializer.calls) == 2
    value.source_paths[0].unlink()

    offline = prepare(value, policy=VerificationPolicyId.STRICT)

    assert offline.cache_hits == ("candidate_views", "selected_views")
    assert offline.candidate_artifact.artifact_id == strict.candidate_artifact.artifact_id
    assert len(value.materializer.calls) == 2


def test_balanced_unchanged_avoids_rehash_but_changed_evidence_forces_it(
    tmp_path: Path,
) -> None:
    value = harness(tmp_path, mixed=False)
    after_ingest = value.sources.hash_reads
    prepare(value)
    assert value.sources.hash_reads == after_ingest

    changed = harness(tmp_path / "changed", mixed=False)
    after_changed_ingest = changed.sources.hash_reads
    changed.sources.generations[changed.source_paths[0].absolute()] = 2
    prepare(changed)
    assert changed.sources.hash_reads == after_changed_ingest + 1
    assert len(changed.materializer.calls) == 1


def test_hash_mismatch_and_change_during_decode_block_publication(tmp_path: Path) -> None:
    mismatch = harness(tmp_path / "mismatch", mixed=False)
    mismatch.source_paths[0].write_bytes(b"changed-source-bytes")
    mismatch.sources.generations[mismatch.source_paths[0].absolute()] = 2
    with pytest.raises(ValueError, match="digest changed"):
        prepare(mismatch)
    assert mismatch.materializer.calls == []
    assert query(mismatch.root, "SELECT count(*) FROM artifacts") == [(0,)]

    changed = harness(tmp_path / "during", mixed=False)

    def mutate_evidence(_cancellation) -> None:  # type: ignore[no-untyped-def]
        changed.sources.generations[changed.source_paths[0].absolute()] = 2

    changed.materializer.on_call = mutate_evidence
    with pytest.raises(ValueError, match="changed during FFmpeg"):
        prepare(changed)
    assert query(changed.root, "SELECT count(*) FROM artifacts") == [(0,)]


def test_strict_unsupported_never_falls_back_to_balanced(tmp_path: Path) -> None:
    value = harness(tmp_path, mixed=False)
    value.sources.strict_supported = False
    with pytest.raises(StrictSourceUnavailableError):
        prepare(value, policy=VerificationPolicyId.STRICT)
    assert value.materializer.calls == []
    provenance = query(value.root, "SELECT source_verification_json FROM attempts")[0][0]
    assert "strict_unavailable" in provenance


def test_m3_records_verification_without_reacquiring_project_writer_lock(
    tmp_path: Path,
) -> None:
    value = harness(tmp_path, mixed=False)
    lock_calls = 0

    def forbidden_lock(_path: Path):
        nonlocal lock_calls
        lock_calls += 1
        raise AssertionError("M3 attempted to reacquire project.lock")

    guarded_media = LocalMediaRepository(
        project_store=LocalProjectStore(),
        lock_factory=forbidden_lock,
    )
    service = ViewsService(
        value.execution,
        guarded_media,
        value.sources,
        value.materializer,
        LocalViewWorkspace(free_bytes=lambda _path: 10**9),
    )

    result = service.prepare(
        value.root,
        candidate_settings=candidate_settings(),
        selection_settings=FixedFpsSettings(target_fps=parse_fps("1")),
        resource_limits=limits(),
        verification_policy=VerificationPolicyId.STRICT,
    )

    assert result.status == "succeeded"
    assert lock_calls == 0


@pytest.mark.parametrize(
    "resource_limits",
    [limits(count=1), limits(byte_count=1)],
)
def test_budget_refuses_before_backend_decode(
    tmp_path: Path, resource_limits: CandidateResourceLimits
) -> None:
    value = harness(tmp_path, mixed=False)
    with pytest.raises(ValueError):
        prepare(value, resource_limits=resource_limits)
    assert value.materializer.calls == []
    assert query(value.root, "SELECT status FROM attempts") == [("failed",)]


def test_insufficient_workspace_space_refuses_before_decode(tmp_path: Path) -> None:
    value = harness(tmp_path, mixed=False, free_bytes=1)
    with pytest.raises(ValueError, match="free space"):
        prepare(value)
    assert value.materializer.calls == []


@pytest.mark.parametrize(
    ("mode", "resource_limits", "message"),
    [
        ("too_many", limits(), "predecode estimate"),
        ("large", limits(byte_count=300_000), "max_candidate_bytes"),
    ],
)
def test_actual_output_cannot_exceed_preflight_bounds(
    tmp_path: Path,
    mode: str,
    resource_limits: CandidateResourceLimits,
    message: str,
) -> None:
    value = harness(tmp_path, mixed=False)
    value.materializer.mode = mode
    with pytest.raises(ValueError, match=message):
        prepare(value, resource_limits=resource_limits)
    assert query(value.root, "SELECT count(*) FROM artifacts") == [(0,)]


def test_corrupt_candidate_image_is_not_cache_eligible(tmp_path: Path) -> None:
    value = harness(tmp_path, mixed=False)
    first = prepare(value)
    candidate_directory = (value.root / first.candidate_artifact.manifest_path).parent
    image = next((candidate_directory / "images").iterdir())
    image.write_bytes(b"corrupt")

    second = prepare(value)

    assert "candidate_views" not in second.cache_hits
    assert second.candidate_artifact.artifact_id != first.candidate_artifact.artifact_id
    assert len(value.materializer.calls) == 2


def test_missing_or_unexpected_candidate_and_corrupt_selection_are_rejected(
    tmp_path: Path,
) -> None:
    missing = harness(tmp_path / "missing", mixed=False)
    first = prepare(missing)
    directory = (missing.root / first.candidate_artifact.manifest_path).parent
    next((directory / "images").iterdir()).unlink()
    rebuilt = prepare(missing)
    assert "candidate_views" not in rebuilt.cache_hits

    unexpected = harness(tmp_path / "unexpected", mixed=False)
    first = prepare(unexpected)
    directory = (unexpected.root / first.candidate_artifact.manifest_path).parent
    (directory / "images" / "unexpected.png").write_bytes(png(16, 12))
    rebuilt = prepare(unexpected)
    assert "candidate_views" not in rebuilt.cache_hits

    selection = harness(tmp_path / "selection", mixed=False)
    first = prepare(selection)
    selected_path = (
        selection.root / first.selected_artifact.manifest_path
    ).parent / "selected_views.json"
    selected_path.write_bytes(b"{}")
    rebuilt = prepare(selection)
    assert rebuilt.cache_hits == ("candidate_views",)
    assert rebuilt.selected_artifact.artifact_id != first.selected_artifact.artifact_id


def test_cache_validation_streams_candidate_images(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    value = harness(tmp_path, mixed=False)
    prepare(value)
    original = Path.read_bytes

    def guarded(path: Path) -> bytes:
        if "artifacts" in path.parts and path.suffix == ".png":
            raise AssertionError("candidate image was read into memory")
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", guarded)
    second = prepare(value)
    assert second.cache_hits == ("candidate_views", "selected_views")


def test_durable_cancellation_blocks_partial_candidate_publication(tmp_path: Path) -> None:
    value = harness(tmp_path, mixed=False)

    def request_cancel(cancellation) -> None:  # type: ignore[no-untyped-def]
        run_id = UUID(query(value.root, "SELECT run_id FROM runs WHERE status='running'")[0][0])
        value.execution.request_cancellation(value.root, run_id=run_id)
        assert cancellation.is_cancelled()

    value.materializer.on_call = request_cancel
    value.materializer.mode = "cancelled"

    result = prepare(value)

    assert result.status == "cancelled"
    assert result.candidate_artifact is None
    attempt = query(
        value.root,
        "SELECT status, cancellation_accepted_at, teardown_state FROM attempts",
    )
    assert attempt[0][0] == "cancelled"
    assert attempt[0][1] is not None
    assert attempt[0][2] == "confirmed"
    assert query(value.root, "SELECT count(*) FROM artifacts") == [(0,)]

    value.materializer.on_call = None
    value.materializer.mode = "success"
    rerun = prepare(value)
    assert rerun.status == "succeeded"
    assert rerun.cache_hits == ()


def test_cancellation_during_source_hash_is_durable_and_never_decodes(
    tmp_path: Path,
) -> None:
    value = harness(tmp_path, mixed=False)
    value.sources.generations[value.source_paths[0].absolute()] = 2

    def request_cancel(cancellation) -> None:  # type: ignore[no-untyped-def]
        run_id = UUID(query(value.root, "SELECT run_id FROM runs WHERE status='running'")[0][0])
        value.execution.request_cancellation(value.root, run_id=run_id)
        cancellation.checkpoint()

    value.sources.on_hash = request_cancel
    result = prepare(value)

    assert result.status == "cancelled"
    assert value.materializer.calls == []
    assert query(value.root, "SELECT count(*) FROM artifacts") == [(0,)]
    assert query(
        value.root,
        "SELECT status, cancellation_accepted_at FROM attempts",
    )[0][0] == "cancelled"


def test_cancellation_after_candidate_publication_reuses_candidate_on_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    value = harness(tmp_path, mixed=False)
    original_append = value.execution.append_event

    def append_and_cancel(root, run_id, *, code, **kwargs):  # type: ignore[no-untyped-def]
        warning = original_append(root, run_id, code=code, **kwargs)
        if code == "candidate.stage.published":
            value.execution.request_cancellation(root, run_id=run_id)
        return warning

    monkeypatch.setattr(value.execution, "append_event", append_and_cancel)
    cancelled = prepare(value)

    assert cancelled.status == "cancelled"
    assert cancelled.candidate_artifact is not None
    assert cancelled.selected_artifact is None
    assert query(value.root, "SELECT count(*) FROM artifacts") == [(1,)]

    monkeypatch.setattr(value.execution, "append_event", original_append)
    restarted = prepare(value)
    assert restarted.status == "succeeded"
    assert restarted.cache_hits == ("candidate_views",)


def test_unconfirmed_teardown_blocks_publication_and_next_execution(tmp_path: Path) -> None:
    value = harness(tmp_path, mixed=False)
    value.materializer.mode = "unresolved"

    result = prepare(value)

    assert result.status == "interrupted"
    assert query(value.root, "SELECT count(*) FROM artifacts") == [(0,)]
    assert query(value.root, "SELECT teardown_state FROM attempts") == [("unresolved",)]
    with pytest.raises(UnresolvedExecutionError, match="teardown"):
        prepare(value)


def test_unconfirmed_unauthorized_cancellation_also_blocks_next_execution(
    tmp_path: Path,
) -> None:
    value = harness(tmp_path, mixed=False)
    value.materializer.mode = "cancelled_unconfirmed"

    result = prepare(value)

    assert result.status == "interrupted"
    assert query(value.root, "SELECT count(*) FROM artifacts") == [(0,)]
    assert query(value.root, "SELECT teardown_state FROM attempts") == [("unresolved",)]
    with pytest.raises(UnresolvedExecutionError, match="teardown"):
        prepare(value)


def test_run_show_recover_and_retry_are_route_aware(tmp_path: Path) -> None:
    value = harness(tmp_path, mixed=False)
    result = prepare(value)
    control = FakeExecutionService(value.execution, LocalFakeStages())

    shown = json.loads(control.show(value.root, result.run_id))
    assert shown["snapshot"]["route"]["route_id"] == "views.prepare_fixed_fps"
    assert control.recover(value.root, result.run_id).status == "succeeded"
    with pytest.raises(RetryNotAllowedError, match="historical fake route"):
        control.retry(value.root, result.run_id)


@pytest.mark.skipif(os.name != "nt", reason="M3 external recovery requires Windows Job Objects")
def test_moved_candidate_orphan_is_validated_adopted_and_reused(tmp_path: Path) -> None:
    value = harness(tmp_path, mixed=False)
    raised = False

    def fail_once(path: Path) -> None:
        nonlocal raised
        if not raised and path.parent.name == "candidate_views":
            raised = True
            raise OSError("crash after candidate move")

    execution = LocalExecutionRepository(
        project_store=LocalProjectStore(),
        fault_hooks=ExecutionFaultHooks(after_artifact_move=fail_once),
    )
    crashing = ViewsService(
        execution,
        value.media,
        value.sources,
        value.materializer,
        LocalViewWorkspace(free_bytes=lambda _path: 10**9),
    )
    with pytest.raises(PublicationUnresolvedError):
        crashing.prepare(
            value.root,
            candidate_settings=candidate_settings(),
            selection_settings=FixedFpsSettings(target_fps=parse_fps("1")),
            resource_limits=limits(),
            verification_policy=VerificationPolicyId.BALANCED_LOCAL,
        )
    run_id = UUID(query(value.root, "SELECT run_id FROM runs")[0][0])

    recovered = FakeExecutionService(execution, LocalFakeStages()).recover(
        value.root, run_id
    )

    assert recovered.status == "interrupted"
    assert len(recovered.adopted_attempts) == 1
    clean_execution = LocalExecutionRepository(project_store=LocalProjectStore())
    restarted = ViewsService(
        clean_execution,
        value.media,
        value.sources,
        value.materializer,
        LocalViewWorkspace(free_bytes=lambda _path: 10**9),
    ).prepare(
        value.root,
        candidate_settings=candidate_settings(),
        selection_settings=FixedFpsSettings(target_fps=parse_fps("1")),
        resource_limits=limits(),
        verification_policy=VerificationPolicyId.BALANCED_LOCAL,
    )
    assert restarted.cache_hits == ("candidate_views",)


@pytest.mark.skipif(os.name != "nt", reason="M3 external recovery requires Windows Job Objects")
def test_corrupt_moved_candidate_orphan_is_not_adopted(tmp_path: Path) -> None:
    value = harness(tmp_path, mixed=False)

    def fail_after_move(path: Path) -> None:
        if path.parent.name == "candidate_views":
            raise OSError("crash after candidate move")

    execution = LocalExecutionRepository(
        project_store=LocalProjectStore(),
        fault_hooks=ExecutionFaultHooks(after_artifact_move=fail_after_move),
    )
    service = ViewsService(
        execution,
        value.media,
        value.sources,
        value.materializer,
        LocalViewWorkspace(free_bytes=lambda _path: 10**9),
    )
    with pytest.raises(PublicationUnresolvedError):
        service.prepare(
            value.root,
            candidate_settings=candidate_settings(),
            selection_settings=FixedFpsSettings(target_fps=parse_fps("1")),
            resource_limits=limits(),
            verification_policy=VerificationPolicyId.BALANCED_LOCAL,
        )
    row = query(
        value.root,
        "SELECT run_id, expected_artifact_id FROM attempts WHERE node_id='candidate_views'",
    )[0]
    artifact_directory = value.root / "artifacts" / "candidate_views" / row[1]
    next((artifact_directory / "images").iterdir()).write_bytes(b"corrupt")

    recovered = FakeExecutionService(execution, LocalFakeStages()).recover(
        value.root, UUID(row[0])
    )

    assert recovered.status == "interrupted"
    assert recovered.adopted_attempts == ()
    assert recovered.warnings[0].code == "orphan.publication_refused"
    assert query(value.root, "SELECT count(*) FROM artifacts") == [(0,)]


class CrashBeforeSelectionRepository(LocalExecutionRepository):
    def begin_attempt(self, root: Path, **kwargs):  # type: ignore[no-untyped-def]
        if kwargs["node_id"] == "selected_views":
            raise KeyboardInterrupt("crash before selection")
        return super().begin_attempt(root, **kwargs)


class CrashBeforeCandidateAttemptRepository(LocalExecutionRepository):
    def begin_attempt(self, root: Path, **kwargs):  # type: ignore[no-untyped-def]
        if kwargs["node_id"] == "candidate_views":
            raise KeyboardInterrupt("crash before candidate attempt")
        return super().begin_attempt(root, **kwargs)


class CrashBeforeFinalizeRepository(LocalExecutionRepository):
    def __init__(self, **kwargs) -> None:  # type: ignore[no-untyped-def]
        super().__init__(**kwargs)
        self.crash = True

    def mark_run_succeeded(self, root: Path, *, run_id: UUID) -> None:
        if self.crash:
            self.crash = False
            raise KeyboardInterrupt("crash before run finalization")
        super().mark_run_succeeded(root, run_id=run_id)


def test_run_created_before_candidate_attempt_recovers_without_adopting(
    tmp_path: Path,
) -> None:
    value = harness(tmp_path, mixed=False)
    execution = CrashBeforeCandidateAttemptRepository(project_store=LocalProjectStore())
    service = ViewsService(
        execution,
        value.media,
        value.sources,
        value.materializer,
        LocalViewWorkspace(free_bytes=lambda _path: 10**9),
    )
    with pytest.raises(KeyboardInterrupt):
        service.prepare(
            value.root,
            candidate_settings=candidate_settings(),
            selection_settings=FixedFpsSettings(target_fps=parse_fps("1")),
            resource_limits=limits(),
            verification_policy=VerificationPolicyId.BALANCED_LOCAL,
        )
    run_id = UUID(query(value.root, "SELECT run_id FROM runs")[0][0])
    assert query(value.root, "SELECT count(*) FROM attempts") == [(0,)]

    recovered = FakeExecutionService(execution, LocalFakeStages()).recover(
        value.root, run_id
    )

    assert recovered.status == "interrupted"
    assert recovered.adopted_attempts == ()
    assert query(value.root, "SELECT count(*) FROM artifacts") == [(0,)]


@pytest.mark.skipif(os.name != "nt", reason="M3 external recovery requires Windows Job Objects")
def test_expected_candidate_identity_before_move_never_adopts_workspace(
    tmp_path: Path,
) -> None:
    value = harness(tmp_path, mixed=False)

    def crash_before_move(path: Path) -> None:
        if path.parent.name == "candidate_views":
            raise KeyboardInterrupt("crash before candidate move")

    execution = LocalExecutionRepository(
        project_store=LocalProjectStore(),
        fault_hooks=ExecutionFaultHooks(before_artifact_move=crash_before_move),
    )
    service = ViewsService(
        execution,
        value.media,
        value.sources,
        value.materializer,
        LocalViewWorkspace(free_bytes=lambda _path: 10**9),
    )
    with pytest.raises(KeyboardInterrupt):
        service.prepare(
            value.root,
            candidate_settings=candidate_settings(),
            selection_settings=FixedFpsSettings(target_fps=parse_fps("1")),
            resource_limits=limits(),
            verification_policy=VerificationPolicyId.BALANCED_LOCAL,
        )
    row = query(
        value.root,
        "SELECT run_id, attempt_id, expected_artifact_id, expected_manifest_digest "
        "FROM attempts WHERE node_id='candidate_views'",
    )[0]
    run_id, attempt_id, artifact_id, manifest_digest = row
    workspace_manifest = (
        value.root / "work" / run_id / attempt_id / "output" / "manifest.json"
    )
    assert artifact_id is not None
    assert manifest_digest is not None
    assert workspace_manifest.is_file()
    assert not (value.root / "artifacts" / "candidate_views" / artifact_id).exists()

    recovered = FakeExecutionService(execution, LocalFakeStages()).recover(
        value.root, UUID(run_id)
    )

    assert recovered.status == "interrupted"
    assert recovered.adopted_attempts == ()
    assert query(value.root, "SELECT count(*) FROM artifacts") == [(0,)]


def test_published_candidate_restarts_at_selection_via_new_run(tmp_path: Path) -> None:
    value = harness(tmp_path, mixed=False)
    execution = CrashBeforeSelectionRepository(project_store=LocalProjectStore())
    service = ViewsService(
        execution,
        value.media,
        value.sources,
        value.materializer,
        LocalViewWorkspace(free_bytes=lambda _path: 10**9),
    )
    with pytest.raises(KeyboardInterrupt):
        service.prepare(
            value.root,
            candidate_settings=candidate_settings(),
            selection_settings=FixedFpsSettings(target_fps=parse_fps("1")),
            resource_limits=limits(),
            verification_policy=VerificationPolicyId.BALANCED_LOCAL,
        )
    run_id = UUID(query(value.root, "SELECT run_id FROM runs")[0][0])
    recovered = FakeExecutionService(execution, LocalFakeStages()).recover(
        value.root, run_id
    )
    assert recovered.status == "interrupted"

    clean = ViewsService(
        LocalExecutionRepository(project_store=LocalProjectStore()),
        value.media,
        value.sources,
        value.materializer,
        LocalViewWorkspace(free_bytes=lambda _path: 10**9),
    ).prepare(
        value.root,
        candidate_settings=candidate_settings(),
        selection_settings=FixedFpsSettings(target_fps=parse_fps("1")),
        resource_limits=limits(),
        verification_policy=VerificationPolicyId.BALANCED_LOCAL,
    )
    assert clean.cache_hits == ("candidate_views",)


def test_fully_published_m3_run_can_be_finalized_by_recovery(tmp_path: Path) -> None:
    value = harness(tmp_path, mixed=False)
    execution = CrashBeforeFinalizeRepository(project_store=LocalProjectStore())
    service = ViewsService(
        execution,
        value.media,
        value.sources,
        value.materializer,
        LocalViewWorkspace(free_bytes=lambda _path: 10**9),
    )
    with pytest.raises(KeyboardInterrupt):
        service.prepare(
            value.root,
            candidate_settings=candidate_settings(),
            selection_settings=FixedFpsSettings(target_fps=parse_fps("1")),
            resource_limits=limits(),
            verification_policy=VerificationPolicyId.BALANCED_LOCAL,
        )
    run_id = UUID(query(value.root, "SELECT run_id FROM runs")[0][0])

    recovered = FakeExecutionService(execution, LocalFakeStages()).recover(
        value.root, run_id
    )

    assert recovered.status == "succeeded"
    assert query(value.root, "SELECT count(*) FROM artifacts") == [(2,)]
