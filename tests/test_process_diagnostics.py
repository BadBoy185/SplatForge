"""Bounded attempt diagnostics, secret-conscious projection and optional failures."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError
from test_ffmpeg import FakeRunner, result
from test_views_execution import BACKEND, harness, png, prepare, query
from typer.testing import CliRunner

from splatforge.adapters.ffmpeg import FFmpegAdapter
from splatforge.adapters.process_diagnostics import invocation_evidence
from splatforge.adapters.process_runner import ProcessCleanupError, ProcessRequest
from splatforge.cli.app import app
from splatforge.core.process import (
    MAX_PROCESS_RECORD_BYTES,
    PROCESS_EXCERPT_BYTES,
    ProcessInvocationEvidence,
)


def setup_route(tmp_path: Path, *, mode: str = "succeeded"):
    value = harness(tmp_path)
    captures = []
    active_cancellation = None

    def callback(request, _index):
        identity = BACKEND.model_copy(update={"version_line": None})
        if request.argv == ("-version",):
            return result(request, identity=identity, stdout=b"ffmpeg version fake\n")
        if mode.startswith("exception"):
            raise ProcessCleanupError(
                ValueError("original synthetic cause"),
                teardown_confirmed=mode == "exception_confirmed",
                forced_tree_termination=True, cleanup_errors=("synthetic cleanup error",),
            )
        if mode == "cancelled":
            run_id = UUID(query(value.root, "SELECT run_id FROM runs WHERE status='running'")[0][0])
            value.execution.request_cancellation(value.root, run_id=run_id)
            # The real runner calls this before returning cancellation.
            assert active_cancellation.is_cancelled()
        pattern = Path(request.argv[-1])
        photo = "-frames:v" in request.argv
        for index in range(1 if photo else 3):
            Path(str(pattern).replace("%08d", f"{index:08d}")).write_bytes(png(16, 12))
        stderr = (
            b"config in time_base: 1/10, frame_rate: 0/1\n"
            b"n: 0 pts: 0 pts_time:0\nn: 1 pts: 7 pts_time:0.7\nn: 2 pts: 10 pts_time:1\n"
            + b"bounded human-readable backend output\n" * 2000
        )
        stdout = b"stdout debug\n" * 3000
        captures.append((stdout, stderr))
        return result(
            request, identity=identity, stdout=stdout, stderr=stderr,
            exit_code=4 if mode == "nonzero_exit" else 0,
            cancelled=mode == "cancelled", timed_out=mode == "timeout",
            teardown_confirmed=mode != "teardown_unconfirmed",
            forced_tree_termination=mode in {"forced_tree_termination", "cancelled", "timeout"},
        )

    class CapturingRunner(FakeRunner):
        def run(self, request, *, cancellation=None):
            nonlocal active_cancellation
            active_cancellation = cancellation
            return super().run(request, cancellation=cancellation)

    value.service._materializer = FFmpegAdapter(runner=CapturingRunner(callback))
    return value, captures


def diagnostic_records(value):
    run_id, attempt_id = query(
        value.root, "SELECT run_id, attempt_id FROM attempts WHERE node_id='candidate_views'"
    )[0]
    path = value.root / "runs" / run_id / "attempts" / attempt_id / "process.jsonl"
    return path, [json.loads(line) for line in path.read_bytes().splitlines()]


def test_success_exact_identity_multiple_invocations_bounded_streams_and_run_show(
    tmp_path: Path, monkeypatch,
) -> None:
    monkeypatch.setenv("SPLATFORGE_FAKE_API_TOKEN", "must-never-be-serialized")
    value, captures = setup_route(tmp_path)
    completed = prepare(value)
    path, records = diagnostic_records(value)
    assert completed.status == "succeeded" and len(records) == 2
    assert [r["invocation_index"] for r in records] == [1, 2]
    for record, streams in zip(records, captures, strict=True):
        for name, data in zip(("stdout", "stderr"), streams, strict=True):
            assert record[f"{name}_captured_bytes"] == len(data)
            assert record[f"{name}_sha256"] == hashlib.sha256(data).hexdigest()
            assert len(record[f"{name}_excerpt"].encode()) <= PROCESS_EXCERPT_BYTES
            assert record[f"{name}_excerpt_truncated"] is True
        assert record["executable"] == BACKEND.model_dump(mode="json")
        assert record["executable_identity_source"] == "process_result"
        assert record["scoped_environment"] == {} and record["outcome"] == "succeeded"
        assert len(json.dumps(record).encode()) < MAX_PROCESS_RECORD_BYTES
    for record, request in zip(
        records, value.service._materializer._runner.requests[1:], strict=True,
    ):
        assert record["argv"] == list(request.argv)
        assert record["working_directory"] == str(request.working_directory)
    encoded = path.read_text(encoding="utf-8")
    assert "must-never-be-serialized" not in encoded and "SPLATFORGE_FAKE_API_TOKEN" not in encoded
    assert "M3 Příliš žluťoučký project" in encoded
    shown = json.loads(value.execution.show_run(value.root, completed.run_id))
    summary = shown["attempts"][0]["process_diagnostics"]
    assert summary["invocation_count"] == 2 and summary["truncated"]
    assert value.root / summary["path"] == path
    assert "stdout debug" not in json.dumps(shown)
    shown_cli = CliRunner().invoke(app, ["run", "show", str(value.root), str(completed.run_id)])
    assert shown_cli.exit_code == 0
    assert json.loads(shown_cli.output)["attempts"][0]["process_diagnostics"] == summary
    assert "stdout debug" not in shown_cli.output
    manifest = (value.root / completed.candidate_artifact.manifest_path).read_text()
    assert "process.jsonl" not in manifest
    path.write_bytes(path.read_bytes() + b"diagnostic-only corruption\n")
    cached = prepare(value)
    assert cached.candidate_artifact == completed.candidate_artifact
    assert cached.cache_hits == ("candidate_views", "selected_views")


@pytest.mark.parametrize("mode", (
    "nonzero_exit", "timeout", "cancelled", "forced_tree_termination",
    "teardown_unconfirmed", "exception_confirmed", "exception_unconfirmed",
))
def test_failures_retain_evidence_and_preserve_teardown(tmp_path: Path, mode: str) -> None:
    value, _ = setup_route(tmp_path, mode=mode)
    if mode in {"cancelled", "teardown_unconfirmed", "exception_unconfirmed"}:
        completed = prepare(value)
        assert completed.status == ("cancelled" if mode == "cancelled" else "interrupted")
    else:
        with pytest.raises(ValueError):
            prepare(value)
    _, records = diagnostic_records(value)
    assert len(records) == 1
    record = records[0]
    if mode.startswith("exception"):
        assert record["outcome"] == "exception"
        assert record["stdout_sha256"] is None and record["stdout_captured_bytes"] is None
        assert record["stderr_excerpt"] is None
        assert record["original_exception_type"] == "ValueError"
        assert record["executable_identity_source"] == "frozen_request"
        assert record["failure_summary"] == "ValueError: original synthetic cause"
        assert record["cleanup_errors"] == ["synthetic cleanup error"]
        assert record["teardown_confirmed"] == (mode == "exception_confirmed")
    else:
        assert record["outcome"] == mode
    assert query(value.root, "SELECT count(*) FROM artifacts") == [(0,)]
    failure = query(value.root, "SELECT failure_json FROM attempts")[0][0]
    assert "bounded human-readable backend output" not in str(failure)


@pytest.mark.parametrize("successful_appends", (0, 1))
def test_append_failure_warns_and_preserves_numerical_success(
    tmp_path: Path, monkeypatch, successful_appends: int,
) -> None:
    value, _ = setup_route(tmp_path)
    original = Path.open
    count = 0

    def fail_append(path, mode="r", *args, **kwargs):
        nonlocal count
        if path.name == "process.jsonl" and mode == "ab":
            count += 1
            if count > successful_appends:
                raise OSError("synthetic optional append failure")
        return original(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", fail_append)
    completed = prepare(value)
    assert completed.status == "succeeded"
    assert any(w.code == "process.diagnostics_append_failed" for w in completed.warnings)
    assert query(value.root, "SELECT count(*) FROM artifacts") == [(2,)]
    shown = json.loads(value.execution.show_run(value.root, completed.run_id))
    assert shown["attempts"][0]["process_diagnostics"]["invocation_count"] == successful_appends
    events = (value.root / "runs" / str(completed.run_id) / "events.jsonl").read_text()
    assert "process.diagnostics_append_failed" in events


def test_total_retention_bound_is_deterministic_and_optional(tmp_path: Path, monkeypatch) -> None:
    import splatforge.adapters.execution_storage as storage

    monkeypatch.setattr(storage, "MAX_ATTEMPT_DIAGNOSTIC_BYTES", 80 * 1024)
    value, _ = setup_route(tmp_path)
    completed = prepare(value)
    path, records = diagnostic_records(value)
    record = records[0]
    run_id, attempt_id = UUID(record.pop("run_id")), UUID(record.pop("attempt_id"))
    evidence = ProcessInvocationEvidence.model_validate(record)
    for _ in range(10):
        warning = value.execution.append_process_evidence(value.root, run_id, attempt_id, evidence)
    assert warning.code == "process.diagnostics_truncated"
    assert path.stat().st_size <= 80 * 1024
    assert json.loads(path.read_bytes().splitlines()[-1])["retention_limit_reached"]
    size = path.stat().st_size
    value.execution.append_process_evidence(value.root, run_id, attempt_id, evidence)
    assert path.stat().st_size == size and completed.status == "succeeded"
    shown = json.loads(value.execution.show_run(value.root, completed.run_id))
    assert shown["attempts"][0]["process_diagnostics"]["truncated"]


def test_explicit_redacted_argv_environment_projection_and_invalid_utf8(tmp_path: Path) -> None:
    request = ProcessRequest(
        executable=BACKEND.resolved_path, argv=("--token", "never-record-this"),
        working_directory=tmp_path / "space žluťoučký", environment={"API_KEY": "secret"},
        timeout_seconds=3,
    )
    completed = result(request, identity=BACKEND, stdout=b"\xff" * 40_000, stdout_truncated=True)
    evidence = invocation_evidence(
        request, executable=BACKEND, diagnostic_argv=("--token", "[REDACTED]"),
        tool_role="future.explicit", source_id=None, elapsed_seconds=0, result=completed,
    )
    assert "never-record-this" not in evidence.model_dump_json()
    assert "secret" not in evidence.model_dump_json() and evidence.stdout_truncated
    assert len(evidence.stdout_excerpt.encode()) <= PROCESS_EXCERPT_BYTES
    with pytest.raises(ValidationError):
        ProcessInvocationEvidence.model_validate({
            **evidence.model_dump(), "scoped_environment": {"API_KEY": "secret"},
        })


def test_record_bound_and_unexpected_sink_failure_are_optional(tmp_path: Path) -> None:
    value, _ = setup_route(tmp_path)

    def fail_record(*args):
        raise OSError("injected unexpected sink failure")

    value.execution.append_process_evidence = fail_record
    with pytest.warns(RuntimeWarning, match="diagnostic recording failed"):
        assert prepare(value).status == "succeeded"
    request = ProcessRequest(
        executable=BACKEND.resolved_path, argv=("x" * 4096,) * 100,
        working_directory=tmp_path, environment={}, timeout_seconds=1,
    )
    with pytest.raises(ValidationError, match="record byte bound"):
        invocation_evidence(
            request, executable=BACKEND, diagnostic_argv=request.argv, tool_role="test",
            source_id=None, elapsed_seconds=0, result=result(request, identity=BACKEND),
        )


def test_control_character_excerpts_fit_the_record_bound(tmp_path: Path) -> None:
    request = ProcessRequest(
        executable=BACKEND.resolved_path, argv=(), working_directory=tmp_path,
        environment={}, timeout_seconds=1,
    )
    evidence = invocation_evidence(
        request, executable=BACKEND, diagnostic_argv=(), tool_role="test", source_id=None,
        elapsed_seconds=0,
        result=result(request, identity=BACKEND, stdout=b"\0" * 20000, stderr=b"\0" * 20000),
    )
    assert len(evidence.model_dump_json().encode()) < MAX_PROCESS_RECORD_BYTES
    assert evidence.stdout_excerpt_truncated and evidence.stderr_excerpt_truncated


@pytest.mark.parametrize("damage", (b"[]\n", b"\n", b"incomplete", b"{}\n"))
def test_run_show_tolerates_corrupt_optional_diagnostics(tmp_path: Path, damage: bytes) -> None:
    value, _ = setup_route(tmp_path)
    completed = prepare(value)
    path, _ = diagnostic_records(value)
    path.write_bytes(damage)
    shown = json.loads(value.execution.show_run(value.root, completed.run_id))
    summary = shown["attempts"][0]["process_diagnostics"]
    assert summary["truncated"] and summary["warning"]
    assert shown["state"]["status"] == "succeeded"
