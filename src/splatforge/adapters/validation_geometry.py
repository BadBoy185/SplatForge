"""Read-only COLMAP detailed geometry normalization for M9, bounded on disk."""

from __future__ import annotations

import shutil
import sqlite3
import struct
import tempfile
import time
from collections.abc import Callable, Iterator
from contextlib import closing
from pathlib import Path
from uuid import UUID

from splatforge.adapters.artifact_validation import _read_bounded
from splatforge.adapters.colmap_reconstruction import binary, read_component
from splatforge.adapters.feature_database import NativeFeaturePayload
from splatforge.application.features_contracts import FeatureResourceError
from splatforge.core.features import MAX_FEATURES_PER_VIEW
from splatforge.core.geometry import CameraPriorSet
from splatforge.core.reconstruction import ReconstructionSet
from splatforge.core.reconstruction_validation import (
    ValidationComponentInput,
    ValidationObservation,
    ValidationPoint,
    ValidationResourceLimits,
)
from splatforge.core.validation_measurements import point_digest
from splatforge.core.views import MAX_VIEWS


class ColmapValidationSource:
    def __init__(
        self,
        directory: Path,
        reconstruction: ReconstructionSet,
        workspace: Path,
        limits: ValidationResourceLimits,
        checkpoint: Callable[[], None],
    ) -> None:
        self.directory, self.reconstruction, self.workspace = directory, reconstruction, workspace
        self.limits, self.owner_checkpoint = limits, checkpoint
        self.started = time.monotonic()
        self.steps = 0
        self.mapping = NativeFeaturePayload.model_validate_json(
            _read_bounded(directory / "backend_mapping.json", 32 * 1024**2, "Native mapping")
        )
        self.priors = CameraPriorSet.model_validate_json(
            _read_bounded(directory / "input_cameras.json", 64 * 1024**2, "Frozen camera priors")
        )
        self._components: dict[UUID, ValidationComponentInput] = {}
        size = sum(
            p.stat().st_size
            for c in reconstruction.components
            for p in (directory / c.native_payload).iterdir()
        )
        if size > limits.max_native_bytes:
            raise ValueError("validation.resource_limit: maximum native bytes exceeded")
        self.checkpoint(force=True)

    def checkpoint(self, *, force: bool = False) -> None:
        self.steps += 1
        if not force and self.steps % 128:
            return
        self.owner_checkpoint()
        if time.monotonic() - self.started > self.limits.timeout_seconds:
            raise ValueError("validation.resource_limit: scan timeout exceeded")

    def component(self, component_id: UUID) -> ValidationComponentInput:
        if component_id not in self._components:
            component = next(
                c for c in self.reconstruction.components if c.component_id == component_id
            )
            try:
                parsed, cameras, views = read_component(
                    self.directory / component.native_payload,
                    self.mapping,
                    maximum_validation_bytes=self.limits.max_scratch_bytes,
                    checkpoint=lambda: self.checkpoint(force=True),
                )
            except FeatureResourceError as exc:
                raise ValueError(
                    "validation.resource_limit: scratch validation budget: " + str(exc)
                ) from exc
            if parsed != component:
                raise ValueError("validation.corrupt_geometry: M8 component metadata mismatch")
            ids = set(component.registered_view_ids)
            self._components[component_id] = ValidationComponentInput(
                component_id=component_id,
                cameras=cameras,
                views=views,
                priors=tuple(p for p in self.priors.cameras if p.view_id in ids),
                points_available=True,
                tracks_available=True,
            )
        return self._components[component_id]

    def points(self, component_id: UUID) -> Iterator[ValidationPoint]:
        data = self.component(component_id)
        component = next(
            c for c in self.reconstruction.components if c.component_id == component_id
        )
        directory = self.directory / component.native_payload
        mapping = {i.image_id: i.view_id for i in self.mapping.images}
        members = {v.view_id for v in data.views}
        self.workspace.mkdir(parents=True, exist_ok=True)
        with (
            tempfile.TemporaryDirectory(prefix="validation-", dir=self.workspace) as temporary,
            closing(sqlite3.connect(Path(temporary) / "normalized.sqlite")) as db,
        ):
            db.execute("PRAGMA cache_size=-2048")
            db.execute("PRAGMA temp_store=FILE")
            db.execute(f"PRAGMA max_page_count={max(1, self.limits.max_scratch_bytes // 4096)}")
            db.execute(
                "CREATE TABLE observations(image INTEGER, idx INTEGER, point BLOB, "
                "view BLOB, x REAL, y REAL, PRIMARY KEY(image,idx)) WITHOUT ROWID"
            )
            db.execute(
                "CREATE TABLE normalized(digest BLOB, ordinal INTEGER, payload TEXT, "
                "PRIMARY KEY(digest,ordinal)) WITHOUT ROWID"
            )

            def budget():
                self.checkpoint()
                if self.steps % 128:
                    return
                size = sum(p.stat().st_size for p in Path(temporary).iterdir() if p.is_file())
                if (
                    size > self.limits.max_scratch_bytes
                    or shutil.disk_usage(temporary).free < 65536
                ):
                    raise ValueError("validation.resource_limit: scratch disk budget exceeded")

            with binary(directory / "images.bin") as source:
                for _ in range(source.count(MAX_VIEWS)):
                    (image,) = source.read("I")
                    source.read("7dI")
                    source.name()
                    if image not in mapping or mapping[image] not in members:
                        raise ValueError("validation.corrupt_geometry: unknown image")
                    for index in range(source.count(MAX_FEATURES_PER_VIEW)):
                        budget()
                        x, y, point = source.read("ddQ")
                        if point != 2**64 - 1:
                            db.execute(
                                "INSERT INTO observations VALUES (?,?,?,?,?,?)",
                                (
                                    image,
                                    index,
                                    struct.pack("<Q", point),
                                    mapping[image].bytes,
                                    x,
                                    y,
                                ),
                            )
            with binary(directory / "points3D.bin") as source:
                for ordinal in range(
                    source.count((directory / "points3D.bin").stat().st_size // 51)
                ):
                    budget()
                    (point,) = source.read("Q")
                    xyz = source.read("3d")
                    source.read("3Bd")  # Stored error and color are not consumed.
                    track = []
                    for _ in range(source.count(MAX_VIEWS)):
                        budget()
                        image, index = source.read("II")
                        row = db.execute(
                            "SELECT view,x,y,point FROM observations WHERE image=? AND idx=?",
                            (image, index),
                        ).fetchone()
                        if row is None or row[3] != struct.pack("<Q", point):
                            raise ValueError("validation.corrupt_geometry: inconsistent track")
                        track.append(
                            ValidationObservation(
                                view_id=UUID(bytes=row[0]),
                                keypoint_index=index,
                                xy=(row[1], row[2]),
                            )
                        )
                    normalized = ValidationPoint(
                        xyz=xyz,
                        observations=tuple(
                            sorted(track, key=lambda o: (o.view_id.int, o.keypoint_index))
                        ),
                    )
                    db.execute(
                        "INSERT INTO normalized VALUES (?,?,?)",
                        (point_digest(normalized), ordinal, normalized.model_dump_json()),
                    )
            db.commit()
            # Incremental primary-key ordering needs no unbounded external sort.
            # Equal content hashes have identical numerical records; their native
            # insertion tie order cannot affect public geometry/measurements.
            size = sum(p.stat().st_size for p in Path(temporary).iterdir() if p.is_file())
            if size > self.limits.max_scratch_bytes:
                raise ValueError("validation.resource_limit: scratch disk budget exceeded")
            self.checkpoint(force=True)
            for (payload,) in db.execute("SELECT payload FROM normalized ORDER BY digest,ordinal"):
                budget()
                yield ValidationPoint.model_validate_json(payload)
            self.checkpoint(force=True)
