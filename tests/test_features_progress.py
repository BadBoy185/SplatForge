"""M7a observed work, ETA signatures and private-history degradation."""

from uuid import UUID

import pytest
from feature_helpers import NativeFixture
from progress_helpers import FakeClock, sample
from test_features_execution import build
from test_views_execution import harness, prepare

from splatforge.adapters.feature_progress import FeatureProgressReader
from splatforge.adapters.performance import LocalPerformanceHistory
from splatforge.application.eta import HybridThroughputEstimator
from splatforge.application.progress import ProgressSupport
from splatforge.application.work_models import features_progress_plan
from splatforge.core.execution import RunSnapshot
from splatforge.core.features import feature_recipe_key


def test_log_parser_requires_complete_expected_per_image_evidence(tmp_path):
    path = tmp_path / "progress.log"
    seen = []
    ids = frozenset((UUID(int=1), UUID(int=2)))
    reader = FeatureProgressReader(path, ids, "SIFT", 100, seen.append)

    def write(text):
        with path.open("ab") as stream:
            stream.write(text.encode())
        reader.poll()

    write("Processed file [1/2]\n")
    assert not seen
    write(f"  Name: {UUID(int=1)}.png\n  Features: 4 (SIFT)\n")
    assert seen[-1].completed_views == 1 and seen[-1].features == 4
    write(f"Processed file [1/2]\nName: {UUID(int=1)}.png\nFeatures: 4 (SIFT)\n")
    assert len(seen) == 1
    write(f"Processed file [2/3]\nName: {UUID(int=2)}.png\nFeatures: 4 (SIFT)\n")
    write(f"Processed file [2/2]\nName: {UUID(int=2)}.png\nFeatures: 4 (LOMA_B)\n")
    assert len(seen) == 1
    write(f"Processed file [2/2]\nName: {UUID(int=2)}.png\nFeatures: 7 (SIFT)")
    assert len(seen) == 1
    write("\n")
    assert seen[-1].completed_views == 2 and seen[-1].features == 11
    path.write_bytes(bytes(33 * 1024 * 1024))
    with pytest.raises(ValueError, match="bounded"):
        reader.poll()


def test_work_model_cold_historical_live_and_performance_identity(tmp_path):
    value, fixture = harness(tmp_path), NativeFixture(tmp_path)
    views = prepare(value)
    clock = FakeClock()
    history = LocalPerformanceHistory(tmp_path / "private.sqlite")
    support = ProgressSupport(clock=clock, history=history)
    fixture.on_extract = lambda _control: clock.advance(3)
    result = build(value, views, fixture, progress=support)
    route = RunSnapshot.model_validate_json(
        (value.root / "runs" / str(result.run_id) / "run.json").read_bytes()
    ).route
    plan = features_progress_plan(route, support.hardware)
    assert plan.work.work_model_id == "features.selected_views_v1"
    assert plan.work.unit == "views" and plan.work.total == 3
    assert {m.name for m in plan.workload} == {"views", "megapixels"}
    assert plan.signature.backend.executable_sha256 == fixture.identity.sha256
    assert HybridThroughputEstimator(plan).estimate().likely_seconds is None
    samples = tuple(sample(plan, rate=1) for _ in range(3))
    assert HybridThroughputEstimator(plan, samples).estimate().likely_seconds is not None
    assert history.statistics().sample_count == 1
    assert build(value, views, fixture, progress=support).cache_hit
    assert history.statistics().sample_count == 1
    changed = plan.model_copy(
        update={"signature": plan.signature.model_copy(update={"settings_key": "e" * 64})}
    )
    assert changed.signature != plan.signature
    key = feature_recipe_key(
        route.selected.semantic_digest,
        route.settings,
        route.backend.numerical_identity,
        route.backend.model_identities(),
    )
    history.reset()
    assert key == feature_recipe_key(
        route.selected.semantic_digest,
        route.settings,
        route.backend.numerical_identity,
        route.backend.model_identities(),
    )


def test_optional_events_and_history_failures_do_not_affect_features(tmp_path, monkeypatch):
    value, fixture = harness(tmp_path), NativeFixture(tmp_path)
    views = prepare(value)

    class BrokenHistory:
        def read(self, _signature):
            raise OSError("history fixture failure")

        def record(self, _sample):
            raise OSError("history fixture failure")

    def fail(*_args, **_kwargs):
        raise OSError("events fixture failure")

    monkeypatch.setattr(value.execution, "append_event", fail)
    monkeypatch.setattr(value.execution, "append_process_evidence", fail)
    result = build(value, views, fixture, progress=ProgressSupport(history=BrokenHistory()))
    assert result.status == "succeeded"
    assert "history.unavailable" in result.warnings
    assert "progress.append_failed" in result.warnings
    assert "events.append_failed" in result.warnings


@pytest.mark.parametrize("mode", ["failed", "timeout", "cancelled", "unresolved"])
def test_unsuccessful_feature_runs_never_teach_history(tmp_path, mode):
    value, fixture = harness(tmp_path), NativeFixture(tmp_path)
    views = prepare(value)
    clock = FakeClock()
    history = LocalPerformanceHistory(tmp_path / "history.sqlite")

    def run(control):
        clock.advance(3)
        if mode == "cancelled":
            value.execution.request_cancellation(value.root, run_id=control.run)
            control.is_cancelled()

    fixture.on_extract, fixture.mode = run, mode
    if mode == "cancelled":
        assert (
            build(
                value, views, fixture, progress=ProgressSupport(clock=clock, history=history)
            ).status
            == "cancelled"
        )
    else:
        with pytest.raises(ValueError):
            build(value, views, fixture, progress=ProgressSupport(clock=clock, history=history))
    assert history.statistics().sample_count == 0
