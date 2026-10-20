"""Deterministic cooperative filesystem fakes for the two-node route."""

from __future__ import annotations

import os
from pathlib import Path

from splatforge.application.execution import ExecutionControl
from splatforge.core.execution import ScaleSettings, SequenceSettings
from splatforge.core.fake_pipeline import (
    NumbersPayload,
    ScaledNumbersPayload,
    canonical_json_bytes,
)


class LocalFakeStages:
    def execute_sequence(
        self,
        workspace: Path,
        *,
        start: int,
        settings: SequenceSettings,
        control: ExecutionControl,
    ) -> None:
        control.checkpoint()
        payload = NumbersPayload(numbers=tuple(range(start, start + settings.count)))
        self._write_payload(workspace, "numbers.json", payload.model_dump(mode="json"))
        control.checkpoint()

    def execute_scale(
        self,
        workspace: Path,
        *,
        input_payload: NumbersPayload,
        settings: ScaleSettings,
        control: ExecutionControl,
    ) -> None:
        control.checkpoint()
        payload = ScaledNumbersPayload(
            numbers=tuple(number * settings.factor for number in input_payload.numbers)
        )
        self._write_payload(workspace, "scaled.json", payload.model_dump(mode="json"))
        control.checkpoint()

    @staticmethod
    def _write_payload(workspace: Path, name: str, value: object) -> None:
        output = workspace / "output"
        output.mkdir()
        payload = canonical_json_bytes(value) + b"\n"
        with (output / name).open("xb") as stream:
            if stream.write(payload) != len(payload):
                raise OSError("Could not write complete fake-stage payload")
            stream.flush()
            os.fsync(stream.fileno())
