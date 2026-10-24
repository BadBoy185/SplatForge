"""Small explicit retention/eviction receipts; cleanup never accepts arbitrary paths."""

from typing import Literal
from uuid import UUID

from pydantic import Field

from splatforge.core.features import Digest, digest_json
from splatforge.core.views import FrozenModel


class CleanupPayload(FrozenModel):
    path: str
    size: int = Field(ge=0)
    sha256: Digest


class CleanupCandidate(FrozenModel):
    artifact_id: UUID
    artifact_type: str
    manifest_digest: Digest
    payloads: tuple[CleanupPayload, ...]
    state: Literal["eligible", "evicting"] = "eligible"


class CleanupPlan(FrozenModel):
    contract_version: Literal[1] = 1
    project_id: UUID
    candidates: tuple[CleanupCandidate, ...]
    protected_artifact_ids: tuple[UUID, ...]
    total_bytes: int

    @property
    def preview_digest(self) -> str:
        return digest_json(self.model_dump(mode="json"))


class ArtifactEvictedError(ValueError):
    """Durably intentional eviction, distinct from missing/corrupt payloads."""
