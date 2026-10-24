"""Strict JSONL worker protocol v1; native text is never progress evidence."""

from __future__ import annotations

import json
from typing import Literal

from pydantic import AwareDatetime, Field

from splatforge.core.features import Digest
from splatforge.core.training import TrainingBackendIdentity, TrainingLimits, TrainingSettings
from splatforge.core.views import FrozenModel


class WorkerEvent(FrozenModel):
    protocol_version: Literal[1] = 1
    sequence: int = Field(ge=1, strict=True)
    timestamp: AwareDatetime
    event: Literal[
        "worker.started",
        "dataset.loaded",
        "training.started",
        "training.progress",
        "checkpoint.saved",
        "evaluation.completed",
        "scene.exported",
        "worker.completed",
        "worker.failed",
    ]
    step: int = Field(ge=0, strict=True)
    total_steps: int = Field(ge=1, strict=True)
    gaussian_count: int | None = Field(default=None, ge=1, strict=True)
    loss: float | None = Field(default=None, strict=True)
    peak_allocated_cuda_bytes: int | None = Field(default=None, ge=0, strict=True)
    identity: Digest | None = None
    failure: Literal["gpu_oom", "worker_error"] | None = None
    message: str | None = Field(default=None, max_length=2048)


class WorkerProbeRequest(FrozenModel):
    operation: Literal["probe"]
    gpu_ordinal: int = Field(ge=0, le=63, strict=True)
    result_path: str = Field(min_length=1, max_length=4096)


class WorkerTrainingRequest(FrozenModel):
    operation: Literal["train"]
    settings: TrainingSettings
    backend: TrainingBackendIdentity
    limits: TrainingLimits
    dataset_path: str = Field(min_length=1, max_length=4096)
    dataset_digest: Digest
    training_recipe: Digest
    output_path: str = Field(min_length=1, max_length=4096)
    events_path: str = Field(min_length=1, max_length=4096)
    result_path: str = Field(min_length=1, max_length=4096)
    scene: bool = Field(strict=True)
    start_step: int = Field(ge=0, strict=True)
    terminal_step: int = Field(ge=1, strict=True)
    resume_path: str | None = Field(default=None, max_length=4096)
    resume_digest: Digest | None = None
    checkpoint_lineage: tuple[Digest, ...]
    source_groups: dict[str, str] = Field(max_length=100000)


def _unique_object(pairs: list) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("training.protocol: duplicate JSON key")
        result[key] = value
    return result


class WorkerFailure(ValueError):
    def __init__(self, event: WorkerEvent) -> None:
        self.event = event
        super().__init__(f"training.{event.failure}: {event.message}")


class WorkerProtocol:
    def __init__(
        self, *, total_steps: int, start_step: int, terminal_step: int, scene: bool
    ) -> None:
        if (
            any(type(i) is not int for i in (total_steps, start_step, terminal_step))
            or not 0 <= start_step <= terminal_step <= total_steps
            or terminal_step < 1
        ):
            raise ValueError("training.protocol: invalid work bounds")
        self.total_steps, self.step, self.terminal_step = total_steps, start_step, terminal_step
        self.scene = scene
        self.sequence = 0
        self.phase = "initial"
        self.completed = False
        self.saved = False
        self.exported = False
        self.last: WorkerEvent | None = None
        self.payload_identity: str | None = None

    def accept(self, line: bytes) -> WorkerEvent:
        if len(line) > 8192:
            raise ValueError("training.protocol: event exceeds 8 KiB")
        try:
            value = WorkerEvent.model_validate(json.loads(line, object_pairs_hook=_unique_object))
        except ValueError as exc:
            raise ValueError("training.protocol: malformed JSON/event") from exc
        if (
            self.completed
            or value.sequence != self.sequence + 1
            or value.total_steps != self.total_steps
            or not self.step <= value.step <= self.terminal_step
        ):
            raise ValueError("training.protocol: sequence/step/total mismatch")
        event = value.event
        expected = {
            "initial": "worker.started",
            "started": "dataset.loaded",
            "loaded": "training.started",
        }.get(self.phase)
        if event == "worker.failed":
            if not value.failure:
                raise ValueError("training.protocol: missing failure classification")
            raise WorkerFailure(value)
        if expected and event != expected:
            raise ValueError("training.protocol: unexpected event order")
        if expected:
            if value.step != self.step:
                raise ValueError("training.protocol: initial/resumed step changed before training")
            self.phase = {"initial": "started", "started": "loaded", "loaded": "training"}[
                self.phase
            ]
        elif event == "checkpoint.saved" and not self.scene and not self.saved:
            if value.step != self.terminal_step or not value.identity:
                raise ValueError("training.protocol: checkpoint identity/step required")
            self.saved = True
            self.payload_identity = value.identity
        elif event == "scene.exported" and self.scene and not self.exported:
            if value.step != self.terminal_step or not value.identity:
                raise ValueError("training.protocol: scene identity/step required")
            self.exported = True
            self.payload_identity = value.identity
        elif event == "worker.completed":
            if (
                value.step != self.terminal_step
                or not value.identity
                or not (self.exported if self.scene else self.saved)
            ):
                raise ValueError("training.protocol: incomplete result")
            self.completed = True
        elif event not in {"training.progress", "evaluation.completed"}:
            raise ValueError("training.protocol: unexpected event")
        self.sequence, self.step, self.last = value.sequence, value.step, value
        return value

    def finish(self) -> None:
        if not self.completed:
            raise ValueError("training.protocol: premature exit without completed result")
