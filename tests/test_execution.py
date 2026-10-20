import json
import sqlite3
from contextlib import closing
from hashlib import sha256
from pathlib import Path
from uuid import UUID

import pytest

from splatforge.adapters.execution_storage import (
    ExecutionFaultHooks,
    LocalExecutionRepository,
)
from splatforge.adapters.fake_stages import LocalFakeStages
from splatforge.application.execution import (
    FakeExecutionService,
    PublicationUnresolvedError,
    UnresolvedExecutionError,
)
from splatforge.application.projects import ProjectError, ProjectWriterBusyError
from splatforge.bootstrap import build_execution_service, build_project_service
from splatforge.core.execution import RunWarning


def query(root: Path, statement: str, parameters: tuple[object, ...] = ()) -> list[tuple]:
    with closing(sqlite3.connect(root / "state.sqlite")) as connection:
        return connection.execute(statement, parameters).fetchall()


def artifact_payload(root: Path, manifest_path: str) -> Path:
    manifest = json.loads((root / manifest_path).read_text(encoding="utf-8"))
    return (root / manifest_path).parent / manifest["payloads"][0]["path"]


def artifact_files(root: Path) -> dict[str, bytes]:
    artifacts = root / "artifacts"
    return {
        path.relative_to(artifacts).as_posix(): path.read_bytes()
        for path in artifacts.rglob("*")
        if path.is_file()
    }


def test_successful_two_node_run_snapshot_lineage_events_and_unicode_path(
    tmp_path: Path,
) -> None:
    root = tmp_path / "Příliš žluťoučký execution project"
    project = build_project_service().create(root, "Fake route")

    result = build_execution_service().run(root, start=2, count=3, factor=4)

    assert result.status == "succeeded"
    assert result.cache_hits == ()
    assert set(result.outputs) == {"numbers", "scaled"}
    snapshot_path = root / "runs" / str(result.run_id) / "run.json"
    snapshot_bytes = snapshot_path.read_bytes()
    snapshot = json.loads(snapshot_bytes)
    assert snapshot["project_id"] == str(project.project_id)
    assert snapshot["project_revision"] == project.revision
    assert snapshot["route"]["sequence"]["start"] == 2
    assert snapshot["route"]["sequence"]["settings"] == {"count": 3}
    assert snapshot["route"]["scale"]["settings"] == {"factor": 4}
    assert snapshot["route"]["adapter_id"] == "splatforge.fake_python"
    assert snapshot["route"]["adapter_version"] == 1
    assert snapshot["route"]["seed_policy"] == "no_randomness"
    assert snapshot["route"]["scale"]["input"] == snapshot["route"]["sequence"][
        "output"
    ]
    assert '"artifact_id"' not in snapshot_bytes.decode("utf-8")

    attempts = query(
        root,
        """
        SELECT node_id, status, input_artifacts_json, literal_inputs_json,
               environment_json, source_verification_json
        FROM attempts ORDER BY created_at, attempt_id
        """,
    )
    assert attempts[0][0:4] == ("numbers", "succeeded", "[]", '{"start":2}')
    assert attempts[1][0:2] == ("scaled", "succeeded")
    assert json.loads(attempts[1][2]) == [str(result.outputs["numbers"].artifact_id)]
    assert attempts[1][3] == "{}"
    assert json.loads(attempts[0][4])["adapter_id"] == "splatforge.fake_python"
    assert json.loads(attempts[0][4])["python_version"]
    assert json.loads(attempts[0][5]) == {"evidence": [], "policy": "not_applicable"}


    numbers_payload = json.loads(
        artifact_payload(root, result.outputs["numbers"].manifest_path).read_text(
            encoding="utf-8"
        )
    )
    scaled_payload = json.loads(
        artifact_payload(root, result.outputs["scaled"].manifest_path).read_text(
            encoding="utf-8"
        )
    )
    assert numbers_payload["numbers"] == [2, 3, 4]
    assert scaled_payload["numbers"] == [8, 12, 16]
    scaled_manifest = json.loads(
        (root / result.outputs["scaled"].manifest_path).read_text(encoding="utf-8")
    )
    assert scaled_manifest["input_lineage"] == [
        {
            "input_name": "numbers",
            "artifact_id": str(result.outputs["numbers"].artifact_id),
            "artifact_type": result.outputs["numbers"].artifact_type,
            "contract_version": 1,
            "semantic_digest": result.outputs["numbers"].semantic_digest,
            "recipe_key": result.outputs["numbers"].recipe_key,
        }
    ]

    events = [
        json.loads(line)
        for line in (root / "runs" / str(result.run_id) / "events.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert [event["sequence"] for event in events] == list(range(1, len(events) + 1))
    assert events[0]["code"] == "run.started"
    assert events[-1]["code"] == "run.succeeded"
    assert {event["code"] for event in events} >= {
        "cache.miss",
        "attempt.started",
        "attempt.succeeded",
    }


def test_identical_run_reuses_both_artifacts_without_attempts_or_mutation(
    tmp_path: Path,
) -> None:
    build_project_service().create(tmp_path, "Cache")
    first = build_execution_service().run(tmp_path, start=1, count=4, factor=3)
    before = artifact_files(tmp_path)
    attempt_count = query(tmp_path, "SELECT count(*) FROM attempts")[0][0]

    second = build_execution_service().run(tmp_path, start=1, count=4, factor=3)

    assert second.cache_hits == ("numbers", "scaled")
    assert second.outputs["numbers"].artifact_id == first.outputs["numbers"].artifact_id
    assert second.outputs["scaled"].artifact_id == first.outputs["scaled"].artifact_id
    assert query(tmp_path, "SELECT count(*) FROM attempts")[0][0] == attempt_count == 2
    assert query(
        tmp_path,
        "SELECT binding_kind FROM run_outputs WHERE run_id=? ORDER BY node_id",
        (str(second.run_id),),
    ) == [("cache_hit",), ("cache_hit",)]
    assert artifact_files(tmp_path) == before


def test_downstream_setting_change_reuses_node_one_and_reruns_node_two(
    tmp_path: Path,
) -> None:
    build_project_service().create(tmp_path, "Downstream invalidation")
    first = build_execution_service().run(tmp_path, start=1, count=3, factor=2)
    second = build_execution_service().run(tmp_path, start=1, count=3, factor=5)

    assert second.cache_hits == ("numbers",)
    assert second.outputs["numbers"].artifact_id == first.outputs["numbers"].artifact_id
    assert second.outputs["scaled"].artifact_id != first.outputs["scaled"].artifact_id
    assert query(
        tmp_path,
        "SELECT node_id, count(*) FROM attempts GROUP BY node_id ORDER BY node_id",
    ) == [("numbers", 1), ("scaled", 2)]


def test_upstream_dependency_change_invalidates_both_nodes(tmp_path: Path) -> None:
    build_project_service().create(tmp_path, "Upstream invalidation")
    first = build_execution_service().run(tmp_path, start=1, count=3, factor=2)
    second = build_execution_service().run(tmp_path, start=2, count=3, factor=2)

    assert second.cache_hits == ()
    assert second.outputs["numbers"].artifact_id != first.outputs["numbers"].artifact_id
    assert second.outputs["scaled"].artifact_id != first.outputs["scaled"].artifact_id


@pytest.mark.parametrize("damage", ["missing", "corrupt"])
def test_invalid_cached_payload_is_not_reused(tmp_path: Path, damage: str) -> None:
    build_project_service().create(tmp_path, "Damaged cache")
    first = build_execution_service().run(tmp_path, start=1, count=3, factor=2)
    payload = artifact_payload(tmp_path, first.outputs["numbers"].manifest_path)
    if damage == "missing":
        payload.unlink()
    else:
        payload.write_bytes(b'{"contract_version":1,"numbers":[999]}\n')

    second = build_execution_service().run(tmp_path, start=1, count=3, factor=2)

    assert "numbers" not in second.cache_hits
    assert second.outputs["numbers"].artifact_id != first.outputs["numbers"].artifact_id
    assert query(
        tmp_path, "SELECT count(*) FROM attempts WHERE node_id='numbers'"
    ) == [(2,)]


def test_cache_checks_all_same_recipe_candidates_in_deterministic_order(
    tmp_path: Path,
) -> None:
    build_project_service().create(tmp_path, "Multiple publications")
    first = build_execution_service().run(tmp_path, start=7, count=2, factor=3)
    first_payload = artifact_payload(tmp_path, first.outputs["numbers"].manifest_path)
    original = first_payload.read_bytes()
    first_payload.write_bytes(b"corrupt first publication")

    second = build_execution_service().run(tmp_path, start=7, count=2, factor=3)
    second_payload = artifact_payload(tmp_path, second.outputs["numbers"].manifest_path)
    first_payload.write_bytes(original)
    second_payload.write_bytes(b"corrupt newest publication")

    third = build_execution_service().run(tmp_path, start=7, count=2, factor=3)

    assert third.outputs["numbers"].artifact_id == first.outputs["numbers"].artifact_id
    assert "numbers" in third.cache_hits
    events = [
        json.loads(line)
        for line in (tmp_path / "runs" / str(third.run_id) / "events.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    hit = next(
        event
        for event in events
        if event["code"] == "cache.hit" and event["node_id"] == "numbers"
    )
    assert hit["details"]["ineligible"][0]["artifact_id"] == str(
        second.outputs["numbers"].artifact_id
    )


def test_failure_after_move_leaves_unresolved_unindexed_publication(
    tmp_path: Path,
) -> None:
    build_project_service().create(tmp_path, "Unresolved publication")

    def fail_after_move(_path: Path) -> None:
        raise OSError("injected final-commit failure")

    repository = LocalExecutionRepository(
        fault_hooks=ExecutionFaultHooks(after_artifact_move=fail_after_move)
    )
    service = FakeExecutionService(repository, LocalFakeStages())

    with pytest.raises(PublicationUnresolvedError, match="final success commit"):
        service.run(tmp_path)

    attempts = query(
        tmp_path,
        """
        SELECT status, expected_artifact_id, expected_manifest_digest FROM attempts
        """,
    )
    assert attempts[0][0] == "running"
    assert attempts[0][1] is not None
    assert attempts[0][2] is not None
    assert query(tmp_path, "SELECT status FROM runs") == [("running",)]
    assert query(tmp_path, "SELECT count(*) FROM artifacts") == [(0,)]
    assert query(tmp_path, "SELECT count(*) FROM run_outputs") == [(0,)]
    publications = list((tmp_path / "artifacts" / "numbers").iterdir())
    assert len(publications) == 1
    assert (publications[0] / "manifest.json").is_file()

    with pytest.raises(UnresolvedExecutionError, match="unfinished run"):
        build_execution_service().run(tmp_path)
    assert publications[0].is_dir()


def test_only_one_stage_is_active_and_read_only_inspection_works_under_writer(
    tmp_path: Path,
) -> None:
    project = build_project_service().create(tmp_path, "Writer inspection")
    repository = LocalExecutionRepository()
    observations: list[str] = []

    class InspectingStages(LocalFakeStages):
        def _inspect(self) -> None:
            assert build_project_service().open(tmp_path) == project
            candidate = build_project_service().open(tmp_path)
            candidate.label = "Competing save"
            with pytest.raises(ProjectWriterBusyError):
                build_project_service().save(tmp_path, candidate)

            rows = query(
                tmp_path,
                "SELECT run_id, node_id FROM attempts WHERE status='running'",
            )
            assert len(rows) == 1
            rendered = json.loads(repository.show_run(tmp_path, UUID(rows[0][0])))
            assert rendered["state"]["status"] == "running"
            observations.append(rows[0][1])

        def execute_sequence(self, workspace, *, start, settings):  # type: ignore[no-untyped-def]
            self._inspect()
            super().execute_sequence(workspace, start=start, settings=settings)

        def execute_scale(  # type: ignore[no-untyped-def]
            self, workspace, *, input_payload, settings
        ):
            self._inspect()
            super().execute_scale(
                workspace, input_payload=input_payload, settings=settings
            )

    FakeExecutionService(repository, InspectingStages()).run(tmp_path)
    assert observations == ["numbers", "scaled"]


def test_event_append_failure_does_not_undo_authoritative_success(tmp_path: Path) -> None:
    build_project_service().create(tmp_path, "Event warning")

    class WarningRepository(LocalExecutionRepository):
        def append_event(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            return RunWarning(code="event.append_failed", message="injected")

    result = FakeExecutionService(WarningRepository(), LocalFakeStages()).run(tmp_path)

    assert result.status == "succeeded"
    assert result.warnings
    assert query(
        tmp_path, "SELECT status FROM runs WHERE run_id=?", (str(result.run_id),)
    ) == [("succeeded",)]
    assert query(tmp_path, "SELECT status FROM attempts ORDER BY created_at") == [
        ("succeeded",),
        ("succeeded",),
    ]


def test_unused_opaque_project_settings_do_not_block_fake_route(tmp_path: Path) -> None:
    build_project_service().create(tmp_path, "Opaque unrelated settings")
    path = tmp_path / "project.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["settings"]["mapping"] = {
        "method_id": "future.mapping",
        "settings_schema_version": 99,
        "settings": {"unknown": [1, 2, 3]},
        "future_field": True,
    }
    path.write_text(json.dumps(raw), encoding="utf-8")

    result = build_execution_service().run(tmp_path)

    assert result.status == "succeeded"


def test_active_attempt_blocks_new_run_before_snapshot_when_parent_is_not_running(
    tmp_path: Path,
) -> None:
    build_project_service().create(tmp_path, "Unresolved attempt")
    first = build_execution_service().run(tmp_path)
    attempt_id = query(
        tmp_path,
        "SELECT attempt_id FROM attempts ORDER BY created_at, attempt_id LIMIT 1",
    )[0][0]
    with closing(sqlite3.connect(tmp_path / "state.sqlite")) as connection, connection:
        connection.execute(
            "UPDATE attempts SET status='running', finished_at=NULL WHERE attempt_id=?",
            (attempt_id,),
        )

    run_count = query(tmp_path, "SELECT count(*) FROM runs")[0][0]
    snapshots = {
        path.relative_to(tmp_path).as_posix() for path in (tmp_path / "runs").glob("*/run.json")
    }

    with pytest.raises(UnresolvedExecutionError, match="unresolved attempt"):
        build_execution_service().run(tmp_path)

    assert query(tmp_path, "SELECT count(*) FROM runs") == [(run_count,)]
    assert {
        path.relative_to(tmp_path).as_posix() for path in (tmp_path / "runs").glob("*/run.json")
    } == snapshots
    assert query(
        tmp_path,
        "SELECT status FROM attempts WHERE attempt_id=?",
        (attempt_id,),
    ) == [("running",)]
    assert query(
        tmp_path,
        "SELECT status FROM runs WHERE run_id=?",
        (str(first.run_id),),
    ) == [("succeeded",)]


def test_writer_revalidates_raced_state_before_changing_diagnostics(
    tmp_path: Path,
) -> None:
    build_project_service().create(tmp_path, "Version race")
    diagnostics: list[dict[str, object]] = []

    def make_state_unsupported() -> None:
        with closing(sqlite3.connect(tmp_path / "state.sqlite")) as connection, connection:
            connection.execute("UPDATE metadata SET value='3' WHERE key='state_schema_version'")

    class RacingLease:
        def __enter__(self) -> "RacingLease":
            make_state_unsupported()
            return self

        def __exit__(self, *_args: object) -> None:
            pass

        def write_diagnostics(self, *, operation: str, owner_token: UUID) -> None:
            diagnostics.append({"operation": operation, "owner_token": owner_token})

    class RacingLockFactory:
        def __call__(self, _path: Path) -> RacingLease:
            return RacingLease()

    repository = LocalExecutionRepository(lock_factory=RacingLockFactory())

    with pytest.raises(ProjectError, match="Unsupported newer project versions"):
        FakeExecutionService(repository, LocalFakeStages()).run(tmp_path)

    assert diagnostics == []
    assert query(tmp_path, "SELECT count(*) FROM runs") == [(0,)]
    assert not (tmp_path / "runs").exists()


@pytest.mark.parametrize("owned_name", ["runs", "work", "artifacts"])
def test_execution_refuses_owned_directory_symlink_before_writing_through_it(
    tmp_path: Path,
    owned_name: str,
) -> None:
    root = tmp_path / f"{owned_name} redirection project"
    build_project_service().create(root, "Owned path redirection")
    redirected_target = root / f"{owned_name}-target"
    redirected_target.mkdir()
    try:
        (root / owned_name).symlink_to(redirected_target, target_is_directory=True)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"Directory symlinks unavailable: {exc}")

    with pytest.raises(ProjectError, match="filesystem redirection"):
        build_execution_service().run(root)

    assert list(redirected_target.iterdir()) == []


def test_cache_refuses_manifest_payload_through_directory_symlink(
    tmp_path: Path,
) -> None:
    build_project_service().create(tmp_path, "Manifest payload redirection")
    first = build_execution_service().run(tmp_path)
    handle = first.outputs["numbers"]
    manifest_path = tmp_path / handle.manifest_path
    artifact_directory = manifest_path.parent
    original_payload = artifact_payload(tmp_path, handle.manifest_path)
    redirected_target = artifact_directory / "payload-target"
    redirected_target.mkdir()
    original_payload.replace(redirected_target / original_payload.name)
    try:
        (artifact_directory / "redirect").symlink_to(redirected_target, target_is_directory=True)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"Directory symlinks unavailable: {exc}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["payloads"][0]["path"] = f"redirect/{original_payload.name}"
    manifest_bytes = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    manifest_path.write_bytes(manifest_bytes)
    with closing(sqlite3.connect(tmp_path / "state.sqlite")) as connection, connection:
        connection.execute(
            "UPDATE artifacts SET manifest_digest=? WHERE artifact_id=?",
            (sha256(manifest_bytes).hexdigest(), str(handle.artifact_id)),
        )

    second = build_execution_service().run(tmp_path)

    assert "numbers" not in second.cache_hits
    assert second.outputs["numbers"].artifact_id != handle.artifact_id
    events = [
        json.loads(line)
        for line in (tmp_path / "runs" / str(second.run_id) / "events.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    miss = next(
        event for event in events if event["code"] == "cache.miss" and event["node_id"] == "numbers"
    )
    assert "filesystem redirection" in miss["details"]["ineligible"][0]["reason"]
