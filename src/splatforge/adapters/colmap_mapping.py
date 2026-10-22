"""Global-only mapping over an attempt-owned independent verified database."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from splatforge.adapters.artifact_validation import _read_bounded
from splatforge.adapters.colmap_features import native_transport_path, runtime_files
from splatforge.adapters.colmap_mapping_options import calibration_arguments, mapping_arguments
from splatforge.adapters.colmap_matching import ColmapMatchingAdapter
from splatforge.adapters.colmap_reconstruction import read_components
from splatforge.adapters.feature_database import NativeFeaturePayload, seal_feature_database
from splatforge.adapters.mapping_database import inspect_mapping_input
from splatforge.adapters.matching_artifacts import validate_matching_output
from splatforge.adapters.matching_database import pair_id
from splatforge.application.features_contracts import (
    FeatureCancellation,
    FeatureCancelledError,
    FeatureCapabilityError,
    FeatureProcessError,
    FeatureResourceError,
    FeatureTeardownError,
    FeatureTimeoutError,
)
from splatforge.core.capabilities import CapabilityStatus, FreshnessPolicy
from splatforge.core.features import digest_json
from splatforge.core.geometry import GEOMETRY_ARTIFACT_TYPE, VerifiedGeometrySet
from splatforge.core.process import ProcessInvocationEvidence
from splatforge.core.reconstruction import (
    CalibrationResult,
    GlobalMapperSettings,
    MappingBackend,
    MappingCalibrationPolicy,
    MappingInput,
    MappingResourceEstimate,
    MappingResourceLimits,
    ReconstructionComponent,
    ViewGraphCalibrationSettings,
    calibration_result_digest,
)


def mapping_source(directory: Path) -> tuple[NativeFeaturePayload, set[int]]:
    mapping = NativeFeaturePayload.model_validate_json(
        _read_bounded(directory / "backend_mapping.json", 32 * 1024**2, "Native mapping")
    )
    geometry = VerifiedGeometrySet.model_validate_json(
        _read_bounded(directory / "verified_geometry.json", 768 * 1024**2, "Verified geometry")
    )
    images = {item.view_id: item.image_id for item in mapping.images}
    allowed = {
        pair_id(images[p.left_view_id], images[p.right_view_id])
        for p in geometry.pairs
        if p.state == "verified"
    }
    return mapping, allowed


class ColmapMappingAdapter(ColmapMatchingAdapter):
    """Reuses M7's contained native launch, runtime pins, diagnostics and teardown."""

    def prepare(
        self,
        policy: MappingCalibrationPolicy,
        *,
        colmap: Path | None = None,
        settings: GlobalMapperSettings,
        calibration: ViewGraphCalibrationSettings | None,
    ) -> MappingBackend:
        report = self._capabilities.probe(
            explicit_executable=colmap.absolute() if colmap else None,
            explicit_model_directory=None,
            bundled_executable=None,
            bundled_model_directory=None,
            deep=True,
            observed_at=datetime.now(UTC),
            freshness=FreshnessPolicy(),
            verification_only=True,
        )
        required = [
            report.binary,
            report.database.evidence,
            report.capability("colmap.mapper.global.version"),
            report.capability("colmap.mapper.global"),
        ]
        if policy == MappingCalibrationPolicy.VIEW_GRAPH:
            required.append(report.capability("colmap.calibration.view_graph"))
        if any(e.status != CapabilityStatus.AVAILABLE for e in required):
            raise FeatureCapabilityError(
                "mapping.incompatible_capability: "
                + "; ".join(e.message for e in required if e.status != CapabilityStatus.AVAILABLE),
                evidence=tuple(required),
            )
        selection = report.selected_executable
        assert selection is not None
        options = {s.command: s.option_names for s in report.command_discovery.subcommands}
        runtime = runtime_files(selection)
        identity = digest_json(
            {
                "adapter_version": 1,
                "executable_sha256": selection.identity.sha256,
                "version": selection.identity.version_line,
                "runtime_files": [r.model_dump(exclude={"path"}) for r in runtime],
                "schema": report.database.model_dump(mode="json", exclude={"evidence"}),
                "runtime_profile": selection.runtime_layout.profile
                if selection.runtime_layout
                else None,
            }
        )
        backend = MappingBackend(
            selection=selection,
            database=report.database,
            option_names=options["global_mapper"],
            calibration_option_names=options.get("view_graph_calibrator", ()),
            numerical_identity=identity,
            runtime_files=runtime,
            capability_evidence=tuple(required[-2:]),
        )
        mapping_arguments(
            settings,
            backend.option_names,
            database=Path("p.db"),
            images=Path("images"),
            output=Path("sparse"),
        )
        if policy == MappingCalibrationPolicy.VIEW_GRAPH:
            calibration_arguments(
                calibration, backend.calibration_option_names, database=Path("p.db")
            )
        return backend

    def input(self, directory: Path) -> MappingInput:
        validate_matching_output(directory, GEOMETRY_ARTIFACT_TYPE, None)
        mapping, allowed = mapping_source(directory)
        return inspect_mapping_input(directory / "matches.db", mapping, allowed_pairs=allowed)

    def map(
        self,
        workspace: Path,
        *,
        directory: Path,
        mapping_input: MappingInput,
        backend: MappingBackend,
        settings: GlobalMapperSettings,
        policy: MappingCalibrationPolicy,
        calibration: ViewGraphCalibrationSettings | None,
        limits: MappingResourceLimits,
        estimate: MappingResourceEstimate,
        cancellation: FeatureCancellation,
        evidence_sink: Callable[[ProcessInvocationEvidence], None],
        phase_sink: Callable[[str], None],
    ) -> tuple[CalibrationResult, tuple[ReconstructionComponent, ...]]:
        phase_sink("preparing_database")
        if self.input(directory) != mapping_input:
            raise ValueError("mapping.input_mismatch: upstream numerical state changed")
        mapping, allowed = mapping_source(directory)
        self._require_schema(mapping, backend)
        self._preflight(workspace, backend, estimate, cancellation)
        output = workspace / "output"
        output.mkdir()
        database = workspace / "mapping.db"
        self._copy(directory / "matches.db", database, cancellation)
        self._copy(
            directory / "backend_mapping.json", output / "backend_mapping.json", cancellation
        )
        self._copy(directory / "cameras.json", output / "input_cameras.json", cancellation)
        with closing(sqlite3.connect(database)) as db, db:
            db.execute("DELETE FROM matches")
            db.execute("DELETE FROM descriptors")
            for (native,) in db.execute("SELECT pair_id FROM two_view_geometries").fetchall():
                if native not in allowed:
                    db.execute("DELETE FROM two_view_geometries WHERE pair_id=?", (native,))
        seal_feature_database(database)
        if inspect_mapping_input(database, mapping) != mapping_input:
            raise ValueError("mapping.input_mismatch: private database assembly differs")

        class WorkspaceBudget:
            owner = cancellation
            failure = None

            def is_cancelled(self):
                if cancellation.is_cancelled():
                    return True
                total, sparse_bytes, files = 0, 0, 0
                for path in workspace.rglob("*"):
                    if path.is_symlink() or path.is_junction():
                        self.failure = "Redirected mapping workspace"
                        return True
                    if path.is_file():
                        files += 1
                        size = path.stat().st_size
                        total += size
                        if path.is_relative_to(output / "sparse"):
                            sparse_bytes += size
                        if files > MAX_MAPPING_FILES:
                            self.failure = "Mapping workspace file count exceeded"
                            return True
                if (
                    total > limits.max_workspace_bytes
                    or sparse_bytes > limits.max_output_bytes
                    or database.stat().st_size > limits.max_database_bytes
                ):
                    self.failure = "Mapping disk/resource growth limit exceeded"
                return self.failure is not None

        budget = WorkspaceBudget()

        def invoke(argv, phase):
            try:
                # M7b's native runner already owns Windows Job/process tree lifetime,
                # bounded streams, timeout, diagnostics and exact binary/DLL identity.
                self._run(
                    workspace,
                    backend,
                    argv,
                    database,
                    limits,
                    estimate.model_copy(update={"database_bytes": limits.max_database_bytes}),
                    budget,
                    evidence_sink,
                    lambda _name: phase_sink(phase),
                )
            except (FeatureTeardownError, FeatureCancelledError, FeatureTimeoutError):
                raise
            except Exception as exc:
                if budget.failure:
                    raise FeatureResourceError(
                        "mapping.resource_failure: " + budget.failure
                    ) from exc
                code = "calibration_failure" if phase == "calibration" else "mapper_process_failure"
                raise FeatureProcessError(f"mapping.{code}: {exc}") from exc
            if budget.failure:
                raise FeatureResourceError("mapping.resource_failure: " + budget.failure)

        if policy == MappingCalibrationPolicy.VIEW_GRAPH:
            phase_sink("calibration")
            invoke(
                calibration_arguments(
                    calibration,
                    backend.calibration_option_names,
                    database=native_transport_path(database),
                ),
                "calibration",
            )
            seal_feature_database(database)
        phase_sink("validating_mapping_input")
        from splatforge.adapters.matching_database import readonly_database

        with closing(readonly_database(database)) as db:
            native_pairs = {row[0] for row in db.execute("SELECT pair_id FROM two_view_geometries")}
            if not native_pairs <= allowed:
                raise ValueError(
                    "mapping.universe_violation: calibration introduced an undeclared edge"
                )
        try:
            after = inspect_mapping_input(database, mapping)
        except ValueError as exc:
            raise ValueError("mapping.malformed_calibrated_database: " + str(exc)) from exc
        if (
            after.view_ids != mapping_input.view_ids
            or after.keypoints_digest != mapping_input.keypoints_digest
        ):
            raise ValueError("mapping.input_mismatch: calibrator altered views/keypoints")
        if policy == MappingCalibrationPolicy.PRESERVE_PRIORS and after != mapping_input:
            raise ValueError("mapping.input_mismatch: preserve priors changed numerical state")
        result = CalibrationResult.model_construct(
            policy=policy,
            settings=calibration,
            method_id="calibration.colmap_view_graph"
            if policy == MappingCalibrationPolicy.VIEW_GRAPH
            else None,
            backend_identity=backend.numerical_identity,
            cameras_before=mapping_input.cameras_digest,
            cameras_after=after.cameras_digest,
            mapping_input_after=after,
            result_digest="0" * 64,
        )
        result = CalibrationResult.model_validate(
            {**result.model_dump(), "result_digest": calibration_result_digest(result)}
        )
        self._copy(database, output / "mapping.db", cancellation)
        images = workspace / "images"
        images.mkdir()
        sparse = output / "sparse"
        sparse.mkdir()
        phase_sink("global_mapping")
        invoke(
            mapping_arguments(
                settings,
                backend.option_names,
                database=native_transport_path(database),
                images=native_transport_path(images),
                output=native_transport_path(sparse),
            ),
            "global_mapping",
        )
        phase_sink("validating_output")

        def validation_checkpoint() -> None:
            phase_sink("validating_output")
            if budget.is_cancelled():
                if budget.failure:
                    raise FeatureResourceError("mapping.resource_failure: " + budget.failure)
                raise FeatureCancelledError("Mapping output validation cancelled")

        used_bytes = sum(p.stat().st_size for p in workspace.rglob("*") if p.is_file())
        validation_budget = max(0, limits.max_workspace_bytes - used_bytes)
        components = read_components(
            output,
            mapping,
            maximum_validation_bytes=validation_budget,
            checkpoint=validation_checkpoint,
        )
        if any(c.registered_view_count < settings.min_model_size for c in components):
            raise ValueError("mapping.malformed_output: backend violated minimum model size")
        # Dimensions/models remain those of their explicit input cameras; intrinsics optimize.
        from splatforge.adapters.colmap_reconstruction import read_component
        from splatforge.adapters.matching_database import CAMERA_MODELS

        with closing(readonly_database(output / "mapping.db")) as db:
            expected = {
                i.view_id: db.execute(
                    "SELECT c.model,c.width,c.height FROM cameras c JOIN images i "
                    "ON i.camera_id=c.camera_id WHERE i.image_id=?",
                    (i.image_id,),
                ).fetchone()
                for i in mapping.images
            }
        for component in components:
            _, cameras, views = read_component(
                output / component.native_payload,
                mapping,
                maximum_validation_bytes=validation_budget,
                checkpoint=validation_checkpoint,
            )
            by_id = {c.camera_id: c for c in cameras}
            for view in views:
                camera = by_id[view.camera_id]
                if (CAMERA_MODELS[camera.model], camera.width, camera.height) != expected[
                    view.view_id
                ]:
                    raise ValueError(
                        "mapping.invalid_camera: output model/dimensions differ from input"
                    )
        if budget.is_cancelled() and budget.failure:
            raise FeatureResourceError("mapping.resource_failure: " + budget.failure)
        return result, components


MAX_MAPPING_FILES = 100000
