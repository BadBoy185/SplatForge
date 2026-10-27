"""Saved intent for the initial project format; no storage or runtime state."""

from datetime import timedelta
from pathlib import PurePosixPath, PureWindowsPath
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, JsonValue, field_validator

from splatforge.core.models import PipelineConfig
from splatforge.core.source_participation import SourceParticipationIntent


class MethodSettingsEnvelope(BaseModel):
    """Preserve opaque settings and extension fields, including future versions."""

    model_config = ConfigDict(extra="allow", allow_inf_nan=False)
    __pydantic_extra__: dict[str, JsonValue] = Field(init=False)

    method_id: str = Field(min_length=1, strict=True)
    settings_schema_version: int = Field(ge=1, strict=True)
    settings: dict[str, JsonValue]


class ProjectSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    config_schema_version: Literal[1]
    frame_selection: MethodSettingsEnvelope
    feature_extraction: MethodSettingsEnvelope
    pair_selection: MethodSettingsEnvelope
    feature_matching: MethodSettingsEnvelope
    mapping: MethodSettingsEnvelope
    training: MethodSettingsEnvelope


class PresetProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    version: int = Field(ge=1, strict=True)


class ProjectDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_format_version: Literal[1]
    project_id: UUID
    revision: int = Field(ge=0, strict=True)
    label: str = Field(min_length=1)
    created_at: AwareDatetime
    updated_at: AwareDatetime
    inventory_reference: str | None
    preset_provenance: PresetProvenance | None
    settings: ProjectSettings
    source_participation: SourceParticipationIntent = Field(
        default_factory=SourceParticipationIntent,
    )

    @field_validator("created_at", "updated_at")
    @classmethod
    def timestamps_must_be_utc(cls, value: AwareDatetime) -> AwareDatetime:
        if value.utcoffset() != timedelta(0):
            raise ValueError("project timestamps must use UTC")
        return value

    @field_validator("inventory_reference")
    @classmethod
    def relative_inventory_reference(cls, value: str | None) -> str | None:
        if value is None:
            return None
        windows = PureWindowsPath(value)
        parts = value.split("/")
        if (
            not value
            or windows.drive
            or windows.root
            or PurePosixPath(value).is_absolute()
            or "\\" in value
            or any(part in ("", ".", "..") for part in parts)
            or ":" in value
        ):
            raise ValueError("inventory_reference must be a project-relative path using '/'")
        return value


def settings_from_pipeline(config: PipelineConfig) -> ProjectSettings:
    """Explicit prototype conversion, not a migration or a preset lookup."""
    frame = config.frame_selection
    sfm = config.sfm

    def envelope(method_id: str, settings: dict[str, JsonValue]) -> MethodSettingsEnvelope:
        return MethodSettingsEnvelope(
            method_id=method_id, settings_schema_version=1, settings=settings
        )

    return ProjectSettings(
        config_schema_version=1,
        frame_selection=envelope(
            frame.method_id,
            {
                "target_fps": frame.target_fps,
                "max_frames": frame.max_frames,
                "reject_blur": frame.reject_blur,
                "reject_duplicates": frame.reject_duplicates,
            },
        ),
        feature_extraction=envelope(sfm.feature_extractor_id, {}),
        pair_selection=envelope(sfm.pair_selector_id, {}),
        feature_matching=envelope(sfm.feature_matcher_id, {}),
        mapping=envelope(sfm.mapper_id, {}),
        training=envelope(config.training.trainer_id, {"preset": config.training.preset}),
    )
