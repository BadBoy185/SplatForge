"""Deterministic equivalence, bounded expansion and linear work regressions."""

from __future__ import annotations

import json
import random
from collections.abc import Iterator, Sequence
from fractions import Fraction
from pathlib import Path
from uuid import UUID

import pytest
from fixed_fps_reference import brute_force_fixed_fps
from test_quality_core import handles, measurement, report
from test_quality_execution import sharp_prepare, with_quality
from test_views_core import candidate, handle, photo_view, source, video_view
from test_views_execution import (
    FakeProbe,
    candidate_settings,
    harness,
    limits,
    prepare,
    query,
)

from splatforge.application.media import MediaService
from splatforge.application.views_contracts import FFmpegBackendError
from splatforge.core.media import MediaType, VerificationPolicyId
from splatforge.core.quality import SharpestIntervalSettings, select_sharpest_interval
from splatforge.core.views import (
    MAX_VIEWS,
    FixedFpsSettings,
    FrameTimestamp,
    RationalValue,
    _nearest_timeline_indices,
    bound_timeline_expansion,
    parse_fps,
    select_fixed_fps,
)


@pytest.mark.parametrize("seed", range(120))
def test_fixed_fps_matches_pre_optimization_reference(seed: int) -> None:
    rng = random.Random(seed)
    views = []
    for index in range(1 + seed % 3):
        item = source(MediaType.VIDEO, source_id=UUID(int=index + 1))
        count = rng.choice((1, 2, 8, 30, 80))
        origin = rng.choice((-103, 0, 57))
        pts = [origin]
        for _ in range(count - 1):
            pts.append(pts[-1] + rng.choice((0, 1, 1, 2, 5, 17)))
        if seed % 4 == 0:
            pts = [origin + j * 2 for j in range(count)]  # CFR and midpoint ties
        base = Fraction(1, rng.choice((3, 10, 1001, 30000)))
        for j, value in enumerate(pts):
            view = video_view(item, value, view_id=UUID(int=10_000 * (index + 1) + j))
            views.append(view.model_copy(update={
                "presentation_timestamp": FrameTimestamp(
                    pts=value, time_base=RationalValue.from_fraction(base)
                ),
            }))
    views.append(photo_view(source(MediaType.PHOTO, source_id=UUID(int=100))))
    rng.shuffle(views)
    pool = candidate(*views)
    artifact = handle(pool)
    settings = FixedFpsSettings(target_fps=parse_fps(rng.choice(("1/3", "2", "7/2", "30"))))
    expected = brute_force_fixed_fps(pool, candidate_artifact=artifact, settings=settings)
    actual = select_fixed_fps(pool, candidate_artifact=artifact, settings=settings)
    assert actual == expected
    assert actual.model_dump_json() == expected.model_dump_json()


class CountingTimes(Sequence[Fraction]):
    def __init__(self, count: int) -> None:
        self.count = count
        self.visits = 0

    def __len__(self) -> int:
        return self.count

    def __getitem__(self, index: int) -> Fraction:
        self.visits += 1
        return Fraction(index, 10)


def test_sweep_visits_scale_linearly() -> None:
    visits = []
    for count in (1000, 2000, 5000, 10000):
        times = CountingTimes(count)
        targets: Iterator[Fraction] = (Fraction(i, 10) for i in range(count))
        assert list(_nearest_timeline_indices(times, targets)) == list(range(count))
        assert times.visits <= 4 * count
        visits.append(times.visits)
    assert visits[1] <= 2 * visits[0] + 4


def test_fixed_fps_refuses_extreme_expansion_before_target_iteration(monkeypatch) -> None:
    item = source(MediaType.VIDEO)
    pool = candidate(video_view(item, -10**12), video_view(item, 10**12))

    def forbidden(*args, **kwargs):
        raise AssertionError("Target iteration started before expansion refusal")

    monkeypatch.setattr("splatforge.core.views._nearest_timeline_indices", forbidden)
    with pytest.raises(ValueError, match=rf"Source {item.source_id}.*slots/intervals=.*bound="):
        select_fixed_fps(pool, candidate_artifact=handle(pool),
                         settings=FixedFpsSettings(target_fps=parse_fps("1000000000")))


def test_expansion_bound_accounts_for_candidates_and_prior_unsatisfied_sources() -> None:
    bound_timeline_expansion("source-a", MAX_VIEWS + 2, candidate_count=2, unsatisfied_count=0)
    with pytest.raises(ValueError, match=rf"source-b.*bound={MAX_VIEWS - 1}"):
        bound_timeline_expansion(
            "source-b", MAX_VIEWS, candidate_count=2, unsatisfied_count=3,
        )


def test_sharpest_refuses_extreme_expansion_before_interval_iteration() -> None:
    item = source(MediaType.VIDEO)
    pool = candidate(video_view(item, -10**12), video_view(item, 10**12))
    quality = report(pool, *(measurement(view, "1") for view in pool.views))
    candidate_handle, quality_handle = handles(pool, quality)
    with pytest.raises(ValueError, match=rf"Source {item.source_id}.*slots/intervals=.*bound="):
        select_sharpest_interval(
            pool, quality, candidate_artifact=candidate_handle,
            quality_artifact=quality_handle,
            settings=SharpestIntervalSettings(target_fps=parse_fps("1")),
        )


@pytest.mark.parametrize("stage", ("m3", "m4", "m6"))
def test_cached_operation_hashes_candidate_images_once_and_fresh_operation_detects_corruption(
    tmp_path: Path, monkeypatch, stage: str,
) -> None:
    from test_pairs_execution import build

    import splatforge.adapters.artifact_validation as validation

    value = harness(tmp_path)
    if stage == "m4":
        with_quality(value)
        first = sharp_prepare(value)
    else:
        first = prepare(value)
    if stage == "m6":
        build(value, first)

    def run():
        if stage == "m6":
            return build(value, first, repository=value.execution)
        if stage == "m4":
            return sharp_prepare(value)
        return prepare(value)
    reads: list[Path] = []
    original = validation.stream_sha256

    def count_reads(path: Path, **kwargs):
        if path.parent.name == "images":
            reads.append(path)
        return original(path, **kwargs)

    monkeypatch.setattr(validation, "stream_sha256", count_reads)
    cached = run()
    assert cached.status == "succeeded"
    assert len(reads) == first.candidate_count
    assert len(set(reads)) == first.candidate_count
    assert value.execution._validation_context is None
    damaged = reads[0]
    damaged.write_bytes(damaged.read_bytes() + b"corrupt between operations")
    reads.clear()
    if stage == "m6":
        with pytest.raises(ValueError, match="digest|manifest"):
            run()
    else:
        rebuilt = run()
        assert "candidate_views" not in rebuilt.cache_hits
        assert rebuilt.candidate_artifact.artifact_id != first.candidate_artifact.artifact_id
    assert damaged in reads


@pytest.mark.parametrize("count", (1, 10, 100, 300))
def test_complete_source_provenance_is_written_once_in_linear_work(
    tmp_path: Path, monkeypatch, count: int,
) -> None:
    value = harness(tmp_path, mixed=False)
    paths = []
    for index in range(count):
        path = tmp_path / f"photo {index}.png"
        path.write_bytes(b"synthetic source")
        paths.append(path)
    added = MediaService(value.media, value.sources, FakeProbe()).add(value.root, paths)
    source_ids = {item.source_id for item in added.added_sources}
    writes = []
    original = value.execution.update_attempt_provenance

    def record(*args, **kwargs):
        writes.append(json.dumps(kwargs["source_verification"], sort_keys=True).encode())
        return original(*args, **kwargs)

    monkeypatch.setattr(value.execution, "update_attempt_provenance", record)
    result = value.service.prepare(
        value.root, candidate_settings=candidate_settings(),
        selection_settings=FixedFpsSettings(target_fps=parse_fps("1")),
        resource_limits=limits(count=MAX_VIEWS, byte_count=10**9),
        verification_policy=VerificationPolicyId.BALANCED_LOCAL, source_ids=source_ids,
    )
    assert result.status == "succeeded"
    assert len(writes) == 1
    evidence = json.loads(writes[0])["evidence"]
    assert len(evidence) == count
    assert all(item["consumed_under_protected_identity"] for item in evidence)
    assert count * 500 < len(writes[0]) < count * 1500
    assert query(value.root, "SELECT count(*) FROM source_verifications")[0][0] == count


def test_failed_later_source_keeps_durable_rows_without_complete_provenance(
    tmp_path: Path, monkeypatch,
) -> None:
    value = harness(tmp_path)
    calls = 0

    def fail_later(_bridge):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise FFmpegBackendError("Synthetic failure at second source")

    value.materializer.on_call = fail_later
    writes = []
    monkeypatch.setattr(
        value.execution, "update_attempt_provenance", lambda *a, **kw: writes.append(kw)
    )
    with pytest.raises(FFmpegBackendError, match="second source"):
        prepare(value)
    assert writes == []
    assert query(value.root, "SELECT count(*) FROM source_verifications")[0][0] == 1
    assert query(value.root, "SELECT count(*) FROM artifacts") == [(0,)]
    encoded = query(value.root, "SELECT source_verification_json FROM attempts")[0][0]
    assert json.loads(encoded)["evidence"] == []
