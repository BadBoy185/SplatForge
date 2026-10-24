"""Analytical sparse fixtures written independently of the M10 transport writer."""

import struct

from PIL import Image
from validation_helpers import scene

from splatforge.adapters.colmap_reconstruction import MODELS
from splatforge.adapters.dataset_reader import output_images, sparse_content
from splatforge.core.dataset import (
    DatasetInputImage,
    DatasetProvenance,
    DatasetSettings,
    PreparedDatasetComponent,
)
from splatforge.core.reconstruction_selection import SelectedComponentContent
from splatforge.core.validation_measurements import geometry_identity
from splatforge.core.views import canonical_json_bytes


def write_scene(directory, data, points, *, offset=0):
    directory.mkdir(parents=True)
    cameras = {c.camera_id: offset + i + 11 for i, c in enumerate(data.cameras)}
    views = {v.view_id: offset + i * 7 + 1 for i, v in enumerate(data.views)}
    models = {name: (native, count) for native, (name, count) in MODELS.items()}
    with (directory / "cameras.bin").open("wb") as stream:
        stream.write(struct.pack("<Q", len(cameras)))
        for c in data.cameras:
            native, count = models[c.model]
            stream.write(
                struct.pack(
                    f"<IiQQ{count}d", cameras[c.camera_id], native, c.width, c.height, *c.parameters
                )
            )
    with (directory / "images.bin").open("wb") as stream:
        stream.write(struct.pack("<Q", len(views)))
        for v in data.views:
            stream.write(
                struct.pack(
                    "<I7dI",
                    views[v.view_id],
                    *v.pose.quaternion_wxyz,
                    *v.pose.translation,
                    cameras[v.camera_id],
                )
            )
            stream.write(f"{v.view_id}.png".encode() + b"\0")
            observations = [
                (p, o)
                for p, point in enumerate(points)
                for o in point.observations
                if o.view_id == v.view_id
            ]
            stream.write(struct.pack("<Q", len(observations)))
            for p, obs in observations:
                stream.write(struct.pack("<ddQ", *obs.xy, offset + p + 999))
    with (directory / "points3D.bin").open("wb") as stream:
        stream.write(struct.pack("<Q", len(points)))
        for index, point in enumerate(points):
            stream.write(
                struct.pack(
                    "<Q3d3BdQ",
                    offset + index + 999,
                    *point.xyz,
                    50,
                    60,
                    70,
                    0.1,
                    len(point.observations),
                )
            )
            for obs in point.observations:
                stream.write(struct.pack("<II", views[obs.view_id], index))


def dataset_fixture(tmp_path, *, offset=0):
    reconstruction, _universe, source = scene(errors=(0.0, 0.1))
    component = reconstruction.components[0]
    data = source.component(component.component_id)
    directory = tmp_path / "dataset ž with spaces"
    write_scene(directory / "sparse/0", data, source.records[component.component_id], offset=offset)
    (directory / "images").mkdir()
    for view in data.views:
        Image.new("RGB", (100, 80), (30, 50, 90)).save(directory / "images" / f"{view.view_id}.png")
    names = {f"{v.view_id}.png": v.view_id for v in data.views}
    sparse = sparse_content(directory / "sparse/0", names)
    images = output_images(directory, names, sparse)
    geometry = geometry_identity(reconstruction, source)
    identity = data.views[0].view_id
    payload = PreparedDatasetComponent(
        source_sparse_digest=sparse.tracked_geometry_digest,
        source_component=SelectedComponentContent(
            component_id=component.component_id,
            component_semantic_digest=component.semantic_digest,
            validation_geometry_digest=geometry.components[0].content_digest,
        ),
        settings=DatasetSettings(),
        backend_numerical_identity="a" * 64,
        input_images=tuple(DatasetInputImage.model_validate(i.model_dump()) for i in images),
        images=images,
        cameras=sparse.cameras,
        views=sparse.views,
        sparse_point_count=sparse.point_count,
        sparse_geometry_digest=sparse.geometry_digest,
        preserved_world_points_digest=sparse.world_digest,
        provenance=DatasetProvenance(
            selection_artifact_id=identity,
            selection_digest="b" * 64,
            reconstruction_artifact_id=identity,
            reconstruction_digest=reconstruction.semantic_digest,
            candidate_artifact_id=identity,
            selected_artifact_id=identity,
            validation_report_digest="c" * 64,
        ),
    )
    (directory / "dataset.json").write_bytes(canonical_json_bytes(payload.metadata()))
    return directory, payload, sparse
