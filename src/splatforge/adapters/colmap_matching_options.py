"""Explicit supported COLMAP 4.2.1 options; no raw backend flags escape this adapter."""

from pathlib import Path

from splatforge.adapters.local_models import local_model_argument
from splatforge.application.features_contracts import FeatureCapabilityError
from splatforge.core.geometry import VerificationSettings
from splatforge.core.matching import (
    LearnedBruteforceSettings,
    LightGlueSettings,
    LomaMatchingSettings,
    MatcherSettings,
    SiftBruteforceSettings,
    matcher_model_role,
)

MATCH_MODEL_OPTIONS = {
    "lightglue.sift": "SiftMatching.lightglue_model_path",
    "lightglue.aliked": "AlikedMatching.lightglue_model_path",
    "bruteforce.aliked": "AlikedMatching.bruteforce_model_path",
    "bruteforce.loma": "LomaMatching.brute_force_model_path",
    **{f"loma.matcher.{v}": f"LomaMatching.{v}_model_path" for v in ("b", "b128", "r", "l", "g")},
}


def _arguments(operation: str, options: tuple[str, ...], values: list) -> tuple[str, ...]:
    missing = [name for name, _ in values if name not in options]
    if missing:
        raise FeatureCapabilityError(f"{operation}: unsupported options: " + ", ".join(missing))
    return (operation, *(arg for name, value in values for arg in ("--" + name, str(value))))


def matching_arguments(
    settings: MatcherSettings,
    options: tuple[str, ...],
    *,
    database: Path,
    pairs: Path,
    models: dict[str, Path],
) -> tuple[str, ...]:
    values = [
        ("database_path", database),
        ("match_list_path", pairs),
        ("match_type", "pairs"),
        ("FeatureMatching.type", settings.variant),
        ("FeatureMatching.use_gpu", int(settings.use_gpu)),
        ("FeatureMatching.gpu_index", "0" if settings.use_gpu else "-1"),
        ("FeatureMatching.num_threads", settings.num_threads),
        ("FeatureMatching.max_num_matches", settings.max_num_matches),
        ("FeatureMatching.guided_matching", 0),
        ("FeatureMatching.skip_geometric_verification", 1),
        ("FeatureMatching.rig_verification", 0),
        ("FeatureMatching.skip_image_pairs_in_same_frame", 0),
        # The native controller otherwise discards raw sets smaller than 15 even
        # when verification is skipped. One preserves every nonempty raw set.
        ("TwoViewGeometry.min_num_inliers", 1),
        ("default_random_seed", settings.random_seed),
        ("log_target", "stderr"),
    ]
    if isinstance(settings, SiftBruteforceSettings):
        values.extend(
            [
                ("SiftMatching.max_ratio", settings.max_ratio),
                ("SiftMatching.max_distance", settings.max_distance),
                ("SiftMatching.cross_check", int(settings.cross_check)),
                ("SiftMatching.cpu_brute_force_matcher", int(settings.cpu_brute_force_matcher)),
            ]
        )
    elif isinstance(settings, LightGlueSettings):
        prefix = "SiftMatching" if settings.variant == "SIFT_LIGHTGLUE" else "AlikedMatching"
        values.append((prefix + ".lightglue_min_score", settings.min_score))
    elif isinstance(settings, LearnedBruteforceSettings):
        prefix = "AlikedMatching" if settings.variant == "ALIKED_BRUTEFORCE" else "LomaMatching"
        values.extend(
            [
                (prefix + ".brute_force_min_cossim", settings.min_cossim),
                (prefix + ".brute_force_max_ratio", settings.max_ratio),
                (prefix + ".brute_force_cross_check", int(settings.cross_check)),
            ]
        )
    elif isinstance(settings, LomaMatchingSettings):
        values.extend(
            [("LomaMatching.min_score", settings.min_score), ("LomaMatching.use_bf16", 0)]
        )
    role = matcher_model_role(settings)
    if role:
        values.append((MATCH_MODEL_OPTIONS[role], local_model_argument(models[role])))
    return _arguments("matches_importer", options, values)


def verification_arguments(
    settings: VerificationSettings,
    options: tuple[str, ...],
    *,
    database: Path,
) -> tuple[str, ...]:
    values = [
        ("database_path", database),
        ("num_threads", settings.num_threads),
        ("batch_size", settings.batch_size),
        ("rig_verification", 0),
        ("default_random_seed", settings.random_seed),
        ("log_target", "stderr"),
    ]
    for name, value in settings.model_dump(
        exclude={
            "method_id",
            "settings_version",
            "num_threads",
            "batch_size",
        }
    ).items():
        values.append(("TwoViewGeometry." + name, int(value) if type(value) is bool else value))
    return _arguments("geometric_verifier", options, values)
