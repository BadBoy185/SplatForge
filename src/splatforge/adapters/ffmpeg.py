"""Contained FFmpeg adapter for bounded M3 candidate-view materialization."""

from __future__ import annotations

import os
import re
import sys
from fractions import Fraction
from pathlib import Path

from splatforge.adapters.process_runner import (
    ExecutableNotFoundError,
    LocalProcessRunner,
    ProcessBoundaryError,
    ProcessCancellation,
    ProcessRequest,
)
from splatforge.application.views_contracts import (
    FFmpegBackendError,
    FFmpegCancelledError,
    FFmpegForcedCleanupError,
    FFmpegMissingError,
    FFmpegOutputError,
    FFmpegTeardownError,
    FFmpegTimeoutError,
    MaterializedFrame,
)
from splatforge.core.media import ExecutableIdentity, MediaType, SourceOccurrence
from splatforge.core.process import ProcessResult
from splatforge.core.views import (
    CandidatePoolSettings,
    ImageFormat,
    OrientationOperation,
    RationalValue,
    photo_orientation_operation,
    video_orientation_operation,
)

_TIME_BASE = re.compile(r"config in time_base:\s*(-?\d+)/(-?\d+)")
_FRAME = re.compile(r"\bn:\s*(\d+)\s+pts:\s*(-?\d+)\s+pts_time:")


def orientation_filter(operation: OrientationOperation) -> str:
    filters = {
        OrientationOperation.IDENTITY: "null",
        OrientationOperation.MIRROR_HORIZONTAL: "hflip",
        OrientationOperation.ROTATE_180: "hflip,vflip",
        OrientationOperation.MIRROR_VERTICAL: "vflip",
        OrientationOperation.TRANSPOSE: "transpose=clock,hflip",
        OrientationOperation.ROTATE_90_CW: "transpose=clock",
        OrientationOperation.TRANSVERSE: "transpose=cclock,hflip",
        OrientationOperation.ROTATE_90_CCW: "transpose=cclock",
    }
    return filters[operation]


class FFmpegAdapter:
    def __init__(
        self,
        *,
        runner: LocalProcessRunner | None = None,
        executable: str | None = None,
        version_timeout_seconds: float = 10.0,
        max_metadata_bytes: int = 8 * 1024 * 1024,
    ) -> None:
        self._runner = runner or LocalProcessRunner()
        self._executable = executable or os.environ.get("SPLATFORGE_FFMPEG") or "ffmpeg"
        self._version_timeout_seconds = version_timeout_seconds
        self._max_metadata_bytes = max_metadata_bytes
        self._backend: ExecutableIdentity | None = None

    def identity(
        self, cancellation: ProcessCancellation | None = None
    ) -> ExecutableIdentity:
        if self._backend is not None:
            return self._backend
        try:
            result = self._runner.run(
                ProcessRequest(
                    executable=self._executable,
                    argv=("-version",),
                    working_directory=Path(sys.executable).resolve().parent,
                    environment={},
                    timeout_seconds=self._version_timeout_seconds,
                    max_stdout_bytes=64 * 1024,
                    max_stderr_bytes=64 * 1024,
                ),
                cancellation=cancellation,
            )
        except ExecutableNotFoundError as exc:
            raise FFmpegMissingError(
                "FFmpeg is unavailable; configure --ffmpeg or SPLATFORGE_FFMPEG"
            ) from exc
        except (ProcessBoundaryError, OSError) as exc:
            raise FFmpegBackendError(f"FFmpeg process boundary failed: {exc}") from exc
        self._require_success(result, version_probe=True)
        lines = result.stdout_text().splitlines()
        if result.stdout_truncated or not lines:
            raise FFmpegOutputError("FFmpeg version output is unavailable or truncated")
        self._backend = result.executable.model_copy(update={"version_line": lines[0][:1024]})
        return self._backend

    def materialize(
        self,
        source_path: Path,
        source: SourceOccurrence,
        output_directory: Path,
        settings: CandidatePoolSettings,
        *,
        timeout_seconds: int,
        expected_backend: ExecutableIdentity,
        cancellation: ProcessCancellation | None = None,
    ) -> tuple[MaterializedFrame, ...]:
        absolute = source_path.absolute()
        output_directory.mkdir(parents=True, exist_ok=False)
        suffix = ".jpg" if settings.encoding.image_format == ImageFormat.JPEG else ".png"
        pattern = output_directory / f"frame-%08d{suffix}"
        operation = (
            photo_orientation_operation(source.probe.orientation)
            if source.media_type == MediaType.PHOTO
            else video_orientation_operation(source.probe.rotation_degrees)
        )
        filters: list[str] = []
        if source.media_type == MediaType.VIDEO:
            interval = FractionText.reciprocal(settings.candidate_fps)
            filters.append(
                "select='isnan(prev_selected_t)+gte(t-prev_selected_t\\," + interval + ")'"
            )
        filters.extend(("showinfo", orientation_filter(operation)))
        argv: list[str] = [
            "-hide_banner",
            "-nostdin",
            "-loglevel",
            "info",
            "-noautorotate",
            "-i",
            str(absolute),
            "-map",
            f"0:{source.probe.selected_visual_stream_index}",
            "-an",
            "-sn",
            "-dn",
            "-vf",
            ",".join(filters),
            "-fps_mode",
            "passthrough",
            "-start_number",
            "0",
        ]
        if source.media_type == MediaType.PHOTO:
            argv.extend(("-frames:v", "1"))
        if settings.encoding.image_format == ImageFormat.JPEG:
            argv.extend(
                (
                    "-c:v",
                    "mjpeg",
                    "-q:v",
                    str(settings.encoding.jpeg_qscale),
                    "-pix_fmt",
                    settings.encoding.jpeg_pixel_format,
                )
            )
        else:
            argv.extend(
                (
                    "-c:v",
                    "png",
                    "-compression_level",
                    str(settings.encoding.png_compression_level),
                )
            )
        argv.append(str(pattern))
        try:
            result = self._runner.run(
                ProcessRequest(
                    executable=expected_backend.resolved_path,
                    argv=tuple(argv),
                    working_directory=output_directory.parent,
                    environment={},
                    timeout_seconds=timeout_seconds,
                    max_stdout_bytes=64 * 1024,
                    max_stderr_bytes=self._max_metadata_bytes,
                ),
                cancellation=cancellation,
            )
        except ExecutableNotFoundError as exc:
            raise FFmpegMissingError(
                "The frozen FFmpeg executable is no longer available"
            ) from exc
        except (ProcessBoundaryError, OSError) as exc:
            raise FFmpegBackendError(f"FFmpeg process boundary failed: {exc}") from exc
        self._require_success(result, version_probe=False)
        if not self._same_binary(expected_backend, result.executable):
            self._backend = None
            raise FFmpegBackendError(
                "FFmpeg executable changed after run provenance was frozen; start a new run"
            )
        if result.stderr_truncated:
            raise FFmpegOutputError(
                "FFmpeg frame metadata exceeded the bounded stderr capture"
            )
        entries = sorted(output_directory.iterdir(), key=lambda path: path.name)
        if any(not path.is_file() or path.is_symlink() or path.is_junction() for path in entries):
            raise FFmpegOutputError("FFmpeg output contains a non-file or redirected entry")
        expected_names = [f"frame-{index:08d}{suffix}" for index in range(len(entries))]
        if [path.name for path in entries] != expected_names:
            raise FFmpegOutputError(
                "FFmpeg output contains missing, duplicate, or unexpected files"
            )
        if not entries:
            raise FFmpegOutputError("FFmpeg produced no candidate image")
        if source.media_type == MediaType.PHOTO:
            if len(entries) != 1:
                raise FFmpegOutputError("A photo source must produce exactly one candidate")
            return (
                MaterializedFrame(
                    temporary_path=entries[0], sequence_index=0, pts=None, time_base=None
                ),
            )
        metadata = parse_showinfo(result.stderr_text())
        if len(metadata) != len(entries):
            raise FFmpegOutputError(
                "Emitted image count does not match parsed selected-frame metadata count"
            )
        frames = []
        paired = zip(metadata, entries, strict=True)
        for index, ((sequence, pts, time_base), path) in enumerate(paired):
            if sequence != index:
                raise FFmpegOutputError("FFmpeg selected-frame sequence is not contiguous")
            frames.append(
                MaterializedFrame(
                    temporary_path=path,
                    sequence_index=index,
                    pts=pts,
                    time_base=time_base,
                )
            )
        return tuple(frames)

    @staticmethod
    def _same_binary(left: ExecutableIdentity, right: ExecutableIdentity) -> bool:
        return left.model_copy(update={"version_line": None}) == right.model_copy(
            update={"version_line": None}
        )

    @staticmethod
    def _require_success(result: ProcessResult, *, version_probe: bool) -> None:
        if result.cancelled:
            raise FFmpegCancelledError(
                "FFmpeg was cancelled",
                teardown_confirmed=result.teardown_confirmed,
            )
        if result.timed_out:
            if not result.teardown_confirmed:
                raise FFmpegTeardownError("FFmpeg timed out and teardown was not confirmed")
            raise FFmpegTimeoutError("FFmpeg timed out after contained tree teardown")
        if not result.teardown_confirmed:
            raise FFmpegTeardownError("FFmpeg process-tree teardown could not be confirmed")
        if result.forced_tree_termination:
            raise FFmpegForcedCleanupError(
                "FFmpeg left surviving descendants that required forced tree termination"
            )
        if result.exit_code != 0:
            detail = result.stderr_text().strip()[:1024]
            action = "version probe" if version_probe else "materialization"
            raise FFmpegBackendError(
                f"FFmpeg {action} exited with code {result.exit_code}: "
                f"{detail or 'no diagnostic output'}"
            )


class FractionText:
    @staticmethod
    def reciprocal(value: RationalValue) -> str:
        return f"{value.denominator}/{value.numerator}"


def parse_showinfo(stderr: str) -> tuple[tuple[int, int, RationalValue], ...]:
    time_bases = _TIME_BASE.findall(stderr)
    if not time_bases:
        raise FFmpegOutputError("FFmpeg showinfo did not report a filter-link time base")
    distinct = set(time_bases)
    if len(distinct) != 1:
        raise FFmpegOutputError("FFmpeg showinfo reported ambiguous filter-link time bases")
    numerator, denominator = next(iter(distinct))
    try:
        time_base = RationalValue.from_fraction(Fraction(int(numerator), int(denominator)))
    except (ValueError, ZeroDivisionError) as exc:
        raise FFmpegOutputError("FFmpeg showinfo reported an invalid time base") from exc
    frames = []
    seen_sequences: set[int] = set()
    for sequence_text, pts_text in _FRAME.findall(stderr):
        sequence = int(sequence_text)
        if sequence in seen_sequences:
            raise FFmpegOutputError("FFmpeg showinfo contains duplicate frame metadata")
        seen_sequences.add(sequence)
        frames.append((sequence, int(pts_text), time_base))
    if not frames:
        raise FFmpegOutputError("FFmpeg showinfo did not report selected-frame metadata")
    return tuple(frames)
