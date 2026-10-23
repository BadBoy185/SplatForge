"""Factual explicit mapper comparison; no reconstruction quality ranking (M8b2)."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from splatforge.core.execution import ArtifactHandle
from splatforge.core.features import Digest
from splatforge.core.progress import ExecutionHardwareProfile
from splatforge.core.reconstruction import (
    GlobalMapperSettings,
    MapperSettings,
    MappingCalibrationPolicy,
    MappingResourceLimits,
    ViewGraphCalibrationSettings,
)
from splatforge.core.views import FrozenModel


class MappingComparisonRoute(FrozenModel):
    label: str = Field(min_length=1, max_length=128)
    settings: MapperSettings = GlobalMapperSettings()
    calibration_policy: MappingCalibrationPolicy = MappingCalibrationPolicy.PRESERVE_PRIORS
    calibration_settings: ViewGraphCalibrationSettings | None = None
    resource_limits: MappingResourceLimits = MappingResourceLimits()

    @model_validator(mode="before")
    @classmethod
    def resolve_calibration(cls, value: object) -> object:
        if (
            isinstance(value, dict)
            and value.get("calibration_policy") == MappingCalibrationPolicy.VIEW_GRAPH
            and value.get("calibration_settings") is None
        ):
            return {**value, "calibration_settings": ViewGraphCalibrationSettings()}
        return value

    @model_validator(mode="after")
    def explicit_policy(self) -> MappingComparisonRoute:
        if self.calibration_policy == MappingCalibrationPolicy.VIEW_GRAPH:
            if self.settings.method_id != "mapping.colmap_global":
                raise ValueError("Only Global accepts explicit view-graph calibration")
            if self.calibration_settings is None:
                raise ValueError("view_graph requires resolved calibration settings")
        elif self.calibration_settings is not None:
            raise ValueError("preserve_priors does not accept calibration settings")
        return self


class MappingComparisonPlan(FrozenModel):
    schema_version: Literal[1] = 1
    data_kind: Literal["synthetic_transport", "representative", "unspecified"] = "unspecified"
    routes: tuple[MappingComparisonRoute, ...] = Field(min_length=1, max_length=16)

    @model_validator(mode="after")
    def unique_labels(self) -> MappingComparisonPlan:
        if len({r.label for r in self.routes}) != len(self.routes):
            raise ValueError("Comparison route labels must be unique")
        return self


class MappingComparisonEntry(FrozenModel):
    label: str
    request: MappingComparisonRoute
    mapping_input_digest: Digest
    status: Literal["succeeded", "failed", "unavailable", "cancelled", "skipped"]
    run_id: UUID | None = None
    artifact: ArtifactHandle | None = None
    recipe_key: Digest | None = None
    backend: dict[str, object] | None = None
    api_seconds: float = Field(ge=0)
    native_seconds: float | None = Field(default=None, ge=0)
    estimated_workspace_bytes: int | None = Field(default=None, ge=0)
    component_count: int | None = None
    registered_views: int | None = None
    unregistered_views: int | None = None
    registration_coverage: float | None = Field(default=None, ge=0, le=1)
    native_point_count: int | None = Field(default=None, ge=0)
    semantic_digest: Digest | None = None
    cache_hit: bool | None = None
    warnings: tuple[str, ...] = ()
    reason: str | None = None
    failure_category: str | None = None
    diagnostics: dict[str, object] = {}


class MappingComparisonReport(FrozenModel):
    schema_version: Literal[1] = 1
    comparison_id: UUID
    verification_run_id: UUID
    mapping_input_digest: Digest
    hardware: ExecutionHardwareProfile
    data_kind: Literal["synthetic_transport", "representative", "unspecified"]
    routes: tuple[MappingComparisonEntry, ...] = Field(min_length=1, max_length=16)
    recommendation: Literal["pending_representative_benchmarks_and_m9"] = (
        "pending_representative_benchmarks_and_m9"
    )
    limitations: tuple[str, ...] = (
        "Native points and registration counts are factual metrics, not reconstruction quality",
        "No universal winner, production default change or automatic fallback is authorized",
        "Sequential explicit normal M8 runs reuse one immutable M7 input",
    )

    @model_validator(mode="after")
    def same_input(self) -> MappingComparisonReport:
        if any(r.mapping_input_digest != self.mapping_input_digest for r in self.routes):
            raise ValueError("Every comparison route must reference the same MappingInput")
        return self
