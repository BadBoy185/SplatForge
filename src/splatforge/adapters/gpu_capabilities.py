"""Optional contained NVIDIA GPU inventory for Doctor diagnostics."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from datetime import datetime, timedelta
from pathlib import Path
from typing import Protocol

from splatforge.adapters.process_runner import (
    ExecutableNotFoundError,
    ExecutableResolver,
    LocalProcessRunner,
    ProcessBoundaryError,
    ProcessRequest,
)
from splatforge.application.doctor_contracts import DoctorTeardownError
from splatforge.core.capabilities import (
    CapabilityEvidence,
    CapabilityStatus,
    EvidenceDetail,
    FreshnessPolicy,
    GpuDevice,
    GpuReport,
)
from splatforge.core.media import ExecutableIdentity
from splatforge.core.process import ProcessResult


class _Runner(Protocol):
    def run(self, request: ProcessRequest, *, cancellation=None) -> ProcessResult: ...


class NvidiaSmiCapabilityAdapter:
    def __init__(
        self,
        *,
        runner: _Runner | None = None,
        resolver: ExecutableResolver | None = None,
        environment: Mapping[str, str] | None = None,
        timeout_seconds: float = 10.0,
        maximum_output_bytes: int = 64 * 1024,
    ) -> None:
        self._resolver = resolver or ExecutableResolver()
        self._runner = runner or LocalProcessRunner(self._resolver)
        self._environment = os.environ if environment is None else environment
        self._timeout = timeout_seconds
        self._maximum_output = maximum_output_bytes

    def configuration_key(self) -> tuple[str, ...]:
        return tuple(self._environment.get(name, "") for name in ("PATH", "PATHEXT"))

    def verify_expected_identity(self, expected: ExecutableIdentity) -> bool:
        return self._resolver.verify_expected_identity(expected)

    def probe(
        self,
        *,
        observed_at: datetime,
        freshness: FreshnessPolicy,
    ) -> GpuReport:
        try:
            identity = self._resolver.resolve(
                "nvidia-smi",
                environment=self._environment,
            )
        except ExecutableNotFoundError:
            return GpuReport(
                evidence=self._evidence(
                    CapabilityStatus.UNAVAILABLE,
                    "gpu.nvidia_tool_missing",
                    "nvidia-smi is unavailable; CPU COLMAP routes may still be usable",
                    observed_at,
                    freshness,
                    None,
                )
            )
        except (ProcessBoundaryError, OSError) as exc:
            return GpuReport(
                evidence=self._evidence(
                    CapabilityStatus.UNKNOWN,
                    "gpu.identity_unavailable",
                    f"Cannot establish nvidia-smi file identity: {exc}",
                    observed_at,
                    freshness,
                    None,
                )
            )
        if os.name == "nt" and Path(identity.resolved_path).suffix.lower() not in {".exe", ".com"}:
            return GpuReport(
                executable=identity,
                evidence=self._evidence(
                    CapabilityStatus.UNKNOWN,
                    "gpu.native_executable_required",
                    "Select native nvidia-smi.exe; batch/script wrappers are not executed",
                    observed_at,
                    freshness,
                    identity,
                ),
            )
        fields = ("name", "driver_version", "memory.total", "memory.free", "compute_cap")
        try:
            result = self._query(identity.resolved_path, fields)
        except (ProcessBoundaryError, OSError) as exc:
            return GpuReport(
                executable=identity,
                evidence=self._evidence(
                    CapabilityStatus.UNKNOWN,
                    "gpu.probe_failed",
                    f"NVIDIA GPU query could not start: {exc}",
                    observed_at,
                    freshness,
                    identity,
                ),
            )
        problem = self._problem(result)
        if (
            problem is not None
            and problem[1] == "gpu.query_failed"
            and re.search(
                r"(?:compute_cap.*(?:not (?:a valid field|supported)|invalid)|"
                r"(?:invalid|unsupported).*compute_cap)",
                result.stderr_text(),
                re.IGNORECASE,
            )
        ):
            fields = ("name", "driver_version", "memory.total", "memory.free")
            try:
                result = self._query(identity.resolved_path, fields)
            except (ProcessBoundaryError, OSError) as exc:
                problem = (
                    CapabilityStatus.UNKNOWN,
                    "gpu.probe_failed",
                    f"NVIDIA GPU fallback query could not start: {exc}",
                )
            else:
                problem = self._problem(result)
        if problem is not None:
            status, code, message = problem
            return GpuReport(
                executable=identity,
                evidence=self._evidence(
                    status,
                    code,
                    message,
                    observed_at,
                    freshness,
                    identity,
                ),
            )
        if identity.model_copy(update={"version_line": None}) != result.executable.model_copy(
            update={"version_line": None}
        ) or not self._resolver.verify_expected_identity(result.executable):
            return GpuReport(
                executable=identity,
                evidence=self._evidence(
                    CapabilityStatus.UNKNOWN,
                    "gpu.identity_changed",
                    "nvidia-smi changed during the GPU query",
                    observed_at,
                    freshness,
                    identity,
                ),
            )
        try:
            devices = self._parse_csv(result.stdout_text(), has_compute=len(fields) == 5)
        except ValueError as exc:
            return GpuReport(
                executable=identity,
                evidence=self._evidence(
                    CapabilityStatus.UNKNOWN,
                    "gpu.query_unrecognized",
                    f"nvidia-smi returned unrecognized bounded data: {exc}",
                    observed_at,
                    freshness,
                    identity,
                ),
            )
        return GpuReport(
            executable=identity,
            evidence=self._evidence(
                CapabilityStatus.AVAILABLE,
                "gpu.nvidia_available",
                f"Detected {len(devices)} NVIDIA GPU(s); free VRAM is a transient observation",
                observed_at,
                freshness,
                identity,
                details=(("device_count", str(len(devices))),),
            ),
            devices=devices,
        )

    def _query(self, executable: str, fields: tuple[str, ...]) -> ProcessResult:
        return self._runner.run(
            ProcessRequest(
                executable=executable,
                argv=(
                    f"--query-gpu={','.join(fields)}",
                    "--format=csv,noheader,nounits",
                ),
                working_directory=Path(executable).resolve().parent,
                environment={},
                timeout_seconds=self._timeout,
                max_stdout_bytes=self._maximum_output,
                max_stderr_bytes=self._maximum_output,
            )
        )

    @staticmethod
    def _parse_csv(text: str, *, has_compute: bool) -> tuple[GpuDevice, ...]:
        devices = []
        expected = 5 if has_compute else 4
        for line in text.splitlines():
            if not line.strip():
                continue
            values = [item.strip() for item in line.split(",")]
            if len(values) != expected or any(not value for value in values):
                raise ValueError("unexpected column count or empty field")
            try:
                total = int(values[2])
                free = int(values[3])
            except ValueError as exc:
                raise ValueError("VRAM fields are not integer MiB values") from exc
            if total < 0 or free < 0 or free > total:
                raise ValueError("VRAM values are outside valid bounds")
            devices.append(
                GpuDevice(
                    name=values[0],
                    driver_version=values[1],
                    total_vram_mib=total,
                    free_vram_mib=free,
                    compute_capability=values[4] if has_compute else None,
                )
            )
            if len(devices) > 32:
                raise ValueError("GPU inventory exceeds the bounded device limit")
        if not devices:
            raise ValueError("no GPU rows")
        return tuple(devices)

    @staticmethod
    def _problem(
        result: ProcessResult,
    ) -> tuple[CapabilityStatus, str, str] | None:
        if not result.teardown_confirmed:
            raise DoctorTeardownError(
                "gpu.probe_teardown_failed: unresolved nvidia-smi process tree"
            )
        if result.timed_out:
            return CapabilityStatus.UNKNOWN, "gpu.probe_timeout", "nvidia-smi timed out"
        if result.cancelled:
            return CapabilityStatus.UNKNOWN, "gpu.probe_cancelled", "nvidia-smi was cancelled"
        if not result.teardown_confirmed or result.forced_tree_termination:
            return (
                CapabilityStatus.UNKNOWN,
                "gpu.probe_teardown_failed",
                "nvidia-smi did not complete clean process-tree teardown",
            )
        if result.stdout_truncated or result.stderr_truncated:
            return (
                CapabilityStatus.UNKNOWN,
                "gpu.query_unrecognized",
                "nvidia-smi output exceeded the bounded capture",
            )
        if result.exit_code != 0:
            detail = " ".join(
                (result.stderr_text().strip() or result.stdout_text().strip()).split()
            )[:1024]
            return (
                CapabilityStatus.UNKNOWN,
                "gpu.query_failed",
                f"nvidia-smi exited with code {result.exit_code}: {detail or 'no diagnostics'}",
            )
        return None

    @staticmethod
    def _evidence(
        status: CapabilityStatus,
        code: str,
        message: str,
        observed_at: datetime,
        freshness: FreshnessPolicy,
        identity: ExecutableIdentity | None,
        *,
        details: tuple[tuple[str, str], ...] = (),
    ) -> CapabilityEvidence:
        ttl = freshness.resource_health_seconds
        return CapabilityEvidence(
            capability_id="gpu.nvidia",
            status=status,
            diagnostic_code=code,
            message=message[:1024],
            observed_at=observed_at,
            expires_at=observed_at + timedelta(seconds=ttl),
            freshness_seconds=ttl,
            backend_identity=identity,
            details=tuple(EvidenceDetail(key=key, value=value) for key, value in details),
        )
