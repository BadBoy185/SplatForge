"""Native binary reader invariance and corruption checks, independent of COLMAP."""

import struct
from uuid import UUID

import pytest
from mapping_helpers import mapping_for, write_model

from splatforge.adapters.colmap_reconstruction import read_component, read_components
from splatforge.core.reconstruction import RecordAvailability, membership_id


def test_reader_current_and_legacy_models_noncontiguous_ids_and_point_count(tmp_path):
    mapping = mapping_for(tuple(UUID(int=i) for i in range(1, 5)), offset=70)
    for legacy in (True, False):
        directory = tmp_path / ("30" if legacy else "2")
        write_model(
            directory,
            mapping,
            selected=mapping.images[:3],
            current_frames=not legacy,
            with_point=True,
        )
        component, cameras, views = read_component(directory, mapping)
        assert component.registered_view_count == 3
        assert component.camera_count == len(cameras) == 1
        assert component.point_count == 1
        assert component.points == component.tracks == RecordAvailability.NOT_PUBLISHED
        assert [v.view_id for v in views] == [m.view_id for m in mapping.images[:3]]
        assert len({v.camera_id for v in views}) == 1
        assert cameras[0].parameters == (100.0, 16.0, 12.0)
        assert views[2].pose.camera_center() == (-2.0, 0.0, 0.0)


def test_native_numbering_path_and_order_do_not_change_public_semantics(tmp_path):
    views = tuple(UUID(int=i) for i in range(1, 4))
    a, b = mapping_for(views), mapping_for(views, offset=1000)
    write_model(tmp_path / "7", a, native_camera_offset=10)
    write_model(tmp_path / "3", b, native_camera_offset=500)
    first = read_component(tmp_path / "7", a)
    second = read_component(tmp_path / "3", b)
    assert first[0].component_id == second[0].component_id
    assert first[0].semantic_digest == second[0].semantic_digest
    assert first[1:] == second[1:]
    write_model(tmp_path / "8", a, shift=1)
    changed = read_component(tmp_path / "8", a)[0]
    assert first[0].component_id == changed.component_id
    assert first[0].semantic_digest != changed.semantic_digest
    write_model(tmp_path / "9", a, focal=120)
    assert first[0].semantic_digest != read_component(tmp_path / "9", a)[0].semantic_digest


def test_all_components_canonical_order_and_changed_membership(tmp_path):
    mapping = mapping_for(tuple(UUID(int=i) for i in range(1, 8)))
    write_model(tmp_path / "sparse" / "100", mapping, selected=mapping.images[:3])
    write_model(tmp_path / "sparse" / "2", mapping, selected=mapping.images[3:6])
    components = read_components(tmp_path, mapping)
    assert len(components) == 2
    assert [c.component_id.int for c in components] == sorted(
        c.component_id.int for c in components
    )
    assert {v for c in components for v in c.registered_view_ids} == {
        UUID(int=i) for i in range(1, 7)
    }
    assert membership_id(mapping.images[i].view_id for i in (0, 1, 2)) != membership_id(
        mapping.images[i].view_id for i in (0, 1, 3)
    )


@pytest.mark.parametrize(
    "kind", ["camera", "pose", "duplicate", "unknown", "truncated", "frame", "point"]
)
def test_malformed_native_models_fail(tmp_path, kind):
    mapping = mapping_for(tuple(UUID(int=i) for i in range(1, 4)))
    directory = tmp_path / "4"
    write_model(directory, mapping, with_point=True)
    if kind == "camera":
        with (directory / "cameras.bin").open("r+b") as stream:
            stream.seek(32)
            stream.write(struct.pack("<d", float("nan")))
    elif kind == "pose":
        with (directory / "images.bin").open("r+b") as stream:
            stream.seek(12)
            stream.write(struct.pack("<4d", 0, 0, 0, 0))
    elif kind == "duplicate":
        path = directory / "images.bin"
        data = path.read_bytes()
        # Equal-length UUID names and one observation per image keep fixed records.
        offset = 8 + 64 + 41 + 8 + 24
        path.write_bytes(
            data[:offset] + struct.pack("<I", mapping.images[0].image_id) + data[offset + 4 :]
        )
    elif kind == "unknown":
        with (directory / "images.bin").open("r+b") as stream:
            stream.seek(8)
            stream.write(struct.pack("<I", 9999))
    elif kind == "truncated":
        (directory / "images.bin").write_bytes(b"invalid")
    elif kind == "frame":
        with (directory / "frames.bin").open("r+b") as stream:
            stream.seek(16 + 32)
            stream.write(struct.pack("<d", 90))
    else:
        (directory / "points3D.bin").write_bytes(struct.pack("<Q", 999))
    with pytest.raises(ValueError):
        read_component(directory, mapping)


def test_zero_components_and_overlapping_membership_fail(tmp_path):
    mapping = mapping_for(tuple(UUID(int=i) for i in range(1, 4)))
    (tmp_path / "sparse").mkdir()
    with pytest.raises(ValueError, match="zero_components"):
        read_components(tmp_path, mapping)
    for name in ("0", "9"):
        write_model(tmp_path / "sparse" / name, mapping)
    with pytest.raises(ValueError, match="overlap"):
        read_components(tmp_path, mapping)


def test_reader_validation_disk_gate_and_checkpoint(tmp_path):
    from splatforge.application.features_contracts import FeatureCancelledError

    mapping = mapping_for(tuple(UUID(int=i) for i in range(1, 4)))
    directory = tmp_path / "9"
    write_model(directory, mapping, with_point=True)
    with pytest.raises(ValueError, match="validation disk budget"):
        read_component(directory, mapping, maximum_validation_bytes=1)
    calls = []
    read_component(directory, mapping, checkpoint=lambda: calls.append(True))
    assert len(calls) >= 2

    def cancel():
        raise FeatureCancelledError("test cancellation")

    with pytest.raises(FeatureCancelledError):
        read_component(directory, mapping, checkpoint=cancel)
