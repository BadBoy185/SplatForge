"""M9 extensions to the existing execution repository, never a second store."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from uuid import UUID

from splatforge.core.execution import (
    ArtifactHandle,
    ReconstructionEvidenceRoute,
    ReconstructionValidationRoute,
)
from splatforge.core.features import digest_json
from splatforge.core.reconstruction_selection import ReconstructionSelectionArtifact
from splatforge.core.reconstruction_validation import (
    MAX_VALIDATION_METADATA_BYTES,
    ValidationUniverse,
    ValidationView,
)
from splatforge.core.validation_artifacts import (
    ReconstructionMetricsArtifact,
    ReconstructionReportArtifact,
    ValidationArtifact,
    ValidationGeometryArtifact,
)
from splatforge.core.views import canonical_json_bytes


class ValidationStorageMixin:
    @contextmanager
    def validation_evidence_operation(self) -> Iterator[None]:
        from splatforge.adapters.artifact_validation import ArtifactValidationContext

        previous = self._validation_context
        if previous is not None and previous.mapping_integrity_only:
            yield
            return
        self._validation_context = ArtifactValidationContext(mapping_integrity_only=True)
        try:
            yield
        finally:
            self._validation_context = previous

    def lineage_handle(self, root: Path, handle: ArtifactHandle, name: str) -> ArtifactHandle:
        manifest = self._validate_indexed_artifact(root, handle, metadata_only=True)[0]
        inputs = [i for i in manifest.input_lineage if i.input_name == name]
        if len(inputs) != 1:
            raise ValueError("validation.input_mismatch: missing/ambiguous historical " + name)
        lineage = inputs[0]
        with self._read_connection(root) as db:
            row = db.execute(
                "SELECT manifest_path FROM artifacts WHERE artifact_id=? "
                "AND artifact_type=? AND contract_version=? AND semantic_digest=? AND recipe_key=?",
                (
                    str(lineage.artifact_id),
                    lineage.artifact_type,
                    lineage.contract_version,
                    lineage.semantic_digest,
                    lineage.recipe_key,
                ),
            ).fetchone()
        if row is None:
            raise ValueError("validation.input_mismatch: exact lineage artifact is not indexed")
        return ArtifactHandle(**lineage.model_dump(exclude={"input_name"}), manifest_path=row[0])

    def validation_universe(
        self, root: Path, reconstruction: ArtifactHandle
    ) -> tuple[ArtifactHandle, ArtifactHandle, ValidationUniverse]:
        with self.validation_evidence_operation():
            return self._validation_universe(root, reconstruction)

    def _validation_universe(self, root: Path, reconstruction: ArtifactHandle):
        # The exact classical path is intentional. Future direct backends can supply
        # their own frozen selected/candidate ancestry without pretending to be M7.
        verified = self.lineage_handle(root, reconstruction, "verified_geometry")
        matches = self.lineage_handle(root, verified, "match_set")
        features = self.lineage_handle(root, matches, "local_features")
        candidate = self.lineage_handle(root, features, "candidate_views")
        selected = self.lineage_handle(root, features, "selected_views")
        candidates, selection = self.load_pairing_inputs(root, candidate, selected)
        ids = {v.view_id for v in selection.selected_views}
        universe = ValidationUniverse(
            views=tuple(
                ValidationView(
                    view_id=v.view_id,
                    source_id=v.source_id,
                    source_group_id=v.source_group_id,
                    camera_group_id=v.camera_group_id,
                    media_type=v.media_type,
                )
                for v in sorted(candidates.views, key=lambda v: v.view_id.int)
                if v.view_id in ids
            )
        )
        universe.require_reconstruction(self.load_reconstruction(root, reconstruction))
        return candidate, selected, universe

    def validation_native_digest(self, root: Path, handle: ArtifactHandle) -> str:
        manifest = self._validate_indexed_artifact(root, handle, metadata_only=True)[0]
        return digest_json(
            [
                p.model_dump(mode="json")
                for p in manifest.payloads
                if p.path.startswith("sparse/")
                or p.path in {"input_cameras.json", "backend_mapping.json"}
            ]
        )

    def load_validation_artifact(self, root: Path, handle: ArtifactHandle) -> ValidationArtifact:
        with self.validation_evidence_operation():
            parsed = self._validate_indexed_artifact(root, handle, metadata_only=True)[2].parsed
        if not isinstance(
            parsed,
            (
                ValidationGeometryArtifact,
                ReconstructionMetricsArtifact,
                ReconstructionReportArtifact,
                ReconstructionSelectionArtifact,
            ),
        ):
            raise ValueError("Artifact is not an M9 validation publication")
        return parsed

    def write_validation_artifact(self, workspace: Path, value: ValidationArtifact) -> None:
        output = workspace / "output"
        output.mkdir()
        data = canonical_json_bytes(value.model_dump(mode="json"))
        if len(data) > MAX_VALIDATION_METADATA_BYTES:
            raise ValueError("validation.resource_limit: evidence metadata exceeds 64 MiB")
        self._write_new_file(output / "evidence.json", data)

    def validate_validation_inputs(self, root: Path, route: ReconstructionEvidenceRoute) -> None:
        from splatforge.application.reconstruction_validation import require_validation_inputs

        require_validation_inputs(self, root, route)

    def validation_run_context(
        self, root: Path, run_id: UUID
    ) -> tuple[ReconstructionValidationRoute, ArtifactHandle]:
        snapshot = self._load_run_snapshot(root, run_id)
        if not isinstance(snapshot.route, ReconstructionValidationRoute):
            raise ValueError("--validation-run requires a successful M9 validation report run")
        report = self.resolve_run_output(root, run_id, "reconstruction_validation", "report")
        self.validate_validation_inputs(root, snapshot.route)
        return snapshot.route, report
