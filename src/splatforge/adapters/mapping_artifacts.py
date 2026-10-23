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


def validate_mapping_integrity_receipt(
    output: Path,
    verified_payloads: dict[str, PayloadFile],
) -> ValidatedArtifact:
    """M9-only read of bytes proven equal to an indexed validated M8 publication.

    The caller must check indexed successful producer/validator, manifest digest,
    and freshly SHA-verify *every* payload. This is reuse of structural evidence,
    not a claim of a fresh point/track scan. M8 publication/cache/recovery never
    uses this shortcut. No additional persistent validation cache is introduced.
    """
    reconstruction = ReconstructionSet.model_validate_json(
        _read_bounded(
            output / "reconstruction.json", MAX_RECONSTRUCTION_METADATA_BYTES, "ReconstructionSet"
        )
    )
    receipt = read_receipt(output)
    receipt.require_output(reconstruction)
    priors = CameraPriorSet.model_validate_json(
        _read_bounded(output / "input_cameras.json", 64 * 1024**2, "Original camera priors")
    )
    mapping = NativeFeaturePayload.model_validate_json(
        _read_bounded(output / "backend_mapping.json", 32 * 1024**2, "Native image mapping")
    )
    if (
        camera_state_digest(priors) != receipt.mapping_input.cameras_digest
        or tuple(i.view_id for i in mapping.images) != reconstruction.input_view_ids
    ):
        raise ValueError("mapping.input_mismatch: frozen metadata receipt differs")
    required = {
        "reconstruction.json",
        "mapping.json",
        "mapping.db",
        "backend_mapping.json",
        "input_cameras.json",
    }
    for component in reconstruction.components:
        directory = output / component.native_payload
        if directory.is_symlink() or directory.is_junction() or not directory.is_dir():
            raise ValueError("mapping.malformed_output: unsafe component payload")
        files = {p.name for p in directory.iterdir()}
        native = {"cameras.bin", "images.bin", "points3D.bin"}
        if files not in (native, native | {"rigs.bin", "frames.bin"}):
            raise ValueError("mapping.malformed_output: sparse payload set differs")
        required.update(f"{component.native_payload}/{name}" for name in files)
    if (output / "sparse" / "project.ini").exists():
        required.add("sparse/project.ini")
    expected_models = {Path(c.native_payload).name for c in reconstruction.components}
    if "sparse/project.ini" in required:
        expected_models.add("project.ini")
    if {p.name for p in (output / "sparse").iterdir()} != expected_models:
        raise ValueError("mapping.malformed_output: unexpected native model entry")
    if any(
        not _plain_file(output / name) or (output / name).stat().st_nlink != 1 for name in required
    ):
        raise ValueError("mapping.malformed_output: payload must be independent plain files")
    actual = set()
    for path in output.rglob("*"):
        if path.is_symlink() or path.is_junction():
            raise ValueError("mapping.malformed_output: redirected payload")
        if path.is_file() and path.name != "manifest.json":
            actual.add(path.relative_to(output).as_posix())
    if actual != required or set(verified_payloads) != required:
        raise ValueError("mapping.malformed_output: integrity receipt payload set differs")
    return ValidatedArtifact(
        payloads=tuple(verified_payloads[k] for k in sorted(required)),
        semantic_digest=reconstruction.semantic_digest,
        parsed=reconstruction,
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
