import json
from pathlib import Path
from uuid import uuid4

from typer.testing import CliRunner

from splatforge.cli.app import app
from splatforge.core.execution import RunStatus, ViewsRunResult

runner = CliRunner()


class RecordingService:
    def __init__(self) -> None:
        self.calls = []

    def prepare(self, path: Path, **kwargs) -> ViewsRunResult:  # type: ignore[no-untyped-def]
        self.calls.append((path, kwargs))
        return ViewsRunResult(
            run_id=uuid4(),
            status=RunStatus.SUCCEEDED,
            candidate_artifact=None,
            selected_artifact=None,
            cache_hits=("candidate_views",),
            candidate_count=7,
            selected_count=4,
        )


def test_views_prepare_cli_parses_exact_settings(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    service = RecordingService()
    monkeypatch.setattr("splatforge.cli.app.build_views_service", lambda ffmpeg_path=None: service)
    source_id = uuid4()

    result = runner.invoke(
        app,
        [
            "views",
            "prepare",
            str(tmp_path),
            "--target-fps",
            "30000/1001",
            "--candidate-fps",
            "60",
            "--source-id",
            str(source_id),
            "--verification",
            "strict",
            "--ffmpeg",
            str(tmp_path / "tools" / "ffmpeg.exe"),
            "--image-format",
            "png",
            "--max-candidates",
            "123",
            "--max-disk-gib",
            "1.5",
            "--process-timeout",
            "45",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["candidate_count"] == 7
    assert payload["selected_count"] == 4
    _, kwargs = service.calls[0]
    assert kwargs["candidate_settings"].candidate_fps.model_dump() == {
        "numerator": 60,
        "denominator": 1,
    }
    assert kwargs["selection_settings"].target_fps.model_dump() == {
        "numerator": 30000,
        "denominator": 1001,
    }
    assert kwargs["resource_limits"].max_candidate_bytes == 3 * 1024**3 // 2
    assert kwargs["source_ids"] == {source_id}
    assert kwargs["verification_policy"] == "strict"


def test_views_prepare_requires_target_fps_and_rejects_undersampling(tmp_path: Path) -> None:
    missing = runner.invoke(app, ["views", "prepare", str(tmp_path)])
    assert missing.exit_code != 0
    assert "target-fps" in missing.output

    invalid = runner.invoke(
        app,
        [
            "views",
            "prepare",
            str(tmp_path),
            "--target-fps",
            "2",
            "--candidate-fps",
            "1",
        ],
    )
    assert invalid.exit_code == 1
    assert "candidate FPS" in invalid.output


def test_views_prepare_cli_parses_sharpest_settings_and_dense_default(
    monkeypatch, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    service = RecordingService()
    monkeypatch.setattr("splatforge.cli.app.build_views_service", lambda ffmpeg_path=None: service)
    result = runner.invoke(
        app,
        [
            "views",
            "prepare",
            str(tmp_path),
            "--target-fps",
            "3/2",
            "--selection",
            "sharpest-interval",
            "--quality-max-side",
            "512",
            "--min-sharpness",
            "7/3",
            "--duplicate-hamming-threshold",
            "6",
            "--duplicate-lookback",
            "5",
            "--allow-duplicates",
        ],
    )
    assert result.exit_code == 0, result.output
    _, kwargs = service.calls[0]
    assert kwargs["candidate_settings"].candidate_fps.model_dump() == {
        "numerator": 3,
        "denominator": 1,
    }
    assert kwargs["quality_settings"].quality_max_side == 512
    settings = kwargs["selection_settings"]
    assert settings.target_fps.model_dump() == {
        "numerator": 3,
        "denominator": 2,
    }
    assert settings.min_sharpness.model_dump() == {
        "numerator": 7,
        "denominator": 3,
    }
    assert settings.reject_duplicates is False
    assert settings.duplicate_hamming_threshold == 6
    assert settings.duplicate_lookback == 5


def test_views_prepare_cli_rejects_unknown_selection(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "views",
            "prepare",
            str(tmp_path),
            "--target-fps",
            "1",
            "--selection",
            "adaptive",
        ],
    )
    assert result.exit_code == 1
    assert "fixed-fps" in result.output
    assert "sharpest-interval" in result.output
