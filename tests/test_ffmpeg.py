from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from fractions import Fraction
from pathlib import Path
from uuid import uuid4

import pytest

from splatforge.adapters.ffmpeg import FFmpegAdapter, orientation_filter, parse_showinfo
from splatforge.adapters.process_runner import (
    ExecutableNotFoundError,
    ProcessCleanupError,
    ProcessRequest,
)
from splatforge.application.views_contracts import (
    FFmpegBackendError,
    FFmpegCancelledError,
    FFmpegForcedCleanupError,
    FFmpegMissingError,
    FFmpegOutputError,
    FFmpegTeardownError,
    FFmpegTimeoutError,
)
from splatforge.core.media import (
    ExecutableIdentity,
    FullHashEvidence,
    MediaType,
    NormalizedProbe,
    SourceEvidence,
    SourceOccurrence,
    StorageKind,
)
from splatforge.core.process import ProcessResult
from splatforge.core.views import (
    CandidateEncodingSettings,
    CandidatePoolSettings,
    ImageFormat,
    parse_fps,
    photo_orientation_operation,
    video_orientation_operation,
)

IDENTITY = ExecutableIdentity(
    resolved_path="C:/Tools/ffmpeg.exe",
    size=100,
    last_write_ns=200,
    sha256="a" * 64,
)
SHOWINFO = b"""
[Parsed_showinfo_1] config in time_base: 1/1000, frame_rate: 0/1
[Parsed_showinfo_1] n:   0 pts:      0 pts_time:0 pos:0
[Parsed_showinfo_1] n:   1 pts:    417 pts_time:0.417 pos:1
"""


class FakeRunner:
    def __init__(
        self,
        callback: Callable[[ProcessRequest, int], ProcessResult] | None = None,
    ) -> None:
        self.requests: list[ProcessRequest] = []
        self.callback = callback

    def run(self, request: ProcessRequest, *, cancellation=None) -> ProcessResult:
        index = len(self.requests)
        self.requests.append(request)
        if self.callback is not None:
            return self.callback(request, index)
        if index == 0:
            return result(request, stdout=b"ffmpeg version fake\n")
        pattern = Path(request.argv[-1])
        for frame_index in range(2):
            path = Path(str(pattern).replace("%08d", f"{frame_index:08d}"))
            path.write_bytes(b"image")
        return result(request, stderr=SHOWINFO)


def result(
    request: ProcessRequest,
    *,
    stdout: bytes = b"",
    stderr: bytes = b"",
    identity: ExecutableIdentity = IDENTITY,
    exit_code: int | None = 0,
    stdout_truncated: bool = False,
    stderr_truncated: bool = False,
    timed_out: bool = False,
    cancelled: bool = False,
    teardown_confirmed: bool = True,
    forced_tree_termination: bool = False,
) -> ProcessResult:
    return ProcessResult(
        executable=identity,
        argv=request.argv,
        working_directory=str(request.working_directory),
        exit_code=exit_code,
        elapsed_seconds=0.01,
        stdout=stdout,
        stderr=stderr,
        stdout_truncated=stdout_truncated,
        stderr_truncated=stderr_truncated,
        timed_out=timed_out,
        cancelled=cancelled,
        teardown_confirmed=teardown_confirmed,
        forced_tree_termination=forced_tree_termination,
    )


def source(
    media_type: MediaType,
    *,
    orientation: int | None = None,
    rotation: int | None = 0,
) -> SourceOccurrence:
    now = datetime.now(UTC)
    evidence = SourceEvidence(
        size=10,
        last_write_ns=1,
        volume_id="v",
        file_id="f",
        change_time_ns=2,
        storage_kind=StorageKind.LOCAL_FIXED,
        evidence_available=True,
    )
    return SourceOccurrence(
        source_id=uuid4(),
        source_revision=1,
        external_locator="C:/média clip/input file.mp4",
        display_filename="input file.mp4",
        media_type=media_type,
        extension=".jpg" if media_type == MediaType.PHOTO else ".mp4",
        byte_size=10,
        content_sha256="b" * 64,
        last_full_hash_at=now,
        full_hash_evidence=FullHashEvidence(
            hashed_at=now,
            byte_count=10,
            evidence_before=evidence,
            evidence_after=evidence,
            stability_mechanism="test",
        ),
        source_group_id=uuid4(),
        camera_group_id=uuid4(),
        probe=NormalizedProbe(
            backend=IDENTITY,
            selected_visual_stream_index=3,
            width=320,
            height=240,
            orientation=orientation if media_type == MediaType.PHOTO else None,
            time_base="1/1000" if media_type == MediaType.VIDEO else None,
            duration="1" if media_type == MediaType.VIDEO else None,
            rotation_degrees=rotation if media_type == MediaType.VIDEO else None,
        ),
    )


def settings(image_format: ImageFormat = ImageFormat.JPEG) -> CandidatePoolSettings:
    return CandidatePoolSettings(
        candidate_fps=parse_fps("30000/1001"),
        encoding=CandidateEncodingSettings(
            image_format=image_format,
            jpeg_qscale=3,
            png_compression_level=7,
        ),
    )


def materialize(tmp_path: Path, runner: FakeRunner, *, image_format=ImageFormat.JPEG):
    adapter = FFmpegAdapter(runner=runner, executable="C:/Tools/ffmpeg.exe")
    backend = adapter.identity()
    item = source(MediaType.VIDEO)
    return adapter.materialize(
        Path(item.external_locator),
        item,
        tmp_path / "frames",
        settings(image_format),
        timeout_seconds=30,
        expected_backend=backend,
    )


def test_exact_argv_preserves_unicode_stream_mapping_and_vfr_semantics(tmp_path: Path) -> None:
    runner = FakeRunner()
    frames = materialize(tmp_path, runner)
    request = runner.requests[1]
    assert request.argv[request.argv.index("-i") + 1] == str(
        Path("C:/média clip/input file.mp4").absolute()
    )
    assert request.argv[request.argv.index("-map") + 1] == "0:3"
    assert "-noautorotate" in request.argv
    assert "-copyts" in request.argv
    assert all(option in request.argv for option in ("-an", "-sn", "-dn"))
    filter_value = request.argv[request.argv.index("-vf") + 1]
    assert "select=" in filter_value
    assert "1001/30000" in filter_value
    assert "showinfo" in filter_value
    assert "fps=" not in filter_value
    assert request.argv[request.argv.index("-fps_mode") + 1] == "passthrough"
    assert [frame.pts for frame in frames] == [0, 417]
    assert frames[1].time_base.as_fraction() == Fraction(1, 1000)


@pytest.mark.parametrize("confirmed", [True, False])
def test_exceptional_cleanup_is_translated_without_losing_original_cause(
    tmp_path: Path, confirmed: bool,
) -> None:
    original = RuntimeError("callback failed while live")
    boundary = ProcessCleanupError(
        original, teardown_confirmed=confirmed, forced_tree_termination=True,
    )

    def fail(request: ProcessRequest, index: int) -> ProcessResult:
        if index == 0:
            return result(request, stdout=b"ffmpeg version fake\n")
        raise boundary from original

    error = FFmpegBackendError if confirmed else FFmpegTeardownError
    with pytest.raises(error, match="callback failed while live") as caught:
        materialize(tmp_path, FakeRunner(fail))
    assert caught.value.__cause__ is boundary
    assert boundary.original_error is original


def test_negative_pts_and_duplicate_pts_remain_exact() -> None:
    metadata = parse_showinfo(
        "config in time_base: 1/90000\n"
        "n: 0 pts: -9000 pts_time:-0.1\n"
        "n: 1 pts: -9000 pts_time:-0.1\n"
        "n: 2 pts: 1001 pts_time:0.0111222\n"
    )
    assert [frame[1] for frame in metadata] == [-9000, -9000, 1001]
    assert metadata[0][1] * metadata[0][2].as_fraction() == Fraction(-1, 10)


@pytest.mark.parametrize(
    ("orientation", "expected"),
    [
        (1, "null"),
        (2, "hflip"),
        (3, "hflip,vflip"),
        (4, "vflip"),
        (5, "transpose=clock,hflip"),
        (6, "transpose=clock"),
        (7, "transpose=cclock,hflip"),
        (8, "transpose=cclock"),
    ],
)
def test_all_exif_orientations_are_explicit(orientation: int, expected: str) -> None:
    assert orientation_filter(photo_orientation_operation(orientation)) == expected


@pytest.mark.parametrize(
    ("rotation", "expected"),
    [
        (0, "null"),
        (90, "transpose=cclock"),
        (180, "hflip,vflip"),
        (270, "transpose=clock"),
        (-90, "transpose=clock"),
    ],
)
def test_video_right_angle_rotations_are_explicit(rotation: int, expected: str) -> None:
    assert orientation_filter(video_orientation_operation(rotation)) == expected


def test_unsupported_video_rotation_refuses() -> None:
    with pytest.raises(ValueError, match="right-angle"):
        video_orientation_operation(45)


@pytest.mark.parametrize(
    ("image_format", "expected_options"),
    [
        (ImageFormat.JPEG, ("mjpeg", "3", "yuvj444p")),
        (ImageFormat.PNG, ("png", "7")),
    ],
)
def test_explicit_jpeg_and_png_configuration(
    tmp_path: Path, image_format: ImageFormat, expected_options: tuple[str, ...]
) -> None:
    runner = FakeRunner()
    materialize(tmp_path, runner, image_format=image_format)
    argv = runner.requests[1].argv
    assert all(value in argv for value in expected_options)


def test_showinfo_requires_exact_unambiguous_metadata() -> None:
    parsed = parse_showinfo(SHOWINFO.decode())
    assert [(item[0], item[1]) for item in parsed] == [(0, 0), (1, 417)]
    with pytest.raises(FFmpegOutputError, match="time base"):
        parse_showinfo("n: 0 pts: 1 pts_time:0.1")
    with pytest.raises(FFmpegOutputError, match="ambiguous"):
        parse_showinfo(
            "config in time_base: 1/10\nconfig in time_base: 1/20\n"
            "n: 0 pts: 1 pts_time:0.1"
        )
    with pytest.raises(FFmpegOutputError, match="duplicate"):
        parse_showinfo(
            "config in time_base: 1/10\n"
            "n: 0 pts: 1 pts_time:0.1\nn: 0 pts: 2 pts_time:0.2"
        )


def test_output_count_mismatch_and_truncated_metadata_refuse(tmp_path: Path) -> None:
    def mismatch(request: ProcessRequest, index: int) -> ProcessResult:
        if index == 0:
            return result(request, stdout=b"ffmpeg version fake\n")
        pattern = Path(request.argv[-1])
        Path(str(pattern).replace("%08d", "00000000")).write_bytes(b"image")
        return result(request, stderr=SHOWINFO)

    with pytest.raises(FFmpegOutputError, match="count"):
        materialize(tmp_path / "mismatch", FakeRunner(mismatch))

    def truncated(request: ProcessRequest, index: int) -> ProcessResult:
        if index == 0:
            return result(request, stdout=b"ffmpeg version fake\n")
        return result(request, stderr=SHOWINFO, stderr_truncated=True)

    with pytest.raises(FFmpegOutputError, match="bounded stderr"):
        materialize(tmp_path / "truncated", FakeRunner(truncated))


def test_unexpected_output_name_refuses(tmp_path: Path) -> None:
    def unexpected(request: ProcessRequest, index: int) -> ProcessResult:
        if index == 0:
            return result(request, stdout=b"ffmpeg version fake\n")
        pattern = Path(request.argv[-1])
        Path(str(pattern).replace("%08d", "00000001")).write_bytes(b"image")
        return result(
            request,
            stderr=(
                b"[Parsed_showinfo_1] config in time_base: 1/1000\n"
                b"[Parsed_showinfo_1] n: 0 pts: 0 pts_time:0\n"
            ),
        )

    with pytest.raises(FFmpegOutputError, match="unexpected"):
        materialize(tmp_path, FakeRunner(unexpected))


def test_missing_executable_has_actionable_diagnostic() -> None:
    class MissingRunner:
        def run(self, request: ProcessRequest, *, cancellation=None) -> ProcessResult:
            raise ExecutableNotFoundError(f"missing: {request.executable}")

    adapter = FFmpegAdapter(runner=MissingRunner(), executable="missing-ffmpeg")
    with pytest.raises(FFmpegMissingError, match="--ffmpeg"):
        adapter.identity()


def test_photo_materialization_is_single_frame_and_explicitly_oriented(
    tmp_path: Path,
) -> None:
    def callback(request: ProcessRequest, index: int) -> ProcessResult:
        if index == 0:
            return result(request, stdout=b"ffmpeg version fake\n")
        pattern = Path(request.argv[-1])
        Path(str(pattern).replace("%08d", "00000000")).write_bytes(b"image")
        return result(request)

    runner = FakeRunner(callback)
    adapter = FFmpegAdapter(runner=runner, executable="C:/Tools/ffmpeg.exe")
    backend = adapter.identity()
    item = source(MediaType.PHOTO, orientation=7)
    frames = adapter.materialize(
        Path(item.external_locator),
        item,
        tmp_path / "frames",
        settings(),
        timeout_seconds=30,
        expected_backend=backend,
    )

    argv = runner.requests[1].argv
    assert argv[argv.index("-frames:v") + 1] == "1"
    assert "select=" not in argv[argv.index("-vf") + 1]
    assert argv[argv.index("-vf") + 1] == "showinfo,transpose=cclock,hflip"
    assert frames[0].pts is None


@pytest.mark.parametrize(
    ("updates", "error"),
    [
        ({"exit_code": 2}, FFmpegBackendError),
        ({"timed_out": True, "exit_code": None}, FFmpegTimeoutError),
        ({"cancelled": True, "exit_code": None}, FFmpegCancelledError),
        ({"teardown_confirmed": False}, FFmpegTeardownError),
        ({"forced_tree_termination": True}, FFmpegForcedCleanupError),
    ],
)
def test_abnormal_process_results_refuse_publication(
    tmp_path: Path, updates: dict[str, object], error: type[Exception]
) -> None:
    def callback(request: ProcessRequest, index: int) -> ProcessResult:
        if index == 0:
            return result(request, stdout=b"ffmpeg version fake\n")
        return result(request, stderr=b"backend error", **updates)

    with pytest.raises(error):
        materialize(tmp_path, FakeRunner(callback))


def test_binary_change_after_version_provenance_refuses(tmp_path: Path) -> None:
    changed = IDENTITY.model_copy(update={"sha256": "f" * 64})

    def callback(request: ProcessRequest, index: int) -> ProcessResult:
        if index == 0:
            return result(request, stdout=b"ffmpeg version fake\n")
        pattern = Path(request.argv[-1])
        for frame_index in range(2):
            Path(str(pattern).replace("%08d", f"{frame_index:08d}")).write_bytes(b"image")
        return result(request, stderr=SHOWINFO, identity=changed)

    with pytest.raises(FFmpegBackendError, match="changed"):
        materialize(tmp_path, FakeRunner(callback))
