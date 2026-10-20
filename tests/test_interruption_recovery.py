import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from splatforge.adapters.execution_storage import (
    ExecutionFaultHooks,
    LocalExecutionRepository,
)
from splatforge.adapters.fake_stages import LocalFakeStages
from splatforge.application.execution import (
    ExecutionCancelledError,
    FakeExecutionService,
    PublicationUnresolvedError,
    RetryNotAllowedError,
    TeardownUnconfirmedError,
)
from splatforge.application.projects import ProjectError
from splatforge.bootstrap import build_execution_service, build_project_service
from splatforge.core.execution import RunWarning


class InjectedCrash(BaseException):
    pass


def query(root: Path, statement: str, parameters: tuple[object, ...] = ()) -> list[tuple]:
    with closing(sqlite3.connect(root / "state.sqlite")) as connection:
        return connection.execute(statement, parameters).fetchall()


def current_run_id(root: Path) -> UUID:
    return UUID(query(root, "SELECT run_id FROM runs WHERE status='running'")[0][0])


def test_cancel_is_lock_free_idempotent_and_acceptance_precedes_stop(
    tmp_path: Path,
) -> None:
    build_project_service().create(tmp_path, "Cancel while owned")
    repository = LocalExecutionRepository()
    observations: list[tuple[bool, bool, bool, bool]] = []

    class CancellingStages(LocalFakeStages):
        def execute_sequence(self, workspace, *, start, settings, control):  # type: ignore[no-untyped-def]
            run_id = current_run_id(tmp_path)
            first = repository.request_cancellation(tmp_path, run_id=run_id)
            second = repository.request_cancellation(tmp_path, run_id=run_id)
            before = query(tmp_path, "SELECT cancellation_accepted_at FROM runs")[0][0]
            try:
                control.checkpoint()
            except ExecutionCancelledError:
                after = query(tmp_path, "SELECT cancellation_accepted_at FROM runs")[0][0]
                observations.append(
                    (before is None, after is not None, first.created, second.created)
                )
                raise

    result = FakeExecutionService(repository, CancellingStages()).run(tmp_path)

    assert result.status == "cancelled"
    assert observations == [(True, True, True, False)]
    row = query(
        tmp_path,
        """
        SELECT r.status, r.cancellation_accepted_at, a.status,
               a.cancellation_accepted_at, a.teardown_state
        FROM runs r JOIN attempts a ON a.run_id=r.run_id
        """,
    )[0]
    assert row[0] == row[2] == "cancelled"
    assert row[1] is not None and row[3] is not None
    assert row[4] == "confirmed"


def test_cancel_after_move_leaves_unindexed_orphan_never_adopted(
    tmp_path: Path,
) -> None:
    build_project_service().create(tmp_path, "Cancel after move")
    holder: dict[str, LocalExecutionRepository] = {}

    def cancel_after_move(_path: Path) -> None:
        holder["repository"].request_cancellation(tmp_path, run_id=current_run_id(tmp_path))

    repository = LocalExecutionRepository(
        fault_hooks=ExecutionFaultHooks(after_artifact_move=cancel_after_move)
    )
    holder["repository"] = repository
    result = FakeExecutionService(repository, LocalFakeStages()).run(tmp_path)

    assert result.status == "cancelled"
    assert query(tmp_path, "SELECT count(*) FROM artifacts") == [(0,)]
    assert len(list((tmp_path / "artifacts" / "numbers").iterdir())) == 1
    assert build_execution_service().recover(tmp_path, result.run_id).status == "cancelled"
    assert query(tmp_path, "SELECT count(*) FROM artifacts") == [(0,)]


def test_success_commit_makes_later_cancel_too_late(tmp_path: Path) -> None:
    build_project_service().create(tmp_path, "Late cancellation")
    result = build_execution_service().run(tmp_path)

    cancellation = build_execution_service().cancel(tmp_path, result.run_id)

    assert cancellation.too_late is True
    assert cancellation.created is False
    assert not (tmp_path / "runs" / str(result.run_id) / "cancel.request").exists()
    assert query(tmp_path, "SELECT status FROM runs") == [("succeeded",)]


def test_recovery_adopts_exact_orphan_then_retry_only_missing_node(
    tmp_path: Path,
) -> None:
    build_project_service().create(tmp_path, "Recover and retry")

    def crash_after_move(_path: Path) -> None:
        raise OSError("injected crash after move")

    repository = LocalExecutionRepository(
        fault_hooks=ExecutionFaultHooks(after_artifact_move=crash_after_move)
    )
    with pytest.raises(PublicationUnresolvedError):
        FakeExecutionService(repository, LocalFakeStages()).run(tmp_path)
    run_id = UUID(query(tmp_path, "SELECT run_id FROM runs")[0][0])

    recovered = build_execution_service().recover(tmp_path, run_id)
    assert recovered.status == "interrupted"
    assert len(recovered.adopted_attempts) == 1
    retried = build_execution_service().retry(tmp_path, run_id)
    assert retried.status == "succeeded"
    assert query(
        tmp_path,
        "SELECT node_id, retry_of_attempt_id FROM attempts ORDER BY created_at",
    ) == [("numbers", None), ("scaled", None)]


def test_recovery_refuses_corrupt_orphan_and_pending_cancel_wins(
    tmp_path: Path,
) -> None:
    corrupt_root = tmp_path / "corrupt"
    build_project_service().create(corrupt_root, "Corrupt orphan")

    def crash(_path: Path) -> None:
        raise OSError("crash")

    with pytest.raises(PublicationUnresolvedError):
        FakeExecutionService(
            LocalExecutionRepository(fault_hooks=ExecutionFaultHooks(after_artifact_move=crash)),
            LocalFakeStages(),
        ).run(corrupt_root)
    run_id = UUID(query(corrupt_root, "SELECT run_id FROM runs")[0][0])
    artifact_id = query(corrupt_root, "SELECT expected_artifact_id FROM attempts")[0][0]
    (corrupt_root / "artifacts" / "numbers" / artifact_id / "numbers.json").write_bytes(b"bad")
    recovered = build_execution_service().recover(corrupt_root, run_id)
    assert recovered.status == "interrupted"
    assert recovered.adopted_attempts == ()
    assert query(corrupt_root, "SELECT count(*) FROM artifacts") == [(0,)]

    cancel_root = tmp_path / "cancel"
    build_project_service().create(cancel_root, "Cancel orphan")
    holder: dict[str, LocalExecutionRepository] = {}

    def request_then_crash(_path: Path) -> None:
        holder["repository"].request_cancellation(cancel_root, run_id=current_run_id(cancel_root))
        raise OSError("crash before acceptance")

    repository = LocalExecutionRepository(
        fault_hooks=ExecutionFaultHooks(after_artifact_move=request_then_crash)
    )
    holder["repository"] = repository
    with pytest.raises(PublicationUnresolvedError):
        FakeExecutionService(repository, LocalFakeStages()).run(cancel_root)
    run_id = UUID(query(cancel_root, "SELECT run_id FROM runs")[0][0])
    assert build_execution_service().recover(cancel_root, run_id).status == "cancelled"
    assert query(cancel_root, "SELECT count(*) FROM artifacts") == [(0,)]


def test_workspace_crash_recovers_and_transient_retry_links_new_attempt(
    tmp_path: Path,
) -> None:
    interrupted_root = tmp_path / "interrupted"
    build_project_service().create(interrupted_root, "Workspace crash")

    class CrashingStages(LocalFakeStages):
        def execute_sequence(self, workspace, *, start, settings, control):  # type: ignore[no-untyped-def]
            raise InjectedCrash("owner disappeared")

    with pytest.raises(InjectedCrash):
        FakeExecutionService(LocalExecutionRepository(), CrashingStages()).run(interrupted_root)
    run_id = UUID(query(interrupted_root, "SELECT run_id FROM runs")[0][0])
    assert build_execution_service().recover(interrupted_root, run_id).status == "interrupted"
    assert build_execution_service().retry(interrupted_root, run_id).status == "succeeded"
    linked = query(
        interrupted_root,
        "SELECT retry_of_attempt_id FROM attempts WHERE node_id='numbers' ORDER BY created_at",
    )
    assert linked[0] == (None,)
    assert linked[1][0] is not None

    transient_root = tmp_path / "transient"
    build_project_service().create(transient_root, "Transient retry")

    class TransientStages(LocalFakeStages):
        def execute_sequence(self, workspace, *, start, settings, control):  # type: ignore[no-untyped-def]
            raise OSError("transient fake I/O")

    with pytest.raises(OSError):
        FakeExecutionService(LocalExecutionRepository(), TransientStages()).run(transient_root)
    run_id = UUID(query(transient_root, "SELECT run_id FROM runs")[0][0])
    first = query(transient_root, "SELECT attempt_id FROM attempts")[0][0]
    assert build_execution_service().retry(transient_root, run_id).status == "succeeded"
    assert query(
        transient_root,
        "SELECT retry_of_attempt_id FROM attempts WHERE node_id='numbers' ORDER BY created_at",
    ) == [(None,), (first,)]


def test_nonretryable_unresolved_teardown_and_attempt_limit_block_retry(
    tmp_path: Path,
) -> None:
    invalid_root = tmp_path / "invalid"
    build_project_service().create(invalid_root, "Invalid")

    class InvalidStages(LocalFakeStages):
        def execute_sequence(self, workspace, *, start, settings, control):  # type: ignore[no-untyped-def]
            raise ValueError("invalid output")

    with pytest.raises(ValueError):
        FakeExecutionService(LocalExecutionRepository(), InvalidStages()).run(invalid_root)
    run_id = UUID(query(invalid_root, "SELECT run_id FROM runs")[0][0])
    with pytest.raises(RetryNotAllowedError, match="non-retryable"):
        build_execution_service().retry(invalid_root, run_id)

    unresolved_root = tmp_path / "unresolved"
    build_project_service().create(unresolved_root, "Unresolved")
    repository = LocalExecutionRepository()

    class UnresolvedStages(LocalFakeStages):
        def execute_sequence(self, workspace, *, start, settings, control):  # type: ignore[no-untyped-def]
            repository.request_cancellation(unresolved_root, run_id=current_run_id(unresolved_root))
            try:
                control.checkpoint()
            except ExecutionCancelledError as exc:
                raise TeardownUnconfirmedError("unresolved") from exc

    result = FakeExecutionService(repository, UnresolvedStages()).run(unresolved_root)
    assert result.status == "interrupted"
    assert query(unresolved_root, "SELECT teardown_state FROM attempts") == [("unresolved",)]
    with pytest.raises(RetryNotAllowedError, match="teardown"):
        build_execution_service().retry(unresolved_root, result.run_id)

    limit_root = tmp_path / "limit"
    build_project_service().create(limit_root, "Limit")

    class AlwaysTransient(LocalFakeStages):
        def execute_sequence(self, workspace, *, start, settings, control):  # type: ignore[no-untyped-def]
            raise OSError("again")

    service = FakeExecutionService(LocalExecutionRepository(), AlwaysTransient())
    with pytest.raises(OSError):
        service.run(limit_root)
    run_id = UUID(query(limit_root, "SELECT run_id FROM runs")[0][0])
    with pytest.raises(OSError):
        service.retry(limit_root, run_id)
    with pytest.raises(OSError):
        service.retry(limit_root, run_id)
    with pytest.raises(RetryNotAllowedError, match="Attempt limit"):
        service.retry(limit_root, run_id)
    assert query(limit_root, "SELECT count(*) FROM attempts") == [(3,)]

    assert query(limit_root, "SELECT status FROM runs") == [("failed",)]

def test_malformed_or_stale_cancellation_request_is_never_overwritten_or_accepted(
    tmp_path: Path,
) -> None:
    build_project_service().create(tmp_path, "Strict request")

    def crash_after_run(_root: Path) -> None:
        raise InjectedCrash("leave running run")

    repository = LocalExecutionRepository(
        fault_hooks=ExecutionFaultHooks(after_run_record=crash_after_run)
    )
    with pytest.raises(InjectedCrash):
        FakeExecutionService(repository, LocalFakeStages()).run(tmp_path)
    run_id = current_run_id(tmp_path)
    request_path = tmp_path / "runs" / str(run_id) / "cancel.request"
    request_path.write_bytes(b"{malformed")
    original = request_path.read_bytes()

    with pytest.raises(ValueError):
        repository.request_cancellation(tmp_path, run_id=run_id)
    assert request_path.read_bytes() == original
    assert repository.accept_cancellation(tmp_path, run_id=run_id, attempt_id=None) is False

    stale = {
        "schema_version": 1,
        "request_id": str(uuid4()),
        "run_id": str(run_id),
        "run_owner_token": str(uuid4()),
        "requested_at": datetime.now(UTC).isoformat(),
    }
    request_path.write_text(json.dumps(stale), encoding="utf-8")
    stale_payload = request_path.read_bytes()
    with pytest.raises(ProjectError, match="stale run identity"):
        repository.request_cancellation(tmp_path, run_id=run_id)
    assert request_path.read_bytes() == stale_payload
    assert repository.accept_cancellation(tmp_path, run_id=run_id, attempt_id=None) is False
    assert query(
        tmp_path,
        "SELECT cancellation_accepted_at, cancellation_request_digest FROM runs",
    ) == [(None, None)]


def test_cancellation_between_nodes_and_after_cache_hit_prevents_next_node(
    tmp_path: Path,
) -> None:
    between_root = tmp_path / "between"
    build_project_service().create(between_root, "Between nodes")

    class RequestAfterNumbers(LocalExecutionRepository):
        def publish_attempt(self, root, **kwargs):  # type: ignore[no-untyped-def]
            artifact = super().publish_attempt(root, **kwargs)
            if kwargs["node_id"] == "numbers":
                self.request_cancellation(root, run_id=kwargs["run_id"])
            return artifact

    result = FakeExecutionService(RequestAfterNumbers(), LocalFakeStages()).run(between_root)
    assert result.status == "cancelled"
    assert query(between_root, "SELECT node_id, status FROM attempts ORDER BY created_at") == [
        ("numbers", "succeeded")
    ]

    cache_root = tmp_path / "cache"
    build_project_service().create(cache_root, "Cache checkpoint")
    assert build_execution_service().run(cache_root).status == "succeeded"

    class RequestAfterCacheBinding(LocalExecutionRepository):
        def bind_cached_output(self, root, **kwargs):  # type: ignore[no-untyped-def]
            super().bind_cached_output(root, **kwargs)
            if kwargs["node_id"] == "numbers":
                self.request_cancellation(root, run_id=kwargs["run_id"])

    cached = FakeExecutionService(RequestAfterCacheBinding(), LocalFakeStages()).run(cache_root)
    assert cached.status == "cancelled"
    assert cached.cache_hits == ("numbers",)
    assert query(
        cache_root,
        "SELECT count(*) FROM attempts WHERE run_id=?",
        (str(cached.run_id),),
    ) == [(0,)]


def test_recovery_boundaries_after_run_record_and_before_artifact_move(
    tmp_path: Path,
) -> None:
    record_root = tmp_path / "record"
    build_project_service().create(record_root, "Run record crash")

    def crash_after_record(_root: Path) -> None:
        raise InjectedCrash("after run record")

    with pytest.raises(InjectedCrash):
        FakeExecutionService(
            LocalExecutionRepository(
                fault_hooks=ExecutionFaultHooks(after_run_record=crash_after_record)
            ),
            LocalFakeStages(),
        ).run(record_root)
    record_run = current_run_id(record_root)
    assert build_execution_service().recover(record_root, record_run).status == "interrupted"
    assert query(record_root, "SELECT count(*) FROM attempts") == [(0,)]

    prepared_root = tmp_path / "prepared"
    build_project_service().create(prepared_root, "Prepared crash")

    def crash_before_move(_path: Path) -> None:
        raise InjectedCrash("before artifact move")

    with pytest.raises(InjectedCrash):
        FakeExecutionService(
            LocalExecutionRepository(
                fault_hooks=ExecutionFaultHooks(before_artifact_move=crash_before_move)
            ),
            LocalFakeStages(),
        ).run(prepared_root)
    prepared_run = current_run_id(prepared_root)
    attempt_id, expected_id = query(
        prepared_root,
        "SELECT attempt_id, expected_artifact_id FROM attempts",
    )[0]
    assert expected_id is not None
    assert (
        prepared_root / "work" / str(prepared_run) / attempt_id / "output" / "manifest.json"
    ).is_file()
    assert query(prepared_root, "SELECT count(*) FROM artifacts") == [(0,)]
    assert build_execution_service().recover(prepared_root, prepared_run).status == "interrupted"
    assert query(prepared_root, "SELECT status FROM attempts") == [("interrupted",)]


def test_recovery_finalizes_when_attempt_publications_were_already_committed(
    tmp_path: Path,
) -> None:
    build_project_service().create(tmp_path, "Finalize recovered run")

    class CrashBeforeRunSuccess(LocalExecutionRepository):
        def mark_run_succeeded(self, root, *, run_id):  # type: ignore[no-untyped-def]
            raise InjectedCrash("before run success")

    with pytest.raises(InjectedCrash):
        FakeExecutionService(CrashBeforeRunSuccess(), LocalFakeStages()).run(tmp_path)
    run_id = current_run_id(tmp_path)
    assert query(tmp_path, "SELECT status FROM attempts ORDER BY created_at") == [
        ("succeeded",),
        ("succeeded",),
    ]
    assert build_execution_service().recover(tmp_path, run_id).status == "succeeded"
    assert query(tmp_path, "SELECT status FROM runs") == [("succeeded",)]


def test_cancellation_and_recovery_refuse_owned_path_redirections(tmp_path: Path) -> None:
    def crash_after_run(_root: Path) -> None:
        raise InjectedCrash("leave running run")

    cancel_root = tmp_path / "cancel redirect"
    build_project_service().create(cancel_root, "Cancel redirect")
    repository = LocalExecutionRepository(
        fault_hooks=ExecutionFaultHooks(after_run_record=crash_after_run)
    )
    with pytest.raises(InjectedCrash):
        FakeExecutionService(repository, LocalFakeStages()).run(cancel_root)
    cancel_run = current_run_id(cancel_root)
    external_request = cancel_root / "request-target"
    external_request.write_text("do not overwrite", encoding="utf-8")
    try:
        (cancel_root / "runs" / str(cancel_run) / "cancel.request").symlink_to(
            external_request
        )
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"File symlinks unavailable: {exc}")
    with pytest.raises(ProjectError, match="filesystem redirection"):
        build_execution_service().cancel(cancel_root, cancel_run)
    assert external_request.read_text(encoding="utf-8") == "do not overwrite"

    recovery_root = tmp_path / "recovery redirect"
    build_project_service().create(recovery_root, "Recovery redirect")
    repository = LocalExecutionRepository(
        fault_hooks=ExecutionFaultHooks(after_run_record=crash_after_run)
    )
    with pytest.raises(InjectedCrash):
        FakeExecutionService(repository, LocalFakeStages()).run(recovery_root)
    recovery_run = current_run_id(recovery_root)
    snapshot = recovery_root / "runs" / str(recovery_run) / "run.json"
    external_snapshot = recovery_root / "snapshot-target"
    snapshot.replace(external_snapshot)
    try:
        snapshot.symlink_to(external_snapshot)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"File symlinks unavailable: {exc}")
    with pytest.raises(ProjectError, match="filesystem redirection"):
        build_execution_service().recover(recovery_root, recovery_run)
    assert external_snapshot.is_file()


def test_event_append_failure_never_changes_cancel_recovery_or_retry_state(
    tmp_path: Path,
) -> None:
    class WarningRepository(LocalExecutionRepository):
        def append_event(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            return RunWarning(code="event.append_failed", message="injected")

    cancel_root = tmp_path / "cancel event"
    build_project_service().create(cancel_root, "Cancel event")
    cancel_repository = WarningRepository()

    class CancellingStages(LocalFakeStages):
        def execute_sequence(self, workspace, *, start, settings, control):  # type: ignore[no-untyped-def]
            cancel_repository.request_cancellation(
                cancel_root, run_id=current_run_id(cancel_root)
            )
            control.checkpoint()

    cancelled = FakeExecutionService(cancel_repository, CancellingStages()).run(cancel_root)
    assert cancelled.status == "cancelled"
    assert query(cancel_root, "SELECT status FROM runs") == [("cancelled",)]

    recovery_root = tmp_path / "recovery event"
    build_project_service().create(recovery_root, "Recovery event")

    def crash_after_run(_root: Path) -> None:
        raise InjectedCrash("leave running run")

    with pytest.raises(InjectedCrash):
        FakeExecutionService(
            LocalExecutionRepository(
                fault_hooks=ExecutionFaultHooks(after_run_record=crash_after_run)
            ),
            LocalFakeStages(),
        ).run(recovery_root)
    recovery_run = current_run_id(recovery_root)
    recovered = FakeExecutionService(WarningRepository(), LocalFakeStages()).recover(
        recovery_root, recovery_run
    )
    assert recovered.status == "interrupted"
    assert recovered.warnings

    retry_root = tmp_path / "retry event"
    build_project_service().create(retry_root, "Retry event")
    class RetryTransient(LocalFakeStages):
        def execute_sequence(self, workspace, *, start, settings, control):  # type: ignore[no-untyped-def]
            raise OSError("transient")

    with pytest.raises(OSError):
        FakeExecutionService(LocalExecutionRepository(), RetryTransient()).run(retry_root)
    retry_run = UUID(query(retry_root, "SELECT run_id FROM runs")[0][0])
    retried = FakeExecutionService(WarningRepository(), LocalFakeStages()).retry(
        retry_root, retry_run
    )
    assert retried.status == "succeeded"
    assert retried.warnings
    assert query(retry_root, "SELECT status FROM runs") == [("succeeded",)]
