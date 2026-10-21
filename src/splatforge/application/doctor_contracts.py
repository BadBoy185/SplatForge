"""Application-owned ports used by the environment Doctor service."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Protocol

from splatforge.core.capabilities import ColmapProbeReport, FreshnessPolicy, GpuReport
from splatforge.core.media import ExecutableIdentity


class DoctorTeardownError(RuntimeError):
    """Probe containment failed; stop Doctor and retain any owned workspace."""


class Clock(Protocol):
    def __call__(self) -> datetime: ...


class ColmapCapabilityProbe(Protocol):
    def probe(
        self,
        *,
        explicit_executable: Path | None,
        explicit_model_directory: Path | None,
        bundled_executable: Path | None,
        bundled_model_directory: Path | None,
        deep: bool,
        observed_at: datetime,
        freshness: FreshnessPolicy,
    ) -> ColmapProbeReport: ...

    def verify_expected_identity(self, expected: ExecutableIdentity) -> bool: ...

    def configuration_key(self) -> tuple[str, ...]: ...


class GpuCapabilityProbe(Protocol):
    def configuration_key(self) -> tuple[str, ...]: ...

    def verify_expected_identity(self, expected: ExecutableIdentity) -> bool: ...

    def probe(
        self,
        *,
        observed_at: datetime,
        freshness: FreshnessPolicy,
    ) -> GpuReport: ...
