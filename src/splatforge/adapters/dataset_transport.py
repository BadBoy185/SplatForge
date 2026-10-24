"""Exact sparse tracks in owned COLMAP transport; unused feature rows are not SfM tracks."""

import sqlite3
import struct
from collections.abc import Callable
from contextlib import closing
from pathlib import Path
from uuid import UUID

from splatforge.adapters.colmap_reconstruction import binary
from splatforge.core.features import MAX_FEATURES_PER_VIEW
from splatforge.core.views import MAX_VIEWS


def write_sparse_tracks(
    source: Path,
    target: Path,
    native_views: dict[int, UUID],
    names: dict[UUID, str],
    index_path: Path,
    maximum_scratch_bytes: int,
    checkpoint: Callable[[], None],
) -> int:
    """Keep every 3D point and reciprocal track; compact only unassociated keypoints.

    COLMAP can assign NaN when undistorting an unprojectable unused feature. Such
    rows are not part of the registered sparse geometry. Excluding all of them
    deterministically also keeps numerical output independent of unused features.
    No image, point or supported track is removed. Native observation indices are
    remapped in both directions using a bounded disk index.
    """
    omitted = 0
    with closing(sqlite3.connect(index_path)) as db:
        db.execute("PRAGMA cache_size=-2048")
        db.execute(f"PRAGMA max_page_count={max(1, maximum_scratch_bytes // 4096)}")
        db.execute(
            "CREATE TABLE indices(image INTEGER, old INTEGER, new INTEGER, "
            "PRIMARY KEY(image,old)) WITHOUT ROWID"
        )
        with binary(source / "images.bin") as reader, (target / "images.bin").open("xb") as writer:
            count = reader.count(MAX_VIEWS)
            if count != len(names):
                raise ValueError("dataset.membership_mismatch: sparse input image count differs")
            writer.write(struct.pack("<Q", count))
            for _ in range(count):
                checkpoint()
                (image,) = reader.read("I")
                values = reader.read("7dI")
                reader.name()
                if image not in native_views or native_views[image] not in names:
                    raise ValueError("dataset.membership_mismatch: unexpected input model image")
                writer.write(struct.pack("<I7dI", image, *values))
                writer.write(names[native_views[image]].encode("ascii") + b"\0")
                count_offset = writer.tell()
                writer.write(struct.pack("<Q", 0))
                retained = 0
                for old in range(reader.count(MAX_FEATURES_PER_VIEW)):
                    if old % 1024 == 0:
                        checkpoint()
                    x, y, point = reader.read("ddQ")
                    if point == 2**64 - 1:
                        omitted += 1
                        continue
                    writer.write(struct.pack("<ddQ", x, y, point))
                    db.execute("INSERT INTO indices VALUES (?,?,?)", (image, old, retained))
                    retained += 1
                end = writer.tell()
                writer.seek(count_offset)
                writer.write(struct.pack("<Q", retained))
                writer.seek(end)
        with (
            binary(source / "points3D.bin") as reader,
            (target / "points3D.bin").open("xb") as writer,
        ):
            count = reader.count((source / "points3D.bin").stat().st_size // 51)
            writer.write(struct.pack("<Q", count))
            for ordinal in range(count):
                if ordinal % 128 == 0:
                    checkpoint()
                values = reader.read("Q3d3Bd")
                track_count = reader.count(MAX_VIEWS)
                writer.write(struct.pack("<Q3d3BdQ", *values, track_count))
                for _ in range(track_count):
                    image, old = reader.read("II")
                    row = db.execute(
                        "SELECT new FROM indices WHERE image=? AND old=?", (image, old)
                    ).fetchone()
                    if row is None:
                        raise ValueError("dataset.invalid_track: missing registered observation")
                    writer.write(struct.pack("<II", image, row[0]))
        checkpoint()
    index_path.unlink()
    return omitted
