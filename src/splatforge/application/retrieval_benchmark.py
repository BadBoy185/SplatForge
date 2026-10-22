"""Opt-in candidate comparison through one unchanged, real M7b LoMa-B route."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Literal, Protocol
from uuid import UUID

from pydantic import Field, model_validator

from splatforge.application.matching import MatchingService
from splatforge.application.pairs import PairsService
from splatforge.application.retrieval import RetrievalRepository, RetrievalService
from splatforge.core.execution import ArtifactHandle
from splatforge.core.features import LocalFeatureSet
from splatforge.core.geometry import VerificationSettings, VerifiedGeometrySet
from splatforge.core.matching import LomaMatchingSettings, MatchSet
from splatforge.core.pairs import (
    HybridPairSettings,
    PairRecord,
    PairResourceLimits,
    PairSet,
    RetrievalPairSettings,
    SequentialSettings,
    compute_coverage,
)
from splatforge.core.retrieval import CandidateMethod, RetrievalResourceLimits
from splatforge.core.retrieval_pairs import NoRetrievalEdgesError
from splatforge.core.views import FrozenModel

FixtureCategory = Literal[
    "overlapping_same_device_clips",
    "phone_drone",
    "partial_overlap_clips",
    "unordered_photos",
    "no_overlap",
    "repetitive_texture",
    "near_duplicate_bursts",
    "large_viewpoint_orientation",
]
REQUIRED_CATEGORIES = (
    "overlapping_same_device_clips",
    "phone_drone",
    "partial_overlap_clips",
    "unordered_photos",
    "no_overlap",
    "repetitive_texture",
    "near_duplicate_bursts",
    "large_viewpoint_orientation",
)


class BenchmarkCandidate(FrozenModel):
    method_id: CandidateMethod
    descriptor_export: Path


class BenchmarkSourceDevice(FrozenModel):
    source_id: UUID
    device_label: str = Field(min_length=1, max_length=128)


class RetrievalBenchmarkFixture(FrozenModel):
    fixture_version: Literal[1] = 1
    fixture_id: str = Field(min_length=1, max_length=128)
    category: FixtureCategory
    data_kind: Literal["real", "synthetic_contract_only"]
    data_license_evidence: str = Field(min_length=1, max_length=2048)
    project: Path
    views_run_id: UUID
    features_run_id: UUID
    candidates: tuple[BenchmarkCandidate, ...] = Field(min_length=1, max_length=4)
    top_k_values: tuple[int, ...] = Field(default=(1, 5), min_length=1, max_length=5)
    pairing: RetrievalPairSettings = RetrievalPairSettings()
    sequential: SequentialSettings = SequentialSettings()
    total_pair_budget: int = Field(default=100_000, ge=1, le=1_000_000, strict=True)
    retrieval_resources: RetrievalResourceLimits = RetrievalResourceLimits()
    matching: LomaMatchingSettings = LomaMatchingSettings(use_gpu=True)
    verification: VerificationSettings = VerificationSettings()
    source_devices: tuple[BenchmarkSourceDevice, ...] = Field(default=(), max_length=4096)

    @model_validator(mode="after")
    def bounded_fair_route(self) -> RetrievalBenchmarkFixture:
        methods = [x.method_id for x in self.candidates]
        if len(methods) != len(set(methods)):
            raise ValueError("Benchmark candidates must have unique method IDs")
        if list(self.top_k_values) != sorted(set(self.top_k_values)) or any(
            type(k) is not int or not 1 <= k <= 100 for k in self.top_k_values
        ):
            raise ValueError("Benchmark K values must be unique sorted integers in 1..100")
        if self.matching.variant != "LOMA_B":
            raise ValueError("Initial retrieval comparison freezes the validated LOMA_B matcher")
        ids = [x.source_id for x in self.source_devices]
        if len(ids) != len(set(ids)):
            raise ValueError("Device metadata must identify each source at most once")
        return self


def retrieval_availability() -> dict[str, object]:
    return {
        "schema_version": 1,
        "representation_import": "implemented",
        "exact_cpu_query": "implemented",
        "hybrid_pairing": "implemented",
        "production_model": None,
        "production_inference": "unavailable",
        "reason": "Representative quality/resource measurements through M7b are missing",
        "candidates": [
            {
                "method": "retrieval.megaloc",
                "status": "external_benchmark_only",
                "code": "MIT",
                "weights": "MIT model-card declaration",
                "bundling": "not_selected_pending_benchmark_and_notice_audit",
            },
            {
                "method": "retrieval.anyloc",
                "status": "external_benchmark_only",
                "code": "BSD-3-Clause",
                "weights": "DINOv2 Apache-2.0; vocabulary terms unresolved",
                "bundling": "not_selected",
            },
            {
                "method": "retrieval.boq",
                "status": "external_benchmark_only",
                "code": "MIT",
                "weights": "separate release-weight grant unconfirmed",
                "bundling": "not_selected",
            },
            {
                "method": "retrieval.salad",
                "status": "external_benchmark_only",
                "code": "GPL-3.0",
                "weights": "separate weight terms unconfirmed",
                "bundling": "excluded_without_explicit_licensing_acceptance",
            },
        ],
        "required_fixture_categories": REQUIRED_CATEGORIES,
        "evidence": "docs/M7C_BENCHMARK.md; licensing audit 2026-10-22",
    }


def _group_components(universe, edges: tuple[PairRecord, ...], field: str) -> int:
    groups = {v.view_id: getattr(v, field) for v in universe.views}
    parent = {g: g for g in groups.values()}

    def find(g):
        while parent[g] != g:
            parent[g] = parent[parent[g]]
            g = parent[g]
        return g

    for edge in edges:
        a, b = find(groups[edge.left_view_id]), find(groups[edge.right_view_id])
        parent[a] = b
    return len({find(g) for g in parent})


def benchmark_metrics(
    pairs: PairSet,
    raw: MatchSet,
    geometry: VerifiedGeometrySet,
    source_devices: tuple[BenchmarkSourceDevice, ...] = (),
) -> dict[str, object]:
    def key(p):
        return p.left_view_id, p.right_view_id

    raw_by_id = {key(p): p for p in raw.pairs}
    geo_by_id = {key(p): p for p in geometry.pairs}
    if set(raw_by_id) != {key(p) for p in pairs.pairs} or set(geo_by_id) != set(raw_by_id):
        raise ValueError("Benchmark M7b outputs differ from the retrieved PairSet")
    retrieval = tuple(p for p in pairs.pairs if any(r.kind == "retrieval" for r in p.reasons))
    sequential = tuple(p for p in pairs.pairs if any(r.kind == "sequential" for r in p.reasons))
    verified = tuple(p for p in pairs.pairs if geo_by_id[key(p)].state == "verified")
    verified_seq = tuple(p for p in sequential if geo_by_id[key(p)].state == "verified")
    useful = tuple(p for p in retrieval if geo_by_id[key(p)].state == "verified")
    sources = {v.view_id: v.source_id for v in pairs.universe.views}
    devices = {s.source_id: s.device_label for s in source_devices}
    if not set(devices) <= set(sources.values()):
        raise ValueError("Declared device metadata references sources outside the selected corpus")
    device_coverage = None
    if devices:
        verified_ids = {v for p in verified for v in (p.left_view_id, p.right_view_id)}
        device_coverage = [
            {
                "device_label": label,
                "selected_views": sum(devices.get(source) == label for source in sources.values()),
                "verified_paired_views": sum(
                    devices.get(sources[v]) == label for v in verified_ids
                ),
            }
            for label in sorted(set(devices.values()))
        ]
    return {
        "retrieved_pairs": len(retrieval),
        "sequential_pairs": len(sequential),
        "final_pairs": len(pairs.pairs),
        "retrieved_pairs_with_raw_matches": sum(
            raw_by_id[key(p)].raw_match_count > 0 for p in retrieval
        ),
        "verified_retrieved_pairs": len(useful),
        "retrieval_raw_matches": sum(raw_by_id[key(p)].raw_match_count for p in retrieval),
        "retrieval_verified_inliers": sum(geo_by_id[key(p)].inlier_count for p in retrieval),
        "useful_verified_edges_per_retrieval_pair": len(useful) / len(retrieval)
        if retrieval
        else None,
        "verified_cross_source_retrieval_pairs": sum(
            sources[p.left_view_id] != sources[p.right_view_id] for p in useful
        ),
        "components_before_candidate_retrieval": compute_coverage(
            pairs.universe, sequential
        ).component_count,
        "components_before_verified_retrieval": compute_coverage(
            pairs.universe, verified_seq
        ).component_count,
        "coverage_after_verified_retrieval": compute_coverage(pairs.universe, verified).model_dump(
            mode="json"
        ),
        "source_components_before": _group_components(pairs.universe, verified_seq, "source_id"),
        "source_components_after": _group_components(pairs.universe, verified, "source_id"),
        "group_components_after": _group_components(pairs.universe, verified, "source_group_id"),
        "declared_device_coverage": device_coverage,
        "views_without_device_metadata": sum(source not in devices for source in sources.values()),
    }


class BenchmarkRepository(RetrievalRepository, Protocol):
    def load_local_features(self, root: Path, handle: ArtifactHandle) -> LocalFeatureSet: ...

    def load_match_set(self, root: Path, handle: ArtifactHandle) -> MatchSet: ...

    def load_verified_geometry(self, root: Path, handle: ArtifactHandle) -> VerifiedGeometrySet: ...


class RetrievalBenchmarkService:
    def __init__(
        self,
        repository: BenchmarkRepository,
        retrieval: RetrievalService,
        pairs: PairsService,
        matching: MatchingService,
    ) -> None:
        self._repo, self._retrieval, self._pairs, self._matching = (
            repository,
            retrieval,
            pairs,
            matching,
        )

    def run(
        self,
        fixture: RetrievalBenchmarkFixture,
        *,
        colmap: Path | None = None,
        model_directory: Path | None = None,
    ) -> dict[str, object]:
        root, repo = fixture.project, self._repo
        feature_handle = repo.resolve_run_output(
            root, fixture.features_run_id, "local_features", "features"
        )
        features = repo.load_local_features(root, feature_handle)
        if features.settings.variant != "LOMA_B":
            raise ValueError("Benchmark needs one shared validated LOMA_B local-feature run")
        results = []
        route_identity = None
        for candidate in fixture.candidates:
            started = time.monotonic()
            built = self._retrieval.build(
                root,
                views_run_id=fixture.views_run_id,
                descriptor_export=candidate.descriptor_export,
                resource_limits=fixture.retrieval_resources,
            )
            import_seconds = time.monotonic() - started
            if built.representation.settings.method_id != candidate.method_id:
                raise ValueError("Candidate label differs from descriptor export method")
            for k in fixture.top_k_values:
                started = time.monotonic()
                try:
                    pair_result = self._pairs.build(
                        root,
                        views_run_id=fixture.views_run_id,
                        retrieval_run_id=built.run_id,
                        settings=HybridPairSettings(
                            sequential=fixture.sequential,
                            retrieval=fixture.pairing.model_copy(update={"top_k": k}),
                        ),
                        resource_limits=PairResourceLimits(max_pairs=fixture.total_pair_budget),
                        retrieval_resources=fixture.retrieval_resources,
                    )
                except NoRetrievalEdgesError:
                    results.append(
                        {
                            "method": candidate.method_id,
                            "k": k,
                            "status": "no_candidate_edges",
                            "m7b_executed": False,
                            "retrieved_pairs": 0,
                            "view_components": len(built.representation.views),
                        }
                    )
                    continue
                query_seconds = time.monotonic() - started
                started = time.monotonic()
                matched = self._matching.match(
                    root,
                    features_run_id=fixture.features_run_id,
                    pairs_run_id=pair_result.run_id,
                    settings=fixture.matching,
                    colmap=colmap,
                    model_directory=model_directory,
                )
                match_seconds = time.monotonic() - started
                started = time.monotonic()
                checked = self._matching.verify(
                    root,
                    matches_run_id=matched.run_id,
                    settings=fixture.verification,
                    colmap=colmap,
                )
                verification_seconds = time.monotonic() - started
                raw = repo.load_match_set(root, matched.artifact)
                geometry = repo.load_verified_geometry(root, checked.artifact)
                identity = (
                    raw.backend_numerical_identity,
                    raw.models,
                    geometry.backend_numerical_identity,
                )
                if route_identity is not None and identity != route_identity:
                    raise ValueError("M7b runtime/model changed during comparison; results invalid")
                route_identity = identity
                pairs = repo.load_pair_set(root, pair_result.pair_set_artifact)
                results.append(
                    {
                        "method": candidate.method_id,
                        "k": k,
                        "representation": built.representation.model_dump(mode="json"),
                        "representation_artifact": built.representation_artifact.model_dump(
                            mode="json"
                        ),
                        "pairs_run_id": str(pair_result.run_id),
                        "matches_run_id": str(matched.run_id),
                        "verification_run_id": str(checked.run_id),
                        "local_features_digest": feature_handle.semantic_digest,
                        "matching_settings": raw.settings.model_dump(mode="json"),
                        "matching_runtime": raw.backend_numerical_identity,
                        "matching_models": [m.model_dump(mode="json") for m in raw.models],
                        "verification_settings": geometry.settings.model_dump(mode="json"),
                        "metrics": benchmark_metrics(pairs, raw, geometry, fixture.source_devices),
                        "observed_wall_seconds": {
                            "import": import_seconds,
                            "query": query_seconds,
                            "matching": match_seconds,
                            "verification": verification_seconds,
                        },
                        "cache_hits": {
                            "import": built.cache_hit,
                            "query": pair_result.cache_hit,
                            "matching": matched.cache_hit,
                            "verification": checked.cache_hit,
                        },
                        "inference_seconds": None,
                        "peak_ram_bytes": None,
                        "peak_vram_bytes": None,
                        "descriptor_dimension": built.representation.settings.descriptor_dimension,
                        "flat_index_bytes": built.descriptor_bytes,
                    }
                )
        return {
            "benchmark_version": 1,
            "fixture": fixture.model_dump(mode="json"),
            "results": results,
            "production_selection": None,
            "selection_status": "requires_representative_suite_and_licensing_review",
        }
