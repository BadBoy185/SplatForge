"""M9a publication/cache/recovery/cancellation with unchanged M8 artifacts."""

import json
from uuid import UUID

import pytest
from mapping_helpers import map_run, mapping_inputs
from test_matching_execution import hashes
from test_views_execution import query

from splatforge.adapters.execution_storage import ExecutionFaultHooks, LocalExecutionRepository
from splatforge.adapters.fake_stages import LocalFakeStages
from splatforge.adapters.validation_geometry import ColmapValidationSource
from splatforge.application.execution import FakeExecutionService, PublicationUnresolvedError
from splatforge.application.progress_reader import RunProgressService
from splatforge.application.reconstruction_validation import ReconstructionValidationService
from splatforge.core.reconstruction_validation import MeasurementSettings, ValidationResourceLimits
from splatforge.core.validation_policy import ReconstructionValidationPolicy


def setup(tmp_path):
    value, fixture, _f, _r, verified = mapping_inputs(tmp_path)
    mapping = map_run(value, fixture, verified)
    return value, fixture, mapping


def service(value, repository=None, source=ColmapValidationSource, **kwargs):
    return ReconstructionValidationService(repository or value.execution, source, **kwargs)


def test_m8_artifacts_consume_without_rewrite_and_thresholds_reuse_measurements(
    tmp_path, monkeypatch
):
    value, fixture, mapping = setup(tmp_path)
    before = hashes(value.root)
    calls = []

    def source(*args):
        calls.append(True)
        return ColmapValidationSource(*args)

    current = service(value, source=source)
    runs_before_refusal = query(value.root, "SELECT count(*) FROM runs")
    with pytest.raises(ValueError, match="metadata plan"):
        current.validate(
            value.root,
            mapping_run_id=mapping.run_id,
            resource_limits=ValidationResourceLimits(max_coverage_cells=1),
        )
    assert not calls and query(value.root, "SELECT count(*) FROM runs") == runs_before_refusal
    first = current.validate(value.root, mapping_run_id=mapping.run_id)
    assert first.status == "succeeded"
    assert len(calls) == 2  # canonical identity then measurements
    assert not first.metrics_run.cache_hit and not first.report_run.cache_hit

    def no_point_rescan(*_args, **_kwargs):
        raise AssertionError("Policy-only validation must not deserialize sparse observations")

    with monkeypatch.context() as checks:
        checks.setattr("splatforge.adapters.mapping_artifacts.read_components", no_point_rescan)
        checks.setattr("splatforge.adapters.mapping_artifacts.read_component", no_point_rescan)
        checks.setattr("splatforge.adapters.validation_geometry.read_component", no_point_rescan)
        second = current.validate(
            value.root,
            mapping_run_id=mapping.run_id,
            policy=ReconstructionValidationPolicy(
                policy_id="custom_v1", fail_registration_below=0.9
            ),
        )
    assert second.geometry_run.cache_hit and second.metrics_run.cache_hit
    assert not second.report_run.cache_hit and len(calls) == 2
    assert first.metrics_run.artifact == second.metrics_run.artifact
    third = current.validate(
        value.root,
        mapping_run_id=mapping.run_id,
        settings=MeasurementSettings(quantile_sample_bound=50),
    )
    assert third.geometry_run.cache_hit and not third.metrics_run.cache_hit
    assert len(calls) == 3
    assert (
        service(value)
        .validate(
            value.root,
            mapping_run_id=mapping.run_id,
            resource_limits=ValidationResourceLimits(
                max_native_bytes=2 * 1024**3, max_components=2000, max_coverage_cells=500000
            ),
        )
        .metrics_run.cache_hit
    )
    assert all(
        __import__("hashlib").sha256(p.read_bytes()).hexdigest() == h for p, h in before.items()
    )
    report, metrics = current.inspect_details(value.root, first.run_id)
    assert metrics.registration.registered_views == 3
    assert report.metrics_digest == metrics.semantic_digest
    assert current.inspect(value.root, first.run_id).report == report
    assert not any(r.argv[0] == "model_analyzer" for r in fixture.requests)
    # Structural-evidence reuse still enforces current ownership and payload set.
    directory = value.execution.artifact_directory(value.root, mapping.artifact)
    extra = directory / "sparse" / "99999"
    extra.mkdir()
    with pytest.raises(ValueError, match="unexpected native model"):
        current.validate(value.root, mapping_run_id=mapping.run_id)
    extra.rmdir()
    import os

    native = directory / mapping.reconstruction.components[0].native_payload / "points3D.bin"
    alias = tmp_path / "native-alias.bin"
    os.link(native, alias)
    with pytest.raises(ValueError, match="independent plain"):
        current.validate(value.root, mapping_run_id=mapping.run_id)
    alias.unlink()
    native.write_bytes(b"corrupted native geometry")
    with pytest.raises(ValueError, match="digest mismatch|size or digest"):
        current.validate(value.root, mapping_run_id=mapping.run_id)


@pytest.mark.parametrize(
    "node", ["validation_geometry", "reconstruction_metrics", "reconstruction_validation"]
)
@pytest.mark.parametrize("corrupt", [False, True])
def test_orphan_adoption_and_corruption_refusal_use_existing_store(tmp_path, node, corrupt):
    value, _fixture, mapping = setup(tmp_path)

    def crash(path):
        if path.parent.name == node:
            if corrupt:
                (path / "evidence.json").write_bytes(b"corrupt orphan")
            raise RuntimeError("after rename")

    repository = LocalExecutionRepository(
        fault_hooks=ExecutionFaultHooks(after_artifact_move=crash)
    )
    with pytest.raises(PublicationUnresolvedError):
        service(value, repository).validate(value.root, mapping_run_id=mapping.run_id)
    run = UUID(query(value.root, "SELECT run_id FROM runs WHERE status='running'")[0][0])
    recovered = FakeExecutionService(value.execution, LocalFakeStages()).recover(value.root, run)
    assert recovered.status == ("interrupted" if corrupt else "succeeded")
    assert len(recovered.adopted_attempts) == (0 if corrupt else 1)
    assert service(value).validate(value.root, mapping_run_id=mapping.run_id).status == "succeeded"


@pytest.mark.parametrize("cancel_at", [1, 2])
def test_durable_cancellation_no_partial_publication_and_restart_from_m8(tmp_path, cancel_at):
    value, _fixture, mapping = setup(tmp_path)
    before = hashes(value.root)
    calls = 0

    def source(*args):
        nonlocal calls
        calls += 1
        if calls != cancel_at:
            return ColmapValidationSource(*args)
        control = args[-1].__self__
        value.execution.request_cancellation(value.root, run_id=control.run)
        control.checkpoint()

    result = service(value, source=source).validate(value.root, mapping_run_id=mapping.run_id)
    assert result.status == "cancelled" and result.report is None
    if cancel_at == 1:
        assert result.geometry_run.artifact is None and result.metrics_run is None
    else:
        assert result.geometry_run.artifact is not None and result.metrics_run.artifact is None
    assert all(
        __import__("hashlib").sha256(p.read_bytes()).hexdigest() == h for p, h in before.items()
    )
    assert service(value).validate(value.root, mapping_run_id=mapping.run_id).status == "succeeded"


def test_corrupt_measurements_refused_in_cache_and_inspection(tmp_path):
    value, _fixture, mapping = setup(tmp_path)
    first = service(value).validate(value.root, mapping_run_id=mapping.run_id)
    path = (
        value.execution.artifact_directory(value.root, first.metrics_run.artifact) / "evidence.json"
    )
    path.write_bytes(b"corrupt measurements")
    with pytest.raises(ValueError):
        service(value).inspect_details(value.root, first.run_id)
    second = service(value).validate(value.root, mapping_run_id=mapping.run_id)
    assert not second.metrics_run.cache_hit


def test_progress_uses_work_points_and_metadata_only_completion_has_no_fake_fraction(tmp_path):
    value, _fixture, mapping = setup(tmp_path)
    result = service(value).validate(value.root, mapping_run_id=mapping.run_id)
    progress = RunProgressService(value.execution).get(value.root, result.metrics_run.run_id)
    assert progress.stages[0].work.work_model_id == "validation.reconstruction_points_v1"
    assert progress.stages[0].work.mode == "phase"  # zero native points in this M8 fixture
    assert progress.stages[0].eta.likely_seconds == 0
    events = [
        json.loads(line)
        for line in (value.root / "runs" / str(result.metrics_run.run_id) / "events.jsonl")
        .read_text()
        .splitlines()
    ]
    assert any(e["code"] == "progress.snapshot" for e in events)


def test_universe_comes_from_historical_artifacts_after_mutable_intent_changes(tmp_path):
    value, _fixture, mapping = setup(tmp_path)
    first = value.execution.validation_universe(value.root, mapping.artifact)[2]
    path = value.root / "project.json"
    intent = json.loads(path.read_text())
    intent["label"] = "New mutable intent"
    path.write_text(json.dumps(intent), encoding="utf8")
    second = value.execution.validation_universe(value.root, mapping.artifact)[2]
    assert first == second
