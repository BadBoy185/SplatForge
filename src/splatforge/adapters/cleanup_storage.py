"""Bounded generated-file eviction with durable intent before each unlink.

Uses state.metadata, not a new storage manager/schema. Manifests and JSON metadata
survive. Never removes directories recursively or accepts external path targets.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from uuid import UUID

from splatforge.adapters.artifact_validation import (
    MAX_MANIFEST_BYTES,
    _read_bounded,
    safe_payload_path,
    stream_sha256,
)
from splatforge.core.cleanup import (
    ArtifactEvictedError,
    CleanupCandidate,
    CleanupPayload,
    CleanupPlan,
)
from splatforge.core.execution import ArtifactManifest
from splatforge.core.features import digest_json

RETENTION_KEY = "storage.retention_v1"
MAX_RETENTION_BYTES = 16 * 1024**2
MAX_CLEANUP_ARTIFACTS = 10000
MAX_CLEANUP_MANIFEST_BYTES = 64 * 1024**2
ELIGIBLE_TYPES = frozenset(
    {
        "views.candidate_set",
        "features.local_feature_set",
        "matching.match_set",
        "geometry.verified_geometry_set",
        "mapping.reconstruction_set",
        "retrieval.representation_set",
        "dataset.prepared_component",
    }
)


class CleanupStorageMixin:
    @contextmanager
    def cleanup_preview_lease(self, root: Path) -> Iterator[None]:
        self.inspect_project(root)
        with self._lock_factory(root / "project.lock"):
            yield

    def retention_state(self, root: Path) -> dict[str, Any]:
        with self._read_connection(root) as db:
            row = db.execute("SELECT value FROM metadata WHERE key=?", (RETENTION_KEY,)).fetchone()
        if row is None:
            return {"version": 1, "pins": [], "evictions": {}}
        if len(row[0]) > MAX_RETENTION_BYTES:
            raise ValueError("cleanup.resource_limit: retention metadata bound exceeded")
        value = json.loads(row[0])
        if value.get("version") != 1:
            raise ValueError("cleanup.unsupported_retention_version")
        return value

    def _save_retention(self, root, value):
        payload = json.dumps(value, sort_keys=True, separators=(",", ":"))
        if len(payload.encode("utf8")) > MAX_RETENTION_BYTES:
            raise ValueError("cleanup.resource_limit: retention metadata bound exceeded")
        with self._write_connection(root) as db, db:
            db.execute(
                "INSERT INTO metadata(key,value) VALUES (?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (RETENTION_KEY, payload),
            )

    def require_not_evicted(self, root: Path, artifact_id: UUID) -> None:
        state = self.retention_state(root)["evictions"].get(str(artifact_id))
        if state:
            raise ArtifactEvictedError(
                f"artifact.{state['state']}: generated payload intentionally "
                "evicted; request recomputation"
            )

    def set_artifact_pin(self, root: Path, artifact_id: UUID, pinned: bool) -> None:
        with self._read_connection(root) as db:
            row = db.execute(
                "SELECT 1 FROM artifacts WHERE artifact_id=?", (str(artifact_id),)
            ).fetchone()
        if row is None:
            raise ValueError("cleanup.unknown_artifact: pins require indexed generated artifacts")
        state = self.retention_state(root)
        if str(artifact_id) in state["evictions"]:
            raise ValueError("cleanup.evicted_artifact: cannot pin an evicted payload")
        pins = set(state["pins"])
        (pins.add if pinned else pins.discard)(str(artifact_id))
        state["pins"] = sorted(pins)
        self._save_retention(root, state)

    def _cleanup_inventory(self, root):
        with self._read_connection(root) as db:
            rows = db.execute(
                "SELECT a.artifact_id,a.artifact_type,a.manifest_path,a.manifest_digest,"
                "a.producer_run_id,a.producer_attempt_id,t.status,r.status,a.published_at "
                "FROM artifacts a JOIN attempts t ON t.attempt_id=a.producer_attempt_id "
                "JOIN runs r ON r.run_id=a.producer_run_id ORDER BY a.published_at,a.artifact_id"
            ).fetchmany(MAX_CLEANUP_ARTIFACTS + 1)
            active = db.execute(
                "SELECT input_artifacts_json,expected_artifact_id FROM attempts "
                "WHERE status IN ('pending','running') OR teardown_state='unresolved'"
            ).fetchall()
            active_outputs = db.execute(
                "SELECT o.artifact_id FROM run_outputs o JOIN runs r ON r.run_id=o.run_id "
                "WHERE r.status IN ('running','interrupted')"
            ).fetchall()
            current_bindings = db.execute(
                "SELECT artifact_id FROM (SELECT o.artifact_id, ROW_NUMBER() OVER ("
                "PARTITION BY a.artifact_type ORDER BY o.bound_at DESC,o.run_id DESC) AS position "
                "FROM run_outputs o JOIN runs r ON r.run_id=o.run_id "
                "JOIN artifacts a ON a.artifact_id=o.artifact_id WHERE r.status='succeeded') "
                "WHERE position=1"
            ).fetchall()
        if len(rows) > MAX_CLEANUP_ARTIFACTS:
            raise ValueError("cleanup.resource_limit: inventory exceeds bounded manual cleanup")
        manifests, by_id = {}, {}
        metadata_bytes = 0
        for row in rows:
            identity, _kind, relative, sha, *_rest = row
            path = self._owned_path(root, relative)
            metadata_bytes += path.stat().st_size
            if metadata_bytes > MAX_CLEANUP_MANIFEST_BYTES:
                raise ValueError("cleanup.resource_limit: cumulative manifest bytes exceed 64 MiB")
            if (
                not relative.startswith("artifacts/")
                or path.name != "manifest.json"
                or path.stat().st_nlink != 1
            ):
                raise ValueError("cleanup.unsafe_path: require owned artifact manifest")
            payload = _read_bounded(path, MAX_MANIFEST_BYTES, "Cleanup manifest")
            if __import__("hashlib").sha256(payload).hexdigest() != sha:
                raise ValueError("cleanup.corrupt_manifest: refuse deletion")
            manifest = ArtifactManifest.model_validate_json(payload)
            if str(manifest.artifact_id) != identity:
                raise ValueError("cleanup.corrupt_manifest: artifact identity differs")
            manifests[identity], by_id[identity] = manifest, row
        state = self.retention_state(root)
        protected = set(state["pins"])
        # Current means newest completed successful publication per artifact kind.
        # Its entire exact dependency closure is implicitly pinned. Historical
        # lineage alone does not retain every superseded payload forever.
        latest = {}
        for row in rows:
            if row[6:8] == ("succeeded", "succeeded") and row[0] not in state["evictions"]:
                latest[row[1]] = row[0]
        protected.update(latest.values())
        # Re-selecting an older cached result makes it current too. Its original
        # publication date must never make the user's latest successful choice
        # eligible for deletion. Keep the newest publications as an extra guard.
        protected.update(r[0] for r in current_bindings)
        for inputs, expected in active:
            protected.update(json.loads(inputs))
            if expected:
                protected.add(expected)
        protected.update(r[0] for r in active_outputs)
        stack = list(protected)
        while stack:
            identity = stack.pop()
            manifest = manifests.get(identity)
            if manifest:
                for lineage in manifest.input_lineage:
                    upstream = str(lineage.artifact_id)
                    if upstream not in protected:
                        protected.add(upstream)
                        stack.append(upstream)
        return rows, manifests, protected, state

    def cleanup_plan(self, root: Path, requested: tuple[UUID, ...]) -> CleanupPlan:
        root = root.resolve()
        rows, manifests, protected, state = self._cleanup_inventory(root)
        by_id = {r[0]: r for r in rows}
        targets = [str(i) for i in requested] if requested else list(by_id)
        if len(targets) != len(set(targets)) or set(targets) - set(by_id):
            raise ValueError("cleanup.unknown_artifact: only unique indexed artifact IDs accepted")
        candidates = []
        for identity in sorted(targets):
            row, manifest = by_id[identity], manifests[identity]
            if row[1] not in ELIGIBLE_TYPES:
                if requested:
                    raise ValueError("cleanup.ineligible_type: only implemented generated payloads")
                continue
            if identity in protected or row[6:8] != ("succeeded", "succeeded"):
                if requested:
                    raise ValueError("cleanup.protected_artifact: active/current/pinned dependency")
                continue
            eviction = state["evictions"].get(identity)
            if eviction and eviction["state"] == "evicted":
                if requested:
                    raise ValueError("cleanup.already_evicted")
                continue
            directory = self._owned_path(root, row[2]).parent
            payloads = []
            # Validate every path before deleting any file. Keep descriptive JSON.
            for payload in manifest.payloads:
                path = safe_payload_path(directory, payload.path)
                if payload.path.endswith(".json"):
                    continue
                if not path.exists() and eviction:
                    continue
                if not path.is_file() or path.stat().st_nlink != 1:
                    raise ValueError(
                        "cleanup.unsafe_payload: missing/redirected/non-independent file"
                    )
                if stream_sha256(path) != (payload.size, payload.sha256):
                    raise ValueError("cleanup.corrupt_payload: inspect before cleanup")
                payloads.append(
                    CleanupPayload(path=payload.path, size=payload.size, sha256=payload.sha256)
                )
            if payloads or eviction:
                candidates.append(
                    CleanupCandidate(
                        artifact_id=UUID(identity),
                        artifact_type=row[1],
                        manifest_digest=row[3],
                        payloads=tuple(payloads),
                        state="evicting" if eviction else "eligible",
                    )
                )
        return CleanupPlan(
            project_id=self.inspect_project(root).document.project_id,
            candidates=tuple(candidates),
            protected_artifact_ids=tuple(sorted((UUID(i) for i in protected), key=lambda i: i.int)),
            total_bytes=sum(p.size for c in candidates for p in c.payloads),
        )

    def apply_cleanup(self, root: Path, plan: CleanupPlan) -> None:
        # Called under the writer lease after exact preview revalidation.
        state = self.retention_state(root)
        for candidate in plan.candidates:
            identity = str(candidate.artifact_id)
            with self._read_connection(root) as db:
                relative = db.execute(
                    "SELECT manifest_path FROM artifacts WHERE artifact_id=?", (identity,)
                ).fetchone()[0]
            directory = self._owned_path(root, relative).parent
            state["evictions"][identity] = {
                "state": "evicting",
                "preview_digest": plan.preview_digest,
                "manifest_digest": candidate.manifest_digest,
                "payload_list_digest": digest_json([p.model_dump() for p in candidate.payloads]),
            }
            self._save_retention(root, state)
            for payload in candidate.payloads:
                path = safe_payload_path(directory, payload.path)
                if (
                    not path.is_file()
                    or path.stat().st_nlink != 1
                    or stream_sha256(path) != (payload.size, payload.sha256)
                ):
                    raise ValueError("cleanup.changed_payload: deletion interrupted; re-preview")
                path.unlink()
            state["evictions"][identity]["state"] = "evicted"
            self._save_retention(root, state)
