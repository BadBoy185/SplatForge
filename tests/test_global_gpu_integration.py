"""Opt-in GPU smoke only when the provisioned Ceres runtime is positively runnable."""

import json
import os
from pathlib import Path
from time import monotonic

import pytest
from hierarchical_helpers import real_mapping_input
from test_incremental_execution import unchanged
from test_matching_execution import hashes

from splatforge.adapters.colmap_mapping import ColmapMappingAdapter
from splatforge.application.features_contracts import FeatureCapabilityError
from splatforge.application.mapping import MappingService
from splatforge.core.reconstruction import GlobalAcceleratedSettings, GlobalAccelerationSettings


@pytest.mark.integration
@pytest.mark.parametrize("gp,ba", [(True, False), (False, True), (True, True)])
def test_real_global_gpu_transport(tmp_path, monkeypatch, record_property, gp, ba):
    configured = os.environ.get("SPLATFORGE_TEST_COLMAP")
    if not configured or os.environ.get("SPLATFORGE_TEST_GLOBAL_GPU") != "1":
        pytest.skip("Set SPLATFORGE_TEST_COLMAP and SPLATFORGE_TEST_GLOBAL_GPU=1")
    executable = Path(configured)
    index = int(os.environ.get("SPLATFORGE_TEST_GLOBAL_GPU_INDEX", "0"))
    settings = GlobalAcceleratedSettings(
        acceleration=GlobalAccelerationSettings(
            positioning_device=index if gp else "cpu", ba_device=index if ba else "cpu"
        )
    )
    adapter = ColmapMappingAdapter()
    try:
        backend = adapter.prepare(
            "preserve_priors", colmap=executable, settings=settings, calibration=None
        )
    except FeatureCapabilityError as exc:
        pytest.skip("Global GPU capability unavailable/unverified: " + str(exc))
    # Native pinned GP/BA switch to GPU only at >=50 views. Tiny 3-view success is insufficient.
    value, verified, geometry = real_mapping_input(tmp_path, monkeypatch, executable, count=60)
    before = hashes(value.root)
    service = MappingService(value.execution, adapter)
    started = monotonic()
    try:
        result = service.run(
            value.root, verification_run_id=verified.run_id, settings=settings, colmap=executable
        )
    except FeatureCapabilityError as exc:
        if "execution_unverified" in str(exc):
            pytest.skip("Global GPU real integration unverified: " + str(exc))
        raise
    api_seconds = monotonic() - started
    assert result.diagnostics["gp_gpu_validated"] == gp
    assert result.diagnostics["ba_gpu_validated"] == ba
    assert result.diagnostics["fallback_evidence_absent"]
    assert tuple(service.reader(value.root, result.run_id).components())
    unchanged(before)
    assert service.run(
        value.root, verification_run_id=verified.run_id, settings=settings, colmap=executable
    ).cache_hit
    metrics = {
        "gp_requested": gp,
        "ba_requested": ba,
        **result.diagnostics,
        "device_gp": backend.positioning_device.model_dump() if gp else None,
        "device_ba": backend.ba_device.model_dump() if ba else None,
        "views": 60,
        "verified_pairs": geometry.accepted_pair_count,
        "components": result.reconstruction.component_count,
        "registered": result.reconstruction.registered_view_count,
        "unregistered": result.reconstruction.unregistered_view_count,
        "points": [c.point_count for c in result.reconstruction.components],
        "native_seconds": result.native_seconds,
        "api_seconds": api_seconds,
        "cache_hit": True,
    }
    record_property("m8b2_global_gpu", json.dumps(metrics))
    print(json.dumps(metrics))
