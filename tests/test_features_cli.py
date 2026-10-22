"""CLI delegates typed M7a settings/results without backend or ETA logic."""

from uuid import uuid4

from typer.testing import CliRunner

import splatforge.cli.app as cli
from splatforge.application.features import FeaturesRunResult


def test_cli_passes_typed_loma_settings_and_returns_json(monkeypatch, tmp_path):
    calls = []
    run_id = uuid4()

    class Service:
        def extract(self, root, **kwargs):
            calls.append((root, kwargs))
            return FeaturesRunResult(
                run_id=run_id,
                status="succeeded",
                method_id=kwargs["settings"].method_id,
                feature_artifact=None,
                selected_view_count=2,
                total_feature_count=10,
                cache_hit=False,
            )

    monkeypatch.setattr(cli, "build_features_service", lambda: Service())
    result = CliRunner().invoke(
        cli.app,
        [
            "features",
            "extract",
            str(tmp_path),
            "--views-run",
            str(uuid4()),
            "--method",
            "LOMA_B128",
            "--max-features",
            "1024",
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    assert '"method_id": "feature_extraction.loma_b128"' in result.output
    assert calls[0][1]["settings"].max_features == 1024
    assert calls[0][1]["settings"].variant == "LOMA_B128"


def test_cli_rejects_matchers_and_invalid_extractor_slots(tmp_path):
    result = CliRunner().invoke(
        cli.app,
        ["features", "extract", str(tmp_path), "--views-run", str(uuid4()), "--method", "LOMA_R"],
    )
    assert result.exit_code == 1 and "Unknown extractor" in result.output
