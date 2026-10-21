"""Typed records for the concrete fake execution route."""

from __future__ import annotations

from datetime import timedelta
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from splatforge.core.media import ExecutableIdentity, SourceOccurrence, VerificationPolicyId
from splatforge.core.pairs import (
    PAIR_ARTIFACT_TYPE,
    PairEndpoints,
    PairingViewUniverse,
    PairResourceLimits,
    PairSettings,
    canonical_explicit_pairs,
)
from splatforge.core.project import ProjectDocument
from splatforge.core.quality import (
    QUALITY_ARTIFACT_CONTRACT_VERSION,
    QUALITY_ARTIFACT_TYPE,
    QualityAnalysisSettings,
    QualityBackendIdentity,
    SharpestIntervalSettings,
)
from splatforge.core.views import (
    CANDIDATE_ARTIFACT_TYPE,
    SELECTED_ARTIFACT_TYPE,
    VIEW_ARTIFACT_CONTRACT_VERSION,
    CandidatePoolSettings,
    CandidateResourceLimits,
    FixedFpsSettings,
)


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


class FailureCategory(StrEnum):
    TRANSIENT = "transient"
    INTERRUPTED = "interrupted"
    NON_RETRYABLE = "non_retryable"


class TeardownState(StrEnum):
    NOT_REQUIRED = "not_required"
    CONFIRMED = "confirmed"
    UNRESOLVED = "unresolved"


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
    determinism_policy: Literal["deterministic_integer_json_v1"] = "deterministic_integer_json_v1"


class ViewPreparationNode(FrozenModel):
    node_id: Literal["candidate_views"] = "candidate_views"
    method_id: Literal["view_preparation.ffmpeg_fixed_pool"] = "view_preparation.ffmpeg_fixed_pool"
    method_version: Literal[1] = 1
    settings_schema_version: Literal[1] = 1
    settings: CandidatePoolSettings
    output: OutputReference


class FixedFpsSelectionNode(FrozenModel):
    node_id: Literal["selected_views"] = "selected_views"
    method_id: Literal["frame_selection.fixed_fps"] = "frame_selection.fixed_fps"
    method_version: Literal[1] = 1
    settings_schema_version: Literal[1] = 1
    settings: FixedFpsSettings
    input: OutputReference
    output: OutputReference


class ViewPreparationRoute(FrozenModel):
    route_id: Literal["views.prepare_fixed_fps"] = "views.prepare_fixed_fps"
    route_version: Literal[1] = 1
    inventory_reference: str = Field(min_length=1)
    inventory_content_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    sources: tuple[SourceOccurrence, ...] = Field(min_length=1)
    verification_policy: VerificationPolicyId
    ffmpeg_backend: ExecutableIdentity
    resource_limits: CandidateResourceLimits
    candidate: ViewPreparationNode
    selection: FixedFpsSelectionNode
    target: OutputReference
    execution_policy: Literal["sequential_two_stage"] = "sequential_two_stage"
    determinism_policy: Literal["deterministic_views_v1"] = "deterministic_views_v1"

    @model_validator(mode="after")
    def two_node_references_are_consistent(self) -> ViewPreparationRoute:
        if (
            self.candidate.output.node_id != self.candidate.node_id
            or self.candidate.output.artifact_type != CANDIDATE_ARTIFACT_TYPE
            or self.candidate.output.contract_version != VIEW_ARTIFACT_CONTRACT_VERSION
        ):
            raise ValueError("candidate output reference does not match the M3 contract")
        if self.selection.input != self.candidate.output:
            raise ValueError("selection input must reference the candidate output")
        if (
            self.selection.output.node_id != self.selection.node_id
            or self.selection.output.artifact_type != SELECTED_ARTIFACT_TYPE
            or self.selection.output.contract_version != VIEW_ARTIFACT_CONTRACT_VERSION
            or self.target != self.selection.output
        ):
            raise ValueError("selection output/target reference does not match the M3 contract")
        return self


class QualityAssessmentNode(FrozenModel):
    node_id: Literal["quality_assessment"] = "quality_assessment"
    method_id: Literal["quality_assessment.pillow_edge_dhash"] = (
        "quality_assessment.pillow_edge_dhash"
    )
    method_version: Literal[1] = 1
    settings_schema_version: Literal[1] = 1
    settings: QualityAnalysisSettings
    input: OutputReference
    output: OutputReference


class SharpestIntervalSelectionNode(FrozenModel):
    node_id: Literal["selected_views"] = "selected_views"
    method_id: Literal["frame_selection.sharpest_interval"] = "frame_selection.sharpest_interval"
    method_version: Literal[1] = 1
    settings_schema_version: Literal[1] = 1
    settings: SharpestIntervalSettings
    candidate_input: OutputReference
    quality_input: OutputReference
    output: OutputReference


class SharpestViewPreparationRoute(FrozenModel):
    route_id: Literal["views.prepare_sharpest_interval"] = "views.prepare_sharpest_interval"
    route_version: Literal[1] = 1
    inventory_reference: str = Field(min_length=1)
    inventory_content_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    sources: tuple[SourceOccurrence, ...] = Field(min_length=1)
    verification_policy: VerificationPolicyId
    ffmpeg_backend: ExecutableIdentity
    quality_backend: QualityBackendIdentity
    resource_limits: CandidateResourceLimits
    candidate: ViewPreparationNode
    quality: QualityAssessmentNode
    selection: SharpestIntervalSelectionNode
    target: OutputReference
    execution_policy: Literal["sequential_three_stage"] = "sequential_three_stage"
    determinism_policy: Literal["deterministic_quality_views_v1"] = "deterministic_quality_views_v1"

    @model_validator(mode="after")
    def three_node_references_are_consistent(self) -> SharpestViewPreparationRoute:
        if (
            self.candidate.output.node_id != self.candidate.node_id
            or self.candidate.output.artifact_type != CANDIDATE_ARTIFACT_TYPE
            or self.candidate.output.contract_version != VIEW_ARTIFACT_CONTRACT_VERSION
        ):
            raise ValueError("candidate output reference does not match the M3 contract")
        if self.quality.input != self.candidate.output:
            raise ValueError("quality input must reference the candidate output")
        if (
            self.quality.output.node_id != self.quality.node_id
            or self.quality.output.artifact_type != QUALITY_ARTIFACT_TYPE
            or self.quality.output.contract_version != QUALITY_ARTIFACT_CONTRACT_VERSION
        ):
            raise ValueError("quality output reference does not match the M4 contract")
        if (
            self.selection.candidate_input != self.candidate.output
            or self.selection.quality_input != self.quality.output
        ):
            raise ValueError("sharpest selection inputs must reference candidate and quality")
        if (
            self.selection.output.node_id != self.selection.node_id
            or self.selection.output.artifact_type != SELECTED_ARTIFACT_TYPE
            or self.selection.output.contract_version != VIEW_ARTIFACT_CONTRACT_VERSION
            or self.target != self.selection.output
        ):
            raise ValueError("selection output/target reference does not match the M4 contract")
        return self


class CancellationRequest(FrozenModel):
    schema_version: Literal[1] = 1
    request_id: UUID
    run_id: UUID
    run_owner_token: UUID
    requested_at: AwareDatetime

    @field_validator("requested_at")
    @classmethod
    def request_timestamp_must_be_utc(cls, value: AwareDatetime) -> AwareDatetime:
        if value.utcoffset() != timedelta(0):
            raise ValueError("cancellation request timestamps must use UTC")
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


class PairSelectionRoute(FrozenModel):
    route_id: Literal["pairs.build"] = "pairs.build"
    route_version: Literal[1] = 1
    views_run_id: UUID
    candidate: ArtifactHandle
    selected: ArtifactHandle
    universe: PairingViewUniverse
    settings: PairSettings
    explicit_pairs: tuple[PairEndpoints, ...] = Field(max_length=1_000_000)
    resource_limits: PairResourceLimits
    node_id: Literal["pair_set"] = "pair_set"
    target: OutputReference = OutputReference(
        node_id="pair_set",
        output_name="pairs",
        artifact_type=PAIR_ARTIFACT_TYPE,
        contract_version=1,
    )

    def input_lineage(self) -> tuple[ArtifactInputLineage, ...]:
        return tuple(
            ArtifactInputLineage(input_name=name, **handle.model_dump(exclude={"manifest_path"}))
            for name, handle in (
                ("candidate_views", self.candidate),
                ("selected_views", self.selected),
            )
        )

    def literal_inputs(self) -> dict[str, object]:
        return {
            "pair_settings": self.settings.model_dump(mode="json"),
            "explicit_pairs": [p.model_dump(mode="json") for p in self.explicit_pairs],
            "resource_limits": self.resource_limits.model_dump(mode="json"),
        }

    @model_validator(mode="after")
    def exact_contracts(self) -> PairSelectionRoute:
        if (
            self.candidate.artifact_type != CANDIDATE_ARTIFACT_TYPE
            or self.selected.artifact_type != SELECTED_ARTIFACT_TYPE
            or self.candidate.contract_version != 1
            or self.selected.contract_version != 1
        ):
            raise ValueError("pair route requires candidate/selected contract 1")
        if self.target != OutputReference(
            node_id=self.node_id,
            output_name="pairs",
            artifact_type=PAIR_ARTIFACT_TYPE,
            contract_version=1,
        ):
            raise ValueError("pair output reference differs from PairSet v1")
        if self.explicit_pairs != canonical_explicit_pairs(self.universe, self.explicit_pairs):
            raise ValueError("pair route explicit pairs are not canonical")
        return self


class RunSnapshot(FrozenModel):
    schema_version: Literal[1] = 1
    run_id: UUID
    project_id: UUID
    project_revision: int = Field(ge=0, strict=True)
    owner_token: UUID
    created_at: AwareDatetime
    project_intent: ProjectDocument
    route: Annotated[
        FakeRoute | ViewPreparationRoute | SharpestViewPreparationRoute | PairSelectionRoute,
        Field(discriminator="route_id"),
    ]

    @field_validator("created_at")
    @classmethod
    def timestamp_must_be_utc(cls, value: AwareDatetime) -> AwareDatetime:
        if value.utcoffset() != timedelta(0):
            raise ValueError("run timestamps must use UTC")
        return value


class CacheIneligible(FrozenModel):
    artifact_id: UUID
    reason: str


class CacheLookup(FrozenModel):
    artifact: ArtifactHandle | None = None
    ineligible: tuple[CacheIneligible, ...] = ()


class AttemptExecution(FrozenModel):
    attempt_id: UUID
    workspace: Annotated[str, Field(min_length=1)]


class CancellationRequestResult(FrozenModel):
    request: CancellationRequest
    created: bool
    too_late: bool = False


class PublishedArtifact(FrozenModel):
    handle: ArtifactHandle
    manifest: ArtifactManifest


class RunWarning(FrozenModel):
    code: str
    message: str


class RecoveryResult(FrozenModel):
    run_id: UUID
    status: RunStatus
    adopted_attempts: tuple[UUID, ...] = ()
    interrupted_attempts: tuple[UUID, ...] = ()
    warnings: tuple[RunWarning, ...] = ()


class FakeRunResult(FrozenModel):
    run_id: UUID
    status: RunStatus
    outputs: dict[str, ArtifactHandle]
    cache_hits: tuple[str, ...]
    warnings: tuple[RunWarning, ...] = ()


class ViewsRunResult(FrozenModel):
    run_id: UUID
    status: RunStatus
    candidate_artifact: ArtifactHandle | None
    quality_artifact: ArtifactHandle | None = None
    selected_artifact: ArtifactHandle | None
    cache_hits: tuple[str, ...]
    candidate_count: int = Field(ge=0, strict=True)
    quality_measured_count: int = Field(default=0, ge=0, strict=True)
    quality_unavailable_count: int = Field(default=0, ge=0, strict=True)
    selected_count: int = Field(ge=0, strict=True)
    rejected_count: int = Field(default=0, ge=0, strict=True)
    unsatisfied_interval_count: int = Field(default=0, ge=0, strict=True)
    warnings: tuple[RunWarning, ...] = ()
