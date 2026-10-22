"""Narrow evidence for the tested Global route, separate from command presence."""

from __future__ import annotations

import re
from datetime import datetime
from typing import TYPE_CHECKING

from splatforge.adapters.colmap_help import ParsedOptionHelp
from splatforge.core.capabilities import CapabilityEvidence, FreshnessPolicy, SubcommandDiscovery
from splatforge.core.media import ExecutableIdentity

if TYPE_CHECKING:
    from splatforge.adapters.colmap_capabilities import ColmapCapabilityAdapter

from splatforge.adapters.colmap_mapping_options import calibration_arguments, mapping_arguments
from splatforge.core.capabilities import CapabilityStatus
from splatforge.core.reconstruction import GlobalMapperSettings, ViewGraphCalibrationSettings


def supported_global_version(version_line: str | None) -> bool:
    # Later releases remain unknown until a positive real integration certifies them.
    match = re.search(r"COLMAP (\d+)\.(\d+)\.(\d+)\b", version_line or "")
    return bool(match and tuple(map(int, match.groups())) == (4, 2, 1))


def mapping_evidence(
    probe: ColmapCapabilityAdapter,
    capabilities: tuple[CapabilityEvidence, ...],
    helps: tuple[tuple[str, SubcommandDiscovery, ParsedOptionHelp], ...],
    identity: ExecutableIdentity,
    now: datetime,
    freshness: FreshnessPolicy,
) -> tuple[CapabilityEvidence, ...]:
    from pathlib import Path

    def evidence(cid, status, code, message):
        return probe._evidence(
            cid, status, code, message, now, freshness.static_cli_seconds, identity
        )

    version = supported_global_version(identity.version_line)
    by_command = {item[1].command: item[2] for item in helps}
    original = next(c for c in capabilities if c.capability_id == "colmap.mapper.global")
    values = [c for c in capabilities if c.capability_id != "colmap.mapper.global"]
    values.append(
        evidence(
            "colmap.mapper.global.version",
            CapabilityStatus.AVAILABLE if version else CapabilityStatus.UNAVAILABLE,
            "mapping.version_supported" if version else "mapping.unsupported_version",
            "Global production requires tested COLMAP 4.2.1 (floor >=4.2.1); "
            "4.2.0 refused, later builds need positive integration validation",
        )
    )
    for command, cid, builder, settings in (
        ("global_mapper", "colmap.mapper.global", mapping_arguments, GlobalMapperSettings()),
        (
            "view_graph_calibrator",
            "colmap.calibration.view_graph",
            calibration_arguments,
            ViewGraphCalibrationSettings(),
        ),
    ):
        parsed = by_command.get(command)
        valid = version and parsed is not None and parsed.recognized
        try:
            if valid:
                kwargs = {"database": Path("probe.db")}
                if command == "global_mapper":
                    kwargs.update(images=Path("images"), output=Path("sparse"))
                builder(settings, parsed.option_names, **kwargs)
        except ValueError:
            valid = False
        values.append(
            evidence(
                cid,
                CapabilityStatus.AVAILABLE
                if valid
                else (
                    CapabilityStatus.UNAVAILABLE
                    if original.status == CapabilityStatus.UNAVAILABLE
                    or (identity.version_line and not version)
                    else CapabilityStatus.UNKNOWN
                ),
                "mapping.options_verified" if valid else "mapping.options_unverified",
                f"{command}: command, version and required typed options "
                + (
                    "verified; actual scene integration is separate"
                    if valid
                    else "not positively verified"
                ),
            )
        )
    values.append(
        evidence(
            "colmap.mapper.global.integration",
            CapabilityStatus.UNKNOWN,
            "mapping.integration_not_run",
            "Doctor help/schema evidence does not "
            "certify a real reconstruction; run the opt-in M8a integration",
        )
    )
    return tuple(values)
