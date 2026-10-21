"""M6 metadata-only view universes, deterministic candidate edges and coverage."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Callable, Iterable
from typing import Annotated, Literal
from uuid import UUID, uuid5

from pydantic import Field, model_validator

from splatforge.core.media import MediaType
from splatforge.core.quality import NonNegativeRational, SharpestSelectedViewSet
from splatforge.core.views import (
    MAX_VIEWS,
    CandidateViewSet,
    FrameTimestamp,
    FrozenModel,
    SelectedViewSet,
    candidate_semantic_digest,
    canonical_json_bytes,
    sha256_bytes,
    validate_selected_against_candidate,
)

PAIR_ARTIFACT_TYPE = "pairs.pair_set"
PAIR_CONTRACT_VERSION = 1
MAX_PAIRS = 1_000_000
MAX_PAIR_METADATA_BYTES = 768 * 1024 * 1024
_PAIR_NAMESPACE = UUID("35a55597-1ab8-5bd4-9a56-82075e175da3")
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Count = Annotated[int, Field(ge=0, le=MAX_PAIRS, strict=True)]


class SequentialSettings(FrozenModel):
    method_id: Literal["pair_selection.sequential"] = "pair_selection.sequential"
    method_version: Literal[1] = 1
    settings_schema_version: Literal[1] = 1
    forward_neighbors: int = Field(default=5, ge=1, le=1000, strict=True)
    max_time_gap: NonNegativeRational | None = None


class ExhaustiveSettings(FrozenModel):
    method_id: Literal["pair_selection.exhaustive"] = "pair_selection.exhaustive"
    method_version: Literal[1] = 1
    settings_schema_version: Literal[1] = 1


PairSettings = Annotated[SequentialSettings | ExhaustiveSettings, Field(discriminator="method_id")]


class PairResourceLimits(FrozenModel):
    max_pairs: int = Field(default=100_000, ge=1, le=MAX_PAIRS, strict=True)


class TimelineIdentity(FrozenModel):
    source_id: UUID
    source_revision: int = Field(ge=1, strict=True)
    selected_visual_stream_index: int = Field(ge=0, strict=True)


class PairingView(TimelineIdentity):
    view_id: UUID
    media_type: MediaType
    source_group_id: UUID
    camera_group_id: UUID
    occurrence_index: int = Field(ge=0, strict=True)
    presentation_timestamp: FrameTimestamp | None

    @model_validator(mode="after")
    def timing_matches_media(self) -> PairingView:
        if (self.media_type == MediaType.VIDEO) != (self.presentation_timestamp is not None):
            raise ValueError("video requires a timestamp; photos must have no timestamp")
        return self

    def timeline(self) -> TimelineIdentity:
        return TimelineIdentity.model_validate(
            self.model_dump(
                include={"source_id", "source_revision", "selected_visual_stream_index"}
            )
        )


class PairingViewUniverse(FrozenModel):
    projection_version: Literal[1] = 1
    views: tuple[PairingView, ...] = Field(min_length=2, max_length=MAX_VIEWS)

    @model_validator(mode="after")
    def canonical_unique_views(self) -> PairingViewUniverse:
        ids = [v.view_id.int for v in self.views]
        if ids != sorted(set(ids)):
            raise ValueError("pairing views must be unique and sorted by unsigned UUID integer")
        return self


def pairing_universe_digest(universe: PairingViewUniverse) -> str:
    return sha256_bytes(canonical_json_bytes(universe.model_dump(mode="json")))


def project_pairing_universe(
    candidate: CandidateViewSet,
    selected: SelectedViewSet | SharpestSelectedViewSet,
) -> PairingViewUniverse:
    if selected.candidate_semantic_digest != candidate_semantic_digest(candidate):
        raise ValueError("selected candidate semantics differ from candidate content")
    if isinstance(selected, SelectedViewSet):
        validate_selected_against_candidate(selected, candidate)
    candidates = {v.view_id: v for v in candidate.views}
    projected = []
    for item in selected.selected_views:
        view = candidates.get(item.view_id)
        if view is None or (item.source_id, item.source_revision, item.media_type) != (
            view.source_id,
            view.source_revision,
            view.media_type,
        ):
            raise ValueError("selected view is missing or differs from candidate identity")
        projected.append(
            PairingView.model_validate(
                view.model_dump(
                    include={
                        "view_id",
                        "media_type",
                        "source_id",
                        "source_revision",
                        "selected_visual_stream_index",
                        "source_group_id",
                        "camera_group_id",
                        "occurrence_index",
                        "presentation_timestamp",
                    }
                )
            )
        )
    return PairingViewUniverse(views=tuple(sorted(projected, key=lambda v: v.view_id.int)))


class PairEndpoints(FrozenModel):
    left_view_id: UUID
    right_view_id: UUID

    @model_validator(mode="after")
    def canonical_endpoints(self) -> PairEndpoints:
        if self.left_view_id.int >= self.right_view_id.int:
            raise ValueError("pair endpoints must use left UUID integer < right UUID integer")
        return self


def canonical_pair(left: UUID, right: UUID) -> PairEndpoints:
    if left == right:
        raise ValueError("self pairs are invalid")
    left, right = sorted((left, right), key=lambda v: v.int)
    return PairEndpoints(left_view_id=left, right_view_id=right)


def parse_explicit_pair(value: str) -> PairEndpoints:
    parts = value.split(":")
    if len(parts) != 2:
        raise ValueError("explicit pair must be <view-uuid>:<view-uuid>")
    return canonical_pair(UUID(parts[0]), UUID(parts[1]))


def stable_pair_id(pair: PairEndpoints) -> UUID:
    return uuid5(_PAIR_NAMESPACE, f"1:{pair.left_view_id}:{pair.right_view_id}")


class SequentialReason(FrozenModel):
    kind: Literal["sequential"] = "sequential"
    timeline: TimelineIdentity
    neighbor_offset: int = Field(ge=1, le=1000, strict=True)
    time_delta: NonNegativeRational


class ExhaustiveReason(FrozenModel):
    kind: Literal["exhaustive"] = "exhaustive"


class ExplicitReason(FrozenModel):
    kind: Literal["explicit"] = "explicit"


PairReason = Annotated[
    SequentialReason | ExhaustiveReason | ExplicitReason, Field(discriminator="kind")
]


class PairRecord(PairEndpoints):
    pair_id: UUID
    reasons: tuple[PairReason, ...] = Field(min_length=1, max_length=3)

    @model_validator(mode="after")
    def stable_and_canonical(self) -> PairRecord:
        if self.pair_id != stable_pair_id(self):
            raise ValueError("pair ID differs from stable endpoint identity")
        kinds = [r.kind for r in self.reasons]
        if kinds != sorted(set(kinds)):
            raise ValueError("pair reasons must be unique and in canonical kind order")
        return self


class GroupCoverage(FrozenModel):
    group_id: UUID
    selected_views: Count
    paired_views: Count
    internal_pairs: Count
    cross_pairs: Count


class PairCoverage(FrozenModel):
    selected_view_count: int = Field(ge=2, le=MAX_VIEWS, strict=True)
    paired_view_count: int = Field(ge=0, le=MAX_VIEWS, strict=True)
    isolated_view_ids: tuple[UUID, ...] = Field(max_length=MAX_VIEWS)
    isolated_view_count: int = Field(ge=0, le=MAX_VIEWS, strict=True)
    pair_count: Count
    component_count: int = Field(ge=1, le=MAX_VIEWS, strict=True)
    component_sizes: tuple[Annotated[int, Field(ge=1, le=MAX_VIEWS, strict=True)], ...] = Field(
        max_length=MAX_VIEWS
    )
    per_source: tuple[GroupCoverage, ...] = Field(max_length=MAX_VIEWS)
    per_source_group: tuple[GroupCoverage, ...] = Field(max_length=MAX_VIEWS)
    within_source_pair_count: Count
    cross_source_pair_count: Count
    cross_group_pair_count: Count
    warnings: tuple[
        Literal[
            "disconnected_candidate_graph",
            "isolated_unordered_photos",
            "video_timelines_without_cross_timeline_edges",
        ],
        ...,
    ] = Field(max_length=3)


def compute_coverage(universe: PairingViewUniverse, pairs: tuple[PairRecord, ...]) -> PairCoverage:
    views = {v.view_id: v for v in universe.views}
    parent = {v: v for v in views}
    degree: Counter[UUID] = Counter()
    source_internal: Counter[UUID] = Counter()
    source_cross: Counter[UUID] = Counter()
    group_internal: Counter[UUID] = Counter()
    group_cross: Counter[UUID] = Counter()
    cross_source = cross_group = 0
    bridged_timelines: set[TimelineIdentity] = set()

    def find(view_id: UUID) -> UUID:
        while parent[view_id] != view_id:
            parent[view_id] = parent[parent[view_id]]
            view_id = parent[view_id]
        return view_id

    sizes = {v: 1 for v in views}
    for pair in pairs:
        left, right = views[pair.left_view_id], views[pair.right_view_id]
        degree[left.view_id] += 1
        degree[right.view_id] += 1
        a, b = find(left.view_id), find(right.view_id)
        if a != b:
            if sizes[a] < sizes[b]:
                a, b = b, a
            parent[b] = a
            sizes[a] += sizes[b]
        for field, internal, cross in (
            ("source_id", source_internal, source_cross),
            ("source_group_id", group_internal, group_cross),
        ):
            x, y = getattr(left, field), getattr(right, field)
            if x == y:
                internal[x] += 1
            else:
                cross[x] += 1
                cross[y] += 1
        cross_source += left.source_id != right.source_id
        cross_group += left.source_group_id != right.source_group_id
        if (
            left.media_type == right.media_type == MediaType.VIDEO
            and left.timeline() != right.timeline()
        ):
            bridged_timelines.update((left.timeline(), right.timeline()))
    components = Counter(find(v) for v in views)
    isolated = tuple(v.view_id for v in universe.views if not degree[v.view_id])

    def groups(
        field: str, internal: Counter[UUID], cross: Counter[UUID]
    ) -> tuple[GroupCoverage, ...]:
        selected = Counter(getattr(v, field) for v in universe.views)
        paired = Counter(getattr(v, field) for v in universe.views if degree[v.view_id])
        return tuple(
            GroupCoverage(
                group_id=g,
                selected_views=selected[g],
                paired_views=paired[g],
                internal_pairs=internal[g],
                cross_pairs=cross[g],
            )
            for g in sorted(selected, key=lambda v: v.int)
        )

    warnings = []
    if len(components) > 1:
        warnings.append("disconnected_candidate_graph")
    if any(views[v].media_type == MediaType.PHOTO for v in isolated):
        warnings.append("isolated_unordered_photos")
    timelines = {v.timeline() for v in universe.views if v.media_type == MediaType.VIDEO}
    if len(timelines) > 1 and timelines - bridged_timelines:
        warnings.append("video_timelines_without_cross_timeline_edges")
    return PairCoverage(
        selected_view_count=len(views),
        paired_view_count=len(degree),
        isolated_view_ids=isolated,
        isolated_view_count=len(isolated),
        pair_count=len(pairs),
        component_count=len(components),
        component_sizes=tuple(sorted(components.values(), reverse=True)),
        per_source=groups("source_id", source_internal, source_cross),
        per_source_group=groups("source_group_id", group_internal, group_cross),
        within_source_pair_count=len(pairs) - cross_source,
        cross_source_pair_count=cross_source,
        cross_group_pair_count=cross_group,
        warnings=tuple(sorted(warnings)),
    )


def pair_graph_digest(universe: PairingViewUniverse, pairs: tuple[PairRecord, ...]) -> str:
    return sha256_bytes(
        canonical_json_bytes(
            {
                "semantic_version": 1,
                "contract_version": PAIR_CONTRACT_VERSION,
                "universe_digest": pairing_universe_digest(universe),
                "pair_ids": [str(p.pair_id) for p in pairs],
            }
        )
    )


def canonical_explicit_pairs(
    universe: PairingViewUniverse,
    pairs: Iterable[PairEndpoints],
) -> tuple[PairEndpoints, ...]:
    ids = {v.view_id for v in universe.views}
    unique = set(pairs)
    if len(unique) > MAX_PAIRS:
        raise ValueError("explicit pair count exceeds the structural bound")
    if any(p.left_view_id not in ids or p.right_view_id not in ids for p in unique):
        raise ValueError("explicit pair endpoints must exist in the selected universe")
    return tuple(sorted(unique, key=lambda p: (p.left_view_id.int, p.right_view_id.int)))


def sequential_recipe_key(
    universe: PairingViewUniverse,
    settings: SequentialSettings,
    explicit_pairs: tuple[PairEndpoints, ...] = (),
) -> str:
    return _recipe_key(universe, settings, explicit_pairs)


def exhaustive_recipe_key(
    universe: PairingViewUniverse,
    settings: ExhaustiveSettings,
    explicit_pairs: tuple[PairEndpoints, ...] = (),
) -> str:
    return _recipe_key(universe, settings, explicit_pairs)


def _recipe_key(
    universe: PairingViewUniverse,
    settings: SequentialSettings | ExhaustiveSettings,
    explicit_pairs: tuple[PairEndpoints, ...],
) -> str:
    return sha256_bytes(
        canonical_json_bytes(
            {
                "fingerprint_schema_version": 1,
                "contract_version": PAIR_CONTRACT_VERSION,
                "settings": settings.model_dump(mode="json"),
                "universe_digest": pairing_universe_digest(universe),
                "explicit_pairs": [
                    p.model_dump(mode="json")
                    for p in canonical_explicit_pairs(universe, explicit_pairs)
                ],
            }
        )
    )


def exhaustive_pair_count(selected_count: int) -> int:
    if selected_count < 0:
        raise ValueError("selected count must be non-negative")
    return selected_count * (selected_count - 1) // 2


def _timelines(universe: PairingViewUniverse) -> dict[TimelineIdentity, list[PairingView]]:
    result: dict[TimelineIdentity, list[PairingView]] = defaultdict(list)
    for view in universe.views:
        if view.media_type == MediaType.VIDEO:
            result[view.timeline()].append(view)
    for views in result.values():
        views.sort(
            key=lambda v: (v.presentation_timestamp.seconds(), v.occurrence_index, v.view_id.int)
        )
    return result


class PairSet(FrozenModel):
    contract_version: Literal[1] = 1
    candidate_artifact_id: UUID
    candidate_semantic_digest: Digest
    selected_artifact_id: UUID
    selected_semantic_digest: Digest
    selected_method_id: Literal["frame_selection.fixed_fps", "frame_selection.sharpest_interval"]
    universe: PairingViewUniverse
    universe_digest: Digest
    settings: PairSettings
    explicit_pairs: tuple[PairEndpoints, ...] = Field(max_length=MAX_PAIRS)
    pairs: tuple[PairRecord, ...] = Field(min_length=1, max_length=MAX_PAIRS)
    coverage: PairCoverage
    semantic_digest: Digest

    @model_validator(mode="after")
    def validate_graph(self) -> PairSet:
        if self.universe_digest != pairing_universe_digest(self.universe):
            raise ValueError("pairing universe digest mismatch")
        ids = {v.view_id: v for v in self.universe.views}
        endpoints = [(p.left_view_id.int, p.right_view_id.int) for p in self.pairs]
        if endpoints != sorted(set(endpoints)):
            raise ValueError("pairs must be unique and canonically ordered")
        if len({p.pair_id for p in self.pairs}) != len(self.pairs):
            raise ValueError("duplicate pair IDs")
        if self.explicit_pairs != canonical_explicit_pairs(self.universe, self.explicit_pairs):
            raise ValueError("explicit pairs are not canonical")
        explicit = set(self.explicit_pairs)
        positions = {}
        for timeline, views in _timelines(self.universe).items():
            for index, view in enumerate(views):
                positions[view.view_id] = (timeline, index)
        for pair in self.pairs:
            if pair.left_view_id not in ids or pair.right_view_id not in ids:
                raise ValueError("pair endpoint is outside the selected universe")
            left, right = ids[pair.left_view_id], ids[pair.right_view_id]
            for reason in pair.reasons:
                if isinstance(reason, ExhaustiveReason) and not isinstance(
                    self.settings, ExhaustiveSettings
                ):
                    raise ValueError("exhaustive reason requires Exhaustive settings")
                if isinstance(reason, SequentialReason):
                    if (
                        not isinstance(self.settings, SequentialSettings)
                        or reason.neighbor_offset > self.settings.forward_neighbors
                        or (
                            self.settings.max_time_gap is not None
                            and reason.time_delta.as_fraction()
                            > self.settings.max_time_gap.as_fraction()
                        )
                    ):
                        raise ValueError("sequential reason contradicts resolved settings")
                    a, b = positions.get(left.view_id), positions.get(right.view_id)
                    if a is None or b is None or a[0] != b[0] or a[0] != reason.timeline:
                        raise ValueError("sequential reason requires one valid video timeline")
                    delta = abs(
                        left.presentation_timestamp.seconds()
                        - right.presentation_timestamp.seconds()
                    )
                    if reason.neighbor_offset != abs(a[1] - b[1]) or (
                        reason.time_delta.as_fraction() != delta
                    ):
                        raise ValueError("sequential reason offset or time delta differs")
                elif (
                    isinstance(reason, ExplicitReason)
                    and PairEndpoints(
                        left_view_id=pair.left_view_id, right_view_id=pair.right_view_id
                    )
                    not in explicit
                ):
                    raise ValueError("explicit reason has no supplied pair")
        actual_explicit = {
            PairEndpoints(left_view_id=p.left_view_id, right_view_id=p.right_view_id)
            for p in self.pairs
            if any(r.kind == "explicit" for r in p.reasons)
        }
        if actual_explicit != explicit:
            raise ValueError("supplied explicit pairs differ from pair reasons")
        if self.coverage != compute_coverage(self.universe, self.pairs):
            raise ValueError("PairSet coverage differs from recomputed graph")
        if self.semantic_digest != pair_graph_digest(self.universe, self.pairs):
            raise ValueError("PairSet semantic digest mismatch")
        return self


def generate_pairs(
    universe: PairingViewUniverse,
    *,
    settings: SequentialSettings | ExhaustiveSettings,
    limits: PairResourceLimits,
    explicit_pairs: tuple[PairEndpoints, ...] = (),
    checkpoint: Callable[[], None] = lambda: None,
    progress: Callable[[int], None] = lambda _count: None,
) -> tuple[PairRecord, ...]:
    """Bounded sparse traversal; exhaustive refuses before allocating any edges."""
    checkpoint()
    explicit_pairs = canonical_explicit_pairs(universe, explicit_pairs)
    if len(explicit_pairs) > limits.max_pairs:
        raise ValueError(f"Explicit pairs exceed max_pairs={limits.max_pairs}")
    if isinstance(settings, ExhaustiveSettings):
        count = exhaustive_pair_count(len(universe.views))
        if count > limits.max_pairs:
            raise ValueError(
                f"Exhaustive selected_count={len(universe.views)}, estimated_pairs={count} "
                f"exceeds max_pairs={limits.max_pairs}; use Sequential or future retrieval "
                "for larger datasets"
            )
    edges: dict[PairEndpoints, dict[str, PairReason]] = {}
    generated = 0

    def add(pair: PairEndpoints, reason: PairReason) -> None:
        nonlocal generated
        if pair not in edges:
            if len(edges) >= limits.max_pairs:
                raise ValueError(f"Pair graph exceeds max_pairs={limits.max_pairs}")
            edges[pair] = {}
        edges[pair][reason.kind] = reason
        generated += 1
        if generated % 256 == 0:
            checkpoint()
            progress(len(edges))

    for pair in explicit_pairs:
        add(pair, ExplicitReason())
    if isinstance(settings, ExhaustiveSettings):
        for index, left in enumerate(universe.views):
            checkpoint()
            for right_index in range(index + 1, len(universe.views)):
                right = universe.views[right_index]
                add(canonical_pair(left.view_id, right.view_id), ExhaustiveReason())
    else:
        for timeline, views in _timelines(universe).items():
            checkpoint()
            for index, left in enumerate(views):
                for offset in range(1, min(settings.forward_neighbors + 1, len(views) - index)):
                    right = views[index + offset]
                    delta = (
                        right.presentation_timestamp.seconds()
                        - left.presentation_timestamp.seconds()
                    )
                    if (
                        settings.max_time_gap is not None
                        and delta > settings.max_time_gap.as_fraction()
                    ):
                        continue
                    add(
                        canonical_pair(left.view_id, right.view_id),
                        SequentialReason(
                            timeline=timeline,
                            neighbor_offset=offset,
                            time_delta=NonNegativeRational.from_fraction(delta),
                        ),
                    )
                if index % 256 == 0:
                    checkpoint()
    if not edges:
        raise ValueError(
            "Sequential requires video chronology producing an edge; "
            "use Exhaustive or explicit pairs for unordered photos"
        )
    checkpoint()
    records = []
    for index, (pair, reasons) in enumerate(
        sorted(
            edges.items(), key=lambda item: (item[0].left_view_id.int, item[0].right_view_id.int)
        )
    ):
        if index % 256 == 0:
            checkpoint()
        records.append(
            PairRecord(
                **pair.model_dump(),
                pair_id=stable_pair_id(pair),
                reasons=tuple(reasons[k] for k in sorted(reasons)),
            )
        )
    checkpoint()
    return tuple(records)
