"""Non-executing external GPL workflow detection; no GUI or backend invocation."""

import shutil
from pathlib import Path

from splatforge.adapters.process_runner import ExecutableResolver


def detect_lichtfeld(executable: Path | None = None) -> dict:
    candidate = (
        str(executable)
        if executable
        else (shutil.which("LichtFeld-Studio.exe") or shutil.which("LichtFeld.exe"))
    )
    if not candidate:
        return {
            "status": "not_detected_on_path",
            "version": None,
            "evidence": "No configured native binary or PATH match; installation not required.",
        }
    identity = ExecutableResolver().resolve(candidate)
    return {
        "status": "binary_detected_not_executed",
        "version": None,
        "executable": identity.model_dump(mode="json"),
        "evidence": "File identity only; version/API/GUI capability unverified; manual workflow.",
    }
