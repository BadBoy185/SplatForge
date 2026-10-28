"""Immutable media inventory and source-verification value models."""

from __future__ import annotations

from datetime import timedelta
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from splatforge.core.capture_metadata import CaptureMetadata


class MediaType(StrEnum):
    PHOTO = "photo"
    VIDEO = "video"


class StorageKind(StrEnum):
    LOCAL_FIXED = "local_fixed"
    NETWORK = "network"
    REMOVABLE = "removable"
    UNKNOWN = "unknown"


class VerificationPolicyId(StrEnum):
    BALANCED_LOCAL = "balanced_local"
    STRICT = "strict"


class VerificationAssurance(StrEnum):
    METADATA_UNCHANGED = "metadata_unchanged"
    CONTENT_VERIFIED = "content_verified"
    UNAVAILABLE = "unavailable"


class VerificationOutcome(StrEnum):
    UNCHANGED = "unchanged"
    CHANGED = "changed"
    MISSING = "missing"
    UNAVAILABLE = "unavailable"
    STRICT_UNAVAILABLE = "strict_unavailable"
    CANCELLED = "cancelled"


class RehashReason(StrEnum):
    STRICT_POLICY = "strict_policy"
    METADATA_CHANGED = "metadata_changed"
    IDENTITY_CHANGED = "identity_changed"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    UNTRUSTED_STORAGE = "untrusted_storage"


class ExecutableIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    resolved_path: str = Field(min_length=1)
    size: int = Field(ge=0, strict=True)
    last_write_ns: int = Field(ge=0, strict=True)
    volume_id: str | None = Field(default=None, max_length=128)
    file_id: str | None = Field(default=None, max_length=128)
    change_time_ns: int | None = Field(default=None, ge=0, strict=True)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    version_line: str | None = Field(default=None, max_length=1024)


class SourceEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    evidence_schema_version: Literal[1] = 1
    size: int = Field(ge=0, strict=True)
    last_write_ns: int | None = Field(default=None, ge=0, strict=True)
    volume_id: str | None = Field(default=None, max_length=128)
    file_id: str | None = Field(default=None, max_length=128)
    change_time_ns: int | None = Field(default=None, ge=0, strict=True)
    storage_kind: StorageKind
    evidence_available: bool
    detail: str | None = Field(default=None, max_length=512)

    @property
    def trusted_local(self) -> bool:
        return (
            self.evidence_available
            and self.storage_kind == StorageKind.LOCAL_FIXED
            and self.last_write_ns is not None
            and self.volume_id is not None
            and self.file_id is not None
            and self.change_time_ns is not None
        )


class FullHashEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    hashed_at: AwareDatetime
    byte_count: int = Field(ge=0, strict=True)
    evidence_before: SourceEvidence
    evidence_after: SourceEvidence
    stability_mechanism: str = Field(min_length=1, max_length=128)

    @field_validator("hashed_at")
    @classmethod
    def timestamp_must_be_utc(cls, value: AwareDatetime) -> AwareDatetime:
        if value.utcoffset() != timedelta(0):
            raise ValueError("hash time must use UTC")
        return value


class NormalizedProbe(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    probe_schema_version: Literal[1] = 1
    backend: ExecutableIdentity
    selected_visual_stream_index: int = Field(ge=0, strict=True)
    codec_name: str | None = None
    width: int = Field(gt=0, strict=True)
    height: int = Field(gt=0, strict=True)
    orientation: int | None = Field(default=None, ge=1, le=8, strict=True)
    time_base: str | None = None
    average_frame_rate: str | None = None
    raw_frame_rate: str | None = None
    duration: str | None = None
    frame_count: int | None = Field(default=None, ge=0, strict=True)
    rotation_degrees: int | None = Field(default=None, strict=True)
    capture: CaptureMetadata | None = None


class SourceOccurrence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    record_type: Literal["source"] = "source"
    source_id: UUID
    source_revision: int = Field(ge=1, strict=True)
    external_locator: str = Field(min_length=1)
    display_filename: str = Field(min_length=1)
    original_filename: str | None = Field(default=None, min_length=1)
    media_type: MediaType
    extension: Literal[".jpg", ".jpeg", ".png", ".mp4", ".mov"]
    byte_size: int = Field(ge=0, strict=True)
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    last_full_hash_at: AwareDatetime
    full_hash_evidence: FullHashEvidence
    source_group_id: UUID
    camera_group_id: UUID
    calibration_policy: Literal["metadata_only"] = "metadata_only"
    probe: NormalizedProbe

    @field_validator("last_full_hash_at")
    @classmethod
    def timestamp_must_be_utc(cls, value: AwareDatetime) -> AwareDatetime:
        if value.utcoffset() != timedelta(0):
            raise ValueError("last full-hash time must use UTC")
        return value

    @model_validator(mode="after")
    def consistent_hash_evidence(self) -> SourceOccurrence:
        if self.byte_size != self.full_hash_evidence.byte_count:
            raise ValueError("source byte size differs from full-hash evidence")
        if self.last_full_hash_at != self.full_hash_evidence.hashed_at:
            raise ValueError("source full-hash times differ")
        if self.probe.orientation is not None and self.media_type != MediaType.PHOTO:
            raise ValueError("EXIF orientation applies only to photos")
        if self.media_type == MediaType.PHOTO and self.extension not in {".jpg", ".jpeg", ".png"}:
            raise ValueError("photo source has a video extension")
        if self.media_type == MediaType.VIDEO and self.extension not in {".mp4", ".mov"}:
            raise ValueError("video source has a photo extension")
        return self


class InventoryHeader(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    record_type: Literal["inventory"] = "inventory"
    inventory_schema_version: Literal[1] = 1
    inventory_id: UUID
    project_id: UUID
    inventory_revision: int = Field(ge=1, strict=True)
    parent_inventory_id: UUID | None
    created_at: AwareDatetime
    source_count: int = Field(ge=0, strict=True)

    @field_validator("created_at")
    @classmethod
    def timestamp_must_be_utc(cls, value: AwareDatetime) -> AwareDatetime:
        if value.utcoffset() != timedelta(0):
            raise ValueError("inventory creation time must use UTC")
        return value


class SourceInventory(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    header: InventoryHeader
    sources: tuple[SourceOccurrence, ...]

    @model_validator(mode="after")
    def validate_inventory(self) -> SourceInventory:
        if self.header.source_count != len(self.sources):
            raise ValueError("inventory source_count is incorrect")
        ids = [source.source_id for source in self.sources]
        if len(ids) != len(set(ids)):
            raise ValueError("inventory contains duplicate source IDs")
        return self


class VerificationResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    verification_id: UUID
    source_id: UUID
    source_revision: int = Field(ge=1, strict=True)
    expected_content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    policy_id: VerificationPolicyId
    policy_version: Literal[1] = 1
    checked_at: AwareDatetime
    baseline_evidence: SourceEvidence | None
    current_evidence: SourceEvidence | None
    full_hash_performed: bool
    observed_content_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    rehash_reason: RehashReason | None
    assurance: VerificationAssurance
    stability_mechanism: str | None = Field(default=None, max_length=128)
    outcome: VerificationOutcome
    diagnostic_code: str = Field(min_length=1, max_length=128)
    diagnostic_message: str = Field(min_length=1, max_length=1024)

    @field_validator("checked_at")
    @classmethod
    def timestamp_must_be_utc(cls, value: AwareDatetime) -> AwareDatetime:
        if value.utcoffset() != timedelta(0):
            raise ValueError("verification time must use UTC")
        return value
