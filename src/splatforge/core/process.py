"""Backend-neutral external-process value records."""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from splatforge.core.media import ExecutableIdentity

PROCESS_EXCERPT_BYTES = 16 * 1024
MAX_PROCESS_RECORD_BYTES = 96 * 1024


class ProcessInvocationEvidence(BaseModel):
    """Optional diagnostics, deliberately excluded from numerical artifact identity.

    Callers supply diagnostic argv explicitly, redacting future secret arguments.
    Missing streams on exceptional execution are None, never invented empty captures.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    diagnostic_schema_version: Literal[1] = 1
    invocation_index: int = Field(default=1, ge=1, strict=True)
    tool_role: str = Field(min_length=1, max_length=128)
    source_id: UUID | None = None
    executable: ExecutableIdentity
    executable_identity_source: Literal["process_result", "frozen_request"]
    argv: Annotated[tuple[Annotated[str, Field(max_length=4096)], ...], Field(max_length=512)]
    working_directory: str = Field(min_length=1, max_length=4096)
    scoped_environment: dict[
        Literal["OMP_NUM_THREADS", "MKL_NUM_THREADS", "CUDA_VISIBLE_DEVICES"],
        Annotated[str, Field(pattern=r"^-?\d+(,-?\d+)*$", max_length=128)],
    ] = Field(default_factory=dict)
    elapsed_seconds: float = Field(ge=0)
    exit_code: int | None = Field(default=None, strict=True)
    timed_out: bool | None
    cancelled: bool | None
    teardown_confirmed: bool | None
    forced_tree_termination: bool | None
    stdout_captured_bytes: int | None = Field(default=None, ge=0, strict=True)
    stderr_captured_bytes: int | None = Field(default=None, ge=0, strict=True)
    stdout_truncated: bool | None = None
    stderr_truncated: bool | None = None
    stdout_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    stderr_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    stdout_excerpt: str | None = None
    stderr_excerpt: str | None = None
    stdout_excerpt_truncated: bool | None = None
    stderr_excerpt_truncated: bool | None = None
    outcome: Literal[
        "succeeded", "nonzero_exit", "timeout", "cancelled", "teardown_unconfirmed",
        "forced_tree_termination", "exception",
    ]
    failure_summary: str | None = Field(default=None, max_length=1024)
    original_exception_type: str | None = Field(default=None, max_length=128)
    cleanup_errors: Annotated[
        tuple[Annotated[str, Field(max_length=1024)], ...], Field(max_length=8)
    ] = ()
    diagnostics_truncated: bool = False

    @field_validator("stdout_excerpt", "stderr_excerpt")
    @classmethod
    def bounded_excerpt(cls, value: str | None) -> str | None:
        if value is not None and len(value.encode("utf-8")) > PROCESS_EXCERPT_BYTES:
            raise ValueError("Process excerpt exceeds its UTF-8 byte bound")
        return value

    @model_validator(mode="after")
    def bounded_record(self) -> ProcessInvocationEvidence:
        if len(self.model_dump_json().encode("utf-8")) > MAX_PROCESS_RECORD_BYTES:
            raise ValueError("Process evidence exceeds its record byte bound")
        return self


class ProcessResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    executable: ExecutableIdentity
    argv: tuple[str, ...]
    working_directory: str
    exit_code: int | None = Field(default=None, strict=True)
    elapsed_seconds: float = Field(ge=0)
    stdout: bytes
    stderr: bytes
    stdout_truncated: bool
    stderr_truncated: bool
    timed_out: bool
    cancelled: bool
    teardown_confirmed: bool
    forced_tree_termination: bool

    def stdout_text(self) -> str:
        return self.stdout.decode("utf-8", errors="replace")

    def stderr_text(self) -> str:
        return self.stderr.decode("utf-8", errors="replace")
