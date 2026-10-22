"""Read-only, bounded COLMAP feature payload validation and streaming identity."""

from __future__ import annotations

import hashlib
import math
import sqlite3
import struct
import time
from contextlib import closing
from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from splatforge.adapters.colmap_capabilities import inspect_colmap_database
from splatforge.core.capabilities import DatabaseTableEvidence
from splatforge.core.features import (
    MAX_FEATURE_DATABASE_BYTES,
    FeatureSettings,
    FeatureViewSummary,
    LocalFeatureSet,
    descriptor_signature,
)
from splatforge.core.views import MAX_VIEWS, FrozenModel, canonical_json_bytes

_NATIVE_TYPES = {"SIFT": 0, "ALIKED_N16ROT": 1, "ALIKED_N32": 2, "LOMA_B": 3, "LOMA_B128": 4}


def seal_feature_database(path: Path) -> None:
    """Checkpoint only the owned attempt database after confirmed native teardown."""
    with closing(sqlite3.connect(path, timeout=5)) as db:
        row = db.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        if row is not None and row[0] != 0:
            raise ValueError("Feature database still has an active WAL owner")
        if db.execute("PRAGMA journal_mode=DELETE").fetchone()[0] != "delete":
            raise ValueError("Feature database could not enter a self-contained publication state")


class FeatureImageMapping(FrozenModel):
    view_id: UUID
    image_id: int = Field(ge=1, lt=2**31 - 1, strict=True)
    image_name: str = Field(max_length=40)

    @model_validator(mode="after")
    def deterministic_name(self) -> FeatureImageMapping:
        if self.image_name not in {f"{self.view_id}.png", f"{self.view_id}.jpg"}:
            raise ValueError("Backend image name must derive from SplatForge view identity")
        return self


class NativeFeaturePayload(FrozenModel):
    payload_version: Literal[1] = 1
    format: Literal["colmap.sqlite.features_v1"] = "colmap.sqlite.features_v1"
    user_version: int = Field(ge=0, strict=True)
    application_id: int = Field(ge=0, strict=True)
    tables: tuple[DatabaseTableEvidence, ...] = Field(max_length=32)
    images: tuple[FeatureImageMapping, ...] = Field(min_length=1, max_length=MAX_VIEWS)

    @model_validator(mode="after")
    def unique_mapping(self) -> NativeFeaturePayload:
        ids = [m.view_id.int for m in self.images]
        if ids != sorted(set(ids)) or len({m.image_id for m in self.images}) != len(ids):
            raise ValueError("Feature mapping must be bijective in canonical view order")
        return self


def _blob_digest(
    connection: sqlite3.Connection,
    table: str,
    image_id: int,
    *,
    columns: int,
    width: int,
    height: int,
    floating: bool,
) -> str:
    digest = hashlib.sha256()
    if connection.execute(
        f"SELECT length(data) FROM {table} WHERE image_id=?", (image_id,)
    ).fetchone()[0] in (None, 0):
        return digest.hexdigest()
    with connection.blobopen(table, "data", image_id, readonly=True) as blob:
        # Fixed chunk aligned to complete rows; never materialize a descriptor matrix.
        stride = columns * (4 if floating else 1)
        chunk_size = max(stride, (64 * 1024 // stride) * stride)
        while data := blob.read(chunk_size):
            digest.update(data)
            if floating:
                for offset, values in enumerate(struct.iter_unpack("<f", data)):
                    value = values[0]
                    if not math.isfinite(value):
                        raise ValueError("Non-finite feature value")
                    if table == "keypoints" and (
                        (offset % columns == 0 and not 0 <= value <= width)
                        or (offset % columns == 1 and not 0 <= value <= height)
                    ):
                        raise ValueError("Keypoint outside published image coordinates")
    return digest.hexdigest()


def inspect_feature_database(
    path: Path,
    summaries: tuple[FeatureViewSummary, ...],
    settings: FeatureSettings,
    *,
    expected_schema: tuple[int, int, tuple[DatabaseTableEvidence, ...]],
    maximum_bytes: int = MAX_FEATURE_DATABASE_BYTES,
    allow_processing_state: bool = False,
) -> tuple[tuple[FeatureViewSummary, ...], NativeFeaturePayload]:
    schema = inspect_colmap_database(path, maximum_bytes=maximum_bytes)
    if schema != expected_schema:
        raise ValueError("Feature database differs from positively verified schema")
    signature = descriptor_signature(settings)
    result = []
    mapping = []
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro&immutable=1", uri=True)) as db:
        deadline = time.monotonic() + 300
        db.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
        db.execute("PRAGMA query_only=ON")
        db.execute("PRAGMA trusted_schema=OFF")
        if db.execute(
            "SELECT 1 FROM sqlite_schema WHERE type IN ('trigger','view') LIMIT 1"
        ).fetchone():
            raise ValueError("Unsupported executable SQLite schema")
        for table in ("images", "keypoints", "descriptors"):
            count = db.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            if count != len(summaries):
                raise ValueError("Feature database has missing or unexpected images/features")
        for table in ("matches", "two_view_geometries"):
            if (not allow_processing_state
                    and db.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone()):
                raise ValueError("M7a database must not contain matches or geometry")
        type_column = "type" in next(t.columns for t in schema[2] if t.name == "descriptors")
        if not type_column and settings.variant != "SIFT":
            raise ValueError("Learned descriptors require a verified native type column")
        for summary in summaries:
            names = (f"{summary.view_id}.png", f"{summary.view_id}.jpg")
            rows = db.execute(
                "SELECT i.image_id, i.name, c.width, c.height FROM images i "
                "JOIN cameras c ON c.camera_id=i.camera_id WHERE i.name IN (?,?)",
                names,
            ).fetchall()
            if len(rows) != 1:
                raise ValueError("Selected-view mapping is missing or ambiguous")
            image_id, name, width, height = rows[0]
            if (width, height) != (summary.width, summary.height):
                raise ValueError("Private camera transport dimensions differ from selected pixels")
            keypoint = db.execute(
                "SELECT rows, cols, length(data), typeof(data) FROM keypoints WHERE image_id=?",
                (image_id,),
            ).fetchone()
            descriptor = db.execute(
                "SELECT rows, cols, length(data), typeof(data)"
                + (", type" if type_column else "")
                + " FROM descriptors WHERE image_id=?",
                (image_id,),
            ).fetchone()
            if keypoint is None or descriptor is None:
                raise ValueError("Missing keypoints/descriptors for selected view")
            n, k, kb, kt = keypoint
            dn, dc, dbytes, dt = descriptor[:4]
            if (
                any(type(v) is not int for v in (n, k, dn, dc))
                or not 0 <= n <= settings.max_features
                or k not in (2, 4, 6)
                or dn != n
                or dc != signature.row_bytes
                or (n > 0 and (kt != "blob" or kb != n * k * 4))
                or (n > 0 and (dt != "blob" or dbytes != n * dc))
                or (n == 0 and (kt not in {"null", "blob"} or kb not in (None, 0)))
                or (n == 0 and (dt not in {"null", "blob"} or dbytes not in (None, 0)))
            ):
                raise ValueError(
                    "Invalid feature counts, dimensions, storage or descriptor mismatch"
                )
            if type_column and (
                type(descriptor[4]) is not int or descriptor[4] != _NATIVE_TYPES[settings.variant]
            ):
                raise ValueError("Incompatible mixed descriptor family/type")
            content = hashlib.sha256(canonical_json_bytes({"count": n, "keypoint_columns": k}))
            for table, cols, floating in (
                ("keypoints", k, True),
                ("descriptors", signature.dimension, signature.scalar_type == "float32_le"),
            ):
                content.update(
                    bytes.fromhex(
                        _blob_digest(
                            db,
                            table,
                            image_id,
                            columns=cols,
                            width=width,
                            height=height,
                            floating=floating,
                        )
                    )
                )
            result.append(
                summary.model_copy(
                    update={
                        "feature_count": n,
                        "keypoint_columns": k,
                        "content_digest": content.hexdigest(),
                    }
                )
            )
            mapping.append(
                FeatureImageMapping(view_id=summary.view_id, image_id=image_id, image_name=name)
            )
    payload = NativeFeaturePayload(
        user_version=schema[0], application_id=schema[1], tables=schema[2], images=tuple(mapping)
    )
    return tuple(result), payload


def validate_feature_payload(directory: Path, features: LocalFeatureSet) -> NativeFeaturePayload:
    path = directory / "backend_mapping.json"
    if path.is_symlink() or path.is_junction() or path.stat().st_size > 32 * 1024 * 1024:
        raise ValueError("Invalid or unbounded feature mapping")
    payload = NativeFeaturePayload.model_validate_json(path.read_bytes())
    summaries, observed = inspect_feature_database(
        directory / "features.db",
        features.views,
        features.settings,
        expected_schema=(payload.user_version, payload.application_id, payload.tables),
    )
    if summaries != features.views or observed != payload:
        raise ValueError("Native feature content/mapping differs from public metadata")
    return payload
