"""Large sparse scans must not walk every image on each validation checkpoint."""

from types import SimpleNamespace

import pytest

from splatforge.adapters import colmap_dataset
from splatforge.application.features_contracts import (
    FeatureCancelledError,
    FeatureResourceError,
    FeatureTimeoutError,
)
from splatforge.core.dataset import DatasetResourceLimits


def guard_fixture(tmp_path, monkeypatch):
    clock = SimpleNamespace(now=0.0)
    control = SimpleNamespace(cancelled=False, calls=0)
    measured = SimpleNamespace(bytes=0, free=1000, walks=0)

    def cancelled():
        control.calls += 1
        return control.cancelled

    def walk(path):
        assert path == tmp_path
        measured.walks += 1
        return measured.bytes

    control.is_cancelled = cancelled
    monkeypatch.setattr(colmap_dataset, "workspace_bytes", walk)
    monkeypatch.setattr(
        colmap_dataset.shutil, "disk_usage", lambda _path: SimpleNamespace(free=measured.free)
    )
    guard = colmap_dataset._PreparationGuard(
        tmp_path,
        DatasetResourceLimits(max_workspace_bytes=100, minimum_free_bytes=10, timeout_seconds=1),
        control,
        clock=lambda: clock.now,
    )
    return guard, clock, control, measured


def test_sparse_checkpoints_keep_cancellation_checks_without_repeated_directory_walks(
    tmp_path, monkeypatch,
):
    guard, clock, control, measured = guard_fixture(tmp_path, monkeypatch)
    for _ in range(10000):
        guard()
    assert control.calls == 10000
    assert measured.walks == 1
    clock.now = 0.25
    guard()
    assert measured.walks == 2
    guard(force_resources=True)
    assert measured.walks == 3


def test_cancellation_is_immediate_inside_filesystem_poll_interval(tmp_path, monkeypatch):
    guard, _clock, control, measured = guard_fixture(tmp_path, monkeypatch)
    guard()
    control.cancelled = True
    with pytest.raises(FeatureCancelledError):
        guard()
    assert measured.walks == 1


def test_timeout_does_not_wait_for_filesystem_poll(tmp_path, monkeypatch):
    guard, clock, _control, measured = guard_fixture(tmp_path, monkeypatch)
    guard()
    clock.now = 1.001
    with pytest.raises(FeatureTimeoutError):
        guard()
    assert measured.walks == 1


@pytest.mark.parametrize("problem", ["workspace", "free_disk"])
def test_budget_is_rechecked_at_interval_and_forced_phase_boundary(tmp_path, monkeypatch, problem):
    guard, clock, _control, measured = guard_fixture(tmp_path, monkeypatch)
    guard()
    if problem == "workspace":
        measured.bytes = 101
    else:
        measured.free = 9
    guard()  # Same instant: no repeated filesystem traversal.
    with pytest.raises(FeatureResourceError):
        guard(force_resources=True)
    clock.now = 0.25
    with pytest.raises(FeatureResourceError):
        guard()
