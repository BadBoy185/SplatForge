"""Command/options/version presence is independent of mapping and integration evidence."""

import pytest
from dataset_helpers import configure
from mapping_helpers import MappingFixture

from splatforge.adapters.colmap_capabilities import ColmapCapabilityAdapter
from splatforge.adapters.colmap_dataset import ColmapDatasetAdapter
from splatforge.core.dataset import DatasetSettings


@pytest.mark.parametrize("problem", [None, "command", "option", "version", "later_version"])
def test_undistorter_requires_own_positive_capability(tmp_path, problem):
    fixture = MappingFixture(tmp_path)
    configure(fixture)
    if problem == "command":
        fixture.top_help = fixture.top_help.replace("image_undistorter", "image_other")
    elif problem == "option":
        fixture.dataset_help = fixture.dataset_help.replace("--max_image_size arg", "")
    elif problem in {"version", "later_version"}:
        fixture.top_help = fixture.top_help.replace(
            "4.2.1", "4.2.0" if problem == "version" else "4.3.0"
        )
    adapter = ColmapDatasetAdapter(
        runner=fixture,
        resolver=fixture.resolver,
        capability_adapter=ColmapCapabilityAdapter(runner=fixture, resolver=fixture.resolver),
    )
    if problem:
        with pytest.raises(ValueError, match="capability_unavailable"):
            adapter.prepare_backend(DatasetSettings(), fixture.exe)
    else:
        backend = adapter.prepare_backend(DatasetSettings(), fixture.exe)
        assert "max_image_size" in backend.option_names
        assert len(backend.numerical_identity) == 64
