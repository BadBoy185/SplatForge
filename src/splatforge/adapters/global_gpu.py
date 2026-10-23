"""Separate Global GPU gates and positive Ceres execution evidence (COLMAP 4.2.1)."""

from __future__ import annotations

import os
import re
import struct
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from splatforge.adapters.caspar_probe import _write_probe_model, observe_caspar_device
from splatforge.adapters.colmap_features import native_transport_path
from splatforge.adapters.colmap_help import ParsedOptionHelp
from splatforge.adapters.colmap_reconstruction import read_component
from splatforge.adapters.colmap_runtime import scoped_runtime_environment
from splatforge.adapters.mapping_capabilities import supported_global_version
from splatforge.adapters.process_runner import ProcessCleanupError
from splatforge.application.doctor_contracts import DoctorTeardownError
from splatforge.application.features_contracts import FeatureCapabilityError
from splatforge.core.capabilities import (
    CapabilityEvidence,
    CapabilityStatus,
    ExecutableSelection,
    FreshnessPolicy,
    SubcommandDiscovery,
)
from splatforge.core.media import ExecutableIdentity
from splatforge.core.reconstruction import CasparDevice, GlobalAccelerationSettings

if TYPE_CHECKING:
    from splatforge.adapters.colmap_capabilities import ColmapCapabilityAdapter


def require_no_gpu_fallback(text: str) -> None:
    normalized = " ".join(text.lower().split())
    forbidden = (
        "compiled without cuda",
        "compiled without cudss",
        "falling back to cpu",
        "fallback to cpu",
        "retrying with cpu",
        "gpu solver unavailable",
        "gpu device unavailable",
        "no cuda gpu",
        "cuda initialization failed",
        "option will be ignored",
        "gpu bundle adjustment failed",
    )
    matched = tuple(value for value in forbidden if value in normalized)
    if matched:
        raise FeatureCapabilityError(
            "mapping.global_gpu_fallback: requested acceleration refused; "
            + "; ".join(matched)
            + "; native: "
            + normalized[-1024:]
        )


def _positive_solver(text: str, *, sparse_only: bool = False) -> bool:
    # Exact Ceres FullReport: Given/Used solver, used algebra library and a
    # positive linear-solver call count. A selected option or zero-work solve
    # cannot by itself certify actual GPU numerical execution.
    sections = re.split(r"Solver Summary[^\n]*", text)
    reports = sections[1:] if len(sections) > 1 else sections
    for report in reports:
        sparse = bool(
            re.search(r"Sparse linear algebra library\s+CUDA_SPARSE\b", report)
            and re.search(r"Linear solver\s+SPARSE_SCHUR\s+SPARSE_SCHUR\b", report)
        )
        dense = bool(
            re.search(r"Dense linear algebra library\s+CUDA\b", report)
            and re.search(r"Linear solver\s+DENSE_SCHUR\s+DENSE_SCHUR\b", report)
        )
        if not (sparse or (dense and not sparse_only)):
            return False
    # Every report must select GPU; at least one solve in the phase must execute.
    return any(
        re.search(r"(?m)^\s*Linear solver\s+[0-9.eE+-]+\s+\([1-9]\d*\)", report)
        for report in reports
    )


def require_global_gpu_execution(text: str, acceleration: GlobalAccelerationSettings) -> None:
    require_no_gpu_fallback(text)
    for requested, start, end, sparse in (
        (
            acceleration.positioning_device,
            "Running global positioning",
            "Global positioning done in",
            True,
        ),
        (
            acceleration.ba_device,
            "Running iterative bundle adjustment",
            "Iterative bundle adjustment done in",
            False,
        ),
    ):
        if requested == "cpu":
            continue
        sections = re.findall(re.escape(start) + r"(.*?)" + re.escape(end), text, re.S)
        if (
            not sections
            or len(sections) != text.count(start)
            or len(sections) != text.count(end)
            or not all(_positive_solver(section, sparse_only=sparse) for section in sections)
        ):
            raise FeatureCapabilityError(
                "mapping.global_gpu_execution_unverified: "
                + start
                + " lacks complete positive Ceres GPU solver evidence; no CPU retry"
            )

    if acceleration.ba_device != "cpu":
        # Refinement may run more BA solves after the initial iterative BA phase.
        start, end = (
            "Running iterative retriangulation and refinement",
            "Iterative retriangulation and refinement done in",
        )
        sections = re.findall(re.escape(start) + r"(.*?)" + re.escape(end), text, re.S)
        if len(sections) != text.count(start) or any(
            "Solver Summary" in section and not _positive_solver(section) for section in sections
        ):
            raise FeatureCapabilityError(
                "mapping.global_gpu_execution_unverified: refinement BA GPU evidence differs"
            )


def probe_global_ceres_gpu(
    probe: ColmapCapabilityAdapter,
    selection: ExecutableSelection,
    index: int,
) -> CasparDevice:
    """Necessary Ceres CUDA/cuDSS probe; does not certify Global GP integration."""
    workspace = Path(tempfile.mkdtemp(prefix="splatforge-colmap-global-gpu-")).resolve()
    ownership = workspace.stat()
    device = None
    try:
        device = observe_caspar_device(probe, selection, index, workspace)
        source, output = workspace / "input", workspace / "output"
        source.mkdir()
        output.mkdir()
        mapping = _write_probe_model(source)
        # Perfect reprojections could converge without invoking any linear solver.
        # Perturb owned synthetic points so the numerical probe must optimize.
        with (source / "points3D.bin").open("r+b") as stream:
            stream.seek(16)
            stream.write(struct.pack("<d", -0.42))
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
                "3",
                "--BundleAdjustment.backend",
                "CERES",
                "--BundleAdjustment.refine_sensor_from_rig",
                "0",
                "--BundleAdjustmentCeres.use_gpu",
                "1",
                "--BundleAdjustmentCeres.gpu_index",
                str(index),
                "--BundleAdjustmentCeres.min_num_images_gpu_solver",
                "0",
                "--BundleAdjustmentCeres.max_num_images_direct_dense_gpu_solver",
                "0",
                "--BundleAdjustmentCeres.max_num_iterations",
                "2",
            ),
            30,
            working_directory=workspace,
            environment=scoped_runtime_environment(selection.runtime_layout, os.environ),
        )
        text = result.stdout_text() + result.stderr_text()
        require_no_gpu_fallback(text)
        if (
            result.exit_code != 0
            or result.timed_out
            or result.cancelled
            or result.forced_tree_termination
            or not result.teardown_confirmed
            or result.stdout_truncated
            or result.stderr_truncated
            or not probe._same_identity(selection.identity, result.executable)
            or not _positive_solver(text, sparse_only=True)
        ):
            raise FeatureCapabilityError(
                "mapping.global_gpu_runtime_unverified: no positive CUDA/cuDSS sparse Ceres "
                "execution; Global subsystem integration remains unverified. " + text[-2048:]
            )
        component, cameras, views = read_component(output, mapping)
        if component.point_count != 12 or len(views) != 3 or len(cameras) != 1:
            raise FeatureCapabilityError("mapping.global_gpu_probe_invalid: output model differs")
        if observe_caspar_device(probe, selection, index, workspace) != device:
            raise FeatureCapabilityError("mapping.gpu_changed: device changed during Global probe")
        return device
    except FeatureCapabilityError as exc:
        exc.global_gpu_device = device
        raise
    except ProcessCleanupError as exc:
        if not exc.teardown_confirmed:
            raise DoctorTeardownError(f"Global GPU probe teardown unresolved: {workspace}") from exc
        raise
    finally:
        if not isinstance(sys.exception(), DoctorTeardownError):
            probe._cleanup_workspace(workspace, ownership)


def global_gpu_evidence(
    probe: ColmapCapabilityAdapter,
    capabilities: tuple[CapabilityEvidence, ...],
    helps: tuple[tuple[str, SubcommandDiscovery, ParsedOptionHelp], ...],
    identity: ExecutableIdentity,
    now: datetime,
    freshness: FreshnessPolicy,
    *,
    selection: ExecutableSelection | None = None,
    deep: bool = False,
) -> tuple[CapabilityEvidence, ...]:
    parsed = next((item[2] for item in helps if item[1].command == "global_mapper"), None)
    values = list(capabilities)
    runtime = CapabilityStatus.UNKNOWN
    cuda, cudss = CapabilityStatus.UNKNOWN, CapabilityStatus.UNKNOWN
    reason = "Ceres CUDA/cuDSS build and runtime not probed"
    if deep and selection is not None and supported_global_version(identity.version_line):
        try:
            device = probe_global_ceres_gpu(probe, selection, 0)
        except FeatureCapabilityError as exc:
            reason = str(exc)
            runtime = CapabilityStatus.UNAVAILABLE
            if "compiled without cuda" in reason.lower():
                cuda = CapabilityStatus.UNAVAILABLE
            if "compiled without cudss" in reason.lower():
                cudss = CapabilityStatus.UNAVAILABLE
        else:
            runtime = cuda = cudss = CapabilityStatus.AVAILABLE
            reason = (
                f"Bounded Ceres CUDA/cuDSS sparse probe passed on gpu:{device.index}, "
                f"{device.name}, UUID {device.uuid}; Global integration separate"
            )
    for subsystem, options in (
        ("positioning", {"GlobalMapper.gp_use_gpu", "GlobalMapper.gp_gpu_index"}),
        ("ba", {"GlobalMapper.ba_ceres_use_gpu", "GlobalMapper.ba_gpu_index"}),
    ):
        verified = (
            supported_global_version(identity.version_line)
            and parsed is not None
            and parsed.recognized
            and options | {"log_path", "log_level"} <= set(parsed.option_names)
        )
        for fact, status, message in (
            (
                "options",
                CapabilityStatus.AVAILABLE if verified else CapabilityStatus.UNKNOWN,
                "Separate typed Global GPU options verified"
                if verified
                else "GPU options unverified",
            ),
            (
                "runtime",
                runtime,
                reason,
            ),
            ("cuda", cuda, reason),
            ("cudss", cudss, reason),
            (
                "integration",
                CapabilityStatus.UNKNOWN,
                "Real Global subsystem requires positive phase-scoped Ceres GPU report; "
                "option acceptance/process exit do not prove GPU use",
            ),
        ):
            values.append(
                probe._evidence(
                    f"colmap.global_gpu.{subsystem}.{fact}",
                    status,
                    "mapping.global_gpu_options_verified"
                    if fact == "options" and verified
                    else "mapping.global_gpu_unverified",
                    message,
                    now,
                    freshness.static_cli_seconds,
                    identity,
                )
            )
    return tuple(values)
