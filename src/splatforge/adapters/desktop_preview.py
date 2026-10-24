"""Read-only deterministic bounded sampling of published native point centers."""

import math
import struct
from pathlib import Path

from splatforge.adapters.colmap_reconstruction import binary
from splatforge.adapters.gaussian_ply import properties
from splatforge.core.reconstruction import ReconstructionPose


def sample_indices(count: int, limit: int) -> set[int]:
    return {i * count // min(count, limit) for i in range(min(count, limit))}


def sparse_centers(path: Path, limit: int = 20000) -> tuple[tuple[float, float, float], ...]:
    points = []
    size = path.stat().st_size
    with binary(path) as source:
        count = source.count(100000000)
        indices = sample_indices(count, limit)
        for i in range(count):
            _, x, y, z, *_ = source.read("QdddBBBd")
            tracks = source.count(1000000)
            offset = source.stream.tell() + tracks * 8
            if offset > size:
                raise ValueError("preview.truncated_sparse_tracks")
            source.stream.seek(offset)
            if i in indices:
                if not all(math.isfinite(v) for v in (x, y, z)):
                    raise ValueError("preview.nonfinite_point")
                points.append((x, y, z))
    return tuple(points)


def camera_centers(path: Path, limit: int = 2000) -> tuple[tuple[float, float, float], ...]:
    centers, size = [], path.stat().st_size
    with binary(path) as source:
        count = source.count(1000000)
        indices = sample_indices(count, limit)
        for i in range(count):
            row = source.read("I7dI")
            source.name()
            observations = source.count(10000000)
            offset = source.stream.tell() + observations * 24
            if offset > size:
                raise ValueError("preview.truncated_image_observations")
            source.stream.seek(offset)
            if i in indices:
                centers.append(
                    ReconstructionPose(
                        quaternion_wxyz=row[1:5], translation=row[5:8]
                    ).camera_center()
                )
    return tuple(centers)


def gaussian_centers(path: Path, limit: int = 20000) -> tuple[tuple[float, float, float], ...]:
    points = []
    with path.open("rb") as stream:
        lines, header_size = [], 0
        while True:
            line = stream.readline(1025)
            header_size += len(line)
            if not line or len(line) > 1024 or header_size > 16384:
                raise ValueError("preview.invalid_ply_header")
            lines.append(line.decode("ascii").strip())
            if lines[-1] == "end_header":
                break
        if lines[:2] != ["ply", "format binary_little_endian 1.0"]:
            raise ValueError("preview.unsupported_ply")
        count = int(lines[2].removeprefix("element vertex "))
        names = tuple(line.removeprefix("property float ") for line in lines[3:-1])
        if not 0 < count <= 10000000 or names not in [properties(d) for d in range(4)]:
            raise ValueError("preview.invalid_ply_layout")
        stride = len(names) * 4
        if path.stat().st_size != header_size + count * stride:
            raise ValueError("preview.invalid_ply_size")
        for i in sorted(sample_indices(count, limit)):
            stream.seek(header_size + i * stride)
            point = struct.unpack("<fff", stream.read(12))
            if not all(math.isfinite(v) for v in point):
                raise ValueError("preview.nonfinite_center")
            points.append(point)
    return tuple(points)
