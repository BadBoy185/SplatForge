"""Hierarchy command/version/options evidence never inferred from Incremental."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from splatforge.adapters.colmap_help import ParsedOptionHelp
from splatforge.core.capabilities import CapabilityEvidence, FreshnessPolicy, SubcommandDiscovery
from splatforge.core.media import ExecutableIdentity

if TYPE_CHECKING:
    from splatforge.adapters.colmap_capabilities import ColmapCapabilityAdapter

from splatforge.adapters.colmap_mapping_options import hierarchical_arguments
from splatforge.adapters.mapping_capabilities import supported_global_version
from splatforge.core.capabilities import CapabilityStatus
from splatforge.core.reconstruction import HierarchicalMapperSettings


def hierarchical_evidence(
    probe: ColmapCapabilityAdapter,
    capabilities: tuple[CapabilityEvidence, ...],
    helps: tuple[tuple[str, SubcommandDiscovery, ParsedOptionHelp], ...],
    identity: ExecutableIdentity,
    now: datetime,
    freshness: FreshnessPolicy,
) -> tuple[CapabilityEvidence, ...]:
    def evidence(cid, status, code, message):
        return probe._evidence(
            cid, status, code, message, now, freshness.static_cli_seconds, identity
        )

    version = supported_global_version(identity.version_line)
    parsed = next((item[2] for item in helps if item[1].command == "hierarchical_mapper"), None)
    original = next(c for c in capabilities if c.capability_id == "colmap.mapper.hierarchical")
    valid = version and parsed is not None and parsed.recognized
    reason = "hierarchical_mapper command/version/typed hierarchy and Mapper options unverified"
    try:
        if valid:
            hierarchical_arguments(
                HierarchicalMapperSettings(),
                parsed.option_names,
                database=Path("p.db"),
                images=Path("images"),
                output=Path("sparse"),
            )
    except ValueError as exc:
        valid, reason = False, str(exc)
    return tuple(c for c in capabilities if c.capability_id != "colmap.mapper.hierarchical") + (
        evidence(
            "colmap.mapper.hierarchical.version",
            CapabilityStatus.AVAILABLE if version else CapabilityStatus.UNAVAILABLE,
            "mapping.version_supported" if version else "mapping.unsupported_version",
            "Hierarchical requires positively tested COLMAP 4.2.1",
        ),
        evidence(
            "colmap.mapper.hierarchical",
            CapabilityStatus.AVAILABLE
            if valid
            else CapabilityStatus.UNAVAILABLE
            if original.status == CapabilityStatus.UNAVAILABLE or not version
            else CapabilityStatus.UNKNOWN,
            "mapping.hierarchical_options_verified"
            if valid
            else "mapping.hierarchical_options_unverified",
            "Hierarchy and required Mapper options verified; real transport separate"
            if valid
            else reason,
        ),
        evidence(
            "colmap.mapper.hierarchical.integration",
            CapabilityStatus.UNKNOWN,
            "mapping.integration_not_run",
            "Run opt-in partition/multiple-leaf/merge transport",
        ),
    )
