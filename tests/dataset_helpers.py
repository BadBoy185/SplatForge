"""Small contained-process fixture for M10 lifecycle tests; no source fallback."""

import os
import shutil
import struct
from pathlib import Path

from test_colmap_capabilities import process_result
from test_selection_execution import service as selection_service
from test_selection_execution import setup

from splatforge.adapters.colmap_capabilities import ColmapCapabilityAdapter
from splatforge.adapters.colmap_dataset import ColmapDatasetAdapter
from splatforge.adapters.colmap_reconstruction import MODELS, NATIVE_FILES, binary
from splatforge.adapters.dataset_capabilities import undistortion_arguments
from splatforge.application.dataset import DatasetService
from splatforge.core.dataset import DatasetSettings


def dataset_setup(tmp_path, *, multi=False, policy=None):
    value, fixture, mapping, validation = setup(tmp_path, multi=multi, policy=policy)
    ids = tuple(c.component_id for c in mapping.reconstruction.components)
    selection = selection_service(value).select(
        value.root, validation_run_id=validation.run_id, component_ids=ids
    )
    configure(fixture)
    return value, fixture, mapping, validation, selection


def configure(fixture):
    fixture.top_help += "\nimage_undistorter\n"
    fixture.undistortion_mode = "success"
    fixture.on_undistort = None
    original = fixture.run
    argv = undistortion_arguments(
        DatasetSettings(),
        tuple(
            [
                "image_path",
                "input_path",
                "output_path",
                "output_type",
                "copy_policy",
                "max_image_size",
                "blank_pixels",
                "min_scale",
                "max_scale",
                "roi_min_x",
                "roi_min_y",
                "roi_max_x",
                "roi_max_y",
                "jpeg_quality",
                "num_threads",
                "log_target",
                "default_random_seed",
            ]
        ),
        images=Path("images"),
        sparse=Path("sparse"),
        output=Path("output"),
    )
    fixture.dataset_help = "-h [ --help ]\n" + "\n".join(
        a + " arg" for a in argv if a.startswith("--")
    )

    def run(request, *, cancellation=None, poll=None):
        if request.argv[0] != "image_undistorter":
            return original(request, cancellation=cancellation, poll=poll)
        fixture.requests.append(request)
        if request.argv[-1] == "-h":
            return process_result(
                request, identity=fixture.identity, stdout=fixture.dataset_help.encode()
            )
        owner = cancellation
        while hasattr(owner, "owner"):
            owner = owner.owner
        if fixture.on_undistort:
            fixture.on_undistort(owner)
        if cancellation and cancellation.is_cancelled():
            return process_result(request, identity=fixture.identity).model_copy(
                update={"cancelled": True}
            )
        if fixture.undistortion_mode in {"failed", "timeout", "unresolved"}:
            return process_result(
                request,
                identity=fixture.identity,
                exit_code=1,
                timed_out=fixture.undistortion_mode == "timeout",
            ).model_copy(update={"teardown_confirmed": fixture.undistortion_mode != "unresolved"})
        output = Path(request.argv[request.argv.index("--output_path") + 1])
        source = Path(request.argv[request.argv.index("--input_path") + 1])
        images = Path(request.argv[request.argv.index("--image_path") + 1])
        (output / "sparse").mkdir()
        shutil.copytree(images, output / "images")
        for name in NATIVE_FILES:
            shutil.copyfile(source / name, output / "sparse" / name)
        if fixture.undistortion_mode == "partial":
            (output / "sparse/points3D.bin").unlink()
        maximum = int(request.argv[request.argv.index("--max_image_size") + 1])
        if maximum > 0:
            from PIL import Image

            records = []
            with binary(source / "cameras.bin") as reader:
                for _ in range(reader.count(100)):
                    native, model, w, h = reader.read("IiQQ")
                    values = list(reader.read(f"{MODELS[model][1]}d"))
                    scale = min(1, maximum / max(w, h))
                    records.append(
                        (
                            native,
                            model,
                            round(w * scale),
                            round(h * scale),
                            [v * scale for v in values],
                        )
                    )
            with (output / "sparse/cameras.bin").open("wb") as writer:
                writer.write(struct.pack("<Q", len(records)))
                for native, model, w, h, values in records:
                    writer.write(struct.pack(f"<IiQQ{len(values)}d", native, model, w, h, *values))
            for path in (output / "images").iterdir():
                with Image.open(path) as image:
                    scale = min(1, maximum / max(image.size))
                    resized = image.resize(tuple(round(v * scale) for v in image.size))
                resized.save(path)
        # The fixture's source priors are ordinary zero-distortion SIMPLE_RADIAL.
        # Native undistortion converts them to PINHOLE even without resizing.
        records = []
        with binary(output / "sparse/cameras.bin") as reader:
            for _ in range(reader.count(100)):
                native, model, w, h = reader.read("IiQQ")
                values = list(reader.read(f"{MODELS[model][1]}d"))
                if model not in (0, 1):
                    values = [values[0], values[0], values[1], values[2]]
                    model = 1
                records.append((native, model, w, h, values))
        with (output / "sparse/cameras.bin").open("wb") as writer:
            writer.write(struct.pack("<Q", len(records)))
            for native, model, w, h, values in records:
                writer.write(struct.pack(f"<IiQQ{len(values)}d", native, model, w, h, *values))
        return process_result(request, identity=fixture.identity)

    fixture.run = run


def dataset_service(value, fixture, repository=None):
    adapter = ColmapDatasetAdapter(
        runner=fixture,
        resolver=fixture.resolver,
        capability_adapter=ColmapCapabilityAdapter(
            runner=fixture,
            resolver=fixture.resolver,
            environment={**os.environ, "SPLATFORGE_COLMAP": str(fixture.exe)},
        ),
    )
    return DatasetService(repository or value.execution, adapter)
