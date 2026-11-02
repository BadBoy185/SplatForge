"""Explicit FFmpeg check of real filmstrip frames on VFR/nonzero-origin media."""

import json
import subprocess
from fractions import Fraction
from io import BytesIO

from PIL import Image
from test_ffmpeg_integration import configured_ffmpeg, configured_ffprobe, ppm

from splatforge.adapters.video_preview import FFmpegVideoPreview


def test_real_preview_input_seek_keeps_container_origin_and_vfr(tmp_path):
    ffmpeg, ffprobe = configured_ffmpeg(), configured_ffprobe()
    colors = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0)]
    for i, color in enumerate(colors):
        ppm(tmp_path / f"frame-{i}.ppm", color)
    concat = tmp_path / "vfr.concat"
    concat.write_text("file 'frame-0.ppm'\nduration 0.12\nfile 'frame-1.ppm'\n"
                      "duration 0.37\nfile 'frame-2.ppm'\nduration 0.41\n"
                      "file 'frame-3.ppm'\nduration 0.21\nfile 'frame-3.ppm'\n")
    path = tmp_path / "Timeline ž Видео.mp4"
    subprocess.run([ffmpeg, "-hide_banner", "-nostdin", "-loglevel", "error", "-y",
                    "-f", "concat", "-safe", "0", "-i", str(concat), "-fps_mode", "vfr",
                    "-c:v", "mpeg4", "-q:v", "2", "-output_ts_offset", "5", str(path)],
                   cwd=tmp_path, shell=False, capture_output=True, check=True, timeout=30)
    original = path.read_bytes()
    data = json.loads(subprocess.run(
        [ffprobe, "-v", "error", "-show_frames", "-show_format", "-show_streams",
         "-of", "json", str(path)], cwd=tmp_path, shell=False, capture_output=True,
        check=True, timeout=30,
    ).stdout)
    origin = Fraction(data["format"]["start_time"])
    time_base = Fraction(data["streams"][0]["time_base"])
    assert origin == 5
    positions = [(int(f["pts"]) * time_base - origin) * 1000 for f in data["frames"]]
    assert len(set(b - a for a, b in zip(positions, positions[1:], strict=False))) > 1

    class Cancellation:
        def is_cancelled(self):
            return False

    adapter = FFmpegVideoPreview(executable=ffmpeg)
    for index in (0, 2, 3):
        image = Image.open(BytesIO(adapter.frame(path, 0, int(positions[index]), Cancellation())))
        assert image.width <= 160 and image.height <= 90
        actual = image.convert("RGB").getpixel((image.width // 2, image.height // 2))
        assert all(abs(a - b) < 12 for a, b in zip(actual, colors[index], strict=True))
    assert path.read_bytes() == original
