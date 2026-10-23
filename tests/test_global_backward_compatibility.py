"""Golden CPU v1 settings/recipes and historical mapping.run snapshot transport."""

from pathlib import Path

import pytest

from splatforge.core.execution import MappingRoute, RunSnapshot
from splatforge.core.reconstruction import (
    GlobalMapperSettings,
    ViewGraphCalibrationSettings,
    mapping_recipe_key,
)


@pytest.mark.parametrize(
    "policy,expected",
    [
        ("preserve_priors", "3ec852467034f25113430f4025dd09bf391c1ad92e739381a0be624d67844870"),
        ("view_graph", "9cc10271340afb204ebf823938861445ecc3f9b6bf19f1ea99c6bf84163c2286"),
    ],
)
def test_original_m8a_cpu_recipe_golden(policy, expected):
    # Independently computed by the original M8a implementation at 4ddcfc6.
    assert (
        mapping_recipe_key(
            "a" * 64,
            GlobalMapperSettings(),
            policy,
            ViewGraphCalibrationSettings() if policy == "view_graph" else None,
            "b" * 64,
        )
        == expected
    )


def test_old_global_snapshot_loads_with_unchanged_route_and_settings():
    path = Path(__file__).parent / "fixtures" / "m8a-global-snapshot.json"
    snapshot = RunSnapshot.model_validate_json(path.read_bytes())
    route = snapshot.route
    assert type(route) is MappingRoute
    assert route.route_id == "mapping.run" and route.settings.settings_version == 1
    assert type(route.settings) is GlobalMapperSettings
    assert "acceleration" not in route.settings.model_dump()
    assert not route.settings.gp_use_gpu and not route.settings.ba_ceres_use_gpu
    assert RunSnapshot.model_validate_json(snapshot.model_dump_json()) == snapshot
