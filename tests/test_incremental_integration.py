"""Opt-in real M7 -> single-model Incremental -> portable reader transport."""

import json
import os
import time
from pathlib import Path
from uuid import UUID

import pytest
import test_views_execution as upstream
from test_mapping_integration import perspective_pixels
from test_pairs_execution import build as build_pairs

from splatforge.adapters.colmap_features import ColmapFeatureAdapter, hash_file
from splatforge.adapters.colmap_mapping import ColmapMappingAdapter
from splatforge.adapters.colmap_matching import ColmapMatchingAdapter
from splatforge.application.features import FeaturesService
from splatforge.application.features_contracts import FeatureCapabilityError
from splatforge.application.mapping import MappingService
from splatforge.application.matching import MatchingService
from splatforge.core.execution import IncrementalMappingRoute, RunSnapshot
from splatforge.core.features import SiftExtractionSettings
from splatforge.core.geometry import CameraPriorSet, VerificationSettings, ViewCameraPrior
from splatforge.core.matching import SiftBruteforceSettings
from splatforge.core.pairs import ExhaustiveSettings
from splatforge.core.reconstruction import IncrementalMapperSettings, reconstruction_semantic_digest


@pytest.mark.integration
@pytest.mark.parametrize("backend", ["CERES", "CASPAR"])
def test_real_incremental_mapping(tmp_path, monkeypatch, record_property, backend):
    configured = os.environ.get("SPLATFORGE_TEST_COLMAP")
    if not configured:
        pytest.skip("Set SPLATFORGE_TEST_COLMAP to an installed supported COLMAP 4.2.1 executable")
    if backend == "CASPAR" and os.environ.get("SPLATFORGE_TEST_CASPAR") != "1":
        pytest.skip(
            "Set SPLATFORGE_TEST_CASPAR=1 for bounded Caspar build/device preflight and smoke"
        )
    executable = Path(configured)
    assert executable.is_absolute()
    index = int(os.environ.get("SPLATFORGE_TEST_CASPAR_GPU", "0"))
    settings = IncrementalMapperSettings(
        ba_local_backend=backend,
        ba_global_backend=backend,
        ba_gpu_index=index if backend == "CASPAR" else -1,
        init_min_tri_angle=4,
    )
    adapter = ColmapMappingAdapter()
    if backend == "CASPAR":
        try:
            adapter.prepare(
                "preserve_priors", colmap=executable, settings=settings, calibration=None
            )
        except FeatureCapabilityError as exc:
            if any(
                code in str(exc)
                for code in (
                    "mapping.caspar_not_compiled",
                    "mapping.gpu_unavailable",
                    "mapping.caspar_options_unknown",
                )
            ):
                pytest.skip("Caspar preflight: " + str(exc))
            raise
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
    model = "PINHOLE" if backend == "CASPAR" else "SIMPLE_PINHOLE"
    cameras = CameraPriorSet(
        cameras=tuple(
            ViewCameraPrior(
                view_id=v.view_id,
                camera_group_id=UUID(int=1),
                model=model,
                width=640,
                height=480,
                parameters=(400, 400, 320, 240) if model == "PINHOLE" else (400, 320, 240),
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
    service = MappingService(value.execution, adapter)
    started = time.monotonic()
    result = service.run(
        value.root, verification_run_id=verified.run_id, colmap=executable, settings=settings
    )
    api_runtime = time.monotonic() - started
    assert result.status == "succeeded" and not result.cache_hit
    reconstruction = result.reconstruction
    assert reconstruction.component_count == 1 and reconstruction.registered_view_count == 3
    assert reconstruction_semantic_digest(reconstruction) == reconstruction.semantic_digest
    reader = service.reader(value.root, result.run_id)
    component = next(reader.components())
    assert len(tuple(reader.registered_views(component.component_id))) == 3
    assert tuple(reader.cameras(component.component_id))
    assert all(hash_file(p) == h for p, h in before.items())
    frozen = RunSnapshot.model_validate_json(
        (value.root / "runs" / str(result.run_id) / "run.json").read_bytes()
    )
    assert type(frozen.route) is IncrementalMappingRoute
    if backend == "CASPAR":
        assert frozen.route.backend.device.index == index
        assert (
            frozen.route.settings.ba_local_backend
            == frozen.route.settings.ba_global_backend
            == "CASPAR"
        )
    assert service.run(
        value.root, verification_run_id=verified.run_id, colmap=executable, settings=settings
    ).cache_hit
    changed_settings = IncrementalMapperSettings.model_validate(
        {**settings.model_dump(), "random_seed": 1}
    )
    changed = service.run(
        value.root,
        verification_run_id=verified.run_id,
        colmap=executable,
        settings=changed_settings,
    )
    assert not changed.cache_hit and changed.artifact.recipe_key != result.artifact.recipe_key
    published = {p: hash_file(p) for p in (value.root / "artifacts").rglob("*") if p.is_file()}
    records = [
        json.loads(line)
        for path in (value.root / "runs" / str(result.run_id) / "attempts").glob("*/process.jsonl")
        for line in path.read_text(encoding="utf-8").splitlines()
    ]
    native = [r for r in records if r["tool_role"] == "colmap.mapper"]
    assert len(native) == 1 and native[0]["outcome"] == "succeeded"
    if backend == "CASPAR":
        text = (native[0]["stderr_excerpt"] or "") + (native[0]["stdout_excerpt"] or "")
        assert "Caspar" in text
        assert native[0]["argv"][native[0]["argv"].index("--Mapper.ba_gpu_index") + 1] == str(index)

    # Own and cancel a real launched mapper. A new recipe prevents accidental cache reuse.
    cancelling_adapter = ColmapMappingAdapter()
    native_runner = cancelling_adapter._runner

    class CancelRunner:
        def run(self, request, *, cancellation=None, poll=None):
            if request.argv[0] != "mapper" or len(request.argv) == 2:
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

    cancelling_adapter._runner = CancelRunner()
    cancelled = MappingService(value.execution, cancelling_adapter).run(
        value.root,
        verification_run_id=verified.run_id,
        colmap=executable,
        settings=IncrementalMapperSettings.model_validate(
            {**settings.model_dump(), "random_seed": 2}
        ),
    )
    assert cancelled.status == "cancelled" and cancelled.artifact is None
    cancel_records = [
        json.loads(line)
        for path in (value.root / "runs" / str(cancelled.run_id) / "attempts").glob(
            "*/process.jsonl"
        )
        for line in path.read_text(encoding="utf-8").splitlines()
    ]
    assert any(r["cancelled"] and r["teardown_confirmed"] for r in cancel_records)
    assert all(hash_file(p) == h for p, h in published.items())
    metrics = {
        "backend": backend,
        "camera_model": model,
        "views": len(feature_set.views),
        "verified_pairs": geometry.accepted_pair_count,
        "registered": component.registered_view_count,
        "unregistered": reconstruction.unregistered_view_count,
        "points": component.point_count,
        "native_seconds": native[0]["elapsed_seconds"],
        "api_seconds": api_runtime,
        "cache_hit": True,
        "setting_change_recomputed_mapping": True,
        "cancelled_no_artifact": True,
        "teardown_confirmed": True,
        "semantic_digest": reconstruction.semantic_digest,
        "device": frozen.route.backend.device.model_dump() if frozen.route.backend.device else None,
        "process_evidence": records,
    }
    record_property("m8b1_metrics", json.dumps(metrics))
    print(json.dumps(metrics))
