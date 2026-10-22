"""Opt-in real M7 -> Global transport on tiny synthetic perspective views.

Unlike M7's identical textures, mapping needs translational parallax. This extends
that harness with deterministic multi-depth texture patches, not a quality benchmark.
"""

import io
import json
import os
import random
import time
from pathlib import Path
from uuid import UUID

import pytest
import test_views_execution as upstream
from PIL import Image
from test_pairs_execution import build as build_pairs

from splatforge.adapters.colmap_features import ColmapFeatureAdapter, hash_file
from splatforge.adapters.colmap_mapping import ColmapMappingAdapter
from splatforge.adapters.colmap_matching import ColmapMatchingAdapter
from splatforge.application.features import FeaturesService
from splatforge.application.mapping import MappingService
from splatforge.application.matching import MatchingService
from splatforge.core.features import SiftExtractionSettings
from splatforge.core.geometry import CameraPriorSet, VerificationSettings, ViewCameraPrior
from splatforge.core.matching import SiftBruteforceSettings
from splatforge.core.pairs import ExhaustiveSettings
from splatforge.core.reconstruction import GlobalMapperSettings, MappingCalibrationPolicy


def perspective_pixels(camera_x):
    rng = random.Random(7038)
    image = Image.new("RGB", (640, 480), (25, 25, 25))
    for row in range(8):
        for column in range(10):
            z = rng.uniform(4, 7)
            x, y = (column - 4.5) * 0.55, (row - 3.5) * 0.5
            texture = Image.frombytes("L", (40, 40), bytes(rng.randrange(256) for _ in range(1600)))
            size = round(400 * 0.4 / z)
            texture = texture.resize((size, size), Image.Resampling.BICUBIC).convert("RGB")
            u, v = (
                round(320 + 400 * (x - camera_x) / z - size / 2),
                round(240 + 400 * y / z - size / 2),
            )
            image.paste(texture, (u, v))
    with io.BytesIO() as stream:
        image.save(stream, format="PNG")
        return stream.getvalue()


@pytest.mark.integration
@pytest.mark.parametrize(
    "policy", [MappingCalibrationPolicy.PRESERVE_PRIORS, MappingCalibrationPolicy.VIEW_GRAPH]
)
def test_real_global_mapping(tmp_path, monkeypatch, record_property, policy):
    configured = os.environ.get("SPLATFORGE_TEST_COLMAP")
    if not configured:
        pytest.skip("Set SPLATFORGE_TEST_COLMAP to an installed tested COLMAP 4.2.1 executable")
    if (
        policy == MappingCalibrationPolicy.VIEW_GRAPH
        and os.environ.get("SPLATFORGE_TEST_MAPPING_CALIBRATION") != "1"
    ):
        pytest.skip("Set SPLATFORGE_TEST_MAPPING_CALIBRATION=1 for explicit calibration smoke")
    executable = Path(configured)
    assert executable.is_absolute()
    original = upstream.FakeProbe.probe
    monkeypatch.setattr(
        upstream.FakeProbe,
        "probe",
        lambda self, *a, **k: original(self, *a, **k).model_copy(
            update={"width": 640, "height": 480}
        ),
    )
    pixels = iter(perspective_pixels(x) for x in (-0.3, -0.1, 0.1, 0.3))
    monkeypatch.setattr(upstream, "png", lambda _w, _h: next(pixels))
    value = upstream.harness(tmp_path)
    views = upstream.prepare(value, resource_limits=upstream.limits(byte_count=100000000))
    pairs = build_pairs(value, views, settings=ExhaustiveSettings())
    features = FeaturesService(value.execution, ColmapFeatureAdapter()).extract(
        value.root,
        views_run_id=views.run_id,
        settings=SiftExtractionSettings(max_image_size=640),
        colmap=executable,
    )
    feature_set = value.execution.load_local_features(value.root, features.feature_artifact)
    matching = MatchingService(value.execution, ColmapMatchingAdapter())
    raw = matching.match(
        value.root,
        features_run_id=features.run_id,
        pairs_run_id=pairs.run_id,
        settings=SiftBruteforceSettings(),
        colmap=executable,
    )
    cameras = CameraPriorSet(
        cameras=tuple(
            ViewCameraPrior(
                view_id=v.view_id,
                camera_group_id=UUID(int=1),
                model="SIMPLE_PINHOLE",
                width=640,
                height=480,
                parameters=(400, 320, 240),
                prior_focal_length=True,
            )
            for v in feature_set.views
        )
    )
    verified = matching.verify(
        value.root,
        matches_run_id=raw.run_id,
        settings=VerificationSettings(compute_relative_pose=True),
        cameras=cameras,
        colmap=executable,
    )
    geometry = value.execution.load_verified_geometry(value.root, verified.artifact)
    before = {p: hash_file(p) for p in (value.root / "artifacts").rglob("*") if p.is_file()}
    service = MappingService(value.execution, ColmapMappingAdapter())
    started = time.monotonic()
    result = service.run(
        value.root,
        verification_run_id=verified.run_id,
        colmap=executable,
        calibration_policy=policy,
    )
    runtime = time.monotonic() - started
    assert result.status == "succeeded" and not result.cache_hit
    reconstruction = result.reconstruction
    assert reconstruction.component_count >= 1 and reconstruction.registered_view_count >= 3
    assert all(hash_file(p) == h for p, h in before.items())
    reader = service.reader(value.root, result.run_id)
    for component in reader.components():
        assert (
            len(tuple(reader.registered_views(component.component_id)))
            == component.registered_view_count
        )
        assert len(tuple(reader.cameras(component.component_id))) == component.camera_count
    published = {p: hash_file(p) for p in (value.root / "artifacts").rglob("*") if p.is_file()}
    assert service.run(
        value.root,
        verification_run_id=verified.run_id,
        colmap=executable,
        calibration_policy=policy,
    ).cache_hit
    assert all(hash_file(p) == h for p, h in published.items())
    diagnostics = list(
        (value.root / "runs" / str(result.run_id) / "attempts").glob("*/process.jsonl")
    )
    records = [
        json.loads(line)
        for path in diagnostics
        for line in path.read_text(encoding="utf-8").splitlines()
    ]
    metrics = {
        "input_views": len(feature_set.views),
        "verified_pairs": geometry.accepted_pair_count,
        "components": reconstruction.component_count,
        "registered_views": [c.registered_view_count for c in reconstruction.components],
        "unregistered_views": reconstruction.unregistered_view_count,
        "points": [c.point_count for c in reconstruction.components],
        "mapping_api_seconds": runtime,
        "cache_hit": True,
        "calibration": policy,
        "process_evidence": records,
        "semantic_digest": reconstruction.semantic_digest,
    }
    record_property("m8a_metrics", json.dumps(metrics))
    print(json.dumps(metrics, ensure_ascii=True))
    if policy == MappingCalibrationPolicy.PRESERVE_PRIORS:
        # Cancel a genuinely launched owned Global process through the existing owner poll.
        adapter = ColmapMappingAdapter()
        native_runner = adapter._runner

        class CancelRunner:
            def run(self, request, *, cancellation=None, poll=None):
                if request.argv[0] != "global_mapper" or len(request.argv) == 2:
                    return native_runner.run(
                        request, cancellation=cancellation, **({"poll": poll} if poll else {})
                    )
                owner = cancellation
                while hasattr(owner, "owner"):
                    owner = owner.owner

                def cancel_poll():
                    value.execution.request_cancellation(value.root, run_id=owner.run)
                    if poll:
                        poll()

                return native_runner.run(request, cancellation=cancellation, poll=cancel_poll)

        adapter._runner = CancelRunner()
        cancelled = MappingService(value.execution, adapter).run(
            value.root,
            verification_run_id=verified.run_id,
            colmap=executable,
            settings=GlobalMapperSettings(random_seed=1),
        )
        assert cancelled.status == "cancelled" and cancelled.artifact is None
        evidence_files = (value.root / "runs" / str(cancelled.run_id) / "attempts").glob(
            "*/process.jsonl"
        )
        cancel_records = [
            json.loads(line)
            for path in evidence_files
            for line in path.read_text(encoding="utf-8").splitlines()
        ]
        assert any(r["cancelled"] and r["teardown_confirmed"] for r in cancel_records)
        print(json.dumps({"real_cancellation": "confirmed", "teardown_confirmed": True}))
        assert all(hash_file(p) == h for p, h in published.items())
