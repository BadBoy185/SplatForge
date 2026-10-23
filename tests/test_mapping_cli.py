"""Thin CLI delegates exact UUID/settings/policy without exposing native flags."""

from uuid import UUID

import pytest
from typer.testing import CliRunner

import splatforge.cli.app as cli
from splatforge.application.mapping import MappingRunResult
from splatforge.core.reconstruction import IncrementalMapperSettings, MappingCalibrationPolicy


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
    result = runner.invoke(cli.app, [*base, "--method", "unknown"])
    assert result.exit_code == 1 and "Choose explicit" in result.output
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


@pytest.mark.parametrize("backend,index", [("ceres", None), ("caspar", 0), ("caspar", 2)])
def test_incremental_cli_freezes_distinct_local_global_backend(
    tmp_path, monkeypatch, backend, index
):
    calls = []

    class Service:
        def run(self, root, **kwargs):
            calls.append(kwargs)
            return MappingRunResult(
                run_id=UUID(int=2),
                status="cancelled",
                artifact=None,
                reconstruction=None,
                cache_hit=False,
            )

    monkeypatch.setattr(cli, "build_mapping_service", lambda: Service())
    argv = [
        "mapping",
        "run",
        str(tmp_path),
        "--verification-run",
        str(UUID(int=1)),
        "--method",
        "incremental",
        "--ba-backend",
        backend,
        "--json",
    ]
    if index is not None:
        argv += ["--gpu-index", str(index)]
    result = CliRunner().invoke(cli.app, argv)
    assert result.exit_code == 0, result.output
    settings = calls[0]["settings"]
    assert type(settings) is IncrementalMapperSettings
    assert settings.ba_local_backend == settings.ba_global_backend == backend.upper()
    assert settings.ba_gpu_index == (-1 if index is None else index)
    assert not settings.multiple_models and not settings.extract_colors


@pytest.mark.parametrize(
    "flags",
    [
        ["--method", "global", "--ba-backend", "caspar"],
        ["--method", "incremental", "--ba-backend", "ceres", "--gpu-index", "0"],
        ["--method", "incremental", "--ba-backend", "caspar", "--gpu-index", "-1"],
        ["--method", "incremental", "--ba-backend", "unknown"],
        ["--method", "incremental", "--Mapper.multiple_models", "1"],
    ],
)
def test_cli_refuses_unsupported_ba_flags_without_substitution(tmp_path, flags):
    result = CliRunner().invoke(
        cli.app, ["mapping", "run", str(tmp_path), "--verification-run", str(UUID(int=1)), *flags]
    )
    assert result.exit_code in {1, 2}


@pytest.mark.parametrize("method,flags", [
    ("hierarchical", ["--num-threads", "4", "--num-workers", "2", "--image-overlap", "4",
                      "--leaf-max-num-images", "6"]),
    ("global", ["--global-positioning-device", "gpu:0", "--global-ba-device", "cpu"]),
    ("global", ["--global-positioning-device", "cpu", "--global-ba-device", "gpu:1"]),
])
def test_m8b2_cli_typed_routes(tmp_path, monkeypatch, method, flags):
    calls = []
    class Service:
        def run(self, root, **kwargs):
            calls.append(kwargs)
            return MappingRunResult(run_id=UUID(int=9), status="cancelled", artifact=None,
                                     reconstruction=None, cache_hit=False)
    monkeypatch.setattr(cli, "build_mapping_service", lambda: Service())
    result = CliRunner().invoke(cli.app, ["mapping", "run", str(tmp_path),
        "--verification-run", str(UUID(int=1)), "--method", method, *flags, "--json"])
    assert result.exit_code == 0, result.output
    numerical = calls[0]["settings"]
    if method == "hierarchical":
        assert numerical.num_threads == 4 and numerical.num_workers == 2
        assert numerical.leaf_max_num_images == 6 and numerical.image_overlap == 4
    else:
        assert numerical.method_id == "mapping.colmap_global" and numerical.settings_version == 2
        assert (numerical.acceleration.positioning_device == 0
                or numerical.acceleration.ba_device == 1)


@pytest.mark.parametrize("flags", [
    ["--method", "incremental", "--global-ba-device", "gpu:0"],
    ["--method", "global", "--num-workers", "2"],
    ["--method", "global", "--global-ba-device", "auto"],
    ["--method", "hierarchical", "--num-workers", "4", "--num-threads", "2"],
])
def test_m8b2_cli_refuses_incompatible_flags(tmp_path, flags):
    result = CliRunner().invoke(cli.app, ["mapping", "run", str(tmp_path),
        "--verification-run", str(UUID(int=1)), *flags])
    assert result.exit_code == 1


def test_old_minimal_global_settings_file_remains_accepted(tmp_path, monkeypatch):
    calls = []
    class Service:
        def run(self, root, **kwargs):
            calls.append(kwargs)
            return MappingRunResult(run_id=UUID(int=9), status="cancelled", artifact=None,
                                     reconstruction=None, cache_hit=False)
    monkeypatch.setattr(cli, "build_mapping_service", lambda: Service())
    path = tmp_path / "old-settings.json"
    path.write_text('{"min_model_size":4}', encoding="utf8")
    result = CliRunner().invoke(cli.app, ["mapping", "run", str(tmp_path),
        "--verification-run", str(UUID(int=1)), "--settings", str(path), "--json"])
    assert result.exit_code == 0, result.output
    assert calls[0]["settings"].settings_version == 1
    assert calls[0]["settings"].min_model_size == 4
