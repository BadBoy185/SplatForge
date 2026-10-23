"""Incremental v1 settings, exact native options, compatibility and portable identity."""

from uuid import UUID

import pytest
from mapping_helpers import incremental_help, mapping_for, write_model
from test_reconstruction_identity import make_set

from splatforge.adapters.colmap_help import parse_option_help
from splatforge.adapters.colmap_mapping_options import incremental_arguments
from splatforge.adapters.colmap_reconstruction import read_components
from splatforge.core.incremental import require_caspar_compatibility
from splatforge.core.reconstruction import (
    GlobalMapperSettings,
    IncrementalMapperSettings,
    MappingCalibrationPolicy,
    mapping_recipe_key,
    reconstruction_semantic_digest,
)


@pytest.mark.parametrize(
    "values",
    [
        {"multiple_models": True},
        {"extract_colors": True},
        {"ba_use_gpu": True},
        {"ba_local_backend": "CASPAR"},
        {"ba_gpu_index": 0},
        {"ba_local_max_num_iterations": 0},
        {"ba_refine_sensor_from_rig": True},
        {"raw_args": []},
        {"num_threads": 0},
    ],
)
def test_incremental_settings_fail_closed(values):
    with pytest.raises(ValueError):
        IncrementalMapperSettings(**values)


def caspar_settings(index=0, **kwargs):
    return IncrementalMapperSettings(
        ba_local_backend="CASPAR", ba_global_backend="CASPAR", ba_gpu_index=index, **kwargs
    )


def test_caspar_requires_concrete_device_and_joint_focal_extra_refinement():
    with pytest.raises(ValueError, match="concrete GPU"):
        caspar_settings(-1)
    with pytest.raises(ValueError, match="focal and extra"):
        caspar_settings(ba_refine_extra_params=False)
    assert not caspar_settings(
        ba_refine_focal_length=False, ba_refine_extra_params=False
    ).ba_refine_focal_length
    value = IncrementalMapperSettings()
    with pytest.raises(ValueError):
        value.multiple_models = True


@pytest.mark.parametrize(
    "model,accepted",
    [
        ("PINHOLE", True),
        ("SIMPLE_RADIAL", True),
        ("SIMPLE_PINHOLE", False),
        ("RADIAL", False),
        ("OPENCV", False),
        ("FULL_OPENCV", False),
    ],
)
def test_verified_421_caspar_camera_support(model, accepted):
    if accepted:
        require_caspar_compatibility((model,))
    else:
        with pytest.raises(ValueError, match=model):
            require_caspar_compatibility(("PINHOLE", model))


def test_caspar_pose_prior_and_rig_refinement_refused():
    with pytest.raises(ValueError, match="pose_priors"):
        require_caspar_compatibility(("PINHOLE",), pose_priors=True)
    with pytest.raises(ValueError, match="rig_refinement"):
        require_caspar_compatibility(("PINHOLE",), non_reference_sensor_refinement=True)


def test_incremental_exact_observed_options_and_no_raw_flags(tmp_path):
    parsed = parse_option_help(incremental_help(), "Mapper")
    assert parsed.recognized
    settings = IncrementalMapperSettings()
    argv = incremental_arguments(
        settings,
        parsed.option_names,
        database=tmp_path / "private.db",
        images=tmp_path / "empty",
        output=tmp_path / "sparse",
    )
    assert argv[0] == "mapper"
    for key in ("multiple_models", "extract_colors", "ba_use_gpu"):
        assert argv[argv.index("--Mapper." + key) + 1] == "0"
    assert argv[argv.index("--Mapper.ba_local_backend") + 1] == "CERES"
    assert argv[argv.index("--Mapper.ba_global_backend") + 1] == "CERES"
    for option in parsed.option_names:
        if option == "log_level":
            continue
        with pytest.raises(ValueError, match="missing_options"):
            incremental_arguments(
                settings,
                tuple(n for n in parsed.option_names if n != option),
                database=tmp_path,
                images=tmp_path,
                output=tmp_path,
            )


def test_mapper_backend_device_and_settings_change_recipe_only():
    def key(settings):
        return mapping_recipe_key(
            "a" * 64, settings, MappingCalibrationPolicy.PRESERVE_PRIORS, None, "b" * 64
        )

    values = [
        GlobalMapperSettings(),
        IncrementalMapperSettings(),
        IncrementalMapperSettings(random_seed=1),
        caspar_settings(),
        caspar_settings(1),
    ]
    assert len({key(v) for v in values}) == len(values)


def test_single_model_portable_semantics_and_native_numbering(tmp_path):
    views = tuple(UUID(int=i) for i in range(1, 5))
    results = []
    for name, offset in (("7", 0), ("900", 1000)):
        root = tmp_path / name
        mapping = mapping_for(views, offset=offset)
        write_model(root / "sparse" / name, mapping, selected=mapping.images[:3])
        value = make_set(mapping, read_components(root, mapping, maximum_components=1))
        results.append(value)
        assert value.unregistered_view_ids == (views[-1],)
    assert results[0].semantic_digest == results[1].semantic_digest
    for method in ("mapping.colmap_global", "mapping.colmap_incremental"):
        changed = results[0].model_copy(update={"method_id": method})
        assert reconstruction_semantic_digest(changed) == results[0].semantic_digest


@pytest.mark.parametrize("overlap", [False, True])
def test_unexpected_multiple_models_always_refused_even_disjoint(tmp_path, overlap):
    mapping = mapping_for(tuple(UUID(int=i) for i in range(1, 7)))
    write_model(tmp_path / "sparse" / "0", mapping, selected=mapping.images[:3])
    write_model(
        tmp_path / "sparse" / "1",
        mapping,
        selected=mapping.images[:3] if overlap else mapping.images[3:],
    )
    with pytest.raises(ValueError, match="unexpected_multiple_models.*overlapping"):
        read_components(tmp_path, mapping, maximum_components=1)


def test_native_incremental_provenance_normalization_preserves_reader(tmp_path):
    from splatforge.adapters.colmap_incremental import normalize_incremental_output

    mapping = mapping_for(tuple(UUID(int=i) for i in range(1, 4)))
    write_model(tmp_path / "sparse" / "9", mapping)
    original = b"[Mapper]\nmultiple_models=false\nextract_colors=false\n"
    (tmp_path / "sparse" / "9" / "project.ini").write_bytes(original)
    normalize_incremental_output(tmp_path)
    assert (tmp_path / "sparse" / "project.ini").read_bytes() == original
    assert read_components(tmp_path, mapping, maximum_components=1)[0].registered_view_count == 3
