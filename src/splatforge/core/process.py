"""Backend-neutral external-process value records."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from splatforge.core.media import ExecutableIdentity


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

    def stdout_text(self) -> str:
        return self.stdout.decode("utf-8", errors="replace")

    def stderr_text(self) -> str:
        return self.stderr.decode("utf-8", errors="replace")
