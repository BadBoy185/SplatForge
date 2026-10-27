"""Portable source participation and a read-only processing selection contract."""

from collections.abc import Iterable
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator


class SourceParticipationIntent(BaseModel):
    model_config = ConfigDict(extra="allow", frozen=True, allow_inf_nan=False)
    __pydantic_extra__: dict[str, JsonValue] = Field(init=False)

    schema_version: int = Field(default=1, ge=1, strict=True)
    excluded_source_ids: tuple[UUID, ...] = ()

    @field_validator("excluded_source_ids")
    @classmethod
    def canonical_ids(cls, value: tuple[UUID, ...]) -> tuple[UUID, ...]:
        return tuple(sorted(set(value), key=str))


class ParticipationDiagnostic(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    code: Literal["unknown_excluded_sources", "unsupported_participation_version"]
    source_ids: tuple[UUID, ...] = ()
    message: str


class EffectiveSources(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    registered_source_ids: tuple[UUID, ...]
    included_source_ids: tuple[UUID, ...]
    excluded_source_ids: tuple[UUID, ...]
    unknown_excluded_source_ids: tuple[UUID, ...]
    supported: bool = True
    diagnostics: tuple[ParticipationDiagnostic, ...] = ()

    def processing_source_ids(self, requested: set[UUID] | None = None) -> set[UUID]:
        """Resolve a run subset; explicit requests cannot bypass project exclusions."""
        if not self.supported:
            raise ValueError("Unsupported source participation version; processing is unavailable")
        included = set(self.included_source_ids)
        if requested is None:
            selected = included
        else:
            unknown = requested - set(self.registered_source_ids)
            if unknown:
                raise ValueError("Unknown source IDs: " + ", ".join(sorted(map(str, unknown))))
            excluded = requested - included
            if excluded:
                raise ValueError(
                    "Restore excluded sources before processing: "
                    + ", ".join(sorted(map(str, excluded)))
                )
            selected = requested
        if not selected:
            raise ValueError("No included sources selected; restore sources before Prepare Data")
        return set(selected)


def resolve_effective_sources(
    registered_source_ids: Iterable[UUID], participation: SourceParticipationIntent,
) -> EffectiveSources:
    """Resolve UUID membership without reading originals or changing saved intent."""
    registered = set(registered_source_ids)
    excluded = set(participation.excluded_source_ids)
    unknown = tuple(sorted(excluded - registered, key=str))
    diagnostics = []
    supported = participation.schema_version == 1
    if not supported:
        diagnostics.append(ParticipationDiagnostic(
            code="unsupported_participation_version",
            message="Source participation uses an unsupported version. Processing is unavailable.",
        ))
    if unknown:
        diagnostics.append(ParticipationDiagnostic(
            code="unknown_excluded_sources", source_ids=unknown,
            message=(
                f"{len(unknown)} saved exclusions reference sources absent from this inventory."
            ),
        ))
    return EffectiveSources(
        registered_source_ids=tuple(sorted(registered, key=str)),
        included_source_ids=tuple(sorted(registered - excluded, key=str)) if supported else (),
        excluded_source_ids=tuple(sorted(registered & excluded, key=str)) if supported else (),
        unknown_excluded_source_ids=unknown, supported=supported, diagnostics=tuple(diagnostics),
    )
