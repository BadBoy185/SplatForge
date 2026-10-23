"""Intentional typed subset of positively observed COLMAP 4.2.1 mapping options."""

from pathlib import Path

from splatforge.core.reconstruction import (
    GlobalAcceleratedSettings,
    GlobalMapperSettings,
    HierarchicalMapperSettings,
    IncrementalMapperSettings,
    ViewGraphCalibrationSettings,
)


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
            if key not in {"settings_version", "method_id", "acceleration"}
        }
    )
    if isinstance(settings, GlobalAcceleratedSettings):
        acceleration = settings.acceleration
        if acceleration.uses_gpu and "log_path" not in options:
            raise ValueError("mapping.missing_options: log_path")
        values.update({
            "GlobalMapper.gp_use_gpu": acceleration.positioning_device != "cpu",
            "GlobalMapper.gp_gpu_index": acceleration.positioning_device
            if acceleration.positioning_device != "cpu" else -1,
            "GlobalMapper.ba_ceres_use_gpu": acceleration.ba_device != "cpu",
            "GlobalMapper.ba_gpu_index": acceleration.ba_device
            if acceleration.ba_device != "cpu" else -1,
            "log_level": 3,
        })
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


def incremental_arguments(
    settings: IncrementalMapperSettings,
    options: tuple[str, ...],
    *,
    database: Path,
    images: Path,
    output: Path,
) -> tuple[str, ...]:
    values = {
        "database_path": str(database), "image_path": str(images), "output_path": str(output),
        "default_random_seed": settings.random_seed, "log_target": "stderr",
    }
    if settings.uses_caspar:
        # Positive numerical solver evidence is required, not just option acceptance.
        values["log_level"] = 2
    values.update({
        "Mapper." + key: value for key, value in settings.model_dump().items()
        if key not in {"settings_version", "method_id"}
    })
    return _arguments("mapper", values, options)


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


def hierarchical_arguments(
    settings: HierarchicalMapperSettings,
    options: tuple[str, ...],
    *, database: Path, images: Path, output: Path,
) -> tuple[str, ...]:
    if "log_path" not in options:
        raise ValueError("mapping.missing_options: log_path")
    values = {
        "database_path": str(database), "image_path": str(images), "output_path": str(output),
        "default_random_seed": settings.cluster.random_seed, "log_target": "stderr",
    }
    values.update({"HierarchicalMapper." + key: value
                   for key, value in settings.model_dump().items()
                   if key not in {"method_id", "settings_version", "cluster"}})
    # Native hierarchy overrides these from its total budget and init trial count.
    # Never multiply workers by an independently configured Mapper thread budget.
    values.update({"Mapper." + key: value
                   for key, value in settings.cluster.model_dump().items()
                   if key not in {"method_id", "settings_version", "num_threads", "init_num_trials"}
    })
    return _arguments("hierarchical_mapper", values, options)
