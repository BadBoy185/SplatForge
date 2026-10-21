"""One-shot contained launcher used by the Windows process boundary."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

_MAX_LAUNCH_MESSAGE = 1024 * 1024


def _fail(message: str, code: int = 127) -> int:
    sys.stderr.write(f"SplatForge process worker: {message}\n")
    sys.stderr.flush()
    return code


def main() -> int:
    payload = sys.stdin.buffer.readline(_MAX_LAUNCH_MESSAGE + 1)
    if not payload or len(payload) > _MAX_LAUNCH_MESSAGE or not payload.endswith(b"\n"):
        return _fail("invalid or oversized launch message")
    try:
        message = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return _fail(f"invalid launch JSON: {exc}")
    if not isinstance(message, dict) or set(message) != {"executable", "argv", "cwd", "env"}:
        return _fail("invalid launch fields")
    executable = message["executable"]
    argv = message["argv"]
    cwd = message["cwd"]
    environment = message["env"]
    if (
        not isinstance(executable, str)
        or not Path(executable).is_absolute()
        or not isinstance(argv, list)
        or not all(isinstance(value, str) for value in argv)
        or not isinstance(cwd, str)
        or not Path(cwd).is_absolute()
        or not isinstance(environment, dict)
        or not all(
            isinstance(key, str) and isinstance(value, str) for key, value in environment.items()
        )
    ):
        return _fail("invalid launch value types")
    if os.name == "nt" and Path(executable).suffix.lower() != ".exe":
        return _fail("Windows backend must be a native .exe entrypoint")
    try:
        process = subprocess.Popen(
            [executable, *argv],
            shell=False,
            cwd=cwd,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=sys.stdout.buffer,
            stderr=sys.stderr.buffer,
            close_fds=True,
        )
        return_code = process.wait()
    except OSError as exc:
        return _fail(f"backend launch failed: {exc}")
    sys.stdout.buffer.flush()
    sys.stderr.buffer.flush()
    if return_code < 0:
        return 128 + min(-return_code, 127)
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
