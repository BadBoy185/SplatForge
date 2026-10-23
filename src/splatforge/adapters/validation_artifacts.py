"""Bounded typed M9 artifact checks shared by publish/cache/recovery."""

from pathlib import Path

from splatforge.adapters.artifact_validation import (
    ValidatedArtifact,
    _payload_digest,
    _plain_file,
    _read_bounded,
)
from splatforge.core.execution import ArtifactManifest, PayloadFile
from splatforge.core.reconstruction_selection import (
    SELECTION_ARTIFACT_TYPE,
    ReconstructionSelectionArtifact,
)
from splatforge.core.reconstruction_validation import (
    GEOMETRY_ARTIFACT_TYPE,
    MAX_VALIDATION_METADATA_BYTES,
    METRICS_ARTIFACT_TYPE,
    REPORT_ARTIFACT_TYPE,
)
from splatforge.core.validation_artifacts import (
    ReconstructionMetricsArtifact,
    ReconstructionReportArtifact,
    ValidationArtifact,
    ValidationGeometryArtifact,
)

VALIDATION_TYPES = {
    GEOMETRY_ARTIFACT_TYPE: ValidationGeometryArtifact,
    METRICS_ARTIFACT_TYPE: ReconstructionMetricsArtifact,
    REPORT_ARTIFACT_TYPE: ReconstructionReportArtifact,
    SELECTION_ARTIFACT_TYPE: ReconstructionSelectionArtifact,
}


def validate_validation_output(
    output: Path,
    artifact_type: str,
    verified_payloads: dict[str, PayloadFile] | None,
) -> ValidatedArtifact:
    files = {p.name for p in output.iterdir()}
    if files not in ({"evidence.json"}, {"evidence.json", "manifest.json"}):
        raise ValueError("M9 publication requires exactly evidence.json")
    path = output / "evidence.json"
    if not _plain_file(path) or path.stat().st_nlink != 1:
        raise ValueError("Unsafe M9 publication payload")
    parsed = VALIDATION_TYPES[artifact_type].model_validate_json(
        _read_bounded(path, MAX_VALIDATION_METADATA_BYTES, "M9 evidence")
    )
    size, digest = _payload_digest(output, path, verified_payloads)
    return ValidatedArtifact(
        payloads=(PayloadFile(path="evidence.json", size=size, sha256=digest),),
        parsed=parsed,
        semantic_digest=parsed.semantic_digest,
    )


def validate_validation_lineage(parsed: ValidationArtifact, manifest: ArtifactManifest) -> None:
    inputs = {i.input_name: i for i in manifest.input_lineage}
    expected = {"reconstruction": parsed.reconstruction_artifact_id}
    if isinstance(parsed, ValidationGeometryArtifact):
        expected.update(
            candidate_views=parsed.candidate_artifact_id, selected_views=parsed.selected_artifact_id
        )
    elif isinstance(parsed, ReconstructionMetricsArtifact):
        expected["validation_geometry"] = parsed.geometry_artifact_id
    elif isinstance(parsed, ReconstructionReportArtifact):
        expected["reconstruction_metrics"] = parsed.metrics_artifact_id
        expected["validation_geometry"] = parsed.geometry_artifact_id
    else:
        expected.update(
            validation_report=parsed.report_artifact_id,
            reconstruction_metrics=parsed.metrics_artifact_id,
            validation_geometry=parsed.geometry_artifact_id,
        )
    if (
        manifest.contract_version != 1
        or set(inputs) != set(expected)
        or len(inputs) != len(manifest.input_lineage)
        or any(inputs[k].artifact_id != v for k, v in expected.items())
        or manifest.recipe_key != parsed.recipe_key
    ):
        raise ValueError("validation.input_mismatch: publication lineage/recipe differs")
