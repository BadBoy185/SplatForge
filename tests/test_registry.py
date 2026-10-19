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
