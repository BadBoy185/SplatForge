"""Explicit M3/M4/M6 diagnostic work models; never used by recipe construction."""

from __future__ import annotations

import hashlib
import math
import platform
from fractions import Fraction

from splatforge.core.execution import (
    FeatureExtractionRoute,
    FeatureMatchingRoute,
    GeometricVerificationRoute,
    MappingRoute,
    PairSelectionRoute,
    RetrievalBuildRoute,
    SharpestViewPreparationRoute,
    ViewPreparationRoute,
)
from splatforge.core.media import MediaType
from splatforge.core.pairs import (
    ExhaustiveSettings,
    HybridPairSettings,
    RetrievalPairSettings,
    exhaustive_pair_count,
)
from splatforge.core.progress import (
    ExecutionHardwareProfile,
    PerformanceBackendIdentity,
    PerformanceSignature,
    PlannedStage,
    ProgressMode,
    WorkDescription,
    WorkMetric,
    WorkUnit,
)
from splatforge.core.views import (
    FFMPEG_ADAPTER_ID,
    FFMPEG_ADAPTER_VERSION,
    CandidateViewSet,
    canonical_json_bytes,
)


def performance_settings_key(settings: object) -> str:
    return hashlib.sha256(canonical_json_bytes(settings)).hexdigest()


def _stage(
    *,
    node_id: str,
    stage_id: str,
    method_id: str,
    model: str,
    unit: WorkUnit,
    total: float | None,
    backend: PerformanceBackendIdentity,
    settings: object,
    metrics: dict[str, float],
    hardware: ExecutionHardwareProfile,
) -> PlannedStage:
    work = WorkDescription(
        node_id=node_id,
        stage_id=stage_id,
        method_id=method_id,
        work_model_id=model,
        unit=unit,
        total=total,
        mode=(ProgressMode.DETERMINATE if total is not None else ProgressMode.INDETERMINATE),
    )
    return PlannedStage(
        work=work,
        signature=PerformanceSignature(
            stage_id=stage_id,
            method_id=method_id,
            work_model_id=model,
            unit=unit,
            hardware=hardware,
            backend=backend,
            settings_key=performance_settings_key(settings),
        ),
        workload=tuple(
            WorkMetric(name=name, value=value) for name, value in sorted(metrics.items())
        ),
    )


def python_backend(adapter: str) -> PerformanceBackendIdentity:
    return PerformanceBackendIdentity(
        adapter_id=adapter,
        family="python",
        runtime_version=platform.python_version(),
    )


def candidate_source_work(
    route: ViewPreparationRoute | SharpestViewPreparationRoute,
) -> tuple[float, ...]:
    """Retained output MP upper plan, refined explicitly to actual MP on success."""
    work = []
    for source in route.sources:
        count = 1
        if source.media_type == MediaType.VIDEO:
            count = (
                math.ceil(
                    Fraction(source.probe.duration)
                    * (route.candidate.settings.candidate_fps.as_fraction())
                )
                + 1
            )
        work.append(count * source.probe.width * source.probe.height / 1_000_000)
    return tuple(work)


def analyzed_megapixels(width: int, height: int, max_side: int) -> float:
    if max(width, height) > max_side:
        if width >= height:
            width, height = max_side, max(1, (height * max_side + width // 2) // width)
        else:
            width, height = max(1, (width * max_side + height // 2) // height), max_side
    return width * height / 1_000_000


def views_progress_plan(
    route: ViewPreparationRoute | SharpestViewPreparationRoute,
    hardware: ExecutionHardwareProfile,
    candidate: CandidateViewSet | None = None,
) -> tuple[PlannedStage, ...]:
    # Missing/malformed preflight metadata belongs to the numerical stage's own
    # validation path. Optional estimation must not change its failure lifecycle.
    try:
        counts = tuple(
            1
            if source.media_type == MediaType.PHOTO
            else math.ceil(
                Fraction(source.probe.duration)
                * route.candidate.settings.candidate_fps.as_fraction()
            )
            + 1
            for source in route.sources
        )
        predicted_mp = sum(candidate_source_work(route))
        seconds = sum(
            float(Fraction(source.probe.duration))
            for source in route.sources
            if source.media_type == MediaType.VIDEO
        )
    except (ValueError, TypeError, ZeroDivisionError, OverflowError):
        counts = tuple(1 for _source in route.sources)
        predicted_mp = None
        seconds = 0
    output_mp = (
        predicted_mp
        if candidate is None
        else sum(view.width * view.height / 1_000_000 for view in candidate.views)
    )
    view_count = (
        (sum(counts) if predicted_mp is not None else None)
        if candidate is None
        else (len(candidate.views))
    )
    backend = PerformanceBackendIdentity(
        adapter_id=FFMPEG_ADAPTER_ID,
        adapter_version=FFMPEG_ADAPTER_VERSION,
        family="ffmpeg",
        runtime_version=performance_settings_key(route.ffmpeg_backend.version_line),
        executable_sha256=route.ffmpeg_backend.sha256,
    )
    plans = [
        _stage(
            node_id=route.candidate.node_id,
            stage_id="view_preparation",
            method_id=route.candidate.method_id,
            model="candidate.output_megapixels_v1",
            unit=WorkUnit.MEGAPIXELS,
            total=output_mp,
            backend=backend,
            settings={
                "settings": route.candidate.settings.model_dump(mode="json"),
                "verification_policy": route.verification_policy.value,
                "codecs": sorted(
                    {source.probe.codec_name or "unknown" for source in route.sources}
                ),
                "containers": sorted({source.extension for source in route.sources}),
            },
            hardware=hardware,
            metrics={
                "views": view_count or 0,
                "source_seconds": seconds,
                "output_megapixels": output_mp or 0,
                "photo_fraction": sum(s.media_type == MediaType.PHOTO for s in route.sources)
                / len(route.sources),
            },
        )
    ]
    if isinstance(route, SharpestViewPreparationRoute):
        quality_mp = (
            sum(
                analyzed_megapixels(
                    source.probe.width, source.probe.height, route.quality.settings.quality_max_side
                )
                * count
                for source, count in zip(route.sources, counts, strict=True)
            )
            if candidate is None
            else sum(
                analyzed_megapixels(
                    view.width, view.height, route.quality.settings.quality_max_side
                )
                for view in candidate.views
            )
        )
        plans.append(
            _stage(
                node_id=route.quality.node_id,
                stage_id="quality_assessment",
                method_id=route.quality.method_id,
                model="quality.analyzed_megapixels_v1",
                unit=WorkUnit.MEGAPIXELS,
                total=quality_mp if view_count is not None else None,
                hardware=hardware,
                backend=PerformanceBackendIdentity(
                    adapter_id=route.quality_backend.adapter_id,
                    adapter_version=route.quality_backend.adapter_version,
                    family="pillow",
                    runtime_version=performance_settings_key(
                        {
                            "pillow": route.quality_backend.pillow_version,
                            "python": route.quality_backend.python_version,
                        }
                    ),
                ),
                settings=route.quality.settings.model_dump(mode="json"),
                metrics={
                    "views": view_count or 0,
                    "megapixels": quality_mp,
                    "output_megapixels": output_mp or 0,
                },
            )
        )
    plans.append(
        _stage(
            node_id=route.selection.node_id,
            stage_id="frame_selection",
            method_id=route.selection.method_id,
            model="selection.candidate_views_v1",
            unit=WorkUnit.VIEWS,
            total=view_count,
            hardware=hardware,
            backend=python_backend(
                "splatforge.sharpest_interval_python"
                if isinstance(route, SharpestViewPreparationRoute)
                else "splatforge.fixed_fps_python"
            ),
            settings=route.selection.settings.model_dump(mode="json"),
            metrics={"views": view_count or 0, "sources": len(route.sources)},
        )
    )
    return tuple(plans)


def pairs_progress_plan(
    route: PairSelectionRoute,
    hardware: ExecutionHardwareProfile,
    generated_pair_count: int | None = None,
) -> PlannedStage:
    exhaustive = isinstance(route.settings, ExhaustiveSettings)
    retrieval = route.retrieval is not None
    query = (route.settings.retrieval if isinstance(route.settings, HybridPairSettings)
             else route.settings if isinstance(route.settings, RetrievalPairSettings) else None)
    total = (
        exhaustive_pair_count(len(route.universe.views))
        if exhaustive
        else len(route.universe.views)
    )
    if query:
        total = len(query.query_view_ids) if query.query_view_ids else len(route.universe.views)

    method = route.settings.method_id
    return _stage(
        node_id=route.node_id,
        stage_id="pair_selection",
        method_id=method,
        model="pairs.emitted_pairs_v1" if exhaustive else "retrieval.queried_views_v1"
        if retrieval else "pairs.selected_views_v1",
        unit=WorkUnit.PAIRS if exhaustive else WorkUnit.VIEWS,
        total=total,
        backend=python_backend("splatforge.pairs_python"),
        hardware=hardware,
        settings={
            "settings": route.settings.model_dump(mode="json"),
            "explicit_pair_count": len(route.explicit_pairs),
            **({"descriptor_dimension": route.retrieval_descriptor_dimension} if retrieval else {}),
        },
        metrics={
            "views": len(route.universe.views),
            **({"descriptor_dimension": route.retrieval_descriptor_dimension} if retrieval else {}),
            **(
                {"pairs": total}
                if exhaustive
                else {"pairs": generated_pair_count}
                if generated_pair_count is not None
                else {}
            ),
        },
    )


def retrieval_progress_plan(
    route: RetrievalBuildRoute, hardware: ExecutionHardwareProfile,
) -> PlannedStage:
    # These are validated/imported views, never claimed as observed model inference.
    return _stage(
        node_id=route.node_id, stage_id="retrieval_representation",
        method_id=route.settings.method_id, model="retrieval.imported_views_v1",
        unit=WorkUnit.VIEWS, total=len(route.export.views), hardware=hardware,
        backend=python_backend("splatforge.retrieval_offline"),
        settings=route.settings.model_dump(mode="json"),
        metrics={"views": len(route.export.views),
                 "megapixels": sum(v.width * v.height for v in route.export.views) / 1_000_000,
                 "descriptor_dimension": route.settings.descriptor_dimension,
                 "descriptor_bytes": route.export.descriptor_bytes},
    )


def features_progress_plan(
    route: FeatureExtractionRoute, hardware: ExecutionHardwareProfile,
) -> PlannedStage:
    backend = route.backend
    plan = _stage(
        node_id=route.node_id, stage_id="feature_extraction", method_id=route.settings.method_id,
        model="features.selected_views_v1", unit=WorkUnit.VIEWS, total=route.estimate.views,
        hardware=hardware.model_copy(update={"device": "gpu" if route.settings.use_gpu else "cpu"}),
        backend=PerformanceBackendIdentity(
            adapter_id=backend.adapter_id, family="colmap",
            runtime_version=backend.numerical_identity,
            executable_sha256=backend.selection.identity.sha256,
            model_sha256=(performance_settings_key(
                [m.sha256 for m in backend.model_identities()]) if backend.models else None),
        ),
        settings=route.settings.model_dump(mode="json"),
        metrics={"views": route.estimate.views, "megapixels": route.estimate.source_megapixels},
    )
    # The exact VIEWS total permits historical ETA through the unchanged M6.5
    # estimator. Unknown log formats retain completed=0 until terminal validation;
    # elapsed time never advances the count. Verified parsers report real views.
    return plan


def matching_progress_plan(
    route: FeatureMatchingRoute | GeometricVerificationRoute,
    hardware: ExecutionHardwareProfile,
) -> PlannedStage:
    matching = isinstance(route, FeatureMatchingRoute)
    backend = route.backend
    settings = route.settings.model_dump(mode="json")
    settings["actual_precision"] = backend.actual_precision
    if matching:
        settings["descriptor"] = route.descriptor.model_dump(mode="json")
    return _stage(
        node_id=route.node_id,
        stage_id="feature_matching" if matching else "geometric_verification",
        method_id=route.settings.method_id,
        model="matching.explicit_pairs_v1" if matching else "verification.raw_match_pairs_v1",
        unit=WorkUnit.PAIRS,
        total=route.estimate.pair_count,
        hardware=hardware.model_copy(
            update={"device": "gpu" if matching and route.settings.use_gpu else "cpu"}
        ),
        backend=PerformanceBackendIdentity(
            adapter_id=backend.adapter_id,
            family="colmap",
            runtime_version=backend.numerical_identity,
            executable_sha256=backend.selection.identity.sha256,
            model_sha256=performance_settings_key([m.sha256 for m in backend.models])
            if backend.models
            else None,
        ),
        settings=settings,
        metrics={
            "pairs": route.estimate.pair_count,
            "views": route.estimate.view_count,
            "features": route.estimate.total_features,
            "matches": route.estimate.raw_matches,
        },
    )


def mapping_progress_plan(route: MappingRoute, hardware: ExecutionHardwareProfile) -> PlannedStage:
    plan = _stage(
        node_id=route.node_id, stage_id="mapping", method_id=route.settings.method_id,
        model="mapping.global_phases_v1", unit=WorkUnit.WORK, total=1.0,
        hardware=hardware.model_copy(update={"device": "cpu"}),
        backend=PerformanceBackendIdentity(adapter_id=route.backend.adapter_id, family="colmap",
            runtime_version=route.backend.numerical_identity,
            executable_sha256=route.backend.selection.identity.sha256),
        settings={"mapper": route.settings.model_dump(mode="json"),
                  "calibration_policy": route.calibration_policy,
                  "calibration": route.calibration_settings.model_dump(mode="json")
                  if route.calibration_settings else None},
        metrics={"views": len(route.mapping_input.view_ids),
                 "pairs": route.mapping_input.verified_pair_count,
                 "features": route.mapping_input.keypoint_count,
                 "matches": route.mapping_input.inlier_count},
    )
    # One complete mapping job normalizes historical duration only. It never
    # supplies a live completion fraction or linear view-registration percentage.
    return plan.model_copy(update={
        "work": plan.work.model_copy(update={
            "mode": ProgressMode.PHASE, "historical_job_duration": True,
        }),
    })
