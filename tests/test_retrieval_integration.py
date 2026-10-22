"""Opt-in real M7b transport and representative external VPR export comparisons."""

import json
import os
from pathlib import Path

import pytest
import test_views_execution as upstream
from test_retrieval_execution import build, exported, pairs

from splatforge.adapters.colmap_capabilities import ColmapCapabilityAdapter
from splatforge.adapters.colmap_features import ColmapFeatureAdapter, hash_file
from splatforge.adapters.colmap_matching import ColmapMatchingAdapter
from splatforge.application.features import FeaturesService
from splatforge.application.matching import MatchingService
from splatforge.application.retrieval_benchmark import (
    RetrievalBenchmarkFixture,
    benchmark_metrics,
)
from splatforge.application.sfm_profiles import SfmProfileService
from splatforge.bootstrap import build_retrieval_benchmark_service
from splatforge.core.features import resolve_extraction_settings
from splatforge.core.matching import resolve_matching_settings
from splatforge.core.sfm_profiles import FeatureMatchingChoice, SfmDevicePolicy


@pytest.mark.integration
def test_real_loma_retrieved_cross_source_transport(tmp_path, monkeypatch, record_property):
    configured = os.environ.get("SPLATFORGE_TEST_COLMAP")
    if not configured or os.environ.get("SPLATFORGE_TEST_RETRIEVAL_TRANSPORT") != "1":
        pytest.skip("Set SPLATFORGE_TEST_COLMAP and SPLATFORGE_TEST_RETRIEVAL_TRANSPORT=1")
    executable = None if configured == "1" else Path(configured)
    model_root = Path(os.environ["SPLATFORGE_COLMAP_MODEL_DIR"])
    resolved = SfmProfileService(ColmapFeatureAdapter(), ColmapMatchingAdapter()).resolve(
        choice=FeatureMatchingChoice(
            extractor=resolve_extraction_settings("LOMA_B"),
            matcher=resolve_matching_settings("LOMA_B"),
        ),
        device_policy=SfmDevicePolicy(os.environ.get("SPLATFORGE_TEST_COLMAP_DEVICE", "gpu:0")),
        colmap=executable,
        model_directory=model_root,
    )
    texture = tmp_path / "texture.png"
    ColmapCapabilityAdapter._write_test_image(texture)
    pixels = texture.read_bytes()
    original = upstream.FakeProbe.probe

    def probe(self, *args, **kwargs):
        return original(self, *args, **kwargs).model_copy(update={"width": 192, "height": 192})

    monkeypatch.setattr(upstream.FakeProbe, "probe", probe)
    monkeypatch.setattr(upstream, "png", lambda _w, _h: pixels)
    value = upstream.harness(tmp_path)
    views = upstream.prepare(value)
    source = exported(value, views, tmp_path / "synthetic external vectors")
    representation = build(value, views, source)
    retrieved = pairs(value, views, representation)
    features = FeaturesService(value.execution, ColmapFeatureAdapter()).extract(
        value.root,
        views_run_id=views.run_id,
        settings=resolved.choice.extractor,
        colmap=executable,
        model_directory=model_root,
    )
    before = {p: hash_file(p) for p in (value.root / "artifacts").rglob("*") if p.is_file()}
    matching = MatchingService(value.execution, ColmapMatchingAdapter())
    raw = matching.match(
        value.root,
        features_run_id=features.run_id,
        pairs_run_id=retrieved.run_id,
        settings=resolved.choice.matcher,
        resolution=resolved,
        colmap=executable,
        model_directory=model_root,
    )
    verified = matching.verify(value.root, matches_run_id=raw.run_id, colmap=executable)
    metrics = benchmark_metrics(
        value.execution.load_pair_set(value.root, retrieved.pair_set_artifact),
        value.execution.load_match_set(value.root, raw.artifact),
        value.execution.load_verified_geometry(value.root, verified.artifact),
    )
    assert metrics["retrieved_pairs"] == 2
    assert metrics["verified_cross_source_retrieval_pairs"] == 2
    assert metrics["source_components_after"] == 1
    assert metrics["components_before_verified_retrieval"] == 2
    assert metrics["retrieval_verified_inliers"] > 0
    assert all(hash_file(p) == digest for p, digest in before.items())
    assert pairs(value, views, representation).cache_hit
    assert build(value, views, source).cache_hit
    record_property("quality_evidence", "none: synthetic vectors/images; transport validation only")
    record_property("resolved_route", resolved.model_dump_json())
    record_property("retrieved_m7b_metrics", json.dumps(metrics))


@pytest.mark.integration
def test_representative_external_retrieval_fixture(record_property):
    configured = os.environ.get("SPLATFORGE_TEST_RETRIEVAL_FIXTURE")
    if not configured:
        pytest.skip("Set SPLATFORGE_TEST_RETRIEVAL_FIXTURE to a real v1 benchmark manifest")
    path = Path(configured)
    assert path.stat().st_size <= 64 * 1024
    fixture = RetrievalBenchmarkFixture.model_validate_json(path.read_bytes())
    assert fixture.data_kind == "real"
    colmap = Path(os.environ["SPLATFORGE_TEST_COLMAP"])
    report = build_retrieval_benchmark_service().run(
        fixture,
        colmap=colmap,
        model_directory=Path(os.environ["SPLATFORGE_COLMAP_MODEL_DIR"]),
    )
    record_property("retrieval_benchmark", json.dumps(report))
    assert len(report["results"]) == len(fixture.candidates) * len(fixture.top_k_values)
