"""Opt-in real CUDA transport; synthetic images never establish product quality."""

import json
import os
import shutil
from pathlib import Path
from uuid import UUID

import pytest
from training_helpers import prepared_training_project

from splatforge.adapters.execution_storage import LocalExecutionRepository
from splatforge.adapters.gaussian_ply import read_gaussian_ply
from splatforge.adapters.gsplat_training import GsplatTrainingBackend
from splatforge.adapters.process_runner import LocalProcessRunner, ProcessRequest
from splatforge.application.training import TrainingService
from splatforge.core.execution import TrainingRuntime
from splatforge.core.training import TrainingSettings

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.environ.get("SPLATFORGE_TEST_TRAINING_RUNTIME"),
        reason="Set SPLATFORGE_TEST_TRAINING_RUNTIME to an explicitly provisioned runtime JSON",
    ),
]


def runtime():
    return TrainingRuntime.model_validate(
        json.loads(
            Path(os.environ["SPLATFORGE_TEST_TRAINING_RUNTIME"]).read_text(encoding="utf-8-sig")
        )
    )


def test_black_sfm_color_can_learn_through_real_raster(tmp_path):
    from splatforge.adapters.gsplat_training import WORKER

    config = runtime()
    script = """
import importlib.util, sys, torch
spec = importlib.util.spec_from_file_location('worker_runtime', sys.argv[1])
worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)
sh = torch.nn.Parameter(worker.rgb_to_sh([[0, 0, 0]] * 4, 'cuda'))
params = {
    'means': torch.tensor(
        [[-.1, -.1, 2.], [.1, -.1, 2.], [-.1, .1, 2.], [.1, .1, 2.]], device='cuda'),
    'scales': torch.full((4, 3), -2., device='cuda'),
    'quats': torch.tensor([[1., 0, 0, 0]] * 4, device='cuda'),
    'opacities': torch.zeros(4, device='cuda'), 'sh0': sh,
    'shN': torch.zeros((4, 15, 3), device='cuda'),
}
k = torch.tensor([[30., 0, 16], [0, 30., 16], [0, 0, 1]], device='cuda')
optimizer = torch.optim.Adam([sh], lr=.01)
colors = worker.raster(params, torch.eye(4, device='cuda'), k, 32, 32, 0)[0]
assert colors.abs().max() == 0
(colors - 1).square().mean().backward()
assert torch.isfinite(sh.grad).all() and sh.grad.abs().sum() > 0
optimizer.step()
after = worker.raster(params, torch.eye(4, device='cuda'), k, 32, 32, 0)[0]
assert after.mean() > colors.mean()
print('black_sfm_gradient_optimizer_pass')
"""
    result = LocalProcessRunner().run(
        ProcessRequest(
            config.python,
            ("-I", "-c", script, str(WORKER.resolve().with_name("runtime.py"))),
            tmp_path,
            config.environment,
            60,
        )
    )
    assert result.exit_code == 0, result.stderr_text()
    assert result.teardown_confirmed
    assert "black_sfm_gradient_optimizer_pass" in result.stdout_text()


@pytest.fixture(scope="module")
def prepared(tmp_path_factory):
    return prepared_training_project(tmp_path_factory.mktemp("m11-real"))


@pytest.mark.parametrize("strategy", ["default", "absgrad", "mcmc"])
def test_real_training_checkpoint_resume_ply_cache_and_consumer(
    tmp_path, prepared, strategy, record_property
):
    root = tmp_path / "real CUDA scene ž with spaces"
    shutil.copytree(prepared[0], root)
    repo, backend = LocalExecutionRepository(), GsplatTrainingBackend()
    service = TrainingService(repo, backend)
    config = runtime()
    parameters = (
        {"strategy": "mcmc", "cap_max": 128}
        if strategy == "mcmc"
        else {
            "strategy": "default",
            "absgrad": strategy == "absgrad",
            "grow_grad2d": 0.0008 if strategy == "absgrad" else 0.0002,
            "reset_every": 100,
        }
    )
    parameters.update(refine_start_iter=0, refine_stop_iter=40, refine_every=10)
    settings = TrainingSettings.model_validate(
        {"strategy": parameters, "max_steps": 50, "checkpoint_every": 25, "sh_degree_interval": 10}
    )
    first = service.run(root, prepared[1], config, settings, stop_after_step=25)
    assert first.status == "checkpointed"
    resumed = service.run(root, prepared[1], config, settings, resume_run=first.jobs[0].run_id)
    assert resumed.status == "succeeded"
    handle, scene = service.inspect(root, resumed.jobs[-1].run_id)
    assert scene.final_step == 50 and scene.gaussian_count > 0
    assert scene.metrics.peak_allocated_cuda_bytes > 0
    assert scene.backend.kernel_backward_optimizer
    path = root / Path(handle.manifest_path).parent / "scene.ply"
    assert read_gaussian_ply(path).count == scene.gaussian_count
    # Independent PLY implementation in a disposable process, separate from our reader.
    consumer = LocalProcessRunner().run(
        ProcessRequest(
            config.python,
            (
                "-c",
                "import sys; from plyfile import PlyData; p=PlyData.read(sys.argv[1]); "
                "assert len(p['vertex'])==int(sys.argv[2]); "
                "assert 'f_rest_44' in p['vertex'].data.dtype.names; "
                "print('independent_ply_consumer_pass')",
                str(path),
                str(scene.gaussian_count),
            ),
            root,
            config.environment,
            60,
        )
    )
    assert consumer.exit_code == 0 and consumer.teardown_confirmed
    again = service.run(root, prepared[1], config, settings)
    assert again.jobs[0].cache_hit and again.scene_set == resumed.scene_set
    checkpoint = service.inspect(root, resumed.jobs[0].run_id)[1]
    assert (
        checkpoint.step == 50
        and checkpoint.resumed_from_checkpoint == first.jobs[0].artifact.semantic_digest
    )
    record_property(
        "m11_transport",
        json.dumps(
            {
                "strategy": strategy,
                "scene": scene.model_dump(mode="json"),
                "consumer": consumer.stdout_text().strip(),
            }
        ),
    )


def test_real_cancellation_contains_cuda_process_tree(tmp_path, prepared):
    root = tmp_path / "cancel CUDA ž"
    shutil.copytree(prepared[0], root)
    repo = LocalExecutionRepository()
    observed = []

    class CancelRunner(LocalProcessRunner):
        def run(self, request, *, cancellation=None, poll=None):
            # Only training requests have an output_path. Probes remain real and bounded.
            config = json.loads(Path(request.argv[-1]).read_text(encoding="utf-8"))

            def cancel_when_training():
                if config.get("operation") == "train":
                    events = Path(config["events_path"])
                    if events.exists() and b'"training.started"' in events.read_bytes():
                        repo.request_cancellation(
                            root, run_id=UUID(request.working_directory.parent.name)
                        )
                if poll:
                    poll()

            result = super().run(request, cancellation=cancellation, poll=cancel_when_training)
            observed.append(result)
            return result

    service = TrainingService(repo, GsplatTrainingBackend(CancelRunner()))
    result = service.run(root, prepared[1], runtime(), TrainingSettings(max_steps=100000))
    assert result.status == "cancelled" and not result.scene_set
    assert any(r.cancelled and r.teardown_confirmed for r in observed)
