from __future__ import annotations

import os
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest

from splatforge.adapters.colmap_capabilities import ColmapCapabilityAdapter
from splatforge.adapters.colmap_runtime import scoped_runtime_environment
from splatforge.core.capabilities import CapabilityStatus, FreshnessPolicy


@pytest.mark.integration
def test_configured_real_colmap_capability_report(
    record_property: Callable[[str, object], None],
) -> None:
    configured = os.environ.get("SPLATFORGE_TEST_COLMAP")
    if not configured:
        pytest.skip("set SPLATFORGE_TEST_COLMAP to opt into the real COLMAP probe")
    if configured == "1":
        explicit = None
    else:
        explicit = Path(configured)
        if not explicit.is_absolute():
            pytest.fail("SPLATFORGE_TEST_COLMAP must be an absolute path or 1")
    adapter = ColmapCapabilityAdapter()
    now = datetime.now(UTC)
    report = adapter.probe(
        explicit_executable=explicit,
        explicit_model_directory=(
            Path(value) if (value := os.environ.get("SPLATFORGE_COLMAP_MODEL_DIR")) else None
        ),
        bundled_executable=None,
        bundled_model_directory=None,
        deep=False,
        observed_at=now,
        freshness=FreshnessPolicy(),
    )
    assert report.binary.status == CapabilityStatus.AVAILABLE
    assert report.selected_executable is not None
    assert report.selected_executable.identity.version_line
    record_property("colmap_path", report.selected_executable.identity.resolved_path)
    record_property("colmap_sha256", report.selected_executable.identity.sha256)
    record_property("colmap_version", report.selected_executable.identity.version_line)
    record_property("colmap_commands", report.command_discovery.commands)
    record_property("colmap_onnx", report.capability("colmap.onnx").model_dump_json())
    record_property("colmap_models", [item.model_dump(mode="json") for item in report.models])
    assert "database_creator" in report.command_discovery.commands
    database = adapter._probe_database(
        report.selected_executable.identity,
        report.command_discovery.commands,
        now,
        FreshnessPolicy(),
        scoped_runtime_environment(report.selected_executable.runtime_layout, os.environ),
    )
    assert database.evidence.status == CapabilityStatus.AVAILABLE
    record_property("colmap_database", database.model_dump_json())
    for kind, command in (
        ("global", "global_mapper"),
        ("incremental", "mapper"),
        ("hierarchical", "hierarchical_mapper"),
    ):
        evidence = report.capability(f"colmap.mapper.{kind}")
        expected = (
            CapabilityStatus.AVAILABLE
            if command in report.command_discovery.commands
            else CapabilityStatus.UNAVAILABLE
        )
        assert evidence.status == expected
        record_property(f"colmap_mapper_{kind}", evidence.model_dump_json())
    if os.environ.get("SPLATFORGE_TEST_COLMAP_DEEP") == "1":
        deep = adapter.probe(
            explicit_executable=explicit,
            explicit_model_directory=None,
            bundled_executable=None,
            bundled_model_directory=None,
            deep=True,
            observed_at=datetime.now(UTC),
            freshness=FreshnessPolicy(),
        )
        cpu = deep.capability("colmap.feature.sift.cpu")
        gpu = deep.capability("colmap.feature.sift.gpu")
        record_property("colmap_cpu_sift", cpu.model_dump_json())
        record_property("colmap_gpu_sift", gpu.model_dump_json())
        assert cpu.status == CapabilityStatus.AVAILABLE, cpu.message
        if os.environ.get("SPLATFORGE_TEST_COLMAP_REQUIRE_GPU") == "1":
            assert gpu.status == CapabilityStatus.AVAILABLE, gpu.message
