"""Thin CLI delegates exact UUID/settings/policy without exposing native flags."""

from uuid import UUID

from typer.testing import CliRunner

import splatforge.cli.app as cli
from splatforge.application.mapping import MappingRunResult
from splatforge.core.reconstruction import MappingCalibrationPolicy


def test_mapping_cli_delegates_global_and_explicit_calibration(tmp_path, monkeypatch):
    calls = []

    class Service:
        def run(self, root, **kwargs):
            calls.append((root, kwargs))
            return MappingRunResult(
                run_id=UUID(int=9),
                status="cancelled",
                artifact=None,
                reconstruction=None,
                cache_hit=False,
            )

    monkeypatch.setattr(cli, "build_mapping_service", lambda: Service())
    result = CliRunner().invoke(
        cli.app,
        [
            "mapping",
            "run",
            str(tmp_path),
            "--verification-run",
            str(UUID(int=1)),
            "--calibration",
            "view-graph",
            "--min-model-size",
            "4",
            "--num-threads",
            "2",
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    assert calls[0][1]["verification_run_id"] == UUID(int=1)
    assert calls[0][1]["calibration_policy"] == MappingCalibrationPolicy.VIEW_GRAPH
    assert calls[0][1]["settings"].min_model_size == 4
    assert calls[0][1]["settings"].multiple_models is True
    assert '"reconstruction": null' in result.output


def test_unsupported_mapper_raw_flags_and_settings_refused(tmp_path):
    base = ["mapping", "run", str(tmp_path), "--verification-run", str(UUID(int=1))]
    runner = CliRunner()
    result = runner.invoke(cli.app, [*base, "--method", "incremental"])
    assert result.exit_code == 1 and "only explicit Global" in result.output
    assert runner.invoke(cli.app, [*base, "--GlobalMapper.multiple_models", "0"]).exit_code == 2
    settings = tmp_path / "unknown.json"
    settings.write_text('{"unknown_backend_flag":1}', encoding="utf-8")
    assert runner.invoke(cli.app, [*base, "--settings", str(settings)]).exit_code == 1


def test_programmatic_bypass_cannot_disable_multiple_models(tmp_path):
    import pytest

    from splatforge.application.mapping import MappingService
    from splatforge.core.reconstruction import GlobalMapperSettings

    invalid = GlobalMapperSettings().model_copy(update={"multiple_models": False})
    with pytest.raises(ValueError):
        MappingService(None, None).run(tmp_path, verification_run_id=UUID(int=1), settings=invalid)
