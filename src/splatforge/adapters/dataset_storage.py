"""M10 additions to the existing repository and publication protocol."""

from pathlib import Path

from splatforge.core.dataset import (
    MAX_METADATA_BYTES,
    PreparedDatasetComponent,
    PreparedDatasetSet,
)
from splatforge.core.execution import ArtifactHandle, ReconstructionSelectionRoute
from splatforge.core.views import canonical_json_bytes


class DatasetStorageMixin:
    def dataset_pairing_method(self, root: Path, reconstruction: ArtifactHandle) -> str:
        verified = self.lineage_handle(root, reconstruction, "verified_geometry")
        matches = self.lineage_handle(root, verified, "match_set")
        pairs = self.lineage_handle(root, matches, "pair_set")
        return self.load_pair_set(root, pairs).settings.method_id

    def selection_route(
        self,
        root: Path,
        handle: ArtifactHandle,
    ) -> ReconstructionSelectionRoute:
        parsed = self.load_validation_artifact(root, handle)
        route = self._load_run_snapshot(
            root,
            self._validate_indexed_artifact(root, handle, metadata_only=True)[0].producer_run_id,
        ).route
        if (
            not isinstance(route, ReconstructionSelectionRoute)
            or parsed.selection != route.decision
        ):
            raise ValueError("dataset.selection_required: exact published M9 selection required")
        from splatforge.application.reconstruction_selection import require_selection_inputs

        require_selection_inputs(self, root, route)
        reconstruction = self.load_reconstruction(root, route.reconstruction)
        geometry = self.load_validation_artifact(root, route.geometry_artifact).geometry
        report = self.load_validation_artifact(root, route.report).report
        parsed.selection.require_current(
            reconstruction, geometry, report, route.reconstruction.artifact_id
        )
        return route

    def load_dataset(
        self,
        root: Path,
        handle: ArtifactHandle,
    ) -> PreparedDatasetComponent | PreparedDatasetSet:
        parsed = self._validate_indexed_artifact(root, handle, metadata_only=True)[2].parsed
        if not isinstance(parsed, (PreparedDatasetComponent, PreparedDatasetSet)):
            raise ValueError("dataset.invalid_artifact: expected M10 dataset publication")
        return parsed

    def input_image_size(self, root: Path, handle: ArtifactHandle, path: str) -> int:
        directory = self.artifact_directory(root, handle)
        return self._artifact_payload_path(directory, path).stat().st_size

    @staticmethod
    def disk_free(root: Path) -> int:
        import shutil

        return shutil.disk_usage(root).free

    def write_dataset_set(self, workspace: Path, value: PreparedDatasetSet) -> None:
        output = workspace / "output"
        output.mkdir()
        payload = canonical_json_bytes(value.model_dump(mode="json"))
        if len(payload) > MAX_METADATA_BYTES:
            raise ValueError("dataset.resource_limit: metadata exceeds 64 MiB")
        self._write_new_file(output / "dataset_set.json", payload)
