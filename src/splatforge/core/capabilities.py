"""Immutable environment-capability records for COLMAP Doctor diagnostics."""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from splatforge.core.media import ExecutableIdentity


class CapabilityStatus(StrEnum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


def required_status(statuses: tuple[CapabilityStatus, ...]) -> CapabilityStatus:
    """All required prerequisites must be positively verified."""

    if CapabilityStatus.UNAVAILABLE in statuses:
        return CapabilityStatus.UNAVAILABLE
    if not statuses or CapabilityStatus.UNKNOWN in statuses:
        return CapabilityStatus.UNKNOWN
    return CapabilityStatus.AVAILABLE


def alternative_status(statuses: tuple[CapabilityStatus, ...]) -> CapabilityStatus:
    """One verified explicit alternative suffices; unknown never becomes available."""

    if CapabilityStatus.AVAILABLE in statuses:
        return CapabilityStatus.AVAILABLE
    if not statuses or CapabilityStatus.UNKNOWN in statuses:
        return CapabilityStatus.UNKNOWN
    return CapabilityStatus.UNAVAILABLE


class ImplementationStatus(StrEnum):
    IMPLEMENTED = "implemented"
    PLANNED = "planned"


class ExecutableSource(StrEnum):
    EXPLICIT = "explicit"
    ENVIRONMENT = "environment"
    BUNDLED = "bundled"
    PATH = "path"


class EvidenceDetail(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    key: str = Field(min_length=1, max_length=128)
    value: str = Field(max_length=1024)


class CapabilityEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    evidence_schema_version: Literal[1] = 1
    capability_id: str = Field(min_length=1, max_length=128)
    status: CapabilityStatus
    diagnostic_code: str = Field(min_length=1, max_length=128)
    message: str = Field(min_length=1, max_length=1024)
    observed_at: AwareDatetime
    expires_at: AwareDatetime
    freshness_seconds: int = Field(ge=0, le=3600, strict=True)
    backend_identity: ExecutableIdentity | None = None
    details: tuple[EvidenceDetail, ...] = Field(default=(), max_length=32)
    prerequisites: tuple[str, ...] = Field(default=(), max_length=32)

    @model_validator(mode="after")
    def validate_times(self) -> CapabilityEvidence:
        if self.observed_at.utcoffset() != timedelta(0):
            raise ValueError("capability observation time must use UTC")
        if self.expires_at.utcoffset() != timedelta(0):
            raise ValueError("capability expiry time must use UTC")
        if self.expires_at < self.observed_at:
            raise ValueError("capability evidence cannot expire before observation")
        if self.expires_at != self.observed_at + timedelta(seconds=self.freshness_seconds):
            raise ValueError("capability expiry must match its declared freshness")
        return self

    def current_at(self, observed_at: datetime) -> CapabilityEvidence:
        if self.observed_at <= observed_at < self.expires_at:
            return self
        return self.model_copy(
            update={
                "status": CapabilityStatus.UNKNOWN,
                "diagnostic_code": "capability.evidence_not_current",
                "message": (
                    "Evidence expired; re-run Doctor to observe this capability again. "
                    + self.message
                )[:1024],
            }
        )


class FreshnessPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    freshness_schema_version: Literal[1] = 1
    static_cli_seconds: int = Field(default=300, gt=0, le=3600, strict=True)
    resource_health_seconds: int = Field(default=30, gt=0, le=300, strict=True)
    binary_identity_rule: Literal["same_concrete_file_identity"] = "same_concrete_file_identity"


class ColmapRuntimeLayout(BaseModel):
    """Bounded adapter evidence, separate from native executable byte identity."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    profile: Literal["windows_official_prebuilt_v1"] = "windows_official_prebuilt_v1"
    installation_root: str = Field(min_length=1, max_length=4096)
    native_executable: str = Field(min_length=1, max_length=4096)
    path_entries: tuple[str, ...] = Field(min_length=1, max_length=3)
    qt_platform_plugin_directory: str | None = Field(default=None, max_length=4096)


class ExecutableSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source: ExecutableSource
    requested: str = Field(min_length=1, max_length=4096)
    identity: ExecutableIdentity
    runtime_layout: ColmapRuntimeLayout | None = None


class SubcommandDiscovery(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    command: str = Field(min_length=1, max_length=128)
    evidence: CapabilityEvidence
    parser_profile: Literal[
        "typed_enum_v1", "native_options_v2", "legacy_sift_v1", "options_v1", "unknown",
    ]
    tokens: tuple[str, ...] = Field(default=(), max_length=128)
    option_names: tuple[str, ...] = Field(default=(), max_length=512)
    model_defaults: tuple[EvidenceDetail, ...] = Field(default=(), max_length=32)


class CommandDiscovery(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    parser_schema_version: Literal[1] = 1
    evidence: CapabilityEvidence
    commands: tuple[str, ...] = Field(default=(), max_length=256)
    feature_tokens: tuple[str, ...] = Field(default=(), max_length=128)
    matcher_tokens: tuple[str, ...] = Field(default=(), max_length=128)
    option_names: tuple[str, ...] = Field(default=(), max_length=512)
    model_defaults: tuple[EvidenceDetail, ...] = Field(default=(), max_length=32)
    subcommands: tuple[SubcommandDiscovery, ...] = Field(default=(), max_length=16)
    bounded_excerpts: tuple[EvidenceDetail, ...] = Field(default=(), max_length=16)


class DatabaseTableEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1, max_length=128)
    columns: tuple[str, ...]
    primary_key_columns: tuple[str, ...] = ()


class DatabaseCompatibility(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    probe_schema_version: Literal[1] = 1
    evidence: CapabilityEvidence
    sqlite_user_version: int | None = Field(default=None, strict=True)
    sqlite_application_id: int | None = Field(default=None, strict=True)
    tables: tuple[DatabaseTableEvidence, ...] = ()


class ModelEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    model_schema_version: Literal[1] = 1
    role: str = Field(min_length=1, max_length=128)
    configured_source: str = Field(min_length=1, max_length=128)
    expected_name: str | None = Field(default=None, max_length=512)
    expected_root: str | None = Field(default=None, max_length=4096)
    checked_path: str | None = Field(default=None, max_length=4096)
    resolved_path: str | None = Field(default=None, max_length=4096)
    size: int | None = Field(default=None, ge=0, strict=True)
    sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    source_uri: str | None = Field(default=None, max_length=2048)
    expected_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    compatibility_verified: bool = False
    evidence: CapabilityEvidence


class GpuDevice(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1, max_length=256)
    driver_version: str = Field(min_length=1, max_length=128)
    total_vram_mib: int = Field(ge=0, strict=True)
    free_vram_mib: int = Field(ge=0, strict=True)
    compute_capability: str | None = Field(default=None, max_length=64)


class GpuReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    probe_schema_version: Literal[1] = 1
    executable: ExecutableIdentity | None = None
    evidence: CapabilityEvidence
    devices: tuple[GpuDevice, ...] = Field(default=(), max_length=32)


class ColmapProbeReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    probe_schema_version: Literal[1] = 1
    selected_executable: ExecutableSelection | None = None
    binary: CapabilityEvidence
    command_discovery: CommandDiscovery
    capabilities: tuple[CapabilityEvidence, ...]
    database: DatabaseCompatibility
    models: tuple[ModelEvidence, ...] = ()
    deep: bool

    def capability(self, capability_id: str) -> CapabilityEvidence:
        if self.binary.capability_id == capability_id:
            return self.binary
        if self.database.evidence.capability_id == capability_id:
            return self.database.evidence
        for item in (
            self.command_discovery.evidence,
            *self.capabilities,
            *(entry.evidence for entry in self.command_discovery.subcommands),
            *(model.evidence for model in self.models),
        ):
            if item.capability_id == capability_id:
                return item
        raise KeyError(capability_id)


class MethodCapability(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    method_id: str = Field(min_length=1, max_length=128)
    catalogued: bool
    supported_by_splatforge: bool = False
    implementation_status: ImplementationStatus
    backend_capability_status: CapabilityStatus
    runnable: bool
    diagnostic_code: str = Field(min_length=1, max_length=128)
    message: str = Field(min_length=1, max_length=1024)
    prerequisites: tuple[str, ...] = ()

    @model_validator(mode="after")
    def runnable_requires_every_gate(self) -> MethodCapability:
        if self.runnable and (
            not self.catalogued
            or self.implementation_status != ImplementationStatus.IMPLEMENTED
            or self.backend_capability_status != CapabilityStatus.AVAILABLE
        ):
            raise ValueError("runnable requires catalogued, implemented, available capability")
        return self


class DoctorReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    doctor_schema_version: Literal[1] = 1
    observed_at: AwareDatetime
    deep: bool
    freshness_policy: FreshnessPolicy
    colmap: ColmapProbeReport
    gpu: GpuReport
    methods: tuple[MethodCapability, ...]
    warnings: tuple[CapabilityEvidence, ...] = Field(default=(), max_length=32)

    @field_validator("observed_at")
    @classmethod
    def observation_is_utc(cls, value: AwareDatetime) -> AwareDatetime:
        if value.utcoffset() != timedelta(0):
            raise ValueError("Doctor observation time must use UTC")
        return value
