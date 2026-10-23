"""Explicit sequential comparison evidence, cache/order neutrality and no ranking."""

import pytest
from mapping_helpers import mapping_inputs
from test_incremental_execution import unchanged
from test_matching_execution import hashes

from splatforge.application.features_contracts import FeatureCapabilityError
from splatforge.application.mapping import MappingService
from splatforge.application.mapping_comparison import MappingComparisonService
from splatforge.core.mapping_comparison import (
    MappingComparisonPlan,
    MappingComparisonReport,
    MappingComparisonRoute,
)
from splatforge.core.reconstruction import (
    GlobalMapperSettings,
    HierarchicalMapperSettings,
    IncrementalMapperSettings,
)


def test_explicit_sequential_same_m7_cache_and_order_do_not_change_reconstruction(tmp_path):
    value, fixture, _, _, verified = mapping_inputs(tmp_path)
    before = hashes(value.root)
    service = MappingService(value.execution, fixture.mapping_adapter())
    routes = tuple(
        MappingComparisonRoute(label=label, settings=settings)
        for label, settings in (
            ("Global CPU", GlobalMapperSettings()),
            ("Incremental Ceres", IncrementalMapperSettings()),
            ("Hierarchical", HierarchicalMapperSettings()),
        )
    )
    comparison = MappingComparisonService(service)
    report = comparison.compare(
        value.root,
        verification_run_id=verified.run_id,
        plan=MappingComparisonPlan(routes=routes, data_kind="synthetic_transport"),
        colmap=fixture.exe,
    )
    assert all(e.status == "succeeded" and not e.cache_hit for e in report.routes)
    assert len({e.mapping_input_digest for e in report.routes}) == 1
    assert len({e.recipe_key for e in report.routes}) == 3
    assert len({e.semantic_digest for e in report.routes}) == 1
    assert all(e.registration_coverage == 1 and e.native_point_count == 0 for e in report.routes)
    assert all(e.backend and e.native_seconds is not None and e.artifact for e in report.routes)
    assert all(e.estimated_workspace_bytes > 0 for e in report.routes)
    assert report.recommendation == "pending_representative_benchmarks_and_m9"
    assert (
        "quality_score" not in report.model_dump_json()
        and '"winner"' not in report.model_dump_json()
    )
    assert MappingComparisonReport.model_validate_json(report.model_dump_json()) == report
    fixture.requests.clear()
    repeated = comparison.compare(
        value.root,
        verification_run_id=verified.run_id,
        plan=MappingComparisonPlan(routes=tuple(reversed(routes))),
        colmap=fixture.exe,
    )
    assert all(e.cache_hit for e in repeated.routes)
    assert {e.label: e.semantic_digest for e in repeated.routes} == {
        e.label: e.semantic_digest for e in report.routes
    }
    assert not any(
        r.argv[0]
        in {
            "feature_extractor",
            "matches_importer",
            "geometric_verifier",
            "global_mapper",
            "mapper",
            "hierarchical_mapper",
        }
        and len(r.argv) > 2 and r.working_directory.is_relative_to(value.root)
        for r in fixture.requests
    )
    unchanged(before)


def test_unavailable_failed_routes_recorded_without_substitution(tmp_path, monkeypatch):
    value, fixture, _, _, verified = mapping_inputs(tmp_path)
    adapter = fixture.mapping_adapter()
    original = adapter.prepare

    def prepare(policy, *, settings, **kwargs):
        if settings.method_id == "mapping.colmap_hierarchical":
            raise FeatureCapabilityError("hierarchical_mapper unavailable")
        return original(policy, settings=settings, **kwargs)

    monkeypatch.setattr(adapter, "prepare", prepare)
    fixture.mapping_mode = "failed"
    report = MappingComparisonService(MappingService(value.execution, adapter)).compare(
        value.root,
        verification_run_id=verified.run_id,
        colmap=fixture.exe,
        plan=MappingComparisonPlan(
            routes=(
                MappingComparisonRoute(label="unavailable", settings=HierarchicalMapperSettings()),
                MappingComparisonRoute(label="failed", settings=GlobalMapperSettings()),
            )
        ),
    )
    assert [e.status for e in report.routes] == ["unavailable", "failed"]
    assert report.routes[0].run_id is None
    assert report.routes[1].run_id and report.routes[1].recipe_key and report.routes[1].backend
    assert report.routes[1].failure_category
    launched = [
        r.argv[0]
        for r in fixture.requests
        if r.argv[0] in {"hierarchical_mapper", "global_mapper", "mapper"} and len(r.argv) > 2
    ]
    assert launched == ["global_mapper"]


def test_comparison_cancellation_stops_later_explicit_runs(tmp_path):
    value, fixture, _, _, verified = mapping_inputs(tmp_path)
    fixture.mapping_mode = "cancelled"
    fixture.on_map = lambda owner: value.execution.request_cancellation(
        value.root, run_id=owner.run
    )
    report = MappingComparisonService(
        MappingService(value.execution, fixture.mapping_adapter())
    ).compare(
        value.root,
        verification_run_id=verified.run_id,
        colmap=fixture.exe,
        plan=MappingComparisonPlan(
            routes=(
                MappingComparisonRoute(label="cancel"),
                MappingComparisonRoute(label="later", settings=HierarchicalMapperSettings()),
            )
        ),
    )
    assert [e.status for e in report.routes] == ["cancelled", "skipped"]
    assert not any(r.argv[0] == "hierarchical_mapper" and len(r.argv) > 2 for r in fixture.requests)


def test_comparison_plan_bounded_and_policies_resolved():
    with pytest.raises(ValueError):
        MappingComparisonPlan(routes=())
    with pytest.raises(ValueError):
        MappingComparisonPlan(routes=(MappingComparisonRoute(label="a"),) * 17)
    with pytest.raises(ValueError, match="unique"):
        MappingComparisonPlan(routes=(MappingComparisonRoute(label="a"),) * 2)
    explicit = MappingComparisonRoute(label="calibration", calibration_policy="view_graph")
    assert explicit.calibration_settings is not None
    with pytest.raises(ValueError, match="Only Global"):
        MappingComparisonRoute(
            label="invalid", settings=IncrementalMapperSettings(), calibration_policy="view_graph"
        )
