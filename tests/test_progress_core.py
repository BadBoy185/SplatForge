from __future__ import annotations

import json

import pytest
from progress_helpers import FakeClock, observation, plan, sample
from pydantic import ValidationError

from splatforge.application.eta import HybridThroughputEstimator
from splatforge.core.progress import (
    Confidence,
    EtaEstimate,
    ExecutionHardwareProfile,
    PerformanceSample,
    ProgressMode,
    StageProgressObservation,
    WorkDescription,
    WorkMetric,
    WorkUnit,
)


def test_contracts_are_frozen_versioned_and_roundtrip() -> None:
    value = observation(plan(), 10, 1)
    assert StageProgressObservation.model_validate_json(value.model_dump_json()) == value
    assert value.observation_schema_version == 1
    with pytest.raises(ValidationError):
        value.completed = 20
    assert set(WorkUnit) >= {
        WorkUnit.BYTES,
        WorkUnit.SOURCE_SECONDS,
        WorkUnit.ITERATIONS,
        WorkUnit.MEGAPIXELS,
        WorkUnit.PAIRS,
    }


@pytest.mark.parametrize(
    "field,value",
    [
        ("completed", -1),
        ("completed", 1001),
        ("completed", float("inf")),
        ("completed", "10"),
        ("elapsed_seconds", -1),
        ("elapsed_seconds", float("nan")),
        ("observation_schema_version", 2),
        ("observation_schema_version", True),
        ("phase_code", "x" * 129),
        ("phase_code", "C:/private/project"),
        ("widget_color", "red"),
    ],
)
def test_invalid_observation_rejected(field: str, value: object) -> None:
    fields = observation(plan(), 0, 0).model_dump()
    fields[field] = value
    with pytest.raises(ValidationError):
        StageProgressObservation.model_validate(fields)


def test_modes_do_not_invent_stage_fraction_or_eta() -> None:
    base = plan()
    for mode, total in ((ProgressMode.INDETERMINATE, None), (ProgressMode.PHASE, 100)):
        stage = base.model_copy(
            update={
                "work": base.work.model_copy(
                    update={
                        "mode": mode,
                        "total": total,
                    }
                )
            }
        )
        estimator = HybridThroughputEstimator(stage, (sample(base),))
        estimator.observe(observation(stage, 10, 1))
        assert estimator.estimate().likely_seconds is None
        assert estimator.estimate().confidence == Confidence.UNAVAILABLE
    with pytest.raises(ValidationError):
        WorkDescription.model_validate({**base.work.model_dump(), "total": None})


def test_monotonic_work_and_clock_require_explicit_new_plan() -> None:
    stage = plan()
    estimator = HybridThroughputEstimator(stage)
    estimator.observe(observation(stage, 100, 1))
    for next_value in (observation(stage, 99, 2), observation(stage, 101, 0.5)):
        with pytest.raises(ValueError):
            estimator.observe(next_value)
    changed = stage.model_copy(update={"work": stage.work.model_copy(update={"total": 2000})})
    with pytest.raises(ValueError, match="revise"):
        estimator.observe(observation(changed, 200, 2))


@pytest.mark.parametrize(
    "fields",
    [
        {"likely_seconds": 4},
        {"likely_seconds": 4, "lower_seconds": 5, "upper_seconds": 6},
        {"likely_seconds": -1, "lower_seconds": 0, "upper_seconds": 2},
        {"confidence": Confidence.HIGH},
    ],
)
def test_eta_requires_ordered_nonnegative_range(fields: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        EtaEstimate(**fields)


def test_history_contract_has_no_arbitrary_or_personal_data() -> None:
    value = sample(clock=FakeClock())
    payload = json.loads(value.model_dump_json())
    assert payload["outcome"] == "succeeded"
    for field in (
        "source_path",
        "filename",
        "project_id",
        "source_id",
        "hostname",
        "username",
        "environment",
        "api_key",
        "raw_logs",
        "artifact_id",
    ):
        with pytest.raises(ValidationError):
            PerformanceSample.model_validate({**value.model_dump(), field: "private"})
    with pytest.raises(ValidationError):
        PerformanceSample.model_validate({**value.model_dump(), "outcome": "cancelled"})
    with pytest.raises(ValidationError):
        PerformanceSample.model_validate({**value.model_dump(), "throughput": 10})
    with pytest.raises(ValidationError):
        ExecutionHardwareProfile(hostname="private")
    with pytest.raises(ValidationError):
        WorkMetric(name="filename", value=1)
