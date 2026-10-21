from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest
from test_views_execution import (
    FakeProbe,
    Harness,
    candidate_settings,
    harness,
    limits,
    prepare,
    query,
)

from splatforge.adapters.execution_storage import (
    ExecutionFaultHooks,
    LocalExecutionRepository,
)
from splatforge.adapters.fake_stages import LocalFakeStages
from splatforge.adapters.project_storage import LocalProjectStore
from splatforge.adapters.view_workspace import LocalViewWorkspace
from splatforge.application.execution import (
    FakeExecutionService,
    PublicationUnresolvedError,
)
from splatforge.application.media import MediaService
from splatforge.application.views import ViewsService
from splatforge.core.media import VerificationPolicyId
from splatforge.core.quality import (
    DuplicateMeasurement,
    MeasurementAvailability,
    NonNegativeRational,
    QualityAnalysisSettings,
    QualityBackendIdentity,
    SharpestIntervalSettings,
    SharpnessMeasurement,
    ViewQualityMeasurement,
)
from splatforge.core.views import parse_fps


class FakeQualityAssessor:
    def __init__(self) -> None:
        self.calls: list[UUID] = []
        self.on_measure = None

    def identity(self) -> QualityBackendIdentity:
        return QualityBackendIdentity(
            pillow_version="12.3.0-test",
            python_version="3.12-test",
        )

    def measure(self, image_path, view, settings):  # type: ignore[no-untyped-def]
        assert image_path.name == Path(view.image_path).name
        self.calls.append(view.view_id)
        if self.on_measure is not None:
            self.on_measure(len(self.calls))
        timestamp = (
            view.presentation_timestamp.pts if view.presentation_timestamp is not None else 100
        )
        return ViewQualityMeasurement(
            view_id=view.view_id,
            candidate_image_sha256=view.image_sha256,
            sharpness=SharpnessMeasurement(
                availability=MeasurementAvailability.AVAILABLE,
                score=NonNegativeRational(numerator=timestamp + 1, denominator=1),
            ),
            duplicate=DuplicateMeasurement(
                availability=MeasurementAvailability.AVAILABLE,
                dhash64=f"{view.view_id.int & ((1 << 64) - 1):016x}",
            ),
        )


def with_quality(value: Harness) -> FakeQualityAssessor:
    quality = FakeQualityAssessor()
    value.service = ViewsService(
        value.execution,
        value.media,
        value.sources,
        value.materializer,
        LocalViewWorkspace(free_bytes=lambda _path: 10**9),
        quality,
    )
    return quality


def sharp_prepare(
    value: Harness,
    *,
    target: str = "1",
    candidate_fps: str = "2",
    quality_max_side: int = 1024,
    minimum: str | None = None,
    duplicate_threshold: int = 4,
    duplicate_lookback: int = 8,
):
    return value.service.prepare(
        value.root,
        candidate_settings=candidate_settings(candidate_fps),
        quality_settings=QualityAnalysisSettings(quality_max_side=quality_max_side),
        selection_settings=SharpestIntervalSettings(
            target_fps=parse_fps(target),
            min_sharpness=(
                NonNegativeRational(numerator=int(minimum), denominator=1)
                if minimum is not None
                else None
            ),
            reject_duplicates=False,
            duplicate_hamming_threshold=duplicate_threshold,
            duplicate_lookback=duplicate_lookback,
        ),
        resource_limits=limits(),
        verification_policy=VerificationPolicyId.BALANCED_LOCAL,
    )


def test_three_stage_route_reuses_cache_and_policy_changes_only_selection(
    tmp_path: Path,
) -> None:
    value = harness(tmp_path)
    quality = with_quality(value)

    first = sharp_prepare(value)
    assert first.status == "succeeded"
    assert first.cache_hits == ()
    assert first.quality_artifact is not None
    assert first.candidate_count == 4
    assert first.quality_measured_count == 4
    assert first.quality_unavailable_count == 0
    assert [row[0] for row in query(value.root, "SELECT node_id FROM attempts")] == [
        "candidate_views",
        "quality_assessment",
        "selected_views",
    ]
    assert len(quality.calls) == 4

    identical = sharp_prepare(value)
    assert identical.cache_hits == (
        "candidate_views",
        "quality_assessment",
        "selected_views",
    )
    assert query(
        value.root,
        "SELECT count(*) FROM attempts WHERE run_id=?",
        (str(identical.run_id),),
    ) == [(0,)]
    assert len(quality.calls) == 4

    threshold = sharp_prepare(value, minimum="8")
    assert threshold.cache_hits == ("candidate_views", "quality_assessment")
    duplicate = sharp_prepare(value, duplicate_threshold=5)
    assert duplicate.cache_hits == ("candidate_views", "quality_assessment")
    lookback = sharp_prepare(value, duplicate_lookback=4)
    assert lookback.cache_hits == ("candidate_views", "quality_assessment")
    changed_target = sharp_prepare(value, target="1/2", candidate_fps="2")
    assert changed_target.cache_hits == ("candidate_views", "quality_assessment")

    resized = sharp_prepare(value, quality_max_side=512)
    assert resized.cache_hits == ("candidate_views",)
    assert len(quality.calls) == 8

    changed_candidate = sharp_prepare(value, candidate_fps="4")
    assert changed_candidate.cache_hits == ()
    assert len(value.materializer.calls) == 4


def test_fixed_fps_route_still_creates_no_quality_attempt(tmp_path: Path) -> None:
    value = harness(tmp_path)
    quality = with_quality(value)
    result = prepare(value)
    assert result.quality_artifact is None
    assert result.quality_measured_count == 0
    assert quality.calls == []
    assert query(
        value.root,
        "SELECT count(*) FROM attempts WHERE node_id='quality_assessment'",
    ) == [(0,)]


def test_locator_only_relink_reuses_candidate_quality_and_selection(
    tmp_path: Path,
) -> None:
    value = harness(tmp_path, mixed=False)
    with_quality(value)
    first = sharp_prepare(value)
    replacement = tmp_path / "moved clip.mp4"
    replacement.write_bytes(value.source_paths[0].read_bytes())
    MediaService(value.media, value.sources, FakeProbe()).relink(
        value.root, value.source_ids[0], replacement
    )
    second = sharp_prepare(value)
    assert second.cache_hits == (
        "candidate_views",
        "quality_assessment",
        "selected_views",
    )
    assert second.candidate_artifact.artifact_id == first.candidate_artifact.artifact_id
    assert second.quality_artifact.artifact_id == first.quality_artifact.artifact_id
    assert second.selected_artifact.artifact_id == first.selected_artifact.artifact_id


def test_photo_only_sharpest_does_not_require_doubled_candidate_fps(
    tmp_path: Path,
) -> None:
    value = harness(tmp_path, mixed=True)
    with_quality(value)
    photo_source = value.source_ids[1]
    result = value.service.prepare(
        value.root,
        candidate_settings=candidate_settings("1"),
        quality_settings=QualityAnalysisSettings(),
        selection_settings=SharpestIntervalSettings(
            target_fps=parse_fps("1"), reject_duplicates=False
        ),
        resource_limits=limits(),
        verification_policy=VerificationPolicyId.BALANCED_LOCAL,
        source_ids={photo_source},
    )
    assert result.status == "succeeded"
    assert result.selected_count == 1


def test_cancel_during_quality_keeps_candidate_reusable(tmp_path: Path) -> None:
    value = harness(tmp_path)
    quality = with_quality(value)

    def request_after_first(call_count: int) -> None:
        if call_count != 1:
            return
        run_id = UUID(
            query(
                value.root,
                "SELECT run_id FROM runs WHERE status='running' ORDER BY created_at DESC",
            )[0][0]
        )
        value.execution.request_cancellation(value.root, run_id=run_id)

    quality.on_measure = request_after_first
    cancelled = sharp_prepare(value)
    assert cancelled.status == "cancelled"
    assert cancelled.candidate_artifact is not None
    assert cancelled.quality_artifact is None
    assert query(
        value.root,
        "SELECT count(*) FROM artifacts WHERE artifact_type='views.quality_report'",
    ) == [(0,)]

    quality.on_measure = None
    rerun = sharp_prepare(value)
    assert rerun.status == "succeeded"
    assert rerun.cache_hits == ("candidate_views",)


def test_corrupt_quality_rebuilds_quality_and_selection_only(tmp_path: Path) -> None:
    value = harness(tmp_path)
    quality = with_quality(value)
    first = sharp_prepare(value)
    assert first.quality_artifact is not None
    quality_path = value.root / first.quality_artifact.manifest_path
    metadata = quality_path.parent / "quality_report.json"
    metadata.write_text("{}", encoding="utf-8")

    rerun = sharp_prepare(value)
    assert rerun.status == "succeeded"
    assert rerun.cache_hits == ("candidate_views",)
    assert len(quality.calls) == 8


def test_corrupt_sharpest_output_rebuilds_only_selection(tmp_path: Path) -> None:
    value = harness(tmp_path)
    quality = with_quality(value)
    first = sharp_prepare(value)
    selected_path = value.root / first.selected_artifact.manifest_path
    (selected_path.parent / "selected_views.json").write_text("{}", encoding="utf-8")

    rerun = sharp_prepare(value)
    assert rerun.status == "succeeded"
    assert rerun.cache_hits == ("candidate_views", "quality_assessment")
    assert len(quality.calls) == 4


def _service_with_execution(
    value: Harness,
    execution: LocalExecutionRepository,
    quality: FakeQualityAssessor,
) -> ViewsService:
    return ViewsService(
        execution,
        value.media,
        value.sources,
        value.materializer,
        LocalViewWorkspace(free_bytes=lambda _path: 10**9),
        quality,
    )


def _sharp_prepare_service(service: ViewsService, value: Harness):
    return service.prepare(
        value.root,
        candidate_settings=candidate_settings("2"),
        quality_settings=QualityAnalysisSettings(),
        selection_settings=SharpestIntervalSettings(
            target_fps=parse_fps("1"), reject_duplicates=False
        ),
        resource_limits=limits(),
        verification_policy=VerificationPolicyId.BALANCED_LOCAL,
    )


def test_moved_quality_orphan_is_adopted_with_exact_candidate_lineage(
    tmp_path: Path,
) -> None:
    value = harness(tmp_path, mixed=False)
    raised = False

    def fail_once(path: Path) -> None:
        nonlocal raised
        if not raised and path.parent.name == "quality_assessment":
            raised = True
            raise OSError("crash after quality move")

    execution = LocalExecutionRepository(
        project_store=LocalProjectStore(),
        fault_hooks=ExecutionFaultHooks(after_artifact_move=fail_once),
    )
    quality = FakeQualityAssessor()
    with pytest.raises(PublicationUnresolvedError):
        _sharp_prepare_service(_service_with_execution(value, execution, quality), value)
    run_id = UUID(query(value.root, "SELECT run_id FROM runs")[0][0])
    recovered = FakeExecutionService(execution, LocalFakeStages()).recover(value.root, run_id)
    assert recovered.status == "interrupted"
    assert len(recovered.adopted_attempts) == 1

    restarted = _sharp_prepare_service(
        _service_with_execution(
            value,
            LocalExecutionRepository(project_store=LocalProjectStore()),
            quality,
        ),
        value,
    )
    assert restarted.cache_hits == ("candidate_views", "quality_assessment")


def test_moved_sharpest_orphan_is_adopted_and_finalizes_run(tmp_path: Path) -> None:
    value = harness(tmp_path, mixed=False)

    def fail_after_move(path: Path) -> None:
        if path.parent.name == "selected_views":
            raise OSError("crash after selection move")

    execution = LocalExecutionRepository(
        project_store=LocalProjectStore(),
        fault_hooks=ExecutionFaultHooks(after_artifact_move=fail_after_move),
    )
    quality = FakeQualityAssessor()
    with pytest.raises(PublicationUnresolvedError):
        _sharp_prepare_service(_service_with_execution(value, execution, quality), value)
    run_id = UUID(query(value.root, "SELECT run_id FROM runs")[0][0])
    recovered = FakeExecutionService(execution, LocalFakeStages()).recover(value.root, run_id)
    assert recovered.status == "succeeded"
    assert len(recovered.adopted_attempts) == 1
    assert query(value.root, "SELECT count(*) FROM artifacts") == [(3,)]


def test_corrupt_moved_quality_orphan_is_not_adopted(tmp_path: Path) -> None:
    value = harness(tmp_path, mixed=False)

    def fail_after_move(path: Path) -> None:
        if path.parent.name == "quality_assessment":
            raise OSError("crash after quality move")

    execution = LocalExecutionRepository(
        project_store=LocalProjectStore(),
        fault_hooks=ExecutionFaultHooks(after_artifact_move=fail_after_move),
    )
    with pytest.raises(PublicationUnresolvedError):
        _sharp_prepare_service(
            _service_with_execution(value, execution, FakeQualityAssessor()), value
        )
    row = query(
        value.root,
        "SELECT run_id, expected_artifact_id FROM attempts WHERE node_id='quality_assessment'",
    )[0]
    artifact = value.root / "artifacts" / "quality_assessment" / row[1]
    (artifact / "quality_report.json").write_text("{}", encoding="utf-8")
    recovered = FakeExecutionService(execution, LocalFakeStages()).recover(value.root, UUID(row[0]))
    assert recovered.status == "interrupted"
    assert recovered.adopted_attempts == ()
    assert recovered.warnings[0].code == "orphan.publication_refused"


class CancelAfterQualityRepository(LocalExecutionRepository):
    def publish_attempt(self, root: Path, **kwargs):  # type: ignore[no-untyped-def]
        artifact = super().publish_attempt(root, **kwargs)
        if kwargs["artifact_type"] == "views.quality_report":
            self.request_cancellation(root, run_id=kwargs["run_id"])
        return artifact


class CancelDuringSelectionRepository(LocalExecutionRepository):
    def begin_attempt(self, root: Path, **kwargs):  # type: ignore[no-untyped-def]
        attempt = super().begin_attempt(root, **kwargs)
        if kwargs["node_id"] == "selected_views":
            self.request_cancellation(root, run_id=kwargs["run_id"])
        return attempt


def test_cancel_after_quality_publication_reuses_quality_on_restart(
    tmp_path: Path,
) -> None:
    value = harness(tmp_path, mixed=False)
    quality = FakeQualityAssessor()
    execution = CancelAfterQualityRepository(project_store=LocalProjectStore())
    cancelled = _sharp_prepare_service(_service_with_execution(value, execution, quality), value)
    assert cancelled.status == "cancelled"
    assert cancelled.quality_artifact is not None
    assert cancelled.selected_artifact is None

    restarted = _sharp_prepare_service(
        _service_with_execution(
            value,
            LocalExecutionRepository(project_store=LocalProjectStore()),
            quality,
        ),
        value,
    )
    assert restarted.cache_hits == ("candidate_views", "quality_assessment")


def test_cancel_during_selection_publishes_no_partial_selected_artifact(
    tmp_path: Path,
) -> None:
    value = harness(tmp_path, mixed=False)
    execution = CancelDuringSelectionRepository(project_store=LocalProjectStore())
    cancelled = _sharp_prepare_service(
        _service_with_execution(value, execution, FakeQualityAssessor()), value
    )
    assert cancelled.status == "cancelled"
    assert cancelled.quality_artifact is not None
    assert cancelled.selected_artifact is None
    assert query(
        value.root,
        "SELECT count(*) FROM artifacts WHERE artifact_type='views.selected_set'",
    ) == [(0,)]
