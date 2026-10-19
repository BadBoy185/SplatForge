import json
from pathlib import Path

from typer.testing import CliRunner

from splatforge.cli.app import app

runner = CliRunner()


def test_project_cli_create_show(tmp_path: Path) -> None:
    path = tmp_path / "\u017dlu\u0165ou\u010dk\u00fd project"
    result = runner.invoke(app, ["project", "create", str(path), "--label", "\u017d test"])
    assert result.exit_code == 0, result.output
    created = json.loads(result.output)
    result = runner.invoke(app, ["project", "show", str(path)])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == created
    assert created["label"] == "\u017d test"
    assert created["revision"] == 0


def test_project_cli_errors(tmp_path: Path) -> None:
    missing = runner.invoke(app, ["project", "show", str(tmp_path / "missing")])
    assert missing.exit_code == 1
    assert "Project storage error" in missing.output
    (tmp_path / "original").write_bytes(b"keep")
    refused = runner.invoke(app, ["project", "create", str(tmp_path), "--label", "No"])
    assert refused.exit_code == 1
    assert "missing or empty" in refused.output
    assert (tmp_path / "original").read_bytes() == b"keep"


def test_existing_cli_commands_preserved() -> None:
    for command in ("version", "methods", "show-default-config"):
        result = runner.invoke(app, [command])
        assert result.exit_code == 0, result.output
    config = json.loads(runner.invoke(app, ["show-default-config"]).output)
    assert config["schema_version"] == 1
    assert config["sfm"]["mapper_id"] == "mapping.colmap_global"
