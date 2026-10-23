"""M9a CLI delegates settings and renders availability plus source imbalance."""

from uuid import UUID

from typer.testing import CliRunner
from validation_helpers import measured

import splatforge.cli.reconstruction as cli
from splatforge.application.reconstruction_validation import (
    EvidenceRunResult,
    ReconstructionValidationResult,
)
from splatforge.cli.app import app
from splatforge.core.validation_policy import ReconstructionValidationPolicy, evaluate_policy


def test_validate_cli_uses_exact_mapping_run_and_bounded_settings(tmp_path, monkeypatch):
    calls = []

    class Service:
        def validate(self, root, **kwargs):
            calls.append((root, kwargs))
            run = EvidenceRunResult(
                run_id=UUID(int=99), status="cancelled", artifact=None, cache_hit=False
            )
            return ReconstructionValidationResult(
                run_id=run.run_id,
                status=run.status,
                geometry_run=run,
                metrics_run=None,
                report_run=None,
                report=None,
            )

    monkeypatch.setattr(cli, "build_reconstruction_validation_service", lambda: Service())
    result = CliRunner().invoke(
        app,
        [
            "reconstruction",
            "validate",
            str(tmp_path),
            "--mapping-run",
            str(UUID(int=9)),
            "--timeout",
            "100",
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    assert calls[0][1]["mapping_run_id"] == UUID(int=9)
    assert calls[0][1]["resource_limits"].timeout_seconds == 100
    assert '"report": null' in result.output
    custom = tmp_path / "policy.json"
    custom.write_text('{"policy_id":"custom_v1","fail_registration_below":0.8}')
    result = CliRunner().invoke(
        app,
        [
            "reconstruction",
            "validate",
            str(tmp_path),
            "--mapping-run",
            str(UUID(int=9)),
            "--policy",
            str(custom),
        ],
    )
    assert result.exit_code == 0, result.output
    assert calls[-1][1]["policy"].fail_registration_below == 0.8


def test_inspection_renders_group_counts_unknown_and_json(tmp_path, monkeypatch):
    metrics = measured(
        [(1, 10)] * 3 + [(2, 20)] * 4, [[0, 1, 2]], points_available=False, tracks_available=False
    )[3]
    report = evaluate_policy(metrics, ReconstructionValidationPolicy())

    class Service:
        def inspect_details(self, root, run_id):
            assert run_id == UUID(int=9)
            return report, metrics

    monkeypatch.setattr(cli, "build_reconstruction_validation_service", lambda: Service())
    args = ["reconstruction", "validation-show", str(tmp_path), str(UUID(int=9))]
    result = CliRunner().invoke(app, args)
    assert result.exit_code == 0, result.output
    assert "3 / 7" in result.output and "0 / 4" in result.output
    assert "unavailable" in result.output and "WARNING" in result.output
    result = CliRunner().invoke(app, [*args, "--json"])
    assert result.exit_code == 0 and '"source_groups"' in result.output
    assert '"value": null' in result.output


def test_validation_cli_rejects_unknown_profile_and_settings(tmp_path):
    args = ["reconstruction", "validate", str(tmp_path), "--mapping-run", str(UUID(int=9))]
    result = CliRunner().invoke(app, [*args, "--profile", "guess"])
    assert result.exit_code == 1 and "baseline_v1" in result.output
    path = tmp_path / "settings.json"
    path.write_text('{"unknown":true}')
    assert CliRunner().invoke(app, [*args, "--measurement-settings", str(path)]).exit_code == 1
