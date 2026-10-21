"""Explicit bounded process evidence construction; no automatic global recording."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from uuid import UUID

from splatforge.adapters.process_runner import ProcessCleanupError, ProcessRequest
from splatforge.core.media import ExecutableIdentity
from splatforge.core.process import PROCESS_EXCERPT_BYTES, ProcessInvocationEvidence, ProcessResult

type ProcessEvidenceSink = Callable[[ProcessInvocationEvidence], None]


def invocation_evidence(
    request: ProcessRequest,
    *,
    executable: ExecutableIdentity,
    diagnostic_argv: tuple[str, ...],
    tool_role: str,
    source_id: UUID | None,
    elapsed_seconds: float,
    scoped_environment: Mapping[str, str] | None = None,
    result: ProcessResult | None = None,
    error: Exception | None = None,
) -> ProcessInvocationEvidence:
    """Only explicit safe argv/environment projections can enter durable evidence."""
    fields: dict[str, object] = {}
    if result is not None:
        outcome = (
            "cancelled" if result.cancelled else
            "timeout" if result.timed_out and result.teardown_confirmed else
            "teardown_unconfirmed" if not result.teardown_confirmed else
            "forced_tree_termination" if result.forced_tree_termination else
            "nonzero_exit" if result.exit_code != 0 else "succeeded"
        )
        for name in ("stdout", "stderr"):
            data = getattr(result, name)
            excerpt = data[:PROCESS_EXCERPT_BYTES].decode("utf-8", errors="replace")
            # Replacement characters can expand invalid UTF-8 bytes.
            excerpt = excerpt.encode("utf-8")[:PROCESS_EXCERPT_BYTES].decode("utf-8", "ignore")
            # Control characters need up to six JSON bytes per readable byte.
            # Keep both stream representations within the record's total budget.
            while len(json.dumps(excerpt, ensure_ascii=False).encode("utf-8")) > 32 * 1024:
                excerpt = excerpt[:len(excerpt) // 2]
            fields.update({
                f"{name}_captured_bytes": len(data),
                f"{name}_sha256": hashlib.sha256(data).hexdigest(),
                f"{name}_excerpt": excerpt,
                f"{name}_truncated": getattr(result, f"{name}_truncated"),
                f"{name}_excerpt_truncated": len(data) > len(excerpt.encode("utf-8")),
            })
        fields.update({
            name: getattr(result, name) for name in (
                "exit_code", "timed_out", "cancelled", "teardown_confirmed",
                "forced_tree_termination",
            )
        })
        same_binary = result.executable.model_copy(update={"version_line": None}) == (
            executable.model_copy(update={"version_line": None})
        )
        executable = result.executable.model_copy(update={
            "version_line": (
                executable.version_line if same_binary else result.executable.version_line
            ),
        })
        elapsed_seconds = result.elapsed_seconds
        summary = None if outcome == "succeeded" else f"Process outcome={outcome}"
    else:
        outcome = "exception"
        original = error.original_error if isinstance(error, ProcessCleanupError) else error
        summary = f"{type(original).__name__}: {original}"[:1024]
        fields.update({
            "timed_out": None, "cancelled": None,
            "teardown_confirmed": (
                error.teardown_confirmed if isinstance(error, ProcessCleanupError) else None
            ),
            "forced_tree_termination": (
                error.forced_tree_termination if isinstance(error, ProcessCleanupError) else None
            ),
            "original_exception_type": type(original).__name__[:128],
            "cleanup_errors": (
                tuple(item[:1024] for item in error.cleanup_errors[:8])
                if isinstance(error, ProcessCleanupError) else ()
            ),
            "diagnostics_truncated": isinstance(error, ProcessCleanupError) and (
                len(error.cleanup_errors) > 8 or any(len(v) > 1024 for v in error.cleanup_errors)
            ),
        })
    return ProcessInvocationEvidence(
        tool_role=tool_role,
        source_id=source_id,
        executable=executable,
        executable_identity_source="process_result" if result is not None else "frozen_request",
        argv=diagnostic_argv,
        working_directory=str(request.working_directory),
        # Only the explicit caller projection, never request.environment/os.environ.
        scoped_environment=dict(scoped_environment or {}),
        elapsed_seconds=elapsed_seconds,
        outcome=outcome,
        failure_summary=summary,
        **fields,
    )
