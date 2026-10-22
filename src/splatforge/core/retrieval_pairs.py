"""Deterministic bounded query policy and ordinary PairSet edge assembly."""

from __future__ import annotations

import heapq
import math
from collections.abc import Callable, Sequence
from uuid import UUID

from pydantic import Field

from splatforge.core.media import MediaType
from splatforge.core.pairs import (
    ExplicitReason,
    HybridPairSettings,
    PairEndpoints,
    PairingView,
    PairingViewUniverse,
    PairRecord,
    PairResourceLimits,
    RetrievalEvidence,
    RetrievalPairSettings,
    RetrievalReason,
    SequentialSettings,
    canonical_explicit_pairs,
    canonical_pair,
    generate_pairs,
    pairing_universe_digest,
    stable_pair_id,
)
from splatforge.core.retrieval import RetrievalExport, RetrievalResourceLimits, validate_storage
from splatforge.core.views import FrozenModel, canonical_json_bytes, sha256_bytes


class RetrievalPairPlan(FrozenModel):
    indexed_views: int
    descriptor_bytes: int
    queries: int
    requested_k: int
    similarity_evaluations_upper_bound: int
    scalar_products_upper_bound: int
    candidate_edge_upper_bound: int = Field(ge=0)
    sequential_edge_count: int = Field(ge=0)
    explicit_edge_count: int = Field(ge=0)
    total_edge_upper_bound: int = Field(ge=0)


class NoRetrievalEdgesError(ValueError):
    """An empty graph cannot be published; a valid negative benchmark outcome."""


def timeline_positions(universe: PairingViewUniverse) -> dict[UUID, int]:
    groups: dict[object, list[PairingView]] = {}
    for view in universe.views:
        if view.media_type == MediaType.VIDEO:
            groups.setdefault(view.timeline(), []).append(view)
    return {
        view.view_id: index
        for group in groups.values()
        for index, view in enumerate(
            sorted(
                group,
                key=lambda v: (
                    v.presentation_timestamp.seconds(),
                    v.occurrence_index,
                    v.view_id.int,
                ),
            )
        )
    }


def eligible(
    query: PairingView,
    target: PairingView,
    settings: RetrievalPairSettings,
    positions: dict[UUID, int],
    sequential: SequentialSettings | None,
) -> bool:
    if query.view_id == target.view_id:
        return False
    same_clip = (
        query.media_type == target.media_type == MediaType.VIDEO
        and query.timeline() == target.timeline()
    )
    if same_clip:
        if settings.same_clip_policy == "exclude":
            return False
        offset = abs(positions[query.view_id] - positions[target.view_id])
        if offset <= settings.same_clip_suppression_window:
            return False
        if (
            sequential
            and offset <= sequential.forward_neighbors
            and (
                sequential.max_time_gap is None
                or abs(
                    query.presentation_timestamp.seconds() - target.presentation_timestamp.seconds()
                )
                <= sequential.max_time_gap.as_fraction()
            )
        ):
            return False
    elif settings.source_policy == "cross_source" and query.source_id == target.source_id:
        return False
    return True


def sequential_count(universe: PairingViewUniverse, settings: SequentialSettings) -> int:
    positions = timeline_positions(universe)
    groups: dict[object, list[PairingView]] = {}
    for v in universe.views:
        if v.view_id in positions:
            groups.setdefault(v.timeline(), []).append(v)
    count = 0
    for group in groups.values():
        group.sort(key=lambda v: positions[v.view_id])
        for i, left in enumerate(group):
            for right in group[i + 1 : i + 1 + settings.forward_neighbors]:
                if settings.max_time_gap is None or (
                    right.presentation_timestamp.seconds() - left.presentation_timestamp.seconds()
                    <= settings.max_time_gap.as_fraction()
                ):
                    count += 1
    return count


def plan_retrieval_pairs(
    export: RetrievalExport,
    settings: RetrievalPairSettings | HybridPairSettings,
    limits: PairResourceLimits,
    resources: RetrievalResourceLimits,
    explicit: tuple[PairEndpoints, ...] = (),
) -> RetrievalPairPlan:
    validate_storage(export, resources)
    universe = export.universe
    explicit = canonical_explicit_pairs(universe, explicit)
    query_settings = settings.retrieval if isinstance(settings, HybridPairSettings) else settings
    sequential = settings.sequential if isinstance(settings, HybridPairSettings) else None
    ids = {v.view_id for v in universe.views}
    queries = set(query_settings.query_view_ids) or ids
    corpus = set(query_settings.corpus_view_ids) or ids
    if not queries <= ids or not corpus <= ids:
        raise ValueError("Query/corpus eligibility contains UUIDs outside the retrieval corpus")
    evaluations = len(queries) * len(corpus)
    products = evaluations * export.settings.descriptor_dimension
    if (
        evaluations > resources.max_similarity_evaluations
        or products > resources.max_scalar_products
    ):
        raise ValueError("Exact retrieval search exceeds evaluation/scalar-product planning limits")
    positions = timeline_positions(universe)
    target_views = [v for v in universe.views if v.view_id in corpus]
    edges = sum(
        min(
            query_settings.top_k,
            sum(eligible(q, t, query_settings, positions, sequential) for t in target_views),
        )
        for q in universe.views
        if q.view_id in queries
    )
    seq = sequential_count(universe, sequential) if sequential else 0
    total = seq + edges + len(explicit)
    if edges > query_settings.max_retrieval_pairs or total > limits.max_pairs:
        raise ValueError(
            f"Conservative pair planning bound: retrieval={edges}, sequential={seq}, "
            f"explicit={len(explicit)}, total={total}; lower K/eligibility or raise pair budgets"
        )
    return RetrievalPairPlan(
        indexed_views=len(ids),
        descriptor_bytes=export.descriptor_bytes,
        queries=len(queries),
        requested_k=query_settings.top_k,
        similarity_evaluations_upper_bound=evaluations,
        scalar_products_upper_bound=products,
        candidate_edge_upper_bound=edges,
        sequential_edge_count=seq,
        explicit_edge_count=len(explicit),
        total_edge_upper_bound=total,
    )


def retrieval_pair_recipe_key(
    universe: PairingViewUniverse,
    representation_digest: str,
    settings: RetrievalPairSettings | HybridPairSettings,
    explicit: tuple[PairEndpoints, ...],
) -> str:
    return sha256_bytes(
        canonical_json_bytes(
            {
                "pair_recipe_version": 1,
                "universe": pairing_universe_digest(universe),
                "representation": representation_digest,
                "settings": settings.model_dump(mode="json"),
                "explicit": [
                    p.model_dump(mode="json") for p in canonical_explicit_pairs(universe, explicit)
                ],
            }
        )
    )


def search_pairs(
    export: RetrievalExport,
    rows: Sequence[Sequence[float]],
    settings: RetrievalPairSettings | HybridPairSettings,
    limits: PairResourceLimits,
    resources: RetrievalResourceLimits,
    explicit: tuple[PairEndpoints, ...] = (),
    checkpoint: Callable[[], None] = lambda: None,
    progress: Callable[[int], None] = lambda _n: None,
) -> tuple[PairRecord, ...]:
    """Exact cosine; O(ND + NK) memory, never an NxN similarity matrix."""
    plan_retrieval_pairs(export, settings, limits, resources, explicit)
    qs = settings.retrieval if isinstance(settings, HybridPairSettings) else settings
    seq = settings.sequential if isinstance(settings, HybridPairSettings) else None
    universe = export.universe
    if len(rows) != len(universe.views) or any(
        len(row) != export.settings.descriptor_dimension for row in rows
    ):
        raise ValueError("Retrieval rows differ from the exact corpus/dimension")
    queries = set(qs.query_view_ids) or {v.view_id for v in universe.views}
    corpus = set(qs.corpus_view_ids) or {v.view_id for v in universe.views}
    positions = timeline_positions(universe)
    found: dict[PairEndpoints, list[RetrievalEvidence]] = {}
    processed = 0
    for i, query in enumerate(universe.views):
        if query.view_id not in queries:
            continue
        checkpoint()

        def neighbors(query=query, i=i):
            for j, target in enumerate(universe.views):
                if j % 64 == 0:
                    checkpoint()
                if target.view_id not in corpus or not eligible(query, target, qs, positions, seq):
                    continue
                score = math.fsum(a * b for a, b in zip(rows[i], rows[j], strict=True))
                if not math.isfinite(score):
                    raise ValueError("Nonfinite retrieval similarity")
                score = max(-1.0, min(1.0, score))
                if score < qs.minimum_similarity:
                    continue
                priority = int(
                    qs.source_policy == "prefer_cross_source"
                    and query.source_id == target.source_id
                )
                yield priority, -score, target.view_id.int, target.view_id

        for rank, (_, negative_score, _, target_id) in enumerate(
            heapq.nsmallest(qs.top_k, neighbors()),
            1,
        ):
            pair = canonical_pair(query.view_id, target_id)
            found.setdefault(pair, []).append(
                RetrievalEvidence(
                    query_view_id=query.view_id,
                    rank=rank,
                    similarity=-negative_score,
                )
            )
        processed += 1
        progress(processed)
    base = ()
    # Preserve the M6 algorithm, including chronology and max_time_gap behavior.
    if seq and sequential_count(universe, seq):
        base = generate_pairs(
            universe, settings=seq, limits=limits, explicit_pairs=explicit, checkpoint=checkpoint
        )
    else:
        base = tuple(
            PairRecord(**p.model_dump(), pair_id=stable_pair_id(p), reasons=(ExplicitReason(),))
            for p in canonical_explicit_pairs(universe, explicit)
        )
    merged = {canonical_pair(p.left_view_id, p.right_view_id): p for p in base}
    for pair, evidence in found.items():
        checkpoint()
        reason = RetrievalReason(
            representation_semantic_digest=export.recipe_key(),
            evidence=tuple(sorted(evidence, key=lambda e: e.query_view_id.int)),
        )
        existing = merged.get(pair)
        merged[pair] = PairRecord(
            **pair.model_dump(),
            pair_id=stable_pair_id(pair),
            reasons=tuple(
                sorted((*(existing.reasons if existing else ()), reason), key=lambda r: r.kind)
            ),
        )
    if not merged:
        raise NoRetrievalEdgesError(
            "No retrieval edges pass the declared policy/threshold; no fallback is used",
        )
    return tuple(
        merged[p]
        for p in sorted(
            merged,
            key=lambda p: (p.left_view_id.int, p.right_view_id.int),
        )
    )
