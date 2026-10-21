"""Validation-strength ordering, identity, diamond lineage and scope isolation."""

import os
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from test_quality_execution import sharp_prepare, with_quality
from test_views_execution import harness, prepare, query

from splatforge.adapters.artifact_validation import ValidationStrength, validate_published_artifact
from splatforge.adapters.execution_storage import ExecutionFaultHooks
from splatforge.adapters.fake_stages import LocalFakeStages
from splatforge.application.execution import FakeExecutionService, PublicationUnresolvedError
from splatforge.core.execution import ArtifactManifest


@pytest.mark.parametrize("full_first", (True, False))
def test_strength_memo_never_upgrades_metadata_to_pixel_assurance(
    tmp_path: Path, monkeypatch, full_first: bool,
) -> None:
    import splatforge.adapters.artifact_validation as validation

    value = harness(tmp_path)
    result = prepare(value)
    decode = validation.validate_decodable_image
    calls = []

    def counted(*args):
        calls.append(args[0])
        return decode(*args)

    monkeypatch.setattr(validation, "validate_decodable_image", counted)
    repo = value.execution
    with repo.validation_operation() as context:
        repo._validate_indexed_artifact(
            value.root, result.candidate_artifact, metadata_only=not full_first
        )
        assert len(calls) == (result.candidate_count if full_first else 0)
        repo.load_candidate_views(value.root, result.candidate_artifact)
        assert len(calls) == result.candidate_count
        repo._validate_indexed_artifact(value.root, result.candidate_artifact, metadata_only=True)
        assert len(calls) == result.candidate_count
        assert next(iter(context.results.values()))[0] == ValidationStrength.FULL_DECODE
        wrong = result.candidate_artifact.model_copy(update={"recipe_key": "e" * 64})
        with pytest.raises(ValueError, match="identity or contract"):
            repo.load_candidate_views(value.root, wrong)
    assert repo._validation_context is None
    repo.load_candidate_views(value.root, result.candidate_artifact)
    assert len(calls) == 2 * result.candidate_count


def test_diamond_lineage_memo_is_separate_from_cycle_path(tmp_path: Path) -> None:
    value = harness(tmp_path)
    with_quality(value)
    result = sharp_prepare(value)
    with value.execution.validation_operation() as context:
        value.execution.load_selected_views(value.root, result.selected_artifact)
        assert len(context.results) == 3
        # A memoized node on the current recursion path still represents a cycle.
        with pytest.raises(ValueError, match="cycle"):
            value.execution._validate_indexed_artifact(
                value.root, result.candidate_artifact,
                frozenset({result.candidate_artifact.artifact_id}), context=context,
            )


def test_operation_memo_discarded_on_exception_and_new_writer(tmp_path: Path) -> None:
    value = harness(tmp_path)
    result = prepare(value)
    with (
        pytest.raises(RuntimeError, match="synthetic"),
        value.execution.writer(value.root, owner_token=uuid4()),
    ):
        value.execution.load_candidate_views(value.root, result.candidate_artifact)
        raise RuntimeError("synthetic")
    assert value.execution._validation_context is None
    with value.execution.writer(value.root, owner_token=uuid4()):
        assert value.execution._validation_context.results == {}


def test_published_payload_digest_reuse_supports_relative_directory_paths(
    tmp_path: Path, monkeypatch,
) -> None:
    value = harness(tmp_path)
    result = prepare(value)
    path = value.root / result.candidate_artifact.manifest_path
    manifest = ArtifactManifest.model_validate_json(path.read_bytes())
    monkeypatch.chdir(tmp_path)
    validated = validate_published_artifact(path.parent.relative_to(tmp_path), manifest)
    assert validated.semantic_digest == result.candidate_artifact.semantic_digest


@pytest.mark.parametrize("complete_provenance", (True, False))
@pytest.mark.skipif(os.name != "nt", reason="M3 external recovery requires Windows Job Objects")
def test_recovery_reuses_adopted_validation_but_refuses_incomplete_provenance(
    tmp_path: Path, monkeypatch, complete_provenance: bool,
) -> None:
    import splatforge.adapters.artifact_validation as validation

    value = harness(tmp_path, mixed=False)

    def fail_move(_path):
        raise OSError("crash after candidate move")

    value.execution._fault_hooks = ExecutionFaultHooks(after_artifact_move=fail_move)
    with pytest.raises(PublicationUnresolvedError):
        prepare(value)
    run_id = UUID(query(value.root, "SELECT run_id FROM runs")[0][0])
    if not complete_provenance:
        with value.execution._write_connection(value.root) as connection, connection:
            connection.execute("UPDATE attempts SET source_verification_json=?", (
                '{"policy":"balanced_local","artifact_backed":false,"evidence":[]}',
            ))
    reads = []
    original = validation.stream_sha256

    def count_reads(path, **kwargs):
        if path.parent.name == "images":
            reads.append(path)
        return original(path, **kwargs)

    monkeypatch.setattr(validation, "stream_sha256", count_reads)
    recovered = FakeExecutionService(value.execution, LocalFakeStages()).recover(value.root, run_id)
    assert len(recovered.adopted_attempts) == int(complete_provenance)
    assert len(reads) == len(set(reads)) == (3 if complete_provenance else 0)
