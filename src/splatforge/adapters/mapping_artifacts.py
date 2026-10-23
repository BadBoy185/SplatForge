"""Full mapping validation shared by publication, cache and orphan recovery."""

from pathlib import Path

from splatforge.adapters.artifact_validation import (
    ValidatedArtifact,
    _payload_digest,
    _plain_file,
    _read_bounded,
)
from splatforge.adapters.colmap_reconstruction import read_component, read_components
from splatforge.adapters.feature_database import NativeFeaturePayload
from splatforge.adapters.mapping_database import camera_state_digest, inspect_mapping_input
from splatforge.adapters.matching_database import CAMERA_MODELS, readonly_database
from splatforge.core.execution import ArtifactManifest, PayloadFile
from splatforge.core.geometry import GEOMETRY_ARTIFACT_TYPE, CameraPriorSet
from splatforge.core.reconstruction import (
    MAX_RECONSTRUCTION_METADATA_BYTES,
    ClassicalMappingReceipt,
    IncrementalMapperSettings,
    ReconstructionSet,
)


def read_receipt(directory: Path) -> ClassicalMappingReceipt:
    return ClassicalMappingReceipt.model_validate_json(
        _read_bounded(
            directory / "mapping.json", MAX_RECONSTRUCTION_METADATA_BYTES, "Mapping receipt"
        )
    )


def validate_mapping_output(
    output: Path,
    verified_payloads: dict[str, PayloadFile] | None,
) -> ValidatedArtifact:
    from contextlib import closing

    reconstruction = ReconstructionSet.model_validate_json(
        _read_bounded(
            output / "reconstruction.json", MAX_RECONSTRUCTION_METADATA_BYTES, "ReconstructionSet"
        )
    )
    receipt = read_receipt(output)
    receipt.require_output(reconstruction)
    mapping = NativeFeaturePayload.model_validate_json(
        _read_bounded(output / "backend_mapping.json", 32 * 1024**2, "Native image mapping")
    )
    priors = CameraPriorSet.model_validate_json(
        _read_bounded(output / "input_cameras.json", 64 * 1024**2, "Original camera priors")
    )
    if camera_state_digest(priors) != receipt.mapping_input.cameras_digest:
        raise ValueError("mapping.input_mismatch: original camera prior snapshot differs")
    actual_input = inspect_mapping_input(output / "mapping.db", mapping)
    if actual_input != receipt.calibration.mapping_input_after:
        raise ValueError("mapping.input_mismatch: calibrated numerical payload differs")
    maximum = 1 if isinstance(receipt.settings, IncrementalMapperSettings) else None
    if read_components(output, mapping, maximum_components=maximum) != reconstruction.components:
        raise ValueError(
            "mapping.malformed_output: component metadata/digests differ from native state"
        )
    with closing(readonly_database(output / "mapping.db")) as db:
        expected = {
            i.view_id: db.execute(
                "SELECT c.model,c.width,c.height FROM cameras c JOIN images i "
                "ON i.camera_id=c.camera_id WHERE i.image_id=?",
                (i.image_id,),
            ).fetchone()
            for i in mapping.images
        }
    for component in reconstruction.components:
        if component.registered_view_count < receipt.settings.min_model_size:
            raise ValueError(
                "mapping.malformed_output: component below explicit minimum model size"
            )
        _, cameras, views = read_component(output / component.native_payload, mapping)
        by_id = {c.camera_id: c for c in cameras}
        for view in views:
            c = by_id[view.camera_id]
            if (CAMERA_MODELS[c.model], c.width, c.height) != expected[view.view_id]:
                raise ValueError("mapping.invalid_camera: input/output model or dimensions differ")
    required = {
        "reconstruction.json",
        "mapping.json",
        "mapping.db",
        "backend_mapping.json",
        "input_cameras.json",
    }
    required |= {
        f"{c.native_payload}/{p.name}"
        for c in reconstruction.components
        for p in (output / c.native_payload).iterdir()
    }
    if (output / "sparse" / "project.ini").exists():
        required.add("sparse/project.ini")
    actual = set()
    for path in output.rglob("*"):
        if path.is_symlink() or path.is_junction():
            raise ValueError("mapping.malformed_output: redirected artifact payload")
        if path.is_file():
            actual.add(path.relative_to(output).as_posix())
    if actual not in (required, required | {"manifest.json"}):
        raise ValueError("mapping.malformed_output: missing/unexpected reconstruction payloads")
    payloads = []
    for name in sorted(required):
        path = output / name
        if not _plain_file(path) or path.stat().st_nlink != 1:
            raise ValueError("mapping.malformed_output: payload must be a plain independent file")
        size, digest = _payload_digest(output, path, verified_payloads)
        payloads.append(PayloadFile(path=name, size=size, sha256=digest))
    return ValidatedArtifact(
        payloads=tuple(payloads),
        parsed=reconstruction,
        semantic_digest=reconstruction.semantic_digest,
    )


def validate_mapping_lineage(parsed: ReconstructionSet, manifest: ArtifactManifest) -> None:
    if len(manifest.input_lineage) != 1 or len(parsed.upstream) != 1:
        raise ValueError("mapping.input_mismatch: reconstruction lineage count")
    native, public = manifest.input_lineage[0], parsed.upstream[0]
    if (
        native.input_name != "verified_geometry"
        or native.artifact_type != GEOMETRY_ARTIFACT_TYPE
        or native.contract_version != 1
        or native.artifact_id != public.artifact_id
        or native.semantic_digest != public.semantic_digest
        or manifest.recipe_key != parsed.recipe_key
    ):
        raise ValueError("mapping.input_mismatch: reconstruction upstream/recipe lineage")
