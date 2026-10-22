"""Real persistence, bounded offline imports and M6/M7b compatibility."""

import pytest
from test_pairs_execution import CancelRepository
from test_retrieval_core import export_for
from test_views_execution import harness, prepare, query

from splatforge.adapters.execution_storage import ExecutionFaultHooks, LocalExecutionRepository
from splatforge.adapters.fake_stages import LocalFakeStages
from splatforge.adapters.pair_workspace import LocalPairWorkspace
from splatforge.adapters.project_storage import LocalProjectStore
from splatforge.adapters.retrieval_artifacts import LocalRetrievalAdapter
from splatforge.application.execution import FakeExecutionService, PublicationUnresolvedError
from splatforge.application.pairs import PairsService
from splatforge.application.progress_reader import RunProgressService
from splatforge.application.retrieval import RetrievalCapabilityError, RetrievalService
from splatforge.core.pairs import (
    HybridPairSettings,
    PairResourceLimits,
    RetrievalPairSettings,
    SequentialSettings,
    canonical_pair,
    project_pairing_universe,
)
from splatforge.core.retrieval import RetrievalExport, RetrievalView
from splatforge.core.views import canonical_json_bytes, sha256_bytes


def exported(value, views, path, *, method="retrieval.megaloc", rows=None):
    candidate, selected = value.execution.load_pairing_inputs(
        value.root,
        views.candidate_artifact,
        views.selected_artifact,
    )
    universe = project_pairing_universe(candidate, selected)
    pixels = {v.view_id: v for v in candidate.views}
    export, data = export_for(
        universe,
        rows,
        pixels=tuple(
            RetrievalView(
                view_id=v.view_id,
                image_sha256=pixels[v.view_id].image_sha256,
                pixel_transform_digest=sha256_bytes(
                    canonical_json_bytes(
                        pixels[v.view_id].transform.model_dump(mode="json"),
                    )
                ),
                width=pixels[v.view_id].width,
                height=pixels[v.view_id].height,
            )
            for v in universe.views
        ),
        method=method,
    )
    path.mkdir()
    (path / "export.json").write_text(export.model_dump_json(), encoding="utf-8")
    (path / "descriptors.f32").write_bytes(data)
    return path / "export.json"


def build(value, views, source, *, repository=None):
    return RetrievalService(repository or value.execution, LocalRetrievalAdapter()).build(
        value.root,
        views_run_id=views.run_id,
        descriptor_export=source,
    )


def pairs(value, views, representation, *, settings=None, repository=None, explicit=()):
    return PairsService(
        repository or value.execution,
        LocalPairWorkspace(),
        retrieval_adapter=LocalRetrievalAdapter(),
    ).build(
        value.root,
        views_run_id=views.run_id,
        retrieval_run_id=representation.run_id,
        settings=settings or HybridPairSettings(retrieval=RetrievalPairSettings(top_k=1)),
        resource_limits=PairResourceLimits(),
        explicit_pairs=explicit,
    )


def test_import_pair_cache_k_sequential_and_progress_boundaries(tmp_path):
    value = harness(tmp_path)
    views = prepare(value)
    source = exported(value, views, tmp_path / "export ž space")
    before = source.read_bytes(), (source.parent / "descriptors.f32").read_bytes()
    representation = build(value, views, source)
    assert representation.status == "succeeded" and not representation.cache_hit
    assert (
        build(value, views, source).representation_artifact
        == representation.representation_artifact
    )
    result = pairs(value, views, representation)
    assert result.status == "succeeded" and result.component_count == 1
    assert result.retrieval.sequential_edge_count == 1
    assert result.retrieval.retrieval_edge_count == 2
    assert pairs(value, views, representation).cache_hit
    different_k = pairs(
        value,
        views,
        representation,
        settings=HybridPairSettings(
            retrieval=RetrievalPairSettings(top_k=2),
        ),
    )
    different_seq = pairs(
        value,
        views,
        representation,
        settings=HybridPairSettings(
            sequential=SequentialSettings(forward_neighbors=1),
            retrieval=RetrievalPairSettings(top_k=1),
        ),
    )
    assert not different_k.cache_hit and not different_seq.cache_hit
    assert build(value, views, source).cache_hit
    for run, model in (
        (representation, "retrieval.imported_views_v1"),
        (result, "retrieval.queried_views_v1"),
    ):
        progress = RunProgressService(value.execution).get(value.root, run.run_id).stages[0]
        assert (
            progress.work.work_model_id,
            progress.work.unit,
            progress.work.total,
            progress.completed,
        ) == (model, "views", 3.0, 3.0)
        assert progress.status == "succeeded"
    payload = value.execution.load_pair_set(value.root, result.pair_set_artifact)
    edge = canonical_pair(payload.pairs[0].left_view_id, payload.pairs[0].right_view_id)
    manual = pairs(value, views, representation, explicit=(edge,))
    assert manual.retrieval.explicit_edge_count == 1
    assert before == (source.read_bytes(), (source.parent / "descriptors.f32").read_bytes())


def test_model_preprocessing_and_byte_corruption_invalidate_or_reject(tmp_path):
    value = harness(tmp_path)
    views = prepare(value)
    source = exported(value, views, tmp_path / "export")
    first = build(value, views, source)
    export = RetrievalExport.model_validate_json(source.read_bytes())
    for update in (
        {"models": (export.settings.models[0].model_copy(update={"sha256": "d" * 64}),)},
        {"preprocessing": export.settings.preprocessing.model_copy(update={"width": 336})},
    ):
        changed = export.model_copy(update={"settings": export.settings.model_copy(update=update)})
        source.write_text(changed.model_dump_json(), encoding="utf-8")
        rebuilt = build(value, views, source)
        assert not rebuilt.cache_hit
        assert (
            rebuilt.representation_artifact.recipe_key != first.representation_artifact.recipe_key
        )
    directory = (value.root / rebuilt.representation_artifact.manifest_path).parent
    (directory / "descriptors.f32").write_bytes(b"broken")
    again = build(value, views, source)
    assert not again.cache_hit
    (source.parent / "descriptors.f32").write_bytes(b"broken")
    # Cached immutable payload remains valid even when the external export is unavailable.
    assert build(value, views, source).cache_hit
    source.write_text(export.model_dump_json(), encoding="utf-8")
    directory = (value.root / first.representation_artifact.manifest_path).parent
    (directory / "descriptors.f32").write_bytes(b"broken")
    with pytest.raises(ValueError, match="storage mismatch"):
        build(value, views, source)


@pytest.mark.parametrize("payload", ["descriptors.f32", "retrieval.json"])
def test_retrieval_cache_corruption_blocks_pairing(tmp_path, payload):
    value = harness(tmp_path)
    views = prepare(value)
    source = exported(value, views, tmp_path / "export")
    representation = build(value, views, source)
    target = (value.root / representation.representation_artifact.manifest_path).parent / payload
    target.write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="digest mismatch"):
        pairs(value, views, representation)


@pytest.mark.parametrize("stage", ["import", "query"])
def test_cancellation_persists_and_stage_restart_works(tmp_path, stage):
    value = harness(tmp_path)
    views = prepare(value)
    source = exported(value, views, tmp_path / "export")
    cancel = CancelRepository(at=3)
    if stage == "import":
        result = build(value, views, source, repository=cancel)
        assert result.representation_artifact is None
    else:
        representation = build(value, views, source)
        result = pairs(value, views, representation, repository=cancel)
        assert result.pair_set_artifact is None
    assert result.status == "cancelled"
    assert query(
        value.root, "SELECT count(*) FROM artifacts WHERE producer_run_id=?", (str(result.run_id),)
    ) == [(0,)]
    assert build(value, views, source).status == "succeeded"


@pytest.mark.parametrize("stage", ["import", "query"])
def test_publication_recovery_revalidates_frozen_corpus_and_graph(tmp_path, stage):
    value = harness(tmp_path)
    views = prepare(value)
    source = exported(value, views, tmp_path / "export")

    def stop(_path):
        raise OSError("after move")

    repo = LocalExecutionRepository(
        project_store=LocalProjectStore(), fault_hooks=ExecutionFaultHooks(after_artifact_move=stop)
    )
    with pytest.raises(PublicationUnresolvedError):
        if stage == "import":
            build(value, views, source, repository=repo)
        else:
            representation = build(value, views, source)
            pairs(value, views, representation, repository=repo)
    run_id = query(value.root, "SELECT run_id FROM runs WHERE status='running'")[0][0]
    from uuid import UUID

    recovered = FakeExecutionService(value.execution, LocalFakeStages()).recover(
        value.root,
        UUID(run_id),
    )
    assert recovered.status == "succeeded" and len(recovered.adopted_attempts) == 1


def test_missing_backend_cannot_create_exhaustive_or_any_run(tmp_path):
    from uuid import uuid4

    with pytest.raises(RetrievalCapabilityError, match="No production retrieval model selected"):
        RetrievalService(LocalExecutionRepository(), LocalRetrievalAdapter()).build(
            tmp_path / "no project",
            views_run_id=uuid4(),
        )


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), 0.0])
def test_declared_hash_does_not_accept_nonfinite_or_unnormalized_descriptors(tmp_path, bad):
    import hashlib
    import struct

    value = harness(tmp_path)
    views = prepare(value)
    source = exported(value, views, tmp_path / "export")
    export = RetrievalExport.model_validate_json(source.read_bytes())
    data = struct.pack("<6f", bad, 0, 1, 0, 1, 0)
    changed = export.model_copy(update={"descriptor_sha256": hashlib.sha256(data).hexdigest()})
    source.write_text(changed.model_dump_json(), encoding="utf-8")
    (source.parent / "descriptors.f32").write_bytes(data)
    with pytest.raises(ValueError, match="finite L2 unit"):
        build(value, views, source)
    assert query(
        value.root,
        "SELECT count(*) FROM artifacts WHERE artifact_type=?",
        ("retrieval.representation_set",),
    ) == [(0,)]


def test_corpus_change_refused_and_request_is_exact(tmp_path):
    from pathlib import Path

    from splatforge.core.retrieval import corpus_digest

    value = harness(tmp_path)
    views = prepare(value)
    source = exported(value, views, tmp_path / "export")
    service = RetrievalService(value.execution, LocalRetrievalAdapter())
    request = service.request(value.root, views_run_id=views.run_id)
    export = RetrievalExport.model_validate_json(source.read_bytes())
    assert request.corpus_semantic_digest == export.corpus_semantic_digest
    assert request.views == export.views
    assert all(Path(p).is_file() for p in request.image_paths)
    changed_views = (
        export.views[0].model_copy(update={"image_sha256": "e" * 64}),
        *export.views[1:],
    )
    changed = export.model_copy(
        update={
            "views": changed_views,
            "corpus_semantic_digest": corpus_digest(export.universe, changed_views),
        }
    )
    source.write_text(changed.model_dump_json(), encoding="utf-8")
    with pytest.raises(ValueError, match="exact selected corpus"):
        build(value, views, source)
