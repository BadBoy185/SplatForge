"""Portable user organization, independent of processing/calibration groups."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator


class LogicalSourceGroup(BaseModel):
    model_config = ConfigDict(extra="allow", frozen=True)
    __pydantic_extra__: dict[str, JsonValue] = Field(init=False)

    group_id: UUID
    label: str = Field(min_length=1, max_length=120)

    @field_validator("label")
    @classmethod
    def clean_label(cls, value: str) -> str:
        label = " ".join(value.split())
        if not label:
            raise ValueError("Group name cannot be empty")
        return label


class LogicalSourceGroups(BaseModel):
    model_config = ConfigDict(extra="allow", frozen=True, allow_inf_nan=False)
    __pydantic_extra__: dict[str, JsonValue] = Field(init=False)

    schema_version: int = Field(default=1, ge=1, strict=True)
    groups: tuple[LogicalSourceGroup, ...] = ()
    source_assignments: dict[UUID, UUID] = Field(default_factory=dict)

    @field_validator("groups")
    @classmethod
    def canonical_groups(
        cls, value: tuple[LogicalSourceGroup, ...],
    ) -> tuple[LogicalSourceGroup, ...]:
        return tuple(sorted(value, key=lambda g: str(g.group_id)))

    @field_validator("source_assignments")
    @classmethod
    def canonical_assignments(cls, value: dict[UUID, UUID]) -> dict[UUID, UUID]:
        return dict(sorted(value.items(), key=lambda item: str(item[0])))

    @model_validator(mode="after")
    def unique_groups(self) -> LogicalSourceGroups:
        ids = [g.group_id for g in self.groups]
        if len(set(ids)) != len(ids):
            raise ValueError("Duplicate logical group UUID")
        return self

    def label_for(self, source_id: UUID) -> str | None:
        if self.schema_version != 1:
            return None
        identity = self.source_assignments.get(source_id)
        return next((g.label for g in self.groups if g.group_id == identity), None)
