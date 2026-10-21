"""Graph contracts, exact chronology, budgets, projections and numerical identity."""

from __future__ import annotations

from fractions import Fraction
from uuid import UUID

import pytest
from pydantic import ValidationError
from test_quality_core import candidate_set, candidate_view, handles, measurement, report

from splatforge.core.media import MediaType
from splatforge.core.pairs import (
    ExhaustiveSettings,
    PairingView,
    PairingViewUniverse,
    PairResourceLimits,
    PairSet,
    SequentialSettings,
    canonical_pair,
    compute_coverage,
    exhaustive_pair_count,
    exhaustive_recipe_key,
    generate_pairs,
    pair_graph_digest,
    pairing_universe_digest,
    parse_explicit_pair,
    project_pairing_universe,
    sequential_recipe_key,
    stable_pair_id,
)
from splatforge.core.quality import (
    SharpestIntervalSettings,
    parse_non_negative_rational,
    select_sharpest_interval,
)
from splatforge.core.views import (
    FixedFpsSettings,
    FrameTimestamp,
    RationalValue,
    parse_fps,
    select_fixed_fps,
)


def view(
    identity: int,
    pts: int | None = 0,
    *,
    source: int = 100,
    group: int = 500,
    revision: int = 1,
    stream: int = 0,
    occurrence: int = 0,
) -> PairingView:
    return PairingView(
        view_id=UUID(int=identity),
        source_id=UUID(int=source),
        source_revision=revision,
        selected_visual_stream_index=stream,
        source_group_id=UUID(int=group),
        camera_group_id=UUID(int=700),
        occurrence_index=occurrence,
        media_type=MediaType.VIDEO if pts is not None else MediaType.PHOTO,
        presentation_timestamp=None
        if pts is None
        else FrameTimestamp(
            pts=pts,
            time_base=RationalValue(numerator=1, denominator=10),
        ),
    )


def universe(*views: PairingView) -> PairingViewUniverse:
    return PairingViewUniverse(views=tuple(sorted(views, key=lambda v: v.view_id.int)))


def generate(value: PairingViewUniverse, *, settings=None, budget=100_000, explicit=(), **kwargs):
    return generate_pairs(
        value,
        settings=settings or SequentialSettings(),
        limits=PairResourceLimits(max_pairs=budget),
        explicit_pairs=explicit,
        **kwargs,
    )


def payload(value: PairingViewUniverse, *, settings=None, explicit=()) -> PairSet:
    settings = settings or SequentialSettings()
    pairs = generate(value, settings=settings, explicit=explicit)
    return PairSet(
        candidate_artifact_id=UUID(int=900),
        candidate_semantic_digest="a" * 64,
        selected_artifact_id=UUID(int=901),
        selected_semantic_digest="b" * 64,
        selected_method_id="frame_selection.fixed_fps",
        universe=value,
        universe_digest=pairing_universe_digest(value),
        settings=settings,
        explicit_pairs=explicit,
        pairs=pairs,
        coverage=compute_coverage(value, pairs),
        semantic_digest=pair_graph_digest(value, pairs),
    )


def endpoints(pairs):
    return [(p.left_view_id.int, p.right_view_id.int) for p in pairs]


def test_pair_identity_and_explicit_reverse_duplicates() -> None:
    a, b = UUID(int=1), UUID(int=2)
    assert canonical_pair(a, b) == canonical_pair(b, a)
    assert stable_pair_id(canonical_pair(a, b)) == stable_pair_id(canonical_pair(b, a))
    pair = canonical_pair(a, b)
    result = generate(universe(view(1), view(2, 10)), explicit=(pair, pair))
    assert endpoints(result) == [(1, 2)]
    assert [r.kind for r in result[0].reasons] == ["explicit", "sequential"]
    assert result[0].pair_id == stable_pair_id(pair)


@pytest.mark.parametrize("text", ["", "bad", "a:b", "a:b:c", f"{UUID(int=1)}:{UUID(int=1)}"])
def test_explicit_pair_rejects_malformed_and_self_pairs(text: str) -> None:
    with pytest.raises(ValueError):
        parse_explicit_pair(text)


def test_sequential_orders_exact_nonzero_vfr_and_equal_timestamps() -> None:
    value = universe(view(1, 104), view(2, 100), view(3, 100, occurrence=1), view(4, 115))
    pairs = generate(value, settings=SequentialSettings(forward_neighbors=1))
    assert endpoints(pairs) == [(1, 3), (1, 4), (2, 3)]
    assert [p.reasons[0].time_delta.as_fraction() for p in pairs] == [
        Fraction(2, 5),
        Fraction(11, 10),
        Fraction(0),
    ]
    tied = universe(view(1, 10), view(2, 10), view(3, 10))
    assert endpoints(generate(tied, settings=SequentialSettings(forward_neighbors=1))) == [
        (1, 2),
        (2, 3),
    ]


@pytest.mark.parametrize("gap,expected", [("0", 1), ("0.4", 3), ("1.5", 6)])
def test_sequential_exact_time_gap_boundary(gap: str, expected: int) -> None:
    value = universe(view(1, 100), view(2, 100), view(3, 104), view(4, 115))
    assert (
        len(
            generate(
                value, settings=SequentialSettings(max_time_gap=parse_non_negative_rational(gap))
            )
        )
        == expected
    )


@pytest.mark.parametrize(
    "field,value",
    [("source_id", UUID(int=101)), ("source_revision", 2), ("selected_visual_stream_index", 1)],
)
def test_sequential_separates_timelines_even_in_one_source_group(field, value) -> None:
    other = [
        view(3, 0).model_copy(update={field: value}),
        view(4, 10).model_copy(update={field: value}),
    ]
    graph = universe(view(1, 0), view(2, 10), *other)
    assert endpoints(generate(graph)) == [(1, 2), (3, 4)]
    coverage = compute_coverage(graph, generate(graph))
    assert coverage.component_sizes == (2, 2)
    assert "video_timelines_without_cross_timeline_edges" in coverage.warnings
    assert len(coverage.per_source_group) == 1


@pytest.mark.parametrize("neighbors,expected", [(1, 3), (2, 5), (5, 6)])
def test_sequential_forward_neighbors(neighbors, expected) -> None:
    value = universe(*(view(i + 1, i) for i in range(4)))
    assert (
        len(generate(value, settings=SequentialSettings(forward_neighbors=neighbors))) == expected
    )


def test_sequential_photos_isolated_and_explicit_bridges_update_coverage() -> None:
    value = universe(
        view(1),
        view(2, 10),
        view(3, None, source=101, group=501),
        view(4, source=102),
        view(5, 10, source=102),
    )
    base = generate(value)
    coverage = compute_coverage(value, base)
    assert (coverage.paired_view_count, coverage.isolated_view_count) == (4, 1)
    assert coverage.component_sizes == (2, 2, 1)
    assert coverage.isolated_view_ids == (UUID(int=3),)
    explicit = (canonical_pair(UUID(int=2), UUID(int=3)), canonical_pair(UUID(int=3), UUID(int=4)))
    bridged = generate(value, explicit=explicit)
    connected = compute_coverage(value, bridged)
    assert connected.component_sizes == (5,)
    assert connected.cross_source_pair_count == connected.cross_group_pair_count == 2
    assert connected.within_source_pair_count == 2
    assert {p.pair_id for p in base}.issubset({p.pair_id for p in bridged})
    assert [
        (g.selected_views, g.paired_views, g.internal_pairs, g.cross_pairs)
        for g in connected.per_source
    ] == [(2, 2, 1, 1), (1, 1, 0, 2), (2, 2, 1, 1)]


def test_sequential_photo_only_requires_explicit_edges() -> None:
    value = universe(view(1, None), view(2, None, source=101))
    with pytest.raises(ValueError, match="video chronology.*Exhaustive or explicit"):
        generate(value)
    assert len(generate(value, explicit=(canonical_pair(UUID(int=1), UUID(int=2)),))) == 1


@pytest.mark.parametrize("method", [SequentialSettings(), ExhaustiveSettings()])
def test_explicit_endpoints_must_be_selected_and_share_pair_budget(method) -> None:
    value = universe(view(1), view(2, 10), view(3, None, source=101))
    with pytest.raises(ValueError, match="selected universe"):
        generate(value, settings=method, explicit=(canonical_pair(UUID(int=1), UUID(int=99)),))
    with pytest.raises(ValueError, match="max_pairs"):
        generate(
            value, settings=method, budget=1, explicit=(canonical_pair(UUID(int=1), UUID(int=3)),)
        )


@pytest.mark.parametrize("size", [2, 3, 10])
def test_exhaustive_exact_count_mixed_sources_groups_and_deterministic_order(size) -> None:
    value = universe(
        *(view(i + 1, None if i % 2 else i, source=100 + i, group=500 + i) for i in range(size))
    )
    expected = exhaustive_pair_count(size)
    pairs = generate(value, settings=ExhaustiveSettings(), budget=expected)
    assert len(pairs) == size * (size - 1) // 2
    assert endpoints(pairs) == sorted(set(endpoints(pairs)))
    assert all(p.left_view_id.int < p.right_view_id.int for p in pairs)
    coverage = compute_coverage(value, pairs)
    assert coverage.component_sizes == (size,)
    assert coverage.cross_source_pair_count == coverage.cross_group_pair_count == expected
    assert coverage.warnings == ()
    if size > 2:
        with pytest.raises(ValueError, match=f"estimated_pairs={expected}"):
            generate(value, settings=ExhaustiveSettings(), budget=expected - 1)


def test_exhaustive_budget_refuses_before_pair_allocation(monkeypatch) -> None:
    import splatforge.core.pairs as module

    def forbidden(*args, **kwargs):
        raise AssertionError("must refuse before allocating pair identities")

    monkeypatch.setattr(module, "canonical_pair", forbidden)
    with pytest.raises(ValueError, match="selected_count=100.*estimated_pairs=4950.*max_pairs=1"):
        generate(
            universe(*(view(i + 1) for i in range(100))), settings=ExhaustiveSettings(), budget=1
        )
    assert exhaustive_pair_count(10**30) == 10**30 * (10**30 - 1) // 2


def test_exhaustive_explicit_reason_deduplication_and_graph_semantics() -> None:
    value = universe(view(1), view(2, 10))
    explicit = (canonical_pair(UUID(int=1), UUID(int=2)),)
    seq = payload(value)
    exhaustive = payload(value, settings=ExhaustiveSettings(), explicit=explicit)
    assert exhaustive.semantic_digest == seq.semantic_digest
    assert exhaustive.pairs[0].pair_id == seq.pairs[0].pair_id
    assert [r.kind for r in exhaustive.pairs[0].reasons] == ["exhaustive", "explicit"]
    assert sequential_recipe_key(value, SequentialSettings()) != exhaustive_recipe_key(
        value, ExhaustiveSettings(), explicit
    )
    changed = seq.model_dump(mode="json")
    changed.update(
        candidate_artifact_id=str(UUID(int=999)), selected_artifact_id=str(UUID(int=998))
    )
    assert PairSet.model_validate(changed).semantic_digest == seq.semantic_digest


@pytest.mark.parametrize("method", [SequentialSettings(), ExhaustiveSettings()])
def test_cancellation_before_and_during_generation(method) -> None:
    class Cancelled(Exception):
        pass

    calls = 0

    def cancel():
        nonlocal calls
        calls += 1
        if calls == 5:
            raise Cancelled

    with pytest.raises(Cancelled):
        generate(
            universe(*(view(i + 1, i) for i in range(600))),
            settings=method,
            budget=200_000,
            checkpoint=cancel,
        )
    assert calls == 5

    def immediately():
        raise Cancelled

    with pytest.raises(Cancelled):
        generate(universe(view(1), view(2)), settings=method, checkpoint=immediately)


@pytest.mark.parametrize(
    "change",
    [
        "pair_id",
        "self",
        "reverse",
        "outside",
        "duplicate",
        "reason_order",
        "empty_reasons",
        "offset",
        "delta",
        "timeline",
        "coverage",
        "semantic",
        "universe_digest",
    ],
)
def test_strict_pair_set_rejects_corrupt_graph_or_diagnostics(change: str) -> None:
    value = universe(view(1), view(2, 10), view(3, 20))
    data = payload(value, explicit=(canonical_pair(UUID(int=1), UUID(int=2)),)).model_dump(
        mode="json"
    )
    pair = data["pairs"][0]
    if change == "pair_id":
        pair["pair_id"] = str(UUID(int=7))
    elif change in {"self", "reverse", "outside"}:
        if change == "self":
            pair["right_view_id"] = pair["left_view_id"]
        elif change == "reverse":
            pair["left_view_id"], pair["right_view_id"] = (
                pair["right_view_id"],
                pair["left_view_id"],
            )
        else:
            pair["right_view_id"] = str(UUID(int=99))
            pair["pair_id"] = str(
                stable_pair_id(
                    canonical_pair(UUID(pair["left_view_id"]), UUID(pair["right_view_id"]))
                )
            )
    elif change == "duplicate":
        data["pairs"].append(pair)
    elif change == "reason_order":
        pair["reasons"].reverse()
    elif change == "empty_reasons":
        pair["reasons"] = []
    elif change in {"offset", "delta", "timeline"}:
        reason = pair["reasons"][1]
        if change == "offset":
            reason["neighbor_offset"] = 2
        elif change == "delta":
            reason["time_delta"]["numerator"] = 2
        else:
            reason["timeline"]["source_id"] = str(UUID(int=999))
    elif change == "coverage":
        data["coverage"]["paired_view_count"] = 0
    elif change == "semantic":
        data["semantic_digest"] = "0" * 64
    else:
        data["universe_digest"] = "0" * 64
    with pytest.raises(ValidationError):
        PairSet.model_validate(data)


@pytest.mark.parametrize("change", ["duplicate", "order", "photo_time", "video_no_time", "single"])
def test_pairing_universe_rejects_invalid_projection(change: str) -> None:
    data = universe(view(1), view(2, 10)).model_dump(mode="json")
    if change == "duplicate":
        data["views"][1] = data["views"][0]
    elif change == "order":
        data["views"].reverse()
    elif change == "photo_time":
        data["views"][0]["media_type"] = "photo"
    elif change == "video_no_time":
        data["views"][0]["presentation_timestamp"] = None
    else:
        data["views"] = data["views"][:1]
    with pytest.raises(ValidationError):
        PairingViewUniverse.model_validate(data)


def test_projection_both_variants_excludes_policy_pixels_and_publication_identity() -> None:
    candidate = candidate_set(candidate_view(identity=1, pts=0), candidate_view(identity=2, pts=10))
    quality = report(candidate, *(measurement(v, "10") for v in candidate.views))
    ch, qh = handles(candidate, quality)
    fixed = select_fixed_fps(
        candidate, candidate_artifact=ch, settings=FixedFpsSettings(target_fps=parse_fps("1"))
    )
    sharp = select_sharpest_interval(
        candidate,
        quality,
        candidate_artifact=ch,
        quality_artifact=qh,
        settings=SharpestIntervalSettings(target_fps=parse_fps("1"), reject_duplicates=False),
    )
    fixed_universe = project_pairing_universe(candidate, fixed)
    assert fixed_universe == project_pairing_universe(candidate, sharp)
    changed = sharp.model_copy(
        update={
            "settings": sharp.settings.model_copy(update={"duplicate_hamming_threshold": 30}),
        }
    )
    assert project_pairing_universe(candidate, changed) == fixed_universe
    assert "image_sha256" not in fixed_universe.model_dump_json()
    missing = fixed.model_copy(
        update={
            "selected_views": (
                fixed.selected_views[0].model_copy(update={"view_id": UUID(int=999)}),
                fixed.selected_views[1],
            )
        }
    )
    with pytest.raises(ValueError, match="absent"):
        project_pairing_universe(candidate, missing)


@pytest.mark.parametrize(
    "field,new_value",
    [
        (
            "presentation_timestamp",
            FrameTimestamp(pts=15, time_base=RationalValue(numerator=1, denominator=10)),
        ),
        ("source_id", UUID(int=101)),
        ("source_revision", 2),
        ("selected_visual_stream_index", 1),
    ],
)
def test_key_invalidation_consumed_timeline_metadata(field, new_value) -> None:
    value = universe(view(1), view(2, 10))
    changed = universe(value.views[0], value.views[1].model_copy(update={field: new_value}))
    assert sequential_recipe_key(value, SequentialSettings()) != sequential_recipe_key(
        changed, SequentialSettings()
    )


def test_key_settings_explicit_membership_and_graph_membership_changes() -> None:
    value = universe(view(1), view(2, 10), view(3, 20))
    key = sequential_recipe_key(value, SequentialSettings())
    assert key != sequential_recipe_key(value, SequentialSettings(forward_neighbors=1))
    assert key != sequential_recipe_key(
        value, SequentialSettings(max_time_gap=parse_non_negative_rational("0.5"))
    )
    assert key != sequential_recipe_key(
        value, SequentialSettings(), (canonical_pair(UUID(int=1), UUID(int=2)),)
    )
    smaller = universe(*value.views[:2])
    assert key != sequential_recipe_key(smaller, SequentialSettings())
    assert payload(value).semantic_digest != payload(smaller).semantic_digest
    assert (
        payload(value).semantic_digest
        != payload(value, settings=SequentialSettings(forward_neighbors=1)).semantic_digest
    )


@pytest.mark.parametrize("text", ["-1", "NaN", "inf", "1/0", "1/999999999999999999999999"])
def test_exact_gap_rejects_invalid_values(text) -> None:
    with pytest.raises(ValueError):
        parse_non_negative_rational(text)


@pytest.mark.parametrize("text,numerator,denominator", [("0.5", 1, 2), ("2", 2, 1), ("3/2", 3, 2)])
def test_exact_gap_inputs(text, numerator, denominator) -> None:
    gap = parse_non_negative_rational(text)
    assert (gap.numerator, gap.denominator) == (numerator, denominator)
