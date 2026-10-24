"""Independent bounded disk consumer for conventional explicit 3DGS PLY payloads."""

from __future__ import annotations

import hashlib
import math
import sqlite3
import struct
import tempfile
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path


def properties(sh_degree: int) -> tuple[str, ...]:
    return (
        "x",
        "y",
        "z",
        "nx",
        "ny",
        "nz",
        "f_dc_0",
        "f_dc_1",
        "f_dc_2",
        *(f"f_rest_{i}" for i in range(3 * ((sh_degree + 1) ** 2 - 1))),
        "opacity",
        "scale_0",
        "scale_1",
        "scale_2",
        "rot_0",
        "rot_1",
        "rot_2",
        "rot_3",
    )


@dataclass(frozen=True)
class PlyEvidence:
    count: int
    sh_degree: int
    size: int
    sha256: str
    numerical_digest: str


def read_gaussian_ply(
    path: Path,
    *,
    max_bytes: int = 8 * 1024**3,
    max_gaussians: int = 10000000,
    checkpoint: Callable[[], None] = lambda: None,
) -> PlyEvidence:
    if path.is_symlink() or path.is_junction() or path.stat().st_nlink != 1:
        raise ValueError("scene.unsafe_ply: plain independent file required")
    size = path.stat().st_size
    if size > max_bytes:
        raise ValueError("scene.resource_limit: PLY byte bound exceeded")
    raw = hashlib.sha256()
    with path.open("rb") as stream:
        lines, header_bytes = [], 0
        while True:
            line = stream.readline(1025)
            header_bytes += len(line)
            if not line or len(line) > 1024 or header_bytes > 16384:
                raise ValueError("scene.invalid_header")
            raw.update(line)
            lines.append(line.decode("ascii").rstrip("\n\r"))
            if lines[-1] == "end_header":
                break
        if lines[:2] != ["ply", "format binary_little_endian 1.0"]:
            raise ValueError("scene.unsupported_ply_format")
        if not lines[2].startswith("element vertex "):
            raise ValueError("scene.invalid_count: element vertex declaration required")
        try:
            count = int(lines[2].removeprefix("element vertex "))
        except ValueError as exc:
            raise ValueError("scene.invalid_count") from exc
        if not 0 < count <= max_gaussians:
            raise ValueError("scene.resource_limit: Gaussian count")
        if any(not line.startswith("property float ") for line in lines[3:-1]):
            raise ValueError("scene.invalid_attributes: float property declarations required")
        names = tuple(line.removeprefix("property float ") for line in lines[3:-1])
        degree = next((d for d in range(4) if names == properties(d)), None)
        if degree is None:
            raise ValueError("scene.invalid_attributes: exact position/SH/opacity/scale/quaternion")
        record = struct.Struct("<" + "f" * len(names))
        if size != header_bytes + count * record.size:
            raise ValueError("scene.invalid_size_or_count")
        with (
            tempfile.TemporaryDirectory(prefix="splatforge-ply-") as temporary,
            closing(sqlite3.connect(Path(temporary) / "order.sqlite")) as db,
        ):
            db.execute("PRAGMA cache_size=-2048")
            db.execute(f"PRAGMA max_page_count={max(1024, count * 128 // 4096 + 1024)}")
            db.execute("CREATE TABLE rows(digest BLOB)")
            for index in range(count):
                if index % 1024 == 0:
                    checkpoint()
                data = stream.read(record.size)
                raw.update(data)
                values = record.unpack(data)
                if not all(math.isfinite(v) for v in values):
                    raise ValueError("scene.nonfinite: NaN/Inf in Gaussian")
                norm = sum(v * v for v in values[-4:])
                if norm < 1e-12 or abs(norm - 1) > 0.001:
                    raise ValueError("scene.invalid_quaternion: normalized wxyz required")
                if any(abs(v) > 80 for v in values[-7:-4]):
                    raise ValueError("scene.invalid_scale: log scale overflows float32")
                canonical = record.pack(*(0.0 if v == 0 else v for v in values))
                db.execute("INSERT INTO rows VALUES (?)", (hashlib.sha256(canonical).digest(),))
            digest = hashlib.sha256(f"gaussian_rows_v1:{count}:{degree}:".encode())
            for index, (value,) in enumerate(db.execute("SELECT digest FROM rows ORDER BY digest")):
                if index % 1024 == 0:
                    checkpoint()
                digest.update(value)
        checkpoint()
    return PlyEvidence(count, degree, size, raw.hexdigest(), digest.hexdigest())
