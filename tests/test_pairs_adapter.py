"""PairSet payload/manifest integrity and bounded serialization validation."""

from pathlib import Path
from uuid import UUID, uuid4

import pytest
from test_pairs_core import payload, universe, view

from splatforge.adapters.artifact_validation import (
    validate_published_artifact,
    validate_workspace_output,
)
from splatforge.adapters.pair_workspace import LocalPairWorkspace
from splatforge.core.execution import (
    ArtifactInputLineage,
    ArtifactManifest,
    ValidationResult,
)
from splatforge.core.pairs import PAIR_ARTIFACT_TYPE


def written(tmp_path: Path):
    value = payload(universe(view(1), view(2, 10)))
    LocalPairWorkspace().write_pair_set(tmp_path, value)
    directory = tmp_path / "output"
    validated = validate_workspace_output(directory, PAIR_ARTIFACT_TYPE)
    lineage = tuple(
        ArtifactInputLineage(
            input_name=name,
            artifact_id=artifact_id,
            artifact_type=artifact_type,
            contract_version=1,
            semantic_digest=digest,
            recipe_key="c" * 64,
        )
        for name, artifact_id, artifact_type, digest in (
            ("candidate_views", value.candidate_artifact_id, "views.candidate_set", "a" * 64),
            ("selected_views", value.selected_artifact_id, "views.selected_set", "b" * 64),
        )
    )
    manifest = ArtifactManifest(
        artifact_id=uuid4(),
        artifact_type=PAIR_ARTIFACT_TYPE,
        contract_version=1,
        producer_run_id=uuid4(),
        producer_node_id="pair_set",
        producer_attempt_id=uuid4(),
        recipe_key="d" * 64,
        semantic_digest=validated.semantic_digest,
        input_lineage=lineage,
        payloads=validated.payloads,
        validation=ValidationResult(
            validator_id=f"{PAIR_ARTIFACT_TYPE}.integrity", validator_version=1
        ),
    )
    return directory, value, manifest


def test_pair_artifact_roundtrip_and_byte_stable_logical_payload(tmp_path) -> None:
    directory, value, manifest = written(tmp_path)
    assert validate_published_artifact(directory, manifest).parsed == value
    second = tmp_path / "second"
    second.mkdir()
    LocalPairWorkspace().write_pair_set(second, value)
    assert (directory / "pair_set.json").read_bytes() == (
        second / "output" / "pair_set.json"
    ).read_bytes()


@pytest.mark.parametrize("change", ["lineage_id", "lineage_digest", "missing_input", "semantic"])
def test_pair_published_provenance_and_semantics_revalidated(tmp_path, change) -> None:
    directory, _, manifest = written(tmp_path)
    if change == "semantic":
        manifest = manifest.model_copy(update={"semantic_digest": "0" * 64})
    elif change == "missing_input":
        manifest = manifest.model_copy(update={"input_lineage": manifest.input_lineage[:1]})
    else:
        first = manifest.input_lineage[0].model_copy(
            update={
                "artifact_id" if change == "lineage_id" else "semantic_digest": UUID(int=1234)
                if change == "lineage_id"
                else "0" * 64,
            }
        )
        manifest = manifest.model_copy(update={"input_lineage": (first, manifest.input_lineage[1])})
    with pytest.raises(ValueError):
        validate_published_artifact(directory, manifest)


def test_pair_metadata_byte_bound_and_extra_files(tmp_path, monkeypatch) -> None:
    import splatforge.adapters.artifact_validation as module

    directory, _, manifest = written(tmp_path)
    monkeypatch.setattr(module, "MAX_PAIR_METADATA_BYTES", 4)
    with pytest.raises(ValueError, match="byte bound"):
        validate_published_artifact(directory, manifest)
    with pytest.raises(ValueError, match="byte limit"):
        validate_workspace_output(directory, PAIR_ARTIFACT_TYPE)
    monkeypatch.undo()
    (directory / "unexpected.bin").write_bytes(b"extra")
    with pytest.raises(ValueError, match="exactly pair_set.json"):
        validate_workspace_output(directory, PAIR_ARTIFACT_TYPE)


def test_pair_workspace_refuses_non_plain_metadata(tmp_path, monkeypatch) -> None:
    import splatforge.adapters.artifact_validation as module

    directory, _, _ = written(tmp_path)
    monkeypatch.setattr(module, "_plain_file", lambda _path: False)
    with pytest.raises(ValueError, match="plain file"):
        validate_workspace_output(directory, PAIR_ARTIFACT_TYPE)


def test_pair_manifest_rejects_extra_payload_before_hashing(tmp_path, monkeypatch) -> None:
    import splatforge.adapters.artifact_validation as module

    directory, _, manifest = written(tmp_path)

    def forbidden(*args, **kwargs):
        raise AssertionError("must refuse manifest before hashing payloads")

    monkeypatch.setattr(module, "stream_sha256", forbidden)
    manifest = manifest.model_copy(update={"payloads": manifest.payloads * 2})
    with pytest.raises(ValueError, match="exactly pair_set.json"):
        validate_published_artifact(directory, manifest)
