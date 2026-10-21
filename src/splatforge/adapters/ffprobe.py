"""FFprobe execution and normalization for the M2 source inventory."""

from __future__ import annotations

import json
import os
import re
import struct
import sys
from pathlib import Path
from typing import Any

from splatforge.adapters.process_runner import (
    LocalProcessRunner,
    ProcessCancellation,
    ProcessRequest,
)
from splatforge.application.media_contracts import (
    ProbeBackendError,
    ProbeCancelledError,
    ProbeMissingError,
    ProbeOutputError,
    ProbeTimeoutError,
    ProbeUnsupportedError,
)
from splatforge.core.media import ExecutableIdentity, MediaType, NormalizedProbe

_RATIONAL = re.compile(r"^-?\d+/-?\d+$")


class FFprobeAdapter:
    def __init__(
        self,
        *,
        runner: LocalProcessRunner | None = None,
        executable: str | None = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        self._runner = runner or LocalProcessRunner()
        self._executable = executable or os.environ.get("SPLATFORGE_FFPROBE") or "ffprobe"
        self._timeout_seconds = timeout_seconds
        self._backend: ExecutableIdentity | None = None

    def probe(
        self,
        path: Path,
        media_type: MediaType,
        *,
        cancellation: ProcessCancellation | None = None,
    ) -> NormalizedProbe:
        absolute = path.absolute()
        backend = self._backend_identity(cancellation)
        result = self._runner.run(
            ProcessRequest(
                executable=backend.resolved_path,
                argv=(
                    "-v",
                    "error",
                    "-print_format",
                    "json",
                    "-show_streams",
                    "-show_format",
                    str(absolute),
                ),
                working_directory=Path(sys.executable).resolve().parent,
                environment={},
                timeout_seconds=self._timeout_seconds,
            ),
            cancellation=cancellation,
        )
        self._require_success(result)
        if result.stdout_truncated:
            raise ProbeOutputError("FFprobe JSON exceeded the bounded stdout capture")
        try:
            payload = json.loads(result.stdout)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProbeOutputError(f"FFprobe returned malformed JSON: {exc}") from exc
        fallback_orientation = None
        if media_type == MediaType.PHOTO and absolute.suffix.lower() in {".jpg", ".jpeg"}:
            fallback_orientation = read_jpeg_exif_orientation(absolute)
        return normalize_ffprobe(
            payload,
            media_type=media_type,
            backend=backend,
            jpeg_orientation=fallback_orientation,
        )

    def _backend_identity(self, cancellation: ProcessCancellation | None) -> ExecutableIdentity:
        if self._backend is not None:
            return self._backend
        try:
            result = self._runner.run(
                ProcessRequest(
                    executable=self._executable,
                    argv=("-version",),
                    working_directory=Path(sys.executable).resolve().parent,
                    environment={},
                    timeout_seconds=min(self._timeout_seconds, 10.0),
                    max_stdout_bytes=64 * 1024,
                    max_stderr_bytes=64 * 1024,
                ),
                cancellation=cancellation,
            )
        except ValueError as exc:
            raise ProbeMissingError(
                "FFprobe is unavailable; configure --ffprobe or SPLATFORGE_FFPROBE"
            ) from exc
        self._require_success(result)
        first_line = result.stdout_text().splitlines()
        if result.stdout_truncated or not first_line:
            raise ProbeOutputError("FFprobe version output is unavailable or truncated")
        self._backend = result.executable.model_copy(update={"version_line": first_line[0][:1024]})
        return self._backend

    @staticmethod
    def _require_success(result: Any) -> None:
        if result.cancelled:
            raise ProbeCancelledError("FFprobe was cancelled after contained tree teardown")
        if result.timed_out:
            raise ProbeTimeoutError("FFprobe timed out after contained tree teardown")
        if not result.teardown_confirmed:
            raise ProbeBackendError("FFprobe process-tree teardown could not be confirmed")
        if result.exit_code != 0:
            detail = result.stderr_text().strip()[:1024]
            raise ProbeBackendError(
                f"FFprobe exited with code {result.exit_code}: {detail or 'no diagnostic output'}"
            )


def _optional_rational(value: object, field: str) -> str | None:
    if value in (None, "", "N/A", "0/0"):
        return None
    if not isinstance(value, str) or not _RATIONAL.fullmatch(value):
        raise ProbeOutputError(f"FFprobe {field} is not a rational value")
    denominator = int(value.split("/", maxsplit=1)[1])
    if denominator == 0:
        return None
    return value


def _optional_text(value: object) -> str | None:
    if value in (None, "", "N/A"):
        return None
    return str(value)


def _orientation(stream: dict[str, object], fallback: int | None) -> int | None:
    tags = stream.get("tags")
    if isinstance(tags, dict):
        for key in ("orientation", "Orientation"):
            raw = tags.get(key)
            try:
                value = int(raw) if raw is not None else None
            except (TypeError, ValueError):
                value = None
            if value is not None and 1 <= value <= 8:
                return value
    return fallback


def _rotation(stream: dict[str, object]) -> int | None:
    side_data = stream.get("side_data_list")
    if isinstance(side_data, list):
        for item in side_data:
            if isinstance(item, dict) and item.get("rotation") is not None:
                try:
                    return int(float(str(item["rotation"])))
                except ValueError:
                    pass
    tags = stream.get("tags")
    if isinstance(tags, dict) and tags.get("rotate") is not None:
        try:
            return int(float(str(tags["rotate"])))
        except ValueError:
            return None
    return None


def normalize_ffprobe(
    payload: object,
    *,
    media_type: MediaType,
    backend: ExecutableIdentity,
    jpeg_orientation: int | None = None,
) -> NormalizedProbe:
    if not isinstance(payload, dict) or not isinstance(payload.get("streams"), list):
        raise ProbeOutputError("FFprobe JSON does not contain a streams array")
    visual = [
        item
        for item in payload["streams"]
        if isinstance(item, dict)
        and item.get("codec_type") == "video"
        and not (
            isinstance(item.get("disposition"), dict)
            and item["disposition"].get("attached_pic") == 1
        )
    ]
    if not visual:
        raise ProbeUnsupportedError("FFprobe found no supported visual stream")
    if len(visual) != 1:
        raise ProbeUnsupportedError(
            "Multiple visual streams are ambiguous in M2; select or preprocess one stream"
        )
    stream = visual[0]
    try:
        index = int(stream["index"])
        width = int(stream["width"])
        height = int(stream["height"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ProbeOutputError("FFprobe visual stream lacks valid index/dimensions") from exc
    if index < 0 or width <= 0 or height <= 0:
        raise ProbeOutputError("FFprobe visual stream has invalid index/dimensions")

    if media_type == MediaType.PHOTO:
        return NormalizedProbe(
            backend=backend,
            selected_visual_stream_index=index,
            codec_name=_optional_text(stream.get("codec_name")),
            width=width,
            height=height,
            orientation=_orientation(stream, jpeg_orientation),
        )

    format_data = payload.get("format")
    if not isinstance(format_data, dict):
        format_data = {}
    frame_count = None
    raw_frame_count = stream.get("nb_frames")
    if raw_frame_count not in (None, "", "N/A"):
        try:
            frame_count = int(str(raw_frame_count))
        except ValueError as exc:
            raise ProbeOutputError("FFprobe frame count is invalid") from exc
    return NormalizedProbe(
        backend=backend,
        selected_visual_stream_index=index,
        codec_name=_optional_text(stream.get("codec_name")),
        width=width,
        height=height,
        orientation=None,
        time_base=_optional_rational(stream.get("time_base"), "time_base"),
        average_frame_rate=_optional_rational(stream.get("avg_frame_rate"), "avg_frame_rate"),
        raw_frame_rate=_optional_rational(stream.get("r_frame_rate"), "r_frame_rate"),
        duration=_optional_text(stream.get("duration") or format_data.get("duration")),
        frame_count=frame_count,
        rotation_degrees=_rotation(stream),
    )


def read_jpeg_exif_orientation(path: Path, *, byte_limit: int = 1024 * 1024) -> int | None:
    """Read only enough JPEG APP1/TIFF metadata to locate EXIF orientation."""

    try:
        with path.open("rb") as stream:
            if stream.read(2) != b"\xff\xd8":
                return None
            consumed = 2
            while consumed < byte_limit:
                marker_start = stream.read(1)
                consumed += 1
                if marker_start != b"\xff":
                    return None
                marker = stream.read(1)
                consumed += 1
                while marker == b"\xff":
                    marker = stream.read(1)
                    consumed += 1
                if not marker or marker in {b"\xd9", b"\xda"}:
                    return None
                length_bytes = stream.read(2)
                consumed += 2
                if len(length_bytes) != 2:
                    return None
                length = int.from_bytes(length_bytes, "big")
                if length < 2 or consumed + length - 2 > byte_limit:
                    return None
                data = stream.read(length - 2)
                consumed += len(data)
                if len(data) != length - 2:
                    return None
                if marker == b"\xe1" and data.startswith(b"Exif\x00\x00"):
                    return _parse_tiff_orientation(data[6:])
    except OSError:
        return None
    return None


def _parse_tiff_orientation(data: bytes) -> int | None:
    if len(data) < 8 or data[:2] not in {b"II", b"MM"}:
        return None
    endian = "<" if data[:2] == b"II" else ">"
    if struct.unpack_from(f"{endian}H", data, 2)[0] != 42:
        return None
    offset = struct.unpack_from(f"{endian}I", data, 4)[0]
    if offset + 2 > len(data):
        return None
    count = struct.unpack_from(f"{endian}H", data, offset)[0]
    if count > 256 or offset + 2 + count * 12 > len(data):
        return None
    for index in range(count):
        entry = offset + 2 + index * 12
        tag, field_type, values = struct.unpack_from(f"{endian}HHI", data, entry)
        if tag == 0x0112 and field_type == 3 and values == 1:
            orientation = struct.unpack_from(f"{endian}H", data, entry + 8)[0]
            return orientation if 1 <= orientation <= 8 else None
    return None
