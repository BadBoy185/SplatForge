import json
from pathlib import Path

from typer.testing import CliRunner

from splatforge.cli.app import app

runner = CliRunner()


def test_fake_run_and_show_cli(tmp_path: Path) -> None:
    root = tmp_path / "CLI execution project"
    created = runner.invoke(app, ["project", "create", str(root), "--label", "CLI"])
    assert created.exit_code == 0, created.output

    executed = runner.invoke(
        app,
        [
            "run",
            "fake",
            str(root),
            "--start",
            "3",
            "--count",
            "2",
            "--factor",
            "5",
        ],
    )
    assert executed.exit_code == 0, executed.output
    result = json.loads(executed.output)
    assert result["status"] == "succeeded"
    assert result["cache_hits"] == []

    shown = runner.invoke(app, ["run", "show", str(root), result["run_id"]])
    assert shown.exit_code == 0, shown.output
    run = json.loads(shown.output)
    assert run["snapshot"]["route"]["sequence"]["start"] == 3

    cancelled = runner.invoke(app, ["run", "cancel", str(root), result["run_id"]])
    assert cancelled.exit_code == 0, cancelled.output
    assert json.loads(cancelled.output)["too_late"] is True

    recovered = runner.invoke(app, ["run", "recover", str(root), result["run_id"]])
    assert recovered.exit_code == 0, recovered.output
    assert json.loads(recovered.output)["status"] == "succeeded"

    retried = runner.invoke(app, ["run", "retry", str(root), result["run_id"]])
    assert retried.exit_code == 1
    assert "terminal: succeeded" in retried.output
    assert run["state"]["status"] == "succeeded"
    assert len(run["attempts"]) == 2


def test_upgrade_current_state_cli_is_safe_no_op(tmp_path: Path) -> None:
    root = tmp_path / "Current schema"
    created = runner.invoke(app, ["project", "create", str(root), "--label", "Current"])
    assert created.exit_code == 0, created.output

    result = runner.invoke(app, ["project", "upgrade-state", str(root)])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload == {
        "previous_version": 4,
        "current_version": 4,
        "upgraded": False,
        "backup_path": None,
    }
