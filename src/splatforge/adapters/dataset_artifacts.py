"""Full M10 publication/cache/recovery validation, no native-exit shortcut."""

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from splatforge.adapters.artifact_validation import (
    ValidatedArtifact,
    _payload_digest,
    _read_bounded,
    safe_payload_path,
)
from splatforge.adapters.dataset_reader import (
    SparseDatasetContent,
    read_dataset,
    require_observation_transform,
    require_preserved_geometry,
    sparse_content,
)
from splatforge.core.dataset import (
    COMPONENT_ARTIFACT_TYPE,
    MAX_METADATA_BYTES,
    PreparedDatasetComponent,
    PreparedDatasetSet,
)
from splatforge.core.execution import ArtifactManifest, DatasetRoute, PayloadFile

if TYPE_CHECKING:
    from splatforge.application.dataset import DatasetRepository


def validate_dataset_output(
    output: Path,
    artifact_type: str,
    verified_payloads: dict[str, PayloadFile] | None,
    *,
    checkpoint: Callable[[], None] | None = None,
) -> ValidatedArtifact:
    if artifact_type == COMPONENT_ARTIFACT_TYPE:
        parsed = read_dataset(output, checkpoint=checkpoint or (lambda: None))
        paths = [
            "dataset.json",
            *sorted("images/" + i.name for i in parsed.images),
            "sparse/0/cameras.bin",
            "sparse/0/images.bin",
            "sparse/0/points3D.bin",
        ]
    else:
        if {p.name for p in output.iterdir()} not in (
            {"dataset_set.json"},
            {"dataset_set.json", "manifest.json"},
        ):
            raise ValueError(
                "dataset.invalid_set: only a small dataset_set.json receipt is allowed"
            )
        paths = ["dataset_set.json"]
        parsed = PreparedDatasetSet.model_validate_json(
            _read_bounded(safe_payload_path(output, paths[0]), MAX_METADATA_BYTES, "DatasetSet")
        )
    payloads = []
    for relative in sorted(paths):
        path = safe_payload_path(output, relative)
        if path.stat().st_nlink != 1:
            raise ValueError("dataset.unsafe_payload: hardlinks are forbidden")
        size, digest = _payload_digest(output, path, verified_payloads)
        payloads.append(PayloadFile(path=relative, size=size, sha256=digest))
    return ValidatedArtifact(
        payloads=tuple(payloads), parsed=parsed, semantic_digest=parsed.semantic_digest
    )


def validate_dataset_lineage(
    parsed: PreparedDatasetComponent | PreparedDatasetSet,
    manifest: ArtifactManifest,
) -> None:
    inputs = {i.input_name: i for i in manifest.input_lineage}
    if isinstance(parsed, PreparedDatasetComponent):
        expected = {
            "reconstruction_selection": parsed.provenance.selection_artifact_id,
            "reconstruction": parsed.provenance.reconstruction_artifact_id,
            "candidate_views": parsed.provenance.candidate_artifact_id,
            "selected_views": parsed.provenance.selected_artifact_id,
        }
    else:
        expected = {
            "reconstruction_selection": parsed.provenance.selection_artifact_id,
            **{f"component_{i}": c.artifact_id for i, c in enumerate(parsed.components)},
        }
    if (
        len(inputs) != len(manifest.input_lineage)
        or set(inputs) != set(expected)
        or any(inputs[k].artifact_id != v for k, v in expected.items())
        or manifest.recipe_key != parsed.recipe_key
        or manifest.contract_version != 1
    ):
        raise ValueError("dataset.input_mismatch: exact manifest lineage/recipe differs")


def require_dataset_source(
    root: Path,
    repo: "DatasetRepository",
    route: DatasetRoute,
    directory: Path,
    payload: PreparedDatasetComponent | PreparedDatasetSet,
    *,
    checkpoint: Callable[[], None] = lambda: None,
) -> None:
    from splatforge.adapters.colmap_dataset import component_directory
    from splatforge.core.execution import DatasetComponentRoute

    if not isinstance(route, DatasetComponentRoute):
        return
    names = {i.name: i.view_id for i in route.images}
    before = sparse_content(
        component_directory(
            repo.artifact_directory(root, route.reconstruction), route.content.component_id
        ),
        names,
        checkpoint=checkpoint,
        maximum_scratch_bytes=route.resource_limits.max_workspace_bytes,
    )
    if not isinstance(payload, PreparedDatasetComponent):
        raise ValueError("dataset.input_mismatch: source comparison requires a component")
    if payload.source_sparse_digest != before.tracked_geometry_digest:
        raise ValueError("dataset.input_mismatch: consumed sparse content/attributes changed")
    if payload.input_unassociated_observations_omitted != before.unassociated_count:
        raise ValueError("dataset.input_mismatch: omitted unused-feature count differs from source")
    # Publication/cache/recovery have just independently parsed and hash-checked
    # this output. Reuse that operation's proven numerical summaries, not writer
    # state; observations below still stream from both actual sparse files.
    after = SparseDatasetContent(
        payload.cameras,
        payload.views,
        payload.sparse_point_count,
        payload.sparse_geometry_digest,
        payload.preserved_world_points_digest,
    )
    require_preserved_geometry(before, after)
    require_observation_transform(
        component_directory(
            repo.artifact_directory(root, route.reconstruction), route.content.component_id
        ),
        directory / "sparse/0",
        before,
        after,
        checkpoint=checkpoint,
        maximum_scratch_bytes=route.resource_limits.max_workspace_bytes,
    )
