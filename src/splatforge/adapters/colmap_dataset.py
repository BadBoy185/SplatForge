"""Attempt-owned COLMAP undistortion; immutable M3/M8 payloads are never writable inputs."""

from __future__ import annotations

import os
import shutil
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from splatforge.adapters.artifact_validation import (
    _read_bounded,
    safe_payload_path,
    validate_decodable_image,
)
from splatforge.adapters.colmap_features import copy_pinned, native_transport_path, runtime_files
from splatforge.adapters.colmap_matching import ColmapMatchingAdapter
from splatforge.adapters.colmap_reconstruction import MODELS, NATIVE_FILES, binary
from splatforge.adapters.colmap_runtime import scoped_runtime_environment
from splatforge.adapters.dataset_capabilities import undistortion_arguments
from splatforge.adapters.dataset_reader import (
    output_images,
    read_dataset,
    require_observation_transform,
    require_preserved_geometry,
    sparse_content,
)
from splatforge.adapters.dataset_transport import write_sparse_tracks
from splatforge.adapters.feature_database import NativeFeaturePayload
from splatforge.adapters.process_diagnostics import invocation_evidence
from splatforge.adapters.process_runner import (
    ProcessBoundaryError,
    ProcessCleanupError,
    ProcessRequest,
)
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
from splatforge.core.dataset import (
    INPUT_MODELS,
    DatasetBackend,
    DatasetSettings,
    PreparedDatasetComponent,
)
from splatforge.core.execution import ArtifactManifest, DatasetComponentRoute
from splatforge.core.features import digest_json
from splatforge.core.process import ProcessInvocationEvidence
from splatforge.core.reconstruction import ReconstructionComponent, ReconstructionSet
from splatforge.core.views import MAX_VIEWS, canonical_json_bytes


def component_directory(directory: Path, component_id: UUID) -> Path:
    reconstruction = ReconstructionSet.model_validate_json(
        _read_bounded(directory / "reconstruction.json", 64 * 1024**2, "Reconstruction metadata")
    )
    component = next(c for c in reconstruction.components if c.component_id == component_id)
    return safe_payload_path(directory, component.native_payload)


def workspace_bytes(workspace: Path) -> int:
    size = 0
    for base, dirs, files in os.walk(workspace, followlinks=False):
        for name in (*dirs, *files):
            path = Path(base) / name
            try:
                redirected = path.is_symlink() or path.is_junction()
            except FileNotFoundError:
                continue
            if redirected:
                raise ValueError("dataset.unsafe_workspace: native output redirection")
        for name in files:
            path = Path(base) / name
            try:
                observed = path.stat()
            except FileNotFoundError:
                # Native temporary files can disappear between enumeration and
                # stat. Required final files are checked after process teardown.
                continue
            if observed.st_nlink != 1:
                raise ValueError("dataset.unsafe_workspace: writable hardlink")
            size += observed.st_size
    return size


class ColmapDatasetAdapter(ColmapMatchingAdapter):
    def prepare_backend(self, settings: DatasetSettings, colmap: Path | None) -> DatasetBackend:
        report = self._capabilities.probe(
            explicit_executable=colmap.absolute() if colmap else None,
            explicit_model_directory=None,
            bundled_executable=None,
            bundled_model_directory=None,
            deep=False,
            observed_at=datetime.now(UTC),
            freshness=FreshnessPolicy(),
            verification_only=True,
        )
        required = (
            report.binary,
            report.capability("colmap.dataset.version"),
            report.capability("colmap.dataset.undistorter"),
        )
        if any(e.status != CapabilityStatus.AVAILABLE for e in required):
            raise FeatureCapabilityError(
                "dataset.capability_unavailable: "
                + "; ".join(e.message for e in required if e.status != CapabilityStatus.AVAILABLE),
                evidence=required,
            )
        selection = report.selected_executable
        runtime = runtime_files(selection)
        options = next(
            s.option_names
            for s in report.command_discovery.subcommands
            if s.command == "image_undistorter"
        )
        undistortion_arguments(
            settings, options, images=Path("images"), sparse=Path("sparse"), output=Path("output")
        )
        return DatasetBackend(
            selection=selection,
            runtime_files=runtime,
            option_names=options,
            capability_evidence=required,
            numerical_identity=digest_json(
                {
                    "adapter_version": 1,
                    "executable": selection.identity.sha256,
                    "version": selection.identity.version_line,
                    "runtime": [r.model_dump(exclude={"path"}) for r in runtime],
                    "runtime_profile": selection.runtime_layout.profile
                    if selection.runtime_layout
                    else None,
                }
            ),
        )

    def inspect_input(
        self,
        directory: Path,
        component: ReconstructionComponent,
    ) -> tuple[dict[str, int], int, str]:
        path = safe_payload_path(directory, component.native_payload)
        models = {}
        with binary(path / "cameras.bin") as source:
            for _ in range(source.count(MAX_VIEWS)):
                _native, model, _width, _height = source.read("IiQQ")
                if model not in MODELS or MODELS[model][0] not in INPUT_MODELS:
                    raise ValueError(
                        "dataset.unsupported_projection: M10 supports ordinary "
                        "perspective flat cameras; panorama/360 preparation is later"
                    )
                name, count = MODELS[model]
                source.read(f"{count}d")
                models[name] = models.get(name, 0) + 1
        mapping = NativeFeaturePayload.model_validate_json(
            _read_bounded(directory / "backend_mapping.json", 32 * 1024**2, "Native mapping")
        )
        members = set(component.registered_view_ids)
        names = {i.image_name: i.view_id for i in mapping.images if i.view_id in members}
        # M9 deliberately excludes color/native stored error. M10 preserves those
        # attributes, so its own canonical consumed sparse digest binds them too.
        content = sparse_content(path, names)
        return (
            models,
            sum((path / f).stat().st_size for f in NATIVE_FILES),
            content.tracked_geometry_digest,
        )

    def produce(
        self,
        workspace: Path,
        route: DatasetComponentRoute,
        reconstruction_directory: Path,
        candidate_directory: Path,
        cancellation: FeatureCancellation,
        evidence: Callable[[ProcessInvocationEvidence], None],
        phase: Callable[[str], None],
    ) -> PreparedDatasetComponent:
        from splatforge.core.views import CandidateViewSet

        backend, limits = route.backend, route.resource_limits
        started = time.monotonic()

        def guard():
            if cancellation.is_cancelled():
                raise FeatureCancelledError("Dataset cancelled after confirmed native teardown")
            if time.monotonic() - started > limits.timeout_seconds:
                raise FeatureTimeoutError("dataset.timeout: preparation time budget exceeded")
            if (
                workspace_bytes(workspace) > limits.max_workspace_bytes
                or shutil.disk_usage(workspace).free < limits.minimum_free_bytes
            ):
                raise FeatureResourceError(
                    "dataset.resource_limit: actual workspace/disk exhausted"
                )

        phase("materializing_input")
        guard()
        if (
            not self._resolver.verify_expected_identity(backend.selection.identity)
            or runtime_files(backend.selection) != backend.runtime_files
        ):
            raise FeatureCapabilityError("dataset.runtime_changed: re-plan before launch")
        inputs, model = workspace / "input-images", workspace / "input-sparse"
        inputs.mkdir()
        model.mkdir()
        candidates = CandidateViewSet.model_validate_json(
            _read_bounded(
                candidate_directory / "candidate_views.json", 64 * 1024**2, "Candidate views"
            )
        )
        by_view = {v.view_id: v for v in candidates.views}
        for image in route.images:
            guard()
            original = safe_payload_path(candidate_directory, by_view[image.view_id].image_path)
            validate_decodable_image(
                original,
                image.width,
                image.height,
                "png" if image.name.endswith(".png") else "jpeg",
            )
            copy_pinned(
                original,
                inputs / image.name,
                size=image.size,
                digest=image.sha256,
                cancellation=cancellation,
            )
        source = component_directory(reconstruction_directory, route.content.component_id)
        manifest = ArtifactManifest.model_validate_json(
            _read_bounded(
                reconstruction_directory / "manifest.json", 64 * 1024**2, "Reconstruction manifest"
            )
        )
        payloads = {p.path: p for p in manifest.payloads}
        source_relative = source.relative_to(reconstruction_directory).as_posix()
        expected_files = {name: payloads[f"{source_relative}/{name}"] for name in NATIVE_FILES}
        native = NativeFeaturePayload.model_validate_json(
            _read_bounded(
                reconstruction_directory / "backend_mapping.json", 32 * 1024**2, "Native mapping"
            )
        )
        mapping = {i.image_id: i.view_id for i in native.images}
        names = {i.view_id: i.name for i in route.images}
        # Legacy independent-camera input preserves cameras, poses and every sparse
        # track. Public image names and observation indices are explicit transport.
        for name in ("cameras.bin",):
            expected = expected_files[name]
            copy_pinned(
                source / name,
                model / name,
                size=expected.size,
                digest=expected.sha256,
                cancellation=cancellation,
            )
        omitted = write_sparse_tracks(
            source,
            model,
            mapping,
            names,
            workspace / "sparse-index.sqlite",
            limits.max_workspace_bytes,
            guard,
        )
        from splatforge.adapters.artifact_validation import stream_sha256

        for name in ("images.bin", "points3D.bin"):
            expected = expected_files[name]
            if stream_sha256(source / name) != (expected.size, expected.sha256):
                raise ValueError(
                    "dataset.corrupt_geometry: source sparse bytes changed during copy"
                )
        phase("validating_input")
        canonical_names = {i.name: i.view_id for i in route.images}
        before = sparse_content(
            model,
            canonical_names,
            checkpoint=guard,
            maximum_scratch_bytes=limits.max_workspace_bytes,
        )
        result = workspace / "native-output"
        result.mkdir()
        argv = undistortion_arguments(
            route.settings,
            backend.option_names,
            images=native_transport_path(inputs),
            sparse=native_transport_path(model),
            output=native_transport_path(result),
        )
        guard()
        phase("undistorting")
        self._undistort(workspace, route, argv, cancellation, evidence, phase)
        guard()
        if runtime_files(backend.selection) != backend.runtime_files:
            raise FeatureCapabilityError("dataset.runtime_changed: native runtime changed")
        phase("validating_output")
        output = workspace / "output"
        output.mkdir()
        (output / "sparse").mkdir()
        (output / "sparse/0").mkdir()
        # Native dense-workspace scaffolding stays private. Move only the public
        # canonical payload; no re-encoding, hardlinks or publication copy.
        shutil.move(result / "images", output / "images")
        for name in NATIVE_FILES:
            shutil.move(result / "sparse" / name, output / "sparse/0" / name)
        after = sparse_content(
            output / "sparse/0",
            canonical_names,
            checkpoint=guard,
            maximum_scratch_bytes=limits.max_workspace_bytes,
        )
        require_preserved_geometry(before, after)
        require_observation_transform(
            model,
            output / "sparse/0",
            before,
            after,
            checkpoint=guard,
            maximum_scratch_bytes=limits.max_workspace_bytes,
        )
        images = output_images(output, canonical_names, after, guard)
        payload = PreparedDatasetComponent(
            source_component=route.content,
            source_sparse_digest=route.source_sparse_digest,
            settings=route.settings,
            backend_numerical_identity=backend.numerical_identity,
            input_images=route.images,
            images=images,
            cameras=after.cameras,
            views=after.views,
            sparse_point_count=after.point_count,
            input_unassociated_observations_omitted=omitted,
            sparse_geometry_digest=after.geometry_digest,
            preserved_world_points_digest=after.world_digest,
            provenance=route.provenance,
        )
        (output / "dataset.json").write_bytes(canonical_json_bytes(payload.metadata()))
        read_dataset(output, checkpoint=guard, maximum_scratch_bytes=limits.max_workspace_bytes)
        guard()
        # Only this attempt's disposable transport is released. Publication is a
        # rename, so later independent components retain only completed payloads.
        for scratch in (inputs, model, result):
            if (
                not scratch.resolve().is_relative_to(workspace.resolve())
                or scratch.is_symlink()
                or scratch.is_junction()
            ):
                raise ValueError("dataset.unsafe_scratch: refuse redirected cleanup")
            workspace_bytes(scratch)
            for base, dirs, files in os.walk(scratch, topdown=False, followlinks=False):
                for name in files:
                    (Path(base) / name).unlink()
                for name in dirs:
                    (Path(base) / name).rmdir()
            scratch.rmdir()
        return payload

    def _undistort(self, workspace, route, argv, cancellation, evidence, phase):
        backend, limits = route.backend, route.resource_limits
        request = ProcessRequest(
            executable=backend.selection.identity.resolved_path,
            argv=argv,
            working_directory=workspace,
            environment=scoped_runtime_environment(backend.selection.runtime_layout, os.environ),
            timeout_seconds=limits.timeout_seconds,
            max_stdout_bytes=256 * 1024,
            max_stderr_bytes=256 * 1024,
            expected_executable=backend.selection.identity,
        )

        class BudgetCancellation:
            owner = cancellation
            failure = None
            next_check = 0.0

            def is_cancelled(self):
                if cancellation.is_cancelled():
                    return True
                if time.monotonic() >= self.next_check:
                    self.next_check = time.monotonic() + 0.25
                    try:
                        if (
                            workspace_bytes(workspace) > limits.max_workspace_bytes
                            or shutil.disk_usage(workspace).free < limits.minimum_free_bytes
                        ):
                            self.failure = "dataset.resource_limit: native workspace/disk exhausted"
                    except (ValueError, OSError) as exc:
                        self.failure = str(exc)
                return self.failure is not None

        budget = BudgetCancellation()
        result, error, started = None, None, time.monotonic()
        try:
            result = self._runner.run(
                request, cancellation=budget, poll=lambda: phase("undistorting")
            )
        except ProcessCleanupError as exc:
            error = exc
            if not exc.teardown_confirmed:
                raise FeatureTeardownError(str(exc)) from exc
            raise FeatureProcessError(str(exc)) from exc
        except (ProcessBoundaryError, OSError) as exc:
            error = exc
            raise FeatureProcessError(str(exc)) from exc
        finally:
            evidence(
                invocation_evidence(
                    request,
                    executable=backend.selection.identity,
                    diagnostic_argv=argv,
                    tool_role="colmap.image_undistorter",
                    source_id=None,
                    elapsed_seconds=time.monotonic() - started,
                    result=result,
                    error=error,
                )
            )
        if not result.teardown_confirmed:
            raise FeatureTeardownError(
                "dataset.teardown_unresolved: process tree not confirmed dead"
            )
        if budget.failure:
            raise FeatureResourceError(budget.failure)
        if result.cancelled:
            raise FeatureCancelledError("Dataset native process cancelled after confirmed teardown")
        if result.timed_out:
            raise FeatureTimeoutError("dataset.timeout: image_undistorter timed out")
        if result.exit_code != 0 or result.forced_tree_termination:
            raise FeatureProcessError("dataset.native_failure: " + result.stderr_text()[:2048])
        if not self._resolver.verify_expected_identity(
            backend.selection.identity
        ) or result.executable.model_copy(
            update={"version_line": None}
        ) != backend.selection.identity.model_copy(update={"version_line": None}):
            raise FeatureCapabilityError("dataset.runtime_changed: executable changed")
