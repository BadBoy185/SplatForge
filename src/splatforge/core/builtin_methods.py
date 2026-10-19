from splatforge.core.models import MethodSpec, StageKind
from splatforge.core.registry import MethodRegistry


def build_builtin_registry() -> MethodRegistry:
    registry = MethodRegistry()
    methods = [
        MethodSpec(id="frame_selection.sharpest_interval", display_name="Sharpest frame per interval", stage=StageKind.FRAME_SELECTION),
        MethodSpec(id="frame_selection.fixed_fps", display_name="Fixed FPS", stage=StageKind.FRAME_SELECTION),
        MethodSpec(id="feature_extraction.aliked", display_name="ALIKED", stage=StageKind.FEATURE_EXTRACTION, descriptor_family="aliked"),
        MethodSpec(id="feature_extraction.sift", display_name="SIFT", stage=StageKind.FEATURE_EXTRACTION, descriptor_family="sift"),
        MethodSpec(id="pair_selection.sequential", display_name="Sequential", stage=StageKind.PAIR_SELECTION),
        MethodSpec(id="pair_selection.exhaustive", display_name="Exhaustive", stage=StageKind.PAIR_SELECTION),
        MethodSpec(id="pair_selection.vocab_tree", display_name="Vocabulary tree / retrieval", stage=StageKind.PAIR_SELECTION),
        MethodSpec(id="pair_selection.spatial", display_name="Spatial / GPS", stage=StageKind.PAIR_SELECTION),
        MethodSpec(id="feature_matching.lightglue_aliked", display_name="LightGlue (ALIKED)", stage=StageKind.FEATURE_MATCHING, accepts_descriptor_families=frozenset({"aliked"})),
        MethodSpec(id="feature_matching.lightglue_sift", display_name="LightGlue (SIFT)", stage=StageKind.FEATURE_MATCHING, accepts_descriptor_families=frozenset({"sift"})),
        MethodSpec(id="mapping.colmap_global", display_name="COLMAP Global Mapper", stage=StageKind.MAPPING),
        MethodSpec(id="mapping.colmap_incremental", display_name="COLMAP Incremental Mapper", stage=StageKind.MAPPING),
        MethodSpec(id="mapping.colmap_hierarchical", display_name="COLMAP Hierarchical Mapper", stage=StageKind.MAPPING),
        MethodSpec(id="training.none", display_name="Export training dataset only", stage=StageKind.TRAINING),
        MethodSpec(id="training.lichtfeld_external", display_name="LichtFeld Studio (external)", stage=StageKind.TRAINING),
        MethodSpec(id="training.gsplat", display_name="gsplat", stage=StageKind.TRAINING, experimental=True),
    ]
    for method in methods:
        registry.register(method)
    return registry
