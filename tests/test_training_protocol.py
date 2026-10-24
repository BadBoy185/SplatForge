import pytest
from training_helpers import event

from splatforge.core.training_protocol import WorkerProtocol


def running(*, scene=False, start=0):
    protocol = WorkerProtocol(total_steps=10, start_step=start, terminal_step=10, scene=scene)
    for seq, name in enumerate(("worker.started", "dataset.loaded", "training.started"), 1):
        protocol.accept(event(name, seq, start))
    return protocol


def test_ordered_checkpoint_and_scene_and_resumed_step():
    for scene in (False, True):
        parser = running(scene=scene, start=5)
        parser.accept(event("training.progress", 4, 6, loss=0.2, gaussian_count=4))
        parser.accept(event("evaluation.completed", 5, 10))
        parser.accept(event("scene.exported" if scene else "checkpoint.saved", 6, 10,
                            identity="a"*64))
        parser.accept(event("worker.completed", 7, 10, identity="b"*64))
        parser.finish()
        assert parser.step == 10 and parser.payload_identity == "a"*64


@pytest.mark.parametrize("line", [b"no json", b"{}", b"[]", b"x"*8193,
    event("training.progress", 3, 5), event("training.progress", 5, 5),
    event("unknown", 4, 5), event("training.progress", 4, 11),
    event("training.progress", 4, 5, total=11), event("worker.started", 4),
    event("worker.completed", 4, 10, identity="a"*64),
    event("worker.failed", 4, failure="gpu_oom", message="allocation failed"),
    event("training.progress", 4, 5, loss=float("nan")),
    event("training.progress", 4, 5, loss="0.2"),
    event("training.progress", 4, 5, loss=True)])
def test_fail_closed(line):
    with pytest.raises(ValueError):
        running().accept(line)


def test_premature_exit_no_scene_and_regression():
    parser = running(scene=True, start=5)
    with pytest.raises(ValueError, match="premature"):
        parser.finish()
    with pytest.raises(ValueError):
        parser.accept(event("checkpoint.saved", 4, 10, identity="a"*64))
    with pytest.raises(ValueError):
        parser.accept(event("training.progress", 4, 4))
    with pytest.raises(ValueError):
        WorkerProtocol(total_steps=10, start_step=5, terminal_step=10, scene=False).accept(
            event("worker.started", 1, 6))
