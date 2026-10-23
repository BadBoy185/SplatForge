"""Acceleration axes, frozen identity, positive evidence and strict fallback refusal."""

from pathlib import Path

import pytest
from mapping_helpers import MappingFixture, map_run, mapping_help, mapping_inputs
from test_caspar_capabilities import DEVICE, probe
from test_incremental_execution import snapshot, unchanged
from test_matching_execution import hashes

from splatforge.adapters import caspar_probe, global_gpu
from splatforge.adapters.colmap_help import parse_option_help
from splatforge.adapters.colmap_mapping_options import mapping_arguments
from splatforge.application.work_models import mapping_progress_plan
from splatforge.core.execution import GlobalAcceleratedRoute, MappingRoute
from splatforge.core.progress import ExecutionHardwareProfile
from splatforge.core.reconstruction import (
    GlobalAcceleratedSettings,
    GlobalAccelerationSettings,
    GlobalMapperSettings,
    mapping_recipe_key,
)

SPARSE = (
    "Sparse linear algebra library CUDA_SPARSE\n"
    "Linear solver SPARSE_SCHUR SPARSE_SCHUR\n  Linear solver 0.001 (2)\n"
)
DENSE = (
    "Dense linear algebra library CUDA\nLinear solver DENSE_SCHUR DENSE_SCHUR\n"
    "  Linear solver 0.001 (2)\n"
)
GPU_LOG = (
    "Running global positioning\n" + SPARSE + "Global positioning done in 1s\n"
    "Running iterative bundle adjustment\n" + DENSE + "Iterative bundle adjustment done in 1s\n"
)


def accelerated(gp="cpu", ba="cpu"):
    return GlobalAcceleratedSettings(
        acceleration=GlobalAccelerationSettings(positioning_device=gp, ba_device=ba)
    )


@pytest.mark.parametrize("gp,ba", [("cpu", "cpu"), (0, "cpu"), ("cpu", 0), (0, 0), (1, 0)])
def test_independent_explicit_global_devices_and_recipe(gp, ba):
    value = accelerated(gp, ba)
    argv = mapping_arguments(
        value,
        parse_option_help(mapping_help(), "GlobalMapper").option_names,
        database=Path("p.db"),
        images=Path("empty"),
        output=Path("out"),
    )
    assert argv[argv.index("--GlobalMapper.gp_use_gpu") + 1] == str(int(gp != "cpu"))
    assert argv[argv.index("--GlobalMapper.ba_ceres_use_gpu") + 1] == str(int(ba != "cpu"))
    assert argv[argv.index("--GlobalMapper.gp_gpu_index") + 1] == str(gp if gp != "cpu" else -1)
    assert argv[argv.index("--GlobalMapper.ba_gpu_index") + 1] == str(ba if ba != "cpu" else -1)
    assert value.method_id == "mapping.colmap_global"
    assert value != GlobalMapperSettings()


@pytest.mark.parametrize("value", ["auto", -1, 32, True, "gpu:0"])
def test_frozen_acceleration_requires_concrete_typed_ordinal(value):
    with pytest.raises(ValueError):
        GlobalAccelerationSettings(positioning_device=value)


@pytest.mark.parametrize(
    "message",
    [
        "Requested to use GPU but Ceres was compiled without CUDA support",
        "Ceres compiled without cuDSS support",
        "Falling back to CPU-based sparse solvers",
        "GPU bundle adjustment failed (CUDA initialization failed), retrying with CPU.",
        "GPU solver unavailable",
        "GPU device unavailable",
        "no CUDA GPU is available",
        "option will be ignored",
    ],
)
def test_requested_gpu_fallback_is_failure(message):
    with pytest.raises(ValueError, match="global_gpu_fallback"):
        global_gpu.require_global_gpu_execution(GPU_LOG + message, accelerated(0, 0).acceleration)


def test_positive_evidence_is_subsystem_scoped_and_not_option_acceptance():
    global_gpu.require_global_gpu_execution(GPU_LOG, accelerated(0, 0).acceleration)
    gp_only = GPU_LOG.split("Running iterative")[0]
    global_gpu.require_global_gpu_execution(gp_only, accelerated(0).acceleration)
    with pytest.raises(ValueError, match="execution_unverified"):
        global_gpu.require_global_gpu_execution(gp_only, accelerated(ba=0).acceleration)
    for text in (
        "GPU detected CUDA available",
        "--GlobalMapper.gp_use_gpu 1",
        GPU_LOG.replace("CUDA_SPARSE", "SUITE_SPARSE"),
        GPU_LOG.replace("SPARSE_SCHUR SPARSE_SCHUR", "SPARSE_SCHUR DENSE_SCHUR"),
    ):
        with pytest.raises(ValueError, match="execution_unverified"):
            global_gpu.require_global_gpu_execution(text, accelerated(0).acceleration)


def test_recipe_keys_preserve_v1_and_separate_all_modes_and_calibration():
    def key(settings, policy="preserve_priors", backend="a" * 64):
        return mapping_recipe_key("b" * 64, settings, policy, None, backend)

    old = GlobalMapperSettings.model_validate_json(GlobalMapperSettings().model_dump_json())
    assert key(old) == key(GlobalMapperSettings())
    modes = [
        GlobalMapperSettings(),
        accelerated(0),
        accelerated(ba=0),
        accelerated(0, 0),
        accelerated(1),
        accelerated(),
    ]
    assert len({key(mode) for mode in modes}) == len(modes)
    assert key(accelerated(0)) != key(accelerated(0), backend="c" * 64)
    assert key(accelerated(0)) != key(accelerated(0), policy="view_graph")


def test_generic_gpu_inventory_and_caspar_do_not_certify_global_gpu(tmp_path):
    fixture = MappingFixture(tmp_path)
    fixture.caspar_compiled = True
    report = probe(fixture)
    for name in ("positioning", "ba"):
        assert report.capability(f"colmap.global_gpu.{name}.options").status == "available"
        assert report.capability(f"colmap.global_gpu.{name}.runtime").status == "unknown"
        assert report.capability(f"colmap.global_gpu.{name}.integration").status == "unknown"
    assert not any(r.argv[0] == "bundle_adjuster" and len(r.argv) > 2 for r in fixture.requests)


@pytest.mark.parametrize(
    "gp,ba,policy",
    [
        (0, "cpu", "preserve_priors"),
        ("cpu", 0, "preserve_priors"),
        (0, 0, "preserve_priors"),
        (0, "cpu", "view_graph"),
    ],
)
def test_accelerated_lifecycle_cache_device_no_fallback_and_cpu_compatibility(
    tmp_path, monkeypatch, gp, ba, policy
):
    value, fixture, _, _, verified = mapping_inputs(tmp_path)
    before = hashes(value.root)
    device = [DEVICE]
    monkeypatch.setattr(global_gpu, "probe_global_ceres_gpu", lambda *_: device[0])
    monkeypatch.setattr(caspar_probe, "observe_caspar_device", lambda *_: device[0])
    fixture.gpu_log = GPU_LOG
    options = {"calibration_policy": policy}
    cpu = map_run(value, fixture, verified, **options)
    settings = accelerated(gp, ba)
    result = map_run(value, fixture, verified, settings=settings, **options)
    assert result.reconstruction.semantic_digest == cpu.reconstruction.semantic_digest
    assert type(snapshot(value, cpu).route) is MappingRoute
    frozen = snapshot(value, result).route
    assert type(frozen) is GlobalAcceleratedRoute
    assert frozen.backend.positioning_device == (DEVICE if gp != "cpu" else None)
    assert frozen.backend.ba_device == (DEVICE if ba != "cpu" else None)
    assert result.reconstruction.settings_version == 2
    assert result.reconstruction.calibration.policy == policy
    if policy == "preserve_priors":
        assert not any(
            r.argv[0] == "view_graph_calibrator" and len(r.argv) > 2 for r in fixture.requests
        )
    assert map_run(value, fixture, verified, settings=settings, **options).cache_hit
    assert map_run(value, fixture, verified, **options).cache_hit
    hardware = ExecutionHardwareProfile()
    assert (
        mapping_progress_plan(frozen, hardware).signature
        != mapping_progress_plan(snapshot(value, cpu).route, hardware).signature
    )
    device[0] = DEVICE.model_copy(update={"uuid": "d" * 32})
    changed = map_run(value, fixture, verified, settings=settings, **options)
    assert not changed.cache_hit and changed.recipe_key != result.recipe_key
    fixture.gpu_log += "Falling back to CPU-based solvers"
    with pytest.raises(ValueError, match="global_gpu_fallback"):
        map_run(
            value,
            fixture,
            verified,
            settings=settings.model_copy(update={"random_seed": 1}),
            **options,
        )
    assert all(
        r.argv[0] == "global_mapper"
        for r in fixture.requests
        if r.argv[0] in {"global_mapper", "mapper", "hierarchical_mapper"} and len(r.argv) > 2
    )
    unchanged(before)


def test_gpu_device_recheck_refuses_substitution_before_mapper(tmp_path, monkeypatch):
    value, fixture, _, _, verified = mapping_inputs(tmp_path)
    monkeypatch.setattr(global_gpu, "probe_global_ceres_gpu", lambda *_: DEVICE)
    monkeypatch.setattr(
        caspar_probe,
        "observe_caspar_device",
        lambda *_: DEVICE.model_copy(update={"uuid": "d" * 32}),
    )
    with pytest.raises(ValueError, match="gpu_changed"):
        map_run(value, fixture, verified, settings=accelerated(0))
    assert not any(r.argv[0] == "global_mapper" and len(r.argv) > 2 for r in fixture.requests)


def test_a_gpu_solve_does_not_hide_later_cpu_solve_in_same_phase():
    text = (
        "Running global positioning\nSolver Summary\n"
        + SPARSE
        + "Solver Summary\nSparse linear algebra library SUITE_SPARSE\n"
        + "Linear solver SPARSE_SCHUR SPARSE_SCHUR\nGlobal positioning done in 1s\n"
    )
    with pytest.raises(ValueError, match="execution_unverified"):
        global_gpu.require_global_gpu_execution(text, accelerated(0).acceleration)


@pytest.mark.parametrize("missing", ["GlobalMapper.gp_gpu_index", "GlobalMapper.ba_gpu_index"])
def test_missing_subsystem_option_refuses_before_native(tmp_path, missing):
    fixture = MappingFixture(tmp_path)
    fixture.map_help = fixture.map_help.replace("--" + missing + " arg\n", "")
    with pytest.raises(ValueError, match="unverified"):
        fixture.mapping_adapter().prepare(
            "preserve_priors",
            colmap=fixture.exe,
            settings=accelerated(0) if ".gp_" in missing else accelerated(ba=0),
            calibration=None,
        )
    assert not any(r.argv[0] == "global_mapper" and len(r.argv) > 2 for r in fixture.requests)


def test_deep_doctor_records_missing_ceres_cuda_and_cudss_separately(tmp_path, monkeypatch):
    from datetime import UTC, datetime

    from splatforge.application.features_contracts import FeatureCapabilityError
    from splatforge.core.capabilities import FreshnessPolicy

    fixture = MappingFixture(tmp_path)

    def fail(*_):
        raise FeatureCapabilityError("Ceres compiled without CUDA support; compiled without cuDSS")

    monkeypatch.setattr(global_gpu, "probe_global_ceres_gpu", fail)
    report = fixture.mapping_adapter()._capabilities.probe(
        explicit_executable=fixture.exe,
        explicit_model_directory=None,
        bundled_executable=None,
        bundled_model_directory=None,
        deep=True,
        observed_at=datetime.now(UTC),
        freshness=FreshnessPolicy(),
    )
    for subsystem in ("positioning", "ba"):
        for fact in ("runtime", "cuda", "cudss"):
            assert (
                report.capability(f"colmap.global_gpu.{subsystem}.{fact}").status == "unavailable"
            )
        assert report.capability(f"colmap.global_gpu.{subsystem}.integration").status == "unknown"
    assert report.capability("colmap.mapper.global").status == "available"


def test_missing_component_phase_and_cpu_refinement_are_unverified():
    for text in (
        GPU_LOG + "Running global positioning\n",
        GPU_LOG
        + "Running iterative retriangulation and refinement\nSolver Summary\n"
        + "Dense linear algebra library EIGEN\nLinear solver DENSE_SCHUR DENSE_SCHUR\n"
        + "Iterative retriangulation and refinement done in 1s",
    ):
        with pytest.raises(ValueError, match="execution_unverified"):
            global_gpu.require_global_gpu_execution(text, accelerated(0, 0).acceleration)


def test_zero_work_solver_report_does_not_prove_actual_gpu_use():
    text = GPU_LOG.replace("(2)", "(0)")
    with pytest.raises(ValueError, match="execution_unverified"):
        global_gpu.require_global_gpu_execution(text, accelerated(0, 0).acceleration)


def test_positive_gpu_evidence_log_transport_is_a_preflight_requirement(tmp_path):
    fixture = MappingFixture(tmp_path)
    fixture.map_help = fixture.map_help.replace("--log_path arg\n", "")
    with pytest.raises(ValueError, match="unverified"):
        fixture.mapping_adapter().prepare(
            "preserve_priors", colmap=fixture.exe, settings=accelerated(0), calibration=None
        )
    assert not any(r.argv[0] == "global_mapper" and len(r.argv) > 2 for r in fixture.requests)
