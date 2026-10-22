"""M7b real persistence lifecycle through synthetic native workers."""

import json
from types import SimpleNamespace
from uuid import UUID

import pytest
from matching_helpers import inputs, match, verify
from test_views_execution import query

from splatforge.adapters.colmap_features import hash_file
from splatforge.adapters.execution_storage import ExecutionFaultHooks, LocalExecutionRepository
from splatforge.adapters.fake_stages import LocalFakeStages
from splatforge.adapters.performance import LocalPerformanceHistory
from splatforge.adapters.project_storage import LocalProjectStore
from splatforge.application.execution import FakeExecutionService, PublicationUnresolvedError
from splatforge.application.progress import ProgressSupport
from splatforge.application.progress_reader import RunProgressService
from splatforge.core.geometry import VerificationSettings, uncalibrated_camera_priors
from splatforge.core.matching import MatchingResourceLimits


def hashes(root):
    return {p: hash_file(p) for p in (root / "artifacts").rglob("*") if p.is_file()}


def test_raw_and_verification_cache_pair_universe_and_immutable_bytes(tmp_path):
    value, fixture, features, pairs = inputs(tmp_path)
    before = hashes(value.root)
    raw = match(value, fixture, features, pairs)
    parsed = value.execution.load_match_set(value.root, raw.artifact)
    assert (
        parsed.requested_pair_count,
        parsed.processed_pair_count,
        parsed.matched_pair_count,
        parsed.zero_match_pair_count,
        parsed.total_raw_match_count,
    ) == (3, 3, 2, 1, 30)
    assert [p.raw_match_count for p in parsed.pairs] == [24, 0, 6]
    assert all(hash_file(p) == digest for p, digest in before.items())
    assert match(value, fixture, features, pairs).cache_hit
    after_raw = hashes(value.root)
    checked = verify(value, fixture, raw)
    geometry = value.execution.load_verified_geometry(value.root, checked.artifact)
    assert [p.state for p in geometry.pairs] == [
        "verified",
        "no_raw_matches",
        "insufficient_raw_matches",
    ]
    assert (checked.accepted_pairs, checked.verified_inliers) == (1, 24)
    assert all(hash_file(p) == digest for p, digest in after_raw.items())
    assert verify(value, fixture, raw).cache_hit
    for result, model, total in (
        (raw, "matching.explicit_pairs_v1", 3),
        (checked, "verification.raw_match_pairs_v1", 2),
    ):
        state = RunProgressService(value.execution).get(value.root, result.run_id).stages[0]
        assert (state.work.work_model_id, state.work.unit, state.work.total) == (
            model,
            "pairs",
            total,
        )
    for request in fixture.requests:
        if request.argv[0] == "matches_importer" and len(request.argv) > 2:
            assert request.argv[request.argv.index("--match_type") + 1] == "pairs"
            assert (
                request.argv[
                    request.argv.index("--FeatureMatching.skip_geometric_verification") + 1
                ]
                == "1"
            )
            assert request.argv[request.argv.index("--TwoViewGeometry.min_num_inliers") + 1] == "1"


@pytest.mark.parametrize(
    "extractor,matcher",
    [
        ("SIFT", "SIFT_LIGHTGLUE"),
        ("ALIKED_N16ROT", "ALIKED_LIGHTGLUE"),
        ("ALIKED_N32", "ALIKED_BRUTEFORCE"),
        ("LOMA_B", "LOMA_B"),
        ("LOMA_B", "LOMA_R"),
        ("LOMA_B", "LOMA_L"),
        ("LOMA_B", "LOMA_G"),
        ("LOMA_B128", "LOMA_B128"),
        ("LOMA_B128", "LOMA_BRUTEFORCE"),
    ],
)
def test_each_production_family_uses_same_services(tmp_path, extractor, matcher):
    value, fixture, features, pairs = inputs(tmp_path, variant=extractor)
    result = match(value, fixture, features, pairs, matcher=matcher)
    assert verify(value, fixture, result).status == "succeeded"
    payload = value.execution.load_match_set(value.root, result.artifact)
    assert payload.models and payload.models[0].sha256
    assert not any(
        "https://" in arg
        for r in fixture.requests
        if r.argv[0] == "matches_importer" and len(r.argv) > 2
        for arg in r.argv
    )


def test_cache_dependencies_and_unchanged_explicit_project_intent(tmp_path):
    value, fixture, features, pairs = inputs(tmp_path)
    original = (value.root / "project.json").read_bytes()
    raw = match(value, fixture, features, pairs)
    verified = verify(value, fixture, raw)
    changed = verify(value, fixture, raw, settings=VerificationSettings(max_error=2))
    assert not changed.cache_hit and changed.artifact.recipe_key != verified.artifact.recipe_key
    assert match(value, fixture, features, pairs).cache_hit
    fs = value.execution.load_local_features(value.root, features.feature_artifact)
    camera = uncalibrated_camera_priors(fs)
    camera = camera.model_copy(
        update={
            "cameras": tuple(
                c.model_copy(update={"parameters": (90.0, c.width / 2, c.height / 2, 0.0)})
                for c in camera.cameras
            )
        }
    )
    assert not verify(value, fixture, raw, cameras=camera).cache_hit
    assert match(value, fixture, features, pairs).cache_hit
    different = match(value, fixture, features, pairs, matcher="SIFT_LIGHTGLUE")
    assert not different.cache_hit and different.artifact.recipe_key != raw.artifact.recipe_key
    assert (value.root / "project.json").read_bytes() == original


@pytest.mark.parametrize(
    "stage,mode",
    [
        ("match", v)
        for v in (
            "failed",
            "timeout",
            "oom",
            "forced",
            "index",
            "duplicate",
            "shape",
            "unexpected",
            "missing",
            "stale_geometry",
        )
    ]
    + [
        ("verify", v)
        for v in ("failed", "timeout", "oom", "matrix", "config", "mutate_raw", "unexpected")
    ],
)
def test_invalid_or_failed_backend_never_publishes_or_falls_back(tmp_path, stage, mode):
    value, fixture, features, pairs = inputs(tmp_path)
    raw = match(value, fixture, features, pairs) if stage == "verify" else None
    before = hashes(value.root)
    fixture.match_mode, fixture.verify_mode = (
        (mode, "success") if stage == "match" else ("success", mode)
    )
    history = LocalPerformanceHistory(tmp_path / "history.sqlite")
    with pytest.raises(ValueError):
        if raw:
            verify(value, fixture, raw, progress=ProgressSupport(history=history))
        else:
            match(value, fixture, features, pairs, progress=ProgressSupport(history=history))
    assert history.statistics().sample_count == 0
    assert all(hash_file(p) == digest for p, digest in before.items())
    assert query(value.root, "SELECT status FROM runs ORDER BY created_at DESC LIMIT 1") == [
        ("failed",)
    ]
    if stage == "match":
        failed = UUID(
            query(value.root, "SELECT run_id FROM runs ORDER BY created_at DESC LIMIT 1")[0][0]
        )
        with pytest.raises(ValueError, match="--matches-run must reference a succeeded"):
            verify(value, fixture, SimpleNamespace(run_id=failed))
    work = [
        r
        for r in fixture.requests
        if "work" in r.working_directory.parts
        and r.argv[0] in ("matches_importer", "geometric_verifier")
    ]
    assert len(work) == (2 if raw else 1)  # no runtime algorithm substitution


@pytest.mark.parametrize("stage", ["match", "verify"])
def test_cancellation_and_unresolved_teardown(tmp_path, stage):
    value, fixture, features, pairs = inputs(tmp_path)
    raw = match(value, fixture, features, pairs) if stage == "verify" else None

    def cancel(control):
        value.execution.request_cancellation(value.root, run_id=control.run)
        assert control.is_cancelled()

    if raw:
        fixture.on_verify, fixture.verify_mode = cancel, "cancelled"
        assert verify(value, fixture, raw).status == "cancelled"
        fixture.on_verify, fixture.verify_mode = None, "unresolved"
    else:
        fixture.on_match, fixture.match_mode = cancel, "cancelled"
        assert match(value, fixture, features, pairs).status == "cancelled"
        fixture.on_match, fixture.match_mode = None, "unresolved"
    with pytest.raises(ValueError, match="teardown"):
        verify(value, fixture, raw) if raw else match(value, fixture, features, pairs)
    assert query(
        value.root, "SELECT teardown_state FROM attempts ORDER BY started_at DESC LIMIT 1"
    ) == [("unresolved",)]


def test_budget_and_incompatible_signature_fail_before_native_probe(tmp_path):
    value, fixture, features, pairs = inputs(tmp_path)
    fixture.requests.clear()
    with pytest.raises(ValueError, match="budget"):
        match(value, fixture, features, pairs, resource_limits=MatchingResourceLimits(max_pairs=1))
    with pytest.raises(ValueError, match="Incompatible"):
        match(value, fixture, features, pairs, matcher="LOMA_B128")
    assert not fixture.requests


def test_profile_execution_pins_backend_and_model_evidence(tmp_path):
    from splatforge.application.matching import MatchingService
    from splatforge.application.sfm_profiles import SfmProfileService
    from splatforge.core.features import resolve_extraction_settings
    from splatforge.core.matching import resolve_matching_settings
    from splatforge.core.sfm_profiles import FeatureMatchingChoice

    value, fixture, features, pairs = inputs(tmp_path)
    choice = FeatureMatchingChoice(
        extractor=resolve_extraction_settings("SIFT"),
        matcher=resolve_matching_settings("SIFT_BRUTEFORCE"),
    )
    resolution = SfmProfileService(fixture.adapter(), fixture.matching_adapter()).resolve(
        choice=choice, colmap=fixture.exe, model_directory=fixture.model_root
    )
    service = MatchingService(value.execution, fixture.matching_adapter())
    raw = service.match(
        value.root,
        features_run_id=features.run_id,
        pairs_run_id=pairs.run_id,
        settings=choice.matcher,
        colmap=fixture.exe,
        model_directory=fixture.model_root,
        resolution=resolution,
    )
    assert (
        service.verify(
            value.root, matches_run_id=raw.run_id, colmap=fixture.exe, resolution=resolution
        ).status
        == "succeeded"
    )
    changed = resolution.model_copy(
        update={
            "decisions": (
                resolution.decisions[-1].model_copy(update={"matcher_backend_identity": "f" * 64}),
            )
        }
    )
    with pytest.raises(ValueError, match="identity changed"):
        service.match(
            value.root,
            features_run_id=features.run_id,
            pairs_run_id=pairs.run_id,
            settings=choice.matcher,
            colmap=fixture.exe,
            model_directory=fixture.model_root,
            resolution=changed,
        )


def test_verification_memory_budget_fails_before_native_probe(tmp_path):
    value, fixture, features, pairs = inputs(tmp_path)
    raw = match(value, fixture, features, pairs)
    fixture.requests.clear()
    with pytest.raises(ValueError, match="working-memory budget"):
        verify(
            value, fixture, raw, resource_limits=MatchingResourceLimits(max_pair_working_bytes=1)
        )
    assert not fixture.requests


def test_published_features_do_not_require_extractor_models_or_operation(tmp_path):
    value, fixture, features, pairs = inputs(tmp_path, variant="LOMA_B")
    for name in ("loma-detector.onnx", "loma-b.onnx"):
        (fixture.model_root / name).unlink()
    fixture.top_help = fixture.top_help.replace("  feature_extractor\n", "")
    fixture.requests.clear()
    raw = match(value, fixture, features, pairs, matcher="LOMA_R")
    assert raw.status == "succeeded"
    assert not any(r.argv[0] == "feature_extractor" for r in fixture.requests)
    assert verify(value, fixture, raw).status == "succeeded"
    assert not any(r.argv[0] == "feature_extractor" for r in fixture.requests)


@pytest.mark.parametrize("stage", ["match", "verify"])
def test_orphan_publication_recovery_uses_frozen_recipe(tmp_path, stage):
    value, fixture, features, pairs = inputs(tmp_path)
    raw = match(value, fixture, features, pairs) if stage == "verify" else None

    def fail(_path):
        raise OSError("synthetic publication interruption")

    repo = LocalExecutionRepository(
        project_store=LocalProjectStore(), fault_hooks=ExecutionFaultHooks(after_artifact_move=fail)
    )
    from splatforge.application.matching import MatchingService
    from splatforge.core.matching import resolve_matching_settings

    service = MatchingService(repo, fixture.matching_adapter())
    with pytest.raises(PublicationUnresolvedError):
        if raw:
            service.verify(value.root, matches_run_id=raw.run_id, colmap=fixture.exe)
        else:
            service.match(
                value.root,
                features_run_id=features.run_id,
                pairs_run_id=pairs.run_id,
                settings=resolve_matching_settings("SIFT_BRUTEFORCE"),
                colmap=fixture.exe,
                model_directory=fixture.model_root,
            )
    run = UUID(query(value.root, "SELECT run_id FROM runs WHERE status='running'")[0][0])
    recovered = FakeExecutionService(value.execution, LocalFakeStages()).recover(value.root, run)
    assert recovered.status == "succeeded" and len(recovered.adopted_attempts) == 1


def test_progress_success_learns_but_cache_and_failures_do_not(tmp_path):
    from progress_helpers import FakeClock

    value, fixture, features, pairs = inputs(tmp_path)
    history = LocalPerformanceHistory(tmp_path / "history.sqlite")
    clock = FakeClock()
    support = ProgressSupport(clock=clock, history=history)
    fixture.on_match = lambda _control: clock.advance(3)
    raw = match(value, fixture, features, pairs, progress=support)
    assert history.statistics().sample_count == 1
    assert match(value, fixture, features, pairs, progress=support).cache_hit
    assert history.statistics().sample_count == 1
    fixture.on_verify = lambda _control: clock.advance(3)
    verify(value, fixture, raw, progress=support)
    assert history.statistics().sample_count == 2
    events = [
        json.loads(line)
        for line in (value.root / "runs" / str(raw.run_id) / "events.jsonl")
        .read_text()
        .splitlines()
    ]
    running = [
        e["details"]["snapshot"]["stages"][0]
        for e in events
        if e["code"] == "progress.snapshot"
        and e["details"]["snapshot"]["stages"][0]["status"] == "running"
    ]
    assert running and all(s["completed"] == 0 for s in running)
