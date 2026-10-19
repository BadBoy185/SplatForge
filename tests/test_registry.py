import pytest

from splatforge.core import build_builtin_registry, recommended_flat_video_profile


def test_recommended_profile_is_valid() -> None:
    registry = build_builtin_registry()
    registry.validate_pipeline(recommended_flat_video_profile())


def test_rejects_aliked_extractor_with_sift_lightglue() -> None:
    registry = build_builtin_registry()
    config = recommended_flat_video_profile()
    config.sfm.feature_matcher_id = "feature_matching.lightglue_sift"

    with pytest.raises(ValueError, match="Incompatible feature pipeline"):
        registry.validate_pipeline(config)


@pytest.mark.parametrize(
    "section,field",
    [
        ("sfm", "mapper_id"),
        ("sfm", "feature_extractor_id"),
        ("sfm", "pair_selector_id"),
        ("sfm", "feature_matcher_id"),
        ("frame_selection", "method_id"),
    ],
)
def test_roles_are_validated_independently(section: str, field: str) -> None:
    config = recommended_flat_video_profile()
    setattr(getattr(config, section), field, "training.none")
    with pytest.raises(ValueError, match="expected"):
        build_builtin_registry().validate_pipeline(config)
