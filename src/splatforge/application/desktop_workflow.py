"""Desktop requests compose existing use cases; they own no processing/cache algorithms."""

from collections.abc import Callable
from pathlib import Path
from uuid import UUID

from splatforge.core.features import resolve_extraction_settings
from splatforge.core.matching import resolve_matching_settings
from splatforge.core.media import VerificationPolicyId
from splatforge.core.pairs import PairResourceLimits, PairSettings
from splatforge.core.project import ProjectDocument
from splatforge.core.quality import QualityAnalysisSettings, SharpestIntervalSettings
from splatforge.core.reconstruction import (
    GlobalAcceleratedSettings,
    GlobalMapperSettings,
    HierarchicalMapperSettings,
    IncrementalMapperSettings,
    MapperSettings,
    MappingCalibrationPolicy,
    ViewGraphCalibrationSettings,
)
from splatforge.core.sfm_profiles import (
    FeatureMatchingChoice,
    ResolvedFeatureMatchingRoute,
    SfmQualityProfile,
)
from splatforge.core.validation_policy import ReconstructionValidationPolicy
from splatforge.core.views import (
    CandidateEncodingSettings,
    CandidatePoolSettings,
    CandidateResourceLimits,
    FixedFpsSettings,
    FrozenModel,
    parse_fps,
)

MAPPERS = {
    m().method_id: m
    for m in (GlobalMapperSettings, IncrementalMapperSettings, HierarchicalMapperSettings)
}


class ReconstructionRequest(FrozenModel):
    candidate: CandidatePoolSettings
    selection: FixedFpsSettings | SharpestIntervalSettings
    quality: QualityAnalysisSettings = QualityAnalysisSettings()
    view_limits: CandidateResourceLimits = CandidateResourceLimits()
    pairing: PairSettings
    pair_limits: PairResourceLimits = PairResourceLimits()
    features: FeatureMatchingChoice
    mapper: MapperSettings
    calibration_policy: MappingCalibrationPolicy = MappingCalibrationPolicy.PRESERVE_PRIORS
    calibration_settings: ViewGraphCalibrationSettings | None = None
    validation: ReconstructionValidationPolicy = ReconstructionValidationPolicy()
    profile: SfmQualityProfile | None = None
    views_run: UUID | None = None
    retrieval_run: UUID | None = None


def reconstruction_request(document: ProjectDocument) -> ReconstructionRequest:
    """Resolve known saved slots only. Unknown intent is preserved, never substituted."""
    from pydantic import TypeAdapter

    from splatforge.core.features import FeatureSettings
    from splatforge.core.matching import MatcherSettings

    saved = document.settings
    for slot in (
        saved.frame_selection,
        saved.feature_extraction,
        saved.pair_selection,
        saved.feature_matching,
        saved.mapping,
    ):
        if slot.settings_schema_version != 1:
            raise ValueError(f"Unsupported saved schema for {slot.method_id}")
    frame = saved.frame_selection
    # The historical envelope stores scalar FPS and prototype presentation flags.
    # Recognize that exact shape; newer typed settings are validated without dropping keys.
    legacy = set(frame.settings) <= {"target_fps", "max_frames", "reject_blur", "reject_duplicates"}
    fps = parse_fps(str(frame.settings["target_fps"])) if legacy else None
    if frame.method_id == "frame_selection.sharpest_interval":
        selection = (
            SharpestIntervalSettings(
                target_fps=fps, reject_duplicates=frame.settings.get("reject_duplicates", True)
            )
            if legacy
            else SharpestIntervalSettings.model_validate(frame.settings)
        )
    elif frame.method_id == "frame_selection.fixed_fps":
        selection = (
            FixedFpsSettings(target_fps=fps)
            if legacy
            else FixedFpsSettings.model_validate(frame.settings)
        )
    else:
        raise ValueError(f"Unsupported frame selection: {frame.method_id}")
    extractor_variants = {
        "feature_extraction.sift": "SIFT",
        "feature_extraction.aliked": "ALIKED_N16ROT",
        "feature_extraction.loma_b": "LOMA_B",
        "feature_extraction.loma_b128": "LOMA_B128",
    }
    matcher_variants = {
        "feature_matching.sift_bruteforce": "SIFT_BRUTEFORCE",
        "feature_matching.lightglue_aliked": "ALIKED_LIGHTGLUE",
        "feature_matching.lightglue": "ALIKED_LIGHTGLUE",
        "feature_matching.loma_b": "LOMA_B",
        "feature_matching.loma_b128": "LOMA_B128",
        "feature_matching.loma_r": "LOMA_R",
        "feature_matching.loma_l": "LOMA_L",
        "feature_matching.loma_g": "LOMA_G",
    }
    extractor = (
        TypeAdapter(FeatureSettings).validate_python(saved.feature_extraction.settings)
        if saved.feature_extraction.settings
        else resolve_extraction_settings(extractor_variants[saved.feature_extraction.method_id])
    )
    matcher = (
        TypeAdapter(MatcherSettings).validate_python(saved.feature_matching.settings)
        if saved.feature_matching.settings
        else resolve_matching_settings(matcher_variants[saved.feature_matching.method_id])
    )
    pairing = TypeAdapter(PairSettings).validate_python(
        {"method_id": saved.pair_selection.method_id, **saved.pair_selection.settings}
    )
    mapper_type = (
        GlobalAcceleratedSettings
        if saved.mapping.method_id == "mapping.colmap_global"
        and saved.mapping.settings.get("settings_version") == 2
        else MAPPERS[saved.mapping.method_id]
    )
    mapper = mapper_type.model_validate(saved.mapping.settings)
    # The candidate pool has no ProjectDocument slot; resolve the required density visibly.
    density = selection.target_fps.as_fraction() * (
        2 if isinstance(selection, SharpestIntervalSettings) else 1
    )
    return ReconstructionRequest(
        candidate=CandidatePoolSettings(
            candidate_fps=parse_fps(str(density)), encoding=CandidateEncodingSettings()
        ),
        selection=selection,
        pairing=pairing,
        features=FeatureMatchingChoice(extractor=extractor, matcher=matcher),
        mapper=mapper,
    )


def plan_reconstruction(
    facade, root: Path, request: ReconstructionRequest, colmap: Path | None, models: Path | None
) -> dict:
    resolution = facade.service("profiles").resolve(
        profile=request.profile,
        choice=None if request.profile else request.features,
        colmap=colmap,
        model_directory=models,
    )
    doctor = facade.service("doctor").report(colmap=colmap, model_directory=models)
    mapper_backend = facade.service("mapping").capability(
        request.mapper, colmap, request.calibration_policy, request.calibration_settings
    )
    overview = facade.overview(root)
    warnings = []
    if not overview.sources and request.views_run is None:
        warnings.append("No registered sources or explicit published views run")
    if request.pairing.method_id in {"pair_selection.retrieval", "pair_selection.hybrid"} and (
        request.retrieval_run is None
    ):
        warnings.append("Offline retrieval/hybrid requires an explicit published retrieval run")
    return {
        "request": request.model_dump(mode="json"),
        "resolved_feature_matching": resolution.model_dump(mode="json"),
        "capability": doctor.model_dump(mode="json"),
        "sources": len(overview.sources),
        "mapper": request.mapper.method_id,
        "mapper_capability": mapper_backend.model_dump(mode="json"),
        "runnable": not warnings,
        "validation_warnings": warnings,
        "tools": {
            "colmap": str(colmap) if colmap else None,
            "models": str(models) if models else None,
        },
        "pairing_status": (
            "reference/exhaustive"
            if request.pairing.method_id.endswith("exhaustive")
            else "sequential"
            if request.pairing.method_id.endswith("sequential")
            else "offline retrieval; production VPR remains pending"
        ),
        "selected_views": "Known after view preparation"
        if not request.views_run
        else "Use exact selected-view artifact in the chosen run",
        "pair_count": "Known after PairSet construction",
        "disk_estimate": "Unavailable: no aggregate reconstruction disk planner exists",
        "cache": "Validated independently by each existing stage during execution",
    }


def run_reconstruction(
    facade,
    root: Path,
    request: ReconstructionRequest,
    colmap: Path | None,
    models: Path | None,
    checkpoint: Callable,
    resolution: ResolvedFeatureMatchingRoute | None = None,
) -> dict:
    checkpoint()
    route = resolution or facade.service("profiles").resolve(
        profile=request.profile,
        choice=None if request.profile else request.features,
        colmap=colmap,
        model_directory=models,
    )
    views_run = request.views_run
    if views_run is None:
        result = facade.service("views").prepare(
            root,
            candidate_settings=request.candidate,
            selection_settings=request.selection,
            quality_settings=request.quality
            if isinstance(request.selection, SharpestIntervalSettings)
            else None,
            resource_limits=request.view_limits,
            verification_policy=VerificationPolicyId.BALANCED_LOCAL,
        )
        _require_success(result)
        views_run = result.run_id
    checkpoint()
    pairs = facade.service("pairs").build(
        root,
        views_run_id=views_run,
        settings=request.pairing,
        resource_limits=request.pair_limits,
        retrieval_run_id=request.retrieval_run,
    )
    _require_success(pairs)
    checkpoint()
    features = facade.service("features").extract(
        root,
        views_run_id=views_run,
        settings=route.choice.extractor,
        colmap=colmap,
        model_directory=models,
    )
    _require_success(features)
    checkpoint()
    matches = facade.service("matching").match(
        root,
        features_run_id=features.run_id,
        pairs_run_id=pairs.run_id,
        settings=route.choice.matcher,
        colmap=colmap,
        model_directory=models,
        resolution=route,
    )
    _require_success(matches)
    checkpoint()
    verified = facade.service("matching").verify(
        root,
        matches_run_id=matches.run_id,
        settings=route.choice.verification,
        colmap=colmap,
        resolution=route,
    )
    _require_success(verified)
    checkpoint()
    mapped = facade.service("mapping").run(
        root,
        verification_run_id=verified.run_id,
        settings=request.mapper,
        colmap=colmap,
        calibration_policy=request.calibration_policy,
        calibration_settings=request.calibration_settings,
    )
    _require_success(mapped)
    checkpoint()
    validated = facade.service("validation").validate(
        root, mapping_run_id=mapped.run_id, policy=request.validation
    )
    _require_success(validated)
    return {
        "mapping_run": str(mapped.run_id),
        "validation_run": str(validated.run_id),
        "validation": validated.report.model_dump(mode="json"),
        "next_action": "Review validation, then request a recommendation or select components",
    }


def _require_success(result) -> None:
    if result.status == "cancelled":
        from splatforge.application.execution import ExecutionCancelledError

        raise ExecutionCancelledError()
    if result.status != "succeeded":
        raise ValueError(f"Operation ended with {result.status}; inspect run {result.run_id}")
