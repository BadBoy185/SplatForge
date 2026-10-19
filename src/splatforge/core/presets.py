from splatforge.core.models import FrameSelectionConfig, PipelineConfig, SfMConfig


def recommended_flat_video_profile() -> PipelineConfig:
    return PipelineConfig(
        frame_selection=FrameSelectionConfig(
            method_id="frame_selection.sharpest_interval",
            target_fps=2.0,
            max_frames=1800,
            reject_blur=True,
            reject_duplicates=True,
        ),
        sfm=SfMConfig(
            feature_extractor_id="feature_extraction.aliked",
            pair_selector_id="pair_selection.sequential",
            feature_matcher_id="feature_matching.lightglue_aliked",
            mapper_id="mapping.colmap_global",
        ),
    )
