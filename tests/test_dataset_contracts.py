"""Canonical identities, independent consumer expectations and numerical preservation."""

import json
import shutil
import struct
from pathlib import Path
from uuid import uuid4

import pytest
from dataset_reader_helpers import dataset_fixture

from splatforge.adapters.colmap_dataset import workspace_bytes
from splatforge.adapters.colmap_reconstruction import binary
from splatforge.adapters.dataset_capabilities import undistortion_arguments
from splatforge.adapters.dataset_reader import (
    read_dataset,
    require_observation_transform,
    require_preserved_geometry,
    sparse_content,
)
from splatforge.adapters.dataset_transport import write_sparse_tracks
from splatforge.core.dataset import (
    DatasetComponentReference,
    DatasetResourceLimits,
    DatasetSettings,
    estimate_dataset_resources,
)


def test_canonical_numerical_identity_ignores_native_ids_artifact_paths_and_warning_text(tmp_path):
    directory, a, original = dataset_fixture(tmp_path / "a", offset=0)
    other, b, prepared = dataset_fixture(tmp_path / "b", offset=100)
    assert read_dataset(directory) == a and read_dataset(other) == b
    assert a.semantic_digest == b.semantic_digest
    changed = a.model_copy(
        update={
            "provenance": a.provenance.model_copy(
                update={
                    "selection_artifact_id": uuid4(),
                    "warnings": ("Different human warning.",),
                    "pairing_method": "pair_selection.hybrid",
                }
            )
        }
    )
    assert changed.recipe_key == a.recipe_key and changed.semantic_digest == a.semantic_digest
    require_preserved_geometry(original, prepared)
    require_observation_transform(directory / "sparse/0", other / "sparse/0", original, prepared)
    assert all(i.name == f"{i.view_id}.png" for i in a.images)


@pytest.mark.parametrize(
    "problem",
    [
        "extra",
        "missing",
        "hash",
        "dimensions",
        "pose",
        "point",
        "track",
        "escape",
        "distorted",
        "metadata",
    ],
)
def test_independent_consumer_refuses_invalid_dataset(tmp_path, problem):
    directory, payload, _sparse = dataset_fixture(tmp_path)
    if problem == "extra":
        shutil.copyfile(
            directory / "images" / payload.images[0].name, directory / "images/extra.png"
        )
    elif problem == "missing":
        (directory / "images" / payload.images[0].name).unlink()
    elif problem == "hash":
        path = directory / "images" / payload.images[0].name
        from PIL import Image

        Image.new("RGB", (100, 80), "red").save(path)
    elif problem in {"pose", "point", "track", "distorted", "dimensions"}:
        filename, offset, fmt, value = {
            "pose": ("images.bin", 44, "d", 42.0),
            "point": ("points3D.bin", 16, "d", 42.0),
            "track": ("points3D.bin", 59, "I", 99999),
            "distorted": ("cameras.bin", 12, "i", 2),
            "dimensions": ("cameras.bin", 16, "Q", 99),
        }[problem]
        with (directory / "sparse/0" / filename).open("r+b") as stream:
            stream.seek(offset)
            stream.write(struct.pack("<" + fmt, value))
    else:
        data = json.loads((directory / "dataset.json").read_text())
        if problem == "escape":
            data["images"][0]["name"] = "../outside.png"
        else:
            data["image_count"] = 123
        (directory / "dataset.json").write_text(json.dumps(data))
    with pytest.raises((ValueError, OSError)):
        read_dataset(directory)


def test_core_refuses_duplicate_membership_and_settings_and_estimates_disk_separately(tmp_path):
    _d, payload, _s = dataset_fixture(tmp_path)
    with pytest.raises(ValueError, match="membership"):
        type(payload).model_validate({**payload.model_dump(), "images": payload.images * 2})
    for value in (0, -1, True, "100", 32769):
        with pytest.raises(ValueError):
            DatasetSettings(max_image_size=value)
    with pytest.raises(ValueError):
        payload.settings.max_image_size = 20
    estimate = estimate_dataset_resources(
        payload.input_images, 1024, DatasetSettings(), DatasetResourceLimits()
    )
    assert estimate.input_pixel_bytes == sum(i.size for i in payload.images)
    assert estimate.output_bytes_expected <= estimate.output_bytes_conservative
    assert estimate.decoded_working_memory_bytes != estimate.peak_workspace_bytes
    changed = payload.model_copy(update={"settings": DatasetSettings(max_image_size=50)})
    assert (
        changed.recipe_key != payload.recipe_key
        and changed.semantic_digest != payload.semantic_digest
    )


@pytest.mark.parametrize("native_model", [5, 9999])
def test_input_fisheye_or_future_projection_is_refused_before_native(tmp_path, native_model):
    from validation_helpers import scene

    from splatforge.adapters.colmap_dataset import ColmapDatasetAdapter

    component = scene()[0].components[0]
    sparse = tmp_path / component.native_payload
    sparse.mkdir(parents=True)
    (sparse / "cameras.bin").write_bytes(struct.pack("<QIiQQ", 1, 1, native_model, 100, 80))
    with pytest.raises(
        ValueError, match="unsupported_projection.*ordinary perspective.*panorama/360"
    ):
        ColmapDatasetAdapter().inspect_input(tmp_path, component)


def test_undistorter_options_must_be_positively_present():
    with pytest.raises(ValueError, match="unsupported_options"):
        undistortion_arguments(
            DatasetSettings(), (), images="images", sparse="sparse", output="output"
        )


@pytest.mark.parametrize(
    "path",
    [
        "../outside",
        "C:/outside",
        "images/../../x",
        "images\\x",
        "artifacts/dataset_component/other/manifest.json",
    ],
)
def test_dataset_reference_paths_cannot_escape(path):
    with pytest.raises(ValueError, match="unsafe_reference"):
        DatasetComponentReference(
            component_id=uuid4(),
            artifact_id=uuid4(),
            semantic_digest="a" * 64,
            manifest_path=path,
            image_count=3,
        )


def test_reader_supports_long_owned_unicode_paths(tmp_path):
    directory, expected, _s = dataset_fixture(tmp_path / ("long bounded segment ž " * 5).rstrip())
    assert read_dataset(directory) == expected


def test_workspace_resource_scan_tolerates_disappearing_native_temporary_file(
    tmp_path, monkeypatch
):
    (tmp_path / "stable.bin").write_bytes(b"owned bytes")
    (tmp_path / "native.tmp").write_bytes(b"temporary bytes")
    stat = Path.stat

    def transient(path, *args, **kwargs):
        if path.name == "native.tmp":
            raise FileNotFoundError("native writer removed its temporary file")
        return stat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", transient)
    assert workspace_bytes(tmp_path) == len(b"owned bytes")


def test_sparse_transport_omits_only_unused_features_and_remaps_every_track(tmp_path):
    directory, payload, _summary = dataset_fixture(tmp_path)
    source = directory / "sparse/0"
    image_mapping = {}
    rewritten = tmp_path / "rewritten-images.bin"
    with binary(source / "images.bin") as reader, rewritten.open("xb") as writer:
        count = reader.count(100)
        writer.write(struct.pack("<Q", count))
        for _ in range(count):
            values = reader.read("I7dI")
            name = reader.name()
            image_mapping[values[0]] = __import__("uuid").UUID(Path(name).stem)
            writer.write(struct.pack("<I7dI", *values))
            writer.write(name.encode() + b"\0")
            observations = reader.count(100)
            writer.write(struct.pack("<QddQ", observations + 1, 1e8, 1e8, 2**64 - 1))
            for _ in range(observations):
                writer.write(struct.pack("<ddQ", *reader.read("ddQ")))
    rewritten.replace(source / "images.bin")
    rewritten = tmp_path / "rewritten-points.bin"
    with binary(source / "points3D.bin") as reader, rewritten.open("xb") as writer:
        count = reader.count(100)
        writer.write(struct.pack("<Q", count))
        for _ in range(count):
            values = reader.read("Q3d3BdQ")
            writer.write(struct.pack("<Q3d3BdQ", *values))
            for _ in range(values[-1]):
                image, index = reader.read("II")
                writer.write(struct.pack("<II", image, index + 1))
    rewritten.replace(source / "points3D.bin")
    target = tmp_path / "transport/0"
    target.mkdir(parents=True)
    shutil.copyfile(source / "cameras.bin", target / "cameras.bin")
    names = {i.view_id: i.name for i in payload.images}
    omitted = write_sparse_tracks(
        source,
        target,
        image_mapping,
        names,
        tmp_path / "indices.sqlite",
        16 * 1024**2,
        lambda: None,
    )
    assert omitted == len(names)
    by_name = {i.name: i.view_id for i in payload.images}
    before, after = sparse_content(source, by_name), sparse_content(target, by_name)
    assert before.unassociated_count == len(names) and after.unassociated_count == 0
    assert before.point_count == after.point_count == payload.sparse_point_count
    require_preserved_geometry(before, after)
    require_observation_transform(source, target, before, after)


def test_preserved_color_and_stored_error_are_explicit_numerical_dependencies(tmp_path):
    directory, payload, before = dataset_fixture(tmp_path)
    with (directory / "sparse/0/points3D.bin").open("r+b") as stream:
        stream.seek(40)
        stream.write(struct.pack("<3Bd", 10, 20, 30, 0.25))
    after = sparse_content(directory / "sparse/0", {i.name: i.view_id for i in payload.images})
    assert before.world_digest == after.world_digest
    assert before.tracked_geometry_digest != after.tracked_geometry_digest
    changed = payload.model_copy(update={"source_sparse_digest": after.tracked_geometry_digest})
    assert changed.recipe_key != payload.recipe_key
