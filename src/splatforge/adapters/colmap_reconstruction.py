"""Bounded sparse binary reader. Native IDs/rig transport never become public IDs."""

from __future__ import annotations

import math
import shutil
import sqlite3
import struct
import tempfile
from collections.abc import Callable, Iterator
from contextlib import closing, contextmanager
from pathlib import Path
from typing import BinaryIO
from uuid import UUID

from splatforge.adapters.artifact_validation import _read_bounded
from splatforge.adapters.feature_database import NativeFeaturePayload
from splatforge.application.features_contracts import FeatureResourceError
from splatforge.core.features import MAX_FEATURES_PER_VIEW
from splatforge.core.reconstruction import (
    ReconstructionCamera,
    ReconstructionComponent,
    ReconstructionPose,
    ReconstructionSet,
    RegisteredView,
    component_semantic_digest,
    membership_id,
)
from splatforge.core.views import MAX_VIEWS

MODELS = {
    0: ("SIMPLE_PINHOLE", 3),
    1: ("PINHOLE", 4),
    2: ("SIMPLE_RADIAL", 4),
    3: ("RADIAL", 5),
    4: ("OPENCV", 8),
    6: ("FULL_OPENCV", 12),
}
NATIVE_FILES = {"cameras.bin", "images.bin", "points3D.bin"}


class Binary:
    def __init__(self, stream: BinaryIO) -> None:
        self.stream = stream

    def read(self, fmt: str) -> tuple:
        parser = struct.Struct("<" + fmt)
        data = self.stream.read(parser.size)
        if len(data) != parser.size:
            raise ValueError("mapping.malformed_output: truncated sparse binary")
        return parser.unpack(data)

    def count(self, bound: int) -> int:
        (n,) = self.read("Q")
        if n > bound:
            raise ValueError("mapping.malformed_output: sparse record bound exceeded")
        return n

    def name(self) -> str:
        data = bytearray()
        for _ in range(256):
            value = self.stream.read(1)
            if value == b"\0":
                return data.decode("utf-8")
            if not value:
                break
            data.extend(value)
        raise ValueError("mapping.malformed_output: invalid native image name")


@contextmanager
def binary(path: Path) -> Iterator[Binary]:
    if (
        not path.is_file()
        or path.is_symlink()
        or path.is_junction()
        or path.stat().st_nlink != 1
        or path.stat().st_size > 1024**4
    ):
        raise ValueError("mapping.malformed_output: unsafe native payload")
    with path.open("rb") as stream:
        yield Binary(stream)
        if stream.read(1):
            raise ValueError("mapping.malformed_output: trailing sparse bytes")


def read_component(
    directory: Path,
    mapping: NativeFeaturePayload,
    *,
    maximum_validation_bytes: int | None = None,
    checkpoint: Callable[[], None] | None = None,
) -> tuple[ReconstructionComponent, tuple[ReconstructionCamera, ...], tuple[RegisteredView, ...]]:
    if directory.is_symlink() or directory.is_junction() or not directory.name.isascii():
        raise ValueError("mapping.malformed_output: redirected model directory")
    files = {p.name for p in directory.iterdir()}
    if files not in (NATIVE_FILES, NATIVE_FILES | {"rigs.bin", "frames.bin"}):
        raise ValueError("mapping.malformed_output: incomplete/unexpected sparse model files")
    validation_bytes = 4 * sum((directory / name).stat().st_size for name in files) + 1024**2
    if maximum_validation_bytes is not None and validation_bytes > maximum_validation_bytes:
        raise FeatureResourceError(
            "mapping.resource_failure: sparse validation disk budget exceeded"
        )
    if shutil.disk_usage(tempfile.gettempdir()).free < validation_bytes:
        raise FeatureResourceError("mapping.resource_failure: insufficient validation scratch disk")
    native_cameras, native_views, observations = {}, {}, {}
    expected = {item.image_id: item for item in mapping.images}
    with binary(directory / "cameras.bin") as source:
        for _ in range(source.count(MAX_VIEWS)):
            native, model, w, h = source.read("IiQQ")
            if native in native_cameras or model not in MODELS:
                raise ValueError("mapping.invalid_camera: duplicate/unsupported native camera")
            name, count = MODELS[model]
            native_cameras[native] = ReconstructionCamera(
                camera_id=UUID(int=0),
                model=name,
                width=w,
                height=h,
                parameters=source.read(f"{count}d"),
            )
    # A disk-backed observation index bounds memory independently of point/track volume.
    # It validates both directions and uniqueness without loading numerical arrays.
    with (
        tempfile.TemporaryDirectory(prefix="splatforge-sparse-") as temporary,
        closing(sqlite3.connect(Path(temporary) / "validation.sqlite")) as db,
    ):
        steps = 0

        def validation_checkpoint() -> None:
            nonlocal steps
            steps += 1
            if steps % 1024:
                return
            if checkpoint:
                checkpoint()
            size = (
                db.execute("PRAGMA page_count").fetchone()[0]
                * db.execute("PRAGMA page_size").fetchone()[0]
            )
            if size > validation_bytes:
                raise FeatureResourceError(
                    "mapping.resource_failure: validation index growth exceeded"
                )
            if shutil.disk_usage(temporary).free < max(0, validation_bytes - size):
                raise FeatureResourceError(
                    "mapping.resource_failure: validation scratch disk exhausted"
                )

        if checkpoint:
            checkpoint()
        db.execute("PRAGMA cache_size=-2048")
        db.execute(
            "CREATE TABLE observations (image INTEGER, idx INTEGER, point BLOB, "
            "seen INTEGER DEFAULT 0, PRIMARY KEY(image,idx)) WITHOUT ROWID"
        )
        db.execute("CREATE TABLE points (id BLOB PRIMARY KEY) WITHOUT ROWID")
        with binary(directory / "images.bin") as source:
            for _ in range(source.count(MAX_VIEWS)):
                (native,) = source.read("I")
                q, t = source.read("4d"), source.read("3d")
                (camera,) = source.read("I")
                name = source.name()
                if native not in expected or name != expected[native].image_name:
                    raise ValueError("mapping.universe_violation: unknown registered image")
                if native in native_views or camera not in native_cameras:
                    raise ValueError("mapping.malformed_output: duplicate image/missing camera")
                pose = ReconstructionPose(quaternion_wxyz=q, translation=t)
                native_views[native] = (expected[native].view_id, camera, pose)
                count = source.count(MAX_FEATURES_PER_VIEW)
                observations[native] = count
                for index in range(count):
                    validation_checkpoint()
                    x, y, point = source.read("ddQ")
                    if not math.isfinite(x) or not math.isfinite(y):
                        raise ValueError("mapping.malformed_output: non-finite observation")
                    if point != 2**64 - 1:
                        db.execute(
                            "INSERT INTO observations(image,idx,point) VALUES (?,?,?)",
                            (native, index, struct.pack("<Q", point)),
                        )
        with binary(directory / "points3D.bin") as source:
            point_count = source.count((directory / "points3D.bin").stat().st_size // 51)
            for _ in range(point_count):
                validation_checkpoint()
                (point,) = source.read("Q")
                xyz, _rgb, error = source.read("3d"), source.read("3B"), source.read("d")[0]
                if (
                    not all(math.isfinite(v) for v in xyz)
                    or not math.isfinite(error)
                    or error < 0
                    or point == 2**64 - 1
                ):
                    raise ValueError("mapping.malformed_output: invalid sparse point")
                key = struct.pack("<Q", point)
                try:
                    db.execute("INSERT INTO points VALUES (?)", (key,))
                except sqlite3.IntegrityError as exc:
                    raise ValueError("mapping.malformed_output: duplicate point ID") from exc
                for _ in range(source.count(MAX_VIEWS)):
                    validation_checkpoint()
                    image, index = source.read("II")
                    if image not in observations or index >= observations[image]:
                        raise ValueError("mapping.malformed_output: invalid track endpoint")
                    changed = db.execute(
                        "UPDATE observations SET seen=1 WHERE image=? AND idx=? "
                        "AND point=? AND seen=0",
                        (image, index, key),
                    ).rowcount
                    if changed != 1:
                        raise ValueError("mapping.malformed_output: inconsistent/duplicate track")
        # Always check the final partial batch too.
        steps = 1023
        validation_checkpoint()
        if db.execute("SELECT 1 FROM observations WHERE seen=0 LIMIT 1").fetchone():
            raise ValueError("mapping.malformed_output: dangling point observation")
    if len(native_views) < 3:
        raise ValueError(
            "mapping.malformed_output: component has fewer than three registered views"
        )
    if "rigs.bin" in files:
        _validate_frames(directory, native_cameras, native_views)
    groups = {}
    for view, camera, _pose in native_views.values():
        groups.setdefault(camera, []).append(view)
    if set(groups) != set(native_cameras):
        raise ValueError("mapping.malformed_output: unused native camera")
    ids = {native: membership_id(members, "camera") for native, members in groups.items()}
    cameras = tuple(
        sorted(
            (c.model_copy(update={"camera_id": ids[n]}) for n, c in native_cameras.items()),
            key=lambda c: c.camera_id.int,
        )
    )
    views = tuple(
        sorted(
            (
                RegisteredView(view_id=v, camera_id=ids[c], pose=p)
                for v, c, p in native_views.values()
            ),
            key=lambda v: v.view_id.int,
        )
    )
    members = tuple(v.view_id for v in views)
    component = ReconstructionComponent(
        component_id=membership_id(members),
        semantic_digest=component_semantic_digest(cameras, views, point_count=point_count),
        registered_view_ids=members,
        registered_view_count=len(members),
        camera_count=len(cameras),
        point_count=point_count,
        native_payload=f"sparse/{directory.name}",
        native_model_id=directory.name,
    )
    return component, cameras, views


def _validate_frames(directory, cameras, views):
    # M7b publishes only independent single-sensor rigs and one frame per view.
    # Reject a new/nontrivial relation rather than silently dropping its semantics.
    rigs, frames, covered = {}, set(), set()
    with binary(directory / "rigs.bin") as source:
        for _ in range(source.count(MAX_VIEWS)):
            rig, count = source.read("II")
            if count != 1 or rig in rigs:
                raise ValueError("mapping.malformed_output: unsupported nontrivial rig")
            sensor_type, sensor = source.read("iI")
            if sensor_type != 0 or sensor not in cameras:
                raise ValueError("mapping.malformed_output: invalid rig reference sensor")
            rigs[rig] = sensor
    with binary(directory / "frames.bin") as source:
        for _ in range(source.count(MAX_VIEWS)):
            frame, rig = source.read("II")
            pose = ReconstructionPose(
                quaternion_wxyz=source.read("4d"), translation=source.read("3d")
            )
            (count,) = source.read("I")
            if frame in frames or rig not in rigs or count != 1:
                raise ValueError("mapping.malformed_output: invalid independent frame")
            frames.add(frame)
            sensor_type, sensor, image = source.read("iIQ")
            if (
                sensor_type != 0
                or sensor != rigs[rig]
                or image not in views
                or views[image][1] != sensor
                or image in covered
            ):
                raise ValueError("mapping.malformed_output: invalid frame/image association")
            original = views[image][2]
            if (
                max(abs(a - b) for a, b in zip(original.translation, pose.translation, strict=True))
                > 1e-8
                or max(
                    abs(a - b)
                    for a, b in zip(original.rotation_matrix(), pose.rotation_matrix(), strict=True)
                    for a, b in zip(a, b, strict=True)
                )
                > 1e-8
            ):
                raise ValueError("mapping.invalid_pose: image/frame poses disagree")
            covered.add(image)
    if covered != set(views):
        raise ValueError("mapping.malformed_output: registered frame mapping incomplete")


def read_components(
    output: Path,
    mapping: NativeFeaturePayload,
    *,
    maximum_validation_bytes: int | None = None,
    checkpoint: Callable[[], None] | None = None,
) -> tuple[ReconstructionComponent, ...]:
    sparse = output / "sparse"
    if not sparse.is_dir() or sparse.is_symlink() or sparse.is_junction():
        raise ValueError("mapping.zero_components: no sparse output")
    components = []
    for directory in sparse.iterdir():
        if directory.name == "project.ini":
            if not directory.is_file() or directory.stat().st_size > 1024**2:
                raise ValueError("mapping.malformed_output: invalid native settings provenance")
            continue
        if not directory.is_dir() or not directory.name.isascii() or not directory.name.isdecimal():
            raise ValueError("mapping.malformed_output: unexpected model entry")
        components.append(
            read_component(
                directory,
                mapping,
                maximum_validation_bytes=maximum_validation_bytes,
                checkpoint=checkpoint,
            )[0]
        )
    if not components:
        raise ValueError("mapping.zero_components: mapper returned no reconstruction components")
    members = [v for c in components for v in c.registered_view_ids]
    if len(members) != len(set(members)):
        raise ValueError("mapping.universe_violation: Global components overlap")
    return tuple(sorted(components, key=lambda c: c.component_id.int))


class ColmapReconstructionReader:
    def __init__(self, directory: Path, reconstruction: ReconstructionSet) -> None:
        self._directory, self._set = directory, reconstruction
        self._mapping = NativeFeaturePayload.model_validate_json(
            _read_bounded(directory / "backend_mapping.json", 32 * 1024**2, "Native mapping")
        )

    def components(self) -> Iterator[ReconstructionComponent]:
        return iter(self._set.components)

    def _read(self, component_id):
        component = next((c for c in self._set.components if c.component_id == component_id), None)
        if component is None:
            raise ValueError("Unknown reconstruction component UUID")
        parsed = read_component(self._directory / component.native_payload, self._mapping)
        if parsed[0] != component:
            raise ValueError("mapping.malformed_output: reader metadata mismatch")
        return parsed

    def cameras(self, component_id: UUID) -> Iterator[ReconstructionCamera]:
        return iter(self._read(component_id)[1])

    def registered_views(self, component_id: UUID) -> Iterator[RegisteredView]:
        return iter(self._read(component_id)[2])

    def unregistered_views(self) -> Iterator[UUID]:
        return iter(self._set.unregistered_view_ids)

    def points(self, component_id: UUID) -> Iterator[object]:
        raise ValueError(
            "Reconstruction points unavailable: not_published in portable semantics v1"
        )

    def tracks(self, component_id: UUID) -> Iterator[object]:
        raise ValueError(
            "Reconstruction tracks unavailable: not_published in portable semantics v1"
        )
