"""Opt-in real production families, identical explicit PairSet, immutable stages."""

import json
import os
import sqlite3
import time
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
import test_views_execution as upstream
from PIL import Image, ImageDraw
from test_pairs_execution import build as build_pairs

from splatforge.adapters.colmap_capabilities import ColmapCapabilityAdapter
from splatforge.adapters.colmap_features import ColmapFeatureAdapter, hash_file
from splatforge.adapters.colmap_matching import ColmapMatchingAdapter
from splatforge.application.features import FeaturesService
from splatforge.application.matching import MatchingService
from splatforge.application.model_provisioning import learned_route_provisioning
from splatforge.application.progress_reader import RunProgressService
from splatforge.application.sfm_profiles import SfmProfileService
from splatforge.core.capabilities import FreshnessPolicy
from splatforge.core.execution import RunSnapshot
from splatforge.core.features import model_roles, resolve_extraction_settings
from splatforge.core.geometry import (
    CameraPriorSet,
    VerificationSettings,
    uncalibrated_camera_priors,
)
from splatforge.core.matching import matcher_model_role, resolve_matching_settings
from splatforge.core.pairs import ExhaustiveSettings
from splatforge.core.sfm_profiles import FeatureMatchingChoice, SfmDevicePolicy

ROUTES = (
    ("SIFT", "SIFT_BRUTEFORCE"),
    ("SIFT", "SIFT_LIGHTGLUE"),
    ("ALIKED_N16ROT", "ALIKED_BRUTEFORCE"),
    ("ALIKED_N16ROT", "ALIKED_LIGHTGLUE"),
    ("ALIKED_N32", "ALIKED_BRUTEFORCE"),
    ("ALIKED_N32", "ALIKED_LIGHTGLUE"),
    ("LOMA_B128", "LOMA_BRUTEFORCE"),
    ("LOMA_B128", "LOMA_B128"),
    ("LOMA_B", "LOMA_BRUTEFORCE"),
    ("LOMA_B", "LOMA_B"),
    ("LOMA_B", "LOMA_R"),
    ("LOMA_B", "LOMA_L"),
    ("LOMA_B", "LOMA_G"),
)


@pytest.mark.integration
@pytest.mark.parametrize("extractor,matcher", ROUTES)
def test_real_explicit_raw_then_verification(
    tmp_path, monkeypatch, record_property, extractor, matcher
):
    configured = os.environ.get("SPLATFORGE_TEST_COLMAP")
    if not configured:
        pytest.skip("Set SPLATFORGE_TEST_COLMAP to an absolute native COLMAP 4.2.1 path")
    extraction = resolve_extraction_settings(extractor, max_image_size=192)
    matching = resolve_matching_settings(matcher)
    learned = bool(model_roles(extraction) or matcher_model_role(matching))
    if learned and os.environ.get("SPLATFORGE_TEST_COLMAP_LEARNED") != "1":
        pytest.skip(
            f"{extractor}+{matcher}: set SPLATFORGE_TEST_COLMAP_LEARNED=1 and "
            "SPLATFORGE_COLMAP_MODEL_DIR; exact required model names/hashes: doctor --deep"
        )
    if matcher in ("LOMA_L", "LOMA_G") and os.environ.get("SPLATFORGE_TEST_COLMAP_HEAVY") != "1":
        pytest.skip(f"{matcher}: additionally set SPLATFORGE_TEST_COLMAP_HEAVY=1")
    executable = None if configured == "1" else Path(configured)
    if executable is not None and not executable.is_absolute():
        pytest.fail("SPLATFORGE_TEST_COLMAP must be absolute or 1")
    model_root = Path(v) if (v := os.environ.get("SPLATFORGE_COLMAP_MODEL_DIR")) else None
    choice = FeatureMatchingChoice(
        extractor=extraction,
        matcher=matching,
    )
    if learned:
        report = ColmapCapabilityAdapter().probe(
            explicit_executable=executable, explicit_model_directory=model_root,
            bundled_executable=None, bundled_model_directory=None, deep=False,
            observed_at=datetime.now(UTC), freshness=FreshnessPolicy(),
        )
        provisioning = learned_route_provisioning(choice, report)
        record_property("provisioning", provisioning.model_dump_json())
        if not provisioning.ready:
            pytest.skip(provisioning.model_dump_json())
    extractor_adapter, matcher_adapter = ColmapFeatureAdapter(), ColmapMatchingAdapter()
    policy = os.environ.get("SPLATFORGE_TEST_COLMAP_DEVICE")
    if policy is None:
        policy = ("gpu:0" if os.environ.get("SPLATFORGE_TEST_COLMAP_FEATURE_GPU") == "1"
                  else "cpu" if extractor == "SIFT" else "auto")
    resolved = SfmProfileService(extractor_adapter, matcher_adapter).resolve(
        choice=choice, device_policy=SfmDevicePolicy(policy),
        colmap=executable, model_directory=model_root,
    )
    record_property("resolved_route", resolved.model_dump_json())
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
    pairs = build_pairs(value, views, settings=ExhaustiveSettings())
    features_service = FeaturesService(value.execution, extractor_adapter)
    service = MatchingService(value.execution, matcher_adapter)
    started = time.monotonic()
    features = features_service.extract(
        value.root,
        views_run_id=views.run_id,
        settings=resolved.choice.extractor,
        colmap=executable,
        model_directory=model_root,
    )
    feature_seconds = time.monotonic() - started
    hashes = {p: hash_file(p) for p in (value.root / "artifacts").rglob("*") if p.is_file()}
    assert features_service.extract(
        value.root, views_run_id=views.run_id, settings=resolved.choice.extractor,
        colmap=executable, model_directory=model_root,
    ).cache_hit
    started = time.monotonic()
    raw = service.match(
        value.root,
        features_run_id=features.run_id,
        pairs_run_id=pairs.run_id,
        settings=resolved.choice.matcher,
        resolution=resolved,
        colmap=executable,
        model_directory=model_root,
    )
    matching_seconds = time.monotonic() - started
    assert all(hash_file(p) == digest for p, digest in hashes.items())
    raw_set = value.execution.load_match_set(value.root, raw.artifact)
    features_set = value.execution.load_local_features(value.root, features.feature_artifact)
    assert raw_set.models == resolved.decisions[-1].matcher_models
    assert features_set.models == resolved.decisions[-1].extractor_models
    assert raw_set.settings.use_gpu == (resolved.resolved_device == "gpu:0")
    raw_directory = (value.root / raw.artifact.manifest_path).parent
    with closing(sqlite3.connect((raw_directory / "matches.db").as_uri() + "?mode=ro",
                                 uri=True)) as database:
        assert database.execute("SELECT COUNT(*) FROM two_view_geometries").fetchone() == (0,)
    assert raw_set.requested_pair_count == 3 and raw_set.total_raw_match_count > 0
    assert [(p.left_view_id, p.right_view_id) for p in raw_set.pairs] == [
        (p.left_view_id, p.right_view_id)
        for p in value.execution.load_pair_set(value.root, pairs.pair_set_artifact).pairs
    ]
    after_raw = {p: hash_file(p) for p in (value.root / "artifacts").rglob("*") if p.is_file()}
    started = time.monotonic()
    geometry = service.verify(
        value.root, matches_run_id=raw.run_id, colmap=executable, settings=VerificationSettings()
    )
    verification_seconds = time.monotonic() - started
    assert geometry.accepted_pairs > 0 and geometry.verified_inliers > 0
    assert all(hash_file(p) == digest for p, digest in after_raw.items())
    assert service.match(
        value.root,
        features_run_id=features.run_id,
        pairs_run_id=pairs.run_id,
        settings=resolved.choice.matcher,
        resolution=resolved,
        colmap=executable,
        model_directory=model_root,
    ).cache_hit
    assert service.verify(value.root, matches_run_id=raw.run_id, colmap=executable).cache_hit
    progress = RunProgressService(value.execution)
    for result, model in ((raw, "matching.explicit_pairs_v1"),
                          (geometry, "verification.raw_match_pairs_v1")):
        state = progress.get(value.root, result.run_id).stages[0]
        assert state.work.work_model_id == model and state.work.unit == "pairs"
        snapshot = RunSnapshot.model_validate_json(
            (value.root / "runs" / str(result.run_id) / "run.json").read_bytes()
        )
        if result == raw:
            assert snapshot.route.resolution == resolved
            raw_backend = snapshot.route.backend
    if extractor == "SIFT":
        prior_set = uncalibrated_camera_priors(
            value.execution.load_local_features(value.root, features.feature_artifact)
        )
        shared = CameraPriorSet(
            cameras=tuple(
                c.model_copy(update={"camera_group_id": UUID(int=1)}) for c in prior_set.cameras
            )
        )
        regrouped = service.verify(
            value.root, matches_run_id=raw.run_id, colmap=executable, cameras=shared
        )
        assert regrouped.status == "succeeded" and not regrouped.cache_hit
        assert regrouped.artifact.recipe_key != geometry.artifact.recipe_key
        assert service.verify(
            value.root, matches_run_id=raw.run_id, colmap=executable, cameras=shared
        ).cache_hit
        assert all(hash_file(p) == digest for p, digest in after_raw.items())
    details = {
        "extractor": extractor,
        "matcher": matcher,
        "views": features.selected_view_count,
        "feature_count": features.total_feature_count,
        "requested_pairs": raw.pair_count,
        "raw_matches": raw.raw_matches,
        "verified_pairs": geometry.accepted_pairs,
        "inliers": geometry.verified_inliers,
        "matching_seconds": matching_seconds,
        "feature_seconds": feature_seconds,
        "verification_seconds": verification_seconds,
        "matching_cache_hit": True,
        "feature_cache_hit": True,
        "verification_cache_hit": True,
        "precision": raw_backend.actual_precision,
        "immutable_upstream": True,
        "resolved_device": resolved.resolved_device,
        "extractor_models": [m.model_dump() for m in features_set.models],
        "matcher_models": [m.model_dump() for m in raw_set.models],
        "backend_identity": raw_set.backend_numerical_identity,
        "executable_sha256": raw_backend.selection.identity.sha256,
        "colmap_version": raw_backend.selection.identity.version_line,
        "progress": "separate PAIRS work models verified",
        "explicit_shared_camera_validation": extractor == "SIFT",
    }
    for name, value in details.items():
        record_property(name, value)
    print(json.dumps(details))


@pytest.mark.integration
@pytest.mark.parametrize("scene", ["textured_with_empty", "sparse_with_empty"])
def test_real_sift_preserves_empty_and_insufficient_pairs(
    tmp_path, monkeypatch, record_property, scene
):
    configured = os.environ.get("SPLATFORGE_TEST_COLMAP")
    if not configured:
        pytest.skip("Set SPLATFORGE_TEST_COLMAP to an absolute native COLMAP 4.2.1 path")
    executable = None if configured == "1" else Path(configured)
    if executable is not None and not executable.is_absolute():
        pytest.fail("SPLATFORGE_TEST_COLMAP must be absolute or 1")
    texture = tmp_path / "texture.png"
    if scene == "sparse_with_empty":
        with Image.new("RGB", (192, 192)) as image:
            ImageDraw.Draw(image).polygon(
                [(60, 60), (100, 60), (100, 80), (80, 80), (80, 100), (60, 100)],
                fill=(255, 255, 255),
            )
            image.save(texture)
    else:
        ColmapCapabilityAdapter._write_test_image(texture)
    pixels = texture.read_bytes()
    empty = upstream.png(192, 192)
    frames = iter((pixels, pixels, pixels, empty))
    original = upstream.FakeProbe.probe

    def probe(self, *args, **kwargs):
        return original(self, *args, **kwargs).model_copy(update={"width": 192, "height": 192})

    monkeypatch.setattr(upstream.FakeProbe, "probe", probe)
    monkeypatch.setattr(upstream, "png", lambda _w, _h: next(frames))
    value = upstream.harness(tmp_path)
    views = upstream.prepare(value)
    pairs = build_pairs(value, views, settings=ExhaustiveSettings())
    features = FeaturesService(value.execution, ColmapFeatureAdapter()).extract(
        value.root,
        views_run_id=views.run_id,
        settings=resolve_extraction_settings("SIFT", max_image_size=192),
        colmap=executable,
    )
    feature_set = value.execution.load_local_features(value.root, features.feature_artifact)
    assert sum(v.feature_count == 0 for v in feature_set.views) == 1
    before = {p: hash_file(p) for p in (value.root / "artifacts").rglob("*") if p.is_file()}
    service = MatchingService(value.execution, ColmapMatchingAdapter())
    raw = service.match(
        value.root,
        features_run_id=features.run_id,
        pairs_run_id=pairs.run_id,
        settings=resolve_matching_settings("SIFT_BRUTEFORCE"),
        colmap=executable,
    )
    match_set = value.execution.load_match_set(value.root, raw.artifact)
    assert match_set.requested_pair_count == 3 and match_set.zero_match_pair_count == 2
    after_raw = {p: hash_file(p) for p in (value.root / "artifacts").rglob("*") if p.is_file()}
    minimum = max(8, raw.raw_matches + 1) if scene == "sparse_with_empty" else 15
    checked = service.verify(
        value.root,
        matches_run_id=raw.run_id,
        settings=VerificationSettings(min_num_inliers=minimum),
        colmap=executable,
    )
    geometry = value.execution.load_verified_geometry(value.root, checked.artifact)
    states = sorted(p.state.value for p in geometry.pairs)
    assert geometry.eligible_pair_count == 1 and states.count("no_raw_matches") == 2
    assert states.count("insufficient_raw_matches") == (scene == "sparse_with_empty")
    assert geometry.accepted_pair_count == (scene == "textured_with_empty")
    assert all(hash_file(p) == digest for p, digest in before.items())
    assert all(hash_file(p) == digest for p, digest in after_raw.items())
    details = {
        "scene": scene,
        "views": 3,
        "requested_pairs": 3,
        "zero_match_pairs": 2,
        "raw_matches": raw.raw_matches,
        "minimum_inliers": minimum,
        "verified_pairs": checked.accepted_pairs,
        "inliers": checked.verified_inliers,
        "states": states,
        "immutable_upstream": True,
    }
    record_property("edge_case_result", json.dumps(details))
    print(json.dumps(details))
