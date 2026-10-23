"""Build evidence never follows from NVIDIA inventory or backend option existence."""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from mapping_helpers import map_run, mapping_inputs
from test_colmap_capabilities import process_result
from test_incremental_contracts import caspar_settings
from test_matching_execution import hashes

from splatforge.adapters import caspar_probe
from splatforge.application.mapping import MappingService
from splatforge.application.work_models import mapping_progress_plan
from splatforge.core.capabilities import FreshnessPolicy
from splatforge.core.execution import IncrementalMappingRoute, RunSnapshot
from splatforge.core.progress import ExecutionHardwareProfile
from splatforge.core.reconstruction import CasparDevice, IncrementalMapperSettings

DEVICE = CasparDevice(
    index=0,
    uuid="a" * 32,
    name="synthetic GPU",
    driver_version=12080,
    driver_binary_sha256="c" * 64,
    compute_major=12,
    compute_minor=0,
)


def probe(fixture):
    return fixture.mapping_adapter()._capabilities.probe(
        explicit_executable=fixture.exe,
        explicit_model_directory=None,
        bundled_executable=None,
        bundled_model_directory=None,
        deep=True,
        observed_at=datetime.now(UTC),
        freshness=FreshnessPolicy(),
        verification_only=True,
    )


@pytest.mark.parametrize("compiled", [False, True])
def test_doctor_separates_options_compilation_runtime_and_integration(tmp_path, compiled):
    from mapping_helpers import MappingFixture

    fixture = MappingFixture(tmp_path)
    fixture.caspar_compiled = compiled
    report = probe(fixture)
    assert report.capability("colmap.mapper.incremental").status == "available"
    assert report.capability("colmap.ba.caspar.options").status == "available"
    assert report.capability("colmap.ba.caspar.compiled").status == (
        "available" if compiled else "unavailable"
    )
    assert report.capability("colmap.ba.caspar.runtime").status == "unknown"
    assert report.capability("colmap.ba.caspar.integration").status == "unknown"
    assert not any(r.argv[0] == "bundle_adjuster" and len(r.argv) > 2 for r in fixture.requests)


@pytest.mark.parametrize("change", ["command", "option", "version"])
def test_incremental_presence_version_and_options_each_required(tmp_path, change):
    from mapping_helpers import MappingFixture

    fixture = MappingFixture(tmp_path)
    if change == "command":
        fixture.top_help = fixture.top_help.replace("  mapper\n", "")
    elif change == "option":
        fixture.incremental_help = fixture.incremental_help.replace(
            "--Mapper.extract_colors arg\n", ""
        )
    else:
        fixture.top_help = fixture.top_help.replace("4.2.1", "4.3.0")
    with pytest.raises(ValueError, match="capability"):
        fixture.mapping_adapter().prepare(
            "preserve_priors",
            colmap=fixture.exe,
            settings=IncrementalMapperSettings(),
            calibration=None,
        )


@pytest.mark.parametrize("reason", ["Requested GPU 9 missing", "compatible CUDA runtime missing"])
def test_caspar_missing_gpu_runtime_never_starts_mapping(tmp_path, monkeypatch, reason):
    from mapping_helpers import MappingFixture

    fixture = MappingFixture(tmp_path)
    fixture.caspar_compiled = True

    def fail(*_):
        raise ValueError("mapping.gpu_unavailable: " + reason)

    monkeypatch.setattr(caspar_probe, "probe_caspar", fail)
    with pytest.raises(ValueError, match=reason):
        fixture.mapping_adapter().prepare(
            "preserve_priors", colmap=fixture.exe, settings=caspar_settings(), calibration=None
        )
    assert not any(r.argv[0] == "mapper" and len(r.argv) > 2 for r in fixture.requests)


@pytest.mark.parametrize("mode", ["success", "failed", "missing_evidence", "cancelled"])
def test_explicit_caspar_device_cache_no_fallback_and_immutability(tmp_path, monkeypatch, mode):
    value, fixture, _features, _raw, verified = mapping_inputs(tmp_path, camera_model="PINHOLE")
    fixture.caspar_compiled = True
    before = hashes(value.root)
    device = [DEVICE]
    monkeypatch.setattr(caspar_probe, "probe_caspar", lambda *_: device[0])
    monkeypatch.setattr(caspar_probe, "observe_caspar_device", lambda *_: device[0])
    fixture.mapping_mode = (
        "failed" if mode == "failed" else ("cancelled" if mode == "cancelled" else "success")
    )
    fixture.caspar_evidence = mode != "missing_evidence"
    if mode == "cancelled":
        fixture.on_map = lambda owner: value.execution.request_cancellation(
            value.root, run_id=owner.run
        )
    if mode in {"failed", "missing_evidence"}:
        with pytest.raises(ValueError, match="mapper_process_failure"):
            map_run(value, fixture, verified, settings=caspar_settings())
    else:
        result = map_run(value, fixture, verified, settings=caspar_settings())
        if mode == "cancelled":
            assert result.status == "cancelled" and result.artifact is None
        else:
            assert not result.cache_hit and result.reconstruction.component_count == 1
            service = MappingService(value.execution, fixture.mapping_adapter())
            assert len(tuple(service.reader(value.root, result.run_id).components())) == 1
            frozen = RunSnapshot.model_validate_json(
                (value.root / "runs" / str(result.run_id) / "run.json").read_bytes()
            )
            assert (
                type(frozen.route) is IncrementalMappingRoute
                and frozen.route.backend.device == DEVICE
            )
            assert frozen.route.settings.ba_gpu_index == 0
            assert map_run(value, fixture, verified, settings=caspar_settings()).cache_hit
            device[0] = DEVICE.model_copy(update={"index": 1, "uuid": "b" * 32})
            changed = map_run(value, fixture, verified, settings=caspar_settings(1))
            assert (
                not changed.cache_hit and changed.artifact.recipe_key != result.artifact.recipe_key
            )
            other = RunSnapshot.model_validate_json(
                (value.root / "runs" / str(changed.run_id) / "run.json").read_bytes()
            )
            hardware = ExecutionHardwareProfile()
            assert (
                mapping_progress_plan(frozen.route, hardware).signature
                != mapping_progress_plan(other.route, hardware).signature
            )
    numerical = [
        r for r in fixture.requests if r.argv[0] in {"mapper", "global_mapper"} and len(r.argv) > 2
    ]
    assert numerical and all(r.argv[0] == "mapper" for r in numerical)
    assert all(
        r.argv[r.argv.index("--Mapper.ba_global_backend") + 1] == "CASPAR" for r in numerical
    )
    assert all(
        __import__("hashlib").sha256(p.read_bytes()).hexdigest() == h for p, h in before.items()
    )


@pytest.mark.parametrize(
    "text",
    [
        b"",
        b"Creating Caspar bundle adjuster\nfallback to CERES",
        b"Creating Caspar bundle adjuster\nCaspar: MAX_ITERATIONS\nSkipping image 1",
    ],
)
def test_solver_evidence_fail_closed(text):
    from splatforge.adapters.process_runner import ProcessRequest

    request = ProcessRequest(
        executable="colmap.exe",
        argv=("mapper",),
        working_directory=Path.cwd(),
        environment={},
        timeout_seconds=1,
    )
    result = process_result(request, stderr=text)
    with pytest.raises(ValueError, match="execution_unverified"):
        caspar_probe.require_caspar_execution(result)
