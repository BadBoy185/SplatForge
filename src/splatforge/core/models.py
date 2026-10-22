from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StageKind(StrEnum):
    QUALITY_ASSESSMENT = "quality_assessment"
    FRAME_SELECTION = "frame_selection"
    MASKING = "masking"
    FEATURE_EXTRACTION = "feature_extraction"
    PAIR_SELECTION = "pair_selection"
    FEATURE_MATCHING = "feature_matching"
    GEOMETRIC_VERIFICATION = "geometric_verification"
    MAPPING = "mapping"
    VALIDATION = "validation"
    TRAINING = "training"
    EXPORT = "export"


class MethodSpec(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    display_name: str
    stage: StageKind
    descriptor_family: str | None = None
    accepts_descriptor_families: frozenset[str] = Field(default_factory=frozenset)
    experimental: bool = False
    notes: str | None = None


class FrameSelectionConfig(BaseModel):
    method_id: str = "frame_selection.sharpest_interval"
    target_fps: float = Field(default=2.0, gt=0)
    max_frames: int | None = Field(default=1800, gt=0)
    reject_blur: bool = True
    reject_duplicates: bool = True


class SfMConfig(BaseModel):
    feature_extractor_id: str = "feature_extraction.aliked"
    pair_selector_id: str = "pair_selection.sequential"
    feature_matcher_id: str = "feature_matching.lightglue_aliked"
    mapper_id: str = "mapping.colmap_global"


class TrainingConfig(BaseModel):
    trainer_id: str = "training.none"
    preset: str = "balanced"


class PipelineConfig(BaseModel):
    schema_version: int = 1
    frame_selection: FrameSelectionConfig = Field(default_factory=FrameSelectionConfig)
    sfm: SfMConfig = Field(default_factory=SfMConfig)
    training: TrainingConfig = Field(default_factory=TrainingConfig)

    @model_validator(mode="after")
    def schema_must_be_supported(self) -> PipelineConfig:
        if self.schema_version != 1:
            raise ValueError(f"Unsupported config schema_version={self.schema_version}")
        return self
