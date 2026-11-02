"""Pure projections of saved review metadata; no original-file access."""

from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import PureWindowsPath
from uuid import UUID

from splatforge.core.frame_review import ReviewProvenance, ReviewScopeOption
from splatforge.core.logical_source_groups import LogicalSourceGroups
from splatforge.core.media import MediaType, SourceOccurrence
from splatforge.core.quality import NonNegativeRational
from splatforge.core.views import CandidateView, CandidateViewSet


@dataclass(frozen=True)
class ReviewScopeProjection:
    options: tuple[ReviewScopeOption, ...]
    source_ids: frozenset[UUID]
    selected_option: ReviewScopeOption
    auto_selected_count: int
    manual_count: int


def _source_labels(sources: tuple[SourceOccurrence, ...]) -> dict[UUID, str]:
    names = {s.source_id: s.original_filename or s.display_filename for s in sources}
    repeated = Counter(name.casefold() for name in names.values())
    labels = {
        s.source_id: (
            f"{names[s.source_id]} · {PureWindowsPath(s.external_locator).parent.name or 'Source'}"
            if repeated[names[s.source_id].casefold()] > 1 else names[s.source_id]
        )
        for s in sources
    }
    collisions = Counter(label.casefold() for label in labels.values())
    ordinals: Counter[str] = Counter()
    for source in sorted(sources, key=lambda s: s.source_id.int):
        label = labels[source.source_id]
        if collisions[label.casefold()] > 1:
            ordinals[label.casefold()] += 1
            labels[source.source_id] = f"{label} ({ordinals[label.casefold()]})"
    return labels


def review_scopes(
    candidate: CandidateViewSet,
    sources: tuple[SourceOccurrence, ...],
    organization: LogicalSourceGroups,
    selected: set[UUID],
    automatic: set[UUID],
    manual: set[UUID],
    scope: str,
) -> ReviewScopeProjection:
    """Count metadata once, then compose each source's all/individual/section scopes."""
    source_map = {s.source_id: s for s in sources}
    candidates: Counter[UUID] = Counter()
    selected_counts: Counter[UUID] = Counter()
    auto_counts: Counter[UUID] = Counter()
    manual_counts: Counter[UUID] = Counter()
    for view in candidate.views:
        source = source_map.get(view.source_id)
        if source is None or (
            view.source_revision, view.source_content_sha256, view.media_type
        ) != (source.source_revision, source.content_sha256, source.media_type):
            raise ValueError("Candidate source identity differs from its frozen preparation run")
        candidates[view.source_id] += 1
        selected_counts[view.source_id] += view.view_id in selected
        auto_counts[view.source_id] += view.view_id in automatic
        manual_counts[view.source_id] += view.view_id in manual

    sections: dict[str, tuple[str, str, set[UUID]]] = {}
    groups = (
        {g.group_id: g.label for g in organization.groups}
        if organization.schema_version == 1 else {}
    )
    for identity, label in groups.items():
        sections[f"group/{identity}"] = (label, "group", set())
    for source in sources:
        group = organization.source_assignments.get(source.source_id)
        if group in groups:
            key, label, kind = f"group/{group}", groups[group], "group"
        elif source.probe.capture and source.probe.capture.device_label != "Unknown device":
            label = source.probe.capture.device_label
            key, kind = "device/" + label.casefold(), "device"
        elif source.media_type == MediaType.VIDEO:
            key, label, kind = "videos", "Videos", "fallback"
        else:
            key, label, kind = "unknown", "Unknown device", "fallback"
        sections.setdefault(key, (label, kind, set()))[2].add(source.source_id)

    source_labels = _source_labels(sources)
    definitions = [("all", "All sources", "all", set(source_map))]
    definitions.extend(
        (f"source/{s.source_id}", source_labels[s.source_id],
         "source", {s.source_id})
        for s in sorted(sources, key=lambda s: (
            (s.original_filename or s.display_filename).casefold(), s.source_id.int,
        ))
    )
    definitions.extend(
        (key, label, kind, identities)
        for key, (label, kind, identities) in sorted(
            sections.items(), key=lambda item: (
                item[1][1] != "group", item[1][0].casefold(), item[0],
            )
        )
    )
    options = tuple(
        ReviewScopeOption(
            key=key, label=label, kind=kind,
            source_count=len(identities),
            candidate_count=sum(candidates[i] for i in identities),
            selected_count=sum(selected_counts[i] for i in identities),
            rejected_count=sum(candidates[i] - selected_counts[i] for i in identities),
        )
        for key, label, kind, identities in definitions
    )
    chosen = next((option for option in options if option.key == scope), None)
    if chosen is None:
        raise ValueError("Unknown review scope")
    identities = next(ids for key, _, _, ids in definitions if key == scope)
    return ReviewScopeProjection(
        options=options, source_ids=frozenset(identities), selected_option=chosen,
        auto_selected_count=sum(auto_counts[i] for i in identities),
        manual_count=sum(manual_counts[i] for i in identities),
    )


def review_provenance(
    view: CandidateView,
    source: SourceOccurrence,
    current: SourceOccurrence | None,
    *,
    inventory_available: bool,
    organization: LogicalSourceGroups,
    source_check: tuple[str, datetime] | None = None,
    automatic_score: NonNegativeRational | None = None,
) -> ReviewProvenance:
    """Current matching metadata is no assertion of current file availability."""
    state = "unavailable"
    locator = None
    if inventory_available:
        if current is None:
            state = "not_in_inventory"
        elif (current.source_revision, current.content_sha256, current.media_type) != (
            view.source_revision, view.source_content_sha256, view.media_type,
        ):
            state = "revision_mismatch"
        else:
            state, locator = "same_source", current.external_locator
    return ReviewProvenance(
        source_id=view.source_id,
        source_revision=view.source_revision,
        media_type=view.media_type,
        source_name=source.original_filename or source.display_filename,
        path_at_preparation=source.external_locator,
        current_locator=locator,
        current_source_state=state,
        source_check=source_check[0] if source_check else None,
        source_checked_at=source_check[1] if source_check else None,
        timestamp=view.presentation_timestamp,
        width=view.width, height=view.height,
        stream_index=view.selected_visual_stream_index,
        device_label=source.probe.capture.device_label if source.probe.capture else None,
        current_group_label=organization.label_for(view.source_id),
        automatic_score=automatic_score,
    )
