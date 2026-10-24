"""Analytically controlled real native undistortion for every M10 perspective model."""

import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from dataset_reader_helpers import write_scene
from PIL import Image
from validation_helpers import scene

from splatforge.adapters.colmap_dataset import ColmapDatasetAdapter
from splatforge.adapters.dataset_capabilities import undistortion_arguments
from splatforge.adapters.dataset_reader import (
    output_images,
    require_observation_transform,
    require_preserved_geometry,
    sparse_content,
)
from splatforge.core.dataset import DatasetResourceLimits, DatasetSettings


@pytest.mark.integration
@pytest.mark.parametrize(
    "model", ["SIMPLE_PINHOLE", "PINHOLE", "SIMPLE_RADIAL", "RADIAL", "OPENCV", "FULL_OPENCV"]
)
def test_real_six_perspective_camera_models(tmp_path, model, record_property):
    executable = os.environ.get("SPLATFORGE_TEST_COLMAP")
    if not executable or os.environ.get("SPLATFORGE_TEST_DATASET") != "1":
        pytest.skip("Set SPLATFORGE_TEST_COLMAP and SPLATFORGE_TEST_DATASET=1 for M10 cameras")
    parameters = {
        "SIMPLE_PINHOLE": (100, 50, 40),
        "PINHOLE": (100, 110, 50, 40),
        "SIMPLE_RADIAL": (100, 50, 40, 0.03),
        "RADIAL": (100, 50, 40, 0.03, -0.001),
        "OPENCV": (100, 110, 50, 40, 0.03, -0.001, 0.002, -0.002),
        "FULL_OPENCV": (
            100,
            110,
            50,
            40,
            0.03,
            -0.001,
            0.002,
            -0.002,
            0.0001,
            0.0002,
            0.0003,
            0.0001,
        ),
    }[model]
    reconstruction, _u, source = scene(model=model, parameters=parameters, errors=(0.0, 0.1))
    component = reconstruction.components[0]
    data = source.component(component.component_id)
    sparse = tmp_path / "input-sparse"
    write_scene(sparse, data, source.records[component.component_id], offset=7)
    images = tmp_path / "images"
    images.mkdir()
    names = {f"{v.view_id}.png": v.view_id for v in data.views}
    for name in names:
        Image.new("RGB", (100, 80), (30, 60, 90)).save(images / name)
    before_bytes = {p: p.read_bytes() for p in images.iterdir()}
    before = sparse_content(sparse, names)
    adapter = ColmapDatasetAdapter()
    metrics = []
    for maximum in (None, 50):
        settings = DatasetSettings(max_image_size=maximum)
        backend = adapter.prepare_backend(settings, Path(executable))
        output = tmp_path / ("native" if maximum is None else "resized")
        output.mkdir()
        argv = undistortion_arguments(
            settings, backend.option_names, images=images, sparse=sparse, output=output
        )
        records = []
        adapter._undistort(
            tmp_path,
            SimpleNamespace(backend=backend, resource_limits=DatasetResourceLimits()),
            argv,
            SimpleNamespace(is_cancelled=lambda: False),
            records.append,
            lambda _phase: None,
        )
        after = sparse_content(output / "sparse", names)
        require_preserved_geometry(before, after)
        require_observation_transform(sparse, output / "sparse", before, after)
        pixels = output_images(output, names, after)
        assert {c.model for c in after.cameras} <= {"PINHOLE", "SIMPLE_PINHOLE"}
        if maximum:
            assert max(max(p.width, p.height) for p in pixels) <= maximum
        elif model in {"SIMPLE_PINHOLE", "PINHOLE"}:
            assert {(p.width, p.height) for p in pixels} == {(100, 80)}
        assert all(p.read_bytes() == value for p, value in before_bytes.items())
        metrics.append(
            {
                "input_model": model,
                "max_image_size": maximum,
                "output_models": sorted({c.model for c in after.cameras}),
                "images": len(pixels),
                "points": after.point_count,
                "native_seconds": sum(r.elapsed_seconds for r in records),
            }
        )
    record_property("m10_camera_metrics", __import__("json").dumps(metrics))
