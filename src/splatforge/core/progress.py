"""Versioned diagnostic progress contracts, independent of numerical identity."""

from __future__ import annotations

from datetime import timedelta
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

Code = Annotated[str, Field(pattern=r"^[a-zA-Z0-9_.-]+$", min_length=1, max_length=128)]
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
NonNegative = Annotated[float, Field(ge=0)]


class ProgressValue(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False, strict=True)

    @field_validator(
        "observation_schema_version",
        "hardware_schema_version",
        "signature_schema_version",
        "sample_schema_version",
        "progress_schema_version",
        "performance_schema_version",
        "estimator_version",
        "work_model_version",
        mode="before",
        check_fields=False,
    )
    @classmethod
    def strict_schema_version(cls, value: object) -> object:
        if type(value) is not int:
            raise ValueError("Schema versions must be integers")
        return value

    @field_validator("observed_at", "recorded_at", check_fields=False)
    @classmethod
    def utc_timestamp(cls, value: AwareDatetime | None) -> AwareDatetime | None:
        if value is not None and value.utcoffset() != timedelta(0):
            raise ValueError("Progress/history timestamps must use UTC")
        return value


class WorkUnit(StrEnum):
    BYTES = "bytes"
    SOURCE_SECONDS = "source_seconds"
    FRAMES = "frames"
    IMAGES = "images"
    MEGAPIXELS = "megapixels"
    VIEWS = "views"
    PAIRS = "pairs"
    MATCHES = "matches"
    ITERATIONS = "iterations"
    STEPS = "steps"
    WORK = "work"


class ProgressMode(StrEnum):
    DETERMINATE = "determinate"
    PHASE = "phase"
    INDETERMINATE = "indeterminate"


class Confidence(StrEnum):
    UNAVAILABLE = "unavailable"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class EvidenceMode(StrEnum):
    COLD_MODEL = "cold_model"
    HISTORICAL = "historical"
    LIVE = "live"
    HYBRID = "hybrid"
    UNAVAILABLE = "unavailable"


class ProgressStatus(StrEnum):
    PLANNED = "planned"
    RUNNING = "running"
    STOPPING = "stopping"
    SUCCEEDED = "succeeded"
    CACHED = "cached"
    SKIPPED = "skipped"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"


class WorkMetric(ProgressValue):
    """Allowlisted numeric characteristics; never arbitrary user metadata."""

    name: Literal[
        "views",
        "sources",
        "source_seconds",
        "megapixels",
        "output_megapixels",
        "width",
        "height",
        "candidate_fps",
        "slots",
        "pairs",
        "photo_fraction",
        "completed_views",
        "descriptor_dimension",
        "descriptor_bytes",
        "features",
        "matches",
    ]
    value: NonNegative


class WorkDescription(ProgressValue):
    stage_id: Code
    node_id: Code
    method_id: Code
    method_version: int = Field(default=1, ge=1, strict=True)
    work_model_id: Code
    work_model_version: Literal[1] = 1
    unit: WorkUnit
    mode: ProgressMode = ProgressMode.DETERMINATE
    total: NonNegative | None
    plan_revision: int = Field(default=1, ge=1, strict=True)

    @model_validator(mode="after")
    def total_matches_mode(self) -> WorkDescription:
        if self.mode == ProgressMode.DETERMINATE and self.total is None:
            raise ValueError("Determinate work requires a total")
        if self.mode == ProgressMode.INDETERMINATE and self.total is not None:
            raise ValueError("Indeterminate work has no total")
        return self


class StageProgressObservation(ProgressValue):
    observation_schema_version: Literal[1] = 1
    work: WorkDescription
    phase_id: Code | None = None
    phase_code: Code | None = None
    completed: NonNegative
    observed_at: AwareDatetime
    elapsed_seconds: NonNegative
    diagnostics: tuple[WorkMetric, ...] = Field(default=(), max_length=16)

    @model_validator(mode="after")
    def within_plan(self) -> StageProgressObservation:
        if self.work.total is not None and self.completed > self.work.total:
            raise ValueError("Completed work exceeds total; revise the work plan explicitly")
        return self


class EstimatorEvidence(ProgressValue):
    similarity_score: float = Field(default=0, ge=0, le=1)
    historical_median_throughput: NonNegative | None = None
    historical_spread: NonNegative | None = None
    live_throughput: NonNegative | None = None
    live_completed_fraction: float | None = Field(default=None, ge=0, le=1)
    live_weight: float = Field(default=0, ge=0, le=1)


class EtaEstimate(ProgressValue):
    likely_seconds: NonNegative | None = None
    lower_seconds: NonNegative | None = None
    upper_seconds: NonNegative | None = None
    confidence: Confidence = Confidence.UNAVAILABLE
    estimator_id: Literal["eta.hybrid_throughput_v1"] = "eta.hybrid_throughput_v1"
    estimator_version: Literal[1] = 1
    evidence_mode: EvidenceMode = EvidenceMode.UNAVAILABLE
    sample_count: int = Field(default=0, ge=0, strict=True)
    reasons: tuple[Code, ...] = Field(default=(), max_length=16)
    evidence: EstimatorEvidence = EstimatorEvidence()

    @model_validator(mode="after")
    def ordered_range(self) -> EtaEstimate:
        values = (self.lower_seconds, self.likely_seconds, self.upper_seconds)
        if self.likely_seconds is None:
            if values != (None, None, None) or self.confidence != Confidence.UNAVAILABLE:
                raise ValueError("Unavailable ETA must have no range/confidence")
        elif any(value is None for value in values) or not (
            self.lower_seconds <= self.likely_seconds <= self.upper_seconds
        ):
            raise ValueError("ETA requires an ordered complete planning range")
        return self


class ExecutionHardwareProfile(ProgressValue):
    hardware_schema_version: Literal[1] = 1
    platform_family: Literal["windows", "linux", "darwin", "unknown"] = "unknown"
    cpu_family: Code = "unknown"
    logical_cpus: int | None = Field(default=None, ge=1, le=65536, strict=True)
    ram_gib_bucket: int | None = Field(default=None, ge=1, strict=True)
    device: Literal["cpu", "gpu", "unknown"] = "unknown"
    gpu_family: Code | None = None
    vram_gib_bucket: int | None = Field(default=None, ge=1, strict=True)
    driver_version: Code | None = None


class PerformanceBackendIdentity(ProgressValue):
    adapter_id: Code
    adapter_version: int = Field(default=1, ge=1, strict=True)
    family: Code
    runtime_version: Code
    executable_sha256: Digest | None = None
    model_sha256: Digest | None = None


class PerformanceSignature(ProgressValue):
    signature_schema_version: Literal[1] = 1
    stage_id: Code
    method_id: Code
    method_version: int = Field(default=1, ge=1, strict=True)
    work_model_id: Code
    work_model_version: Literal[1] = 1
    unit: WorkUnit
    hardware: ExecutionHardwareProfile
    backend: PerformanceBackendIdentity
    settings_key: Digest


class PerformanceSample(ProgressValue):
    sample_schema_version: Literal[1] = 1
    recorded_at: AwareDatetime
    signature: PerformanceSignature
    workload: tuple[WorkMetric, ...] = Field(default=(), max_length=16)
    total_work: float = Field(gt=0)
    elapsed_seconds: float = Field(gt=0)
    throughput: float = Field(gt=0)
    outcome: Literal["succeeded"] = "succeeded"

    @model_validator(mode="after")
    def consistent_rate(self) -> PerformanceSample:
        expected = self.total_work / self.elapsed_seconds
        if abs(self.throughput - expected) > max(1e-9, expected * 1e-6):
            raise ValueError("Throughput must equal completed work / elapsed")
        if len({metric.name for metric in self.workload}) != len(self.workload):
            raise ValueError("Workload metric names must be unique")
        return self


class StageProgressSnapshot(ProgressValue):
    work: WorkDescription
    status: ProgressStatus = ProgressStatus.PLANNED
    phase_id: Code | None = None
    phase_code: Code | None = None
    attempt_id: UUID | None = None
    elapsed_seconds: NonNegative = 0
    completed: NonNegative = 0
    fraction: float | None = Field(default=None, ge=0, le=1)
    throughput: NonNegative | None = None
    throughput_unit: WorkUnit
    eta: EtaEstimate = EtaEstimate()
    observed_at: AwareDatetime | None = None
    observation_age_seconds: NonNegative | None = None
    stale: bool = False


class PipelineProgressSnapshot(ProgressValue):
    progress_schema_version: Literal[1] = 1
    run_id: UUID
    status: Code
    elapsed_seconds: NonNegative
    current_node_id: Code | None = None
    current_stage: StageProgressSnapshot | None = None
    stages: tuple[StageProgressSnapshot, ...] = Field(default=(), max_length=256)
    completed_stages: tuple[Code, ...] = ()
    cached_stages: tuple[Code, ...] = ()
    skipped_stages: tuple[Code, ...] = ()
    unknown_stages: tuple[Code, ...] = ()
    fraction: float | None = Field(default=None, ge=0, le=1)
    recalculated_fraction: float | None = Field(default=None, ge=0, le=1)
    eta: EtaEstimate = EtaEstimate()
    warnings: tuple[Code, ...] = Field(default=(), max_length=16)


class PlannedStage(ProgressValue):
    work: WorkDescription
    signature: PerformanceSignature
    workload: tuple[WorkMetric, ...] = Field(default=(), max_length=16)
    disposition: Literal["planned", "cached", "skipped"] = "planned"

    @model_validator(mode="after")
    def matching_identity(self) -> PlannedStage:
        for name in (
            "stage_id",
            "method_id",
            "method_version",
            "work_model_id",
            "work_model_version",
            "unit",
        ):
            if getattr(self.work, name) != getattr(self.signature, name):
                raise ValueError(f"Work/signature mismatch: {name}")
        return self


class HistoryRead(ProgressValue):
    samples: tuple[PerformanceSample, ...] = Field(default=(), max_length=64)
    warnings: tuple[Code, ...] = Field(default=(), max_length=16)


class SignatureStatistics(ProgressValue):
    signature_key: Digest
    signature: PerformanceSignature
    count: int = Field(ge=0)
    median_throughput: NonNegative
    lower_throughput: NonNegative
    upper_throughput: NonNegative


class PerformanceStatistics(ProgressValue):
    performance_schema_version: Literal[1] = 1
    sample_count: int = Field(default=0, ge=0)
    signatures: tuple[SignatureStatistics, ...] = Field(default=(), max_length=256)
    warnings: tuple[Code, ...] = Field(default=(), max_length=16)
