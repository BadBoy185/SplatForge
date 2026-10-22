"""CLI stays a typed client of shared M7b services."""

import json
from uuid import uuid4

from typer.testing import CliRunner

import splatforge.cli.app as cli
from splatforge.application.matching import MatchingRunResult


def test_stage_commands_delegate_explicit_inputs_and_numerical_settings(tmp_path, monkeypatch):
    calls = []

    class Service:
        def match(self, root, **kwargs):
            calls.append(kwargs)
            return MatchingRunResult(
                run_id=uuid4(),
                status="succeeded",
                method_id=kwargs["settings"].method_id,
                artifact=None,
                pair_count=3,
                raw_matches=24,
                cache_hit=False,
            )

        def verify(self, root, **kwargs):
            calls.append(kwargs)
            return MatchingRunResult(
                run_id=uuid4(),
                status="succeeded",
                method_id=kwargs["settings"].method_id,
                artifact=None,
                pair_count=3,
                raw_matches=24,
                accepted_pairs=1,
                verified_inliers=24,
                cache_hit=False,
            )

    monkeypatch.setattr(cli, "build_matching_service", lambda: Service())
    feature_run, pair_run = uuid4(), uuid4()
    runner = CliRunner()
    raw = runner.invoke(
        cli.app,
        [
            "matches",
            "run",
            str(tmp_path),
            "--features-run",
            str(feature_run),
            "--pairs-run",
            str(pair_run),
            "--matcher",
            "LOMA_R",
            "--max-matches",
            "1024",
            "--json",
        ],
    )
    assert raw.exit_code == 0, raw.output
    assert calls[0]["features_run_id"] == feature_run and calls[0]["pairs_run_id"] == pair_run
    assert calls[0]["settings"].variant == "LOMA_R" and calls[0]["settings"].max_num_matches == 1024
    checked = runner.invoke(
        cli.app,
        [
            "verification",
            "run",
            str(tmp_path),
            "--matches-run",
            str(uuid4()),
            "--min-inliers",
            "20",
            "--max-error",
            "2",
            "--json",
        ],
    )
    assert checked.exit_code == 0, checked.output
    assert calls[1]["settings"].min_num_inliers == 20 and calls[1]["settings"].max_error == 2
    assert json.loads(checked.output)["verified_inliers"] == 24


def test_settings_files_reject_unknown_flags(tmp_path):
    config = tmp_path / "bad.json"
    config.write_text(
        json.dumps({"method_id": "feature_matching.loma_b", "arbitrary_flags": "--foo"})
    )
    result = CliRunner().invoke(
        cli.app,
        [
            "matches",
            "run",
            str(tmp_path),
            "--features-run",
            str(uuid4()),
            "--pairs-run",
            str(uuid4()),
            "--settings",
            str(config),
        ],
    )
    assert result.exit_code == 1 and "Extra inputs are not permitted" in result.output


def test_simple_profile_is_planning_only_and_advanced_combination_is_explicit(monkeypatch):
    calls = []

    class Service:
        def resolve(self, **kwargs):
            calls.append(kwargs)

            class Result:
                def model_dump_json(self, **_kwargs):
                    return '{"resolved":true}'

            return Result()

    monkeypatch.setattr(cli, "build_sfm_profile_service", lambda: Service())
    runner = CliRunner()
    result = runner.invoke(cli.app, ["sfm", "resolve", "--profile", "max-high"])
    assert result.exit_code == 0, result.output
    assert calls[-1]["profile"] == "max_high" and calls[-1]["choice"] is None
    result = runner.invoke(
        cli.app, ["sfm", "resolve", "--extractor", "LOMA_B", "--matcher", "LOMA_R"]
    )
    assert result.exit_code == 0, result.output
    assert calls[-1]["profile"] is None and calls[-1]["choice"].matcher.variant == "LOMA_R"
    assert (
        runner.invoke(
            cli.app, ["sfm", "resolve", "--profile", "fast", "--matcher", "LOMA_B"]
        ).exit_code
        == 1
    )
