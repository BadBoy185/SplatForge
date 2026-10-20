"""Local SQLite/filesystem execution state for the concrete M1b1 route."""

from __future__ import annotations

import json
import os
import platform
import sqlite3
import time
from collections.abc import Callable, Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath, PureWindowsPath
from tempfile import NamedTemporaryFile
from uuid import UUID, uuid4

from pydantic import ValidationError

from splatforge.adapters.project_lock import (
    ProjectWriterLockFactory,
    WindowsProjectWriterLock,
)
from splatforge.adapters.project_storage import LocalProjectStore
from splatforge.application.execution import (
    PublicationUnresolvedError,
    UnresolvedExecutionError,
)
from splatforge.application.projects import ProjectError
from splatforge.core.execution import (
    ArtifactHandle,
    ArtifactInputLineage,
    ArtifactManifest,
    AttemptExecution,
    CacheIneligible,
    CacheLookup,
    PayloadFile,
    RunSnapshot,
    RunWarning,
    ValidationResult,
)
from splatforge.core.fake_pipeline import (
    NUMBERS_ARTIFACT_TYPE,
    SCALED_ARTIFACT_TYPE,
    NumbersPayload,
    ScaledNumbersPayload,
    canonical_json_bytes,
    semantic_digest,
    sha256_bytes,
)
from splatforge.core.project import ProjectDocument


def _no_fault(_path: Path) -> None:
    return


@dataclass(frozen=True)
class ExecutionFaultHooks:
    after_artifact_move: Callable[[Path], None] = _no_fault


@dataclass(frozen=True)
class LocalExecutionProject:
    document: ProjectDocument
    state_version: int


class LocalExecutionRepository:
    def __init__(
        self,
        *,
        project_store: LocalProjectStore | None = None,
        lock_factory: ProjectWriterLockFactory = WindowsProjectWriterLock,
        fault_hooks: ExecutionFaultHooks | None = None,
    ) -> None:
        self._project_store = project_store or LocalProjectStore(lock_factory=lock_factory)
        self._lock_factory = lock_factory
        self._fault_hooks = fault_hooks or ExecutionFaultHooks()
        self._monotonic_starts: dict[UUID, float] = {}

    @contextmanager
    def writer(self, root: Path, *, owner_token: UUID) -> Iterator[None]:
        root = root.resolve()
        # Read-only preflight avoids creating a lock for an invalid or unsupported project.
        self._project_store.inspect(root)
        with self._lock_factory(root / "project.lock") as lease:
            # The application repeats committed inspection under this lease.
            lease.write_diagnostics(operation="fake-run", owner_token=owner_token)
            yield

    def inspect_project(self, root: Path) -> LocalExecutionProject:
        committed = self._project_store.inspect(root.resolve())
        return LocalExecutionProject(
            document=committed.document,
            state_version=committed.versions.state,
        )

    def ensure_no_unfinished_run(self, root: Path) -> None:
        with self._read_connection(root) as connection:
            unfinished = connection.execute(
                "SELECT run_id FROM runs WHERE status='running' ORDER BY created_at, run_id"
            ).fetchone()
        if unfinished is not None:
            raise UnresolvedExecutionError(
                "An unfinished run blocks execution until M1b2 recovery: " + unfinished[0]
            )

    def create_run(self, root: Path, snapshot: RunSnapshot) -> None:
        root = root.resolve()
        run_directory = self._owned_path(root, f"runs/{snapshot.run_id}")
        run_directory.mkdir(parents=True)
        target = run_directory / "run.json"
        payload = snapshot.model_dump_json(indent=2).encode("utf-8") + b"\n"
        temporary: Path | None = None
        try:
            with NamedTemporaryFile(
                mode="w+b",
                dir=run_directory,
                prefix=".run-",
                suffix=".tmp",
                delete=False,
            ) as stream:
                temporary = Path(stream.name)
                if stream.write(payload) != len(payload):
                    raise OSError("Could not write complete run snapshot")
                stream.flush()
                os.fsync(stream.fileno())
            validated = RunSnapshot.model_validate_json(temporary.read_bytes())
            if validated != snapshot:
                raise ProjectError("Validated run snapshot differs from intended run")
            os.replace(temporary, target)
            temporary = None
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

        now = self._now()
        relative = target.relative_to(root).as_posix()
        try:
            with self._write_connection(root) as connection, connection:
                connection.execute(
                    """
                    INSERT INTO runs (
                        run_id, project_id, project_revision, owner_token,
                        snapshot_path, snapshot_digest, status, created_at, started_at
                    ) VALUES (?, ?, ?, ?, ?, ?, 'running', ?, ?)
                    """,
                    (
                        str(snapshot.run_id),
                        str(snapshot.project_id),
                        snapshot.project_revision,
                        str(snapshot.owner_token),
                        relative,
                        sha256_bytes(payload),
                        snapshot.created_at.isoformat(),
                        now,
                    ),
                )
        except sqlite3.Error as exc:
            raise ProjectError(f"Could not persist run state: {exc}") from exc
        self._monotonic_starts[snapshot.run_id] = time.monotonic()

    def append_event(
        self,
        root: Path,
        run_id: UUID,
        *,
        code: str,
        node_id: str | None = None,
        attempt_id: UUID | None = None,
        details: dict[str, object] | None = None,
    ) -> RunWarning | None:
        try:
            root = root.resolve()
            path = self._owned_path(root, f"runs/{run_id}/events.jsonl")
            sequence = 1
            if path.exists():
                lines = path.read_text(encoding="utf-8").splitlines()
                if lines:
                    sequence = int(json.loads(lines[-1])["sequence"]) + 1
            with self._read_connection(root) as connection:
                row = connection.execute(
                    "SELECT project_id FROM runs WHERE run_id=?", (str(run_id),)
                ).fetchone()
            if row is None:
                raise ProjectError(f"Unknown run {run_id}")
            started = self._monotonic_starts.get(run_id, time.monotonic())
            event = {
                "event_schema_version": 1,
                "recorded_at": self._now(),
                "sequence": sequence,
                "monotonic_ms": max(0, round((time.monotonic() - started) * 1000)),
                "project_id": row[0],
                "run_id": str(run_id),
                "attempt_id": str(attempt_id) if attempt_id is not None else None,
                "node_id": node_id,
                "severity": "error" if code.endswith("failed") else "info",
                "code": code,
                "message": code.replace(".", " "),
                "details": details or {},
            }
            data = canonical_json_bytes(event) + b"\n"
            with path.open("ab") as stream:
                if stream.write(data) != len(data):
                    raise OSError("Could not append complete execution event")
                stream.flush()
                os.fsync(stream.fileno())
        except (
            OSError,
            TypeError,
            ValueError,
            KeyError,
            json.JSONDecodeError,
            sqlite3.Error,
        ) as exc:
            return RunWarning(
                code="event.append_failed",
                message=f"Authoritative state committed, but event append failed: {exc}",
            )
        return None

    def find_cache(
        self,
        root: Path,
        *,
        recipe_key: str,
        artifact_type: str,
        contract_version: int,
    ) -> CacheLookup:
        root = root.resolve()
        with self._read_connection(root) as connection:
            rows = connection.execute(
                """
                SELECT a.artifact_id, a.recipe_key, a.semantic_digest, a.manifest_path
                FROM artifacts a
                JOIN attempts t ON t.attempt_id = a.producer_attempt_id
                WHERE a.recipe_key=? AND a.artifact_type=? AND a.contract_version=?
                  AND t.status='succeeded'
                ORDER BY a.published_at DESC, a.artifact_id DESC
                """,
                (recipe_key, artifact_type, contract_version),
            ).fetchall()
        ineligible: list[CacheIneligible] = []
        for row in rows:
            handle = ArtifactHandle(
                artifact_id=UUID(row[0]),
                artifact_type=artifact_type,
                contract_version=contract_version,
                recipe_key=row[1],
                semantic_digest=row[2],
                manifest_path=row[3],
            )
            try:
                self._validate_indexed_artifact(root, handle)
            except (OSError, ValueError, ValidationError, json.JSONDecodeError) as exc:
                ineligible.append(
                    CacheIneligible(artifact_id=handle.artifact_id, reason=str(exc))
                )
                continue
            return CacheLookup(artifact=handle, ineligible=tuple(ineligible))
        return CacheLookup(ineligible=tuple(ineligible))

    def bind_cached_output(
        self,
        root: Path,
        *,
        run_id: UUID,
        node_id: str,
        output_name: str,
        artifact_id: UUID,
    ) -> None:
        with self._write_connection(root) as connection, connection:
            connection.execute(
                """
                INSERT INTO run_outputs (
                    run_id, node_id, output_name, artifact_id, binding_kind, bound_at
                ) VALUES (?, ?, ?, ?, 'cache_hit', ?)
                """,
                (str(run_id), node_id, output_name, str(artifact_id), self._now()),
            )

    def begin_attempt(
        self,
        root: Path,
        *,
        run_id: UUID,
        node_id: str,
        output_name: str,
        recipe_key: str,
        input_artifact_ids: tuple[UUID, ...],
        literal_inputs: dict[str, object],
    ) -> AttemptExecution:
        root = root.resolve()
        attempt_id = uuid4()
        now = self._now()
        with self._write_connection(root) as connection, connection:
            active = connection.execute(
                "SELECT attempt_id FROM attempts WHERE status IN ('pending', 'running')"
            ).fetchone()
            if active is not None:
                raise UnresolvedExecutionError(
                    "Only one active stage is allowed; active attempt: " + active[0]
                )
            connection.execute(
                """
                INSERT INTO attempts (
                    attempt_id, run_id, node_id, output_name, recipe_key,
                    input_artifacts_json, literal_inputs_json, environment_json,
                    source_verification_json, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)
                """,
                (
                    str(attempt_id),
                    str(run_id),
                    node_id,
                    output_name,
                    recipe_key,
                    canonical_json_bytes([str(value) for value in input_artifact_ids]).decode(),
                    canonical_json_bytes(literal_inputs).decode(),
                    canonical_json_bytes(
                        {
                            "adapter_id": "splatforge.fake_python",
                            "adapter_version": 1,
                            "python_version": platform.python_version(),
                        }
                    ).decode(),
                    canonical_json_bytes(
                        {"policy": "not_applicable", "evidence": []}
                    ).decode(),
                    now,
                ),
            )
        workspace = self._owned_path(root, f"work/{run_id}/{attempt_id}")
        try:
            workspace.mkdir(parents=True)
            with self._write_connection(root) as connection, connection:
                updated = connection.execute(
                    """
                    UPDATE attempts SET status='running', started_at=?
                    WHERE attempt_id=? AND status='pending'
                    """,
                    (self._now(), str(attempt_id)),
                )
                if updated.rowcount != 1:
                    raise ProjectError("Attempt did not enter running state")
        except Exception as exc:
            self.mark_attempt_failed(root, attempt_id=attempt_id, message=str(exc))
            raise
        return AttemptExecution(attempt_id=attempt_id, workspace=str(workspace))

    def publish_attempt(
        self,
        root: Path,
        *,
        run_id: UUID,
        node_id: str,
        output_name: str,
        artifact_type: str,
        contract_version: int,
        recipe_key: str,
        attempt: AttemptExecution,
        input_lineage: tuple[ArtifactInputLineage, ...],
    ) -> ArtifactHandle:
        root = root.resolve()
        workspace = Path(attempt.workspace)
        output = workspace / "output"
        payload_name, parsed = self._validate_candidate(output, artifact_type)
        payload_path = output / payload_name
        payload_bytes = payload_path.read_bytes()
        content_digest = semantic_digest(parsed)
        artifact_id = uuid4()
        manifest = ArtifactManifest(
            artifact_id=artifact_id,
            artifact_type=artifact_type,
            contract_version=contract_version,
            producer_run_id=run_id,
            producer_node_id=node_id,
            producer_attempt_id=attempt.attempt_id,
            recipe_key=recipe_key,
            semantic_digest=content_digest,
            input_lineage=input_lineage,
            payloads=(
                PayloadFile(
                    path=payload_name,
                    size=len(payload_bytes),
                    sha256=sha256_bytes(payload_bytes),
                ),
            ),
            validation=ValidationResult(
                validator_id=f"{artifact_type}.integrity", validator_version=1
            ),
        )
        manifest_bytes = manifest.model_dump_json(indent=2).encode("utf-8") + b"\n"
        self._write_new_file(output / "manifest.json", manifest_bytes)
        manifest_digest = sha256_bytes(manifest_bytes)

        with self._write_connection(root) as connection, connection:
            updated = connection.execute(
                """
                UPDATE attempts
                SET expected_artifact_id=?, expected_manifest_digest=?
                WHERE attempt_id=? AND status='running'
                """,
                (str(artifact_id), manifest_digest, str(attempt.attempt_id)),
            )
            if updated.rowcount != 1:
                raise ProjectError("Running attempt was unavailable for publication")

        artifact_directory = self._owned_path(root, f"artifacts/{node_id}/{artifact_id}")
        artifact_directory.parent.mkdir(parents=True, exist_ok=True)
        if artifact_directory.exists():
            raise ProjectError(f"Artifact destination already exists: {artifact_id}")

        moved = False
        try:
            os.replace(output, artifact_directory)
            moved = True
            self._fault_hooks.after_artifact_move(artifact_directory)
            relative_manifest = (artifact_directory / "manifest.json").relative_to(root).as_posix()
            with self._write_connection(root) as connection, connection:
                connection.execute(
                    """
                    INSERT INTO artifacts (
                        artifact_id, producer_attempt_id, producer_run_id,
                        node_id, output_name, artifact_type, contract_version,
                        recipe_key, semantic_digest, manifest_path, manifest_digest,
                        published_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(artifact_id),
                        str(attempt.attempt_id),
                        str(run_id),
                        node_id,
                        output_name,
                        artifact_type,
                        contract_version,
                        recipe_key,
                        content_digest,
                        relative_manifest,
                        manifest_digest,
                        self._now(),
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO run_outputs (
                        run_id, node_id, output_name, artifact_id, binding_kind, bound_at
                    ) VALUES (?, ?, ?, ?, 'executed', ?)
                    """,
                    (str(run_id), node_id, output_name, str(artifact_id), self._now()),
                )
                succeeded = connection.execute(
                    """
                    UPDATE attempts SET status='succeeded', finished_at=?
                    WHERE attempt_id=? AND status='running'
                      AND expected_artifact_id=? AND expected_manifest_digest=?
                    """,
                    (
                        self._now(),
                        str(attempt.attempt_id),
                        str(artifact_id),
                        manifest_digest,
                    ),
                )
                if succeeded.rowcount != 1:
                    raise ProjectError("Attempt success preconditions changed")
        except Exception as exc:
            if moved or artifact_directory.exists():
                raise PublicationUnresolvedError(
                    "Artifact moved but final success commit is unresolved: "
                    f"{artifact_id}: {exc}"
                ) from exc
            raise

        return ArtifactHandle(
            artifact_id=artifact_id,
            artifact_type=artifact_type,
            contract_version=contract_version,
            recipe_key=recipe_key,
            semantic_digest=content_digest,
            manifest_path=relative_manifest,
        )

    def mark_attempt_failed(
        self, root: Path, *, attempt_id: UUID, message: str
    ) -> None:
        with self._write_connection(root) as connection, connection:
            connection.execute(
                """
                UPDATE attempts SET status='failed', finished_at=?, failure_json=?
                WHERE attempt_id=? AND status IN ('pending', 'running')
                """,
                (
                    self._now(),
                    canonical_json_bytes({"message": message}).decode(),
                    str(attempt_id),
                ),
            )

    def mark_run_failed(self, root: Path, *, run_id: UUID, message: str) -> None:
        with self._write_connection(root) as connection, connection:
            connection.execute(
                """
                UPDATE runs SET status='failed', finished_at=?, failure_json=?
                WHERE run_id=? AND status='running'
                """,
                (
                    self._now(),
                    canonical_json_bytes({"message": message}).decode(),
                    str(run_id),
                ),
            )

    def mark_run_succeeded(self, root: Path, *, run_id: UUID) -> None:
        with self._write_connection(root) as connection, connection:
            updated = connection.execute(
                """
                UPDATE runs SET status='succeeded', finished_at=?
                WHERE run_id=? AND status='running'
                """,
                (self._now(), str(run_id)),
            )
            if updated.rowcount != 1:
                raise ProjectError("Run did not enter succeeded state")

    def load_numbers(self, root: Path, artifact: ArtifactHandle) -> NumbersPayload:
        manifest, artifact_directory = self._validate_indexed_artifact(
            root.resolve(), artifact
        )
        payload = artifact_directory / manifest.payloads[0].path
        return NumbersPayload.model_validate_json(payload.read_bytes())

    def show_run(self, root: Path, run_id: UUID) -> str:
        root = root.resolve()
        with self._read_connection(root) as connection:
            connection.row_factory = sqlite3.Row
            run = connection.execute(
                "SELECT * FROM runs WHERE run_id=?", (str(run_id),)
            ).fetchone()
            if run is None:
                raise ProjectError(f"Unknown run {run_id}")
            attempts = connection.execute(
                "SELECT * FROM attempts WHERE run_id=? ORDER BY created_at, attempt_id",
                (str(run_id),),
            ).fetchall()
            outputs = connection.execute(
                """
                SELECT node_id, output_name, artifact_id, binding_kind, bound_at
                FROM run_outputs WHERE run_id=? ORDER BY node_id, output_name
                """,
                (str(run_id),),
            ).fetchall()
        snapshot_path = self._owned_path(root, run["snapshot_path"])
        snapshot_bytes = snapshot_path.read_bytes()
        if sha256_bytes(snapshot_bytes) != run["snapshot_digest"]:
            raise ProjectError("Run snapshot digest mismatch")
        snapshot = RunSnapshot.model_validate_json(snapshot_bytes)
        rendered = {
            "snapshot": snapshot.model_dump(mode="json"),
            "state": dict(run),
            "attempts": [dict(row) for row in attempts],
            "outputs": [dict(row) for row in outputs],
        }
        return json.dumps(rendered, ensure_ascii=False, indent=2)

    def _validate_indexed_artifact(
        self, root: Path, handle: ArtifactHandle
    ) -> tuple[ArtifactManifest, Path]:
        manifest_path = self._owned_path(root, handle.manifest_path)
        with self._read_connection(root) as connection:
            row = connection.execute(
                """
                SELECT manifest_digest, producer_attempt_id FROM artifacts
                WHERE artifact_id=?
                """,
                (str(handle.artifact_id),),
            ).fetchone()
            if row is None:
                raise ValueError("Artifact is not indexed")
            attempt = connection.execute(
                "SELECT status FROM attempts WHERE attempt_id=?", (row[1],)
            ).fetchone()
        if attempt is None or attempt[0] != "succeeded":
            raise ValueError("Producer attempt is not succeeded")
        manifest_bytes = manifest_path.read_bytes()
        if sha256_bytes(manifest_bytes) != row[0]:
            raise ValueError("Manifest digest mismatch")
        manifest = ArtifactManifest.model_validate_json(manifest_bytes)
        if (
            manifest.artifact_id != handle.artifact_id
            or manifest.artifact_type != handle.artifact_type
            or manifest.contract_version != handle.contract_version
            or manifest.recipe_key != handle.recipe_key
            or manifest.semantic_digest != handle.semantic_digest
            or manifest.validation.validator_version != 1
        ):
            raise ValueError("Manifest identity or contract mismatch")
        artifact_directory = manifest_path.parent
        if len(manifest.payloads) != 1:
            raise ValueError("Artifact must contain exactly one declared payload")
        payload = manifest.payloads[0]
        payload_path = self._artifact_payload_path(artifact_directory, payload.path)
        data = payload_path.read_bytes()
        if len(data) != payload.size:
            raise ValueError("Payload size mismatch")
        if sha256_bytes(data) != payload.sha256:
            raise ValueError("Payload digest mismatch")
        if manifest.artifact_type == NUMBERS_ARTIFACT_TYPE:
            parsed = NumbersPayload.model_validate_json(data)
        elif manifest.artifact_type == SCALED_ARTIFACT_TYPE:
            parsed = ScaledNumbersPayload.model_validate_json(data)
        else:
            raise ValueError("Unsupported artifact type")
        if semantic_digest(parsed) != manifest.semantic_digest:
            raise ValueError("Semantic digest mismatch")
        return manifest, artifact_directory

    @staticmethod
    def _validate_candidate(
        output: Path, artifact_type: str
    ) -> tuple[str, NumbersPayload | ScaledNumbersPayload]:
        if not output.is_dir():
            raise ValueError("Fake stage did not create its output directory")
        if artifact_type == NUMBERS_ARTIFACT_TYPE:
            name = "numbers.json"
            model = NumbersPayload
        elif artifact_type == SCALED_ARTIFACT_TYPE:
            name = "scaled.json"
            model = ScaledNumbersPayload
        else:
            raise ValueError(f"Unsupported fake artifact type: {artifact_type}")
        entries = list(output.iterdir())
        if len(entries) != 1 or entries[0].name != name or not entries[0].is_file():
            raise ValueError(f"Fake stage output must contain exactly {name}")
        parsed = model.model_validate_json(entries[0].read_bytes())
        return name, parsed

    @staticmethod
    def _artifact_payload_path(artifact_directory: Path, relative: str) -> Path:
        windows = PureWindowsPath(relative)
        parts = relative.split("/")
        if (
            not relative
            or windows.drive
            or windows.root
            or PurePosixPath(relative).is_absolute()
            or "\\" in relative
            or any(part in ("", ".", "..") for part in parts)
        ):
            raise ValueError("Manifest payload path is not a safe relative path")
        path = (artifact_directory / relative).resolve()
        if not path.is_relative_to(artifact_directory.resolve()):
            raise ValueError("Manifest payload escapes its artifact directory")
        if path.is_symlink() or path.is_junction():
            raise ValueError("Manifest payload must not be a filesystem redirection")
        return path

    @staticmethod
    def _write_new_file(path: Path, payload: bytes) -> None:
        with path.open("xb") as stream:
            if stream.write(payload) != len(payload):
                raise OSError(f"Could not write complete file: {path}")
            stream.flush()
            os.fsync(stream.fileno())

    @staticmethod
    def _owned_path(root: Path, relative: str) -> Path:
        windows = PureWindowsPath(relative)
        parts = relative.split("/")
        if (
            not relative
            or windows.drive
            or windows.root
            or PurePosixPath(relative).is_absolute()
            or "\\" in relative
            or any(part in ("", ".", "..") for part in parts)
        ):
            raise ProjectError("Execution path must be project-relative and use '/'")
        path = (root / relative).resolve()
        if not path.is_relative_to(root):
            raise ProjectError("Execution path escapes the project directory")
        return path

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat()

    @staticmethod
    @contextmanager
    def _read_connection(root: Path) -> Iterator[sqlite3.Connection]:
        uri = (root.resolve() / "state.sqlite").as_uri() + "?mode=ro"
        with closing(sqlite3.connect(uri, uri=True)) as connection:
            connection.execute("PRAGMA foreign_keys = ON")
            yield connection

    @staticmethod
    @contextmanager
    def _write_connection(root: Path) -> Iterator[sqlite3.Connection]:
        with closing(sqlite3.connect(root.resolve() / "state.sqlite")) as connection:
            connection.execute("PRAGMA foreign_keys = ON")
            yield connection
