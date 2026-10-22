"""Bounded COLMAP raw/verified readers; immutable input databases are read-only."""

from __future__ import annotations

import hashlib
import math
import sqlite3
import struct
import time
from contextlib import closing
from pathlib import Path
from uuid import UUID

from splatforge.adapters.feature_database import NativeFeaturePayload, inspect_feature_database
from splatforge.application.features_contracts import FeatureResourceError
from splatforge.core.features import LocalFeatureSet
from splatforge.core.geometry import (
    CameraPriorSet,
    GeometryPairState,
    GeometryPairSummary,
    VerificationSettings,
    ViewCameraPrior,
)
from splatforge.core.matching import MAX_MATCHES_PER_PAIR, MatchSet, RawPairSummary
from splatforge.core.pairs import PairRecord, PairSet

PAIR_BASE = 2**31 - 1
CAMERA_MODELS = {
    "SIMPLE_PINHOLE": 0,
    "PINHOLE": 1,
    "SIMPLE_RADIAL": 2,
    "RADIAL": 3,
    "OPENCV": 4,
    "FULL_OPENCV": 6,
}


def pair_id(left: int, right: int) -> int:
    if not 0 < left < PAIR_BASE or not 0 < right < PAIR_BASE or left == right:
        raise ValueError("Invalid native pair endpoints")
    return min(left, right) * PAIR_BASE + max(left, right)


def decode_pair(value: int) -> tuple[int, int]:
    if type(value) is not int or value <= 0:
        raise ValueError("Invalid native pair ID")
    left, right = divmod(value, PAIR_BASE)
    if not 0 < left < right < PAIR_BASE:
        raise ValueError("Invalid native pair ID encoding")
    return left, right


def readonly_database(path: Path) -> sqlite3.Connection:
    if not path.is_file() or path.is_symlink() or path.is_junction():
        raise ValueError("Unsafe native database payload")
    db = sqlite3.connect(path.resolve().as_uri() + "?mode=ro&immutable=1", uri=True)
    db.execute("PRAGMA query_only=ON")
    db.execute("PRAGMA trusted_schema=OFF")
    deadline = time.monotonic() + 300
    db.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
    return db


def validate_feature_rows(
    path: Path,
    features: LocalFeatureSet,
    mapping: NativeFeaturePayload,
    *,
    maximum_bytes: int,
) -> None:
    summaries, observed = inspect_feature_database(
        path,
        features.views,
        features.settings,
        maximum_bytes=maximum_bytes,
        expected_schema=(mapping.user_version, mapping.application_id, mapping.tables),
        allow_processing_state=True,
    )
    if summaries != features.views or observed != mapping:
        raise ValueError("Matching database changed upstream feature content or native mapping")


def requested_native_pairs(pairs: PairSet, mapping: NativeFeaturePayload) -> dict[int, PairRecord]:
    images = {v.view_id: v.image_id for v in mapping.images}
    if set(images) != {v.view_id for v in pairs.universe.views}:
        raise ValueError("PairSet/native feature view universes differ")
    return {pair_id(images[p.left_view_id], images[p.right_view_id]): p for p in pairs.pairs}


def _correspondences(
    db: sqlite3.Connection,
    table: str,
    native_pair: int,
    counts: dict[int, int],
    *,
    reverse: bool,
    limit: int,
) -> tuple[tuple[int, int], ...]:
    row = db.execute(
        f"SELECT rows, cols, length(data), typeof(data) FROM {table} WHERE pair_id=?",
        (native_pair,),
    ).fetchone()
    if row is None:
        raise ValueError(f"Missing processed pair in {table}")
    rows, cols, size, scalar = row
    if type(rows) is int and rows > min(limit, MAX_MATCHES_PER_PAIR):
        raise FeatureResourceError("Native correspondence output exceeds its frozen per-pair limit")
    if (
        type(rows) is not int
        or not 0 <= rows <= min(limit, MAX_MATCHES_PER_PAIR)
        or type(cols) is not int
        or cols != 2
        or (rows > 0 and (scalar != "blob" or size != rows * 8))
        or (rows == 0 and (scalar not in {"null", "blob"} or size not in (None, 0)))
    ):
        raise ValueError("Malformed native uint32 match matrix shape/dtype/size")
    left, right = decode_pair(native_pair)
    if left not in counts or right not in counts:
        raise ValueError("Match pair has unknown endpoint")
    values = []
    if rows:
        with db.blobopen(table, "data", native_pair, readonly=True) as blob:
            while chunk := blob.read(64 * 1024):
                for a, b in struct.iter_unpack("<II", chunk):
                    if a >= counts[left] or b >= counts[right]:
                        raise ValueError("Match feature index out of range")
                    values.append((b, a) if reverse else (a, b))
    values.sort()
    if any(a == b for a, b in zip(values, values[1:], strict=False)):
        raise ValueError("Duplicate correspondences are invalid (canonical policy v1)")
    return tuple(values)


def correspondences_digest(values: tuple[tuple[int, int], ...]) -> str:
    digest = hashlib.sha256()
    for a, b in values:
        digest.update(struct.pack("<II", a, b))
    return digest.hexdigest()


def inspect_raw_matches(
    path: Path,
    features: LocalFeatureSet,
    pairs: PairSet,
    mapping: NativeFeaturePayload,
    *,
    maximum_matches: int,
    maximum_bytes: int,
    allow_geometry: bool = False,
) -> tuple[RawPairSummary, ...]:
    validate_feature_rows(path, features, mapping, maximum_bytes=maximum_bytes)
    requested = requested_native_pairs(pairs, mapping)
    image_ids = {i.view_id: i.image_id for i in mapping.images}
    counts = {image_ids[v.view_id]: v.feature_count for v in features.views}
    summaries = []
    with closing(readonly_database(path)) as db:
        found = {r[0] for r in db.execute("SELECT pair_id FROM matches")}
        if found != set(requested):
            raise ValueError("PairSet violation: missing processed or unexpected raw pair")
        if (
            not allow_geometry
            and db.execute("SELECT 1 FROM two_view_geometries LIMIT 1").fetchone()
        ):
            raise ValueError("Raw matching contains stale or unexpected two-view geometry")
        for pair in pairs.pairs:
            left, right = image_ids[pair.left_view_id], image_ids[pair.right_view_id]
            values = _correspondences(
                db,
                "matches",
                pair_id(left, right),
                counts,
                reverse=left > right,
                limit=maximum_matches,
            )
            summaries.append(
                RawPairSummary(
                    left_view_id=pair.left_view_id,
                    right_view_id=pair.right_view_id,
                    raw_match_count=len(values),
                    correspondences_digest=correspondences_digest(values),
                )
            )
    return tuple(summaries)


def assemble_camera_priors(
    path: Path,
    priors: CameraPriorSet,
    features: LocalFeatureSet,
    mapping: NativeFeaturePayload,
) -> None:
    expected = {v.view_id: (v.width, v.height) for v in features.views}
    if {v.view_id: (v.width, v.height) for v in priors.cameras} != expected:
        raise ValueError("Camera prior views/dimensions differ from LocalFeatureSet")
    with closing(sqlite3.connect(path)) as db, db:
        names = {r[0] for r in db.execute("SELECT name FROM sqlite_schema WHERE type='table'")}
        transport = {"rigs", "rig_sensors", "frames", "frame_data"}
        if names & transport and not transport <= names:
            raise ValueError("Incomplete native rig/frame transport schema")
        if "pose_priors" in names and db.execute("SELECT 1 FROM pose_priors LIMIT 1").fetchone():
            raise ValueError("Undeclared native pose priors are not supported by M7b")
        if transport <= names:
            if (
                db.execute("SELECT 1 FROM rig_sensors LIMIT 1").fetchone()
                or db.execute(
                    "SELECT frame_id FROM frame_data GROUP BY frame_id HAVING count(*)>1 LIMIT 1"
                ).fetchone()
            ):
                raise ValueError("Nontrivial native rigs require a separate supported camera route")
            for table in ("frame_data", "frames", "rig_sensors", "rigs"):
                db.execute(f"DELETE FROM {table}")
        # This transaction touches only an owned downstream copy. Rebuild current
        # cameras/sharing instead of inheriting provisional extraction camera IDs.
        # The connection starts with foreign_keys off; verify the committed graph
        # before handing it to the native process.
        db.execute("DELETE FROM cameras")
        groups = {}
        camera_for_view = {}
        for camera in priors.cameras:
            key = camera.sharing_key()
            if key not in groups:
                groups[key] = len(groups) + 1
                native = groups[key]
                db.execute(
                    "INSERT INTO cameras (camera_id,model,width,height,params,prior_focal_length) "
                    "VALUES (?,?,?,?,?,?)",
                    (
                        native,
                        CAMERA_MODELS[camera.model],
                        camera.width,
                        camera.height,
                        struct.pack(f"<{len(camera.parameters)}d", *camera.parameters),
                        int(camera.prior_focal_length),
                    ),
                )
                if transport <= names:
                    db.execute(
                        "INSERT INTO rigs (rig_id,ref_sensor_id,ref_sensor_type) VALUES (?,?,0)",
                        (native, native),
                    )
            camera_for_view[camera.view_id] = groups[key]
        for frame, item in enumerate(mapping.images, 1):
            camera = camera_for_view[item.view_id]
            db.execute(
                "UPDATE images SET camera_id=? WHERE image_id=?",
                (camera, item.image_id),
            )
            if transport <= names:
                db.execute("INSERT INTO frames (frame_id,rig_id) VALUES (?,?)", (frame, camera))
                db.execute(
                    "INSERT INTO frame_data (frame_id,data_id,sensor_id,sensor_type) "
                    "VALUES (?,?,?,0)",
                    (frame, item.image_id, camera),
                )
        if db.execute("PRAGMA foreign_key_check").fetchone():
            raise ValueError("Current camera assembly has inconsistent native references")


def validate_camera_priors(
    path: Path, priors: CameraPriorSet, mapping: NativeFeaturePayload
) -> None:
    images = {i.view_id: i.image_id for i in mapping.images}
    with closing(readonly_database(path)) as db:
        actual_groups = {}
        expected_groups = {}
        for camera in priors.cameras:
            row = db.execute(
                "SELECT c.model,c.width,c.height,c.params,c.prior_focal_length FROM cameras c "
                "JOIN images i ON i.camera_id=c.camera_id WHERE i.image_id=?",
                (images[camera.view_id],),
            ).fetchone()
            if row != (
                CAMERA_MODELS[camera.model],
                camera.width,
                camera.height,
                struct.pack(f"<{len(camera.parameters)}d", *camera.parameters),
                int(camera.prior_focal_length),
            ):
                raise ValueError("Verification camera priors changed during processing")
            native = db.execute(
                "SELECT camera_id FROM images WHERE image_id=?", (images[camera.view_id],)
            ).fetchone()[0]
            actual_groups.setdefault(native, set()).add(camera.view_id)
            expected_groups.setdefault(camera.sharing_key(), set()).add(camera.view_id)
        if {frozenset(g) for g in actual_groups.values()} != {
            frozenset(g) for g in expected_groups.values()
        }:
            raise ValueError("Verification camera sharing differs from current camera assumptions")
        if db.execute("PRAGMA foreign_key_check").fetchone():
            raise ValueError("Verification native camera/frame references are inconsistent")
        _validate_camera_transport(db, set(images.values()), len(actual_groups))


def _validate_camera_transport(db: sqlite3.Connection, image_ids: set[int], groups: int) -> None:
    if db.execute("SELECT count(*) FROM cameras").fetchone()[0] != groups:
        raise ValueError("Unexpected unused verification camera records")
    names = {r[0] for r in db.execute("SELECT name FROM sqlite_schema WHERE type='table'")}
    transport = {"rigs", "rig_sensors", "frames", "frame_data"}
    if not names & transport:
        return
    if not transport <= names:
        raise ValueError("Incomplete camera transport schema")
    if (
        db.execute("SELECT count(*) FROM rigs").fetchone()[0] != groups
        or db.execute("SELECT count(*) FROM frames").fetchone()[0] != len(image_ids)
        or db.execute("SELECT count(*) FROM frame_data").fetchone()[0] != len(image_ids)
        or db.execute("SELECT 1 FROM rig_sensors LIMIT 1").fetchone()
    ):
        raise ValueError("Verification camera/frame transport cardinality changed")
    rows = db.execute(
        "SELECT d.frame_id,d.data_id,d.sensor_id,d.sensor_type,r.ref_sensor_id,r.ref_sensor_type,"
        "i.camera_id FROM frame_data d JOIN frames f ON f.frame_id=d.frame_id "
        "JOIN rigs r ON r.rig_id=f.rig_id JOIN images i ON i.image_id=d.data_id"
    ).fetchmany(len(image_ids) + 1)
    if (
        len(rows) != len(image_ids)
        or {r[1] for r in rows} != image_ids
        or len({r[0] for r in rows}) != len(image_ids)
        or any(r[2] != r[4] or r[2] != r[6] or r[3] != 0 or r[5] != 0 for r in rows)
    ):
        raise ValueError("Verification camera/frame transport associations changed")


def _numeric_blob(data: bytes | None, count: int) -> tuple[float, ...] | None:
    if data is None:
        return None
    if type(data) is not bytes or len(data) != count * 8:
        raise ValueError("Malformed geometry matrix/pose layout")
    values = struct.unpack(f"<{count}d", data)
    if not all(math.isfinite(v) for v in values):
        raise ValueError("Non-finite geometry matrix/pose")
    return values


def _estimated_camera(
    data: bytes | None, view_id: UUID, dimensions: tuple[int, int]
) -> ViewCameraPrior | None:
    if data is None:
        return None
    header = struct.Struct("<IiQQBQ")
    if type(data) is not bytes or not header.size <= len(data) <= header.size + 12 * 8:
        raise ValueError("Malformed estimated-camera blob")
    _native_id, model_id, width, height, prior, count = header.unpack_from(data)
    models = {value: key for key, value in CAMERA_MODELS.items()}
    if (
        model_id not in models
        or (width, height) != dimensions
        or prior not in (0, 1)
        or count > 12
        or len(data) != header.size + count * 8
    ):
        raise ValueError("Invalid estimated-camera model/dimensions/parameter layout")
    return ViewCameraPrior(
        view_id=view_id,
        model=models[model_id],
        width=width,
        height=height,
        prior_focal_length=bool(prior),
        parameters=struct.unpack_from(f"<{count}d", data, header.size),
    )


def _camera_numeric_bytes(camera: ViewCameraPrior | None) -> bytes:
    if camera is None:
        return b"\x00"
    return (
        b"\x01"
        + struct.pack(
            "<iQQBQ",
            CAMERA_MODELS[camera.model],
            camera.width,
            camera.height,
            int(camera.prior_focal_length),
            len(camera.parameters),
        )
        + struct.pack(f"<{len(camera.parameters)}d", *camera.parameters)
    )


def inspect_verified_geometry(
    path: Path,
    features: LocalFeatureSet,
    pairs: PairSet,
    mapping: NativeFeaturePayload,
    matches: MatchSet,
    settings: VerificationSettings,
    *,
    maximum_bytes: int,
) -> tuple[GeometryPairSummary, ...]:
    raw = inspect_raw_matches(
        path,
        features,
        pairs,
        mapping,
        maximum_matches=matches.settings.max_num_matches,
        maximum_bytes=maximum_bytes,
        allow_geometry=True,
    )
    if raw != matches.pairs:
        raise ValueError("Verification mutated upstream raw correspondences")
    requested = requested_native_pairs(pairs, mapping)
    images = {i.view_id: i.image_id for i in mapping.images}
    counts = {images[v.view_id]: v.feature_count for v in features.views}
    dimensions = {v.view_id: (v.width, v.height) for v in features.views}
    result = []
    with closing(readonly_database(path)) as db:
        columns = {r[1] for r in db.execute("PRAGMA table_info(two_view_geometries)")}
        if not {"qvec", "tvec"} <= columns:
            raise ValueError("Verification requires verified qvec/tvec native schema")
        if bool("camera1" in columns) != bool("camera2" in columns):
            raise ValueError("Incomplete native estimated-camera schema")
        camera_columns = ",camera1,camera2" if "camera1" in columns else ",NULL,NULL"
        ids = {r[0] for r in db.execute("SELECT pair_id FROM two_view_geometries")}
        if not ids <= set(requested):
            raise ValueError("PairSet violation: unexpected verified geometry pair")
        for pair, raw_pair in zip(pairs.pairs, raw, strict=True):
            left, right = images[pair.left_view_id], images[pair.right_view_id]
            native = pair_id(left, right)
            blob_columns = ("F", "E", "H", "qvec", "tvec") + (
                ("camera1", "camera2") if "camera1" in columns else ()
            )
            metadata = db.execute(
                "SELECT "
                + ",".join(f"typeof({name}),length({name})" for name in blob_columns)
                + " FROM two_view_geometries WHERE pair_id=?",
                (native,),
            ).fetchone()
            if metadata is not None:
                for index, name in enumerate(blob_columns):
                    scalar, size = metadata[index * 2 : index * 2 + 2]
                    bound = (
                        129
                        if name.startswith("camera")
                        else {
                            "F": 72,
                            "E": 72,
                            "H": 72,
                            "qvec": 32,
                            "tvec": 24,
                        }[name]
                    )
                    if scalar != "null" and (scalar != "blob" or size > bound):
                        raise ValueError("Unbounded or invalid geometry numeric blob")
            row = db.execute(
                "SELECT config,F,E,H,qvec,tvec"
                + camera_columns
                + " FROM two_view_geometries WHERE pair_id=?",
                (native,),
            ).fetchone()
            n = raw_pair.raw_match_count
            if n and row is None:
                raise ValueError("Verifier did not process an upstream raw-match pair")
            config, f, e, h, q, t, cam1, cam2 = row or (0, None, None, None, None, None, None, None)
            if type(config) is not int or config not in range(10):
                raise ValueError("Invalid geometry configuration")
            values = (
                ()
                if row is None
                else _correspondences(
                    db,
                    "two_view_geometries",
                    native,
                    counts,
                    reverse=left > right,
                    limit=matches.settings.max_num_matches,
                )
            )
            raw_values = _correspondences(
                db,
                "matches",
                native,
                counts,
                reverse=left > right,
                limit=matches.settings.max_num_matches,
            )
            if not set(values) <= set(raw_values):
                raise ValueError("Verified inliers are not upstream raw correspondences")
            matrices = [_numeric_blob(v, 9) for v in (f, e, h)]
            quaternion, translation = _numeric_blob(q, 4), _numeric_blob(t, 3)
            native_left = pair.right_view_id if left > right else pair.left_view_id
            native_right = pair.left_view_id if left > right else pair.right_view_id
            estimated_left = _estimated_camera(cam1, native_left, dimensions[native_left])
            estimated_right = _estimated_camera(cam2, native_right, dimensions[native_right])
            if (quaternion is None) != (translation is None):
                raise ValueError("Relative pose requires both quaternion and translation")
            if quaternion is not None and abs(sum(v * v for v in quaternion) - 1) > 1e-5:
                raise ValueError("Relative pose quaternion is not unit length")
            if config <= 1 and (
                values
                or any(v is not None for v in matrices)
                or quaternion is not None
                or estimated_left is not None
                or estimated_right is not None
            ):
                raise ValueError("Rejected geometry retains stale numerical payload")
            if config == 2 and matrices[1] is None:
                raise ValueError("Calibrated geometry requires E")
            if config == 3 and matrices[0] is None:
                raise ValueError("Uncalibrated geometry requires F")
            if config in (4, 5, 6) and matrices[2] is None:
                raise ValueError("Planar/panoramic/watermark geometry requires H")
            if config == 7 and all(m is None for m in matrices):
                raise ValueError("Watermark configuration requires an estimated geometric model")
            if config == 9 and quaternion is None:
                raise ValueError("Calibrated rig geometry requires relative pose")
            if left > right:
                matrices, quaternion, translation = _invert_geometry(
                    matrices,
                    quaternion,
                    translation,
                )
                estimated_left, estimated_right = estimated_right, estimated_left
            digest = hashlib.sha256()
            digest.update(pair.left_view_id.bytes + pair.right_view_id.bytes)
            digest.update(struct.pack("<I", config))
            digest.update(bytes.fromhex(correspondences_digest(values)))
            for data in (*matrices, quaternion, translation):
                digest.update(
                    b"\x00"
                    if data is None
                    else b"\x01"
                    + struct.pack(
                        f"<{len(data)}d",
                        *data,
                    )
                )
            digest.update(_camera_numeric_bytes(estimated_left))
            digest.update(_camera_numeric_bytes(estimated_right))
            state = (
                GeometryPairState.NO_RAW_MATCHES
                if n == 0
                else GeometryPairState.INSUFFICIENT_RAW_MATCHES
                if n < settings.min_num_inliers
                else GeometryPairState.VERIFIED
                if len(values) >= settings.min_num_inliers and config >= 2
                else GeometryPairState.GEOMETRICALLY_REJECTED
            )
            result.append(
                GeometryPairSummary(
                    left_view_id=pair.left_view_id,
                    right_view_id=pair.right_view_id,
                    state=state,
                    raw_match_count=n,
                    inlier_count=len(values),
                    configuration=config,
                    geometry_digest=digest.hexdigest(),
                    has_f=matrices[0] is not None,
                    has_e=matrices[1] is not None,
                    has_h=matrices[2] is not None,
                    has_relative_pose=quaternion is not None,
                    estimated_left_camera=estimated_left,
                    estimated_right_camera=estimated_right,
                )
            )
    return tuple(result)


def _invert_geometry(matrices, quaternion, translation):
    # Native matrices are row-major (Database::WriteTwoViewGeometry). Canonical
    # UUID endpoint direction must not depend on native image-number ordering.
    f, e, h = matrices

    def transpose(a):
        return tuple(a[c * 3 + r] for r in range(3) for c in range(3))

    if h is not None:
        a, b, c, d, e0, f0, g, h0, i = h
        cof = (
            e0 * i - f0 * h0,
            c * h0 - b * i,
            b * f0 - c * e0,
            f0 * g - d * i,
            a * i - c * g,
            c * d - a * f0,
            d * h0 - e0 * g,
            b * g - a * h0,
            a * e0 - b * d,
        )
        det = a * cof[0] + b * cof[3] + c * cof[6]
        if abs(det) < 1e-15:
            raise ValueError("Singular homography cannot be inverted")
        h = tuple(v / det for v in cof)
    if quaternion is not None:
        # COLMAP persists qvec as w,x,y,z. Inverse pose: R^T, -R^T t.
        w, x, y, z = quaternion
        quaternion = (w, -x, -y, -z)
        rotation = (
            1 - 2 * (y * y + z * z),
            2 * (x * y - z * w),
            2 * (x * z + y * w),
            2 * (x * y + z * w),
            1 - 2 * (x * x + z * z),
            2 * (y * z - x * w),
            2 * (x * z - y * w),
            2 * (y * z + x * w),
            1 - 2 * (x * x + y * y),
        )
        translation = tuple(
            -sum(rotation[k * 3 + j] * translation[k] for k in range(3)) for j in range(3)
        )
    return [transpose(f) if f else None, transpose(e) if e else None, h], quaternion, translation
