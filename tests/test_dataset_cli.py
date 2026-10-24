"""CLI delegates planning/preparation and reuses generic lifecycle inspection."""

import json

from dataset_helpers import dataset_service, dataset_setup
from typer.testing import CliRunner

from splatforge.cli.app import app


def test_dataset_plan_prepare_show_progress_and_cleanup_cli(tmp_path, monkeypatch):
    value, fixture, _m, _v, selection = dataset_setup(tmp_path)
    service = dataset_service(value, fixture)
    monkeypatch.setattr("splatforge.cli.dataset.build_dataset_service", lambda: service)
    runner = CliRunner()
    args = [str(value.root), "--selection-run", str(selection.run.run_id), "--json"]
    plan = runner.invoke(app, ["dataset", "plan", *args])
    assert plan.exit_code == 0, plan.output
    data = json.loads(plan.output)
    assert data["runnable"] and data["components"][0]["registered_views"] == 3
    assert data["provenance"]["production_multi_video_gate"] == "pending_m7c_production_vpr"
    prepared = runner.invoke(app, ["dataset", "prepare", *args])
    assert prepared.exit_code == 0, prepared.output
    result = json.loads(prepared.output)
    shown = runner.invoke(app, ["dataset", "show", str(value.root), result["run_id"], "--json"])
    assert shown.exit_code == 0 and json.loads(shown.output) == result["dataset"]
    for name in ("show", "progress"):
        inspected = runner.invoke(
            app,
            [
                "run",
                name,
                str(value.root),
                result["run_id"],
                *(["--json"] if name == "progress" else []),
            ],
        )
        assert inspected.exit_code == 0, inspected.output
    preview = runner.invoke(app, ["project", "cleanup", str(value.root), "--dry-run", "--json"])
    assert preview.exit_code == 0 and not json.loads(preview.output)["applied"]
    refused = runner.invoke(app, ["project", "cleanup", str(value.root), "--apply"])
    assert refused.exit_code == 1 and "preview_required" in refused.output
    missing = runner.invoke(app, ["dataset", "prepare", str(value.root)])
    assert missing.exit_code != 0 and "selection-run" in missing.output
    assert json.loads(runner.invoke(app, ["run", "active", str(value.root), "--json"]).output) == []

    def cancel_visible_run(owner):
        active = runner.invoke(app, ["run", "active", str(value.root), "--json"])
        assert active.exit_code == 0, active.output
        snapshots = json.loads(active.output)
        assert [s["run_id"] for s in snapshots] == [str(owner.run)]
        cancelled = runner.invoke(app, ["run", "cancel", str(value.root), str(owner.run)])
        assert cancelled.exit_code == 0, cancelled.output

    fixture.on_undistort = cancel_visible_run
    cancelled = runner.invoke(app, ["dataset", "prepare", *args, "--max-image-size", "15"])
    assert cancelled.exit_code == 2 and json.loads(cancelled.output)["status"] == "cancelled"
