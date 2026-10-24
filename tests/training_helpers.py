"""Tiny synthetic transport evidence; no quality assertions or native GPU requirement."""

import hashlib
import json
import struct
from contextlib import contextmanager
from datetime import UTC, datetime

from splatforge.adapters.gaussian_ply import properties, read_gaussian_ply
from splatforge.application.features_contracts import FeatureCancelledError
from splatforge.core.training import (
    GaussianScene,
    NativeCheckpointFile,
    TrainingBackendIdentity,
    TrainingCheckpoint,
    TrainingMetrics,
)
from splatforge.core.training_protocol import WorkerEvent
from splatforge.core.views import canonical_json_bytes


@contextmanager
def training_dataset_setup(tmp_path, *, multi=False):
    """Extend only this fixture with 24 analytical SFM seeds before M8 publication."""
    import mapping_helpers
    import pytest
    from dataset_helpers import dataset_setup

    original = mapping_helpers.write_model

    def write_model(directory, mapping, **kwargs):
        original(directory, mapping, **kwargs)
        images = kwargs.get("selected") or mapping.images
        shared, offset, shift = (
            kwargs.get("shared", True),
            kwargs.get("native_camera_offset", 0),
            kwargs.get("shift", 0),
        )
        points = [(0.1 * (i % 6 - 3), 0.1 * (i // 6 - 2), 20.0) for i in range(24)]
        with (directory / "images.bin").open("wb") as stream:
            stream.write(struct.pack("<Q", len(images)))
            for index, image in enumerate(images):
                camera = offset + (11 if shared else 11 + index * 13)
                stream.write(
                    struct.pack("<I7dI", image.image_id, 1, 0, 0, 0, shift + index, 0, 0, camera)
                )
                stream.write(image.image_name.encode() + b"\0")
                stream.write(struct.pack("<Q", len(points)))
                for point, (x, y, z) in enumerate(points):
                    stream.write(
                        struct.pack(
                            "<ddQ",
                            100 * (x + shift + index) / z + 16,
                            100 * y / z + 12,
                            999 + point,
                        )
                    )
        with (directory / "points3D.bin").open("wb") as stream:
            stream.write(struct.pack("<Q", len(points)))
            for point, xyz in enumerate(points):
                stream.write(
                    struct.pack("<Q3d3BdQ", 999 + point, *xyz, 80, 100, 120, 0.0, len(images))
                )
                for image in images:
                    stream.write(struct.pack("<II", image.image_id, point))

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(mapping_helpers, "write_model", write_model)
        yield dataset_setup(tmp_path, multi=multi)


def prepared_training_project(directory):
    from dataset_helpers import dataset_service

    with training_dataset_setup(directory) as (value, fixture, _, _, selection):
        result = dataset_service(value, fixture).prepare(
            value.root, selection_run_id=selection.run.run_id
        )
    return value.root, result.run_id


def backend_identity():
    return TrainingBackendIdentity(
        worker_sha256="a" * 64,
        python_sha256="b" * 64,
        python_version="test",
        torch_version="test",
        torch_cuda="12.8",
        packages_digest="c" * 64,
        cuda_runtime="12080",
        driver="610.62",
        gpu_uuid="test-gpu",
        gpu_name="test GPU",
        gpu_ordinal=0,
        compute_capability=(12, 0),
        device_total_bytes=16 * 1024**3,
        features=("default", "absgrad", "antialiased", "mcmc"),
    )


def write_ply(path, *, degree=3, rows=None):
    names = properties(degree)
    if rows is None:
        rows = []
        for index in range(4):
            row = [0.0] * len(names)
            row[0], row[-4] = float(index), 1.0
            rows.append(row)
    header = (
        "ply\nformat binary_little_endian 1.0\nelement vertex "
        + str(len(rows))
        + "\n"
        + "".join("property float " + name + "\n" for name in names)
        + "end_header\n"
    )
    path.write_bytes(
        header.encode() + b"".join(struct.pack("<" + "f" * len(names), *r) for r in rows)
    )
    return rows


class FakeTrainer:
    def __init__(self):
        self.identity = backend_identity()
        self.calls = []
        self.on_produce = None

    def capability(self, runtime, ordinal=0):
        return self.identity

    def produce(self, workspace, route, dataset, resume, cancellation, events, evidence):
        self.calls.append(route)
        if self.on_produce:
            self.on_produce(route, cancellation)
        if cancellation.is_cancelled():
            raise FeatureCancelledError("test cancellation")
        output = workspace / "output"
        output.mkdir()
        metrics = TrainingMetrics(
            training_loss=0.2, duration_seconds=2.0, peak_allocated_cuda_bytes=1024
        )
        common = dict(
            dataset_digest=route.dataset.semantic_digest,
            settings=route.settings,
            backend=route.backend,
            gaussian_count=4,
            metrics=metrics,
        )
        scene = route.node_id == "gaussian_scene"
        if scene:
            write_ply(output / "scene.ply", degree=route.settings.sh_degree)
            ply = read_gaussian_ply(output / "scene.ply")
            payload = GaussianScene(
                **common,
                method_id=route.method_id,
                final_step=route.terminal_step,
                sh_degree=ply.sh_degree,
                ply_sha256=ply.sha256,
                ply_size=ply.size,
                numerical_content_digest=ply.numerical_digest,
                checkpoint_lineage=(route.resume.semantic_digest,),
            )
            metadata, key = "scene.json", ply.sha256
            raw = payload.model_dump(
                mode="json",
                exclude={
                    "numerical_content_digest",
                    "coordinate_convention",
                    "scale",
                    "payload_format",
                    "contract_version",
                    "warnings",
                },
            )
        else:
            (output / "checkpoint").mkdir()
            native = b"opaque fake native state" + str(route.terminal_step).encode()
            (output / "checkpoint/state.pt").write_bytes(native)
            payload = TrainingCheckpoint(
                **common,
                step=route.terminal_step,
                native=NativeCheckpointFile(
                    sha256=hashlib.sha256(native).hexdigest(), size=len(native)
                ),
                state_evidence="parameters_optimizers_schedulers_strategy_python_numpy_torch_cuda_rng_v1",
                resumed_from_checkpoint=route.resume.semantic_digest if route.resume else None,
            )
            metadata, key = "checkpoint.json", payload.native.sha256
            raw = payload.model_dump(mode="json")
        result_bytes = canonical_json_bytes(raw)
        (output / "worker_result.json").write_bytes(result_bytes)
        (output / metadata).write_bytes(canonical_json_bytes(payload.metadata()))
        (output / "worker_receipt.json").write_bytes(
            canonical_json_bytes(
                {"start_step": route.start_step, "teardown_confirmed": True, "stdout_empty": True}
            )
        )
        records = []
        for sequence, (name, step, identity) in enumerate(
            [
                ("worker.started", route.start_step, None),
                ("dataset.loaded", route.start_step, route.dataset.semantic_digest),
                ("training.started", route.start_step, None),
                ("training.progress", route.terminal_step, None),
                ("scene.exported" if scene else "checkpoint.saved", route.terminal_step, key),
                ("worker.completed", route.terminal_step, hashlib.sha256(result_bytes).hexdigest()),
            ],
            1,
        ):
            record = WorkerEvent(
                sequence=sequence,
                timestamp=datetime.now(UTC),
                event=name,
                step=step,
                total_steps=route.settings.max_steps,
                identity=identity,
            )
            events(record)
            records.append(record.model_dump_json().encode() + b"\n")
        (output / "worker_events.jsonl").write_bytes(b"".join(records))
        return payload


def event(name, sequence, step=0, total=10, **fields):
    return json.dumps(
        {
            "protocol_version": 1,
            "timestamp": datetime.now(UTC).isoformat(),
            "event": name,
            "sequence": sequence,
            "step": step,
            "total_steps": total,
            **fields,
        }
    ).encode()
