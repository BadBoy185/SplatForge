"""Opt-in actual partition -> multiple leaves -> native merge -> portable contract."""

import json
import os
from pathlib import Path
from time import monotonic

import pytest
from hierarchical_helpers import real_mapping_input
from test_incremental_execution import unchanged
from test_matching_execution import hashes

from splatforge.adapters.colmap_mapping import ColmapMappingAdapter
from splatforge.application.mapping import MappingService
from splatforge.core.reconstruction import HierarchicalClusterSettings, HierarchicalMapperSettings


@pytest.mark.integration
def test_real_hierarchical_partition_merge_transport(tmp_path, monkeypatch, record_property):
    configured = os.environ.get("SPLATFORGE_TEST_COLMAP")
    if not configured or os.environ.get("SPLATFORGE_TEST_HIERARCHICAL") != "1":
        pytest.skip("Set SPLATFORGE_TEST_COLMAP and SPLATFORGE_TEST_HIERARCHICAL=1")
    executable = Path(configured)
    settings = HierarchicalMapperSettings(
        num_threads=2,
        num_workers=2,
        image_overlap=4,
        leaf_max_num_images=6,
        cluster=HierarchicalClusterSettings(
            init_min_tri_angle=8, ba_refine_focal_length=False, ba_refine_extra_params=False
        ),
    )
    value, verified, geometry = real_mapping_input(tmp_path, monkeypatch, executable)
    before = hashes(value.root)
    service = MappingService(value.execution, ColmapMappingAdapter())
    started = monotonic()
    result = service.run(
        value.root, verification_run_id=verified.run_id, settings=settings, colmap=executable
    )
    elapsed = monotonic() - started
    assert result.status == "succeeded" and not result.cache_hit
    native_records = [
        json.loads(line)
        for p in (value.root / "runs" / str(result.run_id) / "attempts").glob("*/process.jsonl")
        for line in p.read_text(encoding="utf8").splitlines()
    ]
    assert len(native_records) == 1
    assert native_records[0]["tool_role"] == "colmap.hierarchical_mapper"
    assert native_records[0]["argv"][0] == "hierarchical_mapper"
    assert native_records[0]["outcome"] == "succeeded"

    assert result.diagnostics["partition_observed"]
    assert result.diagnostics["leaf_clusters"] > 1
    assert result.diagnostics["reconstructing_clusters_observed"]
    assert result.diagnostics["merge_observed"]
    reader = service.reader(value.root, result.run_id)
    registered = [
        v.view_id for c in reader.components() for v in reader.registered_views(c.component_id)
    ]
    assert len(registered) == len(set(registered)) == result.reconstruction.registered_view_count
    assert result.reconstruction.component_count >= 1 and len(registered) >= 3
    for component in reader.components():
        assert tuple(reader.cameras(component.component_id))
    unchanged(before)
    assert service.run(
        value.root, verification_run_id=verified.run_id, settings=settings, colmap=executable
    ).cache_hit
    changed_settings = HierarchicalMapperSettings.model_validate(
        {**settings.model_dump(), "image_overlap": 5}
    )
    changed = service.run(
        value.root,
        verification_run_id=verified.run_id,
        settings=changed_settings,
        colmap=executable,
    )
    assert not changed.cache_hit and changed.recipe_key != result.recipe_key
    published = hashes(value.root)
    adapter = ColmapMappingAdapter()
    native = adapter._runner

    class CancelRunner:
        def run(self, request, *, cancellation=None, poll=None):
            if request.argv[0] != "hierarchical_mapper" or len(request.argv) == 2:
                return native.run(
                    request, cancellation=cancellation, **({"poll": poll} if poll else {})
                )
            owner = cancellation
            while hasattr(owner, "owner"):
                owner = owner.owner

            def cancel_poll():
                value.execution.request_cancellation(value.root, run_id=owner.run)
                if poll:
                    poll()

            return native.run(request, cancellation=cancellation, poll=cancel_poll)

    adapter._runner = CancelRunner()
    cancelled = MappingService(value.execution, adapter).run(
        value.root,
        verification_run_id=verified.run_id,
        colmap=executable,
        settings=HierarchicalMapperSettings.model_validate(
            {
                **settings.model_dump(),
                "cluster": {**settings.cluster.model_dump(), "random_seed": 2},
            }
        ),
    )
    assert cancelled.status == "cancelled" and cancelled.artifact is None
    records = [
        json.loads(line)
        for p in (value.root / "runs" / str(cancelled.run_id) / "attempts").glob("*/process.jsonl")
        for line in p.read_text(encoding="utf8").splitlines()
    ]
    assert any(r["cancelled"] and r["teardown_confirmed"] for r in records)
    unchanged(published)
    metrics = {
        "views": 12,
        "verified_pairs": geometry.accepted_pair_count,
        **result.diagnostics,
        "image_overlap": 4,
        "workers": 2,
        "total_threads": 2,
        "final_models": result.reconstruction.component_count,
        "registered": result.reconstruction.registered_view_count,
        "unregistered": result.reconstruction.unregistered_view_count,
        "points": [c.point_count for c in result.reconstruction.components],
        "native_seconds": result.native_seconds,
        "api_seconds": elapsed,
        "cache_hit": True,
        "settings_change_recomputed": True,
        "cancellation_no_artifact": True,
        "transport_only": True,
    }
    record_property("m8b2_hierarchical", json.dumps(metrics))
    print(json.dumps(metrics))
