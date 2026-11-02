"""Direct Prepare settings use exact intent and existing processing contracts."""

from datetime import UTC, datetime
from fractions import Fraction
from uuid import uuid4

import pytest
from test_quality_execution import sharp_prepare, with_quality
from test_views_execution import harness

from splatforge.adapters.desktop_prepare import LocalPrepareReader
from splatforge.application.desktop import IndexRow
from splatforge.application.desktop_prepare import PrepareService, preparation_request
from splatforge.application.media import MediaService
from splatforge.application.prepare_settings import (
    preparation_media_context,
    preparation_request_fields,
    prepare_settings_draft,
    prepare_settings_fields,
    prepare_target_fps,
    resolve_preparation_request,
)
from splatforge.application.projects import StaleProjectRevisionError
from splatforge.bootstrap import build_project_service
from splatforge.core.models import PipelineConfig
from splatforge.core.project import ProjectDocument, settings_from_pipeline
from splatforge.core.quality import SharpestIntervalSettings
from splatforge.core.source_participation import SourceParticipationIntent
from splatforge.core.video_usage import VideoUsageEntry, VideoUsageIntent, interval
from splatforge.core.views import FixedFpsSettings, parse_fps


@pytest.fixture
def document():
    return ProjectDocument(
        project_format_version=1, project_id=uuid4(), revision=1, label="Exact Prepare",
        created_at=datetime.now(UTC), updated_at=datetime.now(UTC),
        inventory_reference=None, preset_provenance=None,
        settings=settings_from_pipeline(PipelineConfig()),
    )


def changed(document, **values):
    return prepare_settings_draft(document, {**prepare_settings_fields(document), **values})


@pytest.mark.parametrize("seconds,fps", [("0.1", "10"), ("2/3", "3/2"),
                                            ("1.001", "1000/1001")])
def test_exact_interval_is_only_target_input(document, seconds, fps):
    target = prepare_target_fps(seconds)
    assert target == parse_fps(fps)
    draft = changed(document, interval_seconds=seconds, candidate_fps=str(2 * Fraction(fps)))
    assert preparation_request(draft).selection.target_fps == target
    assert prepare_settings_fields(draft)["interval_seconds"] == str(Fraction(seconds))
    with pytest.raises(ValueError, match="fields mismatch"):
        changed(document, target_fps="99")


@pytest.mark.parametrize("value", ["", "0", "-1", "nan", "inf", "1/0", 0.1])
def test_invalid_interval_refuses_binary_or_nonpositive_time(value):
    with pytest.raises(ValueError, match="interval|Interval"):
        prepare_target_fps(value)


def test_legacy_conversion_preserves_unrelated_intent_and_opaque_backup(document):
    frame = document.settings.frame_selection.model_copy(update={"future_metadata": {"x": [1]}})
    future_mapping = document.settings.mapping.model_copy(update={
        "method_id": "mapping.future", "settings_schema_version": 99,
    })
    document = document.model_copy(update={"settings": document.settings.model_copy(update={
        "frame_selection": frame, "mapping": future_mapping,
    })})
    request = preparation_request(document)
    assert isinstance(request.selection, SharpestIntervalSettings)
    assert request.candidate.candidate_fps == parse_fps("4")
    draft = changed(document, interval_seconds="2/3", candidate_fps="5", quality_max_side="2048")
    extension = draft.settings.frame_selection.model_extra["prepare_data"]
    assert extension["schema_version"] == 1
    assert extension["legacy_settings"] == frame.settings
    assert draft.settings.frame_selection.model_extra["future_metadata"] == {"x": [1]}
    assert draft.settings.mapping == future_mapping
    assert draft.video_usage == document.video_usage
    reopened = ProjectDocument.model_validate_json(draft.model_dump_json())
    assert prepare_settings_fields(reopened) == prepare_settings_fields(draft)
    assert resolve_preparation_request(reopened) == resolve_preparation_request(draft)
    extension["other_extension"] = {"untouched": True}
    second = changed(draft, candidate_fps="6")
    assert second.settings.frame_selection.model_extra["prepare_data"]["other_extension"] == {
        "untouched": True,
    }


@pytest.mark.parametrize("update", [
    {"method_id": "frame_selection.future"}, {"settings_schema_version": 2},
    {"prepare_data": {"schema_version": 2, "future": [1]}},
    {"prepare_data": {"schema_version": True}},
])
def test_unknown_prepare_contract_is_refused_without_rewriting(document, update):
    frame = document.settings.frame_selection.model_copy(update=update)
    future = document.model_copy(update={"settings": document.settings.model_copy(update={
        "frame_selection": frame,
    })})
    snapshot = future.model_dump_json()
    fields = prepare_settings_fields(document)
    for action in [lambda: prepare_settings_fields(future),
                   lambda: prepare_settings_draft(future, fields),
                   lambda: resolve_preparation_request(future)]:
        with pytest.raises(ValueError, match="Unsupported"):
            action()
    assert future.model_dump_json() == snapshot


def test_threshold_none_zero_and_independent_duplicate_toggle(document):
    defaults = preparation_request(document)
    assert defaults.selection.min_sharpness is None
    assert defaults.selection.reject_duplicates
    assert defaults.selection.duplicate_hamming_threshold == 4
    assert defaults.selection.duplicate_lookback == 8
    with pytest.raises(ValueError, match="minimum sharpness threshold"):
        changed(document, min_sharpness_enabled=True, min_sharpness="")
    zero = changed(document, min_sharpness_enabled=True, min_sharpness="0")
    assert preparation_request(zero).selection.min_sharpness.as_fraction() == 0
    disabled = changed(zero, min_sharpness_enabled=False, min_sharpness="invalid",
                       reject_duplicates=False, duplicate_hamming_threshold="invalid",
                       duplicate_lookback="")
    request = preparation_request(disabled)
    assert request.selection.min_sharpness is None
    assert not request.selection.reject_duplicates
    assert request.selection.duplicate_hamming_threshold == 4
    assert request.selection.duplicate_lookback == 8


@pytest.mark.parametrize("field,value", [
    ("quality_max_side", "63"), ("quality_max_side", "4097"),
    ("jpeg_qscale", "32"), ("duplicate_hamming_threshold", "65"),
    ("duplicate_lookback", "0"), ("candidate_fps", "0"),
])
def test_active_bounds_rejected(document, field, value):
    with pytest.raises(ValueError):
        changed(document, **{field: value})


def test_fixed_and_format_inactive_fields_canonicalize(document):
    fixed = changed(document, method="fixed_fps", image_format="png",
                    jpeg_qscale="invalid", png_compression_level="9",
                    quality_max_side="invalid", min_sharpness_enabled=True,
                    min_sharpness="invalid", reject_duplicates=True,
                    duplicate_hamming_threshold="invalid")
    request = preparation_request(fixed)
    assert isinstance(request.selection, FixedFpsSettings) and request.quality is None
    assert request.candidate.encoding.jpeg_qscale is None
    assert request.candidate.encoding.png_compression_level == 9
    assert preparation_request_fields(request)["reject_duplicates"] is False
    assert prepare_settings_fields(fixed)["reject_duplicates"] is True
    jpeg = changed(fixed, image_format="jpeg", jpeg_qscale="31", png_compression_level="invalid")
    assert preparation_request(jpeg).candidate.encoding.png_compression_level is None
    assert preparation_request(jpeg).candidate.encoding.jpeg_qscale == 31


def test_density_uses_actual_media_and_photo_resolution_preserves_saved_intent(document):
    with pytest.raises(ValueError, match=r"2 \* target"):
        changed(document, candidate_fps="3")
    with pytest.raises(ValueError, match="greater than or equal"):
        changed(document, method="fixed_fps", candidate_fps="1")
    original = changed(document, interval_seconds="2/3", candidate_fps="4",
                       duplicate_hamming_threshold="9", duplicate_lookback="13")
    fields = {**prepare_settings_fields(original), "interval_seconds": "invalid",
              "candidate_fps": "invalid", "duplicate_hamming_threshold": "invalid"}
    draft = prepare_settings_draft(original, fields, has_video=False)
    assert preparation_request(draft) == preparation_request(original)
    photo = resolve_preparation_request(draft, has_video=False)
    assert photo.candidate.candidate_fps == photo.selection.target_fps == parse_fps("1")
    assert not photo.selection.reject_duplicates
    assert photo.selection.duplicate_hamming_threshold == 4
    assert photo.selection.duplicate_lookback == 8
    assert resolve_preparation_request(draft, has_video=True) == preparation_request(original)


def rows():
    video, photo = uuid4(), uuid4()
    return (
        IndexRow(identity=video, values={"type": "video", "sha256": "a" * 64,
                                        "streamIndex": 0, "timelineStart": "10", "duration": "5"}),
        IndexRow(identity=photo, values={"type": "photo"}),
    )


def test_media_context_uses_inclusion_trim_and_content_identity(document):
    media = rows()
    assert preparation_media_context(document, media) == {
        "photo_count": 1, "video_count": 1, "used_video_count": 1, "has_video": True,
    }
    entry = VideoUsageEntry(source_id=media[0].identity, content_sha256="a" * 64,
                            stream_index=0, intervals=())
    empty = document.model_copy(update={"video_usage": VideoUsageIntent(entries=(entry,))})
    assert preparation_media_context(empty, media)["has_video"] is False
    assert preparation_media_context(empty, media)["video_count"] == 1
    excluded = document.model_copy(update={"source_participation": SourceParticipationIntent(
        excluded_source_ids=(media[0].identity,),
    )})
    assert preparation_media_context(excluded, media)["video_count"] == 0
    mismatch = empty.model_copy(update={"video_usage": VideoUsageIntent(entries=(
        entry.model_copy(update={"content_sha256": "b" * 64}),
    ))})
    with pytest.raises(ValueError, match="different media"):
        preparation_media_context(mismatch, media)
    bounds = empty.model_copy(update={"video_usage": VideoUsageIntent(entries=(
        entry.model_copy(update={"intervals": (interval("0", "1"),)}),
    ))})
    with pytest.raises(ValueError, match="outside"):
        preparation_media_context(bounds, media)


def test_saved_request_delegates_and_historical_summary_keeps_exact_settings(tmp_path):
    value = harness(tmp_path)
    with_quality(value)
    projects = build_project_service()
    document = projects.open(value.root)
    document = projects.save(value.root, changed(
        document, interval_seconds="1", candidate_fps="2", image_format="png",
        png_compression_level="3", quality_max_side="64", reject_duplicates=False,
        min_sharpness_enabled=True, min_sharpness="0",
    ))
    service = PrepareService(LocalPrepareReader(value.execution),
                             MediaService(value.media, value.sources, None), value.service)
    expected = {"expected_project_id": document.project_id, "expected_revision": document.revision}
    plan = service.plan(value.root, **expected)
    assert plan.runnable and plan.request == preparation_request(document)
    result = service.run(value.root, plan.request, **expected)
    assert result.status == "succeeded"
    summary = LocalPrepareReader(value.execution).summary(value.root, result.run_id)
    assert summary.request == plan.request
    assert (summary.photo_count, summary.video_count) == (1, 1)
    projects.save(value.root, changed(document, candidate_fps="3"))
    historical = LocalPrepareReader(value.execution).summary(value.root, result.run_id)
    assert historical.request == plan.request
    with pytest.raises(StaleProjectRevisionError):
        service.run(value.root, plan.request, **expected)
    current = projects.open(value.root)
    with pytest.raises(ValueError, match="exact saved"):
        service.run(value.root, plan.request, expected_project_id=current.project_id,
                    expected_revision=current.revision)


def test_photo_only_plan_and_delegate_publish_same_canonical_request(tmp_path, monkeypatch):
    value = harness(tmp_path)
    projects = build_project_service()
    document = projects.open(value.root)
    video = value.media.load_current_inventory(value.root, document).sources[0]
    document = projects.save(value.root, document.model_copy(update={
        "video_usage": VideoUsageIntent(entries=(VideoUsageEntry(
            source_id=video.source_id, content_sha256=video.content_sha256,
            stream_index=video.probe.selected_visual_stream_index, intervals=(),
        ),)),
    }))
    service = PrepareService(LocalPrepareReader(value.execution),
                             MediaService(value.media, value.sources, None), value.service)
    expected = {"expected_project_id": document.project_id, "expected_revision": document.revision}
    plan = service.plan(value.root, **expected)
    assert plan.runnable and plan.used_video_count == 0
    assert plan.request == resolve_preparation_request(document, has_video=False)
    delegated = []
    monkeypatch.setattr(value.service, "prepare", lambda *args, **kw: delegated.append(kw))
    service.run(value.root, plan.request, **expected)
    assert delegated[0]["candidate_settings"] == plan.request.candidate
    assert delegated[0]["selection_settings"] == plan.request.selection
    assert delegated[0]["quality_settings"] == plan.request.quality


def test_inactive_duplicate_settings_reuse_exact_canonical_artifact_metadata(tmp_path):
    value = harness(tmp_path)
    with_quality(value)
    projects = build_project_service()
    document = projects.save(value.root, changed(
        projects.open(value.root), interval_seconds="1", candidate_fps="2",
        image_format="png", reject_duplicates=False,
    ))
    service = PrepareService(LocalPrepareReader(value.execution),
                             MediaService(value.media, value.sources, None), value.service)

    def run(saved):
        expected = {"expected_project_id": saved.project_id, "expected_revision": saved.revision}
        plan = service.plan(value.root, **expected)
        return plan, service.run(value.root, plan.request, **expected)

    first_plan, first = run(document)
    frame = document.settings.frame_selection
    # An existing same-version typed project can retain inactive values. The new
    # desktop route resolves them before either recipe construction or publication.
    frame = frame.model_copy(update={"settings": {
        **frame.settings, "duplicate_hamming_threshold": 21, "duplicate_lookback": 17,
    }})
    document = projects.save(value.root, document.model_copy(update={
        "settings": document.settings.model_copy(update={"frame_selection": frame}),
    }))
    second_plan, second = run(document)
    assert first.status == second.status == "succeeded"
    assert second.cache_hits == ("candidate_views", "quality_assessment", "selected_views")
    assert second_plan.request == first_plan.request
    summary = LocalPrepareReader(value.execution).summary(value.root, second.run_id)
    assert summary.request == second_plan.request
    assert summary.request.selection.duplicate_hamming_threshold == 4
    assert summary.request.selection.duplicate_lookback == 8


def test_historical_contract_one_summary_never_normalizes_frozen_policy(tmp_path):
    value = harness(tmp_path)
    with_quality(value)
    result = sharp_prepare(value, duplicate_threshold=21, duplicate_lookback=17)
    summary = LocalPrepareReader(value.execution).summary(value.root, result.run_id)
    fields = preparation_request_fields(summary.request)
    assert fields["reject_duplicates"] is False
    assert fields["duplicate_hamming_threshold"] == "21"
    assert fields["duplicate_lookback"] == "17"


def test_legacy_public_wrapper_preserves_disabled_custom_typed_settings(document):
    selection = SharpestIntervalSettings(
        target_fps=parse_fps("2"), reject_duplicates=False,
        duplicate_hamming_threshold=21, duplicate_lookback=17,
    )
    frame = document.settings.frame_selection.model_copy(update={
        "settings": selection.model_dump(mode="json"),
    })
    document = document.model_copy(update={"settings": document.settings.model_copy(update={
        "frame_selection": frame,
    })})
    assert preparation_request(document).selection == selection
    resolved = resolve_preparation_request(document, has_video=True)
    assert not resolved.selection.reject_duplicates
    assert resolved.selection.duplicate_hamming_threshold == 4
    assert resolved.selection.duplicate_lookback == 8
