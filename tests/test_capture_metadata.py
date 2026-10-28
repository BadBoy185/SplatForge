"""Real bounded EXIF parsing and normal inventory publication, without FFmpeg."""

import json
from datetime import datetime

import pytest
from PIL import Image, TiffImagePlugin
from test_ffprobe import BACKEND, FakeRunner, process_result
from test_media import media_service

from splatforge.adapters.capture_metadata import read_photo_capture
from splatforge.adapters.ffprobe import FFprobeAdapter, normalize_ffprobe
from splatforge.bootstrap import build_gui_facade, build_project_service
from splatforge.core.capture_metadata import CaptureMetadata
from splatforge.core.media import MediaType


def capture_photo(path, *, make="DJI", model="FC220", details=True):
    exif = Image.Exif()
    if make is not None:
        exif[271] = make
    if model is not None:
        exif[272] = model
    exif[274] = 6
    if details:
        exif[34665] = {
            42036: "FC220 lens",
            36867: "2026:10:27 14:32:10",
            36881: "+02:00",
            37386: TiffImagePlugin.IFDRational(45, 10),
            41989: 26,
            33434: TiffImagePlugin.IFDRational(1, 800),
            33437: TiffImagePlugin.IFDRational(28, 10),
            34855: 100,
        }
    Image.new("RGB", (16, 12)).save(path, exif=exif)
    return path


def photo_probe():
    payload = {
        "streams": [
            {"index": 0, "codec_type": "video", "codec_name": "mjpeg", "width": 16, "height": 12}
        ]
    }
    return FFprobeAdapter(runner=FakeRunner(process_result(stdout=json.dumps(payload).encode())))


@pytest.mark.parametrize("extension", ["jpg", "png"])
def test_exif_ingest_persists_orientation_device_and_selected_details_offline(tmp_path, extension):
    root = tmp_path / "Capture project ž"
    build_project_service().create(root, "Capture")
    path = capture_photo(tmp_path / ("DJI_0042." + extension))
    service = media_service(root, probe=photo_probe())[0]
    events = []
    added = service.add(root, [path], progress=events.append)
    source = service.list(root).sources[0]
    assert source.probe.orientation == 6
    capture = source.probe.capture
    assert capture.device_label == "DJI FC220"
    assert capture.focal_length_mm == 4.5 and capture.focal_length_35mm == 26
    assert capture.exposure_seconds == 1 / 800 and capture.f_number == 2.8
    assert capture.iso == 100 and capture.lens_model == "FC220 lens"
    assert capture.captured_at.isoformat() == "2026-10-27T14:32:10+02:00"
    assert capture.gps_present is False
    path.unlink()
    facade = build_gui_facade()
    assert facade.overview(root).sources[0].values["device"] == "DJI FC220"
    details = facade.source_details(root, added.added_sources[0].source_id)
    assert details["capture"] == capture.model_dump(mode="json")
    assert details["originalFilename"] == path.name
    assert events[-1].phase == "succeeded"
    assert source.probe.model_dump_json() == service.list(root).sources[0].probe.model_dump_json()


@pytest.mark.parametrize(
    "make,model,expected",
    [
        (None, None, "Unknown device"),
        ("DJI", None, "Unknown device"),
        (None, "iPhone 16 Pro", "Unknown device"),
        ("Apple", "iPhone 16 Pro", "Apple iPhone 16 Pro"),
        ("Sony", "Sony ILCE-7M4", "Sony ILCE-7M4"),
    ],
)
def test_partial_exif_never_guesses_device_from_filename(tmp_path, make, model, expected):
    path = capture_photo(tmp_path / "DJI_9999.jpg", make=make, model=model, details=False)
    evidence = read_photo_capture(path)
    assert evidence.device_label == expected
    assert evidence.make == make and evidence.model == model
    assert evidence.captured_at is None


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"not jpeg",
        b"\xff\xd8\xff\xe1\x00\x08Exif\x00\x00",
        b"\xff\xd8\xff\xe1\xff\xffExif\x00\x00II\x2a\x00",
    ],
)
def test_malformed_optional_exif_keeps_ingest_usable(tmp_path, data):
    path = tmp_path / "broken metadata.jpg"
    path.write_bytes(data)
    root = tmp_path / "project"
    build_project_service().create(root, "Malformed descriptive evidence")
    service = media_service(root, probe=photo_probe())[0]
    service.add(root, [path])  # Valid visual stream is supplied by the fake process boundary.
    assert service.list(root).sources[0].probe.capture.device_label == "Unknown device"


def test_invalid_individual_tags_and_naive_time_are_honest(tmp_path):
    path = tmp_path / "partial.png"
    exif = Image.Exif()
    exif[271], exif[272] = "Apple", "iPhone"
    exif[34665] = {36867: "2026:10:27 14:32:10", 34855: "bad", 37386: "invalid"}
    Image.new("RGB", (16, 12)).save(path, exif=exif)
    capture = read_photo_capture(path)
    assert capture.device_label == "Apple iPhone"
    assert capture.iso is None and capture.focal_length_mm is None
    assert capture.captured_at == datetime(2026, 10, 27, 14, 32, 10)
    assert read_photo_capture(path, byte_limit=16).device_label == "Unknown device"


def test_video_container_metadata_roundtrip_and_persistence(tmp_path):
    payload = {
        "streams": [
            {
                "index": 0,
                "codec_type": "video",
                "codec_name": "h264",
                "width": 1920,
                "height": 1080,
                "avg_frame_rate": "30000/1001",
                "tags": {"rotate": "90"},
            }
        ],
        "format": {
            "duration": "12.5",
            "tags": {
                "com.apple.quicktime.make": "Apple",
                "com.apple.quicktime.model": "iPhone 16 Pro",
                "creation_time": "2026-10-27T12:32:10Z",
                "location": "+private GPS coordinates",
            },
        },
    }
    normalized = normalize_ffprobe(payload, media_type=MediaType.VIDEO, backend=BACKEND)
    assert normalized.capture.device_label == "Apple iPhone 16 Pro"
    assert normalized.rotation_degrees == -90 and normalized.average_frame_rate == "30000/1001"
    assert "private GPS" not in normalized.model_dump_json()
    root = tmp_path / "project"
    build_project_service().create(root, "Video")
    path = tmp_path / "clip.mov"
    path.write_bytes(b"synthetic stream")
    probe = FFprobeAdapter(runner=FakeRunner(process_result(stdout=json.dumps(payload).encode())))
    service = media_service(root, probe=probe)[0]
    service.add(root, [path])
    path.unlink()
    saved = service.list(root).sources[0].probe
    assert saved.model_dump(exclude={"backend"}) == normalized.model_dump(exclude={"backend"})
    assert saved.duration == "12.5"


def test_capture_serialization_deterministic():
    a = CaptureMetadata(origin="exif", model="FC220", make="DJI")
    b = CaptureMetadata.model_validate({"make": "DJI", "origin": "exif", "model": "FC220"})
    assert a.model_dump_json() == b.model_dump_json()
