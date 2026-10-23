"""Hierarchy shares M8 lifecycle; only final native memberships are public."""

import json
from uuid import UUID

import pytest
from mapping_helpers import map_run, mapping_inputs
from test_incremental_execution import snapshot, unchanged
from test_matching_execution import hashes
from test_views_execution import query

from splatforge.adapters.execution_storage import ExecutionFaultHooks, LocalExecutionRepository
from splatforge.adapters.fake_stages import LocalFakeStages
from splatforge.adapters.performance import LocalPerformanceHistory
from splatforge.adapters.project_storage import LocalProjectStore
from splatforge.application.execution import FakeExecutionService, PublicationUnresolvedError
from splatforge.application.mapping import MappingService
from splatforge.application.progress import ProgressSupport
from splatforge.application.progress_reader import RunProgressService
from splatforge.core.execution import HierarchicalMappingRoute
from splatforge.core.reconstruction import (
    HierarchicalMapperSettings,
    IncrementalMapperSettings,
    MappingResourceLimits,
)


def run(value, fixture, verified, **kwargs):
    return map_run(value, fixture, verified, **{"settings": HierarchicalMapperSettings(), **kwargs})


def test_hierarchy_cache_private_db_old_routes_and_history(tmp_path):
    value, fixture, _, _, verified = mapping_inputs(tmp_path)
    before = hashes(value.root)
    global_result = map_run(value, fixture, verified)
    incremental = map_run(value, fixture, verified, settings=IncrementalMapperSettings())
    history = LocalPerformanceHistory(tmp_path / "history.sqlite")
    support = ProgressSupport(history=history)
    result = run(value, fixture, verified, progress=support)
    assert not result.cache_hit and type(snapshot(value, result).route) is HierarchicalMappingRoute
    assert result.reconstruction.semantic_digest == global_result.reconstruction.semantic_digest
    assert result.reconstruction.semantic_digest == incremental.reconstruction.semantic_digest
    assert result.artifact.recipe_key not in {
        global_result.artifact.recipe_key,
        incremental.artifact.recipe_key,
    }
    assert result.diagnostics["leaf_clusters"] == 2
    assert result.diagnostics["merge_observed"]
    assert result.reconstruction.component_count == 1  # two overlapping INTERNAL leaves
    assert run(
        value,
        fixture,
        verified,
        progress=support,
        resource_limits=MappingResourceLimits(max_views=10001),
    ).cache_hit
    assert history.statistics().sample_count == 1
    changed = run(value, fixture, verified, settings=HierarchicalMapperSettings(image_overlap=51))
    assert not changed.cache_hit and changed.artifact.recipe_key != result.artifact.recipe_key
    assert all(p.stat().st_nlink == 1 for p in fixture.private_databases)
    reader = MappingService(value.execution, fixture.mapping_adapter()).reader(
        value.root, result.run_id
    )
    assert (
        sum(len(tuple(reader.registered_views(c.component_id))) for c in reader.components()) == 3
    )
    progress = RunProgressService(value.execution).get(value.root, result.run_id)
    assert progress.stages[0].work.work_model_id == "mapping.hierarchical_phases_v1"
    events = [
        json.loads(line)
        for line in (value.root / "runs" / str(result.run_id) / "events.jsonl")
        .read_text(encoding="utf8")
        .splitlines()
    ]
    for event in events:
        if event["code"] == "progress.snapshot":
            stages = event["details"]["snapshot"]["stages"]
            if any(s["status"] == "running" for s in stages):
                assert event["details"]["snapshot"]["fraction"] is None
    unchanged(before)


@pytest.mark.parametrize(
    "mode,reason",
    [
        ("failed", "mapper_process_failure"),
        ("timeout", "timed out"),
        ("empty", "zero_components"),
        ("overlap", "Hierarchical native merging left overlapping"),
        ("malformed", "malformed_output"),
        ("prior_snapshot", "input_mismatch"),
        ("unresolved", "teardown"),
    ],
)
def test_hierarchy_failure_no_publication_or_mapper_fallback(tmp_path, mode, reason):
    value, fixture, _, _, verified = mapping_inputs(tmp_path)
    before = hashes(value.root)
    fixture.mapping_mode = mode
    with pytest.raises(ValueError, match=reason):
        run(value, fixture, verified)
    assert (
        len([r for r in fixture.requests if r.argv[0] == "hierarchical_mapper" and len(r.argv) > 2])
        == 1
    )
    assert not any(
        r.argv[0] in {"mapper", "global_mapper"} and len(r.argv) > 2 for r in fixture.requests
    )
    unchanged(before)


def test_hierarchy_disjoint_final_models_and_unregistered(tmp_path):
    value, fixture, _, _, verified = mapping_inputs(tmp_path, multi=True)
    fixture.mapping_mode = "multi"
    result = run(value, fixture, verified)
    assert result.reconstruction.component_count == 2
    assert result.reconstruction.registered_view_count == 6
    assert result.reconstruction.unregistered_view_count == 1
    assert not (
        set(result.reconstruction.components[0].registered_view_ids)
        & set(result.reconstruction.components[1].registered_view_ids)
    )


def test_hierarchy_cancellation_and_corrupt_cache(tmp_path):
    value, fixture, _, _, verified = mapping_inputs(tmp_path)
    before = hashes(value.root)
    fixture.mapping_mode = "cancelled"
    fixture.on_map = lambda owner: value.execution.request_cancellation(
        value.root, run_id=owner.run
    )
    cancelled = run(value, fixture, verified)
    assert cancelled.status == "cancelled" and cancelled.artifact is None
    fixture.on_map, fixture.mapping_mode = None, "success"
    good = run(value, fixture, verified)
    directory = value.execution.artifact_directory(value.root, good.artifact)
    (directory / "sparse" / "7" / "images.bin").write_bytes(b"broken")
    assert not run(value, fixture, verified).cache_hit
    unchanged(before)


@pytest.mark.parametrize("corrupt", [False, True])
def test_hierarchy_orphan_recovery(tmp_path, corrupt):
    value, fixture, _, _, verified = mapping_inputs(tmp_path)

    def crash(_):
        raise RuntimeError("after rename")

    repository = LocalExecutionRepository(
        project_store=LocalProjectStore(),
        fault_hooks=ExecutionFaultHooks(after_artifact_move=crash),
    )
    with pytest.raises(PublicationUnresolvedError):
        run(value, fixture, verified, repository=repository)
    run_id = UUID(query(value.root, "SELECT run_id FROM runs WHERE status='running'")[0][0])
    if corrupt:
        next((value.root / "artifacts").rglob("images.bin")).write_bytes(b"broken")
    recovered = FakeExecutionService(value.execution, LocalFakeStages()).recover(value.root, run_id)
    assert recovered.status == ("interrupted" if corrupt else "succeeded")
    assert len(recovered.adopted_attempts) == (0 if corrupt else 1)


def test_hierarchy_calibration_and_bypass_refused(tmp_path):
    with pytest.raises(ValueError, match="without calibration"):
        MappingService(None, None).run(
            tmp_path,
            verification_run_id=UUID(int=1),
            settings=HierarchicalMapperSettings(),
            calibration_policy="view_graph",
        )
    with pytest.raises(ValueError):
        MappingService(None, None).run(
            tmp_path,
            verification_run_id=UUID(int=1),
            settings=HierarchicalMapperSettings().model_copy(update={"branching": 3}),
        )
