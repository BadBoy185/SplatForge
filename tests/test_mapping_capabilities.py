"""Production version floor and positive option evidence are independent gates."""

import pytest
from mapping_helpers import calibration_help, mapping_help

from splatforge.adapters.colmap_help import parse_option_help
from splatforge.adapters.colmap_mapping_options import mapping_arguments
from splatforge.adapters.mapping_capabilities import supported_global_version
from splatforge.core.reconstruction import GlobalMapperSettings


@pytest.mark.parametrize(
    "version,expected", [("4.2.0", False), ("4.2.1", True), ("4.3.0", False), ("3.13.0", False)]
)
def test_only_positively_tested_supported_version(version, expected):
    assert supported_global_version("COLMAP " + version + " (Commit test)") is expected


def test_global_requires_exact_multiple_model_and_typed_options(tmp_path):
    help_text = mapping_help()
    parsed = parse_option_help(help_text, "GlobalMapper")
    assert parsed.recognized
    assert parse_option_help(calibration_help(), "ViewGraphCalibration").recognized
    for option in ("GlobalMapper.multiple_models", "GlobalMapper.min_model_size"):
        malformed = help_text.replace("--" + option + " arg\n", "")
        assert not parse_option_help(malformed, "GlobalMapper").recognized
    argv = mapping_arguments(
        GlobalMapperSettings(),
        parsed.option_names,
        database=tmp_path / "p.db",
        images=tmp_path,
        output=tmp_path / "sparse",
    )
    assert argv[argv.index("--GlobalMapper.multiple_models") + 1] == "1"
    assert argv[argv.index("--GlobalMapper.min_model_size") + 1] == "3"
