"""Test-only pre-optimization brute-force selection oracle (method version 1)."""

import math
from fractions import Fraction
from uuid import UUID

from splatforge.core.execution import ArtifactHandle
from splatforge.core.media import MediaType
from splatforge.core.views import (
    CANDIDATE_ARTIFACT_TYPE,
    CandidateView,
    CandidateViewSet,
    FixedFpsSettings,
    RationalValue,
    SelectedView,
    SelectedViewSet,
    SelectionReason,
    SourceSelectionCount,
    UnsatisfiedSlot,
    candidate_semantic_digest,
    validate_selected_against_candidate,
)


def brute_force_fixed_fps(
    candidate: CandidateViewSet,
    *,
    candidate_artifact: ArtifactHandle,
    settings: FixedFpsSettings,
) -> SelectedViewSet:
    """Select photos once and video candidates nearest independent per-source grids."""

    if candidate_artifact.artifact_type != CANDIDATE_ARTIFACT_TYPE:
        raise ValueError("fixed-FPS selection requires a CandidateViewSet artifact")
    if candidate_artifact.semantic_digest != candidate_semantic_digest(candidate):
        raise ValueError("candidate handle semantic digest does not match candidate content")
    grouped: dict[tuple[str, int], list[CandidateView]] = {}
    for view in candidate.views:
        grouped.setdefault((str(view.source_id), view.source_revision), []).append(view)

    provisional: list[SelectedView] = []
    unsatisfied: list[UnsatisfiedSlot] = []
    counts: list[SourceSelectionCount] = []
    target_step = Fraction(1, 1) / settings.target_fps.as_fraction()

    for source_key in sorted(grouped):
        source_views = grouped[source_key]
        photos = sorted(
            (view for view in source_views if view.media_type == MediaType.PHOTO),
            key=lambda view: str(view.view_id),
        )
        videos = sorted(
            (view for view in source_views if view.media_type == MediaType.VIDEO),
            key=lambda view: (
                view.presentation_timestamp.seconds() if view.presentation_timestamp else 0,
                str(view.view_id),
            ),
        )
        source_selected = 0
        source_unsatisfied = 0
        for photo in photos:
            provisional.append(
                SelectedView(
                    view_id=photo.view_id,
                    source_id=photo.source_id,
                    source_revision=photo.source_revision,
                    media_type=photo.media_type,
                    selection_order=len(provisional),
                    reason=SelectionReason.PHOTO_SINGLETON,
                )
            )
            source_selected += 1

        if videos:
            first_time = videos[0].presentation_timestamp.seconds()  # type: ignore[union-attr]
            last_time = videos[-1].presentation_timestamp.seconds()  # type: ignore[union-attr]
            slot_count = math.floor((last_time - first_time) / target_step) + 1
            used: set[UUID] = set()
            for slot_index in range(slot_count):
                target = first_time + slot_index * target_step
                nearest = min(
                    videos,
                    key=lambda view: (
                        abs(view.presentation_timestamp.seconds() - target),  # type: ignore[union-attr]
                        view.presentation_timestamp.seconds(),  # type: ignore[union-attr]
                        str(view.view_id),
                    ),
                )
                if nearest.view_id in used:
                    unsatisfied.append(
                        UnsatisfiedSlot(
                            source_id=nearest.source_id,
                            source_revision=nearest.source_revision,
                            target_slot_index=slot_index,
                            target_presentation_time=RationalValue.from_fraction(target),
                        )
                    )
                    source_unsatisfied += 1
                    continue
                used.add(nearest.view_id)
                actual = nearest.presentation_timestamp.seconds()  # type: ignore[union-attr]
                provisional.append(
                    SelectedView(
                        view_id=nearest.view_id,
                        source_id=nearest.source_id,
                        source_revision=nearest.source_revision,
                        media_type=nearest.media_type,
                        selection_order=len(provisional),
                        target_slot_index=slot_index,
                        target_presentation_time=RationalValue.from_fraction(target),
                        actual_presentation_time=RationalValue.from_fraction(actual),
                        time_error=RationalValue.from_fraction(actual - target),
                        reason=SelectionReason.FIXED_FPS,
                    )
                )
                source_selected += 1
        first = source_views[0]
        counts.append(
            SourceSelectionCount(
                source_id=first.source_id,
                source_revision=first.source_revision,
                candidate_count=len(source_views),
                selected_count=source_selected,
                unsatisfied_slot_count=source_unsatisfied,
            )
        )

    selected = SelectedViewSet(
        candidate_artifact_id=candidate_artifact.artifact_id,
        candidate_semantic_digest=candidate_artifact.semantic_digest,
        settings=settings,
        selected_views=tuple(provisional),
        unsatisfied_slots=tuple(unsatisfied),
        counts_per_source=tuple(counts),
        total_selected_count=len(provisional),
    )
    validate_selected_against_candidate(selected, candidate)
    return selected
