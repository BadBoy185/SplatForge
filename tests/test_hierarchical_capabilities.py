"""Hierarchy capability does not follow from Incremental or a version string alone."""

import pytest
from mapping_helpers import MappingFixture
from test_caspar_capabilities import probe

from splatforge.core.reconstruction import HierarchicalMapperSettings


@pytest.mark.parametrize(
    "missing", ["command", "hierarchy_option", "mapper_option", "version", "log_transport"]
)
def test_required_hierarchical_evidence_is_independent(tmp_path, missing):
    fixture = MappingFixture(tmp_path)
    if missing == "command":
        fixture.top_help = fixture.top_help.replace("  hierarchical_mapper\n", "")
    elif missing == "hierarchy_option":
        fixture.hier_help = fixture.hier_help.replace(
            "--HierarchicalMapper.image_overlap arg\n", ""
        )
    elif missing == "log_transport":
        fixture.hier_help = fixture.hier_help.replace("--log_path arg\n", "")
    elif missing == "mapper_option":
        fixture.hier_help = fixture.hier_help.replace("--Mapper.extract_colors arg\n", "")
    else:
        fixture.top_help = fixture.top_help.replace("4.2.1", "4.3.0")
    with pytest.raises(ValueError, match="capability"):
        fixture.mapping_adapter().prepare(
            "preserve_priors",
            colmap=fixture.exe,
            settings=HierarchicalMapperSettings(),
            calibration=None,
        )
    assert not any(r.argv[0] == "hierarchical_mapper" and len(r.argv) > 2 for r in fixture.requests)


def test_hierarchy_help_and_integration_are_distinct(tmp_path):
    fixture = MappingFixture(tmp_path)
    report = probe(fixture)
    assert report.capability("colmap.mapper.hierarchical").status == "available"
    assert report.capability("colmap.mapper.hierarchical.version").status == "available"
    assert report.capability("colmap.mapper.hierarchical.integration").status == "unknown"


def test_absent_colmap_reports_unavailable_instead_of_missing_capability_key(tmp_path):
    from datetime import UTC, datetime

    from splatforge.adapters.colmap_capabilities import ColmapCapabilityAdapter
    from splatforge.adapters.colmap_mapping import ColmapMappingAdapter
    from splatforge.application.features_contracts import FeatureCapabilityError
    from splatforge.core.capabilities import FreshnessPolicy

    capabilities = ColmapCapabilityAdapter(environment={})
    missing = tmp_path / "missing-colmap.exe"
    report = capabilities.probe(
        explicit_executable=missing,
        explicit_model_directory=None,
        bundled_executable=None,
        bundled_model_directory=None,
        deep=False,
        observed_at=datetime.now(UTC),
        freshness=FreshnessPolicy(),
    )
    for fact in (
        "colmap.mapper.hierarchical",
        "colmap.mapper.hierarchical.version",
        "colmap.mapper.hierarchical.integration",
    ):
        assert report.capability(fact).status == "unavailable"
    for subsystem in ("positioning", "ba"):
        for fact in ("options", "runtime", "cuda", "cudss", "integration"):
            assert (
                report.capability(f"colmap.global_gpu.{subsystem}.{fact}").status == "unavailable"
            )
    with pytest.raises(FeatureCapabilityError, match="incompatible_capability"):
        ColmapMappingAdapter(capability_adapter=capabilities).prepare(
            "preserve_priors",
            colmap=missing,
            settings=HierarchicalMapperSettings(),
            calibration=None,
        )
