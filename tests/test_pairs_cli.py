"""CLI metadata-only route parsing and concise structured results."""

from uuid import UUID

import pytest
from typer.testing import CliRunner

from splatforge.application.pairs import PairsRunResult
from splatforge.cli.app import app
from splatforge.core.pairs import ExhaustiveSettings, SequentialSettings


@pytest.fixture
def capture(monkeypatch):
    import importlib

    cli = importlib.import_module("splatforge.cli.app")
    calls = []

    class Service:
        def build(self, path, **kwargs):
            calls.append((path, kwargs))
            return PairsRunResult(
                run_id=UUID(int=10),
                status="succeeded",
                method=kwargs["settings"].method_id,
                pair_set_artifact=None,
                cache_hit=False,
                selected_view_count=3,
                pair_count=2,
                isolated_view_count=0,
                component_count=1,
            )

    monkeypatch.setattr(cli, "build_pairs_service", lambda: Service())
    return calls


def test_cli_sequential_exact_settings_repeatable_pairs_and_json(capture) -> None:
    a, b = UUID(int=1), UUID(int=2)
    result = CliRunner().invoke(
        app,
        [
            "pairs",
            "build",
            "C:/project space Unicode тест",
            "--views-run",
            str(UUID(int=3)),
            "--forward-neighbors",
            "2",
            "--max-time-gap",
            "0.5",
            "--max-pairs",
            "15",
            "--pair",
            f"{b}:{a}",
            "--pair",
            f"{a}:{b}",
        ],
    )
    assert result.exit_code == 0, result.output
    assert '"pair_count": 2' in result.output
    kwargs = capture[0][1]
    assert isinstance(kwargs["settings"], SequentialSettings)
    assert kwargs["settings"].max_time_gap.as_fraction().numerator == 1
    assert kwargs["settings"].max_time_gap.as_fraction().denominator == 2
    assert kwargs["explicit_pairs"][0] == kwargs["explicit_pairs"][1]
    assert kwargs["resource_limits"].max_pairs == 15


def test_cli_exhaustive(capture) -> None:
    result = CliRunner().invoke(
        app,
        ["pairs", "build", "project", "--views-run", str(UUID(int=3)), "--method", "exhaustive"],
    )
    assert result.exit_code == 0, result.output
    assert isinstance(capture[0][1]["settings"], ExhaustiveSettings)


@pytest.mark.parametrize(
    "options",
    [
        [],
        ["--views-run", "bad"],
        ["--views-run", str(UUID(int=3)), "--method", "retrieval"],
        ["--views-run", str(UUID(int=3)), "--method", "exhaustive", "--forward-neighbors", "5"],
        ["--views-run", str(UUID(int=3)), "--method", "exhaustive", "--max-time-gap", "1"],
        ["--views-run", str(UUID(int=3)), "--pair", "bad"],
        ["--views-run", str(UUID(int=3)), "--max-pairs", "0"],
        ["--views-run", str(UUID(int=3)), "--forward-neighbors", "0"],
        ["--views-run", str(UUID(int=3)), "--max-time-gap", "NaN"],
    ],
)
def test_cli_invalid_inputs_refused_before_application(capture, options) -> None:
    result = CliRunner().invoke(app, ["pairs", "build", "project", *options])
    assert result.exit_code != 0 and capture == []


def test_catalog_reports_implemented_and_deferred_pair_methods() -> None:
    result = CliRunner().invoke(app, ["methods"])
    assert result.exit_code == 0
    lines = {line.split()[1]: line for line in result.output.splitlines()}
    assert "Implemented v1" in lines["pair_selection.sequential"]
    assert "Implemented v1" in lines["pair_selection.exhaustive"]
    assert "not implemented or runnable" in lines["pair_selection.vocab_tree"]
    assert "not implemented or runnable" in lines["pair_selection.spatial"]
