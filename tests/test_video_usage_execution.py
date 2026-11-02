"""Restrictions reach actual candidate publication, cache and current/historical Plan."""

from fractions import Fraction

import pytest
from test_plan_source_participation import plan_facade
from test_quality_execution import sharp_prepare, with_quality
from test_source_participation import change
from test_views_execution import FakeProbe, harness, prepare

from splatforge.application.desktop_workflow import plan_reconstruction, reconstruction_request
from splatforge.application.media import MediaService
from splatforge.application.video_usage import video_usage_draft
from splatforge.bootstrap import build_project_service
from splatforge.core.media import MediaType
from splatforge.core.video_usage import VideoSource, interval


def edit(value, operation, start=None, end=None):
    service = build_project_service()
    document = service.open(value.root)
    video = next(
        s
        for s in value.media.load_current_inventory(value.root, document).sources
        if s.media_type == MediaType.VIDEO
    )
    return service.save(
        value.root,
        video_usage_draft(
            document,
            VideoSource.from_source(video),
            operation,
            interval(start, end) if start is not None else None,
        ),
    )


def times(value, run):
    candidate = value.execution.load_candidate_views(value.root, run.candidate_artifact)
    return [
        v.presentation_timestamp.seconds()
        for v in candidate.views
        if v.presentation_timestamp is not None
    ]


def test_restricted_publication_vfr_bounds_cache_and_reset(tmp_path):
    value = harness(tmp_path)
    first = prepare(value)
    old_bytes = (value.root / first.candidate_artifact.manifest_path).read_bytes()
    assert times(value, first) == [Fraction(0), Fraction(7, 10), Fraction(1)]
    edit(value, "add", "0", "7/10")
    edit(value, "add", "1", "11/10")
    used = prepare(value)
    assert used.status == "succeeded"
    assert times(value, used) == [Fraction(0), Fraction(1)]  # end-exclusive, VFR retained
    assert used.candidate_count == 3  # photo survives
    assert not used.cache_hits
    again = prepare(value)
    assert again.cache_hits == ("candidate_views", "selected_views")
    edit(value, "reset")
    restored = prepare(value)
    assert restored.candidate_artifact == first.candidate_artifact
    assert (value.root / first.candidate_artifact.manifest_path).read_bytes() == old_bytes
    assert [p.read_bytes() for p in value.source_paths] == [b"original-video", b"original-photo"]


@pytest.mark.parametrize("mixed", [False, True])
def test_empty_video_is_not_ready_but_photos_remain_and_historical_views_work(tmp_path, mixed):
    value = harness(tmp_path, mixed=mixed)
    historic = prepare(value)
    document = edit(value, "empty")
    request = reconstruction_request(document)
    plan = plan_reconstruction(plan_facade(), value.root, request, None, None)
    assert plan["runnable"] == mixed
    if mixed:
        current = prepare(value)
        assert current.candidate_count == current.selected_count == 1
        assert times(value, current) == []
    else:
        with pytest.raises(ValueError, match="No usable media"):
            prepare(value)
    historical_request = request.model_copy(update={"views_run": historic.run_id})
    assert plan_reconstruction(plan_facade(), value.root, historical_request, None, None)[
        "runnable"
    ]


def test_sharpest_restricted_candidates_and_compatible_quality_reuse(tmp_path):
    value = harness(tmp_path)
    assessor = with_quality(value)
    edit(value, "add", "7/10", "11/10")
    first = sharp_prepare(value)
    assert times(value, first) == [Fraction(7, 10), Fraction(1)]
    assert first.quality_measured_count == 3
    assert len(assessor.calls) == 3
    next_policy = sharp_prepare(value, minimum="1")
    assert next_policy.cache_hits == ("candidate_views", "quality_assessment")


def test_relink_same_identity_and_independent_source_exclude(tmp_path):
    value = harness(tmp_path)
    edit(value, "add", "0", "7/10")
    first = prepare(value)
    document = build_project_service().open(value.root)
    video = next(
        s
        for s in value.media.load_current_inventory(value.root, document).sources
        if s.media_type == MediaType.VIDEO
    )
    alternate = tmp_path / "Moved ž clip.mp4"
    alternate.write_bytes(b"original-video")
    media = MediaService(value.media, value.sources, FakeProbe())
    media.relink(value.root, video.source_id, alternate)
    assert prepare(value).candidate_artifact == first.candidate_artifact
    different = tmp_path / "Different.mp4"
    different.write_bytes(b"different-original")
    with pytest.raises(ValueError, match="different content"):
        media.relink(value.root, video.source_id, different)
    change(value.root, {video.source_id})
    assert prepare(value).candidate_count == 1
    change(value.root, {video.source_id}, included=True)
    assert prepare(value).candidate_artifact == first.candidate_artifact
