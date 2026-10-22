"""Keep every default/integration test's performance telemetry in temporary storage."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolated_performance_history(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "splatforge.bootstrap.default_performance_path",
        lambda: tmp_path / "worker-local" / "performance.sqlite",
    )
