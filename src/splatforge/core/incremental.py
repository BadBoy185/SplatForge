"""Redundant preflight interpretation; never an additional MappingInput identity."""

from collections.abc import Iterable

CASPAR_CAMERA_MODELS = frozenset({"SIMPLE_RADIAL", "PINHOLE"})


def require_caspar_compatibility(
    camera_models: Iterable[str],
    *,
    pose_priors: bool = False,
    non_reference_sensor_refinement: bool = False,
) -> None:
    unsupported = set(camera_models) - CASPAR_CAMERA_MODELS
    if unsupported:
        raise ValueError(
            "mapping.caspar_camera_model: unsupported "
            + ", ".join(sorted(unsupported))
            + "; Caspar 4.2.1 requires PINHOLE or SIMPLE_RADIAL. Choose explicit Ceres "
            "or prepare and verify compatible cameras in a new M7 run"
        )
    if pose_priors:
        raise ValueError("mapping.caspar_pose_priors: pose priors are unsupported")
    if non_reference_sensor_refinement:
        raise ValueError(
            "mapping.caspar_rig_refinement: non-reference sensor refinement unsupported"
        )
