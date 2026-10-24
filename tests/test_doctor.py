from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from typer.testing import CliRunner

from splatforge.application.doctor import DoctorService, render_doctor_report
from splatforge.cli.app import app
from splatforge.core.builtin_methods import build_builtin_registry
from splatforge.core.capabilities import (
    CapabilityEvidence,
    CapabilityStatus,
    ColmapProbeReport,
    CommandDiscovery,
    DatabaseCompatibility,
    DoctorReport,
    ExecutableSelection,
    ExecutableSource,
    FreshnessPolicy,
    GpuReport,
)
from splatforge.core.media import ExecutableIdentity

NOW = datetime(2026, 10, 21, 12, tzinfo=UTC)
IDENTITY = ExecutableIdentity(
    resolved_path="C:/Tools/colmap.exe",
    size=10,
    last_write_ns=20,
    sha256="c" * 64,
    version_line="COLMAP 4.2.1 -- fake build",
)
CAPABILITY_IDS = (
    "colmap.onnx",
    "colmap.feature.sift.cpu",
    "colmap.feature.sift.gpu",
    "colmap.feature.aliked",
    "colmap.match.sift_lightglue",
    "colmap.match.aliked_lightglue",
    "colmap.mapper.global",
    "colmap.mapper.incremental",
    "colmap.mapper.hierarchical",
)


def evidence(
    capability_id: str,
    status: CapabilityStatus,
    now: datetime,
    *,
    identity: ExecutableIdentity | None = None,
) -> CapabilityEvidence:
    return CapabilityEvidence(
        capability_id=capability_id,
        status=status,
        diagnostic_code=f"test.{status.value}",
        message=f"{capability_id} is {status.value}",
        observed_at=now,
        expires_at=now + timedelta(seconds=30),
        freshness_seconds=30,
        backend_identity=identity,
    )


def colmap_report(
    now: datetime,
    *,
    present: bool = True,
    status: CapabilityStatus = CapabilityStatus.AVAILABLE,
    deep: bool = False,
) -> ColmapProbeReport:
    selected = (
        ExecutableSelection(
            source=ExecutableSource.EXPLICIT,
            requested=IDENTITY.resolved_path,
            identity=IDENTITY,
        )
        if present
        else None
    )
    binary_status = CapabilityStatus.AVAILABLE if present else CapabilityStatus.UNAVAILABLE
    return ColmapProbeReport(
        selected_executable=selected,
        binary=evidence(
            "colmap.binary",
            binary_status,
            now,
            identity=IDENTITY if present else None,
        ),
        command_discovery=CommandDiscovery(
            evidence=evidence(
                "colmap.commands",
                binary_status,
                now,
                identity=IDENTITY if present else None,
            ),
            commands=("feature_extractor", "mapper"),
            feature_tokens=("SIFT", "LOMA_B128"),
        ),
        capabilities=tuple(
            evidence(
                item,
                status if present else CapabilityStatus.UNAVAILABLE,
                now,
                identity=IDENTITY,
            )
            for item in CAPABILITY_IDS
        ),
        database=DatabaseCompatibility(
            evidence=evidence(
                "colmap.database",
                CapabilityStatus.UNKNOWN if present else CapabilityStatus.UNAVAILABLE,
                now,
                identity=IDENTITY if present else None,
            )
        ),
        deep=deep,
    )


class FakeColmap:
    def __init__(self, *, present: bool = True) -> None:
        self.present = present
        self.calls = 0
        self.identity_valid = True
        self.environment_key = ("fixed",)

    def configuration_key(self) -> tuple[str, ...]:
        return self.environment_key

    def probe(self, **kwargs) -> ColmapProbeReport:  # type: ignore[no-untyped-def]
        self.calls += 1
        return colmap_report(
            kwargs["observed_at"],
            present=self.present,
            deep=kwargs["deep"],
        )

    def verify_expected_identity(self, expected: ExecutableIdentity) -> bool:
        return self.identity_valid and expected == IDENTITY


class FakeGpu:
    def __init__(
        self,
        status: CapabilityStatus = CapabilityStatus.UNAVAILABLE,
    ) -> None:
        self.calls = 0
        self.status = status

    def configuration_key(self) -> tuple[str, ...]:
        return ("fixed",)

    def verify_expected_identity(self, expected: ExecutableIdentity) -> bool:
        return True

    def probe(self, *, observed_at, freshness) -> GpuReport:  # type: ignore[no-untyped-def]
        self.calls += 1
        return GpuReport(evidence=evidence("gpu.nvidia", self.status, observed_at))


class Clock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value


def test_no_colmap_is_a_valid_report_and_planned_methods_are_not_runnable() -> None:
    service = DoctorService(
        FakeColmap(present=False),
        FakeGpu(),
        build_builtin_registry(),
        clock=Clock(NOW),
    )
    report = service.report()
    assert report.colmap.binary.status == CapabilityStatus.UNAVAILABLE
    assert all(method.catalogued for method in report.methods)
    assert all(method.implementation_status == (
        "implemented" if method.method_id.startswith(("feature_extraction.", "feature_matching.",
                                                     "geometric_verification."))
        or method.method_id in {"mapping.colmap_global", "mapping.colmap_incremental",
                                "mapping.colmap_hierarchical", "dataset.colmap_undistorted_v1"}
        else "planned"
    ) for method in report.methods)
    assert all(method.runnable is False for method in report.methods)
    DoctorReport.model_validate_json(report.model_dump_json())


def test_deep_flag_is_forwarded_and_backend_status_never_marks_stage_runnable() -> None:
    colmap = FakeColmap()
    service = DoctorService(
        colmap,
        FakeGpu(),
        build_builtin_registry(),
        clock=Clock(NOW),
    )
    report = service.report(deep=True)
    assert report.deep is True
    assert report.colmap.deep is True
    assert all(method.backend_capability_status == (
        CapabilityStatus.UNKNOWN if method.method_id.startswith(("feature_extraction.",
            "feature_matching.", "geometric_verification."))
        or method.method_id in {"mapping.colmap_global", "mapping.colmap_incremental",
                                "mapping.colmap_hierarchical", "dataset.colmap_undistorted_v1"}
        else CapabilityStatus.AVAILABLE
    ) for method in report.methods)
    assert all(method.runnable is False for method in report.methods)
    assert colmap.calls == 1


def test_process_local_freshness_cache_expires_and_identity_change_invalidates() -> None:
    clock = Clock(NOW)
    colmap = FakeColmap()
    gpu = FakeGpu()
    service = DoctorService(
        colmap,
        gpu,
        build_builtin_registry(),
        clock=clock,
        freshness=FreshnessPolicy(resource_health_seconds=30),
    )
    first = service.report(colmap=Path("C:/Tools/colmap.exe"))
    clock.value = NOW + timedelta(seconds=20)
    assert service.report(colmap=Path("C:/Tools/colmap.exe")) is first
    assert (colmap.calls, gpu.calls) == (1, 1)

    colmap.identity_valid = False
    changed = service.report(colmap=Path("C:/Tools/colmap.exe"))
    assert changed is not first
    assert (colmap.calls, gpu.calls) == (2, 2)

    colmap.identity_valid = True
    clock.value = NOW + timedelta(seconds=51)
    service.report(colmap=Path("C:/Tools/colmap.exe"))
    assert (colmap.calls, gpu.calls) == (3, 3)


def test_human_report_distinguishes_implementation_from_runtime_availability() -> None:
    report = DoctorService(
        FakeColmap(),
        FakeGpu(),
        build_builtin_registry(),
        clock=Clock(NOW),
    ).report()
    rendered = render_doctor_report(report)
    assert "COLMAP 4.2.1" in rendered
    assert ("mapping.colmap_hierarchical: backend=unknown, "
            "implemented=implemented, runnable=no") in rendered
    assert "Global Positioning GPU: options=unknown; cuda=unknown" in rendered
    assert "Global Ceres BA GPU: options=unknown; cuda=unknown" in rendered
    assert len(rendered.splitlines()) < 40


def test_generic_gpu_availability_does_not_change_colmap_gpu_health() -> None:
    class CpuOnlyColmap(FakeColmap):
        def probe(self, **kwargs) -> ColmapProbeReport:  # type: ignore[no-untyped-def]
            report = super().probe(**kwargs)
            capabilities = tuple(
                (
                    evidence(
                        item.capability_id,
                        CapabilityStatus.UNAVAILABLE,
                        kwargs["observed_at"],
                        identity=IDENTITY,
                    )
                    if item.capability_id == "colmap.feature.sift.gpu"
                    else item
                )
                for item in report.capabilities
            )
            return report.model_copy(update={"capabilities": capabilities})

    report = DoctorService(
        CpuOnlyColmap(),
        FakeGpu(CapabilityStatus.AVAILABLE),
        build_builtin_registry(),
        clock=Clock(NOW),
    ).report()
    assert report.gpu.evidence.status == CapabilityStatus.AVAILABLE
    assert (
        report.colmap.capability("colmap.feature.sift.gpu").status == CapabilityStatus.UNAVAILABLE
    )


def test_doctor_cli_json_and_human_output(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    report = DoctorService(
        FakeColmap(present=False),
        FakeGpu(),
        build_builtin_registry(),
        clock=Clock(NOW),
    ).report()

    class Service:
        def report(self, **kwargs):  # type: ignore[no-untyped-def]
            assert kwargs["deep"] is True
            return report

    monkeypatch.setattr("splatforge.cli.app.build_doctor_service", lambda: Service())
    runner = CliRunner()
    structured = runner.invoke(
        app,
        [
            "doctor",
            "--deep",
            "--json",
            "--colmap",
            "C:/Tools/colmap.exe",
            "--colmap-model-dir",
            "C:/Models",
        ],
    )
    assert structured.exit_code == 0, structured.output
    assert json.loads(structured.output)["doctor_schema_version"] == 1

    human = runner.invoke(app, ["doctor", "--deep"])
    assert human.exit_code == 0
    assert "SplatForge Doctor v1" in human.output


def test_methods_and_version_do_not_trigger_doctor(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    def fail() -> None:
        raise AssertionError("Doctor must remain lazy")

    monkeypatch.setattr("splatforge.cli.app.build_doctor_service", fail)
    runner = CliRunner()
    assert runner.invoke(app, ["methods"]).exit_code == 0
    assert runner.invoke(app, ["version"]).exit_code == 0


def test_expired_static_evidence_reprobes_before_the_longer_resource_ttl() -> None:
    class ShortStaticColmap(FakeColmap):
        def probe(self, **kwargs) -> ColmapProbeReport:
            report = super().probe(**kwargs)
            evidence = report.command_discovery.evidence.model_copy(
                update={
                    "freshness_seconds": 1,
                    "expires_at": kwargs["observed_at"] + timedelta(seconds=1),
                }
            )
            discovery = report.command_discovery.model_copy(update={"evidence": evidence})
            return report.model_copy(update={"command_discovery": discovery})

    clock = Clock(NOW)
    colmap = ShortStaticColmap()
    service = DoctorService(colmap, FakeGpu(), build_builtin_registry(), clock=clock)
    service.report()
    clock.value += timedelta(seconds=2)
    service.report()
    assert colmap.calls == 2


def test_environment_configuration_change_invalidates_current_cache() -> None:
    clock = Clock(NOW)
    colmap = FakeColmap()
    service = DoctorService(colmap, FakeGpu(), build_builtin_registry(), clock=clock)
    service.report()
    colmap.environment_key = ("changed executable selection",)
    service.report()
    assert colmap.calls == 2


def test_slow_deep_probe_cannot_return_expired_health_as_current_available() -> None:
    class SlowGpu(FakeGpu):
        def probe(self, *, observed_at, freshness) -> GpuReport:
            result = super().probe(observed_at=observed_at, freshness=freshness)
            clock.value += timedelta(seconds=31)
            return result

    clock = Clock(NOW)
    colmap = FakeColmap()
    service = DoctorService(
        colmap, SlowGpu(CapabilityStatus.AVAILABLE), build_builtin_registry(), clock=clock
    )
    report = service.report(deep=True)
    assert report.colmap.capability("colmap.feature.sift.cpu").status == CapabilityStatus.UNKNOWN
    assert report.gpu.evidence.status == CapabilityStatus.UNKNOWN
    assert report.gpu.evidence.diagnostic_code == "capability.evidence_not_current"
    assert all(
        item.backend_capability_status != CapabilityStatus.AVAILABLE for item in report.methods
    )
    service.report(deep=True)
    assert colmap.calls == 2


def test_doctor_does_not_mutate_a_real_project_or_acquire_its_writer_lock(
    tmp_path: Path, monkeypatch
) -> None:
    from splatforge.bootstrap import build_project_service

    root = tmp_path / "project"
    build_project_service().create(root, "M5 read-only proof")
    before = {
        str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()
    }

    def forbidden(*args, **kwargs):
        raise AssertionError("Doctor must not acquire a project writer lock")

    monkeypatch.setattr(
        "splatforge.adapters.project_lock.WindowsProjectWriterLock.__enter__", forbidden
    )
    DoctorService(FakeColmap(), FakeGpu(), build_builtin_registry(), clock=Clock(NOW)).report(
        deep=True
    )
    after = {
        str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()
    }
    assert after == before


def test_project_show_and_config_do_not_start_doctor(tmp_path: Path, monkeypatch) -> None:
    from splatforge.bootstrap import build_project_service

    root = tmp_path / "project"
    build_project_service().create(root, "Lazy capability probes")
    monkeypatch.setattr(
        "splatforge.cli.app.build_doctor_service",
        lambda: (_ for _ in ()).throw(AssertionError("Doctor called")),
    )
    runner = CliRunner()
    assert runner.invoke(app, ["project", "show", str(root)]).exit_code == 0
    assert runner.invoke(app, ["show-default-config"]).exit_code == 0
