"""Exact source-presentation-time restrictions, independent of player FPS and storage."""

from fractions import Fraction
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from splatforge.core.media import MediaType, SourceOccurrence
from splatforge.core.views import RationalValue


class VideoUsageError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class VideoInterval(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    start: RationalValue
    end: RationalValue

    @model_validator(mode="after")
    def ordered(self) -> "VideoInterval":
        if self.start.as_fraction() >= self.end.as_fraction():
            raise ValueError("Interval start must be before end")
        return self


def interval(start: str, end: str) -> VideoInterval:
    """UI strings are decimal seconds or fractions; binary floats are never accepted."""
    try:
        return VideoInterval(
            start=RationalValue.from_fraction(Fraction(start)),
            end=RationalValue.from_fraction(Fraction(end)),
        )
    except (ValueError, ZeroDivisionError, TypeError) as exc:
        raise VideoUsageError("invalid_interval", "Enter finite exact start < end seconds") from exc


def normalize(intervals: tuple[VideoInterval, ...]) -> tuple[VideoInterval, ...]:
    result: list[VideoInterval] = []
    for item in sorted(intervals, key=lambda i: i.start.as_fraction()):
        if result and item.start.as_fraction() <= result[-1].end.as_fraction():
            result[-1] = VideoInterval(
                start=result[-1].start,
                end=RationalValue.from_fraction(
                    max(result[-1].end.as_fraction(), item.end.as_fraction())
                ),
            )
        else:
            result.append(item)
    return tuple(result)


class VideoSource(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    source_id: UUID
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    stream_index: int = Field(ge=0, strict=True)
    start: RationalValue | None = None
    playback_start: RationalValue | None = None
    duration: RationalValue | None = None

    @classmethod
    def from_source(cls, source: SourceOccurrence) -> "VideoSource":
        if source.media_type != MediaType.VIDEO:
            raise VideoUsageError("not_video", "Select a registered video")

        def exact(text: str | None) -> RationalValue | None:
            try:
                return RationalValue.from_fraction(Fraction(text)) if text is not None else None
            except (ValueError, ZeroDivisionError):
                return None

        return cls(
            source_id=source.source_id,
            content_sha256=source.content_sha256,
            stream_index=source.probe.selected_visual_stream_index,
            start=exact(source.probe.start_time),
            playback_start=exact(source.probe.playback_start_time),
            duration=exact(source.probe.duration),
        )

    def validate_bounds(self, items: tuple[VideoInterval, ...]) -> None:
        if self.start is None:
            return
        lower = self.start.as_fraction()
        upper = lower + self.duration.as_fraction() if self.duration is not None else None
        if any(
            i.start.as_fraction() < lower or (upper is not None and i.end.as_fraction() > upper)
            for i in items
        ):
            raise VideoUsageError("out_of_bounds", "Interval lies outside the known video timeline")

    def player_time(self, milliseconds: str) -> RationalValue:
        if self.playback_start is None:
            raise VideoUsageError(
                "timeline_origin_unknown", "Source presentation origin is unknown"
            )
        try:
            # Qt position is an integer count of milliseconds, never FPS-derived.
            if not milliseconds.isdecimal():
                raise ValueError
            return RationalValue.from_fraction(
                self.playback_start.as_fraction() + Fraction(int(milliseconds), 1000)
            )
        except (ValueError, TypeError) as exc:
            raise VideoUsageError(
                "invalid_position", "Player position must be nonnegative integer ms"
            ) from exc

    def player_position(self, source_seconds: str) -> int:
        """Round exact source time to nearest Qt millisecond, ties toward later time."""
        if self.playback_start is None:
            raise VideoUsageError(
                "timeline_origin_unknown", "Source presentation origin is unknown"
            )
        try:
            elapsed = (Fraction(source_seconds) - self.playback_start.as_fraction()) * 1000
            if elapsed < 0:
                raise ValueError
            rounded = elapsed + Fraction(1, 2)
            return rounded.numerator // rounded.denominator
        except (ValueError, ZeroDivisionError, TypeError) as exc:
            raise VideoUsageError(
                "invalid_position", "Time precedes playback or is invalid"
            ) from exc


class VideoUsageEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    source_id: UUID
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    stream_index: int = Field(ge=0, strict=True)
    intervals: tuple[VideoInterval, ...]

    @model_validator(mode="after")
    def canonical(self) -> "VideoUsageEntry":
        if self.intervals != normalize(self.intervals):
            raise ValueError("Saved video intervals must be sorted, disjoint and non-adjacent")
        return self


class VideoUsageIntent(BaseModel):
    model_config = ConfigDict(extra="allow", frozen=True, allow_inf_nan=False)
    __pydantic_extra__: dict[str, JsonValue] = Field(init=False)
    schema_version: int = Field(default=1, ge=1, strict=True)
    entries: tuple[VideoUsageEntry, ...] = ()

    @model_validator(mode="after")
    def unique_sources(self) -> "VideoUsageIntent":
        ids = [e.source_id for e in self.entries]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate video usage source IDs")
        return self

    def resolve(self, source: VideoSource) -> tuple[VideoInterval, ...] | None:
        if self.schema_version != 1:
            raise VideoUsageError(
                "unsupported_video_usage_version", "Unsupported video usage version"
            )
        entry = next((e for e in self.entries if e.source_id == source.source_id), None)
        if entry is None:
            return None
        if (entry.content_sha256, entry.stream_index) != (
            source.content_sha256,
            source.stream_index,
        ):
            raise VideoUsageError(
                "source_identity_changed", "Saved intervals belong to different media"
            )
        source.validate_bounds(entry.intervals)
        return entry.intervals


def usable_video_sources(
    sources: tuple[SourceOccurrence, ...], intent: VideoUsageIntent
) -> tuple[SourceOccurrence, ...]:
    if intent.schema_version != 1:
        raise VideoUsageError("unsupported_video_usage_version", "Unsupported video usage version")
    return tuple(
        s
        for s in sources
        if s.media_type != MediaType.VIDEO or intent.resolve(VideoSource.from_source(s)) != ()
    )


def edit_intervals(
    current: tuple[VideoInterval, ...] | None,
    source: VideoSource,
    operation: Literal["add", "update", "remove", "exclude", "reset", "empty"],
    value: VideoInterval | None = None,
    index: int = -1,
) -> tuple[VideoInterval, ...] | None:
    if operation == "reset":
        return None
    if operation == "empty":
        return ()
    items = list(current or ())
    if operation in {"update", "remove"}:
        if not 0 <= index < len(items):
            raise VideoUsageError("invalid_interval_index", "Interval no longer exists")
        items.pop(index)
    if operation in {"add", "update", "exclude"}:
        if value is None:
            raise VideoUsageError("invalid_interval", "Interval is required")
        source.validate_bounds((value,))
        if operation == "exclude":
            if current is None:
                if source.start is None:
                    raise VideoUsageError(
                        "timeline_origin_unknown", "Source presentation origin is unknown"
                    )
                if source.duration is None:
                    raise VideoUsageError(
                        "duration_unknown", "Video duration is unknown; choose used intervals first"
                    )
                items = [
                    VideoInterval(
                        start=source.start,
                        end=RationalValue.from_fraction(
                            source.start.as_fraction() + source.duration.as_fraction()
                        ),
                    )
                ]
            remainder = []
            for item in items:
                a, b = item.start.as_fraction(), item.end.as_fraction()
                c, d = value.start.as_fraction(), value.end.as_fraction()
                if a < min(b, c):
                    remainder.append(
                        VideoInterval(start=item.start, end=RationalValue.from_fraction(min(b, c)))
                    )
                if max(a, d) < b:
                    remainder.append(
                        VideoInterval(start=RationalValue.from_fraction(max(a, d)), end=item.end)
                    )
            items = remainder
        else:
            items.append(value)
    result = normalize(tuple(items))
    source.validate_bounds(result)
    return result
