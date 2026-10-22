"""Local argument transport only; byte identity is checked before copying/launch."""

from pathlib import Path

from splatforge.core.process import ProcessResult


def local_model_argument(path: Path) -> Path:
    value = str(path)
    if (not path.is_absolute() or ";" in value
            or any(token in value.lower() for token in ("http:", "https:", "file:"))):
        raise ValueError("Learned models require absolute local paths, never backend model URIs")
    return path


def reports_cpu_fallback(result: ProcessResult) -> bool:
    text = (result.stdout_text() + "\n" + result.stderr_text()).lower()
    return "falling back to cpu" in text or "fallback to cpu" in text
