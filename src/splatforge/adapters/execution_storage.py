"""Local SQLite/filesystem execution state for the concrete fake route."""

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
    ExecutionCancelledError,
    PublicationUnresolvedError,
    RetryNotAllowedError,
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
    CancellationRequest,
    CancellationRequestResult,
    FailureCategory,
    PayloadFile,
    RecoveryResult,
    RunSnapshot,
    RunStatus,
    RunWarning,
    ValidationResult,
)
from splatforge.core.fake_pipeline import (
    NUMBERS_ARTIFACT_TYPE,
    SCALED_ARTIFACT_TYPE,
    NumbersPayload,
    ScaledNumbersPayload,
    canonical_json_bytes,
    scale_recipe_key,
    semantic_digest,
    sequence_recipe_key,
    sha256_bytes,
)
from splatforge.core.project import ProjectDocument


def _no_fault(_path: Path) -> None:
    return


@dataclass(frozen=True)
class ExecutionFaultHooks:
    after_artifact_move: Callable[[Path], None] = _no_fault
    after_run_record: Callable[[Path], None] = _no_fault
    before_artifact_move: Callable[[Path], None] = _no_fault
    before_cancellation_request_publish: Callable[[Path], None] = _no_fault


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
            # Refuse a raced unsupported format before changing lock diagnostics.
            self._project_store.inspect(root)
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
            unfinished_run = connection.execute(
                "SELECT run_id FROM runs WHERE status='running' ORDER BY created_at, run_id"
            ).fetchone()
            active_attempt = connection.execute(
                """
                SELECT attempt_id FROM attempts
                WHERE status IN ('pending', 'running')
                ORDER BY created_at, attempt_id
                """
            ).fetchone()
        if unfinished_run is not None:
            raise UnresolvedExecutionError(
                "An unfinished run blocks execution until M1b2 recovery: " + unfinished_run[0]
            )
        if active_attempt is not None:
            raise UnresolvedExecutionError(
                "An unresolved attempt blocks execution until M1b2 recovery: " + active_attempt[0]
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
        self._fault_hooks.after_run_record(root)

    def request_cancellation(self, root: Path, *, run_id: UUID) -> CancellationRequestResult:
        root = root.resolve()
        project = self.inspect_project(root)
        if project.state_version in {1, 2}:
            raise ProjectError("State upgrade required before cancellation")
        if project.state_version != 3:
            raise ProjectError(f"Unsupported state schema version {project.state_version}")
        with self._read_connection(root) as connection:
            row = connection.execute(
                "SELECT owner_token, status FROM runs WHERE run_id=?", (str(run_id),)
            ).fetchone()
        if row is None:
            raise ProjectError(f"Unknown run {run_id}")
        request = CancellationRequest(
            request_id=uuid4(),
            run_id=run_id,
            run_owner_token=UUID(row[0]),
            requested_at=datetime.now(UTC),
        )
        path = self._owned_path(root, f"runs/{run_id}/cancel.request")
        if path.exists():
            existing, _ = self._read_cancellation_request(root, run_id)
            if existing.run_id != run_id or existing.run_owner_token != request.run_owner_token:
                raise ProjectError("Existing cancellation request has a stale run identity")
            return CancellationRequestResult(
                request=existing,
                created=False,
                too_late=row[1] in {"succeeded", "cancelled"},
            )
        if row[1] in {"succeeded", "cancelled"}:
            return CancellationRequestResult(request=request, created=False, too_late=True)
        try:
            self._publish_cancellation_request(root, path, request)
        except FileExistsError as exc:
            existing, _ = self._read_cancellation_request(root, run_id)
            if existing.run_id != run_id or existing.run_owner_token != request.run_owner_token:
                raise ProjectError(
                    "Existing cancellation request has a stale run identity"
                ) from exc
            request = existing
            created = False
        else:
            created = True
        with self._read_connection(root) as connection:
            status = connection.execute(
                "SELECT status FROM runs WHERE run_id=?", (str(run_id),)
            ).fetchone()[0]
        return CancellationRequestResult(
            request=request,
            created=created,
            too_late=status in {"succeeded", "cancelled"},
        )

    def accept_cancellation(self, root: Path, *, run_id: UUID, attempt_id: UUID | None) -> bool:
        root = root.resolve()
        path = self._owned_path(root, f"runs/{run_id}/cancel.request")
        if not path.exists():
            return False
        try:
            request, digest = self._read_cancellation_request(root, run_id)
        except (OSError, ValueError, ValidationError) as exc:
            self.append_event(
                root,
                run_id,
                code="cancellation.request_invalid",
                details={"error": str(exc)},
            )
            return False
        with self._write_connection(root) as connection, connection:
            row = connection.execute(
                """
                SELECT owner_token, status, cancellation_accepted_at,
                       cancellation_request_digest
                FROM runs WHERE run_id=?
                """,
                (str(run_id),),
            ).fetchone()
            if row is None:
                raise ProjectError(f"Unknown run {run_id}")
            if request.run_id != run_id or str(request.run_owner_token) != row[0]:
                return False
            if row[2] is not None:
                if row[3] != digest:
                    raise ProjectError("Accepted cancellation request digest changed")
                return True
            if row[1] in {"succeeded", "cancelled"}:
                return False
            accepted_at = self._now()
            updated = connection.execute(
                """
                UPDATE runs
                SET cancellation_accepted_at=?, cancellation_request_digest=?
                WHERE run_id=? AND cancellation_accepted_at IS NULL
                  AND status NOT IN ('succeeded', 'cancelled')
                """,
                (accepted_at, digest, str(run_id)),
            )
            if updated.rowcount != 1:
                return False
            if attempt_id is not None:
                connection.execute(
                    """
                    UPDATE attempts SET cancellation_accepted_at=?
                    WHERE attempt_id=? AND run_id=?
                      AND status IN ('pending', 'running')
                    """,
                    (accepted_at, str(attempt_id), str(run_id)),
                )
        return True

    def finish_cancellation(
        self,
        root: Path,
        *,
        run_id: UUID,
        attempt_id: UUID | None,
        teardown_confirmed: bool,
    ) -> RunStatus:
        now = self._now()
        if attempt_id is None:
            with self._read_connection(root) as connection:
                active = connection.execute(
                    "SELECT attempt_id FROM attempts "
                    "WHERE run_id=? AND status IN ('pending', 'running')",
                    (str(run_id),),
                ).fetchone()
            attempt_id = UUID(active[0]) if active is not None else None
        with self._write_connection(root) as connection, connection:
            run = connection.execute(
                "SELECT cancellation_accepted_at FROM runs WHERE run_id=?",
                (str(run_id),),
            ).fetchone()
            if run is None or run[0] is None:
                raise ProjectError("Cancellation was not durably accepted")
            if teardown_confirmed:
                if attempt_id is not None:
                    connection.execute(
                        """
                        UPDATE attempts
                        SET status='cancelled', finished_at=?, teardown_state='confirmed'
                        WHERE attempt_id=? AND status IN ('pending', 'running')
                        """,
                        (now, str(attempt_id)),
                    )
                connection.execute(
                    """
                    UPDATE runs SET status='cancelled', finished_at=?
                    WHERE run_id=? AND status NOT IN ('succeeded', 'cancelled')
                    """,
                    (now, str(run_id)),
                )
                return RunStatus.CANCELLED
            if attempt_id is not None:
                connection.execute(
                    """
                    UPDATE attempts
                    SET status='interrupted', finished_at=?,
                        failure_category='interrupted', teardown_state='unresolved'
                    WHERE attempt_id=? AND status IN ('pending', 'running')
                    """,
                    (now, str(attempt_id)),
                )
            connection.execute(
                """
                UPDATE runs SET status='interrupted', finished_at=?
                WHERE run_id=? AND status NOT IN ('succeeded', 'cancelled')
                """,
                (now, str(run_id)),
            )
        return RunStatus.INTERRUPTED

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
                ineligible.append(CacheIneligible(artifact_id=handle.artifact_id, reason=str(exc)))
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
        retry: bool = False,
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
            retry_of_attempt_id: str | None = None
            if retry:
                previous = connection.execute(
                    """
                    SELECT attempt_id, status, failure_category
                    FROM attempts
                    WHERE run_id=? AND node_id=?
                    ORDER BY created_at DESC, attempt_id DESC
                    LIMIT 1
                    """,
                    (str(run_id), node_id),
                ).fetchone()
                count = connection.execute(
                    "SELECT count(*) FROM attempts WHERE run_id=? AND node_id=?",
                    (str(run_id), node_id),
                ).fetchone()[0]
                if count >= 3:
                    raise RetryNotAllowedError(
                        f"Attempt limit reached for node {node_id}: 3 total attempts"
                    )
                if previous is not None:
                    if previous[1] not in {"failed", "interrupted"} or previous[2] not in {
                        FailureCategory.TRANSIENT.value,
                        FailureCategory.INTERRUPTED.value,
                    }:
                        raise RetryNotAllowedError(
                            f"Latest attempt for node {node_id} is not retryable"
                        )
                    retry_of_attempt_id = previous[0]
            connection.execute(
                """
                INSERT INTO attempts (
                    attempt_id, run_id, node_id, output_name, recipe_key,
                    input_artifacts_json, literal_inputs_json, environment_json,
                    source_verification_json, retry_of_attempt_id,
                    status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)
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
                    canonical_json_bytes({"policy": "not_applicable", "evidence": []}).decode(),
                    retry_of_attempt_id,
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
            self.mark_attempt_failed(
                root,
                attempt_id=attempt_id,
                message=str(exc),
                category=FailureCategory.TRANSIENT,
            )
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
            self._fault_hooks.before_artifact_move(artifact_directory)
            os.replace(output, artifact_directory)
            moved = True
            self._fault_hooks.after_artifact_move(artifact_directory)
            if self.accept_cancellation(root, run_id=run_id, attempt_id=attempt.attempt_id):
                raise ExecutionCancelledError(attempt.attempt_id)
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
                      AND cancellation_accepted_at IS NULL
                      AND (SELECT cancellation_accepted_at FROM runs WHERE run_id=?) IS NULL
                    """,
                    (
                        self._now(),
                        str(attempt.attempt_id),
                        str(artifact_id),
                        manifest_digest,
                        str(run_id),
                    ),
                )
                if succeeded.rowcount != 1:
                    raise ProjectError("Attempt success preconditions changed")
        except ExecutionCancelledError:
            raise
        except Exception as exc:
            if moved or artifact_directory.exists():
                raise PublicationUnresolvedError(
                    f"Artifact moved but final success commit is unresolved: {artifact_id}: {exc}"
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
        self,
        root: Path,
        *,
        attempt_id: UUID,
        message: str,
        category: FailureCategory,
    ) -> None:
        with self._write_connection(root) as connection, connection:
            connection.execute(
                """
                UPDATE attempts
                SET status='failed', finished_at=?, failure_json=?,
                    failure_category=?, teardown_state='confirmed'
                WHERE attempt_id=? AND status IN ('pending', 'running')
                """,
                (
                    self._now(),
                    canonical_json_bytes({"message": message}).decode(),
                    category.value,
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
                WHERE run_id=? AND status IN ('running', 'interrupted')
                  AND cancellation_accepted_at IS NULL
                """,
                (self._now(), str(run_id)),
            )
            if updated.rowcount != 1:
                raise ProjectError("Run did not enter succeeded state")

    def load_numbers(self, root: Path, artifact: ArtifactHandle) -> NumbersPayload:
        manifest, artifact_directory = self._validate_indexed_artifact(root.resolve(), artifact)
        payload = artifact_directory / manifest.payloads[0].path
        return NumbersPayload.model_validate_json(payload.read_bytes())

    def recover_run(self, root: Path, *, run_id: UUID) -> RecoveryResult:
        root = root.resolve()
        snapshot = self._load_run_snapshot(root, run_id)
        adopted: list[UUID] = []
        interrupted: list[UUID] = []
        warnings: list[RunWarning] = []
        with self._read_connection(root) as connection:
            connection.row_factory = sqlite3.Row
            run = connection.execute("SELECT * FROM runs WHERE run_id=?", (str(run_id),)).fetchone()
            active = connection.execute(
                """
                SELECT * FROM attempts
                WHERE run_id=? AND status IN ('pending', 'running')
                ORDER BY created_at, attempt_id
                """,
                (str(run_id),),
            ).fetchall()
            unresolved = connection.execute(
                """
                SELECT attempt_id FROM attempts
                WHERE run_id=? AND teardown_state='unresolved'
                """,
                (str(run_id),),
            ).fetchone()
        if run is None:
            raise ProjectError(f"Unknown run {run_id}")
        if run["status"] in {"succeeded", "cancelled"}:
            return RecoveryResult(run_id=run_id, status=RunStatus(run["status"]))
        active_attempt_id = UUID(active[-1]["attempt_id"]) if active else None
        if run["cancellation_accepted_at"] is not None or self.accept_cancellation(
            root, run_id=run_id, attempt_id=active_attempt_id
        ):
            if unresolved is not None:
                return RecoveryResult(run_id=run_id, status=RunStatus.INTERRUPTED)
            status = self.finish_cancellation(
                root,
                run_id=run_id,
                attempt_id=active_attempt_id,
                teardown_confirmed=True,
            )
            return RecoveryResult(run_id=run_id, status=status)

        for attempt in active:
            attempt_id = UUID(attempt["attempt_id"])
            adopted_handle: ArtifactHandle | None = None
            expected_artifact_id = attempt["expected_artifact_id"]
            if expected_artifact_id is not None:
                if self.accept_cancellation(root, run_id=run_id, attempt_id=attempt_id):
                    status = self.finish_cancellation(
                        root,
                        run_id=run_id,
                        attempt_id=attempt_id,
                        teardown_confirmed=True,
                    )
                    return RecoveryResult(run_id=run_id, status=status)
                try:
                    adopted_handle = self._adopt_orphan(root, snapshot=snapshot, attempt=attempt)
                except (OSError, ValueError, ValidationError, json.JSONDecodeError) as exc:
                    warning = RunWarning(
                        code="orphan.publication_refused",
                        message=f"Orphan publication was not adopted: {exc}",
                    )
                    warnings.append(warning)
                    self.append_event(
                        root,
                        run_id,
                        code="orphan.publication_refused",
                        attempt_id=attempt_id,
                        details={"error": str(exc)},
                    )
            if adopted_handle is not None:
                adopted.append(attempt_id)
                self.append_event(
                    root,
                    run_id,
                    code="orphan.publication_adopted",
                    node_id=attempt["node_id"],
                    attempt_id=attempt_id,
                )
                continue
            with self._write_connection(root) as connection, connection:
                connection.execute(
                    """
                    UPDATE attempts
                    SET status='interrupted', finished_at=?,
                        failure_category='interrupted', teardown_state='confirmed'
                    WHERE attempt_id=? AND status IN ('pending', 'running')
                    """,
                    (self._now(), str(attempt_id)),
                )
            interrupted.append(attempt_id)
            self.append_event(
                root,
                run_id,
                code="attempt.interrupted",
                node_id=attempt["node_id"],
                attempt_id=attempt_id,
            )

        if self.accept_cancellation(root, run_id=run_id, attempt_id=None):
            status = self.finish_cancellation(
                root,
                run_id=run_id,
                attempt_id=None,
                teardown_confirmed=True,
            )
            return RecoveryResult(
                run_id=run_id,
                status=status,
                adopted_attempts=tuple(adopted),
                interrupted_attempts=tuple(interrupted),
                warnings=tuple(warnings),
            )
        outputs = self._load_valid_run_outputs(root, run_id)
        required = {snapshot.route.sequence.node_id, snapshot.route.scale.node_id}
        if required.issubset(outputs):
            self.mark_run_succeeded(root, run_id=run_id)
            status = RunStatus.SUCCEEDED
        else:
            with self._write_connection(root) as connection, connection:
                updated = connection.execute(
                    """
                    UPDATE runs SET status='interrupted', finished_at=?
                    WHERE run_id=? AND status='running'
                    """,
                    (self._now(), str(run_id)),
                )
            status = (
                RunStatus.INTERRUPTED if updated.rowcount == 1 else RunStatus(run["status"])
            )
        return RecoveryResult(
            run_id=run_id,
            status=status,
            adopted_attempts=tuple(adopted),
            interrupted_attempts=tuple(interrupted),
            warnings=tuple(warnings),
        )

    def prepare_retry(
        self, root: Path, *, run_id: UUID
    ) -> tuple[RunSnapshot, dict[str, ArtifactHandle]]:
        root = root.resolve()
        snapshot = self._load_run_snapshot(root, run_id)
        with self._read_connection(root) as connection:
            connection.row_factory = sqlite3.Row
            run = connection.execute("SELECT * FROM runs WHERE run_id=?", (str(run_id),)).fetchone()
            active = connection.execute(
                """
                SELECT attempt_id FROM attempts
                WHERE run_id=? AND status IN ('pending', 'running')
                """,
                (str(run_id),),
            ).fetchone()
            unresolved = connection.execute(
                """
                SELECT attempt_id FROM attempts
                WHERE run_id=? AND teardown_state='unresolved'
                """,
                (str(run_id),),
            ).fetchone()
            non_retryable = connection.execute(
                """
                SELECT attempt_id FROM attempts
                WHERE run_id=? AND status='failed'
                  AND (failure_category IS NULL OR failure_category!='transient')
                """,
                (str(run_id),),
            ).fetchone()
        if run is None:
            raise ProjectError(f"Unknown run {run_id}")
        if run["status"] in {"succeeded", "cancelled"}:
            raise RetryNotAllowedError(f"Run {run_id} is terminal: {run['status']}")
        if unresolved is not None:
            raise RetryNotAllowedError("Unresolved teardown blocks retry")
        if run["cancellation_accepted_at"] is not None:
            raise RetryNotAllowedError("Accepted cancellation blocks retry")
        try:
            request, _ = self._read_cancellation_request(root, run_id)
        except FileNotFoundError:
            request = None
        except (OSError, ValueError, ValidationError):
            request = None
        if request is not None and str(request.run_owner_token) == run["owner_token"]:
            raise RetryNotAllowedError("Pending cancellation request blocks retry")
        if active is not None:
            raise RetryNotAllowedError("Recovery is required before retry")
        if non_retryable is not None:
            raise RetryNotAllowedError("A non-retryable attempt blocks retry")
        if run["status"] not in {"failed", "interrupted"}:
            raise RetryNotAllowedError(f"Run {run_id} is not retryable")
        outputs = self._load_valid_run_outputs(root, run_id)
        required_nodes = (snapshot.route.sequence.node_id, snapshot.route.scale.node_id)
        with self._read_connection(root) as connection:
            for node_id in required_nodes:
                if node_id in outputs:
                    continue
                attempts = connection.execute(
                    """
                    SELECT status, failure_category FROM attempts
                    WHERE run_id=? AND node_id=?
                    ORDER BY created_at DESC, attempt_id DESC
                    """,
                    (str(run_id), node_id),
                ).fetchall()
                if len(attempts) >= 3:
                    raise RetryNotAllowedError(
                        f"Attempt limit reached for node {node_id}: 3 total attempts"
                    )
                if attempts and (
                    attempts[0][0] not in {"failed", "interrupted"}
                    or attempts[0][1]
                    not in {
                        FailureCategory.TRANSIENT.value,
                        FailureCategory.INTERRUPTED.value,
                    }
                ):
                    raise RetryNotAllowedError(
                        f"Latest attempt for node {node_id} is not retryable"
                    )
        with self._write_connection(root) as connection, connection:
            updated = connection.execute(
                """
                UPDATE runs
                SET status='running', finished_at=NULL, failure_json=NULL
                WHERE run_id=? AND status IN ('failed', 'interrupted')
                  AND cancellation_accepted_at IS NULL
                """,
                (str(run_id),),
            )
            if updated.rowcount != 1:
                raise RetryNotAllowedError("Run retry preconditions changed")
        return snapshot, outputs

    def _load_run_snapshot(self, root: Path, run_id: UUID) -> RunSnapshot:
        with self._read_connection(root) as connection:
            row = connection.execute(
                """
                SELECT project_id, owner_token, snapshot_path, snapshot_digest
                FROM runs WHERE run_id=?
                """,
                (str(run_id),),
            ).fetchone()
        if row is None:
            raise ProjectError(f"Unknown run {run_id}")
        path = self._owned_path(root, row[2])
        payload = path.read_bytes()
        if sha256_bytes(payload) != row[3]:
            raise ProjectError("Run snapshot digest mismatch")
        snapshot = RunSnapshot.model_validate_json(payload)
        if (
            snapshot.run_id != run_id
            or str(snapshot.project_id) != row[0]
            or str(snapshot.owner_token) != row[1]
        ):
            raise ProjectError("Run snapshot identity mismatch")
        project = self.inspect_project(root)
        if snapshot.project_id != project.document.project_id:
            raise ProjectError("Run snapshot project identity mismatch")
        return snapshot

    def _load_valid_run_outputs(self, root: Path, run_id: UUID) -> dict[str, ArtifactHandle]:
        with self._read_connection(root) as connection:
            rows = connection.execute(
                """
                SELECT o.node_id, a.artifact_id, a.artifact_type, a.contract_version,
                       a.recipe_key, a.semantic_digest, a.manifest_path
                FROM run_outputs o
                JOIN artifacts a ON a.artifact_id=o.artifact_id
                WHERE o.run_id=?
                ORDER BY o.node_id
                """,
                (str(run_id),),
            ).fetchall()
        outputs: dict[str, ArtifactHandle] = {}
        for row in rows:
            handle = ArtifactHandle(
                artifact_id=UUID(row[1]),
                artifact_type=row[2],
                contract_version=row[3],
                recipe_key=row[4],
                semantic_digest=row[5],
                manifest_path=row[6],
            )
            self._validate_indexed_artifact(root, handle)
            outputs[row[0]] = handle
        return outputs

    def show_run(self, root: Path, run_id: UUID) -> str:
        root = root.resolve()
        with self._read_connection(root) as connection:
            connection.row_factory = sqlite3.Row
            run = connection.execute("SELECT * FROM runs WHERE run_id=?", (str(run_id),)).fetchone()
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

    def _adopt_orphan(
        self,
        root: Path,
        *,
        snapshot: RunSnapshot,
        attempt: sqlite3.Row,
    ) -> ArtifactHandle | None:
        artifact_id = UUID(attempt["expected_artifact_id"])
        artifact_directory = self._owned_path(root, f"artifacts/{attempt['node_id']}/{artifact_id}")
        if not artifact_directory.is_dir():
            return None
        manifest_path = self._owned_path(
            root,
            f"artifacts/{attempt['node_id']}/{artifact_id}/manifest.json",
        )
        manifest_bytes = manifest_path.read_bytes()
        if sha256_bytes(manifest_bytes) != attempt["expected_manifest_digest"]:
            raise ValueError("Orphan manifest digest mismatch")
        manifest = ArtifactManifest.model_validate_json(manifest_bytes)
        if attempt["node_id"] == snapshot.route.sequence.node_id:
            node = snapshot.route.sequence
            output = node.output
            expected_recipe_key = sequence_recipe_key(start=node.start, settings=node.settings)
            expected_lineage: tuple[ArtifactInputLineage, ...] = ()
            expected_literal_inputs = {"start": node.start}
        elif attempt["node_id"] == snapshot.route.scale.node_id:
            node = snapshot.route.scale
            output = node.output
            inputs = self._load_valid_run_outputs(root, snapshot.run_id)
            input_artifact = inputs.get(snapshot.route.sequence.node_id)
            if input_artifact is None:
                raise ValueError("Orphan publication has no valid upstream run output")
            expected_recipe_key = scale_recipe_key(
                settings=node.settings, input_artifact=input_artifact
            )
            expected_lineage = (
                ArtifactInputLineage(
                    input_name="numbers",
                    artifact_id=input_artifact.artifact_id,
                    artifact_type=input_artifact.artifact_type,
                    contract_version=input_artifact.contract_version,
                    semantic_digest=input_artifact.semantic_digest,
                    recipe_key=input_artifact.recipe_key,
                ),
            )
            expected_literal_inputs = {}
        else:
            raise ValueError("Attempt node is not present in the frozen route")
        expected_inputs = tuple(
            UUID(value) for value in json.loads(attempt["input_artifacts_json"])
        )
        if (
            attempt["run_id"] != str(snapshot.run_id)
            or attempt["output_name"] != output.output_name
            or attempt["recipe_key"] != expected_recipe_key
            or json.loads(attempt["literal_inputs_json"]) != expected_literal_inputs
            or expected_inputs != tuple(item.artifact_id for item in expected_lineage)
            or manifest.artifact_id != artifact_id
            or manifest.producer_run_id != snapshot.run_id
            or manifest.producer_attempt_id != UUID(attempt["attempt_id"])
            or manifest.producer_node_id != attempt["node_id"]
            or manifest.recipe_key != attempt["recipe_key"]
            or manifest.artifact_type != output.artifact_type
            or manifest.contract_version != output.contract_version
            or manifest.input_lineage != expected_lineage
            or manifest.validation.validator_id != f"{output.artifact_type}.integrity"
            or manifest.validation.validator_version != 1
        ):
            raise ValueError("Orphan publication identity or contract mismatch")
        if len(manifest.payloads) != 1:
            raise ValueError("Orphan artifact must contain exactly one payload")
        expected_names = {"manifest.json", manifest.payloads[0].path}
        if {path.name for path in artifact_directory.iterdir()} != expected_names:
            raise ValueError("Orphan artifact contains unexpected files")
        payload = manifest.payloads[0]
        payload_path = self._artifact_payload_path(artifact_directory, payload.path)
        data = payload_path.read_bytes()
        if len(data) != payload.size or sha256_bytes(data) != payload.sha256:
            raise ValueError("Orphan payload size or digest mismatch")
        if manifest.artifact_type == NUMBERS_ARTIFACT_TYPE:
            parsed = NumbersPayload.model_validate_json(data)
        elif manifest.artifact_type == SCALED_ARTIFACT_TYPE:
            parsed = ScaledNumbersPayload.model_validate_json(data)
        else:
            raise ValueError("Unsupported orphan artifact type")
        if semantic_digest(parsed) != manifest.semantic_digest:
            raise ValueError("Orphan semantic digest mismatch")
        relative_manifest = manifest_path.relative_to(root).as_posix()
        now = self._now()
        with self._write_connection(root) as connection, connection:
            run = connection.execute(
                "SELECT cancellation_accepted_at FROM runs WHERE run_id=?",
                (str(snapshot.run_id),),
            ).fetchone()
            current = connection.execute(
                """
                SELECT status, cancellation_accepted_at,
                       expected_artifact_id, expected_manifest_digest
                FROM attempts WHERE attempt_id=?
                """,
                (attempt["attempt_id"],),
            ).fetchone()
            if (
                run is None
                or run[0] is not None
                or current is None
                or current[0] not in {"pending", "running"}
                or current[1] is not None
                or current[2] != str(artifact_id)
                or current[3] != attempt["expected_manifest_digest"]
            ):
                raise ValueError("Orphan adoption preconditions changed")
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
                    attempt["attempt_id"],
                    str(snapshot.run_id),
                    attempt["node_id"],
                    attempt["output_name"],
                    manifest.artifact_type,
                    manifest.contract_version,
                    manifest.recipe_key,
                    manifest.semantic_digest,
                    relative_manifest,
                    attempt["expected_manifest_digest"],
                    now,
                ),
            )
            connection.execute(
                """
                INSERT INTO run_outputs (
                    run_id, node_id, output_name, artifact_id, binding_kind, bound_at
                ) VALUES (?, ?, ?, ?, 'recovered', ?)
                """,
                (
                    str(snapshot.run_id),
                    attempt["node_id"],
                    attempt["output_name"],
                    str(artifact_id),
                    now,
                ),
            )
            connection.execute(
                """
                UPDATE attempts
                SET status='succeeded', finished_at=?, teardown_state='confirmed'
                WHERE attempt_id=?
                """,
                (now, attempt["attempt_id"]),
            )
        return ArtifactHandle(
            artifact_id=artifact_id,
            artifact_type=manifest.artifact_type,
            contract_version=manifest.contract_version,
            recipe_key=manifest.recipe_key,
            semantic_digest=manifest.semantic_digest,
            manifest_path=relative_manifest,
        )

    def _read_cancellation_request(
        self, root: Path, run_id: UUID
    ) -> tuple[CancellationRequest, str]:
        path = self._owned_path(root, f"runs/{run_id}/cancel.request")
        size = path.stat().st_size
        if size > 4096:
            raise ValueError("Cancellation request exceeds its size limit")
        payload = path.read_bytes()
        if len(payload) != size:
            raise ValueError("Cancellation request changed while being read")
        request = CancellationRequest.model_validate_json(payload)
        if request.run_id != run_id:
            raise ValueError("Cancellation request run ID mismatch")
        return request, sha256_bytes(payload)

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
        candidate = artifact_directory
        for part in parts:
            candidate /= part
            if candidate.is_symlink() or candidate.is_junction():
                raise ValueError("Manifest payload must not traverse a filesystem redirection")
        path = candidate.resolve()
        if not path.is_relative_to(artifact_directory.resolve()):
            raise ValueError("Manifest payload escapes its artifact directory")
        return path

    def _publish_cancellation_request(
        self, root: Path, path: Path, request: CancellationRequest
    ) -> None:
        payload = request.model_dump_json(indent=2).encode("utf-8") + b"\n"
        if len(payload) > 4096:
            raise ProjectError("Cancellation request exceeds its size limit")
        if CancellationRequest.model_validate_json(payload) != request:
            raise ProjectError("Serialized cancellation request failed validation")

        temporary: Path | None = None
        try:
            with NamedTemporaryFile(
                mode="w+b",
                dir=path.parent,
                prefix=".cancel-request-",
                suffix=".tmp",
                delete=False,
            ) as stream:
                temporary = Path(stream.name)
                if stream.write(payload) != len(payload):
                    raise OSError("Could not write complete cancellation request")
                stream.flush()
                os.fsync(stream.fileno())
            temporary = self._owned_path(root, temporary.relative_to(root).as_posix())
            self._fault_hooks.before_cancellation_request_publish(temporary)
            os.link(temporary, path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

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
        candidate = root
        for part in parts:
            candidate /= part
            if candidate.is_symlink() or candidate.is_junction():
                raise ProjectError("Execution path must not traverse a filesystem redirection")
        path = candidate.resolve()
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
