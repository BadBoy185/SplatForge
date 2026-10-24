"""Training publication/cache/recovery always validate the actual on-disk payload."""

import json
from collections.abc import Callable
from pathlib import Path

from splatforge.adapters.artifact_validation import (
    ValidatedArtifact,
    _read_bounded,
    safe_payload_path,
    stream_sha256,
)
from splatforge.adapters.gaussian_ply import read_gaussian_ply
from splatforge.core.training import (
    CHECKPOINT_TYPE,
    SET_TYPE,
    GaussianScene,
    GaussianSceneSet,
    TrainingCheckpoint,
)
from splatforge.core.training_protocol import WorkerProtocol


def read_training_output(
    output: Path, artifact_type: str, *, checkpoint: Callable[[], None] = lambda: None
) -> ValidatedArtifact:
    if artifact_type == SET_TYPE:
        names = {"scene_set.json"}
        parsed = GaussianSceneSet.model_validate_json(
            _read_bounded(safe_payload_path(output, "scene_set.json"), 4 * 1024**2, "SceneSet")
        )
    else:
        scene = artifact_type != CHECKPOINT_TYPE
        metadata_name = "scene.json" if scene else "checkpoint.json"
        names = {
            metadata_name,
            "worker_result.json",
            "worker_receipt.json",
            "worker_events.jsonl",
            "scene.ply" if scene else "checkpoint",
        }
        metadata = _read_bounded(safe_payload_path(output, metadata_name), 4 * 1024**2, "Training")
        document = json.loads(metadata)
        keys = {"recipe_key", "backend_numerical_identity", "numerical_semantic_digest"}
        if not scene:
            keys |= {"training_recipe", "compatibility_identity"}
        derived = {key: document.pop(key, None) for key in keys}
        parsed = (GaussianScene if scene else TrainingCheckpoint).model_validate(document)
        if any(parsed.metadata()[key] != value for key, value in derived.items()):
            raise ValueError("training.corrupt_metadata_identity")
        result_path = safe_payload_path(output, "worker_result.json")
        raw = json.loads(_read_bounded(result_path, 4 * 1024**2, "Worker result"))
        receipt = json.loads(
            _read_bounded(safe_payload_path(output, "worker_receipt.json"), 4096, "Worker receipt")
        )
        if set(receipt) != {"start_step", "teardown_confirmed", "stdout_empty"} or (
            receipt["teardown_confirmed"] is not True or receipt["stdout_empty"] is not True
        ):
            raise ValueError("training.invalid_worker_receipt")
        terminal = parsed.final_step if scene else parsed.step
        protocol = WorkerProtocol(
            total_steps=parsed.settings.max_steps,
            start_step=receipt["start_step"],
            terminal_step=terminal,
            scene=scene,
        )
        events = _read_bounded(
            safe_payload_path(output, "worker_events.jsonl"), 64 * 1024**2, "Worker events"
        )
        if not events.endswith(b"\n"):
            raise ValueError("training.partial_worker_protocol")
        for line in events.splitlines():
            checkpoint()
            protocol.accept(line)
        protocol.finish()
        expected_payload_hash = parsed.ply_sha256 if scene else parsed.native.sha256
        if protocol.payload_identity != expected_payload_hash:
            raise ValueError("training.worker_payload_hash_mismatch")
        if protocol.last.identity != stream_sha256(result_path)[1]:
            raise ValueError("training.worker_result_hash_mismatch")
        if scene:
            evidence = read_gaussian_ply(
                safe_payload_path(output, "scene.ply"), checkpoint=checkpoint
            )
            expected = GaussianScene.model_validate(
                {**raw, "numerical_content_digest": evidence.numerical_digest}
            )
            if (evidence.count, evidence.sh_degree, evidence.size, evidence.sha256) != (
                parsed.gaussian_count,
                parsed.sh_degree,
                parsed.ply_size,
                parsed.ply_sha256,
            ):
                raise ValueError("scene.corrupt_payload: count/degree/hash/size differ")
        else:
            expected = TrainingCheckpoint.model_validate(raw)
            native = safe_payload_path(output, parsed.native.path)
            if {p.name for p in native.parent.iterdir()} != {"state.pt"} or (
                stream_sha256(native) != (parsed.native.size, parsed.native.sha256)
            ):
                raise ValueError("training.corrupt_checkpoint")
        if expected != parsed:
            raise ValueError("training.worker_result_metadata_mismatch")
    if {p.name for p in output.iterdir()} not in (names, names | {"manifest.json"}):
        raise ValueError("training.unexpected_payload")
    paths = sorted(n for n in names if n != "checkpoint")
    if artifact_type == CHECKPOINT_TYPE:
        paths.append("checkpoint/state.pt")
    from splatforge.core.execution import PayloadFile

    payloads = []
    for relative in sorted(paths):
        path = safe_payload_path(output, relative)
        if not path.is_file() or path.stat().st_nlink != 1:
            raise ValueError("training.unsafe_payload")
        size, digest = stream_sha256(path)
        payloads.append(PayloadFile(path=relative, size=size, sha256=digest))
    return ValidatedArtifact(
        payloads=tuple(payloads), parsed=parsed, semantic_digest=parsed.semantic_digest
    )


def validate_training_lineage(parsed, manifest) -> None:
    if manifest.recipe_key != parsed.recipe_key or manifest.contract_version != 1:
        raise ValueError("training.manifest_recipe_mismatch")
    inputs = {i.input_name: i for i in manifest.input_lineage}
    if len(inputs) != len(manifest.input_lineage):
        raise ValueError("training.duplicate_lineage")
    if isinstance(parsed, GaussianSceneSet):
        if list(inputs) != [f"scene_{i}" for i in range(len(parsed.scenes))]:
            raise ValueError("training.scene_set_lineage_mismatch")
        for item, ref in zip(inputs.values(), parsed.scenes, strict=True):
            if (item.artifact_id, item.semantic_digest) != (ref.artifact_id, ref.semantic_digest):
                raise ValueError("training.scene_set_lineage_mismatch")
    elif (
        set(inputs) not in ({"dataset"}, {"dataset", "checkpoint"})
        or inputs["dataset"].semantic_digest != parsed.dataset_digest
    ):
        raise ValueError("training.dataset_lineage_mismatch")
