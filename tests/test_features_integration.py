"""Opt-in real M7a extraction from a published, tiny textured SelectedViewSet."""

import os
from pathlib import Path

import pytest
import test_views_execution as upstream

from splatforge.adapters.colmap_capabilities import ColmapCapabilityAdapter
from splatforge.adapters.colmap_features import ColmapFeatureAdapter, hash_file
from splatforge.application.features import FeaturesService
from splatforge.application.features_contracts import FeatureCapabilityError
from splatforge.core.features import resolve_extraction_settings


@pytest.mark.integration
@pytest.mark.parametrize("variant", ["SIFT", "ALIKED_N16ROT", "ALIKED_N32", "LOMA_B", "LOMA_B128"])
def test_configured_real_feature_extraction(tmp_path, monkeypatch, record_property, variant):
    configured = os.environ.get("SPLATFORGE_TEST_COLMAP")
    if not configured:
        pytest.skip("Set SPLATFORGE_TEST_COLMAP to a compatible native COLMAP executable")
    if variant != "SIFT" and os.environ.get("SPLATFORGE_TEST_COLMAP_LEARNED") != "1":
        pytest.skip("Set SPLATFORGE_TEST_COLMAP_LEARNED=1 and provide pinned local ONNX models")
    executable = None if configured == "1" else Path(configured)
    if executable is not None and not executable.is_absolute():
        pytest.fail("SPLATFORGE_TEST_COLMAP must be an absolute path or 1")
    image = tmp_path / "texture.png"
    ColmapCapabilityAdapter._write_test_image(image)
    pixels = image.read_bytes()
    original = upstream.FakeProbe.probe

    def probe(self, *args, **kwargs):
        return original(self, *args, **kwargs).model_copy(update={"width": 192, "height": 192})

    monkeypatch.setattr(upstream.FakeProbe, "probe", probe)
    monkeypatch.setattr(upstream, "png", lambda _width, _height: pixels)
    value = upstream.harness(tmp_path)
    views = upstream.prepare(value)
    hashes = {p: hash_file(p) for p in (value.root / "artifacts").rglob("*") if p.is_file()}
    service = FeaturesService(value.execution, ColmapFeatureAdapter())
    settings = resolve_extraction_settings(
        variant,
        max_image_size=192,
        use_gpu=os.environ.get("SPLATFORGE_TEST_COLMAP_FEATURE_GPU") == "1",
    )
    try:
        result = service.extract(
            value.root,
            views_run_id=views.run_id,
            settings=settings,
            colmap=executable,
            model_directory=(
                Path(v) if (v := os.environ.get("SPLATFORGE_COLMAP_MODEL_DIR")) else None
            ),
        )
    except FeatureCapabilityError as exc:
        if variant == "SIFT":
            pytest.fail(f"Configured real SIFT installation is not compatible: {exc}")
        pytest.skip(f"Learned capability gap: {exc}")
    assert result.status == "succeeded" and result.total_feature_count > 0
    assert all(hash_file(p) == digest for p, digest in hashes.items())
    record_property("feature_method", variant)
    record_property("feature_semantic_digest", result.feature_artifact.semantic_digest)
    record_property("feature_count", result.total_feature_count)
    # Known native log profiles must emit genuine image evidence; generic
    # backends retain phase-only progress and their terminal successful sample.
    import json

    events = [
        json.loads(line)
        for line in (value.root / "runs" / str(result.run_id) / "events.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    observations = [
        e["details"].get("observation") for e in events if e["code"] == "progress.snapshot"
    ]
    route = value.execution.read_progress_evidence(value.root, result.run_id).snapshot.route
    if route.backend.live_progress_profile:
        assert any(o and o["completed"] > 0 for o in observations)
    assert service.extract(
        value.root,
        views_run_id=views.run_id,
        settings=settings,
        colmap=executable,
        model_directory=(Path(v) if (v := os.environ.get("SPLATFORGE_COLMAP_MODEL_DIR")) else None),
    ).cache_hit
