"""Selection uses the existing immutable publication, cache and recovery protocol."""

from uuid import UUID

import pytest
from mapping_helpers import map_run, mapping_inputs
from test_matching_execution import hashes
from test_validation_execution import service as validation_service
from test_views_execution import query

from splatforge.adapters.execution_storage import ExecutionFaultHooks, LocalExecutionRepository
from splatforge.adapters.fake_stages import LocalFakeStages
from splatforge.application.execution import FakeExecutionService, PublicationUnresolvedError
from splatforge.application.reconstruction_selection import ReconstructionSelectionService
from splatforge.core.reconstruction_selection import DominanceSelectionPolicy
from splatforge.core.validation_policy import ReconstructionValidationPolicy


def setup(tmp_path, *, multi=False, policy=None):
    value, fixture, _f, _r, verified = mapping_inputs(tmp_path, multi=multi)
    if multi:
        fixture.mapping_mode = "multi"
    mapping = map_run(value, fixture, verified)
    validation = validation_service(value).validate(
        value.root, mapping_run_id=mapping.run_id, policy=policy
    )
    return value, fixture, mapping, validation


def service(value, repository=None):
    return ReconstructionSelectionService(validation_service(value, repository))


def test_selection_publication_cache_reason_policy_and_unchanged_m8_m9a(tmp_path):
    value, _f, _m, validation = setup(tmp_path)
    before = hashes(value.root)
    current = service(value)
    first = current.select(value.root, validation_run_id=validation.run_id)
    assert first.status == "succeeded" and not first.run.cache_hit
    again = current.select(value.root, validation_run_id=validation.run_id)
    assert again.run.cache_hit and again.run.artifact == first.run.artifact
    ids = first.selection.selected_component_ids
    manual = current.select(value.root, validation_run_id=validation.run_id, component_ids=ids)
    reason = current.select(
        value.root,
        validation_run_id=validation.run_id,
        component_ids=ids,
        manual_reason="Inspected the source-group coverage.",
    )
    changed = current.select(
        value.root,
        validation_run_id=validation.run_id,
        policy=DominanceSelectionPolicy(compare_validation_severity=False),
    )
    assert not manual.run.cache_hit and not reason.run.cache_hit and not changed.run.cache_hit
    assert len({v.selection.semantic_digest for v in (first, manual, reason, changed)}) == 1
    assert current.inspect(value.root, manual.run.run_id).selection == manual.selection
    assert current.inspect_details(value.root, manual.run.run_id)[0] == manual.selection
    assert all(
        __import__("hashlib").sha256(p.read_bytes()).hexdigest() == h for p, h in before.items()
    )
    path = value.execution.artifact_directory(value.root, first.run.artifact) / "evidence.json"
    path.write_bytes(b"corrupt indexed selection")
    with pytest.raises(ValueError):
        current.inspect(value.root, first.run.run_id)
    assert not current.select(value.root, validation_run_id=validation.run_id).run.cache_hit


def test_automatic_ambiguity_publishes_no_artifact_manual_multiple_remains_separate(tmp_path):
    value, _f, _m, validation = setup(tmp_path, multi=True)
    before = query(value.root, "SELECT count(*) FROM artifacts")
    result = service(value).select(value.root, validation_run_id=validation.run_id)
    assert result.status == "ambiguous" and result.run is None and result.selection is None
    assert query(value.root, "SELECT count(*) FROM artifacts") == before
    report, metrics = validation_service(value).inspect_details(value.root, validation.run_id)
    ids = tuple(c.component_id for c in metrics.components)
    a = service(value).select(
        value.root, validation_run_id=validation.run_id, component_ids=(ids[0],)
    )
    both = service(value).select(
        value.root, validation_run_id=validation.run_id, component_ids=tuple(reversed(ids))
    )
    assert both.selection.selected_component_ids == ids
    assert len(both.selection.selected_components) == 2
    assert a.selection.semantic_digest != both.selection.semantic_digest
    assert not both.run.cache_hit


def test_explicit_failed_gate_override_and_stale_policy_refusal(tmp_path):
    value, _fixture, mapping, validation = setup(
        tmp_path,
        policy=ReconstructionValidationPolicy(policy_id="custom_v1", minimum_viable_cameras=4),
    )
    current = service(value)
    blocked = current.select(value.root, validation_run_id=validation.run_id)
    assert blocked.status == "blocked" and blocked.selection is None
    report, metrics = validation_service(value).inspect_details(value.root, validation.run_id)
    ids = (metrics.components[0].component_id,)
    failures = tuple(i.issue_id for i in report.issues if i.severity == "failure")
    with pytest.raises(ValueError, match="validation_failed"):
        current.select(value.root, validation_run_id=validation.run_id, component_ids=ids)
    with pytest.raises(ValueError, match="reason"):
        current.select(
            value.root,
            validation_run_id=validation.run_id,
            component_ids=ids,
            override_issue_ids=failures,
        )
    result = current.select(
        value.root,
        validation_run_id=validation.run_id,
        component_ids=ids,
        override_issue_ids=failures,
        override_reason="Inspected this tiny fixture explicitly.",
    )
    assert result.selection.override.issue_ids == tuple(sorted(failures))
    new = validation_service(value).validate(
        value.root,
        mapping_run_id=mapping.run_id,
        policy=ReconstructionValidationPolicy(policy_id="custom_v1", minimum_viable_cameras=5),
    )
    assert new.metrics_run.cache_hit
    with pytest.raises(ValueError, match="stale_override"):
        current.select(
            value.root,
            validation_run_id=new.run_id,
            component_ids=ids,
            override=result.selection.override,
        )


@pytest.mark.parametrize("corrupt", [False, True])
def test_selection_orphan_recovery_and_corruption_refusal(tmp_path, corrupt):
    value, _f, _m, validation = setup(tmp_path)

    def crash(path):
        if path.parent.name == "reconstruction_selection":
            if corrupt:
                (path / "evidence.json").write_bytes(b"bad selection")
            raise RuntimeError("after selection rename")

    repository = LocalExecutionRepository(
        fault_hooks=ExecutionFaultHooks(after_artifact_move=crash)
    )
    with pytest.raises(PublicationUnresolvedError):
        service(value, repository).select(value.root, validation_run_id=validation.run_id)
    run = UUID(query(value.root, "SELECT run_id FROM runs WHERE status='running'")[0][0])
    result = FakeExecutionService(value.execution, LocalFakeStages()).recover(value.root, run)
    assert result.status == ("interrupted" if corrupt else "succeeded")
    assert len(result.adopted_attempts) == (0 if corrupt else 1)
    assert service(value).select(value.root, validation_run_id=validation.run_id).run.cache_hit is (
        not corrupt
    )


def test_selection_cancellation_before_publication_and_restart(tmp_path):
    value, _f, _m, validation = setup(tmp_path)
    repository = None

    def cancel(path):
        if path.parent.name == "reconstruction_selection":
            run = UUID(query(value.root, "SELECT run_id FROM runs WHERE status='running'")[0][0])
            repository.request_cancellation(value.root, run_id=run)

    repository = LocalExecutionRepository(
        fault_hooks=ExecutionFaultHooks(before_artifact_move=cancel)
    )
    result = service(value, repository).select(value.root, validation_run_id=validation.run_id)
    assert result.status == "cancelled" and result.selection is None and result.run.artifact is None
    assert (
        service(value).select(value.root, validation_run_id=validation.run_id).status == "succeeded"
    )
