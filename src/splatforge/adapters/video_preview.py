"""One bounded, input-seeked frame; never materialize a clip for a UI filmstrip."""

import os
from pathlib import Path

from splatforge.adapters.process_runner import LocalProcessRunner, ProcessRequest
from splatforge.application.video_preview import PreviewCancellation


class FFmpegVideoPreview:
    def __init__(self, runner=None, executable: str | None = None) -> None:
        self.runner = runner or LocalProcessRunner()
        self.executable = executable or os.environ.get("SPLATFORGE_FFMPEG") or "ffmpeg"

    def frame(
        self, path: Path, stream: int, milliseconds: int, cancellation: PreviewCancellation
    ) -> bytes:
        if stream < 0 or milliseconds < 0 or not path.is_absolute():
            raise ValueError("Invalid video preview request")
        result = self.runner.run(ProcessRequest(
            executable=self.executable,
            argv=("-hide_banner", "-loglevel", "error", "-nostdin", "-ss",
                  f"{milliseconds // 1000}.{milliseconds % 1000:03d}", "-i", str(path),
                  "-map", f"0:{stream}", "-frames:v", "1", "-an", "-sn", "-dn",
                  "-vf", "scale=160:90:force_original_aspect_ratio=decrease",
                  "-threads", "1", "-f", "image2pipe", "-vcodec", "mjpeg", "pipe:1"),
            working_directory=path.parent, environment={}, timeout_seconds=8,
            max_stdout_bytes=256 * 1024, max_stderr_bytes=16 * 1024,
        ), cancellation=cancellation)
        if (result.exit_code != 0 or result.cancelled or result.timed_out
                or not result.teardown_confirmed or result.stdout_truncated or not result.stdout):
            raise ValueError("Timeline frame unavailable: " + result.stderr_text()[:256])
        return result.stdout
