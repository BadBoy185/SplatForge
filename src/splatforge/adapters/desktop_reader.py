"""Bounded read-only desktop index. Native preview readers stay in adapters."""

import json
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path
from uuid import UUID

from splatforge.adapters.artifact_validation import safe_payload_path
from splatforge.adapters.desktop_preview import camera_centers, gaussian_centers, sparse_centers
from splatforge.adapters.execution_storage import LocalExecutionRepository
from splatforge.application.desktop import (
    IndexRow,
    PreviewData,
    ProjectIndex,
    ThumbnailReference,
)
from splatforge.core.execution import ArtifactManifest
from splatforge.core.reconstruction import ReconstructionPose
from splatforge.core.views import sha256_bytes


class LocalDesktopReader:
    def __init__(self) -> None:
        self.repository = LocalExecutionRepository()

    def state_version(self, root: Path) -> int:
        return self.repository.inspect_project(root).state_version

    def index(self, root: Path) -> ProjectIndex:
        project = self.repository.inspect_project(root)
        if project.state_version < 2:
            return ProjectIndex(state_version=project.state_version)
        uri = (root.resolve() / "state.sqlite").as_uri() + "?mode=ro"
        with closing(sqlite3.connect(uri, uri=True, timeout=2)) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute("BEGIN")
            extra = (
                ", (SELECT group_concat(DISTINCT a.failure_category) FROM attempts a "
                "WHERE a.run_id=r.run_id) AS failure_category "
                ", (SELECT group_concat(DISTINCT a.teardown_state) FROM attempts a "
                "WHERE a.run_id=r.run_id) AS teardown "
                if project.state_version >= 3
                else ", NULL AS failure_category, NULL AS teardown "
            )
            runs = connection.execute(
                "SELECT r.run_id, r.status, r.started_at, r.finished_at, r.failure_json, "
                "(SELECT group_concat(DISTINCT a.node_id) FROM attempts a "
                "WHERE a.run_id=r.run_id) AS stage, "
                "(SELECT group_concat(DISTINCT o.binding_kind) FROM run_outputs o "
                "WHERE o.run_id=r.run_id) AS cache "
                + extra
                + "FROM runs r ORDER BY r.started_at DESC,r.run_id DESC LIMIT 2001"
            ).fetchall()
            artifacts = connection.execute(
                "SELECT * FROM artifacts ORDER BY published_at DESC,artifact_id DESC LIMIT 2001"
            ).fetchall()
            retention = connection.execute(
                "SELECT value FROM metadata WHERE key='storage.retention_v1'"
            ).fetchone()
            verification_rows = (
                connection.execute(
                    "SELECT source_id,source_revision,expected_content_digest,"
                    "outcome,assurance,checked_at "
                    "FROM source_verifications ORDER BY checked_at DESC LIMIT 10000"
                ).fetchall()
                if project.state_version >= 4
                else []
            )
        storage = json.loads(retention[0]) if retention else {}
        verifications = {}
        for evidence in verification_rows:
            verifications.setdefault(evidence["source_id"], dict(evidence))
        validation_status = "not_started"
        report_row = next(
            (a for a in artifacts if a["artifact_type"] == "validation.reconstruction_report"), None
        )
        if report_row:
            try:
                manifest_path = self.repository._owned_path(
                    root.resolve(), report_row["manifest_path"]
                )
                if manifest_path.stat().st_size > 4 * 1024**2:
                    raise ValueError("preview.manifest_limit")
                raw = manifest_path.read_bytes()
                if sha256_bytes(raw) != report_row["manifest_digest"]:
                    raise ValueError("preview.manifest_digest_mismatch")
                manifest = ArtifactManifest.model_validate_json(raw)
                payload = next(p for p in manifest.payloads if p.path == "evidence.json")
                path = safe_payload_path(manifest_path.parent, payload.path)
                if path.stat().st_size > 4 * 1024**2:
                    raise ValueError("preview.report_limit")
                raw = path.read_bytes()
                if sha256_bytes(raw) != payload.sha256:
                    raise ValueError("preview.report_digest_mismatch")
                validation_status = json.loads(raw)["report"]["status"]
            except (ValueError, OSError, KeyError, StopIteration):
                validation_status = "unavailable — inspect report integrity"
        return ProjectIndex(
            state_version=project.state_version,
            runs=tuple(
                IndexRow(
                    identity=UUID(r["run_id"]),
                    values={
                        **dict(r),
                        "stage": r["stage"] or "pending",
                        "cache": r["cache"] or "none",
                        "duration_seconds": (
                            datetime.fromisoformat(r["finished_at"])
                            - datetime.fromisoformat(r["started_at"])
                        ).total_seconds()
                        if r["finished_at"]
                        else None,
                    },
                )
                for r in runs[:2000]
            ),
            artifacts=tuple(
                IndexRow(
                    identity=UUID(a["artifact_id"]),
                    values={
                        **dict(a),
                        "storage_status": storage.get("evictions", {})
                        .get(a["artifact_id"], {})
                        .get("state", "published"),
                        "pinned": a["artifact_id"] in storage.get("pins", []),
                    },
                )
                for a in artifacts[:2000]
            ),
            truncated=len(runs) > 2000 or len(artifacts) > 2000,
            source_verifications=verifications,
            validation_status=validation_status,
        )

    def inspect(self, root: Path, artifact_id: UUID) -> PreviewData:
        index = self.index(root)
        row = next((a for a in index.artifacts if a.identity == artifact_id), None)
        if row is None:
            raise ValueError("desktop.artifact_outside_recent_index")
        manifest_path = self.repository._owned_path(root.resolve(), row.values["manifest_path"])
        if manifest_path.stat().st_size > 16 * 1024**2:
            raise ValueError("desktop.manifest_preview_limit")
        raw = manifest_path.read_bytes()
        if sha256_bytes(raw) != row.values["manifest_digest"]:
            raise ValueError("preview.manifest_digest_mismatch")
        manifest = ArtifactManifest.model_validate_json(raw)
        if (
            manifest.artifact_id != artifact_id
            or manifest.semantic_digest != row.values["semantic_digest"]
        ):
            raise ValueError("preview.manifest_identity_mismatch")
        directory = manifest_path.parent
        points, cameras, metadata = (), (), {}
        payloads = {p.path: p for p in manifest.payloads}
        for name in (
            "reconstruction.json",
            "dataset.json",
            "scene.json",
            "scene_set.json",
            "dataset_set.json",
            "checkpoint.json",
        ):
            if name in payloads:
                path = safe_payload_path(directory, name)
                if path.stat().st_size > 64 * 1024**2:
                    raise ValueError("preview.metadata_limit")
                data = path.read_bytes()
                if sha256_bytes(data) != payloads[name].sha256:
                    raise ValueError("preview.metadata_digest_mismatch")
                metadata[name] = json.loads(data)
        # Select one explicit native component for display. Never combine coordinate systems.
        point_paths = sorted(p for p in payloads if p.endswith("points3D.bin"))
        if point_paths:
            path = safe_payload_path(directory, point_paths[0])
            points = sparse_centers(path)
            image_name = str(Path(point_paths[0]).with_name("images.bin")).replace("\\", "/")
            if image_name in payloads:
                cameras = camera_centers(safe_payload_path(directory, image_name))
        if "scene.ply" in payloads:
            points = gaussian_centers(safe_payload_path(directory, "scene.ply"))
        if not cameras:
            for value in metadata.values():
                for view in value.get("views", []):
                    pose = view.get("pose")
                    if pose and len(cameras) < 2000:
                        cameras += (ReconstructionPose.model_validate(pose).camera_center(),)
        return PreviewData(
            artifact_id=artifact_id,
            semantic_digest=row.values["semantic_digest"],
            directory=directory,
            metadata={
                **row.values,
                "manifest": compact_metadata(manifest.model_dump(mode="json")),
                "payload_bytes": sum(p.size for p in manifest.payloads),
                "documents": compact_metadata(metadata),
                "preview_component": point_paths[0] if point_paths else None,
                "preview_integrity": "Indexed publication and hashed metadata; "
                "bounded native samples. "
                "Use application inspection/Plan for full payload validation.",
            },
            points=points,
            cameras=cameras,
            label="Point-center preview — not final Gaussian rasterization"
            if "scene.ply" in payloads
            else "Sparse point preview — first native component only; separate coordinate system",
        )

    def live_metrics(self, root: Path, run_ids: tuple[UUID, ...]) -> dict:
        result = {}
        for run in run_ids:
            path = self.repository._owned_path(root.resolve(), f"runs/{run}/events.jsonl")
            if not path.exists():
                continue
            with path.open("rb") as stream:
                stream.seek(max(0, path.stat().st_size - 2 * 1024**2))
                if stream.tell():
                    stream.readline()
                lines = stream.read(2 * 1024**2).splitlines()
            for line in reversed(lines):
                try:
                    event = json.loads(line)
                    observation = event.get("details", {}).get("observation")
                    if observation:
                        result[str(run)] = observation
                        break
                except (ValueError, UnicodeError):
                    continue
        return result

    def gallery(self, root: Path, run_id: UUID, offset: int = 0) -> tuple[ThumbnailReference, ...]:
        if offset < 0:
            raise ValueError("desktop.invalid_gallery_offset")
        repo = self.repository
        candidate = repo.resolve_run_output(root, run_id, "candidate_views", "candidate_set")
        selected = repo.resolve_run_output(root, run_id, "selected_views", "selected_set")
        pool, selection = repo.load_pairing_inputs(root, candidate, selected)
        ids = {v.view_id for v in selection.selected_views}
        views = (v for v in pool.views if v.view_id in ids)
        from itertools import islice

        directory = repo.artifact_directory(root, candidate)
        return tuple(
            ThumbnailReference(
                identity=f"{candidate.semantic_digest}:{v.view_id}",
                path=repo._owned_path(directory, v.image_path),
                caption=f"{v.view_id} · source {v.source_id}",
            )
            for v in islice(views, offset, offset + 100)
        )


def compact_metadata(value, depth: int = 0):
    """Keep large image/lineage inventories out of widget JSON formatting/rendering."""
    if depth > 16:
        return "Nested preview limit"
    if isinstance(value, list):
        sample = [compact_metadata(v, depth + 1) for v in value[:40]]
        return (
            sample
            if len(value) <= 40
            else {"count": len(value), "sample": sample, "truncated_for_preview": True}
        )
    if isinstance(value, dict):
        return {k: compact_metadata(v, depth + 1) for k, v in list(value.items())[:100]}
    if isinstance(value, str):
        return value[:4096]
    return value
