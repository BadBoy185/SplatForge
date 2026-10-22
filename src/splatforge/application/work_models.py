"""Explicit M3/M4/M6 diagnostic work models; never used by recipe construction."""

from __future__ import annotations

import hashlib
import math
import platform
from fractions import Fraction

from splatforge.core.execution import (
    PairSelectionRoute,
    SharpestViewPreparationRoute,
    ViewPreparationRoute,
)
from splatforge.core.media import MediaType
from splatforge.core.pairs import ExhaustiveSettings, exhaustive_pair_count
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
    total = (
        exhaustive_pair_count(len(route.universe.views))
        if exhaustive
        else len(route.universe.views)
    )
    method = "pair_selection.exhaustive" if exhaustive else "pair_selection.sequential"
    return _stage(
        node_id=route.node_id,
        stage_id="pair_selection",
        method_id=method,
        model="pairs.emitted_pairs_v1" if exhaustive else "pairs.selected_views_v1",
        unit=WorkUnit.PAIRS if exhaustive else WorkUnit.VIEWS,
        total=total,
        backend=python_backend("splatforge.pairs_python"),
        hardware=hardware,
        settings={
            "settings": route.settings.model_dump(mode="json"),
            "explicit_pair_count": len(route.explicit_pairs),
        },
        metrics={
            "views": len(route.universe.views),
            **(
                {"pairs": total}
                if exhaustive
                else {"pairs": generated_pair_count}
                if generated_pair_count is not None
                else {}
            ),
        },
    )
