"""M10 capability is positively discovered independently of every mapper."""

from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from splatforge.adapters.colmap_help import ParsedOptionHelp
from splatforge.application.features_contracts import FeatureCapabilityError
from splatforge.core.capabilities import (
    CapabilityEvidence,
    CapabilityStatus,
    FreshnessPolicy,
    SubcommandDiscovery,
)
from splatforge.core.dataset import DatasetSettings
from splatforge.core.media import ExecutableIdentity

if TYPE_CHECKING:
    from splatforge.adapters.colmap_capabilities import ColmapCapabilityAdapter


def undistortion_arguments(
    settings: DatasetSettings,
    options: tuple[str, ...],
    *,
    images: Path,
    sparse: Path,
    output: Path,
) -> tuple[str, ...]:
    values = {
        "image_path": images,
        "input_path": sparse,
        "output_path": output,
        "output_type": "COLMAP",
        "copy_policy": "COPY",
        "max_image_size": settings.max_image_size if settings.max_image_size else -1,
        "blank_pixels": settings.blank_pixels,
        "min_scale": settings.min_scale,
        "max_scale": settings.max_scale,
        "roi_min_x": 0,
        "roi_min_y": 0,
        "roi_max_x": 1,
        "roi_max_y": 1,
        "jpeg_quality": settings.jpeg_quality,
        "num_threads": settings.num_threads,
        "log_target": "stderr",
        "default_random_seed": 0,
    }
    missing = set(values) - set(options)
    if missing:
        raise FeatureCapabilityError("dataset.unsupported_options: " + ", ".join(sorted(missing)))
    return (
        "image_undistorter",
        *(v for k, value in values.items() for v in ("--" + k, str(value))),
    )


def dataset_evidence(
    probe: "ColmapCapabilityAdapter",
    capabilities: tuple[CapabilityEvidence, ...],
    helps: tuple[tuple[str, SubcommandDiscovery, ParsedOptionHelp], ...],
    identity: ExecutableIdentity,
    now: datetime,
    freshness: FreshnessPolicy,
) -> tuple[CapabilityEvidence, ...]:
    from splatforge.adapters.mapping_capabilities import supported_global_version

    def fact(cid, available, code, message):
        return probe._evidence(
            cid, available, code, message, now, freshness.static_cli_seconds, identity
        )

    version = supported_global_version(identity.version_line)
    parsed = next(
        (h for _text, command, h in helps if command.command == "image_undistorter"), None
    )
    valid = version and parsed is not None and parsed.recognized
    if valid:
        try:
            undistortion_arguments(
                DatasetSettings(),
                parsed.option_names,
                images=Path("images"),
                sparse=Path("sparse"),
                output=Path("output"),
            )
        except ValueError:
            valid = False
    return (
        *capabilities,
        fact(
            "colmap.dataset.version",
            CapabilityStatus.AVAILABLE if version else CapabilityStatus.UNAVAILABLE,
            "dataset.version_supported" if version else "dataset.unsupported_version",
            "M10 requires positively tested COLMAP 4.2.1; later versions need validation",
        ),
        fact(
            "colmap.dataset.undistorter",
            CapabilityStatus.AVAILABLE if valid else CapabilityStatus.UNAVAILABLE,
            "dataset.options_verified" if valid else "dataset.options_unverified",
            "image_undistorter command/version/required options "
            + ("verified; integration is separate" if valid else "not positively verified"),
        ),
        fact(
            "colmap.dataset.integration",
            CapabilityStatus.UNKNOWN,
            "dataset.integration_not_run",
            "Run the opt-in M10 dataset integration; help alone does not certify a real dataset",
        ),
    )
