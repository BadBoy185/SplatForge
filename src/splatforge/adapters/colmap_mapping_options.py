"""Intentional typed subset of positively observed COLMAP 4.2.1 mapping options."""

from pathlib import Path

from splatforge.core.reconstruction import GlobalMapperSettings, ViewGraphCalibrationSettings


def mapping_arguments(
    settings: GlobalMapperSettings,
    options: tuple[str, ...],
    *,
    database: Path,
    images: Path | None,
    output: Path,
) -> tuple[str, ...]:
    values = {
        "database_path": str(database),
        "image_path": str(images) if images is not None else "",
        "output_path": str(output),
        "default_random_seed": settings.random_seed,
        "log_target": "stderr",
    }
    values.update(
        {
            "GlobalMapper." + key: value
            for key, value in settings.model_dump().items()
            if key not in {"settings_version", "method_id"}
        }
    )
    return _arguments("global_mapper", values, options)


def calibration_arguments(
    settings: ViewGraphCalibrationSettings, options: tuple[str, ...], *, database: Path
) -> tuple[str, ...]:
    values = {"database_path": str(database), "log_target": "stderr"}
    values.update(
        {
            ("default_random_seed" if key == "random_seed" else key): value
            for key, value in settings.model_dump().items()
            if key != "settings_version"
        }
    )
    return _arguments("view_graph_calibrator", values, options)


def _arguments(command, values, options):
    missing = set(values) - set(options)
    if missing:
        raise ValueError("mapping.missing_options: " + ", ".join(sorted(missing)))
    return (
        command,
        *(
            arg
            for key, value in values.items()
            for arg in ("--" + key, str(int(value)) if isinstance(value, bool) else str(value))
        ),
    )
