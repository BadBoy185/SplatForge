"""Pure saved Prepare intent, exact form fields and source-aware resolution."""

from collections.abc import Iterable, Mapping
from fractions import Fraction
from typing import Protocol
from uuid import UUID

from pydantic import JsonValue

from splatforge.core.media import MediaType, SourceOccurrence, VerificationPolicyId
from splatforge.core.project import MethodSettingsEnvelope, ProjectDocument
from splatforge.core.quality import (
    QualityAnalysisSettings,
    SharpestIntervalSettings,
    parse_non_negative_rational,
    validate_sharpest_candidate_density,
)
from splatforge.core.source_participation import resolve_effective_sources
from splatforge.core.video_usage import VideoSource
from splatforge.core.views import (
    CandidateEncodingSettings,
    CandidatePoolSettings,
    CandidateResourceLimits,
    FixedFpsSettings,
    FrozenModel,
    RationalValue,
    parse_fps,
    validate_fps_density,
)


class PrepareRequest(FrozenModel):
    candidate: CandidatePoolSettings
    selection: FixedFpsSettings | SharpestIntervalSettings
    quality: QualityAnalysisSettings | None = None
    limits: CandidateResourceLimits = CandidateResourceLimits()
    verification_policy: VerificationPolicyId = VerificationPolicyId.BALANCED_LOCAL


class PreparationRow(Protocol):
    identity: UUID
    values: Mapping[str, object]


_LEGACY_FIELDS = {"target_fps", "max_frames", "reject_blur", "reject_duplicates"}
_FIELDS = {
    "method", "interval_seconds", "candidate_fps", "image_format", "jpeg_qscale",
    "png_compression_level", "min_sharpness_enabled", "min_sharpness", "reject_duplicates",
    "duplicate_hamming_threshold", "duplicate_lookback", "quality_max_side",
}


def _extension(frame: MethodSettingsEnvelope) -> dict[str, JsonValue] | None:
    if frame.settings_schema_version != 1:
        raise ValueError(f"Unsupported saved schema for {frame.method_id}")
    if frame.method_id not in {
        "frame_selection.fixed_fps", "frame_selection.sharpest_interval",
    }:
        raise ValueError(f"Unsupported frame selection: {frame.method_id}")
    extra = frame.model_extra or {}
    if "prepare_data" not in extra:
        return None
    extension = extra["prepare_data"]
    if (not isinstance(extension, dict)
            or type(extension.get("schema_version")) is not int
            or extension["schema_version"] != 1):
        raise ValueError("Unsupported saved Prepare Data extension")
    return extension


def _saved_request(document: ProjectDocument) -> PrepareRequest:
    frame = document.settings.frame_selection
    extension = _extension(frame)
    legacy = set(frame.settings) <= _LEGACY_FIELDS
    if legacy:
        if "target_fps" not in frame.settings:
            raise ValueError("Saved frame selection requires target FPS")
        target = parse_fps(str(frame.settings["target_fps"]))
        selection = (
            FixedFpsSettings(target_fps=target)
            if frame.method_id == "frame_selection.fixed_fps" else
            SharpestIntervalSettings(
                target_fps=target,
                reject_duplicates=frame.settings.get("reject_duplicates", True),
            )
        )
    else:
        model = (FixedFpsSettings if frame.method_id == "frame_selection.fixed_fps"
                 else SharpestIntervalSettings)
        selection = model.model_validate(frame.settings)
    sharpest = isinstance(selection, SharpestIntervalSettings)
    if extension is None:
        return PrepareRequest(
            candidate=CandidatePoolSettings(
                candidate_fps=parse_fps(str(selection.target_fps.as_fraction()
                                            * (2 if sharpest else 1))),
                encoding=CandidateEncodingSettings(),
            ),
            selection=selection,
            quality=QualityAnalysisSettings() if sharpest else None,
        )
    if "candidate" not in extension or "quality" not in extension:
        raise ValueError("Saved Prepare Data extension requires candidate and quality settings")
    candidate = CandidatePoolSettings.model_validate(extension["candidate"])
    quality = (QualityAnalysisSettings.model_validate(extension["quality"])
               if extension["quality"] is not None else None)
    if sharpest and quality is None:
        raise ValueError("Sharpest Interval requires quality analysis settings")
    return PrepareRequest(candidate=candidate, selection=selection, quality=quality)


def preparation_request_fields(request: PrepareRequest) -> dict[str, object]:
    """Project an exact request, including historical values, without normalizing it."""
    selection, encoding = request.selection, request.candidate.encoding
    sharpest = isinstance(selection, SharpestIntervalSettings)
    threshold = selection.min_sharpness if sharpest else None
    return {
        "method": "sharpest_interval" if sharpest else "fixed_fps",
        "interval_seconds": str(1 / selection.target_fps.as_fraction()),
        "candidate_fps": str(request.candidate.candidate_fps.as_fraction()),
        "image_format": encoding.image_format.value,
        "jpeg_qscale": str(encoding.jpeg_qscale if encoding.jpeg_qscale is not None else 2),
        "png_compression_level": str(encoding.png_compression_level
                                     if encoding.png_compression_level is not None else 6),
        "min_sharpness_enabled": threshold is not None,
        "min_sharpness": str(threshold.as_fraction()) if threshold is not None else "",
        "reject_duplicates": selection.reject_duplicates if sharpest else False,
        "duplicate_hamming_threshold": str(selection.duplicate_hamming_threshold
                                            if sharpest else 4),
        "duplicate_lookback": str(selection.duplicate_lookback if sharpest else 8),
        "quality_max_side": str(request.quality.quality_max_side if request.quality else 1024),
    }


def prepare_settings_fields(document: ProjectDocument) -> dict[str, object]:
    """Read saved intent independently of the current media and unrelated methods."""
    request = _saved_request(document)
    fields = preparation_request_fields(request)
    if isinstance(request.selection, FixedFpsSettings):
        fields["reject_duplicates"] = True
    return fields


def _text(fields: Mapping[str, object], key: str) -> str:
    value = fields[key]
    if not isinstance(value, str):
        raise ValueError(f"{key} must be an exact string")
    return value.strip()


def _integer(fields: Mapping[str, object], key: str) -> int:
    text = _text(fields, key)
    if not text or not text.isascii() or not text.isdecimal():
        raise ValueError(f"{key} must be an integer")
    return int(text)


def _toggle(fields: Mapping[str, object], key: str) -> bool:
    value = fields[key]
    if type(value) is not bool:
        raise ValueError(f"{key} must be a boolean")
    return value


def prepare_target_fps(interval_seconds: str) -> RationalValue:
    """Return the exact reciprocal of a positive interval supplied as text."""
    if not isinstance(interval_seconds, str):
        raise ValueError("Interval seconds must be an exact string")
    try:
        interval = parse_fps(interval_seconds).as_fraction()
        return parse_fps(str(1 / interval))
    except ValueError as exc:
        raise ValueError(f"Invalid interval seconds: {exc}") from exc


def _canonical(request: PrepareRequest, has_video: bool | None) -> PrepareRequest:
    candidate, selection = request.candidate, request.selection
    if has_video is False:
        candidate = candidate.model_copy(update={"candidate_fps": parse_fps("1")})
        selection = selection.model_copy(update={"target_fps": parse_fps("1")})
    if isinstance(selection, SharpestIntervalSettings):
        if has_video is False or not selection.reject_duplicates:
            selection = selection.model_copy(update={
                "reject_duplicates": False, "duplicate_hamming_threshold": 4,
                "duplicate_lookback": 8,
            })
        quality = request.quality
        try:
            validate_sharpest_candidate_density(
                candidate, selection, has_video=has_video is not False,
            )
        except ValueError as exc:
            minimum = 2 * selection.target_fps.as_fraction()
            raise ValueError(
                f"Sharpest needs candidate sampling at least 2 * target: {minimum} frames/s. "
                "Increase candidate sampling or use a longer target interval."
            ) from exc
    else:
        quality = None
        try:
            validate_fps_density(candidate, selection)
        except ValueError as exc:
            raise ValueError(
                "Candidate frames/s must be greater than or equal to the target "
                f"({selection.target_fps.as_fraction()} frames/s)."
            ) from exc
    # Encoding's validator canonicalizes inactive format parameters. Revalidate
    # rather than changing recipe keys while retaining different artifact metadata.
    candidate = CandidatePoolSettings.model_validate(candidate.model_dump(mode="json"))
    return request.model_copy(update={
        "candidate": candidate, "selection": selection, "quality": quality,
    })


def resolve_preparation_request(
    document: ProjectDocument, *, has_video: bool | None = None,
) -> PrepareRequest:
    """Resolve active settings before planning/publication; saved intent stays intact."""
    return _canonical(_saved_request(document), has_video)


def prepare_settings_draft(
    document: ProjectDocument, fields: Mapping[str, object], *, has_video: bool = True,
) -> ProjectDocument:
    """Compose validated intent only; the existing project service owns persistence."""
    existing = _saved_request(document)  # Refuse unknown schemas before any conversion.
    unknown, missing = set(fields) - _FIELDS, _FIELDS - set(fields)
    if unknown or missing:
        raise ValueError(f"Prepare settings fields mismatch; missing={sorted(missing)}, "
                         f"unknown={sorted(unknown)}")
    method = _text(fields, "method")
    if method not in {"fixed_fps", "sharpest_interval"}:
        raise ValueError(f"Unsupported frame selection: {method}")
    # Photo-only forms retain the last valid video timing intent while inactive.
    target = (prepare_target_fps(_text(fields, "interval_seconds"))
              if has_video else existing.selection.target_fps)
    candidate_fps = (parse_fps(_text(fields, "candidate_fps")) if has_video
                     else existing.candidate.candidate_fps)
    image_format = _text(fields, "image_format")
    encoding = CandidateEncodingSettings(
        image_format=image_format,
        jpeg_qscale=_integer(fields, "jpeg_qscale") if image_format == "jpeg" else 2,
        png_compression_level=(_integer(fields, "png_compression_level")
                               if image_format == "png" else 6),
    )
    sharpest = method == "sharpest_interval"
    if sharpest:
        threshold = None
        if _toggle(fields, "min_sharpness_enabled"):
            threshold_text = _text(fields, "min_sharpness")
            if not threshold_text:
                raise ValueError("Enter a minimum sharpness threshold, or turn that filter off.")
            threshold = parse_non_negative_rational(threshold_text)
        duplicates = (_toggle(fields, "reject_duplicates") if has_video else
                      existing.selection.reject_duplicates
                      if isinstance(existing.selection, SharpestIntervalSettings) else True)
        selection = SharpestIntervalSettings(
            target_fps=target, min_sharpness=threshold, reject_duplicates=duplicates,
            duplicate_hamming_threshold=(
                _integer(fields, "duplicate_hamming_threshold") if duplicates and has_video
                else existing.selection.duplicate_hamming_threshold
                if duplicates and isinstance(existing.selection, SharpestIntervalSettings) else 4
            ),
            duplicate_lookback=(
                _integer(fields, "duplicate_lookback") if duplicates and has_video else
                existing.selection.duplicate_lookback
                if duplicates and isinstance(existing.selection, SharpestIntervalSettings) else 8
            ),
        )
        quality = QualityAnalysisSettings(quality_max_side=_integer(fields, "quality_max_side"))
    else:
        selection = FixedFpsSettings(target_fps=target)
        quality = None
    request = PrepareRequest(
        candidate=CandidatePoolSettings(candidate_fps=candidate_fps, encoding=encoding),
        selection=selection, quality=quality,
    )
    _canonical(request, has_video)  # Validate density for the actual included usable media.
    frame = document.settings.frame_selection
    extension = dict(_extension(frame) or {})
    if set(frame.settings) <= _LEGACY_FIELDS:
        extension.setdefault("legacy_settings", frame.settings.copy())
    extension.update(schema_version=1, candidate=request.candidate.model_dump(mode="json"),
                     quality=quality.model_dump(mode="json") if quality else None)
    updated = frame.model_copy(update={
        "method_id": f"frame_selection.{method}", "settings_schema_version": 1,
        "settings": selection.model_dump(mode="json"), "prepare_data": extension,
    })
    return document.model_copy(update={
        "settings": document.settings.model_copy(update={"frame_selection": updated}),
    })


def preparation_media_context(
    document: ProjectDocument, rows: Iterable[SourceOccurrence | PreparationRow],
) -> dict[str, int | bool]:
    """Use registered source identity and saved participation/Trim, with no media I/O."""
    records = []
    for row in rows:
        if isinstance(row, SourceOccurrence):
            records.append((row.source_id, row.media_type,
                            VideoSource.from_source(row) if row.media_type == MediaType.VIDEO
                            else None))
        else:
            values = row.values
            media_type = MediaType(values["type"])

            video = VideoSource(
                source_id=row.identity, content_sha256=values["sha256"],
                stream_index=values["streamIndex"], start=_row_time(values.get("timelineStart")),
                duration=_row_time(values.get("duration")),
            ) if media_type == MediaType.VIDEO else None
            records.append((row.identity, media_type, video))
    identities = [record[0] for record in records]
    if len(identities) != len(set(identities)):
        raise ValueError("Duplicate registered source IDs")
    effective = resolve_effective_sources(identities, document.source_participation)
    if not effective.supported:
        raise ValueError("Unsupported source participation version; processing is unavailable")
    if document.video_usage.schema_version != 1:
        raise ValueError("Unsupported video usage version")
    included = set(effective.included_source_ids)
    photo_count = video_count = used_video_count = 0
    for identity, media_type, video in records:
        if identity not in included:
            continue
        if media_type == MediaType.PHOTO:
            photo_count += 1
        else:
            video_count += 1
            assert video is not None
            used_video_count += document.video_usage.resolve(video) != ()
    return dict(photo_count=photo_count, video_count=video_count,
                used_video_count=used_video_count, has_video=used_video_count > 0)


def _row_time(value: object) -> RationalValue | None:
    try:
        return RationalValue.from_fraction(Fraction(value)) if value is not None else None
    except (ValueError, ZeroDivisionError, TypeError):
        return None
