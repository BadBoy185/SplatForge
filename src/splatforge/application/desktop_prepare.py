"""Prepare Data use cases shared by desktop presentation and other clients."""

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Protocol
from uuid import UUID

from splatforge.application.execution import ExecutionProject
from splatforge.application.media import MediaService
from splatforge.application.prepare_settings import (
    PrepareRequest,
    _saved_request,
    preparation_media_context,
    resolve_preparation_request,
)
from splatforge.application.projects import StaleProjectRevisionError
from splatforge.application.views import ViewsService
from splatforge.core.execution import ViewsRunResult
from splatforge.core.project import ProjectDocument
from splatforge.core.source_participation import resolve_effective_sources
from splatforge.core.video_usage import usable_video_sources
from splatforge.core.views import (
    CandidateBudgetExceeded,
    FrozenModel,
    estimate_candidate_budget,
)


class PreparePlan(FrozenModel):
    project_id: UUID
    project_revision: int
    request: PrepareRequest
    photo_count: int
    video_count: int
    used_video_count: int
    candidate_count: int | None = None
    candidate_bytes: int | None = None
    peak_workspace_bytes: int | None = None
    warnings: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()
    runnable: bool


class PrepareSummary(FrozenModel):
    run_id: UUID
    created_at: datetime
    project_id: UUID
    project_revision: int
    request: PrepareRequest
    candidate_count: int
    selected_count: int
    rejected_count: int
    quality_measured_count: int | None = None
    quality_unavailable_count: int | None = None
    method_id: str
    cache_hits: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    photo_count: int | None = None
    video_count: int | None = None


class PrepareReader(Protocol):
    def project(self, root: Path) -> ExecutionProject: ...

    def results(self, root: Path) -> tuple[PrepareSummary, ...]: ...

    def summary(self, root: Path, run_id: UUID) -> PrepareSummary: ...


def preparation_request(document: ProjectDocument) -> PrepareRequest:
    """Compatible public entrypoint for the saved frame slot."""
    if "prepare_data" not in (document.settings.frame_selection.model_extra or {}):
        return _saved_request(document)
    return resolve_preparation_request(document)


def _budget_blocker(
    error: CandidateBudgetExceeded, request: PrepareRequest, *, has_video: bool,
) -> str:
    if error.resource == "candidate_bytes":
        reason = (
            f"Candidate storage upper bound is {error.estimated / 1024**3:.2f} GiB, "
            f"above the {error.limit / 1024**3:.2f} GiB limit."
        )
    else:
        reason = (
            f"Candidate count upper bound {error.estimated:,} exceeds the "
            f"{error.limit:,} candidate limit."
        )
    hint = "Reduce the sources Included in preparation"
    if has_video:
        hint += " or lower candidate frames/second"
        if request.quality is not None:
            hint += (
                ". Sharpest video needs at least 2 × target FPS, "
                "so increase the output interval as needed"
            )
        else:
            hint += " without going below target FPS"
    return reason + " " + hint + ". Save settings, then check the plan again."


class PrepareService:
    def __init__(self, reader: PrepareReader, media: MediaService, views: ViewsService) -> None:
        self._reader, self._media, self._views = reader, media, views

    @staticmethod
    def _expected(document: ProjectDocument, project_id: UUID, revision: int) -> None:
        if document.project_id != project_id or document.revision != revision:
            raise StaleProjectRevisionError("Project changed; refresh the Prepare Data plan")

    def plan(
        self, root: Path, *, expected_project_id: UUID, expected_revision: int,
    ) -> PreparePlan:
        project = self._reader.project(root)
        document = project.document
        self._expected(document, expected_project_id, expected_revision)
        inventory = self._media.list(root, document=document)
        sources = inventory.sources if inventory else ()
        context = preparation_media_context(document, sources)
        request = resolve_preparation_request(document, has_video=context["has_video"])
        warnings = []
        blockers = []
        runnable = project.state_version == 4
        if not runnable:
            warnings.append("State upgrade required before preparation")
            blockers.append(warnings[-1])
        photo_count = context["photo_count"]
        video_count = context["video_count"]
        used_video_count = context["used_video_count"]
        estimate = None
        try:
            ids = resolve_effective_sources(
                (s.source_id for s in sources), document.source_participation,
            ).processing_source_ids()
            included = tuple(s for s in sources if s.source_id in ids)
            usable = usable_video_sources(included, document.video_usage)
            if not usable:
                raise ValueError("No usable media: videos have no used intervals")
            warnings.append(
                "Candidate counts and storage are conservative upper bounds, "
                "not expected encoded file sizes or a measurement of free disk space. "
                "Expected encoded size is unknown before processing."
            )
            if used_video_count and document.video_usage.entries:
                warnings.append(
                    "Saved Trim intervals bound retained frames and extraction images. "
                    "Sampling still follows the original full video timeline; "
                    "decoding may scan the full clip."
                )
            warnings.append(
                "Peak workspace covers extraction images, retained frames, metadata "
                "and bounded temporary extraction files. "
                "Image bounds use the same conservative "
                "per-pixel allowance for JPEG and PNG."
            )
            estimate = estimate_candidate_budget(
                usable, settings=request.candidate, limits=request.limits,
                video_usage=document.video_usage,
            )
        except ValueError as exc:
            runnable = False
            blocker = (_budget_blocker(exc, request, has_video=context["has_video"])
                       if isinstance(exc, CandidateBudgetExceeded) else str(exc))
            blockers.append(blocker)
            warnings.append(blocker)
        return PreparePlan(
            project_id=document.project_id, project_revision=document.revision, request=request,
            photo_count=photo_count, video_count=video_count, used_video_count=used_video_count,
            candidate_count=estimate.total_candidates if estimate else None,
            candidate_bytes=estimate.candidate_bytes if estimate else None,
            peak_workspace_bytes=estimate.peak_workspace_bytes if estimate else None,
            runnable=runnable, warnings=tuple(warnings), blockers=tuple(blockers),
        )

    def run(
        self, root: Path, request: PrepareRequest, *, expected_project_id: UUID,
        expected_revision: int, cancellation_check: Callable[[], None] | None = None,
    ) -> ViewsRunResult:
        document = self._reader.project(root).document
        self._expected(document, expected_project_id, expected_revision)
        inventory = self._media.list(root, document=document)
        context = preparation_media_context(document, inventory.sources if inventory else ())
        saved_request = resolve_preparation_request(document, has_video=context["has_video"])
        if request != saved_request:
            raise ValueError("Prepare Data requires the exact saved preparation settings")
        if cancellation_check is not None:
            cancellation_check()
        return self._views.prepare(
            root, candidate_settings=request.candidate, selection_settings=request.selection,
            quality_settings=request.quality, resource_limits=request.limits,
            verification_policy=request.verification_policy,
            expected_project_id=expected_project_id, expected_revision=expected_revision,
        )

    def results(self, root: Path) -> tuple[PrepareSummary, ...]:
        return self._reader.results(root)

    def summary(self, root: Path, run_id: UUID) -> PrepareSummary:
        return self._reader.summary(root, run_id)
