"""Mapping cache/isolation/calibration/cancellation/recovery through real storage."""

import json
from uuid import UUID

import pytest
from mapping_helpers import map_run, mapping_inputs
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
from splatforge.core.reconstruction import (
    GlobalMapperSettings,
    MappingCalibrationPolicy,
    MappingResourceLimits,
)


def test_mapping_cache_reader_and_all_upstream_bytes_immutable(tmp_path):
    value, fixture, features, raw, verified = mapping_inputs(tmp_path)
    before = hashes(value.root)
    result = map_run(value, fixture, verified)
    assert result.status == "succeeded" and not result.cache_hit
    assert all(p.read_bytes() for p in before)
    assert all(
        __import__("hashlib").sha256(p.read_bytes()).hexdigest() == h for p, h in before.items()
    )
    assert result.reconstruction.component_count == 1
    assert result.reconstruction.registered_view_count == 3
    assert result.reconstruction.unregistered_view_count == 0
    assert result.reconstruction.scale == "unknown_arbitrary"
    assert map_run(value, fixture, verified).cache_hit
    after = hashes(value.root)
    assert map_run(
        value, fixture, verified, resource_limits=MappingResourceLimits(max_views=10001)
    ).cache_hit
    assert all(
        __import__("hashlib").sha256(p.read_bytes()).hexdigest() == h for p, h in after.items()
    )
    reader = MappingService(value.execution, fixture.mapping_adapter()).reader(
        value.root, result.run_id
    )
    component = next(reader.components())
    assert len(tuple(reader.cameras(component.component_id))) == 3
    assert len(tuple(reader.registered_views(component.component_id))) == 3
    assert tuple(reader.unregistered_views()) == ()
    for operation in (reader.points, reader.tracks):
        with pytest.raises(ValueError, match="unavailable"):
            operation(component.component_id)
    assert not any(
        r.argv[0] == "view_graph_calibrator" and len(r.argv) > 2 for r in fixture.requests
    )
    assert result.reconstruction.components[0].native_model_id == "7"


def test_mapper_and_calibration_changes_only_rerun_mapping(tmp_path):
    value, fixture, _features, _raw, verified = mapping_inputs(tmp_path)
    before = hashes(value.root)
    original = map_run(value, fixture, verified)
    changed = map_run(value, fixture, verified, settings=GlobalMapperSettings(random_seed=1))
    calibrated = map_run(
        value, fixture, verified, calibration_policy=MappingCalibrationPolicy.VIEW_GRAPH
    )
    assert len({r.artifact.recipe_key for r in (original, changed, calibrated)}) == 3
    assert not changed.cache_hit and not calibrated.cache_hit
    assert all(
        __import__("hashlib").sha256(p.read_bytes()).hexdigest() == h for p, h in before.items()
    )
    assert (
        calibrated.reconstruction.calibration.cameras_before
        != calibrated.reconstruction.calibration.cameras_after
    )
    # A different preserve recipe always begins from M7, never the previous calibrated copy.
    preserved = map_run(value, fixture, verified, settings=GlobalMapperSettings(random_seed=2))
    assert (
        preserved.reconstruction.calibration.cameras_before
        == preserved.reconstruction.calibration.cameras_after
    )
    assert all(path.stat().st_nlink == 1 for path in fixture.private_databases)


@pytest.mark.parametrize(
    "policy,mode",
    [
        ("preserve_priors", "failed"),
        ("preserve_priors", "timeout"),
        ("preserve_priors", "empty"),
        ("preserve_priors", "malformed"),
        ("preserve_priors", "prior_snapshot"),
        ("view_graph", "failed"),
        ("view_graph", "malformed"),
        ("view_graph", "unexpected_edge"),
    ],
)
def test_backend_and_output_failures_never_publish_or_fallback(tmp_path, policy, mode):
    value, fixture, _features, _raw, verified = mapping_inputs(tmp_path)
    before = hashes(value.root)
    if policy == "view_graph":
        fixture.calibration_mode = mode
    else:
        fixture.mapping_mode = mode
    with pytest.raises(ValueError):
        map_run(value, fixture, verified, calibration_policy=MappingCalibrationPolicy(policy))
    assert query(value.root, "SELECT status FROM runs ORDER BY created_at DESC LIMIT 1") == [
        ("failed",)
    ]
    assert all(
        __import__("hashlib").sha256(p.read_bytes()).hexdigest() == h for p, h in before.items()
    )
    assert not any(
        r.argv[0] in {"mapper", "hierarchical_mapper"} and len(r.argv) > 2 for r in fixture.requests
    )
    if policy == "view_graph":
        assert not any(r.argv[0] == "global_mapper" and len(r.argv) > 2 for r in fixture.requests)


def test_calibration_requires_positive_capability(tmp_path):
    value, fixture, _features, _raw, verified = mapping_inputs(tmp_path)
    fixture.cal_help = "unrecognized"
    with pytest.raises(ValueError, match="capability"):
        map_run(value, fixture, verified, calibration_policy=MappingCalibrationPolicy.VIEW_GRAPH)
    assert not any(r.argv[0] == "global_mapper" and len(r.argv) > 2 for r in fixture.requests)


def test_cancellation_and_unresolved_teardown(tmp_path):
    value, fixture, _features, _raw, verified = mapping_inputs(tmp_path)
    before = hashes(value.root)

    def cancel(control):
        value.execution.request_cancellation(value.root, run_id=control.run)
        assert control.is_cancelled()

    fixture.on_map, fixture.mapping_mode = cancel, "cancelled"
    result = map_run(value, fixture, verified)
    assert (
        result.status == "cancelled" and result.artifact is None and result.reconstruction is None
    )
    assert all(
        __import__("hashlib").sha256(p.read_bytes()).hexdigest() == h for p, h in before.items()
    )
    fixture.on_map, fixture.mapping_mode = None, "unresolved"
    with pytest.raises(ValueError, match="teardown"):
        map_run(value, fixture, verified)
    assert query(
        value.root, "SELECT teardown_state FROM attempts ORDER BY started_at DESC LIMIT 1"
    ) == [("unresolved",)]


@pytest.mark.parametrize("corrupt", [False, True])
def test_orphan_publication_recovery_and_corruption_refusal(tmp_path, corrupt):
    value, fixture, _features, _raw, verified = mapping_inputs(tmp_path)

    def crash(_artifact):
        raise RuntimeError("after rename")

    repository = LocalExecutionRepository(
        project_store=LocalProjectStore(),
        fault_hooks=ExecutionFaultHooks(after_artifact_move=crash),
    )
    with pytest.raises(PublicationUnresolvedError):
        map_run(value, fixture, verified, repository=repository)
    run = UUID(query(value.root, "SELECT run_id FROM runs WHERE status='running'")[0][0])
    if corrupt:
        native = next(
            (value.root / "artifacts" / "mapping.reconstruction_set").rglob("images.bin"), None
        )
        if native is None:
            native = next(p for p in (value.root / "artifacts").rglob("images.bin"))
        native.write_bytes(b"corrupted orphan")
    recovered = FakeExecutionService(value.execution, LocalFakeStages()).recover(value.root, run)
    assert recovered.status == ("interrupted" if corrupt else "succeeded")
    assert len(recovered.adopted_attempts) == (0 if corrupt else 1)
    assert map_run(value, fixture, verified).cache_hit is not corrupt


def test_phase_progress_history_and_no_fake_percentage(tmp_path):
    from progress_helpers import FakeClock

    value, fixture, _features, _raw, verified = mapping_inputs(tmp_path)
    history = LocalPerformanceHistory(tmp_path / "history.sqlite")
    clock = FakeClock()
    support = ProgressSupport(history=history, clock=clock)
    fixture.on_map = lambda _owner: clock.advance(10)
    result = map_run(value, fixture, verified, progress=support)
    assert history.statistics().sample_count == 1
    assert map_run(value, fixture, verified, progress=support).cache_hit
    assert history.statistics().sample_count == 1
    events = [
        json.loads(line)
        for line in (value.root / "runs" / str(result.run_id) / "events.jsonl")
        .read_text()
        .splitlines()
    ]
    assert any(e["code"] == "progress.snapshot" for e in events)
    progress = RunProgressService(value.execution).get(value.root, result.run_id)
    assert progress.stages[0].work.work_model_id == "mapping.global_phases_v1"
    assert progress.stages[0].work.mode == "phase"


def test_all_native_components_published_without_selection_and_explicit_minimum(tmp_path):
    value, fixture, _features, _raw, verified = mapping_inputs(tmp_path, multi=True)
    fixture.mapping_mode = "multi"
    result = map_run(value, fixture, verified)
    assert result.reconstruction.component_count == 2
    assert result.reconstruction.registered_view_count == 6
    assert result.reconstruction.unregistered_view_count == 1
    assert sorted(c.native_model_id for c in result.reconstruction.components) == ["1", "23"]
    assert "selected_component" not in result.reconstruction.model_dump()
    with pytest.raises(ValueError, match="minimum model size"):
        map_run(value, fixture, verified, settings=GlobalMapperSettings(min_model_size=4))


def test_resource_gate_before_native_and_calibration_cancellation(tmp_path):
    value, fixture, _features, _raw, verified = mapping_inputs(tmp_path)
    fixture.requests.clear()
    with pytest.raises(ValueError, match="resource_limit"):
        map_run(value, fixture, verified, resource_limits=MappingResourceLimits(max_keypoints=1))
    assert not fixture.requests

    def cancel(control):
        value.execution.request_cancellation(value.root, run_id=control.run)

    fixture.on_calibration, fixture.calibration_mode = cancel, "cancelled"
    result = map_run(
        value, fixture, verified, calibration_policy=MappingCalibrationPolicy.VIEW_GRAPH
    )
    assert result.status == "cancelled" and result.artifact is None
    assert not any(r.argv[0] == "global_mapper" and len(r.argv) > 2 for r in fixture.requests)
