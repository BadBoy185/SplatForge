"""Bounded native Caspar BA and exact CUDA device evidence, with no provisioning."""

from __future__ import annotations

import os
import struct
import sys
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID

from splatforge.adapters.colmap_features import native_transport_path
from splatforge.adapters.colmap_reconstruction import read_component
from splatforge.adapters.colmap_runtime import scoped_runtime_environment
from splatforge.adapters.feature_database import FeatureImageMapping, NativeFeaturePayload
from splatforge.adapters.process_runner import ProcessCleanupError
from splatforge.application.doctor_contracts import DoctorTeardownError
from splatforge.application.features_contracts import FeatureCapabilityError
from splatforge.core.capabilities import ExecutableSelection
from splatforge.core.process import ProcessResult
from splatforge.core.reconstruction import CasparDevice

if TYPE_CHECKING:
    from splatforge.adapters.colmap_capabilities import ColmapCapabilityAdapter


def require_caspar_execution(result: ProcessResult) -> None:
    text = result.stdout_text() + "\n" + result.stderr_text()
    forbidden = (
        "unsupported camera model",
        "Skipping image",
        "Skipping external observation",
        "fallback to ceres",
        "falling back to ceres",
        "falling back to cpu",
        "built without CASPAR_ENABLED",
        "option will be ignored",
    )
    if (
        result.exit_code != 0
        or result.timed_out
        or result.cancelled
        or result.forced_tree_termination
        or not result.teardown_confirmed
        or any(s.lower() in text.lower() for s in forbidden)
        or "Creating Caspar bundle adjuster" not in text
        or not any(s in text for s in ("Caspar: CONVERGED_", "Caspar: MAX_ITERATIONS"))
    ):
        raise FeatureCapabilityError(
            "mapping.caspar_execution_unverified: positive Caspar solver evidence missing or "
            "unsupported/fallback behavior reported; no Ceres retry. " + text[-2048:]
        )


def observe_caspar_device(
    probe: ColmapCapabilityAdapter,
    selection: ExecutableSelection,
    index: int,
    workspace: Path,
) -> CasparDevice:
    result = probe._run(
        sys.executable,
        (
            "-m",
            "splatforge.adapters.caspar_device_worker",
            str(index),
            str(cuda_runtime_path(selection)),
        ),
        15,
        working_directory=workspace,
        environment=scoped_runtime_environment(selection.runtime_layout, os.environ),
    )
    if (
        result.exit_code != 0
        or result.timed_out
        or result.cancelled
        or result.forced_tree_termination
        or result.stdout_truncated
    ):
        raise FeatureCapabilityError(
            "mapping.gpu_unavailable: "
            + result.stdout_text()[-1024:]
            + result.stderr_text()[-1024:]
        )
    try:
        device = CasparDevice.model_validate_json(result.stdout)
    except ValueError as exc:
        raise FeatureCapabilityError(
            "mapping.gpu_unavailable: invalid CUDA device evidence"
        ) from exc
    if device.index != index:
        raise FeatureCapabilityError("mapping.gpu_unavailable: CUDA device ordinal differs")
    return device


def cuda_runtime_path(selection: ExecutableSelection) -> Path:
    """Use the selected bundle's runtime, never an unrelated installed toolkit."""
    if selection.runtime_layout:
        for entry in selection.runtime_layout.path_entries:
            for name in (
                "cudart64_12.dll",
                "cudart64_13.dll",
                "libcudart.so.12",
                "libcudart.so.13",
            ):
                path = Path(entry) / name
                if path.is_file() and not path.is_symlink() and not path.is_junction():
                    return path.resolve()
    raise FeatureCapabilityError(
        "mapping.gpu_unavailable: selected bundle has no inspectable CUDA runtime library; "
        "cannot establish Caspar's runtime GPU ordinal identity"
    )


def probe_caspar(
    probe: ColmapCapabilityAdapter,
    selection: ExecutableSelection,
    index: int,
) -> CasparDevice:
    workspace = Path(tempfile.mkdtemp(prefix="splatforge-colmap-caspar-")).resolve()
    workspace_identity = workspace.stat()
    # Match Doctor's quarantine semantics: never clean an unresolved native tree.
    try:
        device = observe_caspar_device(probe, selection, index, workspace)
        source, output = workspace / "0", workspace / "1"
        source.mkdir()
        output.mkdir()
        mapping = _write_probe_model(source)
        environment = scoped_runtime_environment(selection.runtime_layout, os.environ)
        result = probe._run(
            selection.identity.resolved_path,
            (
                "bundle_adjuster",
                "--input_path",
                str(native_transport_path(source)),
                "--output_path",
                str(native_transport_path(output)),
                "--log_target",
                "stderr",
                "--log_level",
                "2",
                "--BundleAdjustment.backend",
                "CASPAR",
                "--BundleAdjustment.refine_sensor_from_rig",
                "0",
                "--BundleAdjustmentCaspar.gpu_index",
                str(index),
                "--BundleAdjustmentCaspar.solver_iter_max",
                "2",
            ),
            30,
            working_directory=workspace,
            environment=environment,
        )
        if not probe._same_identity(selection.identity, result.executable):
            raise FeatureCapabilityError("mapping.runtime_changed: Caspar probe executable changed")
        require_caspar_execution(result)
        component, cameras, views = read_component(output, mapping)
        if (
            component.point_count != 12
            or len(views) != 3
            or len(cameras) != 1
            or cameras[0].model != "PINHOLE"
        ):
            raise FeatureCapabilityError("mapping.caspar_probe_failed: BA payload contract differs")
        if observe_caspar_device(probe, selection, index, workspace) != device:
            raise FeatureCapabilityError("mapping.gpu_changed: CUDA device changed during probe")
        return device
    except ProcessCleanupError as exc:
        if not exc.teardown_confirmed:
            raise DoctorTeardownError(
                f"Caspar probe teardown unresolved; quarantine {workspace}"
            ) from exc
        raise
    finally:
        if not isinstance(sys.exception(), DoctorTeardownError):
            probe._cleanup_workspace(workspace, workspace_identity)


def _write_probe_model(directory: Path) -> NativeFeaturePayload:
    mapping = NativeFeaturePayload(
        user_version=0,
        application_id=0,
        tables=(),
        images=tuple(
            FeatureImageMapping(view_id=UUID(int=i), image_id=i, image_name=f"{UUID(int=i)}.png")
            for i in (1, 2, 3)
        ),
    )
    points = [(i % 4 * 0.3 - 0.45, i // 4 * 0.3 - 0.3, 4.0 + i * 0.1) for i in range(12)]
    (directory / "cameras.bin").write_bytes(
        struct.pack("<QIiQQ4d", 1, 1, 1, 640, 480, 400, 400, 320, 240)
    )
    with (directory / "images.bin").open("wb") as stream:
        stream.write(struct.pack("<Q", 3))
        for i in (1, 2, 3):
            tx = (i - 2) * 0.3
            stream.write(struct.pack("<I7dI", i, 1, 0, 0, 0, tx, 0, 0, 1))
            stream.write(f"{UUID(int=i)}.png".encode() + b"\0" + struct.pack("<Q", 12))
            for j, (x, y, z) in enumerate(points):
                stream.write(
                    struct.pack("<ddQ", 320 + 400 * (x + tx) / z, 240 + 400 * y / z, j + 1)
                )
    with (directory / "points3D.bin").open("wb") as stream:
        stream.write(struct.pack("<Q", 12))
        for j, (x, y, z) in enumerate(points):
            stream.write(struct.pack("<Q3d3BdQ", j + 1, x, y, z, 0, 0, 0, 0, 3))
            for i in (1, 2, 3):
                stream.write(struct.pack("<II", i, j))
    return mapping
