"""Read-only desktop contracts and a narrow client facade; deliberately Qt-free."""

from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID

from pydantic import Field

from splatforge.application.media_contracts import MediaCancellation, classify_media_path
from splatforge.application.media_scan import (
    MediaScanner,
    MediaScanResult,
    ScanLimits,
    ScanProgress,
)
from splatforge.core.execution import CancellationRequestResult, RecoveryResult
from splatforge.core.progress import PipelineProgressSnapshot
from splatforge.core.project import ProjectDocument
from splatforge.core.views import FrozenModel


class IndexRow(FrozenModel):
    identity: UUID
    values: dict[str, Any]


class ProjectIndex(FrozenModel):
    state_version: int = 4
    runs: tuple[IndexRow, ...] = ()
    artifacts: tuple[IndexRow, ...] = ()
    truncated: bool = False
    source_verifications: dict[str, dict[str, Any]] = Field(default_factory=dict)
    validation_status: str = "not_started"


class WorkflowItem(FrozenModel):
    name: str
    status: str
    detail: str


class ProjectOverview(FrozenModel):
    document: ProjectDocument
    sources: tuple[IndexRow, ...]
    index: ProjectIndex
    active: tuple[PipelineProgressSnapshot, ...]
    workflow: tuple[WorkflowItem, ...]


class PreviewData(FrozenModel):
    artifact_id: UUID
    semantic_digest: str
    directory: Path
    metadata: dict[str, Any]
    points: tuple[tuple[float, float, float], ...] = Field(default=(), max_length=20000)
    cameras: tuple[tuple[float, float, float], ...] = Field(default=(), max_length=2000)
    label: str = "Bounded point preview"


class ThumbnailReference(FrozenModel):
    identity: str
    path: Path
    caption: str


class MediaCandidates(FrozenModel):
    supported: tuple[Path, ...]
    ignored: int
    scanned: int


def enumerate_media(directory: Path, limit: int = 2000) -> MediaCandidates:
    """Nonrecursive, deterministic and bounded. Never traverse links/junctions."""
    supported, ignored, scanned = [], 0, 0
    for path in directory.iterdir():
        scanned += 1
        if scanned > limit:
            raise ValueError(f"desktop.folder_limit: more than {limit} entries; choose files")
        if path.is_symlink() or path.is_junction():
            ignored += 1
        elif path.is_file() and classify_media_path(path) is not None:
            supported.append(path)
        else:
            ignored += 1
    return MediaCandidates(
        supported=tuple(sorted(supported, key=lambda p: (p.name.casefold(), p.name))),
        ignored=ignored,
        scanned=scanned,
    )


class DesktopReader(Protocol):
    def state_version(self, root: Path) -> int: ...
    def index(self, root: Path) -> ProjectIndex: ...
    def inspect(self, root: Path, artifact_id: UUID) -> PreviewData: ...
    def gallery(
        self, root: Path, run_id: UUID, offset: int = 0
    ) -> tuple[ThumbnailReference, ...]: ...
    def live_metrics(self, root: Path, run_ids: tuple[UUID, ...]) -> dict: ...


WORKFLOW_TYPES = {
    "views": ("views.selected_set",),
    "geometry": ("geometry.verified_geometry_set",),
    "reconstruction": ("mapping.reconstruction_set",),
    "validation": ("validation.reconstruction_report",),
    "selection": ("reconstruction.selection",),
    "dataset": ("dataset.prepared_set",),
    "training": ("training.checkpoint",),
    "scene": ("training.gaussian_scene", "training.gaussian_scene_set"),
}


def summarize_workflow(index: ProjectIndex, source_count: int) -> tuple[WorkflowItem, ...]:
    """Report indexed evidence, never infer completion from a directory or file."""
    items = [
        WorkflowItem(
            name="sources",
            status="completed" if source_count else "not_started",
            detail=f"{source_count} registered sources",
        )
    ]
    for name, kinds in WORKFLOW_TYPES.items():
        output = next((a for a in index.artifacts if a.values["artifact_type"] in kinds), None)
        run = next((r for r in index.runs if name in r.values.get("stage", "")), None)
        status = "ready" if items[-1].status == "completed" else "not_started"
        detail = "No published output; use Plan to check current inputs/settings"
        if output:
            status = "stale" if output.values.get("storage_status") == "evicted" else "completed"
            detail = f"Published {output.identity}; current compatibility is checked by Plan"
        if run and run.values["status"] in {"running", "failed", "interrupted"}:
            status = {"interrupted": "warning"}.get(run.values["status"], run.values["status"])
            detail = f"Run {run.identity}: {run.values['status']}"
        items.append(WorkflowItem(name=name, status=status, detail=detail))
    return tuple(items)


class GuiFacade:
    """Each task constructs its own facade/services through bootstrap factories."""

    def __init__(self, reader: DesktopReader, factories: dict[str, Callable]) -> None:
        self.reader, self.factories = reader, factories

    def service(self, name: str) -> Any:
        return self.factories[name]()

    def create(self, root: Path, label: str) -> ProjectDocument:
        return self.service("project").create(root, label)

    def scan_media(
        self, paths: tuple[Path, ...], *, cancellation: MediaCancellation | None = None,
        progress: Callable[[ScanProgress], None] | None = None,
        limits: ScanLimits | None = None,
    ) -> MediaScanResult:
        scanner: MediaScanner = self.service("media_scanner")
        return scanner.scan(paths, limits=limits, cancellation=cancellation, progress=progress)

    def save(self, root: Path, document: ProjectDocument) -> ProjectDocument:
        return self.service("project").save(root, document)

    def overview(self, root: Path) -> ProjectOverview:
        document = self.service("project").open(root)
        inventory = self.service("media").list(root)
        index = self.reader.index(root)

        def verification(source) -> str:
            evidence = index.source_verifications.get(str(source.source_id))
            if evidence and (
                evidence["source_revision"] == source.source_revision
                and evidence["expected_content_digest"] == source.content_sha256
            ):
                return f"{evidence['outcome']} · {evidence['assurance']} · {evidence['checked_at']}"
            return "Full hash at ingest; current verification not recorded"

        sources = (
            tuple(
                IndexRow(
                    identity=s.source_id,
                    values={
                        "filename": s.display_filename,
                        "type": s.media_type.value,
                        "bytes": s.byte_size,
                        "verification": verification(s),
                        "group": str(s.source_group_id),
                        "dimensions": f"{s.probe.width} × {s.probe.height}",
                        "duration": s.probe.duration,
                        "codec": s.probe.codec_name,
                        "sha256": s.content_sha256,
                        "sourceRevision": s.source_revision,
                        "lastHashedAt": s.last_full_hash_at.isoformat(),
                        "locator": s.external_locator,
                    },
                )
                for s in inventory.sources
            )
            if inventory
            else ()
        )
        return ProjectOverview(
            document=document,
            sources=sources,
            index=index,
            active=self.service("progress").active(root) if index.state_version >= 3 else (),
            workflow=summarize_workflow(index, len(sources)),
        )

    def inspect(self, root: Path, artifact_id: UUID) -> PreviewData:
        return self.reader.inspect(root, artifact_id)

    def gallery(self, root: Path, run_id: UUID, offset: int = 0) -> tuple[ThumbnailReference, ...]:
        return self.reader.gallery(root, run_id, offset)

    def cancel(self, root: Path, run_id: UUID) -> CancellationRequestResult:
        return self.service("execution").cancel(root, run_id)

    def recover(self, root: Path, run_id: UUID) -> RecoveryResult:
        return self.service("execution").recover(root, run_id)

    def progress(self, root: Path) -> tuple[PipelineProgressSnapshot, ...]:
        if self.reader.state_version(root) < 3:
            return ()
        return self.service("progress").active(root)

    def live_metrics(self, root: Path, runs: tuple[PipelineProgressSnapshot, ...]) -> dict:
        return self.reader.live_metrics(root, tuple(r.run_id for r in runs))
