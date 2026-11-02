"""Small read-only preview port, independent of processing/publication recipes."""

from pathlib import Path
from typing import Protocol


class PreviewCancellation(Protocol):
    def is_cancelled(self) -> bool: ...


class VideoPreview(Protocol):
    def frame(
        self, path: Path, stream: int, milliseconds: int, cancellation: PreviewCancellation
    ) -> bytes: ...
