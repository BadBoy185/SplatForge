"""Compare external representations through the shared M7b services using fake native IO."""

import pytest
from matching_helpers import MatchingFixture
from test_features_execution import build as features
from test_retrieval_execution import build, exported, pairs
from test_views_execution import harness, prepare
from typer.testing import CliRunner

from splatforge.adapters.pair_workspace import LocalPairWorkspace
from splatforge.adapters.retrieval_artifacts import LocalRetrievalAdapter
from splatforge.application.matching import MatchingService
from splatforge.application.pairs import PairsService
from splatforge.application.retrieval import RetrievalService
from splatforge.application.retrieval_benchmark import (
    BenchmarkCandidate,
    BenchmarkSourceDevice,
    RetrievalBenchmarkFixture,
    RetrievalBenchmarkService,
)
from splatforge.cli.app import app
from splatforge.core.matching import LomaMatchingSettings


def test_benchmark_all_external_candidates_share_local_features_and_matcher(tmp_path):
    value, native = harness(tmp_path), MatchingFixture(tmp_path)
    views = prepare(value)
    local = features(value, views, native, variant="LOMA_B")
    candidates = []
    for method in ("megaloc", "anyloc", "boq", "salad"):
        source = exported(value, views, tmp_path / method, method=f"retrieval.{method}")
        candidates.append(
            BenchmarkCandidate(method_id=f"retrieval.{method}", descriptor_export=source)
        )
    fixture = RetrievalBenchmarkFixture(
        fixture_id="synthetic-contract-only",
        category="phone_drone",
        data_kind="synthetic_contract_only",
        data_license_evidence="generated in tests",
        project=value.root,
        views_run_id=views.run_id,
        features_run_id=local.run_id,
        candidates=tuple(candidates),
        top_k_values=(1,),
        matching=LomaMatchingSettings(),
        source_devices=tuple(
            BenchmarkSourceDevice(source_id=sid, device_label=f"device-{n}")
            for n, sid in enumerate(value.source_ids)
        ),
    )
    adapter = LocalRetrievalAdapter()
    report = RetrievalBenchmarkService(
        value.execution,
        RetrievalService(value.execution, adapter),
        PairsService(value.execution, LocalPairWorkspace(), retrieval_adapter=adapter),
        MatchingService(value.execution, native.matching_adapter()),
    ).run(fixture, colmap=native.exe, model_directory=native.model_root)
    assert report["production_selection"] is None
    assert len(report["results"]) == 4
    assert len({r["local_features_digest"] for r in report["results"]}) == 1
    assert len({r["matching_runtime"] for r in report["results"]}) == 1
    for result in report["results"]:
        assert result["metrics"]["retrieved_pairs"] == 2
        assert result["metrics"]["retrieval_raw_matches"] >= 0
        assert result["peak_ram_bytes"] is None and result["peak_vram_bytes"] is None
        assert len(result["metrics"]["declared_device_coverage"]) == 2


@pytest.mark.parametrize("variant", ["SIFT", "ALIKED_N16ROT", "LOMA_B"])
def test_local_feature_changes_reuse_retrieval_and_pairs(tmp_path, variant):
    value, native = harness(tmp_path), MatchingFixture(tmp_path)
    views = prepare(value)
    source = exported(value, views, tmp_path / "export")
    representation = build(value, views, source)
    first = pairs(value, views, representation)
    features(value, views, native, variant=variant)
    assert build(value, views, source).cache_hit
    reused = pairs(value, views, representation)
    assert reused.cache_hit and reused.pair_set_artifact == first.pair_set_artifact


def test_retrieval_cli_capability_json_and_no_fallback():
    import json
    from uuid import uuid4

    runner = CliRunner()
    result = runner.invoke(app, ["retrieval", "capabilities"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["production_model"] is None and len(payload["candidates"]) == 4
    missing = runner.invoke(app, ["retrieval", "build", "missing", "--views-run", str(uuid4())])
    assert missing.exit_code == 1
    assert "production_backend_unselected" in missing.output
    hybrid = runner.invoke(
        app, ["pairs", "build", "missing", "--views-run", str(uuid4()), "--method", "hybrid"]
    )
    assert hybrid.exit_code == 1 and "--retrieval-run" in hybrid.output
