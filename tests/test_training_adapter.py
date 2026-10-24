import json
from pathlib import Path
from uuid import uuid4

import pytest
from training_helpers import FakeTrainer, backend_identity

from splatforge.adapters.gsplat_training import GsplatTrainingBackend
from splatforge.adapters.training_artifacts import read_training_output
from splatforge.application.features_contracts import FeatureTeardownError
from splatforge.core.execution import (
    ArtifactHandle,
    TrainingCheckpointRoute,
    TrainingRuntime,
    TrainingSceneRoute,
)
from splatforge.core.media import ExecutableIdentity
from splatforge.core.process import ProcessResult
from splatforge.core.training import CHECKPOINT_TYPE, TrainingSettings


class NotCancelled:
    def is_cancelled(self):
        return False


def handle(kind="dataset.prepared_component"):
    identity = uuid4()
    return ArtifactHandle(
        artifact_id=identity,
        artifact_type=kind,
        contract_version=1,
        semantic_digest="a" * 64,
        recipe_key="b" * 64,
        manifest_path=f"artifacts/dataset_component/{identity}/manifest.json",
    )


def route(scene=False):
    common = dict(
        dataset=handle(),
        settings=TrainingSettings(max_steps=10),
        backend=backend_identity(),
        runtime=TrainingRuntime(python="test.exe"),
        terminal_step=10,
        image_count=3,
        megapixels=0.001,
    )
    return (
        TrainingSceneRoute(**common, resume=handle(CHECKPOINT_TYPE), start_step=10)
        if scene
        else (TrainingCheckpointRoute(**common))
    )


class Transport:
    def __init__(self, route, fault=None):
        self.route, self.fault, self.requests = route, fault, []

    def run(self, request, *, cancellation=None):
        self.requests.append(request)
        workspace = request.working_directory
        raw = json.loads(Path(request.argv[-1]).read_text(encoding="utf8"))
        FakeTrainer().produce(
            workspace, self.route, None, None, NotCancelled(), lambda e: None, lambda e: None
        )
        output = workspace / "output"
        Path(raw["events_path"]).write_bytes((output / "worker_events.jsonl").read_bytes())
        Path(raw["result_path"]).write_bytes((output / "worker_result.json").read_bytes())
        for name in (
            "worker_events.jsonl",
            "worker_result.json",
            "worker_receipt.json",
            "scene.json" if raw["scene"] else "checkpoint.json",
        ):
            (output / name).unlink()
        if self.fault in {"malformed", "sequence", "unexpected", "failure", "partial", "premature"}:
            events = Path(raw["events_path"])
            lines = events.read_bytes().splitlines()
            if self.fault == "malformed":
                lines[3] = b"not JSON"
            elif self.fault == "sequence":
                lines[3] = lines[3].replace(b'"sequence":4', b'"sequence":2')
            elif self.fault == "unexpected":
                lines[3] = lines[3].replace(b"training.progress", b"other.event")
            elif self.fault == "failure":
                row = json.loads(lines[-1])
                row.update(event="worker.failed", failure="gpu_oom", message="test allocation")
                lines[-1] = json.dumps(row).encode()
            elif self.fault == "partial":
                lines[-1] = lines[-1][:20]
            else:
                lines.pop()
            events.write_bytes(b"\n".join(lines) + b"\n")
        if self.fault == "missing_scene":
            (output / "scene.ply").unlink()
        if self.fault == "corrupt_checkpoint":
            (output / "checkpoint/state.pt").write_bytes(b"corrupt")
        result = ProcessResult(
            executable=ExecutableIdentity(
                resolved_path="test.exe",
                size=1,
                last_write_ns=1,
                volume_id="1",
                file_id="1",
                change_time_ns=1,
                sha256="a" * 64,
            ),
            argv=request.argv,
            working_directory=str(workspace),
            exit_code=0,
            elapsed_seconds=1,
            stdout=b"",
            stderr=b"",
            stdout_truncated=False,
            stderr_truncated=False,
            timed_out=False,
            cancelled=False,
            teardown_confirmed=True,
            forced_tree_termination=False,
        )
        return (
            result.model_copy(update={self.fault: True})
            if self.fault in {"stdout_truncated", "stderr_truncated", "timed_out"}
            else result.model_copy(update={"stdout": b"unexpected native stdout"})
            if self.fault == "stdout"
            else result
        )


class Backend(GsplatTrainingBackend):
    def capability(self, runtime, ordinal=0, **kwargs):
        return backend_identity()


@pytest.mark.parametrize(
    "fault",
    [
        "malformed",
        "sequence",
        "unexpected",
        "failure",
        "partial",
        "premature",
        "stdout_truncated",
        "stderr_truncated",
        "timed_out",
        "stdout",
        "missing_scene",
    ],
)
def test_transport_failures(tmp_path, fault):
    selected = route(scene=fault == "missing_scene")
    worker = Backend(Transport(selected, fault))
    with pytest.raises((ValueError, OSError)):
        worker.produce(
            tmp_path,
            selected,
            tmp_path,
            tmp_path if selected.resume else None,
            NotCancelled(),
            lambda e: None,
            lambda e: None,
        )


def test_native_checkpoint_hash_checked_independently(tmp_path):
    selected = route()
    Backend(Transport(selected, "corrupt_checkpoint")).produce(
        tmp_path, selected, tmp_path, None, NotCancelled(), lambda e: None, lambda e: None
    )
    with pytest.raises(ValueError, match="corrupt_checkpoint"):
        read_training_output(tmp_path / "output", CHECKPOINT_TYPE)


def test_stale_backend_never_launches(tmp_path):
    selected = route()
    transport = Transport(selected)

    class Stale(Backend):
        def capability(self, *args, **kwargs):
            return backend_identity().model_copy(update={"packages_digest": "e" * 64})

    with pytest.raises(ValueError, match="stale_backend"):
        Stale(transport).produce(
            tmp_path, selected, tmp_path, None, NotCancelled(), lambda e: None, lambda e: None
        )
    assert not transport.requests


def test_teardown_unconfirmed_is_distinct():
    class Result:
        teardown_confirmed = False

    with pytest.raises(FeatureTeardownError):
        GsplatTrainingBackend._teardown(Result())


def test_cancel_before_worker_launch(tmp_path):
    from splatforge.application.features_contracts import FeatureCancelledError

    class Cancelled:
        def is_cancelled(self):
            return True

    selected = route()
    transport = Transport(selected)
    with pytest.raises(FeatureCancelledError, match="before_worker"):
        Backend(transport).produce(
            tmp_path, selected, tmp_path, None, Cancelled(), lambda e: None, lambda e: None
        )
    assert not transport.requests
