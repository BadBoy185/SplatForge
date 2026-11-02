"""Plan consumes the same participation resolver as Prepare, or exact historical views."""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from test_pairs_execution import service
from test_source_participation import change
from test_views_execution import harness, prepare

from splatforge.application.desktop_workflow import plan_reconstruction, reconstruction_request
from splatforge.bootstrap import build_gui_facade, build_project_service


def plan_facade():
    facade = build_gui_facade()
    evidence = SimpleNamespace(model_dump=lambda **_: {})
    facade.factories.update({
        "profiles": lambda: SimpleNamespace(resolve=lambda **_: evidence),
        "doctor": lambda: SimpleNamespace(report=lambda **_: evidence),
        "mapping": lambda: SimpleNamespace(capability=lambda *_, **__: evidence),
        "pairs": service,
    })
    return facade


def test_plan_rejects_all_excluded_and_restore_reenables(tmp_path):
    value = harness(tmp_path)
    request = reconstruction_request(build_project_service().open(value.root))
    facade = plan_facade()
    assert plan_reconstruction(facade, value.root, request, None, None)["runnable"]
    change(value.root, value.source_ids)
    plan = plan_reconstruction(facade, value.root, request, None, None)
    assert not plan["runnable"]
    assert "No included sources" in " ".join(plan["validation_warnings"])
    change(value.root, {value.source_ids[0]}, included=True)
    assert plan_reconstruction(facade, value.root, request, None, None)["runnable"]


def test_plan_validates_exact_historical_views_independently_of_current_exclusions(tmp_path):
    value = harness(tmp_path)
    views = prepare(value)
    change(value.root, value.source_ids)
    request = reconstruction_request(build_project_service().open(value.root)).model_copy(
        update={"views_run": views.run_id}
    )
    facade = plan_facade()
    assert plan_reconstruction(facade, value.root, request, None, None)["runnable"]
    missing = request.model_copy(update={"views_run": uuid4()})
    plan = plan_reconstruction(facade, value.root, missing, None, None)
    assert not plan["runnable"]
    assert "published views" in " ".join(plan["validation_warnings"])


def test_readonly_views_validation_creates_no_run_and_refuses_wrong_run(tmp_path):
    value = harness(tmp_path)
    views = prepare(value)
    before = sorted((value.root / "runs").iterdir())
    assert service().validate_views_input(value.root, views.run_id) == 3
    assert sorted((value.root / "runs").iterdir()) == before
    with pytest.raises(ValueError):
        service().validate_views_input(value.root, uuid4())
