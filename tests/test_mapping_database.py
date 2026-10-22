"""Only mapper-consumed numerical dependencies enter mapping input identity."""

import shutil
import sqlite3
import struct
from contextlib import closing

from mapping_helpers import mapping_inputs

from splatforge.adapters.colmap_mapping import mapping_source
from splatforge.adapters.mapping_database import inspect_mapping_input


def test_numerical_projection_excludes_descriptors_raw_matches_paths_and_native_ids(tmp_path):
    value, fixture, _features, _raw, verified = mapping_inputs(tmp_path)
    source = value.execution.artifact_directory(value.root, verified.artifact)
    mapping, allowed = mapping_source(source)
    copied = tmp_path / "independent state.db"
    shutil.copyfile(source / "matches.db", copied)

    def digest(m=mapping, pairs=allowed):
        return inspect_mapping_input(copied, m, allowed_pairs=pairs)

    original = digest()
    with closing(sqlite3.connect(copied)) as db, db:
        for native, data in db.execute("SELECT image_id,data FROM descriptors").fetchall():
            db.execute(
                "UPDATE descriptors SET data=? WHERE image_id=?", (b"\1" * len(data), native)
            )
        db.execute("DELETE FROM matches")
    assert digest() == original
    with closing(sqlite3.connect(copied)) as db, db:
        db.execute("UPDATE cameras SET camera_id=camera_id+100")
        db.execute("UPDATE images SET camera_id=camera_id+100")
        db.execute("UPDATE images SET image_id=image_id+1000")
        db.execute("UPDATE keypoints SET image_id=image_id+1000")
        db.execute("UPDATE descriptors SET image_id=image_id+1000")
        delta = 1000 * ((2**31 - 1) + 1)
        db.execute("UPDATE two_view_geometries SET pair_id=pair_id+?", (delta,))
    changed_mapping = mapping.model_copy(
        update={
            "images": tuple(
                i.model_copy(update={"image_id": i.image_id + 1000}) for i in mapping.images
            )
        }
    )
    assert digest(changed_mapping, {p + delta for p in allowed}) == original
    with closing(sqlite3.connect(copied)) as db, db:
        native, data = db.execute("SELECT image_id,data FROM keypoints LIMIT 1").fetchone()
        db.execute(
            "UPDATE keypoints SET data=? WHERE image_id=?",
            (struct.pack("<f", 2) + data[4:], native),
        )
    changed = digest(changed_mapping, {p + delta for p in allowed})
    assert changed.keypoints_digest != original.keypoints_digest
    assert changed.geometry_digest == original.geometry_digest
