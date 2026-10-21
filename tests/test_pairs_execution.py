"""M6 execution, cache, provenance, durable cancellation and publication recovery."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from test_quality_execution import sharp_prepare, with_quality
from test_views_execution import harness, prepare, query

from splatforge.adapters.execution_storage import ExecutionFaultHooks, LocalExecutionRepository
from splatforge.adapters.fake_stages import LocalFakeStages
from splatforge.adapters.pair_workspace import LocalPairWorkspace
from splatforge.adapters.project_storage import LocalProjectStore
from splatforge.application.execution import FakeExecutionService, PublicationUnresolvedError
from splatforge.application.pairs import PairsService
from splatforge.bootstrap import build_project_service
from splatforge.core.execution import RunSnapshot
from splatforge.core.pairs import (
    ExhaustiveSettings,
    PairResourceLimits,
    SequentialSettings,
    canonical_pair,
)


def service(repository=None, workspace=None):
    return PairsService(
        repository or LocalExecutionRepository(project_store=LocalProjectStore()),
        workspace or LocalPairWorkspace(),
    )


def build(
    value, views, *, repository=None, workspace=None, settings=None, budget=100_000, explicit=()
):
    return service(repository, workspace).build(
        value.root,
        views_run_id=views.run_id,
        settings=settings or SequentialSettings(),
        resource_limits=PairResourceLimits(max_pairs=budget),
        explicit_pairs=explicit,
    )


def test_execution_cache_budget_and_recipe_changes(tmp_path: Path) -> None:
    value = harness(tmp_path)
    views = prepare(value)
    first = build(value, views)
    assert first.status == "succeeded" and not first.cache_hit
    assert (
        first.selected_view_count,
        first.pair_count,
        first.isolated_view_count,
        first.component_count,
    ) == (3, 1, 1, 2)
    assert query(
        value.root, "SELECT count(*) FROM attempts WHERE run_id=?", (str(first.run_id),)
    ) == [(1,)]
    projects = build_project_service()
    document = projects.open(value.root)
    document.label = "Changed project label"
    projects.save(value.root, document)
    second = build(value, views, budget=2)
    assert second.cache_hit and second.pair_set_artifact == first.pair_set_artifact
    assert query(
        value.root, "SELECT count(*) FROM attempts WHERE run_id=?", (str(second.run_id),)
    ) == [(0,)]
    changed = build(value, views, settings=SequentialSettings(forward_neighbors=1))
    assert not changed.cache_hit
    assert changed.pair_set_artifact.semantic_digest == first.pair_set_artifact.semantic_digest
    candidate, selected = value.execution.load_pairing_inputs(
        value.root,
        views.candidate_artifact,
        views.selected_artifact,
    )
    photo = next(v for v in candidate.views if v.media_type == "photo")
    video = next(v for v in selected.selected_views if v.media_type == "video")
    explicit = (canonical_pair(photo.view_id, video.view_id),)
    manual = build(value, views, explicit=explicit)
    assert not manual.cache_hit and manual.pair_count == 2
    assert manual.component_count == 1 and manual.cross_source_pair_count == 1
    assert build(value, views, explicit=explicit * 2).cache_hit
    with pytest.raises(ValueError, match="Cached pair count=2 exceeds max_pairs=1"):
        build(value, views, explicit=explicit, budget=1)
    assert query(
        value.root, "SELECT count(*) FROM attempts WHERE run_id=?", (str(manual.run_id),)
    ) == [(1,)]


def test_cache_reuses_equivalent_fixed_and_sharpest_selection_projections(tmp_path: Path) -> None:
    value = harness(tmp_path)
    with_quality(value)
    fixed = prepare(value, target="2", candidate_fps="4")
    first = build(value, fixed)
    sharp = sharp_prepare(value, target="2", candidate_fps="4")
    assert fixed.selected_artifact != sharp.selected_artifact
    same = build(value, sharp)
    assert same.cache_hit and same.pair_set_artifact == first.pair_set_artifact
    changed_policy = sharp_prepare(value, target="2", candidate_fps="4", duplicate_threshold=6)
    assert build(value, changed_policy).cache_hit
    route = RunSnapshot.model_validate_json(
        (value.root / "runs" / str(same.run_id) / "run.json").read_bytes()
    ).route
    assert route.selected == sharp.selected_artifact
    # Cached publications retain producer lineage; the new route freezes current inputs.
    parsed = value.execution.load_pair_set(value.root, first.pair_set_artifact)
    assert parsed.selected_artifact_id == fixed.selected_artifact.artifact_id


def test_pairs_never_read_originals_decode_pixels_or_invoke_backends(tmp_path, monkeypatch) -> None:
    import splatforge.adapters.artifact_validation as validation

    value = harness(tmp_path)
    views = prepare(value)

    def forbidden(*args, **kwargs):
        raise AssertionError("M6 must not decode, verify originals or invoke a backend")

    monkeypatch.setattr(validation, "validate_decodable_image", forbidden)
    monkeypatch.setattr(value.sources, "evidence", forbidden)
    monkeypatch.setattr(value.materializer, "identity", forbidden)
    # Offline originals do not affect metadata-only PairSelection.
    for path in value.source_paths:
        path.rename(path.with_suffix(".offline"))
    first = build(value, views)
    assert first.status == "succeeded"
    assert build(value, views).cache_hit
    recovered = FakeExecutionService(value.execution, LocalFakeStages()).recover(
        value.root, first.run_id
    )
    assert recovered.status == "succeeded"


@pytest.mark.parametrize("which", ["candidate", "selected", "image"])
def test_corrupt_upstream_refuses_without_pair_publication(tmp_path, which) -> None:
    value = harness(tmp_path)
    views = prepare(value)
    if which == "candidate":
        path = (value.root / views.candidate_artifact.manifest_path).parent / "candidate_views.json"
    elif which == "selected":
        path = (value.root / views.selected_artifact.manifest_path).parent / "selected_views.json"
    else:
        directory = (value.root / views.candidate_artifact.manifest_path).parent / "images"
        path = next(directory.iterdir())
    path.write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="digest mismatch"):
        build(value, views)
    assert query(
        value.root, "SELECT count(*) FROM artifacts WHERE artifact_type='pairs.pair_set'"
    ) == [(0,)]


def test_corrupt_pair_cache_rejected_and_rebuilt(tmp_path) -> None:
    value = harness(tmp_path)
    views = prepare(value)
    first = build(value, views)
    path = (value.root / first.pair_set_artifact.manifest_path).parent / "pair_set.json"
    path.write_bytes(b"{}")
    second = build(value, views)
    assert not second.cache_hit and second.pair_count == first.pair_count
    assert second.pair_set_artifact.artifact_id != first.pair_set_artifact.artifact_id


@pytest.mark.parametrize("status", ["running", "failed", "interrupted", "cancelled"])
def test_non_succeeded_views_run_refused(tmp_path, status) -> None:
    value = harness(tmp_path)
    views = prepare(value)
    with closing(sqlite3.connect(value.root / "state.sqlite")) as connection, connection:
        connection.execute("UPDATE runs SET status=? WHERE run_id=?", (status, str(views.run_id)))
    with pytest.raises(ValueError):
        build(value, views)
    assert query(
        value.root, "SELECT count(*) FROM artifacts WHERE artifact_type='pairs.pair_set'"
    ) == [(0,)]


def test_unknown_or_wrong_route_and_missing_views_outputs_refused(tmp_path) -> None:
    value = harness(tmp_path)
    views = prepare(value)
    with pytest.raises(ValueError, match="Unknown run"):
        service().build(
            value.root,
            views_run_id=uuid4(),
            settings=SequentialSettings(),
            resource_limits=PairResourceLimits(),
        )
    fake = FakeExecutionService(value.execution, LocalFakeStages()).run(value.root)
    with pytest.raises(ValueError, match="views preparation"):
        service().build(
            value.root,
            views_run_id=fake.run_id,
            settings=SequentialSettings(),
            resource_limits=PairResourceLimits(),
        )
    with closing(sqlite3.connect(value.root / "state.sqlite")) as connection, connection:
        connection.execute(
            "DELETE FROM run_outputs WHERE run_id=? AND node_id='selected_views'",
            (str(views.run_id),),
        )
    with pytest.raises(ValueError, match="no indexed"):
        build(value, views)


class CancelRepository(LocalExecutionRepository):
    def __init__(self, *, at: int) -> None:
        super().__init__(project_store=LocalProjectStore())
        self.at = at
        self.calls = 0

    def accept_cancellation(self, root, *, run_id, attempt_id):
        self.calls += 1
        if self.calls == self.at:
            self.request_cancellation(root, run_id=run_id)
        return super().accept_cancellation(root, run_id=run_id, attempt_id=attempt_id)


@pytest.mark.parametrize("at", [1, 2, 4, 6])
@pytest.mark.parametrize("method", [SequentialSettings(), ExhaustiveSettings()])
def test_durable_cancellation_no_partial_publication_and_restart(tmp_path, at, method) -> None:
    value = harness(tmp_path, mixed=False)
    views = prepare(value)
    repo = CancelRepository(at=at)
    result = build(value, views, repository=repo, settings=method)
    assert result.status == "cancelled" and result.pair_set_artifact is None
    assert query(
        value.root, "SELECT count(*) FROM artifacts WHERE artifact_type='pairs.pair_set'"
    ) == [(0,)]
    assert query(
        value.root,
        "SELECT count(*) FROM attempts WHERE run_id=? AND status='succeeded'",
        (str(result.run_id),),
    ) == [(0,)]
    again = build(value, views, settings=method)
    assert again.status == "succeeded" and not again.cache_hit


def interrupted_pair(value, views, *, before=False):
    def crash(path):
        if path.parent.name == "pair_set":
            raise OSError("injected publication boundary")

    hooks = ExecutionFaultHooks(
        **{
            "before_artifact_move" if before else "after_artifact_move": crash,
        }
    )
    repo = LocalExecutionRepository(project_store=LocalProjectStore(), fault_hooks=hooks)
    if before:
        with pytest.raises(OSError, match="publication boundary"):
            build(value, views, repository=repo)
    else:
        with pytest.raises(PublicationUnresolvedError):
            build(value, views, repository=repo)
    row = query(
        value.root, "SELECT run_id, expected_artifact_id FROM attempts WHERE node_id='pair_set'"
    )[0]
    return repo, UUID(row[0]), value.root / "artifacts" / "pair_set" / row[1]


def recover(value, repo, run_id):
    return FakeExecutionService(repo, LocalFakeStages()).recover(value.root, run_id)


def test_recovery_move_before_index_adopts_exact_pair_and_finalizes(tmp_path) -> None:
    value = harness(tmp_path)
    views = prepare(value)
    repo, run_id, _ = interrupted_pair(value, views)
    result = recover(value, repo, run_id)
    assert result.status == "succeeded" and len(result.adopted_attempts) == 1
    assert build(value, views).cache_hit


@pytest.mark.parametrize("corruption", ["payload", "lineage", "manifest_digest"])
def test_recovery_corrupt_or_wrong_lineage_orphan_refused(tmp_path, corruption) -> None:
    value = harness(tmp_path)
    views = prepare(value)
    repo, run_id, directory = interrupted_pair(value, views)
    if corruption == "payload":
        (directory / "pair_set.json").write_bytes(b"{}")
    else:
        manifest = directory / "manifest.json"
        if corruption == "lineage":
            data = json.loads(manifest.read_bytes())
            data["input_lineage"][0]["artifact_id"] = str(uuid4())
            manifest.write_text(json.dumps(data), encoding="utf-8")
            # Preserve expected byte identity so this specifically exercises lineage checks.
            digest = hashlib.sha256(manifest.read_bytes()).hexdigest()
            with closing(sqlite3.connect(value.root / "state.sqlite")) as connection, connection:
                connection.execute(
                    "UPDATE attempts SET expected_manifest_digest=? WHERE run_id=?",
                    (digest, str(run_id)),
                )
        else:
            manifest.write_bytes(manifest.read_bytes() + b" ")
    result = recover(value, repo, run_id)
    assert result.status == "interrupted" and result.adopted_attempts == ()
    assert result.warnings[0].code == "orphan.publication_refused"
    assert not build(value, views).cache_hit


@pytest.mark.parametrize("accepted", [False, True])
def test_recovery_cancellation_blocks_orphan_adoption(tmp_path, accepted) -> None:
    value = harness(tmp_path)
    views = prepare(value)
    repo, run_id, _ = interrupted_pair(value, views)
    repo.request_cancellation(value.root, run_id=run_id)
    if accepted:
        attempt_id = UUID(
            query(value.root, "SELECT attempt_id FROM attempts WHERE run_id=?", (str(run_id),))[0][
                0
            ]
        )
        assert repo.accept_cancellation(value.root, run_id=run_id, attempt_id=attempt_id)
    result = recover(value, repo, run_id)
    assert result.status == "cancelled" and result.adopted_attempts == ()
    assert not build(value, views).cache_hit


def test_recovery_indexed_pair_unfinished_run_finalizes(tmp_path) -> None:
    value = harness(tmp_path)
    views = prepare(value)

    class CrashBeforeFinalize(LocalExecutionRepository):
        def mark_run_succeeded(self, root, *, run_id):
            raise PublicationUnresolvedError("crash after indexed PairSet")

    repo = CrashBeforeFinalize(project_store=LocalProjectStore())
    with pytest.raises(PublicationUnresolvedError):
        build(value, views, repository=repo)
    run_id = UUID(query(value.root, "SELECT run_id FROM attempts WHERE node_id='pair_set'")[0][0])
    result = recover(value, value.execution, run_id)
    assert result.status == "succeeded" and result.adopted_attempts == ()
    assert build(value, views).cache_hit


def test_recovery_never_adopts_unmoved_workspace(tmp_path) -> None:
    value = harness(tmp_path)
    views = prepare(value)

    def crash(path):
        if path.parent.name == "pair_set":
            raise SystemExit("simulated owner loss before move")

    repo = LocalExecutionRepository(
        project_store=LocalProjectStore(),
        fault_hooks=ExecutionFaultHooks(before_artifact_move=crash),
    )
    with pytest.raises(SystemExit):
        build(value, views, repository=repo)
    run_id = UUID(query(value.root, "SELECT run_id FROM attempts WHERE node_id='pair_set'")[0][0])
    result = recover(value, repo, run_id)
    assert result.status == "interrupted" and result.adopted_attempts == ()
    assert len(result.interrupted_attempts) == 1
    assert not build(value, views).cache_hit


def test_pair_publication_refuses_payload_provenance_mismatch_before_move(tmp_path) -> None:
    value = harness(tmp_path)
    views = prepare(value)

    class WrongProvenanceWorkspace(LocalPairWorkspace):
        def write_pair_set(self, workspace, payload):
            super().write_pair_set(
                workspace,
                payload.model_copy(
                    update={
                        "selected_artifact_id": uuid4(),
                    }
                ),
            )

    with pytest.raises(ValueError, match="provenance differs"):
        build(value, views, workspace=WrongProvenanceWorkspace())
    assert query(
        value.root, "SELECT count(*) FROM artifacts WHERE artifact_type='pairs.pair_set'"
    ) == [(0,)]
    artifacts = value.root / "artifacts" / "pair_set"
    assert not artifacts.exists()
