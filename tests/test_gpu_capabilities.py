from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from splatforge.adapters.gpu_capabilities import NvidiaSmiCapabilityAdapter
from splatforge.adapters.process_runner import ExecutableNotFoundError, ProcessRequest
from splatforge.core.capabilities import CapabilityStatus, FreshnessPolicy
from splatforge.core.media import ExecutableIdentity
from splatforge.core.process import ProcessResult

NOW = datetime(2026, 10, 21, 12, tzinfo=UTC)
IDENTITY = ExecutableIdentity(
    resolved_path="C:/NVIDIA/nvidia-smi.exe",
    size=100,
    last_write_ns=200,
    sha256="b" * 64,
)


class Resolver:
    def __init__(self, *, missing: bool = False) -> None:
        self.missing = missing
        self.verifications = 0

    def resolve(self, requested: str, *, environment=None) -> ExecutableIdentity:  # type: ignore[no-untyped-def]
        if self.missing:
            raise ExecutableNotFoundError(requested)
        return IDENTITY

    def verify_expected_identity(self, expected: ExecutableIdentity) -> bool:
        self.verifications += 1
        return expected == IDENTITY


def result(
    request: ProcessRequest,
    *,
    stdout: bytes = b"",
    stderr: bytes = b"",
    exit_code: int | None = 0,
    timed_out: bool = False,
) -> ProcessResult:
    return ProcessResult(
        executable=IDENTITY,
        argv=request.argv,
        working_directory=str(request.working_directory),
        exit_code=exit_code,
        elapsed_seconds=0.1,
        stdout=stdout,
        stderr=stderr,
        stdout_truncated=False,
        stderr_truncated=False,
        timed_out=timed_out,
        cancelled=False,
        teardown_confirmed=True,
        forced_tree_termination=timed_out,
    )


class Runner:
    def __init__(self, outputs: list[dict[str, object]]) -> None:
        self.outputs = outputs
        self.requests: list[ProcessRequest] = []

    def run(self, request: ProcessRequest, *, cancellation=None) -> ProcessResult:
        self.requests.append(request)
        return result(request, **self.outputs.pop(0))


def test_no_nvidia_smi_is_optional_unavailable() -> None:
    report = NvidiaSmiCapabilityAdapter(
        runner=Runner([]),
        resolver=Resolver(missing=True),  # type: ignore[arg-type]
        environment={},
    ).probe(observed_at=NOW, freshness=FreshnessPolicy())
    assert report.evidence.status == CapabilityStatus.UNAVAILABLE
    assert report.evidence.diagnostic_code == "gpu.nvidia_tool_missing"
    assert report.devices == ()


def test_gpu_inventory_parses_driver_vram_and_compute_capability() -> None:
    resolver = Resolver()
    runner = Runner([{"stdout": b"NVIDIA RTX 4090, 590.10, 24564, 20123, 8.9\n"}])
    report = NvidiaSmiCapabilityAdapter(
        runner=runner,
        resolver=resolver,  # type: ignore[arg-type]
        environment={},
    ).probe(observed_at=NOW, freshness=FreshnessPolicy())
    assert report.evidence.status == CapabilityStatus.AVAILABLE
    assert report.evidence.freshness_seconds == 30
    assert report.devices[0].driver_version == "590.10"
    assert report.devices[0].total_vram_mib == 24564
    assert report.devices[0].free_vram_mib == 20123
    assert report.devices[0].compute_capability == "8.9"
    assert resolver.verifications == 1
    assert runner.requests[0].working_directory == Path(IDENTITY.resolved_path).resolve().parent


def test_unsupported_compute_query_falls_back_without_fabricating_value() -> None:
    runner = Runner(
        [
            {"exit_code": 2, "stderr": b"Field compute_cap is not supported"},
            {"stdout": b"NVIDIA RTX, 555.42, 8192, 4096\n"},
        ]
    )
    report = NvidiaSmiCapabilityAdapter(
        runner=runner,
        resolver=Resolver(),  # type: ignore[arg-type]
        environment={},
    ).probe(observed_at=NOW, freshness=FreshnessPolicy())
    assert report.evidence.status == CapabilityStatus.AVAILABLE
    assert report.devices[0].compute_capability is None
    assert len(runner.requests) == 2


def test_malformed_or_timed_out_gpu_query_is_unknown() -> None:
    malformed = NvidiaSmiCapabilityAdapter(
        runner=Runner([{"stdout": b"not,csv\n"}]),
        resolver=Resolver(),  # type: ignore[arg-type]
        environment={},
    ).probe(observed_at=NOW, freshness=FreshnessPolicy())
    assert malformed.evidence.status == CapabilityStatus.UNKNOWN
    assert malformed.evidence.diagnostic_code == "gpu.query_unrecognized"

    timed_out = NvidiaSmiCapabilityAdapter(
        runner=Runner([{"exit_code": None, "timed_out": True}]),
        resolver=Resolver(),  # type: ignore[arg-type]
        environment={},
    ).probe(observed_at=NOW, freshness=FreshnessPolicy())
    assert timed_out.evidence.status == CapabilityStatus.UNKNOWN
    assert timed_out.evidence.diagnostic_code == "gpu.probe_timeout"


def test_nvidia_smi_replacement_during_query_is_refused() -> None:
    changed = IDENTITY.model_copy(update={"sha256": "f" * 64})

    class ChangedRunner:
        def run(self, request: ProcessRequest, *, cancellation=None) -> ProcessResult:
            return result(
                request,
                stdout=b"NVIDIA RTX, 555.42, 8192, 4096, 8.9\n",
            ).model_copy(update={"executable": changed})

    report = NvidiaSmiCapabilityAdapter(
        runner=ChangedRunner(),
        resolver=Resolver(),  # type: ignore[arg-type]
        environment={},
    ).probe(observed_at=NOW, freshness=FreshnessPolicy())
    assert report.evidence.status == CapabilityStatus.UNKNOWN
    assert report.evidence.diagnostic_code == "gpu.identity_changed"
