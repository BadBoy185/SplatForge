"""Selection/lineage/isolation/cache/resource/cancel/recovery acceptance for M10."""

from uuid import UUID

import pytest
from dataset_helpers import dataset_service, dataset_setup
from test_matching_execution import hashes
from test_selection_execution import service as selection_service
from test_views_execution import query

from splatforge.adapters.dataset_reader import read_dataset
from splatforge.adapters.execution_storage import ExecutionFaultHooks, LocalExecutionRepository
from splatforge.adapters.fake_stages import LocalFakeStages
from splatforge.application.execution import FakeExecutionService, PublicationUnresolvedError
from splatforge.core.dataset import DatasetResourceLimits, DatasetSettings


def test_dataset_plan_prepare_reader_cache_resize_and_reason(tmp_path):
    value, fixture, _mapping, validation, selection = dataset_setup(tmp_path)
    service = dataset_service(value, fixture)
    before = hashes(value.root)
    count = query(value.root, "SELECT count(*) FROM artifacts")
    with pytest.raises(ValueError):
        service.plan(value.root, selection_run_id=_mapping.run_id)
    plan = service.plan(value.root, selection_run_id=selection.run.run_id)
    assert plan.runnable and len(plan.components) == 1
    assert plan.components[0].registered_views == 3
    assert query(value.root, "SELECT count(*) FROM artifacts") == count
    first = service.prepare(value.root, selection_run_id=selection.run.run_id)
    assert first.status == "succeeded" and not first.cache_hit
    reference = first.dataset.components[0]
    directory = value.root / reference.manifest_path
    component = read_dataset(directory.parent)
    assert component.image_count == 3 and component.scale == "unknown_arbitrary"
    assert component.source_component == selection.selection.selected_components[0]
    assert component.selected_view_ids == tuple(i.view_id for i in component.input_images)
    again = service.prepare(value.root, selection_run_id=selection.run.run_id)
    assert again.cache_hit and again.artifact == first.artifact
    assert service.inspect(value.root, first.run_id) == first.dataset
    manual = selection_service(value).select(
        value.root,
        validation_run_id=validation.run_id,
        component_ids=selection.selection.selected_component_ids,
        manual_reason="Different reason.",
    )
    changed = service.prepare(value.root, selection_run_id=manual.run.run_id)
    assert changed.component_runs[0].cache_hit
    assert changed.dataset.semantic_digest == first.dataset.semantic_digest
    assert changed.dataset.provenance.selection_artifact_id == manual.run.artifact.artifact_id
    resized = service.prepare(
        value.root,
        selection_run_id=selection.run.run_id,
        settings=DatasetSettings(max_image_size=16),
    )
    assert not resized.component_runs[0].cache_hit
    resized_component = read_dataset(
        (value.root / resized.dataset.components[0].manifest_path).parent
    )
    assert {(i.width, i.height) for i in resized_component.images} == {(16, 12)}
    assert resized_component.semantic_digest != component.semantic_digest
    assert all(
        __import__("hashlib").sha256(p.read_bytes()).hexdigest() == h for p, h in before.items()
    )
    next((directory.parent / "images").iterdir()).write_bytes(b"corrupt prepared image")
    repaired = service.prepare(value.root, selection_run_id=selection.run.run_id)
    assert not repaired.component_runs[0].cache_hit
    assert repaired.dataset.semantic_digest == first.dataset.semantic_digest


def test_multiple_components_have_separate_layouts_and_reuse(tmp_path):
    value, fixture, _m, validation, selection = dataset_setup(tmp_path, multi=True)
    service = dataset_service(value, fixture)
    result = service.prepare(value.root, selection_run_id=selection.run.run_id)
    assert len(result.dataset.components) == 2
    ids = [c.component_id.int for c in result.dataset.components]
    assert ids == sorted(set(ids))
    a, b = [read_dataset((value.root / c.manifest_path).parent) for c in result.dataset.components]
    assert not set(a.selected_view_ids) & set(b.selected_view_ids)
    one = selection_service(value).select(
        value.root,
        validation_run_id=validation.run_id,
        component_ids=(a.source_component.component_id,),
    )
    assert service.prepare(value.root, selection_run_id=one.run.run_id).component_runs[0].cache_hit


def test_cancel_later_component_keeps_completed_component_and_no_set(tmp_path):
    value, fixture, _m, _v, selection = dataset_setup(tmp_path, multi=True)
    service = dataset_service(value, fixture)
    calls = 0

    def cancel_second(owner):
        nonlocal calls
        calls += 1
        if calls == 2:
            value.execution.request_cancellation(value.root, run_id=owner.run)

    fixture.on_undistort = cancel_second
    result = service.prepare(value.root, selection_run_id=selection.run.run_id)
    assert result.status == "cancelled" and len(result.component_runs) == 2
    assert result.component_runs[0].artifact and result.artifact is None
    assert not query(
        value.root, "SELECT artifact_id FROM artifacts WHERE artifact_type='dataset.prepared_set'"
    )
    fixture.on_undistort = None
    restarted = service.prepare(value.root, selection_run_id=selection.run.run_id)
    assert restarted.status == "succeeded" and restarted.component_runs[0].cache_hit


def test_cancel_before_native_launch(tmp_path):
    value, fixture, _m, _v, selection = dataset_setup(tmp_path)

    class CancelRepository(LocalExecutionRepository):
        def begin_attempt(self, root, **kwargs):
            attempt = super().begin_attempt(root, **kwargs)
            self.request_cancellation(root, run_id=kwargs["run_id"])
            return attempt

    result = dataset_service(value, fixture, CancelRepository()).prepare(
        value.root, selection_run_id=selection.run.run_id
    )
    assert result.status == "cancelled" and result.artifact is None
    assert not any(r.argv[0] == "image_undistorter" and len(r.argv) > 2 for r in fixture.requests)


def test_optional_process_diagnostics_failure_does_not_reverse_dataset(tmp_path):
    value, fixture, _m, _v, selection = dataset_setup(tmp_path)

    class DiagnosticFailureRepository(LocalExecutionRepository):
        def append_process_evidence(self, *_args, **_kwargs):
            raise OSError("diagnostic disk unavailable")

    result = dataset_service(value, fixture, DiagnosticFailureRepository()).prepare(
        value.root, selection_run_id=selection.run.run_id
    )
    assert result.status == "succeeded"


def test_current_selection_check_and_override_provenance(tmp_path, monkeypatch):
    from dataset_helpers import configure
    from test_selection_execution import service as select_service
    from test_selection_execution import setup

    from splatforge.core.validation_policy import ReconstructionValidationPolicy

    value, fixture, mapping, validation = setup(
        tmp_path,
        policy=ReconstructionValidationPolicy(
            policy_id="custom_v1", minimum_viable_cameras=4, warn_focal_ratio_above=0.1
        ),
    )
    report = validation.report
    ids = tuple(c.component_id for c in mapping.reconstruction.components)
    selection = select_service(value).select(
        value.root,
        validation_run_id=validation.run_id,
        component_ids=ids,
        override_issue_ids=tuple(i.issue_id for i in report.issues if i.severity == "failure"),
        override_reason="Reviewed the controlled three-camera fixture.",
    )
    configure(fixture)
    service = dataset_service(value, fixture)
    result = service.prepare(value.root, selection_run_id=selection.run.run_id)
    assert result.dataset.provenance.override == selection.selection.override.model_dump(
        mode="json"
    )
    assert result.dataset.provenance.warnings
    original = value.execution.load_reconstruction

    def stale(root, handle):
        reconstruction = original(root, handle)
        component = reconstruction.components[0].model_copy(update={"semantic_digest": "f" * 64})
        return reconstruction.model_copy(update={"components": (component,)})

    monkeypatch.setattr(value.execution, "load_reconstruction", stale)
    with pytest.raises(ValueError, match="stale"):
        service.plan(value.root, selection_run_id=selection.run.run_id)


def test_original_sources_unavailable_but_corrupt_historical_pixels_refused(tmp_path):
    value, fixture, _m, _v, selection = dataset_setup(tmp_path)
    service = dataset_service(value, fixture)
    # Controlled fixture only. Never manipulate real pilot originals.
    for path in value.source_paths:
        path.rename(path.with_suffix(path.suffix + ".relocated"))
    assert all(not p.exists() for p in value.source_paths)
    result = service.prepare(value.root, selection_run_id=selection.run.run_id)
    assert result.status == "succeeded"
    plan = service.plan(value.root, selection_run_id=selection.run.run_id)
    directory = value.execution.artifact_directory(value.root, plan.candidate)
    next((directory / "images").iterdir()).write_bytes(b"corrupted historical pixels")
    with pytest.raises(ValueError):
        service.prepare(value.root, selection_run_id=selection.run.run_id)


def test_resource_refusal_before_native_and_nonbinding_budget_reuses(tmp_path, monkeypatch):
    value, fixture, _m, _v, selection = dataset_setup(tmp_path)
    service = dataset_service(value, fixture)
    limits = DatasetResourceLimits(max_workspace_bytes=1)
    plan = service.plan(value.root, selection_run_id=selection.run.run_id, resource_limits=limits)
    assert not plan.runnable
    with pytest.raises(ValueError, match="resource_limit"):
        service.prepare(value.root, selection_run_id=selection.run.run_id, resource_limits=limits)
    with monkeypatch.context() as disk:
        disk.setattr(value.execution, "disk_free", lambda _root: 1)
        disk_plan = service.plan(value.root, selection_run_id=selection.run.run_id)
        assert not disk_plan.runnable
        assert any("insufficient free disk" in d for d in disk_plan.diagnostics)
        with pytest.raises(ValueError, match="insufficient free disk"):
            service.prepare(value.root, selection_run_id=selection.run.run_id)
    assert not any(r.argv[0] == "image_undistorter" and len(r.argv) > 2 for r in fixture.requests)
    service.prepare(value.root, selection_run_id=selection.run.run_id)
    assert service.prepare(
        value.root,
        selection_run_id=selection.run.run_id,
        resource_limits=DatasetResourceLimits(max_workspace_bytes=64 * 1024**3),
    ).cache_hit


def test_native_workspace_growth_refused_without_changing_resolution(tmp_path):
    value, fixture, _m, _v, selection = dataset_setup(tmp_path)
    service = dataset_service(value, fixture)
    plan = service.plan(value.root, selection_run_id=selection.run.run_id)
    bound = plan.components[0].estimate.peak_workspace_bytes + 1024

    def grow(owner):
        path = owner.root / "work" / str(owner.run) / str(owner.attempt) / "native-growth.bin"
        with path.open("wb") as stream:
            stream.truncate(bound + 1)

    fixture.on_undistort = grow
    with pytest.raises(ValueError, match="resource_limit"):
        service.prepare(
            value.root,
            selection_run_id=selection.run.run_id,
            resource_limits=DatasetResourceLimits(max_workspace_bytes=bound),
        )
    assert not query(
        value.root, "SELECT artifact_id FROM artifacts WHERE artifact_type LIKE 'dataset.%'"
    )
    assert plan.settings.max_image_size is None


@pytest.mark.parametrize("mode", ["cancel", "failed", "timeout", "partial", "unresolved"])
def test_dataset_native_failures_no_partial_publication(tmp_path, mode):
    value, fixture, _m, _v, selection = dataset_setup(tmp_path)
    service = dataset_service(value, fixture)
    before = hashes(value.root)
    fixture.undistortion_mode = mode
    if mode == "cancel":
        fixture.on_undistort = lambda owner: value.execution.request_cancellation(
            value.root, run_id=owner.run
        )
        assert (
            service.prepare(value.root, selection_run_id=selection.run.run_id).status == "cancelled"
        )
    else:
        with pytest.raises((ValueError, OSError)):
            service.prepare(value.root, selection_run_id=selection.run.run_id)
    assert not query(
        value.root, "SELECT artifact_id FROM artifacts WHERE artifact_type LIKE 'dataset.%'"
    )
    assert all(
        __import__("hashlib").sha256(p.read_bytes()).hexdigest() == h for p, h in before.items()
    )
    if mode != "unresolved":
        fixture.undistortion_mode, fixture.on_undistort = "success", None
        assert (
            service.prepare(value.root, selection_run_id=selection.run.run_id).status == "succeeded"
        )


@pytest.mark.parametrize("corrupt", [False, True])
def test_dataset_orphan_adoption_requires_full_validation(tmp_path, corrupt):
    value, fixture, _m, _v, selection = dataset_setup(tmp_path)

    def crash(path):
        if path.parent.name == "dataset_component":
            if corrupt:
                (path / "sparse/0/points3D.bin").write_bytes(b"partial")
            raise RuntimeError("after dataset rename")

    repo = LocalExecutionRepository(fault_hooks=ExecutionFaultHooks(after_artifact_move=crash))
    with pytest.raises(PublicationUnresolvedError):
        dataset_service(value, fixture, repo).prepare(
            value.root, selection_run_id=selection.run.run_id
        )
    run = UUID(query(value.root, "SELECT run_id FROM runs WHERE status='running'")[0][0])
    recovered = FakeExecutionService(value.execution, LocalFakeStages()).recover(value.root, run)
    assert len(recovered.adopted_attempts) == (0 if corrupt else 1)
    result = dataset_service(value, fixture).prepare(
        value.root, selection_run_id=selection.run.run_id
    )
    assert result.component_runs[0].cache_hit is (not corrupt)
