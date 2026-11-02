"""Portable, exact-run manual frame review and immutable effective selections."""

from datetime import datetime
from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

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
)

ReviewDecision = Literal["automatic", "exclude", "include"]
ReviewFilter = Literal["selected", "rejected", "all"]


class FrameReviewIntent(BaseModel):
    """Future schemas/entries survive unrelated project saves unchanged."""

    model_config = ConfigDict(extra="allow", frozen=True, allow_inf_nan=False)
    __pydantic_extra__: dict[str, JsonValue] = Field(init=False)
    schema_version: int = Field(default=1, ge=1, strict=True)
    bindings: dict[str, JsonValue] = Field(default_factory=dict)


class ManualDecision(FrozenModel):
    view_id: UUID
    decision: Literal["exclude", "include"]


class ReviewBinding(FrozenModel):
    run_id: UUID
    candidate_artifact_id: UUID
    candidate_semantic_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    automatic_artifact_id: UUID
    automatic_semantic_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    decisions: tuple[ManualDecision, ...] = Field(max_length=MAX_VIEWS)
    effective_run_id: UUID

    @model_validator(mode="after")
    def canonical(self) -> "ReviewBinding":
        ids = [d.view_id.int for d in self.decisions]
        if ids != sorted(set(ids)):
            raise ValueError("Review decisions must be unique and in canonical UUID order")
        return self

    @property
    def review_digest(self) -> str:
        return sha256_bytes(
            canonical_json_bytes(
                self.model_dump(
                    mode="json",
                    exclude={"effective_run_id"},
                )
            )
        )


class ReviewedView(FrozenModel):
    view_id: UUID
    source_id: UUID
    source_revision: int = Field(ge=1, strict=True)
    media_type: MediaType
    selection_order: int = Field(ge=0, strict=True)


class ReviewedSelectedViewSet(FrozenModel):
    contract_version: Literal[1] = 1
    selection_method_id: Literal["frame_selection.manual_review"] = "frame_selection.manual_review"
    selection_method_version: Literal[1] = 1
    binding: ReviewBinding
    selected_views: tuple[ReviewedView, ...] = Field(max_length=MAX_VIEWS)

    @property
    def candidate_artifact_id(self) -> UUID:
        return self.binding.candidate_artifact_id

    @property
    def candidate_semantic_digest(self) -> str:
        return self.binding.candidate_semantic_digest

    @property
    def total_selected_count(self) -> int:
        return len(self.selected_views)

    @model_validator(mode="after")
    def canonical(self) -> "ReviewedSelectedViewSet":
        ids = [v.view_id.int for v in self.selected_views]
        if ids != sorted(set(ids)) or [v.selection_order for v in self.selected_views] != list(
            range(len(ids))
        ):
            raise ValueError("Reviewed selection must have canonical UUIDs and contiguous order")
        return self


AutomaticSelection = SelectedViewSet | SharpestSelectedViewSet
EffectiveSelection = AutomaticSelection | ReviewedSelectedViewSet


def reviewed_digest(selected: ReviewedSelectedViewSet) -> str:
    return sha256_bytes(
        canonical_json_bytes(
            selected.model_dump(
                mode="json",
                exclude={"binding": {"effective_run_id"}},
            )
        )
    )


def build_reviewed_selection(
    binding: ReviewBinding,
    candidate: CandidateViewSet,
    automatic: AutomaticSelection,
) -> ReviewedSelectedViewSet:
    if (
        binding.candidate_semantic_digest != candidate_semantic_digest(candidate)
        or automatic.candidate_semantic_digest != binding.candidate_semantic_digest
    ):
        raise ValueError("Review candidate semantics differ from the bound automatic selection")
    candidates = {v.view_id: v for v in candidate.views}
    selected = {v.view_id for v in automatic.selected_views}
    if not selected <= candidates.keys():
        raise ValueError("Automatic selection contains an unknown candidate UUID")
    if any(
        (v.source_id, v.source_revision, v.media_type)
        != (
            candidates[v.view_id].source_id,
            candidates[v.view_id].source_revision,
            candidates[v.view_id].media_type,
        )
        for v in automatic.selected_views
    ):
        raise ValueError("Automatic selection differs from candidate source identity")
    for item in binding.decisions:
        if item.view_id not in candidates:
            raise ValueError("Review contains an unknown candidate UUID")
        if item.decision == "include":
            selected.add(item.view_id)
        else:
            selected.discard(item.view_id)
    views = tuple(
        ReviewedView(
            **candidates[view_id].model_dump(
                include={
                    "view_id",
                    "source_id",
                    "source_revision",
                    "media_type",
                }
            ),
            selection_order=order,
        )
        for order, view_id in enumerate(sorted(selected, key=lambda v: v.int))
    )
    return ReviewedSelectedViewSet(binding=binding, selected_views=views)


class ReviewScopeOption(FrozenModel):
    key: str
    label: str
    kind: Literal["all", "source", "group", "device", "fallback"]
    source_count: int
    candidate_count: int
    selected_count: int
    rejected_count: int


class ReviewProvenance(FrozenModel):
    """Saved preparation evidence, separate from today's inventory presentation."""

    source_id: UUID
    source_revision: int
    media_type: MediaType
    source_name: str
    path_at_preparation: str | None = None
    current_locator: str | None = None
    current_source_state: Literal[
        "same_source", "revision_mismatch", "not_in_inventory", "unavailable"
    ] = "unavailable"
    source_check: str | None = None
    source_checked_at: datetime | None = None
    timestamp: FrameTimestamp | None = None
    width: int | None = None
    height: int | None = None
    stream_index: int | None = None
    device_label: str | None = None
    current_group_label: str | None = None
    automatic_score: NonNegativeRational | None = None


class ReviewItem(FrozenModel):
    view_id: UUID
    path: Path
    caption: str
    auto_selected: bool
    decision: ReviewDecision
    included: bool
    auto_reason: str
    reason: str
    previous_view_id: UUID | None = None
    next_view_id: UUID | None = None
    source_id: UUID | None = None
    provenance: ReviewProvenance | None = None


class ReviewPage(FrozenModel):
    project_id: UUID
    project_revision: int
    run_id: UUID
    review_digest: str
    effective_run_id: UUID
    candidate_count: int
    auto_selected_count: int
    selected_count: int
    rejected_count: int
    manual_count: int
    offset: int
    total: int
    items: tuple[ReviewItem, ...]
    scope_key: str = "all"
    scope_label: str = "All sources"
    scopes: tuple[ReviewScopeOption, ...] = ()
    scope_candidate_count: int | None = None
    scope_auto_selected_count: int | None = None
    scope_selected_count: int | None = None
    scope_rejected_count: int | None = None
    scope_manual_count: int | None = None


class ReviewResult(FrozenModel):
    project_revision: int
    review_digest: str
    effective_run_id: UUID
