"""Deterministic filesystem fakes for the M1b1 two-node route."""

from __future__ import annotations

import os
from pathlib import Path

from splatforge.core.execution import ScaleSettings, SequenceSettings
from splatforge.core.fake_pipeline import (
    NumbersPayload,
    ScaledNumbersPayload,
    canonical_json_bytes,
)


class LocalFakeStages:
    def execute_sequence(
        self, workspace: Path, *, start: int, settings: SequenceSettings
    ) -> None:
        payload = NumbersPayload(numbers=tuple(range(start, start + settings.count)))
        self._write_payload(workspace, "numbers.json", payload.model_dump(mode="json"))

    def execute_scale(
        self,
        workspace: Path,
        *,
        input_payload: NumbersPayload,
        settings: ScaleSettings,
    ) -> None:
        payload = ScaledNumbersPayload(
            numbers=tuple(number * settings.factor for number in input_payload.numbers)
        )
        self._write_payload(workspace, "scaled.json", payload.model_dump(mode="json"))

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
