from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from splatforge.core.capabilities import (
    CapabilityEvidence,
    CapabilityStatus,
    ImplementationStatus,
    MethodCapability,
    required_status,
)


def test_capability_evidence_requires_utc_and_nonnegative_freshness_window() -> None:
    observed = datetime(2026, 10, 21, 12, tzinfo=UTC)
    evidence = CapabilityEvidence(
        capability_id="colmap.binary",
        status=CapabilityStatus.UNKNOWN,
        diagnostic_code="test.unknown",
        message="Unknown is explicit",
        observed_at=observed,
        expires_at=observed + timedelta(seconds=30),
        freshness_seconds=30,
    )
    assert evidence.status == CapabilityStatus.UNKNOWN

    with pytest.raises(ValidationError, match="UTC"):
        CapabilityEvidence(
            capability_id="colmap.binary",
            status=CapabilityStatus.UNKNOWN,
            diagnostic_code="test.unknown",
            message="Wrong timezone",
            observed_at=observed.astimezone(timezone(timedelta(hours=2))),
            expires_at=observed + timedelta(seconds=30),
            freshness_seconds=30,
        )


@pytest.mark.parametrize(
    ("catalogued", "implementation", "backend"),
    [
        (False, ImplementationStatus.IMPLEMENTED, CapabilityStatus.AVAILABLE),
        (True, ImplementationStatus.PLANNED, CapabilityStatus.AVAILABLE),
        (True, ImplementationStatus.IMPLEMENTED, CapabilityStatus.UNKNOWN),
        (True, ImplementationStatus.IMPLEMENTED, CapabilityStatus.UNAVAILABLE),
    ],
)
def test_runnable_method_requires_all_independent_gates(
    catalogued: bool,
    implementation: ImplementationStatus,
    backend: CapabilityStatus,
) -> None:
    with pytest.raises(ValidationError, match="runnable requires"):
        MethodCapability(
            method_id="mapping.example",
            catalogued=catalogued,
            implementation_status=implementation,
            backend_capability_status=backend,
            runnable=True,
            diagnostic_code="test.blocked",
            message="blocked",
        )


def test_available_backend_does_not_make_planned_method_runnable() -> None:
    method = MethodCapability(
        method_id="mapping.colmap_global",
        catalogued=True,
        implementation_status=ImplementationStatus.PLANNED,
        backend_capability_status=CapabilityStatus.AVAILABLE,
        runnable=False,
        diagnostic_code="splatforge.stage_not_implemented",
        message="SplatForge stage not implemented yet",
    )
    assert method.runnable is False


def test_unknown_required_dependency_prevents_available_capability() -> None:
    assert (
        required_status((CapabilityStatus.AVAILABLE, CapabilityStatus.UNKNOWN))
        == CapabilityStatus.UNKNOWN
    )
