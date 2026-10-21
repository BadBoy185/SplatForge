import base64
import json
import os
from pathlib import Path

import pytest
from PIL import Image

from splatforge.adapters.ffprobe import FFprobeAdapter, normalize_ffprobe
from splatforge.adapters.process_runner import (
    ExecutableNotFoundError,
    ProcessBoundaryError,
    ProcessCleanupError,
)
from splatforge.application.media_contracts import (
    ProbeBackendError,
    ProbeCancelledError,
    ProbeMissingError,
    ProbeOutputError,
    ProbeTimeoutError,
    ProbeUnsupportedError,
)
from splatforge.core.media import ExecutableIdentity, MediaType
from splatforge.core.process import ProcessResult

BACKEND = ExecutableIdentity(
    resolved_path="C:/tools/ffprobe.exe",
    size=123,
    last_write_ns=456,
    sha256="b" * 64,
    version_line="ffprobe version test",
)


@pytest.mark.parametrize(("extension", "codec"), [(".jpg", "mjpeg"), (".png", "png")])
def test_normalizes_photo_dimensions_stream_and_orientation(extension: str, codec: str) -> None:
    payload = {
        "streams": [
            {
                "index": 2,
                "codec_type": "video",
                "codec_name": codec,
                "width": 640,
                "height": 480,
                "tags": {"orientation": "6"} if extension == ".jpg" else {},
            }
        ],
        "format": {},
    }

    result = normalize_ffprobe(
        payload,
        media_type=MediaType.PHOTO,
        backend=BACKEND,
        jpeg_orientation=None,
    )

    assert result.selected_visual_stream_index == 2
    assert (result.codec_name, result.width, result.height) == (codec, 640, 480)
    assert result.orientation == (6 if extension == ".jpg" else None)
    assert result.time_base is None


def test_jpeg_bounded_reader_orientation_is_used_when_probe_omits_it() -> None:
    result = normalize_ffprobe(
        {
            "streams": [
                {
                    "index": 0,
                    "codec_type": "video",
                    "codec_name": "mjpeg",
                    "width": 10,
                    "height": 20,
                }
            ]
        },
        media_type=MediaType.PHOTO,
        backend=BACKEND,
        jpeg_orientation=8,
    )

    assert result.orientation == 8


@pytest.mark.parametrize("container", ["mp4", "mov"])
def test_normalizes_video_rationals_rotation_and_optional_fields(container: str) -> None:
    result = normalize_ffprobe(
        {
            "streams": [
                {
                    "index": 1,
                    "codec_type": "video",
                    "codec_name": "h264",
                    "width": 1920,
                    "height": 1080,
                    "time_base": "1/90000",
                    "avg_frame_rate": "30000/1001",
                    "r_frame_rate": "30/1",
                    "duration": "1.234",
                    "nb_frames": "37",
                    "side_data_list": [{"rotation": -90}],
                }
            ],
            "format": {"format_name": container, "duration": "9.0"},
        },
        media_type=MediaType.VIDEO,
        backend=BACKEND,
    )

    assert result.selected_visual_stream_index == 1
    assert result.time_base == "1/90000"
    assert result.average_frame_rate == "30000/1001"
    assert result.raw_frame_rate == "30/1"
    assert result.duration == "1.234"
    assert result.frame_count == 37
    assert result.rotation_degrees == -90


def test_missing_video_timing_metadata_remains_null() -> None:
    result = normalize_ffprobe(
        {
            "streams": [
                {
                    "index": 0,
                    "codec_type": "video",
                    "width": 12,
                    "height": 8,
                    "avg_frame_rate": "0/0",
                }
            ]
        },
        media_type=MediaType.VIDEO,
        backend=BACKEND,
    )

    assert result.codec_name is None
    assert result.time_base is None
    assert result.average_frame_rate is None
    assert result.raw_frame_rate is None
    assert result.duration is None
    assert result.frame_count is None
    assert result.rotation_degrees is None


@pytest.mark.parametrize(
    "payload",
    [
        {"streams": [{"index": 0, "codec_type": "audio"}]},
        {
            "streams": [
                {"index": 0, "codec_type": "video", "width": 1, "height": 1},
                {"index": 1, "codec_type": "video", "width": 1, "height": 1},
            ]
        },
    ],
)
def test_rejects_no_visual_or_ambiguous_visual_streams(payload: object) -> None:
    with pytest.raises(ProbeUnsupportedError):
        normalize_ffprobe(payload, media_type=MediaType.VIDEO, backend=BACKEND)


class FakeRunner:
    def __init__(self, probe_result: ProcessResult) -> None:
        self.probe_result = probe_result
        self.requests = []

    def run(self, request, *, cancellation=None):  # type: ignore[no-untyped-def]
        self.requests.append(request)
        if request.argv == ("-version",):
            return process_result(stdout=b"ffprobe version fake\n")
        return self.probe_result


def process_result(
    *,
    stdout: bytes = b"",
    stderr: bytes = b"",
    exit_code: int | None = 0,
    stdout_truncated: bool = False,
    timed_out: bool = False,
    cancelled: bool = False,
    teardown_confirmed: bool = True,
    forced_tree_termination: bool = False,
    executable: ExecutableIdentity = BACKEND,
) -> ProcessResult:
    return ProcessResult(
        executable=executable.model_copy(update={"version_line": None}),
        argv=(),
        working_directory="C:/work",
        exit_code=exit_code,
        elapsed_seconds=0.1,
        stdout=stdout,
        stderr=stderr,
        stdout_truncated=stdout_truncated,
        stderr_truncated=False,
        timed_out=timed_out,
        cancelled=cancelled,
        teardown_confirmed=teardown_confirmed,
        forced_tree_termination=forced_tree_termination,
    )


@pytest.mark.parametrize(
    ("result", "error"),
    [
        (process_result(stdout=b"{"), ProbeOutputError),
        (process_result(stdout=b"{}", stdout_truncated=True), ProbeOutputError),
        (process_result(stderr=b"bad input", exit_code=2), ProbeBackendError),
        (process_result(exit_code=None, timed_out=True), ProbeTimeoutError),
        (process_result(exit_code=None, cancelled=True), ProbeCancelledError),
        (process_result(exit_code=0, teardown_confirmed=False), ProbeBackendError),
        (process_result(exit_code=0, forced_tree_termination=True), ProbeBackendError),
    ],
)
def test_probe_process_failures_are_structured(
    tmp_path: Path, result: ProcessResult, error: type[ValueError]
) -> None:
    source = tmp_path / "source.png"
    source.write_bytes(b"not decoded by fake")

    with pytest.raises(error):
        FFprobeAdapter(runner=FakeRunner(result), executable="fake").probe(source, MediaType.PHOTO)


def test_probe_uses_absolute_source_argument_and_json_contract(tmp_path: Path) -> None:
    source = tmp_path / "space žluťoučký.png"
    Image.new("RGB", (1, 1)).save(source)
    payload = {
        "streams": [
            {
                "index": 0,
                "codec_type": "video",
                "codec_name": "png",
                "width": 1,
                "height": 1,
            }
        ]
    }
    runner = FakeRunner(process_result(stdout=json.dumps(payload).encode()))

    probe = FFprobeAdapter(runner=runner, executable="fake").probe(source, MediaType.PHOTO)

    request = runner.requests[-1]
    assert request.argv[:-1] == (
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_streams",
        "-show_format",
    )
    assert Path(request.argv[-1]).is_absolute()
    assert probe.orientation == 1


def probe_json() -> bytes:
    return json.dumps(
        {
            "streams": [
                {
                    "index": 0,
                    "codec_type": "video",
                    "codec_name": "png",
                    "width": 1,
                    "height": 1,
                }
            ]
        }
    ).encode()


class SequencedRunner:
    def __init__(self, results: list[ProcessResult | Exception]) -> None:
        self.results = results
        self.requests = []

    def run(self, request, *, cancellation=None):  # type: ignore[no-untyped-def]
        self.requests.append(request)
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def test_unchanged_ffprobe_identity_reuses_cached_version(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    Image.new("RGB", (1, 1)).save(source)
    runner = SequencedRunner(
        [
            process_result(stdout=b"ffprobe version stable\n"),
            process_result(stdout=probe_json()),
            process_result(stdout=probe_json()),
        ]
    )
    adapter = FFprobeAdapter(runner=runner, executable="fake")

    first = adapter.probe(source, MediaType.PHOTO)
    second = adapter.probe(source, MediaType.PHOTO)

    assert first.backend == second.backend
    assert first.backend.sha256 == BACKEND.sha256
    assert first.backend.version_line == "ffprobe version stable"
    assert [request.argv for request in runner.requests].count(("-version",)) == 1


def test_changed_ffprobe_identity_refreshes_matching_version_provenance(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.png"
    Image.new("RGB", (1, 1)).save(source)
    changed = BACKEND.model_copy(
        update={"size": 321, "last_write_ns": 654, "sha256": "c" * 64}
    )
    runner = SequencedRunner(
        [
            process_result(stdout=b"ffprobe version old\n"),
            process_result(stdout=probe_json()),
            process_result(stdout=probe_json(), executable=changed),
            process_result(stdout=b"ffprobe version changed\n", executable=changed),
        ]
    )
    adapter = FFprobeAdapter(runner=runner, executable="fake")

    old_probe = adapter.probe(source, MediaType.PHOTO)
    changed_probe = adapter.probe(source, MediaType.PHOTO)

    assert old_probe.backend.sha256 == BACKEND.sha256
    assert changed_probe.backend.sha256 == changed.sha256
    assert changed_probe.backend.version_line == "ffprobe version changed"
    assert [request.argv for request in runner.requests].count(("-version",)) == 2


def test_identity_change_during_version_refresh_is_actionable(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    Image.new("RGB", (1, 1)).save(source)
    metadata_binary = BACKEND.model_copy(update={"sha256": "c" * 64})
    version_binary = BACKEND.model_copy(update={"sha256": "d" * 64})
    runner = SequencedRunner(
        [
            process_result(stdout=b"ffprobe version old\n"),
            process_result(stdout=probe_json(), executable=metadata_binary),
            process_result(stdout=b"ffprobe version newer\n", executable=version_binary),
        ]
    )

    with pytest.raises(ProbeBackendError, match="changed while refreshing"):
        FFprobeAdapter(runner=runner, executable="fake").probe(source, MediaType.PHOTO)


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (ExecutableNotFoundError("not found"), ProbeMissingError),
        (ProcessBoundaryError("job assignment failed"), ProbeBackendError),
    ],
)
def test_only_executable_not_found_is_classified_as_ffprobe_missing(
    tmp_path: Path, failure: Exception, expected: type[ValueError]
) -> None:
    source = tmp_path / "source.png"
    Image.new("RGB", (1, 1)).save(source)

    with pytest.raises(expected):
        FFprobeAdapter(
            runner=SequencedRunner([failure]), executable="fake"
        ).probe(source, MediaType.PHOTO)


@pytest.mark.skipif(
    not os.environ.get("SPLATFORGE_TEST_FFPROBE"),
    reason="set SPLATFORGE_TEST_FFPROBE for the opt-in real FFprobe test",
)
def test_real_ffprobe_generated_png(tmp_path: Path) -> None:
    png = tmp_path / "generated.png"
    png.write_bytes(
        base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
        )
    )

    result = FFprobeAdapter(executable=os.environ["SPLATFORGE_TEST_FFPROBE"]).probe(
        png, MediaType.PHOTO
    )

    assert (result.width, result.height) == (1, 1)
    assert result.codec_name == "png"
    assert result.backend.version_line is not None


@pytest.mark.parametrize("angle", [90.5, "-90.5", "nan", "45", "infinity"])
@pytest.mark.parametrize("kind", ["matrix", "tag"])
def test_fractional_or_arbitrary_video_rotation_is_never_truncated(angle, kind) -> None:
    stream = {"index": 0, "codec_type": "video", "width": 4, "height": 2}
    if kind == "matrix":
        stream["side_data_list"] = [{"rotation": angle}]
    else:
        stream["tags"] = {"rotate": angle}
    with pytest.raises(ProbeUnsupportedError, match="rotation"):
        normalize_ffprobe({"streams": [stream]}, media_type=MediaType.VIDEO, backend=BACKEND)


@pytest.mark.parametrize("angle", ["0.0", "90.0", "-90.0", "180.0", "270.0"])
def test_exact_decimal_right_angle_preserves_matrix_convention(angle: str) -> None:
    stream = {"index": 0, "codec_type": "video", "width": 4, "height": 2,
              "side_data_list": [{"rotation": angle}]}
    result = normalize_ffprobe(
        {"streams": [stream]}, media_type=MediaType.VIDEO, backend=BACKEND,
    )
    assert result.rotation_degrees == int(angle.split(".")[0])


@pytest.mark.parametrize("orientation", range(1, 9))
def test_png_exif_probe_is_metadata_only_and_preserves_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, orientation: int,
) -> None:
    path = tmp_path / "oriented.png"
    exif = Image.Exif()
    exif[274] = orientation
    with Image.new("RGB", (4, 2)) as image:
        image.save(path, exif=exif)
    before = path.read_bytes()
    runner = SequencedRunner([
        process_result(stdout=b"ffprobe version test\n"), process_result(stdout=probe_json()),
    ])
    monkeypatch.setattr(Image, "open", lambda *a, **kw: pytest.fail("must not decode source"))
    probe = FFprobeAdapter(runner=runner, executable="fake").probe(path, MediaType.PHOTO)
    assert probe.orientation == orientation
    assert path.read_bytes() == before


def test_png_exif_metadata_resource_bound(tmp_path: Path) -> None:
    from splatforge.adapters.ffprobe import read_png_exif_orientation

    path = tmp_path / "huge-metadata.png"
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + (2**31).to_bytes(4, "big") + b"eXIf")
    with pytest.raises(ProbeUnsupportedError, match="byte bound"):
        read_png_exif_orientation(path)


def test_exceptional_probe_cleanup_diagnostics_keep_original_and_teardown(tmp_path: Path) -> None:
    cause = ProcessCleanupError(
        RuntimeError("probe callback sentinel"), teardown_confirmed=False,
        forced_tree_termination=True,
    )
    adapter = FFprobeAdapter(runner=SequencedRunner([cause]), executable="fake")
    with pytest.raises(
        ProbeBackendError, match="probe callback sentinel.*teardown_confirmed=False",
    ):
        adapter.probe(tmp_path / "source.png", MediaType.PHOTO)
