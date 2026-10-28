"""Bounded descriptive EXIF/container tags, without image decoding or inference."""

import math
import struct
import warnings
from datetime import datetime
from pathlib import Path

from PIL import Image

from splatforge.core.capture_metadata import CaptureMetadata


def _text(value: object) -> str | None:
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    if not isinstance(value, str):
        return None
    text = " ".join(value.replace("\x00", "").split())
    return text[:256] or None


def _number(value: object) -> float | None:
    try:
        number = float(value)
        return number if math.isfinite(number) and 0 < number < 1e9 else None
    except (TypeError, ValueError, OverflowError, ZeroDivisionError):
        return None


def _timestamp(value: object, offset: object = None) -> datetime | None:
    text = _text(value)
    if not text:
        return None
    # EXIF local time has no timezone unless OffsetTimeOriginal is present.
    if len(text) >= 19 and text[4] == ":" and text[7] == ":":
        text = text[:4] + "-" + text[5:7] + "-" + text[8:]
    if _text(offset) and len(text) == 19:
        text += _text(offset)
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _tiff_header(path: Path, byte_limit: int) -> bytes | None:
    with path.open("rb") as stream:
        signature = stream.read(8)
        if signature.startswith(b"\xff\xd8"):
            stream.seek(2)
            while stream.tell() + 4 <= byte_limit:
                if stream.read(1) != b"\xff":
                    return None
                marker = stream.read(1)
                while marker == b"\xff" and stream.tell() < byte_limit:
                    marker = stream.read(1)
                if marker in {b"", b"\xda", b"\xd9"}:
                    return None
                length = int.from_bytes(stream.read(2), "big") - 2
                if length < 0 or stream.tell() + length > byte_limit:
                    return None
                data = stream.read(length)
                if marker == b"\xe1" and data.startswith(b"Exif\x00\x00"):
                    return data[6:]
        elif signature == b"\x89PNG\r\n\x1a\n":
            # Metadata-only: do not scan pixel payloads looking for late EXIF.
            while stream.tell() + 12 <= byte_limit:
                header = stream.read(8)
                if len(header) != 8:
                    return None
                length, kind = int.from_bytes(header[:4], "big"), header[4:]
                if kind in {b"IDAT", b"IEND"} or stream.tell() + length + 4 > byte_limit:
                    return None
                if kind == b"eXIf":
                    return stream.read(length)
                stream.seek(length + 4, 1)
    return None


def read_photo_capture(path: Path, *, byte_limit: int = 1024 * 1024) -> CaptureMetadata:
    """Read at ingest only. Optional malformed tags cannot reject valid media."""
    fields = {}
    try:
        data = _tiff_header(path, byte_limit)
        if data:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                exif = Image.Exif()
                exif.load(data)
                for name, tag in (("make", 271), ("model", 272)):
                    fields[name] = _text(exif.get(tag))
                # A malformed sub-IFD must not discard valid top-level make/model.
                try:
                    details = exif.get_ifd(34665)
                except (ValueError, TypeError, OSError, SyntaxError, KeyError):
                    details = {}
                fields["lens_model"] = _text(details.get(42036))
                fields["captured_at"] = _timestamp(details.get(36867), details.get(36881))
                for name, tag in (
                    ("focal_length_mm", 37386), ("focal_length_35mm", 41989),
                    ("exposure_seconds", 33434), ("f_number", 33437),
                ):
                    fields[name] = _number(details.get(tag))
                iso = _number(details.get(34855))
                fields["iso"] = int(iso) if iso and iso.is_integer() else None
                fields["gps_present"] = bool(exif.get(34853))
    except (OSError, ValueError, TypeError, SyntaxError, KeyError, OverflowError, struct.error):
        pass
    return CaptureMetadata(origin="exif", **fields)


def container_capture(format_data: dict, stream: dict) -> CaptureMetadata:
    tags = {}
    for source in (format_data, stream):
        raw = source.get("tags")
        if isinstance(raw, dict):
            tags.update({str(k).casefold(): v for k, v in raw.items()})

    def first(*names: str) -> str | None:
        return next((value for n in names if (value := _text(tags.get(n)))), None)

    return CaptureMetadata(
        origin="container_tags",
        make=first("make", "com.apple.quicktime.make"),
        model=first("model", "com.apple.quicktime.model"),
        captured_at=_timestamp(first("com.apple.quicktime.creationdate", "creation_time")),
    )
