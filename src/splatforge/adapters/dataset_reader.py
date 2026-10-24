"""Independent on-disk consumer of the conventional flat COLMAP training layout.

The writer does not supply this reader's cameras, poses, tracks or pixel evidence.
Native record IDs are transport only; disk-backed canonical streams bound memory.
"""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import struct
import tempfile
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from splatforge.adapters.artifact_validation import (
    _read_bounded,
    safe_payload_path,
    stream_sha256,
    validate_decodable_image,
)
from splatforge.adapters.colmap_reconstruction import NATIVE_FILES, binary, read_component
from splatforge.adapters.feature_database import FeatureImageMapping, NativeFeaturePayload
from splatforge.core.dataset import (
    MAX_METADATA_BYTES,
    OUTPUT_MODELS,
    POSE_ABSOLUTE_TOLERANCE,
    DatasetImage,
    PreparedDatasetComponent,
)
from splatforge.core.features import MAX_FEATURES_PER_VIEW, digest_json
from splatforge.core.reconstruction import ReconstructionCamera, RegisteredView
from splatforge.core.validation_measurements import project
from splatforge.core.views import MAX_VIEWS


@dataclass(frozen=True)
class SparseDatasetContent:
    cameras: tuple[ReconstructionCamera, ...]
    views: tuple[RegisteredView, ...]
    point_count: int
    geometry_digest: str
    world_digest: str
    unassociated_count: int = 0
    tracked_geometry_digest: str = "0" * 64


def sparse_content(
    directory: Path,
    names: dict[str, UUID],
    *,
    checkpoint: Callable[[], None] = lambda: None,
    maximum_scratch_bytes: int = 32 * 1024**3,
) -> SparseDatasetContent:
    """Read and validate both track directions, independently of the model writer."""
    mapping = []
    with binary(directory / "images.bin") as source:
        for _ in range(source.count(MAX_VIEWS)):
            checkpoint()
            (native,) = source.read("I")
            source.read("7dI")
            name = source.name()
            if name not in names:
                raise ValueError("dataset.membership_mismatch: unexpected sparse image name")
            mapping.append(
                FeatureImageMapping(view_id=names[name], image_id=native, image_name=name)
            )
            for _ in range(source.count(MAX_FEATURES_PER_VIEW)):
                source.read("ddQ")
    if len({i.view_id for i in mapping}) != len(names) or len(mapping) != len(names):
        raise ValueError("dataset.membership_mismatch: missing/duplicate sparse image")
    native_mapping = NativeFeaturePayload(
        user_version=0,
        application_id=0,
        tables=(),
        images=tuple(sorted(mapping, key=lambda i: i.view_id.int)),
    )
    component, cameras, views = read_component(
        directory,
        native_mapping,
        checkpoint=checkpoint,
        maximum_validation_bytes=maximum_scratch_bytes,
    )
    native_views = {i.image_id: i.view_id for i in mapping}
    with (
        tempfile.TemporaryDirectory(prefix="splatforge-dataset-reader-") as temporary,
        closing(sqlite3.connect(Path(temporary) / "canonical.sqlite")) as db,
    ):
        db.execute("PRAGMA cache_size=-2048")
        db.execute(f"PRAGMA max_page_count={max(1, maximum_scratch_bytes // 4096)}")
        db.execute(
            "CREATE TABLE obs (image INTEGER, idx INTEGER, x REAL, y REAL, "
            "PRIMARY KEY(image,idx)) WITHOUT ROWID"
        )
        db.execute("CREATE TABLE digests (kind INTEGER, digest BLOB)")
        steps = 0
        unassociated = 0

        def guard():
            nonlocal steps
            steps += 1
            if steps % 1024 == 0:
                checkpoint()

        with binary(directory / "images.bin") as source:
            for _ in range(source.count(MAX_VIEWS)):
                (native,) = source.read("I")
                source.read("7dI")
                source.name()
                for index in range(source.count(MAX_FEATURES_PER_VIEW)):
                    guard()
                    x, y, point = source.read("ddQ")
                    if point == 2**64 - 1:
                        unassociated += 1
                        db.execute(
                            "INSERT INTO digests VALUES (2,?)",
                            (bytes.fromhex(digest_json((str(native_views[native]), x, y))),),
                        )
                    else:
                        db.execute("INSERT INTO obs VALUES (?,?,?,?)", (native, index, x, y))
        with binary(directory / "points3D.bin") as source:
            for _ in range(source.count((directory / "points3D.bin").stat().st_size // 51)):
                guard()
                source.read("Q")
                xyz, rgb, error = source.read("3d"), source.read("3B"), source.read("d")[0]
                track = []
                for _ in range(source.count(MAX_VIEWS)):
                    image, index = source.read("II")
                    x, y = db.execute(
                        "SELECT x,y FROM obs WHERE image=? AND idx=?", (image, index)
                    ).fetchone()
                    track.append((str(native_views[image]), x, y))
                track.sort()
                # IDs/indices/order do not enter either canonical content stream.
                world = (xyz, [v[0] for v in track])
                full = (xyz, rgb, error, track)
                for kind, record in ((0, world), (1, full)):
                    db.execute(
                        "INSERT INTO digests VALUES (?,?)",
                        (kind, bytes.fromhex(digest_json(record))),
                    )
        db.execute("CREATE INDEX ordered_digests ON digests(kind,digest)")
        digests = []
        for kind in range(3):
            digest = hashlib.sha256()
            for (value,) in db.execute(
                "SELECT digest FROM digests WHERE kind=? ORDER BY digest", (kind,)
            ):
                guard()
                digest.update(value)
            digests.append(digest.hexdigest())
        checkpoint()
    return SparseDatasetContent(
        cameras,
        views,
        component.point_count,
        digest_json(digests[1:]),
        digests[0],
        unassociated,
        digests[1],
    )


def require_preserved_geometry(
    original: SparseDatasetContent,
    prepared: SparseDatasetContent,
) -> None:
    if (
        original.world_digest != prepared.world_digest
        or original.point_count != prepared.point_count
    ):
        raise ValueError("dataset.changed_world_geometry: XYZ/point track membership changed")
    before = {v.view_id: v.pose for v in original.views}
    if set(before) != {v.view_id for v in prepared.views}:
        raise ValueError("dataset.changed_poses: extrinsic view membership changed")
    for view in prepared.views:
        expected = before[view.view_id]
        a, b = expected.rotation_matrix(), view.pose.rotation_matrix()
        differences = [
            abs(x - y) for ra, rb in zip(a, b, strict=True) for x, y in zip(ra, rb, strict=True)
        ]
        differences.extend(
            abs(x - y) for x, y in zip(expected.translation, view.pose.translation, strict=True)
        )
        if any(not math.isfinite(v) or v > POSE_ABSOLUTE_TOLERANCE for v in differences):
            raise ValueError("dataset.changed_poses: camera_from_world changed beyond 1e-8")


def require_observation_transform(
    original_directory: Path,
    prepared_directory: Path,
    original: SparseDatasetContent,
    prepared: SparseDatasetContent,
    *,
    checkpoint: Callable[[], None] = lambda: None,
    maximum_scratch_bytes: int = 32 * 1024**3,
) -> None:
    """Check every retained track ray by public view and canonical world point.

    Native point IDs and observation indices may be remapped. Unassociated feature
    rows are deliberately not dataset inputs. Duplicate identical world/track keys
    use multiset matching within the explicit source-pixel tolerance.
    """
    old_views = {v.view_id: v for v in original.views}
    new_views = {v.view_id: v for v in prepared.views}
    old_cameras = {c.camera_id: c for c in original.cameras}
    new_cameras = {c.camera_id: c for c in prepared.cameras}
    with (
        tempfile.TemporaryDirectory(prefix="splatforge-dataset-rays-") as temporary,
        closing(sqlite3.connect(Path(temporary) / "observations.sqlite")) as db,
    ):
        db.execute("PRAGMA cache_size=-2048")
        db.execute(f"PRAGMA max_page_count={max(1, maximum_scratch_bytes // 4096)}")
        db.execute(
            "CREATE TABLE obs(side INTEGER, view BLOB, idx INTEGER, x REAL, y REAL, "
            "point BLOB, PRIMARY KEY(side,view,idx)) WITHOUT ROWID"
        )
        db.execute(
            "CREATE TABLE points(side INTEGER, native BLOB, signature BLOB, "
            "PRIMARY KEY(side,native)) WITHOUT ROWID"
        )
        steps = 0

        def guard():
            nonlocal steps
            steps += 1
            if steps % 1024 == 0:
                checkpoint()

        for side, directory in enumerate((original_directory, prepared_directory)):
            native_views = {}
            with binary(directory / "images.bin") as source:
                for _ in range(source.count(MAX_VIEWS)):
                    (image,) = source.read("I")
                    source.read("7dI")
                    view = UUID(source.name().rsplit(".", 1)[0])
                    native_views[image] = view
                    for index in range(source.count(MAX_FEATURES_PER_VIEW)):
                        guard()
                        x, y, point = source.read("ddQ")
                        if point != 2**64 - 1:
                            db.execute(
                                "INSERT INTO obs VALUES (?,?,?,?,?,?)",
                                (side, view.bytes, index, x, y, struct.pack("<Q", point)),
                            )
            with binary(directory / "points3D.bin") as source:
                for _ in range(source.count((directory / "points3D.bin").stat().st_size // 51)):
                    guard()
                    (point,) = source.read("Q")
                    xyz = source.read("3d")
                    source.read("3Bd")
                    members = []
                    for _ in range(source.count(MAX_VIEWS)):
                        image, _index = source.read("II")
                        members.append(str(native_views[image]))
                    signature = bytes.fromhex(digest_json((xyz, sorted(members))))
                    db.execute(
                        "INSERT INTO points VALUES (?,?,?)",
                        (side, struct.pack("<Q", point), signature),
                    )
        db.execute(
            "CREATE TABLE expected(signature BLOB, view BLOB, x REAL, y REAL, "
            "seen INTEGER DEFAULT 0)"
        )
        db.execute(
            "INSERT INTO expected(signature,view,x,y) SELECT p.signature,o.view,o.x,o.y "
            "FROM obs o JOIN points p ON p.native=o.point AND p.side=o.side WHERE o.side=0"
        )
        db.execute("CREATE INDEX lookup ON expected(signature,view,seen)")
        prepared_observations = db.execute(
            "SELECT p.signature,o.view,o.x,o.y FROM obs o JOIN points p "
            "ON p.native=o.point AND p.side=o.side WHERE o.side=1"
        )
        for signature, view_bytes, x, y in prepared_observations:
            guard()
            view = UUID(bytes=view_bytes)
            old_camera = old_cameras[old_views[view].camera_id]
            camera = new_cameras[new_views[view].camera_id]
            p = camera.parameters
            fx, fy = p[0], p[1] if camera.model == "PINHOLE" else p[0]
            cx, cy = p[2:4] if camera.model == "PINHOLE" else p[1:3]
            projected = project(old_camera, ((x - cx) / fx, (y - cy) / fy, 1.0))
            row = (
                None
                if projected is None
                else db.execute(
                    "SELECT rowid FROM expected WHERE signature=? AND view=? AND seen=0 "
                    "AND abs(x-?)<=0.0001 AND abs(y-?)<=0.0001 LIMIT 1",
                    (signature, view_bytes, *projected),
                ).fetchone()
            )
            if row is None:
                raise ValueError(
                    "dataset.invalid_observations: retained track ray differs "
                    "from historical observation by more than 1e-4 pixels"
                )
            db.execute("UPDATE expected SET seen=1 WHERE rowid=?", row)
        if db.execute("SELECT 1 FROM expected WHERE seen=0 LIMIT 1").fetchone():
            raise ValueError("dataset.invalid_observations: tracked observation membership changed")
        checkpoint()


def output_images(
    directory: Path,
    names: dict[str, UUID],
    sparse: SparseDatasetContent,
    checkpoint: Callable[[], None] = lambda: None,
) -> tuple[DatasetImage, ...]:
    images = safe_payload_path(directory, "images")
    if {p.name for p in images.iterdir()} != set(names):
        raise ValueError("dataset.membership_mismatch: exact output images required")
    by_view = {v.view_id: v for v in sparse.views}
    cameras = {c.camera_id: c for c in sparse.cameras}
    result = []
    for name, view in sorted(names.items(), key=lambda item: item[1].int):
        checkpoint()
        path = safe_payload_path(directory, "images/" + name)
        if not path.is_file() or path.stat().st_nlink != 1:
            raise ValueError("dataset.unsafe_pixels: require independent output pixel copies")
        camera = cameras[by_view[view].camera_id]
        validate_decodable_image(
            path,
            width=camera.width,
            height=camera.height,
            image_format="png" if name.endswith(".png") else "jpeg",
        )
        size, sha = stream_sha256(path)
        result.append(
            DatasetImage(
                view_id=view,
                name=name,
                sha256=sha,
                width=camera.width,
                height=camera.height,
                size=size,
            )
        )
    return tuple(result)


def read_dataset(
    directory: Path,
    *,
    checkpoint: Callable[[], None] = lambda: None,
    maximum_scratch_bytes: int = 32 * 1024**3,
) -> PreparedDatasetComponent:
    """A standalone conventional COLMAP dataset consumer, including metadata hashes."""
    if directory.is_symlink() or directory.is_junction():
        raise ValueError("dataset.unsafe_path: redirected component")
    if {p.name for p in directory.iterdir()} not in (
        {"images", "sparse", "dataset.json"},
        {"images", "sparse", "dataset.json", "manifest.json"},
    ):
        raise ValueError("dataset.invalid_layout: require only canonical dataset files")
    metadata_path = safe_payload_path(directory, "dataset.json")
    if not metadata_path.is_file() or metadata_path.stat().st_nlink != 1:
        raise ValueError("dataset.unsafe_metadata: require an independent plain metadata file")
    data = json.loads(_read_bounded(metadata_path, MAX_METADATA_BYTES, "Dataset metadata"))
    derived = {
        name: data.pop(name, None)
        for name in (
            "numerical_semantic_digest",
            "recipe_key",
            "image_count",
            "camera_count",
            "selected_view_ids",
            "output_camera_models",
        )
    }
    metadata = PreparedDatasetComponent.model_validate(data)
    if any(metadata.metadata()[name] != value for name, value in derived.items()):
        raise ValueError("dataset.corrupt_metadata: numerical identity/counts/models differ")
    if {p.name for p in safe_payload_path(directory, "sparse").iterdir()} != {"0"}:
        raise ValueError("dataset.invalid_layout: exactly one independent sparse/0 required")
    sparse = safe_payload_path(directory, "sparse/0")
    if {p.name for p in sparse.iterdir()} != NATIVE_FILES:
        raise ValueError("dataset.invalid_layout: require conventional three binary files")
    names = {i.name: i.view_id for i in metadata.images}
    actual = sparse_content(
        sparse, names, checkpoint=checkpoint, maximum_scratch_bytes=maximum_scratch_bytes
    )
    if any(c.model not in OUTPUT_MODELS for c in actual.cameras):
        raise ValueError("dataset.distorted_output: trainer requires flat undistorted cameras")
    if actual.unassociated_count:
        raise ValueError(
            "dataset.invalid_observations: only registered sparse tracks are published"
        )
    if (
        actual.cameras,
        actual.views,
        actual.point_count,
        actual.geometry_digest,
        actual.world_digest,
    ) != (
        metadata.cameras,
        metadata.views,
        metadata.sparse_point_count,
        metadata.sparse_geometry_digest,
        metadata.preserved_world_points_digest,
    ):
        raise ValueError("dataset.corrupt_geometry: sparse output differs from metadata")
    if output_images(directory, names, actual, checkpoint) != metadata.images:
        raise ValueError("dataset.corrupt_pixels: output image hash/dimensions differ")
    if metadata.settings.max_image_size and any(
        max(i.width, i.height) > metadata.settings.max_image_size for i in metadata.images
    ):
        raise ValueError("dataset.invalid_resolution: output exceeds explicit max_image_size")
    return metadata
