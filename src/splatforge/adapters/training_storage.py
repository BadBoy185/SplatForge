"""M11 additions to existing immutable project storage; no second state system."""

from pathlib import Path
from uuid import UUID

from splatforge.core.dataset import PreparedDatasetComponent
from splatforge.core.execution import (
    ArtifactHandle,
    DatasetComponentRoute,
    DatasetSetRoute,
    TrainingRoute,
)
from splatforge.core.training import GaussianScene, GaussianSceneSet, TrainingCheckpoint


class TrainingStorageMixin:
    def training_datasets(
        self, root: Path, run_id: UUID
    ) -> tuple[tuple[ArtifactHandle, PreparedDatasetComponent], ...]:
        route = self._load_run_snapshot(root, run_id).route
        if not isinstance(route, (DatasetComponentRoute, DatasetSetRoute)):
            raise ValueError("training.requires_explicit_successful_m10_run")
        output = self.resolve_run_output(root, run_id, route.node_id, route.target.output_name)
        dataset = self.load_dataset(root, output)
        if isinstance(dataset, PreparedDatasetComponent):
            return ((output, dataset),)
        result = []
        for handle, reference in zip(route.components, dataset.components, strict=True):
            payload = self.load_dataset(root, handle)
            if (
                handle.artifact_id,
                payload.semantic_digest,
                payload.source_component.component_id,
            ) != (reference.artifact_id, reference.semantic_digest, reference.component_id):
                raise ValueError("training.stale_dataset_set")
            result.append((handle, payload))
        return tuple(result)

    def load_training(
        self, root: Path, handle: ArtifactHandle
    ) -> TrainingCheckpoint | GaussianScene | GaussianSceneSet:
        with self.validation_evidence_operation():
            value = self._validate_indexed_artifact(root, handle, metadata_only=True)[2].parsed
            if not isinstance(value, (TrainingCheckpoint, GaussianScene, GaussianSceneSet)):
                raise ValueError("training.invalid_artifact")
            return value

    def training_groups(self, root: Path, handle: ArtifactHandle) -> dict[str, str]:
        candidate = self.lineage_handle(root, handle, "candidate_views")
        return {
            str(v.view_id): str(v.source_group_id)
            for v in self.load_candidate_views(root, candidate).views
        }

    def write_scene_set(self, workspace: Path, value: GaussianSceneSet) -> None:
        from splatforge.core.views import canonical_json_bytes

        output = workspace / "output"
        output.mkdir()
        self._write_new_file(
            output / "scene_set.json", canonical_json_bytes(value.model_dump(mode="json"))
        )

    def validate_training_route(
        self,
        root: Path,
        route: TrainingRoute,
        payload: TrainingCheckpoint | GaussianScene | GaussianSceneSet | None = None,
        directory: Path | None = None,
    ) -> None:
        from splatforge.application.training import (
            require_training_inputs,
            require_training_payload,
        )

        require_training_inputs(self, root, route)
        if payload is not None:
            require_training_payload(route, payload)
            if isinstance(payload, TrainingCheckpoint) and (
                payload.native.size > route.resource_limits.max_checkpoint_bytes
            ):
                raise ValueError("training.checkpoint_resource_limit")
            if isinstance(payload, GaussianScene) and (
                payload.ply_size > route.resource_limits.max_scene_bytes
            ):
                raise ValueError("training.scene_resource_limit")
            if isinstance(payload, (GaussianScene, TrainingCheckpoint)) and (
                payload.gaussian_count > route.resource_limits.max_gaussians
            ):
                raise ValueError("training.gaussian_resource_limit")
        if directory is not None and route.node_id != "gaussian_scene_set":
            import json

            from splatforge.adapters.artifact_validation import _read_bounded

            receipt = json.loads(_read_bounded(directory / "worker_receipt.json", 4096, "Receipt"))
            if receipt["start_step"] != route.start_step:
                raise ValueError("training.resumed_step_mismatch")
            if isinstance(payload, TrainingCheckpoint) and payload.resumed_from_checkpoint != (
                route.resume.semantic_digest if route.resume else None
            ):
                raise ValueError("training.checkpoint_lineage_mismatch")

    def inspect_training_run(
        self, root: Path, run_id: UUID
    ) -> tuple[ArtifactHandle, TrainingCheckpoint | GaussianScene | GaussianSceneSet]:
        route = self._load_run_snapshot(root, run_id).route
        if not isinstance(route, TrainingRoute):
            raise ValueError("training.requires_training_run")
        handle = self.resolve_run_output(root, run_id, route.node_id, route.target.output_name)
        return handle, self.load_training(root, handle)
