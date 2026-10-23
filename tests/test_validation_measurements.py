"""Exact universe/coverage, normalized geometry, cameras and sparse measurements."""

import math
from uuid import UUID

import pytest
from validation_helpers import measured, scene

from splatforge.core.reconstruction_validation import (
    MeasurementSettings,
    MetricValue,
    ReconstructionMetrics,
    ValidationUniverse,
)
from splatforge.core.validation_measurements import (
    Distribution,
    geometry_identity,
    measure_reconstruction,
    project,
)
from splatforge.core.validation_policy import (
    ReconstructionValidationPolicy,
    RequiredMetric,
    evaluate_policy,
)


@pytest.mark.parametrize(
    "value",
    [
        {"availability": "unavailable", "value": 0},
        {"availability": "exact", "value": None},
        {"availability": "exact", "value": float("nan")},
        {"availability": "sampled", "value": 1},
    ],
)
def test_metric_availability_cannot_disguise_unknown(value):
    with pytest.raises(ValueError):
        MetricValue(**value)


def test_exact_historical_selected_universe_and_source_group_denominators():
    assignments = [(1, 10), (1, 10), (3, 10), (3, 10), (2, 20), (2, 20), (4, 20), (4, 20)]
    reconstruction, universe, _source, metrics = measured(assignments, [[0, 1, 4], [2, 5, 6]])
    assert metrics.registration.input_views == 8
    assert metrics.registration.registered_views == 6
    assert metrics.registration.ratio == 0.75
    assert metrics.unregistered_count == 2
    assert [g.overall.input_views for g in metrics.source_groups] == [4, 4]
    assert [g.overall.registered_views for g in metrics.source_groups] == [3, 3]
    assert [s.overall.input_views for s in metrics.sources] == [2] * 4
    a = next(c for c in reconstruction.components if UUID(int=1) in c.registered_view_ids)
    drone, phone = metrics.source_groups
    assert (
        next(c.coverage.ratio for c in drone.components if c.component_id == a.component_id) == 0.5
    )
    assert (
        next(c.coverage.ratio for c in phone.components if c.component_id == a.component_id) == 0.25
    )
    altered = ValidationUniverse(views=universe.views[:-1])
    with pytest.raises(ValueError, match="input_mismatch"):
        altered.require_reconstruction(reconstruction)
    with pytest.raises(ValueError, match="canonical"):
        ValidationUniverse(views=tuple(reversed(universe.views)))
    bad = metrics.model_dump()
    bad["registration"]["ratio"] = 1
    with pytest.raises(ValueError, match="Coverage"):
        ReconstructionMetrics.model_validate(bad)


def test_group_fully_missing_and_split_and_fragmentation_are_factual():
    _r, _u, _s, metrics = measured([(1, 10)] * 3 + [(2, 20)] * 6, [[0, 1, 2], [3, 4, 5]])
    assert metrics.component_sizes == (3, 3)
    assert metrics.largest_component.ratio == 1 / 3
    assert metrics.second_largest_component.ratio == 1 / 3
    assert metrics.registered_outside_largest_fraction == 0.5
    phone = metrics.source_groups[1]
    assert sorted(c.coverage.ratio for c in phone.components) == [0, 0.5]
    assert phone.overall.ratio == 0.5


@pytest.mark.parametrize(
    "model", ["SIMPLE_PINHOLE", "PINHOLE", "SIMPLE_RADIAL", "RADIAL", "OPENCV", "FULL_OPENCV"]
)
def test_positive_projection_models_and_analytical_pixel_errors(model):
    _r, _u, _s, metrics = measured(model=model, errors=(0, 3, 4))
    c = metrics.components[0]
    assert c.metric("point.count").value == 3
    assert c.metric("track.observation_count").value == 9
    assert c.metric("reprojection.mean").value == pytest.approx(7 / 3)
    assert c.metric("reprojection.rms").value == pytest.approx(math.sqrt(25 / 3))
    assert c.metric("reprojection.median").value == pytest.approx(3)
    assert c.metric("reprojection.p95").value == pytest.approx(4)
    assert c.metric("reprojection.p95").availability == "exact"


@pytest.mark.parametrize(
    "model,params,expected",
    [
        ("SIMPLE_RADIAL", (100, 50, 40, 0.1), (60.02, 50.02)),
        ("RADIAL", (100, 50, 40, 0.1, 0.2), (60.0208, 50.0208)),
        ("OPENCV", (100, 100, 50, 40, 0.1, 0.2, 0.01, 0.02), (60.1208, 50.1008)),
    ],
)
def test_nonzero_distortion_equations(model, params, expected):
    _r, _u, source = scene(model=model, parameters=params)
    camera = next(iter(source.data.values())).cameras[0]
    assert project(camera, (1, 1, 10)) == pytest.approx(expected)


def test_full_opencv_rational_projection_and_undefined_denominator():
    _r, _u, source = scene(
        model="FULL_OPENCV", parameters=(100, 100, 50, 40, 0, 0, 0, 0, 1, 1, 0, 0)
    )
    camera = next(iter(source.data.values())).cameras[0]
    ratio = (1 + 0.02**3) / 1.02
    assert project(camera, (1, 1, 10)) == pytest.approx((50 + 10 * ratio, 40 + 10 * ratio))
    bad = camera.model_copy(update={"parameters": (100, 100, 50, 40, 0, 0, 0, 0, 0, -1, 0, 0)})
    assert project(bad, (1, 0, 1)) is None
    assert project(camera, (0, 0, -1)) is None


def test_exact_track_histogram_integer_quantiles_and_explicit_definitions():
    settings = MeasurementSettings(long_track_min_length=4)
    _r, _u, _s, metrics = measured(
        [(1, 10)] * 5, errors=(0, 0, 0), lengths=(2, 3, 5), settings=settings
    )
    c = metrics.components[0]
    assert [(b.length, b.count) for b in c.track_histogram] == [(2, 1), (3, 1), (5, 1)]
    for name, value in {
        "min": 2,
        "max": 5,
        "mean": 10 / 3,
        "median": 3,
        "p90": 5,
        "two_view_count": 1,
        "two_view_fraction": 1 / 3,
        "long_count": 1,
        "long_fraction": 1 / 3,
    }.items():
        assert c.metric("track." + name).value == value
        assert c.metric("track." + name).availability == "exact"


def test_bounded_reprojection_quantiles_keep_exact_moments_and_order_independent_sample():
    distribution = Distribution(7)
    reverse = Distribution(7)
    for i in range(1000):
        distribution.add(str(i).encode(), float(i))
    for i in reversed(range(1000)):
        reverse.add(str(i).encode(), float(i))
    assert len(distribution.sample) == 7
    assert distribution.values() == reverse.values()
    assert distribution.values()["mean"].availability == "exact"
    assert distribution.values()["p95"].availability == "sampled"
    assert distribution.values()["p95"].sampling.sample_count == 7
    assert distribution.values()["p95"].sampling.population_count == 1000
    _r, _u, _s, m = measured(
        errors=tuple(range(20)), settings=MeasurementSettings(quantile_sample_bound=5)
    )
    assert m.components[0].metric("reprojection.p95").availability == "sampled"


def test_triangulation_healthy_tiny_baseline_and_long_tracks_are_bounded_deterministically():
    healthy = measured()[3].components[0]
    weak = measured(baseline=0.000001)[3].components[0]
    assert healthy.metric("triangulation.median").value > 10
    assert weak.metric("triangulation.median").value < 0.001
    assert weak.metric("triangulation.low_angle_fraction").value == 1
    first = measured([(1, 10)] * 30, settings=MeasurementSettings(triangulation_ray_bound=4))[3]
    second = measured([(1, 10)] * 30, settings=MeasurementSettings(triangulation_ray_bound=4))[3]
    assert first.semantic_digest == second.semantic_digest
    metric = first.components[0].metric("triangulation.median")
    assert metric.availability == "sampled"
    assert metric.sampling.method == "uuid_bounded_rays_v1"
    assert metric.sampling.sample_count == 6
    assert metric.sampling.population_count == 435


def test_cameras_only_points_without_tracks_and_unknown_projection_do_not_fabricate_metrics():
    _r, _u, _s, metrics = measured(points_available=False, tracks_available=False, prior=False)
    c = metrics.components[0]
    assert c.metric("point.count").availability == "unavailable"
    assert c.metric("point.count").value is None
    assert c.metric("reprojection.mean").availability == "unavailable"
    assert c.metric("camera.focal_ratio_min").availability == "exact"
    _r, _u, _s, metrics = measured(tracks_available=False)
    assert metrics.components[0].metric("point.count").value == 1
    assert metrics.components[0].metric("track.mean").availability == "unavailable"
    # Future reader can use an uninterpreted camera while registration still works.
    from splatforge.core.validation_measurements import camera_measurements

    _r, universe, source = scene()
    data = next(iter(source.data.values()))
    unknown = data.model_copy(
        update={"cameras": tuple(c.model_copy(update={"model": "FUTURE"}) for c in data.cameras)}
    )
    result = camera_measurements(unknown, universe)
    assert result["camera.distortion_abs_max"].availability == "unavailable"
    assert project(unknown.cameras[0], (0, 0, 10)) is None


@pytest.mark.parametrize(
    "params,metric",
    [
        ((2000, 2000, 50, 40), "camera.focal_ratio_max"),
        ((100, 100, 250, 40), "camera.principal_offset_max"),
    ],
)
def test_camera_plausibility_policy_is_explicit_and_model_aware(params, metric):
    m = measured(parameters=params)[3]
    report = evaluate_policy(m, ReconstructionValidationPolicy())
    assert any(i.metric == metric and i.severity == "warning" for i in report.issues)
    assert report.status == "warn"
    assert not any(i.severity == "failure" for i in report.issues)


def test_distortion_focal_change_and_camera_sharing_evidence():
    reconstruction, universe, source = scene(model="SIMPLE_RADIAL", parameters=(100, 50, 40, 2))
    key = reconstruction.components[0].component_id
    data = source.data[key]
    source.data[key] = data.model_copy(
        update={
            "priors": tuple(
                p.model_copy(update={"parameters": (50, 50, 40, 0)}) for p in data.priors
            )
        }
    )
    geometry = geometry_identity(reconstruction, source)
    m = measure_reconstruction(reconstruction, universe, geometry, source, MeasurementSettings())
    assert m.components[0].metric("camera.focal_change_max").value == 1
    assert m.components[0].metric("camera.distortion_abs_max").value == 2
    assert m.components[0].metric("camera.sharing_mismatch_count").value == 0
    altered = ValidationUniverse(
        views=tuple(v.model_copy(update={"camera_group_id": UUID(int=888)}) for v in universe.views)
    )
    m = measure_reconstruction(reconstruction, altered, geometry, source, MeasurementSettings())
    assert m.components[0].metric("camera.sharing_mismatch_count").value == 0
    # Candidate groups express possible sharing; frozen priors declare the actual
    # input partition against which final sharing must be compared.
    source.data[key] = source.data[key].model_copy(
        update={
            "priors": tuple(
                p.model_copy(update={"camera_group_id": UUID(int=888)})
                for p in source.data[key].priors
            )
        }
    )
    geometry = geometry_identity(reconstruction, source)
    m = measure_reconstruction(reconstruction, altered, geometry, source, MeasurementSettings())
    assert m.components[0].metric("camera.sharing_mismatch_count").value == 1


def test_policy_pass_warn_fail_and_explicit_required_unknown():
    m = measured()[3]
    baseline = evaluate_policy(m, ReconstructionValidationPolicy())
    assert baseline.status == "pass" and not baseline.issues
    weak = measured(baseline=0.000001)[3]
    assert evaluate_policy(weak, ReconstructionValidationPolicy()).status == "warn"
    failed = evaluate_policy(
        weak,
        ReconstructionValidationPolicy(policy_id="custom_v1", fail_triangulation_median_below=1),
    )
    assert failed.status == "fail"
    assert len({i.issue_id for i in failed.issues}) == len(failed.issues)
    missing = measured(points_available=False, tracks_available=False)[3]
    optional = evaluate_policy(missing, ReconstructionValidationPolicy())
    assert optional.unknown_metrics and optional.status == "pass"
    assert all(u.evidence.value is None for u in optional.unknown_metrics)
    required = evaluate_policy(
        missing,
        ReconstructionValidationPolicy(
            policy_id="custom_v1",
            required_metrics=(
                RequiredMetric(name="reprojection.p95", unavailable_severity="failure"),
            ),
        ),
    )
    assert required.status == "fail"
    assert any(i.code == "required.reprojection.p95" for i in required.issues)
    with pytest.raises(ValueError, match="custom_v1"):
        ReconstructionValidationPolicy(warn_registration_below=0.8)


def test_geometry_and_measurement_identities_include_points_tracks_cameras_and_universe():
    reconstruction, universe, source, metrics = measured(errors=(0, 2))
    key = reconstruction.components[0].component_id
    original = geometry_identity(reconstruction, source)
    source.records[key][0] = source.records[key][0].model_copy(update={"xyz": (0, 0, 11)})
    changed = geometry_identity(reconstruction, source)
    assert original.semantic_digest != changed.semantic_digest
    assert reconstruction.semantic_digest == metrics.reconstruction_digest
    with pytest.raises(ValueError, match="changed during measurement"):
        measure_reconstruction(reconstruction, universe, original, source, MeasurementSettings())
    record = source.records[key][0]
    source.records[key][0] = record.model_copy(update={"observations": record.observations[:2]})
    assert geometry_identity(reconstruction, source).semantic_digest != changed.semantic_digest
    shifted = measured(baseline=2)[3]
    assert shifted.geometry.semantic_digest != metrics.geometry.semantic_digest
    grouped = ValidationUniverse(
        views=tuple(v.model_copy(update={"source_group_id": UUID(int=777)}) for v in universe.views)
    )
    assert grouped.semantic_digest != universe.semantic_digest
    new = measure_reconstruction(
        reconstruction,
        grouped,
        geometry_identity(reconstruction, source),
        source,
        MeasurementSettings(),
    )
    assert new.semantic_digest != metrics.semantic_digest
    other = measured(errors=(0, 2), settings=MeasurementSettings(quantile_sample_bound=3))[3]
    assert other.recipe_key != metrics.recipe_key


def test_report_wording_is_not_numerical_evidence_and_issue_ids_bind_exact_report():
    from splatforge.core.validation_policy import report_digest

    metrics = measured(baseline=0.00001)[3]
    report = evaluate_policy(metrics, ReconstructionValidationPolicy())
    worded = report.model_copy(
        update={
            "issues": tuple(i.model_copy(update={"message": "Inspect."}) for i in report.issues)
        }
    )
    assert report_digest(worded) == report.semantic_digest
    changed = evaluate_policy(
        metrics,
        ReconstructionValidationPolicy(policy_id="custom_v1", warn_triangulation_median_below=2),
    )
    assert changed.semantic_digest != report.semantic_digest
    assert {i.issue_id for i in changed.issues}.isdisjoint(i.issue_id for i in report.issues)


def test_future_unknown_projection_keeps_coverage_and_exposes_partial_measurement_evidence():
    from mapping_helpers import mapping_for
    from test_reconstruction_identity import make_set

    from splatforge.core.reconstruction import component_semantic_digest
    from splatforge.core.reconstruction_validation import ValidationComponentInput

    r, universe, source = scene()
    component = r.components[0]
    data = source.data[component.component_id]
    cameras = tuple(
        c.model_copy(update={"model": "FUTURE"}) if i == 0 else c
        for i, c in enumerate(data.cameras)
    )
    source.data[component.component_id] = ValidationComponentInput.model_validate(
        {**data.model_dump(), "cameras": [c.model_dump() for c in cameras]}
    )
    component = component.model_copy(
        update={"semantic_digest": component_semantic_digest(cameras, data.views, point_count=1)}
    )
    reconstruction = make_set(mapping_for(r.input_view_ids), (component,))
    geometry = geometry_identity(reconstruction, source)
    metrics = measure_reconstruction(
        reconstruction, universe, geometry, source, MeasurementSettings()
    )
    c = metrics.components[0]
    assert metrics.registration.ratio == 1
    assert c.metric("reprojection.p95").availability == "unavailable"
    assert c.metric("reprojection.p95").reason == "partial_projection_support"
    assert c.metric("reprojection_supported.mean").value == 0
    assert c.metric("reprojection.supported_observation_count").value == 2


def test_combined_triangulation_quantile_and_ray_sampling_records_both_methods():
    _r, _u, _s, metrics = measured(
        [(i * 2 + 1, 10) for i in range(20)],
        errors=(0,) * 12,
        settings=MeasurementSettings(quantile_sample_bound=3, triangulation_ray_bound=4),
    )
    evidence = metrics.components[0].metric("triangulation.p95")
    assert evidence.availability == "sampled"
    assert evidence.sampling.method == "sha256_bottom_k_v1"
    assert evidence.sampling.sample_count == 3 and evidence.sampling.population_count == 12
    assert evidence.sampling.upstream.method == "uuid_bounded_rays_v1"


def test_camera_groups_can_vary_within_one_frozen_source():
    reconstruction, universe, source = scene([(1, 10)] * 3)
    changed = ValidationUniverse(
        views=tuple(
            v.model_copy(update={"camera_group_id": UUID(int=900 + i)})
            for i, v in enumerate(universe.views)
        )
    )
    geometry = geometry_identity(reconstruction, source)
    metrics = measure_reconstruction(
        reconstruction, changed, geometry, source, MeasurementSettings()
    )
    assert metrics.components[0].camera_group_count == 3
    assert metrics.registration.registered_views == 3


def test_report_cannot_claim_pass_while_structured_failure_evidence_remains():
    from splatforge.core.validation_policy import (
        ReconstructionValidationReport,
        ValidationStatus,
        report_digest,
    )

    metrics = measured()[3]
    report = evaluate_policy(
        metrics, ReconstructionValidationPolicy(policy_id="custom_v1", minimum_viable_cameras=4)
    )
    incorrect = report.model_copy(update={"status": ValidationStatus.PASS})
    with pytest.raises(ValueError, match="status/scope"):
        ReconstructionValidationReport.model_validate(
            {**incorrect.model_dump(), "semantic_digest": report_digest(incorrect)}
        )


def test_many_independent_photo_sources_do_not_rescan_component_membership_per_source():
    r, universe, source = scene(
        [(2 * i + 2, 10) for i in range(400)], points_available=False, tracks_available=False
    )
    geometry = geometry_identity(r, source)
    visits = []

    class CountedViews(tuple):
        def __iter__(self):
            for identity in super().__iter__():
                visits.append(identity)
                yield identity

    component = r.components[0]
    counted = r.model_copy(
        update={
            "components": (
                component.model_copy(
                    update={"registered_view_ids": CountedViews(component.registered_view_ids)}
                ),
            )
        }
    )
    metrics = measure_reconstruction(counted, universe, geometry, source, MeasurementSettings())
    assert len(metrics.sources) == 400 and metrics.registration.registered_views == 400
    assert all(s.overall.registered_views == s.overall.input_views == 1 for s in metrics.sources)
    assert len(visits) <= 10 * 400


@pytest.mark.parametrize("limit", ["components", "coverage_cells"])
def test_metadata_resource_refusal_precedes_geometry_scanning(limit):
    from splatforge.core.reconstruction_validation import ValidationResourceLimits

    reconstruction, universe, _source, metrics = measured(
        [(i * 2 + 1, 10) for i in range(6)], [[0, 1, 2], [3, 4, 5]]
    )

    class NoScan:
        def component(self, _identity):
            raise AssertionError("Metadata resource refusal must precede geometry access")

        def points(self, _identity):
            raise AssertionError("No point stream may be opened")

    limits = (
        ValidationResourceLimits(max_components=1)
        if limit == "components"
        else (ValidationResourceLimits(max_coverage_cells=13))
    )
    with pytest.raises(ValueError, match="validation.resource_limit.*metadata plan"):
        measure_reconstruction(
            reconstruction,
            universe,
            metrics.geometry,
            NoScan(),
            MeasurementSettings(),
            resource_limits=limits,
        )


def test_inactive_metadata_resource_limits_do_not_change_numerical_identity():
    from splatforge.core.reconstruction_validation import ValidationResourceLimits

    reconstruction, universe, source, metrics = measured()
    changed = measure_reconstruction(
        reconstruction,
        universe,
        metrics.geometry,
        source,
        MeasurementSettings(),
        resource_limits=ValidationResourceLimits(max_components=2000, max_coverage_cells=500000),
    )
    assert changed == metrics
    assert (
        changed.recipe_key == metrics.recipe_key
        and changed.semantic_digest == metrics.semantic_digest
    )


def test_component_metadata_is_bounded_during_measurement(monkeypatch):
    reconstruction, universe, source, metrics = measured()
    monkeypatch.setattr("splatforge.core.validation_measurements.MAX_VALIDATION_METADATA_BYTES", 1)
    with pytest.raises(ValueError, match="component metric metadata"):
        measure_reconstruction(
            reconstruction, universe, metrics.geometry, source, MeasurementSettings()
        )
