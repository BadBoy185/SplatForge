"""Single-model Incremental lifecycle through the M8a database/publication boundary."""

import hashlib
import json
import sqlite3
from contextlib import closing
from uuid import UUID

import pytest
from mapping_helpers import map_run, mapping_inputs
from test_incremental_contracts import caspar_settings
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
from splatforge.application.work_models import mapping_progress_plan
from splatforge.core.execution import IncrementalMappingRoute, MappingRoute, RunSnapshot
from splatforge.core.progress import ExecutionHardwareProfile
from splatforge.core.reconstruction import (
    CasparDevice,
    GlobalMapperSettings,
    IncrementalMapperSettings,
    MappingResourceLimits,
)


def run(value, fixture, verified, **kwargs):
    return map_run(value, fixture, verified, **{"settings": IncrementalMapperSettings(), **kwargs})


def unchanged(before):
    assert all(hashlib.sha256(p.read_bytes()).hexdigest() == h for p, h in before.items())


def snapshot(value, result):
    return RunSnapshot.model_validate_json(
        (value.root / "runs" / str(result.run_id) / "run.json").read_bytes()
    )


def test_incremental_global_cache_boundaries_reader_and_old_snapshots(tmp_path):
    value, fixture, _features, _raw, verified = mapping_inputs(tmp_path)
    before = hashes(value.root)
    global_run = map_run(value, fixture, verified)
    result = run(value, fixture, verified)
    assert not result.cache_hit and result.reconstruction.component_count == 1
    assert result.reconstruction.semantic_digest == global_run.reconstruction.semantic_digest
    assert result.artifact.recipe_key != global_run.artifact.recipe_key
    assert type(snapshot(value, global_run).route) is MappingRoute
    assert type(snapshot(value, result).route) is IncrementalMappingRoute
    assert map_run(value, fixture, verified).cache_hit
    assert run(value, fixture, verified).cache_hit
    assert run(
        value, fixture, verified, resource_limits=MappingResourceLimits(max_views=10001)
    ).cache_hit
    changed = run(value, fixture, verified, settings=IncrementalMapperSettings(random_seed=1))
    assert not changed.cache_hit
    assert changed.artifact.recipe_key != result.artifact.recipe_key
    reader = MappingService(value.execution, fixture.mapping_adapter()).reader(
        value.root, result.run_id
    )
    component = next(reader.components())
    assert len(tuple(reader.registered_views(component.component_id))) == 3
    assert len(tuple(reader.cameras(component.component_id))) == 3
    assert tuple(reader.unregistered_views()) == ()
    argv = next(r.argv for r in fixture.requests if r.argv[0] == "mapper" and len(r.argv) > 2)
    assert argv[argv.index("--Mapper.multiple_models") + 1] == "0"
    assert argv[argv.index("--Mapper.extract_colors") + 1] == "0"
    assert all(p.stat().st_nlink == 1 for p in fixture.private_databases)
    assert not any(
        r.argv[0] == "view_graph_calibrator" and len(r.argv) > 2 for r in fixture.requests
    )
    unchanged(before)


@pytest.mark.parametrize(
    "mode,reason",
    [
        ("failed", "mapper_process_failure"),
        ("timeout", "timed out"),
        ("empty", "zero_components"),
        ("malformed", "malformed_output"),
        ("overlap", "unexpected_multiple_models"),
        ("prior_snapshot", "input_mismatch"),
        ("unresolved", "teardown"),
    ],
)
def test_incremental_failures_preserve_all_published_bytes_and_never_retry(tmp_path, mode, reason):
    value, fixture, _features, _raw, verified = mapping_inputs(tmp_path)
    previous = run(value, fixture, verified)
    before = hashes(value.root)
    fixture.requests.clear()
    fixture.mapping_mode = mode
    with pytest.raises(ValueError, match=reason):
        run(value, fixture, verified, settings=IncrementalMapperSettings(random_seed=2))
    assert len([r for r in fixture.requests if r.argv[0] == "mapper" and len(r.argv) > 2]) == 1
    assert not any(
        r.argv[0] in {"global_mapper", "hierarchical_mapper"} and len(r.argv) > 2
        for r in fixture.requests
    )
    assert (
        MappingService(value.execution, fixture.mapping_adapter()).inspect(
            value.root, previous.run_id
        )
        == previous.reconstruction
    )
    if mode == "unresolved":
        assert query(
            value.root, "SELECT teardown_state FROM attempts ORDER BY started_at DESC LIMIT 1"
        ) == [("unresolved",)]
        with pytest.raises(ValueError):
            run(value, fixture, verified)
    unchanged(before)


def test_cancellation_no_artifact_and_corrupt_cache_refused(tmp_path):
    value, fixture, _features, _raw, verified = mapping_inputs(tmp_path)
    before = hashes(value.root)
    fixture.mapping_mode = "cancelled"
    fixture.on_map = lambda owner: value.execution.request_cancellation(
        value.root, run_id=owner.run
    )
    result = run(value, fixture, verified)
    assert result.status == "cancelled" and result.artifact is None
    fixture.on_map, fixture.mapping_mode = None, "success"
    good = run(value, fixture, verified)
    directory = value.execution.artifact_directory(value.root, good.artifact)
    (directory / "sparse" / "7" / "images.bin").write_bytes(b"corrupt")
    replacement = run(value, fixture, verified)
    assert (
        not replacement.cache_hit and replacement.artifact.artifact_id != good.artifact.artifact_id
    )
    unchanged(before)


@pytest.mark.parametrize("corrupt", [False, True])
def test_incremental_orphan_adoption_and_corruption(tmp_path, corrupt):
    value, fixture, _features, _raw, verified = mapping_inputs(tmp_path)

    def crash(_artifact):
        raise RuntimeError("after rename")

    repository = LocalExecutionRepository(
        project_store=LocalProjectStore(),
        fault_hooks=ExecutionFaultHooks(after_artifact_move=crash),
    )
    with pytest.raises(PublicationUnresolvedError):
        run(value, fixture, verified, repository=repository)
    run_id = UUID(query(value.root, "SELECT run_id FROM runs WHERE status='running'")[0][0])
    if corrupt:
        next((value.root / "artifacts").rglob("images.bin")).write_bytes(b"corrupt")
    recovered = FakeExecutionService(value.execution, LocalFakeStages()).recover(value.root, run_id)
    assert recovered.status == ("interrupted" if corrupt else "succeeded")
    assert len(recovered.adopted_attempts) == (0 if corrupt else 1)


def test_no_calibration_and_bypass_invariants_refused_before_planning(tmp_path):
    service = MappingService(None, None)
    invalid = IncrementalMapperSettings().model_copy(update={"multiple_models": True})
    with pytest.raises(ValueError):
        service.run(tmp_path, verification_run_id=UUID(int=1), settings=invalid)
    with pytest.raises(ValueError, match="without calibration"):
        service.run(
            tmp_path,
            verification_run_id=UUID(int=1),
            settings=IncrementalMapperSettings(),
            calibration_policy="view_graph",
        )


def test_caspar_unsupported_input_and_missing_build_fail_before_numerical_attempt(tmp_path):
    value, fixture, _features, _raw, verified = mapping_inputs(
        tmp_path, camera_model="SIMPLE_PINHOLE"
    )
    fixture.requests.clear()
    with pytest.raises(ValueError, match="SIMPLE_PINHOLE"):
        run(value, fixture, verified, settings=caspar_settings())
    assert not fixture.requests
    # Direct preparation isolates compiled support from input compatibility.
    with pytest.raises(ValueError, match="caspar_not_compiled"):
        fixture.mapping_adapter().prepare(
            "preserve_priors", colmap=fixture.exe, settings=caspar_settings(), calibration=None
        )
    assert not any(r.argv[0] == "mapper" and len(r.argv) > 2 for r in fixture.requests)


def test_incremental_history_phase_and_device_signatures(tmp_path, monkeypatch):
    from splatforge.adapters import caspar_probe

    value, fixture, _features, _raw, verified = mapping_inputs(tmp_path)
    history = LocalPerformanceHistory(tmp_path / "history.sqlite")
    result = run(value, fixture, verified, progress=ProgressSupport(history=history))
    assert history.statistics().sample_count == 1
    assert run(value, fixture, verified, progress=ProgressSupport(history=history)).cache_hit
    assert history.statistics().sample_count == 1
    observed = RunProgressService(value.execution).get(value.root, result.run_id)
    assert observed.stages[0].work.work_model_id == "mapping.incremental_phases_v1"
    assert observed.stages[0].work.mode == "phase"
    events = [
        json.loads(line)
        for line in (value.root / "runs" / str(result.run_id) / "events.jsonl")
        .read_text()
        .splitlines()
    ]
    assert all(
        e["details"]["snapshot"]["fraction"] is None
        for e in events
        if e["code"] == "progress.snapshot"
        and any(stage["status"] == "running" for stage in e["details"]["snapshot"]["stages"])
    )
    fixture.caspar_compiled = True
    device = CasparDevice(
        index=0,
        uuid="a" * 32,
        name="fixture GPU",
        driver_version=12080,
        driver_binary_sha256="c" * 64,
        compute_major=12,
        compute_minor=0,
    )
    monkeypatch.setattr(caspar_probe, "probe_caspar", lambda *_: device)
    backend = fixture.mapping_adapter().prepare(
        "preserve_priors", colmap=fixture.exe, settings=caspar_settings(), calibration=None
    )
    route = snapshot(value, result).route
    cpu_plan = mapping_progress_plan(route, ExecutionHardwareProfile())
    gpu_route = IncrementalMappingRoute.model_validate(
        {**route.model_dump(), "backend": backend, "settings": caspar_settings()}
    )
    gpu_plan = mapping_progress_plan(gpu_route, ExecutionHardwareProfile())
    assert cpu_plan.signature != gpu_plan.signature and gpu_plan.signature.hardware.device == "gpu"
    assert route.recipe_key() != gpu_route.recipe_key()


def test_incremental_single_component_retains_all_unregistered_and_enforces_minimum(tmp_path):
    value, fixture, _features, _raw, verified = mapping_inputs(tmp_path, multi=True)
    fixture.mapping_mode = "partial"
    result = run(value, fixture, verified)
    assert result.reconstruction.component_count == 1
    assert result.reconstruction.registered_view_count == 3
    assert result.reconstruction.unregistered_view_count == 4
    assert len(result.reconstruction.unregistered_view_ids) == 4
    with pytest.raises(ValueError, match="minimum model size"):
        run(value, fixture, verified, settings=IncrementalMapperSettings(min_model_size=4))
    fixture.mapping_mode = "multi"
    with pytest.raises(ValueError, match="unexpected_multiple_models"):
        run(value, fixture, verified, settings=IncrementalMapperSettings(random_seed=1))


@pytest.mark.parametrize("original_method", ["global", "incremental"])
def test_recovery_never_adopts_artifact_into_other_mapper_route(tmp_path, original_method):
    value, fixture, _features, _raw, verified = mapping_inputs(tmp_path)

    def crash(_artifact):
        raise RuntimeError("orphan")

    repository = LocalExecutionRepository(
        project_store=LocalProjectStore(),
        fault_hooks=ExecutionFaultHooks(after_artifact_move=crash),
    )
    settings = (
        GlobalMapperSettings() if original_method == "global" else IncrementalMapperSettings()
    )
    with pytest.raises(PublicationUnresolvedError):
        map_run(value, fixture, verified, settings=settings, repository=repository)
    run_id = UUID(query(value.root, "SELECT run_id FROM runs WHERE status='running'")[0][0])
    path = value.root / "runs" / str(run_id) / "run.json"
    data = json.loads(path.read_text())
    route = data["route"]
    if original_method == "global":
        route.update(
            route_id="mapping.incremental.run", settings=IncrementalMapperSettings().model_dump()
        )
        route["backend"].update(
            adapter_id="splatforge.colmap_incremental", operation="mapper", device=None
        )
    else:
        route.update(route_id="mapping.run", settings=GlobalMapperSettings().model_dump())
        route["backend"].update(adapter_id="splatforge.colmap_global", operation="global_mapper")
        route["backend"].pop("device")
    RunSnapshot.model_validate(data)
    path.write_text(json.dumps(data), encoding="utf-8")
    # Fault injection beyond the independent snapshot-integrity guard: the orphan
    # still must not be adopted into a different, internally consistent frozen route.
    with closing(sqlite3.connect(value.root / "state.sqlite")) as db, db:
        db.execute("UPDATE runs SET snapshot_digest=? WHERE run_id=?",
                   (hashlib.sha256(path.read_bytes()).hexdigest(), str(run_id)))
    recovered = FakeExecutionService(value.execution, LocalFakeStages()).recover(value.root, run_id)
    assert recovered.status == "interrupted" and not recovered.adopted_attempts
