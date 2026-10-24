import subprocess
import sys
from uuid import uuid4

from typer.testing import CliRunner

from splatforge.cli.app import app
from splatforge.core.execution import TrainingRuntime


def test_cli_routes_and_conflicting_strategy(tmp_path):
    runner = CliRunner()
    help_result = runner.invoke(app, ["training", "--help"])
    assert help_result.exit_code == 0
    for command in ("handoff", "capability", "plan", "run", "show", "compare"):
        assert command in help_result.stdout
    settings = tmp_path / "settings.json"
    settings.write_text('{"strategy":{"strategy":"default"}}', encoding="utf8")
    import pytest

    from splatforge.cli.training import load_settings

    with pytest.raises(ValueError, match="conflicts"):
        load_settings(settings, "mcmc")
    with pytest.raises(ValueError, match="unsafe_runtime"):
        TrainingRuntime(python="test.exe", environment={"SECRET": "not allowed"})
    result = runner.invoke(app, ["training", "show", str(tmp_path), str(uuid4())])
    assert result.exit_code == 1


def test_host_imports_do_not_initialize_optional_engines():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import splatforge.cli.app; import splatforge.application.training; "
            "assert not any(n in sys.modules for n in ('torch','gsplat')); print('isolated')",
        ],
        shell=False,
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 0 and b"isolated" in result.stdout
