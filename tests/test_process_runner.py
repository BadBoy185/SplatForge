from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

import splatforge.adapters.process_runner as process_runner_module
from splatforge.adapters.process_runner import (
    ExecutableResolver,
    LocalProcessRunner,
    ProcessBoundaryError,
    ProcessRequest,
)


def request(
    cwd: Path,
    *argv: str,
    timeout: float = 10.0,
    stdout_limit: int = 1024 * 1024,
    stderr_limit: int = 1024 * 1024,
    environment: dict[str, str] | None = None,
    teardown_timeout: float = 5.0,
) -> ProcessRequest:
    return ProcessRequest(
        executable=sys.executable,
        argv=argv,
        working_directory=cwd,
        environment=environment or {},
        timeout_seconds=timeout,
        max_stdout_bytes=stdout_limit,
        max_stderr_bytes=stderr_limit,
        teardown_timeout_seconds=teardown_timeout,
    )


def test_success_exact_unicode_argv_cwd_scoped_env_and_shell_false(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cwd = tmp_path / "space žluťoučký"
    cwd.mkdir()
    observed_shell: list[object] = []
    original = subprocess.Popen

    def recording_popen(*args, **kwargs):  # type: ignore[no-untyped-def]
        observed_shell.append(kwargs.get("shell"))
        return original(*args, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", recording_popen)
    argument = "value with spaces žluťoučký"
    code = (
        "import os,sys;"
        "os.write(1, ('\\n'.join((sys.argv[1],os.getcwd(),"
        "os.environ['SPLATFORGE_PROCESS_TEST']))+'\\n').encode('utf-8'))"
    )

    result = LocalProcessRunner().run(
        request(
            cwd,
            "-c",
            code,
            argument,
            environment={"SPLATFORGE_PROCESS_TEST": "scoped"},
        )
    )

    lines = result.stdout_text().splitlines()
    assert result.exit_code == 0
    assert result.argv == ("-c", code, argument)
    assert lines == [argument, str(cwd), "scoped"]
    assert result.teardown_confirmed is True
    assert result.forced_tree_termination is False
    assert observed_shell == [False]
    assert "SPLATFORGE_PROCESS_TEST" not in os.environ


def test_nonzero_exit_and_stderr_capture(tmp_path: Path) -> None:
    result = LocalProcessRunner().run(
        request(
            tmp_path,
            "-c",
            "import sys;sys.stderr.write('diagnostic');raise SystemExit(7)",
        )
    )

    assert result.exit_code == 7
    assert result.stderr == b"diagnostic"
    assert result.timed_out is False
    assert result.cancelled is False
    assert result.teardown_confirmed is True
    assert result.forced_tree_termination is False


def test_both_streams_are_drained_and_bounded_without_deadlock(tmp_path: Path) -> None:
    code = "import os;[(os.write(1,b'o'*4096),os.write(2,b'e'*4096)) for _ in range(128)]"

    result = LocalProcessRunner().run(
        request(tmp_path, "-c", code, stdout_limit=8192, stderr_limit=4096)
    )

    assert result.exit_code == 0
    assert len(result.stdout) == 8192
    assert len(result.stderr) == 4096
    assert result.stdout_truncated is True
    assert result.stderr_truncated is True
    assert result.teardown_confirmed is True
    assert result.forced_tree_termination is False


def test_timeout_is_not_an_ordinary_exit(tmp_path: Path) -> None:
    result = LocalProcessRunner().run(
        request(tmp_path, "-c", "import time;time.sleep(30)", timeout=0.2)
    )

    assert result.exit_code is None
    assert result.timed_out is True
    assert result.cancelled is False
    assert result.teardown_confirmed is True
    assert result.forced_tree_termination is True


class CancelAfterPolls:
    def __init__(self, count: int = 3) -> None:
        self.remaining = count

    def is_cancelled(self) -> bool:
        self.remaining -= 1
        return self.remaining <= 0


def test_cooperative_cancellation_is_not_an_ordinary_exit(tmp_path: Path) -> None:
    result = LocalProcessRunner().run(
        request(tmp_path, "-c", "import time;time.sleep(30)"),
        cancellation=CancelAfterPolls(),
    )

    assert result.exit_code is None
    assert result.cancelled is True
    assert result.timed_out is False
    assert result.teardown_confirmed is True
    assert result.forced_tree_termination is True


def test_executable_cache_invalidates_same_size_mtime_replacement(tmp_path: Path) -> None:
    executable = tmp_path / "backend.exe"
    replacement = tmp_path / "replacement.exe"
    timestamp = 1_700_000_000_000_000_000
    executable.write_bytes(b"first-binary")
    os.utime(executable, ns=(timestamp, timestamp))
    resolver = ExecutableResolver()

    first = resolver.resolve(str(executable))
    replacement.write_bytes(b"other-binary")
    os.utime(replacement, ns=(timestamp, timestamp))
    os.replace(replacement, executable)
    second = resolver.resolve(str(executable))

    assert first.size == second.size
    assert first.last_write_ns == second.last_write_ns
    assert first.sha256 == hashlib.sha256(b"first-binary").hexdigest()
    assert second.sha256 == hashlib.sha256(b"other-binary").hexdigest()
    assert second.sha256 != first.sha256


def test_unconfirmed_teardown_is_structured_not_fabricated_success(tmp_path: Path) -> None:
    class UnconfirmedRunner(LocalProcessRunner):
        @staticmethod
        def _wait_tree_empty(process, job, timeout):  # type: ignore[no-untyped-def]
            return False, True

    result = UnconfirmedRunner().run(request(tmp_path, "-c", "pass"))

    assert result.exit_code == 0
    assert result.teardown_confirmed is False
    assert result.forced_tree_termination is True


@pytest.mark.skipif(os.name != "nt", reason="Windows Job Object setup ordering")
def test_job_setup_failure_spawns_no_worker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    popen_calls = 0

    class SetupFailureJob:
        def __init__(self) -> None:
            raise ProcessBoundaryError("job setup sentinel")

    def unexpected_popen(*args, **kwargs):  # type: ignore[no-untyped-def]
        nonlocal popen_calls
        popen_calls += 1
        raise AssertionError("worker must not spawn before Job setup")

    monkeypatch.setattr(process_runner_module, "_WindowsJob", SetupFailureJob)
    monkeypatch.setattr(process_runner_module.subprocess, "Popen", unexpected_popen)

    with pytest.raises(ProcessBoundaryError, match="job setup sentinel"):
        LocalProcessRunner().run(request(tmp_path, "-c", "pass"))

    assert popen_calls == 0


@pytest.mark.skipif(os.name != "nt", reason="Windows Job Object spawn cleanup")
def test_worker_spawn_failure_closes_empty_job(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    jobs = []

    class TrackingJob:
        def __init__(self) -> None:
            self.closed = False
            jobs.append(self)

        def close(self) -> None:
            self.closed = True

    def fail_spawn(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise OSError("worker spawn sentinel")

    monkeypatch.setattr(process_runner_module, "_WindowsJob", TrackingJob)
    monkeypatch.setattr(process_runner_module.subprocess, "Popen", fail_spawn)

    with pytest.raises(OSError, match="worker spawn sentinel"):
        LocalProcessRunner().run(request(tmp_path, "-c", "pass"))

    assert len(jobs) == 1
    assert jobs[0].closed is True


@pytest.mark.skipif(os.name != "nt", reason="Windows Job Object assignment cleanup")
def test_job_assignment_failure_preserves_error_and_reaps_waiting_worker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    backend_marker = tmp_path / "backend-launched.marker"
    workers: list[subprocess.Popen[bytes]] = []
    jobs = []
    original_popen = subprocess.Popen

    class AssignmentFailureJob:
        def __init__(self) -> None:
            self.closed = False
            jobs.append(self)

        def assign(self, process: subprocess.Popen[bytes]) -> None:
            raise ProcessBoundaryError("job assignment sentinel")

        def close(self) -> None:
            self.closed = True

    def recording_popen(*args, **kwargs):  # type: ignore[no-untyped-def]
        process = original_popen(*args, **kwargs)
        workers.append(process)
        return process

    monkeypatch.setattr(process_runner_module, "_WindowsJob", AssignmentFailureJob)
    monkeypatch.setattr(process_runner_module.subprocess, "Popen", recording_popen)
    backend = (
        "from pathlib import Path;import sys;"
        "Path(sys.argv[1]).write_text('launched', encoding='utf-8')"
    )

    with pytest.raises(ProcessBoundaryError, match="job assignment sentinel") as raised:
        LocalProcessRunner().run(
            request(tmp_path, "-c", backend, str(backend_marker))
        )

    assert "cannot join thread" not in str(raised.value)
    assert not backend_marker.exists()
    assert len(workers) == 1
    assert workers[0].poll() is not None
    assert workers[0].stdin is not None and workers[0].stdin.closed
    assert workers[0].stdout is not None and workers[0].stdout.closed
    assert workers[0].stderr is not None and workers[0].stderr.closed
    assert len(jobs) == 1
    assert jobs[0].closed is True


@pytest.mark.skipif(os.name != "nt", reason="Windows Job Object tree containment")
def test_cancellation_kills_descendant_holding_file_lock(tmp_path: Path) -> None:
    child = tmp_path / "child.py"
    parent = tmp_path / "parent.py"
    lock_file = tmp_path / "held.lock"
    ready = tmp_path / "ready.marker"
    child.write_text(
        """
import msvcrt
import sys
import time
from pathlib import Path

lock_path = Path(sys.argv[1])
ready_path = Path(sys.argv[2])
with lock_path.open("a+b") as stream:
    stream.write(b"x")
    stream.flush()
    stream.seek(0)
    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
    ready_path.write_text("ready", encoding="utf-8")
    while True:
        time.sleep(10)
""".lstrip(),
        encoding="utf-8",
    )
    parent.write_text(
        """
import subprocess
import sys
import time

subprocess.Popen([sys.executable, sys.argv[1], sys.argv[2], sys.argv[3]])
while True:
    time.sleep(10)
""".lstrip(),
        encoding="utf-8",
    )

    class CancelWhenReady:
        def is_cancelled(self) -> bool:
            return ready.exists()

    result = LocalProcessRunner().run(
        request(tmp_path, str(parent), str(child), str(lock_file), str(ready)),
        cancellation=CancelWhenReady(),
    )

    assert result.cancelled is True
    assert result.teardown_confirmed is True
    with lock_file.open("r+b") as stream:
        import msvcrt

        stream.seek(0)
        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)


@pytest.mark.skipif(os.name != "nt", reason="Windows Job Object timeout tree containment")
def test_timeout_kills_descendant_holding_file_lock(tmp_path: Path) -> None:
    child = tmp_path / "timeout_child.py"
    parent = tmp_path / "timeout_parent.py"
    lock_file = tmp_path / "timeout-held.lock"
    ready = tmp_path / "timeout-ready.marker"
    child.write_text(
        """
import msvcrt
import sys
import time
from pathlib import Path

with Path(sys.argv[1]).open("a+b") as stream:
    stream.write(b"x")
    stream.flush()
    stream.seek(0)
    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
    Path(sys.argv[2]).write_text("ready", encoding="utf-8")
    while True:
        time.sleep(10)
""".lstrip(),
        encoding="utf-8",
    )
    parent.write_text(
        """
import subprocess
import sys
import time
from pathlib import Path

subprocess.Popen([sys.executable, sys.argv[1], sys.argv[2], sys.argv[3]])
deadline = time.monotonic() + 10
while not Path(sys.argv[3]).exists() and time.monotonic() < deadline:
    time.sleep(0.01)
while True:
    time.sleep(10)
""".lstrip(),
        encoding="utf-8",
    )

    result = LocalProcessRunner().run(
        request(
            tmp_path,
            str(parent),
            str(child),
            str(lock_file),
            str(ready),
            timeout=2.0,
        )
    )

    assert ready.exists(), "descendant did not acquire its handle before timeout"
    assert result.timed_out is True
    assert result.teardown_confirmed is True
    with lock_file.open("r+b") as stream:
        import msvcrt

        stream.seek(0)
        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)


@pytest.mark.skipif(os.name != "nt", reason="Windows Job Object survivor cleanup")
def test_clean_backend_exit_forces_surviving_descendant_cleanup(tmp_path: Path) -> None:
    child = tmp_path / "survivor_child.py"
    backend = tmp_path / "survivor_backend.py"
    lock_file = tmp_path / "survivor-held.lock"
    ready = tmp_path / "survivor-ready.marker"
    child.write_text(
        """
import msvcrt
import sys
import time
from pathlib import Path

with Path(sys.argv[1]).open("a+b") as stream:
    stream.write(b"x")
    stream.flush()
    stream.seek(0)
    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
    Path(sys.argv[2]).write_text("ready", encoding="utf-8")
    while True:
        time.sleep(10)
""".lstrip(),
        encoding="utf-8",
    )
    backend.write_text(
        """
import subprocess
import sys
import time
from pathlib import Path

subprocess.Popen([sys.executable, sys.argv[1], sys.argv[2], sys.argv[3]])
deadline = time.monotonic() + 10
while not Path(sys.argv[3]).exists() and time.monotonic() < deadline:
    time.sleep(0.01)
raise SystemExit(0 if Path(sys.argv[3]).exists() else 4)
""".lstrip(),
        encoding="utf-8",
    )

    result = LocalProcessRunner().run(
        request(
            tmp_path,
            str(backend),
            str(child),
            str(lock_file),
            str(ready),
            teardown_timeout=0.5,
        )
    )

    assert ready.exists(), "descendant did not acquire its handle before backend exit"
    assert result.exit_code == 0
    assert result.timed_out is False
    assert result.cancelled is False
    assert result.forced_tree_termination is True
    assert result.teardown_confirmed is True
    with lock_file.open("r+b") as stream:
        import msvcrt

        stream.seek(0)
        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)


@pytest.mark.skipif(os.name != "nt", reason="Windows Job Object kill-on-close")
def test_owner_death_kills_contained_descendant_and_releases_handle(tmp_path: Path) -> None:
    child = tmp_path / "owner_child.py"
    backend = tmp_path / "owner_backend.py"
    owner = tmp_path / "owner.py"
    lock_file = tmp_path / "owner-held.lock"
    ready = tmp_path / "owner-ready.marker"
    child.write_text(
        """
import msvcrt
import sys
import time
from pathlib import Path

with Path(sys.argv[1]).open("a+b") as stream:
    stream.write(b"x")
    stream.flush()
    stream.seek(0)
    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
    Path(sys.argv[2]).write_text("ready", encoding="utf-8")
    while True:
        time.sleep(10)
""".lstrip(),
        encoding="utf-8",
    )
    backend.write_text(
        """
import subprocess
import sys
import time

subprocess.Popen([sys.executable, sys.argv[1], sys.argv[2], sys.argv[3]])
while True:
    time.sleep(10)
""".lstrip(),
        encoding="utf-8",
    )
    owner.write_text(
        """
import sys
from pathlib import Path
from splatforge.adapters.process_runner import LocalProcessRunner, ProcessRequest

LocalProcessRunner().run(ProcessRequest(
    executable=sys.executable,
    argv=(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]),
    working_directory=Path(sys.argv[5]),
    environment={},
    timeout_seconds=60,
))
""".lstrip(),
        encoding="utf-8",
    )
    owner_process = subprocess.Popen(
        [
            sys.executable,
            str(owner),
            str(backend),
            str(child),
            str(lock_file),
            str(ready),
            str(tmp_path),
        ],
        shell=False,
        cwd=tmp_path,
    )
    deadline = time.monotonic() + 15
    while not ready.exists() and time.monotonic() < deadline:
        if owner_process.poll() is not None:
            pytest.fail(f"owner exited before readiness: {owner_process.returncode}")
        time.sleep(0.02)
    assert ready.exists(), "contained descendant did not report readiness"

    owner_process.kill()
    owner_process.wait(timeout=5)
    while time.monotonic() < deadline:
        try:
            with lock_file.open("r+b") as stream:
                import msvcrt

                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            break
        except OSError:
            time.sleep(0.02)
    else:
        pytest.fail("owner death did not release the descendant file lock")
