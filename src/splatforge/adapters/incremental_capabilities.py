"""Command/options, compiled Caspar, runtime health and integration are separate facts."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from splatforge.adapters.colmap_help import ParsedOptionHelp
from splatforge.adapters.colmap_mapping_options import incremental_arguments
from splatforge.adapters.mapping_capabilities import supported_global_version
from splatforge.core.capabilities import (
    CapabilityEvidence,
    CapabilityStatus,
    FreshnessPolicy,
    SubcommandDiscovery,
)
from splatforge.core.media import ExecutableIdentity
from splatforge.core.reconstruction import IncrementalMapperSettings

if TYPE_CHECKING:
    from splatforge.adapters.colmap_capabilities import ColmapCapabilityAdapter


def incremental_evidence(
    probe: ColmapCapabilityAdapter,
    capabilities: tuple[CapabilityEvidence, ...],
    helps: tuple[tuple[str, SubcommandDiscovery, ParsedOptionHelp], ...],
    identity: ExecutableIdentity,
    now: datetime,
    freshness: FreshnessPolicy,
) -> tuple[CapabilityEvidence, ...]:
    def evidence(cid: str, status: CapabilityStatus, code: str, message: str) -> CapabilityEvidence:
        return probe._evidence(
            cid, status, code, message, now, freshness.static_cli_seconds, identity
        )

    version = supported_global_version(identity.version_line)
    by_command = {item[1].command: item[2] for item in helps}
    original = next(c for c in capabilities if c.capability_id == "colmap.mapper.incremental")
    values = [c for c in capabilities if c.capability_id != "colmap.mapper.incremental"]
    values.append(
        evidence(
            "colmap.mapper.incremental.version",
            CapabilityStatus.AVAILABLE if version else CapabilityStatus.UNAVAILABLE,
            "mapping.version_supported" if version else "mapping.unsupported_version",
            "Incremental requires positively tested COLMAP 4.2.1; later versions refused",
        )
    )
    parsed = by_command.get("mapper")
    valid = version and parsed is not None and parsed.recognized
    reason = "mapper help/options not positively recognized"
    code = "mapping.incremental_options_unverified"
    if not version:
        reason, code = (
            "unsupported COLMAP version; positively tested 4.2.1 required",
            ("mapping.unsupported_version"),
        )
    elif original.status == CapabilityStatus.UNAVAILABLE:
        reason, code = (
            "mapper command unavailable in this executable",
            ("mapping.incremental_command_unavailable"),
        )
    try:
        if valid:
            incremental_arguments(
                IncrementalMapperSettings(),
                parsed.option_names,
                database=Path("p.db"),
                images=Path("images"),
                output=Path("sparse"),
            )
    except ValueError as exc:
        valid = False
        reason, code = str(exc), "mapping.incremental_missing_options"
    status = (
        CapabilityStatus.AVAILABLE
        if valid
        else (
            CapabilityStatus.UNAVAILABLE
            if original.status == CapabilityStatus.UNAVAILABLE
            or (identity.version_line and not version)
            else CapabilityStatus.UNKNOWN
        )
    )
    values.append(
        evidence(
            "colmap.mapper.incremental",
            status,
            "mapping.options_verified" if valid else code,
            "Incremental Ceres CPU: "
            + ("command/version/typed options verified" if valid else reason),
        )
    )
    ba = by_command.get("bundle_adjuster")
    compiled = CapabilityStatus.UNKNOWN
    if version and ba and ba.recognized:
        # In exact 4.2.1 these options exist only inside #ifdef CASPAR_ENABLED.
        compiled = (
            CapabilityStatus.AVAILABLE
            if "BundleAdjustmentCaspar.gpu_index" in ba.option_names
            and "BundleAdjustmentCaspar.solver_iter_max" in ba.option_names
            else CapabilityStatus.UNAVAILABLE
        )
    values.append(
        evidence(
            "colmap.ba.caspar.compiled",
            compiled,
            "mapping.caspar_compiled"
            if compiled == CapabilityStatus.AVAILABLE
            else "mapping.caspar_not_compiled"
            if compiled == CapabilityStatus.UNAVAILABLE
            else "mapping.caspar_build_unknown",
            "Exact 4.2.1 bundle_adjuster help "
            + (
                "contains CASPAR_ENABLED-only options; GPU execution still needs a disposable probe"
                if compiled == CapabilityStatus.AVAILABLE
                else "omits CASPAR_ENABLED-only options: Caspar backend not compiled; select a "
                "separately provisioned Caspar build (SplatForge never builds/installs it)"
                if compiled == CapabilityStatus.UNAVAILABLE
                else "does not establish Caspar build support"
            ),
        )
    )
    caspar_options = valid and "log_level" in parsed.option_names
    values.append(
        evidence(
            "colmap.ba.caspar.options",
            CapabilityStatus.AVAILABLE if caspar_options else CapabilityStatus.UNKNOWN,
            "mapping.caspar_options_verified"
            if caspar_options
            else "mapping.caspar_options_unknown",
            "Separate local/global backend and concrete ba_gpu_index options "
            + (
                "verified; neither proves compiled Caspar or CUDA health"
                if caspar_options
                else "unverified"
            ),
        )
    )
    for cid, message in (
        ("colmap.mapper.incremental.integration", "Run opt-in M8b1 real Incremental integration"),
        (
            "colmap.ba.caspar.runtime",
            "Requested Caspar/device needs bounded native BA/CUDA preflight; "
            "NVIDIA inventory and learned GPU success are insufficient",
        ),
        (
            "colmap.ba.caspar.integration",
            "Real Caspar Incremental integration has not been run by Doctor",
        ),
    ):
        values.append(
            evidence(cid, CapabilityStatus.UNKNOWN, "mapping.integration_not_run", message)
        )
    return tuple(values)
