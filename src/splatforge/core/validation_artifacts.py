"""Small M9 publication receipts: exact lineage separate from numerical identity."""

from typing import Literal
from uuid import UUID

from splatforge.core.features import Digest, digest_json
from splatforge.core.reconstruction_selection import ReconstructionSelectionArtifact
from splatforge.core.reconstruction_validation import (
    ReconstructionMetrics,
    ValidationGeometryInput,
    ValidationUniverse,
)
from splatforge.core.validation_policy import ReconstructionValidationReport
from splatforge.core.views import FrozenModel


def geometry_recipe(reconstruction: str, native: str, universe: str) -> str:
    # Transport scan cache only. Native hashes never enter canonical geometry or
    # measurement identity. A repacked model re-canonicalizes, then reuses metrics.
    return digest_json(
        {
            "scan_version": 1,
            "reconstruction": reconstruction,
            "native_payload": native,
            "universe": universe,
        }
    )


class ValidationGeometryArtifact(FrozenModel):
    contract_version: Literal[1] = 1
    reconstruction_artifact_id: UUID
    candidate_artifact_id: UUID
    selected_artifact_id: UUID
    universe: ValidationUniverse
    native_payload_digest: Digest
    geometry: ValidationGeometryInput

    @property
    def semantic_digest(self) -> str:
        return self.geometry.semantic_digest

    @property
    def recipe_key(self) -> str:
        return geometry_recipe(
            self.geometry.reconstruction_digest,
            self.native_payload_digest,
            self.universe.semantic_digest,
        )


class ReconstructionMetricsArtifact(FrozenModel):
    contract_version: Literal[1] = 1
    reconstruction_artifact_id: UUID
    geometry_artifact_id: UUID
    metrics: ReconstructionMetrics

    @property
    def semantic_digest(self) -> str:
        return self.metrics.semantic_digest

    @property
    def recipe_key(self) -> str:
        return self.metrics.recipe_key


class ReconstructionReportArtifact(FrozenModel):
    contract_version: Literal[1] = 1
    reconstruction_artifact_id: UUID
    metrics_artifact_id: UUID
    geometry_artifact_id: UUID
    report: ReconstructionValidationReport

    @property
    def semantic_digest(self) -> str:
        return self.report.semantic_digest

    @property
    def recipe_key(self) -> str:
        return self.report.recipe_key


ValidationArtifact = (
    ValidationGeometryArtifact
    | ReconstructionMetricsArtifact
    | ReconstructionReportArtifact
    | ReconstructionSelectionArtifact
)
