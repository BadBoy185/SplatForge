"""Real planning of synthetic 4K metadata, without decoding any large media."""

from uuid import uuid4

import pytest
from test_desktop_prepare import saved, service
from test_views_core import settings, source
from test_views_execution import harness, query

from splatforge.application.prepare_settings import prepare_settings_draft, prepare_settings_fields
from splatforge.application.projects import StaleProjectRevisionError
from splatforge.application.video_usage import video_usage_draft
from splatforge.bootstrap import build_project_service
from splatforge.core.media import MediaType
from splatforge.core.video_usage import (
    VideoSource,
    VideoUsageEntry,
    VideoUsageIntent,
    interval,
)
from splatforge.core.views import (
    CandidateBudgetExceeded,
    CandidateEncodingSettings,
    CandidateResourceLimits,
    ImageFormat,
    estimate_candidate_budget,
)


def test_trimmed_4k_budget_keeps_explanation_and_explicit_density_replans(tmp_path, monkeypatch):
    value = harness(tmp_path, mixed=False)
    prepare = service(value)
    projects = build_project_service()
    inventory = prepare._media.list(value.root)
    original = inventory.sources[0]
    clip = original.model_copy(update={"probe": original.probe.model_copy(update={
        "width": 3840, "height": 2160, "duration": "108.575",
    })})
    # Identity/content stay real fixture values; only probe metadata is synthetic.
    inventory = inventory.model_copy(update={"sources": (clip,)})
    monkeypatch.setattr(prepare._media, "list", lambda *_args, **_kwargs: inventory)
    document = projects.open(value.root)
    full_plan = prepare.plan(value.root, **saved(value))
    assert not full_plan.runnable and full_plan.candidate_count is None
    assert "26.97 GiB" in full_plan.blockers[0] and "20.00 GiB" in full_plan.blockers[0]
    assert full_plan.blockers[0].startswith("Candidate storage upper bound is ")
    assert "2 × target FPS" in full_plan.blockers[0]
    for start, end in (("0", "20.891"), ("40.109", "70.162"), ("103.323", "108.575")):
        document = video_usage_draft(
            document, VideoSource.from_source(clip), "add", interval(start, end),
        )
    document = projects.save(value.root, document)
    before = (value.root / "project.json").read_bytes()
    originals = [p.read_bytes() for p in value.source_paths]
    plan = prepare.plan(value.root, **saved(value))
    assert plan.runnable and not plan.blockers
    assert plan.candidate_count == 230
    assert plan.candidate_bytes == 230 * (3840 * 2160 * 8 + 65536)
    assert plan.peak_workspace_bytes == plan.candidate_bytes + 230 * 4096 + 12 * 1024**2
    assert any("Saved Trim" in w and "full clip" in w for w in plan.warnings)
    assert any("not expected encoded file sizes" in w for w in plan.warnings)
    assert any("unknown" in w for w in plan.warnings)
    assert "increase the budget" not in "\n".join(plan.warnings)
    assert plan.request.limits == CandidateResourceLimits()
    assert plan.request.candidate.candidate_fps.as_fraction() == 4
    assert plan.request.selection.target_fps.as_fraction() == 2
    assert (value.root / "project.json").read_bytes() == before

    # Explicit compatible edit, rather than an automatic change or limit bypass.
    fields = prepare_settings_fields(document)
    fields.update(interval_seconds="1", candidate_fps="2")
    projects.save(value.root, prepare_settings_draft(document, fields))
    retry = prepare.plan(value.root, **saved(value))
    assert retry.runnable and not retry.blockers
    assert retry.candidate_count == 117
    assert retry.candidate_bytes == 117 * (3840 * 2160 * 8 + 65536)
    assert retry.request.limits == plan.request.limits
    assert projects.open(value.root).video_usage == document.video_usage
    assert [p.read_bytes() for p in value.source_paths] == originals
    assert not value.materializer.calls
    assert not query(value.root, "SELECT run_id FROM runs")


def restricted(video, *ranges):
    return VideoUsageIntent(entries=(VideoUsageEntry(
        source_id=video.source_id, content_sha256=video.content_sha256,
        stream_index=video.probe.selected_visual_stream_index,
        intervals=tuple(interval(start, end) for start, end in ranges),
    ),))


@pytest.mark.parametrize("image_format", [ImageFormat.JPEG, ImageFormat.PNG])
def test_exact_interval_bounds_cover_gaps_tiny_ranges_and_concurrent_images(image_format):
    video = source(MediaType.VIDEO)
    video = video.model_copy(update={"probe": video.probe.model_copy(update={
        "start_time": "-100", "duration": "1000000",
    })})
    photo = source(MediaType.PHOTO)
    usage = restricted(video, ("-99", "-98"), ("100", "100000001/1000000"))
    pool = settings("3/2").model_copy(update={"encoding": CandidateEncodingSettings(
        image_format=image_format,
    )})
    estimate = estimate_candidate_budget(
        (video, photo), settings=pool, limits=CandidateResourceLimits(), video_usage=usage,
    )
    # ceil(1 * 3/2) + 1, ceil(1/1000000 * 3/2) + 1, and one photo.
    assert estimate.total_candidates == 6
    per_image = 640 * 480 * 8 + 65536
    assert estimate.candidate_bytes == 6 * per_image
    # Scratch is renamed to retained images; previous/current sources coexist
    # once each, rather than occupying two allocations for the same frame.
    assert estimate.peak_workspace_bytes == 6 * (per_image + 4096) + 12 * 1024**2
    with pytest.raises(CandidateBudgetExceeded) as failure:
        estimate_candidate_budget(
            (video, photo), settings=pool,
            limits=CandidateResourceLimits(max_candidates=5), video_usage=usage,
        )
    assert (failure.value.estimated, failure.value.limit) == (6, 5)


def test_trim_bound_never_exceeds_full_clip_and_keeps_byte_limit():
    video = source(MediaType.VIDEO)
    pool = settings("2")
    full = estimate_candidate_budget((video,), settings=pool, limits=CandidateResourceLimits())
    # Unknown historical origin permits explicit intervals without inventing a
    # start. Such a union must never inflate the existing full-duration bound.
    usage = restricted(video, ("-1000", "1000"))
    trimmed = estimate_candidate_budget(
        (video,), settings=pool, limits=CandidateResourceLimits(), video_usage=usage,
    )
    assert trimmed.total_candidates == full.total_candidates
    assert trimmed.candidate_bytes == full.candidate_bytes
    assert trimmed.peak_workspace_bytes == full.peak_workspace_bytes + 8 * 1024**2
    with pytest.raises(CandidateBudgetExceeded) as failure:
        estimate_candidate_budget(
            (video,), settings=pool, video_usage=usage,
            limits=CandidateResourceLimits(max_candidate_bytes=full.candidate_bytes - 1),
        )
    assert failure.value.resource == "candidate_bytes"
    assert failure.value.estimated == full.candidate_bytes


def test_trim_budget_preserves_unknown_duration_and_origin_contracts():
    video = source(MediaType.VIDEO)  # Historical probe has no known start_time.
    usage = restricted(video, ("100", "100000001/1000000"))
    estimate = estimate_candidate_budget(
        (video,), settings=settings("2"), limits=CandidateResourceLimits(), video_usage=usage,
    )
    assert estimate.total_candidates == 2
    unknown = video.model_copy(update={"probe": video.probe.model_copy(update={"duration": None})})
    with pytest.raises(ValueError, match="no bounded duration"):
        estimate_candidate_budget(
            (unknown,), settings=settings("2"), limits=CandidateResourceLimits(), video_usage=usage,
        )
    changed = video.model_copy(update={"content_sha256": "c" * 64})
    with pytest.raises(ValueError, match="different media"):
        estimate_candidate_budget(
            (changed,), settings=settings("2"), limits=CandidateResourceLimits(), video_usage=usage,
        )
    with pytest.raises(ValueError, match="No usable media"):
        estimate_candidate_budget(
            (video,), settings=settings("2"), limits=CandidateResourceLimits(),
            video_usage=restricted(video),
        )


def test_saved_trim_change_revokes_prior_plan_run_without_processing(tmp_path):
    value = harness(tmp_path, mixed=False)
    prepare = service(value)
    expected = saved(value)
    plan = prepare.plan(value.root, **expected)
    projects = build_project_service()
    document = projects.open(value.root)
    video = prepare._media.list(value.root).sources[0]
    projects.save(value.root, video_usage_draft(
        document, VideoSource.from_source(video), "add", interval("0", "1/4"),
    ))
    with pytest.raises(StaleProjectRevisionError):
        prepare.run(value.root, plan.request, **expected)
    assert not value.materializer.calls
    assert not query(value.root, "SELECT run_id FROM runs")


@pytest.mark.parametrize("empty_video", [False, True])
def test_photo_budget_never_recommends_inactive_video_controls(tmp_path, monkeypatch, empty_video):
    value = harness(tmp_path)
    prepare = service(value)
    inventory = prepare._media.list(value.root)
    photo = next(s for s in inventory.sources if s.media_type == MediaType.PHOTO)
    clip = next(s for s in inventory.sources if s.media_type == MediaType.VIDEO)
    photos = tuple(photo.model_copy(update={
        "source_id": uuid4(),
        "probe": photo.probe.model_copy(update={"width": 3840, "height": 2160}),
    }) for _ in range(324))
    if empty_video:
        projects = build_project_service()
        document = projects.open(value.root)
        projects.save(value.root, video_usage_draft(
            document, VideoSource.from_source(clip), "empty",
        ))
    sources = (*photos, clip) if empty_video else photos
    inventory = inventory.model_copy(update={"sources": sources})
    monkeypatch.setattr(prepare._media, "list", lambda *_args, **_kwargs: inventory)
    plan = prepare.plan(value.root, **saved(value))
    assert not plan.runnable and plan.request.quality is not None
    assert plan.photo_count == 324 and plan.used_video_count == 0
    assert "Included" in plan.blockers[0]
    assert "frames/second" not in plan.blockers[0]
    assert "target FPS" not in plan.blockers[0] and "output interval" not in plan.blockers[0]
    assert not value.materializer.calls
    assert not query(value.root, "SELECT run_id FROM runs")
