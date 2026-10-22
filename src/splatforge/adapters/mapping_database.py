"""Canonical mapper-consumed SQLite state. No descriptor or raw-match identity."""

from __future__ import annotations

import hashlib
import math
import struct
from contextlib import closing
from pathlib import Path

from splatforge.adapters.feature_database import NativeFeaturePayload
from splatforge.adapters.matching_database import (
    CAMERA_MODELS,
    _camera_numeric_bytes,
    _correspondences,
    _estimated_camera,
    _invert_geometry,
    _numeric_blob,
    _validate_camera_transport,
    correspondences_digest,
    decode_pair,
    readonly_database,
)
from splatforge.core.features import MAX_FEATURES_PER_VIEW, digest_json
from splatforge.core.geometry import CameraPriorSet, ViewCameraPrior
from splatforge.core.reconstruction import MappingInput, numerical_bytes


def camera_state_digest(priors: CameraPriorSet) -> str:
    groups = {}
    for camera in priors.cameras:
        groups.setdefault(camera.sharing_key(), []).append(camera.view_id)
    return digest_json(
        {
            "version": 1,
            "cameras": [
                c.model_dump(mode="json", exclude={"camera_group_id"}) for c in priors.cameras
            ],
            "sharing": [[str(v) for v in groups[c.sharing_key()]] for c in priors.cameras],
        }
    )


def inspect_mapping_input(
    database: Path,
    mapping: NativeFeaturePayload,
    *,
    allowed_pairs: set[int] | None = None,
) -> MappingInput:
    images = {m.image_id: m for m in mapping.images}
    counts, dimensions = {}, {}
    keypoints = hashlib.sha256(b"mapping.xy.v1")
    geometry = hashlib.sha256(b"mapping.geometry.v1")
    cameras, total_inliers, pairs = [], 0, 0
    with closing(readonly_database(database)) as db:
        if db.execute("PRAGMA quick_check").fetchone() != ("ok",):
            raise ValueError("mapping.corrupt_database: SQLite integrity failure")
        actual = dict(db.execute("SELECT image_id,name FROM images"))
        if actual != {m.image_id: m.image_name for m in mapping.images}:
            raise ValueError("mapping.universe_violation: native input image mapping differs")
        model_names = {v: k for k, v in CAMERA_MODELS.items()}
        camera_groups = {}
        for item in mapping.images:
            row = db.execute(
                "SELECT c.camera_id,c.model,c.width,c.height,substr(c.params,1,97),"
                "c.prior_focal_length "
                "FROM cameras c JOIN images i ON i.camera_id=c.camera_id WHERE i.image_id=?",
                (item.image_id,),
            ).fetchone()
            if (
                row is None
                or row[1] not in model_names
                or not isinstance(row[4], bytes)
                or len(row[4]) > 96
            ):
                raise ValueError("mapping.invalid_camera: unsupported camera state")
            native, model, w, h, params, prior = row
            if prior not in (0, 1) or len(params) % 8:
                raise ValueError("mapping.invalid_camera: malformed camera parameters")
            camera_groups.setdefault(native, []).append(item.view_id)
            cameras.append(
                ViewCameraPrior(
                    view_id=item.view_id,
                    camera_group_id=None,
                    model=model_names[model],
                    width=w,
                    height=h,
                    parameters=struct.unpack(f"<{len(params) // 8}d", params),
                    prior_focal_length=bool(prior),
                )
            )
            dimensions[item.view_id] = (w, h)
            shape = db.execute(
                "SELECT rows,cols,length(data) FROM keypoints WHERE image_id=?", (item.image_id,)
            ).fetchone()
            if (
                shape is None
                or type(shape[0]) is not int
                or not 0 <= shape[0] <= MAX_FEATURES_PER_VIEW
                or shape[1] not in (2, 4, 6)
                or shape[2] not in ((None, 0) if shape[0] == 0 else (shape[0] * shape[1] * 4,))
            ):
                raise ValueError("mapping.corrupt_database: invalid keypoint layout")
            n, cols, _ = shape
            counts[item.image_id] = n
            keypoints.update(item.view_id.bytes + struct.pack("<Q", n))
            if n:
                stride = cols * 4
                with db.blobopen("keypoints", "data", item.image_id, readonly=True) as blob:
                    while chunk := blob.read((65536 // stride) * stride):
                        for values in struct.iter_unpack(f"<{cols}f", chunk):
                            x, y = values[:2]
                            if not (
                                math.isfinite(x)
                                and math.isfinite(y)
                                and 0 <= x <= w
                                and 0 <= y <= h
                            ):
                                raise ValueError("mapping.corrupt_database: invalid keypoint")
                            keypoints.update(numerical_bytes((x, y)))
        if {r[0] for r in db.execute("SELECT image_id FROM keypoints")} != set(images):
            raise ValueError("mapping.corrupt_database: keypoint universe differs")
        _validate_camera_transport(db, set(images), len(camera_groups))
        names = {r[0] for r in db.execute("SELECT name FROM sqlite_schema WHERE type='table'")}
        if "pose_priors" in names and db.execute("SELECT 1 FROM pose_priors LIMIT 1").fetchone():
            raise ValueError("mapping.corrupt_database: unsupported undeclared pose priors")
        sharing = {v: members for members in camera_groups.values() for v in members}
        camera_digest = camera_state_digest(
            CameraPriorSet(
                cameras=tuple(
                    camera.model_copy(update={"camera_group_id": sharing[camera.view_id][0]})
                    for camera in cameras
                )
            )
        )
        columns = {r[1] for r in db.execute("PRAGMA table_info(two_view_geometries)")}
        extra = (
            ",substr(camera1,1,130),substr(camera2,1,130)"
            if {"camera1", "camera2"} <= columns
            else ",NULL,NULL"
        )
        canonical = []
        for native, config in db.execute("SELECT pair_id,config FROM two_view_geometries"):
            a, b = decode_pair(native)
            if a not in images or b not in images:
                raise ValueError("mapping.universe_violation: native geometry endpoint")
            if allowed_pairs is not None and native not in allowed_pairs:
                continue
            if type(config) is not int or not 0 <= config <= 9:
                raise ValueError("mapping.corrupt_database: invalid two-view configuration")
            if config >= 2:
                left, right = sorted((images[a].view_id, images[b].view_id), key=lambda v: v.int)
                canonical.append((left.int, right.int, native, config, left, right))
        for _, _, native, config, left, right in sorted(canonical):
            a, b = decode_pair(native)
            reverse = images[a].view_id != left
            matches = _correspondences(
                db, "two_view_geometries", native, counts, reverse=reverse, limit=100000
            )
            row = db.execute(
                "SELECT substr(F,1,73),substr(E,1,73),substr(H,1,73),"
                "substr(qvec,1,33),substr(tvec,1,25)"
                + extra
                + " FROM two_view_geometries WHERE pair_id=?",
                (native,),
            ).fetchone()
            matrices = [_numeric_blob(v, 9) for v in row[:3]]
            q, t = _numeric_blob(row[3], 4), _numeric_blob(row[4], 3)
            if (q is None) != (t is None) or (
                q is not None and abs(sum(v * v for v in q) - 1) > 1e-5
            ):
                raise ValueError("mapping.invalid_pose: invalid two-view relative pose")
            if (
                (config == 2 and matrices[1] is None)
                or (config == 3 and matrices[0] is None)
                or (config in (4, 5, 6) and matrices[2] is None)
                or (config == 9 and q is None)
            ):
                raise ValueError("mapping.corrupt_database: missing two-view numerical model")
            c1 = _estimated_camera(row[5], images[a].view_id, dimensions[images[a].view_id])
            c2 = _estimated_camera(row[6], images[b].view_id, dimensions[images[b].view_id])
            if reverse:
                matrices, q, t = _invert_geometry(matrices, q, t)
                c1, c2 = c2, c1
            geometry.update(left.bytes + right.bytes + struct.pack("<I", config))
            geometry.update(bytes.fromhex(correspondences_digest(matches)))
            for values in (*matrices, q, t):
                geometry.update(b"\0" if values is None else b"\1" + numerical_bytes(values))
            geometry.update(_camera_numeric_bytes(c1) + _camera_numeric_bytes(c2))
            pairs += 1
            total_inliers += len(matches)
    return MappingInput(
        view_ids=tuple(m.view_id for m in mapping.images),
        cameras_digest=camera_digest,
        keypoints_digest=keypoints.hexdigest(),
        geometry_digest=geometry.hexdigest(),
        verified_pair_count=pairs,
        keypoint_count=sum(counts.values()),
        inlier_count=total_inliers,
    )
