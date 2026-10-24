"""Local SQLite/filesystem execution state for fake and concrete view routes."""

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

from splatforge.adapters.artifact_validation import (
    MAX_MANIFEST_BYTES,
    ArtifactValidationContext,
    ValidatedArtifact,
    ValidationStrength,
    validate_feature_lineage,
    validate_pair_lineage,
    validate_published_artifact,
    validate_workspace_output,
)
from splatforge.adapters.cleanup_storage import CleanupStorageMixin
from splatforge.adapters.dataset_storage import DatasetStorageMixin
from splatforge.adapters.project_lock import (
    ProjectWriterLockFactory,
    WindowsProjectWriterLock,
)
from splatforge.adapters.project_storage import LocalProjectStore
from splatforge.adapters.training_storage import TrainingStorageMixin
from splatforge.adapters.validation_storage import ValidationStorageMixin
from splatforge.application.execution import (
    ExecutionCancelledError,
    PublicationUnresolvedError,
    RetryNotAllowedError,
    UnresolvedExecutionError,
)
from splatforge.application.progress_contracts import (
    AttemptLifecycle,
    OutputBinding,
    RunProgressEvidence,
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
    DatasetComponentRoute,
    DatasetRoute,
    FailureCategory,
    FakeRoute,
    FeatureExtractionRoute,
    FeatureMatchingRoute,
    GeometricVerificationRoute,
    MappingRoute,
    PairSelectionRoute,
    ReconstructionEvidenceRoute,
    RecoveryResult,
    RetrievalBuildRoute,
    RunSnapshot,
    RunStatus,
    RunWarning,
    SharpestViewPreparationRoute,
    TrainingJobRoute,
    TrainingRoute,
    ValidationResult,
    ViewPreparationRoute,
)
from splatforge.core.fake_pipeline import (
    NumbersPayload,
    canonical_json_bytes,
    scale_recipe_key,
    sequence_recipe_key,
    sha256_bytes,
)
from splatforge.core.features import (
    MAX_FEATURE_METADATA_BYTES,
    LocalFeatureSet,
    feature_recipe_key,
)
from splatforge.core.geometry import CameraPriorSet, VerifiedGeometrySet
from splatforge.core.matching import MAX_MATCH_METADATA_BYTES, MatchSet
from splatforge.core.media import SourceOccurrence, VerificationPolicyId
from splatforge.core.pairs import (
    PAIR_ARTIFACT_TYPE,
    PairSet,
    SequentialSettings,
    exhaustive_recipe_key,
    generate_pairs,
    project_pairing_universe,
    sequential_recipe_key,
)
from splatforge.core.process import MAX_PROCESS_RECORD_BYTES, ProcessInvocationEvidence
from splatforge.core.progress import PipelineProgressSnapshot
from splatforge.core.project import ProjectDocument
from splatforge.core.quality import (
    QualityReport,
    SharpestSelectedViewSet,
    quality_recipe_key,
    sharpest_selection_recipe_key,
    validate_quality_against_candidate,
    validate_sharpest_against_inputs,
)
from splatforge.core.reconstruction import (
    MAX_RECONSTRUCTION_METADATA_BYTES,
    ClassicalMappingReceipt,
    ReconstructionReader,
    ReconstructionSet,
)
from splatforge.core.retrieval import RetrievalRepresentationSet
from splatforge.core.views import (
    CandidateViewSet,
    SelectedViewSet,
    candidate_recipe_key,
    selection_recipe_key,
    validate_selected_against_candidate,
)


def _no_fault(_path: Path) -> None:
    return


MAX_ATTEMPT_DIAGNOSTIC_BYTES = 4 * 1024 * 1024
_DIAGNOSTIC_RESERVE_BYTES = 512


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


class LocalExecutionRepository(
    ValidationStorageMixin, DatasetStorageMixin, TrainingStorageMixin, CleanupStorageMixin
):
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
        self._event_sequences: dict[UUID, int] = {}
        self._validation_context: ArtifactValidationContext | None = None

    @contextmanager
    def validation_operation(self) -> Iterator[ArtifactValidationContext]:
        """Explicit scope for read-only operations and nested repository loaders."""
        if self._validation_context is not None:
            yield self._validation_context
            return
        self._validation_context = ArtifactValidationContext()
        try:
            yield self._validation_context
        finally:
            self._validation_context = None

    @contextmanager
    def writer(
        self, root: Path, *, owner_token: UUID, operation: str = "fake-run"
    ) -> Iterator[None]:
        root = root.resolve()
        # Read-only preflight avoids creating a lock for an invalid or unsupported project.
        self._project_store.inspect(root)
        with (
            self._lock_factory(root / "project.lock") as lease,
            self.validation_operation(),
        ):
            # Refuse a raced unsupported format before changing lock diagnostics.
            self._project_store.inspect(root)
            lease.write_diagnostics(operation=operation, owner_token=owner_token)
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
            unresolved_teardown = connection.execute(
                """
                SELECT attempt_id FROM attempts
                WHERE teardown_state='unresolved'
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
        if unresolved_teardown is not None:
            raise UnresolvedExecutionError(
                "Unresolved external process teardown blocks new execution: "
                + unresolved_teardown[0]
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
        self._event_sequences[snapshot.run_id] = 0
        self._fault_hooks.after_run_record(root)

    def request_cancellation(self, root: Path, *, run_id: UUID) -> CancellationRequestResult:
        root = root.resolve()
        project = self.inspect_project(root)
        if project.state_version in {1, 2}:
            raise ProjectError("State upgrade required before cancellation")
        if project.state_version not in {3, 4}:
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
            previous_sequence = self._event_sequences.get(run_id)
            if previous_sequence is None:
                previous_sequence = self._last_event_sequence(path)
            sequence = previous_sequence + 1
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
            if len(data) > 1024 * 1024:
                raise ValueError("Execution event exceeds its 1 MiB bound")
            with path.open("ab") as stream:
                if stream.write(data) != len(data):
                    raise OSError("Could not append complete execution event")
                stream.flush()
                os.fsync(stream.fileno())
            self._event_sequences[run_id] = sequence
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

    @staticmethod
    def _last_event_sequence(path: Path) -> int:
        if not path.exists():
            return 0
        size = path.stat().st_size
        with path.open("rb") as stream:
            stream.seek(max(0, size - 1024 * 1024))
            tail = stream.read(1024 * 1024)
        lines = tail.splitlines()
        if not lines:
            return 0
        return int(json.loads(lines[-1].decode("utf-8"))["sequence"])

    def append_process_evidence(
        self, root: Path, run_id: UUID, attempt_id: UUID, evidence: ProcessInvocationEvidence
    ) -> RunWarning | None:
        """Best-effort diagnostic append; SQLite alone decides numerical status."""
        try:
            root = root.resolve()
            with self._read_connection(root) as connection:
                row = connection.execute(
                    "SELECT run_id FROM attempts WHERE attempt_id=?", (str(attempt_id),)
                ).fetchone()
            if row is None or row[0] != str(run_id):
                raise ValueError("Process diagnostics require the exact owning run/attempt")
            path = self._owned_path(root, f"runs/{run_id}/attempts/{attempt_id}/process.jsonl")
            path.parent.mkdir(parents=True, exist_ok=True)
            evidence = ProcessInvocationEvidence.model_validate(evidence.model_dump())
            record = evidence.model_dump(mode="json")
            record.update({"run_id": str(run_id), "attempt_id": str(attempt_id)})
            data = canonical_json_bytes(record) + b"\n"
            if len(data) > MAX_PROCESS_RECORD_BYTES:
                raise ValueError("Process diagnostic record exceeds its byte bound")
            size = path.stat().st_size if path.exists() else 0
            if size:
                with path.open("rb") as stream:
                    stream.seek(max(0, size - _DIAGNOSTIC_RESERVE_BYTES))
                    tail = stream.read(_DIAGNOSTIC_RESERVE_BYTES)
                if not tail.endswith(b"\n") or not tail.splitlines():
                    raise ValueError("Process diagnostic tail is incomplete")
                last = tail.splitlines()[-1]
                if b'"retention_limit_reached":true' in last:
                    return RunWarning(
                        code="process.diagnostics_truncated",
                        message="Attempt process diagnostic retention limit was reached",
                    )
            if size + len(data) > MAX_ATTEMPT_DIAGNOSTIC_BYTES - _DIAGNOSTIC_RESERVE_BYTES:
                data = canonical_json_bytes({
                    "diagnostic_schema_version": 1, "run_id": str(run_id),
                    "attempt_id": str(attempt_id), "diagnostics_truncated": True,
                    "retention_limit_reached": True,
                }) + b"\n"
                if size + len(data) > MAX_ATTEMPT_DIAGNOSTIC_BYTES:
                    raise ValueError("Existing process diagnostics exceed retention bound")
                truncated = True
            else:
                truncated = False
            with path.open("ab") as stream:
                if stream.write(data) != len(data):
                    raise OSError("Could not append complete process diagnostic record")
                stream.flush()
                os.fsync(stream.fileno())
            if truncated:
                return RunWarning(
                    code="process.diagnostics_truncated",
                    message="Attempt process diagnostic retention limit was reached",
                )
        except (OSError, ValueError, TypeError, sqlite3.Error, ProjectError) as exc:
            return RunWarning(
                code="process.diagnostics_append_failed",
                message=f"Optional process diagnostic append failed: {str(exc)[:512]}",
            )
        return None

    def _process_diagnostic_summary(
        self, root: Path, run_id: UUID, attempt_id: UUID
    ) -> dict[str, object]:
        relative = f"runs/{run_id}/attempts/{attempt_id}/process.jsonl"
        summary: dict[str, object] = {
            "path": relative, "exists": False, "invocation_count": 0, "truncated": False,
        }
        try:
            path = self._owned_path(root, relative)
            if not path.exists():
                return summary
            summary["exists"] = True
            if path.stat().st_size > MAX_ATTEMPT_DIAGNOSTIC_BYTES:
                raise ValueError("Process diagnostics exceed retention bound")
            count = 0
            with path.open("rb") as stream:
                while line := stream.readline(MAX_PROCESS_RECORD_BYTES + 1):
                    if len(line) > MAX_PROCESS_RECORD_BYTES:
                        raise ValueError("Process diagnostic line exceeds record bound")
                    record = json.loads(line)
                    if not isinstance(record, dict):
                        raise ValueError("Process diagnostic record must be an object")
                    if record.get("run_id") != str(run_id) or record.get("attempt_id") != str(
                        attempt_id
                    ):
                        raise ValueError("Process diagnostic owner identity mismatch")
                    if "invocation_index" in record:
                        count += 1
                    if record.get("diagnostics_truncated") or any(
                        record.get(name) for name in (
                            "stdout_truncated", "stderr_truncated", "stdout_excerpt_truncated",
                            "stderr_excerpt_truncated",
                        )
                    ):
                        summary["truncated"] = True
            summary["invocation_count"] = count
        except (OSError, ValueError, ProjectError) as exc:
            summary["warning"] = str(exc)[:512]
            summary["truncated"] = True
        return summary

    def find_cache(
        self,
        root: Path,
        *,
        recipe_key: str,
        artifact_type: str,
        contract_version: int,
        source_requirements: tuple[SourceOccurrence, ...] = (),
        verification_policy: VerificationPolicyId | None = None,
    ) -> CacheLookup:
        root = root.resolve()
        with self._read_connection(root) as connection:
            rows = connection.execute(
                """
                SELECT a.artifact_id, a.recipe_key, a.semantic_digest, a.manifest_path,
                       t.source_verification_json
                FROM artifacts a
                JOIN attempts t ON t.attempt_id = a.producer_attempt_id
                WHERE a.recipe_key=? AND a.artifact_type=? AND a.contract_version=?
                  AND t.status='succeeded'
                ORDER BY a.published_at DESC, a.artifact_id DESC
                """,
                (recipe_key, artifact_type, contract_version),
            ).fetchall()
        ineligible: list[CacheIneligible] = []
        context = self._validation_context or ArtifactValidationContext()
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
                self._require_cache_verification(
                    row[4],
                    sources=source_requirements,
                    policy=verification_policy,
                )
            except (ValueError, json.JSONDecodeError) as exc:
                ineligible.append(CacheIneligible(artifact_id=handle.artifact_id, reason=str(exc)))
                continue
            try:
                self._validate_indexed_artifact(root, handle, context=context)
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
        environment: dict[str, object] | None = None,
        source_verification: dict[str, object] | None = None,
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
                        environment
                        or {
                            "adapter_id": "splatforge.fake_python",
                            "adapter_version": 1,
                            "python_version": platform.python_version(),
                        }
                    ).decode(),
                    canonical_json_bytes(
                        source_verification or {"policy": "not_applicable", "evidence": []}
                    ).decode(),
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

    def update_attempt_provenance(
        self,
        root: Path,
        *,
        attempt_id: UUID,
        environment: dict[str, object],
        source_verification: dict[str, object],
    ) -> None:
        environment_json = canonical_json_bytes(environment).decode()
        verification_json = canonical_json_bytes(source_verification).decode()
        if len(environment_json.encode("utf-8")) > 1024 * 1024:
            raise ProjectError("Attempt environment provenance exceeds 1 MiB")
        if len(verification_json.encode("utf-8")) > 16 * 1024 * 1024:
            raise ProjectError("Attempt source-verification provenance exceeds 16 MiB")
        with self._write_connection(root) as connection, connection:
            updated = connection.execute(
                """
                UPDATE attempts
                SET environment_json=?, source_verification_json=?
                WHERE attempt_id=? AND status='running'
                """,
                (environment_json, verification_json, str(attempt_id)),
            )
            if updated.rowcount != 1:
                raise ProjectError("Running attempt was unavailable for provenance update")

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
        next_checkpoint = 0.0

        def dataset_checkpoint():
            nonlocal next_checkpoint
            if time.monotonic() >= next_checkpoint:
                next_checkpoint = time.monotonic() + 0.25
                if self.accept_cancellation(root, run_id=run_id, attempt_id=attempt.attempt_id):
                    raise ExecutionCancelledError(attempt.attempt_id)

        validated = validate_workspace_output(
            output, artifact_type, checkpoint=dataset_checkpoint
            if artifact_type.startswith(("dataset.", "training.")) else None)
        content_digest = validated.semantic_digest
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
            payloads=validated.payloads,
            validation=ValidationResult(
                validator_id=f"{artifact_type}.integrity", validator_version=1
            ),
        )
        if isinstance(validated.parsed, PairSet):
            validate_pair_lineage(validated.parsed, manifest)
        if isinstance(validated.parsed, LocalFeatureSet):
            validate_feature_lineage(validated.parsed, manifest)
        if artifact_type.startswith("training."):
            from splatforge.adapters.training_artifacts import validate_training_lineage

            route = self._load_run_snapshot(root, run_id).route
            if not isinstance(route, TrainingRoute):
                raise ValueError("training.invalid_producer_route")
            self.validate_training_route(root, route, validated.parsed, output)
            validate_training_lineage(validated.parsed, manifest)
        if artifact_type.startswith("dataset."):
            from splatforge.adapters.dataset_artifacts import (
                require_dataset_source,
                validate_dataset_lineage,
            )
            from splatforge.application.dataset import (
                require_dataset_inputs,
                require_dataset_payload,
            )

            route = self._load_run_snapshot(root, run_id).route
            if not isinstance(route, DatasetRoute):
                raise ValueError("M10 publication requires its exact producer route")
            validate_dataset_lineage(validated.parsed, manifest)
            require_dataset_inputs(self, root, route)
            require_dataset_payload(route, validated.parsed, exact_lineage=True)
            require_dataset_source(root, self, route, output, validated.parsed,
                                   checkpoint=dataset_checkpoint)
        if isinstance(validated.parsed, RetrievalRepresentationSet):
            from splatforge.adapters.retrieval_artifacts import validate_retrieval_lineage

            validate_retrieval_lineage(validated.parsed, manifest)
        if isinstance(validated.parsed, (MatchSet, VerifiedGeometrySet)):
            from splatforge.adapters.matching_artifacts import validate_matching_lineage

            validate_matching_lineage(validated.parsed, manifest)
        manifest_bytes = manifest.model_dump_json(indent=2).encode("utf-8") + b"\n"
        if len(manifest_bytes) > MAX_MANIFEST_BYTES:
            raise ValueError("Artifact manifest exceeds its explicit size limit")
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

    def mark_external_interrupted(
        self,
        root: Path,
        *,
        run_id: UUID,
        attempt_id: UUID,
        message: str,
    ) -> None:
        now = self._now()
        with self._write_connection(root) as connection, connection:
            connection.execute(
                """
                UPDATE attempts
                SET status='interrupted', finished_at=?, failure_json=?,
                    failure_category='interrupted', teardown_state='unresolved'
                WHERE attempt_id=? AND run_id=? AND status IN ('pending', 'running')
                """,
                (
                    now,
                    canonical_json_bytes({"message": message}).decode(),
                    str(attempt_id),
                    str(run_id),
                ),
            )
            connection.execute(
                """
                UPDATE runs SET status='interrupted', finished_at=?, failure_json=?
                WHERE run_id=? AND status='running'
                """,
                (
                    now,
                    canonical_json_bytes({"message": message}).decode(),
                    str(run_id),
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
        _, _, validated = self._validate_indexed_artifact(root.resolve(), artifact)
        if not isinstance(validated.parsed, NumbersPayload):
            raise ValueError("Artifact is not a NumbersPayload")
        return validated.parsed

    def load_candidate_views(self, root: Path, artifact: ArtifactHandle) -> CandidateViewSet:
        _, _, validated = self._validate_indexed_artifact(root.resolve(), artifact)
        if not isinstance(validated.parsed, CandidateViewSet):
            raise ValueError("Artifact is not a CandidateViewSet")
        return validated.parsed

    def load_selected_views(
        self, root: Path, artifact: ArtifactHandle
    ) -> SelectedViewSet | SharpestSelectedViewSet:
        _, _, validated = self._validate_indexed_artifact(root.resolve(), artifact)
        if not isinstance(validated.parsed, (SelectedViewSet, SharpestSelectedViewSet)):
            raise ValueError("Artifact is not a supported SelectedViewSet")
        return validated.parsed

    def resolve_run_output(
        self,
        root: Path,
        run_id: UUID,
        node_id: str,
        output_name: str,
    ) -> ArtifactHandle:
        snapshot = self._load_run_snapshot(root, run_id)
        if isinstance(snapshot.route, (ViewPreparationRoute, SharpestViewPreparationRoute)):
            allowed = {(snapshot.route.candidate.node_id, "candidate_set"),
                       (snapshot.route.selection.node_id, "selected_set")}
        elif isinstance(snapshot.route, (FeatureExtractionRoute, PairSelectionRoute,
                                         RetrievalBuildRoute,
                                         FeatureMatchingRoute, GeometricVerificationRoute,
                                         MappingRoute, ReconstructionEvidenceRoute, DatasetRoute,
                                         TrainingRoute)):
            allowed = {(snapshot.route.node_id, snapshot.route.target.output_name)}
        else:
            allowed = set()
        if (node_id, output_name) not in allowed:
            if node_id in {"candidate_views", "selected_views"}:
                raise ValueError("--views-run requires a completed views preparation run")
            raise ValueError("Requested run does not produce the exact required stage output")
        with self._read_connection(root) as connection:
            run = connection.execute(
                "SELECT status FROM runs WHERE run_id=?", (str(run_id),)
            ).fetchone()
            row = connection.execute(
                """SELECT a.artifact_id, a.artifact_type, a.contract_version, a.recipe_key,
                          a.semantic_digest, a.manifest_path
                   FROM run_outputs o JOIN artifacts a ON a.artifact_id=o.artifact_id
                   WHERE o.run_id=? AND o.node_id=? AND o.output_name=?""",
                (str(run_id), node_id, output_name),
            ).fetchone()
        if run is None or run[0] != "succeeded":
            if node_id in {"candidate_views", "selected_views"}:
                raise ValueError("--views-run must reference a succeeded views run")
            flag = {"local_features": "--features-run", "pair_set": "--pairs-run",
                    "raw_matches": "--matches-run"}.get(node_id, "Upstream run")
            raise ValueError(f"{flag} must reference a succeeded compatible run")
        if row is None:
            label = "Views run" if node_id in {"candidate_views", "selected_views"} else "Run"
            raise ValueError(f"{label} has no indexed {node_id}/{output_name} output")
        handle = ArtifactHandle(
            artifact_id=UUID(row[0]),
            artifact_type=row[1],
            contract_version=row[2],
            recipe_key=row[3],
            semantic_digest=row[4],
            manifest_path=row[5],
        )
        self._validate_indexed_artifact(root, handle, metadata_only=True)
        return handle

    def load_pairing_inputs(
        self,
        root: Path,
        candidate: ArtifactHandle,
        selected: ArtifactHandle,
    ) -> tuple[CandidateViewSet, SelectedViewSet | SharpestSelectedViewSet]:
        result = []
        with self.validation_operation():
            for handle in (candidate, selected):
                _, _, validated = self._validate_indexed_artifact(root, handle, metadata_only=True)
                result.append(validated.parsed)
        if not isinstance(result[0], CandidateViewSet) or not isinstance(
            result[1], (SelectedViewSet, SharpestSelectedViewSet)
        ):
            raise ValueError("Pairing requires CandidateViewSet and a supported SelectedViewSet")
        project_pairing_universe(result[0], result[1])
        return result[0], result[1]

    def load_pair_set(self, root: Path, handle: ArtifactHandle) -> PairSet:
        _, _, validated = self._validate_indexed_artifact(root, handle)
        parsed = validated.parsed
        if not isinstance(parsed, PairSet):
            raise ValueError("Artifact is not a PairSet")
        return parsed

    def load_retrieval(self, root: Path, handle: ArtifactHandle) -> RetrievalRepresentationSet:
        parsed = self._validate_indexed_artifact(root, handle, metadata_only=True)[2].parsed
        if not isinstance(parsed, RetrievalRepresentationSet):
            raise ValueError("Artifact is not a RetrievalRepresentationSet")
        return parsed

    def _recover_retrieval_pairs(self, root: Path, route: PairSelectionRoute):
        from splatforge.adapters.retrieval_artifacts import LocalRetrievalAdapter

        representation = self.load_retrieval(root, route.retrieval)
        return LocalRetrievalAdapter().query(
            self.artifact_directory(root, route.retrieval), representation,
            route.settings, route.resource_limits, route.retrieval_resources,
            route.explicit_pairs, checkpoint=lambda: None, progress=lambda _n: None,
        )

    def load_local_features(self, root: Path, handle: ArtifactHandle) -> LocalFeatureSet:
        _, _, validated = self._validate_indexed_artifact(root, handle)
        if not isinstance(validated.parsed, LocalFeatureSet):
            raise ValueError("Artifact is not a LocalFeatureSet")
        return validated.parsed

    def write_feature_metadata(self, workspace: Path, features: LocalFeatureSet) -> None:
        data = canonical_json_bytes(features.model_dump(mode="json")) + b"\n"
        if len(data) > MAX_FEATURE_METADATA_BYTES:
            raise ValueError("LocalFeatureSet metadata exceeds structural byte bound")
        self._write_new_file(workspace / "output" / "features.json", data)

    def load_match_set(self, root: Path, handle: ArtifactHandle) -> MatchSet:
        parsed = self._validate_indexed_artifact(root, handle, metadata_only=True)[2].parsed
        if not isinstance(parsed, MatchSet):
            raise ValueError("Artifact is not a MatchSet")
        return parsed

    def load_verified_geometry(self, root: Path, handle: ArtifactHandle) -> VerifiedGeometrySet:
        parsed = self._validate_indexed_artifact(root, handle, metadata_only=True)[2].parsed
        if not isinstance(parsed, VerifiedGeometrySet):
            raise ValueError("Artifact is not a VerifiedGeometrySet")
        return parsed

    def load_match_inputs(
        self, root: Path, handle: ArtifactHandle,
    ) -> tuple[LocalFeatureSet, PairSet]:
        from splatforge.adapters.matching_artifacts import read_matching_inputs

        _, directory, _ = self._validate_indexed_artifact(root, handle, metadata_only=True)
        return read_matching_inputs(directory)

    def write_matching_metadata(
        self, workspace: Path, payload: MatchSet | VerifiedGeometrySet,
        cameras: CameraPriorSet | None = None,
    ) -> None:
        name = "match_set.json" if isinstance(payload, MatchSet) else "verified_geometry.json"
        data = canonical_json_bytes(payload.model_dump(mode="json")) + b"\n"
        if len(data) > MAX_MATCH_METADATA_BYTES:
            raise ValueError("M7b metadata exceeds structural byte bound")
        self._write_new_file(workspace / "output" / name, data)
        if cameras is not None:
            data = canonical_json_bytes(cameras.model_dump(mode="json")) + b"\n"
            if len(data) > MAX_FEATURE_METADATA_BYTES:
                raise ValueError("Camera metadata exceeds structural byte bound")
            self._write_new_file(workspace / "output" / "cameras.json", data)

    def load_reconstruction(self, root: Path, handle: ArtifactHandle) -> ReconstructionSet:
        parsed = self._validate_indexed_artifact(root, handle, metadata_only=True)[2].parsed
        if not isinstance(parsed, ReconstructionSet):
            raise ValueError("Artifact is not a ReconstructionSet")
        return parsed

    def reconstruction_reader(self, root: Path, handle: ArtifactHandle) -> ReconstructionReader:
        from splatforge.adapters.colmap_reconstruction import ColmapReconstructionReader

        parsed = self.load_reconstruction(root, handle)
        return ColmapReconstructionReader(self.artifact_directory(root, handle), parsed)

    def write_reconstruction_metadata(self, workspace: Path, payload: ReconstructionSet,
                                      receipt: ClassicalMappingReceipt) -> None:
        receipt.require_output(payload)
        for name, value in (("reconstruction.json", payload), ("mapping.json", receipt)):
            data = canonical_json_bytes(value.model_dump(mode="json")) + b"\n"
            if len(data) > MAX_RECONSTRUCTION_METADATA_BYTES:
                raise ValueError("Reconstruction metadata exceeds structural byte bound")
            self._write_new_file(workspace / "output" / name, data)

    def load_quality_report(self, root: Path, artifact: ArtifactHandle) -> QualityReport:
        _, _, validated = self._validate_indexed_artifact(root.resolve(), artifact)
        if not isinstance(validated.parsed, QualityReport):
            raise ValueError("Artifact is not a QualityReport")
        return validated.parsed

    def artifact_directory(self, root: Path, artifact: ArtifactHandle) -> Path:
        _, artifact_directory, _ = self._validate_indexed_artifact(root.resolve(), artifact)
        return artifact_directory

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
        if (isinstance(snapshot.route, (FeatureMatchingRoute, GeometricVerificationRoute,
                                        MappingRoute, DatasetComponentRoute, TrainingJobRoute))
                and active and os.name != "nt"):
            raise ProjectError("Native M7b recovery requires tested Windows Job Object owner-death "
                               "containment; an OS writer lease alone does not prove teardown")
        if (
            isinstance(snapshot.route, (ViewPreparationRoute, SharpestViewPreparationRoute))
            and active
            and any(item["node_id"] == snapshot.route.candidate.node_id for item in active)
            and os.name != "nt"
        ):
            raise ProjectError(
                "Recovery cannot declare an external M3 FFmpeg attempt dead without "
                "the tested Windows Job Object kill-on-close guarantee"
            )
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
        if isinstance(snapshot.route, FakeRoute):
            required = {snapshot.route.sequence.node_id, snapshot.route.scale.node_id}
        elif isinstance(snapshot.route, (PairSelectionRoute, FeatureExtractionRoute,
                                         RetrievalBuildRoute,
                                         FeatureMatchingRoute, GeometricVerificationRoute,
                                         MappingRoute, ReconstructionEvidenceRoute, DatasetRoute,
                                         TrainingRoute)):
            required = {snapshot.route.node_id}
        elif isinstance(snapshot.route, SharpestViewPreparationRoute):
            required = {
                snapshot.route.candidate.node_id,
                snapshot.route.quality.node_id,
                snapshot.route.selection.node_id,
            }
        else:
            required = {snapshot.route.candidate.node_id, snapshot.route.selection.node_id}
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
            status = RunStatus.INTERRUPTED if updated.rowcount == 1 else RunStatus(run["status"])
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
        if not isinstance(snapshot.route, FakeRoute):
            raise RetryNotAllowedError(
                "run retry supports only the historical fake route; restart views with "
                "'splatforge views prepare' to reuse completed stages"
            )
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
            "attempts": [
                {**dict(row), "process_diagnostics": self._process_diagnostic_summary(
                    root, run_id, UUID(row["attempt_id"])
                )}
                for row in attempts
            ],
            "outputs": [dict(row) for row in outputs],
        }
        return json.dumps(rendered, ensure_ascii=False, indent=2)

    def active_run_ids(self, root: Path) -> tuple[UUID, ...]:
        self.inspect_project(root)
        with self._read_connection(root) as connection:
            rows = connection.execute(
                "SELECT run_id FROM runs WHERE status='running' "
                "ORDER BY started_at,run_id LIMIT 101"
            ).fetchall()
        if len(rows) > 100:
            raise ValueError("Too many active runs for bounded inspection; inspect state recovery")
        return tuple(UUID(row[0]) for row in rows)

    def read_progress_evidence(self, root: Path, run_id: UUID) -> RunProgressEvidence:
        """No writer lock, mutation, source access or artifact validation required."""
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
                "SELECT node_id, binding_kind FROM run_outputs WHERE run_id=?", (str(run_id),),
            ).fetchall()
        snapshot = self._load_run_snapshot(root, run_id)
        requested = False
        try:
            request, _ = self._read_cancellation_request(root, run_id)
            requested = request.run_owner_token == snapshot.owner_token
        except (OSError, ValueError):
            pass
        latest, warnings = self._latest_progress(root, run_id)
        return RunProgressEvidence(
            snapshot=snapshot, status=run["status"],
            started_at=datetime.fromisoformat(run["started_at"]),
            finished_at=datetime.fromisoformat(run["finished_at"]) if run["finished_at"] else None,
            cancellation_requested=requested,
            cancellation_accepted=bool(dict(run).get("cancellation_accepted_at")),
            attempts=tuple(AttemptLifecycle(
                node_id=row["node_id"], attempt_id=UUID(row["attempt_id"]), status=row["status"],
                started_at=datetime.fromisoformat(row["started_at"]) if row["started_at"] else None,
                finished_at=(datetime.fromisoformat(row["finished_at"])
                             if row["finished_at"] else None),
            ) for row in attempts),
            outputs=tuple(OutputBinding(row["node_id"], row["binding_kind"]) for row in outputs),
            latest=latest, warnings=warnings,
        )

    def _latest_progress(
        self, root: Path, run_id: UUID,
    ) -> tuple[PipelineProgressSnapshot | None, tuple[str, ...]]:
        """Read at most 4 MiB from the JSONL tail; ignore partial/old event kinds."""
        warnings = set()
        try:
            path = self._owned_path(root, f"runs/{run_id}/events.jsonl")
            with path.open("rb") as stream:
                stream.seek(0, os.SEEK_END)
                offset = max(0, stream.tell() - 4 * 1024 * 1024)
                stream.seek(offset)
                payload = stream.read(4 * 1024 * 1024)
            lines = payload.splitlines()
            if offset:
                lines = lines[1:]
            for line in reversed(lines):
                if len(line) > 1024 * 1024:
                    continue
                try:
                    event = json.loads(line)
                    if event.get("code") != "progress.snapshot":
                        continue
                    snapshot = PipelineProgressSnapshot.model_validate_json(
                        json.dumps(event["details"]["snapshot"])
                    )
                    if snapshot.run_id != run_id:
                        raise ValueError("Mismatched progress run")
                    return snapshot, tuple(sorted(warnings))
                except (ValueError, KeyError, TypeError, AttributeError):
                    warnings.add("progress.malformed_event")
        except (OSError, ValueError):
            warnings.add("progress.unavailable")
        return None, tuple(sorted(warnings))

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
        manifest_size = manifest_path.stat().st_size
        if manifest_size > MAX_MANIFEST_BYTES:
            raise ValueError("Orphan manifest exceeds its explicit size limit")
        with manifest_path.open("rb") as stream:
            manifest_bytes = stream.read(MAX_MANIFEST_BYTES + 1)
        if len(manifest_bytes) != manifest_size:
            raise ValueError("Orphan manifest changed while being read")
        if sha256_bytes(manifest_bytes) != attempt["expected_manifest_digest"]:
            raise ValueError("Orphan manifest digest mismatch")
        manifest = ArtifactManifest.model_validate_json(manifest_bytes)
        route = snapshot.route
        expected_lineage: tuple[ArtifactInputLineage, ...]
        consumed_candidate: CandidateViewSet | None = None
        consumed_quality: QualityReport | None = None
        candidate_artifact: ArtifactHandle | None = None
        quality_artifact: ArtifactHandle | None = None
        if isinstance(route, FakeRoute):
            if attempt["node_id"] == route.sequence.node_id:
                node = route.sequence
                output = node.output
                expected_recipe_key = sequence_recipe_key(start=node.start, settings=node.settings)
                expected_lineage = ()
                expected_literal_inputs = {"start": node.start}
            elif attempt["node_id"] == route.scale.node_id:
                node = route.scale
                output = node.output
                inputs = self._load_valid_run_outputs(root, snapshot.run_id)
                input_artifact = inputs.get(route.sequence.node_id)
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
                raise ValueError("Attempt node is not present in the frozen fake route")
        elif isinstance(route, TrainingRoute):
            if attempt["node_id"] != route.node_id:
                raise ValueError("training.orphan_node_mismatch")
            self.validate_training_route(root, route)
            output = route.target
            expected_recipe_key = route.recipe_key()
            expected_lineage = route.input_lineage()
            expected_literal_inputs = route.literal_inputs()
        elif isinstance(route, DatasetRoute):
            from splatforge.application.dataset import require_dataset_inputs

            if attempt["node_id"] != route.node_id:
                raise ValueError("Attempt node absent from frozen M10 route")
            require_dataset_inputs(self, root, route)
            output = route.target
            expected_recipe_key = route.recipe_key()
            expected_lineage = route.input_lineage()
            expected_literal_inputs = route.literal_inputs()
        elif isinstance(route, ReconstructionEvidenceRoute):
            if attempt["node_id"] != route.node_id:
                raise ValueError("Attempt node absent from frozen M9 route")
            self.validate_validation_inputs(root, route)
            output = route.target
            expected_recipe_key = route.recipe_key()
            expected_lineage = route.input_lineage()
            expected_literal_inputs = route.literal_inputs()
        elif isinstance(route, (FeatureMatchingRoute, GeometricVerificationRoute,
                                         MappingRoute)):
            if attempt["node_id"] != route.node_id:
                raise ValueError("Attempt node absent from frozen M7b route")
            if isinstance(route, MappingRoute):
                self.load_verified_geometry(root, route.verification)
                from splatforge.adapters.colmap_mapping import mapping_source
                from splatforge.adapters.mapping_database import inspect_mapping_input

                directory = self.artifact_directory(root, route.verification)
                mapping, allowed = mapping_source(directory)
                if inspect_mapping_input(directory / "matches.db", mapping,
                                         allowed_pairs=allowed) != route.mapping_input:
                    raise ValueError("mapping.input_mismatch: recovery upstream state differs")
            elif isinstance(route, FeatureMatchingRoute):
                self.load_local_features(root, route.features)
                self.load_pair_set(root, route.pairs)
            else:
                self.load_match_set(root, route.matches)
            output = route.target
            expected_recipe_key = route.recipe_key()
            expected_lineage = route.input_lineage()
            expected_literal_inputs = route.literal_inputs()
        elif isinstance(route, FeatureExtractionRoute):
            if attempt["node_id"] != route.node_id:
                raise ValueError("Attempt node absent from frozen feature route")
            candidate, selected = self.load_pairing_inputs(root, route.candidate, route.selected)
            output = route.target
            expected_recipe_key = feature_recipe_key(
                route.selected.semantic_digest, route.settings, route.backend.numerical_identity,
                route.backend.model_identities(),
            )
            expected_lineage = route.input_lineage()
            expected_literal_inputs = route.literal_inputs()
        elif isinstance(route, RetrievalBuildRoute):
            from splatforge.application.retrieval import require_corpus

            if attempt["node_id"] != route.node_id:
                raise ValueError("Attempt node absent from frozen retrieval route")
            candidate, selected = self.load_pairing_inputs(root, route.candidate, route.selected)
            require_corpus(route.export, candidate, selected)
            output = route.target
            expected_recipe_key = route.recipe_key()
            expected_lineage = route.input_lineage()
            expected_literal_inputs = route.literal_inputs()
        elif isinstance(route, PairSelectionRoute):
            if attempt["node_id"] != route.node_id:
                raise ValueError("Attempt node is absent from frozen pair route")
            candidate, selected = self.load_pairing_inputs(root, route.candidate, route.selected)
            if project_pairing_universe(candidate, selected) != route.universe:
                raise ValueError("Pair route projection differs from validated upstream inputs")
            output = route.target
            key_function = (
                sequential_recipe_key
                if isinstance(route.settings, SequentialSettings)
                else exhaustive_recipe_key
            )
            if route.retrieval:
                representation = self.load_retrieval(root, route.retrieval)
                from splatforge.application.retrieval import require_corpus
                from splatforge.core.retrieval_pairs import retrieval_pair_recipe_key

                require_corpus(representation.export(), candidate, selected)
                expected_recipe_key = retrieval_pair_recipe_key(
                    route.universe, representation.semantic_digest,
                    route.settings, route.explicit_pairs,
                )
            else:
                expected_recipe_key = key_function(
                    route.universe, route.settings, route.explicit_pairs,
                )
            expected_lineage = route.input_lineage()
            expected_literal_inputs = route.literal_inputs()
        elif attempt["node_id"] == route.candidate.node_id:
            node = route.candidate
            output = node.output
            expected_recipe_key = candidate_recipe_key(
                sources=route.sources,
                settings=node.settings,
                backend=route.ffmpeg_backend,
            )
            expected_lineage = ()
            expected_literal_inputs = {
                "candidate_settings": node.settings.model_dump(mode="json"),
                "inventory_content_digest": route.inventory_content_digest,
                "selected_source_ids": [str(source.source_id) for source in route.sources],
            }
            self._require_cache_verification(
                attempt["source_verification_json"],
                sources=route.sources,
                policy=route.verification_policy,
            )
        elif (
            isinstance(route, SharpestViewPreparationRoute)
            and attempt["node_id"] == route.quality.node_id
        ):
            node = route.quality
            output = node.output
            inputs = self._load_valid_run_outputs(root, snapshot.run_id)
            candidate_artifact = inputs.get(route.candidate.node_id)
            if candidate_artifact is None:
                raise ValueError("Orphan quality has no valid candidate run output")
            consumed_candidate = self.load_candidate_views(root, candidate_artifact)
            expected_recipe_key = quality_recipe_key(
                candidate=consumed_candidate,
                candidate_digest=candidate_artifact.semantic_digest,
                settings=node.settings,
                backend=route.quality_backend,
            )
            expected_lineage = (
                ArtifactInputLineage(
                    input_name="candidate_views",
                    artifact_id=candidate_artifact.artifact_id,
                    artifact_type=candidate_artifact.artifact_type,
                    contract_version=candidate_artifact.contract_version,
                    semantic_digest=candidate_artifact.semantic_digest,
                    recipe_key=candidate_artifact.recipe_key,
                ),
            )
            expected_literal_inputs = {"quality_settings": node.settings.model_dump(mode="json")}
        elif (
            isinstance(route, SharpestViewPreparationRoute)
            and attempt["node_id"] == route.selection.node_id
        ):
            node = route.selection
            output = node.output
            inputs = self._load_valid_run_outputs(root, snapshot.run_id)
            candidate_artifact = inputs.get(route.candidate.node_id)
            quality_artifact = inputs.get(route.quality.node_id)
            if candidate_artifact is None or quality_artifact is None:
                raise ValueError(
                    "Orphan sharpest selection has no valid candidate and quality outputs"
                )
            consumed_candidate = self.load_candidate_views(root, candidate_artifact)
            consumed_quality = self.load_quality_report(root, quality_artifact)
            expected_recipe_key = sharpest_selection_recipe_key(
                candidate=consumed_candidate,
                candidate_digest=candidate_artifact.semantic_digest,
                quality=consumed_quality,
                quality_digest=quality_artifact.semantic_digest,
                settings=node.settings,
            )
            expected_lineage = (
                ArtifactInputLineage(
                    input_name="candidate_views",
                    artifact_id=candidate_artifact.artifact_id,
                    artifact_type=candidate_artifact.artifact_type,
                    contract_version=candidate_artifact.contract_version,
                    semantic_digest=candidate_artifact.semantic_digest,
                    recipe_key=candidate_artifact.recipe_key,
                ),
                ArtifactInputLineage(
                    input_name="quality_report",
                    artifact_id=quality_artifact.artifact_id,
                    artifact_type=quality_artifact.artifact_type,
                    contract_version=quality_artifact.contract_version,
                    semantic_digest=quality_artifact.semantic_digest,
                    recipe_key=quality_artifact.recipe_key,
                ),
            )
            expected_literal_inputs = {"selection_settings": node.settings.model_dump(mode="json")}
        elif (
            isinstance(route, ViewPreparationRoute)
            and attempt["node_id"] == route.selection.node_id
        ):
            node = route.selection
            output = node.output
            inputs = self._load_valid_run_outputs(root, snapshot.run_id)
            candidate_artifact = inputs.get(route.candidate.node_id)
            if candidate_artifact is None:
                raise ValueError("Orphan selection has no valid candidate run output")
            consumed_candidate = self.load_candidate_views(root, candidate_artifact)
            expected_recipe_key = selection_recipe_key(
                candidate=consumed_candidate,
                candidate_digest=candidate_artifact.semantic_digest,
                settings=node.settings,
            )
            expected_lineage = (
                ArtifactInputLineage(
                    input_name="candidate_views",
                    artifact_id=candidate_artifact.artifact_id,
                    artifact_type=candidate_artifact.artifact_type,
                    contract_version=candidate_artifact.contract_version,
                    semantic_digest=candidate_artifact.semantic_digest,
                    recipe_key=candidate_artifact.recipe_key,
                ),
            )
            expected_literal_inputs = {"selection_settings": node.settings.model_dump(mode="json")}
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
        validated = validate_published_artifact(artifact_directory, manifest)
        if isinstance(route, TrainingRoute):
            self.validate_training_route(root, route, validated.parsed, artifact_directory)
        elif isinstance(route, DatasetRoute):
            from splatforge.adapters.dataset_artifacts import require_dataset_source
            from splatforge.application.dataset import require_dataset_payload

            require_dataset_payload(route, validated.parsed, exact_lineage=True)
            require_dataset_source(root, self, route, artifact_directory, validated.parsed)
        elif isinstance(route, ReconstructionEvidenceRoute):
            from splatforge.application.reconstruction_validation import require_validation_payload

            require_validation_payload(self, root, route, validated.parsed, exact_lineage=True)
        elif isinstance(route, MappingRoute):
            from splatforge.application.mapping import require_mapping_payload

            require_mapping_payload(route, validated.parsed)
        elif isinstance(route, (FeatureMatchingRoute, GeometricVerificationRoute)):
            from splatforge.application.matching import require_route_payload

            require_route_payload(route, validated.parsed)
        elif isinstance(route, FeatureExtractionRoute):
            parsed = validated.parsed
            if not isinstance(parsed, LocalFeatureSet):
                raise ValueError("Orphan feature payload has wrong contract")
            selected_ids = {s.view_id for s in selected.selected_views}
            expected = {v.view_id: v for v in candidate.views if v.view_id in selected_ids}
            if (parsed.settings != route.settings
                    or parsed.backend_numerical_identity != route.backend.numerical_identity
                    or parsed.models != route.backend.model_identities()
                    or parsed.selected_artifact_id != route.selected.artifact_id
                    or parsed.selected_semantic_digest != route.selected.semantic_digest
                    or {v.view_id for v in parsed.views} != set(expected)
                    or any((v.width, v.height, v.image_sha256) != (
                        expected[v.view_id].width, expected[v.view_id].height,
                        expected[v.view_id].image_sha256) for v in parsed.views)):
                raise ValueError("Orphan features differ from frozen route/upstream pixels")
        elif isinstance(route, RetrievalBuildRoute):
            parsed = validated.parsed
            if (not isinstance(parsed, RetrievalRepresentationSet)
                    or parsed.export() != route.export
                    or parsed.candidate_artifact_id != route.candidate.artifact_id
                    or parsed.selected_artifact_id != route.selected.artifact_id):
                raise ValueError("Orphan retrieval representation differs from frozen route")
        elif isinstance(route, PairSelectionRoute):
            if not isinstance(validated.parsed, PairSet):
                raise ValueError("Orphan pair payload has wrong contract")
            parsed = validated.parsed
            if (
                parsed.universe != route.universe
                or parsed.settings != route.settings
                or parsed.explicit_pairs != route.explicit_pairs
                or parsed.candidate_artifact_id != route.candidate.artifact_id
                or parsed.selected_artifact_id != route.selected.artifact_id
                or parsed.selected_method_id != selected.selection_method_id
                or parsed.pairs != (self._recover_retrieval_pairs(root, route) if route.retrieval
                else generate_pairs(
                    route.universe,
                    settings=route.settings,
                    limits=route.resource_limits,
                    explicit_pairs=route.explicit_pairs,
                ))
            ):
                raise ValueError("Orphan PairSet differs from frozen recipe or lineage")
        elif isinstance(validated.parsed, QualityReport):
            if consumed_candidate is None or candidate_artifact is None:
                raise ValueError("Orphan quality payload has no consumed candidate")
            validate_quality_against_candidate(validated.parsed, consumed_candidate)
            if validated.parsed.candidate_artifact_id != candidate_artifact.artifact_id:
                raise ValueError("Orphan quality references a different candidate artifact")
        elif isinstance(validated.parsed, SharpestSelectedViewSet):
            if (
                consumed_candidate is None
                or consumed_quality is None
                or candidate_artifact is None
                or quality_artifact is None
            ):
                raise ValueError("Orphan sharpest payload has incomplete upstream inputs")
            validate_sharpest_against_inputs(
                validated.parsed,
                consumed_candidate,
                consumed_quality,
                candidate_artifact=candidate_artifact,
                quality_artifact=quality_artifact,
            )
        elif consumed_candidate is not None:
            if not isinstance(validated.parsed, SelectedViewSet):
                raise ValueError("Orphan selection payload has the wrong typed contract")
            validate_selected_against_candidate(validated.parsed, consumed_candidate)
            if validated.parsed.candidate_semantic_digest != expected_lineage[0].semantic_digest:
                raise ValueError("Orphan selection references different candidate semantics")
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
        if self._validation_context is not None:
            identity = (
                str(root.resolve()), str(artifact_id), manifest.artifact_type,
                str(manifest.contract_version), manifest.recipe_key, manifest.semantic_digest,
                str(manifest_path), attempt["expected_manifest_digest"], attempt["attempt_id"],
            )
            strength = (
                ValidationStrength.PAYLOAD_INTEGRITY
                if manifest.artifact_type == PAIR_ARTIFACT_TYPE else ValidationStrength.FULL_DECODE
            )
            self._validation_context.results[identity] = (
                strength, manifest, artifact_directory, validated,
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

    @staticmethod
    def _require_cache_verification(
        encoded: str,
        *,
        sources: tuple[SourceOccurrence, ...],
        policy: VerificationPolicyId | None,
    ) -> None:
        if not sources:
            return
        if policy is None:
            raise ValueError("Source-consuming cache lookup omitted verification policy")
        payload = json.loads(encoded)
        evidence = payload.get("evidence")
        if not isinstance(evidence, list):
            raise ValueError("Cached candidate has no bounded source-verification evidence")
        indexed: dict[tuple[str, int], dict[str, object]] = {}
        for item in evidence:
            if not isinstance(item, dict):
                raise ValueError("Cached source-verification evidence is malformed")
            try:
                key = (str(item["source_id"]), int(item["source_revision"]))
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError("Cached source-verification identity is malformed") from exc
            if key in indexed:
                raise ValueError("Cached source-verification evidence contains duplicates")
            indexed[key] = item
        for source in sources:
            item = indexed.get((str(source.source_id), source.source_revision))
            if item is None:
                raise ValueError(
                    f"Cached candidate lacks verification for source {source.source_id}"
                )
            if item.get("registered_digest") != source.content_sha256:
                raise ValueError(
                    f"Cached verification digest differs for source {source.source_id}"
                )
            if (
                item.get("outcome") != "unchanged"
                or item.get("consumed_under_protected_identity") is not True
            ):
                raise ValueError(
                    f"Cached candidate lacks protected unchanged consumption for "
                    f"source {source.source_id}"
                )
            assurance = item.get("assurance")
            producer_policy = item.get("policy_id")
            if policy == VerificationPolicyId.STRICT:
                if producer_policy != VerificationPolicyId.STRICT.value or assurance != (
                    "content_verified"
                ):
                    raise ValueError(
                        f"Cached candidate has insufficient Strict provenance for "
                        f"source {source.source_id}"
                    )
            elif assurance not in {"metadata_unchanged", "content_verified"}:
                raise ValueError(
                    f"Cached candidate has insufficient Balanced provenance for "
                    f"source {source.source_id}"
                )

    def _validate_indexed_artifact(
        self,
        root: Path,
        handle: ArtifactHandle,
        _seen: frozenset[UUID] = frozenset(),
        *,
        metadata_only: bool = False,
        context: ArtifactValidationContext | None = None,
    ) -> tuple[ArtifactManifest, Path, ValidatedArtifact]:
        root = root.resolve()
        self.require_not_evicted(root, handle.artifact_id)
        context = context or self._validation_context or ArtifactValidationContext()
        if handle.artifact_id in _seen:
            raise ValueError("Artifact lineage contains a cycle")
        seen = _seen | {handle.artifact_id}
        metadata_only = (metadata_only or handle.artifact_type == PAIR_ARTIFACT_TYPE
                         or context.mapping_integrity_only)
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
        strength = (
            ValidationStrength.PAYLOAD_INTEGRITY
            if metadata_only else ValidationStrength.FULL_DECODE
        )
        identity = (
            str(root), str(handle.artifact_id), handle.artifact_type,
            str(handle.contract_version), handle.recipe_key, handle.semantic_digest,
            str(manifest_path), row[0], row[1],
        )
        memo = context.results.get(identity)
        if memo is not None and memo[0] >= strength:
            return memo[1], memo[2], memo[3]
        manifest_size = manifest_path.stat().st_size
        if manifest_size > MAX_MANIFEST_BYTES:
            raise ValueError("Manifest exceeds its explicit size limit")
        with manifest_path.open("rb") as stream:
            manifest_bytes = stream.read(MAX_MANIFEST_BYTES + 1)
        if len(manifest_bytes) != manifest_size:
            raise ValueError("Manifest changed while being read")
        if sha256_bytes(manifest_bytes) != row[0]:
            raise ValueError("Manifest digest mismatch")
        manifest = ArtifactManifest.model_validate_json(manifest_bytes)
        if (
            manifest.artifact_id != handle.artifact_id
            or manifest.artifact_type != handle.artifact_type
            or manifest.contract_version != handle.contract_version
            or manifest.recipe_key != handle.recipe_key
            or manifest.semantic_digest != handle.semantic_digest
            or manifest.validation.validator_id != f"{manifest.artifact_type}.integrity"
            or manifest.validation.validator_version != 1
        ):
            raise ValueError("Manifest identity or contract mismatch")
        artifact_directory = manifest_path.parent
        validated = validate_published_artifact(
            artifact_directory, manifest, decode_pixels=not metadata_only,
            mapping_integrity_only=context.mapping_integrity_only,
        )
        for lineage in manifest.input_lineage:
            with self._read_connection(root) as connection:
                upstream = connection.execute(
                    """
                    SELECT manifest_path FROM artifacts
                    WHERE artifact_id=? AND artifact_type=? AND contract_version=?
                      AND recipe_key=? AND semantic_digest=?
                    """,
                    (
                        str(lineage.artifact_id),
                        lineage.artifact_type,
                        lineage.contract_version,
                        lineage.recipe_key,
                        lineage.semantic_digest,
                    ),
                ).fetchone()
            if upstream is None:
                raise ValueError("Artifact lineage input is not indexed with exact identity")
            upstream_handle = ArtifactHandle(
                artifact_id=lineage.artifact_id,
                artifact_type=lineage.artifact_type,
                contract_version=lineage.contract_version,
                recipe_key=lineage.recipe_key,
                semantic_digest=lineage.semantic_digest,
                manifest_path=upstream[0],
            )
            self._validate_indexed_artifact(
                root, upstream_handle, seen, metadata_only=metadata_only, context=context
            )
        if isinstance(validated.parsed, ReconstructionSet):
            from splatforge.adapters.colmap_mapping import mapping_source
            from splatforge.adapters.mapping_artifacts import read_receipt
            from splatforge.adapters.mapping_database import inspect_mapping_input

            directory = self._owned_path(root, upstream[0]).parent
            mapping, allowed = mapping_source(directory)
            receipt = read_receipt(artifact_directory)
            if inspect_mapping_input(directory / "matches.db", mapping,
                                     allowed_pairs=allowed) != receipt.mapping_input:
                raise ValueError("mapping.input_mismatch: numerical input differs from lineage")
            if ((artifact_directory / "input_cameras.json").read_bytes()
                    != (directory / "cameras.json").read_bytes()):
                raise ValueError("mapping.input_mismatch: camera priors differ from lineage")
        if (manifest.artifact_type.startswith("validation.")
                or manifest.artifact_type == "reconstruction.selection"):
            from splatforge.application.reconstruction_validation import require_validation_payload

            snapshot_route = self._load_run_snapshot(root, manifest.producer_run_id).route
            if not isinstance(snapshot_route, ReconstructionEvidenceRoute):
                raise ValueError("M9 publication producer is not an M9 frozen route")
            self.validate_validation_inputs(root, snapshot_route)
            require_validation_payload(self, root, snapshot_route, validated.parsed,
                                       exact_lineage=True)
        if manifest.artifact_type.startswith("training."):
            route = self._load_run_snapshot(root, manifest.producer_run_id).route
            if not isinstance(route, TrainingRoute):
                raise ValueError("training.invalid_producer_route")
            self.validate_training_route(root, route, validated.parsed, artifact_directory)
        if manifest.artifact_type.startswith("dataset."):
            from splatforge.adapters.dataset_artifacts import require_dataset_source
            from splatforge.application.dataset import (
                require_dataset_inputs,
                require_dataset_payload,
            )

            route = self._load_run_snapshot(root, manifest.producer_run_id).route
            if not isinstance(route, DatasetRoute):
                raise ValueError("M10 publication requires its exact frozen producer route")
            require_dataset_inputs(self, root, route)
            require_dataset_payload(route, validated.parsed, exact_lineage=True)
            require_dataset_source(root, self, route, artifact_directory, validated.parsed)
        context.results[identity] = (strength, manifest, artifact_directory, validated)
        return manifest, artifact_directory, validated

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
