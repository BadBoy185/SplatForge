"""Device intent resolves inside an exact technology candidate, before execution."""

import pytest
from pydantic import ValidationError
from test_matching_core import assess

from splatforge.core.matching import matching_recipe_key
from splatforge.core.sfm_profiles import (
    FeatureMatchingChoice,
    ProfileResolutionError,
    ResolvedFeatureMatchingRoute,
    SfmDevicePolicy,
    SfmQualityProfile,
    on_device,
    profile_candidates,
    resolve_advanced,
    resolve_profile,
)


def recording(available):
    calls = []

    def check(choice):
        calls.append((choice.extractor.variant, choice.matcher.variant, choice.extractor.use_gpu))
        return assess(choice, () if available(choice) else (choice.matcher.variant,))

    return calls, check


@pytest.mark.parametrize("profile", SfmQualityProfile)
def test_simple_default_auto_prefers_positively_verified_gpu(profile):
    calls, check = recording(lambda c: True)
    result = resolve_profile(profile, check)
    assert result.choice == profile_candidates(profile, use_gpu=True)[0]
    assert result.requested_device_policy == "auto" and result.resolved_device == "gpu:0"
    assert len(calls) == 1 and len(result.device_decisions) == 1
    assert ResolvedFeatureMatchingRoute.model_validate_json(result.model_dump_json()) == result


def test_cpu_is_checked_for_same_technology_before_downgrade():
    calls, check = recording(lambda c: not c.extractor.use_gpu)
    result = resolve_profile(SfmQualityProfile.HIGH, check)
    assert calls == [("LOMA_B", "LOMA_L", True), ("LOMA_B", "LOMA_L", False)]
    assert result.resolved_device == "cpu" and len(result.decisions) == 1
    assert len(result.device_decisions) == 2 and result.downgrade_reason is None


def test_inventory_without_exact_runtime_proof_never_selects_gpu_or_assumes_cpu():
    calls, check = recording(lambda c: c.matcher.variant == "ALIKED_LIGHTGLUE"
                             and not c.extractor.use_gpu)
    result = resolve_profile(SfmQualityProfile.FAST, check)
    assert calls == [("LOMA_B128", "LOMA_B128", True), ("LOMA_B128", "LOMA_B128", False),
                     ("ALIKED_N16ROT", "ALIKED_LIGHTGLUE", True),
                     ("ALIKED_N16ROT", "ALIKED_LIGHTGLUE", False)]
    assert result.resolved_device == "cpu" and len(result.decisions) == 2
    assert all(d.reason for d in result.device_decisions)


@pytest.mark.parametrize("policy", [SfmDevicePolicy.CPU, SfmDevicePolicy.GPU])
@pytest.mark.parametrize("available", [False, True])
def test_advanced_explicit_device_has_one_assessment_no_fallback(policy, available):
    choice = profile_candidates(SfmQualityProfile.HIGH)[0]
    calls, check = recording(lambda c: available)
    if available:
        result = resolve_advanced(choice, check, device_policy=policy)
        assert result.resolved_device == policy.value
    else:
        with pytest.raises(ProfileResolutionError) as exc:
            resolve_advanced(choice, check, device_policy=policy)
        assert len(exc.value.device_decisions) == 1
    assert calls == [("LOMA_B", "LOMA_L", policy == SfmDevicePolicy.GPU)]


def test_advanced_auto_changes_device_only_and_keeps_all_numerical_controls():
    from splatforge.core.features import resolve_extraction_settings
    from splatforge.core.matching import resolve_matching_settings

    choice = FeatureMatchingChoice(
        extractor=resolve_extraction_settings("LOMA_B", max_features=1234),
        matcher=resolve_matching_settings("LOMA_R", min_score=0.3, num_threads=2),
    )
    calls, check = recording(lambda c: not c.extractor.use_gpu)
    result = resolve_advanced(choice, check, device_policy=SfmDevicePolicy.AUTO)
    assert calls == [("LOMA_B", "LOMA_R", True), ("LOMA_B", "LOMA_R", False)]
    assert result.choice == choice
    with pytest.raises(ProfileResolutionError) as exc:
        resolve_advanced(choice, lambda c: assess(c, ("LOMA_R",)),
                         device_policy=SfmDevicePolicy.AUTO)
    assert len(exc.value.decisions) == 1 and len(exc.value.device_decisions) == 2


def test_old_explicit_snapshot_preserves_cpu_and_mixed_device_settings():
    choice = profile_candidates(SfmQualityProfile.FAST)[-1]
    mixed = choice.model_copy(update={"matcher": on_device(choice, "gpu:0").matcher})
    result = resolve_advanced(mixed, assess)
    payload = result.model_dump(exclude={"requested_device_policy", "resolved_device",
                                         "device_decisions"})
    assert ResolvedFeatureMatchingRoute.model_validate(payload).choice == mixed
    assert result.requested_device_policy is None


def test_resolved_device_and_device_trace_cannot_disagree_with_numerical_recipe():
    result = resolve_profile(SfmQualityProfile.FAST, assess)
    with pytest.raises(ValidationError):
        ResolvedFeatureMatchingRoute.model_validate(
            {**result.model_dump(), "resolved_device": "cpu"}
        )
    with pytest.raises(ValidationError):
        ResolvedFeatureMatchingRoute.model_validate(
            {**result.model_dump(), "device_decisions": ()}
        )
    with pytest.raises(ValidationError):
        result.resolved_device = "cpu"
    with pytest.raises(ValueError):
        SfmDevicePolicy("gpu:1")


def test_policy_label_is_provenance_actual_device_is_numerical_identity():
    auto = resolve_profile(SfmQualityProfile.FAST, assess)
    explicit = resolve_advanced(auto.choice, assess, device_policy=SfmDevicePolicy.GPU)
    def key(r):
        return matching_recipe_key("a" * 64, "b" * 64, r.choice.matcher, "c" * 64, ())
    assert auto.requested_device_policy != explicit.requested_device_policy
    assert key(auto) == key(explicit)
    cpu = resolve_advanced(auto.choice, assess, device_policy=SfmDevicePolicy.CPU)
    assert key(cpu) != key(auto)


def test_capability_callback_cannot_substitute_device():
    with pytest.raises(ValueError, match="changed"):
        resolve_profile(SfmQualityProfile.HIGH,
                        lambda c: assess(on_device(c, "cpu")))


def test_legacy_explicit_profile_device_and_conflicting_policy():
    assert resolve_profile(SfmQualityProfile.FAST, assess, use_gpu=False).resolved_device == "cpu"
    with pytest.raises(ValueError, match="legacy"):
        resolve_profile(SfmQualityProfile.FAST, assess, use_gpu=False,
                        device_policy=SfmDevicePolicy.AUTO)


@pytest.mark.parametrize("device", ["auto", "cpu", "gpu", "gpu:0", "gpu:1"])
def test_cli_device_policy_is_typed_and_simple_default_is_auto(monkeypatch, device):
    from typer.testing import CliRunner

    import splatforge.cli.app as cli

    calls = []

    class Service:
        def resolve(self, **kwargs):
            calls.append(kwargs)
            return resolve_profile(kwargs["profile"], assess,
                                   use_gpu=kwargs["use_gpu"],
                                   device_policy=kwargs["device_policy"])

    monkeypatch.setattr(cli, "build_sfm_profile_service", lambda: Service())
    runner = CliRunner()
    args = ["sfm", "resolve", "--profile", "fast"]
    default = runner.invoke(cli.app, args)
    assert default.exit_code == 0 and '"requested_device_policy": "auto"' in default.output
    result = runner.invoke(cli.app, [*args, "--device", device])
    assert result.exit_code == (1 if device == "gpu:1" else 0)
    if device != "gpu:1":
        assert calls[-1]["device_policy"] == ("gpu:0" if device == "gpu" else device)
    assert runner.invoke(cli.app, [*args, "--device", "auto", "--cpu"]).exit_code == 1


@pytest.mark.parametrize("mode", ["oom", "failed", "cpu_fallback"])
def test_runtime_gpu_failure_never_retries_cpu_or_other_technology(tmp_path, mode):
    from matching_helpers import inputs
    from test_views_execution import query

    from splatforge.application.matching import MatchingService
    from splatforge.core.matching import resolve_matching_settings

    value, fixture, features, pairs = inputs(tmp_path, variant="LOMA_B")
    original = fixture.run

    def run(request, **kwargs):
        numerical = "work" in request.working_directory.parts
        if numerical and request.argv[0] == "matches_importer":
            if mode != "cpu_fallback":
                fixture.match_mode = mode
            result = original(request, **kwargs)
            if mode == "cpu_fallback":
                from test_colmap_capabilities import process_result

                return process_result(request, identity=fixture.identity,
                                      stderr=b"Falling back to CPU")
            return result
        return original(request, **kwargs)

    fixture.run = run
    with pytest.raises(ValueError):
        MatchingService(value.execution, fixture.matching_adapter()).match(
            value.root, features_run_id=features.run_id, pairs_run_id=pairs.run_id,
            settings=resolve_matching_settings("LOMA_R", use_gpu=True),
            colmap=fixture.exe, model_directory=fixture.model_root,
        )
    work = [r for r in fixture.requests if "work" in r.working_directory.parts
            and r.argv[0] == "matches_importer"]
    assert len(work) == 1
    assert work[0].argv[work[0].argv.index("--FeatureMatching.use_gpu") + 1] == "1"
    assert work[0].argv[work[0].argv.index("--FeatureMatching.type") + 1] == "LOMA_R"
    assert query(value.root, "SELECT status FROM runs ORDER BY created_at DESC LIMIT 1") == [
        ("failed",)
    ]
