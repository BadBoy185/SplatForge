"""M9 defensible point totals and separate M6.5 live/history evidence."""

from uuid import UUID

from progress_helpers import FakeClock
from validation_helpers import measured

from splatforge.adapters.performance import LocalPerformanceHistory
from splatforge.application.progress import ProgressSupport
from splatforge.application.work_models import validation_progress_plan
from splatforge.core.execution import ArtifactHandle, ReconstructionMeasurementRoute
from splatforge.core.progress import WorkMetric


def handle(kind, identity=1):
    return ArtifactHandle(
        artifact_id=UUID(int=identity),
        artifact_type=kind,
        contract_version=1,
        recipe_key="a" * 64,
        semantic_digest="b" * 64,
        manifest_path="unused",
    )


def test_exact_point_work_live_eta_and_history_do_not_change_measurement_identity(tmp_path):
    reconstruction, universe, _source, metrics = measured(errors=tuple(range(40)))
    h = handle("mapping.reconstruction_set")
    h = h.model_copy(update={"semantic_digest": reconstruction.semantic_digest})
    route = ReconstructionMeasurementRoute(
        reconstruction=h,
        geometry_artifact=handle("validation.geometry_input", 2),
        geometry=metrics.geometry,
        universe=universe,
        settings=metrics.settings,
    )
    clock = FakeClock()
    history = LocalPerformanceHistory(tmp_path / "performance.sqlite")
    support = ProgressSupport(clock=clock, history=history)
    plan = validation_progress_plan(route, support.hardware)
    assert plan.work.unit == "work" and plan.work.total == 40
    assert plan.work.mode == "determinate"
    assert plan.work.work_model_id == "validation.reconstruction_points_v1"
    recipe = route.recipe_key()
    events = []
    session = support.session(UUID(int=3), (plan,), emit=lambda *args: events.append(args))
    session.start(route.node_id, UUID(int=4))
    assert session.snapshot().stages[0].eta.likely_seconds is None
    for count in (10, 20, 30):
        clock.advance(2)
        session.report(
            route.node_id, count, diagnostics=(WorkMetric(name="observations", value=count * 3),)
        )
    assert session.snapshot().stages[0].completed == 30
    assert session.snapshot().stages[0].fraction == 0.75
    assert session.snapshot().stages[0].eta.likely_seconds is not None
    clock.advance(2)
    session.complete(route.node_id)
    assert history.statistics().sample_count == 1
    cached = support.session(UUID(int=5), (plan,), emit=lambda *_args: None)
    cached.cached(route.node_id)
    assert cached.snapshot().stages[0].eta.likely_seconds == 0
    assert history.statistics().sample_count == 1
    assert route.recipe_key() == recipe
