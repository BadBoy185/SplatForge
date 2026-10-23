"""M9 canonical detailed identity independently of native IDs and layout."""

import struct
from uuid import UUID

import pytest
from mapping_helpers import mapping_for, write_model
from test_reconstruction_identity import make_set

from splatforge.adapters.colmap_reconstruction import read_components
from splatforge.adapters.validation_geometry import ColmapValidationSource
from splatforge.core.geometry import CameraPriorSet, ViewCameraPrior
from splatforge.core.reconstruction_validation import ValidationResourceLimits
from splatforge.core.validation_measurements import geometry_identity


def native_scene(root, *, native_offset=0, folder="7", point_id=999, xyz=(1, 2, 3)):
    mapping = mapping_for(tuple(UUID(int=i) for i in range(1, 4)), offset=native_offset)
    directory = root / "sparse" / folder
    write_model(
        directory,
        mapping,
        native_camera_offset=native_offset,
        with_point=True,
        current_frames=False,
    )
    with (directory / "points3D.bin").open("r+b") as stream:
        stream.seek(8)
        stream.write(struct.pack("<Q3d", point_id, *xyz))
    with (directory / "images.bin").open("r+b") as stream:
        for i in range(3):
            stream.seek(8 + i * (64 + 41 + 8 + 24) + 64 + 41 + 8 + 16)
            stream.write(struct.pack("<Q", point_id))
    (root / "backend_mapping.json").write_text(mapping.model_dump_json(), encoding="utf8")
    (root / "input_cameras.json").write_text(
        CameraPriorSet(
            cameras=tuple(
                ViewCameraPrior(
                    view_id=i.view_id,
                    model="SIMPLE_PINHOLE",
                    width=32,
                    height=24,
                    parameters=(100, 16, 12),
                )
                for i in mapping.images
            )
        ).model_dump_json(),
        encoding="utf8",
    )
    reconstruction = make_set(mapping, read_components(root, mapping))
    source = ColmapValidationSource(
        root, reconstruction, root / "work", ValidationResourceLimits(), lambda: None
    )
    return reconstruction, source


def test_native_point_image_camera_ids_and_folder_number_do_not_enter_geometry_identity(tmp_path):
    a, source_a = native_scene(tmp_path / "a")
    b, source_b = native_scene(tmp_path / "b", native_offset=500, folder="903", point_id=552299)
    assert a.semantic_digest == b.semantic_digest
    assert geometry_identity(a, source_a) == geometry_identity(b, source_b)
    assert next(source_a.points(a.components[0].component_id)).observations[0].view_id == UUID(
        int=1
    )
    changed, source_changed = native_scene(tmp_path / "changed", xyz=(2, 2, 3))
    assert a.components[0].component_id == changed.components[0].component_id
    assert a.semantic_digest == changed.semantic_digest
    assert geometry_identity(a, source_a).semantic_digest != (
        geometry_identity(changed, source_changed).semantic_digest
    )


def test_stored_error_is_not_consumed_but_observation_coordinates_are(tmp_path):
    a, source = native_scene(tmp_path)
    before = geometry_identity(a, source)
    path = tmp_path / "sparse" / "7"
    with (path / "points3D.bin").open("r+b") as stream:
        stream.seek(8 + 8 + 24 + 3)
        stream.write(struct.pack("<d", 9999))
    assert geometry_identity(a, source) == before
    with (path / "images.bin").open("r+b") as stream:
        stream.seek(8 + 64 + 41 + 8)
        stream.write(struct.pack("<d", 17))
    assert geometry_identity(a, source).semantic_digest != before.semantic_digest


def test_native_budget_cancellation_and_corrupt_track_are_hard_errors(tmp_path):
    a, source = native_scene(tmp_path)
    with pytest.raises(ValueError, match="native bytes"):
        ColmapValidationSource(
            tmp_path,
            a,
            tmp_path / "work",
            ValidationResourceLimits(max_native_bytes=1),
            lambda: None,
        )
    with pytest.raises(ValueError, match="scratch"):
        low = ColmapValidationSource(
            tmp_path,
            a,
            tmp_path / "work",
            ValidationResourceLimits(max_scratch_bytes=1),
            lambda: None,
        )
        geometry_identity(a, low)

    def stop():
        raise RuntimeError("cancelled test scan")

    with pytest.raises(RuntimeError, match="cancelled"):
        ColmapValidationSource(tmp_path, a, tmp_path / "work", ValidationResourceLimits(), stop)
    with (tmp_path / "sparse" / "7" / "points3D.bin").open("r+b") as stream:
        stream.seek(8 + 51)
        stream.write(struct.pack("<II", 99999, 0))
    with pytest.raises(ValueError, match="track"):
        geometry_identity(
            a,
            ColmapValidationSource(
                tmp_path, a, tmp_path / "work", ValidationResourceLimits(), lambda: None
            ),
        )


def test_native_point_image_and_track_record_order_does_not_change_measurements(tmp_path):
    from splatforge.core.reconstruction_validation import (
        MeasurementSettings,
        ValidationUniverse,
        ValidationView,
    )
    from splatforge.core.validation_measurements import measure_reconstruction

    values = []
    for reverse in (False, True):
        root = tmp_path / str(reverse)
        mapping = mapping_for(tuple(UUID(int=i) for i in range(1, 4)), offset=100 if reverse else 0)
        directory = root / "sparse" / ("190" if reverse else "0")
        directory.mkdir(parents=True)
        camera = 901 if reverse else 1
        xyz = ((1.0, 2.0, 3.0), (2.0, 1.0, 6.0))
        point_ids = (1900, 300) if reverse else (17, 990)
        with (directory / "cameras.bin").open("wb") as stream:
            stream.write(struct.pack("<QIiQQ3d", 1, camera, 0, 32, 24, 100, 16, 12))
        with (directory / "images.bin").open("wb") as stream:
            stream.write(struct.pack("<Q", 3))
            for image in reversed(mapping.images) if reverse else mapping.images:
                stream.write(
                    struct.pack(
                        "<I7dI", image.image_id, 1, 0, 0, 0, image.view_id.int - 1, 0, 0, camera
                    )
                )
                stream.write(image.image_name.encode() + b"\0" + struct.pack("<Q", 2))
                for index, (x, y, z) in enumerate(xyz):
                    stream.write(
                        struct.pack(
                            "<ddQ",
                            16 + 100 * (x + image.view_id.int - 1) / z + index * 4,
                            12 + 100 * y / z,
                            point_ids[index],
                        )
                    )
        with (directory / "points3D.bin").open("wb") as stream:
            stream.write(struct.pack("<Q", 2))
            for index in (1, 0) if reverse else (0, 1):
                stream.write(
                    struct.pack("<Q3d3BdQ", point_ids[index], *xyz[index], 0, 0, 0, 123, 3)
                )
                for image in reversed(mapping.images) if reverse else mapping.images:
                    stream.write(struct.pack("<II", image.image_id, index))
        (root / "backend_mapping.json").write_text(mapping.model_dump_json(), encoding="utf8")
        (root / "input_cameras.json").write_text(
            CameraPriorSet(
                cameras=tuple(
                    ViewCameraPrior(
                        view_id=i.view_id,
                        model="SIMPLE_PINHOLE",
                        width=32,
                        height=24,
                        parameters=(100, 16, 12),
                    )
                    for i in mapping.images
                )
            ).model_dump_json(),
            encoding="utf8",
        )
        reconstruction = make_set(mapping, read_components(root, mapping))
        source = ColmapValidationSource(
            root, reconstruction, root / "work", ValidationResourceLimits(), lambda: None
        )
        universe = ValidationUniverse(
            views=tuple(
                ValidationView(
                    view_id=i.view_id,
                    source_id=UUID(int=100),
                    source_group_id=UUID(int=200),
                    camera_group_id=UUID(int=300),
                    media_type="video",
                )
                for i in mapping.images
            )
        )
        geometry = geometry_identity(reconstruction, source)
        values.append(
            measure_reconstruction(
                reconstruction,
                universe,
                geometry,
                source,
                MeasurementSettings(quantile_sample_bound=3),
            )
        )
    assert values[0].geometry.semantic_digest == values[1].geometry.semantic_digest
    assert values[0].semantic_digest == values[1].semantic_digest
    assert values[0].components[0].metric("reprojection.mean").value == pytest.approx(2)
    assert values[0].components[0].metric("reprojection.p95").availability == "sampled"


def test_oversized_evidence_is_refused_before_a_payload_file_is_written(tmp_path, monkeypatch):
    from validation_helpers import measured

    from splatforge.adapters.execution_storage import LocalExecutionRepository
    from splatforge.core.validation_artifacts import ValidationGeometryArtifact

    _r, universe, _s, metrics = measured()
    artifact = ValidationGeometryArtifact(
        reconstruction_artifact_id=UUID(int=1),
        candidate_artifact_id=UUID(int=2),
        selected_artifact_id=UUID(int=3),
        universe=universe,
        native_payload_digest="a" * 64,
        geometry=metrics.geometry,
    )
    monkeypatch.setattr("splatforge.adapters.validation_storage.MAX_VALIDATION_METADATA_BYTES", 1)
    with pytest.raises(ValueError, match="evidence metadata"):
        LocalExecutionRepository().write_validation_artifact(tmp_path, artifact)
    assert not (tmp_path / "output" / "evidence.json").exists()
