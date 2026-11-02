"""Validated, metadata-only readback of immutable Prepare Data publications."""

from pathlib import Path
from uuid import UUID

from splatforge.adapters.execution_storage import LocalExecutionRepository
from splatforge.application.desktop_prepare import PrepareRequest, PrepareSummary
from splatforge.application.execution import ExecutionProject
from splatforge.core.execution import (
    ArtifactHandle,
    SharpestViewPreparationRoute,
    ViewPreparationRoute,
)
from splatforge.core.media import MediaType
from splatforge.core.quality import (
    MeasurementAvailability,
    QualityReport,
    SharpestSelectedViewSet,
)


class LocalPrepareReader:
    def __init__(self, repository: LocalExecutionRepository | None = None) -> None:
        self._repository = repository or LocalExecutionRepository()

    def project(self, root: Path) -> ExecutionProject:
        return self._repository.inspect_project(root)

    def results(self, root: Path) -> tuple[PrepareSummary, ...]:
        if self.project(root).state_version < 3:
            return ()
        # Identify the automatic selector through its producer, including cache-hit
        # bindings, before limiting history. Review attempts persist `selection`
        # instead; their candidate/selected bindings must not crowd out Prepare runs.
        # The bounded summaries below still validate each exact automatic route.
        with self._repository._read_connection(root) as connection:
            rows = connection.execute(
                "SELECT r.run_id FROM runs r WHERE r.status='succeeded' "
                "AND EXISTS (SELECT 1 FROM run_outputs o WHERE o.run_id=r.run_id "
                "AND o.node_id='candidate_views' AND o.output_name='candidate_set') "
                "AND EXISTS (SELECT 1 FROM run_outputs o "
                "JOIN artifacts a ON a.artifact_id=o.artifact_id "
                "JOIN attempts producer ON producer.attempt_id=a.producer_attempt_id "
                "WHERE o.run_id=r.run_id AND o.node_id='selected_views' "
                "AND o.output_name='selected_set' "
                "AND json_type(producer.literal_inputs_json,'$.selection_settings')='object') "
                "ORDER BY r.started_at DESC,r.run_id DESC LIMIT 25"
            ).fetchall()
        summaries = []
        with self._repository.validation_operation():
            for row in rows:
                try:
                    summaries.append(self.summary(root, UUID(row[0])))
                except (ValueError, OSError):
                    # Unavailable/corrupt/evicted historical publications are not ready results.
                    # Explicit summary inspection still raises its actionable error.
                    continue
        return tuple(summaries)

    def summary(self, root: Path, run_id: UUID) -> PrepareSummary:
        with self._repository.validation_operation():
            return self._summary(root, run_id)

    def _summary(self, root: Path, run_id: UUID) -> PrepareSummary:
        repo = self._repository
        snapshot = repo._load_run_snapshot(root, run_id)
        route = snapshot.route
        if not isinstance(route, (ViewPreparationRoute, SharpestViewPreparationRoute)):
            raise ValueError("Prepare Data review requires an exact views preparation run")
        candidate_handle = repo.resolve_run_output(root, run_id, "candidate_views", "candidate_set")
        selected_handle = repo.resolve_run_output(root, run_id, "selected_views", "selected_set")
        candidate, selected = repo.load_pairing_inputs(root, candidate_handle, selected_handle)
        if (candidate.settings != route.candidate.settings
                or candidate.backend != route.ffmpeg_backend):
            raise ValueError("Prepared candidate settings/backend differ from the frozen run")
        if selected.settings != route.selection.settings:
            raise ValueError("Prepared selection settings differ from the frozen run")
        quality = None
        with repo._read_connection(root) as connection:
            bindings = connection.execute(
                "SELECT o.node_id,o.output_name,o.binding_kind,a.artifact_id,a.artifact_type,"
                "a.contract_version,a.recipe_key,a.semantic_digest,a.manifest_path "
                "FROM run_outputs o JOIN artifacts a ON a.artifact_id=o.artifact_id "
                "WHERE o.run_id=? ORDER BY o.node_id,o.output_name", (str(run_id),),
            ).fetchall()
        if isinstance(route, SharpestViewPreparationRoute):
            row = next((r for r in bindings if r[:2] == (
                route.quality.node_id, route.quality.output.output_name,
            )), None)
            if row is None or not isinstance(selected, SharpestSelectedViewSet):
                raise ValueError("Sharpest preparation has no exact quality/selection binding")
            handle = ArtifactHandle(
                artifact_id=UUID(row[3]), artifact_type=row[4], contract_version=row[5],
                recipe_key=row[6], semantic_digest=row[7], manifest_path=row[8],
            )
            if (handle.artifact_id != selected.quality_artifact_id
                    or handle.semantic_digest != selected.quality_semantic_digest):
                raise ValueError("Prepared selection quality binding differs from its lineage")
            quality = repo._validate_indexed_artifact(root, handle, metadata_only=True)[2].parsed
            if not isinstance(quality, QualityReport):
                raise ValueError("Prepare Data quality binding is not a quality report")
            if quality.settings != route.quality.settings:
                raise ValueError("Prepared quality settings differ from the frozen run")
        elif isinstance(selected, SharpestSelectedViewSet):
            raise ValueError("Fixed-FPS preparation has an incompatible selection binding")
        warnings = []
        unavailable = measured = None
        if quality is not None:
            measured = sum(
                q.sharpness.availability == MeasurementAvailability.AVAILABLE
                for q in quality.measurements
            )
            unavailable = len(quality.measurements) - measured
            if unavailable:
                warnings.append(f"Quality measurement unavailable for {unavailable} candidates")
        rejected = selected.total_rejected_count if isinstance(
            selected, SharpestSelectedViewSet,
        ) else 0
        unsatisfied = len(selected.unsatisfied_intervals) if isinstance(
            selected, SharpestSelectedViewSet,
        ) else len(selected.unsatisfied_slots)
        if unsatisfied:
            warnings.append(f"{unsatisfied} selection intervals or target slots were unsatisfied")
        return PrepareSummary(
            run_id=run_id, created_at=snapshot.created_at, project_id=snapshot.project_id,
            project_revision=snapshot.project_revision,
            request=PrepareRequest(
                candidate=route.candidate.settings, selection=route.selection.settings,
                quality=route.quality.settings if isinstance(
                    route, SharpestViewPreparationRoute,
                ) else None,
                limits=route.resource_limits, verification_policy=route.verification_policy,
            ),
            candidate_count=len(candidate.views), selected_count=selected.total_selected_count,
            rejected_count=rejected, quality_measured_count=measured,
            quality_unavailable_count=unavailable, method_id=selected.selection_method_id,
            cache_hits=tuple(row[0] for row in bindings if row[2] == "cache_hit"),
            warnings=tuple(warnings),
            photo_count=sum(source.media_type == MediaType.PHOTO for source in route.sources),
            video_count=sum(source.media_type == MediaType.VIDEO for source in route.sources),
        )
