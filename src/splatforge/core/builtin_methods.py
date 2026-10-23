from splatforge.core.models import MethodSpec, StageKind
from splatforge.core.registry import MethodRegistry


def build_builtin_registry() -> MethodRegistry:
    registry = MethodRegistry()
    methods = [
        MethodSpec(
            id="quality_assessment.pillow_edge_dhash",
            display_name="Pillow edge variance and dHash",
            stage=StageKind.QUALITY_ASSESSMENT,
        ),
        MethodSpec(
            id="frame_selection.sharpest_interval",
            display_name="Sharpest frame per interval",
            stage=StageKind.FRAME_SELECTION,
        ),
        MethodSpec(
            id="frame_selection.fixed_fps",
            display_name="Fixed FPS",
            stage=StageKind.FRAME_SELECTION,
        ),
        MethodSpec(
            id="feature_extraction.aliked",
            display_name="ALIKED",
            stage=StageKind.FEATURE_EXTRACTION,
            descriptor_family="aliked",
        ),
        MethodSpec(
            id="feature_extraction.sift",
            display_name="SIFT",
            stage=StageKind.FEATURE_EXTRACTION,
            descriptor_family="sift",
        ),
        MethodSpec(
            id="feature_extraction.loma_b", display_name="LoMa B",
            stage=StageKind.FEATURE_EXTRACTION, descriptor_family="loma_b",
            notes="M7a native extraction; verified COLMAP >=4.2.1 and local ONNX models required",
        ),
        MethodSpec(
            id="feature_extraction.loma_b128", display_name="LoMa B128",
            stage=StageKind.FEATURE_EXTRACTION, descriptor_family="loma_b128",
            notes="M7a native extraction; verified COLMAP >=4.2.1 and local ONNX models required",
        ),
        MethodSpec(
            id="pair_selection.sequential",
            display_name="Sequential",
            stage=StageKind.PAIR_SELECTION,
            notes="Implemented v1; metadata-only via pairs build; no COLMAP/GPU required",
        ),
        MethodSpec(
            id="pair_selection.exhaustive",
            display_name="Exhaustive",
            stage=StageKind.PAIR_SELECTION,
            notes="Implemented v1; metadata-only via pairs build; no COLMAP/GPU required",
        ),
        MethodSpec(
            id="pair_selection.vocab_tree",
            display_name="Vocabulary tree / retrieval",
            stage=StageKind.PAIR_SELECTION,
            notes="Catalog only; not implemented or runnable",
        ),
        *(MethodSpec(
            id=f"pair_selection.{name}", display_name=name.title(),
            stage=StageKind.PAIR_SELECTION,
            notes="Implemented v1 with explicit immutable offline retrieval representation; "
                  "production neural model selection pending representative M7b benchmark",
        ) for name in ("retrieval", "hybrid")),
        MethodSpec(
            id="pair_selection.spatial",
            display_name="Spatial / GPS",
            stage=StageKind.PAIR_SELECTION,
            notes="Catalog only; not implemented or runnable",
        ),
        MethodSpec(
            id="feature_matching.lightglue_aliked",
            display_name="LightGlue (ALIKED)",
            stage=StageKind.FEATURE_MATCHING,
            accepts_descriptor_families=frozenset({"aliked"}),
        ),
        MethodSpec(
            id="feature_matching.lightglue_sift",
            display_name="LightGlue (SIFT)",
            stage=StageKind.FEATURE_MATCHING,
            accepts_descriptor_families=frozenset({"sift"}),
        ),
        MethodSpec(
            id="mapping.colmap_global", display_name="COLMAP Global Mapper",
            stage=StageKind.MAPPING,
            notes=("Implemented M8a/M8b2: tested 4.2.1, explicit calibration "
                   "and separate GP/BA GPU gates")
        ),
        MethodSpec(
            id="feature_matching.sift_bruteforce", display_name="SIFT brute-force",
            stage=StageKind.FEATURE_MATCHING, accepts_descriptor_families=frozenset({"sift"}),
        ),
        MethodSpec(
            id="feature_matching.aliked_bruteforce", display_name="ALIKED brute-force",
            stage=StageKind.FEATURE_MATCHING, accepts_descriptor_families=frozenset({"aliked"}),
        ),
        *(MethodSpec(
            id=f"feature_matching.loma_{variant}", display_name=f"LoMa {variant.upper()}",
            stage=StageKind.FEATURE_MATCHING,
            accepts_descriptor_families=frozenset(
                {"loma_b", "loma_b128"} if variant == "bruteforce" else
                {"loma_b128"} if variant == "b128" else {"loma_b"}),
            notes="Production native route; verified COLMAP >=4.2.1 and pinned local models",
        ) for variant in ("bruteforce", "b", "b128", "r", "l", "g")),
        MethodSpec(
            id="geometric_verification.colmap", display_name="COLMAP geometric verification",
            stage=StageKind.GEOMETRIC_VERIFICATION,
        ),
        MethodSpec(
            id="mapping.colmap_incremental",
            display_name="COLMAP Incremental Mapper",
            stage=StageKind.MAPPING,
            notes="Implemented M8b1: single model, CPU Ceres or capability-gated Caspar BA",
        ),
        MethodSpec(
            id="mapping.colmap_hierarchical",
            display_name="COLMAP Hierarchical Mapper",
            stage=StageKind.MAPPING,
            notes="Implemented M8b2: internal clusters, native merge, disjoint final components",
        ),
        MethodSpec(
            id="validation.sparse_measurements_v1",
            display_name="Reconstruction measurements",
            stage=StageKind.VALIDATION,
            notes="Implemented M9a: local normalized geometry, explicit metric availability; "
                  "no COLMAP executable/GPU required to read existing artifacts",
        ),
        MethodSpec(
            id="validation.policy_v1", display_name="Reconstruction validation policy",
            stage=StageKind.VALIDATION,
            notes="Implemented M9a: baseline_v1/custom_v1 over immutable measurements",
        ),
        MethodSpec(
            id="selection.dominance_v1", display_name="Conservative component dominance",
            stage=StageKind.RECONSTRUCTION_SELECTION,
            notes="Implemented M9b: explicit coverage/severity dominance; ambiguous alternatives "
                  "require manual selection; no score or largest-component tie-break",
        ),
        MethodSpec(
            id="training.none",
            display_name="Export training dataset only",
            stage=StageKind.TRAINING,
        ),
        MethodSpec(
            id="training.lichtfeld_external",
            display_name="LichtFeld Studio (external)",
            stage=StageKind.TRAINING,
        ),
        MethodSpec(
            id="training.gsplat", display_name="gsplat", stage=StageKind.TRAINING, experimental=True
        ),
    ]
    for method in methods:
        registry.register(method)
    return registry
