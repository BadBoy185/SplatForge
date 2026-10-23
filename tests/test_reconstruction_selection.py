"""M9b explicit choices, coverage dominance, scoped overrides and stale content."""

from uuid import UUID, uuid4

import pytest
from validation_helpers import measured

from splatforge.core.reconstruction_selection import (
    DominanceSelectionPolicy,
    RankingMetric,
    ReconstructionSelection,
    ValidationFailureOverride,
    applicable_issues,
    make_selection,
    recommend_components,
    selected_content,
)
from splatforge.core.reconstruction_validation import MeasurementSettings
from splatforge.core.validation_measurements import geometry_identity, measure_reconstruction
from splatforge.core.validation_policy import ReconstructionValidationPolicy, evaluate_policy


def report_for(metrics, **kwargs):
    return evaluate_policy(metrics, ReconstructionValidationPolicy(**kwargs))


def choose(reconstruction, metrics, report, ids, **kwargs):
    return make_selection(
        UUID(int=9000), reconstruction, metrics, report, metrics.geometry, tuple(ids), **kwargs
    )


def bound_override(reconstruction, metrics, report, ids, **kwargs):
    content = selected_content(reconstruction, metrics.geometry, tuple(ids))
    issues = tuple(
        sorted(i.issue_id for i in applicable_issues(report, tuple(ids)) if i.severity == "failure")
    )
    return ValidationFailureOverride(
        reconstruction_artifact_id=UUID(int=9000),
        reconstruction_digest=reconstruction.semantic_digest,
        geometry_digest=metrics.geometry.semantic_digest,
        report_digest=report.semantic_digest,
        selected_components=content,
        issue_ids=issues,
        reason="Reviewed measured evidence.",
        **kwargs,
    )


def test_one_eligible_and_clear_dominant_component_with_no_scores():
    reconstruction, _u, _s, metrics = measured()
    report = report_for(metrics)
    decision = recommend_components(metrics, report, DominanceSelectionPolicy())
    assert decision.status == "selected"
    assert decision.reasons == ("only_eligible_component",)
    ids = decision.selected_component_ids
    result = choose(reconstruction, metrics, report, ids, mode="recommended")
    assert result.mode == "recommended" and result.policy.policy_id == "selection.dominance_v1"
    r, _u, _s, m = measured(
        [(i * 2 + 1, 10) for i in range(8)], [list(range(3)), list(range(3, 8))]
    )
    report = report_for(m)
    decision = recommend_components(m, report, DominanceSelectionPolicy())
    assert decision.status == "selected"
    winner = next(c for c in m.components if c.registration.registered_views == 5)
    assert decision.selected_component_ids == (winner.component_id,)
    assert decision.reasons == ("dominates_all_required_dimensions",)
    assert "score" not in decision.model_dump_json()
    assert choose(r, m, report, decision.selected_component_ids, mode="recommended")


def test_larger_phone_drone_component_is_not_dominant_and_requires_manual_selection():
    # Disjoint M8 components: A 500 drone+20 phone (520); B 250+250 (500).
    assignments = [(1, 10)] * 800 + [(2, 20)] * 300
    components = [
        list(range(500)) + list(range(800, 820)),
        list(range(500, 750)) + list(range(820, 1070)),
    ]
    _r, _u, _s, m = measured(
        assignments, components, points_available=False, tracks_available=False
    )
    decision = recommend_components(m, report_for(m), DominanceSelectionPolicy())
    assert decision.status == "ambiguous" and not decision.selected_component_ids
    a = next(c for c in decision.candidates if c.registration.registered_views == 520)
    b = next(c for c in decision.candidates if c.registration.registered_views == 500)
    assert a.source_groups[0].coverage.ratio == 500 / 800
    assert a.source_groups[1].coverage.ratio == 20 / 300
    assert b.source_groups[0].coverage.ratio == 250 / 800
    assert b.source_groups[1].coverage.ratio == 250 / 300
    assert decision.reasons[-1] == "Manual selection required."


def test_equal_evidence_never_uses_first_largest_or_uuid_order():
    _r, _u, _s, m = measured(
        [(i * 2 + 1, 10) for i in range(6)],
        [[0, 1, 2], [3, 4, 5]],
        points_available=False,
        tracks_available=False,
    )
    decision = recommend_components(m, report_for(m), DominanceSelectionPolicy())
    assert decision.status == "ambiguous" and decision.selected_component_ids == ()


def test_component_fail_is_removed_only_one_eligible_and_no_eligible_is_blocked():
    r, _u, _s, m = measured(
        [(i * 2 + 1, 10) for i in range(8)], [list(range(3)), list(range(3, 8))]
    )
    report = report_for(m, policy_id="custom_v1", fail_component_coverage_below=0.5)
    decision = recommend_components(m, report, DominanceSelectionPolicy())
    assert decision.status == "selected"
    assert decision.reasons == ("only_eligible_component",)
    assert choose(r, m, report, decision.selected_component_ids)
    fail = report_for(m, policy_id="custom_v1", minimum_viable_cameras=6)
    decision = recommend_components(m, fail, DominanceSelectionPolicy())
    assert decision.status == "blocked" and not decision.selected_component_ids


def test_unknown_required_comparison_is_ambiguous_and_not_perfect_geometry():
    _r, _u, _s, m = measured(
        [(i * 2 + 1, 10) for i in range(7)],
        [[0, 1, 2], [3, 4, 5, 6]],
        points_available=False,
        tracks_available=False,
    )
    policy = DominanceSelectionPolicy(
        required_ranking_metrics=(RankingMetric(name="reprojection.p95", direction="lower"),)
    )
    decision = recommend_components(m, report_for(m), policy)
    assert decision.status == "ambiguous"
    assert decision.reasons[0] == "required_comparison_evidence_unavailable"
    assert all(c.required_metrics[0][1].value is None for c in decision.candidates)


def test_manual_multiple_canonical_components_remain_separate_and_reject_invalid_ids():
    r, _u, _s, m = measured([(i * 2 + 1, 10) for i in range(6)], [[0, 1, 2], [3, 4, 5]])
    report = report_for(m)
    ids = tuple(c.component_id for c in r.components)
    result = choose(r, m, report, tuple(reversed(ids)))
    assert result.selected_component_ids == ids
    assert len(result.selected_components) == 2
    assert result.reasons[0].code == "multiple_components_retained"
    assert result.mode == "manual" and result.policy is None
    assert len({c.validation_geometry_digest for c in result.selected_components}) == 2
    for invalid in ((), (ids[0], ids[0]), (uuid4(),)):
        with pytest.raises(ValueError, match="components|component"):
            choose(r, m, report, invalid)
    with pytest.raises(ValueError, match="policy"):
        choose(r, m, report, ids, policy=DominanceSelectionPolicy())


def test_component_failure_on_unselected_independent_component_does_not_block_clean_selection():
    r, _u, _s, m = measured(
        [(i * 2 + 1, 10) for i in range(10)], [list(range(3)), list(range(3, 10))]
    )
    report = report_for(m, policy_id="custom_v1", fail_component_coverage_below=0.5)
    clean = next(c.component_id for c in m.components if c.registration.registered_views == 7)
    bad = next(c.component_id for c in m.components if c.registration.registered_views == 3)
    assert report.status == "fail" and report.project_status != "fail"
    assert choose(r, m, report, (clean,))
    with pytest.raises(ValueError, match="validation_failed"):
        choose(r, m, report, (bad,))
    override = bound_override(r, m, report, (bad,))
    assert choose(r, m, report, (bad,), override=override).override == override


def test_global_failure_cannot_be_waived_by_deselection_and_requires_exact_issue_override():
    r, _u, _s, m = measured(
        [(i * 2 + 1, 10) for i in range(10)], [list(range(3)), list(range(3, 9))]
    )
    report = report_for(m, policy_id="custom_v1", fail_registration_below=1)
    assert report.project_status == "fail"
    assert recommend_components(m, report, DominanceSelectionPolicy()).status == "blocked"
    for component in m.components:
        ids = (component.component_id,)
        with pytest.raises(ValueError, match="validation_failed"):
            choose(r, m, report, ids)
        override = bound_override(r, m, report, ids)
        assert choose(r, m, report, ids, override=override)


@pytest.mark.parametrize(
    "change",
    ["reason", "unknown_issue", "warning_issue", "components", "report", "artifact", "geometry"],
)
def test_invalid_and_stale_overrides_fail_closed(change):
    r, _u, _s, m = measured([(i * 2 + 1, 10) for i in range(7)], [[0, 1, 2], [3, 4, 5]])
    report = report_for(m, policy_id="custom_v1", fail_registration_below=1)
    ids = (m.components[0].component_id,)
    original = bound_override(r, m, report, ids)
    data = original.model_dump()
    if change == "reason":
        data["reason"] = "   "
        with pytest.raises(ValueError, match="reason"):
            ValidationFailureOverride.model_validate(data)
        return
    if change == "unknown_issue":
        data["issue_ids"] = ("0" * 64,)
    elif change == "warning_issue":
        warning = next(i.issue_id for i in report.issues if i.severity == "warning")
        data["issue_ids"] = (warning,)
    elif change == "components":
        data["selected_components"] = selected_content(
            r, m.geometry, (m.components[1].component_id,)
        )
    elif change == "report":
        data["report_digest"] = "0" * 64
    elif change == "artifact":
        data["reconstruction_artifact_id"] = uuid4()
    else:
        data["geometry_digest"] = "0" * 64
    override = ValidationFailureOverride.model_validate(data)
    with pytest.raises(ValueError, match="invalid_override|stale_override"):
        choose(r, m, report, ids, override=override)


def test_same_component_uuid_changed_sparse_geometry_invalidates_selection_and_override():
    r, universe, source, m = measured()
    report = report_for(m, policy_id="custom_v1", minimum_viable_cameras=4)
    ids = (r.components[0].component_id,)
    override = bound_override(r, m, report, ids)
    selection = choose(r, m, report, ids, override=override)
    source.records[ids[0]][0] = source.records[ids[0]][0].model_copy(update={"xyz": (0, 0, 20)})
    geometry = geometry_identity(r, source)
    new = measure_reconstruction(r, universe, geometry, source, MeasurementSettings())
    new_report = report_for(new, policy_id="custom_v1", minimum_viable_cameras=4)
    assert m.reconstruction_digest == new.reconstruction_digest
    assert m.components[0].component_id == new.components[0].component_id
    assert m.geometry.semantic_digest != geometry.semantic_digest
    with pytest.raises(ValueError, match="stale_selection"):
        selection.require_current(r, geometry, new_report, UUID(int=9000))
    with pytest.raises(ValueError, match="stale_override"):
        choose(r, new, new_report, ids, override=override)
    new_override = bound_override(r, new, new_report, ids)
    updated = choose(r, new, new_report, ids, override=new_override)
    assert updated.semantic_digest != selection.semantic_digest


def test_same_membership_changed_camera_geometry_and_stale_report_are_rejected():
    r, _u, _s, m = measured()
    report = report_for(m)
    ids = (r.components[0].component_id,)
    selection = choose(r, m, report, ids)
    changed, _u, _s, new = measured(baseline=2)
    assert changed.components[0].component_id == ids[0]
    with pytest.raises(ValueError, match="stale_selection"):
        selection.require_current(changed, new.geometry, report_for(new), UUID(int=9000))
    with pytest.raises(ValueError, match="stale_validation"):
        choose(changed, new, report, ids)


def test_reason_policy_and_artifact_provenance_do_not_contaminate_downstream_semantics():
    r, _u, _s, m = measured()
    report = report_for(m)
    ids = (r.components[0].component_id,)
    first = choose(r, m, report, ids, manual_reason="First explicit reason.")
    second = choose(r, m, report, ids, manual_reason="Different explanation.")
    assert first.recipe_key != second.recipe_key
    assert first.semantic_digest == second.semantic_digest
    recommended = choose(r, m, report, ids, mode="recommended")
    changed = choose(
        r,
        m,
        report,
        ids,
        mode="recommended",
        policy=DominanceSelectionPolicy(compare_validation_severity=False),
    )
    assert recommended.recipe_key != changed.recipe_key
    assert first.semantic_digest == recommended.semantic_digest == changed.semantic_digest
    other_artifact = make_selection(uuid4(), r, m, report, m.geometry, ids)
    assert other_artifact.semantic_digest == first.semantic_digest
    assert ReconstructionSelection.model_validate_json(first.model_dump_json()) == first


def test_changed_component_choice_changes_only_selection_content_identity_and_keeps_warnings():
    r, _u, _s, m = measured([(i * 2 + 1, 10) for i in range(7)], [[0, 1, 2], [3, 4, 5]])
    report = report_for(m)
    a, b = (c.component_id for c in m.components)
    first, second = choose(r, m, report, (a,)), choose(r, m, report, (b,))
    assert first.semantic_digest != second.semantic_digest
    assert first.warning_issue_ids == tuple(
        sorted(i.issue_id for i in report.issues if i.severity == "warning")
    )


def test_source_group_fail_scope_is_preserved_and_not_blanket_ignored():
    r, _u, _s, m = measured([(1, 10)] * 3 + [(2, 20)] * 4, [[0, 1, 2]])
    report = report_for(m, policy_id="custom_v1", fail_source_group_below=0.5)
    assert any(
        i.scope.kind == "source_group" and i.scope.component_id is None and i.severity == "failure"
        for i in report.issues
    )
    ids = (r.components[0].component_id,)
    with pytest.raises(ValueError, match="validation_failed"):
        choose(r, m, report, ids)
    override = bound_override(r, m, report, ids)
    assert choose(r, m, report, ids, override=override)


def test_warning_severity_and_required_quality_dimensions_are_transparent_tradeoffs():
    r, universe, source, m = measured(
        [(i * 2 + 1, 10) for i in range(8)], [list(range(3)), list(range(3, 8))]
    )
    large = next(c.component_id for c in m.components if c.registration.registered_views == 5)
    point = source.records[large][0]
    source.records[large][0] = point.model_copy(
        update={
            "observations": tuple(
                o.model_copy(update={"xy": (o.xy[0] + 10, o.xy[1])}) for o in point.observations
            )
        }
    )
    geometry = geometry_identity(r, source)
    m = measure_reconstruction(r, universe, geometry, source, MeasurementSettings())
    report = report_for(m)
    assert recommend_components(m, report, DominanceSelectionPolicy()).status == "ambiguous"
    policy = DominanceSelectionPolicy(compare_validation_severity=False)
    assert recommend_components(m, report, policy).selected_component_ids == (large,)
    selection = choose(r, m, report, (large,), mode="recommended", policy=policy)
    assert selection.warning_issue_ids and selection.override is None
    strict = DominanceSelectionPolicy(
        compare_validation_severity=False,
        required_ranking_metrics=(RankingMetric(name="reprojection.p95", direction="lower"),),
    )
    assert recommend_components(m, report, strict).status == "ambiguous"


def test_point_count_is_factual_and_not_a_quality_ranking_dimension():
    with pytest.raises(ValueError):
        RankingMetric(name="point.count", direction="higher")
    with pytest.raises(ValueError, match="direction"):
        RankingMetric(name="reprojection.p95", direction="higher")


def test_component_source_group_failure_does_not_block_a_clean_independent_component():
    r, _u, _s, metrics = measured([(1, 10)] * 6 + [(2, 20)] * 6, [[0, 1, 2], list(range(3, 12))])
    report = report_for(metrics, policy_id="custom_v1", fail_source_group_below=0.25)
    bad = next(c.component_id for c in metrics.components if c.registration.registered_views == 3)
    clean = next(c.component_id for c in metrics.components if c.registration.registered_views == 9)
    assert report.project_status != "fail"
    assert any(
        i.scope.kind == "source_group" and i.scope.component_id == bad and i.severity == "failure"
        for i in report.issues
    )
    assert choose(r, metrics, report, (clean,))
    with pytest.raises(ValueError, match="validation_failed"):
        choose(r, metrics, report, (bad,))


def test_frozen_reference_only_changes_recompute_metrics_but_preserve_selected_content():
    r, universe, source, metrics = measured()
    report = report_for(metrics)
    component = r.components[0].component_id
    original = choose(r, metrics, report, (component,))
    data = source.data[component]
    source.data[component] = data.model_copy(
        update={
            "priors": tuple(
                p.model_copy(update={"parameters": (80, 80, 50, 40)}) for p in data.priors
            )
        }
    )
    geometry = geometry_identity(r, source)
    updated = measure_reconstruction(r, universe, geometry, source, MeasurementSettings())
    assert geometry.components[0].content_digest == metrics.geometry.components[0].content_digest
    assert (
        geometry.components[0].reference_digest != metrics.geometry.components[0].reference_digest
    )
    assert updated.recipe_key != metrics.recipe_key
    selection = choose(r, updated, report_for(updated), (component,))
    assert selection.recipe_key != original.recipe_key
    assert selection.semantic_digest == original.semantic_digest
