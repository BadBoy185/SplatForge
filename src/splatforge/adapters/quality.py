"""Pillow-backed deterministic M4 quality measurements."""

from __future__ import annotations

import platform
from fractions import Fraction
from pathlib import Path

from PIL import Image, ImageFilter, UnidentifiedImageError
from PIL import __version__ as pillow_version

from splatforge.core.quality import (
    DuplicateMeasurement,
    MeasurementAvailability,
    MeasurementUnavailableReason,
    NonNegativeRational,
    QualityAnalysisSettings,
    QualityBackendIdentity,
    SharpnessMeasurement,
    ViewQualityMeasurement,
)
from splatforge.core.views import CandidateView


class PillowQualityAdapter:
    """Measure one immutable candidate image at a time with bounded proxy pixels."""

    def identity(self) -> QualityBackendIdentity:
        return QualityBackendIdentity(
            pillow_version=pillow_version,
            python_version=platform.python_version(),
        )

    def measure(
        self,
        image_path: Path,
        view: CandidateView,
        settings: QualityAnalysisSettings,
    ) -> ViewQualityMeasurement:
        if not image_path.is_file() or image_path.is_symlink() or image_path.is_junction():
            raise ValueError(f"Candidate image is missing or unsafe: {view.view_id}")
        grayscale: Image.Image | None = None
        try:
            with Image.open(image_path) as image:
                if image.size != (view.width, view.height):
                    raise ValueError(
                        f"Decoded candidate dimensions disagree for {view.view_id}: "
                        f"decoded={image.size}, declared={(view.width, view.height)}"
                    )
                grayscale = image.convert("L")
                if max(grayscale.size) > settings.quality_max_side:
                    width, height = _bounded_dimensions(
                        grayscale.width,
                        grayscale.height,
                        settings.quality_max_side,
                    )
                    resized = grayscale.resize((width, height), Image.Resampling.LANCZOS)
                    grayscale.close()
                    grayscale = resized
        except FileNotFoundError:
            raise
        except (UnidentifiedImageError, OSError):
            return _unavailable(view, MeasurementUnavailableReason.DECODE_FAILED)

        assert grayscale is not None
        try:
            sharpness = _sharpness(grayscale)
            duplicate = _dhash(grayscale)
        finally:
            grayscale.close()
        return ViewQualityMeasurement(
            view_id=view.view_id,
            candidate_image_sha256=view.image_sha256,
            sharpness=sharpness,
            duplicate=duplicate,
        )


def _bounded_dimensions(width: int, height: int, max_side: int) -> tuple[int, int]:
    if width >= height:
        return max_side, max(1, (height * max_side + width // 2) // width)
    return max(1, (width * max_side + height // 2) // height), max_side


def _sharpness(grayscale: Image.Image) -> SharpnessMeasurement:
    if grayscale.width < 3 or grayscale.height < 3:
        return SharpnessMeasurement(
            availability=MeasurementAvailability.UNAVAILABLE,
            unavailable_reason=MeasurementUnavailableReason.IMAGE_TOO_SMALL,
        )
    edged = grayscale.filter(ImageFilter.FIND_EDGES)
    try:
        interior = edged.crop((1, 1, edged.width - 1, edged.height - 1))
        try:
            histogram = interior.histogram()
        finally:
            interior.close()
    finally:
        edged.close()
    count = sum(histogram)
    if count <= 0:
        return SharpnessMeasurement(
            availability=MeasurementAvailability.UNAVAILABLE,
            unavailable_reason=MeasurementUnavailableReason.IMAGE_TOO_SMALL,
        )
    value_sum = sum(value * frequency for value, frequency in enumerate(histogram))
    squared_sum = sum(value * value * frequency for value, frequency in enumerate(histogram))
    variance = Fraction(count * squared_sum - value_sum * value_sum, count * count)
    return SharpnessMeasurement(
        availability=MeasurementAvailability.AVAILABLE,
        score=NonNegativeRational.from_fraction(variance),
    )


def _dhash(grayscale: Image.Image) -> DuplicateMeasurement:
    proxy = grayscale.resize((9, 8), Image.Resampling.BILINEAR)
    try:
        pixels = tuple(proxy.tobytes())
    finally:
        proxy.close()
    value = 0
    for row in range(8):
        offset = row * 9
        for column in range(8):
            value = (value << 1) | int(pixels[offset + column] > pixels[offset + column + 1])
    return DuplicateMeasurement(
        availability=MeasurementAvailability.AVAILABLE,
        dhash64=f"{value:016x}",
    )


def _unavailable(
    view: CandidateView, reason: MeasurementUnavailableReason
) -> ViewQualityMeasurement:
    return ViewQualityMeasurement(
        view_id=view.view_id,
        candidate_image_sha256=view.image_sha256,
        sharpness=SharpnessMeasurement(
            availability=MeasurementAvailability.UNAVAILABLE,
            unavailable_reason=reason,
        ),
        duplicate=DuplicateMeasurement(
            availability=MeasurementAvailability.UNAVAILABLE,
            unavailable_reason=reason,
        ),
    )


__all__ = ["PillowQualityAdapter"]
