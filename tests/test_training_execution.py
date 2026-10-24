import os
import shutil
import sys
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest
from dataset_helpers import dataset_service
from test_views_execution import query
from training_helpers import FakeTrainer, training_dataset_setup

from splatforge.adapters.execution_storage import ExecutionFaultHooks, LocalExecutionRepository
from splatforge.application.execution import PublicationUnresolvedError
from splatforge.application.progress_reader import RunProgressService
from splatforge.application.training import TrainingService
from splatforge.core.execution import TrainingRuntime
from splatforge.core.training import TrainingLimits, TrainingSettings


@pytest.fixture(scope="module")
def prepared(tmp_path_factory):
    base = tmp_path_factory.mktemp("m11-base")
    with training_dataset_setup(base) as (value, fixture, _, _, selection):
        dataset = dataset_service(value, fixture).prepare(
            value.root, selection_run_id=selection.run.run_id
        )
    return value.root, dataset.run_id


@pytest.fixture
def project(tmp_path, prepared):
    root = tmp_path / "training ž with spaces"
    shutil.copytree(prepared[0], root)
    trainer = FakeTrainer()
    repository = LocalExecutionRepository()
    return root, prepared[1], trainer, repository, TrainingService(repository, trainer)


def settings(**values):
    return TrainingSettings(max_steps=10, checkpoint_every=5, **values)


@pytest.mark.parametrize("terminal", [0, -1, 11])
def test_invalid_stop_refused_before_storage_or_worker(tmp_path, terminal):
    service = TrainingService(object(), object())
    with pytest.raises(ValueError, match="invalid_stop_step"):
        service.run(
            tmp_path, uuid4(), TrainingRuntime(python="unused"), settings(),
            stop_after_step=terminal,
        )


def test_checkpoint_resume_scene_cache_and_progress(project, monkeypatch):
    root, dataset, trainer, repo, service = project
    monkeypatch.chdir(root.parent)
    relative = Path(root.name)
    runtime = TrainingRuntime(python="explicit-test-python")
    assert service.plan(relative, dataset, runtime, settings()).runnable
    first = service.run(relative, dataset, runtime, settings(), stop_after_step=5)
    assert first.status == "checkpointed" and len(first.jobs) == 1
    _, checkpoint = service.inspect(relative, first.jobs[0].run_id)
    assert checkpoint.step == 5
    resumed = service.run(root, dataset, runtime, settings(), resume_run=first.jobs[0].run_id)
    assert resumed.status == "succeeded" and len(resumed.scene_set.scenes) == 1
    assert [(r.start_step, r.terminal_step) for r in trainer.calls] == [(0, 5), (5, 10), (10, 10)]
    _, scene = service.inspect(root, resumed.jobs[-1].run_id)
    assert scene.final_step == 10 and scene.scale == "unknown_arbitrary"
    assert scene.metrics.evaluation_psnr is None
    assert repo.load_training(root, resumed.jobs[0].artifact).resumed_from_checkpoint == (
        first.jobs[0].artifact.semantic_digest
    )
    stage = RunProgressService(repo).get(root, resumed.jobs[0].run_id).stages[0]
    assert stage.completed == 10 and stage.work.initial_completed == 5
    before = len(trainer.calls)
    cached = service.run(root, dataset, runtime, settings(), TrainingLimits(timeout_seconds=1))
    assert len(trainer.calls) == before and cached.jobs[0].cache_hit
    changed = TrainingSettings(max_steps=11, checkpoint_every=5)
    assert not service.plan(root, dataset, runtime, changed).components[0].cache_hit
    assert len(service.handoff(root, dataset)) == 1


@pytest.mark.parametrize("change", ["strategy", "backend", "settings"])
def test_resume_compatibility(project, change):
    root, dataset, trainer, _, service = project
    runtime = TrainingRuntime(python="explicit-test-python")
    first = service.run(root, dataset, runtime, settings(), stop_after_step=5)
    selected = settings()
    if change == "strategy":
        selected = settings(strategy={"strategy": "mcmc"})
    elif change == "backend":
        trainer.identity = trainer.identity.model_copy(update={"packages_digest": "d" * 64})
    else:
        selected = settings(data_factor=2)
    with pytest.raises(ValueError, match="incompatible_checkpoint"):
        service.run(root, dataset, runtime, selected, resume_run=first.jobs[0].run_id)


def test_cancel_retains_published_checkpoint_and_no_partial_scene(project):
    root, dataset, trainer, repo, service = project
    runtime = TrainingRuntime(python="explicit-test-python")
    first = service.run(root, dataset, runtime, settings(), stop_after_step=5)

    def cancel(route, control):
        repo.request_cancellation(root, run_id=control.run)

    trainer.on_produce = cancel
    result = service.run(root, dataset, runtime, settings(), resume_run=first.jobs[0].run_id)
    assert result.status == "cancelled" and not result.scene_set
    assert service.inspect(root, first.jobs[0].run_id)[1].step == 5
    assert not query(
        root, "SELECT artifact_id FROM artifacts WHERE artifact_type='training.gaussian_scene'"
    )


def test_oom_failure_never_completes_progress_or_falls_back(project):
    root, dataset, trainer, repo, service = project

    def oom(route, control):
        raise ValueError("training.gpu_oom: controlled allocation failure")

    trainer.on_produce = oom
    with pytest.raises(ValueError, match="gpu_oom"):
        service.run(root, dataset, TrainingRuntime(python="test"), settings())
    assert len(trainer.calls) == 1
    run_id = __import__("uuid").UUID(
        query(root, "SELECT run_id FROM runs WHERE status='failed' ORDER BY created_at DESC")[0][0]
    )
    progress = RunProgressService(repo).get(root, run_id)
    assert progress.status == "failed"
    assert progress.stages[0].status == "failed" and progress.stages[0].fraction != 1
    assert not query(
        root, "SELECT artifact_id FROM artifacts WHERE artifact_type LIKE 'training.%'"
    )


@pytest.mark.skipif(
    os.name != "nt", reason="Native owner-death recovery requires Windows Job Objects"
)
def test_checkpoint_corruption_and_orphan_recovery(project):
    root, dataset, trainer, repo, service = project
    runtime = TrainingRuntime(python="explicit-test-python")

    def crash(path):
        raise OSError("simulated crash after rename")

    broken = LocalExecutionRepository(fault_hooks=ExecutionFaultHooks(after_artifact_move=crash))
    with pytest.raises(PublicationUnresolvedError):
        TrainingService(broken, trainer).run(root, dataset, runtime, settings(), stop_after_step=5)
    run_id = __import__("uuid").UUID(
        query(root, "SELECT run_id FROM runs WHERE status='running' ORDER BY created_at DESC")[0][0]
    )
    with repo.writer(root, owner_token=__import__("uuid").uuid4()):
        recovered = repo.recover_run(root, run_id=run_id)
    assert recovered.status == "succeeded" and recovered.adopted_attempts
    handle, checkpoint = service.inspect(root, run_id)
    path = root / Path(handle.manifest_path).parent / checkpoint.native.path
    path.write_bytes(b"broken")
    with pytest.raises(ValueError):
        service.run(root, dataset, runtime, settings(), resume_run=run_id)


def test_multi_component_separate_scene_jobs(tmp_path):
    with training_dataset_setup(tmp_path, multi=True) as (value, fixture, _, _, selection):
        dataset = dataset_service(value, fixture).prepare(
            value.root, selection_run_id=selection.run.run_id
        )
    trainer = FakeTrainer()
    service = TrainingService(value.execution, trainer)
    result = service.run(value.root, dataset.run_id, TrainingRuntime(python="test"), settings())
    assert result.status == "succeeded" and len(result.scene_set.scenes) == 2
    ids = [s.component_id for s in result.scene_set.scenes]
    assert ids == sorted(set(ids), key=lambda i: i.int)
    assert len({r.dataset.artifact_id for r in trainer.calls}) == 2
    assert len(trainer.calls) == 6


@pytest.mark.parametrize("stage", ["checkpoint", "scene"])
def test_cancel_partial_write_terminates_owned_tree_and_preserves_checkpoint(project, stage):
    from splatforge.adapters.gsplat_training import GsplatTrainingBackend
    from splatforge.adapters.process_runner import LocalProcessRunner

    root, dataset, trainer, repo, service = project
    config = TrainingRuntime(python=sys.executable)
    first = service.run(
        root, dataset, config, settings(), stop_after_step=5 if stage == "checkpoint" else 10
    )
    checkpoint_job = (
        first.jobs[-1]
        if stage == "checkpoint"
        else next(
            j for j in reversed(first.jobs) if j.artifact.artifact_type == "training.checkpoint"
        )
    )
    if stage == "scene":
        scene_path = root / Path(first.jobs[-1].artifact.manifest_path).parent / "scene.ply"
        scene_path.write_bytes(b"invalidate fixture scene to require an export attempt")
    observed, workspaces = [], []

    class Runner(LocalProcessRunner):
        def run(self, request, *, cancellation=None, poll=None):
            workspaces.append(request.working_directory)
            script = Path(__file__).parent / "fixtures/training_partial_worker.py"

            def cancel_ready():
                if (request.working_directory / "child.ready").exists():
                    repo.request_cancellation(
                        root, run_id=__import__("uuid").UUID(request.working_directory.parent.name)
                    )

            value = super().run(
                replace(request, argv=(str(script), request.argv[-1])),
                cancellation=cancellation,
                poll=cancel_ready,
            )
            observed.append(value)
            return value

    class Backend(GsplatTrainingBackend):
        def capability(self, *args, **kwargs):
            return trainer.identity

    result = TrainingService(repo, Backend(Runner())).run(
        root, dataset, config, settings(), resume_run=checkpoint_job.run_id
    )
    assert result.status == "cancelled" and not result.scene_set
    assert any(r.cancelled and r.teardown_confirmed for r in observed)
    assert service.inspect(root, checkpoint_job.run_id)[1].step in {5, 10}
    partial = next(workspaces[-1].rglob("*.partial"))
    # Windows refuses deletion while the fixture's descendant still holds this file.
    partial.unlink()
