"""gsplat worker transport; this module never imports Torch or gsplat."""

from __future__ import annotations

import json
import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path

from splatforge.adapters.artifact_validation import _read_bounded, stream_sha256
from splatforge.adapters.gaussian_ply import read_gaussian_ply
from splatforge.adapters.process_diagnostics import invocation_evidence
from splatforge.adapters.process_runner import (
    LocalProcessRunner,
    ProcessCleanupError,
    ProcessRequest,
)
from splatforge.application.features_contracts import (
    FeatureCancellation,
    FeatureCancelledError,
    FeatureCapabilityError,
    FeatureTeardownError,
)
from splatforge.core.execution import TrainingJobRoute, TrainingRuntime
from splatforge.core.process import ProcessInvocationEvidence, ProcessResult
from splatforge.core.training import (
    GaussianScene,
    TrainingBackendIdentity,
    TrainingCheckpoint,
    required_training_features,
)
from splatforge.core.training_protocol import WorkerEvent, WorkerFailure, WorkerProtocol
from splatforge.core.views import canonical_json_bytes

WORKER = Path(__file__).resolve().parents[1] / "../splatforge_gsplat_worker/__main__.py"


class GsplatTrainingBackend:
    def __init__(self, runner: LocalProcessRunner | None = None) -> None:
        self.runner = runner or LocalProcessRunner()
        self._unresolved_probe: Path | None = None

    def capability(
        self,
        runtime: TrainingRuntime,
        ordinal: int = 0,
        *,
        cancellation: FeatureCancellation | None = None,
    ) -> TrainingBackendIdentity:
        if self._unresolved_probe:
            raise FeatureTeardownError(f"training.probe_quarantined: {self._unresolved_probe}")
        directory = Path(tempfile.mkdtemp(prefix="splatforge-gsplat-probe-")).resolve()
        cleanup = True
        try:
            request_path, result_path = directory / "request.json", directory / "result.json"
            request_path.write_bytes(
                canonical_json_bytes(
                    {"operation": "probe", "gpu_ordinal": ordinal, "result_path": str(result_path)}
                )
            )
            request = ProcessRequest(
                runtime.python,
                ("-I", str(WORKER.resolve()), str(request_path)),
                directory,
                runtime.environment,
                1800,
            )
            try:
                result = self.runner.run(request, cancellation=cancellation)
            except ProcessCleanupError as exc:
                if not exc.teardown_confirmed:
                    cleanup, self._unresolved_probe = False, directory
                    raise FeatureTeardownError(f"{exc}; retained {directory}") from exc
                raise
            if not result.teardown_confirmed:
                cleanup, self._unresolved_probe = False, directory
            self._teardown(result)
            if result.cancelled:
                raise FeatureCancelledError("training.capability_cancelled")
            if (
                result.exit_code != 0
                or result.timed_out
                or result.stdout
                or (result.stdout_truncated or result.stderr_truncated)
            ):
                raise FeatureCapabilityError(
                    "training.runtime_unavailable: " + result.stderr_text()[-2048:]
                )
            return TrainingBackendIdentity.model_validate_json(
                _read_bounded(result_path, 65536, "Trainer capability")
            )
        finally:
            if cleanup:
                if (
                    directory.parent != Path(tempfile.gettempdir()).resolve()
                    or not directory.name.startswith("splatforge-gsplat-probe-")
                    or directory.is_symlink()
                    or directory.is_junction()
                ):
                    raise ValueError("training.unsafe_probe_cleanup")
                shutil.rmtree(directory)

    @staticmethod
    def _teardown(result: ProcessResult) -> None:
        if not result.teardown_confirmed:
            raise FeatureTeardownError("training.teardown_unconfirmed")

    def produce(
        self,
        workspace: Path,
        route: TrainingJobRoute,
        dataset: Path,
        resume: Path | None,
        cancellation: FeatureCancellation,
        events: Callable[[WorkerEvent], None],
        evidence: Callable[[ProcessInvocationEvidence], None],
    ) -> GaussianScene | TrainingCheckpoint:
        # Reprobe exact runtime before each native segment; stale runtime cannot resume.
        if cancellation.is_cancelled():
            raise FeatureCancelledError("training.cancelled_before_worker")
        actual = self.capability(
            route.runtime, route.backend.gpu_ordinal, cancellation=cancellation
        )
        if actual != route.backend:
            raise FeatureCapabilityError("training.stale_backend: create a new explicit plan")
        if not required_training_features(route.settings) <= set(actual.features):
            raise FeatureCapabilityError("training.requested_feature_combination_unavailable")
        scene = route.node_id == "gaussian_scene"
        events_path, result_path = workspace / "events.jsonl", workspace / "result.json"
        config = {
            "operation": "train",
            "settings": route.settings.model_dump(mode="json"),
            "backend": route.backend.model_dump(mode="json"),
            "limits": route.resource_limits.model_dump(),
            "dataset_path": str(dataset),
            "dataset_digest": route.dataset.semantic_digest,
            "training_recipe": route.training_recipe,
            "output_path": str(workspace / "output"),
            "events_path": str(events_path),
            "result_path": str(result_path),
            "scene": scene,
            "start_step": route.start_step,
            "terminal_step": route.terminal_step,
            "resume_path": str(resume / "checkpoint/state.pt") if resume else None,
            "resume_digest": route.resume.semantic_digest if route.resume else None,
            "checkpoint_lineage": [route.resume.semantic_digest] if route.resume else [],
            "source_groups": route.source_groups,
        }
        config_path = workspace / "request.json"
        config_path.write_bytes(canonical_json_bytes(config))
        parser = WorkerProtocol(
            total_steps=route.settings.max_steps,
            start_step=route.start_step,
            terminal_step=route.terminal_step,
            scene=scene,
        )
        position, pending, failure = 0, b"", None

        class Control:
            def is_cancelled(inner):
                nonlocal position, pending, failure
                try:
                    if events_path.exists():
                        if events_path.stat().st_size > route.resource_limits.max_log_bytes:
                            raise ValueError("training.protocol: maximum event log bytes")
                        with events_path.open("rb") as stream:
                            stream.seek(position)
                            block = stream.read(route.resource_limits.max_log_bytes + 1)
                        position += len(block)
                        pending += block
                        while b"\n" in pending:
                            line, pending = pending.split(b"\n", 1)
                            try:
                                record = parser.accept(line)
                            except WorkerFailure as exc:
                                events(exc.event)
                                raise
                            events(record)
                        if len(pending) > 8192:
                            raise ValueError("training.protocol: excessive partial event")
                except Exception as exc:
                    failure = exc
                return failure is not None or cancellation.is_cancelled()

        control = Control()
        request = ProcessRequest(
            route.runtime.python,
            ("-I", str(WORKER.resolve()), str(config_path)),
            workspace,
            route.runtime.environment,
            route.resource_limits.timeout_seconds,
            max_stdout_bytes=route.resource_limits.max_log_bytes,
            max_stderr_bytes=route.resource_limits.max_log_bytes,
        )
        try:
            result = self.runner.run(request, cancellation=control)
        except ProcessCleanupError as exc:
            if not exc.teardown_confirmed:
                raise FeatureTeardownError(str(exc)) from exc
            raise
        record = invocation_evidence(
            request,
            executable=result.executable,
            diagnostic_argv=request.argv,
            tool_role="gsplat.training",
            source_id=None,
            elapsed_seconds=result.elapsed_seconds,
            result=result,
        )
        # Preserve full captured stream identities/counts while retaining readable tails.
        tails = {}
        for name in ("stdout", "stderr"):
            captured = getattr(result, name)
            tail = (
                captured[-16384:]
                .decode("utf-8", "replace")
                .encode("utf-8")[-16384:]
                .decode("utf-8", "ignore")
            )
            while len(json.dumps(tail).encode()) > 32768:
                tail = tail[len(tail) // 2 :]
            tails[name + "_excerpt"] = tail
            tails[name + "_excerpt_truncated"] = len(captured) > len(tail.encode())
        evidence(ProcessInvocationEvidence.model_validate({**record.model_dump(), **tails}))
        self._teardown(result)
        control.is_cancelled()
        if failure:
            raise failure
        if result.cancelled or cancellation.is_cancelled():
            raise FeatureCancelledError("training.cancelled")
        if (
            result.exit_code != 0
            or result.timed_out
            or result.forced_tree_termination
            or result.stdout
            or result.stdout_truncated
            or result.stderr_truncated
        ):
            raise ValueError(
                "training.worker_process_failed_or_excessive_output: "
                + result.stderr_text()[-2048:]
            )
        if pending:
            raise ValueError("training.protocol: partial final JSONL event")
        parser.finish()
        if parser.last.identity != stream_sha256(result_path)[1]:
            raise ValueError("training.protocol: result digest mismatch")
        raw = json.loads(_read_bounded(result_path, 4 * 1024**2, "Worker result"))
        output = workspace / "output"
        if scene:

            def checkpoint():
                if cancellation.is_cancelled():
                    raise FeatureCancelledError("training.cancelled_during_scene_validation")

            ply = read_gaussian_ply(
                output / "scene.ply",
                max_bytes=route.resource_limits.max_scene_bytes,
                max_gaussians=route.resource_limits.max_gaussians,
                checkpoint=checkpoint,
            )
            payload = GaussianScene.model_validate(
                {**raw, "numerical_content_digest": ply.numerical_digest}
            )
            metadata = "scene.json"
        else:
            payload, metadata = TrainingCheckpoint.model_validate(raw), "checkpoint.json"
        (output / metadata).write_bytes(canonical_json_bytes(payload.metadata()))
        shutil.copyfile(result_path, output / "worker_result.json")
        shutil.copyfile(events_path, output / "worker_events.jsonl")
        (output / "worker_receipt.json").write_bytes(
            canonical_json_bytes(
                {"start_step": route.start_step, "stdout_empty": True, "teardown_confirmed": True}
            )
        )
        return payload
