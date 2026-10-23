"""Hierarchical settings, exact 4.2.1 flags, resource bounds and neutral semantics."""

from uuid import UUID

import pytest
from mapping_helpers import hierarchical_help, mapping_for, write_model
from test_reconstruction_identity import make_set

from splatforge.adapters.colmap_help import parse_option_help
from splatforge.adapters.colmap_mapping_options import hierarchical_arguments
from splatforge.adapters.colmap_reconstruction import read_components
from splatforge.core.reconstruction import (
    HierarchicalClusterSettings,
    HierarchicalMapperSettings,
    MappingInput,
    MappingResourceLimits,
    estimate_mapping_resources,
    mapping_recipe_key,
    reconstruction_semantic_digest,
)


@pytest.mark.parametrize(
    "values",
    [
        {"branching": 3},
        {"branching": 1},
        {"num_workers": 2},
        {"num_threads": 0},
        {"leaf_max_num_images": 2},
        {"raw_flags": []},
        {"num_image_matches": 0},
        {"cluster": {"extract_colors": True}},
        {"cluster": {"num_threads": 4}},
        {"cluster": {"ba_local_backend": "CASPAR", "ba_global_backend": "CASPAR"}},
        {"cluster": {"init_num_trials": 400}},
    ],
)
def test_hierarchical_settings_fail_closed(values):
    with pytest.raises(ValueError):
        HierarchicalMapperSettings(**values)


def test_exact_hierarchy_and_internal_mapper_options(tmp_path):
    settings = HierarchicalMapperSettings(num_threads=4, num_workers=2)
    options = parse_option_help(hierarchical_help(), "HierarchicalMapper")
    assert options.recognized
    argv = hierarchical_arguments(
        settings,
        options.option_names,
        database=tmp_path / "p.db",
        images=tmp_path / "empty",
        output=tmp_path / "sparse",
    )
    assert argv[0] == "hierarchical_mapper"
    for name in (
        "init_num_trials",
        "num_threads",
        "num_workers",
        "is_hierarchical",
        "branching",
        "image_overlap",
        "num_image_matches",
        "leaf_max_num_images",
    ):
        assert "--HierarchicalMapper." + name in argv
    assert "--Mapper.num_threads" not in argv
    assert "--Mapper.init_num_trials" not in argv
    assert argv[argv.index("--Mapper.multiple_models") + 1] == "1"
    assert argv[argv.index("--Mapper.extract_colors") + 1] == "0"
    assert settings.cluster.multiple_models
    for option in argv[1::2]:
        with pytest.raises(ValueError, match="missing_options"):
            hierarchical_arguments(
                settings,
                tuple(n for n in options.option_names if "--" + n != option),
                database=tmp_path,
                images=tmp_path,
                output=tmp_path,
            )


def test_hierarchy_reservation_and_recipe_exclude_limits():
    value = MappingInput(
        view_ids=tuple(UUID(int=i) for i in range(1, 20)),
        cameras_digest="a" * 64,
        keypoints_digest="b" * 64,
        geometry_digest="c" * 64,
        verified_pair_count=30,
        keypoint_count=200,
        inlier_count=100,
    )
    a = HierarchicalMapperSettings()
    b = HierarchicalMapperSettings(leaf_max_num_images=4, num_threads=4, num_workers=2)
    limits = MappingResourceLimits()
    plain = estimate_mapping_resources(value, 1000, limits)
    x = estimate_mapping_resources(value, 1000, limits, a)
    y = estimate_mapping_resources(value, 1000, limits, b)
    assert plain.peak_workspace_bytes < x.peak_workspace_bytes < y.peak_workspace_bytes
    with pytest.raises(ValueError, match="resource_limit"):
        estimate_mapping_resources(
            value,
            1000,
            limits.model_copy(update={"max_workspace_bytes": y.peak_workspace_bytes - 1}),
            b,
        )

    def key(s):
        return mapping_recipe_key(value.semantic_digest, s, "preserve_priors", None, "d" * 64)

    assert key(a) != key(b)
    assert key(a) != key(
        HierarchicalMapperSettings(cluster=HierarchicalClusterSettings(random_seed=1))
    )


def test_final_numbering_and_method_do_not_enter_portable_identity(tmp_path):
    mapping = mapping_for(tuple(UUID(int=i) for i in range(1, 8)))
    values = []
    for root, names in ((tmp_path / "a", ("0", "2")), (tmp_path / "b", ("99", "400"))):
        for name, selected in zip(names, (mapping.images[:3], mapping.images[3:6]), strict=True):
            write_model(root / "sparse" / name, mapping, selected=selected)
        values.append(make_set(mapping, read_components(root, mapping)))
    assert values[0].semantic_digest == values[1].semantic_digest
    for method in (
        "mapping.colmap_hierarchical",
        "mapping.colmap_global",
        "mapping.colmap_incremental",
    ):
        assert (
            reconstruction_semantic_digest(values[0].model_copy(update={"method_id": method}))
            == values[0].semantic_digest
        )
    assert values[0].unregistered_view_ids == (UUID(int=7),)
