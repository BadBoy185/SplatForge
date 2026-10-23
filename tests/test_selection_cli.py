"""Thin selection CLI preserves explicit manual choices and targeted overrides."""

from uuid import UUID

from typer.testing import CliRunner
from validation_helpers import measured

import splatforge.cli.reconstruction as cli
from splatforge.application.reconstruction_selection import ReconstructionSelectionResult
from splatforge.cli.app import app
from splatforge.core.reconstruction_selection import DominanceSelectionPolicy, recommend_components
from splatforge.core.validation_policy import ReconstructionValidationPolicy, evaluate_policy


def test_manual_repeatable_components_and_exact_override_arguments(tmp_path, monkeypatch):
    calls = []

    class Service:
        def select(self, root, **kwargs):
            calls.append(kwargs)
            return ReconstructionSelectionResult(
                status="cancelled", run=None, decision=None, selection=None
            )

    monkeypatch.setattr(cli, "build_reconstruction_selection_service", lambda: Service())
    result = CliRunner().invoke(
        app,
        [
            "reconstruction",
            "select",
            str(tmp_path),
            "--validation-run",
            str(UUID(int=9)),
            "--component",
            str(UUID(int=2)),
            "--component",
            str(UUID(int=1)),
            "--override-issue",
            "a" * 64,
            "--override-reason",
            "Reviewed exact failures.",
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    assert calls[0]["component_ids"] == (UUID(int=2), UUID(int=1))
    assert calls[0]["override_issue_ids"] == ("a" * 64,)
    assert calls[0]["override_reason"] == "Reviewed exact failures."
    assert calls[0]["validation_run_id"] == UUID(int=9)


def test_ambiguous_cli_prints_candidates_and_requires_manual_without_fake_artifact(
    tmp_path, monkeypatch
):
    _r, _u, _s, metrics = measured(
        [(i * 2 + 1, 10) for i in range(6)],
        [[0, 1, 2], [3, 4, 5]],
        points_available=False,
        tracks_available=False,
    )
    report = evaluate_policy(metrics, ReconstructionValidationPolicy())
    decision = recommend_components(metrics, report, DominanceSelectionPolicy())

    class Service:
        def select(self, root, **kwargs):
            return ReconstructionSelectionResult(
                status="ambiguous", run=None, decision=decision, selection=None
            )

    monkeypatch.setattr(cli, "build_reconstruction_selection_service", lambda: Service())
    args = [
        "reconstruction",
        "select",
        str(tmp_path),
        "--validation-run",
        str(UUID(int=9)),
        "--mode",
        "recommended",
    ]
    result = CliRunner().invoke(app, args)
    assert result.exit_code == 2 and "Manual selection required." in result.output
    assert "Candidate" in result.output and "Source group" in result.output
    result = CliRunner().invoke(app, [*args, "--json"])
    assert result.exit_code == 2 and '"selection": null' in result.output


def test_blanket_ignore_flag_does_not_exist(tmp_path):
    result = CliRunner().invoke(
        app,
        [
            "reconstruction",
            "select",
            str(tmp_path),
            "--validation-run",
            str(UUID(int=9)),
            "--ignore-validation",
        ],
    )
    assert result.exit_code == 2 and "No such option" in result.output


def test_selection_inspection_exposes_exact_references_and_numerical_digest(tmp_path, monkeypatch):
    import json

    from splatforge.core.reconstruction_selection import (
        ReconstructionSelectionArtifact,
        make_selection,
    )

    reconstruction, _u, _s, metrics = measured()
    report = evaluate_policy(metrics, ReconstructionValidationPolicy())
    selection = make_selection(
        UUID(int=7),
        reconstruction,
        metrics,
        report,
        metrics.geometry,
        (reconstruction.components[0].component_id,),
    )
    artifact = ReconstructionSelectionArtifact(
        reconstruction_artifact_id=UUID(int=7),
        report_artifact_id=UUID(int=8),
        metrics_artifact_id=UUID(int=9),
        geometry_artifact_id=UUID(int=10),
        selection=selection,
    )

    class Service:
        def inspect(self, root, run_id):
            return artifact

        def inspect_details(self, root, run_id):
            return selection, report, metrics

    monkeypatch.setattr(cli, "build_reconstruction_selection_service", lambda: Service())
    args = ["reconstruction", "selection-show", str(tmp_path), str(UUID(int=99))]
    result = CliRunner().invoke(app, [*args, "--json"])
    assert result.exit_code == 0, result.output
    value = json.loads(result.output)
    assert value["reconstruction_artifact_id"] == str(UUID(int=7))
    assert value["report_artifact_id"] == str(UUID(int=8))
    assert value["semantic_digest"] == selection.semantic_digest
    assert value["recipe_key"] == selection.recipe_key
    human = CliRunner().invoke(app, args)
    assert human.exit_code == 0 and "Selected" in human.output and "manual" in human.output
