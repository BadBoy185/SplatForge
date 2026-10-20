"""Typed records for the concrete M1b1 execution route."""

from __future__ import annotations

from datetime import timedelta
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator

from splatforge.core.project import ProjectDocument


class FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class AttemptStatus(StrEnum):
    """Storage vocabulary; M1b1 only drives pending/running/terminal happy paths."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"


class RunStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"


class OutputReference(FrozenModel):
    node_id: str = Field(min_length=1)
    output_name: str = Field(min_length=1)
    artifact_type: str = Field(min_length=1)
    contract_version: int = Field(ge=1, strict=True)


class SequenceSettings(FrozenModel):
    count: int = Field(default=3, ge=1, le=10_000, strict=True)


class ScaleSettings(FrozenModel):
    factor: int = Field(default=2, ge=-1_000_000, le=1_000_000, strict=True)


class SequenceNode(FrozenModel):
    node_id: Literal["numbers"] = "numbers"
    method_id: Literal["fake.sequence"] = "fake.sequence"
    method_version: Literal[1] = 1
    settings_schema_version: Literal[1] = 1
    settings: SequenceSettings
    start: int = Field(ge=-1_000_000, le=1_000_000, strict=True)
    output: OutputReference


class ScaleNode(FrozenModel):
    node_id: Literal["scaled"] = "scaled"
    method_id: Literal["fake.scale"] = "fake.scale"
    method_version: Literal[1] = 1
    settings_schema_version: Literal[1] = 1
    settings: ScaleSettings
    input: OutputReference
    output: OutputReference


class FakeRoute(FrozenModel):
    route_id: Literal["fake.two_node"] = "fake.two_node"
    route_version: Literal[1] = 1
    sequence: SequenceNode
    adapter_id: Literal["splatforge.fake_python"] = "splatforge.fake_python"
    adapter_version: Literal[1] = 1
    seed_policy: Literal["no_randomness"] = "no_randomness"
    scale: ScaleNode
    target: OutputReference
    execution_policy: Literal["sequential_single_stage"] = "sequential_single_stage"
    determinism_policy: Literal["deterministic_integer_json_v1"] = (
        "deterministic_integer_json_v1"
    )


class RunSnapshot(FrozenModel):
    schema_version: Literal[1] = 1
    run_id: UUID
    project_id: UUID
    project_revision: int = Field(ge=0, strict=True)
    owner_token: UUID
    created_at: AwareDatetime
    project_intent: ProjectDocument
    route: FakeRoute

    @field_validator("created_at")
    @classmethod
    def timestamp_must_be_utc(cls, value: AwareDatetime) -> AwareDatetime:
        if value.utcoffset() != timedelta(0):
            raise ValueError("run timestamps must use UTC")
        return value


class ArtifactInputLineage(FrozenModel):
    input_name: str = Field(min_length=1)
    artifact_id: UUID
    artifact_type: str = Field(min_length=1)
    contract_version: int = Field(ge=1, strict=True)
    semantic_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    recipe_key: str = Field(pattern=r"^[0-9a-f]{64}$")


class PayloadFile(FrozenModel):
    path: str = Field(min_length=1)
    size: int = Field(ge=0, strict=True)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class ValidationResult(FrozenModel):
    valid: Literal[True] = True
    validator_id: str = Field(min_length=1)
    validator_version: int = Field(ge=1, strict=True)


class ArtifactManifest(FrozenModel):
    manifest_schema_version: Literal[1] = 1
    artifact_id: UUID
    artifact_type: str = Field(min_length=1)
    contract_version: int = Field(ge=1, strict=True)
    producer_run_id: UUID
    producer_node_id: str = Field(min_length=1)
    producer_attempt_id: UUID
    recipe_key: str = Field(pattern=r"^[0-9a-f]{64}$")
    semantic_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    input_lineage: tuple[ArtifactInputLineage, ...]
    payloads: tuple[PayloadFile, ...]
    validation: ValidationResult


class ArtifactHandle(FrozenModel):
    artifact_id: UUID
    artifact_type: str
    contract_version: int
    recipe_key: str
    semantic_digest: str
    manifest_path: str


class CacheIneligible(FrozenModel):
    artifact_id: UUID
    reason: str


class CacheLookup(FrozenModel):
    artifact: ArtifactHandle | None = None
    ineligible: tuple[CacheIneligible, ...] = ()


class AttemptExecution(FrozenModel):
    attempt_id: UUID
    workspace: Annotated[str, Field(min_length=1)]


class PublishedArtifact(FrozenModel):
    handle: ArtifactHandle
    manifest: ArtifactManifest


class RunWarning(FrozenModel):
    code: str
    message: str


class FakeRunResult(FrozenModel):
    run_id: UUID
    status: RunStatus
    outputs: dict[str, ArtifactHandle]
    cache_hits: tuple[str, ...]
    warnings: tuple[RunWarning, ...] = ()
