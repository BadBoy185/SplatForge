"""Numerical identity and malformed native database content, independent of SQLite layout."""

import shutil
import sqlite3
import struct
from contextlib import closing

import pytest
from matching_helpers import inputs, match, verify
from pydantic import ValidationError

from splatforge.adapters.feature_database import NativeFeaturePayload
from splatforge.adapters.matching_database import (
    _invert_geometry,
    inspect_raw_matches,
    inspect_verified_geometry,
)
from splatforge.core.geometry import VerificationSettings, VerifiedGeometrySet
from splatforge.core.matching import MatchSet


@pytest.fixture(scope="module")
def published(tmp_path_factory):
    directory = tmp_path_factory.mktemp("published_matching")
    value, fixture, features, pairs = inputs(directory)
    raw = match(value, fixture, features, pairs)
    checked = verify(value, fixture, raw)
    fs = value.execution.load_local_features(value.root, features.feature_artifact)
    ps = value.execution.load_pair_set(value.root, pairs.pair_set_artifact)
    ms = value.execution.load_match_set(value.root, raw.artifact)
    raw_path = (value.root / raw.artifact.manifest_path).parent
    geometry_path = (value.root / checked.artifact.manifest_path).parent
    mapping = NativeFeaturePayload.model_validate_json(
        (raw_path / "backend_mapping.json").read_bytes()
    )
    return fs, ps, ms, mapping, raw_path, geometry_path


def test_sqlite_layout_and_correspondence_row_order_do_not_change_identity(tmp_path, published):
    fs, ps, ms, mapping, raw, _ = published
    private = tmp_path / "copy.db"
    shutil.copyfile(raw / "matches.db", private)
    with closing(sqlite3.connect(private)) as db, db:
        for pid, data in list(db.execute("SELECT pair_id,data FROM matches WHERE rows>0")):
            values = list(struct.iter_unpack("<II", data))[::-1]
            db.execute(
                "UPDATE matches SET data=? WHERE pair_id=?",
                (b"".join(struct.pack("<II", a, b) for a, b in values), pid),
            )
        db.commit()
        db.execute("VACUUM")
    assert (
        inspect_raw_matches(private, fs, ps, mapping, maximum_matches=32768, maximum_bytes=10**8)
        == ms.pairs
    )


@pytest.mark.parametrize(
    "config,field", [(2, "E"), (3, "F"), (4, "H"), (5, "H"), (6, "H"), (8, None)]
)
def test_numeric_model_and_optional_relative_pose(tmp_path, published, config, field):
    fs, ps, ms, mapping, _, geometry = published
    private = tmp_path / "geometry.db"
    shutil.copyfile(geometry / "matches.db", private)
    with closing(sqlite3.connect(private)) as db, db:
        db.execute(
            "UPDATE two_view_geometries SET config=?,F=NULL,E=NULL,H=NULL WHERE rows>0", (config,)
        )
        if field:
            db.execute(
                f"UPDATE two_view_geometries SET {field}=? WHERE rows>0",
                (struct.pack("<9d", 1, 0, 0, 0, 1, 0, 0, 0, 1),),
            )
        db.execute(
            "UPDATE two_view_geometries SET qvec=?,tvec=? WHERE rows>0",
            (struct.pack("<4d", 1, 0, 0, 0), struct.pack("<3d", 0, 0, 0)),
        )
    first = inspect_verified_geometry(
        private, fs, ps, mapping, ms, VerificationSettings(), maximum_bytes=10**8
    )
    assert first[0].configuration == config and first[0].has_relative_pose
    assert first == inspect_verified_geometry(
        private, fs, ps, mapping, ms, VerificationSettings(), maximum_bytes=10**8
    )


@pytest.mark.parametrize(
    "sql,args",
    [
        ("UPDATE two_view_geometries SET H=? WHERE rows>0", (bytes(8),)),
        (
            "UPDATE two_view_geometries SET H=? WHERE rows>0",
            (struct.pack("<9d", *([float("nan")] * 9)),),
        ),
        ("UPDATE two_view_geometries SET qvec=? WHERE rows>0", (struct.pack("<4d", 1, 0, 0, 0),)),
        (
            "UPDATE two_view_geometries SET qvec=?,tvec=? WHERE rows>0",
            (struct.pack("<4d", 2, 0, 0, 0), struct.pack("<3d", 0, 0, 0)),
        ),
        ("UPDATE two_view_geometries SET data=? WHERE rows>0", (struct.pack("<II", 999, 0) * 24,)),
        ("UPDATE two_view_geometries SET config=1 WHERE rows>0", ()),
    ],
)
def test_malformed_geometric_numeric_layout_fails(tmp_path, published, sql, args):
    fs, ps, ms, mapping, _, geometry = published
    private = tmp_path / "bad.db"
    shutil.copyfile(geometry / "matches.db", private)
    with closing(sqlite3.connect(private)) as db, db:
        db.execute(sql, args)
    with pytest.raises(ValueError):
        inspect_verified_geometry(
            private, fs, ps, mapping, ms, VerificationSettings(), maximum_bytes=10**8
        )


def test_public_schema_requires_canonical_pairs_and_consistent_totals(published):
    _, _, ms, _, _, geometry = published
    for changes in (
        {"pairs": tuple(reversed(ms.pairs))},
        {"total_raw_match_count": 123},
        {"semantic_digest": "f" * 64},
        {"processed_pair_count": 2},
    ):
        with pytest.raises(ValidationError):
            MatchSet.model_validate({**ms.model_dump(), **changes})
    gs = VerifiedGeometrySet.model_validate_json((geometry / "verified_geometry.json").read_bytes())
    with pytest.raises(ValidationError):
        VerifiedGeometrySet.model_validate({**gs.model_dump(), "accepted_pair_count": 2})


def test_canonical_native_direction_inverts_pose_and_models():
    identity = (1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0)
    matrices, q, t = _invert_geometry(
        [identity, identity, identity], (1.0, 0.0, 0.0, 0.0), (1.0, 2.0, 3.0)
    )
    assert (
        matrices == [identity, identity, identity]
        and q == (1.0, 0.0, 0.0, 0.0)
        and t == (-1.0, -2.0, -3.0)
    )


def test_current_camera_sharing_is_fingerprinted_and_reassembled(tmp_path, published):
    from uuid import uuid4

    from splatforge.adapters.matching_database import assemble_camera_priors, validate_camera_priors
    from splatforge.core.geometry import CameraPriorSet, uncalibrated_camera_priors

    features, _pairs, _matches, mapping, raw, _geometry = published
    independent = uncalibrated_camera_priors(features)
    group = uuid4()
    shared = CameraPriorSet(
        cameras=tuple(c.model_copy(update={"camera_group_id": group}) for c in independent.cameras)
    )
    assert independent.semantic_digest != shared.semantic_digest
    relabeled = CameraPriorSet(
        cameras=tuple(
            c.model_copy(update={"camera_group_id": uuid4()}) for c in independent.cameras
        )
    )
    assert independent.semantic_digest == relabeled.semantic_digest
    private = tmp_path / "current-cameras.db"
    shutil.copyfile(raw / "matches.db", private)
    assemble_camera_priors(private, shared, features, mapping)
    validate_camera_priors(private, shared, mapping)
    with closing(sqlite3.connect(private)) as db:
        assert db.execute("SELECT count(*) FROM cameras").fetchone()[0] == 1
    assemble_camera_priors(private, independent, features, mapping)
    validate_camera_priors(private, independent, mapping)
    with closing(sqlite3.connect(private)) as db:
        assert db.execute("SELECT count(*) FROM cameras").fetchone()[0] == 3
    with pytest.raises(ValidationError, match="Shared camera group"):
        CameraPriorSet(
            cameras=(
                shared.cameras[0],
                shared.cameras[1].model_copy(update={"parameters": (123.0, 8.0, 6.0, 0.0)}),
                shared.cameras[2],
            )
        )


def test_estimated_camera_output_is_validated_and_native_ids_are_excluded(tmp_path, published):
    features, pairs, matches, mapping, _raw, geometry = published
    private = tmp_path / "estimated.db"
    shutil.copyfile(geometry / "matches.db", private)
    camera = features.views[0]

    def blob(native, focal=20.0):
        return struct.pack(
            "<IiQQBQ4d",
            native,
            2,
            camera.width,
            camera.height,
            0,
            4,
            focal,
            camera.width / 2,
            camera.height / 2,
            0.0,
        )

    with closing(sqlite3.connect(private)) as db, db:
        db.execute("ALTER TABLE two_view_geometries ADD COLUMN camera1 BLOB")
        db.execute("ALTER TABLE two_view_geometries ADD COLUMN camera2 BLOB")
        db.execute("UPDATE two_view_geometries SET camera1=? WHERE rows>0", (blob(1),))
    from splatforge.adapters.colmap_capabilities import inspect_colmap_database

    mapping = mapping.model_copy(update={"tables": inspect_colmap_database(private)[2]})
    first = inspect_verified_geometry(
        private, features, pairs, mapping, matches, VerificationSettings(), maximum_bytes=10**8
    )
    assert first[0].estimated_left_camera is not None
    with closing(sqlite3.connect(private)) as db, db:
        db.execute("UPDATE two_view_geometries SET camera1=? WHERE rows>0", (blob(999),))
    assert (
        inspect_verified_geometry(
            private, features, pairs, mapping, matches, VerificationSettings(), maximum_bytes=10**8
        )
        == first
    )
    with closing(sqlite3.connect(private)) as db, db:
        db.execute("UPDATE two_view_geometries SET camera1=? WHERE rows>0", (blob(999, 22.0),))
    assert (
        inspect_verified_geometry(
            private, features, pairs, mapping, matches, VerificationSettings(), maximum_bytes=10**8
        )
        != first
    )
    with closing(sqlite3.connect(private)) as db, db:
        db.execute("UPDATE two_view_geometries SET camera1=X'00' WHERE rows>0")
    with pytest.raises(ValueError, match="estimated-camera"):
        inspect_verified_geometry(
            private, features, pairs, mapping, matches, VerificationSettings(), maximum_bytes=10**8
        )


def test_native_zero_features_accept_null_or_empty_blob_only(tmp_path, published):
    from splatforge.adapters.feature_database import inspect_feature_database

    features, _pairs, _matches, mapping, raw, _geometry = published
    private = tmp_path / "empty-features.db"
    shutil.copyfile(raw / "matches.db", private)
    image = mapping.images[0].image_id

    def inspect():
        return inspect_feature_database(
            private,
            features.views,
            features.settings,
            expected_schema=(mapping.user_version, mapping.application_id, mapping.tables),
            allow_processing_state=True,
        )[0]

    results = []
    for data in (None, b""):
        with closing(sqlite3.connect(private)) as db, db:
            for table in ("keypoints", "descriptors"):
                db.execute(
                    f"UPDATE {table} SET rows=0,data=? WHERE image_id=?", (data, image)
                )
        results.append(inspect())
    assert results[0] == results[1] and results[0][0].feature_count == 0
    with closing(sqlite3.connect(private)) as db, db:
        db.execute("UPDATE descriptors SET rows=1,data=NULL WHERE image_id=?", (image,))
    with pytest.raises(ValueError, match="Invalid feature"):
        inspect()


def test_native_correspondence_cap_is_a_resource_failure(published):
    from splatforge.application.features_contracts import FeatureResourceError

    features, pairs, _matches, mapping, raw, _geometry = published
    with pytest.raises(FeatureResourceError, match="per-pair limit"):
        inspect_raw_matches(
            raw / "matches.db", features, pairs, mapping, maximum_matches=8, maximum_bytes=10**8
        )
