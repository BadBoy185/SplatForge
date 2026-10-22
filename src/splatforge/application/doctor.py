"""Application orchestration and presentation for environment diagnostics."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from splatforge.application.doctor_contracts import (
    Clock,
    ColmapCapabilityProbe,
    GpuCapabilityProbe,
)
from splatforge.core.capabilities import (
    CapabilityEvidence,
    CapabilityStatus,
    ColmapProbeReport,
    DoctorReport,
    FreshnessPolicy,
    ImplementationStatus,
    MethodCapability,
    required_status,
)
from splatforge.core.registry import MethodRegistry


@dataclass(frozen=True)
class _CachedReport:
    report: DoctorReport
    expires_at: datetime


class DoctorService:
    def __init__(
        self,
        colmap: ColmapCapabilityProbe,
        gpu: GpuCapabilityProbe,
        registry: MethodRegistry,
        *,
        clock: Clock | None = None,
        freshness: FreshnessPolicy | None = None,
        bundled_colmap: Path | None = None,
        bundled_model_directory: Path | None = None,
    ) -> None:
        self._colmap = colmap
        self._gpu = gpu
        self._registry = registry
        self._clock = clock or (lambda: datetime.now(UTC))
        self._freshness = freshness or FreshnessPolicy()
        self._bundled_colmap = bundled_colmap
        self._bundled_model_directory = bundled_model_directory
        self._cache: dict[tuple[object, ...], _CachedReport] = {}

    def report(
        self,
        *,
        colmap: Path | None = None,
        model_directory: Path | None = None,
        deep: bool = False,
    ) -> DoctorReport:
        now = self._clock()
        key = (
            str(colmap.absolute()) if colmap is not None else None,
            str(model_directory.absolute()) if model_directory is not None else None,
            deep,
            self._colmap.configuration_key(),
            self._gpu.configuration_key(),
        )
        cached = self._cache.get(key)
        if cached is not None and cached.report.observed_at <= now < cached.expires_at:
            selected = cached.report.colmap.selected_executable
            gpu_identity = cached.report.gpu.executable
            if (
                selected is not None
                and self._colmap.verify_expected_identity(selected.identity)
                and (not hasattr(self._colmap, "verify_model_identities")
                     or self._colmap.verify_model_identities(cached.report.colmap.models))
                and (gpu_identity is None or self._gpu.verify_expected_identity(gpu_identity))
            ):
                return cached.report
        colmap_report = self._colmap.probe(
            explicit_executable=colmap.absolute() if colmap is not None else None,
            explicit_model_directory=(
                model_directory.absolute() if model_directory is not None else None
            ),
            bundled_executable=self._bundled_colmap,
            bundled_model_directory=self._bundled_model_directory,
            deep=deep,
            observed_at=now,
            freshness=self._freshness,
        )
        gpu_report = self._gpu.probe(observed_at=now, freshness=self._freshness)
        completed_at = self._clock()
        colmap_report = self._current_colmap_report(colmap_report, completed_at)
        gpu_report = gpu_report.model_copy(
            update={"evidence": gpu_report.evidence.current_at(completed_at)}
        )
        report = DoctorReport(
            observed_at=completed_at,
            deep=deep,
            freshness_policy=self._freshness,
            colmap=colmap_report,
            gpu=gpu_report,
            methods=self._map_methods(colmap_report, completed_at),
            warnings=self._warnings(colmap_report),
        )
        evidence = (
            colmap_report.binary,
            colmap_report.command_discovery.evidence,
            colmap_report.database.evidence,
            *colmap_report.capabilities,
            *(item.evidence for item in colmap_report.models),
            *(item.evidence for item in colmap_report.command_discovery.subcommands),
            gpu_report.evidence,
        )
        expiry = min(item.expires_at for item in evidence)
        self._cache.clear()
        if completed_at < expiry and colmap_report.selected_executable is not None:
            self._cache[key] = _CachedReport(report=report, expires_at=expiry)
        return report

    @staticmethod
    def _current_colmap_report(
        report: ColmapProbeReport, observed_at: datetime
    ) -> ColmapProbeReport:
        discovery = report.command_discovery.model_copy(
            update={
                "evidence": report.command_discovery.evidence.current_at(observed_at),
                "subcommands": tuple(
                    item.model_copy(update={"evidence": item.evidence.current_at(observed_at)})
                    for item in report.command_discovery.subcommands
                ),
            }
        )
        return report.model_copy(
            update={
                "binary": report.binary.current_at(observed_at),
                "command_discovery": discovery,
                "capabilities": tuple(item.current_at(observed_at) for item in report.capabilities),
                "database": report.database.model_copy(
                    update={"evidence": report.database.evidence.current_at(observed_at)}
                ),
                "models": tuple(
                    item.model_copy(update={"evidence": item.evidence.current_at(observed_at)})
                    for item in report.models
                ),
            }
        )

    def _map_methods(
        self, report: ColmapProbeReport, observed_at: datetime
    ) -> tuple[MethodCapability, ...]:
        catalog = {item.id for item in self._registry.list()}
        routes = (
            (
                "feature_extraction.aliked",
                ("colmap.feature.aliked",),
            ),
            (
                "feature_extraction.sift",
                ("colmap.feature.sift.cpu", "colmap.feature.sift.gpu"),
            ),
            ("feature_extraction.loma_b",
             ("colmap.feature.loma_b.cpu", "colmap.feature.loma_b.gpu")),
            ("feature_extraction.loma_b128",
             ("colmap.feature.loma_b128.cpu", "colmap.feature.loma_b128.gpu")),
            (
                "feature_matching.lightglue_aliked",
                ("colmap.match.aliked_lightglue.cpu", "colmap.match.aliked_lightglue.gpu"),
            ),
            (
                "feature_matching.lightglue_sift",
                ("colmap.match.sift_lightglue.cpu", "colmap.match.sift_lightglue.gpu"),
            ),
            *((f"feature_matching.{token}",
               (f"colmap.match.{token}.cpu", f"colmap.match.{token}.gpu"))
              for token in ("sift_bruteforce", "aliked_bruteforce", "loma_bruteforce",
                            "loma_b", "loma_b128", "loma_r", "loma_l", "loma_g")),
            ("geometric_verification.colmap", ("colmap.verification.standalone",)),
            ("mapping.colmap_global", ("colmap.mapper.global",)),
            ("mapping.colmap_incremental", ("colmap.mapper.incremental",)),
            ("mapping.colmap_hierarchical", ("colmap.mapper.hierarchical",)),
        )
        mapped = []
        for method_id, prerequisites in routes:
            statuses = []
            for item in prerequisites:
                try:
                    statuses.append(report.capability(item).current_at(observed_at).status)
                except KeyError:
                    statuses.append(CapabilityStatus.UNKNOWN)
            if len(prerequisites) > 1:
                if CapabilityStatus.AVAILABLE in statuses:
                    backend_status = CapabilityStatus.AVAILABLE
                elif CapabilityStatus.UNKNOWN in statuses:
                    backend_status = CapabilityStatus.UNKNOWN
                else:
                    backend_status = CapabilityStatus.UNAVAILABLE
            else:
                backend_status = statuses[0]
            if report.binary.status != CapabilityStatus.AVAILABLE:
                backend_status = report.binary.status
            implemented = method_id.startswith((
                "feature_extraction.", "feature_matching.", "geometric_verification.",
            )) or method_id == "mapping.colmap_global"
            if implemented:
                backend_status = required_status((backend_status, report.database.evidence.status))
            mapped.append(
                MethodCapability(
                    method_id=method_id,
                    catalogued=method_id in catalog,
                    supported_by_splatforge=implemented,
                    implementation_status=(ImplementationStatus.IMPLEMENTED if implemented
                                           else ImplementationStatus.PLANNED),
                    backend_capability_status=backend_status,
                    runnable=implemented and backend_status == CapabilityStatus.AVAILABLE,
                    diagnostic_code=("splatforge.native_capability_gate" if implemented else
                                     "splatforge.stage_not_implemented"),
                    message=("Native execution requires verified method/device/models and options"
                             if implemented else "SplatForge stage not implemented yet"),
                    prerequisites=prerequisites,
                )
            )
        return tuple(mapped)

    @staticmethod
    def _warnings(report: ColmapProbeReport) -> tuple[CapabilityEvidence, ...]:
        warnings = []
        if report.binary.status != CapabilityStatus.AVAILABLE:
            warnings.append(report.binary)
        if report.command_discovery.evidence.status == CapabilityStatus.UNKNOWN:
            warnings.append(report.command_discovery.evidence)
        if report.database.evidence.status == CapabilityStatus.UNAVAILABLE:
            warnings.append(report.database.evidence)
        return tuple(warnings[:32])


def render_doctor_report(report: DoctorReport) -> str:
    selected = report.colmap.selected_executable
    lines = [
        f"SplatForge Doctor v{report.doctor_schema_version}",
        f"Observed: {report.observed_at.isoformat()}",
        f"Mode: {'deep' if report.deep else 'lightweight'}",
        (
            f"COLMAP: {selected.identity.resolved_path} "
            f"({selected.identity.version_line or 'version unknown'})"
            if selected is not None
            else f"COLMAP: {report.colmap.binary.status.value} — {report.colmap.binary.message}"
        ),
        (
            "Native database: "
            f"{report.colmap.database.evidence.status.value} — "
            f"{report.colmap.database.evidence.message}"
        ),
        f"NVIDIA GPU: {report.gpu.evidence.status.value} — {report.gpu.evidence.message}",
    ]
    for capability_id, label in (
        ("colmap.feature.sift.cpu", "CPU SIFT"),
        ("colmap.feature.sift.gpu", "GPU SIFT"),
        ("colmap.onnx", "ONNX build"),
    ):
        item = report.colmap.capability(capability_id)
        lines.append(f"{label}: {item.status.value} — {item.message}")
    model_counts = {
        status.value: sum(item.evidence.status == status for item in report.colmap.models)
        for status in CapabilityStatus
    }
    lines.append(
        "Learned models (file evidence only): "
        + ", ".join(f"{count} {status}" for status, count in model_counts.items())
    )
    lines.append("SplatForge methods:")
    for method in report.methods:
        lines.append(
            f"  {method.method_id}: backend={method.backend_capability_status.value}, "
            f"implemented={method.implementation_status.value}, "
            f"runnable={'yes' if method.runnable else 'no'}"
        )
    if report.warnings:
        lines.append("Warnings:")
        lines.extend(
            f"  {warning.diagnostic_code}: {warning.message}" for warning in report.warnings
        )
    return "\n".join(lines)
