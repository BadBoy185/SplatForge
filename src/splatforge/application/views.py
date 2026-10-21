"""Concrete candidate, quality, and frame-selection orchestration."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol
from uuid import UUID, uuid4

from splatforge.application.execution import (
    ExecutionCancelledError,
    ExecutionRepository,
    PublicationUnresolvedError,
    StateUpgradeRequiredError,
)
from splatforge.application.media_contracts import (
    SourceFiles,
    SourceUnavailableError,
    SourceUnstableError,
    StrictSourceUnavailableError,
)
from splatforge.application.projects import ProjectError
from splatforge.application.views_contracts import (
    CandidateMaterializer,
    FFmpegCancelledError,
    FFmpegTeardownError,
    MaterializedFrame,
    QualityAssessor,
    ViewWorkspace,
)
from splatforge.core.execution import (
    ArtifactHandle,
    ArtifactInputLineage,
    FailureCategory,
    FixedFpsSelectionNode,
    OutputReference,
    QualityAssessmentNode,
    RunSnapshot,
    RunStatus,
    RunWarning,
    SharpestIntervalSelectionNode,
    SharpestViewPreparationRoute,
    ViewPreparationNode,
    ViewPreparationRoute,
    ViewsRunResult,
)
from splatforge.core.media import (
    ExecutableIdentity,
    MediaType,
    RehashReason,
    SourceEvidence,
    SourceInventory,
    SourceOccurrence,
    VerificationAssurance,
    VerificationOutcome,
    VerificationPolicyId,
    VerificationResult,
)
from splatforge.core.project import ProjectDocument
from splatforge.core.quality import (
    QUALITY_ARTIFACT_CONTRACT_VERSION,
    QUALITY_ARTIFACT_TYPE,
    MeasurementAvailability,
    QualityAnalysisSettings,
    QualityBackendIdentity,
    QualityReport,
    SharpestIntervalSettings,
    SharpestSelectedViewSet,
    quality_recipe_key,
    select_sharpest_interval,
    sharpest_selection_recipe_key,
    validate_quality_against_candidate,
    validate_sharpest_against_inputs,
    validate_sharpest_candidate_density,
)
from splatforge.core.views import (
    CANDIDATE_ARTIFACT_TYPE,
    FFMPEG_ADAPTER_VERSION,
    SELECTED_ARTIFACT_TYPE,
    VIEW_ARTIFACT_CONTRACT_VERSION,
    CandidateBudgetEstimate,
    CandidatePoolSettings,
    CandidateResourceLimits,
    CandidateView,
    CandidateViewSet,
    FixedFpsSettings,
    FrameTimestamp,
    ImageFormat,
    PixelTransform,
    SelectedViewSet,
    candidate_recipe_key,
    deterministic_photo_view_id,
    deterministic_video_view_id,
    estimate_candidate_budget,
    photo_orientation_operation,
    select_fixed_fps,
    selection_recipe_key,
    validate_fps_density,
    validate_selected_against_candidate,
    video_orientation_operation,
)


class MediaStateRepository(Protocol):
    def load_current_inventory(
        self, root: Path, document: ProjectDocument
    ) -> SourceInventory | None: ...

    def inventory_content_digest(self, root: Path, reference: str) -> str: ...

    def latest_full_evidence(
        self,
        root: Path,
        *,
        source_id: UUID,
        source_revision: int,
        content_sha256: str,
    ) -> SourceEvidence | None: ...

    def record_verification_under_writer(self, root: Path, result: VerificationResult) -> None: ...


class _ExternalCancellation(Exception):
    def __init__(self, attempt_id: UUID, teardown_confirmed: bool) -> None:
        self.attempt_id = attempt_id
        self.teardown_confirmed = teardown_confirmed


class _ExternalUnresolved(Exception):
    pass


class _OwnerCancellationBridge:
    """Return true to the process runner only after SQLite acceptance is durable."""

    def __init__(
        self,
        repository: ExecutionRepository,
        root: Path,
        run_id: UUID,
        attempt_id: UUID,
    ) -> None:
        self._repository = repository
        self._root = root
        self._run_id = run_id
        self._attempt_id = attempt_id
        self.accepted = False
        self._event_written = False

    def is_cancelled(self) -> bool:
        accepted = self._repository.accept_cancellation(
            self._root, run_id=self._run_id, attempt_id=self._attempt_id
        )
        if accepted:
            self.accepted = True
            if not self._event_written:
                self._repository.append_event(
                    self._root,
                    self._run_id,
                    code="cancellation.accepted",
                    attempt_id=self._attempt_id,
                )
                self._event_written = True
        return accepted

    def checkpoint(self) -> None:
        if self.is_cancelled():
            raise ExecutionCancelledError(self._attempt_id)


class ViewsService:
    def __init__(
        self,
        execution_repository: ExecutionRepository,
        media_repository: MediaStateRepository,
        source_files: SourceFiles,
        materializer: CandidateMaterializer,
        workspace: ViewWorkspace,
        quality_assessor: QualityAssessor | None = None,
    ) -> None:
        self._execution = execution_repository
        self._media = media_repository
        self._sources = source_files
        self._materializer = materializer
        self._workspace = workspace
        self._quality_assessor = quality_assessor

    def prepare(
        self,
        root: Path,
        *,
        candidate_settings: CandidatePoolSettings,
        selection_settings: FixedFpsSettings | SharpestIntervalSettings,
        quality_settings: QualityAnalysisSettings | None = None,
        resource_limits: CandidateResourceLimits,
        verification_policy: VerificationPolicyId,
        source_ids: set[UUID] | None = None,
    ) -> ViewsRunResult:
        if isinstance(selection_settings, FixedFpsSettings):
            validate_fps_density(candidate_settings, selection_settings)
            if quality_settings is not None:
                raise ValueError("fixed-FPS selection does not accept quality settings")
        elif quality_settings is None:
            raise ValueError("sharpest-per-interval selection requires quality settings")
        if isinstance(selection_settings, SharpestIntervalSettings) and (
            self._quality_assessor is None
        ):
            raise ValueError("sharpest-per-interval quality adapter is unavailable")
        root = root.resolve()
        run_id = uuid4()
        owner_token = uuid4()
        warnings: list[RunWarning] = []
        cache_hits: list[str] = []
        candidate_handle: ArtifactHandle | None = None
        quality_handle: ArtifactHandle | None = None
        selected_handle: ArtifactHandle | None = None
        candidate_count = 0
        selected_count = 0
        quality_measured_count = 0
        quality_unavailable_count = 0
        rejected_count = 0
        unsatisfied_interval_count = 0
        status = RunStatus.RUNNING

        with self._execution.writer(root, owner_token=owner_token, operation="views-prepare"):
            project = self._execution.inspect_project(root)
            if project.state_version != 4:
                if project.state_version in {1, 2, 3}:
                    raise StateUpgradeRequiredError(
                        "State upgrade required: run 'splatforge project upgrade-state <project>'"
                    )
                raise ProjectError(f"Unsupported state schema version {project.state_version}")
            self._execution.ensure_no_unfinished_run(root)
            project_copy = ProjectDocument.model_validate(project.document.model_dump(mode="json"))
            inventory = self._media.load_current_inventory(root, project_copy)
            if inventory is None or not inventory.sources:
                raise ProjectError("Project has no registered media sources")
            selected_sources = self._select_sources(inventory, source_ids)
            for source in selected_sources:
                if source.extension == ".png" and source.probe.orientation is None:
                    raise ProjectError(
                        f"PNG source {source.source_id} has ambiguous historical orientation "
                        "metadata; re-ingest it with 'media add', then prepare with --source-id "
                        "for the newly added source"
                    )
            if isinstance(selection_settings, SharpestIntervalSettings):
                validate_sharpest_candidate_density(
                    candidate_settings,
                    selection_settings,
                    has_video=any(
                        source.media_type == MediaType.VIDEO for source in selected_sources
                    ),
                )
            backend = self._materializer.identity()
            quality_backend = (
                self._quality_assessor.identity()
                if isinstance(selection_settings, SharpestIntervalSettings)
                and self._quality_assessor is not None
                else None
            )
            assert project_copy.inventory_reference is not None
            inventory_digest = self._media.inventory_content_digest(
                root, project_copy.inventory_reference
            )
            route = self._build_route(
                inventory_reference=project_copy.inventory_reference,
                inventory_digest=inventory_digest,
                sources=selected_sources,
                verification_policy=verification_policy,
                backend=backend,
                candidate_settings=candidate_settings,
                selection_settings=selection_settings,
                quality_settings=quality_settings,
                quality_backend=quality_backend,
                resource_limits=resource_limits,
            )
            snapshot = RunSnapshot(
                run_id=run_id,
                project_id=project_copy.project_id,
                project_revision=project_copy.revision,
                owner_token=owner_token,
                created_at=datetime.now(UTC),
                project_intent=project_copy,
                route=route,
            )
            self._execution.create_run(root, snapshot)
            self._event(warnings, root, run_id, code="run.started")
            try:
                self._checkpoint(root, snapshot, None)
                candidate_handle, candidate = self._run_candidate(
                    root, snapshot, warnings, cache_hits
                )
                candidate_count = len(candidate.views)
                self._checkpoint(root, snapshot, None)
                if isinstance(snapshot.route, SharpestViewPreparationRoute):
                    quality_handle, quality = self._run_quality(
                        root,
                        snapshot,
                        candidate_handle,
                        candidate,
                        warnings,
                        cache_hits,
                    )
                    quality_measured_count = sum(
                        item.sharpness.availability == MeasurementAvailability.AVAILABLE
                        for item in quality.measurements
                    )
                    quality_unavailable_count = len(quality.measurements) - quality_measured_count
                    self._checkpoint(root, snapshot, None)
                    selected_handle, selected = self._run_sharpest_selection(
                        root,
                        snapshot,
                        candidate_handle,
                        candidate,
                        quality_handle,
                        quality,
                        warnings,
                        cache_hits,
                    )
                    selected_count = selected.total_selected_count
                    rejected_count = selected.total_rejected_count
                    unsatisfied_interval_count = len(selected.unsatisfied_intervals)
                else:
                    selected_handle, selected = self._run_selection(
                        root,
                        snapshot,
                        candidate_handle,
                        candidate,
                        warnings,
                        cache_hits,
                    )
                    selected_count = selected.total_selected_count
                self._checkpoint(root, snapshot, None)
                self._execution.mark_run_succeeded(root, run_id=run_id)
                status = RunStatus.SUCCEEDED
                self._event(
                    warnings,
                    root,
                    run_id,
                    code="run.completed",
                    details={
                        "candidate_count": candidate_count,
                        "selected_count": selected_count,
                        "quality_measured_count": quality_measured_count,
                        "quality_unavailable_count": quality_unavailable_count,
                        "rejected_count": rejected_count,
                        "unsatisfied_interval_count": unsatisfied_interval_count,
                    },
                )
            except ExecutionCancelledError as exc:
                status = self._execution.finish_cancellation(
                    root,
                    run_id=run_id,
                    attempt_id=exc.attempt_id,
                    teardown_confirmed=True,
                )
                self._event(
                    warnings,
                    root,
                    run_id,
                    code="run.cancelled",
                    attempt_id=exc.attempt_id,
                )
            except _ExternalCancellation as exc:
                status = self._execution.finish_cancellation(
                    root,
                    run_id=run_id,
                    attempt_id=exc.attempt_id,
                    teardown_confirmed=exc.teardown_confirmed,
                )
                self._event(
                    warnings,
                    root,
                    run_id,
                    code=("run.cancelled" if status == RunStatus.CANCELLED else "run.interrupted"),
                    attempt_id=exc.attempt_id,
                )
            except _ExternalUnresolved:
                status = RunStatus.INTERRUPTED
                self._event(warnings, root, run_id, code="run.interrupted")
            except PublicationUnresolvedError:
                raise
            except Exception as exc:
                self._execution.mark_run_failed(root, run_id=run_id, message=str(exc))
                self._event(
                    warnings,
                    root,
                    run_id,
                    code="run.failed",
                    details={"error": str(exc)},
                )
                raise

        return ViewsRunResult(
            run_id=run_id,
            status=status,
            candidate_artifact=candidate_handle,
            quality_artifact=quality_handle,
            selected_artifact=selected_handle,
            cache_hits=tuple(cache_hits),
            candidate_count=candidate_count,
            quality_measured_count=quality_measured_count,
            quality_unavailable_count=quality_unavailable_count,
            selected_count=selected_count,
            rejected_count=rejected_count,
            unsatisfied_interval_count=unsatisfied_interval_count,
            warnings=tuple(warnings),
        )

    def _run_candidate(
        self,
        root: Path,
        snapshot: RunSnapshot,
        warnings: list[RunWarning],
        cache_hits: list[str],
    ) -> tuple[ArtifactHandle, CandidateViewSet]:
        route = self._view_route(snapshot)
        node = route.candidate
        key = candidate_recipe_key(
            sources=route.sources,
            settings=node.settings,
            backend=route.ffmpeg_backend,
        )
        cached = self._execution.find_cache(
            root,
            recipe_key=key,
            artifact_type=node.output.artifact_type,
            contract_version=node.output.contract_version,
            source_requirements=route.sources,
            verification_policy=route.verification_policy,
        )
        if cached.artifact is not None:
            self._execution.bind_cached_output(
                root,
                run_id=snapshot.run_id,
                node_id=node.node_id,
                output_name=node.output.output_name,
                artifact_id=cached.artifact.artifact_id,
            )
            candidate = self._execution.load_candidate_views(root, cached.artifact)
            cache_hits.append(node.node_id)
            self._event(
                warnings,
                root,
                snapshot.run_id,
                code="candidate.stage.cache_hit",
                node_id=node.node_id,
                details={
                    "artifact_id": str(cached.artifact.artifact_id),
                    "reuse": "artifact_backed",
                    "fresh_source_verification": False,
                },
            )
            return cached.artifact, candidate

        self._event(
            warnings,
            root,
            snapshot.run_id,
            code="candidate.stage.started",
            node_id=node.node_id,
            details={"source_count": len(route.sources)},
        )
        attempt = self._execution.begin_attempt(
            root,
            run_id=snapshot.run_id,
            node_id=node.node_id,
            output_name=node.output.output_name,
            recipe_key=key,
            input_artifact_ids=(),
            literal_inputs={
                "candidate_settings": node.settings.model_dump(mode="json"),
                "inventory_content_digest": route.inventory_content_digest,
                "selected_source_ids": [str(source.source_id) for source in route.sources],
            },
            environment=self._ffmpeg_environment(route),
            source_verification={
                "policy": route.verification_policy.value,
                "artifact_backed": False,
                "evidence": [],
            },
        )
        bridge = _OwnerCancellationBridge(
            self._execution, root, snapshot.run_id, attempt.attempt_id
        )
        verification_entries: list[dict[str, object]] = []
        try:
            estimate = estimate_candidate_budget(
                route.sources,
                settings=node.settings,
                limits=route.resource_limits,
            )
            free = self._workspace.free_bytes(Path(attempt.workspace))
            if estimate.peak_workspace_bytes > free:
                raise ProjectError(
                    f"Candidate peak workspace estimate {estimate.peak_workspace_bytes} "
                    f"bytes exceeds current free space {free} bytes"
                )
            candidate = self._materialize_candidate_set(
                root,
                snapshot,
                attempt.attempt_id,
                Path(attempt.workspace),
                estimate,
                bridge,
                verification_entries,
                warnings,
            )
            bridge.checkpoint()
            artifact = self._execution.publish_attempt(
                root,
                run_id=snapshot.run_id,
                node_id=node.node_id,
                output_name=node.output.output_name,
                artifact_type=node.output.artifact_type,
                contract_version=node.output.contract_version,
                recipe_key=key,
                attempt=attempt,
                input_lineage=(),
            )
        except FFmpegCancelledError as exc:
            if not bridge.accepted:
                if not exc.teardown_confirmed:
                    self._execution.mark_external_interrupted(
                        root,
                        run_id=snapshot.run_id,
                        attempt_id=attempt.attempt_id,
                        message=(
                            "FFmpeg reported cancellation without durable owner "
                            "acceptance and teardown was not confirmed"
                        ),
                    )
                    raise _ExternalUnresolved(
                        "Unconfirmed FFmpeg teardown after unauthorized cancellation"
                    ) from exc
                self._execution.mark_attempt_failed(
                    root,
                    attempt_id=attempt.attempt_id,
                    message="FFmpeg reported cancellation without durable owner acceptance",
                    category=self._non_retryable(),
                )
                raise ProjectError(
                    "FFmpeg reported cancellation without durable owner acceptance"
                ) from exc
            raise _ExternalCancellation(attempt.attempt_id, exc.teardown_confirmed) from exc
        except FFmpegTeardownError as exc:
            self._execution.mark_external_interrupted(
                root,
                run_id=snapshot.run_id,
                attempt_id=attempt.attempt_id,
                message=str(exc),
            )
            raise _ExternalUnresolved(str(exc)) from exc
        except (ExecutionCancelledError, PublicationUnresolvedError):
            raise
        except Exception as exc:
            self._execution.mark_attempt_failed(
                root,
                attempt_id=attempt.attempt_id,
                message=str(exc),
                category=self._non_retryable(),
            )
            raise
        self._event(
            warnings,
            root,
            snapshot.run_id,
            code="candidate.stage.published",
            node_id=node.node_id,
            attempt_id=attempt.attempt_id,
            details={
                "artifact_id": str(artifact.artifact_id),
                "candidate_count": len(candidate.views),
            },
        )
        return artifact, candidate

    def _materialize_candidate_set(
        self,
        root: Path,
        snapshot: RunSnapshot,
        attempt_id: UUID,
        workspace: Path,
        estimate: CandidateBudgetEstimate,
        bridge: _OwnerCancellationBridge,
        verification_entries: list[dict[str, object]],
        warnings: list[RunWarning],
    ) -> CandidateViewSet:
        route = self._view_route(snapshot)
        self._workspace.prepare_candidate(workspace)
        source_estimates = {item.source_id: item for item in estimate.sources}
        views: list[CandidateView] = []
        payload_bytes = 0
        for source_index, source in enumerate(route.sources):
            bridge.checkpoint()
            self._event(
                warnings,
                root,
                snapshot.run_id,
                code="source.preparation.started",
                node_id=route.candidate.node_id,
                attempt_id=attempt_id,
                details={
                    "source_id": str(source.source_id),
                    "completed_sources": source_index,
                    "total_sources": len(route.sources),
                },
            )
            source_output = self._workspace.source_output_directory(workspace, source_index)
            frames = self._consume_verified_source(
                root,
                snapshot,
                attempt_id,
                source,
                source_output,
                bridge,
                verification_entries,
            )
            source_estimate = source_estimates[source.source_id]
            if len(frames) > source_estimate.candidate_count:
                raise ValueError(
                    f"Source {source.source_id} produced {len(frames)} candidates, above "
                    f"its predecode estimate {source_estimate.candidate_count}"
                )
            occurrences: defaultdict[tuple[int, int, int], int] = defaultdict(int)
            for frame in frames:
                if source.media_type == MediaType.PHOTO:
                    view_id = deterministic_photo_view_id(source)
                    timestamp = None
                    frame_identity = "photo_singleton"
                    occurrence = 0
                else:
                    if frame.pts is None or frame.time_base is None:
                        raise ValueError("Video frame lacks actual FFmpeg presentation identity")
                    occurrence_key = (
                        frame.pts,
                        frame.time_base.numerator,
                        frame.time_base.denominator,
                    )
                    occurrence = occurrences[occurrence_key]
                    occurrences[occurrence_key] += 1
                    view_id = deterministic_video_view_id(
                        source,
                        pts=frame.pts,
                        time_base=frame.time_base,
                        occurrence_index=occurrence,
                    )
                    timestamp = FrameTimestamp(pts=frame.pts, time_base=frame.time_base)
                    frame_identity = (
                        f"pts:{frame.pts}@{frame.time_base.numerator}/{frame.time_base.denominator}"
                    )
                suffix = (
                    ".jpg"
                    if route.candidate.settings.encoding.image_format == ImageFormat.JPEG
                    else ".png"
                )
                relative = f"images/{view_id}{suffix}"
                materialized = self._workspace.publish_candidate_image(
                    workspace, frame.temporary_path, relative
                )
                payload_bytes += materialized.size
                operation = (
                    photo_orientation_operation(source.probe.orientation)
                    if source.media_type == MediaType.PHOTO
                    else video_orientation_operation(source.probe.rotation_degrees)
                )
                swap = operation.value in {
                    "transpose",
                    "rotate_90_cw",
                    "transverse",
                    "rotate_90_ccw",
                }
                width = source.probe.height if swap else source.probe.width
                height = source.probe.width if swap else source.probe.height
                transform = PixelTransform(
                    source_width=source.probe.width,
                    source_height=source.probe.height,
                    orientation_operation=operation,
                    output_width=width,
                    output_height=height,
                )
                views.append(
                    CandidateView(
                        view_id=view_id,
                        source_id=source.source_id,
                        source_revision=source.source_revision,
                        source_content_sha256=source.content_sha256,
                        source_group_id=source.source_group_id,
                        camera_group_id=source.camera_group_id,
                        media_type=source.media_type,
                        selected_visual_stream_index=(source.probe.selected_visual_stream_index),
                        frame_identity=frame_identity,
                        occurrence_index=occurrence,
                        presentation_timestamp=timestamp,
                        image_path=relative,
                        image_sha256=materialized.sha256,
                        width=width,
                        height=height,
                        transform=transform,
                        display_filename=source.display_filename,
                    )
                )
            if len(views) > route.resource_limits.max_candidates:
                raise ValueError("Actual candidate count exceeds max_candidates")
            if payload_bytes > route.resource_limits.max_candidate_bytes:
                raise ValueError("Actual candidate payload bytes exceed max_candidate_bytes")
            self._event(
                warnings,
                root,
                snapshot.run_id,
                code="source.preparation.completed",
                node_id=route.candidate.node_id,
                attempt_id=attempt_id,
                details={
                    "source_id": str(source.source_id),
                    "completed_sources": source_index + 1,
                    "total_sources": len(route.sources),
                    "candidate_count_so_far": len(views),
                },
            )
        if len(views) > estimate.total_candidates:
            raise ValueError("Actual candidate count exceeds the predecode estimate")
        if payload_bytes > estimate.candidate_bytes:
            raise ValueError("Actual candidate bytes exceed the conservative predecode estimate")
        ordered = tuple(
            sorted(
                views,
                key=lambda view: (
                    str(view.source_id),
                    (
                        view.presentation_timestamp.seconds()
                        if view.presentation_timestamp is not None
                        else 0
                    ),
                    str(view.view_id),
                ),
            )
        )
        candidate = CandidateViewSet(
            backend=route.ffmpeg_backend,
            settings=route.candidate.settings,
            views=ordered,
        )
        self._workspace.write_candidate_metadata(workspace, candidate)
        return candidate

    def _consume_verified_source(
        self,
        root: Path,
        snapshot: RunSnapshot,
        attempt_id: UUID,
        source: SourceOccurrence,
        output_directory: Path,
        bridge: _OwnerCancellationBridge,
        verification_entries: list[dict[str, object]],
    ) -> tuple[MaterializedFrame, ...]:
        route = self._view_route(snapshot)
        path = Path(source.external_locator)
        baseline = (
            self._media.latest_full_evidence(
                root,
                source_id=source.source_id,
                source_revision=source.source_revision,
                content_sha256=source.content_sha256,
            )
            or source.full_hash_evidence.evidence_after
        )
        checked_at = datetime.now(UTC)
        strict = route.verification_policy == VerificationPolicyId.STRICT
        try:
            with self._sources.lease(path, strict=strict) as lease:
                path_before = self._sources.evidence(path)
                if path_before != lease.evidence_before:
                    raise SourceUnstableError(
                        f"Source identity changed while acquiring decode lease: {path}"
                    )
                full_hash = strict or not (
                    baseline.trusted_local and path_before.trusted_local and baseline == path_before
                )
                observed_digest: str | None = None
                rehash_reason: RehashReason | None = None
                if full_hash:
                    rehash_reason = (
                        RehashReason.STRICT_POLICY
                        if strict
                        else self._rehash_reason(baseline, path_before)
                    )
                    hashed = self._sources.hash_lease(lease, bridge)
                    observed_digest = hashed.sha256
                    verification = VerificationResult(
                        verification_id=uuid4(),
                        source_id=source.source_id,
                        source_revision=source.source_revision,
                        expected_content_sha256=source.content_sha256,
                        policy_id=route.verification_policy,
                        checked_at=checked_at,
                        baseline_evidence=baseline,
                        current_evidence=hashed.evidence.evidence_after,
                        full_hash_performed=True,
                        observed_content_sha256=hashed.sha256,
                        rehash_reason=rehash_reason,
                        assurance=VerificationAssurance.CONTENT_VERIFIED,
                        stability_mechanism=lease.stability_mechanism,
                        outcome=(
                            VerificationOutcome.UNCHANGED
                            if hashed.sha256 == source.content_sha256
                            else VerificationOutcome.CHANGED
                        ),
                        diagnostic_code=(
                            "source.content_verified"
                            if hashed.sha256 == source.content_sha256
                            else "source.content_changed"
                        ),
                        diagnostic_message=(
                            "Full hash confirms the registered content"
                            if hashed.sha256 == source.content_sha256
                            else "Full hash differs from the registered content"
                        ),
                    )
                    if hashed.sha256 != source.content_sha256:
                        self._record_verification(
                            root,
                            attempt_id,
                            route,
                            verification_entries,
                            verification,
                            consumed=False,
                        )
                        raise SourceUnstableError(
                            f"Registered source digest changed: {source.source_id}"
                        )
                else:
                    verification = VerificationResult(
                        verification_id=uuid4(),
                        source_id=source.source_id,
                        source_revision=source.source_revision,
                        expected_content_sha256=source.content_sha256,
                        policy_id=route.verification_policy,
                        checked_at=checked_at,
                        baseline_evidence=baseline,
                        current_evidence=path_before,
                        full_hash_performed=False,
                        observed_content_sha256=None,
                        rehash_reason=None,
                        assurance=VerificationAssurance.METADATA_UNCHANGED,
                        stability_mechanism=lease.stability_mechanism,
                        outcome=VerificationOutcome.UNCHANGED,
                        diagnostic_code="source.metadata_unchanged",
                        diagnostic_message="Trusted local source evidence is unchanged",
                    )
                frames = self._materializer.materialize(
                    path,
                    source,
                    output_directory,
                    route.candidate.settings,
                    timeout_seconds=route.resource_limits.per_source_timeout_seconds,
                    expected_backend=route.ffmpeg_backend,
                    cancellation=bridge,
                )
                lease_after = lease.current_evidence()
                path_after = self._sources.evidence(path)
                if lease_after != path_before or path_after != path_before:
                    changed = verification.model_copy(
                        update={
                            "current_evidence": path_after,
                            "assurance": VerificationAssurance.UNAVAILABLE,
                            "outcome": VerificationOutcome.CHANGED,
                            "diagnostic_code": "source.changed_during_consumption",
                            "diagnostic_message": (
                                "Source identity changed during FFmpeg consumption"
                            ),
                        }
                    )
                    self._record_verification(
                        root,
                        attempt_id,
                        route,
                        verification_entries,
                        changed,
                        consumed=False,
                    )
                    raise SourceUnstableError(
                        f"Source changed during FFmpeg consumption: {source.source_id}"
                    )
                if observed_digest is not None and observed_digest != source.content_sha256:
                    raise AssertionError("digest mismatch was not blocked before decode")
                self._record_verification(
                    root,
                    attempt_id,
                    route,
                    verification_entries,
                    verification,
                    consumed=True,
                )
                return frames
        except StrictSourceUnavailableError as exc:
            unavailable = self._unavailable_verification(
                source,
                route.verification_policy,
                baseline,
                checked_at,
                VerificationOutcome.STRICT_UNAVAILABLE,
                str(exc),
            )
            self._record_verification(
                root,
                attempt_id,
                route,
                verification_entries,
                unavailable,
                consumed=False,
            )
            raise
        except SourceUnavailableError as exc:
            outcome = (
                VerificationOutcome.MISSING if exc.missing else VerificationOutcome.UNAVAILABLE
            )
            unavailable = self._unavailable_verification(
                source,
                route.verification_policy,
                baseline,
                checked_at,
                outcome,
                str(exc),
            )
            self._record_verification(
                root,
                attempt_id,
                route,
                verification_entries,
                unavailable,
                consumed=False,
            )
            raise

    def _record_verification(
        self,
        root: Path,
        attempt_id: UUID,
        route: ViewPreparationRoute | SharpestViewPreparationRoute,
        entries: list[dict[str, object]],
        result: VerificationResult,
        *,
        consumed: bool,
    ) -> None:
        self._media.record_verification_under_writer(root, result)
        entries.append(
            {
                "verification_id": str(result.verification_id),
                "source_id": str(result.source_id),
                "source_revision": result.source_revision,
                "registered_digest": result.expected_content_sha256,
                "policy_id": result.policy_id.value,
                "policy_version": result.policy_version,
                "assurance": result.assurance.value,
                "full_hash_performed": result.full_hash_performed,
                "evidence": (
                    result.current_evidence.model_dump(mode="json")
                    if result.current_evidence is not None
                    else None
                ),
                "stability_mechanism": result.stability_mechanism,
                "consumed_under_protected_identity": consumed,
                "outcome": result.outcome.value,
                "checked_at": result.checked_at.isoformat(),
            }
        )
        self._execution.update_attempt_provenance(
            root,
            attempt_id=attempt_id,
            environment=self._ffmpeg_environment(route),
            source_verification={
                "policy": route.verification_policy.value,
                "artifact_backed": False,
                "evidence": entries,
            },
        )

    def _run_quality(
        self,
        root: Path,
        snapshot: RunSnapshot,
        candidate_artifact: ArtifactHandle,
        candidate: CandidateViewSet,
        warnings: list[RunWarning],
        cache_hits: list[str],
    ) -> tuple[ArtifactHandle, QualityReport]:
        route = snapshot.route
        if not isinstance(route, SharpestViewPreparationRoute):
            raise ProjectError("Quality assessment requires the M4 view route")
        node = route.quality
        key = quality_recipe_key(
            candidate=candidate,
            candidate_digest=candidate_artifact.semantic_digest,
            settings=node.settings,
            backend=route.quality_backend,
        )
        cached = self._execution.find_cache(
            root,
            recipe_key=key,
            artifact_type=node.output.artifact_type,
            contract_version=node.output.contract_version,
        )
        if cached.artifact is not None:
            quality = self._execution.load_quality_report(root, cached.artifact)
            validate_quality_against_candidate(quality, candidate)
            if quality.candidate_semantic_digest != candidate_artifact.semantic_digest:
                raise ValueError("Cached QualityReport references different candidate semantics")
            self._execution.bind_cached_output(
                root,
                run_id=snapshot.run_id,
                node_id=node.node_id,
                output_name=node.output.output_name,
                artifact_id=cached.artifact.artifact_id,
            )
            cache_hits.append(node.node_id)
            self._event(
                warnings,
                root,
                snapshot.run_id,
                code="quality.stage.cache_hit",
                node_id=node.node_id,
                details={"artifact_id": str(cached.artifact.artifact_id)},
            )
            return cached.artifact, quality

        self._event(
            warnings,
            root,
            snapshot.run_id,
            code="quality.stage.started",
            node_id=node.node_id,
            details={"total_count": len(candidate.views)},
        )
        attempt = self._execution.begin_attempt(
            root,
            run_id=snapshot.run_id,
            node_id=node.node_id,
            output_name=node.output.output_name,
            recipe_key=key,
            input_artifact_ids=(candidate_artifact.artifact_id,),
            literal_inputs={"quality_settings": node.settings.model_dump(mode="json")},
            environment=route.quality_backend.model_dump(mode="json"),
            source_verification={
                "policy": "artifact_backed",
                "artifact_backed": True,
                "fresh_source_verification": False,
                "evidence": [],
            },
        )
        lineage = (
            ArtifactInputLineage(
                input_name="candidate_views",
                artifact_id=candidate_artifact.artifact_id,
                artifact_type=candidate_artifact.artifact_type,
                contract_version=candidate_artifact.contract_version,
                semantic_digest=candidate_artifact.semantic_digest,
                recipe_key=candidate_artifact.recipe_key,
            ),
        )
        if self._quality_assessor is None:
            raise AssertionError("M4 route was built without a quality assessor")
        candidate_directory = self._execution.artifact_directory(root, candidate_artifact)
        measurements = []
        unavailable = 0
        try:
            for index, view in enumerate(candidate.views):
                self._checkpoint(root, snapshot, attempt.attempt_id)
                measurement = self._quality_assessor.measure(
                    candidate_directory / view.image_path,
                    view,
                    node.settings,
                )
                measurements.append(measurement)
                if measurement.sharpness.availability == MeasurementAvailability.UNAVAILABLE:
                    unavailable += 1
                completed = index + 1
                if completed == len(candidate.views) or completed % 50 == 0:
                    self._event(
                        warnings,
                        root,
                        snapshot.run_id,
                        code="quality.progress",
                        node_id=node.node_id,
                        attempt_id=attempt.attempt_id,
                        details={
                            "completed_count": completed,
                            "total_count": len(candidate.views),
                            "unavailable_count": unavailable,
                        },
                    )
            quality = QualityReport(
                candidate_artifact_id=candidate_artifact.artifact_id,
                candidate_semantic_digest=candidate_artifact.semantic_digest,
                pillow_version=route.quality_backend.pillow_version,
                python_version=route.quality_backend.python_version,
                settings=node.settings,
                measurements=tuple(measurements),
            )
            validate_quality_against_candidate(quality, candidate)
            self._workspace.write_quality_metadata(Path(attempt.workspace), quality)
            self._checkpoint(root, snapshot, attempt.attempt_id)
            artifact = self._execution.publish_attempt(
                root,
                run_id=snapshot.run_id,
                node_id=node.node_id,
                output_name=node.output.output_name,
                artifact_type=node.output.artifact_type,
                contract_version=node.output.contract_version,
                recipe_key=key,
                attempt=attempt,
                input_lineage=lineage,
            )
        except (ExecutionCancelledError, PublicationUnresolvedError):
            raise
        except Exception as exc:
            self._execution.mark_attempt_failed(
                root,
                attempt_id=attempt.attempt_id,
                message=str(exc),
                category=self._non_retryable(),
            )
            raise
        self._event(
            warnings,
            root,
            snapshot.run_id,
            code="quality.stage.published",
            node_id=node.node_id,
            attempt_id=attempt.attempt_id,
            details={
                "artifact_id": str(artifact.artifact_id),
                "measured_count": len(quality.measurements) - unavailable,
                "unavailable_count": unavailable,
            },
        )
        return artifact, quality

    def _run_sharpest_selection(
        self,
        root: Path,
        snapshot: RunSnapshot,
        candidate_artifact: ArtifactHandle,
        candidate: CandidateViewSet,
        quality_artifact: ArtifactHandle,
        quality: QualityReport,
        warnings: list[RunWarning],
        cache_hits: list[str],
    ) -> tuple[ArtifactHandle, SharpestSelectedViewSet]:
        route = snapshot.route
        if not isinstance(route, SharpestViewPreparationRoute):
            raise ProjectError("Sharpest selection requires the M4 view route")
        node = route.selection
        key = sharpest_selection_recipe_key(
            candidate=candidate,
            candidate_digest=candidate_artifact.semantic_digest,
            quality=quality,
            quality_digest=quality_artifact.semantic_digest,
            settings=node.settings,
        )
        cached = self._execution.find_cache(
            root,
            recipe_key=key,
            artifact_type=node.output.artifact_type,
            contract_version=node.output.contract_version,
        )
        if cached.artifact is not None:
            selected = self._execution.load_selected_views(root, cached.artifact)
            if not isinstance(selected, SharpestSelectedViewSet):
                raise ValueError("Cached selected artifact has the wrong M4 payload")
            validate_sharpest_against_inputs(
                selected,
                candidate,
                quality,
                candidate_artifact=candidate_artifact,
                quality_artifact=quality_artifact,
            )
            self._execution.bind_cached_output(
                root,
                run_id=snapshot.run_id,
                node_id=node.node_id,
                output_name=node.output.output_name,
                artifact_id=cached.artifact.artifact_id,
            )
            cache_hits.append(node.node_id)
            self._event(
                warnings,
                root,
                snapshot.run_id,
                code="sharpest.selection.cache_hit",
                node_id=node.node_id,
                details={"artifact_id": str(cached.artifact.artifact_id)},
            )
            return cached.artifact, selected

        self._event(
            warnings,
            root,
            snapshot.run_id,
            code="sharpest.selection.started",
            node_id=node.node_id,
        )
        attempt = self._execution.begin_attempt(
            root,
            run_id=snapshot.run_id,
            node_id=node.node_id,
            output_name=node.output.output_name,
            recipe_key=key,
            input_artifact_ids=(
                candidate_artifact.artifact_id,
                quality_artifact.artifact_id,
            ),
            literal_inputs={"selection_settings": node.settings.model_dump(mode="json")},
            environment={
                "adapter_id": "splatforge.sharpest_interval_python",
                "adapter_version": 1,
            },
            source_verification={"policy": "not_applicable", "evidence": []},
        )
        lineage = (
            ArtifactInputLineage(
                input_name="candidate_views",
                artifact_id=candidate_artifact.artifact_id,
                artifact_type=candidate_artifact.artifact_type,
                contract_version=candidate_artifact.contract_version,
                semantic_digest=candidate_artifact.semantic_digest,
                recipe_key=candidate_artifact.recipe_key,
            ),
            ArtifactInputLineage(
                input_name="quality_report",
                artifact_id=quality_artifact.artifact_id,
                artifact_type=quality_artifact.artifact_type,
                contract_version=quality_artifact.contract_version,
                semantic_digest=quality_artifact.semantic_digest,
                recipe_key=quality_artifact.recipe_key,
            ),
        )
        try:
            selected = select_sharpest_interval(
                candidate,
                quality,
                candidate_artifact=candidate_artifact,
                quality_artifact=quality_artifact,
                settings=node.settings,
                checkpoint=lambda: self._checkpoint(root, snapshot, attempt.attempt_id),
            )
            self._workspace.write_selected_metadata(Path(attempt.workspace), selected)
            self._checkpoint(root, snapshot, attempt.attempt_id)
            artifact = self._execution.publish_attempt(
                root,
                run_id=snapshot.run_id,
                node_id=node.node_id,
                output_name=node.output.output_name,
                artifact_type=node.output.artifact_type,
                contract_version=node.output.contract_version,
                recipe_key=key,
                attempt=attempt,
                input_lineage=lineage,
            )
        except (ExecutionCancelledError, PublicationUnresolvedError):
            raise
        except Exception as exc:
            self._execution.mark_attempt_failed(
                root,
                attempt_id=attempt.attempt_id,
                message=str(exc),
                category=self._non_retryable(),
            )
            raise
        self._event(
            warnings,
            root,
            snapshot.run_id,
            code="sharpest.selection.completed",
            node_id=node.node_id,
            attempt_id=attempt.attempt_id,
            details={
                "selected_count": selected.total_selected_count,
                "rejected_count": selected.total_rejected_count,
                "unsatisfied_interval_count": len(selected.unsatisfied_intervals),
            },
        )
        self._event(
            warnings,
            root,
            snapshot.run_id,
            code="sharpest.selection.published",
            node_id=node.node_id,
            attempt_id=attempt.attempt_id,
            details={"artifact_id": str(artifact.artifact_id)},
        )
        return artifact, selected

    def _run_selection(
        self,
        root: Path,
        snapshot: RunSnapshot,
        candidate_artifact: ArtifactHandle,
        candidate: CandidateViewSet,
        warnings: list[RunWarning],
        cache_hits: list[str],
    ) -> tuple[ArtifactHandle, SelectedViewSet]:
        route = self._view_route(snapshot)
        node = route.selection
        key = selection_recipe_key(
            candidate=candidate,
            candidate_digest=candidate_artifact.semantic_digest,
            settings=node.settings,
        )
        cached = self._execution.find_cache(
            root,
            recipe_key=key,
            artifact_type=node.output.artifact_type,
            contract_version=node.output.contract_version,
        )
        if cached.artifact is not None:
            self._execution.bind_cached_output(
                root,
                run_id=snapshot.run_id,
                node_id=node.node_id,
                output_name=node.output.output_name,
                artifact_id=cached.artifact.artifact_id,
            )
            selected = self._execution.load_selected_views(root, cached.artifact)
            validate_selected_against_candidate(selected, candidate)
            if selected.candidate_semantic_digest != candidate_artifact.semantic_digest:
                raise ValueError("Cached SelectedViewSet references different candidate semantics")
            cache_hits.append(node.node_id)
            self._event(
                warnings,
                root,
                snapshot.run_id,
                code="selection.stage.cache_hit",
                node_id=node.node_id,
                details={"artifact_id": str(cached.artifact.artifact_id)},
            )
            return cached.artifact, selected
        self._event(
            warnings,
            root,
            snapshot.run_id,
            code="selection.stage.started",
            node_id=node.node_id,
        )
        attempt = self._execution.begin_attempt(
            root,
            run_id=snapshot.run_id,
            node_id=node.node_id,
            output_name=node.output.output_name,
            recipe_key=key,
            input_artifact_ids=(candidate_artifact.artifact_id,),
            literal_inputs={"selection_settings": node.settings.model_dump(mode="json")},
            environment={
                "adapter_id": "splatforge.fixed_fps_python",
                "adapter_version": 1,
            },
            source_verification={"policy": "not_applicable", "evidence": []},
        )
        lineage = (
            ArtifactInputLineage(
                input_name="candidate_views",
                artifact_id=candidate_artifact.artifact_id,
                artifact_type=candidate_artifact.artifact_type,
                contract_version=candidate_artifact.contract_version,
                semantic_digest=candidate_artifact.semantic_digest,
                recipe_key=candidate_artifact.recipe_key,
            ),
        )
        try:
            selected = select_fixed_fps(
                candidate,
                candidate_artifact=candidate_artifact,
                settings=node.settings,
            )
            self._workspace.write_selected_metadata(Path(attempt.workspace), selected)
            self._checkpoint(root, snapshot, attempt.attempt_id)
            artifact = self._execution.publish_attempt(
                root,
                run_id=snapshot.run_id,
                node_id=node.node_id,
                output_name=node.output.output_name,
                artifact_type=node.output.artifact_type,
                contract_version=node.output.contract_version,
                recipe_key=key,
                attempt=attempt,
                input_lineage=lineage,
            )
        except (ExecutionCancelledError, PublicationUnresolvedError):
            raise
        except Exception as exc:
            self._execution.mark_attempt_failed(
                root,
                attempt_id=attempt.attempt_id,
                message=str(exc),
                category=self._non_retryable(),
            )
            raise
        self._event(
            warnings,
            root,
            snapshot.run_id,
            code="selection.stage.published",
            node_id=node.node_id,
            attempt_id=attempt.attempt_id,
            details={
                "artifact_id": str(artifact.artifact_id),
                "selected_count": selected.total_selected_count,
            },
        )
        return artifact, selected

    def _checkpoint(self, root: Path, snapshot: RunSnapshot, attempt_id: UUID | None) -> None:
        if self._execution.accept_cancellation(root, run_id=snapshot.run_id, attempt_id=attempt_id):
            self._execution.append_event(
                root,
                snapshot.run_id,
                code="cancellation.accepted",
                attempt_id=attempt_id,
            )
            raise ExecutionCancelledError(attempt_id)

    @staticmethod
    def _build_route(
        *,
        inventory_reference: str,
        inventory_digest: str,
        sources: tuple[SourceOccurrence, ...],
        verification_policy: VerificationPolicyId,
        backend: ExecutableIdentity,
        candidate_settings: CandidatePoolSettings,
        selection_settings: FixedFpsSettings | SharpestIntervalSettings,
        quality_settings: QualityAnalysisSettings | None,
        quality_backend: QualityBackendIdentity | None,
        resource_limits: CandidateResourceLimits,
    ) -> ViewPreparationRoute | SharpestViewPreparationRoute:
        candidate_output = OutputReference(
            node_id="candidate_views",
            output_name="candidate_set",
            artifact_type=CANDIDATE_ARTIFACT_TYPE,
            contract_version=VIEW_ARTIFACT_CONTRACT_VERSION,
        )
        selected_output = OutputReference(
            node_id="selected_views",
            output_name="selected_set",
            artifact_type=SELECTED_ARTIFACT_TYPE,
            contract_version=VIEW_ARTIFACT_CONTRACT_VERSION,
        )
        if isinstance(selection_settings, SharpestIntervalSettings):
            if quality_settings is None or quality_backend is None:
                raise ValueError("M4 route requires resolved quality settings and backend")
            quality_output = OutputReference(
                node_id="quality_assessment",
                output_name="quality_report",
                artifact_type=QUALITY_ARTIFACT_TYPE,
                contract_version=QUALITY_ARTIFACT_CONTRACT_VERSION,
            )
            return SharpestViewPreparationRoute(
                inventory_reference=inventory_reference,
                inventory_content_digest=inventory_digest,
                sources=sources,
                verification_policy=verification_policy,
                ffmpeg_backend=backend,
                quality_backend=quality_backend,
                resource_limits=resource_limits,
                candidate=ViewPreparationNode(
                    settings=candidate_settings,
                    output=candidate_output,
                ),
                quality=QualityAssessmentNode(
                    settings=quality_settings,
                    input=candidate_output,
                    output=quality_output,
                ),
                selection=SharpestIntervalSelectionNode(
                    settings=selection_settings,
                    candidate_input=candidate_output,
                    quality_input=quality_output,
                    output=selected_output,
                ),
                target=selected_output,
            )
        return ViewPreparationRoute(
            inventory_reference=inventory_reference,
            inventory_content_digest=inventory_digest,
            sources=sources,
            verification_policy=verification_policy,
            ffmpeg_backend=backend,
            resource_limits=resource_limits,
            candidate=ViewPreparationNode(
                settings=candidate_settings,
                output=candidate_output,
            ),
            selection=FixedFpsSelectionNode(
                settings=selection_settings,
                input=candidate_output,
                output=selected_output,
            ),
            target=selected_output,
        )

    @staticmethod
    def _select_sources(
        inventory: SourceInventory, source_ids: set[UUID] | None
    ) -> tuple[SourceOccurrence, ...]:
        if source_ids is not None:
            known = {source.source_id for source in inventory.sources}
            unknown = source_ids - known
            if unknown:
                raise ProjectError("Unknown source IDs: " + ", ".join(sorted(map(str, unknown))))
            if not source_ids:
                raise ProjectError("At least one source ID is required")
            selected = [source for source in inventory.sources if source.source_id in source_ids]
        else:
            selected = list(inventory.sources)
        return tuple(
            sorted(selected, key=lambda source: (str(source.source_id), source.source_revision))
        )

    @staticmethod
    def _view_route(
        snapshot: RunSnapshot,
    ) -> ViewPreparationRoute | SharpestViewPreparationRoute:
        if not isinstance(snapshot.route, (ViewPreparationRoute, SharpestViewPreparationRoute)):
            raise ProjectError("Run snapshot does not contain a concrete view route")
        return snapshot.route

    @staticmethod
    def _ffmpeg_environment(
        route: ViewPreparationRoute | SharpestViewPreparationRoute,
    ) -> dict[str, object]:
        return {
            "adapter_id": "splatforge.ffmpeg",
            "adapter_version": FFMPEG_ADAPTER_VERSION,
            "executable": route.ffmpeg_backend.model_dump(mode="json"),
        }

    @staticmethod
    def _unavailable_verification(
        source: SourceOccurrence,
        policy: VerificationPolicyId,
        baseline: SourceEvidence,
        checked_at: datetime,
        outcome: VerificationOutcome,
        message: str,
    ) -> VerificationResult:
        return VerificationResult(
            verification_id=uuid4(),
            source_id=source.source_id,
            source_revision=source.source_revision,
            expected_content_sha256=source.content_sha256,
            policy_id=policy,
            checked_at=checked_at,
            baseline_evidence=baseline,
            current_evidence=None,
            full_hash_performed=False,
            observed_content_sha256=None,
            rehash_reason=None,
            assurance=VerificationAssurance.UNAVAILABLE,
            stability_mechanism=None,
            outcome=outcome,
            diagnostic_code=f"source.{outcome.value}",
            diagnostic_message=message[:1024] or "Source verification is unavailable",
        )

    @staticmethod
    def _rehash_reason(baseline: SourceEvidence, current: SourceEvidence) -> RehashReason:
        if current.storage_kind.value != "local_fixed":
            return RehashReason.UNTRUSTED_STORAGE
        if not baseline.trusted_local or not current.trusted_local:
            return RehashReason.INSUFFICIENT_EVIDENCE
        if baseline.volume_id != current.volume_id or baseline.file_id != current.file_id:
            return RehashReason.IDENTITY_CHANGED
        return RehashReason.METADATA_CHANGED

    @staticmethod
    def _non_retryable() -> FailureCategory:
        return FailureCategory.NON_RETRYABLE

    def _event(
        self,
        warnings: list[RunWarning],
        root: Path,
        run_id: UUID,
        *,
        code: str,
        node_id: str | None = None,
        attempt_id: UUID | None = None,
        details: dict[str, object] | None = None,
    ) -> None:
        warning = self._execution.append_event(
            root,
            run_id,
            code=code,
            node_id=node_id,
            attempt_id=attempt_id,
            details=details,
        )
        if warning is not None:
            warnings.append(warning)
