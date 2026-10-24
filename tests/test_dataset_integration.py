"""Opt-in installed COLMAP transport, never a production quality/VPR benchmark."""

import json
import os
import time
from pathlib import Path
from uuid import UUID

import pytest
from test_mapping_integration import test_real_global_mapping as real_mapping_fixture
from test_views_execution import query

from splatforge.adapters.colmap_dataset import ColmapDatasetAdapter
from splatforge.adapters.dataset_reader import read_dataset
from splatforge.adapters.execution_storage import LocalExecutionRepository
from splatforge.adapters.validation_geometry import ColmapValidationSource
from splatforge.application.dataset import DatasetService
from splatforge.application.reconstruction_selection import ReconstructionSelectionService
from splatforge.application.reconstruction_validation import ReconstructionValidationService
from splatforge.core.dataset import DatasetSettings
from splatforge.core.reconstruction import MappingCalibrationPolicy


@pytest.mark.integration
def test_real_m7_m8_m9_m10_dataset(tmp_path, monkeypatch, record_property):
    configured = os.environ.get("SPLATFORGE_TEST_COLMAP")
    if not configured or os.environ.get("SPLATFORGE_TEST_DATASET") != "1":
        pytest.skip("Set SPLATFORGE_TEST_COLMAP and SPLATFORGE_TEST_DATASET=1 for real M10")
    # This existing deterministic parallax fixture actually executes M7 and M8.
    real_mapping_fixture(
        tmp_path, monkeypatch, record_property, MappingCalibrationPolicy.PRESERVE_PRIORS
    )
    root = next(p.parent for p in tmp_path.rglob("project.json"))
    repo = LocalExecutionRepository()
    mapping_run = UUID(
        query(
            root,
            "SELECT producer_run_id FROM artifacts "
            "WHERE artifact_type='mapping.reconstruction_set'",
        )[0][0]
    )
    validation_service = ReconstructionValidationService(repo, ColmapValidationSource)
    validation = validation_service.validate(root, mapping_run_id=mapping_run)
    selection = ReconstructionSelectionService(validation_service).select(
        root, validation_run_id=validation.run_id
    )
    service = DatasetService(repo, ColmapDatasetAdapter())
    before = {
        p: __import__("hashlib").sha256(p.read_bytes()).hexdigest()
        for p in (root / "artifacts").rglob("*")
        if p.is_file()
    }
    started = time.monotonic()
    result = service.prepare(root, selection_run_id=selection.run.run_id, colmap=Path(configured))
    api_seconds = time.monotonic() - started
    assert result.status == "succeeded"
    component = read_dataset((root / result.dataset.components[0].manifest_path).parent)
    assert component.image_count >= 3 and component.sparse_point_count > 0
    assert {c.model for c in component.cameras} <= {"PINHOLE", "SIMPLE_PINHOLE"}
    assert service.prepare(
        root, selection_run_id=selection.run.run_id, colmap=Path(configured)
    ).cache_hit
    resized = service.prepare(
        root,
        selection_run_id=selection.run.run_id,
        colmap=Path(configured),
        settings=DatasetSettings(max_image_size=320),
    )
    assert not resized.component_runs[0].cache_hit
    assert resized.dataset.semantic_digest != result.dataset.semantic_digest
    small = read_dataset((root / resized.dataset.components[0].manifest_path).parent)
    assert max(max(i.width, i.height) for i in small.images) <= 320
    records = [
        json.loads(line)
        for run in result.component_runs
        for p in (root / "runs" / str(run.run_id) / "attempts").glob("*/process.jsonl")
        for line in p.read_text(encoding="utf8").splitlines()
    ]
    assert records and all(r["tool_role"] == "colmap.image_undistorter" for r in records)
    assert "COLMAP" in records[0]["argv"]
    metrics = {
        "images": component.image_count,
        "cameras": component.camera_count,
        "points": component.sparse_point_count,
        "api_seconds": api_seconds,
        "native_seconds": sum(r["elapsed_seconds"] for r in records),
        "semantic_digest": component.semantic_digest,
        "input_megapixels": sum(i.width * i.height for i in component.input_images) / 1e6,
        "output_megapixels": sum(i.width * i.height for i in component.images) / 1e6,
        "cache_hit": True,
    }
    record_property("m10_metrics", json.dumps(metrics))
    print(json.dumps(metrics))
    adapter = ColmapDatasetAdapter()
    runner = adapter._runner

    class CancelRunner:
        def run(self, request, *, cancellation=None, poll=None):
            if request.argv[0] != "image_undistorter" or len(request.argv) == 2:
                return runner.run(
                    request, cancellation=cancellation, **({"poll": poll} if poll else {})
                )
            owner = cancellation
            while hasattr(owner, "owner"):
                owner = owner.owner

            def cancel_poll():
                repo.request_cancellation(root, run_id=owner.run)
                if poll:
                    poll()

            return runner.run(request, cancellation=cancellation, poll=cancel_poll)

    adapter._runner = CancelRunner()
    cancelled = DatasetService(repo, adapter).prepare(
        root,
        selection_run_id=selection.run.run_id,
        colmap=Path(configured),
        settings=DatasetSettings(max_image_size=319),
    )
    assert cancelled.status == "cancelled" and cancelled.artifact is None
    cancel_records = [
        json.loads(line)
        for p in (root / "runs" / str(cancelled.run_id) / "attempts").glob("*/process.jsonl")
        for line in p.read_text(encoding="utf8").splitlines()
    ]
    assert any(r["cancelled"] and r["teardown_confirmed"] for r in cancel_records)
    assert all(
        __import__("hashlib").sha256(p.read_bytes()).hexdigest() == h for p, h in before.items()
    )
